#pragma once
// When the ride stops following the simulation's session (USkateComponent::BailOffLostSimulation, SkateRuntime.cpp):
// plain values in, a verdict out, so it is tested without a world (RideLostSimulationTests.cpp).
//
// The glue sets the actor on the session's root every step, and reads a state without Wipeout, Grind or Air in its
// name as the ground. The session has its own recovery: an air over 300 ticks (5 s, default in PlayerStateSelector.cpp;
// raised to 1800 ticks / 30 s in GameplayRuntime.cpp for the game) or a wipeout's automatic reset makes it Teleporting,
// and RespawnHistory::Automatic puts its rider where it stands only over ground the session has under it; with none it
// takes a place from its history, the ground ridden a few seconds before. A board that misses an overshot mega gap's
// landing in the session (its world not there yet, or the impact carrying it through) falls on through Unreal's floor
// until that timeout runs out, and the rider was carried back to the run-in to ride on: the teleport back. The rider is
// the body's from where the session lost it instead: it bails there, and the get-up starts a fresh session where the body
// lies.
#include "CoreMinimal.h"

enum class ERideLostSimulation : uint8
{
    Kept,           // the session is where the rider is: ride on
    Teleport,       // the session's own recovery (Teleporting)
    Jump,           // its board further than its speed takes it (a recovery published past its Teleporting ticks)
    ThroughFloor    // its board down through Unreal's floor while the session is still in the air
};

/** One step of the session against the one shown before it. Points are the deck's ground point (cm, world). */
struct FRideLostSimulationStep
{
    FString State;                                  // the session's state after the step
    uint64 Tick = 0;                                // the session's ticks since it was made
    FVector From = FVector::ZeroVector, To = FVector::ZeroVector;
    FVector Velocity = FVector::ZeroVector;         // the session's board after the step (cm/s)
    float Speed = 0.f;                              // the faster of the board's speeds before and after the step (cm/s)
    // The session's ticks from the pose shown to this one (60 Hz; a stalled step catches up to six at once). The pose
    // shown is a tick behind its latest (RideShownMotion.h), so the glue counts that tick too.
    uint64 Ticks = 1;
    // The first face of the world crossed on the way from just over From down to To, its normal turned toward From;
    // and whether a face lies over To, up to that one's height (To under the floor, not over a spine's other side).
    bool bCrossed = false, bCovered = false;
    FVector CrossedAt = FVector::ZeroVector, CrossedNormal = FVector::ZeroVector;
};

/** The floor a kept step went into and ended under (a landing's allowance, Judge): the next steps start their trace over
 *  it, so a board that went on down through it is still judged against it (Observe). */
struct FRideLostFloor
{
    bool bHeld = false;
    FVector At = FVector::ZeroVector, Normal = FVector::ZeroVector;   // a point on its face, and its normal (up)
};

namespace RideLostSimulation
{
    // An activation travels the fresh session to the ride's start, passing through Teleporting for a tick, in the 5
    // ticks before its first pose (GameplaySession::Activate); its own recovery comes seconds into a ride at the earliest.
    constexpr uint64 SettleTicks = 30;
    // A step's board moves at most twice its speed over the session's time between the two poses (its ticks, at least
    // two: the frame's own time undercounts a catch-up after a stall), plus a flip's swing of the deck about the rider
    // (FollowSimulationBoardInBail's reach).
    constexpr float JumpSlack = 50.f, TickSeconds = 1.f / 60.f;
    constexpr uint64 FewestTicks = 2;
    // The face the board went through is looked for from this far over the ground point shown last (cm): a landing
    // presses the wheels a little into the floor, and a ground point already under its face would miss it.
    constexpr float TraceAbove = 30.f;
    // Past the face by more than this along its normal (cm), the board is not on it: the session's board rides the same
    // collision a few millimetres deep, and one gone through at 15-20 m/s is 25-33 cm further at each 60 Hz tick.
    constexpr float ThroughDepth = 25.f;
    // A floor faces up within 60 degrees: a wall or a spine's other side crossed between two steps is not one.
    constexpr float FloorUp = .5f;

    /** The board's own airs: the rider on foot in the air (BipedAir) leaves the board to fall by itself. */
    inline bool IsBoardAir(const FString& State)
    {
        return State == TEXT("PhysicsAir") || State == TEXT("KnownAir") || State == TEXT("PhysicsAirSecondary");
    }

    /** How far To is past the floor's face along its normal (cm; under it when positive). */
    inline double Under(const FVector& To, const FVector& At, const FVector& Normal)
    {
        return FVector::DotProduct(At - To, Normal);
    }

    inline ERideLostSimulation Judge(const FRideLostSimulationStep& S)
    {
        if (S.Tick < SettleTicks) return ERideLostSimulation::Kept;
        if (S.State == TEXT("Teleporting")) return ERideLostSimulation::Teleport;
        if (FVector::Dist(S.From, S.To) > JumpSlack + 2.f * S.Speed * TickSeconds * float(FMath::Max(S.Ticks, FewestTicks)))
            return ERideLostSimulation::Jump;
        // Down through a floor, deep past it and under it, still in the air and still going into it: the session had no
        // floor there. Scale the depth threshold with speed only when crossing the floor (landing): at high speeds,
        // the board naturally travels 50-80 cm further in one tick at 30-50 m/s. A board already deep under (fall-through)
        // uses the strict threshold.
        if (S.bCrossed && S.bCovered && IsBoardAir(S.State) && S.To.Z < S.From.Z && S.CrossedNormal.Z > FloorUp &&
            FVector::DotProduct(S.Velocity, S.CrossedNormal) < 0.)
        {
            // Check if this step crosses the floor (landing) or the board is already deep below (fall-through).
            // If From is at or above the floor level, this is a crossing/landing.
            const bool bCrossing = S.From.Z >= S.CrossedAt.Z;
            const float ThresholdDepth = bCrossing ?
                ThroughDepth + S.Speed * TickSeconds * 1.5f :  // Landing: allow high-speed penetration
                ThroughDepth;  // Already below: strict check
            if (Under(S.To, S.CrossedAt, S.CrossedNormal) > ThresholdDepth)
                return ERideLostSimulation::ThroughFloor;
        }
        return ERideLostSimulation::Kept;
    }

    /** Where a step's face trace starts: TraceAbove over the ground point shown last, raised to TraceAbove over the
     *  floor held from the steps before when the board is under it. A landing's allowance keeps a board up to a metre
     *  and a half under a floor at speed; from under it, a trace from just over the board would never meet that floor
     *  again, and a board that went on down through it would never be judged. */
    inline FVector TraceStart(const FVector& From, const FRideLostFloor& Held)
    {
        FVector Start = From + FVector(0, 0, TraceAbove);
        if (Held.bHeld && Held.Normal.Z > FloorUp)
        {
            // The held face's height over From (its plane, through At).
            const double Over = Held.At.Z - ((From.X - Held.At.X) * Held.Normal.X + (From.Y - Held.At.Y) * Held.Normal.Y) / Held.Normal.Z;
            Start.Z = FMath::Max(Start.Z, Over + TraceAbove);
        }
        return Start;
    }

    /** After a step's verdict: the floor it went into and ended under while kept is held for the next step, and one held
     *  before stays held while the board is still in its air and under it. Anything else lets it go. */
    inline void Hold(const FRideLostSimulationStep& S, ERideLostSimulation Verdict, FRideLostFloor& Held)
    {
        if (Verdict != ERideLostSimulation::Kept || !IsBoardAir(S.State)) { Held = FRideLostFloor(); return; }
        if (S.bCrossed && S.bCovered && S.CrossedNormal.Z > FloorUp && Under(S.To, S.CrossedAt, S.CrossedNormal) > 0.)
        {
            Held.bHeld = true; Held.At = S.CrossedAt; Held.Normal = S.CrossedNormal;
            return;
        }
        if (!Held.bHeld || !(Under(S.To, Held.At, Held.Normal) > 0.)) Held = FRideLostFloor();
    }

    /** One step as the glue sees it (USkateComponent::BailOffLostSimulation): for a board air going down, the first
     *  face from TraceStart down to To, and whether a face lies over To up to it; then the verdict, and the floor held
     *  for the next step. Trace(Start, End, OutAt, OutNormal) is the world's first face from Start to End, its normal
     *  turned toward Start (a trace meets a face from either side). */
    template <typename FTrace>
    inline ERideLostSimulation Observe(FRideLostSimulationStep& S, FRideLostFloor& Held, FTrace&& Trace)
    {
        S.bCrossed = S.bCovered = false;
        if (IsBoardAir(S.State) && S.To.Z < S.From.Z)
        {
            FVector At, Normal;
            if (Trace(TraceStart(S.From, Held), S.To, At, Normal))
            {
                S.bCrossed = true; S.CrossedAt = At; S.CrossedNormal = Normal;
                FVector OverAt, OverNormal;
                S.bCovered = Trace(S.To, FVector(S.To.X, S.To.Y, FMath::Max(S.To.Z, At.Z) + TraceAbove), OverAt, OverNormal);
            }
        }
        const ERideLostSimulation Verdict = Judge(S);
        Hold(S, Verdict, Held);
        return Verdict;
    }

    inline const TCHAR* Describe(ERideLostSimulation Lost)
    {
        switch (Lost)
        {
        case ERideLostSimulation::Teleport: return TEXT("its recovery teleport");
        case ERideLostSimulation::Jump: return TEXT("its board further than its speed takes it");
        case ERideLostSimulation::ThroughFloor: return TEXT("its board through the floor");
        default: return TEXT("kept");
        }
    }
}
