#include "SkateSoundSet.h"
#include "SkateComponent.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "Components/AudioComponent.h"
#include "Sound/SoundWave.h"
#include <limits>

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSkateAudioPreferencesTest, "AtelierSkate.Audio.Preferences",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FSkateAudioPreferencesTest::RunTest(const FString&)
{
    auto Wave = [](bool bLoop)
    {
        auto* Result = NewObject<USoundWave>();
        Result->Duration = .25f;
        Result->bLooping = bLoop;
        return Result;
    };
    auto* Component = NewObject<USkateComponent>();
    for (int32 I = 0; I < 12; ++I)
    {
        auto* Audio = NewObject<UAudioComponent>(Component);
        Audio->SetSound(Wave(true));
        Audio->SetVolumeMultiplier(.6f);
        Component->Loops.Add(Audio);
    }
    Component->LoopVolume.Init(0.f, 12);
    Component->LoopVolume[0] = .6f;
    auto* Shot = NewObject<UAudioComponent>();
    auto* Other = NewObject<UAudioComponent>();
    Other->SetVolumeMultiplier(.7f);

    Component->SetAudioPreferences(false, 1.f);
    TestEqual(TEXT("Default leaves the sounding loop untouched"), Component->Loops[0]->VolumeMultiplier, .6f);
    TestEqual(TEXT("Default leaves a silent loop untouched"), Component->Loops[1]->VolumeMultiplier, .6f);
    TestFalse(TEXT("Default bypasses the low-pass"), bool(Component->Loops[0]->bEnableLowPassFilter));
    Component->ApplyVoicePreferences(Shot, .8f);
    TestEqual(TEXT("Default preserves one-shot gain"), Shot->VolumeMultiplier, .8f);
    TestFalse(TEXT("Default one-shot is unfiltered"), bool(Shot->bEnableLowPassFilter));
    Component->ShotVoices.Add(Shot, .8f);

    Component->SetAudioPreferences(true, .5f);
    TestEqual(TEXT("Sounding loop updates immediately from its envelope"), Component->Loops[0]->VolumeMultiplier, .3f);
    TestEqual(TEXT("Silent loop keeps its stopped gain until UpdateAudio"), Component->Loops[1]->VolumeMultiplier, .6f);
    bool bAllFiltered = true;
    for (const auto& Loop : Component->Loops)
        bAllFiltered &= Loop->bEnableLowPassFilter && Loop->LowPassFilterFrequency == 3000.f;
    TestTrue(TEXT("Every loop enables the 3 kHz low-pass"), bAllFiltered);
    TestEqual(TEXT("Envelopes are not rewritten"), Component->LoopVolume[0], .6f);
    TestEqual(TEXT("Playing one-shot updates immediately"), Shot->VolumeMultiplier, .4f);
    TestTrue(TEXT("Playing one-shot enables the low-pass"), bool(Shot->bEnableLowPassFilter));
    TestEqual(TEXT("One-shot cutoff in hertz"), Shot->LowPassFilterFrequency, 3000.f);
    auto* Future = NewObject<UAudioComponent>();
    Component->ApplyVoicePreferences(Future, .6f);
    TestEqual(TEXT("Next one-shot inherits gain before play"), Future->VolumeMultiplier, .3f);
    TestTrue(TEXT("Next one-shot inherits filter before play"), bool(Future->bEnableLowPassFilter));

    Component->SetAudioPreferences(false, 1.f);
    TestEqual(TEXT("Repeated changes use the envelope without compounding"), Component->Loops[0]->VolumeMultiplier, .6f);
    TestEqual(TEXT("One-shot restores its own gain"), Shot->VolumeMultiplier, .8f);
    TestFalse(TEXT("Disabling restores unfiltered loops"), bool(Component->Loops[0]->bEnableLowPassFilter));
    TestFalse(TEXT("Disabling restores unfiltered one-shots"), bool(Shot->bEnableLowPassFilter));
    Component->SetAudioPreferences(true, -1.f);
    TestEqual(TEXT("Zero floor mutes the owned loop"), Component->Loops[0]->VolumeMultiplier, 0.f);
    TestEqual(TEXT("Zero floor mutes the owned one-shot"), Shot->VolumeMultiplier, 0.f);
    Component->SetAudioPreferences(false, 2.f);
    TestEqual(TEXT("Upper bound restores loop gain"), Component->Loops[0]->VolumeMultiplier, .6f);
    Component->SetAudioPreferences(true, std::numeric_limits<float>::quiet_NaN());
    TestFalse(TEXT("Nonfinite request preserves filter"), bool(Component->Loops[0]->bEnableLowPassFilter));
    TestEqual(TEXT("Nonfinite request preserves gain"), Shot->VolumeMultiplier, .8f);
    TestEqual(TEXT("Unowned audio remains untouched"), Other->VolumeMultiplier, .7f);

    Component->SetAudioPreferences(true, .5f);
    auto* Set = NewObject<USkateSoundSet>();
    Set->Loops.Add(TEXT("roll"), Wave(true));
    FString Error;
    TestTrue(TEXT("Sound set changes while softened"), Component->SetSoundSet(Set, Error));
    TestTrue(TEXT("Replaced loop keeps the low-pass"), bool(Component->Loops[0]->bEnableLowPassFilter));
    TestEqual(TEXT("Replaced loop starts silent"), Component->Loops[0]->VolumeMultiplier, 0.f);
    TestEqual(TEXT("Sound set change keeps the saved gain"), Component->SoundVolume, .5f);
    TestEqual(TEXT("Sound set change keeps playing one-shot gain"), Shot->VolumeMultiplier, .4f);
    TestTrue(TEXT("Original restoration keeps softening"), Component->SetSoundSet(nullptr, Error) && Component->Loops[0]->bEnableLowPassFilter);
    auto* AfterSet = NewObject<UAudioComponent>();
    Component->ApplyVoicePreferences(AfterSet, .8f);
    TestEqual(TEXT("One-shot created after a set change inherits gain"), AfterSet->VolumeMultiplier, .4f);
    TestTrue(TEXT("One-shot created after a set change is filtered on Play"), bool(AfterSet->bEnableLowPassFilter));
    TestEqual(TEXT("One-shot created after a set change uses the soft cutoff"), AfterSet->LowPassFilterFrequency, 3000.f);

    Component->StopShotVoices();
    TestTrue(TEXT("Cleanup releases owned handles"), Component->ShotVoices.IsEmpty());
    TestFalse(TEXT("Cleanup destroys the owned one-shot"), IsValid(Shot));
    TestTrue(TEXT("Cleanup retains unowned audio"), IsValid(Other));
    TestTrue(TEXT("Cleanup retains board loops"), IsValid(Component->Loops[0]));
    return true;
}
#endif
