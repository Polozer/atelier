#pragma once
// The ride shown between the session's ticks (FSkateRuntime::Poll and Present, SkateRuntimeDetail.h) and the body's
// placement test (URidePhysicalRider::Update): plain values in and out, tested without a world (RideShownMotionTests.cpp).
//
// The session steps whole 60 Hz ticks and keeps the rest of the frame's time for the next step (GameplaySession::Step),
// and each frame showed its latest whole tick. The game is limited to 60 fps, so a frame lasts about a tick, and its
// jitter about the tick's edge gave runs of frames with no tick and frames with two: the rider stood for a frame, then
// jumped two ticks (in a 35 m/s air, 0 then 117 cm). A stalled step shows up to six at once. The body read a jump over
// 1 m as a placement: its bodies were put back on the animation and their spin stopped, and Physics Control
// teleported the board-frame root body. That is the stutter on big airs, the only place the ride goes that fast.
#include "CoreMinimal.h"

namespace RideShownMotion
{
    // A step runs at most 0.1 s of ticks (StepSimulation's FrameTime and GameplaySession::Step both clamp): six.
    constexpr float LongestStep = .1f;
    constexpr uint64 MostTicks = 6;
    constexpr float TickSeconds = 1.f / 60.f;
    // A pose further from the last than the board's speed takes it over the ticks between, plus this (cm), is a jump
    // (a placement, the session's own recovery): shown as it comes, not blended.
    constexpr float JumpSlack = 100.f;

    /** How far from the previous tick's pose (at PreviousTick) to the latest (at Tick) the frame is shown, 0..1: one tick
     *  behind the session's time (Tick plus Fraction, the time it keeps for the next step, in ticks), so every frame moves
     *  by its own time. A first pose, or ticks too far apart to be one step, shows the latest. */
    inline float Alpha(uint64 PreviousTick, uint64 Tick, float Fraction)
    {
        if (Tick <= PreviousTick || Tick - PreviousTick > MostTicks) return 1.f;
        const double Shown = double(Tick) - 1. + FMath::Clamp(double(Fraction), 0., 1.);
        return float(FMath::Clamp((Shown - double(PreviousTick)) / double(Tick - PreviousTick), 0., 1.));
    }

    /** Whether the root moved From to To over the ticks between two poses at Speed at most (cm/s), as riding does. */
    inline bool Continues(const FVector& From, const FVector& To, uint64 PreviousTick, uint64 Tick, float Speed)
    {
        if (Tick <= PreviousTick || Tick - PreviousTick > MostTicks) return false;
        return FVector::Dist(From, To) <= JumpSlack + Speed * TickSeconds * float(Tick - PreviousTick);
    }

    inline FTransform Blend(const FTransform& A, const FTransform& B, float T)
    {
        if (T >= 1.f) return B;
        if (T <= 0.f) return A;
        return FTransform(FQuat::Slerp(A.GetRotation(), B.GetRotation(), T).GetNormalized(),
            FMath::Lerp(A.GetLocation(), B.GetLocation(), double(T)), FMath::Lerp(A.GetScale3D(), B.GetScale3D(), double(T)));
    }

    /** The furthest the body's mesh moves in a frame while ridden, not placed (cm): Base, plus what Speed (cm/s, the
     *  faster of the frame's two) covers in the longest step a frame can show. */
    inline float PlacedReach(float Base, float Speed)
    {
        return Base + FMath::Max(Speed, 0.f) * LongestStep;
    }
}
