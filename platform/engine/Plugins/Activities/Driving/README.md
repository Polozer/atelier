# Atelier driving simulation

A self-contained C++17 driving simulation for a four-wheel car. It is engine-free: it has no
engine, renderer, asset or platform dependency. How a host exposes it is outside this module.

## What it does

One fixed 60 Hz step drives a four-wheel car:

- rigid body with box inertia, drag, sleep and ordered ground contacts;
- spring and damper corners with progressive springs, digressive dampers, blow-off and anti-roll;
- load-sensitive lateral tire curve, friction ellipse, brake lock, wheel spin and damage;
- engine torque curve, clutch, automatic and manual gearbox, differentials and torque converter;
- speed-sensitive steering, range and rate shaping, counter-steer, Ackermann and wall-steering escape;
- drag and downforce with a caller-supplied maneuver assist;
- forced induction, nitrous, drift state, burnout and launch traction control;
- jump stabilizers, landing assist, terrain alignment and low-speed sleep damping;
- rigid-body pair contacts, ball joints, angular limits, OBB and sphere contacts for props and trailers.

The entry point is atelier::driving::Vehicle. A ground is the only world interface the car needs: a
ray hit per wheel plus optional prepared planes and surface grip. Vehicle keeps its own body; a host
receives position(), orientation() and wheel(i) and can drive its own presentation from them.

## Layout

| Path | Contents |
|---|---|
| Source/AtelierDriving/Private/Simulation/SimulationMath.h | Vec3, Quat, Mat3, tables and units |
| SimulationSpec.h | plain car, chassis, tire, engine, transmission and tuning data |
| SimulationRigidBody.* | rigid body, ground response, pair contacts, OBB/sphere contacts, joints and limits |
| SimulationDrivetrain.* | engine coupling, clutch, gearbox, differentials and torque loop |
| SimulationTires.* | tire force, slip, load, damage and surface grip |
| SimulationSuspension.* | corner geometry, probes, compression, springs and dampers |
| SimulationSteering.* | steering tables, input history, speed-sensitive range and Ackermann |
| SimulationVehicle.* | the car step, wheel loop, aero, wall response and hardware replacement |
| SimulationPerformance.* | measured top speed and acceleration table |
| Tests/Simulation/self_test.cpp | standalone C++ checks for driving, shifting, contacts and performance |

## Units and conventions

- Physics space is metres, kilograms, seconds and radians: x right, y up, z forward.
- Wheel order is front left, front right, rear left, rear right.
- Gear ids are 0 reverse, 1 neutral, 2 first, and so on.
- Parameter structs keep the units of the production car data (inches, ft*lb, lb/in, mph, rpm); the
  simulation converts at construction.
- The step is FIXED_STEP = 1/60. The tuning assumes 60 Hz.

## Build and test

    clang++ -std=c++17 -O2 -ffp-contract=off -fno-fast-math -Wall -Wextra -Werror \
      -ISource/AtelierDriving/Private/Simulation \
      Source/AtelierDriving/Private/Simulation/*.cpp \
      Tests/Simulation/self_test.cpp -o /tmp/driving-self-test
    /tmp/driving-self-test

Keep the floating-point flags. The simulation relies on precise IEEE arithmetic and avoids FMA
contraction; do not add -ffast-math or architecture-specific reassociation. A host that compiles
these translation units should also keep them out of unity builds and use precise floating point.

## Out of scope

Car data import, car meshes, materials, animations, audio, streaming, traffic, pursuit, networking
and host integration are separate concerns. This module provides the simulation state and step only.
