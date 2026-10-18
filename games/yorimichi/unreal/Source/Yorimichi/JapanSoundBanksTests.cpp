#include "JapanSoundBanks.h"
#include "JapanSoundBank.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "Engine/World.h"
#include "Components/AudioComponent.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FJapanSoundBankSelectionTest,"Yorimichi.Audio.SoundBankSelection",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FJapanSoundBankSelectionTest::RunTest(const FString&)
{
    UWorld* World=UWorld::CreateWorld(EWorldType::Game,false);
    if(!TestNotNull(TEXT("Isolated local test world"),World)) return false;
    auto* Banks=NewObject<UJapanSoundBanks>(World);
    Banks->Restore(0);
    TestFalse(TEXT("Fresh Original does not read or load another bank"),Banks->bRegistryLoaded);
    TestFalse(TEXT("Fresh Original starts no asynchronous load"),Banks->Loading.IsValid());
    TestNull(TEXT("Fresh Original retains delegation"),Banks->Active.Get());
    TestNull(TEXT("Fresh Original does not load its audition"),Banks->PreviewWave.Get());
    FJapanSoundChoice Original;
    Original.Id=TEXT("original"); Original.Label=TEXT("Original");
    bool Saved=false;
    TestFalse(TEXT("A failed preference write refuses the transaction"),Banks->Commit(Original,nullptr,[&](int32){Saved=true;return false;}));
    TestTrue(TEXT("The actual persistence callback was attempted"),Saved);
    TestNull(TEXT("Failed save leaves active references intact"),Banks->Active.Get());
    TestEqual(TEXT("Failed save leaves selected Original intact"),Banks->Selection(),0);
    TestTrue(TEXT("Original can commit with an accepted save"),Banks->Commit(Original,nullptr,[](int32 Value){return Value==0;}));
    FJapanSoundChoice Alternative;
    Alternative.Id=TEXT("dry_street"); Alternative.Selection=2;
    Alternative.Asset=TEXT("/Game/AudioBanks/dry_street/DA_Bank.DA_Bank");
    auto* Wrong=NewObject<UJapanSoundBank>();
    Saved=false;
    TestFalse(TEXT("Wrong asset identity refuses before persistence"),Banks->Commit(Alternative,Wrong,[&](int32){Saved=true;return true;}));
    TestFalse(TEXT("Invalid loaded object never reaches the save callback"),Saved);
    TestNull(TEXT("Invalid object leaves Original active"),Banks->Active.Get());
    const uint64 SelectionToken=Banks->Generation,PreviewToken=Banks->PreviewGeneration;
    Banks->CancelSelection(); Banks->StopPreview();
    TestTrue(TEXT("Cancellation invalidates stale selection completions"),Banks->Generation>SelectionToken);
    TestTrue(TEXT("Stop invalidates pending preview completions"),Banks->PreviewGeneration>PreviewToken);
    Banks->Audition=NewObject<UAudioComponent>(Banks);
    Banks->StopPreview();
    TestNull(TEXT("Stop releases the owned player"),Banks->Audition.Get());
    Banks->bShuttingDown=true;
    Saved=false;
    TestFalse(TEXT("World teardown refuses even a ready request"),Banks->Commit(Original,nullptr,[&](int32){Saved=true;return true;}));
    TestFalse(TEXT("Teardown never writes settings"),Saved);
    World->DestroyWorld(false);
    return true;
}
#endif
