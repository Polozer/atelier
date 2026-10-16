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
// the vert.
inline constexpr float WallFollowSteepNormalY=0.75f;
// A launch latches the wall's curvature this much tighter (WallFollowLaunchCurvature).
inline constexpr float WallFollowMargin=1.03f;

// A velocity with any part away from the wall dropped: `inward` is the wall's horizontal normal (unit, towards the
// bowl). An air that turns with the wall leaves it as the vert alignment aims it, straight up; a little speed away from
// the wall would carry the turned air outward over the lip however tight the turn (its circle, tangent to the
// velocity, crosses the wall's own).
inline Vec3 WallFollowInward(Vec3 v,float inward_x,float inward_z)
{
    const float into=v.x*inward_x+v.z*inward_z;
    if(!(into<0.0f))return v;
    v.x-=inward_x*into;v.z-=inward_z*into;return v;
}

// The plan curvature of the steep wall under the board, measured while riding it. On a wall swept round a centre (a
// bowl's wall, at any height on its transition) every ground normal's horizontal line passes through the centre, so
// the centre is the point nearest all the normal lines of the last Window updates (least squares), and the curvature
// is 1 over the board's distance from it now: the radius of the air's circle. Faceted collision holds a facet's
// normal across it, which offsets each line by up to half a facet; the fit averages that out where counting the
// normal's turn per metre would read whole facets. A straight wall's lines are parallel and read 0. The sign is the
// way the line turns as ridden (as YawAboutUp); the side of the wall the centre is on is WallFollowConcave's.
struct WallCurvatureTracker
{
    static constexpr int Window=24;           // 0.4 s at 60 updates a second
    static constexpr int Needed=12;           // at least 0.2 s of steep wall in a row
    static constexpr float MinimumRadius=8.0f,MaximumRadius=400.0f;
    static constexpr float MinimumDistance=4.0f; // metres ridden along the wall in the window
    struct Sample {float x,z,nx,nz;};
    std::array<Sample,Window> samples{};
    int count=0,next=0;
    void Reset(){count=0;next=0;}
    // One update on the ground: the ground normal under the board and the board's position. Ground no steeper than
    // max_normal_y (normal y at or above it), or with too little horizontal normal, restarts the measurement.
    void Observe(Vec3 normal,Vec3 position,float max_normal_y)
    {
        const float horizontal=std::sqrt(normal.x*normal.x+normal.z*normal.z);
        if(!(normal.y<max_normal_y) || !(horizontal>0.3f)
            || !std::isfinite(position.x) || !std::isfinite(position.z)){Reset();return;}
        samples[std::size_t(next)]={position.x,position.z,normal.x/horizontal,normal.z/horizontal};
        next=(next+1)%Window;if(count<Window)++count;
    }
    // 1/m, signed as YawAboutUp; 0 while unknown, or outside radii MinimumRadius to MaximumRadius.
    float Curvature() const
    {
        if(count<Needed)return 0;
        const auto& first=samples[std::size_t((next-count+Window)%Window)];
        const auto& last=samples[std::size_t((next-1+Window)%Window)];
        // Ridden along the wall: the travel along the wall's tangent up x n = (nz, -nx).
        const double vx=double(last.x)-first.x,vz=double(last.z)-first.z;
        if(!(std::abs(vx*last.nz-vz*last.nx)>=MinimumDistance))return 0;
        // The point c nearest every line p + s n: minimise the sum of ((c - p) . t)^2 with t = (nz, -nx), relative to
        // the latest position for precision.
        double a=0,b=0,d=0,e=0,f=0;
        for(int i=0;i<count;++i)
        {
            const auto& q=samples[std::size_t(i)];
            const double tx=q.nz,tz=-q.nx,along=tx*(double(q.x)-last.x)+tz*(double(q.z)-last.z);
            a+=tx*tx;b+=tx*tz;d+=tz*tz;e+=tx*along;f+=tz*along;
        }
        const double n=count,det=a*d-b*b;
        if(!(det/(n*n)>1e-9))return 0;
        const double cx=(d*e-b*f)/det,cz=(a*f-b*e)/det,radius=std::sqrt(cx*cx+cz*cz);
        if(!(radius>=MinimumRadius && radius<=MaximumRadius))return 0;
        // Turning towards the centre: positive (as YawAboutUp) when the centre is along up x v = (vz, -vx).
        const double side=vz*cx-vx*cz;
        return side==0?0.0f:float((side>0?1.0:-1.0)/radius);
    }
};

// The assist's state, owned by AirTrajectoryRuntime. A launch that qualifies latches strength x the measured
// curvature (pending); the first air update turns it on (active) and every update after the physics step turns the
// rider and the board until the board is down, the rider bails, grinds or plants, or after MaximumTime.
struct WallFollowAir
{
    static constexpr float MaximumTime=6.0f;
    static constexpr std::uint32_t PendingTicks=10; // a launch that has not left the ground by then is dropped
    float strength=0;                // FeelTuning::wall_follow: 0 off (stock), 1 the wall's full curvature
    WallCurvatureTracker tracker;
    std::uint32_t ticks_since_ground=0xffff;
    bool pending=false,active=false;
    std::uint32_t pending_ticks=0;
    float curvature=0,elapsed=0;     // latched: strength x the wall's curvature (1/m), seconds turned so far
    float inward_x=0,inward_z=0;     // latched: the wall's horizontal normal at the launch (unit, towards the bowl)
    void Stop(){pending=false;active=false;pending_ticks=0;curvature=0;elapsed=0;inward_x=inward_z=0;}
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
    // The measured radius can read up to about 2% wide on fine facets: 3% tighter keeps the turned air over the wall
    // (a wider one lands behind the lip, a tighter one a little further down onto the wall).
    const float k=w.tracker.Curvature();
    return WallFollowConcave(k,velocity,ground_normal)?k*w.strength*WallFollowMargin:0.0f;
}
}
