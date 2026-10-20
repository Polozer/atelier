# Gondola ropeway

The aerial cable car between Hidamari, Belmonte, the Crater Park rim and the crater floor. It is modelled in the
style of the gondola concepts (`gondola_cabin.jpg`, `gondola_tower_pylon.jpg`, `gondola_valley_station.jpg`,
`gondola_rim_station.jpg`, `gondola_crater_floor_station.jpg`). The concepts set the look. The structure is designed
for riding and walking. All lines are monocable detachable gondola (MDG) lines, and every line runs both ways.

This stage builds only route-independent geometry: the cabin, a parametric tower and three station shells. It does
not place anything in the world, choose routes or import into Unreal.

## Build and review

```sh
B=/Applications/Blender.app/Contents/MacOS/Blender
ATELIER_AGENT=OWNER nice -n 10 uv run python -m atelier.safety.guarded --report build/yorimichi/gondola/logs/build \
  --timeout 1500 --small 3 --purpose 'gondola model build' -- \
  $B --background --factory-startup --threads 3 --python-exit-code 1 -P games/yorimichi/assets/vehicles/gondola/build.py
ATELIER_AGENT=OWNER nice -n 10 uv run python -m atelier.safety.guarded --report build/yorimichi/gondola/logs/render \
  --timeout 1500 --small 3 --purpose 'gondola review render' -- \
  $B --background --factory-startup --threads 3 --python-exit-code 1 -P games/yorimichi/assets/vehicles/gondola/render.py
uv run python games/yorimichi/assets/vehicles/gondola/compare.py CONCEPT_DIR   # folder with the gondola_*.jpg concepts
uv run python games/yorimichi/assets/vehicles/gondola/walk.py
```

- [`build.py`](build.py) writes into `build/yorimichi/gondola/`:
  - one FBX per mesh, plus one UCX collision FBX per piece, under `assets/`;
  - a `.blend` per piece;
  - `layout_<piece>.json`, the walk layouts;
  - `textures/`, the procedural timber maps;
  - `manifest.json`, written on a full run only.

  `$GONDOLA_PIECES` limits a run to some of `cabin,towers,valley,rim,crater`. Setting `$GONDOLA_SOFT_FAIL` turns the
  failure exit into a report, for review renders.
- [`render.py`](render.py) renders the matched views and close-ups into `review/`, including
  `<station>_bullwheel.png` (the bullwheel bay from the deck) and `<station>_eave.png` (a roof eave with its post and
  brackets) for each station. `$GONDOLA_VIEWS` limits a run to some of `cabin,towers,valley,rim,crater`.
- [`compare.py`](compare.py) writes:
  - `compare_<concept>.png`, with the concept on the left and the model on the right in matched framing;
  - `overlay_<concept>.png`, a 50% blend;
  - `edges_<concept>.png`, the concept's strong edges over the render;
  - `closeup_*.png`.
- [`walk.py`](walk.py) runs without Blender. It writes `review/walk_report.json` and the top-down layouts
  `review/walk_{cabin,valley,rim,crater}.png`.
- [`fitcam.py`](fitcam.py) fits the cabin cameras to picked correspondences in the cabin concept (Levenberg-Marquardt)
  and writes [`cameras.json`](cameras.json). The tower and station cameras are framed by eye: their structure does
  not trace the paintings.
- [`params.py`](params.py) holds the parameters. [`rope.py`](rope.py) is the rope path. [`textures.py`](textures.py)
  makes the timber textures. [`solid.py`](solid.py) is the closed-mesh core and holds the audits.

## Parameters

Overrides come from a JSON file named by `$GONDOLA_PARAMS`, and the build records the values it used in
`manifest.json`.

| Parameter | Default | What it moves |
| --- | --- | --- |
| `gauge` | 6.0 m | distance between the two rope tracks; bullwheel rope diameter; tower crossarm |
| `rope_radius` | 0.025 m | 50 mm haul rope; jaw groove radius |
| `hanger_length` | 1.45 m | rope axis to the cabin roof deck; grip-to-floor 3.75 m; rope height at the platforms 3.77 m |
| `tower_heights` | 10, 13, 16, 20, 24 m | one tower model per height (saddle height above the foundation datum) |
| `berth_x`, `pit_depth`, `berth_floor_step` | 3.4 m, 0.28 m, 0.02 m | berth position, cabin channel depth, sill step |

`manifest.json` records the attachment points for every piece:

- **Cabin:** grip point, jaw groove, running wheels, door frame, sill and leaves.
- **Towers:** rope saddles and sheave trains, crossarm, foundation datum and allowed ground relief, guy anchors, ladder.
- **Stations:**
  - rope exits and the station rope height;
  - the bullwheel;
  - the running rail;
  - berths: cabin grip, door centre and platform edge;
  - the pit;
  - access edges.

## Mechanism (MDG)

The model uses one rope path for everything. `rope.py`'s `RopePath` is the single source of `rope_point(s)` and
`rope_tangent(s)`. The rope meshes and every cabin placement use its `grip_frame(s)` (x along the tangent, z up, door
side outward):

- review spans;
- tower passes (`over_tower`);
- the station loop (`station_loop`).

**Grip.** A clamp housing about 0.45 m long and 0.30 m tall straddles the rope: a top body over two bolted,
chamfered side plates, with the rope running between them. Inside, a fixed jaw (inner side) and a movable jaw (outer,
door side) close on the rope from above. Their grooves are arcs of the rope radius about the rope axis, ending at the
axis height. Below the rope the housing is open, so the tower sheaves and the bullwheel run under the rope. Also on
the grip:

- two running wheels (0.32 m, grooved tyres), one at each end of the housing on the outer side at rope height, with
  planes parallel to the rope and axles across it. They roll on the station rail once the jaws open, and touch
  nothing on the line;
- a pivot: a lug under the outer side plate and a pin across the rope (along y), 0.13 m below the rope axis and
  0.185 m outboard of it;
- the hanger, a chamfered rectangular post from a bolted base plate on the roof. It rises nearly vertically, has one
  dogleg 40% of the way up and ends in a round boss on the pivot pin, beside the rope, never across it.

**Hanging plumb.** Only the grip (`GD_CabinGrip`) takes the rope's frame. The hanger, the body and the doors hang
from the pivot pin: `rope.hang_frame` gives them the grip's heading turned level, with world up and no pitch or roll,
and keeps the pivot point shared. On every grade the cabin floor stays level and the hanger stays vertical, while the
grip pitches about the pin. `cabin.pose` builds this two-frame placement; the build, the stations and the renders all
use it.

The load path is rope → jaws → grip body → hanger → cabin.

**Groove check.** The build measures the distance from the rope axis to the jaw groove at every placement:

- a level rope;
- a 40% grade;
- a sagging span;
- 49 positions over each tower sheave train;
- the station mouths.

It fails if any point is off the rope radius by more than 2 mm. The current maximum is 0.2 mm.

**Stations.** The haul rope drops 0.15 m inside the mouth (`station_loop`), away from the opened grips, and runs
round the bullwheel at that height. The detached grips roll on a running rail whose top is at the wheels' bottom. The
rail is hung from an overhead frame on the inside of the loop: posts in the pit, a spine and crossarms over the grips,
and drop plates outside the wheel path. The cabin is checked round the whole loop:

- the running wheels against everything but the rail;
- the rest of the cabin against everything including the rail;
- the jaws against the rope everywhere except the 1.8 m attach zone inside the mouth.

**Rope clearance.** `solid.rope_clearance` samples the rope centreline every 2 cm within 3 m of the grip, in each
mesh's own frame. It measures the nearest-surface distance to the cabin, hanger and grip, and casts a ray along each
sample segment so that any crossing counts as 0. The jaws and the clamp body over them are left out, because they
close on the rope. The build fails below the rope radius plus 0.05 m. The poses checked are:

- spans: level, 40% and 75% grades (the steepest, as the crater-floor line), and a sagging span, in both directions;
- every tower pass;
- every station loop position, including the dropped rope round the bullwheel.

The manifest records the minimum distance and where it occurs (`rope_clearance`).

## Mesh rules

Every part is a closed solid with outward normals. The build fails on:

- an open or misoriented edge, or a degenerate face;
- coplanar same-facing overlaps between parts (z-fighting);
- a fitting that floats or sinks beyond its declared embedding: ray seats with five probes, 15 mm apart;
- a cabin touching a tower or a station;
- a triangle-budget overrun: cabin 15k, tower 8k, station 60k.

Timber surfaces carry procedural textures, `textures.py`:

- 1 m tiles;
- UVs in metres along each part's grain;
- planks 10 cm wide (walls) and 12.5 cm wide (decks), with dark seams, staggered butt joints and matte roughness that
  varies slightly.

## Walkability

`walk.py` uses the same proxies that the build exports as UCX hulls:

- a 0.22 m capsule;
- 0.30 m step limit;
- 2.0 m headroom;
- 0.9 m minimum clear width.

It reports route bottlenecks, pinch points, trapping pockets and slivers, and the stair riser and tread checks. Each
station is checked with a cabin in each berth with its doors open, so the boarding routes run from the access through
the gate into the cabin.

## Contracts

- **closed-visible-geometry** and **pieces-meet-by-construction:** see Mesh rules.
- **ground-is-the-rendered-surface:** the towers record their foundation datum and the allowed ground relief at each
  pedestal; the stations record their platform datum and access edges. Placement is a later, route-dependent stage.
  - Beyond each station mouth, the ground must stay below the pit floor (−0.28 m), because the cabin bottoms run 0.18 m
    below the platform.
- **walkable-routes-traversable:** the raster walk audit is done. A game drive of the routes is not, because nothing
  is in Unreal yet.
- **one-implementation-per-mechanism:**
  - `solid.py` and the raster core of `walk.py` are carried over from the ferry's build. The ferry is not on `main`
    yet; the two should share one module once it lands.
  - The rope path, the grip frame and the groove check have one implementation, `rope.py`.

## Asset library

Everything here is procedural Python plus Markdown and JSON. Under `games/yorimichi/assets`, only `.glb`, `.npz`,
`.blend`, `.png` and `.jpg` files need `source-library.json` entries, so nothing is registered. The textures and
models are build outputs under `build/`.
