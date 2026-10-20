# Gondola: unfinished work and known differences

This is the list of what is not finished, kept current with each review pass. [`README.md`](README.md) describes what
is built.

## Mechanism

- **Grip: jaw versus running wheels.** The grip is a detachable (MDG) grip. The **jaw** is the pair of grooved
  blocks under the housing's top body, between the two side plates. It closes on the rope, and its groove sits on the
  rope radius within 2 mm in every checked placement. The two large tyred wheels at the ends of the housing are the
  **station running wheels**. On the line they turn freely beside the rope at rope height and touch nothing. In the
  station they roll on the steel running rail (the band round the bullwheel bay) once the jaw has opened. The wheels
  sit on the cabin's outer side, so the rail and the hanger brackets clear the rope and the jaw. The build checks the
  wheels against everything except the rail, and the rest of the cabin against everything including the rail.
- **Rope size.** The rope is 90 mm across (radius 0.045 m). Real MDG haul ropes are 40 to 60 mm; it is stylised so it
  reads at riding distance. The sheave grooves, jaw groove and clearances are all built from `rope_radius`.
- **Hanging.** The cabin hangs plumb from the grip's pivot pin, which only allows pitch. Real cabins also swing a
  little across the line in wind and on deceleration; that swing is not modelled.
- The grip is modelled closed on the rope everywhere. Nothing models the jaws opening in the station, the detach and
  attach cams, or the tyre conveyor that drives the friction plate. The station rope drops 0.15 m inside the mouth, and
  the build checks the 1.8 m attach zone without the rope.
- Tower sheave trains are fixed groups of four sheaves per rope on a straight carrier. There are no rocker beams, no
  compression and depression variants, and no catch hooks or rope catchers.
- The rope geometry is a parametric review path: level over the sheave train, falling 3° each side. Real spans and
  sag come with the routes. Placement must then call `rope.py` with the route's rope path, so that the grip frame and
  the groove check use the same path.

## Look

- **Cabin door side.** The door is on the face parallel to the rope, as boarding at the berth needs. In the cabin
  concept the rope runs across the door face.
- **Interior painting.** The painting's view down the cabin is matched by looking along the rope.
- **Textures.** The timber textures are procedural (`textures.py`, no paid generation): plank grain, seams, butt
  joints and roughness variation. They have no normal maps, so the seams are colour only. Painted-detail passes (wear,
  dirt, metal edge highlights) are not done.
- **Towers and stations.** These follow the concepts' style (timber framing, stone piers, tiles and shingles), but
  their structure is designed for riding and walking. Their cameras are framed by eye, not fitted, so overlays show
  layout differences that are deliberate.
- **Bullwheels.** All bullwheels are horizontal, as the loop through the berth needs. The crater-floor concept shows a
  vertical wheel in its mechanism house. The valley and rim concepts show a horizontal wheel under its own roof, which
  the model follows.

## Deliberately different for riding and walking

- **Pit railing.** A railing runs round the bullwheel bay, 0.26 m back from the pit edge. The concepts show open decks; the
  railing keeps players out of the cabins' path.
- **Berth gates.** Gates 1.6 m wide (±0.8 m about the berth) open the railing at each berth. They line up with the
  cabin door.
- **Rim boardwalk.** The boardwalk is 2.4 m wide at a 1:15 grade and curves on a 7 m radius, so a player can walk it
  without stairs. The concept's boardwalk is narrower and steeper.
- **Roof heights.** Shelter and canopy tie beams sit above the rail frame and the passing grips (rim shelter ties at
  5.1 m), higher than the concepts' proportions.
- **Crater stair.** The stair from the deck to the crater floor has six 0.20 m risers and 0.30 m treads, with a
  1.5 m landing. The concept has no stair.
- **Ground at the mouth.** The ground beyond each mouth must stay below the pit floor (see below).
- **No set dressing.** There is no foliage, trees, pools or terrain. Those belong to world placement.

## Gameplay and placement

- Nothing is placed in the world and nothing is imported into Unreal. Routes and tower spacing are not chosen.
- The walkability audit is a raster check on the collision proxies. A game drive of the routes (the
  walkable-routes-traversable contract) needs the Unreal import.
- The ground beyond each station mouth must stay below the pit floor (−0.28 m): the cabin bottoms run 0.18 m below
  the platform there.
- **Riding logic.** Cabin spacing, the doors opening and closing in the berth, and the slow-down through the station
  are not modelled.

## Code

- `solid.py` and the raster core of `walk.py` duplicate the ferry's builder, which is not on `main` yet. Merge them
  into one shared module when the ferry lands (one-implementation-per-mechanism).
