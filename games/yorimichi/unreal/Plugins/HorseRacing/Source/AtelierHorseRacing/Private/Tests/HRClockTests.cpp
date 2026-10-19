#include "HRClock.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include <limits>

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FHRClockScheduleTest, "Atelier.HorseRacing.Clock.Schedule",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FHRClockScheduleTest::RunTest(const FString&)
{
    TestEqual(TEXT("Two real hours per race day"), HRClock::DaySeconds, 7200.);
    TestEqual(TEXT("A season lasts one real day"), HRClock::DaysPerSeason * HRClock::DaySeconds, 86400.);
    TestEqual(TEXT("Horse year lasts one real week"), HRClock::LifeYear * HRClock::DaySeconds, 604800.);
    TestEqual(TEXT("Retired archive interval"), HRClock::ArchiveDays * HRClock::DaySeconds, 172800.);
    TestEqual(TEXT("Before day zero uses floor semantics"), HRClock::DayAt(-1.), -1);
    TestEqual(TEXT("Last instant of day zero"), HRClock::DayAt(7199.99), 0);
    TestEqual(TEXT("Next day starts at the boundary"), HRClock::DayAt(7200.), 1);
    TestEqual(TEXT("Negative day belongs to previous season"), HRClock::SeasonOf(-1), -1);
    TestEqual(TEXT("Negative day index wraps"), HRClock::DayOfSeason(-1), 11);
    TestEqual(TEXT("Age subtraction cannot overflow before division"), HRClock::LifeMonths(MIN_int32, MAX_int32), 613566756);
    int32 GrandPrix = 0;
    for (int32 Day = 0; Day < 12; ++Day)
    {
        const bool Expected = Day == 2 || Day == 5 || Day == 8 || Day == 11;
        TestTrue(TEXT("Reference Grand Prix calendar"), HRClock::IsGrandPrixDay(Day) == Expected);
        GrandPrix += HRClock::IsGrandPrixDay(Day) ? 1 : 0;
    }
    TestEqual(TEXT("Four Grand Prix dates"), GrandPrix, HRClock::GrandPrixPerSeason);
    for (int32 Count : {6,9,14})
        for (int32 Slot = 0; Slot < Count; ++Slot)
        {
            const double Start = HRClock::SlotStart(26, Slot, Count);
            const auto Before = HRClock::ScheduleAt(Start - 1e-6, Count);
            const auto At = HRClock::ScheduleAt(Start, Count);
            TestEqual(TEXT("Exact boundary selects the new slot"), At.Slot, Slot);
            TestEqual(TEXT("Before the boundary retains the preceding slot"), Before.Slot, FMath::Max(0, Slot - 1));
            TestTrue(TEXT("Boundary starts running"), At.Phase == HRClock::EHRRacePhase::Running);
            TestTrue(TEXT("Running phase is half open"), HRClock::PhaseAt(Start, Start + HRClock::RaceSeconds) == HRClock::EHRRacePhase::Finished);
            TestTrue(TEXT("A slot finishes within its day"), Start + HRClock::RaceSeconds < HRClock::DayStart(27));
        }
    TestEqual(TEXT("Grand Prix reserves final and barrage slots"), HRClock::SlotCount(5, true), 7);
    TestEqual(TEXT("Small meetings retain six slots"), HRClock::SlotCount(2, false), 6);
    HRClock::FSlot Large;
    TestTrue(TEXT("Large schedule is searched in bounded work"), HRClock::TryScheduleAt(3000., MAX_int32, Large));
    TestTrue(TEXT("Large schedule upper bound is correct"), Large.Start <= 3000. &&
        HRClock::SlotStart(0, Large.Slot + 1, MAX_int32) > 3000.);
    HRClock::FSlot Out;
    Out.T = 73;
    for (double Time : {std::numeric_limits<double>::quiet_NaN(), std::numeric_limits<double>::infinity(),
             -std::numeric_limits<double>::infinity(), HRClock::DayStart(MAX_int32) + HRClock::DaySeconds,
             HRClock::DayStart(MIN_int32) - HRClock::DaySeconds})
    {
        TestFalse(TEXT("Invalid external time is rejected"), HRClock::TryScheduleAt(Time, 6, Out));
        TestEqual(TEXT("Failed admission preserves the output"), Out.T, 73);
    }
    TestFalse(TEXT("Negative counts are rejected"), HRClock::TryScheduleAt(0., -1, Out));
    TestEqual(TEXT("Bad count preserves the output"), Out.T, 73);
    return true;
}
#endif
