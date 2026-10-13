# Belmonte train — prompts for the missing vehicles

The restaurant and first-class coaches exist as measured Blender shells ([shell notes](BELMONTE_TRAIN_SHELL.md)).
A working train needs a few more vehicles. Order from the head: locomotive and tender · baggage van · restaurant ·
first class · shabby second class with its canteen · tail car. Generate their references in ChatGPT with the prompts below, one image
per request, and attach the listed existing references to each request. Save the results under
`build/yorimichi/train-concepts/<vehicle>/` (ignored by Git) with their prompts. Like the coaches, these images
are art direction: the Blender build sets the real dimensions.

Every vehicle shares the **coupling interface**, so any vehicle couples to any other. Repeat it in every prompt:
buffers 1.065 m above rail and 1.75 m apart with 0.40 m heads, a central draw hook and screw coupling, standard gauge.
Passenger vehicles also share the floor at 1.25 m and a rubber-bellows gangway around a 0.80 × 2.00 m end door.
The coupled pitch between passenger coaches is 24 m over buffers.

Attach to every request: `r03-panoramic/restaurant-exterior-profile.png` and
`r02/first-class-exterior-profile.png` (livery and proportions), plus the crest from either.

## 1. Locomotive and tender (required)

Request four images: locomotive profile, locomotive three-quarter, tender profile, and the cab interior looking
forward. The cab must be walkable: side cab openings with steps and handrails, a footplate floor, and a gap to the
tender with a fall plate.

```text
Design an original Belle Époque express steam locomotive with its tender, hauling an exceptionally luxurious
Orient Express-style train between Belmonte, a Tuscan hill town, and Hidamari. Match the attached coaches exactly:
deep midnight-blue lacquer with fine champagne-gold lining, polished brass, charcoal-black smokebox and running
gear, and the same small original crest (a sun above two olive branches) on the cab side and the tender. No real
railway logos, numbers or insignia.

A 4-6-2 "Pacific" type: long boiler, three large coupled driving wheels on each side, a four-wheel leading bogie,
a two-wheel trailing truck under the cab, a brass dome, a polished chimney band, smoke deflectors and visible
connecting and coupling rods. A spacious enclosed cab with large side windows, side entrances with steps and brass
grab handles, and a curved roof echoing the coaches. Separate six-wheel tender carrying coal and water, with the
same livery and the crest, and a rear end with buffers and a coupling matching the coaches.

Proportions for a train whose coaches are 24 m long over buffers, 3.10 m wide and 4.30 m tall above the rail:
locomotive about 14 m long over buffers and tender about 9 m, both no wider than 3.10 m; chimney top about 4.30 m
above the rail; driving wheels about 2.0 m in diameter; buffers 1.065 m above the rail and 1.75 m apart; cab floor
about 1.25 m above the rail, level with the coach floors. The tender's rear coupling matches the coaches; there is no
passenger gangway between tender and coach.

[VIEW] Plain matte white seamless background, no rails, sleepers, ground, scenery, people, text, labels or
dimension marks. Even studio lighting that keeps the blue, brass and black readable. Stylized but convincing game
asset quality, clean silhouettes, controlled detail, consistent with the attached coaches.
```

Replace `[VIEW]` in turn with:
- `Exact side profile of the locomotive alone, orthographic-looking, front to the right, whole vehicle visible.`
- `Front three-quarter view of the locomotive alone, slightly elevated, restrained perspective.`
- `Exact side profile of the tender alone, front to the right, whole vehicle visible.`
- `Interior of the empty cab looking forward towards the firebox door and boiler backhead: brass gauges, regulator
  and reverser, wooden floorboards, side entrances on both sides, the tender's coal opening behind the viewer. No
  crew.`

## 2. Baggage van with guard's compartment (required)

A luxury train carries a baggage van, usually right behind the tender, which also buffers the first passenger coach
from the locomotive. It is also the first walkable vehicle from the head of the train.

```text
Design an original luxury-train baggage van (fourgon) for the same Orient Express-style train as the attached
coaches. Same carriage envelope as the coaches: 24 m over buffers, 3.10 m wide, curved charcoal roof with brass
ventilators, the same bogies, underframe, buffers, couplers and rubber-bellows end gangways, and the same livery:
midnight-blue lower body, warm ivory band, champagne-gold lining, polished brass, the sun-and-olive crest. No real
railway logos.

Body side: two pairs of wide double sliding luggage doors per side, each with a small window; a guard's compartment
at one end with two windows and a raised lookout (a small bay with side windows projecting from the body side);
otherwise only a few small high windows. Floor 1.25 m above the rail, end doors with gangways at both ends, so
passengers and staff can walk through it.

[VIEW] Plain matte white seamless background, no rails, ground, scenery, people, text or dimension marks. Even
studio lighting. Clear transparent glazing that shows the empty interior: wooden plank floor, walnut-panelled
guard's compartment, luggage racks along the walls. Stylized but convincing game-asset quality, consistent with the
attached coaches.
```

Views: `Exact side profile, whole vehicle visible.` · `Three-quarter view from the guard's end, slightly elevated.`
· `Empty interior of the luggage hold looking towards the guard's compartment door.`

## 3. Shabby second-class coach with a canteen (required, at the back)

The comic counterpoint to the luxury coaches: the same carriage, decades of neglect. It sits at the back of the
train, just before the tail car. At one end, a canteen serves old porridge (the canteen lady is designed in her own
session). The shell stays on the same envelope and coupling interface, so it couples like the others.

```text
Design an original, comically run-down SECOND-CLASS coach for the same Orient Express-style train as the attached
luxury coaches. It is the poor relation at the back of the train: the very same carriage body, roof profile, bogies,
underframe, buffers, couplers and rubber-bellows gangways (24 m over buffers, 3.10 m wide, floor 1.25 m above rail),
but decades of neglect. The same livery, faded and abused: the midnight blue gone chalky and patched with
mismatched paint, the ivory band yellowed and streaked with soot, the gold lining mostly missing, brass dull and
green with verdigris, a few dents, rust bleeding from rivets, a crooked hand-painted "2" in place of the crest,
one window pane cracked and taped. Funny and charming, not horrific: stylized game look, no gore, no graffiti
text, no real logos.

Inside: an open saloon (no compartments) with plain smaller windows, rows of hard wooden slatted benches facing in
pairs along a central aisle, scuffed linoleum floor, peeling brown paint over tired plain panelling, a sagging
luggage net, bare bulbs. At one end, a cramped canteen: a battered serving counter with a sliding hatch, a huge
dented pot on a stove behind it, a menu board, stacked tin plates, steam and grime on the tiles.

[VIEW] Plain matte white seamless background, no rails, ground, scenery, people, text or dimension marks. Even
studio lighting. Clear (if grimy) transparent glazing that shows the EMPTY interior: the benches, counter, pot and
plates are separate assets made later, so show only the architecture, worn panelling, floor and the canteen's
built-in tiled walls and hatch opening. Stylized but convincing game-asset quality, consistent with the attached
coaches.
```

Views: `Exact side profile, whole vehicle visible.` · `Three-quarter view, slightly elevated.` · `Empty saloon
interior looking along the aisle towards the canteen end.` · `Empty canteen end seen from the aisle: counter opening,
hatch, tiled back wall, no props.` Then the same two interior views **furnished** (benches, counter, pot, plates,
menu board) for the separate Tripo assets.

## 4. Tail car (required, at the very end)

Something has to close the train. The observation salon below does it in style. A more modest option is a short
brake van with an end balcony, which suits the shabby second class better: tell me which you prefer, or generate
both.

## 4a. Observation salon car (tail of the train)


```text
Design an original observation salon car to close the same Orient Express-style train as the attached coaches.
Same envelope, bogies, underframe, roof profile, livery and crest as the coaches, 24 m over buffers. The front end
has the standard buffers, coupling and rubber-bellows gangway. The rear end is an open observation platform with
an ornate brass railing, a lantern and a door into the salon. Inside: a walnut-panelled lounge with large panoramic
windows like the attached restaurant, low sills, glass almost to the ceiling, slim structural piers, cream ceiling
with brass ribs, green-and-gold carpet. Floor 1.25 m above the rail.

[VIEW] Plain matte white seamless background, no rails, ground, scenery, people, text or dimension marks. Even
studio lighting; clear glazing that shows the EMPTY interior (no armchairs, tables or lamps: furniture comes later
as separate assets). Stylized but convincing game-asset quality, consistent with the attached coaches.
```

Views: `Exact side profile.` · `Rear three-quarter view showing the observation platform.` · `Empty lounge interior
looking towards the observation platform door.` · `The same lounge looking forward to the gangway end.`

## After generation

Send the images (or tell me where they are). I then build each vehicle on the same measured envelope and coupling
interface, with real openings, walkable interiors where there is a door, collision and coupling sockets.
The locomotive is the exception: its shape is too complex for a full script build, so I script the frame, wheels,
cab and boiler, and some hero parts (dome, chimney, cab fittings) can come from Tripo Studio like the furniture.

## 4b. Brake van with end balcony (alternative tail car)

```text
Design an original short brake van to close the same train as the attached coaches, right behind the run-down
second-class coach. Same buffers, coupling and floor height (1.25 m above rail); a rubber-bellows gangway at the
front end only. About 12 m over buffers, two axles or two small bogies, the same curved roof profile with a raised
guard's lookout (a small cupola with windows) and an open rear balcony with a railing, a red tail lamp and steps.
Livery as tired as the second-class coach: faded blue, yellowed ivory band, dull brass. Inside, a small guard's
room with a stove and a bench, wooden floor.

[VIEW] Plain matte white seamless background, no rails, ground, scenery, people, text or dimension marks. Even
studio lighting, glazing that shows the empty interior. Stylized but convincing game-asset quality.
```

Views: `Exact side profile.` · `Rear three-quarter view showing the balcony and tail lamp.` · `Empty guard's room
interior.`
