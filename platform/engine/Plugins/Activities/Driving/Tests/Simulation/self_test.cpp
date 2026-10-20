#include "SimulationPerformance.h"
#include "SimulationRigidBody.h"
#include "SimulationVehicle.h"

#include <cmath>
#include <cstdio>

using namespace atelier::driving;

namespace
{
int failures = 0;

void check(bool condition, const char* what)
{
    if (!condition)
    {
        std::fprintf(stderr, "FAIL: %s\n", what);
        ++failures;
    }
}

void step(Vehicle& car, const Ground& ground, const InputState& input, int count)
{
    for (int i = 0; i < count; ++i)
    {
        car.step(FIXED_STEP, input, ground);
    }
}
} // namespace

int main()
{
    FlatGround flat(0.0f);

    {
        Vehicle car(Vehicle::example());
        check(car.place_on_ground(flat, 0.0f, 0.0f, 5.0f, 0.0f), "car placed on ground");
        InputState input;
        input.throttle = 1.0f;
        step(car, flat, input, 600);
        check(car.forward_speed() > 20.0f, "car accelerates");
        check(car.position().z > 100.0f, "car travels forward");
        check(car.wheels_on_ground() >= 2, "wheels carry the car");
        check(std::isfinite(car.position().x) && std::isfinite(car.orientation().w), "pose stays finite");
    }

    {
        Vehicle car(Vehicle::example());
        car.place_on_ground(flat, 0.0f, 0.0f, 5.0f, 0.0f);
        InputState input;
        input.throttle = 0.7f;
        step(car, flat, input, 180);
        input.steer = 0.7f;
        step(car, flat, input, 180);
        check(car.position().x > 1.0f, "positive steering turns right");
        check(std::fabs(car.wheel(0).steer_angle) > 0.01f, "front wheels steer");
    }

    {
        Vehicle car(Vehicle::example());
        car.place_on_ground(flat, 0.0f, 0.0f, 5.0f, 0.0f);
        InputState input;
        input.throttle = 1.0f;
        step(car, flat, input, 240);
        input.throttle = 0.0f;
        input.brake = 1.0f;
        step(car, flat, input, 600);
        check(car.forward_speed() < -1.0f, "brake pedal selects reverse");
        check(car.gear() == 0, "reverse gear engaged");
    }

    {
        Vehicle car(Vehicle::example());
        car.place_on_ground(flat, 0.0f, 0.0f, 5.0f, 0.0f);
        car.config.automatic = false;
        InputState input;
        input.throttle = 0.9f;
        const int first = car.gear();
        input.shift_up = true;
        car.step(FIXED_STEP, input, flat);
        input.shift_up = false;
        step(car, flat, input, 30);
        check(car.gear() > first, "manual upshift changes gear");
    }

    {
        Vehicle car(Vehicle::example());
        car.place_on_ground(flat, 0.0f, 0.0f, 5.0f, 0.0f);
        InputState input;
        for (int i = 0; i < 3000; ++i)
        {
            input.throttle = (i % 300) < 200 ? 0.8f : 0.2f;
            input.steer = 0.5f * std::sin(static_cast<float>(i) * 0.03f);
            input.handbrake = (i % 500) > 450 ? 0.6f : 0.0f;
            car.step(FIXED_STEP, input, flat);
        }
        check(std::isfinite(car.position().x) && std::isfinite(car.position().y) &&
                  std::isfinite(car.position().z),
              "mixed driving pose finite");
        for (int wheel = 0; wheel < 4; ++wheel)
        {
            const WheelState state = car.wheel(wheel);
            check(std::isfinite(state.load) && std::isfinite(state.slip) && std::isfinite(state.slip_angle),
                  "wheel state finite");
        }
    }

    {
        Sphere a{{0.0f, 0.0f, 0.0f}, 1.0f};
        Sphere b{{1.0f, 0.0f, 0.0f}, 1.0f};
        ObbContact contact;
        check(sphere_contact(a, b, contact), "overlapping spheres touch");
        b.centre = {3.0f, 0.0f, 0.0f};
        check(!sphere_contact(a, b, contact), "separated spheres miss");

        Obb unit{{0.0f, 0.0f, 0.0f}, MAT3_IDENTITY, VEC3_ONE};
        Obb shifted{{1.5f, 0.0f, 0.0f}, MAT3_IDENTITY, VEC3_ONE};
        check(obb_contact(unit, shifted, contact), "overlapping boxes touch");
        shifted.centre = {3.0f, 0.0f, 0.0f};
        check(!obb_contact(unit, shifted, contact), "separated boxes miss");
    }

    {
        RigidBody body(1000.0f, Vec3{1.0f, 0.5f, 2.0f}, VEC3_ONE, RigidBodySpec{});
        body.place({0.0f, 2.0f, 0.0f}, QUAT_IDENTITY);
        body.apply_force({0.0f, 0.0f, 1000.0f});
        body.begin_frame(FIXED_STEP);
        check(body.position.z > 0.0f && std::isfinite(body.linear_velocity.z), "rigid body integrates force");
    }

    {
        const performance::Performance p = performance::measure(Vehicle::example());
        check(p.top_speed > 30.0f && p.top_speed < 130.0f, "performance top speed plausible");
        check(p.acceleration[0] > 2.0f, "performance acceleration plausible");
    }

    if (failures != 0)
    {
        std::fprintf(stderr, "%d driving simulation checks failed\n", failures);
        return 1;
    }
    std::printf("driving simulation self-test passed\n");
    return 0;
}
