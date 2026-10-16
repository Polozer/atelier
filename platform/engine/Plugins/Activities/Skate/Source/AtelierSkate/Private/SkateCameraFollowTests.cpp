// Camera follow (CameraFollow, GameplayRuntime::Feel): the camera's anchor chases the rider through a VectorTracker
// capped at the authored SubjectTrackerMaxSpeed, 40 m/s, times camera_follow. At the stock cap a rider at 45 m/s pulls
// away from the camera by 5 m every second; at twice the cap the anchor stays on the rider.
#include "Simulation/CameraTracking.h"
#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FSkateCameraFollowTest, "AtelierSkate.Camera.Follow",
    EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// A named namespace, not an anonymous one or a using-directive: a unity build shares this file's scope with others.
namespace SkateCameraFollow
{
    using namespace atelier::skate;
    // The anchor's gap behind a rider riding straight at Speed m/s for Seconds, at 60 updates a second, with the
    // anchor's authored acceleration limit (10000) and no smoothing (AnchorRigTracking above 8 m/s).
    float Gap(float Speed, float Cap, float Seconds)
    {
        camera::ScalarTrackerParameters P{};
        P.speed_clamp = Cap;
        P.acceleration_clamp_min = P.acceleration_clamp_max = 10000.f;
        camera::VectorTracker T;
        const float Dt = 1.f / 60.f;
        T.velocity = {Speed, 0.f, 0.f, 0.f};
        Vec4 Rider{};
        for (int Update = 1; Update <= int(Seconds * 60.f); ++Update)
        {
            Rider[0] = Speed * Dt * Update;
            T.Update(Dt, Rider, P);
        }
        return Rider[0] - T.position[0];
    }
}

bool FSkateCameraFollowTest::RunTest(const FString&)
{
    using namespace SkateCameraFollow;
    TestTrue(TEXT("Stock cap: a rider at 30 m/s is followed"), Gap(30.f, 40.f, 3.f) < .01f);
    const float Stock = Gap(45.f, 40.f, 3.f), Doubled = Gap(45.f, 80.f, 3.f);
    TestTrue(TEXT("Stock cap: a rider at 45 m/s is 15 m ahead of the anchor after 3 s"), Stock > 14.9f && Stock < 15.1f);
    TestTrue(TEXT("Twice the cap: the anchor stays on the rider"), Doubled < .01f);
    TestTrue(TEXT("Twice the cap: a rider at 70 m/s is followed too"), Gap(70.f, 80.f, 3.f) < .01f);
    return true;
}
#endif
