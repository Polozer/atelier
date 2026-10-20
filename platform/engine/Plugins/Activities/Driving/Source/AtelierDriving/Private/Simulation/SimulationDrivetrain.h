#pragma once

#include "SimulationEngine.h"
#include "SimulationInduction.h"
#include "SimulationNos.h"

#include <array>

namespace atelier::driving
{
inline int top_gear(const TransmissionSpec& t) { return static_cast<int>(t.gear_ratio.size()) - 1; }
inline float gear_ratio(const TransmissionSpec& t, int gear)
{
    if (gear < 0 || gear >= static_cast<int>(t.gear_ratio.size()))
    {
        return 0.0f;
    }
    return std::fabs(t.gear_ratio[gear]);
}
inline float gear_efficiency(const TransmissionSpec& t, int gear)
{
    if (gear < 0 || gear >= static_cast<int>(t.gear_efficiency.size()))
    {
        return 1.0f;
    }
    return t.gear_efficiency[gear];
}
inline bool front_driven(const TransmissionSpec& t) { return t.torque_split > 0.0f; }
inline bool rear_driven(const TransmissionSpec& t) { return t.torque_split < 1.0f; }

inline std::array<float, 2> calc_split(float bias, float factor, bool locked, bool traction[2], float omega[2])
{
    const std::array<float, 2> open{bias, 1.0f - bias};
    if (!(traction[0] && traction[1]) || locked || factor <= 0.0f)
    {
        return open;
    }
    const float av_a = omega[0] * (1.0f - bias);
    const float av_b = omega[1] * bias;
    const float c = std::fabs(av_a + av_b);
    if (c <= 1.19209290e-7f)
    {
        return open;
    }
    const float split_a = (1.0f - factor) * bias + factor * std::fabs(av_b) / c;
    const float split_b = (1.0f - factor) * (1.0f - bias) + factor * std::fabs(av_a) / c;
    return {clamp(split_a, 0.0f, 1.0f), clamp(split_b, 0.0f, 1.0f)};
}

inline std::array<float, 4> split_drive_torque(float drive_torque, const TransmissionSpec& trans,
                                               const std::array<float, 4>& omega,
                                               const std::array<bool, 4>& grounded)
{
    std::array<float, 4> out{0.0f, 0.0f, 0.0f, 0.0f};
    if (std::fabs(drive_torque) <= 1.19209290e-7f)
    {
        return out;
    }
    std::array<float, 2> share;
    if (trans.differential[2] > 0.0f)
    {
        bool axle_traction[2] = {grounded[0] || grounded[1], grounded[2] || grounded[3]};
        float axle_omega[2] = {omega[0] + omega[1], omega[2] + omega[3]};
        share = calc_split(trans.torque_split, trans.differential[2], false, axle_traction, axle_omega);
    }
    else
    {
        share = {trans.torque_split, 1.0f - trans.torque_split};
    }
    for (int axle = 0; axle < 2; ++axle)
    {
        const float axle_torque = drive_torque * share[axle];
        if (std::fabs(axle_torque) <= 1.19209290e-7f)
        {
            continue;
        }
        const int a = axle * 2;
        const int b = a + 1;
        bool wheel_traction[2] = {grounded[a], grounded[b]};
        float wheel_omega[2] = {omega[a], omega[b]};
        const std::array<float, 2> s = calc_split(0.5f, trans.differential[axle], false, wheel_traction, wheel_omega);
        if (grounded[a])
        {
            out[a] = axle_torque * s[0];
        }
        if (grounded[b])
        {
            out[b] = axle_torque * s[1];
        }
    }
    return out;
}

struct DrivenAxles
{
    bool front = false;
    bool rear = false;
};

inline float axle_mean(const std::array<float, 4>& av, int axle)
{
    return 0.5f * (av[axle * 2] + av[axle * 2 + 1]);
}

inline std::pair<float, float> driven_speeds(const std::array<float, 4>& av, DrivenAxles driven, bool reverse)
{
    float free_speed = 0.0f;
    if (driven.front && driven.rear)
    {
        const float f = axle_mean(av, 0);
        const float r = axle_mean(av, 1);
        free_speed = std::fabs(f) >= std::fabs(r) ? f : r;
    }
    else if (driven.front)
    {
        free_speed = axle_mean(av, 0);
    }
    else if (driven.rear)
    {
        free_speed = axle_mean(av, 1);
    }
    const float locked = reverse ? std::fmin(free_speed, 0.0f) : std::fmax(free_speed, 0.0f);
    return {free_speed, locked};
}

inline void write_back(std::array<float, 4>& av, const std::array<bool, 4>& grounded, DrivenAxles driven,
                       bool reverse, float wanted, float speed)
{
    const bool axles[2] = {driven.front, driven.rear};
    for (int axle = 0; axle < 2; ++axle)
    {
        if (!axles[axle])
        {
            continue;
        }
        const int a = axle * 2;
        const int b = a + 1;
        if (speed * MS_TO_MPH < 40.0f || (!grounded[a] && !grounded[b]))
        {
            const float m = 0.5f * (av[a] + av[b]);
            av[a] = m;
            av[b] = m;
        }
    }
    const float locked = driven_speeds(av, driven, reverse).second;
    const float delta = wanted - locked;
    for (int axle = 0; axle < 2; ++axle)
    {
        if (axles[axle])
        {
            av[axle * 2] += delta;
            av[axle * 2 + 1] += delta;
        }
    }
}

struct ShiftPoints
{
    std::vector<float> up;
    std::vector<float> down;

    static ShiftPoints compute(const EngineSpec& engine, const TransmissionSpec& trans);
    ShiftPotential potential(const EngineSpec& engine, const TransmissionSpec& trans, int gear, float rpm,
                             float throttle) const;
    int downshift_target(const EngineSpec& engine, const TransmissionSpec& trans, int gear, float rpm,
                         float throttle) const;
};

struct TickInput
{
    float dt = 0.0f;
    float gas = 0.0f;
    bool nos_held = false;
    bool can_recharge_nos = true;
    bool blown = false;
    bool automatic = true;
    float speed = 0.0f;
    std::array<float, 4>* wheel_av = nullptr;
    std::array<bool, 4> grounded{false, false, false, false};
    bool drifting = false;
    float drive_slip = 0.0f;
    float max_wheel_slip = 0.0f;
    float induction_tuning = 0.0f;
    float nos_tuning = 0.0f;
    bool has_clutch_pedal = false;
    float clutch_pedal = 0.0f;
};

class Powertrain
{
public:
    EngineSpec engine;
    TransmissionSpec trans;
    InductionSpec induction_spec;
    NosSpec nos_spec;
    float avg_wheel_radius = 0.0f;
    float omega = 0.0f;
    float omega_trans = 0.0f;
    float rpm_display = 0.0f;
    Clutch clutch;
    int gear = GEAR_FIRST;
    float shift_timer = 0.0f;
    float sport_timer = 0.0f;
    float throttle = 0.0f;
    ShiftPoints shift_points;
    float peak_torque_rpm = 0.0f;
    float peak_torque_nm = 0.0f;
    Induction induction;
    Nos nos;
    float prev_rpm_diff = 0.0f;
    float drive_torque = 0.0f;
    bool engine_braking = false;
    std::array<bool, 4> wheel_written{false, false, false, false};

    Powertrain() = default;
    Powertrain(const EngineSpec& engine_spec, const TransmissionSpec& trans_spec,
               const InductionSpec& induction_spec_, const NosSpec& nos_spec_, float avg_wheel_radius_);

    void reset();
    bool has_nos() const { return nos_spec.present(); }
    void set_no_rev_limiter(bool on) { engine.no_rev_limiter = on; }
    const EngineSpec& engine_spec_ref() const { return engine; }
    const TransmissionSpec& transmission_spec_ref() const { return trans; }
    int gear_id() const { return gear; }
    int top_gear_id() const { return top_gear(trans); }
    float throttle_value() const { return throttle; }
    float rpm() const { return rad_to_rpm(omega); }
    float rpm_display_value() const { return rpm_display; }
    float drive_torque_value() const { return drive_torque; }
    std::array<bool, 4> wheel_writes() const { return wheel_written; }
    std::pair<float, float> peak_torque() const { return {peak_torque_nm, peak_torque_rpm}; }
    const ShiftPoints& shift_points_ref() const { return shift_points; }
    bool shifting() const { return shift_timer > 0.0f; }
    bool is_engine_braking() const { return engine_braking; }
    float speed_at(float rpm, int gear) const;
    float speedometer() const;
    float max_speed() const;
    bool shift(int new_gear);
    void request_shift(int dir, bool automatic);
    bool select_gear(int new_gear, float forward_speed);
    void match_speed(float v);
    float tick(TickInput& input);
    float rpm_fraction() const { return ramp(rpm(), engine.idle, engine.red_line); }
    bool shift_up_wish() const;
    void reconfigure(const EngineSpec& engine_spec, const TransmissionSpec& trans_spec,
                     const InductionSpec& induction_spec_, const NosSpec& nos_spec_, float radius);

    struct LoopContext
    {
        float dt = 0.0f;
        std::array<float, 4>* av = nullptr;
        std::array<bool, 4> grounded{false, false, false, false};
        float drive_slip = 0.0f;
        float speed = 0.0f;
    };
    float torque_loop(LoopContext& c);

private:
    static std::pair<float, float> scan_peak(const EngineSpec& engine_spec, const InductionSpec& induction_spec_);
    float speed_to_rpm(float v, int gear) const;
    void auto_shift(const TickInput& i, float dt);
    void command_clutch(bool has_pedal, float pedal);
    void smooth_rpm(float dt);
    void mark_driven_written(DrivenAxles driven);
};
} // namespace atelier::driving
