# Belmonte train: to-do

The owner's running list for the Belmonte train, in order. All seven vehicles are built as shells
([the shell](BELMONTE_TRAIN_SHELL.md)); what is left is mostly furniture, then the train on the map. Each coach's
unbuilt items are the reservation boxes in `world/train/layout.py`. This list follows them: an item is done when
its box becomes a fitted Tripo piece (`fit_furniture.py`) or a modelled part, with `L.check` still clean.

## 1. Finish the interiors (now)

The train must be fully finished and designed inside before anyone can ride it.

| Vehicle | Still reservation boxes |
|---|---|
| Second class | canteen counter (re-fit from the new Tripo model, in progress), canteen sink and draining board, canteen shelves (stacked tin plates and mugs) |
| Restaurant | bar counter and glazed back-bar (the empty grey floor at the bar end), drinks ledge under window 6, galley range and worktops (outer and partition side), WC toilet and basin |
| First class | 8 brass luggage racks above the sofas, attendant pantry counter and folding seat, luggage shelving, 2 WCs (toilet and basin each) |
| Locomotive | cab back plates, screw reverser stand, driver's and fireman's flap seats, backhead pipework on both sides |
| Baggage van | 6 parcel and trunk shelf units, guard's stove, sorting desk, handbrake column |
| Brake van | stove with its flue, guard's bench, desk with pigeon-holes, lookout steps, 2 parcel shelf units, balcony handbrake |

Simple, straight or repeated parts (shelves, racks, steps, pipework, rails) are better modelled in code than drawn
in Tripo: they come out straight and cost nothing. The canteen tray slide was the first.

## 2. Later

- **The canteen lady** ([brief](BELMONTE_TRAIN_CANTEEN_LADY.md)): her spot, the serve point and the queue are already
  placed at the counter.
- **The train on the map, rideable.** Decisions so far:
  - It runs on today's map, keeping at least 1550 m from (850, 2400), where the volcano will go.
  - It follows a fixed timetable, computed on every machine from the server clock, the way the zeppelin's position
    is computed.
  - Departure boards in the stations. Yorimichi has no in-game clock yet, so the boards need one to be designed.
  - Hidamari station is Henry's to design and Belmonte station the owner's. Reserve their space; build neither here.
  - Riding: board at the doors in stations. Aboard, players walk in the train's own frame on each coach's floor plan
    (rooms, walls, doors and furniture from `layout.py`), with no physics at speed, so nobody can fall out or through
    a wall. Seats to sit on, coach to coach through the gangways, get off at stations.
  - Before playtests, multiplayer receipts like the zeppelin's and long bot walks aboard a moving train.
