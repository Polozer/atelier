// Grind tolerance (FeelTuning::grind_tolerance): at 2 a grind rides through twice the push off its pose and twice the
// deck twist that bail at 1, and its entry half as much more speed across the rail and impact snapping on; a slam
// past those, or an entry pitched steeply along the rail, still bails. The limits are the authored ones
// (settings.json, physics_wipeout).
#include "Simulation/GrindForces.h"
#include "Simulation/PlayerGrindEntry.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include <algorithm>
#include <cmath>

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSkateGrindToleranceTest, "AtelierSkate.Grind.Tolerance",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// A named namespace, not an anonymous one or a using-directive: a unity build shares this file's scope with others.
namespace SkateGrindTolerance
{
    using atelier::skate::GrindPostSettings; using atelier::skate::WipeoutFrame; using atelier::skate::WipeoutRequests;
    using atelier::skate::Vec4;
    // Wipeout_GroundSkeletonMaxContactArms, ...MaxContact, Wipeout_GrindXZDeck, ...SkeletonMaxDisp, ...MaxAngularDeckError.
    const GrindPostSettings Stock{30.f, 8.5f, 6.f, 2.f, 1.3f};
    constexpr float Impact = 8.f;   // Wipeout_AirMaxSpeedIntoCollisionNearGrind

    // A grind frame with the body Push off its pose and the deck turned Twist radians about up from its target.
    WipeoutFrame Riding(float Push, float Twist)
    {
        WipeoutFrame F;
        F.pose_error = {Push, 0.f, 0.f, 0.f};
        const float C = std::cos(Twist), S = std::sin(Twist);
        F.deck = {Vec4{C, 0.f, -S, 0.f}, Vec4{0.f, 1.f, 0.f, 0.f}, Vec4{S, 0.f, C, 0.f}, Vec4{0.f, 0.f, 0.f, 1.f}};
        F.input_board = {Vec4{1.f, 0.f, 0.f, 0.f}, Vec4{0.f, 1.f, 0.f, 0.f}, Vec4{0.f, 0.f, 1.f, 0.f}, Vec4{0.f, 0.f, 0.f, 1.f}};
        return F;
    }
    bool Bails(const WipeoutFrame& F, float Tolerance)
    {
        WipeoutRequests State;
        atelier::skate::CheckGrindPost(State, atelier::skate::GrindPostTolerance(Stock, Tolerance), F);
        return std::any_of(State.reasons.begin(), State.reasons.end(), [](bool R) { return R; });
    }
    // An entry along +X onto a thin rail, the board crossing it at Across and snapping on with an Impact change.
    std::vector<std::size_t> Entry(float Across, float Snap, float Tolerance, Vec4 Direction = {1.f, 0.f, 0.f, 0.f})
    {
        const float Share = (1.f + Tolerance) * .5f;
        const Vec4 Board{5.f, 0.f, Across, 0.f}, Corrected{5.f, 0.f, Across + Snap, 0.f};
        return atelier::skate::PlayerGrindAirborneRejections(Direction, {0.f, 1.f, 0.f, 0.f}, Board, Board, Corrected, 0,
            {0.f, 0.f, 1.f, 0.f}, Impact * Share, 7.f * Share);
    }
}

bool FSkateGrindToleranceTest::RunTest(const FString&)
{
    using namespace SkateGrindTolerance;
    using atelier::skate::GrindPostTolerance;
    TestFalse(TEXT("A steady grind rides"), Bails(Riding(.5f, .1f), 1.f));
    TestTrue(TEXT("Stock: the body pushed 3 off its pose bails"), Bails(Riding(3.f, .1f), 1.f));
    TestFalse(TEXT("Tolerance 2: the same push rides"), Bails(Riding(3.f, .1f), 2.f));
    TestTrue(TEXT("Tolerance 2: pushed 5 still bails"), Bails(Riding(5.f, .1f), 2.f));
    TestTrue(TEXT("Stock: the deck twisted 90 degrees off its target bails"), Bails(Riding(.5f, 1.57f), 1.f));
    TestFalse(TEXT("Tolerance 2: the same twist rides"), Bails(Riding(.5f, 1.57f), 2.f));
    TestTrue(TEXT("Tolerance 1 is stock, bit for bit"), GrindPostTolerance(Stock, 1.f).max_angular_deck_error_212 == Stock.max_angular_deck_error_212
        && GrindPostTolerance(Stock, 1.f).y_acceleration == 100.f);

    TestTrue(TEXT("A clean entry is taken"), Entry(1.f, 1.f, 2.f).empty());
    TestTrue(TEXT("Stock: 9 m/s across the rail bails"), Entry(9.f, 0.f, 1.f).size() == 1);
    TestTrue(TEXT("Tolerance 2: 9 m/s across is taken"), Entry(9.f, 0.f, 2.f).empty());
    TestTrue(TEXT("Tolerance 2: landing sideways at 12 m/s still bails"), !Entry(12.f, 0.f, 2.f).empty());
    TestTrue(TEXT("Stock: a 10 m/s snap onto the rail bails"), !Entry(0.f, 10.f, 1.f).empty());
    TestTrue(TEXT("Tolerance 2: the same snap is taken"), Entry(0.f, 10.f, 2.f).empty());
    TestTrue(TEXT("Tolerance 2: a 14 m/s slam still bails"), !Entry(0.f, 14.f, 2.f).empty());
    TestTrue(TEXT("Tolerance 2: an entry pitched 37 degrees along the rail still bails"),
        Entry(0.f, 0.f, 2.f, {.8f, .6f, 0.f, 0.f}).size() == 1);
    return true;
}
#endif
