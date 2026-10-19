#include "JapanSoundBanks.h"
#include "SkateComponent.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Components/AudioComponent.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Misc/AutomationTest.h"
#include "Sound/SoundWave.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FJapanSkatePreferencesTest,"Yorimichi.Audio.SkatePreferences",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FJapanSkatePreferencesTest::RunTest(const FString&)
{
    const auto Init=UWorld::InitializationValues().AllowAudioPlayback(false).CreatePhysicsScene(false);
    UWorld* World=UWorld::CreateWorld(EWorldType::Game,false,NAME_None,nullptr,true,ERHIFeatureLevel::Num,&Init);
    if(!TestNotNull(TEXT("Isolated local audio world"),World)) return false;
    auto* Actor=World->SpawnActor<AActor>();
    if(!TestNotNull(TEXT("Local emitter owner"),Actor)) { World->DestroyWorld(false); return false; }
    auto MakeReady=[](USkateComponent* Skate)
    {
        for(int32 I=0;I<12;++I)
        {
            auto* Loop=NewObject<UAudioComponent>(Skate);
            auto* Wave=NewObject<USoundWave>(); Wave->Duration=.25f; Wave->bLooping=true;
            Loop->SetSound(Wave);
            Skate->Loops.Add(Loop);
        }
        Skate->LoopVolume.Init(0.f,12);
        Skate->LoopVolume[0]=.8f;
    };
    auto* Ready=NewObject<USkateComponent>(Actor);
    MakeReady(Ready);
    auto* Pending=NewObject<USkateComponent>(Actor);
    auto* Banks=NewObject<UJapanSoundBanks>(World);
    Banks->SetSkatePreferences(true,.25f);
    TestEqual(TEXT("Already-ready board receives local gain"),Ready->SoundVolume,.25f);
    TestTrue(TEXT("Already-ready board receives softening"),Ready->bSoftenSounds);
    TestEqual(TEXT("Sounding loop updates now"),Ready->Loops[0]->VolumeMultiplier,.2f);
    TestEqual(TEXT("Board without loaded audio waits for readiness"),Pending->SoundVolume,1.f);
    MakeReady(Pending);
    Banks->SkateReady(Pending);
    TestEqual(TEXT("Late Original board receives saved gain without loading a bank"),Pending->SoundVolume,.25f);
    TestTrue(TEXT("Late Original board receives softening"),Pending->bSoftenSounds && Pending->Loops[3]->bEnableLowPassFilter);
    TestFalse(TEXT("Preferences do not load registry or bank"),Banks->bRegistryAttempted);
    TestNull(TEXT("Original remains delegated"),Banks->Active.Get());
    TestEqual(TEXT("Footstep preferences stay independent"),Banks->FootstepVolume,1.f);
    TestFalse(TEXT("Footstep softening stays independent"),Banks->bSoftenFootsteps);
    Banks->SetFootstepPreferences(true,.5f);
    TestEqual(TEXT("Footstep changes leave skate gain alone"),Ready->SoundVolume,.25f);
    auto* Unrelated=NewObject<USkateComponent>();
    MakeReady(Unrelated);
    Banks->SkateReady(Unrelated);
    TestEqual(TEXT("Readiness from another world cannot inherit settings"),Unrelated->SoundVolume,1.f);
    Banks->bShuttingDown=true;
    Banks->SetSkatePreferences(false,1.f);
    TestEqual(TEXT("Teardown refuses preference mutation"),Ready->SoundVolume,.25f);
    World->DestroyWorld(false);
    return true;
}
#endif
