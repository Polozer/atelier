#pragma once
#include <algorithm>
#include <cmath>
namespace atelier::skate
{
// Host-only, like GameplayPumps: the speed boost a boost zone gives pumping and powersliding on its transitions (README
// "Boost zones"). The host sets the zone's scale before each step (0 outside every zone, which changes nothing) and the
// feel's bowl_boost multiplies it. Only on ground tilted more than 12 degrees from level, so a bowl's flat bottom and
// decks never boost:
// - a tick's intentional pump gains PumpExtra times the speed the pump itself added, more;
// - a powerslide keeps up to SlideKeep m/s^2 of the speed the slide (and the climb) took, and gains SlideGain m/s^2.
// Nothing raises the speed past the cap: the speed the board came into the zone with, times 1 + CapRise x the scale, or
// CapFloor, whichever is more. All speeds m/s.
// Being in a zone and being able to gain in it are separate: the entry speed is taken when the board comes into the zone
// and held for as long as it stays in it, through its airs (no gain there) and the landings after them, so an air
// landed back in the same zone keeps the cap it had rather than raising it to the landing's speed.
struct BowlBoost
{
    static constexpr float TransitionCos=0.978f;   // cos 12 degrees: the ground's up must lean further than this
    static constexpr float PumpExtra=1.5f,SlideGain=2.5f,SlideKeep=6.0f,CapRise=0.35f,CapFloor=18.0f;
    float zone=0;          // this step's zone scale, set by the host (0..3)
    float entry=0;         // the speed the board came into the zone with
    bool inside=false;
    float total=0;         // speed added since the host last read it (logging)
    // The speed to add after a tick. in_zone: the board is in a boost zone (its scale over 0), whatever it is doing;
    // scale: the gain's scale this tick, the zone's times the feel's, or 0 where it cannot gain (in the air); up_cos: the
    // deck's up against world up; pump: the tick's intentional pump gain (0 when not pumping on the ground); before,
    // after: the speed either side of it.
    float Gain(bool in_zone,float scale,float up_cos,float pump,bool sliding,float before,float after,float dt)
    {
        if(!in_zone){inside=false;return 0;}
        if(!std::isfinite(before) || !std::isfinite(after))return 0;
        if(!inside){inside=true;entry=before;}
        if(!(scale>0) || !(up_cos<TransitionCos))return 0;
        float gain=0;
        if(pump>0)gain+=pump*PumpExtra*scale;
        if(sliding)gain+=(std::min(std::max(before-after,0.0f),SlideKeep*dt)+SlideGain*dt)*scale;
        const float cap=std::max(entry*(1+CapRise*scale),CapFloor);
        return std::clamp(cap-after,0.0f,gain);
    }
    // The session's tick (GameplaySession::ApplyBoost): zone_scale is the host's zone scale (0 outside every zone), feel
    // the feel's bowl_boost, grounded whether the board is on the ground or powersliding, the only states that gain. In
    // the air the board stays in its zone; it only gains nothing.
    float Tick(float zone_scale,float feel,bool grounded,float up_cos,float pump,bool sliding,float before,float after,float dt)
    {
        const float scale=grounded?zone_scale*feel:0;
        return Gain(zone_scale>0,scale>0?scale:0,up_cos,pump,sliding,before,after,dt);
    }
};
}
