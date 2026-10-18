# Terrain consolidation

The baseline is the published r8 source, `4ff62dabbc1a20350a3a849e58f00196db8a3dff`.
Its Yorimichi files equal the validated PR395 head `2a718605`. The consolidation
preserves authored geometry, regional appearance, railway design, refinement
lattice and evaluation order. A different refinement policy or landscape system
would be a separate behavior change with its own measurements and review.

## First increment: fixtures and inventory

`tests/fixtures/terrain-r8.json` freezes bounded inputs through the unchanged r8
production functions. `tests/terrain_fixture_cases.py` supplies those inputs;
`tests/test_terrain_inventory.py` compares every ordered vertex and face,
interpolated attribute, planner report and selected interior query. The fixtures
cover:

| Fixture | Preserved behavior |
| --- | --- |
| Inserted parent saddle | Initial knots retain the original parent a–c breakline. |
| Asymmetric curved sampling | Nonlinear shaping is evaluated at mesh vertices, with the existing fan diagonals. |
| Rail lattice transition | Original parent rail density and neighboring coastal edge knots remain conforming. |
| Selected/retained edge | Retained neighbors reuse selected subdivision nodes before the common carve. |
| Portal opening | Carving preserves the tunnel hood and intentionally missing portal triangles. |

These fixtures need no generated world cache, Blender or Unreal. Their vertex
comparison allows `1e-12` metres for numerical representation; face order is
exact. They supplement the existing geometric invariants and do not replace full
production export, route, root, border or native checks. A passing fixture suite
alone cannot certify a newly extracted island surface.

`tools/terrain_inventory.py` inventories explicit world-metre triangles without
modifying them. Position and index digests use ordered little-endian float64 and
int64 arrays, including their shapes. Duplicate render vertices remain distinct.
The edge census uses vertex indices: its boundary/nonmanifold counts do **not**
prove geometric continuity between duplicated vertices or separate owners.
Degenerate, downward and vertical faces are reported separately. No automatic
welding, triangulation, ownership selection or tolerance repair happens here.

The retained final FarHills export is recorded in
`tests/fixtures/terrain-r8-production.json`. It is an observational witness with
source/artifact provenance, explicit coordinate conversion and ordered hashes.
It is not a replacement terrain asset or a private build dependency. The natural
pre-rail product has not yet been extracted. FBX timestamps and texture paths
are not geometry identity.

Run the cheap fixtures with:

```sh
uv run pytest games/yorimichi/tests/test_terrain_inventory.py -q
```

Do not update the frozen fixture outputs merely to make a refactor pass. Diagnose
the changed face, operation order, support hole or attribute first. Any intended
change requires an explicit behavior review and a separately named baseline.

## Current owners and consumers

| Owner/layer | Current authority and final geometry | Current queries/consumers |
| --- | --- | --- |
| Fine main ground | `gen_world.py` heightmap, then `build_terrain.py` grid | Spawn/road placement, world map, Terrain export/import |
| FarHills | `forest_backdrop.source_grid/mesh_grid/rail_refinement`, `shorelines.grid_mesh`, then conforming `earthworks.polygons` | Export rebuilds the full surface; crown placement reconstructs selected cells separately |
| Hidamari city | `hidamari/layout.py`, city terrain meshes | City grading, roads, forest placement, HD_Terrain export and desktop tiles |
| Foothills and apron | `hidamari/mountains.py` sheets and earthworks | North height/approach sampling and independent mountain exports |
| Belmonte authored ground | Committed source triangles in `belmonte/source.py` | Triangle-indexed map/placement queries, authored terrain exports |
| Belmonte collar/country | `belmonte/terrain.py` and `belmonte/build.py`; natural stitching, carve, final stitching | Route raster consumes natural GLBs; planting/map/runtime consume final products |
| Track banks/decks/interiors | `train/track.py` and committed alignment | Separate railway support/structure layer; not arbitrary terrain maxima |
| Water | `shorelines.sea_mesh`, harbor geometry/materials | Separate visual layer without terrain-ground authority |

An analytical height function, a reconstructed local mesh and a serialized final
mesh are different authorities today. Future queries must identify their owner
and stage explicitly rather than silently choosing the highest overlapping
surface. Existing buried replacements and intended support holes must remain
explicit.

## Following increments

The first extraction publishes `terrain.FarHills.natural`,
`terrain.FarHills.final` and `terrain.FarHills.provenance` from the existing
`world.terrain` caller. Its Blender/NumPy context, source grid, one railway carve,
appearance and exports retain their order. Natural polygons keep their original
corner order; explicit fan triangles are stored alongside them, after the
planner has consumed the original polygons. Product bytes contain explicit
owner/stage/city mode and canonical arrays, with fixed archive timestamps.
Missing, malformed or mismatched products fail when loaded. This initial
extraction does not yet move crown placement or claim narrower invalidation.

1. Extract FarHills natural/final NumPy products in the **current discrete order**,
   keeping original parents, rail lattice, selected/retained adjacency and every
   triangle/index order. Compare complete arrays and exported payloads against
   this baseline before changing export consumers.
2. Introduce the shared owner/face/barycentric/height/normal query interface and
   move owned crown grounding to the final product. Prove full producer RNG,
   outside-row, root embedding and generated/native parity.
3. Migrate remaining regional owners separately. Publish explicit shared edge
   chains and ownership before replacing any current stitching behavior.
4. Separate geometry, scenery, appearance, export and import dependencies with
   complete named products and reads. Demonstrate invalidation/cutoff benefits;
   remove duplicate imports only after comparing all material, collision,
   distance-field and save operations.

Production preflight will reject missing/stale products, invalid indices,
unexpected holes, broken shared edges, unsupported roots and railway clearance
regressions before native import. Region looks and the existing FBX/GLB adapters
remain in place during extraction. Geometry parity, export round trips and
imported native support remain separate checks. No speedup has been measured by
this first increment.
