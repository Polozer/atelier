#include "GameplayFrameRuntime.h"
#include "SkeletonLineQueries.h"
#include <algorithm>
#include <cmath>
#include <cassert>
#include <cstring>
#if defined(__clang__)
#pragma clang fp contract(off)
#endif
namespace atelier::skate
{
namespace
{
Vec4 Value(RawVector raw){Vec4 value;std::memcpy(value.data(),raw.data(),16);return value;}
Vec3 Xyz(Vec4 value){return {value[0],value[1],value[2]};}
bool DefaultTrainer(const TrainerTuning& t)
{
    return t.pop==1 && t.grind_pop==1 && t.push_speed==1 && t.push_power==1
        && t.braking==1 && t.steering==1 && t.wobble==1 && t.offboard_jump==1
        && t.grip==1 && t.turn_power==1 && t.manual_drag==1 && !t.hold_fakie
        && t.rolling_friction==1 && t.hill_speed==1 && t.wobble_onset==1 && t.manual_drift==1;
}
// The deck's accumulated torque is checked after each stage that adds to it, so a non-finite one names its source
// instead of surfacing later as an anonymous "before shared solve" failure.
bool DeckTorqueFinite(const PhysicalSimulationRuntime& f,const char* stage,std::string& error)
{
    const auto& t=f.board.Bodies()[6].rates.torque_acceleration;
    if(std::isfinite(t.x)&&std::isfinite(t.y)&&std::isfinite(t.z))return true;
    error=std::string("Non-finite deck torque_acceleration after ")+stage;return false;
}
void CheckOwners(const GameplayFrameOwners& o)
{
    static_cast<void>(o);
    const auto& p=o.post.states.player;static_cast<void>(p);
    assert(&p.physical==&o.input.player.physical && &p.physical==&o.publication.shared.physical);
    assert(&p.physical==&o.animation.physics && &p.physical==&o.feedback.physics && &p.physical==&o.climbing_frame.physical);
    assert(&p.input==&o.input.player.input && &p.input==&o.publication.shared.input);
    assert(&p.input==&o.animation.input && &p.input==&o.feedback.input && &p.input==&o.climbing_frame.player);
    assert(&p.state==&o.input.player.state && &p.state==&o.publication.shared.state);
    assert(&o.post.states.animation==&o.animation.animation && &o.animation.animation==&o.feedback.animation);
    assert(&o.animation.conditioning==&p.state.conditioning && &o.feedback.conditioning==&p.state.conditioning);
    assert(&o.animation.feedback==&o.feedback.publication && &o.animation.feedback_owner==&o.feedback.conditioner);
    assert(&o.post.states.ground_settings==&o.ground_settings && &o.post.states.slide.ground_settings==&o.ground_settings);
    assert(&o.post.states.ground_animation.trainer==&o.animation.trainer);
    assert(&o.animation.centre_of_mass==&o.centre_of_mass_output && &o.climbing_frame.centre_of_mass_output==&o.centre_of_mass_output);
    assert(&o.climbing_frame.centre_of_mass_filter==&o.centre_of_mass_filter);
    assert(&o.climbing_frame.render_pose==&o.post.render.render_pose && &o.climbing_frame.pose_generation==&o.post.render.pose_generation);
}
class ClimbingStages final:public ClimbingGlobalStages
{
    GameplayFrameOwners owners;
    PlayerStatePhases& phases;
public:
    ClimbingStages(GameplayFrameOwners o,PlayerStatePhases& p):owners(o),phases(p){}
    bool AdvanceCamera(ClimbingFrame&,camera::CameraRuntime& camera,std::string& error) override
    {
        camera::CameraOutputResult result;
        return camera::AdvanceCameraOutput(BindGameplayCameraFrame(owners),owners.post.states.player.exchange,camera,result,error);
    }
    void FinishClockTick() override{owners.clock.FinishTick();}
    bool ResumeAfterClimb(ClimbingFrame&,std::string& error) override{return phases.ResumeAfterClimb(error);}
};
class TrajectoryPublication final:public PlayerTrajectoryGrindOwner
{
    const AirTrajectorySelector& selector;
public:
    explicit TrajectoryPublication(const AirTrajectorySelector& s):selector(s){}
    bool GrindLockedToMiddle() const override{return selector.GrindLockedToMiddle();}
};
// Wall-follow air (FeelTuning::wall_follow, WallFollow.h), right after the physics step so the post-physics phases,
// publication, camera and next update all see the same turned state. On steep ground it measures the wall's plan
// curvature for the next launch. Through an air AirTrajectoryRuntime::Launch latched, every update turns each body's
// velocity, the board's and the rider's, about world up by the latched curvature times the board's horizontal speed
// (a pure centripetal turn: the speed and the climb stay), and yaws the air reckoning's up and heading with it so the
// rider and the board turn with the path; the first air update also gives every body that yaw rate. Positions follow
// by integration. It stops when the air does (a landing, a bail, a grind or a plant) or after MaximumTime. At strength 0
// (stock) it returns before reading or writing anything.
void AdvanceWallFollowAir(PlayerStatePhaseOwners& s,bool teleported)
{
    auto& w=s.air.trajectory.wall_follow;if(!(w.strength>0.0f))return;
    auto& f=s.player.physical;auto& selector=s.air.trajectory.selector;
    if(teleported){w.Reset();selector.SetWallFollow(0,0);return;}
    using S=PhysicalStateId;const auto state=s.player.state.Current();
    const bool air=state==S::PhysicsAir||state==S::KnownAir||state==S::PhysicsAirSecondary;
    const bool ground=state==S::PhysicsGround||state==S::SlideGround||state==S::RevertGround||state==S::GroundAnimation;
    const float dt=s.player.input.processed.timestep_2604;
    const auto& deck=f.board.Bodies()[std::size_t(BoardBodyId::Deck)].rates;
    const float speed=std::sqrt(deck.linear_velocity.x*deck.linear_velocity.x+deck.linear_velocity.z*deck.linear_velocity.z);
    if(w.pending)
    {
        if(air)
        {
            // The air leaves the wall straight up (any speed away from it dropped) and takes the turn's yaw rate.
            w.pending=false;w.active=true;w.elapsed=0;
            const float rate=w.curvature*speed;
            const auto start=[&w,rate](auto& body){
                body.rates.linear_velocity=WallFollowInward(body.rates.linear_velocity,w.inward_x,w.inward_z);
                body.rates.angular_velocity.y+=rate;};
            for(auto& body:f.board.BodiesMut())start(body);
            for(auto& body:f.skeleton.BodiesMut())start(body);
            auto& com=s.physics_air.state.centre_of_mass_trajectory.velocity;
            const auto straight=WallFollowInward(Vec3(com[0],com[1],com[2]),w.inward_x,w.inward_z);com[0]=straight.x;com[2]=straight.z;
        }
        else if(++w.pending_ticks>WallFollowAir::PendingTicks){w.Stop();selector.SetWallFollow(0,0);}
    }
    if(w.active)
    {
        if(!air || w.elapsed>=WallFollowAir::MaximumTime){w.Stop();selector.SetWallFollow(0,0);}
        else
        {
            const float turn=w.curvature*speed*dt;
            const auto yaw=[turn](auto& body){
                body.rates.linear_velocity=YawAboutUp(body.rates.linear_velocity,turn);
                body.rates.angular_velocity=YawAboutUp(body.rates.angular_velocity,turn);};
            for(auto& body:f.board.BodiesMut())yaw(body);
            for(auto& body:f.skeleton.BodiesMut())yaw(body);
            auto& reckoning=f.riding.reckoning;
            reckoning.up=YawAboutUp(reckoning.up,turn);reckoning.dynamic_up=YawAboutUp(reckoning.dynamic_up,turn);
            reckoning.target=YawAboutUp(reckoning.target,turn);
            f.riding.reckoning_frames.heading=YawAboutUp(f.riding.reckoning_frames.heading,turn);
            // PhysicsAir's own centre-of-mass arc (once every prediction missed) is integrated a step at a time.
            auto& com=s.physics_air.state.centre_of_mass_trajectory;com.velocity=YawAboutUp(com.velocity,turn);
            w.elapsed+=dt;
        }
    }
    if(ground)
    {
        const auto normal=Xyz(Value(s.player.input.processed.vectors_464_480_496_512_528[0]));
        w.tracker.Observe(normal,deck.position,WallFollowSteepNormalY);w.ticks_since_ground=0;
    }
    else {w.tracker.Reset();if(w.ticks_since_ground<0xffff)++w.ticks_since_ground;}
}
bool PublishExchange(GameplayFrameOwners o,std::uint64_t tick,std::string& error)
{
    const auto& states=o.post.states;const auto& f=states.player.physical;
    const auto& deck=f.board.Bodies()[6];const auto& bodies=f.skeleton.Bodies();
    if(bodies.empty()){error="Physical output requires the constructed rider body";return false;}
    const auto& rider=bodies.front();const auto& events=states.player.exchange.Events();
    const bool landed=std::any_of(events.begin(),events.end(),[](const PhysicsEvent& event){return std::holds_alternative<PhysicsLanding>(event);});
    states.player.exchange.PublishOutput({tick,states.player.state.Current(),deck.rates.position,
        deck.rates.linear_velocity,rider.rates.position,rider.rates.linear_velocity,
        f.riding.ground.wheel_normal,static_cast<std::uint32_t>(f.riding.ground.part_contact_count),
        Xyz(Value(states.player.input.physical.collision.predicted_position_64)),
        states.player.state.Current()==PhysicalStateId::PhysicsGround,f.skeleton_collision.is_ragdoll,landed,events});
    error.clear();return true;
}
bool AdvanceScoring(GameplayFrameOwners o,std::uint64_t tick,bool teleported,std::string& error)
{
    auto& states=o.post.states;const auto& f=states.player.physical;
    const auto& score=states.animation.motion.score_packet;
    const auto& deck=f.board.Bodies()[6];const auto frame=f.board.PartTransforms()[6];
    const auto& filtered=states.player.state.conditioning.filtered_output;
    const auto& quality=states.player.state.conditioning.landing_quality;
    const auto& output=states.player.input.physical;const auto& pose=states.animation.packet;
    ScoringFrame input;
    input.tick=static_cast<std::uint32_t>(tick);input.dt=f.settings.board.step.simulation.time_step;
    input.category=filtered?static_cast<std::uint32_t>(filtered->category):0;
    input.state=static_cast<std::uint32_t>(states.player.state.Current());
    input.descriptor=score.trick_names[0];if(!input.descriptor && score.grab)input.descriptor=score.grab->first;
    input.grind_id=filtered?filtered->grind.scorable_id:-1;input.flags=score.flags;
    input.position={deck.rates.position.x,deck.rates.position.y,deck.rates.position.z};
    input.velocity={deck.rates.linear_velocity.x,deck.rates.linear_velocity.y,deck.rates.linear_velocity.z};
    input.forward=frame.basis.columns[2];input.switch_stance=pose.riding_switch;input.fakie=pose.riding_fakie;
    input.nollie=pose.weight_forwards;input.body_flip=output.air.flag_441!=0;
    input.suspend_air=output.air.use_air_reckoning_452!=0;input.teleported=teleported;input.reverting=output.state.flag_66!=0;
    input.landing_data_167=quality.landing_data_167;input.landing_type_96=quality.landing_type_96;
    input.sideways_speed_84=quality.sideways_speed_84;input.spin_92=quality.spin_92;
    return o.scoring.Advance(input,error);
}
}
camera::CameraPublicationFrame BindGameplayCameraFrame(GameplayFrameOwners o)
{
    const auto& s=o.post.states;const auto& p=s.player;
    return {p.physical,p.input.processed,p.input.physical,p.input.toolkit?&*p.input.toolkit:nullptr,
        s.ground.ground,p.animation_input,s.animation,o.feedback.publication,o.centre_of_mass_output,
        p.state.Current(),p.state.state_flags[81-52]};
}
bool AdvanceGameplayFrame(GameplayFrameOwners o,ActionMap& original_actions,bool input_available,std::string& error)
{
    CheckOwners(o);auto& s=o.post.states;auto& shared=s.player;auto& f=shared.physical;
    const auto tick=f.ticks;shared.exchange=SimulationExchange(tick);
    auto requests=std::move(o.camera.simulation_rate_requests);o.camera.simulation_rate_requests.clear();
    for(const auto& request:requests)if(!o.network_active && !o.clock.Apply(request,error))return false;
    if(o.network_active)o.clock=SimulationClock{};
    PlayerStatePhases phases(s);
    if(f.ticks==0 && !InitializePlayerPhysicalState(shared,phases,error))return false;
    ClimbingStages climbing_stages(o,phases);bool climbed=false;
    const ClimbingControls climbing_controls{o.controls.controller,o.controls.offboard_direction};
    if(!o.climbing.Advance(o.climbing_frame,climbing_controls,o.camera,climbing_stages,climbed,error))return false;
    if(climbed){error.clear();return true;}
    if(!s.biped_air.ConsumeSelector(s.biped,error))return false;
    f.board.ClearForces();if(!f.BeginBoardQueries(error))return false;
    SkeletonLineTests skeleton_queries;if(!QuerySkeletonLines(f.world,f.skeleton,skeleton_queries,error))return false;
    AnimationPhaseOutput animation;
    if(!AdvanceAnimationPhase(o.animation,{o.controls.action_intents,o.controls.controller,o.controls.actor_flags},
        o.graphs,o.animation_profile,f.settings.board.step.simulation.time_step,animation,error))
    {error="Animation tick"+std::to_string(f.ticks)+": "+error;return false;}
    auto& force_mode=s.animation.motion.riding.force_mode;
    if(force_mode){shared.skeleton_input.force_mode=*force_mode;force_mode.reset();}
    auto actions=o.controls.SimulationActions(original_actions);const auto packet=animation.Packet();bool teleported=false;
    std::vector<AnimationAttribute> attributes;attributes.reserve(s.animation.attributes.Size());
    for(std::size_t i=0;i<s.animation.attributes.Size();++i)attributes.push_back(s.animation.attributes[i]);
    if(!AdvancePlayerInputHostPhase(o.input,{packet,s.animation.packet,attributes,actions,input_available},teleported,error))return false;
    const auto selected=o.ground_profiles.Select(shared.input.processed.state_variant_index_2528,shared.input.processed.surface_mode_2540,error);
    if(!selected)return false;
    o.ground_settings=*selected;
    if(!DefaultTrainer(o.animation.trainer))o.ground_settings=o.ground_settings.Tuned(o.animation.trainer);
    bool vehicle_ejected=false;
    if(teleported)
    {
        s.respawn.ResetMeasurements();s.biped.contact.ResetHistory();shared.state.ResetForTeleport();
        o.centre_of_mass_filter.Reset();o.feedback.conditioner.Reset();
        if(!phases.EnterAfterTeleport(error))return false;
        FinishBoardPossessionTeleport(f.possession_live,f.board,f.settings.board.collision,f.board_wiping_out,
            shared.ground_lifecycle.board_animated_290,shared.input.processed.timestep_2604);
        s.ragdoll.ragdoll.RestoreNormal(f.skeleton,f.skeleton_joints,f.skeleton_collision,f.collision_feedback);
        if(!phases.ApplyVehicleEjection(vehicle_ejected,error))return false;
    }
    if(!f.FinishBoardQueries(error))return false;
    if(!DeckTorqueFinite(f,"input and animation",error))return false;
    const OffboardGrabScene grab_scene(f.world,o.grab_registry);
    if(!shared.grab.ExecuteQueries(grab_scene,error))return false;
    const auto before=shared.state.Current();
    if(!CompletePlayerPostInput(shared,s.air,o.input.input.grind_materials,s.grinding,error))return false;
    if(!DeckTorqueFinite(f,"post-input",error))return false;
    if(!vehicle_ejected && !SelectPlayerPhysicalState(shared,shared.input.Snapshot(f.ticks),phases,error))return false;
    const auto after=shared.state.Current();
    if(before!=after && !shared.exchange.EmitEvent(tick,PhysicsStateChanged{before,after},error))return false;
    if(!DeckTorqueFinite(f,"state selection",error))return false;
    if(!AdvancePlayerPreState(shared,grab_scene,error))return false;
    if(!DeckTorqueFinite(f,"pre-state",error))return false;
    if(!phases.Update(shared.state.Current(),error)){if(!f.riding.reckoning.fault.empty())error+=" [reckoning "+f.riding.reckoning.fault+"]";return false;}
    if(!DeckTorqueFinite(f,"phase update",error))return false;
    shared.input.player.state_timer_1344+=shared.input.processed.timestep_2604;
    UpdateBoardPossession(f.possession,f.possession_live,f.board,f.settings.board.collision,f.board_wiping_out,
        shared.ground_lifecycle.board_animated_290,f.controller_fields,BindPlayerBoardPossessionObservation(shared),shared.input.processed.timestep_2604);
    f.processed_flags_2468=shared.input.processed.flags_2468;
    skeleton_queries.Publish(shared.input.player);
    if(!DeckTorqueFinite(f,"board possession",error))return false;
    if(!f.Solve(s.ground.ground.steering.targets,error))return false;
    AdvanceWallFollowAir(s,teleported);
    ResetPhysicalPlayerOutputs(shared.input.physical);
    if(!FinishPlayerPostPhysics(o.post,error))return false;
    const auto simulation=f.settings.board.step.simulation;
    shared.input.UpdateDynamicNormal(f.riding,simulation.gravity_acceleration);
    if(!shared.input.PublishBoard(f.riding,error))return false;
    shared.input.physical.skeleton.PublishDeckAngles(f.animation_record.pose[0][2],s.animation.packet.board_flipped);
    const auto up=f.riding.reckoning.up;
    const TrajectoryPublication trajectory(s.air.trajectory.selector);
    if(!shared.input.PublishGrindGraphOutputs(f.skeleton.record,{up.x,up.y,up.z,0},trajectory,error))return false;
    if(!PublishPlayerPhysicalState(o.publication,error))return false;
    s.grinding.ConditionCamera(shared.input.physical.grinds);
    o.centre_of_mass_output=o.centre_of_mass_filter.Update(Value(shared.input.physical.reckoning.vector_64),Value(shared.input.physical.reckoning.vector_16));
    PublishAnimationPhaseFeedback(o.feedback);
    if(!s.respawn.Observe(f,shared.input,s.animation,{shared.state.state_count,s.biped_ground.controller.state.contact.active},error))return false;
    if(!PublishExchange(o,tick,error))return false;
    camera::CameraOutputResult camera_output;
    if(!camera::AdvanceCameraOutput(BindGameplayCameraFrame(o),shared.exchange,o.camera,camera_output,error))return false;
    if(!AdvanceScoring(o,tick,teleported,error))return false;
    if(!o.climbing.Approach(o.climbing_frame,climbing_controls,error))return false;
    shared.animation_input.FinishOutputPublication();++shared.input.player.update_count_1316;
    o.clock.FinishTick();error.clear();return true;
}
}
