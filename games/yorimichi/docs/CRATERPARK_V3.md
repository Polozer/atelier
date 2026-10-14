# Crater Park remake: design and acceptance

The park is rebuilt from scratch around four lines from one tower. Concept
paintings guide materials and finish; the game's physics determines the geometry.
This document tracks the owner's accepted requirements. A generated mesh or a
preview image is not evidence that a route rides correctly.

## Required final design

- Four long switchback lines, normally at least 500 m and 4–6 jumps per line.
  L4 is technical, with about six jumps and five turns.
- One common tower, working target 780 m world elevation. All four line spawns
  stand on its deck and face down their own roll-ins. F7 returns to the tower.
- L1 has a 60–70 m mega air. L2, L3 and L4 each have a 40 m or longer open mega
  gap and at least 50 m of clean flight. Gap lips launch forward, at most 30°.
- Every run and roll-in has curved bowl shoulders, 2.5–3.5 m high. Floors are
  at least 16 m wide and landings at least 18 m wide.
- Every elbow has a large vert quarter pipe. The green and blue major turns
  include large half bowls. High-speed convex crests and turns use R60 minimum,
  preferably R80, subject to the assembled riding checks.
- Orange L1 and purple L4 share one section with two large vert walls. At its
  end the player can use the vert to continue onto the remaining orange
  features, or transfer forward directly into the finishing bowl. Both options
  must be present in geometry and tested as complete routes.
- Orange and blue merge farther downstream. They use one shared final kicker,
  open gap and receiver into the bowl. Shared geometry is built once.
- The finishing bowl roughly follows Marseille Prado: a connected clover at
  one side and longer pockets divided by rideable spines at the other. Pockets,
  landings and run-outs are scaled for this park's large high-speed transfers.
  Each spine has opposed transitions meeting a narrow solid coping crest,
  with no gap between walls. The owner's overhead photo is the primary shape
  reference.
- The original Blue Pool shape and the Peanut remain part of the connected
  finishing complex. The blue line's low exit needs a broad rising spine or
  equivalent smooth recovery into the bowl, checked at the actual entry speed.
- Two selected gaps offer optional large rainbow grind rails. Ordinary jumps
  must still work. Grind and normal jump routes are checked separately.
- Gap terrain can include boulders, snow, scrub and crater landforms. Riding,
  grinding approaches, normal jump corridors and landing zones stay clear.
- Pale concrete, timber where suitable, continuous steel coping, thick capped
  walls, smooth shading, UVs and vertex AO. No dark concrete or ridable snow.

## Evidence required before release

1. All geometry checks pass: topology, buried and overlapping faces, wall
   thickness, protrusions, ownership, budgets, UVs, facets, slivers and outlines.
   No relaxed limits or cosmetic preview opt-in in the release.
2. Every assembled line and choice branch passes the native gameplay follower
   at 1, 4 and 8 m/s tower starts, without pushes in the 1 m/s case. Named
   receivers, landing slope and continuous recovery are checked per gap.
3. Slow-case touchdown is at least 3 m beyond each required knuckle. The fast
   case lands on its receiver. Normal impact is at most 7 m/s; inspect the
   pre-contact peak as well as the last airborne frame.
4. The full park imports and plays in Unreal with four usable tower starts.
   Complete an in-game tour, inspect riding transitions and publish new shots.
5. Refresh the orbitable whole-park model and lit renders at milestones. Planned
   and untested geometry remains labelled until its checks pass.
6. A clean committed revision is packaged, independently verified and smoke
   tested from the packaged application, then released as a GitHub playtest
   with checksums, manifest, verification and accurate release notes.

## Current evidence

- The four-line placement candidate is visible in the progress viewer. It still
  has structural failures and has not passed assembled native riding checks.
- The Prado bowl component has two 30 cm solid spine crests, with exact floor
  cutouts. Its closed-manifold, facet and triangle-quality checks pass; maximum
  riding facet is 1.913 degrees. Its UVs, full-park entries and native transfer
  riding have not yet been accepted.
- No v3 park release has been accepted or published yet.
