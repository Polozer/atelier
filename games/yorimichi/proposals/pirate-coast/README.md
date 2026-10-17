# Brinecove: a pirate coastal city proposal

An unbuilt district for Yorimichi. It is not referenced by `game.toml`, the world generator or any Unreal import.
The point of this folder is to answer one art-direction question: what would a whole pirate port, sized and shaped
like an entire district the scale of Belmonte, look like beside the existing island?

The proposal is **Brinecove**: a horseshoe cove cut into a jungle headland, with a stone quay, three timber piers,
a market square at the water, a town climbing two cliff terraces, a watchtower on the crest, a lighthouse on the west
headland and a waterfall in the east cliff. Booty Bay is the broad reference for the vertical, ramshackle port and
the ships tied along the quay. The painting language, palette and low-poly construction are Yorimichi's.

## What is here

- `design.md` records the plan, dimensions, district names and the art-direction rules used for every reference.
- `references/` paints a consistent set of Sunburst concepts, stores every prompt and paid-call record, and writes a
  contact sheet. The generated images live under `build/yorimichi/pirate-coast/references/`.
- `src/` builds the region as separate Blender collections, exports each collection as its own GLB, then assembles
  the same collections into one review scene.
- `viewer/` is a three.js page that loads the modules separately, lets each be switched on and off, and offers a
  set of camera viewpoints and a concept gallery.

## Build

```sh
uv run python games/yorimichi/proposals/pirate-coast/references/generate.py
uv run python games/yorimichi/proposals/pirate-coast/src/build.py --stage all
```

The Blender stage is meant to run headless under the normal guard, never as an unguarded foreground job:

```sh
python -m atelier.safety.guarded --report build/yorimichi/pirate-coast/guard \
  --purpose "Brinecove proposal build" --memory-gib 4 -- \
  nice -n 10 blender -b --factory-startup --python games/yorimichi/proposals/pirate-coast/src/build.py -- --stage all
```

`viewer/serve.py` serves the assembled page on the machine's Tailscale address. It is a plain static server: the
page has no external requests and all of its three.js code is vendored from the character-review tool.

## Scale

The playable basin is 1,600 m east-west by 1,200 m north-south, with the town occupying about 900 m of waterfront
and 500 m of depth. That is deliberately in the same family as Belmonte's 2 km valley and larger than Hidamari's
900 x 600 m street grid, because the cliffs, headlands and cove need room to read as a separate destination.

## Status

Proposal only. No game map, level, import or committed asset library entry is changed. The models are procedural
review geometry, intended to prove silhouette, layout and scale before a production pass.
