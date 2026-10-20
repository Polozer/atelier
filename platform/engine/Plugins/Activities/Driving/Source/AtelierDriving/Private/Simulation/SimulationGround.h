#pragma once

#include "SimulationMath.h"

#include <cstdint>

namespace atelier::driving
{
struct SurfaceGrip
{
    float lateral = 1.0f;
    float drive = 1.0f;
    float rolling = 1.0f;
    uint32_t tag = 0;
    bool operator==(const SurfaceGrip& o) const
    {
        return lateral == o.lateral && drive == o.drive && rolling == o.rolling && tag == o.tag;
    }
};

struct GroundHit
{
    float distance = 0.0f;
    Vec3 normal = VEC3_Y;
    SurfaceGrip surface;
};

struct WheelPlane
{
    Vec3 normal = VEC3_Y;
    float separation = 0.0f;
    SurfaceGrip surface;
};

class Ground
{
public:
    virtual ~Ground() = default;
    virtual bool wheel_plane(int wheel, Vec3 point, float tolerance, bool reuse, WheelPlane& out) const
    {
        (void)wheel;
        (void)point;
        (void)tolerance;
        (void)reuse;
        (void)out;
        return false;
    }
    virtual SurfaceGrip surface_grip(uint32_t tag) const
    {
        SurfaceGrip out;
        out.tag = tag;
        return out;
    }
    virtual float body_friction(uint32_t surface) const
    {
        (void)surface;
        return 1.0f;
    }
    virtual bool hit(Vec3 origin, Vec3 dir, float max_distance, GroundHit& out) const = 0;
};

struct FlatGround : Ground
{
    float height = 0.0f;
    SurfaceGrip surface;
    explicit FlatGround(float h = 0.0f) : height(h) {}
    bool hit(Vec3 origin, Vec3 dir, float max_distance, GroundHit& out) const override
    {
        if (dir.y >= -1e-6f)
        {
            return false;
        }
        const float distance = (height - origin.y) / dir.y;
        if (distance >= 0.0f && distance <= max_distance)
        {
            out = {distance, VEC3_Y, surface};
            return true;
        }
        return false;
    }
};

struct SlopedGround : Ground
{
    float height = 0.0f;
    float slope = 0.0f;
    SurfaceGrip surface;
    bool hit(Vec3 origin, Vec3 dir, float max_distance, GroundHit& out) const override
    {
        const Vec3 normal = normalize(Vec3{0.0f, 1.0f, -slope});
        const float denom = dot(normal, dir);
        if (denom >= -1e-6f)
        {
            return false;
        }
        const float distance = dot(normal, Vec3{0.0f, height, 0.0f} - origin) / denom;
        if (distance >= 0.0f && distance <= max_distance)
        {
            out = {distance, normal, surface};
            return true;
        }
        return false;
    }
};

struct NoGround : Ground
{
    bool hit(Vec3, Vec3, float, GroundHit&) const override { return false; }
};

} // namespace atelier::driving
