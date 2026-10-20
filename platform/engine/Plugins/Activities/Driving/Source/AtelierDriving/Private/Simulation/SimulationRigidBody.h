#pragma once

#include "SimulationGround.h"
#include "SimulationSpec.h"

#include <array>
#include <vector>

namespace atelier::driving
{
inline constexpr float MAX_LINEAR_SPEED = 300.0f;
inline constexpr float MAX_ANGULAR_SPEED = 30.0f;

struct PlaneContact
{
    Vec3 point = VEC3_ZERO;
    Vec3 normal = VEC3_Y;
    float friction_static = 0.0f;
    float friction_kinetic = 0.0f;
};

struct ContactParams
{
    float restitution = 0.0f;
    Vec3 inertia_scale = VEC3_ONE;
};

struct Reaction
{
    float impulse = 0.0f;
    float closing_speed = 0.0f;
    float sliding_speed = 0.0f;
    FrictionState friction = FrictionState::None;
};

struct GroundContact
{
    Vec3 point = VEC3_ZERO;
    Vec3 normal = VEC3_Y;
    float depth = 0.0f;
    float friction = 0.0f;
    uint32_t surface = 0;
    Vec3 velocity = VEC3_ZERO;
    float impulse_delta_v = 0.0f;
};

struct BodyHit
{
    float restitution = 0.0f;
    Vec3 inertia_scale = VEC3_ONE;
    float mass_scale = 1.0f;
    bool has_centre = false;
    Vec3 centre = VEC3_ZERO;
    bool immobile = false;
    float breaking_impulse = 0.0f;
    bool fixed_centre = false;
};

struct ContactMoment
{
    float mass = 0.0f;
    Mat3 inverse_inertia = MAT3_ZERO;
    Vec3 centre = VEC3_ZERO;
    Vec3 linear_velocity = VEC3_ZERO;
    Vec3 angular_velocity = VEC3_ZERO;
    float elasticity = 0.0f;
    bool immobile = false;
    float breaking_impulse = 0.0f;
    bool fixed_centre = false;
};

struct BodyContact
{
    Vec3 point = VEC3_ZERO;
    Vec3 normal = VEC3_Y;
    float overlap = 0.0f;
    float friction_static = 0.0f;
    float friction_kinetic = 0.0f;
    bool point_on_first = false;
};

struct BodyReaction
{
    Reaction reaction;
    bool immobile[2] = {false, false};
    float impulse_delta_v[2] = {0.0f, 0.0f};
};

class RigidBody
{
public:
    Vec3 position = VEC3_ZERO;
    Quat orientation = QUAT_IDENTITY;
    Vec3 linear_velocity = VEC3_ZERO;
    Vec3 angular_velocity = VEC3_ZERO;
    BodyState state = BodyState::Awake;

    RigidBody() = default;
    RigidBody(float mass, Vec3 dimension, Vec3 tensor_scale, const RigidBodySpec& spec);

    float mass() const { return mass_; }
    Vec3 inertia() const { return inertia_; }
    Vec3 dimension() const { return dimension_; }
    float radius() const { return radius_; }
    const RigidBodySpec& spec() const { return spec_; }
    Vec3 cog() const { return cog_; }
    void set_cog(Vec3 cog) { cog_ = cog; }
    void set_mass(float mass);
    Mat3 rotation() const { return rotation_; }
    Mat3 inv_world_tensor() const { return inv_world_tensor_; }
    Vec3 world_cog() const { return position + rotation_ * cog_; }
    Vec3 point_velocity(Vec3 world_point) const
    {
        return linear_velocity + cross(angular_velocity, world_point - world_cog());
    }
    Vec3 pending_force() const { return force_; }
    Vec3 pending_torque() const { return torque_; }
    void place(Vec3 position, Quat orientation);
    void wake();
    void set_orientation(Quat orientation);
    void apply_force(Vec3 force);
    void apply_torque(Vec3 torque);
    void apply_force_at(Vec3 force, Vec3 world_point);
    void apply_impulse_at(Vec3 impulse, Vec3 world_point);
    void apply_torque_at(Vec3 force, Vec3 world_point);
    void accelerate(Vec3 accel, float dt);
    void damp(float k);
    void begin_frame(float dt);
    void apply_drag();
    BodyState update_sleep(int contact_points);
    Mat3 scaled_inv_world_tensor(Vec3 scale) const;
    ContactMoment contact_moment(const BodyHit& hit) const;
    void apply_contact_moment(const ContactMoment& moment);
    bool react_plane(const PlaneContact& contact, const ContactParams& params, Reaction& out);
    bool react_plane_at(const PlaneContact& contact, const ContactParams& params, bool has_centre, Vec3 centre,
                        Reaction& out);
    bool ground_contact(Vec3 point, const Ground& ground, float dt, GroundContact& out) const;
    void resolve_ground(std::vector<GroundContact>& contacts);
    ContactMoment joint_moment(Vec3 point) const;

private:
    float mass_ = 1.0f;
    float inv_mass_ = 1.0f;
    Vec3 inertia_ = VEC3_ONE;
    Vec3 dimension_ = VEC3_ONE;
    float radius_ = 0.0f;
    Vec3 cog_ = VEC3_ZERO;
    Vec3 force_ = VEC3_ZERO;
    Vec3 torque_ = VEC3_ZERO;
    Mat3 rotation_ = MAT3_IDENTITY;
    Mat3 inv_world_tensor_ = MAT3_IDENTITY;
    RigidBodySpec spec_;

    void refresh_matrices();
};

struct Obb
{
    Vec3 centre = VEC3_ZERO;
    Mat3 axes = MAT3_IDENTITY;
    Vec3 half = VEC3_ONE;
    Vec3 support(Vec3 direction) const;
};

struct ObbContact
{
    Vec3 normal = VEC3_Y;
    Vec3 point = VEC3_ZERO;
    float overlap = 0.0f;
    bool point_on_first = false;
};

struct Sphere
{
    Vec3 centre = VEC3_ZERO;
    float radius = 0.0f;
};

struct BallJoint
{
    Vec3 anchor_a = VEC3_ZERO;
    Vec3 anchor_b = VEC3_ZERO;
    std::pair<Vec3, Vec3> world_anchors(const RigidBody& a, const RigidBody& b) const;
    float gap(const RigidBody& a, const RigidBody& b) const;
    Vec3 fulcrum(const RigidBody& a, const RigidBody& b) const;
    void solve(RigidBody& a, RigidBody& b, float dt, int iterations) const;
};

struct AngularLimit
{
    Quat frame_a = QUAT_IDENTITY;
    Vec3 vector_b = VEC3_ZERO;
    float positive = 0.0f;
    float negative = 0.0f;
    LimitMode mode = LimitMode::Prismatic;
    bool exceeded(const RigidBody& a, const RigidBody& b, Quat& frame, float& delta) const;
    void solve(const BallJoint& joint, RigidBody& a, RigidBody& b) const;
};

bool react_moments(ContactMoment& a, ContactMoment& b, const PlaneContact& plane, uint32_t iterations,
                   Reaction& out);
bool react_joint_moments(ContactMoment& a, ContactMoment& b, Vec3 point, uint32_t iterations);
bool resolve_bodies(RigidBody& a, RigidBody& b, const BodyContact& contact, const BodyHit& hit_a,
                    const BodyHit& hit_b, Separation separation, BodyReaction& out);
void separate(RigidBody& a, RigidBody& b, Vec3 normal, float overlap);
bool react_bodies(RigidBody& a, RigidBody& b, const BodyContact& contact, const BodyHit& hit_a,
                  const BodyHit& hit_b, Reaction& out);
bool obb_contact(const Obb& a, const Obb& b, ObbContact& out);
bool box_contact(const Obb& a, const Obb& b, Vec3 travel_a, Vec3 travel_b, ObbContact& out);
bool sphere_contact(Sphere a, Sphere b, ObbContact& out);
bool sphere_box_contact(Sphere sphere, const Obb& b, Vec3 travel, ObbContact& out);
Vec3 box_inertia(float mass, Vec3 half);
Vec3 inverse_diagonal(Vec3 inertia);
} // namespace atelier::driving
