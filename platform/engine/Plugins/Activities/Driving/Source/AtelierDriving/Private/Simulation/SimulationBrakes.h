#pragma once

#include "SimulationSpec.h"

namespace atelier::driving
{
inline constexpr float BRAKING_TORQUE_SCALE = 4.0f;
inline constexpr float EBRAKING_TORQUE_SCALE = 10.0f;

inline float brake_torque(const BrakeSpec& b, int axle)
{
    return b.brakes[axle] * FT_LB_TO_NM * BRAKING_TORQUE_SCALE;
}
inline float brake_lock_torque(const BrakeSpec& b, int axle)
{
    return b.brake_lock[axle] * brake_torque(b, axle);
}
inline float ebrake_torque(const BrakeSpec& b)
{
    return b.ebrake * FT_LB_TO_NM * EBRAKING_TORQUE_SCALE;
}

struct BrakeContext
{
    float brake = 0.0f;
    float ebrake = 0.0f;
    float gas = 0.0f;
    float speed = 0.0f;
    float slip_angle = 0.0f;
    float tuning = 0.0f;
};

struct BrakeCommand
{
    float brake = 0.0f;
    float ebrake = 0.0f;
    bool operator==(const BrakeCommand& o) const { return brake == o.brake && ebrake == o.ebrake; }
};

inline BrakeCommand wheel_command(const BrakeContext& ctx, int wheel, bool driven, bool blown)
{
    if (blown)
    {
        return {1.0f, 0.0f};
    }
    const bool rear = wheel >= 2;
    const float t = ctx.tuning;
    float brake = ctx.brake * (rear ? 1.0f - 0.5f * t : 1.0f + 0.5f * t);
    const float speed_mph = ms_to_mph(ctx.speed);
    if (ctx.gas > 0.8f && ctx.brake > 0.5f && std::fabs(speed_mph) < 10.0f && driven)
    {
        brake = std::fabs(speed_mph) * 0.05f;
    }
    float ebrake = 0.0f;
    if (rear)
    {
        ebrake = ctx.ebrake;
        if (ctx.ebrake > 0.2f && ctx.slip_angle > 0.3f && speed_mph < 80.0f)
        {
            ebrake += 0.5f;
        }
    }
    return {brake, ebrake};
}
} // namespace atelier::driving
