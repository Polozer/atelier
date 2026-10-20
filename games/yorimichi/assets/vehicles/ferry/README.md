# Passenger ferry

The old-school passenger ferry between Yorimichi's harbour towns, modelled after the approved concept C
(`ferry_oldschool_c.jpg`). It is about 80 m long, with a long white hull, a raked bow and an elegant sheer. A blue
boot-top and a gold rope moulding run along the hull. Tiered decks with rounded fronts step back toward the stern.
The deckhouses are varnished timber with tall framed windows. One tall cream funnel has a black top. There are covered
wooden lifeboats on gold davits, a foremast and an aft mast with rigging, and a canvas canopy over the stern deck.

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
  writes a 50% overlay of the matched view.

## Model

- Units are metres. +X is the bow, z is up and the waterline is at z = 0.
- The ship is 80.1 m long, 11.6 m in beam and has a 2.6 m draft; the masthead is 24 m above the water. There are
  about 64k triangles in all: the hull 21.9k, rails 16.2k, superstructure 12.0k, fittings 7.3k, lifeboats 5.4k,
  masts 0.7k and funnel 0.4k.
- Materials: `FY_WhitePaint`, `FY_BootTopBlue`, `FY_GoldMoulding`, `FY_VarnishedTimber`, `FY_DeckTimber`,
  `FY_CreamFunnel`, `FY_Black`, `FY_Brass`, `FY_Canvas`, `FY_Glass`, `FY_DarkIron`, `FY_Lifebuoy` and `FY_BoatTimber`.
- Every part is a closed solid. Roofs, decks, canopies and covers have thickness. The build fails on any open edge
  and flips any part whose normals face inward.
- The hull lines and the positions of the superstructure come from a pinhole camera fitted to the concept's hull
  edge, rope moulding and boot-top. The upper decks follow the sheer, as they do in the painting.
- Walkable decks:
  - the main deck all round the hull, with rails;
  - the boat deck, reached by a stair at the aft face of the deckhouse, with bridge wings;
  - the open stern deck under the canopy;
  - the monkey island on the wheelhouse roof, reached by a ladder.
- Boarding: there is a 2.2 m opening in the main-deck rail amidships on both sides, centred at x = 15.2, in front of
  the deckhouse's white-framed side door. It has brass gate posts and a landing plate. The gangway lands on the deck
  edge there. `manifest.json` records its centre, width and outward direction.
