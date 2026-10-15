// RideLostSimulation.h's verdicts, from the steps of a ride at 60 Hz: an overshot mega gap's landing (25-30 m/s,
// 15-20 of them into the ground) that the session's board missed, the session's recovery after its 5 s air, and the
// steps of ordinary riding that must ride on.
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
        S.State = State; S.Tick = 600; S.Dt = 1.f / 60.f;
        S.From = From; S.To = From + Velocity * S.Dt; S.Velocity = Velocity; S.Speed = float(Velocity.Size());
        return S;
    }
    // The step crossed a face at At with Normal (turned toward From), and ends under a face (bCovered) or in the open.
    FRideLostSimulationStep Crossing(FRideLostSimulationStep S, const FVector& At, const FVector& Normal, bool bCovered = true)
    {
        S.bCrossed = true; S.bCovered = bCovered; S.CrossedAt = At; S.CrossedNormal = Normal.GetSafeNormal();
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
    // Ordinary riding: the fastest frames ride on, and so does a slow frame at speed.
    {
        TestTrue(TEXT("30 m/s at 60 Hz rides on"), Judge(Moving(TEXT("PhysicsGround"), FVector::ZeroVector, FVector(3000, 0, 0))) == ERideLostSimulation::Kept);
        FRideLostSimulationStep Slow = Moving(TEXT("PhysicsAir"), FVector::ZeroVector, FVector(3000, 0, 0));
        Slow.Dt = .1f; Slow.To = Slow.From + Slow.Velocity * Slow.Dt;
        TestTrue(TEXT("A 100 ms frame at 30 m/s rides on"), Judge(Slow) == ERideLostSimulation::Kept);
        FRideLostSimulationStep Flip = Moving(TEXT("KnownAir"), FVector::ZeroVector, FVector::ZeroVector);
        Flip.To = FVector(0, 0, 40);
        TestTrue(TEXT("A flip swinging the deck 40 cm about a rider at rest rides on"), Judge(Flip) == ERideLostSimulation::Kept);
    }
    return true;
}
#endif
