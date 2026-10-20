#pragma once

#include "SimulationGround.h"
#include "SimulationSpec.h"

namespace atelier::driving
{
inline constexpr float PROBE_LIFT = 0.5f;

struct Geometry
{
    Vec3 arms[4] = {VEC3_ZERO, VEC3_ZERO, VEC3_ZERO, VEC3_ZERO};
    float radius[4] = {0.0f, 0.0f, 0.0f, 0.0f};

    static Geometry make(const ChassisSpec& chassis, const TireSpec& tires, float half_height);
    float front_z() const { return arms[0].z; }
    float rear_z() const { return arms[2].z; }
};

inline Vec3 center_of_gravity(const ChassisSpec& chassis, float half_height, float ride_extra,
                              bool any_wheel_on_ground)
{
    const float front_z = chassis.front_axle;
    const float rear_z = chassis.front_axle - chassis.wheel_base;
    const float bias = any_wheel_on_ground ? chassis.front_weight_bias * 0.01f : 0.5f;
    const float ride = inch_to_m(std::fmax(chassis.ride_height[0] + ride_extra, chassis.ride_height[1] + ride_extra));
    return {0.0f, inch_to_m(chassis.roll_center) - (half_height + ride),
            (front_z - rear_z) * bias + rear_z};
}

struct WheelContact
{
    Vec3 point = VEC3_ZERO;
    Vec3 normal = VEC3_Y;
    float penetration = 0.0f;
    SurfaceGrip surface;
};

inline bool probe(const Ground& ground, Vec3 point, float tolerance, WheelContact& out)
{
    GroundHit hit;
    if (!ground.hit(point + VEC3_Y * PROBE_LIFT, VEC3_NEG_Y, PROBE_LIFT + std::fmax(tolerance, 0.0f), hit))
    {
        return false;
    }
    if (!std::isfinite(hit.distance) || hit.normal.y <= 0.0f)
    {
        return false;
    }
    out.point = point + VEC3_Y * (PROBE_LIFT - hit.distance);
    out.normal = hit.normal;
    out.penetration = (PROBE_LIFT - hit.distance) * hit.normal.y;
    out.surface = hit.surface;
    return true;
}

struct Compression
{
    float value = 0.0f;
    float lift_need = 0.0f;
    float upness = 0.0f;
    bool loaded = false;
};

inline Compression compression(float ride, float travel, float upness, float penetration)
{
    const float raw = ride * upness + penetration;
    const float lift_need = std::fmax(raw - travel, 0.0f);
    const float value = clamp(raw, 0.0f, travel);
    return {value, lift_need, upness, value > 0.0f && upness > 0.2f};
}

struct Corner
{
    float compression = 0.0f;
    float air_time = 0.0f;
};

enum class Side : uint8_t
{
    Left,
    Right,
};

struct SpringInput
{
    float c_old = 0.0f;
    float c_new = 0.0f;
    float c_left_old = 0.0f;
    float c_right_old = 0.0f;
    Side side = Side::Left;
    float dt = 0.0f;
    float mass = 0.0f;
    float blowout = 0.0f;
};

inline float spring_force(const AxleConstants& a, const SpringInput& i)
{
    float rise = (i.c_new - i.c_old) / i.dt;
    if (a.valving > 1e-6f && a.digression < 1.0f && std::fabs(rise) > a.valving)
    {
        rise = signum(rise) * a.valving * std::pow(std::fabs(rise) / a.valving, a.digression);
    }
    const float spring = i.c_new * a.spring * (1.0f + i.c_new * a.progression);
    float damper = rise * (rise > 0.0f ? a.shock : a.shock_ext);
    if (i.blowout > 0.0f && damper > i.blowout * 9.81f * i.mass)
    {
        damper = 0.0f;
    }
    const float roll = (i.c_left_old - i.c_right_old) * a.sway;
    const float sway = i.side == Side::Left ? roll : -roll;
    return std::fmax(damper + spring + sway, 0.0f);
}
} // namespace atelier::driving
