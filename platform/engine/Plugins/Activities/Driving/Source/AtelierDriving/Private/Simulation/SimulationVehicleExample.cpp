#include "SimulationVehicle.h"

namespace atelier::driving
{
VehicleSpec Vehicle::example()
{
    VehicleSpec s;
    s.mass = 1450.0f;
    s.dimension = {0.9f, 0.62f, 2.2f};
    s.tensor_scale = VEC3_ONE;
    s.body = RigidBodySpec{};
    s.chassis.spring_stiffness[0] = 800.0f;
    s.chassis.spring_stiffness[1] = 700.0f;
    s.chassis.spring_progression[0] = 2.0f;
    s.chassis.spring_progression[1] = 2.0f;
    s.chassis.shock_stiffness[0] = 60.0f;
    s.chassis.shock_stiffness[1] = 55.0f;
    s.chassis.shock_ext_stiffness[0] = 80.0f;
    s.chassis.shock_ext_stiffness[1] = 75.0f;
    s.chassis.shock_valving[0] = 0.0f;
    s.chassis.shock_valving[1] = 0.0f;
    s.chassis.shock_digression[0] = 0.0f;
    s.chassis.shock_digression[1] = 0.0f;
    s.chassis.shock_blowout = 0.0f;
    s.chassis.swaybar_stiffness[0] = 120.0f;
    s.chassis.swaybar_stiffness[1] = 100.0f;
    s.chassis.travel[0] = 4.0f;
    s.chassis.travel[1] = 4.0f;
    s.chassis.ride_height[0] = 4.5f;
    s.chassis.ride_height[1] = 4.5f;
    s.chassis.track_width[0] = 1.55f;
    s.chassis.track_width[1] = 1.55f;
    s.chassis.wheel_base = 2.7f;
    s.chassis.front_axle = 1.4f;
    s.chassis.front_weight_bias = 55.0f;
    s.chassis.roll_center = 20.0f;

    s.tires.rim_size[0] = 17.0f;
    s.tires.rim_size[1] = 17.0f;
    s.tires.section_width[0] = 225.0f;
    s.tires.section_width[1] = 235.0f;
    s.tires.aspect_ratio[0] = 45.0f;
    s.tires.aspect_ratio[1] = 45.0f;
    s.tires.grip_scale[0] = 1.0f;
    s.tires.grip_scale[1] = 1.0f;
    s.tires.static_grip[0] = 1.05f;
    s.tires.static_grip[1] = 1.05f;
    s.tires.dynamic_grip[0] = 0.95f;
    s.tires.dynamic_grip[1] = 0.95f;
    s.tires.steering = 1.0f;
    s.tires.yaw_control = {1.0f, 0.8f, 0.6f};
    s.tires.yaw_speed = 1.0f;

    s.brakes.brakes[0] = 260.0f;
    s.brakes.brakes[1] = 170.0f;
    s.brakes.brake_lock[0] = 0.9f;
    s.brakes.brake_lock[1] = 0.9f;
    s.brakes.ebrake = 120.0f;

    s.engine.torque = {190.0f, 225.0f, 250.0f, 265.0f, 265.0f, 250.0f, 225.0f, 190.0f, 150.0f};
    s.engine.idle = 900.0f;
    s.engine.red_line = 7000.0f;
    s.engine.max_rpm = 8000.0f;
    s.engine.flywheel_mass = 20.0f;
    s.engine.engine_braking = {0.15f};
    s.engine.speed_limiter[0] = 0.0f;
    s.engine.speed_limiter[1] = 0.0f;
    s.engine.no_rev_limiter = false;

    s.transmission.gear_ratio = {3.4f, 0.0f, 3.6f, 2.2f, 1.5f, 1.1f, 0.9f, 0.75f};
    s.transmission.gear_efficiency.assign(8, 0.9f);
    s.transmission.final_gear = 3.7f;
    s.transmission.torque_split = 0.0f;
    s.transmission.differential[0] = 0.0f;
    s.transmission.differential[1] = 0.3f;
    s.transmission.differential[2] = 0.0f;
    s.transmission.torque_converter = 0.0f;
    s.transmission.clutch_slip = 0.3f;
    s.transmission.shift_speed = 0.1f;
    s.transmission.optimal_shift = 0.0f;

    s.induction = InductionSpec{};
    s.nos.nos_capacity = 5.0f;
    s.nos.torque_boost = 0.4f;
    s.nos.nos_disengage = 0.5f;
    s.nos.recharge_min = 25.0f;
    s.nos.recharge_max = 8.0f;
    s.nos.recharge_min_speed = 20.0f;
    s.nos.recharge_max_speed = 100.0f;

    s.aero.drag_coefficient = 0.35f;
    s.aero.aero_coefficient = 0.003f;
    s.aero.aero_cg = 50.0f;
    s.aero.airborne_scale = 0.1f;
    return s;
}
} // namespace atelier::driving
