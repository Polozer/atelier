# World map

The landscape atlas opens on the player's current region. **World** goes up one level to the island overview;
choose a region there to inspect it. All seven regions have label-free, orthographic paintings, live place labels,
the player's position and heading, and the existing travel destinations. Every position comes from the generated layout (`world.json`, the
heightmaps, `hidamari/city.json`, the island and city height functions), never from screenshots or hand placement;
only the artwork is painted. The tools live in [`games/yorimichi/world/map/`](../world/map/).

The regions are **Momiji Coast**, **Momiji Woods**, **Hidamari**, **Temple Island**, **Northern Foothills**,
**Volcanic Highlands**, and **Haras Valley** (the countryside around Belmonte). Search works across every region.
The world destination list always contains the complete current registry, including saved places, Ronin camp,
air stations, both railway stations, the racecourses and skate parks. Travel still uses the original resolver,
including safe marker returns, the active Crater Park drop-in and the train platform service.

## Live labels and regional artwork

Stable labels are editable data identified by permanent keys. Select a stable in Haras Valley, change its name,
then **Save name**; **Reset** restores the default. No names, titles, pins or UI are painted into any atlas image.
The current implementation saves overrides locally in `stable-names.json` beside the preferences file, shared
across character switches. A future multiplayer naming policy can change ownership without repainting any map.
An unreadable save is preserved; a failed write publishes neither a partial file nor a changed in-memory name.
The phone uses the same frames, labels and travel registry as the native atlas.

The World overview is a single island plate rather than a rectangular ocean tile. Its painted RGB sheet is still
checked against the signed coast mask; a deterministic feathered alpha edge derived from that mask fades the outer
sea into the atlas background and makes the coastline the visible boundary. The alpha never clears real land. The
alpha and its source receipt are recorded together. The alpha tool rejects a source receipt with no current
geography unless an explicit terrain-reference-revalidation witness binds the painting, signed mask and reference
hashes; it never mints a new geography claim for an unverified painting.

~~~sh
uv run python games/yorimichi/world/map/paint_atlas.py world --references PLAN_ROOT --style STYLE_IMAGE --coast-mask games/yorimichi/world/map/atlas/coasts/world.png
uv run python games/yorimichi/world/map/mask_atlas_island.py --source BUILD/world.png --record BUILD/world.json --mask games/yorimichi/world/map/atlas/coasts/world.png --out games/yorimichi/world/map/atlas/world.png --out-record games/yorimichi/world/map/atlas/world.json
~~~

Names are laid out in screen space around their pins. The layout prefers above, then below, sides and diagonals,
avoids every other label, pin and the player marker, and draws a leader when a name moves to a side. Only the
lowest-priority names that cannot fit are hidden; the hovered or selected name is always shown on top. Region
captions are placed first and keep a leader to their region centre. No two visible labels overlap.

The native atlas supports controllers throughout. The left stick and d-pad choose places; triggers cycle
every pin, including overlapping locations. The right stick pans, shoulders zoom, right-stick click fits
the map, and left-stick click returns to the current region. The bottom face button selects, the right
face button goes back through region → world → closed, the top button saves a place, and the left button
returns to the selected saved place. Hints use Xbox, PlayStation or Nintendo button names when detected,
and physical positions for unknown pads. Holding View/Touchpad outside the map still opens the saved-places bar.

`atlas.py` defines the world and regional frames in Blender metres. The atlas uses a uniform **linear** scale
with north up, preserving circles and aspect ratio. Outside regional artwork coverage, it opens the world view.
Paintings live in `world/map/atlas/`, with matching JSON provenance: frame, geometry-source hashes, input hashes,
full prompt, Sunburst model, high quality and the exclusive paid-operation receipt. `world.map` rejects stale
frames, changed geography and paintings declared to contain baked labels. Signed coast masks also reject invented
land and ocean extending into real land, allowing three source pixels for shore ink/surf and a small total
allowance for boats/foam. This colour check complements source registration and visual inspection.

Prepare a precise painting input with `build_map.py --atlas-reference REGION_KEY --data BUILD_DATA --out OUTPUT`.
The plan uses current terrain, roads, rail, water, building footprints and actual tree variants; blue is reserved
for water so dry contour rings cannot be confused with lakes. `paint_atlas.py REGION_KEY --references PLAN_ROOT
--style STYLE_IMAGE` authors one painting through `atelier.ai.ledger`. Existing receipts prevent resubmission;
normal builds never make paid calls. Review top view, water, alignment and absence of text before accepting art.

After preparing all eight reference frames, run `coast_masks.py --references PLAN_ROOT --verify-paintings`.
It records current terrain/water masks and checks every painting. If any fails, it writes no painting revalidation
records: correct the failed image with `paint_atlas.py --coast-mask MASK --style PREVIOUS_IMAGE` after preserving
the previous image and receipt. On success, a `verified_geography` witness binds the current geography, reference,
mask and painting hashes while keeping the original generation prompt and input hashes intact. New terrain must
be checked again; copying an old witness cannot approve changed artwork or masks.

For a small painted shore overshoot, `register_coast.py` follows the existing local-map registration workflow:
it samples a verified open-water texture patch from the same painting, matches its sea colour and blends only
inside reference ocean connected to the frame edge. It changes at most 3% of the frame, keeps every real-land
and landmark pixel identical, and must pass both coast checks. Missing land requires a repaint. The registered
asset's provenance nests the untouched original Sunburst receipt and records the mask, texture patch, colour
shift and changed-pixel count. Registration and normal builds make no paid calls.

## Build

```sh
uv run atelier build yorimichi world.map data.stage
```

`world.map` runs [`build_map.py`](../world/map/build_map.py) after `world.layout`, `world.hidamari`,
`world.skatepark`, `world.zeppelin` and `world.belmonte`. It writes `build/yorimichi/map/`:

| File | Contents |
| --- | --- |
| `rough.png`, `rough.jpg` | The label-free sheet drawn from the data, the base for any painting |
| `map.png`, `map.jpg` | The sheet the game (`map.png`) and the phone page (`map.jpg`) show: the committed painted sheet when it matches, otherwise the rough sheet |
| `map.json` | `bounds`, `projection_x`/`projection_y`, `px_per_m`, `sea_level` and the `zones` |
| `atlas/*.png` | The world overview and seven regional paintings in their declared linear frames |
| `map_lines.json` | Every polyline drawn, to check that a painted sheet's roads sit on the data |

`data.stage` copies them into `unreal/Content/Data/map/`, where `UJapanMap` reads them.

## Legacy compatibility sheet

- Coordinates are Blender metres: x east, y north, z up, the frame of `gen_world.py` and `world.json`. Unreal uses
  the same values in centimetres with y negated (`AJapanWorld::ToUE`); zone yaws are negated on load.
- The retained compatibility sheet uses the compact projection in [`map_projection.py`](../world/map/map_projection.py): piecewise-linear
  knots on each axis (`X_KNOTS`, `Y_KNOTS`) over `BOUNDS = [-400, -650, 1685, 1120]`. Gameplay scale is untouched; the
  distant north takes only a fifth of the sheet. The southern strip reaches world y -730, keeping the temple island
  visible after its 50 m offshore move; projection controls north of world y -461.31835938 are unchanged.
  `map.json` carries the knots, and the game and `phone/map.js` place
  the player and the pins through the same ones.
- The committed painted sheet is 2085 × 1770 pixels; its dimensions follow the current projection bounds.

## What the sheet draws

Height-coloured terrain and sea from one height raster over the whole sheet (the 600 m square, the south-west island,
Hidamari and the northern foothills; everything else fades to paper), forest cover from the placed trees, land
contours, the water the game tests against (canal, park pond, plaza basin, the woodland lake), roads, streets, lanes
and trails, the mini-mega's two riding sections with their gap, rollout and ladder, the Mega Park's riding footprint,
buildings, landmarks and props, and the spawn. Sunset Pier's 170 x 132 m deck, riding features and trees are drawn
from `skatepark/park.json` by [`pier_plan.py`](../world/map/pier_plan.py).

## Zones

Each zone is a travel target with a key, name, position, yaw and hint. Zones are snapped to a walkable polyline
(road, lane, route or stair), so travel lands on paved ground; the game traces the ground again on arrival.
An indoor stop can set `above_m`, the trace height above its recorded position, in metres (finite, 0–60).
Absent or invalid values retain the 25 m outdoor default. The salon uses 1.5 m to start below its roof;
both local travel and the host's multiplayer landing use that height. Its target is clear hall paving,
facing the betting counters.

After the guarded game is ready, `Automation RunTests Yorimichi.Map.SalonLanding` checks the real map
and host-handler landings, standing capsule clearance, heading and health against a roof-landing control.

| Region | Zone keys |
| --- | --- |
| Main road and hamlet | `spawn`, `hamlet`, `mega` |
| South-west island | `fishing`, `cove`, `landing`, `temple` |
| Hidamari | `arrival`, `arcade`, `plaza`, `harbor`, `hillside`, `park`, `station`, `foothills` |
| Elsewhere | `forest_lake`, `megapark`, `skatepier`, `hippodrome`, `zeppelin_forest`, `zeppelin_city`, `zeppelin_megapark`, `zeppelin_belmonte` |
| Volcano | `craterpark` (Crater Park: its marked ramp drop-in, looking across the park; [CRATERPARK.md](CRATERPARK.md)) |
| Belmonte | `belmonte`, `belmonte_course`, `belmonte_training`, `belmonte_salon` (Salon des Paris, from `belmonte/runtime.json`) |

`UJapanMap` adds a `skatepier` stop from `skatepark/park.json`, and a `hippodrome` stop (by the grandstand, at the
grandstand) from `hippodrome/hippodrome.json`, when `map.json` has none ([HIPPODROME.md](HIPPODROME.md)).

## Saved skate-line markers

Press **F5** while grounded to save a new place and heading; **F9** returns to the selected marker. Each F5 press
adds a new `Marker N`, keeping your earlier locations. Open the map with **M** to enter a name and **Save here**,
press **Enter** to save the name, choose **Previous** / **Next**, **Rename selected**, or **Delete selected**.
Clicking a blue **M** pin selects and returns to that place. With the map open, the controller's top face button saves a new place and its left face
button returns; the hint names the connected pad's buttons. Controller users can choose any saved pin with the
stick or d-pad and travel with the bottom face button. The phone receives the same named marker zones.

**In the game with a controller.** Hold **View** (Touchpad, Minus) for 0.4 s to open the saved-places bar at the
bottom of the screen; a tap still opens the map. The bar shows the selected place, its position in the list and
its distance:
- the d-pad, left stick or shoulders choose a place;
- the top face button saves here as a new `Marker N` and closes;
- the bottom or left face button returns there and closes;
- d-pad Down twice deletes the selected place;
- the right face button, View or Menu closes.

The game pauses input while the bar is open, as it does for the map, so no jump or sword fires behind it. The keyboard
works in the bar too: arrows, F5, Enter or F9, Delete twice, Esc. Messages after a save or a refused return name the
connected pad's buttons.

Up to 64 places are saved, with unique names of 1–48 characters. Positions, headings and the selected marker are
written to `markers.json` beside the game's preferences file (normally `unreal/Saved/settings.txt` in development;
in the packaged game's user container beside `settings.txt`). They survive character switches and game restarts,
including a new package with the same bundle identity. Saving uses a temporary sibling and an atomic replacement;
a failed write or unreadable save preserves the previous file and reports the problem.

Returns stow vehicles and clear momentum through normal travel. A local ground trace keeps a place under a roof
under it. Missing, changed or obstructed ground refuses travel and preserves the marker. An airborne or ungrounded
save attempt also leaves previous places intact.

The durable review scenario is `uv run atelier qa yorimichi session_marker --port PORT --save-file FILE`. Start a
fresh guarded CairoAdventure game with `-markersave=FILE` pointing to a new review file; the scenario refuses to operate
on a game using the player's normal save. It checks keyboard input, the controller's View tap and hold, the
saved-places bar (choose, save, return, two-press delete, close), several named places, selection, rename/delete,
map/phone travel, text-input isolation and Enter-to-save, airborne refusal, roofs, blocked or removed floors and
character switches. Restart with the same review save and add `--reload` to verify persisted places, headings and selection. Evidence goes to
`build/yorimichi/session-marker/review/`; test files remain under `build/`.

## The painted sheet

The painted sheet is committed in [`world/map/painted/`](../world/map/painted/), because it cannot be reproduced
from data:

| File | Contents |
| --- | --- |
| `world_map.png` | The painted sheet |
| `world_map_bounds.json`, `world_map_registration.json` | The bounds and projection knots it was painted for |
| `world_map_calibration.json` | The pixel control points of the axis calibration |
| `world_map_provenance.json` | Model, prompt and inputs, with each earlier version's record nested under `parent` |
| `island_repaint.provenance.json` | The ledger of the south-west island repaint call |
| `sunset_pier_repaint.provenance.json` | The shared paid-call ledger for the enlarged pier and moved island |
| `volcano_repaint.provenance.json` | The ledger of the enlarged volcano's repaint ([`repaint_volcano.py`](../world/map/repaint_volcano.py)) |

`build_map.py` uses the painted sheet only while its bounds and knots match the current ones exactly; otherwise it
falls back to the generated sheet. Never stretch old artwork over a changed world: every pin would move off its
destination.

To make a painted sheet the map:

```sh
uv run python games/yorimichi/world/map/promote_map.py build/yorimichi/map/<sheet>.png
```

[`promote_map.py`](../world/map/promote_map.py) writes `map.png`, `map.jpg` and `painted.txt` in
`build/yorimichi/map/`, and the committed sheet, bounds, registration and provenance (from a `paint_provenance.json`
next to the sheet) in `painted/`.

### Local repaints

Fix a wrong landmark or a redesigned area by repainting only that area, never the whole sheet. The mini-mega
landmark and the south-west island were corrected this way. [`repaint_island.py`](../world/map/repaint_island.py)
now handles the enlarged pier and the moved island together:

```sh
uv run atelier build yorimichi world.layout
uv run python games/yorimichi/world/map/build_map.py                # current generated plan and travel zones
uv run python games/yorimichi/world/map/repaint_island.py prepare    # old sheet crop and exact pier/island plan
uv run python games/yorimichi/world/map/repaint_island.py paint      # one GPT Image 2.5 Sunburst call
uv run python games/yorimichi/world/map/repaint_island.py register   # fit, blend, check -> world_map_candidate.png
uv run python games/yorimichi/world/map/promote_map.py build/yorimichi/map/sunset_pier_repaint/world_map_candidate.png
```

- `prepare` keeps the committed sheet as the parent and writes a 3:2 crop with a plan in the same frame: the
  current pier footprint and features, island coastline, rock, cove, tree crowns, stair, torii and temple.
- `paint` sends both crops and the aerial island concept to `gpt-image-2.5-sunburst` (quality high). Its provenance
  file goes through `atelier.ai.ledger` before and after the call; while it exists the call is never sent again.
- `register` fits the island and pier independently to their data footprints, matches the sea colour,
  blends through a feathered mask around the affected land and water, and checks that every pixel outside the mask
  equals the parent. It writes `registration-check.json` and `registration-check.jpg` (data coastline and stair over
  the result).

Sheet bounds stay fixed. The southern projection control and the island's landing/temple zones follow the new
location. Work files go to `build/yorimichi/map/sunset_pier_repaint/`. Completed paid revisions and older evidence
belong in the archive; an existing ledger is never removed to retry an uncertain submission.

### Rules

- Never hand-place anything on the sheet. A missing feature is missing from `world.json`; fix it there.
- Check landmark identity and orientation as well as road alignment: a yellow dot at the mini-mega was once painted
  as a cottage, which is why `build_map.py` draws the ramp itself.
- Label only what a player can reach or see as a destination.

## In the game

- **Desktop:** M opens and closes the atlas in the current region. The World button returns to the overview;
  selecting a region opens its details. Place pins and the searchable sidebar share the complete travel registry.
- **Controller:** View / Touchpad / Minus opens and closes it. The left stick moves a reticle that catches the nearest
  pin, the d-pad hops to the nearest pin in that direction, the right stick pans, the shoulders zoom about the
  reticle, the bottom button selects or travels and the right button returns through region → world → closed.
  Triggers cycle every target, including coincident pins; right-stick click fits and left-stick click opens the current region.
  The top/left buttons set/return to the selected saved marker;
  holding View outside the map opens the saved-places bar instead (see Saved skate-line markers);
  other pad buttons are swallowed. Moving the mouse
  hands the sheet back to hover and click; the header and hint lines name the connected pad's buttons.
- **Phone:** `{action:"map"}` returns the bounds, knots, zones and the sheet URL (`/map/map.jpg`, served from
  `build/yorimichi/map` by the `[stream] routes` entry in `game.toml`); `{action:"teleport", zone}` travels. The
  status message carries `yaw`. [`phone/map.js`](../phone/map.js) draws the pins and the player;
  [`phone/map-smoke.mjs`](../phone/map-smoke.mjs) exercises it against a running stream
  (`atelier stream yorimichi start`), and [`phone/map-scroll-smoke.mjs`](../phone/map-scroll-smoke.mjs) tests the
  touch gestures offline.

Travel goes through `AWandererCharacter::TravelTo`: it cancels a zeppelin ride, stows the board, the sailboat, the
bike and the horse, clears momentum, traces the ground under the target and places the character facing the zone's
yaw. The phone's "back to spawn" button uses the same path.

`uv run atelier play yorimichi -- -mapqa -reviewdir=DIR` travels to every zone in turn, screenshots each
(`map_NN_key.png`) and the open map (`map_overlay.png`), and writes `map_qa.json` (target, landed position, drift,
on-ground).
