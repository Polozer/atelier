#pragma once

#include <cstdint>

namespace atelier::driving
{
enum class BodyState : uint8_t
{
    Awake,
    Asleep,
    Frozen,
};

enum class ClutchState : uint8_t
{
    Engaged,
    Engaging,
    Disengaged,
};

enum class ShiftPotential : uint8_t
{
    None,
    Up,
    Down,
};

enum class TireIntegration : uint8_t
{
    Regularized,
    Reference,
};

enum class TireStateKind : uint8_t
{
    None,
    Punctured,
    Blown,
};

struct TireState
{
    TireStateKind kind = TireStateKind::None;
    float fuse = 0.0f;

    static TireState none() { return {}; }
    static TireState punctured(float left) { return {TireStateKind::Punctured, left}; }
    static TireState blown() { return {TireStateKind::Blown, 0.0f}; }
    bool operator==(const TireState& o) const { return kind == o.kind && fuse == o.fuse; }
};

enum class SteeringDevice : uint8_t
{
    Pad,
    WheelSpeedSensitive,
    WheelFixed,
    Ai,
};

enum class GearRequestKind : uint8_t
{
    None,
    Reverse,
    First,
    Shift,
    Select,
};

struct GearRequest
{
    GearRequestKind kind = GearRequestKind::None;
    int value = 0;

    static GearRequest none() { return {}; }
    static GearRequest reverse() { return {GearRequestKind::Reverse, 0}; }
    static GearRequest first() { return {GearRequestKind::First, 0}; }
    static GearRequest shift(int dir) { return {GearRequestKind::Shift, dir}; }
    static GearRequest select(int gear) { return {GearRequestKind::Select, gear}; }
    bool has_value() const { return kind != GearRequestKind::None; }
    bool operator==(const GearRequest& o) const { return kind == o.kind && value == o.value; }
};

struct Controls
{
    float gas = 0.0f;
    float brake = 0.0f;
    float handbrake = 0.0f;
    float steering = 0.0f;
    bool nos = false;
    GearRequest gear_request;
    bool has_clutch = false;
    float clutch = 0.0f;
};

enum class LimitMode : uint8_t
{
    Prismatic,
    Conical,
};

enum class Separation : uint8_t
{
    Mass,
    NormalSpeed,
};

enum class FrictionState : uint8_t
{
    None,
    Static,
    Dynamic,
};

enum class InductionKind : uint8_t
{
    None,
    Turbo,
    Supercharger,
};

} // namespace atelier::driving
