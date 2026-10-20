#include "SimulationDrivetrain.h"

namespace atelier::driving
{
namespace
{
constexpr float SPORT_HOLD = 1.25f;
constexpr float CLUTCH_PEDAL_BITE = 0.1f;
constexpr float REVERSE_SPEED = 2.5f;
constexpr float CLUTCH_STIFFNESS = 20.0f;
constexpr float CLUTCH_LIMITER = 300.0f;
constexpr float CLUTCH_PLAY[5][2] = {
    {-10.0f, 1.0f}, {-7.5f, 0.96f}, {-3.5f, 0.925f}, {-0.3f, 0.875f}, {-0.05f, 0.0f}};
} // namespace

ShiftPoints ShiftPoints::compute(const EngineSpec& engine, const TransmissionSpec& trans)
{
    const int n = static_cast<int>(trans.gear_ratio.size());
    ShiftPoints points;
    points.up.assign(n, 0.0f);
    points.down.assign(n, 0.0f);
    if (n <= GEAR_FIRST + 1 || n > 10)
    {
        return points;
    }
    const int top = top_gear(trans);
    const float red = engine.red_line;
    for (int j = GEAR_FIRST; j < top; ++j)
    {
        const float g1 = gear_ratio(trans, j);
        const float g2 = gear_ratio(trans, j + 1);
        if (g1 < 1e-6f)
        {
            continue;
        }
        const float k = g2 / g1;
        float rpm = (red + engine.idle) * 0.5f;
        while (rpm < red)
        {
            const float cur = engine_torque_ftlb(engine, rpm);
            const float next = engine_torque_ftlb(engine, rpm * k) * k;
            if (next > cur)
            {
                break;
            }
            rpm += 50.0f;
        }
        points.up[j] = rpm >= red ? red - 100.0f : rpm;
        points.down[j + 1] = points.up[j] * k;
    }
    points.up[top] = red;
    return points;
}

ShiftPotential ShiftPoints::potential(const EngineSpec& engine, const TransmissionSpec& trans, int gear, float rpm,
                                      float throttle_value) const
{
    if (gear < 0 || gear >= static_cast<int>(up.size()) || gear < GEAR_FIRST || up[gear] <= 0.0f)
    {
        return ShiftPotential::None;
    }
    const float up_point = up[gear];
    float down_point = down[gear];
    if (gear > GEAR_FIRST && gear_ratio(trans, gear - 1) > 0.0f)
    {
        const float lower_up = up[gear - 1] * gear_ratio(trans, gear) / gear_ratio(trans, gear - 1) - 200.0f;
        const float coast = lerp(engine.idle, down_point, 0.65f);
        down_point = std::fmin(lerp(coast, down_point, throttle_value), lower_up);
    }
    if (rpm >= up_point && gear < top_gear(trans))
    {
        return ShiftPotential::Up;
    }
    if (rpm <= down_point && gear > GEAR_FIRST)
    {
        return ShiftPotential::Down;
    }
    return ShiftPotential::None;
}

int ShiftPoints::downshift_target(const EngineSpec& engine, const TransmissionSpec& trans, int gear, float rpm,
                                  float throttle_value) const
{
    const float base = std::fmax(gear_ratio(trans, gear), 1e-6f);
    const auto predicted = [&](int new_gear) { return rpm * gear_ratio(trans, new_gear) / base; };
    int next = std::max(gear - 1, GEAR_FIRST);
    while (next > GEAR_FIRST)
    {
        if (potential(engine, trans, next, predicted(next), throttle_value) != ShiftPotential::Down)
        {
            return next;
        }
        --next;
    }
    return next;
}

Powertrain::Powertrain(const EngineSpec& engine_spec, const TransmissionSpec& trans_spec,
                       const InductionSpec& induction_spec_, const NosSpec& nos_spec_, float avg_wheel_radius_)
    : engine(engine_spec),
      trans(trans_spec),
      induction_spec(induction_spec_),
      nos_spec(nos_spec_),
      avg_wheel_radius(avg_wheel_radius_)
{
    shift_points = ShiftPoints::compute(engine, trans);
    const auto peak = scan_peak(engine, induction_spec);
    peak_torque_nm = peak.first;
    peak_torque_rpm = peak.second;
    omega = engine_idle_rad(engine);
    omega_trans = 0.0f;
    rpm_display = engine.idle;
    gear = std::min(GEAR_FIRST, top_gear(trans));
    nos = Nos::make(nos_spec);
}

std::pair<float, float> Powertrain::scan_peak(const EngineSpec& engine, const InductionSpec& induction_spec_)
{
    if (engine.torque.size() < 2)
    {
        return {0.0f, engine.idle};
    }
    float best = 0.0f;
    float best_rpm = engine.idle;
    float rpm = engine.idle;
    const float step = (engine.max_rpm - engine.idle) / static_cast<float>(engine.torque.size() - 1);
    for (const float torque : engine.torque)
    {
        const float t = torque * (1.0f + induction_spec_.full_boost(rpm, engine.idle, engine.red_line));
        if (t > best)
        {
            best = t;
            best_rpm = rpm;
        }
        rpm += step;
    }
    return {best * FT_LB_TO_NM, clamp(best_rpm, engine.idle, std::fmax(engine.red_line, engine.idle))};
}

void Powertrain::reset()
{
    omega = engine_idle_rad(engine);
    omega_trans = 0.0f;
    rpm_display = engine.idle;
    clutch.reset();
    gear = std::min(GEAR_FIRST, top_gear(trans));
    shift_timer = 0.0f;
    sport_timer = 0.0f;
    throttle = 0.0f;
    induction = Induction{};
    nos = Nos::make(nos_spec);
    drive_torque = 0.0f;
    wheel_written = {false, false, false, false};
}

float Powertrain::speed_at(float rpm, int gear_id) const
{
    const float ratio = gear_ratio(trans, gear_id) * trans.final_gear;
    if (ratio <= 1e-6f || engine_rev_limit(engine) <= engine.idle)
    {
        return 0.0f;
    }
    const float clutch_rpm = (rpm - engine.idle) / ratio / (engine_rev_limit(engine) - engine.idle) *
                             engine_rev_limit(engine);
    return std::fmax(rpm_to_rad(clutch_rpm) * avg_wheel_radius, 0.0f);
}

float Powertrain::speedometer() const
{
    const float v = speed_at(rad_to_rpm(omega_trans), gear);
    const float limit = engine.speed_limiter[0];
    return limit > 0.0f ? std::fmin(v, mph_to_ms(limit)) : v;
}

float Powertrain::max_speed() const
{
    const float v = speed_at(engine_rev_limit(engine), top_gear(trans));
    const float limit = engine.speed_limiter[0];
    return limit > 0.0f ? std::fmin(v, mph_to_ms(limit)) : v;
}

bool Powertrain::shift(int new_gear)
{
    if (new_gear > top_gear(trans) || new_gear == gear)
    {
        return false;
    }
    const float delay = trans.shift_speed * gear_ratio(trans, new_gear);
    shift_timer = new_gear < gear ? delay * 0.25f : delay;
    gear = new_gear;
    clutch.disengage();
    return true;
}

void Powertrain::request_shift(int dir, bool automatic)
{
    if (gear == GEAR_REVERSE)
    {
        return;
    }
    const int desired = clamp(gear + dir, 1, top_gear(trans));
    if (desired == gear)
    {
        return;
    }
    if (!automatic)
    {
        shift(desired);
        return;
    }
    if (gear <= GEAR_NEUTRAL || shifting())
    {
        return;
    }
    const float rpm_value = rad_to_rpm(omega_trans);
    const ShiftPotential wish = shift_points.potential(engine, trans, gear, rpm_value, throttle);
    const bool contradicts = (dir > 0 && wish == ShiftPotential::Down) || (dir < 0 && wish == ShiftPotential::Up);
    if (!contradicts && shift(desired))
    {
        sport_timer = SPORT_HOLD;
    }
}

bool Powertrain::select_gear(int new_gear, float forward_speed)
{
    if (new_gear < 0 || new_gear > top_gear(trans))
    {
        return false;
    }
    if (new_gear == GEAR_REVERSE && forward_speed > REVERSE_SPEED)
    {
        return false;
    }
    return shift(new_gear);
}

void Powertrain::match_speed(float v)
{
    reset();
    if (v < 0.0f)
    {
        gear = GEAR_REVERSE;
    }
    else
    {
        const int top = top_gear(trans);
        int g = std::min(GEAR_FIRST, top);
        while (g < top)
        {
            const float rpm_value = speed_to_rpm(v, g);
            if (rpm_value < shift_points.up[g])
            {
                break;
            }
            ++g;
        }
        gear = g;
    }
    const float rpm_value = clamp(speed_to_rpm(std::fabs(v), gear), engine.idle, engine_rev_limit(engine));
    omega = rpm_to_rad(rpm_value);
    omega_trans = omega;
    rpm_display = rpm_value;
}

float Powertrain::speed_to_rpm(float v, int gear_id) const
{
    const float min_w = engine_idle_rad(engine);
    const float max_w = engine_rev_limit_rad(engine);
    const float ratio = gear_ratio(trans, gear_id) * trans.final_gear;
    const float wheel_w = v / std::fmax(avg_wheel_radius, 1e-3f);
    return rad_to_rpm(min_w + wheel_w * ratio * (max_w - min_w) / max_w);
}

float Powertrain::tick(TickInput& i)
{
    const float dt = i.dt;
    throttle = i.blown ? 0.0f : clamp(i.gas, 0.0f, 1.0f);
    const float speed_mph = ms_to_mph(i.speed);
    NosInput nos_input;
    nos_input.dt = dt;
    nos_input.held = i.nos_held;
    nos_input.gear = gear;
    nos_input.throttle = throttle;
    nos_input.speed_mph = speed_mph;
    nos_input.blown = i.blown;
    nos_input.tuning = i.nos_tuning;
    nos_input.can_recharge = i.can_recharge_nos;
    nos.update(nos_spec, nos_input);

    const float limit = engine.speed_limiter[0];
    const float band = engine.speed_limiter[1];
    if (gear > GEAR_NEUTRAL && limit > 0.0f && band > 0.0f)
    {
        const float v = speed_at(rad_to_rpm(omega_trans), gear);
        const float lim = mph_to_ms(limit);
        if (v > lim)
        {
            throttle *= 1.0f - clamp((v - lim) / mph_to_ms(band), 0.0f, 1.0f);
        }
    }

    const float rpm_value = rad_to_rpm(omega);
    InductionInput induction_input;
    induction_input.dt = dt;
    induction_input.throttle = throttle;
    induction_input.rpm = rpm_value;
    induction_input.idle = engine.idle;
    induction_input.red_line = engine.red_line;
    induction_input.shifting = shifting();
    induction_input.tuning = i.induction_tuning;
    induction.update(induction_spec, induction_input);

    shift_timer = std::fmax(shift_timer - dt, 0.0f);
    clutch.update(dt);
    if (i.automatic)
    {
        auto_shift(i, dt);
    }
    command_clutch(i.has_clutch_pedal, i.clutch_pedal);

    LoopContext ctx;
    ctx.dt = dt;
    ctx.av = i.wheel_av;
    ctx.grounded = i.grounded;
    ctx.drive_slip = i.drive_slip;
    ctx.speed = i.speed;
    wheel_written = {false, false, false, false};
    drive_torque = clamp_signed(torque_loop(ctx), 1.0e6f);
    smooth_rpm(dt);
    return drive_torque;
}

void Powertrain::auto_shift(const TickInput& i, float dt)
{
    if (gear == GEAR_REVERSE || shifting())
    {
        return;
    }
    if (sport_timer > 0.0f)
    {
        sport_timer -= dt * (2.0f - clamp(i.gas, 0.0f, 1.0f));
        return;
    }
    if (gear == GEAR_NEUTRAL)
    {
        shift(std::min(GEAR_FIRST, top_gear(trans)));
        return;
    }
    if (!clutch.is_engaged())
    {
        return;
    }
    const float rpm_value = rad_to_rpm(omega_trans);
    switch (shift_points.potential(engine, trans, gear, rpm_value, throttle))
    {
    case ShiftPotential::Down:
        shift(shift_points.downshift_target(engine, trans, gear, rpm_value, throttle));
        break;
    case ShiftPotential::Up:
        if (std::all_of(i.grounded.begin(), i.grounded.end(), [](bool g) { return g; }) &&
            i.max_wheel_slip < 4.0f)
        {
            shift(gear + 1);
        }
        break;
    default:
        break;
    }
}

void Powertrain::command_clutch(bool has_pedal, float pedal)
{
    if (has_pedal && pedal > CLUTCH_PEDAL_BITE)
    {
        clutch.hold_open();
        return;
    }
    const float idle = engine_idle_rad(engine);
    if (gear == GEAR_NEUTRAL)
    {
        clutch.disengage();
        return;
    }
    if (gear == GEAR_FIRST || gear == GEAR_REVERSE)
    {
        const float extra = gear == GEAR_REVERSE ? 2400.0f : 800.0f;
        const float limit = idle + rpm_to_rad(extra);
        if (omega > limit || omega_trans > limit || throttle >= 0.1f)
        {
            clutch.engage(0.05f);
        }
        else
        {
            clutch.disengage();
        }
        return;
    }
    clutch.engage(0.25f);
}

void Powertrain::smooth_rpm(float dt)
{
    const float inertia = engine_inertia(engine, gear == GEAR_NEUTRAL);
    const bool fast = (shifting() && gear > GEAR_FIRST) || gear == GEAR_NEUTRAL;
    const float max_decel = -(fast ? 15.0f : 2.5f) * 1000.0f / inertia;
    const float next = rad_to_rpm(omega);
    const float old = rpm_display;
    float n = next;
    if ((next - old) / dt < max_decel)
    {
        n = std::fmax(old + max_decel * dt, next);
    }
    rpm_display = 0.55f * n + 0.45f * old;
}

bool Powertrain::shift_up_wish() const
{
    if (!clutch.is_engaged())
    {
        return false;
    }
    const float rpm_value = rad_to_rpm(omega_trans);
    return shift_points.potential(engine, trans, gear, rpm_value, throttle) == ShiftPotential::Up;
}

void Powertrain::mark_driven_written(DrivenAxles driven)
{
    wheel_written = {driven.front, driven.front, driven.rear, driven.rear};
}

float Powertrain::torque_loop(LoopContext& c)
{
    const float dt = c.dt;
    const float min_w = engine_idle_rad(engine);
    const float max_w = engine_rev_limit_rad(engine);
    const bool reverse = gear == GEAR_REVERSE;
    const bool neutral = gear == GEAR_NEUTRAL;
    const float dir = reverse ? -1.0f : 1.0f;
    const DrivenAxles driven{front_driven(trans), rear_driven(trans)};
    float ratio = gear_ratio(trans, gear) * trans.final_gear * dir;
    const float rpm_value = rad_to_rpm(omega);

    if (trans.torque_converter > 0.0f)
    {
        float conv = trans.torque_converter * throttle * (1.0f - ramp(rpm_value, engine.idle, peak_torque_rpm));
        if (shifting())
        {
            conv *= clutch.factor();
        }
        ratio *= 1.0f + conv;
    }
    if (ratio == 0.0f && !neutral)
    {
        return 0.0f;
    }

    const float engine_t = engine_torque_nm(engine, rpm_value) * (1.0f + induction.boost) * nos.boost;
    float braking_t = engine_braking_torque(engine, engine_t, rpm_value);

    const std::pair<float, float> speeds = driven_speeds(*c.av, driven, reverse);
    const float free_speed = speeds.first;
    const float locked = speeds.second;
    const float omega_trans_old = omega_trans;
    omega_trans = min_w + locked * ratio * (max_w - min_w) / max_w;
    const float trans_accel = (omega_trans - omega_trans_old) / dt;

    if (!neutral && clutch.is_engaged() && braking_t * free_speed * dir > 0.0f)
    {
        braking_t = -braking_t;
    }
    const float total_t = engine_t * throttle + braking_t * (1.0f - throttle);
    engine_braking = total_t < 0.0f;
    int on_ground = 0;
    for (bool g : c.grounded)
    {
        on_ground += g ? 1 : 0;
    }
    const float wheels_ratio = std::fmax(static_cast<float>(on_ground) / 4.0f, 0.25f);
    const float inertia = engine_inertia(engine, neutral);
    const bool first_or_reverse = !neutral && gear <= GEAR_FIRST;

    float drive_t = 0.0f;
    float road_t = 0.0f;
    const float diff_rpm = rad_to_rpm(omega - omega_trans);
    if (!neutral)
    {
        if (clutch.state == ClutchState::Engaged)
        {
            drive_t = total_t;
            road_t = -total_t * wheels_ratio;
            const float ae = (total_t + road_t) / inertia;
            const float diff = ae - trans_accel;
            const float r2 = ratio * ratio;
            float response = 1.0f / inertia;
            if (driven.front)
            {
                response += trans.torque_split * 0.1f * r2 * 0.5f;
            }
            if (driven.rear)
            {
                response += (1.0f - trans.torque_split) * 0.1f * r2 * 0.5f;
            }
            const float r = diff / response;
            drive_t += std::fmin(r, 0.0f);
            road_t -= r * wheels_ratio;
        }
        else if (clutch.state == ClutchState::Engaging)
        {
            const float d = clamp(omega - omega_trans, -CLUTCH_LIMITER, CLUTCH_LIMITER);
            float stiffness = CLUTCH_STIFFNESS;
            if (prev_rpm_diff * diff_rpm < 0.0f && std::fabs(prev_rpm_diff) > 2000.0f &&
                std::fabs(diff_rpm) > 2000.0f)
            {
                stiffness *= 0.5f;
            }
            const float clutch_t = d * stiffness * clutch.factor();
            drive_t += clutch_t;
            road_t -= clutch_t * wheels_ratio;
        }
    }
    prev_rpm_diff = diff_rpm;

    if (!neutral && clutch.is_engaged() && on_ground > 0)
    {
        if (throttle > 0.2f && c.drive_slip > 0.1f && gear <= GEAR_FIRST && omega_trans < omega)
        {
            omega_trans = omega;
            write_back(*c.av, c.grounded, driven, reverse, omega / ratio, c.speed);
            mark_driven_written(driven);
        }
        else
        {
            const float lim = std::fabs(total_t);
            road_t += clamp((omega_trans - omega) * CLUTCH_STIFFNESS, -lim, lim);
        }
    }

    if (first_or_reverse && clutch.is_engaged())
    {
        const float net = total_t + road_t;
        if (road_t < total_t && net < 0.0f)
        {
            const float play = graph(CLUTCH_PLAY, 5, 1000.0f * net);
            road_t += play * net * trans.clutch_slip;
        }
        if (throttle > 0.0f && road_t * total_t < 0.0f)
        {
            const float slip =
                trans.clutch_slip * throttle * (1.0f - throttle * ramp(rpm_value, engine.idle, peak_torque_rpm));
            road_t *= (1.0f - slip) * (1.0f - slip);
        }
    }

    const float alpha = (total_t + road_t) / inertia;
    omega = clamp(omega + alpha * dt, min_w, max_w);

    if (ratio != 0.0f)
    {
        const float limit = max_w / std::fabs(ratio);
        for (int i = 0; i < 4; ++i)
        {
            const bool is_driven = i < 2 ? driven.front : driven.rear;
            if (is_driven && !c.grounded[i])
            {
                float& av = (*c.av)[i];
                av = av * dir < 0.0f ? 0.0f : clamp(av, -limit, limit);
                wheel_written[i] = true;
            }
        }
        if (omega_trans > max_w)
        {
            if (drive_t * ratio > 0.0f)
            {
                drive_t = 0.0f;
            }
            omega_trans = max_w;
            write_back(*c.av, c.grounded, driven, reverse, max_w / ratio, c.speed);
            mark_driven_written(driven);
        }
    }
    return drive_t * ratio * gear_efficiency(trans, gear);
}

void Powertrain::reconfigure(const EngineSpec& engine_spec, const TransmissionSpec& trans_spec,
                             const InductionSpec& induction_spec_, const NosSpec& nos_spec_, float radius)
{
    const float old_ratio = gear_ratio(trans, gear) * trans.final_gear;
    const float old_max = engine_rev_limit_rad(engine);
    const float old_range = old_max - engine_idle_rad(engine);
    const float axle_speed = old_ratio > 0.0f && old_range > 0.0f
                                 ? (omega_trans - engine_idle_rad(engine)) * old_max / (old_ratio * old_range)
                                 : 0.0f;
    Powertrain next(engine_spec, trans_spec, induction_spec_, nos_spec_, radius);
    next.gear = std::min(gear, next.top_gear_id());
    next.omega = clamp(omega, engine_idle_rad(next.engine), engine_rev_limit_rad(next.engine));
    next.rpm_display = clamp(rpm_display, next.engine.idle, engine_rev_limit(next.engine));
    const float max_w = engine_rev_limit_rad(next.engine);
    const float ratio = gear_ratio(next.trans, next.gear) * next.trans.final_gear;
    next.omega_trans = engine_idle_rad(next.engine) +
                       axle_speed * ratio * (max_w - engine_idle_rad(next.engine)) / max_w;
    if (gear == next.gear)
    {
        next.clutch = clutch;
        next.shift_timer = shift_timer;
        next.sport_timer = sport_timer;
    }
    if (induction_spec == induction_spec_)
    {
        next.induction = induction;
    }
    if (nos_spec == nos_spec_)
    {
        next.nos = nos;
    }
    else if (has_nos() && next.has_nos())
    {
        next.nos.capacity = clamp(nos.capacity, 0.0f, 1.0f);
    }
    *this = next;
}
} // namespace atelier::driving
