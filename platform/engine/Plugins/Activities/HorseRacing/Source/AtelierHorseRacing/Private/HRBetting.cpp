#include "HRRules.h"

#include "HRRandom.h"

// Win bets in a pari-mutuel pool per race. A simulated crowd stakes on public replays of the field (never the day's form
// draw); every player's ticket on the race joins the same pool, so the odds move as players bet.

namespace
{
	int32 CrowdPool(const FHRWorldState& S)
	{
		return HRContent::EventForT(S.T).bGrandPrix ? 900 : 300;
	}
}

namespace HRRules
{
	double WinChance(const FHRRace& Race, const FString& HorseId)
	{
		const int32 N = Race.Entries.Num();
		const int32 Picked = Race.Entries.IndexOfByPredicate([&HorseId](const FHRRunner& R) { return R.HorseId == HorseId; });
		int32 Runs = 0;
		for (const FHROrderCount& O : Race.PublicOrders) Runs += O.Count;
		Runs = FMath::Max(1, Runs);
		double Chance = 0;
		for (const FHROrderCount& O : Race.PublicOrders)
		{
			TArray<FString> Parts;
			O.Key.ParseIntoArray(Parts, TEXT(">"));
			if (Parts.Num() > 0 && FCString::Atoi(*Parts[0]) == Picked) Chance += (double)O.Count / Runs;
		}
		return (1 - Longshot) * Chance + Longshot / FMath::Max(1, N);
	}

	double Rapport(const FHRWorldState& S, const FHRRace& Race, const FString& HorseId, int32 ExtraStake)
	{
		const int32 Pool = CrowdPool(S);
		int32 PlayerPool = ExtraStake;
		int32 OnHorse = ExtraStake;
		for (const FHRTicket& T : S.Tickets)
		{
			if (T.T != S.T || T.RaceKey != Race.Key || T.Status == TEXT("refunded")) continue;
			PlayerPool += T.Stake;
			if (T.HorseId == HorseId) OnHorse += T.Stake;
		}
		const double OnOutcome = Pool * WinChance(Race, HorseId) + OnHorse;
		if (OnOutcome <= 0) return MinRapport;
		const double Value = ((Pool + PlayerPool) * (1 - Take)) / OnOutcome;
		return FMath::Max(MinRapport, FMath::FloorToDouble(Value * 100) / 100);
	}

	int32 DayStake(const FHRWorldState& S, const FString& PlayerId)
	{
		int32 Sum = 0;
		for (const FHRTicket& T : S.Tickets)
			if (T.T == S.T && T.PlayerId == PlayerId) Sum += T.Stake;
		return Sum;
	}

	FString BetRefusal(const FHRWorldState& S, const FString& PlayerId, const FHRRace& Race, const FString& HorseId, int32 Stake)
	{
		const FHRPlayer* P = FindPlayer(S, PlayerId);
		if (!P) return TEXT("Unknown player.");
		if (Race.IsRun()) return TEXT("This race has been run.");
		if (Race.Entries.Num() < 2) return TEXT("Not enough runners to bet.");
		if (!Race.Entries.ContainsByPredicate([&HorseId](const FHRRunner& R) { return R.HorseId == HorseId; }))
			return TEXT("This horse is not declared to run.");
		if (Stake < FBetLimits::MinStake || Stake > FBetLimits::MaxStake)
			return FString::Printf(TEXT("Stake between %d and %d coins."), FBetLimits::MinStake, FBetLimits::MaxStake);
		if (DayStake(S, PlayerId) + Stake > FBetLimits::PerDay)
			return FString::Printf(TEXT("No more than %d coins of bets a day."), FBetLimits::PerDay);
		if (P->Coins < Stake) return FString::Printf(TEXT("It takes %d coins."), Stake);
		int32 OnRace = 0;
		for (const FHRTicket& T : S.Tickets)
			if (T.T == S.T && T.RaceKey == Race.Key && T.PlayerId == PlayerId) OnRace++;
		if (OnRace >= FBetLimits::TicketsPerRace)
			return FString::Printf(TEXT("No more than %d tickets per race."), FBetLimits::TicketsPerRace);
		return FString();
	}

	FString PlaceBet(FHRWorldState& S, const FString& PlayerId, const FString& RaceKey, const FString& HorseId, int32 Stake)
	{
		const FHRRace* Race = FindRace(S, RaceKey);
		if (!Race) return TEXT("Race not found.");
		const FString Refusal = BetRefusal(S, PlayerId, *Race, HorseId, Stake);
		if (!Refusal.IsEmpty()) return Refusal;
		FHRTicket T;
		T.Id = FString::Printf(TEXT("bet:%d:%d"), S.T, S.Serial++);
		T.PlayerId = PlayerId;
		T.T = S.T;
		T.RaceKey = RaceKey;
		T.HorseId = HorseId;
		T.Stake = Stake;
		T.Status = TEXT("open");
		FHRPlayer& P = *FindPlayer(S, PlayerId);
		P.Coins -= Stake;
		P.TotalStaked += Stake;
		S.Tickets.Add(T);
		return FString();
	}

	void SettleRace(FHRWorldState& S, const FHRRace& Race)
	{
		const FString Winner = Race.Finishes.Num() ? Race.Finishes[0].HorseId : FString();
		for (FHRTicket& T : S.Tickets)
		{
			if (T.T != S.T || T.RaceKey != Race.Key || T.Status != TEXT("open")) continue;
			FHRPlayer* P = FindPlayer(S, T.PlayerId);
			const bool bRan = Race.Finishes.ContainsByPredicate([&T](const FHRFinish& F) { return F.HorseId == T.HorseId; });
			// A declared horse that does not run is a non-runner: the stake is refunded, as for a race not run.
			if (Race.Status != TEXT("run") || !bRan || Race.Finishes.Num() < 2)
			{
				T.Status = TEXT("refunded");
				T.Payout = T.Stake;
				if (P) P->Coins += T.Stake;
				continue;
			}
			if (Winner != T.HorseId)
			{
				T.Status = TEXT("lost");
				T.Payout = 0;
				continue;
			}
			// The odds are fixed by the frozen field and every player ticket in this pool.
			T.Rapport = Rapport(S, Race, T.HorseId);
			T.Payout = FMath::FloorToInt(T.Stake * T.Rapport);
			T.Status = TEXT("won");
			if (P)
			{
				P->Coins += T.Payout;
				P->TotalWon += T.Payout;
				P->TicketsWon++;
			}
		}
	}
}
