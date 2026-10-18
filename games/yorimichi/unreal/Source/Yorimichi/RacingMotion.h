#pragma once
#include "CoreMinimal.h"

/**
 * How a runner moves through a race, as a pure function of replicated data (docs/RACING.md, "Motion"): the rules decide
 * each horse's time at the end of the race's four stages (15, 35, 25 and 25 % of the distance) when the race starts, and
 * every machine draws the same distance over time from those splits and the replicated start time. Nothing moves per frame
 * over the network.
 */
namespace RacingMotion
{
    /** Share of the distance at the end of each stage (HRRace.cpp's stage fractions). */
    inline constexpr double StageEnd[4] = {.15, .50, .75, 1.};
    /** Before the start: the field walks the last ParadeDistance metres to the start, arriving ParadeHold s early. */
    inline constexpr double ParadeSeconds = 120., ParadeHold = 15., ParadeDistance = 120.;
    /** After the post: the field eases down at PullUp m/s² to a CoolDown m/s trot. */
    inline constexpr double PullUp = 1.6, CoolDown = 2.6;

    /** One runner's plan: the race distance (m) and the cumulative time (s) at the end of each stage; all zero before
     *  the race is run. */
    struct FPlan
    {
        double Distance = 0.;
        double Splits[4] = {0., 0., 0., 0.};
        bool IsRun() const { return Splits[3] > 0.; }
        double FinishTime() const { return Splits[3]; }
    };

    /** Distance run (metres from the start, past Distance after the post) T seconds after the start, and the speed (m/s).
     *  Before the start (T < 0): the parade, negative distances up to 0. A race not yet run stands at the start. */
    YORIMICHI_API double Distance(const FPlan& Plan, double T, double* Speed = nullptr);
}
