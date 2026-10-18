#include "JapanSoundBanks.h"
#include "JapanSoundBank.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "Engine/World.h"
#include "Components/AudioComponent.h"
#include "Engine/StreamableManager.h"
#include "Sound/SoundWave.h"
#include "UObject/StrongObjectPtr.h"

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
    Banks->Audition=NewObject<UAudioComponent>(Banks);
    const uint64 FailedPreviewToken=Banks->PreviewGeneration;
    bool Saved=false;
    TestFalse(TEXT("A failed preference write refuses the transaction"),Banks->Commit(Original,nullptr,[&](int32){Saved=true;return false;}));
    TestTrue(TEXT("The actual persistence callback was attempted"),Saved);
    TestNull(TEXT("Failed save leaves active references intact"),Banks->Active.Get());
    TestEqual(TEXT("Failed save leaves selected Original intact"),Banks->Selection(),0);
    TestNotNull(TEXT("Failed save preserves an already requested current-bank preview"),Banks->Audition.Get());
    TestEqual(TEXT("Failed save does not invalidate the current audition"),Banks->PreviewGeneration,FailedPreviewToken);
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
    Banks->Active=Wrong; Banks->ActiveSelection=2;
    Banks->Audition=NewObject<UAudioComponent>(Banks);
    const uint64 BeforeRestore=Banks->PreviewGeneration;
    TestTrue(TEXT("Actual restoration commits after preflight"),Banks->Commit(Original,nullptr,{}));
    TestNull(TEXT("Successful actual bank change stops the previous audition"),Banks->Audition.Get());
    TestTrue(TEXT("Successful commit invalidates pending old-bank previews"),Banks->PreviewGeneration>BeforeRestore);
    Banks->bShuttingDown=true;
    Saved=false;
    TestFalse(TEXT("World teardown refuses even a ready request"),Banks->Commit(Original,nullptr,[&](int32){Saved=true;return true;}));
    TestFalse(TEXT("Teardown never writes settings"),Saved);
    World->DestroyWorld(false);
    return true;
}

class FWaitForSoundBankCompletion : public IAutomationLatentCommand
{
public:
    explicit FWaitForSoundBankCompletion(TFunction<bool()> InPoll):Poll(MoveTemp(InPoll)){}
    virtual bool Update() override { return Poll(); }
private:
    TFunction<bool()> Poll;
};

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FJapanSoundBankCompletionTest,"Yorimichi.Audio.SoundBankSelectionCompletion",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FJapanSoundBankCompletionTest::RunTest(const FString&)
{
    UWorld* World=UWorld::CreateWorld(EWorldType::Game,false);
    if(!TestNotNull(TEXT("Isolated completion test world"),World)) return false;
    auto* Banks=NewObject<UJapanSoundBanks>(World); Banks->AddToRoot();
    const auto Clean=[Banks,World] { Banks->Deinitialize(); Banks->RemoveFromRoot(); World->DestroyWorld(false); };
    if(!Banks->ReadRegistry()) { AddError(TEXT("Completion acceptance requires the current native registry.")); Clean(); return false; }
    const auto* Dry=Banks->Choices.FindByPredicate([](const auto& C){return C.Selection==2;});
    const auto* Original=Banks->Choices.FindByPredicate([](const auto& C){return C.Selection==0;});
    if(!Dry || !Original) { AddError(TEXT("Completion acceptance requires the complete imported Dry Street bank.")); Clean(); return false; }
    auto* Installed=LoadObject<UJapanSoundBank>(nullptr,*Dry->Asset);
    auto* Preview=LoadObject<USoundWave>(nullptr,*Original->Audition);
    FString Error;
    if(!Installed || !Preview || !Banks->Validate(*Dry,Installed,Error))
    { AddError(TEXT("Completion test refuses missing or invalid actual installed assets: ")+Error); Clean(); return false; }
    const auto KeepBank=MakeShared<TStrongObjectPtr<UJapanSoundBank>>(Installed);
    const auto KeepPreview=MakeShared<TStrongObjectPtr<USoundWave>>(Preview);
    const FJapanSoundChoice OriginalChoice=*Original;
    Banks->Select(2); Banks->Preview();
    const uint64 PendingPreview=Banks->PreviewGeneration;
    const double Deadline=FPlatformTime::Seconds()+15.;
    const TSharedRef<int32> Stage=MakeShared<int32>(0);
    ADD_LATENT_AUTOMATION_COMMAND(FWaitForSoundBankCompletion([this,Banks,KeepBank,KeepPreview,OriginalChoice,PendingPreview,Deadline,Stage,Clean]
    {
        if(FPlatformTime::Seconds()>Deadline)
        { AddError(TEXT("Actual async bank completion exceeded15s.")); Clean(); return true; }
        if(Banks->Loading) return false;
        TestEqual(TEXT("Actual async selection installed Dry Street"),Banks->Active.Get(),KeepBank->Get());
        TestNotNull(TEXT("Fixture retains Original preview across deferred collection"),KeepPreview->Get());
        TestFalse(TEXT("Old pending/player preview cannot survive completion"),Banks->IsPreviewing());
        if(*Stage==0)
        {
            TestTrue(TEXT("Commit invalidated the preview requested during loading"),Banks->PreviewGeneration>PendingPreview);
            *Stage=1;
            Banks->Select(0); Banks->Select(2); Banks->Preview();
            // Model a preview decode completing before the selection load. The
            // actual production completion method creates the owned audio player.
            if(Banks->PreviewLoading) Banks->PreviewLoading->CancelHandle();
            Banks->PreviewLoading.Reset();
            Banks->PreviewLoaded(Banks->PreviewGeneration,OriginalChoice);
            TestNotNull(TEXT("Old audition player exists while new bank is pending"),Banks->Audition.Get());
            return false;
        }
        TestNull(TEXT("Successful async commit releases the old player's wave"),Banks->PreviewWave.Get());
        Clean(); return true;
    }));
    return true;
}
#endif
