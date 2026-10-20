# Driving

The car is an open go-kart (`assets/vehicles/kart`, 2.16 m long, 1.24 m wide) driven by Atelier's four-wheel
simulation (`platform/engine/Plugins/Activities/Driving`). The chassis is simulated in metres at a fixed 60 Hz;
the host moves the character actor with it and reads the world with one ray per wheel.

## Controls

- `L`, or `live.car()` from the live bridge, summons the kart beside the rider and mounts. Press it again,
  stopped, to step out and park it.
- `W` / `S` (the stick's forward axis) accelerate and brake; holding `S` from a stop selects reverse. `A` / `D`
  steer. `Space` is the handbrake.
- The camera settles behind the kart, pulls back a little and widens with speed.

## The driver

The character stays visible, seated on the kart's pan by the sailing stance node's pelvis target, with both
feet on the pedals and both hands wrapped around the wheel's rim. Hand targets follow the rim's steer angle, so
the grip stays on the wheel while it turns. This is the same two-bone leg and arm IK the sailboat seat uses,
with the right hand's articulated tiller grip extended to the left hand.

## Scale and placement

The kart is built at the game's centimetre scale: 2.16 m long, 1.24 m wide, 1.50 m wheelbase, 0.14 m wheels.
Its origin is the ground under the middle, +X the nose. The body is offset below the simulated centre of gravity
by the half height plus the ride height; its four wheels and the steering wheel are separate meshes that turn
with the simulation's wheel spin and steer angle. The rider's capsule is off while driving; a box sweep of the
chassis stops the kart at walls and fences, and every painted surface it crosses is read as tarmac unless a
finer surface mapping is added.

## Current limits

The kart is single player: the vehicle prediction layer does not carry it yet, so `L` does nothing in a shared
game. The seated pose comes from IK rather than an authored clip, so the driver's spine does not lean with the
steering; a passing visual review should decide whether a kart-specific pose or clip is worth authoring.
