# Belmonte railway track

The track for the Belmonte steam line (H2 to Belmonte, 7.17 km, route v3 at 4%), generated from the route study.

- Input: `build/yorimichi/belmonte-train/route/route.json` (`world/train/route.py`, explicit step
  `world.belmonte_train_route`).
- Layout code, no Blender: `world/train/track.py`.
- Meshes: `world/train/track_build.py` (Blender, explicit step `world.belmonte_track`).
- Output: `build/yorimichi/belmonte-track/`.

## Scope of the first version

Built:

- Standard-gauge track: two rails (1435 mm gauge), sleepers and a ballast bed with shoulders.
- The passing loop. Its second track sits 4 m to one side, with a turnout at each end built as a simple
  points-and-crossing mesh.
- The ends of the line. At each terminus the track runs to a buffer stop, and a stop board marks the stopping point.
  There are no station buildings. The 200 m station reserves stay in the data, but nothing is built on them.
- Tunnels: four portals in Belmonte stone, and a simple horseshoe lining for both tunnels, the spiral included.
- The viaduct: arched piers and a deck in Belmonte stone (`MI_B_ashlar`, with `MI_B_stone` for the copings).
- Earthwork marker posts every 50 m at the top of each cut and the toe of each fill. They are editor-only and data
  only.

Not built:

- No terrain carving. That needs Henry's agreement first.
- The rail floats on placeholder ground where the far hills have not been rebuilt (route.json flags those samples).
- No Nanite anywhere.

## How the track is made

Everything follows the route.json samples. The rail top is at `rail_z`, and the curves come from the alignment.

| Part | How | LODs |
| --- | --- | --- |
| Ballast bed | Unique strip meshes bent to the line, one per 100 m chunk. Ballast texture with sleepers painted into the far mip. | 3 |
| Rails | Part of the same chunk mesh (one material slot each), swept along the line. Profile: 8 verts at LOD0, 4 at LOD1, a flat strip at LOD2. | 3 |
| Sleepers | One 0.25 x 2.6 m mesh, instanced every 0.63 m in an HISM per chunk. The cull distance fades them out at 120 m. | 2 |
| Loop and turnouts | Loop track chunks as above. Two unique turnout meshes. | 2 |
| Buffer stops and stop boards | One mesh each, instanced. | 2 |
| Tunnel lining | Horseshoe profile of 14 verts, inward faces, chunked every 100 m. Each tunnel goes on its own data layer, loaded only within 60 m of a portal or inside. | 2 |
| Portals | One stone portal mesh with an arch ring and wing walls, instanced 4 times and scaled to the cutting depth. | 2 |
| Viaduct | One mesh per span (pier, arch and spandrel), with the deck carrying the track chunk. Chunked into 3 pieces of 100 m. | 3 |

Collision:

- The ballast top, as simple boxes per chunk.
- The viaduct deck and parapets, as boxes.
- The tunnel lining, through its LOD2 used as complex collision.

Rails and sleepers get no collision.

## Budgets

The target is 1080p at ≥ 60 fps on a MacBook Air M5. The track must stay a small share of the frame: its numbers
are for the worst view, either a player on the viaduct or at the loop looking down the line.

| Budget | Limit |
| --- | --- |
| Draw calls from the track in view | ≤ 40 |
| Triangles in view (after LOD) | ≤ 60k |
| Ballast + rails chunk, LOD0 / LOD1 / LOD2 | ≤ 1,200 / 400 / 120 tris |
| LOD screen sizes | 0.5 / 0.15 / 0.04 (LOD2 holds beyond about 600 m) |
| Sleeper | 12 tris; ≤ 400 drawn instances in view (11.4k in total) |
| Tunnel lining chunk, LOD0 / LOD1 | ≤ 600 / 200 tris; nothing drawn from outside a tunnel |
| Portal | ≤ 2,000 / 600 tris |
| Viaduct (290 m in total), LOD0 / LOD1 / LOD2 | ≤ 25k / 6k / 1.5k tris |
| Turnout | ≤ 3,000 tris each |
| Buffer stop | ≤ 800 tris |
| Materials | reuse the Belmonte MIs (`MI_B_ashlar`, `MI_B_stone`, `MI_B_gravel`, `MI_B_iron`) plus one 1k ballast-and-sleeper texture set |
| Shaders | opaque only: no translucency, no world-position offset, no tessellation |
| Total unique mesh data on disk | ≤ 15 MB |

The build writes `manifest.json` with the triangle count of every mesh and LOD. A test checks the counts against
these budgets.

## Outputs (`build/yorimichi/belmonte-track/`)

- `SM_TK_Chunk_<nn>_LOD0/1/2.glb`: one per 100 m of line, loop chunks included.
- Tunnel linings: `SM_TK_Tunnel_<tunnel>_<nn>_LOD*.glb`.
- Viaduct pieces: `SM_TK_Viaduct_<nn>_LOD*.glb`.
- One file each for the turnouts, portal, sleeper, buffer stop and stop board: `SM_TK_Turnout_*`, `SM_TK_Portal`,
  `SM_TK_Sleeper`, `SM_TK_BufferStop`, `SM_TK_StopBoard`.
- `track.json`, listing:
  - every mesh's world transform;
  - the HISM instance lists (sleepers per chunk, portals, buffer stops, boards, marker posts);
  - the tunnel data-layer extents and the portal trigger boxes.
- `manifest.json`: sizes, checksums, triangle counts per LOD and the budget checks.

The world frame is route.json's: map metres with z up, and the GLBs are in metres. The Unreal import (a later
`unreal.belmonte_track` step, modelled on `import_belmonte.py`) turns the instance lists into HISMs and the
tunnels into data layers.
