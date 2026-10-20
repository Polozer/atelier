# Driving

The car is a kei car from the Mega Park car park (`assets/vehicles/kei`, 3.39 m long, 1.47 m
wide), driven by Atelier's four-wheel simulation
(`platform/engine/Plugins/Activities/Driving`). The chassis is simulated in metres at a fixed
60 Hz; the host moves the character actor with it and reads the world with one ray per wheel.

## Controls

- `L`, or `live.car()` from the live bridge, summons the car beside the rider and mounts. Press it
  again, stopped, to step out and park it.
- `W` / `S` (the stick's forward axis) accelerate and brake; holding `S` from a stop selects
  reverse. `A` / `D` steer. `Space` is the handbrake. The gearbox shifts automatically.
- The camera settles behind the car, pulls back a little and widens with speed.

## Scale and placement

The mesh is the `SM_Kei_Retro` import at the game's centimetre scale, exactly as it stands in the
car park. Its origin is the ground under the middle of the car and +X is the nose, so the body is
offset below the simulated centre of gravity by the half height plus the ride height. The chassis
is a box of 3.39 x 1.47 x 1.40 m. The rider's capsule is off while driving; a box sweep of the
chassis stops the car at walls and fences, and every painted surface it crosses is read as tarmac
unless a finer surface mapping is added.

## Current limits

The car is single player: the vehicle prediction layer does not carry it yet, so `L` does nothing
in a shared game. The body is one mesh, so the wheels do not turn visually, and the rider's mesh
is hidden rather than seated. The simulation exposes each wheel's steer, spin, load and contact
for a later presentation pass.
