// RideShownMotion.h, against the session's own clock (GameplaySession::Step: whole ticks of 16.6666 ms, the rest kept,
// at most 0.1 s a step): a 35 m/s air shown at a jittery 60 fps, at 50 fps and through a stalled step, as each frame
// showed its last whole tick and as it is shown now; and the body's placement test at that speed.
#include "RideShownMotion.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRideShownMotionTest, "AtelierSkate.Ride.ShownMotion",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace
{
    constexpr float Period = .0166666f;   // SimulationClock's 16666600 ns
    constexpr double Speed = 3500.;      // cm/s: a mega gap's lip speed and its fall

    /** The session (its clock and the board's place at each tick) and the ride's poll and presentation of it. */
    struct FRide
    {
        float Elapsed = 0.f; uint64 Tick = 0;
        uint64 Shown = 0, PreviousTick = 0; FTransform Latest, Previous;
        static FTransform At(uint64 T, double Jump = 0.) { return FTransform(FVector(Speed * Period * double(T) + Jump, 0., 0.)); }
        double Jump = 0.;
        // One frame: the session steps its time (GameplaySession::Step), the ride takes the pose (FSkateRuntime::Poll).
        void Frame(float Dt)
        {
            Elapsed = FMath::Min(Elapsed + Dt, RideShownMotion::LongestStep);
            while (Elapsed + 1.0e-7f >= Period) { Elapsed -= Period; ++Tick; }
            if (Tick == Shown) return;
            const FTransform Now = At(Tick, Jump);
            if (RideShownMotion::Continues(Latest.GetLocation(), Now.GetLocation(), Shown, Tick, float(Speed))) { Previous = Latest; PreviousTick = Shown; }
            else PreviousTick = Tick;
            Latest = Now; Shown = Tick;
        }
        double Time() const { return double(Period) * double(Tick) + double(Elapsed); }   // the session's, s
        double Raw() const { return Latest.GetLocation().X; }
        double Smooth() const
        {
            return RideShownMotion::Blend(Previous, Latest, RideShownMotion::Alpha(PreviousTick, Shown, Elapsed / Period)).GetLocation().X;
        }
    };

    struct FMoves { double RawLeast = 1e9, RawMost = 0, SmoothWorst = 0; };

    // Frames of the given lengths; each frame's move against what the session's time over it takes the board (from the
    // third on; a step clamped at 0.1 s drops the rest, in the session as here).
    FMoves Ride(FRide& R, const TArray<float>& Frames)
    {
        FMoves M; double Raw = R.Raw(), Smooth = R.Smooth(), Time = R.Time();
        for (int32 I = 0; I < Frames.Num(); ++I)
        {
            R.Frame(Frames[I]);
            if (I >= 2)
            {
                M.RawLeast = FMath::Min(M.RawLeast, R.Raw() - Raw); M.RawMost = FMath::Max(M.RawMost, R.Raw() - Raw);
                M.SmoothWorst = FMath::Max(M.SmoothWorst, FMath::Abs(R.Smooth() - Smooth - Speed * (R.Time() - Time)));
            }
            Raw = R.Raw(); Smooth = R.Smooth(); Time = R.Time();
        }
        return M;
    }
}

bool FRideShownMotionTest::RunTest(const FString&)
{
    using namespace RideShownMotion;
    const double TickMove = Speed * Period;   // 58 cm

    // The 60 fps limit's frames, 16.2 and 17.1 ms about the tick's 16.67, with the session's kept time near a tick's edge.
    {
        FRide R; R.Elapsed = .0002f;
        TArray<float> Frames; for (int32 I = 0; I < 240; ++I) Frames.Add(I % 2 ? .0171f : .0162f);
        const FMoves M = Ride(R, Frames);
        TestTrue(TEXT("Its last whole tick stood still for a frame (the stutter)"), M.RawLeast < 1.);
        TestTrue(TEXT("and jumped two ticks the next (117 cm at 35 m/s)"), M.RawMost > 2. * TickMove - 1.);
        TestTrue(TEXT("Shown between ticks, every frame moves by its own time"), M.SmoothWorst < .05);
    }
    // 50 fps (a frame of 20 ms): one tick, then two.
    {
        FRide R; R.Elapsed = .005f;
        TArray<float> Frames; for (int32 I = 0; I < 150; ++I) Frames.Add(.02f);
        const FMoves M = Ride(R, Frames);
        TestTrue(TEXT("At 50 fps its last whole tick moves one tick, then two"), M.RawLeast < TickMove + 1. && M.RawMost > 2. * TickMove - 1.);
        TestTrue(TEXT("Shown between ticks, 50 fps moves 70 cm each frame"), M.SmoothWorst < .05);
    }
    // A stalled step (a frame of 0.1 s: six ticks at once) is still the ride, shown by its time.
    {
        FRide R; R.Elapsed = .003f;
        TArray<float> Frames; for (int32 I = 0; I < 20; ++I) Frames.Add(I == 10 ? .1f : 1.f / 60.f);
        const FMoves M = Ride(R, Frames);
        TestTrue(TEXT("Six ticks at once blend on"), M.SmoothWorst < .05);
        TestTrue(TEXT("and move 350 cm, within the body's reach at that speed"), M.RawMost <= PlacedReach(100.f, float(Speed)));
    }
    // A jump (a placement, the session's recovery) is shown as it comes.
    {
        FRide R; R.Elapsed = .003f;
        for (int32 I = 0; I < 10; ++I) R.Frame(1.f / 60.f);
        R.Jump = 2000.; R.Frame(1.f / 60.f);
        TestEqual(TEXT("A 20 m jump in a tick is shown, not crossed"), R.Smooth(), R.Raw(), .001);
    }

    TestEqual(TEXT("A first pose is shown as it comes"), Alpha(5, 5, .5f), 1.f);
    TestEqual(TEXT("Ticks further apart than a step are shown as they come"), Alpha(2, 10, .5f), 1.f);
    TestEqual(TEXT("A tick on, with no time kept, shows the tick before"), Alpha(4, 5, 0.f), 0.f);
    TestEqual(TEXT("A tick on with a quarter kept, a quarter of the way"), Alpha(4, 5, .25f), .25f);
    TestEqual(TEXT("Two ticks on with none kept, the tick between"), Alpha(3, 5, 0.f), .5f);
    TestFalse(TEXT("A step of no tick is not a pose of its own"), Continues(FVector::ZeroVector, FVector::ZeroVector, 5, 5, 0.f));
    {
        const FTransform A(FRotator(0, 0, 0), FVector::ZeroVector), B(FRotator(0, 90, 0), FVector(100, 0, 0));
        const FTransform Half = Blend(A, B, .5f);
        TestEqual(TEXT("Half way turns half way"), Half.Rotator().Yaw, 45., .01);
        TestEqual(TEXT("and moves half way"), Half.GetLocation().X, 50., .001);
    }

    // The body (URidePhysicalRider::Update): two ticks at 35 m/s were over the old 1 m, and read as a placement.
    TestTrue(TEXT("Two ticks of a 35 m/s air were a placement at 1 m"), 2. * TickMove > 100.);
    TestTrue(TEXT("and are riding now"), 2. * TickMove < PlacedReach(100.f, float(Speed)));
    TestEqual(TEXT("At rest a placement is still a metre"), PlacedReach(100.f, 0.f), 100.f);
    TestTrue(TEXT("A 10 m placement at 35 m/s is still one"), 1000.f > PlacedReach(100.f, float(Speed)));
    return true;
}
#endif
