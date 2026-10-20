#pragma once

#include "SimulationSpec.h"
#include "SimulationNos.h"

namespace atelier::driving
{
struct InputContext
{
    float forward_speed = 0.0f;
    int gear = GEAR_FIRST;
    bool disabled = false;
};

inline float snap(float v, float dead_zone)
{
    v = clamp(finite_or(v, 0.0f), 0.0f, 1.0f);
    if (v > 1.0f - dead_zone)
    {
        return 1.0f;
    }
    if (v < dead_zone)
    {
        return 0.0f;
    }
    return v;
}

inline Controls shape(const InputState& input, const ControlConfig& config, const InputContext& ctx)
{
    Controls out;
    if (ctx.disabled)
    {
        out.gas = 0.0f;
        out.brake = 1.0f;
        out.handbrake = 1.0f;
        out.steering = clamp(finite_or(input.steer, 0.0f), -1.0f, 1.0f);
        out.nos = false;
        out.gear_request = GearRequest::none();
        out.has_clutch = false;
        return out;
    }
    float gas = snap(input.throttle, config.dead_zone);
    float brake = snap(input.brake, config.dead_zone);
    const float handbrake = clamp(finite_or(input.handbrake, 0.0f), 0.0f, 1.0f);
    const float steer = clamp(finite_or(input.steer, 0.0f), -1.0f, 1.0f);
    const float raw_gas = gas;
    const float raw_brake = brake;
    const float v = ctx.forward_speed;
    GearRequest gear_request = (!config.automatic && input.has_gear_select) ? GearRequest::select(input.gear_select)
                                                                          : GearRequest::none();
    const bool explicit_gear = gear_request.has_value();
    const bool auto_reverse = config.auto_reverse && !(config.h_shifter && !config.automatic);

    if (auto_reverse)
    {
        if (explicit_gear)
        {
            // The request stands; the automatic reverse waits.
        }
        else if (ctx.gear != GEAR_REVERSE)
        {
            if (v < 2.5f && raw_brake > 0.0f && raw_gas == 0.0f)
            {
                gear_request = GearRequest::reverse();
            }
        }
        else if (v > -5.0f && (raw_brake == 0.0f || raw_gas > 0.0f))
        {
            gear_request = GearRequest::first();
        }
        bool reversing;
        if (gear_request.kind == GearRequestKind::Reverse)
        {
            reversing = true;
        }
        else if (gear_request.kind == GearRequestKind::First)
        {
            reversing = false;
        }
        else if (gear_request.kind == GearRequestKind::Select)
        {
            reversing = gear_request.value == GEAR_REVERSE;
        }
        else
        {
            reversing = ctx.gear == GEAR_REVERSE;
        }
        if (reversing)
        {
            const float tmp = gas;
            gas = brake;
            brake = tmp;
        }
        if (config.auto_brake && raw_gas == 0.0f && raw_brake == 0.0f)
        {
            if (reversing)
            {
                brake = 1.0f - 0.75f * ramp(-v, 0.0f, 10.0f);
            }
            else if (v < 8.0f)
            {
                brake = 1.0f - 0.75f * ramp(v, 0.0f, 8.0f);
            }
            else
            {
                brake = 0.0f;
            }
        }
    }
    else if (config.auto_brake && raw_gas == 0.0f && raw_brake == 0.0f && v < 8.0f)
    {
        brake = 1.0f - 0.75f * ramp(v, 0.0f, 8.0f);
    }
    if (handbrake > 0.0f)
    {
        brake = 0.0f;
    }
    if (!gear_request.has_value())
    {
        const int dir = (input.shift_up ? 1 : 0) - (input.shift_down ? 1 : 0);
        if (dir != 0 && ctx.gear != GEAR_REVERSE)
        {
            gear_request = GearRequest::shift(dir);
        }
    }
    out.gas = gas;
    out.brake = brake;
    out.handbrake = handbrake;
    out.steering = steer;
    out.nos = input.nos;
    out.gear_request = gear_request;
    out.has_clutch = config.manual_clutch;
    out.clutch = config.manual_clutch ? clamp(finite_or(input.clutch, 0.0f), 0.0f, 1.0f) : 0.0f;
    return out;
}
} // namespace atelier::driving
