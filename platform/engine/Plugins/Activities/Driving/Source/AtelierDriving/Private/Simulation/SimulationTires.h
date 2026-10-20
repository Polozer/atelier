#pragma once

#include "SimulationGround.h"
#include "SimulationSpec.h"

namespace atelier::driving
{
inline constexpr float WHEEL_INERTIA = 10.0f;
inline constexpr float ROLLING_FRICTION = 2.0f;
inline constexpr float BLOW_DELAY = 0.5f;
inline constexpr float RUN_FLAT_BLOW_DELAY = 180.0f;
inline constexpr float BLOWN_TRACTION = 0.3f;

inline float lateral_force(float load, float slip_angle, float grip_scale, float grip_boost);

struct StepScales
{
    float max_slip = 0.0f;
    float grip_scale = 0.0f;
    float traction_scale = 0.0f;
    static StepScales make(float speed, bool reverse);
};

struct TireParams
{
    float radius = 0.0f;
    float grip_scale = 0.0f;
    float static_grip = 0.0f;
    float dynamic_grip = 0.0f;
    float brake_spec = 0.0f;
    float brake_lock_spec = 0.0f;
    float ebrake_spec = 0.0f;
    bool front = false;
};

struct LoadedInput
{
    float lat_vel = 0.0f;
    float fwd_vel = 0.0f;
    float body_speed = 0.0f;
    float load = 0.0f;
    float dt = 0.0f;
    float quarter_mass = 0.0f;
    SurfaceGrip surface;
};

struct Tire
{
    TireIntegration integration = TireIntegration::Regularized;
    float av = 0.0f;
    float load = 0.0f;
    float lateral_force = 0.0f;
    float longitudinal_force = 0.0f;
    float drive_torque = 0.0f;
    float traction = 1.0f;
    float slip = 0.0f;
    float slip_angle = 0.0f;
    float road_speed = 0.0f;
    float lateral_speed = 0.0f;
    bool brake_locked = false;
    int8_t last_sign = 0;
    float last_torque = 0.0f;
    float angular_acc = 0.0f;
    float brake = 0.0f;
    float ebrake = 0.0f;
    float max_slip = 0.5f;
    float grip_boost = 1.0f;
    float traction_boost = 1.0f;
    float drag_reduction = 0.15f;
    float lateral_boost = 1.0f;
    float traction_circle_lateral = 1.0f;
    float traction_circle_longitudinal = 1.0f;
    float drift_friction = 1.0f;

    void begin_frame(float max_slip_, float grip_boost_, float traction_boost_);
    void check_sign();
    float display_av(float radius, bool compressed) const;
    float pilot_factor(const TireParams& p, float body_speed) const;
    float update_loaded(const TireParams& p, const LoadedInput& i);
    void update_free(const TireParams& p, float dt);
};

struct TireDamage
{
    TireState states[4];
    bool run_flat = false;

    TireState state(int wheel) const
    {
        if (wheel < 0 || wheel >= 4)
        {
            return TireState::none();
        }
        return states[wheel];
    }
    bool puncture(int wheel);
    void advance(float dt);
    bool is_blown(int wheel) const { return state(wheel).kind == TireStateKind::Blown; }
    void reset()
    {
        for (auto& s : states)
        {
            s = TireState::none();
        }
    }
    bool operator==(const TireDamage& o) const
    {
        for (int i = 0; i < 4; ++i)
        {
            if (!(states[i] == o.states[i]))
            {
                return false;
            }
        }
        return run_flat == o.run_flat;
    }
};
} // namespace atelier::driving
