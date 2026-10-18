# Belmonte train: to-do

The owner's running list for the Belmonte train, in order. All seven vehicles are built as shells
([the shell](BELMONTE_TRAIN_SHELL.md)); what is left is mostly furniture, then the train on the map. Each coach's
unbuilt items are the reservation boxes in `world/train/layout.py`. This list follows them: an item is done when
its box becomes a fitted Tripo piece (`fit_furniture.py`) or a modelled part, with `L.check` still clean.

## 1. Finish the interiors (now)

The train must be fully finished and designed inside before anyone can ride it.

| Vehicle | Still reservation boxes |
|---|---|
| Second class | canteen plates (stacks on the shelves, once the Tripo plate is made) |
| Restaurant | bar counter and glazed back-bar (the empty grey floor at the bar end), drinks ledge under window 6, galley range and worktops (outer and partition side), WC toilet and basin |
| First class | attendant pantry counter and folding seat, luggage shelving, 2 WCs (toilet and basin each) |
| Locomotive | cab back plates, screw reverser stand, driver's and fireman's flap seats, backhead pipework on both sides |
| Baggage van | 6 parcel and trunk shelf units, guard's stove, sorting desk, handbrake column |
| Brake van | stove with its flue, guard's bench, desk with pigeon-holes, lookout steps, 2 parcel shelf units, balcony handbrake |

Simple, straight or repeated parts (shelves, racks, steps, pipework, rails) are better modelled in code than drawn
in Tripo: they come out straight and cost nothing. The canteen tray slide was the first.

## 2. When the interiors are designed: fit and access

Before riding, check the whole train against the playable characters, and make the checks automatic in
`layout.py` (`check()` and the tests), so a later piece of furniture can't break them:

- **Sizes:** every playable character, from Cairo (1.48 m) to Modori (1.75 m), fits the headroom under lamps, racks
  and doorways, the door widths, and the aisle and corridor clearances, with each character's own radius.
- **Walking through:** each coach can be walked end to end, and the gangways join neighbouring coaches at the same
  floor height.
- **Access by class**, in consist order (locomotive, tender, baggage van, restaurant, first class, second class,
  brake van):
  - first class and the restaurant are open to each other;
  - the gangway doors from **second class to first class and to the brake van are locked** for passengers;
  - the locomotive, tender and baggage van are staff only: not reachable from the passenger coaches, but walkable
    inside.
- **Tickets:** a second-class ticket keeps the player in second class until the next stop, with only the exterior
  doors opening, at stations. The rule lives in an access graph that the layout checks: no passenger route from
  second class to any other coach.

## 3. Later

- **The canteen lady** ([brief](BELMONTE_TRAIN_CANTEEN_LADY.md)): her spot, the serve point and the queue are already
  placed at the counter.
- **The train on the map, rideable.** Decisions so far:
  - It runs on today's map, keeping at least 1550 m from (850, 2400), where the volcano will go.
  - It follows a fixed timetable, computed on every machine from the server clock, the way the zeppelin's position
    is computed.
  - Departure boards in the stations. Yorimichi has no in-game clock yet, so the boards need one to be designed.
  - Hidamari and Belmonte stations are designed separately. Reserve their space; build neither here.
  - Sitting: on the controller, D-pad down (Yorimichi's Interact) near a seat sits the player on the nearest free
    seat marker (each bench and sofa exports its seats with position, height and facing), and again stands them
    up. A seat taken in multiplayer is unavailable to others. The characters' seat correctives
    (`SeatCorrectiveComponent`) keep every body height seated cleanly.
  - Riding: board at the doors in stations. Aboard, players walk in the train's own frame on each coach's floor plan
    (rooms, walls, doors and furniture from `layout.py`), with no physics at speed, so nobody can fall out or through
    a wall. Seats to sit on, coach to coach through the gangways, get off at stations.
  - On foot only (done): the boarding walk (Monter at a station door) is the one way aboard. Aboard, seated or on
    the steps, the skateboard, bike, horse and sailboat are refused ("Pas à bord du train"), locally and by the host.
    The ticket (`BelmonteTrainRules::FAdmission`) holds through the door walk, seats, gangways and vestibules
    (1.5 s grace off the train) and the whole run; the walk down, a teleport, respawn or the map's travel ends it, a
    pawn replacement carries it over and a disconnect drops it. Anyone riding inside a running or departing coach
    without it (a vehicle through an open door, a jump, the paraglider, a dash) is put back on safe ground, off any
    vehicle, by the host (`ABelmonteTrainService::Eject`); a bystander a passing coach merely sweeps through is left
    alone. The destination is, in order, the platform beside the coach, a door-side point, the player's last safe
    ground, a door-side point recorded while the train ran in the open, then the next station; in a tunnel or on a
    viaduct never beside the coach. Each is accepted only on walkable ground that is not the train with room for the
    standing capsule (`BelmonteTrainRecovery::SafeStand`); with none the player is not moved.
  - First-person view aboard (done): P or the left bumper switches between third and first person, standing or
    seated; the body is hidden from the player's own view only, and leaving the train restores third person. The
    last choice is kept for the session.
  - No sprinting aboard: each coach exports its interior (rooms and gangways) as a no-sprint zone, and the
    game drops players to walking speed inside it.
  - Gangways are closed: invisible walls on both sides (and above) every coach-to-coach crossing, so nobody
    can fall out between two coaches.
  - Hit boxes: every piece of furniture is solid, no box sticks into aisles or doorways, seats sit on their
    collision, and the brake van lookout can be climbed (its ceiling collision still spans the well).
  - Before playtests, multiplayer receipts like the zeppelin's and long bot walks aboard a moving train.
