#pragma once

#include "SimulationVehicle.h"

#include <array>

namespace atelier::driving::performance
{
inline constexpr int TABLE_SIZE = 10;
inline constexpr float GRAVITY = 9.8128f;
inline constexpr float MAX_SECONDS = 90.0f;
inline constexpr float SETTLE_GAIN = 0.05f;
inline constexpr float SETTLE_SECONDS = 4.0f;

struct Performance
{
    float top_speed = 0.0f;
    std::array<float, TABLE_SIZE> acceleration{};
    float start_grip = 0.0f;
    float end_grip = 0.0f;

    float acceleration_at(float speed) const
    {
        if (top_speed <= 0.0f)
        {
            return 0.0f;
        }
        const float position =
            clamp(std::fabs(speed) / top_speed * static_cast<float>(TABLE_SIZE - 1), 0.0f,
                  static_cast<float>(TABLE_SIZE - 1));
        const int low = static_cast<int>(std::floor(position));
        const int high = std::min(low + 1, TABLE_SIZE - 1);
        const float t = position - static_cast<float>(low);
        return acceleration[low] * (1.0f - t) + acceleration[high] * t;
    }
};

Performance measure(const VehicleSpec& spec);
Performance measure_with_integration(const VehicleSpec& spec, TireIntegration integration);
} // namespace atelier::driving::performance
