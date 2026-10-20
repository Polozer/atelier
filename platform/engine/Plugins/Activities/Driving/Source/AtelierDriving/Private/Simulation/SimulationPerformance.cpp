#include "SimulationPerformance.h"

#include <vector>

namespace atelier::driving::performance
{
Performance measure_with_integration(const VehicleSpec& spec, TireIntegration integration)
{
    FlatGround ground(0.0f);
    Vehicle car(spec);
    car.set_tire_integration(integration);
    car.place_on_ground(ground, 0.0f, 0.0f, 5.0f, 0.0f);
    InputState input;
    input.throttle = 1.0f;
    const int steps = static_cast<int>(MAX_SECONDS / FIXED_STEP);
    const int window = static_cast<int>(SETTLE_SECONDS / FIXED_STEP);
    std::vector<float> speeds;
    speeds.reserve(static_cast<size_t>(steps));
    for (int step = 0; step < steps; ++step)
    {
        car.step(FIXED_STEP, input, ground);
        speeds.push_back(std::fmax(car.forward_speed(), 0.0f));
        if (step > window && speeds[static_cast<size_t>(step)] - speeds[static_cast<size_t>(step - window)] <
                                 SETTLE_GAIN)
        {
            break;
        }
    }
    Performance out;
    for (float speed : speeds)
    {
        out.top_speed = std::fmax(out.top_speed, speed);
    }
    out.start_grip = std::fmin(spec.tires.static_grip[0], spec.tires.static_grip[1]);
    const float downforce = out.top_speed * 2.0f * spec.aero.aero_coefficient * 1000.0f;
    out.end_grip = out.start_grip * (GRAVITY + downforce / std::fmax(spec.mass, 1.0f)) / GRAVITY;
    if (out.top_speed <= 0.0f)
    {
        return out;
    }
    const int span = static_cast<int>(1.0f / FIXED_STEP);
    for (int i = 0; i < TABLE_SIZE; ++i)
    {
        const float target = out.top_speed * static_cast<float>(i) / static_cast<float>(TABLE_SIZE - 1);
        int at = static_cast<int>(speeds.size()) - 1;
        for (size_t j = 0; j < speeds.size(); ++j)
        {
            if (speeds[j] >= target)
            {
                at = static_cast<int>(j);
                break;
            }
        }
        const int from = std::max(at - span / 2, 0);
        const int to = std::min(at + span / 2, static_cast<int>(speeds.size()) - 1);
        out.acceleration[i] = to > from
                                 ? std::fmax((speeds[static_cast<size_t>(to)] - speeds[static_cast<size_t>(from)]) /
                                                 (static_cast<float>(to - from) * FIXED_STEP),
                                             0.0f)
                                 : 0.0f;
    }
    return out;
}

Performance measure(const VehicleSpec& spec)
{
    return measure_with_integration(spec, TireIntegration::Regularized);
}
} // namespace atelier::driving::performance
