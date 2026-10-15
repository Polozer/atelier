#pragma once
// Where the ride's collision snapshot is centred and when it is rebuilt (USkateComponent::RefreshSimulationCollision,
// SkateRuntime.cpp): plain values in, a plan out, so it is tested without a world (SkateCollisionCoverageTests.cpp).
//
// A snapshot covers a cube about its centre, of the half size FillWorld fits in the budget (100, 60, 35 or 20 m), and is
// rebuilt off the game thread once the ride passes its reach (60% of that). It was asked for at the board's place when
// the board had already passed the reach, and came in a build later: at 25-35 m/s the board goes 12-18 m in a half
// second build, and in a dense place, whose cube shrinks to 35 or 20 m, that is past the cube's face (14 or 8 m on
// from the reach), where the session's board finds no floor and falls on through a landing. Now the board's place is looked ahead by the time a build takes (measured), falling
// under gravity in the air, so a world is asked for early and centred where the board will be when it comes in, the
// landing below a falling board included. A board about to leave the world it has, with none coming that covers it,
// waits for one built at once: a hitch, not a fall through the floor. The budget and the radii stay as they were.
#include "CoreMinimal.h"

enum class ESkateCoverage : uint8
{
    Keep,       // the world installed covers the board for now
    Rebuild,    // ask for a world at Target, built off the game thread
    Now         // the board leaves the world within SoonSeconds: a world covering it is needed before the next step
};

struct FSkateCoveragePlan
{
    ESkateCoverage Refresh = ESkateCoverage::Keep;
    FVector Target = FVector::ZeroVector;   // where a world asked for now is centred (before its 10 m cell is taken)
};

namespace SkateCoverage
{
    constexpr double ReachFraction = .6;     // a world's reach over its half size (FillWorld)
    constexpr double Edge = 300.;            // cm the board, its rider and their contact queries keep inside the cube's face
    constexpr double SoonSeconds = .1;       // a frame and the step in flight
    // A world comes in a build after it is asked for: half as long again as the slowest of the last builds, and a quarter
    // second to its first step, never under a quarter or over two seconds.
    constexpr double FirstBuildSeconds = .5, LeadScale = 1.5, LeadMargin = .25, ShortestLead = .25, LongestLead = 2.;

    inline double Lead(double BuildSeconds) { return FMath::Clamp(BuildSeconds * LeadScale + LeadMargin, ShortestLead, LongestLead); }

    /** The board's place after T seconds: along its velocity, falling under Gravity (cm/s^2; 0 on the ground). */
    inline FVector Predict(const FVector& At, const FVector& Velocity, double T, double Gravity)
    {
        FVector P = At + Velocity * T;
        P.Z -= .5 * Gravity * T * T;
        return P;
    }

    /** Whether the cube of half size Radius about Centre holds Point with Edge to spare. */
    inline bool Covers(const FVector& Centre, double Radius, const FVector& Point) { return (Point - Centre).GetAbsMax() <= Radius - Edge; }

    /** The plan for a board at At with Velocity, given the world installed (Centre, Reach) and the slowest recent build. */
    inline FSkateCoveragePlan Plan(const FVector& Centre, double Reach, const FVector& At, const FVector& Velocity, double Gravity, double BuildSeconds)
    {
        FSkateCoveragePlan Out;
        // Where the board will be when a world asked for now comes in; no further from it than the reach, so the board's
        // place now stays inside that world too (a long lead at speed, or a fall the floor will stop, is cut back).
        Out.Target = Predict(At, Velocity, Lead(BuildSeconds), Gravity);
        const FVector Ahead = Out.Target - At;
        const double Far = Ahead.GetAbsMax();
        if (Far > Reach) Out.Target = At + Ahead * (Reach / Far);
        // At rest this is the old rule: a world past its reach is rebuilt about the board.
        if (!Covers(Centre, Reach / ReachFraction, Predict(At, Velocity, SoonSeconds, Gravity))) Out.Refresh = ESkateCoverage::Now;
        else if ((Out.Target - Centre).GetAbsMax() > Reach) Out.Refresh = ESkateCoverage::Rebuild;
        return Out;
    }

    /** The slowest recent build, the last one counted in full and the ones before fading by a fifth each. */
    inline double NextBuildSeconds(double Slowest, double Last) { return FMath::Max(Last, Slowest * .8); }
}
