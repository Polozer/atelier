// SkateCollisionCoverage.h's plans: at rest the old rule, at speed across a gap a world asked for early and ahead, a
// falling board's landing below it covered, and a board about to leave its world waiting for one.
#include "SkateCollisionCoverage.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSkateCollisionCoverageTest, "AtelierSkate.Ride.CollisionCoverage",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FSkateCollisionCoverageTest::RunTest(const FString&)
{
    using namespace SkateCoverage;
    // A dense place's world: 35 m half size, its reach 21 m, about the origin. A build took half a second (a 1 s lead).
    const FVector Centre = FVector::ZeroVector;
    const double Radius = 3500., Reach = Radius * ReachFraction, Build = .5, G = 980.;
    TestTrue(TEXT("The lead is half a build again and a quarter second"), FMath::IsNearlyEqual(Lead(Build), 1.));
    TestTrue(TEXT("The lead is at least a quarter second"), FMath::IsNearlyEqual(Lead(0.), ShortestLead));
    TestTrue(TEXT("The lead is at most two seconds"), FMath::IsNearlyEqual(Lead(10.), LongestLead));

    // At rest the old rule: inside the reach kept, past it rebuilt about the board.
    {
        const FSkateCoveragePlan In = Plan(Centre, Reach, FVector(2000, 0, 0), FVector::ZeroVector, 0., Build);
        TestTrue(TEXT("A board at rest inside the reach keeps its world"), In.Refresh == ESkateCoverage::Keep);
        const FSkateCoveragePlan Out = Plan(Centre, Reach, FVector(2200, 0, 0), FVector::ZeroVector, 0., Build);
        TestTrue(TEXT("A board at rest past the reach rebuilds"), Out.Refresh == ESkateCoverage::Rebuild);
        TestTrue(TEXT("... about itself"), Out.Target.Equals(FVector(2200, 0, 0)));
    }
    // Off a lip at 30 m/s, 10 m from the centre: the old rule waited 11 m more (a third of a second) to ask, and the board
    // was past this cube's face (35 m) before that world came in, half a second later. Now it is asked for here, ahead.
    {
        const FVector At(1000, 0, 0), Velocity(3000, 0, 900);
        TestTrue(TEXT("The old rule kept this world"), (At - Centre).GetAbsMax() <= Reach);
        const FSkateCoveragePlan P = Plan(Centre, Reach, At, Velocity, G, Build);
        TestTrue(TEXT("A fast air asks for a world before the reach"), P.Refresh == ESkateCoverage::Rebuild);
        TestTrue(TEXT("... centred ahead along its travel"), P.Target.X > At.X + 1500.);
        TestTrue(TEXT("... that still holds the board's place now"), (P.Target - At).GetAbsMax() <= Reach + 1.);
    }
    // Falling 20 m/s, 15 m under the centre: the landing 25 m below the board is outside this world (its floor 35 m
    // down). The world asked for is centred below, so its cube reaches past the landing.
    {
        const FVector At(0, 0, -1500), Velocity(0, 0, -2000);
        const FSkateCoveragePlan P = Plan(Centre, Reach, At, Velocity, G, Build);
        TestTrue(TEXT("A falling board asks for a world"), P.Refresh == ESkateCoverage::Rebuild);
        TestTrue(TEXT("... centred below it"), P.Target.Z < At.Z - 2000.);
        TestTrue(TEXT("... whose cube holds the landing 25 m down"), P.Target.Z - Radius < At.Z - 2500.);
    }
    // On the ground the board follows the floor: no fall is added.
    TestTrue(TEXT("A riding board is looked ahead along its velocity"),
        Predict(FVector::ZeroVector, FVector(1000, 0, -200), 1., 0.).Equals(FVector(1000, 0, -200)));
    TestTrue(TEXT("An airborne one falls"), FMath::IsNearlyEqual(Predict(FVector::ZeroVector, FVector::ZeroVector, 1., G).Z, -490.));
    // 30 m from the centre at 30 m/s: out of the world within a tenth of a second.
    {
        const FSkateCoveragePlan P = Plan(Centre, Reach, FVector(3000, 0, 0), FVector(3000, 0, 0), 0., Build);
        TestTrue(TEXT("A board about to leave its world needs one now"), P.Refresh == ESkateCoverage::Now);
        TestTrue(TEXT("A world about it would hold it"), Covers(FVector(3000, 0, 0), Radius, Predict(FVector(3000, 0, 0), FVector(3000, 0, 0), SoonSeconds, 0.)));
    }
    // The slowest recent build: a slow one counts at once, a fast one lets it fade.
    TestTrue(TEXT("A slower build is the new slowest"), FMath::IsNearlyEqual(NextBuildSeconds(.5, .9), .9));
    TestTrue(TEXT("After a faster one the slowest fades by a fifth"), FMath::IsNearlyEqual(NextBuildSeconds(1., .3), .8));
    return true;
}
#endif
