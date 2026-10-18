# Where Brinecove would go in Yorimichi

Brinecove is still unwired. This note picks its site on the world map and lists what a real integration would touch.
World coordinates are Blender metres (x east, y north, z up), the frame of `docs/WORLD_MAP.md`; Unreal is
`(100x, -100y, 100z)` cm.

## Recommended site: the Western Reach, a brand-new zone

Brinecove gets a zone of its own on land nothing uses yet: no region polygon, map stop, zeppelin station, island,
park or other region layout lies west of x -650 along the south coast. It becomes the eighth region rather than an
addition to an existing one. Jungle City, the other unplaced region proposal (about 650 x 520 m of inland jungle), does
not need coast, so the two need not compete for this strip; agree its site before either is wired in.

The south coast west of Momiji, x ≈ -2400..-650 along y ≈ -60, belongs to no region today (`world/map/atlas.py`
`region_at()` returns `world` there). It is far-hill backdrop only, a 67 m grid ramping from the shore to 60-300 m
within a few hundred metres, with open sea to the south. That is Brinecove's own orientation: the cove opens south,
the town climbs north, and the headland cliffs rise out of the far hills.

| Brinecove (local) | World |
| --- | --- |
| Transform | `world = local + (-1500, -120)`, no rotation |
| Quay line, local y 60 | y ≈ -60, the existing coastline |
| Basin, local x -800..800, y -700..500 | x -2300..-700, y -820..380 |
| Back ridge, local y 500..760 | y 380..640, blended into the far hills |
| Lighthouse (-618, -38) | (-2118, -158) |
| Watchtower (-120, 470) | (-1620, 350) |
| Waterfall gorge (459..700, 30) | (-1041..-800, -90) |
| Market square centre (0, 160) | (-1500, 40) |

Why here rather than elsewhere:

- **Closest unclaimed coast to the start.** The east headland ends about 50 m short of Momiji Coast (x -650). The
  spawn road (-295, -95) and the coconut-stand sailboat launch (-216, -169) are 0.5-1.3 km away. Players sail west
  along the coast, round the waterfall headland and open the cove: the best reveal Brinecove has.
- **South-facing town.** The facades face the sun across the water, which is the look of every concept painting.
- **Nothing to move.** Temple Island (x -650..330, y -1000..-340) and the south-west island (-150, -530) stay east of
  the bay mouth; the cove's sea is open water today.
- **Visible landmark.** From Sunset Pier (-110, -234) the waterfall headland and, on clear days, the lighthouse sit on
  the western horizon, which gives players a destination before they find it on the map.

## Alternative: east of Hidamari

The coast at x 1500..3200, y ≈ -60 is also unclaimed, next to the Hidamari air station (1273, 308) and the railway
start, so a train or zeppelin stop would be cheap. It is further from the start, and a pirate port beside Hidamari's
Japanese harbour would weaken both silhouettes. Keep it as the fallback if the western coast is reserved.

## Integration steps

1. **Region.** Add `brinecove` ("Brinecove Reach", polygon (-2400, -900), (-650, -900), (-650, 430), (-850, 430),
   (-850, 700), (-2400, 700), which steps around Northern Foothills' corner) wherever region keys are
   listed: `world/map/atlas.py` `REGIONS`, `world/map/build_map.py`, `build.py`, `runtime_data.py`,
   `scenarios/regional_atlas.py`, the `paint_atlas.py` prompts, `JapanAtlas.cpp` (`region_for_zone`) and the atlas
   painting and coast mask for the new key. Any terrain change re-signs the coast masks.
2. **Terrain.** Export `layout.height` as a detailed patch that replaces the far hills inside the region and feathers
   into them at the border, the way Hidamari and the south-west island do.
3. **Modules.** Export each Brinecove collection as its own asset set. The flora library maps directly onto
   instanced foliage (HISM): the same prototypes, the same placements.
4. **Water.** The waterfall ribbons keep their streak texture with a panner; the river and ledge pool become water
   surfaces at the levels `layout.gorge_levels()` already defines.
5. **Travel.** A map teleport zone `brinecove_quay` at (-1500, -55); the sailboat already launches from any shore,
   so the three timber piers are docks for free.

## Existing game assets that fit

- **Belmonte** (`assets/belmonte/source.json`): barrels, crates, crate stacks, sacks, amphorae, handcarts, market
  stalls and stall goods, kiosks, lantern posts, wall lanterns, quay wall, rocks and gorge strata. These can replace
  the proposal's primitive props one for one.
- **Hidamari and the south-west island**: the harbour boats, the fishing nets, buoys and lobster pots
  (`world/regions/southwest/fishing.py`), crates and rope coils (`world/regions/hidamari/harbor.py`), and the
  coconut stand (`world/regions/southwest/stand.py`).
- **Sailboat** (`assets/vehicles/sailboat`) for moored small craft and player arrival.
- The game has no palm and no waterfall of this size (Belmonte's fall is 17 m), so Brinecove's palms, species library
  and two-tier waterfall would be new shared assets.
