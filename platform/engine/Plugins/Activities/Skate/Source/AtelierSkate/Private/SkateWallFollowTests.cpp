// Wall-follow air (WallFollow, FeelTuning::wall_follow): the wall's plan curvature is measured riding a steep wall (a
// circle reads 1/R whichever way it is ridden and however finely it is faceted; a straight wall reads 0); an air turned
// at it (leaving the wall straight up) stays over a circular lip that a straight air leaves (Crater Park's Vert drop U-turn: 95 m to the lip, 40 m/s
// along it), with its speed and climb unchanged; the predicted arc follows the turned air, and the landing query's chords
// over it stay as close to it as stock's to a parabola; and only a vert-aligned launch with vert assist and no transfer
// latches it, so a zero-assist zone or a transfer flies exactly as stock.
#include "Simulation/WallFollow.h"
#include "Simulation/AirTrajectoryQuery.h"
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

    struct Flight { double WorstRadiusError, WorstOutside, FinalRadius, SpeedChange, HeightError; };
    // An air off the U-turn's lip, 95 m from its centre: 40 m/s along the wall (+Z at (95, 34, 0)) and 10 m/s up, for
    // Seconds at 60 updates a second in the session's order: the physics step moves the air on its velocity, then
    // AdvanceWallFollowAir turns that velocity by curvature x speed x dt (none: stock). Its worst distance off the lip's
    // circle, its furthest outside it, its last distance from the centre, the change in horizontal speed and how far its
    // height is from the stock air's.
    Flight Fly(float Curvature, float Seconds, float Outward = 0.f)
    {
        Vec3 P(95.f, 34.f, 0.f), V(Outward, 10.f, 40.f);
        double Worst = 0, Outside = 0, Stock = 34;
        double StockV = 10;
        for (int Update = 0; Update < int(Seconds * 60.f); ++Update)
        {
            V.y -= 9.8f * Dt;StockV -= 9.8 * Dt;
            P.x += V.x * Dt;P.y += V.y * Dt;P.z += V.z * Dt;Stock += StockV * Dt;
            V = YawAboutUp(V, Curvature * std::sqrt(V.x * V.x + V.z * V.z) * Dt);
            const double Off = std::sqrt(double(P.x) * P.x + double(P.z) * P.z) - 95.;
            Worst = std::max(Worst, std::abs(Off));Outside = std::max(Outside, Off);
        }
        return {Worst, Outside, std::sqrt(double(P.x) * P.x + double(P.z) * P.z), std::sqrt(V.x * V.x + V.z * V.z) - 40., std::abs(P.y - Stock)};
    }

    // How far the predicted arc (AirTrajectoryPositionAt's WallFollowArcAt) ends from the air turned update by update
    // (in the session's order, as Fly), after Seconds.
    double ArcError(float Curvature, float Seconds)
    {
        Vec3 P(95.f, 34.f, 0.f), V(0.f, 0.f, 40.f);
        for (int Update = 0; Update < int(Seconds * 60.f); ++Update)
        {
            P.x += V.x * Dt;P.z += V.z * Dt;
            V = YawAboutUp(V, Curvature * 40.f * Dt);
        }
        const auto A = WallFollowArcAt(0.f, 40.f, Curvature, 10.f, Seconds);
        return std::hypot(95. + A.dx - P.x, A.dz - P.z);
    }

    // The landing query (QueryAirTrajectory) over a 4 s air from the origin, 10 m/s up and 40 m/s along +Z, turning at
    // Curvature throughout, as the air selector asks it (sweep radius 0.2 m, chord errors 0.25 and 1.2 of it), against a
    // world that records each swept segment and hits nothing. How far the path at the first chord's middle is from
    // every segment, and the furthest any point of the path is from them all.
    struct Chords { std::size_t Segments; double FirstMiddle, Worst; };
    Chords Query(float Curvature)
    {
        struct Recorder : AirTrajectoryWorldQueries
        {
            std::vector<std::pair<Vec4, Vec4>> Segments;
            bool Line(Vec4 Start, Vec4 End, float, std::optional<AirTrajectorySurfaceHit>& Hit, std::string&) override
            {
                Segments.push_back({Start, End});Hit.reset();return true;
            }
            bool Nearby(Vec4, float, std::vector<std::array<Vec4, 3>>& Triangles, std::string&) override { Triangles.clear();return true; }
        } World;
        AirTrajectory T;
        T.position = {0.f, 0.f, 0.f, 0.f};T.velocity = {0.f, 10.f, 40.f, 0.f};T.acceleration = {0.f, -9.8f, 0.f, 0.f};
        T.scalar_48 = 4.f;T.wall_curvature = Curvature;T.wall_follow_time = Curvature != 0.f ? 4.f : 0.f;
        AirTrajectoryQueryResult Result;
        std::string Error;
        QueryAirTrajectory({T, .2f, .25f, 1.2f}, World, Result, Error);
        const auto Nearest = [&World](Vec4 P)
        {
            double Best = 1e30;
            for (const auto& [A, B] : World.Segments)
            {
                double D[3], Q[3], DD = 0, DQ = 0;
                for (int I = 0; I < 3; ++I) { D[I] = double(B[I]) - A[I];Q[I] = double(P[I]) - A[I];DD += D[I] * D[I];DQ += D[I] * Q[I]; }
                const double F = DD > 0 ? std::clamp(DQ / DD, 0., 1.) : 0.;
                double Square = 0;
                for (int I = 0; I < 3; ++I) Square += (Q[I] - F * D[I]) * (Q[I] - F * D[I]);
                Best = std::min(Best, std::sqrt(Square));
            }
            return Best;
        };
        if (World.Segments.empty()) return {0, 1e30, 1e30};
        // The first chord's end time: where along the path its end point lies.
        double FirstEnd = 0, Closest = 1e30;
        for (double Time = 0; Time <= 4.; Time += 1e-4)
        {
            const Vec4 P = AirTrajectoryPositionAt(T, float(Time));
            const double D = std::hypot(std::hypot(P[0] - World.Segments[0].second[0], P[1] - World.Segments[0].second[1]),
                P[2] - World.Segments[0].second[2]);
            if (D < Closest) { Closest = D;FirstEnd = Time; }
        }
        double Worst = 0;
        for (double Time = 0; Time < 3.99; Time += 1. / 600.) Worst = std::max(Worst, Nearest(AirTrajectoryPositionAt(T, float(Time))));
        return {World.Segments.size(), Nearest(AirTrajectoryPositionAt(T, float(FirstEnd / 2.))), Worst};
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
    TestTrue(TEXT("Crater Park's riding facets (0.74 degrees at 95 m) read 1/95 within 5%"),
        std::abs(Ride(95.f, 40.f, .1f, .74f).Curvature() + 1.f / 95.f) < .05f / 95.f);
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
    // A launch latches the measured curvature WallFollowMargin tight: the turned air comes down a little inside the lip.
    // At the wall's exact curvature, turned after each step, it drifts outside it (0.32 m after 3 s).
    const float Latched = Smooth * WallFollowMargin;
    const auto Followed = Fly(Latched, 2.f), Long = Fly(Latched, 3.f), Stock = Fly(0.f, 2.f);
    TestTrue(TEXT("Exact curvature, turned after each step: 3 s of air drifts outside the lip"), Fly(Smooth, 3.f).WorstOutside > .25);
    TestTrue(TEXT("Followed: 2 s of air stays within 1 m of the 95 m lip, never 0.05 m outside it"),
        Followed.WorstRadiusError < 1. && Followed.WorstOutside < .05);
    TestTrue(TEXT("Followed: 3 s of air stays within 2 m of the lip, never 0.05 m outside it"), Long.WorstRadiusError < 2. && Long.WorstOutside < .05);
    // Off the faceted wall the radius reads 2% wide and latches 3% tight of that, about 5% tight: further inside.
    const auto FacetedFlight = Fly(Latch(1.f, true, 1.f, 1.f, 0.f), 3.f);
    TestTrue(TEXT("Followed: the faceted wall's latch stays within 3.5 m of the lip over 3 s, never 0.05 m outside it"),
        FacetedFlight.WorstRadiusError < 3.5 && FacetedFlight.WorstOutside < .05);
    TestTrue(TEXT("Followed: the speed along the wall is kept"), std::abs(Followed.SpeedChange) < .01);
    TestTrue(TEXT("Followed: the height is the stock air's"), Followed.HeightError < 1e-3);
    TestTrue(TEXT("Stock: the same air ends over 25 m outside the lip"), Stock.FinalRadius - 95. > 25.);
    TestTrue(TEXT("The predicted arc follows the turned air within 0.5 m over 2 s"), ArcError(Latched, 2.f) < .5);
    // The landing query's chords keep to the turned arc as closely as stock's to a parabola, however tight the turn (1/8 m
    // at 40 m/s: 200 m/s^2 towards the centre): they sag from it at most the start error x the sweep radius at first
    // (0.05 m) and the end error x it by the end (0.24 m). Before the chords were bounded by the turn, the tight arc's
    // first chord missed its middle by 1 m and the U-turn's chords sagged 0.4 m.
    const auto StockChords = Query(0.f), Tight = Query(-1.f / 8.f), UTurn = Query(Latched);
    TestTrue(TEXT("Stock: the query's first chord within 0.05 m of the parabola, every chord within 0.24 m"),
        StockChords.FirstMiddle < .051 && StockChords.Worst < .241);
    TestTrue(TEXT("A tight turned arc: the first chord within 0.05 m of the path"), Tight.FirstMiddle < .051);
    TestTrue(TEXT("A tight turned arc: every chord within 0.24 m of the path"), Tight.Worst < .241);
    TestTrue(TEXT("The U-turn's turned arc: the first chord within 0.05 m, every chord within 0.24 m"), UTurn.FirstMiddle < .051 && UTurn.Worst < .241);
    const auto Capped = WallFollowArcAt(0.f, 40.f, -1.f / 95.f, 1.f, 2.f);
    TestTrue(TEXT("Past its time the arc runs straight on, turned only as far as then"),
        std::abs(std::atan2(-Capped.vx, Capped.vz) - 40.f / 95.f) < 1e-4f);

    // The air leaves the wall straight up: speed away from the wall is dropped, along it and into the bowl kept.
    const Vec3 Out = WallFollowInward(Vec3(.3f, 17.f, 30.f), -1.f, 0.f), In = WallFollowInward(Vec3(-.3f, 17.f, 30.f), -1.f, 0.f);
    TestTrue(TEXT("Speed away from the wall is dropped"), Out.x == 0.f && Out.y == 17.f && Out.z == 30.f);
    TestTrue(TEXT("Speed into the bowl is kept"), In.x == -.3f && In.z == 30.f);
    const auto Drifting = Fly(Latched, 3.f, .3f), Straightened = Fly(Latched, 3.f, 0.f);
    TestTrue(TEXT("0.3 m/s away from the wall carries a turned air outside the lip"), Drifting.WorstOutside > .15);
    TestTrue(TEXT("Dropped, the turned air stays inside it"), Straightened.WorstOutside < .05);

    // The bend is towards the bowl's centre, never round behind a convex wall.
    TestTrue(TEXT("Inside the bowl the centre is in front of the wall"), WallFollowConcave(-1.f / 95.f, {0.f, 0.f, 40.f, 0.f}, {-1.f, 0.f, 0.f, 0.f}));
    TestTrue(TEXT("Outside a round pillar it is behind the wall"), !WallFollowConcave(-1.f / 95.f, {0.f, 0.f, 40.f, 0.f}, {1.f, 0.f, 0.f, 0.f}));

    // Only a vert-aligned launch with vert assist above zero and no transfer latches it.
    const float Full = Latch(1.f, true, 1.f, 1.f, 0.f);
    TestTrue(TEXT("A vert-aligned launch with assist, no transfer, latches the wall's curvature, a little tight"),
        Full < -1.f / 95.f && Full > -1.1f / 95.f);
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
