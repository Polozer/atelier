# Belmonte railway: hand-off note for Henry's agent

Paul's side (the owner, working from the fork Polozer/atelier, branch `belmonte-train`) has built a rideable steam
train on the map. This note says what it is, which files belong to it, what touches your modules, and what is still
open, so you can integrate it into `main` and keep working with the train in mind.

## What exists

- **The train:** seven vehicles (loco, tender, baggage van, restaurant, first class, second class, brake van) with
  furnished interiors. The shell and data are built in `world/train/` (layout, fittings, build, collision, consist,
  parts, budgets, lod_furniture). Collision boxes, no-sprint and no-climb volumes, seats and per-door boarding records
  are exported in `placements.json` and `consist.json`. See [the shell](BELMONTE_TRAIN_SHELL.md) and
  [the to-do](BELMONTE_TRAIN_TODO.md).
- **The line:** `world/train/route.py` lays out 7.2 km from Hidamari (H2) to Belmonte at up to 4%. It has a 300 m
  spiral in tunnel, a second tunnel (T1), a 14-arch viaduct and a passing loop at 4580–4840 m. There are no stations,
  only a buffer stop at each end. The service is two trains with a 90 s dwell at each end, crossing in the loop.
  Running uses 1.2 m/s² braking, a 100 km/h top speed and curve limits with cant. The timetable is in `route.json`'s
  `summary.service`, and `line.json` holds the geometry only.
- **The track:** `world/train/track.py` and `track_build.py` produce the ballast and rail chunks, instanced sleepers,
  turnouts, buffer stops and grass banks. They also make dark tunnel linings with wall lamps every 30 m, stone portals
  and the viaduct. `track.json` is the instance and light list. See [the track](BELMONTE_TRACK.md).
- **Earthworks:** `world/train/earthworks.py` carves the line's formation, cuttings, banks and portal mouths into the
  terrains it crosses. `world/train/corridor.py` clears trees along the line outside tunnels. It brings shrubs and
  grass to a soft edge and sets plants on the carved ground.
- **In game:** `ABelmonteTrainService` runs both trains deterministically from the game clock, like the zeppelin, with
  no movement replication. `ABelmonteTrack` places the track, the tunnel lights and the exposure boxes. Players teleport
  through the map's "Gare de Belmonte" or "Gare de Hidamari", or with `-traingo=belmonte`. Interact (D-pad down) opens a
  door at a station (either side) and boards or alights ("Monter" / "Descendre"). Interact also sits on the nearest free seat. Aboard,
  the player cannot sprint or climb and gets a short train camera. Build steps: `world.belmonte_train_service`,
  `world.belmonte_track_data`, `unreal.belmonte_train`, `unreal.belmonte_track` (all explicit).

## What touches your modules

Each hook is one call and is reversible. Every earthworks hook switches off with `RAILWAY_EARTHWORKS=0` in the
environment, and does nothing when `line.json` has not been built.

| File | Change |
|---|---|
| `world/regions/hidamari/mountains.py` | `mesh()` returns `earthworks.sheet(...)`: foothill cells along the line refined, cuttings and banks carved, holes at the tunnel mouths, snow cleared on moved ground. `height()`, `north_height()` and `surface_grid` stay natural. |
| `world/build_terrain.py` | FarHills polygons go through `earthworks.polygons(...)`: the far-hills grid carved where the line runs in the open east of x 2400. |
| `world/regions/hidamari/build.py` | `surface()`: HD_Terrain carved for the line's first 300 m out of H2. `layout.height()` stays natural, so props don't move. |
| `world/gen_world.py`, `world/regions/hidamari/layout.py` | One `corridor.clear_instances(...)` call each: trees off the line, plants set on the carved ground. |
| `unreal/Source/Yorimichi/JapanWorld.cpp` | Spawns `ABelmonteTrack` and `ABelmonteTrainService` after Belmonte. |
| `JapanMap.cpp`, `JapanHUD.cpp` | The "Gare de …" map zones and the train's Interact hint. |
| `WandererCharacter`, `JapanMovementPrediction.cpp`, `AdventureMoveSet`, `JapanCameraArm` | `bNoSprint`, the `NoClimb` actor tag, an Interact hook, and the camera arm's `ProbeObjectsOnly`. |
| `build.py`, `content_policy.py` | The train and track steps and content roots. `world.terrain`, `world.layout`, `world.hidamari` and `world.belmonte` take `corridor.py`, `earthworks.py` and `line.json` as inputs. |

## Open

- **Doors:** every door opens for everyone (Paul, 2026-10-16): no locked gangways, no class separation.
  `world/train/access.py` keeps the old class rules behind `LOCKED_DOORS`. Exterior doors still open only while a train
  stands at a station.

- **Multiplayer:** the trains are computed locally on each machine from the shared clock. A rider is carried locally
  by the service, because the movement base isn't replicated. It is solid in single player; with clients it needs
  validating.
- **Stations:** none yet; the 200 m reserves at each end are kept empty. You design the Hidamari station, Paul the
  Belmonte one.
- **Known test failure:** `test_northern_landscape`'s snow test fails the same way with the earthworks off. It is not
  caused by the railway.
- **Later on Paul's side:** Tripo models for the bar, galley, WC, stove and canteen plate; the sofa's rough LOD1; a
  dedicated boarding animation; tuning the tunnel darkness under Lumen.
