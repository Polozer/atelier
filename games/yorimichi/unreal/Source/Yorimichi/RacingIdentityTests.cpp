#include "RacingIdentity.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "HRRules.h"
#include "HRSave.h"
#include "RacingBetting.h"
#include "RacingService.h"
#include "HAL/FileManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"

namespace RacingIdentityTest
{
    FString TempDir()
    {
        return FPaths::ConvertRelativePathToFull(FPaths::AutomationTransientDir() / FString::Printf(TEXT("racing-identity-%s"),
            *FGuid::NewGuid().ToString(EGuidFormats::Digits)));
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingIdentityIdsTest, "Yorimichi.Racing.IdentityIds",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingIdentityIdsTest::RunTest(const FString&)
{
    using namespace RacingIdentity;
    // Generation: 32 hexadecimal digits, a new one each time.
    const FString A = NewInstallId(), B = NewInstallId();
    TestTrue(TEXT("A new id is valid"), IsValidInstallId(A));
    TestEqual(TEXT("32 digits"), A.Len(), InstallIdChars);
    TestNotEqual(TEXT("Two ids differ"), A, B);
    TestFalse(TEXT("Empty"), IsValidInstallId(FString()));
    TestFalse(TEXT("Too short"), IsValidInstallId(A.Left(31)));
    TestFalse(TEXT("Too long"), IsValidInstallId(A + TEXT("0")));
    TestFalse(TEXT("Not hexadecimal"), IsValidInstallId(FString::ChrN(32, TEXT('g'))));
    TestFalse(TEXT("A key is not an id"), IsValidInstallId(HostKey(A)));
    TestFalse(TEXT("No separators"), IsValidInstallId(FGuid::NewGuid().ToString(EGuidFormats::DigitsWithHyphens)));
    // Keys: the host's, a guest's and a session player's never meet.
    TestTrue(TEXT("Host key"), IsHost(HostKey(A)) && IsPersistent(HostKey(A)) && !IsGuest(HostKey(A)));
    TestTrue(TEXT("Guest key"), IsGuest(GuestKey(A)) && IsPersistent(GuestKey(A)) && !IsHost(GuestKey(A)));
    TestTrue(TEXT("Session key"), IsSession(SessionKey(A)) && !IsPersistent(SessionKey(A)));
    TestNotEqual(TEXT("A guest from the host's own install is not the host's player"), GuestKey(A), HostKey(A));
    TestTrue(TEXT("The service's session test agrees"), ARacingService::IsSessionPlayer(SessionKey(A)) && !ARacingService::IsSessionPlayer(GuestKey(A)));
    TestTrue(TEXT("Keys fit the rules' ids"), GuestKey(A).Len() <= HRSave::MaxIdChars);
    // The file: "local:<id>" as before guests had an identity, or the bare id.
    TestEqual(TEXT("The host's file"), ParseFile(HostKey(A)), A);
    TestEqual(TEXT("with a newline"), ParseFile(HostKey(A) + TEXT("\n")), A);
    TestEqual(TEXT("A bare id"), ParseFile(A), A);
    TestEqual(TEXT("Garbage holds none"), ParseFile(TEXT("local:hello")), FString());
    TestEqual(TEXT("Nor a guest key"), ParseFile(GuestKey(A)), FString());
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingIdentityFileTest, "Yorimichi.Racing.IdentityFile",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingIdentityFileTest::RunTest(const FString&)
{
    using namespace RacingIdentity;
    const FString Dir = RacingIdentityTest::TempDir();
    const FString Path = Dir / TEXT("player-id.txt");
    bool bSaved = false;
    const FString First = LoadOrCreate(Path, &bSaved);
    TestTrue(TEXT("Generated once, valid"), IsValidInstallId(First));
    TestTrue(TEXT("and saved"), bSaved);
    FString Text;
    TestTrue(TEXT("The file exists"), FFileHelper::LoadFileToString(Text, *Path));
    TestEqual(TEXT("in the host's format"), Text, HostKey(First));
    TestEqual(TEXT("Read back, the same id"), LoadOrCreate(Path), First);
    TestEqual(TEXT("and again"), LoadOrCreate(Path), First);
    // An existing host's file from before guests had an identity keeps its player.
    const FString Legacy = NewInstallId();
    FFileHelper::SaveStringToFile(HostKey(Legacy) + TEXT("\r\n"), *Path);
    TestEqual(TEXT("A legacy file keeps its id"), LoadOrCreate(Path), Legacy);
    // A damaged file is replaced, once.
    FFileHelper::SaveStringToFile(TEXT("not an id"), *Path);
    const FString Fresh = LoadOrCreate(Path);
    TestTrue(TEXT("A damaged file gets a new id"), IsValidInstallId(Fresh) && Fresh != Legacy);
    TestEqual(TEXT("which then stays"), LoadOrCreate(Path), Fresh);
    IFileManager::Get().DeleteDirectory(*Dir, false, true);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingIdentityCollisionTest, "Yorimichi.Racing.IdentityCollision",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingIdentityCollisionTest::RunTest(const FString&)
{
    using namespace RacingIdentity;
    const FString Id = NewInstallId();
    TSet<FString> Held;
    FString Why;
    TestEqual(TEXT("A guest's id gives its guest key"), ResolveGuest(Id, TEXT("s1"), Held, &Why), GuestKey(Id));
    TestTrue(TEXT("no reason"), Why.IsEmpty());
    Held.Add(GuestKey(Id));
    TestEqual(TEXT("A second guest with the same id gets a session player"), ResolveGuest(Id, TEXT("s2"), Held, &Why), SessionKey(TEXT("s2")));
    TestFalse(TEXT("and a reason"), Why.IsEmpty());
    TestEqual(TEXT("The host's own install id is no collision for a guest"), ResolveGuest(Id, TEXT("s3"), {HostKey(Id)}, &Why), GuestKey(Id));
    TestEqual(TEXT("An invalid id gets a session player"), ResolveGuest(TEXT("../../etc"), TEXT("s4"), {}, &Why), SessionKey(TEXT("s4")));
    TestFalse(TEXT("(said why)"), Why.IsEmpty());
    TestTrue(TEXT("Without a session id, still a session player"), IsSession(ResolveGuest(FString(), FString(), {})));

    // The wallet decides once: a second presentation (another id) changes nothing under the player.
    URacingWallet* Wallet = NewObject<URacingWallet>(GetTransientPackage());
    TestTrue(TEXT("No key before the guest presents its id"), Wallet->GetGuestKey().IsEmpty());
    Wallet->HostIdentify(Id);
    TestEqual(TEXT("The guest's key"), Wallet->GetGuestKey(), GuestKey(Id));
    Wallet->HostIdentify(NewInstallId());
    TestEqual(TEXT("set once"), Wallet->GetGuestKey(), GuestKey(Id));
    URacingWallet* Bad = NewObject<URacingWallet>(GetTransientPackage());
    Bad->HostIdentify(FString::ChrN(4096, TEXT('a')));
    TestTrue(TEXT("An oversized id gets a session player"), IsSession(Bad->GetGuestKey()));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingIdentityReturnTest, "Yorimichi.Racing.IdentityReturn",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingIdentityReturnTest::RunTest(const FString&)
{
    // A guest leaves and comes back in a later session: its wallet, open bet and stable are there again; a session player
    // (an id in use) has none of it; the stables are the host's Belmonte and the first guest's Hidamari, for good.
    using namespace RacingIdentity;
    const FString Dir = RacingIdentityTest::TempDir();
    const FString Path = Dir / TEXT("world.json");
    const FString Host = HostKey(NewInstallId()), Henry = GuestKey(NewInstallId()), Lea = GuestKey(NewInstallId());
    const FString Twin = SessionKey(TEXT("twin"));
    ARacingService* First = NewObject<ARacingService>(GetTransientPackage());
    if (!TestTrue(TEXT("A world"), First->OpenWorld(Path, TEXT("identity-return-test")))) return false;
    TestTrue(TEXT("The host's player"), First->RegisterPlayer(Host, TEXT("Paul")));
    TestTrue(TEXT("The first guest"), First->RegisterPlayer(Henry, TEXT("Henry")));
    TestTrue(TEXT("A second connection with Henry's id, a session player"), First->RegisterPlayer(Twin, TEXT("Twin")));
    const FHRWorldState& S1 = First->GetWorldState();
    TestEqual(TEXT("Belmonte is the host's"), HRRules::PlayerStable(S1, Host)->Id, FString(TEXT("old_mill")));
    TestEqual(TEXT("Hidamari the first guest's"), HRRules::PlayerStable(S1, Henry)->Id, FString(TEXT("hidamari")));
    TestNull(TEXT("The session player has none"), HRRules::PlayerStable(S1, Twin));
    const double Now = First->HostWorldSeconds();
    const FHRRace* Race = nullptr;
    for (const FHRRace& R : S1.Meeting.Races)
        if (!R.IsRun() && R.Entries.Num() >= 2 && HRRules::RaceStartSeconds(S1, R.Key) > Now + 5.) { Race = &R; break; }
    if (!TestNotNull(TEXT("A race ahead"), Race)) return false;
    const FString Key = Race->Key, Horse = Race->Entries[0].HorseId;
    TestEqual(TEXT("Henry bets"), First->PlaceBet(Henry, Key, Horse, 5), FString());
    TestEqual(TEXT("so does the session player"), First->PlaceBet(Twin, Key, Horse, 3), FString());
    const int32 Coins = HRRules::FindPlayer(S1, Henry)->Coins;
    FRacingWalletView View;
    ARacingService::BuildWallet(S1, Henry, Now, View);
    TestFalse(TEXT("Henry's wallet is not for this session only"), View.bSession);
    TestTrue(TEXT("Saved"), First->SaveNow());

    FString Text;
    FFileHelper::LoadFileToString(Text, *Path);
    FHRWorldState Admitted;
    FString Error;
    TestTrue(TEXT("The save is admitted by HRSave: ") + Error, HRSave::FromJson(Text, Admitted, Error));
    TestNotNull(TEXT("Henry is saved"), HRRules::FindPlayer(Admitted, Henry));
    TestNull(TEXT("the session player is not"), HRRules::FindPlayer(Admitted, Twin));
    int32 HenryTickets = 0, TwinTickets = 0;
    for (const FHRTicket& T : Admitted.Tickets) { HenryTickets += T.PlayerId == Henry; TwinTickets += T.PlayerId == Twin; }
    TestEqual(TEXT("Henry's open ticket is saved"), HenryTickets, 1);
    TestEqual(TEXT("the session player's is not"), TwinTickets, 0);

    // The next session: Lea comes first, then Henry.
    ARacingService* Second = NewObject<ARacingService>(GetTransientPackage());
    if (!TestTrue(TEXT("Reloaded"), Second->OpenWorld(Path, TEXT("another-seed")))) return false;
    const FHRWorldState& S2 = Second->GetWorldState();
    Second->RegisterPlayer(Host, TEXT("Paul"));
    TestTrue(TEXT("Lea"), Second->RegisterPlayer(Lea, TEXT("Lea")));
    TestNull(TEXT("Lea, first tonight, does not take the away guest's Hidamari"), HRRules::PlayerStable(S2, Lea));
    TestTrue(TEXT("Henry comes back"), Second->RegisterPlayer(Henry, TEXT("Henry")));
    const FHRPlayer* Back = HRRules::FindPlayer(S2, Henry);
    if (TestNotNull(TEXT("with his wallet"), Back)) TestEqual(TEXT("and its coins"), Back->Coins, Coins);
    const FHRStable* Stable = HRRules::PlayerStable(S2, Henry);
    TestTrue(TEXT("and Hidamari"), Stable && Stable->Id == TEXT("hidamari"));
    ARacingService::BuildWallet(S2, Henry, Now, View);
    TestTrue(TEXT("His open bet is in his wallet"), View.bActive && View.OpenCount() == 1 && View.Tickets.Num() == 1 && View.Tickets[0].Stake == 5);
    TestEqual(TEXT("The host keeps Belmonte"), HRRules::PlayerStable(S2, Host)->Id, FString(TEXT("old_mill")));
    TestEqual(TEXT("The world stays admissible"), HRSave::Validate(S2), FString());
    IFileManager::Get().DeleteDirectory(*Dir, false, true);
    return true;
}
#endif
