#include "HRTestUtil.h"
#include "JsonObjectConverter.h"
#include "Misc/AutomationTest.h"
#include <limits>

#if WITH_DEV_AUTOMATION_TESTS

// Save admission (HRSave::FromJson) and the economy's invariants: settlement, refunds, balances, saturation and bounded
// catch-up.

namespace HRAdmissionTest
{
	/** The horse as the save writes it (one JSON object). */
	FString HorseJson(const FHRHorse& H)
	{
		FString Json;
		FJsonObjectConverter::UStructToJsonObjectString(H, Json, 0, 0, 0, nullptr, false);
		return Json;
	}

	/** Every stable, player and debt within 0..MaxCoins. */
	bool BalancesValid(const FHRWorldState& S, FString& Why)
	{
		for (const FHRStable& St : S.Stables)
			if (St.Coins < 0 || St.Debt < 0 || St.Coins > HRRules::MaxCoins)
			{
				Why = FString::Printf(TEXT("stable %s: coins %d, debt %d"), *St.Id, St.Coins, St.Debt);
				return false;
			}
		for (const TPair<FString, FHRPlayer>& It : S.Players)
			if (It.Value.Coins < 0 || It.Value.Coins > HRRules::MaxCoins)
			{
				Why = FString::Printf(TEXT("player %s: coins %d"), *It.Key, It.Value.Coins);
				return false;
			}
		return true;
	}

	/** The first race of today with a field, run or not. */
	const FHRRace* FieldRace(const FHRWorldState& S, bool bRun)
	{
		return S.Meeting.Races.FindByPredicate([bRun](const FHRRace& R)
		{
			return R.Entries.Num() >= 2 && (bRun ? R.Status == TEXT("run") && R.Finishes.Num() >= 2 : R.Status == TEXT("declared"));
		});
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FHRSaveAdmissionTest, "Atelier.HorseRacing.Save.Admission", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FHRSaveAdmissionTest::RunTest(const FString&)
{
	FHRWorldState S = HRRules::CreateWorld(TEXT("admission-1"));
	HRRules::AddPlayer(S, TEXT("p1"), TEXT("Ada"));
	HRRules::StartClock(S, 1800000000);
	const FHRRace* Race = HRAdmissionTest::FieldRace(S, false);
	if (!TestNotNull(TEXT("a race to bet on"), Race)) return false;
	TestTrue(TEXT("a ticket"), HRRules::PlaceBet(S, TEXT("p1"), Race->Key, Race->Entries[0].HorseId, 5).IsEmpty());
	const FString Good = HRSave::ToJson(S);
	TestEqual(TEXT("a world of these rules is admissible"), HRSave::Validate(S), FString());
	FHRWorldState Loaded;
	FString Error;
	TestTrue(TEXT("and loads: ") + Error, HRSave::FromJson(Good, Loaded, Error));

	// A refused load names the reason and leaves the destination as it was.
	FHRWorldState Untouched = S;
	const FString Before = HRSave::ToJson(Untouched);
	auto Refused = [&](const TCHAR* What, const FString& Json, const TCHAR* Expected)
	{
		FString Why;
		const bool bLoaded = HRSave::FromJson(Json, Untouched, Why);
		TestFalse(FString::Printf(TEXT("%s is refused"), What), bLoaded);
		TestTrue(FString::Printf(TEXT("%s: the reason (%s) mentions \"%s\""), What, *Why, Expected), Why.Contains(Expected));
		TestTrue(FString::Printf(TEXT("%s leaves the world untouched"), What), HRSave::ToJson(Untouched) == Before);
	};
	auto Mutated = [&S](TFunctionRef<void(FHRWorldState&)> Change)
	{
		FHRWorldState Copy = S;
		Change(Copy);
		return HRSave::ToJson(Copy);
	};
	FString HorseId, ParentlessId;
	for (const TPair<FString, FHRHorse>& It : S.Horses)
	{
		if (HorseId.IsEmpty()) HorseId = It.Key;
		if (ParentlessId.IsEmpty() && It.Value.Parents.IsEmpty()) ParentlessId = It.Key;
	}
	const FString RiderId = S.Riders.CreateConstIterator()->Key;

	// Versions and required fields.
	Refused(TEXT("not JSON"), TEXT("not json"), TEXT("JSON"));
	Refused(TEXT("another rules version"), Mutated([](FHRWorldState& W) { W.RulesVersion = TEXT("atelier-horse-racing-0"); }), TEXT("rules version"));
	Refused(TEXT("another schema version"), Mutated([](FHRWorldState& W) { W.SchemaVersion = 2; }), TEXT("schema version"));
	{
		FString NoHorses = Good;
		NoHorses.ReplaceInline(TEXT("\"horses\":"), TEXT("\"horsez\":"), ESearchCase::CaseSensitive);
		Refused(TEXT("a save without horses"), NoHorses, TEXT("horses"));
	}

	// Unique ids.
	{
		FString Twice = Good;
		const FString Field = FString::Printf(TEXT("\"horses\":{"));
		const int32 At = Twice.Find(Field, ESearchCase::CaseSensitive);
		if (TestTrue(TEXT("the save has a horse map"), At != INDEX_NONE))
		{
			Twice.InsertAt(At + Field.Len(), FString::Printf(TEXT("\"%s\":%s,"), *HorseId, *HRAdmissionTest::HorseJson(S.Horses[HorseId])));
			Refused(TEXT("a horse id twice"), Twice, TEXT("appears twice"));
		}
		FString SeedTwice = Good;
		SeedTwice.InsertAt(1, TEXT("\"seed\":\"other\","));
		Refused(TEXT("a field twice"), SeedTwice, TEXT("appears twice"));
	}
	Refused(TEXT("a stable twice"), Mutated([](FHRWorldState& W) { const FHRStable Copy = W.Stables[1]; W.Stables.Add(Copy); }), TEXT("appears twice"));
	Refused(TEXT("a horse under another id"), Mutated([&HorseId](FHRWorldState& W) { W.Horses[HorseId].Id = TEXT("someone-else"); }), TEXT("does not match"));
	Refused(TEXT("a race twice"), Mutated([](FHRWorldState& W) { const FHRRace Copy = W.Meeting.Races[0]; W.Meeting.Races.Add(Copy); }), TEXT("appears twice"));
	Refused(TEXT("a ticket twice"), Mutated([](FHRWorldState& W) { const FHRTicket Copy = W.Tickets[0]; W.Tickets.Add(Copy); }), TEXT("appears twice"));

	// Dangling references.
	Refused(TEXT("an unknown owner"), Mutated([&HorseId](FHRWorldState& W) { W.Horses[HorseId].OwnerId = TEXT("nobody"); }), TEXT("unknown owner"));
	Refused(TEXT("an unknown dam"), Mutated([&ParentlessId](FHRWorldState& W) { W.Horses[ParentlessId].Parents = {TEXT("ghost-a"), TEXT("ghost-b")}; }), TEXT("unknown parent"));
	Refused(TEXT("an unknown rider's stable"), Mutated([&RiderId](FHRWorldState& W) { W.Riders[RiderId].OwnerId = TEXT("nowhere"); }), TEXT("unknown stable"));
	Refused(TEXT("an unknown entrant"), Mutated([](FHRWorldState& W) { W.Meeting.Races[0].Entries[0].HorseId = TEXT("ghost"); }), TEXT("unknown entrant"));
	Refused(TEXT("an unknown race day rider"), Mutated([&HorseId](FHRWorldState& W) { W.Meeting.Riders.Add(HorseId, TEXT("ghost-rider")); }), TEXT("unknown horse or rider"));
	Refused(TEXT("a ticket of an unknown player"), Mutated([](FHRWorldState& W) { W.Tickets[0].PlayerId = TEXT("ghost"); }), TEXT("unknown player"));
	Refused(TEXT("a stable of an unknown player"), Mutated([](FHRWorldState& W) { W.Stables[0].OwnerPlayerId = TEXT("ghost"); }), TEXT("unknown player"));

	// Ranges.
	Refused(TEXT("a negative ability"), Mutated([&HorseId](FHRWorldState& W) { W.Horses[HorseId].Abilities[1] = -5; }), TEXT("abilities[1]"));
	Refused(TEXT("a huge ability"), Mutated([&HorseId](FHRWorldState& W) { W.Horses[HorseId].Abilities[0] = 1000000; }), TEXT("abilities[0]"));
	Refused(TEXT("a condition of 9"), Mutated([&HorseId](FHRWorldState& W) { W.Horses[HorseId].Condition = 9; }), TEXT("condition"));
	Refused(TEXT("an allele beyond the breeds"), Mutated([&HorseId](FHRWorldState& W) { W.Horses[HorseId].Genome.FindOrAdd(TEXT("breed")).A = 7; }), TEXT("gene breed"));
	Refused(TEXT("negative coins"), Mutated([](FHRWorldState& W) { W.Players[TEXT("p1")].Coins = -1; }), TEXT("coins"));
	Refused(TEXT("coins beyond the cap"), Mutated([](FHRWorldState& W) { W.Players[TEXT("p1")].Coins = HRRules::MaxCoins + 1; }), TEXT("coins"));
	Refused(TEXT("a stake beyond the limit"), Mutated([](FHRWorldState& W) { W.Tickets[0].Stake = 1000; }), TEXT("stake"));
	Refused(TEXT("a day in the future of the race day"), Mutated([](FHRWorldState& W) { W.Meeting.T = W.T + 1; }), TEXT("race day"));

	// Collection sizes.
	Refused(TEXT("a huge ability list"), Mutated([&HorseId](FHRWorldState& W) { W.Horses[HorseId].Abilities.Init(1, 5000); }), TEXT("abilities"));
	Refused(TEXT("three parents"), Mutated([&ParentlessId, &HorseId](FHRWorldState& W) { W.Horses[ParentlessId].Parents = {HorseId, HorseId, HorseId}; }), TEXT("two"));
	Refused(TEXT("too much news"), Mutated([](FHRWorldState& W)
	{
		FHRNews N;
		N.Text = TEXT("x");
		W.News.Init(N, HRSave::MaxNews + 1);
	}), TEXT("news"));
	Refused(TEXT("too many runners"), Mutated([](FHRWorldState& W)
	{
		FHRRace& R = W.Meeting.Races[0];
		const FHRRunner Copy = R.Entries[0];
		while (R.Entries.Num() <= HRSave::MaxEntries) R.Entries.Add(Copy);
	}), TEXT("entries"));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FHREconomyTest, "Atelier.HorseRacing.Economy.Invariants", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FHREconomyTest::RunTest(const FString&)
{
	const FHRWorldState Base = HRRules::CreateWorld(TEXT("economy-1"));

	// Saturating arithmetic.
	TestEqual(TEXT("a credit saturates at the cap"), HRRules::Credit(HRRules::MaxCoins - 1, 1000000000000LL), HRRules::MaxCoins);
	TestEqual(TEXT("a credit is never negative"), HRRules::Credit(10, -50), 10);
	TestEqual(TEXT("a tally saturates at int32"), HRRules::Tally(MAX_int32 - 1, 10), MAX_int32);

	// A ticket is settled once: settling again, or closing the day, pays nothing more.
	{
		FHRWorldState S = Base;
		HRRules::AddPlayer(S, TEXT("p1"), TEXT("Ada"));
		const FHRRace* Race = HRAdmissionTest::FieldRace(S, false);
		if (!TestNotNull(TEXT("a race to bet on"), Race)) return false;
		const FString Key = Race->Key;
		for (int32 I = 0; I < 2; ++I) TestTrue(TEXT("a ticket"), HRRules::PlaceBet(S, TEXT("p1"), Key, Race->Entries[I].HorseId, 5).IsEmpty());
		HRRules::SettleRace(S, *HRRules::FindRace(S, Key));
		TestTrue(TEXT("a declared race settles nothing"), !S.Tickets.ContainsByPredicate([](const FHRTicket& T) { return T.Status != TEXT("open"); }));
		while (!HRRules::FindRace(S, Key)->IsRun()) HRRules::RunNextRace(S);
		const int32 Coins = S.Players[TEXT("p1")].Coins;
		const TArray<FHRTicket> Settled = S.Tickets;
		TestTrue(TEXT("both tickets are settled"), !Settled.ContainsByPredicate([](const FHRTicket& T) { return T.Status == TEXT("open"); }));
		HRRules::SettleRace(S, *HRRules::FindRace(S, Key));
		TestEqual(TEXT("settling again pays nothing"), S.Players[TEXT("p1")].Coins, Coins);
		const int32 Income = HRRules::PlayerDailyIncome;
		HRRules::AdvanceDay(S);
		TestEqual(TEXT("the day's close pays only the daily income"), S.Players[TEXT("p1")].Coins, Coins + Income);
		for (int32 I = 0; I < Settled.Num(); ++I)
			TestEqual(TEXT("a settled ticket keeps its outcome"), S.Tickets[I].Status, Settled[I].Status);
	}

	// A void race refunds every stake.
	{
		FHRWorldState S = Base;
		HRRules::AddPlayer(S, TEXT("p1"), TEXT("Ada"));
		const FHRRace* Race = HRAdmissionTest::FieldRace(S, false);
		const FString Key = Race->Key;
		const int32 Before = S.Players[TEXT("p1")].Coins;
		TestTrue(TEXT("a ticket"), HRRules::PlaceBet(S, TEXT("p1"), Key, Race->Entries[0].HorseId, 7).IsEmpty());
		FHRRace& Void = *HRRules::FindRace(S, Key);
		Void.Status = TEXT("uncontested");
		Void.Finishes.Reset();
		HRRules::SettleRace(S, Void);
		TestEqual(TEXT("refunded"), S.Tickets.Last().Status, FString(TEXT("refunded")));
		TestEqual(TEXT("the stake is back"), S.Players[TEXT("p1")].Coins, Before);
		HRRules::SettleRace(S, Void);
		TestEqual(TEXT("refunded once"), S.Players[TEXT("p1")].Coins, Before);
	}

	// A winning ticket on a balance at the cap saturates; the daily income too.
	{
		FHRWorldState S = Base;
		HRRules::AddPlayer(S, TEXT("p1"), TEXT("Ada"));
		HRRules::RunNextRace(S);
		while (!HRAdmissionTest::FieldRace(S, true) && !HRRules::RunNextRace(S).IsEmpty()) {}
		const FHRRace* Run = HRAdmissionTest::FieldRace(S, true);
		if (TestNotNull(TEXT("a race was run"), Run))
		{
			FHRTicket T;
			T.Id = TEXT("bet:manual");
			T.PlayerId = TEXT("p1");
			T.T = S.T;
			T.RaceKey = Run->Key;
			T.HorseId = Run->Finishes[0].HorseId;
			T.Stake = 10;
			T.Status = TEXT("open");
			S.Tickets.Add(T);
			S.Players[TEXT("p1")].Coins = HRRules::MaxCoins - 3;
			HRRules::SettleRace(S, *Run);
			TestEqual(TEXT("won"), S.Tickets.Last().Status, FString(TEXT("won")));
			TestEqual(TEXT("the payout saturates at the cap"), S.Players[TEXT("p1")].Coins, HRRules::MaxCoins);
		}
		HRRules::AdvanceDay(S);
		TestEqual(TEXT("the income saturates at the cap"), S.Players[TEXT("p1")].Coins, HRRules::MaxCoins);
	}

	// Two seasons with players betting and owning: no balance goes negative and every day's world is admissible.
	{
		FHRWorldState S = Base;
		HRRules::AddPlayer(S, TEXT("owner"), TEXT("Ada")).Coins = 600;
		HRRules::AddPlayer(S, TEXT("punter"), TEXT("Bo"));
		TestTrue(TEXT("the owner buys the stable for sale"), HRRules::BuyStable(S, TEXT("owner"), S.Stables[0].Id, true).IsEmpty());
		bool bValid = true;
		for (int32 Day = 0; Day < 2 * HRClock::DaysPerSeason && bValid; ++Day)
		{
			for (const FHRRace& R : S.Meeting.Races)
			{
				if (R.Status != TEXT("declared") || R.Entries.Num() < 2) continue;
				HRRules::PlaceBet(S, TEXT("punter"), R.Key, R.Entries.Last().HorseId, 10);
				HRRules::PlaceBet(S, TEXT("owner"), R.Key, R.Entries[0].HorseId, 3);
				break;
			}
			HRRules::AdvanceDay(S);
			FString Why;
			bValid = HRAdmissionTest::BalancesValid(S, Why);
			TestTrue(FString::Printf(TEXT("day %d: balances within 0..cap (%s)"), S.T, *Why), bValid);
			const FString Admission = HRSave::Validate(S);
			TestTrue(FString::Printf(TEXT("day %d: the world is admissible (%s)"), S.T, *Admission), Admission.IsEmpty());
			bValid &= Admission.IsEmpty();
		}
	}

	// A long absence: the catch-up is bounded, deterministic, and moves the clock anchor by whole days.
	{
		FHRWorldState A = Base;
		HRRules::StartClock(A, 1800000000);
		FHRWorldState B = A;
		const int32 T0 = A.T;
		const int64 Epoch = A.EpochUnix;
		const double Far = HRClock::DayStart(T0 + 1000) + 1234.;
		constexpr int32 Cap = 4;
		HRRules::AdvanceTo(A, Far, Cap);
		HRRules::AdvanceTo(B, Far, Cap);
		TestTrue(FString::Printf(TEXT("at most %d days simulated (%d)"), Cap, A.T - T0), A.T - T0 <= Cap && A.T - T0 >= Cap - 1);
		TestTrue(TEXT("deterministic"), HRSave::ToJson(A) == HRSave::ToJson(B));
		TestEqual(TEXT("the anchor moved by whole days"), (A.EpochUnix - Epoch) % (int64)HRClock::DaySeconds, (int64)0);
		const double Resumed = HRRules::WorldSeconds(A, 1800000000.0 + (Far - HRClock::DayStart(T0)));
		TestTrue(TEXT("the world resumes on its present day"), Resumed >= HRClock::DayStart(A.T) && Resumed < HRClock::DayStart(A.T + 1));
		const FString Once = HRSave::ToJson(A);
		HRRules::AdvanceTo(A, std::numeric_limits<double>::quiet_NaN());
		HRRules::AdvanceTo(A, 1e300);
		TestTrue(TEXT("a non-finite or absurd time changes nothing"), HRSave::ToJson(A) == Once);
		TestEqual(TEXT("the default cap is one real week"), HRRules::MaxCatchUpDays, 84);
	}
	return true;
}

#endif
