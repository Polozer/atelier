#pragma once
#include <algorithm>
#include <cmath>
namespace atelier::skate
{
// Host-only, like GameplayPumps: the speed boost a boost zone gives pumping and powersliding on its transitions (README
// "Boost zones"). The host sets the zone's scale before each step (0 outside every zone, which changes nothing) and the
// feel's bowl_boost multiplies it. Only on ground tilted more than 12 degrees from level, so a bowl's flat bottom and
// decks never boost:
// - a tick the rider pumps gains PumpGain m/s^2: standing up from a trigger's crouch, which the simulation reads as an
//   intentional pump (a trigger held is a crouch, not a pump), whatever the physical pump made of it;
// - a powerslide keeps up to SlideKeep m/s^2 of the speed the slide (and the climb) took, and gains SlideGain m/s^2.
// The pump's gain is its own, not a multiple of the physical pump's: at speed on a short transition a stand-up can hardly
// be timed, so that pump adds almost nothing, and a multiple of it nothing more.
// Nothing raises the speed past the cap: the speed the board came into the zone with, times 1 + CapRise x the scale, or
// CapFloor, whichever is more. All speeds m/s.
// Being in a zone and being able to gain in it are separate: the entry speed is taken when the board comes into the zone
// and held for as long as it stays in it, through its airs (no gain there) and the landings after them, so an air
// landed back in the same zone keeps the cap it had rather than raising it to the landing's speed.
struct BowlBoost
{
    static constexpr float TransitionCos=0.978f;   // cos 12 degrees: the ground's up must lean further than this
    static constexpr float PumpGain=6.0f,SlideGain=5.0f,SlideKeep=6.0f,CapRise=0.8f,CapFloor=24.0f;
    static constexpr float Crouch=30.0f/255.0f;    // a trigger pulled further than this crouches (XInput's threshold)
    float zone=0;          // this step's zone scale, set by the host (0..3)
    float entry=0;         // the speed the board came into the zone with
    bool inside=false;
    float total=0;         // speed added since the host last read it (logging)
    // The speed to add after a tick. in_zone: the board is in a boost zone (its scale over 0), whatever it is doing;
    // scale: the gain's scale this tick, the zone's times the feel's, or 0 where it cannot gain (in the air); up_cos: the
    // deck's up against world up; pumping: the rider pumps this tick (on the ground); before, after: the speed either
    // side of it.
    float Gain(bool in_zone,float scale,float up_cos,bool pumping,bool sliding,float before,float after,float dt)
    {
        if(!in_zone){inside=false;return 0;}
        if(!std::isfinite(before) || !std::isfinite(after))return 0;
        if(!inside){inside=true;entry=before;}
        if(!(scale>0) || !(up_cos<TransitionCos))return 0;
        float gain=0;
        if(pumping)gain+=PumpGain*dt*scale;
        if(sliding)gain+=(std::min(std::max(before-after,0.0f),SlideKeep*dt)+SlideGain*dt)*scale;
        const float cap=std::max(entry*(1+CapRise*scale),CapFloor);
        return std::clamp(cap-after,0.0f,gain);
    }
    // The session's tick (GameplaySession::ApplyBoost): zone_scale is the host's zone scale (0 outside every zone), feel
    // the feel's bowl_boost, grounded whether the board is on the ground or powersliding, the only states that gain. In
    // the air the board stays in its zone; it only gains nothing.
    float Tick(float zone_scale,float feel,bool grounded,float up_cos,bool pumping,bool sliding,float before,float after,float dt)
    {
        const float scale=grounded?zone_scale*feel:0;
        return Gain(zone_scale>0,scale>0?scale:0,up_cos,pumping,sliding,before,after,dt);
    }
};
}
