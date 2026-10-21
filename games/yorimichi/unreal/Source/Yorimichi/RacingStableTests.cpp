#include "RacingStables.h"
#include "RacingPlaces.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "RacingService.h"
#include "HRClock.h"
#include "HRRules.h"
#include "HRSave.h"
#include "HAL/FileManager.h"
#include "Misc/AutomationTest.h"
#include "Algo/AnyOf.h"
#include "Misc/FileHelper.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"
#include "Net/UnrealNetwork.h"
#include "Serialization/MemoryReader.h"
#include "Serialization/MemoryWriter.h"

namespace RacingStableTest
{
    constexpr const TCHAR* Host = TEXT("local:paul");
    constexpr const TCHAR* Guest = TEXT("guest:0123456789abcdef0123456789abcdef");

    /** A fresh world with the host's player and a guest, each given their stable. */
    struct FFixture
    {
        FHRWorldState World;
        bool Make(FAutomationTestBase& Test, bool bGuest = true)
        {
            World = HRRules::CreateWorld(TEXT("yorimichi-stables-test"));
            HRRules::StartClock(World, 1700000000);
            HRRules::AddPlayer(World, Host, TEXT("Paul"));
            if (!Test.TestEqual(TEXT("The host's player gets a stable"), RacingStables::Assign(World, Host), FString())) return false;
            if (bGuest)
            {
                HRRules::AddPlayer(World, Guest, TEXT("Henry"));
                if (!Test.TestEqual(TEXT("The guest gets one"), RacingStables::Assign(World, Guest), FString())) return false;
            }
            return true;
        }
        FHRPlayer& Player(const TCHAR* Id) { return *HRRules::FindPlayer(World, Id); }
        FHRStable& Stable(const TCHAR* Id) { return *HRRules::PlayerStable(World, Id); }
        FString Ask(const TCHAR* Player, ERacingStableAction Action, const FString& Target, const FString& Other = FString())
        {
            FRacingStableRequest R;
            R.Action = uint8(Action);
            R.Target = Target;
            R.Other = Other;
            return RacingStables::Apply(World, Player, R);
        }
        /** A horse of the stable, as old and fit as it takes to breed. */
        FHRHorse& Breeder(const TCHAR* Player, bool bMare)
        {
            TArray<const FHRHorse*> Mine = HRRules::StableHorses(World, Stable(Player).Id);
            FHRHorse& H = World.Horses[Mine[0]->Id];
            H.bMare = bMare;
            H.BirthT = World.T - 3 * HRClock::LifeYear;
            H.ReadyT = FMath::Min(H.ReadyT, World.T);
            H.NextBreedingT = 0;
            return H;
        }
    };

    template <typename T> T OverTheWire(const T& Value)
    {
        TArray<uint8> Bytes;
        FMemoryWriter Writer(Bytes);
        T::StaticStruct()->SerializeBin(Writer, const_cast<T*>(&Value));
        T Received;
        FMemoryReader Reader(Bytes);
        T::StaticStruct()->SerializeBin(Reader, &Received);
        return Received;
    }

    FString TempSave()
    {
        return FPaths::ConvertRelativePathToFull(FPaths::AutomationTransientDir() / FString::Printf(TEXT("racing-stables-%s/world.json"),
            *FGuid::NewGuid().ToString(EGuidFormats::Digits)));
    }
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingStableAssignTest, "Yorimichi.Racing.StableAssign",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingStableAssignTest::RunTest(const FString&)
{
    using namespace RacingStableTest;
    FFixture F;
    if (!F.Make(*this)) return false;
    const FHRStable& Paul = F.Stable(Host);
    TestEqual(TEXT("The host's player gets Belmonte's \"Votre écurie\" (the rules' stable for sale)"), Paul.Id, FString(TEXT("old_mill")));
    TestEqual(TEXT("under the estate's name"), Paul.Name, FString(TEXT("Écurie de la Vallée")));
    TestFalse(TEXT("no longer for sale"), Paul.bForSale);
    TestEqual(TEXT("The guest gets the Hidamari stable"), F.Stable(Guest).Id, FString(TEXT("hidamari")));
    TestEqual(TEXT("Both free: the rules' starting coins kept"), F.Player(Host).Coins, FHRPlayer().Coins);
    TestEqual(TEXT("(the guest's too)"), F.Player(Guest).Coins, FHRPlayer().Coins);
    for (const TCHAR* Who : {Host, Guest})
    {
        const FString Id = F.Stable(Who).Id;
        TestEqual(FString::Printf(TEXT("%s: three jockeys"), Who), HRRules::StableRiders(F.World, Id).Num(), HRRules::RidersPerStable);
        TestTrue(FString::Printf(TEXT("%s: a horse to start with"), Who), HRRules::StableHorses(F.World, Id).Num() >= 1);
        TestFalse(FString::Printf(TEXT("%s: its jockeys ride"), Who), F.Player(Who).bRides);
    }
    for (const TPair<FString, FHRHorse>& It : F.World.Horses)
        TestFalse(TEXT("No horse id carries a player's id"), It.Key.Contains(TEXT("guest:")) || It.Key.Contains(TEXT("local:")));
    TestNull(TEXT("The stand-in founder is gone"), HRRules::FindPlayer(F.World, TEXT("site:hidamari")));
    TestEqual(TEXT("Assigning again changes nothing"), RacingStables::Assign(F.World, Host), FString());
    TestEqual(TEXT("still Belmonte"), F.Stable(Host).Id, FString(TEXT("old_mill")));
    // A third player: V1 has two player stables.
    const TCHAR* Third = TEXT("guest:fedcba9876543210fedcba9876543210");
    HRRules::AddPlayer(F.World, Third, TEXT("Third"));
    TestFalse(TEXT("A third player gets none"), RacingStables::Assign(F.World, Third).IsEmpty());
    TestNull(TEXT("(no stable)"), HRRules::PlayerStable(F.World, Third));
    // A session player (a guest without a usable install id) gets none, even with Hidamari free.
    FHRWorldState Free = HRRules::CreateWorld(TEXT("yorimichi-stables-session"));
    HRRules::AddPlayer(Free, TEXT("session:0123"), TEXT("Session"));
    TestTrue(TEXT("A session player gets no stable"), RacingStables::Assign(Free, TEXT("session:0123")).Contains(TEXT("reconnus")));
    TestNull(TEXT("(none)"), HRRules::PlayerStable(Free, TEXT("session:0123")));
    // A guest first never takes the host's estate.
    FHRWorldState W = HRRules::CreateWorld(TEXT("yorimichi-stables-order"));
    HRRules::AddPlayer(W, Guest, TEXT("Henry"));
    HRRules::AddPlayer(W, Host, TEXT("Paul"));
    RacingStables::Assign(W, Guest);
    RacingStables::Assign(W, Host);
    TestEqual(TEXT("A guest who comes first still gets Hidamari"), HRRules::PlayerStable(W, Guest)->Id, FString(TEXT("hidamari")));
    TestEqual(TEXT("and the host Belmonte"), HRRules::PlayerStable(W, Host)->Id, FString(TEXT("old_mill")));
    // A released stable (a session player's, from a world before guests had an identity) stays in the world, run by it;
    // the next guest takes it over.
    const int32 Horses = HRRules::StableHorses(F.World, TEXT("hidamari")).Num();
    RacingStables::Release(F.World, Guest);
    const FHRStable* Left = HRRules::FindStable(F.World, TEXT("hidamari"));
    if (TestNotNull(TEXT("Hidamari stays"), Left)) TestTrue(TEXT("as a computer stable"), Left->IsComputer());
    TestEqual(TEXT("with its horses"), HRRules::StableHorses(F.World, TEXT("hidamari")).Num(), Horses);
    TestEqual(TEXT("The next guest gets it back"), RacingStables::Assign(F.World, Third), FString());
    TestEqual(TEXT("the same stable"), HRRules::PlayerStable(F.World, Third)->Id, FString(TEXT("hidamari")));
    TestEqual(TEXT("The world stays admissible"), HRSave::Validate(F.World), FString());
    // The world lives on: both stables race with the computer ones over a day.
    HRRules::AdvanceDay(F.World);
    int32 Entries = 0;
    for (const FHRRace& R : F.World.Meeting.Races)
        for (const FHRRunner& E : R.Entries) Entries += E.StableId == TEXT("old_mill") || E.StableId == TEXT("hidamari") ? 1 : 0;
    TestTrue(TEXT("The players' horses are entered the next day"), Entries >= 1);
    TestEqual(TEXT("and the world is still admissible"), HRSave::Validate(F.World), FString());
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingStableEntryTest, "Yorimichi.Racing.StableEntry",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingStableEntryTest::RunTest(const FString&)
{
    using namespace RacingStableTest;
    FFixture F;
    if (!F.Make(*this, false)) return false;
    const FString Horse = HRRules::StableHorses(F.World, TEXT("old_mill"))[0]->Id;
    FRacingStableView View;
    RacingStables::BuildView(F.World, Host, View);
    if (!TestEqual(TEXT("The view shows the horse"), View.Horses.Num(), HRRules::StableHorses(F.World, TEXT("old_mill")).Num())) return false;
    TestTrue(TEXT("entered by default"), View.Horses[0].bEntered && View.Horses[0].bCanRace);
    TestEqual(TEXT("Rest it"), F.Ask(Host, ERacingStableAction::Rest, Horse), FString());
    TestTrue(TEXT("It is resting"), F.Player(Host).Resting.Contains(Horse));
    HRRules::AdvanceDay(F.World);
    bool bRuns = false;
    for (const FHRRace& R : F.World.Meeting.Races) for (const FHRRunner& E : R.Entries) bRuns |= E.HorseId == Horse;
    TestFalse(TEXT("A resting horse sits the next race day out"), bRuns);
    TestEqual(TEXT("Enter it again"), F.Ask(Host, ERacingStableAction::Enter, Horse), FString());
    TestFalse(TEXT("It no longer rests"), F.Player(Host).Resting.Contains(Horse));
    HRRules::AdvanceDay(F.World);
    for (const FHRRace& R : F.World.Meeting.Races) for (const FHRRunner& E : R.Entries) bRuns |= E.HorseId == Horse;
    TestTrue(TEXT("An entered horse runs the next race day"), bRuns);
    RacingStables::BuildView(F.World, Host, View);
    const FRacingStableHorse* Shown = View.Horses.FindByPredicate([&Horse](const FRacingStableHorse& H) { return H.Id == Horse; });
    if (TestNotNull(TEXT("still shown"), Shown)) TestFalse(TEXT("its plate names today's race"), Shown->Today.IsEmpty());
    // Refusals.
    const FString Theirs = HRRules::StableHorses(F.World, TEXT("alders"))[0]->Id;
    TestTrue(TEXT("Another stable's horse is refused"), F.Ask(Host, ERacingStableAction::Rest, Theirs).Contains(TEXT("pas à vous")));
    FHRHorse& H = F.World.Horses[Horse];
    H.Injury.bActive = true;
    TestTrue(TEXT("An injured horse cannot be entered"), F.Ask(Host, ERacingStableAction::Enter, Horse).Contains(TEXT("blessé")));
    H.Injury.bActive = false;
    TestTrue(TEXT("An empty target is refused"), F.Ask(Host, ERacingStableAction::Enter, FString()).Contains(TEXT("valable")));
    TestTrue(TEXT("A player without a stable is refused"), [&] { HRRules::AddPlayer(F.World, TEXT("local:other"), TEXT("O")); return F.Ask(TEXT("local:other"), ERacingStableAction::Enter, Horse); }().Contains(TEXT("pas encore d'écurie")));
    FRacingStableRequest Bad;
    Bad.Action = uint8(ERacingStableAction::Count);
    Bad.Target = Horse;
    TestTrue(TEXT("An unknown action is refused"), RacingStables::Apply(F.World, Host, Bad).Contains(TEXT("valable")));
    // The plate says it in world text.
    const FString Plate = RacingStables::PlateText(View, 0);
    TestTrue(TEXT("The plate names its horse: ") + Plate, Plate.Contains(View.Horses[0].Name, ESearchCase::IgnoreCase));
    for (const TCHAR C : Plate) if (C > 0xFF) { AddError(TEXT("World text is Latin-1 only")); break; }
    TestTrue(TEXT("An empty stall says so"), RacingStables::PlateText(View, 10).Contains(TEXT("libre")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingStableTradeTest, "Yorimichi.Racing.StableTrade",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingStableTradeTest::RunTest(const FString&)
{
    using namespace RacingStableTest;
    FFixture F;
    if (!F.Make(*this, false)) return false;
    FRacingStableMarket Market;
    RacingStables::BuildMarket(F.World, Host, Market);
    TestTrue(TEXT("The market offers today's two recruits"), Market.Horses.Num() >= 2 && Market.Horses[0].Key.StartsWith(TEXT("market:")));
    const int32 Coins = F.Player(Host).Coins;
    const int32 Before = HRRules::StableHorses(F.World, TEXT("old_mill")).Num();
    TestEqual(TEXT("Buy the prospect"), F.Ask(Host, ERacingStableAction::BuyHorse, TEXT("market:prospect")), FString());
    TestEqual(TEXT("paid from the wallet"), F.Player(Host).Coins, Coins - HRRules::ProspectPrice);
    TestEqual(TEXT("one more horse"), HRRules::StableHorses(F.World, TEXT("old_mill")).Num(), Before + 1);
    TestTrue(TEXT("It is gone from the market"), F.Ask(Host, ERacingStableAction::BuyHorse, TEXT("market:prospect")).Contains(TEXT("déjà vendu")));
    F.Player(Host).Coins = 10;
    TestTrue(TEXT("Too dear for the wallet"), F.Ask(Host, ERacingStableAction::BuyHorse, TEXT("market:adult")).Contains(TEXT("pièces")));
    TestEqual(TEXT("costing nothing"), F.Player(Host).Coins, 10);
    // Sell: on the list at its value; another stable buys it at a day's close.
    const FString Horse = HRRules::StableHorses(F.World, TEXT("old_mill"))[0]->Id;
    TestEqual(TEXT("Put it up for sale"), F.Ask(Host, ERacingStableAction::SellHorse, Horse), FString());
    TestTrue(TEXT("It is listed"), F.World.Listings.ContainsByPredicate([&Horse](const FHRSaleListing& L) { return L.HorseId == Horse; }));
    FRacingStableView View;
    RacingStables::BuildView(F.World, Host, View);
    TestTrue(TEXT("Its plate says it is for sale"), View.Horses.ContainsByPredicate([&Horse](const FRacingStableHorse& H) { return H.Id == Horse && H.bListed; }));
    TestEqual(TEXT("Withdraw it"), F.Ask(Host, ERacingStableAction::Withdraw, Horse), FString());
    TestFalse(TEXT("No longer listed"), F.World.Listings.ContainsByPredicate([&Horse](const FHRSaleListing& L) { return L.HorseId == Horse; }));
    TestTrue(TEXT("Selling another stable's horse is refused"),
        F.Ask(Host, ERacingStableAction::SellHorse, HRRules::StableHorses(F.World, TEXT("alders"))[0]->Id).Contains(TEXT("pas à vous")));
    // A listed horse of another stable, bought: its price to the seller.
    F.Player(Host).Coins = 1000;
    HRRules::FindStable(F.World, TEXT("alders"))->Coins = 0;
    FHRSaleListing L;
    L.HorseId = HRRules::StableHorses(F.World, TEXT("alders"))[0]->Id;
    L.SellerId = TEXT("alders");
    L.Price = 90;
    L.SinceT = F.World.T;
    F.World.Listings.Add(L);
    TestEqual(TEXT("Buy a listed horse"), F.Ask(Host, ERacingStableAction::BuyHorse, L.HorseId), FString());
    TestEqual(TEXT("It is ours"), F.World.Horses[L.HorseId].OwnerId, FString(TEXT("old_mill")));
    TestEqual(TEXT("paid"), F.Player(Host).Coins, 910);
    TestEqual(TEXT("to its seller"), HRRules::FindStable(F.World, TEXT("alders"))->Coins, 90);
    TestEqual(TEXT("The world stays admissible"), HRSave::Validate(F.World), FString());
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingStableBreedTest, "Yorimichi.Racing.StableBreed",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingStableBreedTest::RunTest(const FString&)
{
    using namespace RacingStableTest;
    FFixture F;
    if (!F.Make(*this, false)) return false;
    FHRHorse& Mare = F.Breeder(Host, true);
    const FString MareId = Mare.Id;
    FRacingStableMarket Market;
    RacingStables::BuildMarket(F.World, Host, Market);
    const FRacingStableOffer* Stallion = Market.Studs.FindByPredicate([](const FRacingStableOffer& O) { return !O.bMare; });
    if (!TestNotNull(TEXT("Stallions of other stables are offered"), Stallion)) return false;
    const FString Sire = Stallion->Key;
    const int32 Cost = Stallion->Price;
    TestEqual(TEXT("A covering costs the service and the fee"), Cost, HRRules::BreedingCost(F.World, Host, F.World.Horses[Sire]));
    TestTrue(TEXT("A partner is needed"), F.Ask(Host, ERacingStableAction::Breed, MareId).Contains(TEXT("partenaire")));
    F.Player(Host).Coins = Cost - 1;
    TestTrue(TEXT("Not enough coins"), F.Ask(Host, ERacingStableAction::Breed, MareId, Sire).Contains(TEXT("manque")));
    F.Player(Host).Coins = Cost + 50;
    const FString Mares = Market.Studs.ContainsByPredicate([](const FRacingStableOffer& O) { return O.bMare; })
        ? Market.Studs.FindByPredicate([](const FRacingStableOffer& O) { return O.bMare; })->Key : FString();
    if (!Mares.IsEmpty()) TestTrue(TEXT("Two mares cannot breed"), F.Ask(Host, ERacingStableAction::Breed, MareId, Mares).Contains(TEXT("jument et un étalon")));
    TestEqual(TEXT("The covering is done"), F.Ask(Host, ERacingStableAction::Breed, MareId, Sire), FString());
    TestEqual(TEXT("and paid"), F.Player(Host).Coins, 50);
    const FHRPregnancy* P = HRRules::FindPregnancy(F.World, MareId);
    if (TestNotNull(TEXT("The mare is in foal"), P))
    {
        TestEqual(TEXT("for our stable"), P->BreederId, FString(TEXT("old_mill")));
        TestEqual(TEXT("due after the rules' gestation"), P->DueT, F.World.T + HRRules::GestationDays);
    }
    TestTrue(TEXT("Not twice"), !F.Ask(Host, ERacingStableAction::Breed, MareId, Sire).IsEmpty());
    FRacingStableView View;
    RacingStables::BuildView(F.World, Host, View);
    const FRacingStableHorse* Shown = View.Horses.FindByPredicate([&MareId](const FRacingStableHorse& H) { return H.Id == MareId; });
    if (TestNotNull(TEXT("The mare's plate"), Shown)) TestTrue(TEXT("says she is in foal: ") + Shown->Breeding, Shown->Breeding.Contains(TEXT("Pleine")));
    // The foal is born at its due day, in our stable.
    const int32 Due = P ? P->DueT : 0;
    while (F.World.T <= Due) HRRules::AdvanceDay(F.World);
    const bool bFoal = Algo::AnyOf(F.World.Horses, [&MareId](const TPair<FString, FHRHorse>& It)
        { return It.Value.Parents.Contains(MareId) && It.Value.OwnerId == TEXT("old_mill"); });
    TestTrue(TEXT("The foal is born, ours"), bFoal);
    TestNull(TEXT("No longer in foal"), HRRules::FindPregnancy(F.World, MareId));
    TestEqual(TEXT("The world stays admissible"), HRSave::Validate(F.World), FString());
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingStableJockeysTest, "Yorimichi.Racing.StableJockeys",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingStableJockeysTest::RunTest(const FString&)
{
    using namespace RacingStableTest;
    FFixture F;
    if (!F.Make(*this, false)) return false;
    FRacingStableView View;
    RacingStables::BuildView(F.World, Host, View);
    if (!TestEqual(TEXT("The jockeys' board shows three"), View.Jockeys.Num(), 3)) return false;
    for (const FRacingStableRider& J : View.Jockeys)
    {
        TestEqual(TEXT("four stats"), J.Stats.Num(), 4);
        TestEqual(TEXT("the overall is their sum"), J.Overall, int32(J.Stats[0]) + J.Stats[1] + J.Stats[2] + J.Stats[3]);
        TestTrue(TEXT("a salary"), J.Wage >= 1);
    }
    TestEqual(TEXT("The salaries add up"), View.Wages, View.Jockeys[0].Wage + View.Jockeys[1].Wage + View.Jockeys[2].Wage);
    const FString Mine = View.Jockeys[2].Id;
    // List one: on the transfer list at its value; take it off again.
    TestEqual(TEXT("List a jockey"), F.Ask(Host, ERacingStableAction::ListRider, Mine), FString());
    TestEqual(TEXT("at the rules' value"), F.World.Riders[Mine].ListedPrice, HRRules::RiderValue(F.World.Riders[Mine], F.World.T));
    TestEqual(TEXT("Unlist"), F.Ask(Host, ERacingStableAction::UnlistRider, Mine), FString());
    TestEqual(TEXT("off the list"), F.World.Riders[Mine].ListedPrice, 0);
    // A fourth is refused; release one, then a transfer from another stable's list.
    FRacingStableMarket Market;
    const FString Theirs = HRRules::StableRiders(F.World, TEXT("alders"))[0]->Id;
    F.World.Riders[Theirs].ListedPrice = 40;
    RacingStables::BuildMarket(F.World, Host, Market);
    TestTrue(TEXT("The transfer board shows the listed rider"), Market.Riders.ContainsByPredicate([&Theirs](const FRacingStableRider& R) { return R.Id == Theirs && R.Price == 40; }));
    TestTrue(TEXT("A fourth jockey is refused"), F.Ask(Host, ERacingStableAction::HireRider, Theirs).Contains(TEXT("3 jockeys")));
    TestEqual(TEXT("Release one"), F.Ask(Host, ERacingStableAction::ReleaseRider, Mine), FString());
    TestTrue(TEXT("a free agent"), F.World.Riders[Mine].OwnerId.IsEmpty());
    TestTrue(TEXT("Releasing another stable's rider is refused"), F.Ask(Host, ERacingStableAction::ReleaseRider, Theirs).Contains(TEXT("ne monte pas")));
    F.Player(Host).Coins = 30;
    TestTrue(TEXT("A transfer the wallet cannot pay"), F.Ask(Host, ERacingStableAction::HireRider, Theirs).Contains(TEXT("transfert")));
    F.Player(Host).Coins = 500;
    HRRules::FindStable(F.World, TEXT("alders"))->Coins = 0;
    TestEqual(TEXT("The transfer is done"), F.Ask(Host, ERacingStableAction::HireRider, Theirs), FString());
    TestEqual(TEXT("He rides for us"), F.World.Riders[Theirs].OwnerId, FString(TEXT("old_mill")));
    TestEqual(TEXT("the price paid"), F.Player(Host).Coins, 460);
    TestEqual(TEXT("to his old stable"), HRRules::FindStable(F.World, TEXT("alders"))->Coins, 40);
    TestEqual(TEXT("Release another"), F.Ask(Host, ERacingStableAction::ReleaseRider, View.Jockeys[1].Id), FString());
    TestTrue(TEXT("A rider not on the list is refused"),
        F.Ask(Host, ERacingStableAction::HireRider, [&F] { for (const FHRRider* X : HRRules::StableRiders(F.World, TEXT("three_meadows"))) if (X->ListedPrice <= 0) return X->Id; return FString(); }())
            .Contains(TEXT("liste des transferts")));
    TestEqual(TEXT("A free agent signs for no fee"), F.Ask(Host, ERacingStableAction::HireRider, View.Jockeys[1].Id), FString());
    // Salaries: the day's close takes the upkeep and the wages from the wallet; an unpaid jockey leaves.
    FHRStable& St = F.Stable(Host);
    const int32 Upkeep = HRRules::DailyUpkeep(F.World, St);
    const int32 Wages = HRRules::RiderWages(F.World, St.Id);
    F.Player(Host).Coins = 1000;
    HRRules::CloseOwnerDay(F.World, St, 0);
    TestEqual(TEXT("The close pays the upkeep and the salaries"), F.Player(Host).Coins, 1000 - Upkeep);
    RacingStables::BuildView(F.World, Host, View);
    TestEqual(TEXT("as the board says"), View.DailyCosts, Upkeep);
    TestEqual(TEXT("salaries included"), View.Wages, Wages);
    F.Player(Host).Coins = Upkeep - Wages;
    HRRules::CloseOwnerDay(F.World, St, 0);
    TestTrue(TEXT("Jockeys who cannot be paid leave"), HRRules::StableRiders(F.World, St.Id).Num() < 3);
    TestEqual(TEXT("The world stays admissible"), HRSave::Validate(F.World), FString());
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingStableRequestTest, "Yorimichi.Racing.StableRequest",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingStableRequestTest::RunTest(const FString&)
{
    using namespace RacingStableTest;
    {
        URacingStableDesk::StaticClass()->SetUpRuntimeReplicationData();
        TArray<FLifetimeProperty> Props;
        GetDefault<URacingStableDesk>()->GetLifetimeReplicatedProps(Props);
        int32 OwnerOnly = 0;
        for (const FName Name : {FName(TEXT("View")), FName(TEXT("Market"))})
        {
            const FProperty* Property = URacingStableDesk::StaticClass()->FindPropertyByName(Name);
            if (!TestNotNull(TEXT("A replicated property"), Property)) return false;
            for (const FLifetimeProperty& P : Props)
                if (P.RepIndex == Property->RepIndex) OwnerOnly += P.Condition == COND_OwnerOnly ? 1 : 0;
        }
        TestEqual(TEXT("The stable and its market replicate to their owner only"), OwnerOnly, 2);
    }
    const FString Path = TempSave();
    ARacingService* Service = NewObject<ARacingService>(GetTransientPackage());
    if (!TestTrue(TEXT("A world"), Service->OpenWorld(Path, TEXT("stable-request-test")))) return false;
    TestTrue(TEXT("The host's player"), Service->RegisterPlayer(Host, TEXT("Paul")));
    TestTrue(TEXT("A guest"), Service->RegisterPlayer(Guest, TEXT("Henry")));
    TestEqual(TEXT("The guest has Hidamari"), HRRules::PlayerStable(Service->GetWorldState(), Guest)->Id, FString(TEXT("hidamari")));
    URacingStableDesk* OnHost = NewObject<URacingStableDesk>(GetTransientPackage());
    URacingStableDesk* OnClient = NewObject<URacingStableDesk>(GetTransientPackage());
    OnHost->HostPlayerId = Guest;
    auto Round = [&](const FRacingStableRequest& Request)
    {
        const FString Error = OnHost->HostHandle(OverTheWire(Request), Service);
        OnClient->ApplyReply(Request.Seq, Error);
        FRacingStableView View;
        RacingStables::BuildView(Service->GetWorldState(), Guest, View);
        OnHost->HostSetView(View);
        OnClient->ApplyReplicatedView(OverTheWire(OnHost->GetView()));
        return Error;
    };
    FRacingStableRequest R;
    R.Seq = 1;
    R.Action = uint8(ERacingStableAction::BuyHorse);
    R.Target = TEXT("market:adult");
    const int32 Coins = HRRules::FindPlayer(Service->GetWorldState(), Guest)->Coins;
    const int32 Horses = HRRules::StableHorses(Service->GetWorldState(), TEXT("hidamari")).Num();
    TestEqual(TEXT("The host buys the horse for the guest"), Round(R), FString());
    TestTrue(TEXT("The client hears so"), OnClient->GetReplySeq() == 1u && OnClient->GetReplyError().IsEmpty());
    TestEqual(TEXT("Its stable arrives with the new horse"), OnClient->GetView().Horses.Num(), Horses + 1);
    TestEqual(TEXT("and the coins paid"), OnClient->GetView().Coins, Coins - HRRules::AdultPrice);
    TestEqual(TEXT("It is the guest's Hidamari stable"), OnClient->GetView().Site, FString(TEXT("hidamari")));
    TestFalse(TEXT("kept across sessions"), OnClient->GetView().bSession);
    R.Seq = 2;
    R.Action = uint8(ERacingStableAction::Rest);
    R.Target = HRRules::StableHorses(Service->GetWorldState(), TEXT("old_mill"))[0]->Id;
    TestTrue(TEXT("The host's horse is not the guest's"), Round(R).Contains(TEXT("pas à vous")));
    TestTrue(TEXT("and the client hears why"), OnClient->GetReplySeq() == 2u && OnClient->GetReplyError().Contains(TEXT("pas à vous")));
    R.Seq = 3;
    R.Target = FString::ChrN(HRSave::MaxIdChars + 1, TEXT('x'));
    TestTrue(TEXT("An oversized request is refused before the rules"), Round(R).Contains(TEXT("valable")));
    R.Seq = 4;
    R.Action = 200;
    R.Target = TEXT("x");
    TestTrue(TEXT("An unknown action is refused"), Round(R).Contains(TEXT("valable")));
    TestEqual(TEXT("Refusals cost nothing"), OnClient->GetView().Coins, Coins - HRRules::AdultPrice);
    TestTrue(TEXT("The view survives the wire"),
        FRacingStableView::StaticStruct()->CompareScriptStruct(&OnHost->GetView(), &OnClient->GetView(), PPF_None));
    FRacingStableMarket Market;
    RacingStables::BuildMarket(Service->GetWorldState(), Guest, Market);
    const FRacingStableMarket Received = OverTheWire(Market);
    TestTrue(TEXT("The market survives the wire"), FRacingStableMarket::StaticStruct()->CompareScriptStruct(&Market, &Received, PPF_None));
    TestTrue(TEXT("The rate limit is five a second"), URacingStableDesk::MinRequestGap >= .2);
    IFileManager::Get().DeleteDirectory(*FPaths::GetPath(Path), false, true);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingStablePersistenceTest, "Yorimichi.Racing.StablePersistence",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingStablePersistenceTest::RunTest(const FString&)
{
    using namespace RacingStableTest;
    const FString Path = TempSave();
    ARacingService* First = NewObject<ARacingService>(GetTransientPackage());
    if (!TestTrue(TEXT("A world"), First->OpenWorld(Path, TEXT("stable-persist-test")))) return false;
    First->RegisterPlayer(Host, TEXT("Paul"));
    First->RegisterPlayer(Guest, TEXT("Henry"));
    FRacingStableRequest R;
    R.Action = uint8(ERacingStableAction::BuyHorse);
    R.Target = TEXT("market:prospect");
    TestEqual(TEXT("The host's player buys a horse"), First->ApplyStableRequest(Host, R), FString());
    const FString Rider = HRRules::StableRiders(First->GetWorldState(), TEXT("old_mill"))[0]->Id;
    R.Action = uint8(ERacingStableAction::ListRider);
    R.Target = Rider;
    TestEqual(TEXT("and lists a jockey"), First->ApplyStableRequest(Host, R), FString());
    R.Action = uint8(ERacingStableAction::BuyHorse);
    R.Target = TEXT("market:adult");
    TestEqual(TEXT("The guest buys one too"), First->ApplyStableRequest(Guest, R), FString());
    const int32 PaulHorses = HRRules::StableHorses(First->GetWorldState(), TEXT("old_mill")).Num();
    const int32 HidamariHorses = HRRules::StableHorses(First->GetWorldState(), TEXT("hidamari")).Num();
    const int32 Coins = HRRules::FindPlayer(First->GetWorldState(), Host)->Coins;
    TestTrue(TEXT("Saved"), First->SaveNow());
    FString Text;
    FFileHelper::LoadFileToString(Text, *Path);
    FHRWorldState Admitted;
    FString Error;
    TestTrue(TEXT("The file is an admissible world: ") + Error, HRSave::FromJson(Text, Admitted, Error));
    const int32 GuestCoins = HRRules::FindPlayer(First->GetWorldState(), Guest)->Coins;
    for (const TPair<FString, FHRPlayer>& It : Admitted.Players) TestFalse(TEXT("No session player in the file"), ARacingService::IsSessionPlayer(It.Key));
    TestNotNull(TEXT("The guest is in the file"), HRRules::FindPlayer(Admitted, Guest));
    const FHRStable* Saved = HRRules::FindStable(Admitted, TEXT("hidamari"));
    TestTrue(TEXT("and owns Hidamari there"), Saved && Saved->OwnerPlayerId == Guest);

    // The next session: the guest is away, the host plays on for a race day.
    ARacingService* Second = NewObject<ARacingService>(GetTransientPackage());
    if (!TestTrue(TEXT("Reloaded"), Second->OpenWorld(Path, TEXT("another-seed")))) return false;
    const FHRWorldState& S = Second->GetWorldState();
    const FHRStable* Paul = HRRules::PlayerStable(S, Host);
    if (TestNotNull(TEXT("The host's player keeps Belmonte"), Paul))
    {
        TestEqual(TEXT("the same stable"), Paul->Id, FString(TEXT("old_mill")));
        TestEqual(TEXT("with its horses"), HRRules::StableHorses(S, Paul->Id).Num(), PaulHorses);
        TestTrue(TEXT("its jockey still listed"), S.Riders[Rider].ListedPrice > 0);
    }
    TestEqual(TEXT("and the coins"), HRRules::FindPlayer(S, Host)->Coins, Coins);
    const FHRStable* Hidamari = HRRules::FindStable(S, TEXT("hidamari"));
    if (TestNotNull(TEXT("Hidamari is in the world"), Hidamari))
    {
        TestEqual(TEXT("still the away guest's"), Hidamari->OwnerPlayerId, FString(Guest));
        TestEqual(TEXT("with its horses"), HRRules::StableHorses(S, TEXT("hidamari")).Num(), HidamariHorses);
    }
    if (const FHRPlayer* Back = HRRules::FindPlayer(S, Guest)) TestEqual(TEXT("The guest's coins are kept"), Back->Coins, GuestCoins);
    else AddError(TEXT("The guest is kept"));
    Second->RegisterPlayer(Host, TEXT("Paul"));
    // Another guest comes while the first is away: Hidamari is not theirs to take.
    const TCHAR* Other = TEXT("guest:fedcba9876543210fedcba9876543210");
    TestTrue(TEXT("Another guest is registered"), Second->RegisterPlayer(Other, TEXT("Lea")));
    TestNull(TEXT("but gets no stable"), HRRules::PlayerStable(S, Other));
    Second->AdvanceClock(3. * 3600.);
    const FHRStable* Kept = HRRules::FindStable(S, TEXT("hidamari"));
    TestTrue(TEXT("A race day later, Hidamari is still the away guest's"), Kept && Kept->OwnerPlayerId == Guest);
    TestTrue(TEXT("The guest comes back"), Second->RegisterPlayer(Guest, TEXT("Henry")));
    const FHRStable* Back = HRRules::PlayerStable(S, Guest);
    TestTrue(TEXT("and has Hidamari"), Back && Back->Id == TEXT("hidamari"));
    TestEqual(TEXT("The world stays admissible"), HRSave::Validate(S), FString());
    IFileManager::Get().DeleteDirectory(*FPaths::GetPath(Path), false, true);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingStablePlacesTest, "Yorimichi.Racing.StablePlaces",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingStablePlacesTest::RunTest(const FString&)
{
    // Belmonte's "Votre écurie" estate: eleven stall plates and two boards on the stable range's yard front, near the
    // estate's sign (Haras Valley's source.json: "Votre écurie" at (35859, 32184, -812) cm, region frame). The places are
    // runtime.json's racing_places.belmonte_stable as world/regions/belmonte/build.py derives them from the estate's
    // committed placement (this text is its current output).
    const FString Places =
        TEXT("{\"racing_places\":{\"belmonte_stable\":[{\"kind\":\"plate\",\"stall\":0,\"at_cm\":[34909.38,31353.0,-848.0],\"yaw\":90.0,\"size_cm\":[92.0,56.0]},")
        TEXT("{\"kind\":\"plate\",\"stall\":1,\"at_cm\":[35268.12,31353.0,-848.0],\"yaw\":90.0,\"size_cm\":[92.0,56.0]},")
        TEXT("{\"kind\":\"plate\",\"stall\":2,\"at_cm\":[35626.88,31353.0,-848.0],\"yaw\":90.0,\"size_cm\":[92.0,56.0]},")
        TEXT("{\"kind\":\"plate\",\"stall\":3,\"at_cm\":[35985.62,31353.0,-848.0],\"yaw\":90.0,\"size_cm\":[92.0,56.0]},")
        TEXT("{\"kind\":\"plate\",\"stall\":4,\"at_cm\":[36344.38,31353.0,-848.0],\"yaw\":90.0,\"size_cm\":[92.0,56.0]},")
        TEXT("{\"kind\":\"plate\",\"stall\":5,\"at_cm\":[36703.12,31353.0,-848.0],\"yaw\":90.0,\"size_cm\":[92.0,56.0]},")
        TEXT("{\"kind\":\"plate\",\"stall\":6,\"at_cm\":[37061.88,31353.0,-848.0],\"yaw\":90.0,\"size_cm\":[92.0,56.0]},")
        TEXT("{\"kind\":\"plate\",\"stall\":7,\"at_cm\":[38138.12,31353.0,-848.0],\"yaw\":90.0,\"size_cm\":[92.0,56.0]},")
        TEXT("{\"kind\":\"plate\",\"stall\":8,\"at_cm\":[38496.88,31353.0,-848.0],\"yaw\":90.0,\"size_cm\":[92.0,56.0]},")
        TEXT("{\"kind\":\"plate\",\"stall\":9,\"at_cm\":[38855.62,31353.0,-848.0],\"yaw\":90.0,\"size_cm\":[92.0,56.0]},")
        TEXT("{\"kind\":\"plate\",\"stall\":10,\"at_cm\":[39214.38,31353.0,-848.0],\"yaw\":90.0,\"size_cm\":[92.0,56.0]},")
        TEXT("{\"kind\":\"jockeys\",\"stall\":0,\"at_cm\":[37302.0,31353.0,-892.0],\"yaw\":90.0,\"size_cm\":[150.0,112.0]},")
        TEXT("{\"kind\":\"transfers\",\"stall\":0,\"at_cm\":[37898.0,31353.0,-892.0],\"yaw\":90.0,\"size_cm\":[150.0,112.0]}]}}");
    const FVector Origin(55000., -450000., 21000.);
    TArray<RacingStables::FAnchor> A;
    if (!TestTrue(TEXT("Belmonte's places parse"), RacingStables::BelmonteAnchors(RacingPlaces::Parse(Places), Origin, A))) return false;
    TArray<RacingStables::FAnchor> None;
    TestFalse(TEXT("No racing_places, no anchors"), RacingStables::BelmonteAnchors(RacingPlaces::Parse(TEXT("{}")), Origin, None) || None.Num());
    TestFalse(TEXT("A board missing"), RacingStables::BelmonteAnchors(RacingPlaces::Parse(Places.Replace(TEXT("\"transfers\""), TEXT("\"plate\""))), Origin, None));
    int32 Plates = 0, Jockeys = 0, Transfers = 0;
    const FVector Sign = Origin + FVector(35859.2, 32184.4, -812.5);
    for (const RacingStables::FAnchor& X : A)
    {
        Plates += X.Kind == RacingStables::EAnchor::Plate;
        Jockeys += X.Kind == RacingStables::EAnchor::Jockeys;
        Transfers += X.Kind == RacingStables::EAnchor::Transfers;
        TestTrue(TEXT("Facing the yard (+Y)"), X.At.GetRotation().GetForwardVector().Equals(FVector(0., 1., 0.), 1e-3));
        TestTrue(TEXT("Within 40 m of the estate's sign"), FVector::Dist(X.At.GetLocation(), Sign) < 4000.);
        const double Above = X.At.GetLocation().Z - (Origin.Z - 1000.);
        TestTrue(TEXT("At eye height above the yard"), Above > 50. && Above < 200.);
    }
    TestEqual(TEXT("Eleven stall plates"), Plates, 11);
    TestTrue(TEXT("and the two boards"), Jockeys == 1 && Transfers == 1);
    for (int32 I = 0; I < A.Num(); ++I)
        for (int32 J = I + 1; J < A.Num(); ++J)
            TestTrue(TEXT("No two overlap"), FMath::Abs(A[I].At.GetLocation().X - A[J].At.GetLocation().X) >= (A[I].Size.X + A[J].Size.X) * .5);
    // Reach: in front of a plate, not behind it or far off.
    const FVector Front = A[3].At.TransformPosition(FVector(120., 0., -60.));
    TestEqual(TEXT("A player in front reaches its plate"), RacingStables::AnchorInReach(A, Front), 3);
    TestEqual(TEXT("not from behind the wall"), RacingStables::AnchorInReach(A, A[3].At.TransformPosition(FVector(-120., 0., -60.))), int32(INDEX_NONE));
    TestEqual(TEXT("nor from across the yard"), RacingStables::AnchorInReach(A, A[3].At.TransformPosition(FVector(900., 0., -60.))), int32(INDEX_NONE));
    // Hidamari: the plates and the halved cork board from its stable.json.
    const FString Json = TEXT("{\"site\":{\"origin\":[955,447,45.6]},\"stalls\":[{\"id\":\"N1\",\"plaque\":{\"centre\":[1,2,1.75],\"normal\":[0,-1,0],\"size\":[0.42,0.28]}},"
        "{\"id\":\"N2\",\"plaque\":{\"centre\":[4.6,2,1.75],\"normal\":[0,-1,0],\"size\":[0.42,0.28]}}],\"notice_board\":{\"centre\":[-2,5,1.55],\"normal\":[-1,0,0],\"size\":[1.6,1.0]}}");
    TArray<RacingStables::FAnchor> H;
    if (TestTrue(TEXT("Hidamari's anchors"), RacingStables::HidamariAnchors(Json, H)))
    {
        TestEqual(TEXT("two plates and two halves of the board"), H.Num(), 4);
        TestTrue(TEXT("Its first plate where AHidamariStable puts it"), H[0].At.GetLocation().Equals(FVector(95600., -44900., 4735.), 1.));
        TestTrue(TEXT("facing +Y (Blender -Y)"), H[0].At.GetRotation().GetForwardVector().Equals(FVector(0., 1., 0.), 1e-3));
        TestTrue(TEXT("The halves sit side by side on the board"), FVector::Dist(H[2].At.GetLocation(), H[3].At.GetLocation()) > 70.);
    }
    TestFalse(TEXT("Not a stable file"), RacingStables::HidamariAnchors(TEXT("{}"), H));
    // Boards' text.
    FRacingStableView View;
    View.Name = TEXT("Écurie de la Vallée");
    FRacingStableRider R;
    R.Name = TEXT("Jean Dupont");
    R.Stats = {5, 6, 7, 4};
    R.Overall = 22;
    R.Wage = 2;
    View.Jockeys.Add(R);
    TestTrue(TEXT("The jockeys' board lists them"), RacingStables::JockeysText(View).Contains(TEXT("Jean Dupont")));
    FRacingStableMarket Market;
    Market.Riders.Add(R);
    TestTrue(TEXT("The transfer board too"), RacingStables::TransfersText(Market).Contains(TEXT("Jean Dupont")));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingStableFrenchTest, "Yorimichi.Racing.StableFrench",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingStableFrenchTest::RunTest(const FString&)
{
    TestEqual(TEXT("A price"), RacingStables::French(TEXT("It costs 65 coins.")), FString(TEXT("Il coûte 65 pièces.")));
    TestEqual(TEXT("A transfer"), RacingStables::French(TEXT("It costs 42 coins (transfer and first wage).")), FString(TEXT("Il faut 42 pièces (transfert et premier salaire).")));
    TestEqual(TEXT("The roster"), RacingStables::French(TEXT("A stable keeps 3 riders: release one first.")), FString(TEXT("Une écurie garde 3 jockeys : libérez-en un d'abord.")));
    TestEqual(TEXT("A horse's reason"), RacingStables::French(TEXT("Bella: Already in foal.")), FString(TEXT("Bella : déjà pleine.")));
    TestEqual(TEXT("A reason with a colon"), RacingStables::French(TEXT("Too young: two horse years at least.")), FString(TEXT("Trop jeune : deux ans au moins.")));
    TestEqual(TEXT("Missing coins"), RacingStables::French(TEXT("12 coins are missing.")), FString(TEXT("Il manque 12 pièces.")));
    TestEqual(TEXT("Unknown text is passed on"), RacingStables::French(TEXT("Something new.")), FString(TEXT("Something new.")));
    return true;
}
#endif
