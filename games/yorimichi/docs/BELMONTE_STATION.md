# Belmonte station

The terminus of the Belmonte steam line, designed by Paul (2026-10-17): a Tuscan station that mixes London King's Cross
and Paris Saint-Lazare. Paul's reference elevations are in `assets/belmonte/concepts/station/`. They inspire the
building but are not traced.

## Site

- The station stands on the flat ground north of the road that runs from Belmonte's south-east gate to the Dunes Basses
  estate (`route.py` `BELMONTE`: platform centre (900, 4625), trains arrive running north-west, bearing 140°).
- Its facade faces the town. The forecourt is about 230 m from the north gate, and the Salon des paris is
  200 m from the access road's junction.
- The line now ends in Belmonte's valley:
  - a viaduct over the river;
  - a cutting under the road from the south-east gate, 229 m before the buffer stop. The rail there is 8.6 m below
    the road.
  - It is 496 m longer than the riverside site, takes 17 s more uphill, and leaves the loop and its crossing offset
    unchanged.
- The road keeps its line and level. A stone overbridge (`SM_ST_Overbridge`) carries it over the cutting. Retaining
  walls stand 5 m either side of the track for 16 m each way, so the cutting never reaches the road's ground.
- An access road (7 m of cobbles, 86 m at 2 %) runs from the forecourt north to the road between the north gate and
  the Trois Prés estate. That road also leads to the Salon and the town.

## Train size

Paul wants the train 15 % larger (2026-10-18). Today it is 131 m long, 3.60 m wide and 4.30 m tall; scaled it is
150.7 m, 4.14 m and 4.95 m. `station_site.py` sizes the station for it (`TRAIN_SCALE`):

- the sheds are 175 m long, so the whole train stands under the roof when its head stops 10 m short of the buffer;
- the platform edges stand 2.12 m from each track, clear of the scaled body.

## Levels

The rail is at 207.6 m. The ground around the station is at 210 to 215 m, so the station sits in a shallow cutting.

| Level | Over the rail | What stands there |
| --- | --- | --- |
| Formation | -0.85 m | Ground under the sheds and the headhouse |
| Platforms and concourse | +1.0 m | The train service's boarding height |
| Street | +7.2 m (214.8 m) | Vestibule, forecourt and the access road's start |

A double staircase in the headhouse joins the street to the concourse: one flight per shed, 37 steps. The landing
between the flights overlooks the concourse.

## Building

All dimensions are in the station frame of `station_site.py`:

- `a` runs along the track towards the buffer stop and beyond it to the facade;
- `u` runs to the left of an arriving train;
- the origin is the end of the line.

| Part | Where | Notes |
| --- | --- | --- |
| Train sheds | a -175..0 | Two glazed vaults, 22 m span each, springing 15.6 m over the street, rise 13.4 m. Ten bays of 17.5 m. The south-west shed holds the line's track. The other holds a decorative siding with three old wooden coaches. Iron columns carry the spine between the sheds. |
| Platforms | | P1 against the south-west wall, an island between the tracks, P3 by the north-east wall. Edges are 2.12 m from each track. |
| Rear end | a -175 | Stone piers with an archivolt over each open shed end, an iron screen above the trains' opening, and pavilions at the outer corners. |
| Great arches | a 17 | Iron tracery windows over the stair hall, framed by archivolts with keystone cartouches. Outer pylons carry finials. |
| Headhouse | a 0..26 | Concourse (a 0.5..7), stair hall (7..18) and vestibule (18..26). The street front has nine open arches under three iron and glass canopies, arched first-floor windows, a cornice and a balustrade with urns. A pediment stands under the clock tower. |
| Clock tower | over the spine | Brick shaft with stone quoins, four 2.3 m dials, a belfry cornice and a tiled spire. Its top is 38 m over the street, plus the spire. |
| Wings | u 12..26 and -55..-41 | Two storeys of terracotta brick panels between stone pilasters, closed arched doors, pedimented windows and a hipped terracotta roof. The wings cannot be entered. |
| Forecourt | a 26..46 | Cobbles and lamp posts. |

Materials reuse Belmonte's instances: `MI_B_ashlar`, `MI_B_stone`, `MI_B_plaster` (brick), `MI_B_roof`,
`MI_B_glass_dark`, `MI_B_flag`, `MI_B_cobble`, `MI_B_gravel`, `MI_B_iron` and `MI_B_wood`. Five flat colours are added
as `MI_ST_*` instances of `M_Belmonte`: green ironwork, roof glass, clock dials, coach teak and coach roofs. All shaders
are opaque.

### Glazing

- Up close (LOD0), the roofs, clerestories and arch screens are open iron lattices. Sunlight falls through them onto
  the platforms.
- From farther away (LOD1 and LOD2), the lattice becomes glass panels.

## Pieces and budgets

The station is built with the track. Its pieces sit in `track.json`'s `station` block and are placed by
`ABelmonteTrack`, so every client builds them the same way in multiplayer.

| Mesh | Triangles LOD0 / LOD1 / LOD2 (budget) | Collision |
| --- | --- | --- |
| `SM_ST_Headhouse` | 60k / 16k / 5k | LOD2: open arches, floors, stairs as ramps |
| `SM_ST_Sheds` | 70k / 14k / 5k | LOD2: platforms, walls, columns |
| `SM_ST_Coaches` | 9k / 2.4k / 400 | LOD2 boxes |
| `SM_ST_Forecourt` | 3k / 800 / 400 | LOD2 |
| `SM_ST_Overbridge` | 6k / 1.5k / 500 | LOD2 |

The train service no longer adds its makeshift platform at Belmonte (`tools/belmonte_train_service.py` `BUILT`).

## Ground

- `train/earthworks.py` designs the station's ground together with the line's:
  - under the sheds and the headhouse, the formation, standing straight against their walls;
  - the forecourt and the access road at street level, with soil slopes beyond;
  - under the overbridge, the cutting between its walls.
- `train/corridor.py` keeps plants off all of it, beyond the line's ends too (`settle`).
- The valley's committed terrain tiles are edited once by `tools/belmonte_station_terrain.py`. It refines and carves
  the touched triangles and repaints their layers: Rock on cut faces, Dirt on the formation, forecourt and access
  road, Green on new slopes. It records the line's digest in `source.json`, so the tool does not carve the same tile
  twice.
- The same tool paints a 4 m dirt path (`SALON_PATH`) from the road up to the Salon des paris' terrace, down the
  middle of its cypress avenue, following the ground (Paul, 2026-10-18).
- Each carved tile's natural version stays in `assets/belmonte/natural/`. The route study plans on that natural
  ground, so it still yields the committed line. A later line is carved again from these copies.

## Builds

After a change to the station:

```sh
uv run atelier build yorimichi world.belmonte_track world.belmonte_track_data unreal.belmonte_track
uv run atelier build yorimichi world.belmonte_station_review     # control renders
```

After a change to the line or the site:

1. Run `world.belmonte_train_route` and copy its `line.json` to `assets/vehicles/belmonte-train/line.json`.
2. Run `tools/belmonte_station_terrain.py`. It carves from the natural copies and updates `source.json` and
   `assets/source-library.json`.
3. Rebuild `world.belmonte` and the steps after it.
