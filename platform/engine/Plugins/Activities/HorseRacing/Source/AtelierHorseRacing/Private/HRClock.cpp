#include "HRClock.h"

#include "HRContent.h"

namespace HRClock
{
	int32 DayAt(double WorldSeconds)
	{
		return FMath::FloorToInt(WorldSeconds / DaySeconds);
	}

	bool IsGrandPrixDay(int32 T)
	{
		return HRContent::EventForT(T).bGrandPrix;
	}

	int32 SlotCount(int32 FirstRoundRaces, bool bGrandPrix)
	{
		return FMath::Max(RaceSlots, FirstRoundRaces + (bGrandPrix ? 2 : 0));
	}

	double SlotStart(int32 T, int32 Slot, int32 Count)
	{
		return DayStart(T) + FirstRaceSecond + Slot * RaceSpan / FMath::Max(RaceSlots, Count);
	}

	EHRRacePhase PhaseAt(double StartSeconds, double WorldSeconds)
	{
		if (WorldSeconds < StartSeconds) return EHRRacePhase::Upcoming;
		return WorldSeconds < StartSeconds + RaceSeconds ? EHRRacePhase::Running : EHRRacePhase::Finished;
	}

	FSlot ScheduleAt(double WorldSeconds, int32 Count)
	{
		FSlot Out;
		Out.T = DayAt(WorldSeconds);
		Out.Season = SeasonOf(Out.T);
		Out.DayOfSeason = DayOfSeason(Out.T);
		Out.bGrandPrix = IsGrandPrixDay(Out.T);
		Out.SlotCount = FMath::Max(RaceSlots, Count);
		Out.Slot = 0;
		for (int32 I = Out.SlotCount - 1; I > 0; --I)
		{
			if (SlotStart(Out.T, I, Out.SlotCount) <= WorldSeconds)
			{
				Out.Slot = I;
				break;
			}
		}
		Out.Start = SlotStart(Out.T, Out.Slot, Out.SlotCount);
		Out.End = Out.Start + RaceSeconds;
		Out.Phase = PhaseAt(Out.Start, WorldSeconds);
		return Out;
	}
}
