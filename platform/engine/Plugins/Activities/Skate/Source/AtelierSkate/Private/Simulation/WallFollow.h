#pragma once
#include "SimulationMath.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
namespace atelier::skate
{
// Wall-follow air (FeelTuning::wall_follow). The stock vert alignment (AdjustAirTrajectoryLaunchVelocity) aims the climb
// up a vert wall but keeps the whole along-wall speed, which in the air runs straight along the tangent while a curved
// wall turns away beneath it: off a bowl's outer wall the rider lands behind the lip, (v t)^2 / 2R outside it. With
// the assist on, a vert-aligned launch off a curved wall (with vert assist, without a transfer) turns its horizontal
// velocity round the wall's curvature centre at the wall's own curvature: a centripetal turn that keeps the speed and
// the climb, so the rider stays over the wall and comes back down onto it. Everything here is pure math and state;
// GameplayRuntime (Advance's frame) measures and applies it, AirTrajectoryRuntime decides a launch and bends its arcs.

// Rotates a horizontal direction about world up (+Y) by `angle` radians: (x, z) -> (c x + s z, c z - s x). A
// positive angle takes +X towards -Z, the sense of the signed turns below.
inline void YawAboutUp(float& x,float& z,float angle)
{
    const double c=std::cos(double(angle)),s=std::sin(double(angle));
    const double rx=c*x+s*z,rz=c*z-s*x;x=float(rx);z=float(rz);
}
inline Vec3 YawAboutUp(Vec3 v,float angle){YawAboutUp(v.x,v.z,angle);return v;}
inline Vec4 YawAboutUp(Vec4 v,float angle){YawAboutUp(v[0],v[2],angle);return v;}

// The turn of a path whose horizontal velocity (vx, vz) turns about +Y at `curvature` (1/m, signed as YawAboutUp;
// the rate is curvature times the horizontal speed) for the first `turning` seconds and then runs straight on: its
// horizontal displacement after `time` seconds and its horizontal velocity then. The path is a circle of radius
// 1/|curvature|, so the speed never changes.
struct WallFollowArc {double dx,dz;float vx,vz;};
inline WallFollowArc WallFollowArcAt(float vx,float vz,float curvature,float turning,float time)
{
    const double speed=std::sqrt(double(vx)*vx+double(vz)*vz),rate=double(curvature)*speed;
    const double t=time,turned=std::clamp(t,0.0,std::max(double(turning),0.0));
    if(rate==0 || !(turned>0))return {double(vx)*t,double(vz)*t,vx,vz};
    const double angle=rate*turned,s=std::sin(angle),half=std::sin(angle*0.5),h=2*half*half,c=1-h;
    // The arc: (sin a / rate) v + ((1 - cos a) / rate) (up x v), with up x (vx, vz) = (vz, -vx).
    const double ax=(s*vx+h*vz)/rate,az=(s*vz-h*vx)/rate;
    const double wx=c*vx+s*vz,wz=c*vz-s*vx,straight=t-turned;
    return {ax+wx*straight,az+wz*straight,float(wx),float(wz)};
}

// Whether a path along velocity v turning at `curvature` bends towards the side the wall's normal n faces (the
// centre is in front of the wall, as inside a bowl), not round behind it (the outside of a round pillar).
inline bool WallFollowConcave(float curvature,Vec4 v,Vec4 n)
{
    // The centre lies along sign(curvature) (up x v) = sign(curvature) (vz, -vx).
    const float side=(v[2]*n[0]-v[0]*n[2])*(curvature>0?1.0f:-1.0f);
    return curvature!=0 && side>0;
}

// Ground at least this steep (normal y below it, about 41 degrees) is measured as a wall: the upper transition and
// the vert. Lower down a bowl's wall has a smaller radius, so a window reaching there reads a little more curvature
// and the air turns a little tighter (lands a little further onto the transition), never wider.
inline constexpr float WallFollowSteepNormalY=0.75f;

// The plan curvature of the steep wall under the board, measured while riding it: the turn of the ground normal's
// horizontal part (about +Y) per metre ridden along the wall, over the last Window updates. A circular wall of radius R
// reads 1/R whichever way it is ridden (the sign says which way the line turns); a straight wall reads 0 however the
// board moves on it. Faceted collision turns the normal in steps, so the window spans several facets.
struct WallCurvatureTracker
{
    static constexpr int Window=24;           // 0.4 s at 60 updates a second
    static constexpr int Needed=12;           // at least 0.2 s of steep wall in a row
    static constexpr float MinimumRadius=8.0f,MaximumRadius=400.0f;
    static constexpr float MinimumDistance=4.0f; // metres ridden along the wall in the window
    std::array<float,Window> turn{},distance{};
    int count=0,next=0;
    float last_x=0,last_z=0,last_px=0,last_pz=0;
    bool has_last=false;
    void Reset(){count=0;next=0;has_last=false;}
    // One update on the ground: the ground normal under the board and the board's position. Ground no steeper than
    // max_normal_y (normal y at or above it), or with too little horizontal normal, restarts the measurement.
    void Observe(Vec3 normal,Vec3 position,float max_normal_y)
    {
        const float horizontal=std::sqrt(normal.x*normal.x+normal.z*normal.z);
        if(!(normal.y<max_normal_y) || !(horizontal>0.3f)
            || !std::isfinite(position.x) || !std::isfinite(position.z)){Reset();return;}
        const float nx=normal.x/horizontal,nz=normal.z/horizontal;
        if(has_last)
        {
            // Signed turn from the last normal to this one about +Y, and the distance ridden along the wall (its
            // tangent is up x n = (nz, -nx)), whichever way.
            const float sine=last_z*nx-last_x*nz,cosine=last_x*nx+last_z*nz;
            const float dx=position.x-last_px,dz=position.z-last_pz;
            turn[std::size_t(next)]=std::atan2(sine,cosine);
            distance[std::size_t(next)]=std::abs(dx*nz-dz*nx);
            next=(next+1)%Window;if(count<Window)++count;
        }
        last_x=nx;last_z=nz;last_px=position.x;last_pz=position.z;has_last=true;
    }
    // 1/m, signed as YawAboutUp; 0 while unknown, or outside radii MinimumRadius to MaximumRadius.
    float Curvature() const
    {
        if(count<Needed)return 0;
        double turned=0,ridden=0;
        for(int i=0;i<count;++i){turned+=turn[std::size_t(i)];ridden+=distance[std::size_t(i)];}
        if(!(ridden>=MinimumDistance))return 0;
        const double k=turned/ridden,a=std::abs(k);
        return a>=1.0/MaximumRadius && a<=1.0/MinimumRadius?float(k):0.0f;
    }
};

// The assist's state, owned by AirTrajectoryRuntime. A launch that qualifies latches strength x the measured
// curvature (pending); the first air update turns it on (active) and every update after the physics step turns the
// rider and the board until the board is down, the rider bails, grinds or plants, or after MaximumTime.
struct WallFollowAir
{
    static constexpr float MaximumTime=4.0f;
    static constexpr std::uint32_t PendingTicks=10; // a launch that has not left the ground by then is dropped
    float strength=0;                // FeelTuning::wall_follow: 0 off (stock), 1 the wall's full curvature
    WallCurvatureTracker tracker;
    std::uint32_t ticks_since_ground=0xffff;
    bool pending=false,active=false;
    std::uint32_t pending_ticks=0;
    float curvature=0,elapsed=0;     // latched: strength x the wall's curvature (1/m), seconds turned so far
    void Stop(){pending=false;active=false;pending_ticks=0;curvature=0;elapsed=0;}
    void Reset(){Stop();tracker.Reset();ticks_since_ground=0xffff;}
    float Remaining() const {return std::max(MaximumTime-elapsed,0.0f);}
};

// The curvature a launch latches (strength x the wall's), or 0 when it starts no wall-follow air. Only a launch the
// stock alignment aims up a vert wall (vert_aligned: AdjustAirTrajectoryLaunchVelocity's result, false for a
// zero-assist zone's ballistic launch), with vert assist above zero there (the session's assist, at most the assist
// zone's limit, and the limit itself), no lean forward (directional_input, the transfer, at most 0.25: the align's lean
// directional_input - 0.25 is not forward), within two updates of riding a concave wall whose curvature was measured.
inline float WallFollowLaunchCurvature(const WallFollowAir& w,bool vert_aligned,float vert_assist,float vert_assist_limit,
    float directional_input,Vec4 velocity,Vec4 ground_normal)
{
    if(!(w.strength>0.0f) || w.pending || w.active || !vert_aligned || !(vert_assist>0.0f) || !(vert_assist_limit>0.0f)
        || !(directional_input<=0.25f) || w.ticks_since_ground>2)return 0;
    const float k=w.tracker.Curvature();
    return WallFollowConcave(k,velocity,ground_normal)?k*w.strength:0.0f;
}
}
