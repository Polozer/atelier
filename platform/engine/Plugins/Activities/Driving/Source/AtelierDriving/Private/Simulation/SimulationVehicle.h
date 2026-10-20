#pragma once

#include "SimulationAero.h"
#include "SimulationBrakes.h"
#include "SimulationDrivetrain.h"
#include "SimulationInput.h"
#include "SimulationRigidBody.h"
#include "SimulationSteering.h"
#include "SimulationSuspension.h"
#include "SimulationTires.h"

#include <optional>
#include <vector>

namespace atelier::driving
{
inline constexpr float FIXED_STEP = 1.0f / 60.0f;

struct JumpInput
{
    float dt = 0.0f;
    float mass = 0.0f;
    Vec3 inertia = VEC3_ONE;
    Mat3 rotation = MAT3_IDENTITY;
    Vec3 linear_velocity = VEC3_ZERO;
    Vec3 angular_velocity = VEC3_ZERO;
    float speed = 0.0f;
    int grounded_wheels = 0;
    bool body_contact = false;
    bool has_ground = false;
    GroundReference ground;
};

struct JumpForces
{
    Vec3 force = VEC3_ZERO;
    Vec3 torque = VEC3_ZERO;
    bool operator==(const JumpForces& o) const { return force == o.force && torque == o.torque; }
};

struct JumpState
{
    float airborne_time = 0.0f;
    float peak_altitude = 0.0f;
    JumpForces update(const JumpConfig& config, const JumpInput& input);
    float landing(const JumpConfig& config, const JumpInput& input) const;
};

struct WallSteering
{
    float nose = 0.0f;
    float side = 0.0f;
    float yaw(float steer, float gas, int grounded, bool reverse, float gain) const;
};

struct Burnout
{
    int state = 0;
    float traction = 0.0f;
    float time = 0.0f;
    float release_time = 0.0f;
    void update(float dt, bool active, float speed, float body_slip, float slip, int wheel);
};

struct Drift
{
    enum class Phase : uint8_t
    {
        Out,
        Enter,
        In,
        Exit,
    };
    Phase phase = Phase::Out;
    float value = 0.0f;
    float speed = 0.0f;
};

class Vehicle
{
public:
    Tunings tunings;
    ControlConfig config;
    bool has_forced_wheel_angles = false;
    WheelAngles forced_wheel_angles;
    bool disabled = false;
    bool can_recharge_nos = true;
    ManeuverAssist maneuver;
    JumpConfig jump_config;
    bool has_ground_reference = false;
    GroundReference ground_reference;
    WallSteeringConfig wall_steering_config;
    TireDamage tire_damage;
    VehicleSpec spec;

    explicit Vehicle(const VehicleSpec& spec);

    const VehicleSpec& spec_ref() const { return spec; }
    const std::vector<GroundContact>& body_contacts() const { return body_contacts_; }

    void place(Vec3 position, Quat orientation);
    void place_moving(Vec3 position, Quat orientation, float speed);
    bool place_on_ground(const Ground& ground, float x, float z, float top, float yaw);
    bool place_on_ground_moving(const Ground& ground, float x, float z, float top, float yaw, float speed);

    Vec3 position() const { return body.position; }
    Quat orientation() const { return body.orientation; }
    Mat3 rotation() const { return body.rotation(); }
    Vec3 linear_velocity() const { return body.linear_velocity; }
    Vec3 angular_velocity() const { return body.angular_velocity; }
    float speed() const { return length(body.linear_velocity); }
    float forward_speed() const
    {
        return (transpose(body.rotation()) * body.linear_velocity).z;
    }
    int gear() const { return powertrain.gear_id(); }
    float rpm() const { return powertrain.rpm(); }
    int wheels_on_ground() const { return wheels_on_ground_; }
    const Controls& controls() const { return controls_; }
    float slip_angle() const { return body_slip; }
    float time() const { return time_; }
    bool is_asleep() const { return body.state == BodyState::Asleep; }
    float nos_level() const { return powertrain.nos.capacity; }
    bool nos_burning() const { return powertrain.nos.boost > 1.0f; }
    bool has_nos() const { return powertrain.has_nos(); }
    float boost_psi() const { return powertrain.induction.psi; }
    WheelAngles wheel_angles() const { return wheel_angles_; }
    WheelState wheel(int i) const;
    bool wheel_surface_tag(int i, uint32_t& out) const;
    bool wheel_ground_hit(int i, Vec3& point, Vec3& normal) const;
    void notify_collision(float impulse);
    bool shift_to(int gear) { return powertrain.shift(gear); }
    void set_no_rev_limiter(bool on) { powertrain.set_no_rev_limiter(on); }

    TireIntegration tire_integration() const { return tire_integration_; }
    float drift_strength() const { return drift_.value; }
    void set_tire_integration(TireIntegration integration);

    void step(float dt, const InputState& input, const Ground& ground);

    void notify_wall_contact(Vec3 point, Vec3 normal, Vec3 closing_velocity, Vec3 body_velocity);
    std::pair<Vec3, ContactParams> wall_reaction(Vec3 normal, ContactParams params) const;
    void set_spec(const VehicleSpec& new_spec);
    void modify_object_hit(BodyHit& hit) const;

    static VehicleSpec example();

    RigidBody body;
    Powertrain powertrain;

private:
    Geometry geometry;
    TireParams params[4];
    Steering steering;
    WheelAngles wheel_angles_;
    Tire tires[4];
    TireIntegration tire_integration_ = TireIntegration::Regularized;
    Corner corners_[4];
    WheelContact contacts_[4];
    bool contact_valid_[4] = {false, false, false, false};
    bool loaded_[4] = {false, false, false, false};
    Vec3 patch_positions_[4];
    int wheels_on_ground_ = 0;
    int wheels_on_ground_prev_ = 0;
    Controls controls_;
    float yaw_control = 1.0f;
    Burnout burnout_;
    Drift drift_;
    float body_slip = 0.0f;
    bool collided = false;
    float time_ = 0.0f;
    bool body_ground_contact_ = false;
    std::vector<GroundContact> body_contacts_;
    JumpState jump_state_;
    WallSteering wall_steering_;

    void reset_dynamics();
    void update_controls(const InputState& input, float forward_speed);
    void update_steering(float dt, float forward_speed);
    void run_powertrain(float dt, float speed);
    bool is_drifting() const;
    void apply_aero();
    void sanitize();
    void begin_tires(float speed);
    void tune_tires(float dt, float speed, Vec3 angular_velocity);
    void update_drift(float dt, float speed, Vec3 angular_velocity);
    void distribute_drive(float torque, const std::array<float, 4>& av, const std::array<bool, 4>& grounded);
    int collide_body_with_ground(const Ground& ground);
    struct WheelOutput
    {
        Vec3 force = VEC3_ZERO;
        Vec3 torque = VEC3_ZERO;
        float lift_need = 0.0f;
    };
    WheelOutput wheel_forces(float dt, const Ground& ground, Vec3 angular_velocity);
    Vec3 damp_landing(Vec3 angular_velocity);
    void damp_creep(bool collided, Vec3 angular_velocity);
    void set_pending(Vec3 force, Vec3 torque);
    void apply_jump(float dt, float speed, Vec3 angular_velocity);
    void apply_wall_steering();
};
} // namespace atelier::driving
