#include "JapanFootsteps.h"
#include "JapanSoundBank.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "Sound/SoundWave.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FJapanFootstepSoundBankTest, "Yorimichi.Audio.FootstepBank",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FJapanFootstepSoundBankTest::RunTest(const FString&)
{
    auto Wave=[] { auto* W=NewObject<USoundWave>(); W->Duration=.2f; return W; };
    auto* Foot=NewObject<UJapanFootstepComponent>();
    auto* Alternative=NewObject<UJapanSoundBank>();
    FString Error;
    TestTrue(TEXT("Fresh Original needs no new bank"),Foot->SetSoundBank(nullptr,Error));
    TestFalse(TEXT("Unready footstep component refuses an alternative"),Foot->SetSoundBank(Alternative,Error));
    auto* Original=NewObject<UJapanFootstepSet>();
    FJapanFootstepBank OriginalPool;
    FJapanSoundPool Pool;
    for(int32 I=0;I<4;++I) { OriginalPool.Steps.Add(Wave()); Pool.Variants.Add(Wave()); }
    Original->Surfaces.Add(TEXT("grass"),OriginalPool);
    Original->MaterialSurfaces.Add(TEXT("Road"),TEXT("stone"));
    Foot->Set=Original;
    Foot->bPlanted[0]=false; Foot->Height[0]=3.f; Foot->SincePlant[0]=.7f;
    TestNotNull(TEXT("Original draws a real legacy sample"),Foot->DrawStep(TEXT("grass"),false));
    auto ExpectedOriginal=Foot->Bags[TEXT("grass")];
    const FName Surfaces[]={TEXT("barefoot"),TEXT("dirt_gravel"),TEXT("grass"),TEXT("leaves"),TEXT("mud_water"),TEXT("stone"),TEXT("wood")};
    for(FName Surface:Surfaces) Alternative->Footsteps.Add(Surface,Pool);
    TestTrue(TEXT("Complete alternative passes read-only preflight"),Foot->CanSetSoundBank(Alternative,Error));
    TestNull(TEXT("Preflight does not activate a bank"),Foot->GetSoundBank());
    Alternative->Footsteps.Remove(TEXT("wood"));
    TestFalse(TEXT("Incomplete alternative refuses atomically"),Foot->SetSoundBank(Alternative,Error));
    TestNull(TEXT("Incomplete request keeps Original selected"),Foot->GetSoundBank());
    TestFalse(TEXT("Refusal preserves plant state"),Foot->bPlanted[0]);
    Alternative->Footsteps.Add(TEXT("wood"),Pool);
    TestTrue(TEXT("Complete alternative selects"),Foot->SetSoundBank(Alternative,Error));
    TestTrue(TEXT("Footsteps draw from selected alternative"),Pool.Variants.Contains(Foot->DrawStep(TEXT("grass"),false)));
    TestTrue(TEXT("Unknown material retains same-bank default fallback"),Pool.Variants.Contains(Foot->DrawStep(TEXT("unmapped"),false)));
    TestTrue(TEXT("Hoof stand-ins keep the exact Original shuffle continuation"),
        Foot->DrawStep(TEXT("grass"),true)==OriginalPool.Steps[ExpectedOriginal.Draw(4)].Get());
    TestTrue(TEXT("Original set and its mapping/attenuation owner stay retained"),Foot->Set.Get()==Original);
    TestEqual(TEXT("Successful swap preserves plant height"),Foot->Height[0],3.f);
    TestEqual(TEXT("Successful swap preserves contact clock"),Foot->SincePlant[0],.7f);
    TestFalse(TEXT("Successful swap preserves plant gate"),Foot->bPlanted[0]);
    TestTrue(TEXT("Original restores"),Foot->SetSoundBank(nullptr,Error));
    TestTrue(TEXT("Original resumes its existing shared foot/hoof queue"),
        Foot->DrawStep(TEXT("grass"),false)==OriginalPool.Steps[ExpectedOriginal.Draw(4)].Get());
    TestTrue(TEXT("Alternative queue is discarded on switch"),Foot->AlternativeBags.IsEmpty());
    return true;
}
#endif
