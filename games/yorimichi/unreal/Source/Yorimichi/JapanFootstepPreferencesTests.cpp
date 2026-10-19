#include "JapanFootsteps.h"
#include "JapanSoundBank.h"
#include "JapanSoundBanks.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Components/AudioComponent.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Misc/AutomationTest.h"
#include "Sound/SoundWave.h"
#include <limits>

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FJapanFootstepPreferencesTest,"Yorimichi.Audio.FootstepPreferences",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FJapanFootstepPreferencesTest::RunTest(const FString&)
{
    auto* Foot=NewObject<UJapanFootstepComponent>();
    auto* Voice=NewObject<UAudioComponent>();
    auto* Other=NewObject<UAudioComponent>();
    Other->SetVolumeMultiplier(.7f);
    Foot->ApplyVoicePreferences(Voice,.8f);
    TestEqual(TEXT("Default preserves contact gain"),Voice->VolumeMultiplier,.8f);
    TestFalse(TEXT("Default bypasses the low-pass"),bool(Voice->bEnableLowPassFilter));
    Foot->FootstepVoices.Add(Voice,.8f);
    Foot->SetAudioPreferences(true,.5f);
    TestEqual(TEXT("Existing voice updates immediately"),Voice->VolumeMultiplier,.4f);
    TestTrue(TEXT("Existing voice enables real engine low-pass"),bool(Voice->bEnableLowPassFilter));
    TestEqual(TEXT("Soft cutoff in hertz"),Voice->LowPassFilterFrequency,3000.f);
    auto* Future=NewObject<UAudioComponent>();
    Foot->ApplyVoicePreferences(Future,.6f);
    TestEqual(TEXT("Next voice inherits gain before play"),Future->VolumeMultiplier,.3f);
    TestTrue(TEXT("Next voice inherits filter before play"),bool(Future->bEnableLowPassFilter));
    Foot->SetAudioPreferences(false,1.f);
    TestEqual(TEXT("Repeated changes use original gain without compounding"),Voice->VolumeMultiplier,.8f);
    TestFalse(TEXT("Disabling restores unfiltered voice"),bool(Voice->bEnableLowPassFilter));
    Foot->SetAudioPreferences(true,-1.f);
    TestEqual(TEXT("Zero floor mutes only owned voice"),Voice->VolumeMultiplier,0.f);
    Foot->SetAudioPreferences(false,2.f);
    TestEqual(TEXT("Upper bound restores original gain"),Voice->VolumeMultiplier,.8f);
    Foot->SetAudioPreferences(true,std::numeric_limits<float>::quiet_NaN());
    TestFalse(TEXT("Nonfinite request preserves filter"),bool(Voice->bEnableLowPassFilter));
    TestEqual(TEXT("Nonfinite request preserves gain"),Voice->VolumeMultiplier,.8f);
    TestEqual(TEXT("Unowned hoof/skate/music voice remains untouched"),Other->VolumeMultiplier,.7f);
    Foot->Set=NewObject<UJapanFootstepSet>();
    FString Error;
    Foot->SetAudioPreferences(true,.5f);
    for(int32 Selection=0;Selection<4;++Selection)
    {
        UJapanSoundBank* Bank=nullptr;
        if(Selection)
        {
            Bank=NewObject<UJapanSoundBank>();
            const FName Surfaces[]={TEXT("barefoot"),TEXT("dirt_gravel"),TEXT("grass"),TEXT("leaves"),TEXT("mud_water"),TEXT("stone"),TEXT("wood")};
            for(FName Surface:Surfaces)
            {
                FJapanSoundPool Pool;
                for(int32 I=0;I<4;++I) { auto* Wave=NewObject<USoundWave>(); Wave->Duration=.2f; Pool.Variants.Add(Wave); }
                Bank->Footsteps.Add(Surface,Pool);
            }
        }
        TestTrue(TEXT("Each bank can select with local controls"),Foot->SetSoundBank(Bank,Error));
        TestEqual(TEXT("Bank change cannot reset existing voice gain"),Voice->VolumeMultiplier,.4f);
        TestEqual(TEXT("Bank change cannot reset future voice gain"),Foot->FootstepVolume,.5f);
        TestTrue(TEXT("Every bank supports live softening"),bool(Voice->bEnableLowPassFilter));
        Foot->SetAudioPreferences(false,1.f);
        TestEqual(TEXT("Each bank can restore unmodified live gain"),Voice->VolumeMultiplier,.8f);
        Foot->SetAudioPreferences(true,.5f);
    }
    Foot->StopFootstepVoices();
    TestTrue(TEXT("Cleanup releases owned handles"),Foot->FootstepVoices.IsEmpty());
    TestFalse(TEXT("Cleanup destroys the owned voice"),IsValid(Voice));
    TestTrue(TEXT("Cleanup retains unowned audio"),IsValid(Other));

    const auto Init=UWorld::InitializationValues().AllowAudioPlayback(false).CreatePhysicsScene(false);
    UWorld* World=UWorld::CreateWorld(EWorldType::Game,false,NAME_None,nullptr,true,ERHIFeatureLevel::Num,&Init);
    if(!TestNotNull(TEXT("Isolated local audio world"),World)) return false;
    auto* Actor=World->SpawnActor<AActor>();
    if(!TestNotNull(TEXT("Local emitter owner"),Actor)) { World->DestroyWorld(false); return false; }
    auto* Ready=NewObject<UJapanFootstepComponent>(Actor);
    Ready->Set=NewObject<UJapanFootstepSet>();
    auto* Banks=NewObject<UJapanSoundBanks>(World);
    Banks->SetFootstepPreferences(true,.25f);
    TestEqual(TEXT("Already-ready world emitter receives local gain"),Ready->FootstepVolume,.25f);
    TestTrue(TEXT("Already-ready world emitter receives softening"),Ready->bSoftenFootsteps);
    auto* Late=NewObject<UJapanFootstepComponent>(Actor);
    Late->Set=Ready->Set;
    Banks->FootReady(Late);
    TestEqual(TEXT("Late Original emitter receives saved gain without loading a bank"),Late->FootstepVolume,.25f);
    TestTrue(TEXT("Late Original emitter receives softening"),Late->bSoftenFootsteps);
    TestFalse(TEXT("Preferences do not load registry or bank"),Banks->bRegistryAttempted);
    TestNull(TEXT("Original remains delegated"),Banks->Active.Get());
    auto* Unrelated=NewObject<UJapanFootstepComponent>();
    Banks->FootReady(Unrelated);
    TestEqual(TEXT("Readiness from another world cannot inherit settings"),Unrelated->FootstepVolume,1.f);
    Banks->bShuttingDown=true;
    Banks->SetFootstepPreferences(false,1.f);
    TestEqual(TEXT("Teardown refuses preference mutation"),Ready->FootstepVolume,.25f);
    World->DestroyWorld(false);
    return true;
}
#endif
