#pragma once

#include "SimulationSpec.h"

namespace atelier::driving::aero
{
struct AeroInput
{
    Vec3 linear_velocity = VEC3_ZERO;
    Mat3 rotation = MAT3_IDENTITY;
    float gas = 0.0f;
    float ground_effect = 0.0f;
    bool any_wheel_on_ground = false;
    float tuning = 0.0f;
};

struct AeroForces
{
    Vec3 drag = VEC3_ZERO;
    float drag_drop = 0.0f;
    Vec3 downforce = VEC3_ZERO;
    bool has_downforce_z = false;
    float downforce_z = 0.0f;
};

inline AeroForces forces(const AeroSpec& spec, const AeroInput& i, float front_z, float rear_z)
{
    AeroForces out;
    const float speed = length(i.linear_velocity);
    const float tuning = clamp(i.tuning, -1.0f, 1.0f);
    if (spec.drag_coefficient != 0.0f)
    {
        float drag = speed * spec.drag_coefficient;
        drag += drag * (1.0f - clamp(i.gas, 0.0f, 1.0f));
        drag += drag * 0.25f * tuning;
        out.drag = -i.linear_velocity * drag;
        if (i.ground_effect >= 0.5f)
        {
            out.drag_drop = 0.1f * (1.0f - clamp(i.gas, 0.0f, 1.0f));
        }
    }
    if (spec.aero_coefficient != 0.0f)
    {
        const Vec3 up = i.rotation.y_axis;
        const Vec3 forward = i.rotation.z_axis;
        const float upness = i.ground_effect >= 0.5f ? 1.0f : std::fmax(up.y, 0.0f);
        const Vec3 move_dir = speed > 1e-4f ? i.linear_velocity / speed : forward;
        const float forwardness = std::fmax(std::sqrt(std::fmax(dot(move_dir, forward), 0.0f)), 0.4f);
        float downforce = upness * forwardness * speed * 2.0f * spec.aero_coefficient * 1000.0f;
        if (!i.any_wheel_on_ground)
        {
            downforce *= spec.airborne_scale;
        }
        downforce *= 1.0f + 0.25f * tuning;
        out.downforce = -up * downforce;
        if (i.ground_effect != 0.0f)
        {
            out.has_downforce_z = true;
            out.downforce_z = (front_z - rear_z) * spec.aero_cg * 0.01f + rear_z;
        }
    }
    return out;
}
} // namespace atelier::driving::aero
