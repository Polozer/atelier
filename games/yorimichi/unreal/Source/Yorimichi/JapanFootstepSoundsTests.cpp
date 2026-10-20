#include "JapanFootsteps.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "Sound/SoundWave.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FJapanFootstepShuffleTest, "Yorimichi.Audio.FootstepShuffle",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FJapanFootstepShuffleTest::RunTest(const FString&)
{
    auto Wave=[] { auto* W=NewObject<USoundWave>(); W->Duration=.2f; return W; };
    auto* Foot=NewObject<UJapanFootstepComponent>();
    TestNull(TEXT("No set, no step"),Foot->DrawStep(TEXT("grass")));
    auto* Original=NewObject<UJapanFootstepSet>();
    FJapanFootstepBank Pool;
    for(int32 I=0;I<4;++I) Pool.Steps.Add(Wave());
    Original->Surfaces.Add(TEXT("grass"),Pool);
    Foot->Set=Original;
    TestNotNull(TEXT("Original draws a real sample"),Foot->DrawStep(TEXT("grass")));
    // Feet and hoof stand-ins share one shuffled queue per surface, so a sample never comes round twice in a row.
    auto Expected=Foot->Bags[TEXT("grass")];
    for(int32 I=0;I<8;++I)
        TestTrue(TEXT("Each draw continues the surface's single shuffle"),
            Foot->DrawStep(TEXT("grass"))==Pool.Steps[Expected.Draw(4)].Get());
    TestTrue(TEXT("An unknown surface falls back to the default surface's samples"),
        Pool.Steps.Contains(Foot->DrawStep(TEXT("unmapped"))));
    return true;
}
#endif
