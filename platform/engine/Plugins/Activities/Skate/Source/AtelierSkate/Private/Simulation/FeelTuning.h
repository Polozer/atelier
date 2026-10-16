#pragma once
#include <cstdint>
namespace atelier::skate
{
// The player's skating feel, beside Tune's pop, spin and push. Every field is a multiplier on the authored value of the
// active difficulty (1 is stock) or a switch where -1 keeps the difficulty's own choice. GameplayRuntime::Feel applies it
// to copies of the authored settings, so any change can be undone exactly; at the defaults nothing differs from stock.
struct FeelTuning
{
    // Flick tricks: how far a flick may stray from a trick's shape, how long a flick may take, and how fast a flick must
    // be for full pop (lower is less flick speed needed).
    float flick_radius=1,flick_window=1,flick_pace=1;
    // Air: gravity (below 1 floats, above 1 drops; jump heights stay put, air time changes), boneless and hippy heights.
    float gravity=1,boneless=1,hippy=1;
    // Rails: how far a jump may be bent onto a rail or ledge, the pop off a grind and the grind's friction.
    float rail_magnetism=1,grind_pop=1,grind_friction=1;
    // Grinds: how much a grind takes before it bails (0.5..3). Its in-grind limits (GrindPostTolerance) and the time a
    // push-off has to clear the rail are this times the authored; the entry's (the impact snapping on, the speed
    // across the rail, the speed landing into it) are half as much more, (1 + this) / 2, so a sideways or hard slam
    // still bails. Above 1, a rail slide that stalls is pushed off the rail instead of wiping out.
    float grind_tolerance=1;
    // Camera: how fast the camera's anchor may chase the rider, times the authored 40 m/s (1..3). At stock a rider
    // faster than that pulls away from the camera and the gap jitters as the limit catches and lets go.
    float camera_follow=1;
    // Air off a curved wall (0..1; 0 stock, off). The stock vert alignment keeps a launch's whole speed along the wall,
    // which flies straight on along the tangent while a curved wall turns away beneath: off a bowl's outer wall the rider
    // lands behind the lip. Above 0, a vert-aligned launch (vert assist above 0, no transfer) off a concave curved wall
    // turns round the wall's centre at this times the wall's curvature, measured riding it (WallFollow.h): speed and
    // climb unchanged, so at 1 the rider stays over the wall and lands back on it.
    float wall_follow=0;
    // Rolling: braking, steering, carve strength, wheel grip, powerslide bite, rolling resistance, downhill pull and pumping.
    float braking=1,steering=1,carve=1,grip=1,powerslide=1,rolling_friction=1,hill_speed=1,pump=1;
    // Balance: speed wobble size and the speed at which it starts, manual balance drift.
    float wobble=1,wobble_onset=1,manual_drift=1;
    // Bails: the landing angles and speeds that are forgiven, and the impacts that are survived.
    float landing=1,impact=1;
    // -1 keeps the difficulty's choice; 0 off; 1 on. Auto push keeps rolling speed; assisted air completes body
    // spins and flips for you.
    std::int8_t auto_push=-1,assisted_air=-1;
    // 0 off (stock); 1 on. Tight flicks also read a hardflip or inward heelflip flicked close to straight down then
    // up, as in newer skate games, beside the authored wide arc.
    std::int8_t tight_flicks=0;
    // 0 off (stock): Flick-It reads the stick once per 60 Hz tick. 1: twice per tick (120 Hz), from the host's stick
    // readings (GameplaySession::Step). The flick window, pace and the pause after a trick keep their times.
    std::int8_t flick_120hz=0;
    // Powerslides: how far the board turns across the travel (1 stock; 0.25..1.5).
    float powerslide_turn=1;
    // 0 off (stock). 1 drift: the left stick straight down starts a powerslide as well as a rear diagonal (to the right
    // when dead straight), the slide holds from half tilt, and the slide's wheel friction follows how far down the stick
    // is pulled: drift_grip (0..1.5) of the slide's own at half tilt to drift_full_grip at full tilt. Less friction keeps
    // more speed and bends the line less. Let go, the slide holds on at the light grip while the board comes back round
    // under the rider (GameplayRuntime::Advance), so the travel does not swing round to the board.
    std::int8_t drift_powerslide=0;
    float drift_grip=0.3f,drift_full_grip=0.6f;
    // Boost zones (BowlBoost.h): how much speed pumping and powersliding on a boost zone's transitions add (0 off, 1 the
    // tuned boost, up to 2). The host-only boost reads it; outside a zone it changes nothing.
    float bowl_boost=1;
};
}
