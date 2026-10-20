# Passenger ferry

The old-school passenger ferry between Yorimichi's harbour towns, modelled after the approved concept C
(`ferry_oldschool_c.jpg`). It is about 80 m long, with a long white hull, a raked bow and an elegant sheer. A blue
boot-top and a gold rope moulding run along the hull. The forward deckhouse is a low varnished timber house with a
rounded (superellipse) front and a continuous band of tall windows. Above it, a shorter, narrower wheelhouse with a
rounded front sits well back, with a narrow white deck walk and rail round it. Its railed roof carries a brass
searchlight and bell. The midship house is white, with varnished, white-framed window bays set in raised white portals
between white pilasters. One fat, faceted cream funnel tapers to a black top band and a smaller black inner stack.
Short, fat brass bell-mouth cowl ventilators stand round it on white drums; their mouths are dark warm brass inside.
Full clinker-built varnished lifeboats, with keels and beige ridged covers lashed down, hang outboard in gold crook
davits from blocks and falls, with daylight under them and clear of the house wall. There is a foremast with a
crosstree and a brass lantern on a forward platform, and an aft mast, both with a few fine tarred stays. A canvas
canopy covers the stern deck. A stockless anchor sits in a recessed, white-lipped hawse pocket on each bow.

This is a Blender-only stage: nothing imports the ferry into Unreal yet.

## Build and review

```sh
B=/Applications/Blender.app/Contents/MacOS/Blender
ATELIER_AGENT=OWNER nice -n 10 uv run python -m atelier.safety.guarded --report build/yorimichi/ferry/logs/build \
  --timeout 900 --small 3 --purpose 'ferry model build' -- \
  $B --background --factory-startup --threads 3 --python-exit-code 1 -P games/yorimichi/assets/vehicles/ferry/build.py
ATELIER_AGENT=OWNER nice -n 10 uv run python -m atelier.safety.guarded --report build/yorimichi/ferry/logs/render \
  --timeout 900 --small 3 --purpose 'ferry review render' -- \
  $B --background --factory-startup --threads 3 --python-exit-code 1 -P games/yorimichi/assets/vehicles/ferry/render.py
uv run python games/yorimichi/assets/vehicles/ferry/compare.py
```

- [`build.py`](build.py) writes `FY_Hull`, `FY_Superstructure`, `FY_Funnel`, `FY_Lifeboats`, `FY_Rails`, `FY_Masts` and
  `FY_Fittings` as FBX files under `build/yorimichi/ferry/assets/`. It also writes `ferry.blend` and `manifest.json`
  (triangle counts, bounds, decks and boarding openings).
- [`render.py`](render.py) renders three views into `build/yorimichi/ferry/review/`: the concept's camera, which was
  fitted to the concept's hull lines, an orthographic side elevation and a top view.
- [`compare.py`](compare.py) writes `compare_*.png` with the concept on the left and the render on the right. It also
  writes a 50% overlay of the matched view and close-ups, `closeup_*.png`, which crop the concept and the render to
  the same framing: both rigging areas, the funnel and ventilators, the lifeboats and the bow anchor. A side-view
  stair close-up compares the previous side elevation with the current one.
- `build.py` also writes `assets/FY_Collision.fbx` and `deck_layout.json`, and runs a deck audit (see below).
- [`walk.py`](walk.py) runs without Blender (`uv run python games/yorimichi/assets/vehicles/ferry/walk.py`). It reads
  `deck_layout.json` and writes `review/walk_report.json` and a top-down layout per deck, `review/walk_*.png`.

## Model

- Units are metres. +X is the bow, z is up and the waterline is at z = 0.
- The ship is 80.1 m long, 12.0 m across the swung-out lifeboats and has a 2.6 m draft; the masthead is 24 m above
  the water. There are about 84k triangles in all: the hull 22.9k, superstructure 19.0k, rails 16.2k, lifeboats 15.2k, fittings
  8.5k, masts and rigging 2.1k and funnel 0.3k. The collision file holds 914 convex hulls.
- Materials: `FY_WhitePaint`, `FY_BootTopBlue`, `FY_GoldMoulding`, `FY_VarnishedTimber`, `FY_DeckTimber`,
  `FY_CreamFunnel`, `FY_Black`, `FY_Brass`, `FY_Canvas`, `FY_Glass`, `FY_DarkIron`, `FY_Lifebuoy`, `FY_BoatTimber` and
  `FY_TarredRope`, `FY_CowlThroat`, `FY_AnchorBronze` and `FY_HawseRecess`.
- Every part is a closed solid. Roofs, decks, canopies and covers have thickness. The build fails on any open edge
  and flips any part whose normals face inward. The hawse pockets are cut into the closed hull with an exact
  boolean, so the shell stays closed.
- The hull lines and the positions of the superstructure come from a pinhole camera fitted to the concept's hull
  edge, rope moulding and boot-top. The upper decks follow the sheer, as they do in the painting.
- Rigging follows the painting: a forestay pair from the lamp platform to the foredeck, and three shrouds on each
  side of the foremast (one from the masthead crosstree, two from the lamp platform). The shrouds set up on the
  monkey island inside its rail. The aft mast has two shrouds on each side to the boat deck. The landing points
  were solved so that each stay matches its painted line in the concept camera. Stays are 2 cm tarred rope (1.6 cm
  on the aft mast), with brass turnbuckles and eye plates at the deck ends and brass bands at the mast fittings.
- In game, the stays are about a pixel wide at normal viewing distances and will alias. Keep them in a separate
  LOD section: draw them with temporal AA, or as camera-facing ribbons whose opacity fades with distance (about
  1 px minimum width), and cull them from about 150 m.
- Walkable decks:
  - the main deck all round the hull, with rails;
  - the boat deck, reached by the companionway stair, with a narrow walk round the wheelhouse;
  - the open stern deck under the canopy (the canopy stops at x = -24.6 to give the stair headroom). Benches line its
    sides, and a white seat-locker with a timber top fills the narrow stern tip and carries the stern lantern;
  - the monkey island on the wheelhouse roof, reached by a ladder. The ladder is climb-only: it has a gate in the
    roof rail and side rails that stand above the roof.
- Companionway: a straight fore-and-aft flight on the starboard side of the centreline (y -1.7 to -0.7, 1.0 m wide).
  It climbs from the stern deck to the boat deck's aft edge. Its treads are solid and closed, with stringers and
  handrails on both sides. The top lands through a gated opening in the boat-deck rail. `manifest.json` records its
  risers, rise, tread, angle, foot and top.
- Deck audit: every deck fitting registers seat points. Fittings with a footprint register each corner of the
  footprint, and bench legs register both feet. The build ray-casts each seat onto the deck-bearing meshes and fails
  if there is a gap over 1 cm or a penetration beyond the fitting's declared embedding. It also fails if a lifeboat
  touches the ship. On the sloping sheer, flat-based fittings (windlass, capstan, bollards, vent box, lockers, lamp
  pedestals and monkey-island fittings) stand on deck-following plinths, so no edge floats. The build also fails if
  any fitting triangle meets a rail triangle. The result is in `manifest.json` under `deck_audit`.
- Collision: `FY_Collision.fbx` holds one `UCX_FY_Collision_###` convex hull per deck, house and obstacle proxy. It
  also holds a tiny placeholder render mesh, `FY_Collision`, which should be hidden or deleted after import. The
  same proxies drive the walk analysis.
- Walkability, for a player capsule of radius 0.22 m and half-height 0.755 m: `walk.py` rasterises the proxies
  that fall in the capsule's body band and measures clearance with an exact distance transform. It reports the
  narrowest point of every required route against a 0.9 m minimum (0.6 m for short, isolated pinches). It also
  reports any free pocket that the capsule cannot sweep, headroom per stair tread, and the stair and landing
  dimensions. In the layout images, walkable area is green, the capsule-dilated margins of obstacles are pink,
  pinches are annotated with their width, and the boarding openings are marked.
- Boarding: there is a 2.2 m opening in the main-deck rail amidships on both sides, centred at x = 15.2, in front of
  the deckhouse's white-framed side door. It has brass gate posts and a landing plate. The gangway lands on the deck
  edge there. `manifest.json` records its centre, width and outward direction.
