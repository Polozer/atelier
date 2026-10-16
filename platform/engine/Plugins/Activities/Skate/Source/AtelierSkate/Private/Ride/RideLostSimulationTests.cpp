// RideLostSimulation.h's verdicts, from the steps of a ride at 60 Hz: an overshot mega gap's landing (25-30 m/s,
// 15-20 of them into the ground) that the session's board missed, the session's recovery after its 5 s air, and the
// steps of ordinary riding that must ride on; and the caller's steps over a floor (Observe), where a landing kept under the
// floor and gone on down through it must still bail.
#include "RideLostSimulation.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRideLostSimulationTest, "AtelierSkate.Ride.LostSimulation",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace
{
    // A step of the board at Velocity (cm/s) over a 60 Hz frame from From, in State, well into the ride.
    FRideLostSimulationStep Moving(const TCHAR* State, const FVector& From, const FVector& Velocity)
    {
        FRideLostSimulationStep S;
        S.State = State; S.Tick = 600; S.Ticks = 1;
        S.From = From; S.To = From + Velocity * (1.f / 60.f); S.Velocity = Velocity; S.Speed = float(Velocity.Size());
        return S;
    }
    // The step crossed a face at At with Normal (turned toward From), and ends under a face (bCovered) or in the open.
    FRideLostSimulationStep Crossing(FRideLostSimulationStep S, const FVector& At, const FVector& Normal, bool bCovered = true)
    {
        S.bCrossed = true; S.bCovered = bCovered; S.CrossedAt = At; S.CrossedNormal = Normal.GetSafeNormal();
        return S;
    }
    // The world's faces as the glue traces them (RideLostSimulation::Observe): one flat floor at z 0, its first face
    // from Start to End, the normal turned toward Start. DownFrom is where the last trace down started.
    struct FFlatFloor
    {
        double DownFrom = 0.;
        bool operator()(const FVector& Start, const FVector& End, FVector& At, FVector& Normal)
        {
            if (Start.Z > End.Z) DownFrom = Start.Z;
            if (Start.Z == End.Z || (Start.Z > 0.) == (End.Z > 0.)) return false;
            const double T = Start.Z / (Start.Z - End.Z);
            At = Start + (End - Start) * T; At.Z = 0.;
            Normal = Start.Z > 0. ? FVector::UpVector : -FVector::UpVector;
            return true;
        }
    };
    // A step of the board from From to To over Ticks of the session at Velocity, in PhysicsAir, well into the ride.
    FRideLostSimulationStep Air(const FVector& From, const FVector& To, const FVector& Velocity, uint64 Ticks = 1)
    {
        FRideLostSimulationStep S;
        S.State = TEXT("PhysicsAir"); S.Tick = 600; S.Ticks = Ticks;
        S.From = From; S.To = To; S.Velocity = Velocity; S.Speed = float(Velocity.Size());
        return S;
    }
}

bool FRideLostSimulationTest::RunTest(const FString&)
{
    using RideLostSimulation::Judge;
    const FVector Landing(2800.f, 0.f, -1800.f);   // 28 m/s on, 18 m/s down

    // The board 10 cm over a flat floor at z 0, then 20 cm under it: one frame inside, but not yet through.
    {
        const FRideLostSimulationStep S = Crossing(Moving(TEXT("PhysicsAir"), FVector(0, 0, 10), Landing), FVector(0, 0, 0), FVector::UpVector);
        TestTrue(TEXT("A landing 20 cm into the floor rides on (the next step shows whether the session found it)"),
            Judge(S) == ERideLostSimulation::Kept);
    }
    // Already 20 cm under it, the next step 50 cm under: the session had no floor there.
    {
        const FRideLostSimulationStep S = Crossing(Moving(TEXT("PhysicsAir"), FVector(0, 0, -20), Landing), FVector(0, 0, 0), FVector::UpVector);
        TestTrue(TEXT("A board through the floor, still in the air, bails"), Judge(S) == ERideLostSimulation::ThroughFloor);
        FRideLostSimulationStep Known = S; Known.State = TEXT("KnownAir");
        TestTrue(TEXT("A known air through the floor bails"), Judge(Known) == ERideLostSimulation::ThroughFloor);
        FRideLostSimulationStep Landed = S; Landed.State = TEXT("PhysicsGround");
        TestTrue(TEXT("A session on the ground found its floor: it rides on"), Judge(Landed) == ERideLostSimulation::Kept);
        FRideLostSimulationStep OnFoot = S; OnFoot.State = TEXT("BipedAir");
        TestTrue(TEXT("The rider on foot in the air leaves the board to itself: it rides on"), Judge(OnFoot) == ERideLostSimulation::Kept);
        FRideLostSimulationStep Wiped = S; Wiped.State = TEXT("WipeoutGround");
        TestTrue(TEXT("A wipeout is the body's bail already"), Judge(Wiped) == ERideLostSimulation::Kept);
        FRideLostSimulationStep Uncrossed = S; Uncrossed.bCrossed = false;
        TestTrue(TEXT("No face crossed (open air) rides on"), Judge(Uncrossed) == ERideLostSimulation::Kept);
        FRideLostSimulationStep Open = S; Open.bCovered = false;
        TestTrue(TEXT("A board in the open past the face it crossed rides on"), Judge(Open) == ERideLostSimulation::Kept);
    }
    // A wall crossed between two steps is not a floor gone through, nor is a 45 degree face the board ends 35 cm past
    // along its normal but in the open (over a spine's other side).
    {
        const FRideLostSimulationStep Wall = Crossing(Moving(TEXT("PhysicsAir"), FVector(-20, 0, 100), FVector(3000, 0, -300)),
            FVector(0, 0, 97), FVector(-1, 0, 0));
        TestTrue(TEXT("A wall crossed rides on"), Judge(Wall) == ERideLostSimulation::Kept);
        FRideLostSimulationStep Spine = Moving(TEXT("PhysicsAir"), FVector(-30, 0, -25), FVector(3000, 0, -300));
        Spine.To = FVector(20, 0, -30);
        Spine = Crossing(Spine, FVector(-5, 0, -5), FVector(-1, 0, 1), false);
        TestTrue(TEXT("A face crossed with the board in the open past it rides on"), Judge(Spine) == ERideLostSimulation::Kept);
        Spine.bCovered = true;
        TestTrue(TEXT("The same step under a face bails"), Judge(Spine) == ERideLostSimulation::ThroughFloor);
    }
    // Rising out through a face (the normal toward the start, below it) is not falling through a floor.
    {
        const FRideLostSimulationStep Up = Crossing(Moving(TEXT("PhysicsAir"), FVector(0, 0, -20), FVector(0, 0, 3000)),
            FVector(0, 0, 0), -FVector::UpVector);
        TestTrue(TEXT("A board rising through a face rides on"), Judge(Up) == ERideLostSimulation::Kept);
    }

    // The session's own recovery: Teleporting, or its board moved further than its speed takes it.
    {
        FRideLostSimulationStep S = Moving(TEXT("Teleporting"), FVector(0, 0, -900), FVector(0, 0, -2500));
        TestTrue(TEXT("The session's recovery teleport bails where the rider is"), Judge(S) == ERideLostSimulation::Teleport);
        S.Tick = 5;
        TestTrue(TEXT("The travel to a fresh session's start (its first ticks) is not one"), Judge(S) == ERideLostSimulation::Kept);
        FRideLostSimulationStep Back = Moving(TEXT("PhysicsGround"), FVector(0, 0, -900), FVector(0, 0, -2500));
        Back.To = FVector(-6000, 0, 2400);
        TestTrue(TEXT("A board back on the run-in 70 m away bails"), Judge(Back) == ERideLostSimulation::Jump);
    }
    // High-speed big air landings (ThroughFloor robustness at speed).
    {
        // 40 m/s landing: the board crosses the floor and passes through 60 cm in one frame.
        // Speed-adjusted threshold allows this for landings (board starting above floor).
        FRideLostSimulationStep Steep = Moving(TEXT("PhysicsAir"), FVector(0, 0, 50), FVector(4000, 0, -800));
        Steep.Tick = 150;  // well into the air
        // Floor at z=0. From.Z = 50 (above floor). Speed = 4079 cm/s.
        // Depth threshold = 25 + 4079/60 * 1.5 = 25 + 102 = 127 cm.
        // Board ends 60 cm below floor: within lenient threshold (and within the speed's reach: no jump).
        Steep.To = FVector(67, 0, -60);
        Steep = Crossing(Steep, FVector(30, 0, 0), FVector::UpVector);
        TestTrue(TEXT("A 40 m/s touchdown crossing the floor at 60 cm depth rides on (speed-adjusted)"),
            Judge(Steep) == ERideLostSimulation::Kept);
        // 50 m/s landing on same floor type, board passes 75 cm through.
        FRideLostSimulationStep Fast = Moving(TEXT("KnownAir"), FVector(0, 0, 100), FVector(5000, 0, -500));
        Fast.Tick = 200;
        // Speed = 5024 cm/s. Depth threshold = 25 + 5024/60 * 1.5 = 25 + 126 = 151 cm.
        // Board ends 75 cm below floor: within lenient threshold.
        Fast.To = FVector(84, 0, -75);
        Fast = Crossing(Fast, FVector(48, 0, 0), FVector::UpVector);
        TestTrue(TEXT("A 50 m/s touchdown at 75 cm depth rides on (speed-adjusted)"),
            Judge(Fast) == ERideLostSimulation::Kept);
    }
    // Fall-through case: board already below floor uses strict threshold and bails.
    {
        // A board already 30 cm under a floor at z=0, moving further down at the original speed from test line 42.
        // This uses the strict threshold (25 cm) because From.Z < 0.
        FRideLostSimulationStep FallThrough = Moving(TEXT("PhysicsAir"), FVector(0, 0, -30), FVector(2800, 0, -1800));
        FallThrough.Tick = 150;
        FallThrough = Crossing(FallThrough, FVector(47, 0, 0), FVector::UpVector);
        // After one frame at 3206 cm/s down, the board ends at -80 cm: 80 cm below floor.
        // With strict threshold of 25 cm, this bails.
        FallThrough.To = FVector(47, 0, -80);
        TestTrue(TEXT("A board already 30 cm under and reaching 80 cm bails with strict threshold"),
            Judge(FallThrough) == ERideLostSimulation::ThroughFloor);
    }
    // The caller's steps (Observe, as USkateComponent::BailOffLostSimulation runs them) over a flat floor at z 0: a
    // board coming down at 39 m/s, kept 60 cm under the floor by the landing's allowance, then going on down through it.
    // The floor is traced for from 30 cm over the board shown last: from 60 cm under, that trace starts under the
    // floor and never meets it again, so the held floor raises it.
    {
        using RideLostSimulation::Observe;
        const FVector Down(3000.f, 0.f, -2500.f);   // 30 m/s on, 25 m/s down
        FRideLostFloor Held;
        FFlatFloor World;
        // Over the floor: nothing crossed, nothing held.
        FRideLostSimulationStep Over = Air(FVector(-150, 0, 190), FVector(0, 0, 65), Down, 3);
        TestTrue(TEXT("Coming down over the floor rides on"), Observe(Over, Held, World) == ERideLostSimulation::Kept);
        TestFalse(TEXT("Over the floor no face is crossed"), Over.bCrossed);
        TestFalse(TEXT("Over the floor nothing is held"), Held.bHeld);
        // Into it: three ticks of a catch-up end 60 cm under it, within the landing's allowance (25 + 98 cm).
        FRideLostSimulationStep Into = Air(Over.To, FVector(150, 0, -60), Down, 3);
        TestTrue(TEXT("A landing 60 cm into the floor rides on"), Observe(Into, Held, World) == ERideLostSimulation::Kept);
        TestTrue(TEXT("Its step crossed the floor, and ends under it"), Into.bCrossed && Into.bCovered);
        TestTrue(TEXT("The floor it ended under is held"), Held.bHeld && FMath::IsNearlyEqual(Held.At.Z, 0., 1e-6) && Held.Normal.Z > .99);
        // On down through it, still in the air: the next trace starts over the held floor and finds it again.
        FRideLostSimulationStep Through = Air(Into.To, Into.To + Down * (1.f / 60.f), Down);
        TestTrue(TEXT("The step from 60 cm under is traced from over the floor"),
            RideLostSimulation::TraceStart(Through.From, Held).Z >= RideLostSimulation::TraceAbove - 1e-3);
        TestTrue(TEXT("Going on down through the floor bails"), Observe(Through, Held, World) == ERideLostSimulation::ThroughFloor);
        TestTrue(TEXT("Its trace started over the floor"), World.DownFrom > 0.);
        TestFalse(TEXT("A bail lets the floor go"), Held.bHeld);
        // Without the held floor (the trace from 30 cm over the board), the same step met no floor and rode on under it.
        FRideLostFloor None;
        FRideLostSimulationStep Unheld = Air(Into.To, Into.To + Down * (1.f / 60.f), Down);
        TestTrue(TEXT("Unheld, the trace from under the floor misses it"),
            Observe(Unheld, None, World) == ERideLostSimulation::Kept && !Unheld.bCrossed);
    }
    // The held floor follows the session: a landing found leaves it, and so does a board that comes back over it.
    {
        using RideLostSimulation::Observe;
        const FVector Down(3000.f, 0.f, -2500.f);
        FFlatFloor World;
        FRideLostFloor Held;
        FRideLostSimulationStep Into = Air(FVector(0, 0, 65), FVector(150, 0, -60), Down, 3);
        Observe(Into, Held, World);
        FRideLostSimulationStep Landed = Air(Into.To, FVector(200, 0, -2), FVector(3000, 0, 0));
        Landed.State = TEXT("PhysicsGround");
        TestTrue(TEXT("The session found its floor: it rides on"), Observe(Landed, Held, World) == ERideLostSimulation::Kept);
        TestFalse(TEXT("On the ground nothing is held"), Held.bHeld);
        Observe(Into, Held, World);
        FRideLostSimulationStep Rising = Air(Into.To, FVector(200, 0, -20), FVector(3000, 0, 2400));
        TestTrue(TEXT("Rising under the held floor rides on"), Observe(Rising, Held, World) == ERideLostSimulation::Kept);
        TestTrue(TEXT("Still under it, it stays held"), Held.bHeld);
        FRideLostSimulationStep Out = Air(Rising.To, FVector(250, 0, 15), FVector(3000, 0, 2100));
        Observe(Out, Held, World);
        TestFalse(TEXT("Back over it, it is let go"), Held.bHeld);
        // A shallow landing kept 15 cm under, then a step settling 10 cm further, still in the air: within the strict 25 cm.
        FRideLostFloor Shallow;
        FRideLostSimulationStep Touch = Air(FVector(0, 0, 20), FVector(50, 0, -15), FVector(3000, 0, -2100));
        TestTrue(TEXT("A touchdown 15 cm in rides on"), Observe(Touch, Shallow, World) == ERideLostSimulation::Kept && Shallow.bHeld);
        FRideLostSimulationStep Settle = Air(Touch.To, FVector(100, 0, -24), FVector(3000, 0, -540));
        TestTrue(TEXT("Settling to 24 cm under, judged against the held floor, rides on"),
            Observe(Settle, Shallow, World) == ERideLostSimulation::Kept && Settle.bCrossed);
    }
    // A held floor on a 30 degree slope is traced for over its own height at the board, not the point it was crossed at.
    {
        FRideLostFloor Slope;
        Slope.bHeld = true; Slope.At = FVector(0, 0, 0); Slope.Normal = FVector(-.5, 0, .866).GetSafeNormal();
        const FVector Start = RideLostSimulation::TraceStart(FVector(100, 0, -40), Slope);
        TestTrue(TEXT("The slope's height at the board, plus 30 cm"), FMath::IsNearlyEqual(Start.Z, 100. * .5 / .866 + 30., 1e-2));
        TestTrue(TEXT("Nothing held: 30 cm over the board"),
            FMath::IsNearlyEqual(RideLostSimulation::TraceStart(FVector(100, 0, -40), FRideLostFloor()).Z, -10., 1e-6));
    }
    // Ordinary riding: the fastest frames ride on, and so does a slow frame at speed.
    {
        TestTrue(TEXT("30 m/s at 60 Hz rides on"), Judge(Moving(TEXT("PhysicsGround"), FVector::ZeroVector, FVector(3000, 0, 0))) == ERideLostSimulation::Kept);
        FRideLostSimulationStep Slow = Moving(TEXT("PhysicsAir"), FVector::ZeroVector, FVector(3000, 0, 0));
        Slow.Ticks = 6; Slow.To = Slow.From + Slow.Velocity * .1f;
        TestTrue(TEXT("A 100 ms frame at 30 m/s rides on"), Judge(Slow) == ERideLostSimulation::Kept);
        // A stalled step: the frame was 17 ms, but the session caught up six ticks (and the pose shown is one behind).
        FRideLostSimulationStep CatchUp = Moving(TEXT("PhysicsAir"), FVector::ZeroVector, FVector(3500, 0, -1500));
        CatchUp.Ticks = 7; CatchUp.To = CatchUp.From + CatchUp.Velocity * (7.f / 60.f);
        TestTrue(TEXT("A catch-up of seven ticks at 38 m/s after a stall rides on"), Judge(CatchUp) == ERideLostSimulation::Kept);
        FRideLostSimulationStep Short = CatchUp; Short.Ticks = 1;
        TestTrue(TEXT("Counted as one frame's tick it would have bailed"), Judge(Short) == ERideLostSimulation::Jump);
        FRideLostSimulationStep Far = CatchUp; Far.To = FVector(2000, 0, 0) + CatchUp.Velocity * (7.f / 60.f);
        TestTrue(TEXT("20 m beyond those seven ticks still bails"), Judge(Far) == ERideLostSimulation::Jump);
        FRideLostSimulationStep Flip = Moving(TEXT("KnownAir"), FVector::ZeroVector, FVector::ZeroVector);
        Flip.To = FVector(0, 0, 40);
        TestTrue(TEXT("A flip swinging the deck 40 cm about a rider at rest rides on"), Judge(Flip) == ERideLostSimulation::Kept);
    }
    return true;
}
#endif
