// Wall-follow air (WallFollow, FeelTuning::wall_follow): the wall's plan curvature is measured riding a steep wall (a
// circle reads 1/R whichever way it is ridden and however finely it is faceted; a straight wall reads 0); an air turned
// at it stays over a circular lip that a straight air leaves (Crater Park's Vert drop U-turn: 95 m to the lip, 40 m/s
// along it), with its speed and climb unchanged; the predicted arc follows the turned air; and only a vert-aligned launch
// with vert assist and no transfer latches it, so a zero-assist zone or a transfer flies exactly as stock.
#include "Simulation/WallFollow.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSkateWallFollowTest, "AtelierSkate.Air.WallFollow",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// A named namespace, not an anonymous one or a using-directive: a unity build shares this file's scope with others.
namespace SkateWallFollow
{
    using namespace atelier::skate;
    constexpr float Dt = 1.f / 60.f;
    constexpr double Pi = 3.14159265358979323846;

    // Rides `Seconds` round a bowl's outer wall centred on the origin: the board `Radius` m out at `Speed` m/s
    // (positive: from +X towards +Z), the ground normal facing the centre and tilted `NormalY` up. Facets of
    // `FacetDegrees` (0 smooth) hold the normal of their middle. Returns the tracker after the ride.
    WallCurvatureTracker Ride(float Radius, float Speed, float NormalY, float FacetDegrees, float Seconds = .5f)
    {
        WallCurvatureTracker T;
        const double Horizontal = std::sqrt(1. - double(NormalY) * NormalY), Facet = FacetDegrees * Pi / 180.;
        for (int Update = 0; Update <= int(Seconds * 60.f); ++Update)
        {
            const double Angle = double(Speed) * Dt * Update / Radius;
            const double Face = Facet > 0 ? (std::floor(Angle / Facet) + .5) * Facet : Angle;
            const Vec3 Normal(float(-std::cos(Face) * Horizontal), NormalY, float(-std::sin(Face) * Horizontal));
            T.Observe(Normal, Vec3(float(Radius * std::cos(Angle)), 20.f, float(Radius * std::sin(Angle))), WallFollowSteepNormalY);
        }
        return T;
    }

    // The same ride along a straight wall facing -X.
    float StraightWall()
    {
        WallCurvatureTracker T;
        for (int Update = 0; Update <= 30; ++Update)
            T.Observe(Vec3(-.95f, .3f, 0.f), Vec3(95.f, 20.f, 40.f * Dt * Update), WallFollowSteepNormalY);
        return T.Curvature();
    }

    struct Flight { double WorstRadiusError, FinalRadius, SpeedChange, HeightError; };
    // An air off the U-turn's lip, 95 m from its centre: 40 m/s along the wall (+Z at (95, 34, 0)) and 10 m/s up, for
    // Seconds at 60 updates a second, each update turning the horizontal velocity by curvature x speed x dt (none:
    // stock). Its worst distance off the lip's circle, its last distance from the centre, the change in horizontal speed
    // and how far its height is from the stock air's.
    Flight Fly(float Curvature, float Seconds)
    {
        Vec3 P(95.f, 34.f, 0.f), V(0.f, 10.f, 40.f);
        double Worst = 0, Stock = 34;
        double StockV = 10;
        for (int Update = 0; Update < int(Seconds * 60.f); ++Update)
        {
            V.y -= 9.8f * Dt;StockV -= 9.8 * Dt;
            const float Speed = std::sqrt(V.x * V.x + V.z * V.z);
            V = YawAboutUp(V, Curvature * Speed * Dt);
            P.x += V.x * Dt;P.y += V.y * Dt;P.z += V.z * Dt;Stock += StockV * Dt;
            Worst = std::max(Worst, std::abs(std::sqrt(double(P.x) * P.x + double(P.z) * P.z) - 95.));
        }
        return {Worst, std::sqrt(double(P.x) * P.x + double(P.z) * P.z), std::sqrt(V.x * V.x + V.z * V.z) - 40., std::abs(P.y - Stock)};
    }

    // How far the predicted arc (AirTrajectoryPositionAt's WallFollowArcAt) ends from the air turned update by update,
    // after Seconds.
    double ArcError(float Curvature, float Seconds)
    {
        Vec3 P(95.f, 34.f, 0.f), V(0.f, 0.f, 40.f);
        for (int Update = 0; Update < int(Seconds * 60.f); ++Update)
        {
            V = YawAboutUp(V, Curvature * 40.f * Dt);
            P.x += V.x * Dt;P.z += V.z * Dt;
        }
        const auto A = WallFollowArcAt(0.f, 40.f, Curvature, 10.f, Seconds);
        return std::hypot(95. + A.dx - P.x, A.dz - P.z);
    }

    // The latch for a launch off the measured U-turn wall at the lip, 40 m/s along it (+Z), the wall facing -X.
    float Latch(float Strength, bool Aligned, float Assist, float Limit, float Transfer, std::uint32_t TicksSinceGround = 1,
        float WallRadius = 95.f, float Speed = 40.f)
    {
        WallFollowAir W;
        W.strength = Strength;W.tracker = Ride(WallRadius, Speed, .1f, .74f);W.ticks_since_ground = TicksSinceGround;
        return WallFollowLaunchCurvature(W, Aligned, Assist, Limit, Transfer, {0.f, 30.f, Speed, 0.f}, {-1.f, 0.f, 0.f, 0.f});
    }
}

bool FSkateWallFollowTest::RunTest(const FString&)
{
    using namespace SkateWallFollow;
    // The wall's curvature, ridden from +X towards +Z (the turn from +X towards +Z about +Y is negative).
    const float Smooth = Ride(95.f, 40.f, .1f, 0.f).Curvature(), Back = Ride(95.f, -40.f, .1f, 0.f).Curvature();
    TestTrue(TEXT("A smooth 95 m wall reads 1/95 within 1%"), std::abs(Smooth + 1.f / 95.f) < .01f / 95.f);
    TestTrue(TEXT("Ridden the other way it reads the opposite turn"), std::abs(Back - 1.f / 95.f) < .01f / 95.f);
    TestTrue(TEXT("The 55 m centre line's radius reads 1/55 within 1%"), std::abs(Ride(55.f, 40.f, .4f, 0.f).Curvature() + 1.f / 55.f) < .01f / 55.f);
    TestTrue(TEXT("Crater Park's riding facets (0.74 degrees at 95 m) read 1/95 within 10%"),
        std::abs(Ride(95.f, 40.f, .1f, .74f).Curvature() + 1.f / 95.f) < .1f / 95.f);
    TestTrue(TEXT("Coarse 3 degree facets read 1/95 within 30%"), std::abs(Ride(95.f, 40.f, .1f, 3.f).Curvature() + 1.f / 95.f) < .3f / 95.f);
    TestTrue(TEXT("A straight wall reads 0"), StraightWall() == 0.f);
    TestTrue(TEXT("Ground shallower than 41 degrees is not a wall"), Ride(95.f, 40.f, .8f, 0.f).Curvature() == 0.f);
    TestTrue(TEXT("Too short a ride (0.15 s) is not measured"), Ride(95.f, 40.f, .1f, 0.f, .15f).Curvature() == 0.f);
    TestTrue(TEXT("Tighter than 8 m is no wall to follow"), Ride(6.f, 10.f, .1f, 0.f).Curvature() == 0.f);
    TestTrue(TEXT("Wider than 400 m is straight"), Ride(600.f, 40.f, .1f, 0.f).Curvature() == 0.f);

    // The turn keeps the speed, and the turned air stays over the lip that the straight air leaves.
    const Vec3 Turned = YawAboutUp(Vec3(3.f, -7.f, 40.f), .3f);
    TestTrue(TEXT("Turning a velocity keeps its speed and its climb"),
        std::abs(std::sqrt(Turned.x * Turned.x + Turned.z * Turned.z) - std::sqrt(9.f + 1600.f)) < 1e-3f && Turned.y == -7.f);
    const auto Followed = Fly(Smooth, 2.f), Stock = Fly(0.f, 2.f);
    TestTrue(TEXT("Followed: 2 s of air stays within 0.3 m of the 95 m lip"), Followed.WorstRadiusError < .3);
    TestTrue(TEXT("Followed: the speed along the wall is kept"), std::abs(Followed.SpeedChange) < .01);
    TestTrue(TEXT("Followed: the height is the stock air's"), Followed.HeightError < 1e-3);
    TestTrue(TEXT("Stock: the same air ends over 25 m outside the lip"), Stock.FinalRadius - 95. > 25.);
    TestTrue(TEXT("The predicted arc follows the turned air within 0.5 m over 2 s"), ArcError(Smooth, 2.f) < .5);
    const auto Capped = WallFollowArcAt(0.f, 40.f, -1.f / 95.f, 1.f, 2.f);
    TestTrue(TEXT("Past its time the arc runs straight on, turned only as far as then"),
        std::abs(std::atan2(-Capped.vx, Capped.vz) - 40.f / 95.f) < 1e-4f);

    // The bend is towards the bowl's centre, never round behind a convex wall.
    TestTrue(TEXT("Inside the bowl the centre is in front of the wall"), WallFollowConcave(-1.f / 95.f, {0.f, 0.f, 40.f, 0.f}, {-1.f, 0.f, 0.f, 0.f}));
    TestTrue(TEXT("Outside a round pillar it is behind the wall"), !WallFollowConcave(-1.f / 95.f, {0.f, 0.f, 40.f, 0.f}, {1.f, 0.f, 0.f, 0.f}));

    // Only a vert-aligned launch with vert assist above zero and no transfer latches it.
    const float Full = Latch(1.f, true, 1.f, 1.f, 0.f);
    TestTrue(TEXT("A vert-aligned launch with assist, no transfer, latches the wall's curvature"), std::abs(Full + 1.f / 95.f) < .1f / 95.f);
    TestTrue(TEXT("Half strength latches half"), std::abs(Latch(.5f, true, 1.f, 1.f, 0.f) - Full * .5f) < 1e-7f);
    TestTrue(TEXT("Strength 0 (stock) never latches"), Latch(0.f, true, 1.f, 1.f, 0.f) == 0.f);
    TestTrue(TEXT("A zero-assist zone (limit 0) never latches"), Latch(1.f, true, 0.f, 0.f, 0.f) == 0.f && Latch(1.f, true, 1.f, 0.f, 0.f) == 0.f);
    TestTrue(TEXT("Vert assist 0 never latches"), Latch(1.f, true, 0.f, 1.f, 0.f) == 0.f);
    TestTrue(TEXT("A launch the stock alignment did not aim up the wall never latches"), Latch(1.f, false, 1.f, 1.f, 0.f) == 0.f);
    TestTrue(TEXT("A transfer never latches"), Latch(1.f, true, 1.f, 1.f, 1.f) == 0.f);
    TestTrue(TEXT("Any lean forward never latches"), Latch(1.f, true, 1.f, 1.f, .3f) == 0.f);
    TestTrue(TEXT("A wall left more than two updates ago never latches"), Latch(1.f, true, 1.f, 1.f, 0.f, 3) == 0.f);
    TestTrue(TEXT("A straight wall never latches"), Latch(1.f, true, 1.f, 1.f, 0.f, 1, 600.f) == 0.f);
    return true;
}
#endif
