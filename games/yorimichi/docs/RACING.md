# Horse racing

Races run in the world on the rules of Yorimichi's `HorseRacing` plugin
(`unreal/Plugins/HorseRacing`, module `AtelierHorseRacing`): a continuous clock with one race day
every two real hours and up to six races a day, computer stables, jockeys and Grand Prix days. Yorimichi shows the
races at two racecourses, the same for every player. There are no bets, stables or menus yet: later work adds TVs,
betting and player stables.

## The service

`ARacingService` (`RacingService.h/.cpp`) is one replicated actor, spawned by the host (offline: the game itself) once
the world is in place; clients receive it. It follows `ABelmonteTrainService`: one network-state struct with a serial,
and positions computed on every machine from the replicated clock, never replicated per frame.

- **The world.** The host owns the rules' `FHRWorldState`. It loads `Saved/racing/world.json` (or `-racingsave=PATH`)
  or creates a world from `-racingseed=` (default `yorimichi-racing-1`) and anchors its clock to Unix time, so the
  racing world keeps going between sessions and a host that was away catches up (at most one race day per frame, so
  hours of catch-up never hitch, and at most `HRRules::MaxCatchUpDays`, one real week: a host away longer resumes as if
  the world had paused then). It saves after a race or a day changes the world (at most every 15 s) and when the game
  ends, atomically: a flushed temporary file renamed over the old one, so a crash leaves the old world or the new one.
- **Admission and failures.** A save is admitted by `HRSave::FromJson` before it replaces anything (schema and rules
  versions, required fields, unique ids, references, ranges and collection sizes). A file that is not an admissible
  world is kept aside (`world.json.unreadable-<time>`) and a new world is created; if it cannot be moved aside, or the
  file cannot be read at all, it is left exactly as it is, no world opens and racing stays off (an error in the log,
  `GetPersistenceError()`). A failed save keeps the accepted world in memory and dirty, logs the error, and the next save
  tries again.
- **Players.** V1 registers the host's own player only (`HRRules::AddPlayer`), with an id saved beside the world
  (`Saved/racing/player-id.txt`); its name is their character's. **Remote guests get no player record, wallet or stable**:
  there is no persistent guest identity yet (an online id may be missing and a session id changes every session), so
  nothing persistent may be owned by one. Guests watch from the replicated snapshot, which carries no player, coins,
  tickets or ownership; every rules call that changes the world (and `racing.Next`, `racing.TimeScale`, `racing.Save`)
  runs on the host only. Betting, stables and wallets for guests wait for a persistent guest identity.
- **The snapshot.** `FRacingNetState` carries the clock anchor (the rules' world second at a server time, and the dev
  time scale), the race day and its event, the race in focus, the last podium and the six best stables. The race in
  focus is the one running or just run (for the rules' 180 s after its start), else the next one today. Each runner
  has its horse, stable, jockey, silks colour, win odds, look (breed, coat, scale) and, once run, its place and the
  four stage splits. A five-runner snapshot weighs about 0.8 kB on the wire (`FRacingNetState::PayloadBytes`; `Yorimichi.Racing.Snapshot` holds it under 2 kB). The host
  rebuilds it every second and publishes a new serial only when its content changes or the clock needs re-anchoring.

## Motion

The rules decide a race when it starts (`HRRules::ResolveRace`): each horse's cumulative time at the end of its four
stages (15, 35, 25 and 25 % of the distance). `RacingMotion::Distance` (`RacingMotion.h`) turns those splits into
distance over time with a monotone cubic through the stage ends, from a standing start, so every machine draws the same
race and each horse crosses the line at its official time in its official place. Before the start the field walks the
last 120 m to the start and stands for 15 s; after the post each horse eases down to a trot until the race leaves the
focus. Each runner keeps its draw lane (the entries' order) across the track. A two-run Grand Prix race shows the run
that counts.

## Venues

| Venue | Course | Lanes |
| --- | --- | --- |
| Hidamari hippodrome | `FHippodromeCourse` (554.2 m oval, counter-clockwise, post at x = 600) | from 5 m inside to 5 m outside the centre line |
| Belmonte racecourse | turf (1799.8 m) or sand (1703.7 m) polyline, `FRacingPolylineCourse` | lane 1 on the line, then 1.9 m steps inwards, to 10 m in |

**Rule:** Grand Prix days (days 3, 6, 9 and 12 of a season) are at Belmonte. The eight ordinary days alternate,
counting from the season's first: Hidamari, Belmonte, Hidamari... A race on sand (the rules' surface 2) at Belmonte
uses its sand track; every other Belmonte race uses the turf.

The Belmonte tracks are the committed course data `world/racing/belmonte_courses.json` (closed centrelines in
Belmonte's plan metres, pinned to the venue scene; the finish post is `finish_s` = 240 m from the first point).
`world/racing/courses.py` validates them against the placed course mesh and `data.stage` stages them as
`Content/Data/racing/belmonte_courses.json`. At runtime the points are placed round the Belmonte region's origin (the
`ABelmonteRegion` actor's location, `layout.ORIGIN`), as the region places its zones: a point (x, y, z) lands at
`ORIGIN + (x, y, z)` metres. The finish line is at plan (-155, 607.3), the post 3.6 m outside it.

## Horses

While a player is within about 600 m of the course of the race in focus (from 120 s before its start to 180 s after),
the service shows its field: up to six runners (the rules' `MaxRunners`). Each is three skeletal components moved by the
service: the roster's breed mesh (`Content/Data/horses/roster.json`) with its coat variant, the first tack set's saddle
in the stable's colour (the saddle cloth), and a jockey, the default character on his own horse clips (authored on the
reference breed and moved by the breed's seat offset; the hands and feet are not re-solved as `FHorseRiderNode` does
for the player). The gait follows the speed through the roster's Idle, Walk, Trot, Canter, Gallop and Sprint clips,
horse and jockey on one phase. The rules' breed gene picks the breed (Standard: Thoroughbred, Giant: Friesian, Bone:
Andalusian, Spirit: Arabian), the visual genome's coat colour the closest coat variant, and the size its individual
scale within 8 %.

**No stand-ins.** Every racing breed's mesh, six gait clips, first saddle and seat contacts, every coat texture and the
default character's six horseback clips are required. If one is missing the service logs an error and shows no field: a
runner is never riderless, in another breed or coat, or missing from its race (an entrant the world lacks is an error
too). The build checks the same list before the cook: `data.racing_assets` (`tools/racing_assets.py`) fails when an asset
is missing from the staged roster or Content, or lies outside a folder `DefaultGame.ini` always cooks (`/Game/Horses`
and the default rig's `/Game/<rig>Horse`, since the service loads them by path).

**Ground.** A shown runner traces the ground every 0.4 s through its course point. Only walkable ground counts
(`RacingGround::Pick`): a hit facing up (normal z at least 0.7), within 2.5 m above and 4 m below the point's authored
height, the nearest to it, so walls, rails and roofs above the track are ignored. Without one the runner is back on the
authored height, never on the last traced one; the traced offset follows the authored slope between traces.

Performance: no runner exists away from the venue, out of the race window or on a dedicated server; the service then
ticks four times a second. A shown runner evaluates its pose only when rendered.

## HUD

Near a racecourse the HUD shows one line at the top: the next race and its countdown, "Course en cours" while the
field runs, the podium ("Arrivée : 1. … 2. … 3. …") for five minutes after a finish, or where today's races are run.

## Dev and live

```sh
racing.Next [lead s]        # jump to lead seconds (default 100) before the next start (host)
racing.TimeScale 10         # the racing clock ten times faster (host)
racing.Go hidamari|belmonte # stand by the post of a racecourse
racing.Save                 # write the world now
```

Launch flags: `-racingnext`, `-racingseed=`, `-racingsave=`. The live bridge has `unreal.RacingLive.racing_state()`
(JSON: clock, race, each runner's distance, speed and position), `racing_next(lead)`, `racing_go(venue)` and
`racing_view_point(along, outwards)` (a point by the course and the yaw facing it).

## Tests

`Yorimichi.Racing.*`: `BelmonteCourse` (lap lengths, continuity of every lane, the finish point and the post),
`HippodromeCourse`, `Motion` (the same distances from the host's world and from a serialised snapshot, monotone, through
each split on time, places in finishing order), `Snapshot` (size, the venue rule, the last result after a race),
`Save` (create, save and reload through the service on a temporary path), `SaveSafety` (an invalid save kept aside; one
that cannot be moved left untouched with no world opened; a failed save keeping the world in memory, then succeeding)
and `Ground` (walls, rails, roofs and steep slopes ignored, the authored height after a miss). `uv run pytest
games/yorimichi/tests/test_racing_courses.py -q` checks the committed course data against the venue and its staging;
`test_racing_assets.py` the asset validation and its lists against the service's.
