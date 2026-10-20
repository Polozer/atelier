# Belmonte environmental library

The current town, estates and countryside courses from [HarasValley](https://github.com/Polozer/HarasValley),
pinned to `fec48785a36e666d092134f73cebb157f020d3cd` and extracted from `/Game/Maps/HarasValley`.
The project owner authorized this integration from their brother's project.

`source.json` records the current scene placements, model and texture checksums, native transforms,
resolved surface colours and planting data. Every consumed GLB is committed in `meshes/`.
The 127 `_Collision.glb` files contain the original hull geometry and are never rendered.

The library contains 288 render models and 18 current colour textures, stored as 2K JPEGs at quality 92 with full chroma.
Full reference exports remain outside git; the game finishes these maps at 1K. No Haras tree or vegetation model,
crowd, character, distant backdrop, level, plugin or gameplay script is consumed. Embedded foliage
faces are removed from the architectural models. Planting is rebuilt using the existing island flora.
Terrain consists of the 56 current static mesh tiles, rather than a copied landscape or stale authoring grid.
The railway's last cutting and the Belmonte station are carved into four of them by `tools/belmonte_station_terrain.py`;
their natural versions stay in `natural/` for the route study (docs/BELMONTE_STATION.md).
The same tool paints a dirt path up the Salon des paris' cypress avenue, from the road to its terrace.

The acquisition tools are `tools/belmonte_extract.py` (read-only isolated reference editor) and
`tools/belmonte_convert.py` (guarded Blender). Normal builds never use the reference project:
`world.belmonte` reads this library and `unreal.belmonte` imports it into `/Game/Belmonte`.

## Building collision

The committed hulls miss upper storeys, roofs, chimneys and the grandstand tiers, so a walker or a board could end
up inside a drawn building. `world.belmonte` generates each building's collision under `build/` instead
(`world/regions/belmonte/collision.py`): the committed hulls, the drawn surface they miss (simplified to 0.25 m
where that is lighter), and closed plugs in the doors and windows of unfurnished interiors. The osteria's taproom and
the salon's hall are furnished: they collide as drawn and stay open. The step audits every building on a 0.2 m grid
and fails if a walker could reach inside a wall or an interior, or if more than 0.2% of a drawn outer wall or roof
lacks collision; `build-report.json` records each building's triangles, plugs and measures under
`building_collision`. The board rides the same collision: the Skate plugin reads a mesh's separate complex collision
mesh, and keeps each face's side, so every collision file the step writes faces outward like the drawn meshes. The
library's hulls wind into their solids; the step turns them (`glb/<mesh>_Collision.glb` for the other meshes too).

To compare every building with the committed hulls (about ten minutes, no Unreal):

```sh
uv run python games/yorimichi/tools/belmonte_collision_audit.py [--json OUT] [NAME ...]
```
