#include "RacingRecords.h"
#include "RacingPlaces.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "RacingService.h"
#include "HRClock.h"
#include "HRRules.h"
#include "HRSave.h"
#include "HAL/FileManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"
#include "Net/UnrealNetwork.h"
#include "Serialization/MemoryReader.h"
#include "Serialization/MemoryWriter.h"

namespace RacingRecordsTest
{
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
        return FPaths::ConvertRelativePathToFull(FPaths::AutomationTransientDir() / FString::Printf(TEXT("racing-records-%s/world.json"),
            *FGuid::NewGuid().ToString(EGuidFormats::Digits)));
    }

    /** A world run for Days race days with its ledger noting every race, as the host does (ARacingService::AdvanceNoting). */
    struct FFixture
    {
        FHRWorldState World;
        FRacingLedger Ledger;
        void Make(int32 Days, const TCHAR* Seed = TEXT("yorimichi-records-test"))
        {
            World = HRRules::CreateWorld(Seed);
            HRRules::StartClock(World, 1700000000);
            Ledger = FRacingLedger();
            Ledger.Seed = World.Seed;
            for (int32 D = 0; D < Days; ++D) Day();
        }
        void Day()
        {
            const double End = HRClock::DayStart(World.T + 1);
            HRRules::AdvanceTo(World, End - 1e-3);
            RacingRecords::Note(Ledger, World, End, true);
            HRRules::AdvanceTo(World, End);
        }
        FRacingRecordsPage Page(ERacingHallObject Object, uint8 Index = 0, ERacingHallKind Kind = ERacingHallKind::Horse, int32 PageNo = 0,
            const FString& Subject = FString(), uint8 Sort = 0, const FString& Search = FString())
        {
            FRacingRecordsQuery Q;
            Q.Seq = 7;
            Q.Object = uint8(Object);
            Q.Index = Index;
            Q.Kind = uint8(Kind);
            Q.Page = PageNo;
            Q.Subject = Subject;
            Q.Sort = Sort;
            Q.Search = Search;
            FRacingRecordsPage Out;
            RacingRecords::BuildPage(World, Ledger, HRClock::DayStart(World.T) + 1., Q, Out);
            return Out;
        }
    };
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingRecordsLedgerTest, "Yorimichi.Racing.RecordsLedger",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingRecordsLedgerTest::RunTest(const FString&)
{
    using namespace RacingRecordsTest;
    FFixture F;
    F.World = HRRules::CreateWorld(TEXT("yorimichi-records-test"));
    HRRules::StartClock(F.World, 1700000000);
    F.Ledger.Seed = F.World.Seed;
    // A race is noted as it is seen: not at its start, once its winner is home, and once only.
    const double End = HRClock::DayStart(F.World.T + 1);
    HRRules::AdvanceTo(F.World, End - 1e-3);
    const FHRRace* First = nullptr;
    for (const FHRRace& R : F.World.Meeting.Races) if (R.Status == TEXT("run") && R.Finishes.Num()) { First = &R; break; }
    if (!TestNotNull(TEXT("A race was run on the first day"), First)) return false;
    const double Start = HRRules::RaceStartSeconds(F.World, First->Key);
    TestTrue(TEXT("Its start: the board is opened"), RacingRecords::Note(F.Ledger, F.World, Start, false));
    TestFalse(TEXT("but the race is not noted before its winner is home"), F.Ledger.Seen.Contains(FString::Printf(TEXT("%d:%s"), F.World.T, *First->Key)));
    RacingRecords::Note(F.Ledger, F.World, Start + First->Finishes[0].TimeUs / 1e6 + .01, false);
    TestTrue(TEXT("Once the winner is home it is"), F.Ledger.Seen.Contains(FString::Printf(TEXT("%d:%s"), F.World.T, *First->Key)));
    const int32 Riders = F.Ledger.Riders.Num();
    TestTrue(TEXT("with its riders"), Riders > 0);
    RacingRecords::Note(F.Ledger, F.World, End, true);
    const uint32 Revision = F.Ledger.Revision;
    TestFalse(TEXT("Noting again changes nothing"), RacingRecords::Note(F.Ledger, F.World, End, true));
    TestEqual(TEXT("(its revision too)"), F.Ledger.Revision, Revision);
    HRRules::AdvanceTo(F.World, End);
    for (int32 D = 0; D < 14; ++D) F.Day();
    TestTrue(TEXT("Records on the circuits"), F.Ledger.Records.ContainsByPredicate([](const FRacingRecordTime& R) { return R.Key.StartsWith(TEXT("c:")); }));
    TestTrue(TEXT("and in the Grands Prix"), F.Ledger.Records.ContainsByPredicate([](const FRacingRecordTime& R) { return R.Key.StartsWith(TEXT("gp:")); }));
    TestTrue(TEXT("Yesterday's races only are remembered as noted"), F.Ledger.Seen.Num() <= 2 * HRRules::MaxRunners * 4);
    for (const FRacingRecordTime& R : F.Ledger.Records)
    {
        TestTrue(TEXT("A record has its time and its horse"), R.TimeUs > 0 && !R.Horse.IsEmpty() && F.World.Horses.Contains(R.HorseId));
        TestTrue(TEXT("and a distance"), R.Distance > 0);
        if (R.Key.StartsWith(TEXT("c:")))
            TestTrue(TEXT("Its key is its circuit and distance"), R.Key.EndsWith(FString::Printf(TEXT(":%d"), R.Distance)));
    }
    // Each record is the best time ever run there: no career race at that circuit and distance was faster (checked
    // against a ledger noting a copy race by race).
    for (const TPair<FString, FRacingRiderTally>& P : F.Ledger.Riders)
    {
        TestTrue(TEXT("Wins within rides"), P.Value.Wins <= P.Value.Rides && P.Value.GpWins <= P.Value.Wins);
        TestTrue(TEXT("A streak within wins"), P.Value.Streak <= P.Value.BestStreak && P.Value.BestStreak <= P.Value.Wins);
        if (const FHRRider* R = F.World.Riders.Find(P.Key))
            TestTrue(TEXT("The ledger's wins are the rules' since it opened"), P.Value.Wins <= R->Wins);
    }
    // The ledger round trip.
    FRacingLedger Back;
    if (TestTrue(TEXT("The ledger reads back"), FRacingLedger::FromJson(F.Ledger.ToJson(), Back)))
    {
        TestEqual(TEXT("Same JSON"), Back.ToJson(), F.Ledger.ToJson());
        TestEqual(TEXT("Same records"), Back.Records.Num(), F.Ledger.Records.Num());
    }
    TestFalse(TEXT("Not a ledger"), FRacingLedger::FromJson(TEXT("{\"version\":99}"), Back));
    TestFalse(TEXT("Not JSON"), FRacingLedger::FromJson(TEXT("nope"), Back));
    // Admission: unique record keys, bounded and sane counts, before anything is changed.
    const FString Rec = TEXT("{\"key\":\"c:1:1200\",\"distance\":1200,\"time_us\":70000000,\"t\":3}");
    TestTrue(TEXT("A minimal ledger"), FRacingLedger::FromJson(FString::Printf(TEXT("{\"version\":1,\"seed\":\"s\",\"since\":-1,\"records\":[%s]}"), *Rec), Back));
    TestFalse(TEXT("A duplicate record key"), FRacingLedger::FromJson(FString::Printf(TEXT("{\"version\":1,\"records\":[%s,%s]}"), *Rec, *Rec), Back));
    TestFalse(TEXT("A negative day"), FRacingLedger::FromJson(TEXT("{\"version\":1,\"since\":-5}"), Back));
    TestFalse(TEXT("More wins than rides"), FRacingLedger::FromJson(TEXT("{\"version\":1,\"riders\":{\"r1\":{\"rides\":1,\"wins\":2}}}"), Back));
    TestFalse(TEXT("A negative tally"), FRacingLedger::FromJson(TEXT("{\"version\":1,\"riders\":{\"r1\":{\"rides\":-1}}}"), Back));
    TestFalse(TEXT("A non-string seen race"), FRacingLedger::FromJson(TEXT("{\"version\":1,\"seen\":[3]}"), Back));
    // A faster time replaces a record, a slower one does not.
    FHRWorldState S = F.World;
    S.Meeting.Races.Reset();
    FHRRace& R = S.Meeting.Races.AddDefaulted_GetRef();
    R.Key = TEXT("village:9");
    R.Round = TEXT("village");
    R.EventId = HRContent::EventForT(S.T).Id;
    R.Distance = 4321;
    R.Status = TEXT("run");
    FHRFinish& W = R.Finishes.AddDefaulted_GetRef();
    W.HorseId = TEXT("h-fast");
    W.HorseName = TEXT("Quick");
    W.Place = 1;
    W.TimeUs = 60000000;
    W.RiderId = TEXT("r-test");
    W.RiderName = TEXT("Ann Test");
    FRacingLedger L;
    RacingRecords::Note(L, S, 0., true);
    const FString Key = FString::Printf(TEXT("c:%d:4321"), RacingRecords::CircuitOf(S.T));
    TestTrue(TEXT("The first time is the record"), L.Find(Key) && L.Find(Key)->TimeUs == 60000000);
    R.Key = TEXT("village:10");
    W.TimeUs = 61000000;
    W.HorseName = TEXT("Slow");
    RacingRecords::Note(L, S, 0., true);
    TestEqual(TEXT("A slower one leaves it"), L.Find(Key)->Horse, FString(TEXT("Quick")));
    R.Key = TEXT("village:11");
    W.TimeUs = 59000000;
    W.HorseName = TEXT("Quicker");
    RacingRecords::Note(L, S, 0., true);
    TestEqual(TEXT("A faster one takes it"), L.Find(Key)->Horse, FString(TEXT("Quicker")));
    TestEqual(TEXT("The rider won three in a row"), L.Riders[TEXT("r-test")].BestStreak, 3);
    R.Key = TEXT("semi:0");
    R.Round = TEXT("semi");
    RacingRecords::Note(L, S, 0., true);
    TestEqual(TEXT("A heat is a ride, never a win"), L.Riders[TEXT("r-test")].Wins, 3);
    TestEqual(TEXT("and does not end a streak"), L.Riders[TEXT("r-test")].Streak, 3);
    TestEqual(TEXT("but it is a ride"), L.Riders[TEXT("r-test")].Rides, 4);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingRecordsHonoursTest, "Yorimichi.Racing.RecordsHonours",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingRecordsHonoursTest::RunTest(const FString&)
{
    using namespace RacingRecordsTest;
    // Streaks: consecutive wins in order, heats skipped.
    TArray<FHRCareerLine> Career;
    auto Line = [&Career](int32 Place, const TCHAR* Round = TEXT("village")) { FHRCareerLine L; L.Place = Place; L.Round = Round; Career.Add(L); };
    Line(1); Line(1); Line(2); Line(1); Line(3, TEXT("semi")); Line(1); Line(1, TEXT("final")); Line(4);
    TestEqual(TEXT("The longest run of wins, a heat in between"), RacingRecords::LongestStreak(Career), 3);
    TestEqual(TEXT("None"), RacingRecords::LongestStreak({}), 0);

    FFixture F;
    F.Make(13);
    for (int32 K = 0; K < int32(ERacingHallKind::Count); ++K)
    {
        const TArray<RacingRecords::FTally> All = RacingRecords::Tallies(F.World, F.Ledger, ERacingHallKind(K));
        TestTrue(TEXT("Someone of each kind"), All.Num() > 0);
        for (const RacingRecords::FTally& T : All)
        {
            TestTrue(TEXT("Wins and defeats are the starts"), T.Wins + T.Defeats <= T.Starts && T.Wins <= T.Starts);
            TestTrue(TEXT("A streak within the wins"), T.Streak <= T.Wins);
            TestTrue(TEXT("A Grand Prix is a win"), K == int32(ERacingHallKind::Stable) || T.GrandPrix <= T.Wins);
        }
        for (int32 H = 0; H < int32(ERacingHonour::Count); ++H)
        {
            const TArray<RacingRecords::FTally> Rank = RacingRecords::Ranking(F.World, F.Ledger, ERacingHallKind(K), ERacingHonour(H));
            for (int32 I = 1; I < Rank.Num(); ++I)
                TestTrue(TEXT("Best first"), Rank[I - 1].Value(ERacingHonour(H)) >= Rank[I].Value(ERacingHonour(H)));
            for (const RacingRecords::FTally& T : Rank) TestTrue(TEXT("Nobody with nothing"), T.Value(ERacingHonour(H)) > 0);
        }
    }
    // The horses' numbers are the rules'.
    const TArray<RacingRecords::FTally> Horses = RacingRecords::Ranking(F.World, F.Ledger, ERacingHallKind::Horse, ERacingHonour::Wins);
    if (TestTrue(TEXT("A winner"), Horses.Num() > 0))
    {
        const FHRHorse& H = F.World.Horses[Horses[0].Subject.Mid(6)];
        TestEqual(TEXT("Its wins are the rules'"), Horses[0].Wins, H.Wins);
        TestEqual(TEXT("its earnings too"), Horses[0].Earnings, H.Earnings);
        TestEqual(TEXT("and its streak its career's"), Horses[0].Streak, RacingRecords::LongestStreak(H.Career));
    }
    // A stable wins a race once, however many of its horses ran in it; its titles are the rules'.
    const TArray<RacingRecords::FTally> Stables = RacingRecords::Tallies(F.World, F.Ledger, ERacingHallKind::Stable);
    int32 StableWins = 0, Races = 0;
    for (const RacingRecords::FTally& T : Stables)
    {
        StableWins += T.Wins;
        const FHRStable* St = HRRules::FindStable(F.World, T.Subject.Mid(7));
        if (TestNotNull(TEXT("A stable"), St)) TestEqual(TEXT("Its Grands Prix are its titles"), T.GrandPrix, St->GpTitles.Num());
    }
    TSet<FString> Won;
    for (const TPair<FString, FHRHorse>& P : F.World.Horses)
        for (const FHRCareerLine& C : P.Value.Career)
            if (C.Place == 1 && !HRRules::IsHeatRound(C.Round)) Won.Add(FString::Printf(TEXT("%d:%s"), C.T, *C.RaceKey));
    Races = Won.Num();
    TestEqual(TEXT("Every race won counts once among the stables"), StableWins, Races);
    // A rider goes to the archives as a horse does, two in-game years after retiring.
    FHRRider R;
    R.RetiredT = 10;
    TestFalse(TEXT("Not yet"), RacingRecords::IsArchived(R, 10 + HRClock::ArchiveDays - 1));
    TestTrue(TEXT("Two years on"), RacingRecords::IsArchived(R, 10 + HRClock::ArchiveDays));
    R.RetiredT = -1;
    TestFalse(TEXT("Never while riding"), RacingRecords::IsArchived(R, 100000));
    TestEqual(TEXT("The rules' archive delay is two seasons"), HRClock::ArchiveDays, 2 * HRClock::DaysPerSeason);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingRecordsPagesTest, "Yorimichi.Racing.RecordsPages",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingRecordsPagesTest::RunTest(const FString&)
{
    using namespace RacingRecordsTest;
    FFixture F;
    F.Make(13);
    // Every object and ranking builds a page.
    for (int32 O = 0; O < int32(ERacingHallObject::Count); ++O)
        for (int32 K = 0; K < int32(ERacingHallKind::Count); ++K)
        {
            const int32 Indexes = O == int32(ERacingHallObject::Record) ? RacingRecords::Panels().Num() : O == int32(ERacingHallObject::Honour) ? int32(ERacingHonour::Count) : 1;
            for (int32 I = 0; I < Indexes; ++I)
            {
                const FRacingRecordsPage P = F.Page(ERacingHallObject(O), uint8(I), ERacingHallKind(K));
                TestTrue(FString::Printf(TEXT("Object %d index %d kind %d: %s"), O, I, K, *P.Error), P.Error.IsEmpty() && !P.Title.IsEmpty());
                TestTrue(TEXT("At most a page of lines"), P.Lines.Num() <= RacingRecords::PageLines);
                TestEqual(TEXT("The answer to that query"), P.Seq, 7u);
            }
        }
    TestEqual(TEXT("Seven record panels: three circuits, four Grands Prix"), RacingRecords::Panels().Num(), 7);
    // The board: the standings and today's results.
    const FRacingRecordsPage Board = F.Page(ERacingHallObject::Board);
    TestTrue(TEXT("The board's standings"), Board.Lines.Num() > 0 && Board.Lines[0].bHeading);
    // Paging: the cabinet's horses.
    const FRacingRecordsPage First = F.Page(ERacingHallObject::Cabinet);
    TestTrue(TEXT("Many horses"), First.Total > RacingRecords::PageLines);
    TestEqual(TEXT("Pages"), First.Pages, FMath::DivideAndRoundUp(First.Total, RacingRecords::PageLines));
    const FRacingRecordsPage Second = F.Page(ERacingHallObject::Cabinet, 0, ERacingHallKind::Horse, 1);
    TestEqual(TEXT("The second page"), Second.Page, 1);
    TestTrue(TEXT("other cards"), Second.Lines.Num() > 0 && Second.Lines[0].Subject != First.Lines[0].Subject);
    const FRacingRecordsPage Past = F.Page(ERacingHallObject::Cabinet, 0, ERacingHallKind::Horse, 9999);
    TestEqual(TEXT("A page too far is the last"), Past.Page, Past.Pages - 1);
    for (int32 I = 1; I < First.Lines.Num(); ++I) TestTrue(TEXT("By name"), First.Lines[I - 1].Left <= First.Lines[I].Left);
    // Search.
    if (!TestTrue(TEXT("Cards"), First.Lines.Num() > 0)) return false;
    const FString Name = First.Lines[0].Left;
    const FRacingRecordsPage Found = F.Page(ERacingHallObject::Cabinet, 0, ERacingHallKind::Horse, 0, FString(), 0, Name.Left(4).ToLower());
    TestTrue(TEXT("A name found by its start, case ignored"), Found.Lines.ContainsByPredicate([&Name](const FRacingRecordsLine& L) { return L.Left == Name; }));
    TestTrue(TEXT("and only matching names"), Found.Total <= First.Total);
    const FRacingRecordsPage Letter = F.Page(ERacingHallObject::Cabinet, 0, ERacingHallKind::Horse, 0, FString(), 0, Name.Left(1));
    for (const FRacingRecordsLine& L : Letter.Lines) TestTrue(TEXT("One letter: names starting with it"), L.Left.StartsWith(Name.Left(1), ESearchCase::IgnoreCase));
    const FRacingRecordsPage Nobody = F.Page(ERacingHallObject::Cabinet, 0, ERacingHallKind::Horse, 0, FString(), 0, TEXT("zzzqqq"));
    TestEqual(TEXT("Nobody"), Nobody.Total, 0);
    const FRacingRecordsPage ByWins = F.Page(ERacingHallObject::Cabinet, 0, ERacingHallKind::Jockey, 0, FString(), 1);
    TestTrue(TEXT("Jockeys by wins"), ByWins.Lines.Num() > 1);
    // Cards.
    for (const TCHAR* Kind : {TEXT("horse"), TEXT("jockey"), TEXT("stable")})
    {
        const ERacingHallKind K = FCString::Strcmp(Kind, TEXT("horse")) == 0 ? ERacingHallKind::Horse : FCString::Strcmp(Kind, TEXT("jockey")) == 0 ? ERacingHallKind::Jockey : ERacingHallKind::Stable;
        const FRacingRecordsPage List = F.Page(ERacingHallObject::Cabinet, 0, K);
        if (!TestTrue(TEXT("A list"), List.Lines.Num() > 0)) continue;
        const FRacingRecordsPage Card = F.Page(ERacingHallObject::Cabinet, 0, K, 0, List.Lines[0].Subject);
        TestTrue(FString::Printf(TEXT("A %s's card: %s"), Kind, *Card.Error), Card.Error.IsEmpty() && Card.Title == List.Lines[0].Left);
        TestTrue(TEXT("its numbers"), Card.Lines.ContainsByPredicate([](const FRacingRecordsLine& L) { return L.Left == TEXT("Victoires"); }));
    }
    TestFalse(TEXT("No such card"), F.Page(ERacingHallObject::Cabinet, 0, ERacingHallKind::Horse, 0, TEXT("horse:nobody")).Error.IsEmpty());
    // Refusals.
    FRacingRecordsQuery Bad;
    Bad.Object = 99;
    TestFalse(TEXT("An unknown object"), RacingRecords::Refusal(Bad).IsEmpty());
    Bad.Object = uint8(ERacingHallObject::Record);
    Bad.Index = 7;
    TestFalse(TEXT("A panel too far"), RacingRecords::Refusal(Bad).IsEmpty());
    Bad.Index = 0;
    Bad.Search = FString::ChrN(33, TEXT('a'));
    TestFalse(TEXT("An oversized search"), RacingRecords::Refusal(Bad).IsEmpty());
    Bad.Search.Reset();
    Bad.Page = -1;
    TestFalse(TEXT("A negative page"), RacingRecords::Refusal(Bad).IsEmpty());
    // Formats.
    TestEqual(TEXT("A sprint time"), RacingRecords::Time(52314000), FString(TEXT("52.31 s")));
    TestEqual(TEXT("A long time"), RacingRecords::Time(72345000), FString(TEXT("1:12.35")));
    TestEqual(TEXT("A date"), RacingRecords::Date(HRClock::DaysPerSeason + 4), FString(TEXT("saison 2, jour 5")));
    // The boards' texts.
    FRacingHallBoards B;
    RacingRecords::BuildBoards(F.World, F.Ledger, HRClock::DayStart(F.World.T) + 1., B);
    TestEqual(TEXT("A text per panel"), B.Records.Num(), RacingRecords::Panels().Num());
    TestEqual(TEXT("and per honour"), B.Honours.Num(), int32(ERacingHonour::Count));
    TestTrue(TEXT("The standings"), B.Standings.StartsWith(TEXT("CLASSEMENT")));
    TestTrue(TEXT("Today's results"), B.Results.StartsWith(TEXT("RÉSULTATS DU JOUR")));
    // No schedule or countdown in the town hall (only the hippodrome, the Salon's windows and the TVs show race timing).
    TestFalse(TEXT("No next races on the board"), B.Results.Contains(TEXT("PROCHAIN")) || B.Results.Contains(TEXT("DANS ")));
    for (const FRacingRecordsLine& Line : Board.Lines)
        TestFalse(TEXT("No countdown on the board's page"), Line.Right.StartsWith(TEXT("dans ")) || Line.Left.Contains(TEXT("Prochaine")));
    auto Latin1 = [](const FString& T) { for (const TCHAR C : T) if (C > 0xFF && C != 0x00B7) return false; return true; };
    for (const FString& T : B.Honours) TestTrue(TEXT("World text is Latin-1"), Latin1(T));
    for (const FString& T : B.Records) TestTrue(TEXT("World text is Latin-1"), Latin1(T));
    const FRacingHallBoards Received = RacingRecordsTest::OverTheWire(B);
    TestTrue(TEXT("The boards cross the wire"), FRacingHallBoards::StaticStruct()->CompareScriptStruct(&B, &Received, PPF_None));
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingRecordsArchiveTest, "Yorimichi.Racing.RecordsArchive",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingRecordsArchiveTest::RunTest(const FString&)
{
    using namespace RacingRecordsTest;
    FFixture F;
    // Old enough that a retirement two in-game years ago is a day of this world.
    F.Make(2);
    while (F.World.T < HRClock::ArchiveDays + 12) F.Day();
    // Retire some horses long enough ago that the rules archive them at the next day's start, and some riders.
    TArray<FString> Ids;
    F.World.Horses.GetKeys(Ids);
    Ids.Sort();
    const int32 Before = F.Page(ERacingHallObject::Archive, 0, ERacingHallKind::Horse).Total;
    int32 Archived = 0;
    FString Newest;
    for (int32 I = 0; I < Ids.Num() && Archived < 11; ++I)
    {
        FHRHorse& H = F.World.Horses[Ids[I]];
        if (H.IsRetired() || H.Placement == TEXT("archive") || H.Placement == TEXT("offer")) continue;
        HRRules::Retire(H, F.World.T - HRClock::ArchiveDays - Archived);
        HRRules::AdvanceHorse(H, F.World.T);
        if (!TestEqual(TEXT("The rules archive it"), H.Placement, FString(TEXT("archive")))) continue;
        if (!Archived) Newest = TEXT("horse:") + H.Id;
        ++Archived;
    }
    TArray<FString> RiderIds;
    F.World.Riders.GetKeys(RiderIds);
    RiderIds.Sort();
    F.World.Riders[RiderIds[0]].RetiredT = F.World.T - HRClock::ArchiveDays;
    F.World.Riders[RiderIds[1]].RetiredT = F.World.T - 1;
    const FRacingRecordsPage Horses = F.Page(ERacingHallObject::Archive, 0, ERacingHallKind::Horse);
    TestTrue(TEXT("Archived horses counted"), Before >= 0);
    if (!TestEqual(TEXT("Eleven horses archived"), Archived, 11)) return false;
    TestEqual(TEXT("Every archived horse has its register"), Horses.Total, Before + Archived);
    const int32 Total = Before + Archived;
    TestEqual(TEXT("Pages of eight"), Horses.Pages, FMath::DivideAndRoundUp(Total, RacingRecords::PageLines));
    TestEqual(TEXT("the first full"), Horses.Lines.Num(), RacingRecords::PageLines);
    TestEqual(TEXT("the second the rest"), F.Page(ERacingHallObject::Archive, 0, ERacingHallKind::Horse, 1).Lines.Num(), FMath::Min(RacingRecords::PageLines, Total - RacingRecords::PageLines));
    // Newest first: the horse retired last went to the archives last.
    if (!TestTrue(TEXT("Registers"), Horses.Lines.Num() > 0)) return false;
    TestTrue(TEXT("The newest registers first (archived today)"), Horses.Lines[0].Right.Contains(RacingRecords::Date(F.World.T)));
    TestTrue(TEXT("ours among them"), Horses.Lines.ContainsByPredicate([&Newest](const FRacingRecordsLine& L) { return L.Subject == Newest; }) ||
        F.Page(ERacingHallObject::Archive, 0, ERacingHallKind::Horse, 1).Lines.ContainsByPredicate([&Newest](const FRacingRecordsLine& L) { return L.Subject == Newest; }));
    const FRacingRecordsPage ByName = F.Page(ERacingHallObject::Archive, 0, ERacingHallKind::Horse, 0, FString(), 1);
    for (int32 I = 1; I < ByName.Lines.Num(); ++I) TestTrue(TEXT("or by name"), ByName.Lines[I - 1].Left <= ByName.Lines[I].Left);
    // The cabinet no longer has their cards; the archives do, and the honour boards still count them.
    const FRacingRecordsPage Cabinet = F.Page(ERacingHallObject::Cabinet, 0, ERacingHallKind::Horse, 0, FString(), 0, F.World.Horses[Newest.Mid(6)].Name);
    TestFalse(TEXT("Not in the cabinet"), Cabinet.Lines.ContainsByPredicate([&Newest](const FRacingRecordsLine& L) { return L.Subject == Newest; }));
    TestTrue(TEXT("Its card from the archives"), F.Page(ERacingHallObject::Archive, 0, ERacingHallKind::Horse, 0, Newest).Error.IsEmpty());
    const FRacingRecordsPage Jockeys = F.Page(ERacingHallObject::Archive, 0, ERacingHallKind::Jockey);
    auto Has = [&Jockeys](const FString& Id) { return Jockeys.Lines.ContainsByPredicate([&Id](const FRacingRecordsLine& L) { return L.Subject == TEXT("jockey:") + Id; }); };
    TestTrue(TEXT("The rider retired two years ago is archived"), Has(RiderIds[0]));
    TestFalse(TEXT("not the one retired yesterday"), Has(RiderIds[1]));
    TestEqual(TEXT("Stables are never archived"), F.Page(ERacingHallObject::Archive, 0, ERacingHallKind::Stable).Total, 0);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingRecordsRequestTest, "Yorimichi.Racing.RecordsRequest",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingRecordsRequestTest::RunTest(const FString&)
{
    using namespace RacingRecordsTest;
    {
        URacingRecordsDesk::StaticClass()->SetUpRuntimeReplicationData();
        TArray<FLifetimeProperty> Props;
        GetDefault<URacingRecordsDesk>()->GetLifetimeReplicatedProps(Props);
        int32 OwnerOnly = 0;
        for (const FName Name : {FName(TEXT("Page")), FName(TEXT("Boards"))})
        {
            const FProperty* Property = URacingRecordsDesk::StaticClass()->FindPropertyByName(Name);
            if (!TestNotNull(TEXT("A replicated property"), Property)) return false;
            for (const FLifetimeProperty& P : Props)
                if (P.RepIndex == Property->RepIndex) OwnerOnly += P.Condition == COND_OwnerOnly ? 1 : 0;
        }
        TestEqual(TEXT("A reader's page and the hall's texts replicate to their owner only"), OwnerOnly, 2);
    }
    const FString Path = TempSave();
    ARacingService* Service = NewObject<ARacingService>(GetTransientPackage());
    if (!TestTrue(TEXT("A world"), Service->OpenWorld(Path, TEXT("records-request-test")))) return false;
    Service->AdvanceClock(3. * HRClock::DaySeconds);
    TestTrue(TEXT("The host's clock notes the races"), Service->GetLedger().Riders.Num() > 0 && Service->GetLedger().Records.Num() > 0);
    URacingRecordsDesk* OnHost = NewObject<URacingRecordsDesk>(GetTransientPackage());
    URacingRecordsDesk* OnClient = NewObject<URacingRecordsDesk>(GetTransientPackage());
    auto Round = [&](const FRacingRecordsQuery& Q)
    {
        OnHost->HostHandle(OverTheWire(Q), Service);
        OnClient->ApplyReplicatedPage(OverTheWire(OnHost->GetPage()));
        return OnClient->GetPage();
    };
    FRacingRecordsQuery Q;
    Q.Seq = 1;
    Q.Object = uint8(ERacingHallObject::Honour);
    Q.Index = uint8(ERacingHonour::Wins);
    const FRacingRecordsPage Honour = Round(Q);
    TestTrue(TEXT("The client reads the honour board"), Honour.Seq == 1u && Honour.Error.IsEmpty() && Honour.Lines.Num() > 0);
    TestTrue(TEXT("The page survives the wire"), FRacingRecordsPage::StaticStruct()->CompareScriptStruct(&Honour, &OnHost->GetPage(), PPF_None));
    if (!TestTrue(TEXT("Someone on it"), Honour.Lines.Num() > 0)) return false;
    Q.Seq = 2;
    Q.Subject = Honour.Lines[0].Subject;
    const FRacingRecordsPage Card = Round(Q);
    TestTrue(TEXT("and the card of its first"), Card.Seq == 2u && Card.Error.IsEmpty() && Card.Kicker.Contains(TEXT("FICHE")));
    Q.Seq = 3;
    Q.Object = 200;
    TestTrue(TEXT("A bad query is refused before any work"), Round(Q).Error.Contains(TEXT("valable")));
    Q.Seq = 4;
    Q.Object = uint8(ERacingHallObject::Cabinet);
    Q.Subject = FString::ChrN(HRSave::MaxIdChars + 20, TEXT('x'));
    TestTrue(TEXT("An oversized subject too"), Round(Q).Error.Contains(TEXT("valable")));
    TestTrue(TEXT("At most ten pages a second"), URacingRecordsDesk::MinAskGap >= .1);
    URacingRecordsDesk* Closed = NewObject<URacingRecordsDesk>(GetTransientPackage());
    Q.Seq = 5;
    Q.Subject.Reset();
    Closed->HostHandle(Q, nullptr);
    TestTrue(TEXT("Without a world the hall is closed"), Closed->GetPage().Error.Contains(TEXT("fermée")));
    // The ledger is saved beside the world and read back by the next session; another world's is set aside.
    TestTrue(TEXT("Saved"), Service->SaveNow());
    TestTrue(TEXT("records.json beside world.json"), IFileManager::Get().FileExists(*ARacingService::LedgerPath(Path)));
    const FString Saved = Service->GetLedger().ToJson();
    ARacingService* Second = NewObject<ARacingService>(GetTransientPackage());
    if (TestTrue(TEXT("The world again"), Second->OpenWorld(Path, TEXT("records-request-test"))))
    {
        TestEqual(TEXT("The same records"), Second->GetLedger().Records.Num(), Service->GetLedger().Records.Num());
        TestEqual(TEXT("The same riders"), Second->GetLedger().Riders.Num(), Service->GetLedger().Riders.Num());
    }
    FString Text = Saved.Replace(TEXT("records-request-test"), TEXT("another-world"));
    FFileHelper::SaveStringToFile(Text, *ARacingService::LedgerPath(Path));
    ARacingService* Third = NewObject<ARacingService>(GetTransientPackage());
    if (TestTrue(TEXT("The world once more"), Third->OpenWorld(Path, TEXT("records-request-test"))))
        TestTrue(TEXT("Another world's ledger is not this one's"), Third->GetLedger().Records.Num() <= 6 && Third->GetLedger().Seed == Third->GetWorldState().Seed);
    {
        TArray<FString> Aside;
        IFileManager::Get().FindFiles(Aside, *(FPaths::GetPath(Path) / TEXT("records.json.unreadable-*")), true, false);
        TestEqual(TEXT("and it is kept aside, not written over"), Aside.Num(), 1);
    }
    IFileManager::Get().DeleteDirectory(*FPaths::GetPath(Path), false, true);
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRacingRecordsPlacesTest, "Yorimichi.Racing.RecordsPlaces",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FRacingRecordsPlacesTest::RunTest(const FString&)
{
    // runtime.json's racing_places.records_hall as world/regions/belmonte/build.py derives it from the Palazzo Comunale's
    // committed placement (this text is its current output).
    const FString Places =
        TEXT("{\"racing_places\":{\"records_hall\":{\"centre_cm\":[0.0,-2690.0,263.0],\"floor_cm\":263.0,\"objects\":[{\"object\":\"board\",\"index\":0,\"at_cm\":[0.0,-2896.0,743.0],\"yaw\":90.0,\"size_cm\":[600.0,165.0]},")
        TEXT("{\"object\":\"record\",\"index\":0,\"at_cm\":[-785.0,-2896.0,428.0],\"yaw\":90.0,\"size_cm\":[124.0,100.0]},")
        TEXT("{\"object\":\"record\",\"index\":1,\"at_cm\":[-650.0,-2896.0,428.0],\"yaw\":90.0,\"size_cm\":[124.0,100.0]},")
        TEXT("{\"object\":\"record\",\"index\":2,\"at_cm\":[-290.0,-2896.0,428.0],\"yaw\":90.0,\"size_cm\":[124.0,100.0]},")
        TEXT("{\"object\":\"record\",\"index\":3,\"at_cm\":[-155.0,-2896.0,428.0],\"yaw\":90.0,\"size_cm\":[124.0,100.0]},")
        TEXT("{\"object\":\"record\",\"index\":4,\"at_cm\":[155.0,-2896.0,428.0],\"yaw\":90.0,\"size_cm\":[124.0,100.0]},")
        TEXT("{\"object\":\"record\",\"index\":5,\"at_cm\":[290.0,-2896.0,428.0],\"yaw\":90.0,\"size_cm\":[124.0,100.0]},")
        TEXT("{\"object\":\"record\",\"index\":6,\"at_cm\":[650.0,-2896.0,428.0],\"yaw\":90.0,\"size_cm\":[124.0,100.0]},")
        TEXT("{\"object\":\"plaque\",\"index\":0,\"at_cm\":[785.0,-2896.0,428.0],\"yaw\":90.0,\"size_cm\":[124.0,100.0]},")
        TEXT("{\"object\":\"honour\",\"index\":0,\"at_cm\":[-1236.0,-2536.5,453.0],\"yaw\":0.0,\"size_cm\":[113.0,210.0]},")
        TEXT("{\"object\":\"honour\",\"index\":1,\"at_cm\":[-1236.0,-2660.0,453.0],\"yaw\":0.0,\"size_cm\":[113.0,210.0]},")
        TEXT("{\"object\":\"honour\",\"index\":2,\"at_cm\":[-1236.0,-2783.5,453.0],\"yaw\":0.0,\"size_cm\":[113.0,210.0]},")
        TEXT("{\"object\":\"honour\",\"index\":3,\"at_cm\":[1236.0,-2755.0,453.0],\"yaw\":180.0,\"size_cm\":[170.0,210.0]},")
        TEXT("{\"object\":\"honour\",\"index\":4,\"at_cm\":[1236.0,-2575.0,453.0],\"yaw\":180.0,\"size_cm\":[170.0,210.0]},")
        TEXT("{\"object\":\"cabinet\",\"index\":0,\"at_cm\":[1132.0,-2848.0,328.0],\"yaw\":90.0,\"size_cm\":[110.0,130.0]},")
        TEXT("{\"object\":\"archive\",\"index\":0,\"at_cm\":[-1132.0,-2838.0,333.0],\"yaw\":90.0,\"size_cm\":[120.0,85.0]}]}}}");
    const FVector Origin(100000., -200000., 3000.);
    TArray<RacingRecords::FAnchor> A;
    FVector Centre;
    if (!TestTrue(TEXT("The hall's places parse"), RacingRecords::HallAnchors(RacingPlaces::Parse(Places), Origin, A, Centre))) return false;
    TArray<RacingRecords::FAnchor> None;
    FVector Nowhere;
    TestFalse(TEXT("No racing_places, no hall"), RacingRecords::HallAnchors(RacingPlaces::Parse(TEXT("{}")), Origin, None, Nowhere) || None.Num());
    TestFalse(TEXT("An object missing"), RacingRecords::HallAnchors(RacingPlaces::Parse(Places.Replace(TEXT("\"cabinet\""), TEXT("\"archive\""))), Origin, None, Nowhere));
    int32 Count[int32(ERacingHallObject::Count)] = {};
    for (const RacingRecords::FAnchor& X : A) Count[int32(X.Object)]++;
    TestEqual(TEXT("One split-flap board"), Count[int32(ERacingHallObject::Board)], 1);
    TestEqual(TEXT("Seven record panels"), Count[int32(ERacingHallObject::Record)], 7);
    TestEqual(TEXT("Five honour boards"), Count[int32(ERacingHallObject::Honour)], int32(ERacingHonour::Count));
    TestTrue(TEXT("The cabinet, the archives and the plaque"), Count[int32(ERacingHallObject::Cabinet)] == 1 && Count[int32(ERacingHallObject::Archive)] == 1 &&
        Count[int32(ERacingHallObject::Plaque)] == 1);
    // Inside the Palazzo Comunale's loggia: x within +-12.4 m, between its back wall and its arcade, on its floor.
    TestTrue(TEXT("The hall's centre in front of the town hall's sign"), FVector::Dist2D(Centre, Origin + FVector(-460., -2385., 0.)) < 600.);
    for (const RacingRecords::FAnchor& X : A)
    {
        const FVector L = X.At.GetLocation() - Origin;
        TestTrue(TEXT("Within the loggia"), FMath::Abs(L.X) <= 1240. && L.Y >= -2900. && L.Y <= -2480.);
        TestTrue(TEXT("Its face in the loggia"), FMath::Abs(L.X + X.At.GetRotation().GetForwardVector().X * 10.) < 1240. &&
            L.Y + X.At.GetRotation().GetForwardVector().Y * 10. > -2900.);
        const double Above = X.At.GetLocation().Z - X.Floor;
        TestTrue(TEXT("Above the floor, under the beams"), Above - X.Size.Y * .5 >= -1. && Above + X.Size.Y * .5 <= 580.);
        TestTrue(TEXT("The floor is the loggia's"), FMath::IsNearlyEqual(X.Floor, Origin.Z + 263.));
    }
    // On the back wall, the boards clear the doors (x 0, +-9.4 m, 1.7 m wide) and the windows (+-4.7 m, 1.1 m wide, their shutters 60 cm more).
    for (const RacingRecords::FAnchor& X : A)
    {
        if (X.Object != ERacingHallObject::Record && X.Object != ERacingHallObject::Plaque) continue;
        const double Lx = X.At.GetLocation().X - Origin.X;
        for (const TPair<double, double>& Opening : {TPair<double, double>(0., 85.), TPair<double, double>(940., 85.), TPair<double, double>(-940., 85.),
                 TPair<double, double>(470., 115.), TPair<double, double>(-470., 115.)})
            TestTrue(TEXT("Clear of the doors and windows (and the windows' open shutters)"), FMath::Abs(Lx - Opening.Key) >= Opening.Value + X.Size.X * .5);
        for (const RacingRecords::FAnchor& Y : A)
            if (&Y != &X && (Y.Object == ERacingHallObject::Record || Y.Object == ERacingHallObject::Plaque))
                TestTrue(TEXT("No two overlap"), FMath::Abs(Lx - (Y.At.GetLocation().X - Origin.X)) >= (X.Size.X + Y.Size.X) * .5);
    }
    // Reach: before a panel, not behind it, not far off, not from the floor above.
    const int32 Panel = A.IndexOfByPredicate([](const RacingRecords::FAnchor& X) { return X.Object == ERacingHallObject::Record && X.Index == 2; });
    const FVector Front = A[Panel].At.TransformPosition(FVector(130., 0., 0.));
    const FVector Stand(Front.X, Front.Y, A[Panel].Floor + 95.);
    TestEqual(TEXT("A reader before a panel reaches it"), RacingRecords::AnchorInReach(A, Stand), Panel);
    TestEqual(TEXT("not from far off"), RacingRecords::AnchorInReach(A, A[Panel].At.TransformPosition(FVector(900., 0., 0.))), int32(INDEX_NONE));
    TestEqual(TEXT("nor from the piano nobile"), RacingRecords::AnchorInReach(A, Stand + FVector(0., 0., 600.)), int32(INDEX_NONE));
    const int32 Board = A.IndexOfByPredicate([](const RacingRecords::FAnchor& X) { return X.Object == ERacingHallObject::Board; });
    const FVector Under = A[Board].At.TransformPosition(FVector(300., 0., 0.));
    TestEqual(TEXT("The high board is read from the middle of the loggia"), RacingRecords::AnchorInReach(A, FVector(Under.X, Under.Y, A[Board].Floor + 95.)), Board);
    TestEqual(TEXT("The first query of a panel"), RacingRecords::FirstQuery(A[Panel]).Index, uint8(2));
    // In the west corner the last honour board and the archive table are both within reach: the reader reads the one
    // they face.
    const int32 Honour = A.IndexOfByPredicate([](const RacingRecords::FAnchor& X) { return X.Object == ERacingHallObject::Honour && X.Index == 2; });
    const int32 Archive = A.IndexOfByPredicate([](const RacingRecords::FAnchor& X) { return X.Object == ERacingHallObject::Archive; });
    const FVector Corner = A[Honour].At.TransformPosition(FVector(140., 0., 0.));
    const FVector At(Corner.X, Corner.Y, A[Honour].Floor + 95.);
    TestEqual(TEXT("Facing the honour board"), RacingRecords::AnchorInReach(A, At, FVector(-1., 0., 0.)), Honour);
    TestEqual(TEXT("Facing the archive table"), RacingRecords::AnchorInReach(A, At, FVector(0., -1., 0.)), Archive);
    TestTrue(TEXT("The honour boards read left to right"), A[Honour].At.GetLocation().Y < A[Honour - 2].At.GetLocation().Y);
    return true;
}
#endif
