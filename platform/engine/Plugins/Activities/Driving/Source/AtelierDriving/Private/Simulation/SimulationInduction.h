#pragma once

#include "SimulationSpec.h"

namespace atelier::driving
{
struct InductionInput
{
    float dt = 0.0f;
    float throttle = 0.0f;
    float rpm = 0.0f;
    float idle = 0.0f;
    float red_line = 0.0f;
    bool shifting = false;
    float tuning = 0.0f;
};

struct Induction
{
    float spool = 0.0f;
    float boost = 0.0f;
    float psi = 0.0f;

    void update(const InductionSpec& spec, const InductionInput& i)
    {
        const InductionKind kind = spec.kind();
        if (kind == InductionKind::None)
        {
            *this = Induction{};
            return;
        }
        const float t = clamp(i.tuning, -1.0f, 1.0f);
        float spool_n = spec.spool;
        if (spec.spool > 0.0f && t != 0.0f)
        {
            const float range = t < 0.0f ? spec.spool * 0.25f : (1.0f - spec.spool) * 0.25f;
            spool_n = spec.spool + range * t;
        }
        const float spool_rpm = spool_n * (i.red_line - i.idle) + i.idle;
        const float low = spec.low_boost - spec.low_boost * t * 0.25f;
        const float high = spec.high_boost + spec.high_boost * t * 0.25f;

        float desired = ramp(i.throttle, 0.0f, 0.5f);
        if (i.shifting || (kind == InductionKind::Turbo && i.rpm < spool_rpm))
        {
            desired = 0.0f;
        }
        const float time = desired > spool ? spec.spool_time_up : spec.spool_time_down;
        if (time <= 1.19209290e-7f)
        {
            spool = desired;
        }
        else
        {
            const float step = i.dt / time;
            if (desired > spool)
            {
                spool = std::fmin(spool + step, desired);
            }
            else
            {
                spool = std::fmax(spool - step, desired);
            }
        }
        spool = clamp(spool, 0.0f, 1.0f);

        const float peak = std::fmax(high, low);
        float boost_value;
        float target_psi;
        if (i.rpm >= spool_rpm)
        {
            const float r = ramp(i.rpm, spool_rpm, i.red_line);
            boost_value = r * high + (1.0f - r) * low;
            target_psi = spool * spec.psi * ramp(boost_value, 0.0f, peak);
        }
        else if (spec.vacuum < 0.0f)
        {
            const float d = ramp(i.rpm, i.idle, spool_rpm);
            boost_value = d * spec.vacuum;
            target_psi = d * -spec.psi * ramp(-boost_value, 0.0f, peak);
        }
        else
        {
            boost_value = 0.0f;
            target_psi = 0.0f;
        }
        boost = boost_value * spool;
        const float max_step = 20.0f * i.dt;
        psi += clamp(target_psi - psi, -max_step, max_step);
    }
};
} // namespace atelier::driving
