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
  contact sheet. It also paints the eleven-surface tileable set (41 palette-tinted maps) and six isolated hero-prop
  references for the local TRELLIS
  workflow. The generated images live under `build/yorimichi/pirate-coast/references/` and `references/props/`.
- `textures/` holds the seamless, palette-tinted Sunburst surface maps used by the Blender model and the viewer.
- `assets/models/` holds the selected TRELLIS town GLBs with their processing provenance; the neural sources and
  rejected trials stay in the ignored build cache.
- `src/` builds the region as separate Blender collections, exports each collection as its own GLB, then assembles
  the same collections into one review scene. It also normalizes, reduces, validates and places the TRELLIS assets.
- `viewer/` is a three.js page that loads the modules separately, lets each be switched on and off, and offers a
  set of camera viewpoints and a concept gallery.

## Build

```sh
uv run python games/yorimichi/proposals/pirate-coast/references/generate.py
uv run python games/yorimichi/proposals/pirate-coast/references/textures.py
uv run python games/yorimichi/proposals/pirate-coast/references/textures.py finish   # retint after a palette change
uv run python games/yorimichi/proposals/pirate-coast/references/props.py
blender -b --factory-startup --threads 3 --python games/yorimichi/proposals/pirate-coast/src/process_assets.py -- --only pirate-queen-statue
blender -b --factory-startup --threads 3 --python games/yorimichi/proposals/pirate-coast/src/build.py -- --stage all
```

The Blender stage is meant to run headless under the normal guard, never as an unguarded foreground job:

```sh
uv run python -m atelier.safety.guarded --report build/yorimichi/pirate-coast/guard --purpose "Brinecove proposal build" --timeout 3600 -- /usr/local/bin/blender -b --factory-startup --threads 3 --python games/yorimichi/proposals/pirate-coast/src/build.py -- --stage all
```

Use the normal 10 GiB guard: the TRELLIS hero import and the assembled scene exceed the 4 GiB `--small 3` envelope.
The guard already launches the child at normal application priority with nice 10. Keep Blender as the direct
command and declare its thread count; wrapping it in another command makes full-capacity admission treat the job as
an unknown exclusive launcher.

`viewer/serve.py` serves the assembled page on the machine's Tailscale address. It is a plain static server: the
page has no external requests and all of its three.js code is vendored from the character-review tool.

## Scale

The playable basin is 1,600 m east-west by 1,200 m north-south, with the town occupying about 900 m of waterfront
and 500 m of depth. That is deliberately in the same family as Belmonte's 2 km valley and larger than Hidamari's
900 x 600 m street grid, because the cliffs, headlands and cove need room to read as a separate destination.

## Outputs

- build/yorimichi/pirate-coast/references/ holds the 13 Sunburst PNGs, their prompts and paid-call provenance,
  plus a contact sheet.
- build/yorimichi/pirate-coast/models/ holds the nine procedural module GLBs and `10_hero_assets.glb`, which carries
  the six processed TRELLIS hero assets. The assembled scene is about 5.1 million triangles; the hero module alone
  is about 3.3 million. scene/brinecove.blend is the assembled
  Blender scene and scene/brinecove.glb is the same scene as one GLB.
- build/yorimichi/pirate-coast/renders/ holds the Blender review views and the concept/render comparison sheets.
- build/yorimichi/pirate-coast/viewer/ is the hosted page: module toggles, ten camera views, day-to-night lighting,
  a lighthouse beam, animated water and mist, district labels, the painted plan, the reference gallery, the
  TRELLIS prop references and the Sunburst surface sheet.

## Viewer

Run:

    uv run python games/yorimichi/proposals/pirate-coast/viewer/serve.py --port 8842

The server prints the machine's Tailscale URL. The page makes no external requests: three.js and its loaders are
copied from the existing character-review tool, and every reference and model is served from the same folder. On a
phone, open that URL on the tailnet; the controls are drag, pinch and right-drag or two-finger pan. H hides the UI
for a clean view.

## What the review checks

The comparison sheets put each concept beside the Blender camera that matches it: aerial, harbor approach, market,
upper terrace, lighthouse, shipyard, waterfall and night harbor. The main masses to compare are the horseshoe bay,
the three piers and two galleons, the stepped roofscape, the watchtower, the statue islet, the lighthouse and the
east-cliff waterfall. The pass now includes painted surfaces, 247 dense narrow lots, two-storey market halls,
a terrace-lip row that hides the retaining-wall top, street crowds, quay clutter, layered terraces and locally
generated hero props; the low-poly translation still stops short of the concepts' brushwork and individual
character detail.

## Status

Proposal only. No game map, level, import or committed asset library entry is changed. There is no collision, nav
mesh, gameplay, audio or Unreal import yet. The models are procedural review geometry, intended to prove silhouette,
layout and scale before a production pass.
