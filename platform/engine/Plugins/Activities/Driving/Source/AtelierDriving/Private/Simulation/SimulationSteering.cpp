#include "SimulationSteering.h"

namespace atelier::driving
{
float Steering::update(const SteeringInput& i)
{
    const float u = clamp(i.steer, -1.0f, 1.0f);
    if (i.device == SteeringDevice::Ai)
    {
        prev_angle = ABSOLUTE_MAX_STEERING * i.tire_steering * u;
        return prev_angle;
    }
    const float v = i.forward_speed;
    collision_timer = std::fmax(collision_timer - i.dt, 0.0f);
    const float avg = std::fabs(avg_input.mean());

    float range;
    switch (i.device)
    {
    case SteeringDevice::Pad:
        range = table(RANGE_PAD, 10, 0.0f, MAX_SPEED_AXIS, v);
        break;
    case SteeringDevice::WheelSpeedSensitive:
        range = table(RANGE_WHEEL, 10, 0.0f, MAX_SPEED_AXIS, v);
        break;
    default:
        range = ABSOLUTE_MAX_STEERING;
        break;
    }
    const float speed_coef = table(STEER_SPEED, 10, 0.0f, MAX_SPEED_AXIS, v);
    const float tb = 1.0f - (i.gas + 1.0f - (i.brake + i.ebrake) * 0.5f) * 0.5f;
    float max = range * (1.45f * tb * speed_coef + 1.0f);
    max *= table(RANGE_COEF, 6, 0.0f, 1.0f, avg);
    max *= 1.0f + 0.2f * i.tuning;

    if (collision_timer > 0.0f)
    {
        const float secs = 1.0f - collision_timer;
        const float speed_term = 1.0f - clamp(v / (mph_to_ms(170.0f) * 0.7f), 0.0f, 1.0f);
        const float blend = graph(COLLISION_BLEND, 4, secs);
        max *= speed_term * (1.0f - blend) + blend;
    }

    if (u > 0.0f && i.rear_slip_deg[1] > 0.0f)
    {
        max = std::fmin(std::fmax(max, i.rear_slip_deg[1]), ABSOLUTE_MAX_STEERING);
    }
    else if (u < 0.0f && i.rear_slip_deg[0] < 0.0f)
    {
        max = std::fmin(std::fmax(max, -i.rear_slip_deg[0]), ABSOLUTE_MAX_STEERING);
    }
    else if (avg >= 0.5f)
    {
        max = std::fmax(max, last_max);
    }
    max = std::fmin(max, ABSOLUTE_MAX_STEERING);
    if (i.device == SteeringDevice::WheelFixed)
    {
        max = ABSOLUTE_MAX_STEERING;
    }
    last_max = max;

    const float target = clamp(u * max * i.tire_steering, -ABSOLUTE_MAX_STEERING, ABSOLUTE_MAX_STEERING);
    if (i.device == SteeringDevice::Pad)
    {
        const float input_speed = std::fabs((u - last_input) / i.dt);
        this->input_speed.push(table(INPUT_SPEED_COEF, 6, 0.0f, 10.0f, input_speed));
        const float rate = 180.0f * i.tire_steering * speed_coef * this->input_speed.mean() *
                           table(INPUT_COEF, 6, 0.0f, 1.0f, avg);
        prev_angle = clamp(target, prev_angle - rate * i.dt, prev_angle + rate * i.dt);
    }
    else
    {
        prev_angle = target;
    }
    float recorded;
    if (i.device == SteeringDevice::Pad)
    {
        const std::array<float, 21> remap = input_remap();
        recorded = table(remap.data(), 21, -1.0f, 1.0f, u);
    }
    else
    {
        recorded = u;
    }
    last_input = recorded;
    avg_input.push(recorded);
    return prev_angle;
}
} // namespace atelier::driving
