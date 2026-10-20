#pragma once

#include "SimulationSpec.h"

namespace atelier::driving
{
inline float engine_rev_limit(const EngineSpec& e)
{
    return e.no_rev_limiter ? std::fmax(e.max_rpm, e.red_line) : e.red_line;
}

inline float engine_torque_ftlb(const EngineSpec& e, float rpm)
{
    if (e.torque.size() <= 1)
    {
        return 0.0f;
    }
    const float limited = clamp(rpm, e.idle, std::fmax(engine_rev_limit(e), e.idle));
    return table(e.torque.data(), static_cast<int>(e.torque.size()), e.idle, e.max_rpm, limited);
}

inline float engine_torque_nm(const EngineSpec& e, float rpm)
{
    return engine_torque_ftlb(e, rpm) * FT_LB_TO_NM;
}

inline float engine_braking_torque(const EngineSpec& e, float torque, float rpm)
{
    if (e.engine_braking.empty())
    {
        return 0.0f;
    }
    if (e.engine_braking.size() == 1)
    {
        return -torque * e.engine_braking[0];
    }
    const float limited = clamp(rpm, e.idle, std::fmax(engine_rev_limit(e), e.idle));
    const float factor = table(e.engine_braking.data(), static_cast<int>(e.engine_braking.size()), e.idle,
                               e.max_rpm, limited);
    return -torque * clamp(factor, 0.0f, 1.0f);
}

inline float engine_inertia(const EngineSpec& e, bool in_neutral)
{
    return (e.flywheel_mass * 0.025f + 0.25f) * (in_neutral ? 0.35f : 1.0f);
}

inline float engine_idle_rad(const EngineSpec& e) { return rpm_to_rad(e.idle); }
inline float engine_rev_limit_rad(const EngineSpec& e) { return rpm_to_rad(engine_rev_limit(e)); }
inline float engine_red_line_rad(const EngineSpec& e) { return rpm_to_rad(e.red_line); }

inline float engine_horse_power(const EngineSpec& e, float torque_nm, float throttle, float rpm)
{
    (void)e;
    return torque_nm * throttle * 0.7376f * rpm / HP_RPM_CONSTANT;
}

class Clutch
{
public:
    ClutchState state = ClutchState::Engaged;
    float factor() const
    {
        switch (state)
        {
        case ClutchState::Engaged:
            return 1.0f;
        case ClutchState::Engaging:
            return 1.0f - 0.75f * ramp(timer_, 0.0f, engage_time_);
        default:
            return 0.25f;
        }
    }
    bool is_engaged() const { return state == ClutchState::Engaged; }
    void disengage()
    {
        if (state == ClutchState::Engaged)
        {
            state = ClutchState::Disengaged;
        }
    }
    void hold_open() { state = ClutchState::Disengaged; }
    void engage(float time)
    {
        if (state != ClutchState::Disengaged)
        {
            return;
        }
        if (time <= 0.0f)
        {
            state = ClutchState::Engaged;
            return;
        }
        state = ClutchState::Engaging;
        timer_ = time;
        engage_time_ = time;
    }
    void update(float dt)
    {
        if (state != ClutchState::Engaging)
        {
            return;
        }
        timer_ -= dt;
        if (timer_ <= 0.0f)
        {
            timer_ = 0.0f;
            state = ClutchState::Engaged;
        }
    }
    void reset() { *this = Clutch{}; }

private:
    float timer_ = 0.0f;
    float engage_time_ = 0.0f;
};
} // namespace atelier::driving
