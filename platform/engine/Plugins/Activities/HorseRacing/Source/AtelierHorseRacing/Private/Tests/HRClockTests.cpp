#include "HRTestUtil.h"
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

using HRClock::EHRRacePhase;

// The continuous schedule: two-hour race days, twelve a season (eight ordinary, four Grand Prix), races spread over the
// day, and what the clock says at any second.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FHRScheduleTest, "Atelier.HorseRacing.Clock.Schedule", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FHRScheduleTest::RunTest(const FString&)
{
	TestEqual(TEXT("a race day lasts two hours"), HRClock::DaySeconds, 7200.0);
	TestEqual(TEXT("a season (one in-game year) lasts 24 real hours"), HRClock::DaysPerSeason * HRClock::DaySeconds, 24.0 * 3600.0);
	TestEqual(TEXT("one horse year is one real week"), HRClock::LifeYear * HRClock::DaySeconds, 7.0 * 24.0 * 3600.0);
	TestEqual(TEXT("archiving waits two in-game years, 48 real hours"), HRClock::ArchiveDays * HRClock::DaySeconds, 48.0 * 3600.0);
	TestEqual(TEXT("second 0 is day 0"), HRClock::DayAt(0), 0);
	TestEqual(TEXT("the last second of day 0"), HRClock::DayAt(7199.99), 0);
	TestEqual(TEXT("day 1 starts at 7200 s"), HRClock::DayAt(7200), 1);
	TestEqual(TEXT("day 1 start"), HRClock::DayStart(1), 7200.0);
	TestEqual(TEXT("day 12 opens season 1"), HRClock::SeasonOf(12), 1);
	TestEqual(TEXT("day 12 is the season's first day"), HRClock::DayOfSeason(12), 0);

	int32 Ordinary = 0, GrandPrix = 0;
	for (int32 T = 24; T < 36; ++T) (HRClock::IsGrandPrixDay(T) ? GrandPrix : Ordinary)++;
	TestEqual(TEXT("eight ordinary race days a season"), Ordinary, 8);
	TestEqual(TEXT("four Grand Prix days a season"), GrandPrix, HRClock::GrandPrixPerSeason);

	for (const int32 Count : {HRClock::RaceSlots, 9, 14})
	{
		double Last = -1;
		for (int32 Slot = 0; Slot < Count; ++Slot)
		{
			const double Start = HRClock::SlotStart(40, Slot, Count);
			TestTrue(TEXT("slots in order"), Start > Last);
			Last = Start;
		}
		TestEqual(TEXT("the first race starts ten minutes into the day"), HRClock::SlotStart(40, 0, Count), HRClock::DayStart(40) + 600.0);
		TestTrue(FString::Printf(TEXT("%d races fit in the day"), Count), Last + HRClock::RaceSeconds <= HRClock::DayStart(41));
	}
	TestEqual(TEXT("a Grand Prix keeps two slots for its barrages and final"), HRClock::SlotCount(5, true), 7);
	TestEqual(TEXT("at least six slots"), HRClock::SlotCount(2, false), HRClock::RaceSlots);

	// What the clock says on a Grand Prix day.
	const int32 Day = 26;
	TestTrue(TEXT("day 26 is a Grand Prix"), HRClock::IsGrandPrixDay(Day));
	HRClock::FSlot At = HRClock::ScheduleAt(HRClock::DayStart(Day) + 10);
	TestTrue(TEXT("before the first race"), At.T == Day && At.Slot == 0 && At.Phase == EHRRacePhase::Upcoming && At.bGrandPrix);
	TestEqual(TEXT("season and day"), At.Season * 100 + At.DayOfSeason, 2 * 100 + 2);
	At = HRClock::ScheduleAt(HRClock::SlotStart(Day, 0) + 10);
	TestTrue(TEXT("the first race is running"), At.Slot == 0 && At.Phase == EHRRacePhase::Running && At.Start == HRClock::SlotStart(Day, 0));
	At = HRClock::ScheduleAt(HRClock::SlotStart(Day, 0) + HRClock::RaceSeconds + 1);
	TestTrue(TEXT("then finished"), At.Slot == 0 && At.Phase == EHRRacePhase::Finished && At.End == At.Start + HRClock::RaceSeconds);
	At = HRClock::ScheduleAt(HRClock::SlotStart(Day, 3) + 1);
	TestTrue(TEXT("the fourth race is running"), At.Slot == 3 && At.Phase == EHRRacePhase::Running);
	At = HRClock::ScheduleAt(HRClock::DayStart(Day + 1) - 1);
	TestTrue(TEXT("the day ends with its last race finished"), At.T == Day && At.Slot == HRClock::RaceSlots - 1 && At.Phase == EHRRacePhase::Finished);
	At = HRClock::ScheduleAt(HRClock::DayStart(Day + 1));
	TestTrue(TEXT("the next day starts upcoming"), At.T == Day + 1 && At.Slot == 0 && At.Phase == EHRRacePhase::Upcoming && !At.bGrandPrix);
	return true;
}

// The world follows the clock: races run when their slot starts, days close by themselves, and catching up hours at once
// gives the same world as stepping through them.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FHRAdvanceToTest, "Atelier.HorseRacing.Clock.AdvanceTo", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FHRAdvanceToTest::RunTest(const FString&)
{
	FHRWorldState W = HRRules::CreateWorld(TEXT("clock-1"));
	constexpr int64 Now = 1'800'000'000;
	HRRules::StartClock(W, Now);
	TestEqual(TEXT("the clock anchor"), HRRules::WorldSeconds(W, (double)Now), HRClock::DayStart(W.T));
	TestEqual(TEXT("an hour later"), HRRules::WorldSeconds(W, (double)Now + 3600), HRClock::DayStart(W.T) + 3600);
	const int32 T0 = W.T;

	FHRWorldState A = W;
	HRRules::AdvanceTo(A, HRClock::DayStart(T0) + 599);
	TestTrue(TEXT("no race before the first slot"), !A.Meeting.Races[0].IsRun());
	const FString First = A.Meeting.Races[0].Key;
	const double Start = HRRules::RaceStartSeconds(A, First);
	TestEqual(TEXT("the first race's start"), Start, HRClock::SlotStart(T0, 0, HRRules::DaySlotCount(A)));
	TestTrue(TEXT("upcoming"), HRRules::RacePhase(A, First, Start - 1) == EHRRacePhase::Upcoming);
	HRRules::AdvanceTo(A, Start);
	TestTrue(TEXT("the first race is run at its start"), A.Meeting.Races[0].IsRun());
	if (A.Meeting.Races.Num() > 1) TestFalse(TEXT("the second one is not yet"), A.Meeting.Races[1].IsRun());
	TestTrue(TEXT("running"), HRRules::RacePhase(A, First, Start + 1) == EHRRacePhase::Running);
	TestTrue(TEXT("finished"), HRRules::RacePhase(A, First, Start + HRClock::RaceSeconds) == EHRRacePhase::Finished);
	TestEqual(TEXT("still the same day"), A.T, T0);

	// Three days at once, step by step every ten minutes, or day by day: the same world.
	const double Target = HRClock::DayStart(T0 + 3) + 1;
	FHRWorldState B = W, C = W, D = W;
	HRRules::AdvanceTo(B, Target);
	for (double S = HRClock::DayStart(T0); S <= Target; S += 600) HRRules::AdvanceTo(C, S);
	HRRules::AdvanceTo(C, Target);
	for (int32 K = 0; K < 3; ++K) HRRules::AdvanceDay(D);
	HRRules::AdvanceTo(D, Target);
	TestEqual(TEXT("three days later"), B.T, T0 + 3);
	TestTrue(TEXT("catching up equals stepping"), HRTest::ToJson(B) == HRTest::ToJson(C));
	TestTrue(TEXT("catching up equals closing day by day"), HRTest::ToJson(B) == HRTest::ToJson(D));
	const FString Once = HRTest::ToJson(B);
	HRRules::AdvanceTo(B, Target);
	HRRules::AdvanceTo(B, Target - 3600);
	TestTrue(TEXT("idempotent, and the clock never runs back"), HRTest::ToJson(B) == Once);

	// A Grand Prix day: the final appears once the heats are run and runs in the last slot.
	FHRWorldState G = W;
	int32 GpDay = G.T;
	while (!HRClock::IsGrandPrixDay(GpDay)) ++GpDay;
	HRRules::AdvanceTo(G, HRClock::DayStart(GpDay));
	const int32 Count = HRRules::DaySlotCount(G);
	HRRules::AdvanceTo(G, HRClock::SlotStart(GpDay, Count - 2, Count) - 1);
	TestTrue(TEXT("every heat is run"), !G.Meeting.Races.ContainsByPredicate([](const FHRRace& R) { return HRRules::IsHeatRound(R.Round) && R.Round != TEXT("barrage") && !R.IsRun(); }));
	const FHRRace* Final = HRRules::FindRace(G, TEXT("final:0"));
	if (TestNotNull(TEXT("the final is declared after the heats"), Final))
	{
		TestFalse(TEXT("but not run before its slot"), Final->IsRun());
		TestEqual(TEXT("in the last slot"), HRRules::RaceSlot(G, *Final), Count - 1);
		HRRules::AdvanceTo(G, HRClock::SlotStart(GpDay, Count - 1, Count));
		TestTrue(TEXT("run at its slot"), HRRules::FindRace(G, TEXT("final:0"))->IsRun());
	}
	return true;
}

// Horses age on the horse clock: a foal is an adult (ready to race) one real week after its birth, and its look grows up
// on the same clock; a career of six to nine horse years lasts six to nine weeks.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FHRAgeingTest, "Atelier.HorseRacing.Clock.Ageing", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FHRAgeingTest::RunTest(const FString&)
{
	FHRWorldState S = HRRules::CreateWorld(TEXT("ageing-1"));
	const FHRHorse* Mare = nullptr;
	const FHRHorse* Sire = nullptr;
	for (const TPair<FString, FHRHorse>& It : S.Horses)
	{
		if (It.Value.bMare && !Mare) Mare = &It.Value;
		if (!It.Value.bMare && !Sire) Sire = &It.Value;
	}
	if (!TestTrue(TEXT("parents"), Mare && Sire)) return false;
	HRRules::FGenerationOptions O;
	O.Id = TEXT("ageing:foal");
	O.Seed = TEXT("ageing-1:foal");
	O.OwnerId = Mare->OwnerId;
	O.T = S.T;
	O.Origin = TEXT("foal");
	O.Mother = Mare;
	O.Father = Sire;
	FHRHorse Foal = HRRules::GenerateHorse(O);
	TestEqual(TEXT("born today"), Foal.BirthT, S.T);
	TestEqual(TEXT("an adult one real week after its birth"), HRClock::DayStart(Foal.ReadyT) - HRClock::DayStart(Foal.BirthT), 7.0 * 24 * 3600);
	TestFalse(TEXT("not ready the day before"), HRRules::Runnable(Foal, Foal.ReadyT - 1));
	TestTrue(TEXT("ready on its first birthday"), HRRules::Runnable(Foal, Foal.ReadyT));
	TestEqual(TEXT("twelve horse months old after a week"), HRRules::HorseAgeMonths(Foal, Foal.ReadyT), 12);
	TestEqual(TEXT("one horse month is fourteen real hours"), HRClock::LifeMonth * HRClock::DaySeconds, 14.0 * 3600);
	const int32 CareerDays = Foal.ScheduledRetirementT - Foal.ReadyT;
	TestTrue(TEXT("a career of six to nine horse years (weeks)"), CareerDays % HRClock::LifeYear == 0 && CareerDays >= 6 * HRClock::LifeYear && CareerDays <= 9 * HRClock::LifeYear);
	TestEqual(TEXT("a newborn looks like a foal"), HRVisual::ResolvePhenotypeAt(Foal, Foal.BirthT).Juvenile, 1.0);
	TestTrue(TEXT("a yearling still grows"), HRVisual::ResolvePhenotypeAt(Foal, Foal.ReadyT).Juvenile > 0);
	TestEqual(TEXT("fully grown at two horse years (two weeks)"), HRVisual::ResolvePhenotypeAt(Foal, Foal.BirthT + 2 * HRClock::LifeYear).Juvenile, 0.0);
	TestEqual(TEXT("gestation: three horse months, 42 real hours"), HRRules::GestationDays * HRClock::DaySeconds, 42.0 * 3600);

	// In a running world, every foal born races only from its first horse birthday.
	for (int32 Day = 0; Day < 30; ++Day)
	{
		HRRules::AdvanceDay(S);
		for (const FHRRace& R : S.Meeting.Races)
			for (const FHRRunner& E : R.Entries)
				TestTrue(TEXT("runners are at least one horse year old"), HRRules::HorseAgeMonths(S.Horses[E.HorseId], S.T) >= 12);
	}
	// Riders age on the same clock: a rider's career curve moves once per rider month, never in between.
	FHRWorldState R = S;
	TMap<FString, TArray<int32>> Skills;
	for (const TPair<FString, FHRRider>& It : R.Riders) Skills.Add(It.Key, It.Value.Skill);
	int32 Steps = 0, Quiet = 0;
	for (int32 Day = 0; Day < 2 * HRClock::LifeMonth; ++Day)
	{
		const int32 T = R.T;
		HRRules::AdvanceDay(R);
		for (const TPair<FString, FHRRider>& It : R.Riders)
		{
			const TArray<int32>* Before = Skills.Find(It.Key);
			if (!Before || It.Value.IsRetired()) continue;
			const bool bMonth = HRRules::RiderAgeMonths(It.Value, T + 1) > HRRules::RiderAgeMonths(It.Value, T);
			if (*Before != It.Value.Skill) TestTrue(TEXT("skills move only when a rider month passes"), bMonth);
			(bMonth ? Steps : Quiet)++;
		}
		Skills.Reset();
		for (const TPair<FString, FHRRider>& It : R.Riders) Skills.Add(It.Key, It.Value.Skill);
	}
	TestTrue(TEXT("riders step once per rider month (seven race days)"), Steps > 0 && Quiet > Steps * 4);
	return true;
}

// A retired horse's history goes to the archives two in-game years (48 real hours) after its retirement.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FHRArchiveTest, "Atelier.HorseRacing.Clock.Archive", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FHRArchiveTest::RunTest(const FString&)
{
	FHRWorldState S = HRRules::CreateWorld(TEXT("archive-1"));
	FHRHorse H = S.Horses.CreateConstIterator()->Value;
	const int32 T0 = S.T;
	HRRules::Retire(H, T0);
	TestTrue(TEXT("retired"), H.IsRetired() && H.Placement == TEXT("retired"));
	HRRules::AdvanceHorse(H, T0 + HRClock::ArchiveDays - 1);
	TestEqual(TEXT("not archived 46 hours later"), H.Placement, FString(TEXT("retired")));
	HRRules::AdvanceHorse(H, T0 + HRClock::ArchiveDays);
	TestEqual(TEXT("archived 48 hours later"), H.Placement, FString(TEXT("archive")));

	// In a running world: every retired horse reaches the archives exactly then, and leaves the stables' lists.
	int32 Archived = 0;
	for (int32 Day = 0; Day < 120; ++Day)
	{
		HRRules::AdvanceDay(S);
		for (const TPair<FString, FHRHorse>& It : S.Horses)
		{
			const FHRHorse& X = It.Value;
			if (!X.IsRetired()) continue;
			const bool bDue = S.T >= X.RetiredT + HRClock::ArchiveDays;
			TestEqual(X.Id + TEXT(" archived exactly 48 hours after retiring"), X.Placement == TEXT("archive"), bDue);
			if (X.Placement != TEXT("archive")) continue;
			Archived += X.RetiredT + HRClock::ArchiveDays == S.T ? 1 : 0;
			TestFalse(TEXT("archived horses leave the stable's list"), HRRules::StableHorses(S, X.OwnerId).Contains(&X));
			TestTrue(TEXT("but stay in the archive list"), HRRules::StableHorses(S, X.OwnerId, true).Contains(&X));
		}
	}
	AddInfo(FString::Printf(TEXT("%d horses archived in 120 race days"), Archived));
	TestTrue(TEXT("horses reach the archives"), Archived > 0);
	return true;
}

// The whole world round-trips through JSON: players, stables, horses, riders, bets and the clock anchor.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FHRSaveTest, "Atelier.HorseRacing.Save.RoundTrip", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FHRSaveTest::RunTest(const FString&)
{
	FHRWorldState S = HRRules::CreateWorld(TEXT("save-1"));
	HRRules::StartClock(S, 1'800'000'000);
	HRRules::AddPlayer(S, TEXT("p1"), TEXT("Ada")).Coins = 1000;
	HRRules::AddPlayer(S, TEXT("p2"), TEXT("Bo")).Coins = 1000;
	TestTrue(TEXT("p1 buys the stable for sale"), HRRules::BuyStable(S, TEXT("p1"), S.Stables[0].Id, true).IsEmpty());
	TestTrue(TEXT("p2 founds one"), HRRules::FoundStable(S, TEXT("p2"), TEXT("Blue Barn"), TEXT("3366cc")).IsEmpty());
	const FHRRace& R = S.Meeting.Races[0];
	TestTrue(TEXT("a bet"), HRRules::PlaceBet(S, TEXT("p2"), R.Key, R.Entries[0].HorseId, 5).IsEmpty());
	HRRules::AdvanceTo(S, HRClock::SlotStart(S.T, 1, HRRules::DaySlotCount(S)));

	const FString Json = HRSave::ToJson(S);
	FHRWorldState Loaded;
	TestTrue(TEXT("parses"), HRSave::FromJson(Json, Loaded));
	TestEqual(TEXT("lossless"), HRSave::ToJson(Loaded), Json);
	TestEqual(TEXT("players kept"), Loaded.Players.Num(), 2);
	TestEqual(TEXT("clock anchor kept"), Loaded.EpochUnix, S.EpochUnix);
	TestEqual(TEXT("the owner kept"), Loaded.Stables[0].OwnerPlayerId, FString(TEXT("p1")));
	const double Later = HRClock::DayStart(S.T + 2) + 2000;
	HRRules::AdvanceTo(S, Later);
	HRRules::AdvanceTo(Loaded, Later);
	TestEqual(TEXT("the reloaded world plays on identically"), HRSave::ToJson(Loaded), HRSave::ToJson(S));

	FHRWorldState Untouched = S;
	TestFalse(TEXT("not JSON"), HRSave::FromJson(TEXT("not json"), Untouched));
	FHRWorldState Other = S;
	Other.RulesVersion = TEXT("other-rules");
	TestFalse(TEXT("other rules refused"), HRSave::FromJson(HRSave::ToJson(Other), Untouched));
	TestEqual(TEXT("a refused load leaves the world as it was"), HRSave::ToJson(Untouched), HRSave::ToJson(S));
	AddInfo(FString::Printf(TEXT("save size %d characters"), Json.Len()));
	return true;
}

// Same seed, same world, same race result: a listen server and its clients compute the same outcomes.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FHRDeterminismTest, "Atelier.HorseRacing.Determinism", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FHRDeterminismTest::RunTest(const FString&)
{
	const FHRWorldState A = HRRules::CreateWorld(TEXT("same-seed"));
	const FHRWorldState B = HRRules::CreateWorld(TEXT("same-seed"));
	TestTrue(TEXT("same seed, same world"), HRTest::ToJson(A) == HRTest::ToJson(B));
	TestFalse(TEXT("another seed, another world"), HRTest::ToJson(A) == HRTest::ToJson(HRRules::CreateWorld(TEXT("other-seed"))));

	// The same race resolved on two machines (two copies of the state).
	FHRWorldState X = A, Y = B;
	FHRRace& RX = X.Meeting.Races[0];
	FHRRace& RY = Y.Meeting.Races[0];
	HRRules::ResolveRace(X, RX);
	HRRules::ResolveRace(Y, RY);
	TestTrue(TEXT("a race is run"), RX.Status == TEXT("run") && RX.Finishes.Num() >= 2);
	bool bSame = RX.Finishes.Num() == RY.Finishes.Num();
	for (int32 I = 0; bSame && I < RX.Finishes.Num(); ++I)
		bSame = RX.Finishes[I].HorseId == RY.Finishes[I].HorseId && RX.Finishes[I].TimeUs == RY.Finishes[I].TimeUs;
	TestTrue(TEXT("same seed, same race result to the microsecond"), bSame);
	TestTrue(TEXT("same incidents"), RX.Incidents.Num() == RY.Incidents.Num());

	// A different world seed redraws the day's form.
	FHRWorldState Z = A;
	Z.Seed = TEXT("another-day");
	FHRRace& RZ = Z.Meeting.Races[0];
	HRRules::ResolveRace(Z, RZ);
	bool bDiffers = false;
	for (int32 I = 0; I < RZ.Finishes.Num() && I < RX.Finishes.Num(); ++I) bDiffers |= RZ.Finishes[I].TimeUs != RX.Finishes[I].TimeUs;
	TestTrue(TEXT("another seed, other times"), bDiffers);

	// Two hosts following the same clock stay identical for days.
	FHRWorldState P = A, Q = B;
	const double Target = HRClock::DayStart(A.T + 2) + 4000;
	HRRules::AdvanceTo(P, Target);
	HRRules::AdvanceTo(Q, Target);
	TestTrue(TEXT("same clock, same world"), HRTest::ToJson(P) == HRTest::ToJson(Q));
	return true;
}

#endif
