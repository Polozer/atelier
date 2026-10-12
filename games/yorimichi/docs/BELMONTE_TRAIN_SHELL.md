# Belmonte train — coach shells (blockout v1)

Status, 12 October 2026: measured plan, parametric shells, collision, reservations and placements built for both
coaches; control renders and dimensioned plans generated. Nothing is imported into Unreal, placed on a map or
attached to gameplay. Library and assembly guide: [assets/vehicles/belmonte-train](../assets/vehicles/belmonte-train/README.md).

## The shared envelope

| | Value | Status |
| --- | --- | --- |
| Length over buffers / body over end walls | 24.00 / 23.20 m | design target |
| Belt (blue below, ivory above) | 1.85 m above rail, under the restaurant's low sills | design target |
| Exterior / interior width | 3.10 / 2.95 m (walls 0.075 m) | validated by the blockout |
| Floor above rail | 1.25 m | assumption: platform heights and steps to agree with the map owner |
| Clear height | 2.30 m at the centre, 2.05 m at the walls (flat elliptical ceiling) | validated |
| Side walls / roof / ventilators | 3.45 / 4.18 / 4.30 m above rail | design target |
| Windows | first class: 1.40 m wide, sill 0.80 m, head 1.72 m above the floor; restaurant: panoramic bays 1.87 m wide, sill 0.65 m, head 1.97 m, 0.30 m piers | validated against furniture |
| Vestibules | 1.60 m clear at each end, exterior doors 0.75 × 1.95 m both sides, gangway door 0.80 × 2.00 m | design target |
| Bogies | centres ±8.50 m, wheelbase 2.50 m, wheels 0.92 m | design target |
| Gauge, buffers | 1.435 m, buffers at 1.065 m, 1.75 m apart | assumptions |

Both coaches share the end walls, roof, ceiling, deck, underframe, bogies (one mesh, linked), buffers, gangways,
steps, exterior doors and livery. Side walls are built per coach because the windows follow each plan, as on a real
coach. Window and door openings are real holes cut through the walls (exact boolean); the glass is a separate
object and material, so the empty interior is visible from outside.

## A working train: entering and coupling

- **Entering.** Each vestibule has exterior doors on both sides (0.75 × 1.95 m, hinged inward, pivot at the hinge,
  `swing_deg` in the placements), two hanging steps and brass grab handles. The collision leaves every doorway free.
- **Coupling.** Every vehicle shares one interface (`layout.coupling()`, in each placements JSON and in the
  manifest). It defines buffer heads 1.065 m above rail and 1.75 m apart, a draw hook on the centre line and a
  bellows gangway around a 0.80 × 2.00 m end door, with the floor at 1.25 m. The GLBs carry
  `SOCKET_Coupler_A/B` and `SOCKET_Gangway_A/B` at ±12.00 m. Two coupled coaches sit 24.00 m apart, origin to
  origin, with buffer heads and gangway faces touching, so passengers walk from one coach to the next at the same
  floor level. The `consist-*` renders check a coupled pair.
- **Missing vehicles.** The locomotive and tender, a baggage van and an optional observation car:
  [ChatGPT prompts](BELMONTE_TRAIN_MISSING_VEHICLES_PROMPTS.md), all on the same interface.

## Restaurant

From end A: vestibule (1.60) · lobby with WC (1.45) · salon with five dining bays (10 tables, 20 banquettes) and the
bar · service corridor beside the galley · vestibule. Central aisle 1.08 m between banquettes (contract minimum 0.95); furniture stands 0.035 m off the panelling, clear
of the bay frames.
Each bay is banquette 0.65 · knee gap 0.10 · table 0.65 · knee gap 0.10 · banquette 0.65; banquettes of
neighbouring bays stand back to back, so each table sits in front of a window and a pier sits behind each pair of
backs.

Panoramic glazing (revision r03, chosen by the user): one bay per dining bay, 1.87 m of glass centred on its
tables, sill 0.65 m and head 1.97 m above the floor (0.08 m under the ceiling's springing, room for the top rail),
with 0.30 m structural piers. The piers stand exactly where the banquette backs of neighbouring bays meet, so the
backs (1.15 m) rise in front of the piers, not the glass, as long as each back is at most 0.14 m thick. A sixth bay
(1.52 m) lights the bar's standing area; the concept's five bays are not imposed, since five dining bays plus the
bar make six. Sconces are on the piers at 1.45 m, above the backs; curtain rails span bay plus pier so the curtains
gather on the piers; racks move to the ceiling cove. Table tops (0.75 m) stand 0.10 m above the sill, as in the
references. Five dining bays instead of the brief's four raised the counts in the contract (banquettes 16→20,
tables 8→10, table lamps 12→14); no furniture dimension changed.

The bar counter faces the salon on the +Y side; behind it are the staff space, the back-bar and
the galley (3.78 m) on the +Y side, with the 0.90 m service corridor on −Y continuing the passage to vestibule B.
The galley is entered from the bar and from the corridor. This raised the restaurant counts in the contract
(banquettes 16→20, tables 8→10, table lamps 12→14). No furniture dimension changed.

## First class

From end A along the compartment side (+Y): WC 1.30 · luggage 2.40 · four cabins of 3.00 × 2.00 · attendant's
pantry 2.40 · WC 1.30, separated by 0.05 m partitions; the 0.90 m corridor runs the whole length on −Y. The plan is
symmetric about the coach's centre. The cabins are not stretched: the remaining 7.4 m go to two WCs, luggage and
the pantry. Each cabin: two sofas against the bulkheads (1.44 m between their fronts), the small table at the
window (0.385 m from each sofa front), a 0.70 m sliding glazed door centred on the corridor, its leaf running on
the corridor face (the corridor keeps 0.85 m beside an open leaf). The corridor side's windows mirror the
compartment side, so both elevations stay regular.

## Circulation and checks

`layout.check()` (run by the build and the tests) verifies the widths, the cabin and aisle sizes, that every
placement stays in its room, the windows clear the partitions and doors, and walks a 2D grid from vestibule A with
two discs: the provisional adult gauge (1.75 m tall, radius 0.28 m) and Cairo, Yorimichi's player (1.48 m, capsule
radius 0.22 m). Both reach gangway B, all four exterior doors and every room, with the doors open and furniture and
fixed fittings in place. The build also checks every architectural mesh: no open edges and positive volume
(outward normals). It counts non-manifold edges too, but they only occur where separate solids touch (the blue and
ivory bands, the door leaves' stiles): seams, not holes.

## Budgets (per coach)

| | Triangles | Notes |
| --- | --- | --- |
| LOD0 | ≈ 28,000 | everything, including lining panels and trims |
| LOD1 | ≈ 14,000 | no panels, trims, ribs, roof details or steps |
| LOD2 | ≈ 270 | closed hull, dark window quads |
| Collision | 42–52 boxes | convex boxes, doorways free |

Seven shared detail maps (512–1024 px) drawn by `textures.py`: walnut grain, two marquetry panels with an olive sprig
in gold inlay, burgundy and emerald carpets, vestibule tiles, the sun-and-olive crest. The fine ornament is in the
textures, not the geometry.

## Limits and next steps

- The interior lining is generated from the plan: raised walnut panels, dado rail and brass architraves. Its
  ornament is simpler than the references: no carved cornices, no ceiling lamps, and no marquetry on the ceiling.
- The galley, bar, WC fixtures, luggage shelving and pantry exist only as blue reservations; they need their own
  assets (Studio or script).
- The gauge, the floor height against platforms, curve limits and the gangway articulation must be agreed with the
  map owner before any rail placement. In 0.90 m corridors the chase camera will slide in close: check it in game.
- Unreal: the GLBs and collision import directly (Interchange), but no import script or material instances exist
  yet. Pick the tested route before integrating.
