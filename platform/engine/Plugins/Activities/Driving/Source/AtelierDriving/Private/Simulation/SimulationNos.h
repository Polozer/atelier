#pragma once

#include "SimulationSpec.h"

namespace atelier::driving
{
inline constexpr int GEAR_REVERSE = 0;
inline constexpr int GEAR_NEUTRAL = 1;
inline constexpr int GEAR_FIRST = 2;

struct NosInput
{
    float dt = 0.0f;
    bool held = false;
    int gear = GEAR_FIRST;
    float throttle = 0.0f;
    float speed_mph = 0.0f;
    bool blown = false;
    float tuning = 0.0f;
    bool can_recharge = true;
};

struct Nos
{
    float capacity = 0.0f;
    float engaged = 0.0f;
    float boost = 1.0f;

    static Nos make(const NosSpec& spec) { return {spec.present() ? 1.0f : 0.0f, 0.0f, 1.0f}; }
    bool is_engaged() const { return engaged >= 1.0f; }

    void update(const NosSpec& spec, const NosInput& i)
    {
        const float t = clamp(i.tuning, -1.0f, 1.0f);
        const float boost_n = spec.torque_boost * (1.0f + 0.25f * t);
        const float capacity_n = spec.nos_capacity * (1.0f - 0.25f * t);
        const bool was_engaged = is_engaged();

        bool engaged_now = i.held;
        if (i.gear < GEAR_FIRST || i.throttle <= 0.0f || i.blown)
        {
            engaged_now = false;
        }
        if ((i.speed_mph < 10.0f && !was_engaged) || (i.speed_mph < 5.0f && was_engaged))
        {
            engaged_now = false;
        }
        if (!spec.present() || capacity_n <= 0.0f)
        {
            *this = {0.0f, 0.0f, 1.0f};
            return;
        }
        float recharge = 0.0f;
        if (i.can_recharge && i.speed_mph >= spec.recharge_min_speed && i.gear >= GEAR_FIRST)
        {
            recharge = lerp(spec.recharge_min, spec.recharge_max,
                            ramp(i.speed_mph, spec.recharge_min_speed, spec.recharge_max_speed));
        }
        if (engaged_now && capacity > 0.0f)
        {
            capacity = std::fmax(capacity - i.dt / capacity_n, 0.0f);
            boost = 1.0f + boost_n;
            engaged = 1.0f;
            return;
        }
        boost = 1.0f;
        if (engaged > 0.0f && spec.nos_disengage > 0.0f)
        {
            engaged = std::fmax(engaged - i.dt / spec.nos_disengage, 0.0f);
            return;
        }
        if (capacity < 1.0f && recharge > 0.0f)
        {
            capacity = std::fmin(capacity + i.dt / recharge, 1.0f);
        }
        engaged = 0.0f;
    }
};
} // namespace atelier::driving
