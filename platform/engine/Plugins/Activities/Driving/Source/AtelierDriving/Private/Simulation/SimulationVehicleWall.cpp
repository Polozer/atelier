#include "SimulationVehicle.h"

namespace atelier::driving
{
float WallSteering::yaw(float steer, float gas, int grounded, bool reverse, float gain) const
{
    if (grounded <= 2)
    {
        return 0.0f;
    }
    const float command = steer * gas;
    if (nose != 0.0f && gas > 0.0f && nose * command < 0.0f)
    {
        return 0.0f;
    }
    if (reverse && side * command > 0.0f)
    {
        return -command * gain * std::fabs(side);
    }
    if (nose != 0.0f && gas > 0.0f)
    {
        return command * gain * std::fabs(nose);
    }
    return 0.0f;
}

void Vehicle::notify_wall_contact(Vec3 point, Vec3 normal, Vec3 closing_velocity, Vec3 body_velocity)
{
    const WallSteeringConfig c = wall_steering_config;
    if (c.yaw_gain == 0.0f || std::fabs(normal.y) >= c.maximum_normal_y ||
        length_squared(closing_velocity) >= c.maximum_closing_speed_squared)
    {
        return;
    }
    const Mat3 rot = body.rotation();
    const float lateral = dot(normal, rot.x_axis);
    const float reach = dot(point - body.position, rot.z_axis);
    const float end = spec.dimension.z * c.end_fraction;
    if (wall_steering_.nose == 0.0f && length_squared(body_velocity) < c.maximum_nose_speed_squared &&
        dot(normal, rot.z_axis) <= 0.0f && reach > end)
    {
        const float sign = lateral > 0.0f ? 1.0f : -1.0f;
        wall_steering_.nose = sign - lateral;
    }
    if (wall_steering_.side == 0.0f && dot(body_velocity, rot.z_axis) < 0.0f &&
        std::fabs(lateral) > c.side_epsilon && std::fabs(reach) > end)
    {
        wall_steering_.side = lateral;
    }
}

std::pair<Vec3, ContactParams> Vehicle::wall_reaction(Vec3 normal, ContactParams params) const
{
    const Vec3 cog = body.world_cog();
    const Vec3 centre{cog.x, body.position.y, cog.z};
    const Vec3 forward = body.rotation().z_axis;
    const float nose = -dot(normal, forward);
    const float closing = clamp(-dot(normal, body.linear_velocity) / 5.0f, 0.0f, 1.0f);
    const float damp = clamp((nose + 1.0f) / 2.0f, 0.0f, 1.0f);
    ContactParams adjusted = params;
    adjusted.restitution = 0.0f;
    adjusted.inertia_scale.y *= 1.0f + closing * damp * 8.0f;
    return {centre, adjusted};
}

void Vehicle::apply_wall_steering()
{
    const WallSteering pending = wall_steering_;
    wall_steering_ = WallSteering{};
    const float yaw = pending.yaw(controls_.steering, controls_.gas, wheels_on_ground_prev_,
                                  powertrain.gear_id() == GEAR_REVERSE, wall_steering_config.yaw_gain);
    body.angular_velocity += body.rotation().y_axis * yaw;
}
} // namespace atelier::driving
