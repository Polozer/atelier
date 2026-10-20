#include "SimulationRigidBody.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>

namespace atelier::driving
{
namespace
{
constexpr float AIR_DENSITY = 1.225f;
constexpr float EPSILON = 1.19209290e-7f;

struct DVec3
{
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

DVec3 to_d(Vec3 v) { return {v.x, v.y, v.z}; }
Vec3 to_f(DVec3 v) { return {static_cast<float>(v.x), static_cast<float>(v.y), static_cast<float>(v.z)}; }
DVec3 operator+(DVec3 a, DVec3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
DVec3 operator-(DVec3 a, DVec3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
DVec3 operator*(DVec3 a, double s) { return {a.x * s, a.y * s, a.z * s}; }
double dot_d(DVec3 a, DVec3 b) { return (a.x * b.x + a.y * b.y) + a.z * b.z; }

int32_t float_order(float v)
{
    uint32_t bits;
    std::memcpy(&bits, &v, sizeof(bits));
    const int32_t i = static_cast<int32_t>(bits);
    return i < 0 ? static_cast<int32_t>(0x80000000u - bits) : i;
}

bool total_less(float a, float b) { return float_order(a) < float_order(b); }

struct IterationBody
{
    Vec3 linear;
    Vec3 angular;
    Vec3 output_linear = VEC3_ZERO;
    Vec3 output_angular = VEC3_ZERO;
    Vec3 arm;
    bool immobile;

    IterationBody(const ContactMoment& m, Vec3 point, bool mobile)
        : linear(m.linear_velocity), angular(m.angular_velocity), arm(point - m.centre), immobile(mobile)
    {
    }
    Vec3 velocity() const { return linear + cross(angular, arm); }
    void release(ContactMoment& moment, float impulse)
    {
        if (moment.breaking_impulse > 0.0f && impulse > moment.breaking_impulse)
        {
            immobile = false;
            moment.immobile = false;
        }
    }
    void apply(const ContactMoment& moment, Vec3 normal, Vec3 tangent)
    {
        if (immobile)
        {
            return;
        }
        const Vec3 turn_normal = moment.inverse_inertia * cross(arm, normal);
        const Vec3 turn_tangent = moment.inverse_inertia * cross(arm, tangent);
        angular += turn_normal + turn_tangent;
        output_angular += turn_normal * (1.0f + moment.elasticity) + turn_tangent;
        if (moment.fixed_centre)
        {
            return;
        }
        const float inv_mass = 1.0f / moment.mass;
        linear += (normal + tangent) * inv_mass;
        output_linear += (normal * (1.0f + moment.elasticity) + tangent) * inv_mass;
    }
    void finish(ContactMoment& moment) const
    {
        moment.linear_velocity += output_linear;
        moment.angular_velocity += output_angular;
    }
};

bool moment_valid(const ContactMoment& m)
{
    return std::isfinite(m.mass) && m.mass > 0.0f && is_finite(m.inverse_inertia) && is_finite(m.centre) &&
           is_finite(m.linear_velocity) && is_finite(m.angular_velocity) && std::isfinite(m.elasticity) &&
           std::isfinite(m.breaking_impulse);
}

float reduced_mass(const ContactMoment& a, const ContactMoment& b, bool immobile_a, bool immobile_b)
{
    if (immobile_a)
    {
        return b.mass;
    }
    if (immobile_b)
    {
        return a.mass;
    }
    return a.mass * b.mass / (a.mass + b.mass);
}

std::pair<Vec3, FrictionState> friction(Vec3 momentum, Vec3 normal, float impulse, const PlaneContact& plane)
{
    const Vec3 tangent = momentum + normal * impulse;
    const float len = length(tangent);
    if (len > plane.friction_static * impulse)
    {
        return {-tangent * (plane.friction_kinetic * impulse / len), FrictionState::Dynamic};
    }
    return {-tangent, FrictionState::Static};
}

struct Face
{
    const Obb* reference;
    const Obb* incident;
    int axis;
    Vec3 normal;
    Vec3 travel;
    ObbContact contact;
    bool clip(ObbContact& out) const;
};

Vec3 orient(Vec3 axis, Vec3 delta)
{
    return dot_d(to_d(axis), to_d(delta)) < 0.0 ? -axis : axis;
}

bool segment_plane(Vec3 start, Vec3 end, Vec3 plane, Vec3 normal, Vec3& out)
{
    const DVec3 direction = to_d(end) - to_d(start);
    const double denominator = dot_d(direction, to_d(normal));
    if (std::fabs(denominator) <= 0.000001)
    {
        return false;
    }
    const float t = static_cast<float>(dot_d(to_d(plane) - to_d(start), to_d(normal)) / denominator);
    if (!(t >= 0.0f && t <= 1.0f))
    {
        return false;
    }
    out = to_f(to_d(start) + to_d(to_f(direction)) * static_cast<double>(t));
    return true;
}

constexpr int SIDE_AXES[3][2] = {{1, 2}, {0, 2}, {0, 1}};

bool valid_obb(const Obb& b)
{
    return is_finite(b.centre) && is_finite(b.axes) && is_finite(b.half) && min_element(b.half) >= 0.0f;
}
} // namespace

Vec3 box_inertia(float mass, Vec3 half)
{
    const float w = 2.0f * half.x;
    const float h = 2.0f * half.y;
    const float l = 2.0f * half.z;
    return Vec3{h * h + l * l, w * w + l * l, w * w + h * h} * (mass / 12.0f);
}

Vec3 inverse_diagonal(Vec3 inertia)
{
    const auto inv = [](float i) { return i > EPSILON ? 1.0f / i : 0.0f; };
    return {inv(inertia.x), inv(inertia.y), inv(inertia.z)};
}

RigidBody::RigidBody(float mass, Vec3 dimension, Vec3 tensor_scale, const RigidBodySpec& spec)
    : spec_(spec)
{
    dimension_ = max(dimension, Vec3::splat(0.001f));
    mass_ = std::fmax(mass, EPSILON);
    inv_mass_ = 1.0f / mass_;
    inertia_ = box_inertia(mass_, dimension_) * tensor_scale;
    radius_ = length(dimension_);
    cog_ = spec.cg;
    refresh_matrices();
}

void RigidBody::refresh_matrices()
{
    rotation_ = mat3_from_quat(orientation);
    const Mat3 inv = from_diagonal(inverse_diagonal(inertia_));
    inv_world_tensor_ = rotation_ * inv * transpose(rotation_);
}

void RigidBody::set_mass(float mass)
{
    if (mass > 0.0f && mass != mass_)
    {
        inertia_ = inertia_ * (mass / mass_);
        mass_ = mass;
        inv_mass_ = 1.0f / mass;
        refresh_matrices();
    }
}

void RigidBody::place(Vec3 p, Quat o)
{
    position = p;
    orientation = quat_normalize(o);
    linear_velocity = VEC3_ZERO;
    angular_velocity = VEC3_ZERO;
    force_ = VEC3_ZERO;
    torque_ = VEC3_ZERO;
    state = BodyState::Awake;
    refresh_matrices();
}

void RigidBody::wake()
{
    if (state == BodyState::Asleep)
    {
        state = BodyState::Awake;
    }
}

void RigidBody::set_orientation(Quat o)
{
    if (!is_finite(o) || quat_length_squared(o) <= EPSILON)
    {
        return;
    }
    orientation = quat_normalize(o);
    refresh_matrices();
}

void RigidBody::apply_force(Vec3 force)
{
    wake();
    force_ += force;
}
void RigidBody::apply_torque(Vec3 torque)
{
    wake();
    torque_ += torque;
}
void RigidBody::apply_force_at(Vec3 force, Vec3 world_point)
{
    wake();
    torque_ += cross(world_point - world_cog(), force);
    force_ += force;
}
void RigidBody::apply_impulse_at(Vec3 impulse, Vec3 world_point)
{
    if (state == BodyState::Frozen)
    {
        return;
    }
    wake();
    linear_velocity += impulse * inv_mass_;
    angular_velocity += inv_world_tensor_ * cross(world_point - world_cog(), impulse);
}
void RigidBody::apply_torque_at(Vec3 force, Vec3 world_point)
{
    wake();
    torque_ += cross(world_point - world_cog(), force);
}
void RigidBody::accelerate(Vec3 accel, float dt)
{
    if (state == BodyState::Awake)
    {
        linear_velocity += accel * dt;
    }
}
void RigidBody::damp(float k)
{
    const float s = 1.0f - k;
    linear_velocity *= s;
    angular_velocity *= s;
    force_ *= s;
    torque_ *= s;
}

void RigidBody::begin_frame(float dt)
{
    if (state == BodyState::Frozen)
    {
        return;
    }
    if (state == BodyState::Asleep)
    {
        linear_velocity = VEC3_ZERO;
        angular_velocity = VEC3_ZERO;
        force_ = VEC3_ZERO;
        torque_ = VEC3_ZERO;
        return;
    }
    const Vec3 cg0 = rotation_ * cog_;
    linear_velocity += force_ * (dt * inv_mass_);
    position += linear_velocity * dt;
    angular_velocity += inv_world_tensor_ * (torque_ * dt);
    linear_velocity = clamp(linear_velocity, Vec3::splat(-MAX_LINEAR_SPEED), Vec3::splat(MAX_LINEAR_SPEED));
    angular_velocity = clamp(angular_velocity, Vec3::splat(-MAX_ANGULAR_SPEED), Vec3::splat(MAX_ANGULAR_SPEED));
    if (length_squared(angular_velocity) != 0.0f)
    {
        const Vec3 w = angular_velocity * dt;
        const Quat dq = Quat{w.x, w.y, w.z, 0.0f} * orientation;
        orientation = quat_normalize(orientation + dq * 0.5f);
    }
    refresh_matrices();
    position += cg0 - rotation_ * cog_;
    force_ = VEC3_ZERO;
    torque_ = VEC3_ZERO;
    force_.y += spec_.gravity * mass_;
}

void RigidBody::apply_drag()
{
    if (state != BodyState::Awake)
    {
        return;
    }
    const Vec3 h = dimension_;
    const Mat3 rot = rotation_;
    if (!(spec_.drag == VEC3_ZERO))
    {
        const Vec3 v = transpose(rot) * linear_velocity;
        const Vec3 area = h * h * 4.0f;
        const Vec3 f = -(v * area * spec_.drag) * (0.5f * AIR_DENSITY * length(v));
        force_ += rot * f;
    }
    if (!(spec_.drag_angular == VEC3_ZERO))
    {
        const Vec3 w = transpose(rot) * angular_velocity;
        const Vec3 s{
            4.0f * h.x * std::sqrt(h.y * h.y + h.z * h.z),
            4.0f * h.y * std::sqrt(h.x * h.x + h.z * h.z),
            4.0f * h.z * std::sqrt(h.x * h.x + h.y * h.y),
        };
        const Vec3 t = -(w * s * spec_.drag_angular) * (0.5f * AIR_DENSITY * length(w));
        torque_ += rot * t;
    }
}

BodyState RigidBody::update_sleep(int contact_points)
{
    if (state == BodyState::Awake)
    {
        const float sum = length(linear_velocity) + length(angular_velocity) * radius_;
        if (sum < spec_.sleep_velocity && contact_points > 2)
        {
            state = BodyState::Asleep;
            linear_velocity = VEC3_ZERO;
            angular_velocity = VEC3_ZERO;
        }
    }
    return state;
}

Mat3 RigidBody::scaled_inv_world_tensor(Vec3 scale) const
{
    const Mat3 inv = from_diagonal(inverse_diagonal(inertia_ * scale));
    return rotation_ * inv * transpose(rotation_);
}

ContactMoment RigidBody::contact_moment(const BodyHit& hit) const
{
    ContactMoment m;
    m.mass = mass_ * hit.mass_scale;
    m.inverse_inertia = scaled_inv_world_tensor(hit.inertia_scale);
    m.centre = hit.has_centre ? hit.centre : world_cog();
    m.linear_velocity = linear_velocity;
    m.angular_velocity = angular_velocity;
    m.elasticity = hit.restitution;
    m.immobile = hit.immobile;
    m.breaking_impulse = hit.breaking_impulse;
    m.fixed_centre = hit.fixed_centre;
    return m;
}

void RigidBody::apply_contact_moment(const ContactMoment& moment)
{
    if (state == BodyState::Frozen || moment.immobile)
    {
        return;
    }
    wake();
    linear_velocity = moment.linear_velocity;
    angular_velocity = moment.angular_velocity;
}

bool RigidBody::react_plane_at(const PlaneContact& contact, const ContactParams& params, bool has_centre,
                               Vec3 centre, Reaction& out)
{
    if (state == BodyState::Frozen)
    {
        return false;
    }
    BodyHit hit;
    hit.restitution = params.restitution;
    hit.inertia_scale = params.inertia_scale;
    hit.has_centre = has_centre;
    hit.centre = centre;
    ContactMoment body = contact_moment(hit);
    ContactMoment surface;
    surface.mass = 1.0f;
    surface.inverse_inertia = MAT3_ZERO;
    surface.centre = contact.point;
    surface.linear_velocity = VEC3_ZERO;
    surface.angular_velocity = VEC3_ZERO;
    surface.elasticity = 0.0f;
    surface.immobile = true;
    surface.breaking_impulse = 0.0f;
    surface.fixed_centre = true;
    if (!react_moments(body, surface, contact, 16, out))
    {
        return false;
    }
    apply_contact_moment(body);
    return true;
}

bool RigidBody::react_plane(const PlaneContact& contact, const ContactParams& params, Reaction& out)
{
    return react_plane_at(contact, params, false, VEC3_ZERO, out);
}

bool RigidBody::ground_contact(Vec3 point, const Ground& ground, float dt, GroundContact& out) const
{
    if (spec_.no_ground_collisions || state != BodyState::Awake)
    {
        return false;
    }
    const float extent = length(transpose(rotation_) * VEC3_Y * dimension_);
    const Vec3 arm = point - world_cog();
    const float downward = angular_velocity.x * arm.z - angular_velocity.z * arm.x - linear_velocity.y;
    const float planar = std::hypot(linear_velocity.x, linear_velocity.z);
    const float ceiling = position.y + extent;
    const float lift = std::fmin(std::fmax(planar * dt + std::fmax(downward, 0.0f) * dt + extent, 0.25f),
                                 ceiling - point.y);
    if (!std::isfinite(lift) || lift <= 0.0f)
    {
        return false;
    }
    GroundHit hit;
    if (!ground.hit(point + VEC3_Y * lift, VEC3_NEG_Y, lift, hit))
    {
        return false;
    }
    const Vec3 normal = hit.normal * signum(hit.normal.y);
    const float depth = (lift - hit.distance) * normal.y;
    if (!is_finite(normal) || !std::isfinite(depth) || depth <= 0.000001f)
    {
        return false;
    }
    out.point = point;
    out.normal = normal;
    out.depth = depth;
    out.friction = ground.body_friction(hit.surface.tag);
    out.surface = hit.surface.tag;
    out.velocity = point_velocity(point);
    out.impulse_delta_v = 0.0f;
    return true;
}

void RigidBody::resolve_ground(std::vector<GroundContact>& contacts)
{
    std::stable_sort(contacts.begin(), contacts.end(),
                     [](const GroundContact& a, const GroundContact& b) { return total_less(b.depth, a.depth); });
    const RigidBodySpec spec = spec_;
    for (auto& c : contacts)
    {
        const Vec3 local = transpose(rotation_) * c.normal;
        ContactParams params;
        params.restitution = length(local * spec.ground_elasticity);
        params.inertia_scale = spec.ground_moment_scale;
        PlaneContact plane;
        plane.point = c.point;
        plane.normal = c.normal;
        plane.friction_static = spec.ground_friction[0] * c.friction;
        plane.friction_kinetic = std::fmin(spec.ground_friction[1], spec.ground_friction[0]) * c.friction;
        Reaction reaction;
        if (react_plane(plane, params, reaction))
        {
            c.impulse_delta_v = reaction.impulse / mass_;
            break;
        }
    }
    if (!contacts.empty())
    {
        position += contacts[0].normal * contacts[0].depth;
    }
}

bool react_moments(ContactMoment& a, ContactMoment& b, const PlaneContact& plane, uint32_t iterations,
                   Reaction& out)
{
    if (iterations == 0 || !moment_valid(a) || !moment_valid(b) || !is_finite(plane.point))
    {
        return false;
    }
    if (!std::isfinite(plane.friction_static) || !std::isfinite(plane.friction_kinetic))
    {
        return false;
    }
    Vec3 normal;
    if (!try_normalize(plane.normal, normal))
    {
        return false;
    }
    IterationBody left(a, plane.point, a.immobile && !b.immobile);
    IterationBody right(b, plane.point, b.immobile && !a.immobile);
    float mass = reduced_mass(a, b, left.immobile, right.immobile);
    bool has_reaction = false;
    for (uint32_t i = 0; i < iterations; ++i)
    {
        const Vec3 velocity = left.velocity() - right.velocity();
        const Vec3 momentum = velocity * mass;
        const float approach = -dot(momentum, normal);
        if (approach <= 0.0f)
        {
            break;
        }
        const auto tang = friction(momentum, normal, approach, plane);
        if (i == 0)
        {
            out.impulse = 0.0f;
            out.closing_speed = -dot(velocity, normal);
            out.sliding_speed = length(velocity + normal * out.closing_speed);
            out.friction = tang.second;
            has_reaction = true;
            left.release(a, approach);
            right.release(b, approach);
            mass = reduced_mass(a, b, left.immobile, right.immobile);
            continue;
        }
        const float fraction = static_cast<float>(i) / static_cast<float>(iterations);
        const Vec3 normal_impulse = normal * (approach * fraction);
        const Vec3 tangent_impulse = tang.first * fraction;
        left.apply(a, normal_impulse, tangent_impulse);
        right.apply(b, -normal_impulse, -tangent_impulse);
        out.impulse += approach * fraction;
    }
    left.finish(a);
    right.finish(b);
    return has_reaction;
}

bool react_joint_moments(ContactMoment& a, ContactMoment& b, Vec3 point, uint32_t iterations)
{
    if (iterations == 0 || !moment_valid(a) || !moment_valid(b) || !is_finite(point) || (a.immobile && b.immobile))
    {
        return false;
    }
    IterationBody left(a, point, a.immobile);
    IterationBody right(b, point, b.immobile);
    const float mass = reduced_mass(a, b, a.immobile, b.immobile);
    bool reacted = false;
    ContactMoment ma = a;
    ContactMoment mb = b;
    ma.elasticity = 0.0f;
    mb.elasticity = 0.0f;
    for (uint32_t i = 0; i < iterations; ++i)
    {
        const Vec3 momentum = (left.velocity() - right.velocity()) * mass;
        if (length_squared(momentum) == 0.0f)
        {
            break;
        }
        reacted = true;
        if (i == 0)
        {
            continue;
        }
        const Vec3 impulse = -momentum * (static_cast<float>(i) / static_cast<float>(iterations));
        left.apply(ma, impulse, VEC3_ZERO);
        right.apply(mb, -impulse, VEC3_ZERO);
    }
    if (reacted)
    {
        left.finish(a);
        right.finish(b);
    }
    return reacted;
}

ContactMoment RigidBody::joint_moment(Vec3 point) const
{
    BodyHit hit;
    hit.immobile = state == BodyState::Frozen;
    ContactMoment moment = contact_moment(hit);
    const Vec3 r = transpose(rotation_) * (point - world_cog());
    const Vec3 squared = r * r;
    const Vec3 offset{squared.y + squared.z, squared.x + squared.z, squared.x + squared.y};
    const Vec3 inverse = inverse_diagonal(inertia_ + offset * mass_);
    moment.inverse_inertia = rotation_ * from_diagonal(inverse) * transpose(rotation_);
    return moment;
}

Vec3 Obb::support(Vec3 direction) const
{
    const auto sign = [&](Vec3 axis) {
        const float v = dot(axis, direction);
        return v > 0.0f ? 1.0f : (v < 0.0f ? -1.0f : 0.0f);
    };
    return centre + axes.x_axis * (half.x * sign(axes.x_axis)) + axes.y_axis * (half.y * sign(axes.y_axis)) +
           axes.z_axis * (half.z * sign(axes.z_axis));
}

bool Face::clip(ObbContact& out) const
{
    const Vec3 delta = contact.point - reference->centre;
    int inside = 0;
    for (int side_index = 0; side_index < 2; ++side_index)
    {
        const int side = SIDE_AXES[axis][side_index];
        const Vec3 normal_side = orient(col(reference->axes, side), delta + travel);
        if (dot_d(to_d(delta), to_d(normal_side)) <= static_cast<double>(reference->half[side]))
        {
            ++inside;
            continue;
        }
        const Vec3 plane =
            to_f(to_d(reference->centre) + to_d(normal_side) * static_cast<double>(reference->half[side]));
        for (int axis_i = 0; axis_i < 3; ++axis_i)
        {
            const Vec3 edge_axis = col(incident->axes, axis_i);
            const double extent = dot_d(to_d(contact.point - incident->centre), to_d(edge_axis));
            const Vec3 reflected = to_f(to_d(contact.point) - to_d(edge_axis) * (2.0 * extent));
            Vec3 point;
            if (!segment_plane(reflected, contact.point, plane, normal_side, point))
            {
                continue;
            }
            const Vec3 offset = point - reference->centre;
            const double depth = -dot_d(to_d(offset), to_d(normal));
            if (depth >= static_cast<double>(reference->half[axis]))
            {
                continue;
            }
            bool contains = true;
            for (int k = 0; k < 2; ++k)
            {
                const int i = SIDE_AXES[side][k];
                const bool ok =
                    i == axis
                        ? depth <= static_cast<double>(reference->half[i])
                        : dot_d(to_d(offset), to_d(orient(col(reference->axes, i), offset + travel))) <=
                              static_cast<double>(reference->half[i]);
                if (!ok)
                {
                    contains = false;
                    break;
                }
            }
            if (!contains)
            {
                continue;
            }
            out.point = point;
            out.overlap = static_cast<float>(static_cast<double>(reference->half[axis]) - depth);
            return true;
        }
    }
    if (inside == 2)
    {
        out = contact;
        return true;
    }
    return false;
}

bool box_contact(const Obb& a, const Obb& b, Vec3 travel_a, Vec3 travel_b, ObbContact& out)
{
    if (!is_finite(travel_a) || !is_finite(travel_b) || !valid_obb(a) || !valid_obb(b))
    {
        return false;
    }
    bool has_best = false;
    float best_score = -std::numeric_limits<float>::infinity();
    Face best{};
    const Obb* refs[2] = {&a, &b};
    const Obb* incs[2] = {&b, &a};
    const Vec3 drs[2] = {travel_a, travel_b};
    const Vec3 dis[2] = {travel_b, travel_a};
    const bool on_first[2] = {false, true};
    for (int pair = 0; pair < 2; ++pair)
    {
        const Obb& reference = *refs[pair];
        const Obb& incident = *incs[pair];
        DVec3 delta = to_d(reference.centre) - to_d(incident.centre);
        delta.z = static_cast<double>(static_cast<float>(delta.z));
        const DVec3 relative = to_d(drs[pair]) - to_d(dis[pair]);
        const DVec3 previous = to_d(to_f(delta - relative));
        const int axes[3] = {0, 2, 1};
        for (int ai = 0; ai < 3; ++ai)
        {
            const int axis = axes[ai];
            const Vec3 axis_vector = col(reference.axes, axis);
            const Vec3 normal = dot_d(to_d(axis_vector), previous) < 0.0 ? -axis_vector : axis_vector;
            const DVec3 n = to_d(normal);
            float signed_distance =
                static_cast<float>(dot_d(delta, n) - static_cast<double>(reference.half[axis]));
            for (int i = 0; i < 3; ++i)
            {
                const double extent = std::fabs(dot_d(n, to_d(col(incident.axes, i) * incident.half[i])));
                signed_distance = static_cast<float>(static_cast<double>(signed_distance) - extent);
            }
            if (signed_distance > 0.0f)
            {
                return false;
            }
            const double score = static_cast<double>(signed_distance) - dot_d(relative, n);
            if (score <= static_cast<double>(best_score))
            {
                continue;
            }
            best_score = static_cast<float>(score);
            const Vec3 output_normal = on_first[pair] ? -normal : normal;
            ObbContact contact;
            contact.normal = output_normal;
            contact.point = incident.support(normal);
            contact.overlap = -signed_distance;
            contact.point_on_first = on_first[pair];
            best = Face{&reference, &incident, axis, normal, to_f(relative), contact};
            has_best = true;
        }
    }
    if (!has_best)
    {
        return false;
    }
    out = best.contact;
    return best.clip(out);
}

bool obb_contact(const Obb& a, const Obb& b, ObbContact& out)
{
    return box_contact(a, b, VEC3_ZERO, VEC3_ZERO, out);
}

bool sphere_contact(Sphere a, Sphere b, ObbContact& out)
{
    if (!is_finite(a.centre) || !is_finite(b.centre) || !std::isfinite(a.radius) || !std::isfinite(b.radius) ||
        a.radius <= 0.0f || b.radius <= 0.0f)
    {
        return false;
    }
    const float distance = length(a.centre - b.centre);
    if (distance == 0.0f)
    {
        out = {VEC3_NEG_Y, a.centre, a.radius, true};
        return true;
    }
    const float overlap = a.radius + b.radius - distance;
    if (overlap <= 0.0f || !std::isfinite(overlap))
    {
        return false;
    }
    const Vec3 normal = (a.centre - b.centre) / distance;
    out = {normal, a.centre - normal * a.radius, overlap, true};
    return true;
}

bool sphere_box_contact(Sphere sphere, const Obb& b, Vec3 travel, ObbContact& out)
{
    const float radius = sphere.radius;
    if (radius <= 0.0f || !std::isfinite(radius) || !is_finite(sphere.centre) || !is_finite(travel) ||
        !is_finite(b.centre) || !is_finite(b.half) || min_element(b.half) < 0.0f)
    {
        return false;
    }
    const Vec3 local = transpose(b.axes) * (sphere.centre - b.centre);
    const Vec3 previous = local - transpose(b.axes) * travel;
    Vec3 sign;
    sign.x = previous.x > 0.0f ? 1.0f : -1.0f;
    sign.y = previous.y > 0.0f ? 1.0f : -1.0f;
    sign.z = previous.z > 0.0f ? 1.0f : -1.0f;
    const Vec3 current = local * sign;
    const Vec3 before = previous * sign;
    const Vec3 reach = b.half + Vec3::splat(radius);
    if (current.x >= reach.x || current.y >= reach.y || current.z >= reach.z)
    {
        return false;
    }
    const Vec3 depth = b.half + Vec3::splat(radius) - current;
    const Vec3 old_depth = b.half + Vec3::splat(radius) - before;
    const Vec3 area{b.half.y * b.half.z, b.half.x * b.half.z, b.half.x * b.half.y};
    const bool outside[3] = {before.x > b.half.x, before.y > b.half.y, before.z > b.half.z};
    const bool any_outside = outside[0] || outside[1] || outside[2];
    const bool all_inside = current.x <= b.half.x && current.y <= b.half.y && current.z <= b.half.z;
    const auto flat_axis = [&]() -> int {
        for (int i = 0; i < 3; ++i)
        {
            if (outside[i] && area[i] > 0.0f)
            {
                return i;
            }
        }
        return -1;
    };
    if (all_inside || !any_outside)
    {
        int axis = -1;
        float best = 0.0f;
        const float depths[3] = {old_depth.x, old_depth.y, old_depth.z};
        for (int i = 0; i < 3; ++i)
        {
            if (area[i] <= 0.0f)
            {
                continue;
            }
            if (axis < 0 || total_less(depths[i], best))
            {
                axis = i;
                best = depths[i];
            }
        }
        if (axis < 0)
        {
            return false;
        }
        const Vec3 normal = col(b.axes, axis) * sign[axis];
        const float d[3] = {depth.x, depth.y, depth.z};
        out = {normal, sphere.centre + normal * d[axis], d[axis], false};
        return true;
    }
    const Vec3 offset = b.axes * select(outside, (b.half - current) * sign, VEC3_ZERO);
    const Vec3 point = sphere.centre + offset;
    const float length2 = length_squared(travel);
    const float projection = dot(offset + travel, travel);
    const bool full_volume = min_element(b.half) > 0.0f;
    if (length2 <= 1e-6f || projection <= 0.0f || projection >= length2)
    {
        if (full_volume)
        {
            const float distance = length(offset);
            if (distance <= 1e-6f)
            {
                return false;
            }
            const Vec3 direction = offset / distance;
            const float overlap = radius - distance;
            if (radius + dot(direction, travel) < distance || overlap <= 0.0f)
            {
                return false;
            }
            out = {-direction, point, overlap, false};
            return true;
        }
        const float offset2 = length_squared(offset);
        if (offset2 >= radius * radius)
        {
            return false;
        }
        const int axis = flat_axis();
        if (axis < 0)
        {
            return false;
        }
        const Vec3 normal = col(b.axes, axis) * sign[axis];
        const float along = dot(offset, normal);
        const float overlap = along + std::sqrt(along * along + radius * radius - offset2);
        if (overlap <= 1e-6f)
        {
            return false;
        }
        out = {normal, point, overlap, false};
        return true;
    }
    const Vec3 closest = sphere.centre - travel + travel * (projection / length2);
    const float distance2 = distance_squared(closest, point);
    const float radicand = radius * radius - distance2;
    if (radicand < 1e-6f)
    {
        return false;
    }
    if (!full_volume)
    {
        const int axis = flat_axis();
        if (axis < 0)
        {
            return false;
        }
        const float d[3] = {depth.x, depth.y, depth.z};
        out = {col(b.axes, axis) * sign[axis], point, d[axis], false};
        return true;
    }
    const Vec3 entry = closest - travel * std::sqrt(radicand / length2);
    Vec3 normal;
    if (!try_normalize(entry - point, normal))
    {
        return false;
    }
    const float overlap = radius - std::sqrt(distance2);
    if (overlap <= 0.0f)
    {
        return false;
    }
    out = {normal, point, overlap, false};
    return true;
}

bool resolve_bodies(RigidBody& a, RigidBody& b, const BodyContact& contact, const BodyHit& hit_a,
                    const BodyHit& hit_b, Separation separation, BodyReaction& out)
{
    if (a.state == BodyState::Frozen || b.state == BodyState::Frozen)
    {
        return false;
    }
    ContactMoment left = a.contact_moment(hit_a);
    ContactMoment right = b.contact_moment(hit_b);
    BodyContact c = contact;
    if (!std::isfinite(c.overlap) || c.overlap <= 1e-6f || !is_finite(c.point))
    {
        return false;
    }
    const Vec3 normal = c.normal;
    if (!is_finite(normal) || length_squared(normal) <= 1e-6f)
    {
        return false;
    }
    if (left.immobile && right.immobile)
    {
        for (ContactMoment* m : {&left, &right})
        {
            if (m->breaking_impulse <= 0.0f)
            {
                continue;
            }
            m->immobile = false;
            m->breaking_impulse = 0.0f;
        }
    }
    if (left.immobile && right.immobile)
    {
        return false;
    }
    float share;
    if (left.immobile)
    {
        share = 0.0f;
    }
    else if (right.immobile)
    {
        share = 1.0f;
    }
    else if (separation == Separation::Mass)
    {
        share = b.mass() / (a.mass() + b.mass());
    }
    else
    {
        const float va = -dot(a.linear_velocity, normal);
        const float vb = dot(b.linear_velocity, normal);
        const float closing = va + vb;
        if (std::fabs(closing) <= 1e-6f)
        {
            share = b.mass() / (a.mass() + b.mass());
        }
        else
        {
            const float own = closing > 0.0f ? va : vb;
            share = clamp(own / closing, 0.0f, 1.0f);
        }
    }
    const Vec3 delta_a = normal * (share * c.overlap);
    const Vec3 delta_b = normal * (-(1.0f - share) * c.overlap);
    a.position += delta_a;
    b.position += delta_b;
    left.centre += delta_a;
    right.centre += delta_b;
    c.point += c.point_on_first ? delta_a : delta_b;

    PlaneContact plane;
    plane.point = c.point;
    plane.normal = c.normal;
    plane.friction_static = c.friction_static;
    plane.friction_kinetic = c.friction_kinetic;
    Reaction reaction;
    if (!react_moments(left, right, plane, 32, reaction))
    {
        return false;
    }
    a.apply_contact_moment(left);
    b.apply_contact_moment(right);
    out.reaction = reaction;
    out.immobile[0] = left.immobile;
    out.immobile[1] = right.immobile;
    out.impulse_delta_v[0] = left.immobile ? 0.0f : reaction.impulse / left.mass;
    out.impulse_delta_v[1] = right.immobile ? 0.0f : reaction.impulse / right.mass;
    return true;
}

void separate(RigidBody& a, RigidBody& b, Vec3 normal, float overlap)
{
    const float total = a.mass() + b.mass();
    const float move_b = a.mass() / total;
    a.position += normal * (overlap * (1.0f - move_b));
    b.position -= normal * (overlap * move_b);
}

bool react_bodies(RigidBody& a, RigidBody& b, const BodyContact& contact, const BodyHit& hit_a,
                  const BodyHit& hit_b, Reaction& out)
{
    if (a.state == BodyState::Frozen || b.state == BodyState::Frozen)
    {
        return false;
    }
    ContactMoment left = a.contact_moment(hit_a);
    ContactMoment right = b.contact_moment(hit_b);
    PlaneContact plane;
    plane.point = contact.point;
    plane.normal = contact.normal;
    plane.friction_static = contact.friction_static;
    plane.friction_kinetic = contact.friction_kinetic;
    if (!react_moments(left, right, plane, 32, out))
    {
        return false;
    }
    a.apply_contact_moment(left);
    b.apply_contact_moment(right);
    return true;
}

std::pair<Vec3, Vec3> BallJoint::world_anchors(const RigidBody& a, const RigidBody& b) const
{
    return {a.position + a.rotation() * anchor_a, b.position + b.rotation() * anchor_b};
}

float BallJoint::gap(const RigidBody& a, const RigidBody& b) const
{
    const auto anchors = world_anchors(a, b);
    return distance(anchors.first, anchors.second);
}

Vec3 BallJoint::fulcrum(const RigidBody& a, const RigidBody& b) const
{
    const auto anchors = world_anchors(a, b);
    if (a.state == BodyState::Frozen)
    {
        return anchors.first;
    }
    if (b.state == BodyState::Frozen)
    {
        return anchors.second;
    }
    const float share = a.mass() / (a.mass() + b.mass());
    return anchors.first * share + anchors.second * (1.0f - share);
}

void BallJoint::solve(RigidBody& a, RigidBody& b, float dt, int iterations) const
{
    if (!std::isfinite(dt) || dt <= 0.0f || iterations == 0 ||
        (a.state == BodyState::Frozen && b.state == BodyState::Frozen))
    {
        return;
    }
    const Vec3 centre = fulcrum(a, b);
    const auto set_fulcrum = [&](RigidBody& body, Vec3 anchor) {
        if (body.state == BodyState::Frozen)
        {
            return;
        }
        const Vec3 arm = body.rotation() * anchor;
        Vec3 from;
        Vec3 to;
        if (try_normalize(arm, from) && try_normalize(centre - body.position, to))
        {
            body.set_orientation(from_rotation_arc(from, to) * body.orientation);
        }
        const Vec3 p = centre - body.rotation() * anchor;
        if (distance_squared(p, body.position) > 0.000001f)
        {
            body.wake();
        }
        body.position = p;
    };
    set_fulcrum(a, anchor_a);
    set_fulcrum(b, anchor_b);
    ContactMoment ma = a.joint_moment(centre);
    ContactMoment mb = b.joint_moment(centre);
    if (react_joint_moments(ma, mb, centre, static_cast<uint32_t>(iterations)))
    {
        a.apply_contact_moment(ma);
        b.apply_contact_moment(mb);
    }
}

bool AngularLimit::exceeded(const RigidBody& a, const RigidBody& b, Quat& frame_out, float& delta) const
{
    const Vec3 vector = b.rotation() * vector_b;
    Quat frame = a.orientation * frame_a;
    if (mode == LimitMode::Conical)
    {
        const Vec3 local = conjugate(frame) * vector;
        const Quat x = rotation_x(-std::atan2(local.y, local.z));
        const Quat z = rotation_z(std::atan2(local.y, local.x));
        frame = frame * (z * x);
    }
    const Vec3 local = conjugate(frame) * vector;
    const float angle = std::atan2(local.x, local.z);
    if (angle > positive)
    {
        frame_out = frame;
        delta = positive - angle;
        return true;
    }
    if (angle < -negative)
    {
        frame_out = frame;
        delta = -negative - angle;
        return true;
    }
    return false;
}

void AngularLimit::solve(const BallJoint& joint, RigidBody& a, RigidBody& b) const
{
    Quat frame;
    float delta;
    if (!exceeded(a, b, frame, delta))
    {
        return;
    }
    const Vec3 centre = joint.fulcrum(a, b);
    const float share =
        a.state == BodyState::Frozen ? 1.0f : (b.state == BodyState::Frozen ? 0.0f : a.mass() / (a.mass() + b.mass()));
    const auto turn = [&](RigidBody& body, Vec3 anchor, float angle) {
        if (body.state == BodyState::Frozen)
        {
            return;
        }
        const Quat o = frame * rotation_y(angle) * conjugate(frame) * body.orientation;
        body.set_orientation(o);
        body.position = centre - body.rotation() * anchor;
    };
    turn(a, joint.anchor_a, -(1.0f - share) * delta);
    turn(b, joint.anchor_b, share * delta);

    const bool positive_side = delta < 0.0f;
    const float angle = positive_side ? positive : negative;
    const float sign = positive_side ? 1.0f : -1.0f;
    float sin_a;
    float cos_a;
    sin_cos(angle, sin_a, cos_a);
    const Vec3 normal = frame * Vec3{-sign * cos_a, 0.0f, sin_a};
    const Vec3 point = centre + frame * (Vec3{sign * sin_a, 0.0f, cos_a} * length(vector_b));
    BodyHit hit_a;
    hit_a.immobile = a.state == BodyState::Frozen;
    BodyHit hit_b;
    hit_b.immobile = b.state == BodyState::Frozen;
    ContactMoment ma = a.contact_moment(hit_a);
    ContactMoment mb = b.contact_moment(hit_b);
    PlaneContact plane;
    plane.point = point;
    plane.normal = normal;
    plane.friction_static = 0.0f;
    plane.friction_kinetic = 0.0f;
    Reaction reaction;
    if (react_moments(ma, mb, plane, 32, reaction))
    {
        a.apply_contact_moment(ma);
        b.apply_contact_moment(mb);
    }
}
} // namespace atelier::driving
