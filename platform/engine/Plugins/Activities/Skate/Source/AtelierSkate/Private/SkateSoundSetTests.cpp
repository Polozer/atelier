#include "SkateSoundSet.h"
#include "SkateComponent.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "Components/AudioComponent.h"
#include "Sound/SoundWave.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSkateSoundSetTest, "AtelierSkate.Audio.SoundSet",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FSkateSoundSetTest::RunTest(const FString&)
{
    auto Wave = [](bool bLoop)
    {
        auto* Result = NewObject<USoundWave>();
        Result->Duration = .25f;
        Result->bLooping = bLoop;
        return Result;
    };
    auto* Component = NewObject<USkateComponent>();
    FString Error;
    TestTrue(TEXT("Fresh Original needs no new asset or initialized audio"), Component->SetSoundSet(nullptr, Error));
    TestFalse(TEXT("Fresh Original does not capture or rewrite legacy state"), Component->bOriginalSoundsCaptured);
    auto* First = NewObject<USkateSoundSet>();
    First->Loops.Add(TEXT("roll"), Wave(true));
    TestFalse(TEXT("Replacement refuses before audio is ready"), Component->SetSoundSet(First, Error));
    TestFalse(TEXT("Refusal leaves Original uncaptured"), Component->bOriginalSoundsCaptured);

    auto* OriginalLand = Wave(false);
    auto* OriginalPop = Wave(false);
    Component->Waves = {OriginalLand, OriginalPop};
    Component->CueRange.Add(TEXT("land"), FIntPoint(0, 1));
    Component->CueRange.Add(TEXT("pop"), FIntPoint(1, 1));
    Component->LastVariant = 1;
    for (int32 I = 0; I < 12; ++I)
    {
        auto* Audio = NewObject<UAudioComponent>(Component);
        Audio->SetSound(Wave(true));
        Audio->SetVolumeMultiplier(.6f);
        Component->Loops.Add(Audio);
    }
    Component->LoopVolume.Init(.6f, 12);
    const auto OriginalLoops = Component->Loops;
    auto* OriginalRoll = Component->Loops[0]->Sound.Get();
    auto* OriginalSkid = Component->Loops[3]->Sound.Get();
    auto* OriginalGrind = Component->Loops[1]->Sound.Get();
    TestTrue(TEXT("Ready Original is still a no-op"), Component->SetSoundSet(nullptr, Error));
    TestEqual(TEXT("Default keeps variant bookkeeping"), Component->LastVariant, 1);
    TestEqual(TEXT("Default keeps active loop envelope"), Component->LoopVolume[0], .6f);

    auto* NewLand = Wave(false);
    FSkateSoundPool Pool;
    Pool.Variants.Add(NewLand);
    First->OneShots.Add(TEXT("land"), Pool);
    First->Loops.Add(TEXT("skid"), Wave(false));
    TestFalse(TEXT("One invalid loop refuses the complete transaction"), Component->SetSoundSet(First, Error));
    TestEqual(TEXT("Rejected land is not installed"), Component->Waves[0].Get(), OriginalLand);
    TestEqual(TEXT("Rejected roll is not installed"), Component->Loops[0]->Sound.Get(), OriginalRoll);
    TestEqual(TEXT("Rejected set preserves envelopes"), Component->LoopVolume[0], .6f);
    TestEqual(TEXT("Rejected set preserves random bookkeeping"), Component->LastVariant, 1);
    TestFalse(TEXT("Rejected set does not capture defaults"), Component->bOriginalSoundsCaptured);

    First->Loops[TEXT("skid")] = Wave(true);
    Component->bNetworkProxy = true;
    const auto ModeBefore = Component->Mode;
    TestTrue(TEXT("Local presentation of a remote proxy can select a set"), Component->SetSoundSet(First, Error));
    TestTrue(TEXT("The selected asset stays owned"), Component->GetSoundSet() == First);
    TestTrue(TEXT("Proxy ownership stays intact"), Component->bNetworkProxy);
    TestTrue(TEXT("Simulation mode stays intact"), Component->Mode == ModeBefore);
    TestEqual(TEXT("New land variants activate"), Component->Waves[Component->CueRange[TEXT("land")].X].Get(), NewLand);
    TestEqual(TEXT("Unspecified one-shot inherits Original"), Component->Waves[Component->CueRange[TEXT("pop")].X].Get(), OriginalPop);
    TestTrue(TEXT("New roll activates on the existing component"), Component->Loops[0]->Sound.Get() == First->Loops[TEXT("roll")].Get());
    TestEqual(TEXT("Changed loop starts from a silent envelope"), Component->LoopVolume[0], 0.f);
    TestEqual(TEXT("Changed loop output starts silent"), Component->Loops[0]->VolumeMultiplier, 0.f);
    TestEqual(TEXT("Unchanged grind keeps its wave"), Component->Loops[1]->Sound.Get(), OriginalGrind);
    TestEqual(TEXT("Unchanged grind keeps its envelope"), Component->LoopVolume[1], .6f);

    auto* Invalid = NewObject<USkateSoundSet>();
    Invalid->Loops.Add(TEXT("not_a_loop"), Wave(true));
    TestFalse(TEXT("Unknown keys cannot partially replace an active set"), Component->SetSoundSet(Invalid, Error));
    TestTrue(TEXT("Rejected replacement preserves selected asset"), Component->GetSoundSet() == First);
    TestTrue(TEXT("Rejected replacement preserves active roll"), Component->Loops[0]->Sound.Get() == First->Loops[TEXT("roll")].Get());
    Invalid->Loops.Reset();
    Pool.Variants[0] = Wave(true);
    Invalid->OneShots.Add(TEXT("land"), Pool);
    TestFalse(TEXT("Looping waves cannot enter one-shot pools"), Component->SetSoundSet(Invalid, Error));
    TestTrue(TEXT("Malformed one-shot keeps the active selection"), Component->GetSoundSet() == First);

    auto* Second = NewObject<USkateSoundSet>();
    Second->Loops.Add(TEXT("roll"), Wave(true));
    TestTrue(TEXT("A second partial set selects"), Component->SetSoundSet(Second, Error));
    TestEqual(TEXT("Missing skid inherits Original, not the first alternative"), Component->Loops[3]->Sound.Get(), OriginalSkid);
    TestEqual(TEXT("Missing landing inherits Original, not the first alternative"), Component->Waves[Component->CueRange[TEXT("land")].X].Get(), OriginalLand);
    TestTrue(TEXT("Original can be restored"), Component->SetSoundSet(nullptr, Error));
    TestNull(TEXT("Restored Original has no alternative asset"), Component->GetSoundSet());
    TestEqual(TEXT("Restored waves have exactly the original inventory"), Component->Waves.Num(), 2);
    TestEqual(TEXT("Restored roll uses its original reference"), Component->Loops[0]->Sound.Get(), OriginalRoll);
    TestTrue(TEXT("Switching never creates or replaces audio components"), Component->Loops == OriginalLoops);
    return true;
}
#endif
