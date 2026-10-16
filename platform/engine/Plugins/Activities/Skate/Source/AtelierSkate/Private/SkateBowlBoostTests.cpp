// Boost zones (Simulation/BowlBoost.h): a tick's speed gain from pumping or powersliding on a boost zone's transition,
// at 60 Hz. Nothing outside a zone, with the setting at 0, or on ground under 12 degrees; a pump gains half as much
// again as itself; a slide gains instead of scrubbing; 200% doubles the gain; the cap holds.
#include "Simulation/BowlBoost.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include <cmath>

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSkateBowlBoostTest, "AtelierSkate.Ride.BowlBoost",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace SkateBowlBoost
{
    using atelier::skate::BowlBoost;
    constexpr float Dt = 1.f / 60.f;
    const float Wall = std::cos(30.f * PI / 180.f);   // the deck's up on a 30 degree transition
    const float Flat = 1.f;
    const float Gentle = std::cos(8.f * PI / 180.f);
}

bool FSkateBowlBoostTest::RunTest(const FString&)
{
    using namespace SkateBowlBoost;
    {
        BowlBoost B;
        TestEqual(TEXT("Outside every zone nothing is added"), B.Gain(false, 1.f, Wall, .05f, true, 10.f, 9.9f, Dt), 0.f);
        TestFalse(TEXT("Outside every zone the board is not inside one"), B.inside);
    }
    {
        BowlBoost B;
        TestEqual(TEXT("On a zone's flat bottom a pump adds nothing"), B.Gain(true, 1.f, Flat, .05f, false, 10.f, 10.05f, Dt), 0.f);
        TestEqual(TEXT("On 8 degree ground a powerslide adds nothing"), B.Gain(true, 1.f, Gentle, 0.f, true, 10.f, 9.9f, Dt), 0.f);
        TestTrue(TEXT("The zone's entry speed is the board's on coming in"), B.inside && B.entry == 10.f);
    }
    {
        BowlBoost B;
        const float Gain = B.Gain(true, 1.f, Wall, .05f, false, 10.f, 10.05f, Dt);
        TestTrue(TEXT("A pump on the transition gains 1.5 times its own speed more"), FMath::IsNearlyEqual(Gain, .075f, 1e-5f));
        BowlBoost Off;
        TestEqual(TEXT("With the setting at 0 (scale 0) a pump gains nothing"), Off.Gain(true, 0.f, Wall, .05f, false, 10.f, 10.05f, Dt), 0.f);
        BowlBoost Double;
        TestTrue(TEXT("At 200% a pump gains twice as much"),
            FMath::IsNearlyEqual(Double.Gain(true, 2.f, Wall, .05f, false, 10.f, 10.05f, Dt), 2.f * Gain, 1e-5f));
        BowlBoost Coasting;
        TestEqual(TEXT("Coasting up a transition (no pump, no slide) gains nothing"), Coasting.Gain(true, 1.f, Wall, 0.f, false, 10.f, 9.9f, Dt), 0.f);
    }
    {
        // A powerslide that took 0.08 m/s this tick: the keep is at most 6 m/s^2 (0.1 m/s a tick), the gain 2.5 m/s^2.
        BowlBoost B;
        const float Gain = B.Gain(true, 1.f, Wall, 0.f, true, 10.f, 9.92f, Dt);
        TestTrue(TEXT("A powerslide on the transition gets back what it took, and more"),
            FMath::IsNearlyEqual(Gain, .08f + 2.5f * Dt, 1e-5f) && 9.92f + Gain > 10.f);
        BowlBoost Hard;
        TestTrue(TEXT("A slide's keep is at most 6 m/s^2, so a climb still slows it"),
            FMath::IsNearlyEqual(Hard.Gain(true, 1.f, Wall, 0.f, true, 10.f, 9.7f, Dt), (6.f + 2.5f) * Dt, 1e-5f));
    }
    {
        // Into the zone at 20 m/s: the cap is 27 m/s at 100%, 34 m/s at 200%; under 18 m/s it is 18.
        BowlBoost B;
        B.Gain(true, 1.f, Flat, 0.f, false, 20.f, 20.f, Dt);
        TestEqual(TEXT("At the cap a pump adds nothing"), B.Gain(true, 1.f, Wall, .5f, false, 27.01f, 27.01f, Dt), 0.f);
        TestTrue(TEXT("Near the cap a pump adds only up to it"), FMath::IsNearlyEqual(B.Gain(true, 1.f, Wall, .5f, false, 26.9f, 26.9f, Dt), .1f, 1e-4f));
        BowlBoost Double;
        Double.Gain(true, 2.f, Flat, 0.f, false, 20.f, 20.f, Dt);
        TestTrue(TEXT("At 200% the cap rises with it"), Double.Gain(true, 2.f, Wall, .5f, false, 27.f, 27.f, Dt) > 0.f
            && Double.Gain(true, 2.f, Wall, .5f, false, 34.01f, 34.01f, Dt) == 0.f);
        BowlBoost Slow;
        Slow.Gain(true, 1.f, Flat, 0.f, false, 5.f, 5.f, Dt);
        TestTrue(TEXT("A slow entry may still be boosted up to 18 m/s"), Slow.Gain(true, 1.f, Wall, .5f, false, 17.f, 17.f, Dt) > 0.f
            && Slow.Gain(true, 1.f, Wall, .5f, false, 18.f, 18.f, Dt) == 0.f);
        // Pumping round and round never runs away: 600 ticks of strong pumps stop at the cap.
        BowlBoost Loop;
        float Speed = 15.f;
        for (int32 I = 0; I < 600; ++I) Speed += Loop.Gain(true, 1.f, Wall, .2f, false, Speed, Speed, Dt);
        TestTrue(TEXT("A long run of pumps stops at the cap"), FMath::IsNearlyEqual(Speed, 20.25f, 1e-3f));
    }
    {
        BowlBoost B;
        B.Gain(true, 1.f, Wall, 0.f, false, 20.f, 20.f, Dt);
        B.Gain(false, 0.f, Wall, 0.f, false, 12.f, 12.f, Dt);
        B.Gain(true, 1.f, Flat, 0.f, false, 12.f, 12.f, Dt);
        TestEqual(TEXT("Leaving a zone and coming back takes the new entry speed"), B.entry, 12.f);
        TestEqual(TEXT("A nonfinite speed adds nothing"), B.Gain(true, 1.f, Wall, .05f, false, NAN, 10.f, Dt), 0.f);
        TestTrue(TEXT("A nonfinite speed leaves the zone's entry as it was"), B.inside && B.entry == 12.f);
    }
    {
        // The session's ticks (BowlBoost::Tick, as GameplaySession::ApplyBoost calls it) through one zone, its scale
        // unchanged: in at 20 m/s on the ground (cap 27 m/s), a hop inside the same box, landed near the cap. The air
        // gains nothing and keeps the board in the zone, so the landing keeps the cap of 27 m/s (it took the landing's
        // 26.9 m/s as a new entry, and a 36.3 m/s cap, before).
        BowlBoost B;
        B.Tick(1.f, 1.f, true, Flat, 0.f, false, 20.f, 20.f, Dt);
        TestTrue(TEXT("Into the zone on the ground at 20 m/s"), B.inside && B.entry == 20.f);
        float Air = 0.f;
        for (int32 I = 0; I < 40; ++I) Air += B.Tick(1.f, 1.f, false, Wall, .5f, true, 26.f + I * .02f, 26.02f + I * .02f, Dt);
        TestEqual(TEXT("In the air the zone adds nothing"), Air, 0.f);
        TestTrue(TEXT("In the air the board is still in the zone, with its entry speed"), B.inside && B.entry == 20.f);
        TestTrue(TEXT("Landed at 26.9 m/s, a pump adds only up to the first cap"),
            FMath::IsNearlyEqual(B.Tick(1.f, 1.f, true, Wall, .5f, false, 26.9f, 26.9f, Dt), .1f, 1e-4f));
        TestEqual(TEXT("At 27 m/s after the landing a pump adds nothing"), B.Tick(1.f, 1.f, true, Wall, .5f, false, 27.01f, 27.01f, Dt), 0.f);
        TestTrue(TEXT("The landing kept the entry speed"), B.entry == 20.f);
        // Out of the zone (scale 0) the next one starts afresh, from the ground or the air.
        B.Tick(0.f, 1.f, false, Wall, 0.f, false, 26.f, 26.f, Dt);
        TestFalse(TEXT("Out of every zone the board is in none"), B.inside);
        B.Tick(1.f, 1.f, false, Wall, 0.f, false, 15.f, 15.f, Dt);
        TestTrue(TEXT("Into a zone in the air takes the speed it came in with"), B.inside && B.entry == 15.f);
        BowlBoost Off;
        TestEqual(TEXT("With the setting at 0 the session's tick gains nothing"), Off.Tick(1.f, 0.f, true, Wall, .5f, false, 10.f, 10.f, Dt), 0.f);
    }
    return true;
}
#endif
