// Slide hold (GrindTolerance above 1, GameplayRuntime::Feel): a slide's lean-off clock runs slide_hold times slower,
// so a tail slide ridden into a coping is tipped off after about 4 s, not 1.3 s, while a 50-50's timing is stock; and
// the tip spring a tail or nose slide gets pulls the middle of its tip zone back onto the line.
#include "Simulation/GrindForces.h"
#include "Simulation/PlayerGrindBalance.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSkateSlideHoldTest, "AtelierSkate.Grind.SlideHold",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// A named namespace, not an anonymous one or a using-directive: a unity build shares this file's scope with others.
namespace SkateSlideHold
{
    using namespace atelier::skate;
    // ExitLeanAngleVsTime as authored (settings.json, physics_grinds): 0 until 0.65 s, 14 at 1.08 s, 28 at 1.24 s.
    PointGraph<8> Lean()
    {
        PointGraph<8> G;
        G.x = {0.f, .65f, 1.08f, 1.24f, 1.6f, 2.f, 3.f, 4.f};
        G.y = {0.f, 0.f, 14.f, 28.f, 40.f, 50.f, 60.f, 60.f};
        return G;
    }
    // Seconds ridden into a coping on a ledge, at 60 updates a second, until the lean passes 28 degrees (forced off).
    float SecondsHeld(std::uint32_t Family, float Hold)
    {
        PlayerGrindSurface S{};
        S.kind = PlayerGrindGeometryKind::Ledge;
        S.upmost_normal = S.tilted_upmost_normal = {0.f, 1.f, 0.f, 0.f};
        S.high_side = {0.f, 0.f, 1.f, 0.f};
        const PlayerGrindBalanceContact C{S, {1.f, 0.f, 0.f, 0.f}, {1.f, 0.f, 0.f, 0.f}, Family, PlayerGrindEntryKind::RideIntoCoping};
        PlayerGrindBalanceState B;
        const auto Graph = Lean();
        for (int Update = 1; Update < 1200; ++Update)
        {
            PlayerGrindBalanceVectors V{{0.f, 1.f, 0.f, 0.f}, {0.f, 1.f, 0.f, 0.f}};
            if (B.UpdateExitLean({400, 402, 1, 1.f / 60.f, Hold}, &C, Graph, V) > 28.f) return Update / 60.f;
        }
        return 20.f;
    }
}

bool FSkateSlideHoldTest::RunTest(const FString&)
{
    using namespace SkateSlideHold;
    const float StockSlide = SecondsHeld(2, 1.f), HeldSlide = SecondsHeld(2, 3.f), HeldFifty = SecondsHeld(0, 3.f);
    TestTrue(TEXT("Stock: a tail slide into a coping is tipped off at about 1.3 s"), StockSlide > 1.2f && StockSlide < 1.5f);
    TestTrue(TEXT("Held 3 times: it holds about 4 s"), HeldSlide > 3.7f && HeldSlide < 4.2f);
    TestTrue(TEXT("A 50-50 keeps the stock timing"), HeldFifty == SecondsHeld(0, 1.f) && HeldFifty < 1.5f);
    TestTrue(TEXT("Hold 1 is stock for a slide too"), SecondsHeld(2, 1.f) == StockSlide);

    // A board across a coping along +X, its nose (+Z) on the line; drifted so the line sits 5 cm short of the tip zone's
    // middle (0.35 m out), the spring pulls the board toward it, along +Z.
    const Mat4 Board{Vec4{1.f, 0.f, 0.f, 0.f}, Vec4{0.f, 1.f, 0.f, 0.f}, Vec4{0.f, 0.f, 1.f, 0.f}, Vec4{0.f, 0.f, 0.f, 1.f}};
    const Vec4 Across{0.f, 0.f, 1.f, 0.f}, Still{0.f, 0.f, 0.f, 0.f};
    const auto Out = GrindLateralPin(Board, {0.f, 0.f, .40f, 1.f}, Across, Still, 3000.f, .35f, .025f, true, 1.f);
    TestTrue(TEXT("The tip spring pulls the drifted board back onto the line"), Out && (*Out)[2] > 100.f);
    const auto Tail = GrindLateralPin(Board, {0.f, 0.f, -.30f, 1.f}, Across, Still, 3000.f, .35f, .025f, false, 1.f);
    TestTrue(TEXT("On the tail, the other way"), Tail && (*Tail)[2] > 100.f);
    return true;
}
#endif
