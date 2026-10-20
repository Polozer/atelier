# Passenger ferry

The old-school passenger ferry between Yorimichi's harbour towns, modelled after the approved concept C
(`ferry_oldschool_c.jpg`). It is about 80 m long, with a long white hull, a raked bow and an elegant sheer. A blue
boot-top and a gold rope moulding run along the hull. The forward deckhouse is a low varnished timber house with a
rounded (superellipse) front and a continuous band of tall windows. Above it, a shorter, narrower wheelhouse with a
rounded front sits well back, with a narrow white deck walk and rail round it. Its railed roof carries a brass
searchlight and bell. The midship house is white, with varnished, white-framed window bays set in raised white portals
between white pilasters. One fat, faceted cream funnel tapers to a black top band and a smaller black inner stack.
Big brass cowl ventilators stand round it. Clinker-built varnished lifeboats with beige covers hang outboard in
gold crook davits, with daylight under them and clear of the house wall. There is a foremast and an aft mast with a
few fine tarred stays, and a canvas canopy over the stern deck.

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
  writes a 50% overlay of the matched view and two rigging close-ups, `closeup_*.png`, which crop the concept and
  the render to the same framing.

## Model

- Units are metres. +X is the bow, z is up and the waterline is at z = 0.
- The ship is 80.1 m long, 12.0 m across the swung-out lifeboats and has a 2.6 m draft; the masthead is 24 m above
  the water. There are about 75k triangles in all: the hull 21.9k, superstructure 17.6k, rails 15.8k, fittings 9.3k,
  lifeboats 8.6k, masts and rigging 1.9k and funnel 0.3k.
- Materials: `FY_WhitePaint`, `FY_BootTopBlue`, `FY_GoldMoulding`, `FY_VarnishedTimber`, `FY_DeckTimber`,
  `FY_CreamFunnel`, `FY_Black`, `FY_Brass`, `FY_Canvas`, `FY_Glass`, `FY_DarkIron`, `FY_Lifebuoy`, `FY_BoatTimber` and
  `FY_TarredRope`.
- Every part is a closed solid. Roofs, decks, canopies and covers have thickness. The build fails on any open edge
  and flips any part whose normals face inward.
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
  - the boat deck, reached by a stair at the aft face of the deckhouse, with a narrow walk round the wheelhouse;
  - the open stern deck under the canopy;
  - the monkey island on the wheelhouse roof, reached by a ladder.
- Boarding: there is a 2.2 m opening in the main-deck rail amidships on both sides, centred at x = 15.2, in front of
  the deckhouse's white-framed side door. It has brass gate posts and a landing plate. The gangway lands on the deck
  edge there. `manifest.json` records its centre, width and outward direction.
