#include "SimulationSuspension.h"

namespace atelier::driving
{
Geometry Geometry::make(const ChassisSpec& chassis, const TireSpec& tires, float half_height)
{
    const auto axle_width = [&](int axle) {
        return chassis.track_width[axle] - tires.section_width[axle] * 0.001f;
    };
    const float wf = axle_width(0) * 0.5f;
    const float wr = axle_width(1) * 0.5f;
    const float front_z = chassis.front_axle;
    const float rear_z = chassis.front_axle - chassis.wheel_base;
    const float y = -half_height;
    Geometry g;
    g.arms[0] = {-wf, y, front_z};
    g.arms[1] = {wf, y, front_z};
    g.arms[2] = {-wr, y, rear_z};
    g.arms[3] = {wr, y, rear_z};
    g.radius[0] = tires.radius(0);
    g.radius[1] = tires.radius(0);
    g.radius[2] = tires.radius(1);
    g.radius[3] = tires.radius(1);
    return g;
}
} // namespace atelier::driving
