# Horse racing

Races run in the world on the rules of the `HorseRacing` game plugin
(`games/yorimichi/unreal/Plugins/HorseRacing`, module `AtelierHorseRacing`): a continuous clock with one race day
every two real hours and up to six races a day, computer stables, jockeys and Grand Prix days. Yorimichi shows the
races at two racecourses, the same for every player. Four TVs in Belmonte show the races live, and the Salon des Paris
takes win bets ("gagnant") from every player's wallet. Player stables come later.

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
- **Players.** The host's own player keeps one id across sessions, saved beside the world
  (`Saved/racing/player-id.txt`), and its record (`HRRules::AddPlayer`: wallet, tickets) is saved with the world; its
  name is their character's. **A remote guest has no persistent identity yet** (an online id may be missing and a
  session id changes every session), so it gets a session player, `session:<session player id>`: a wallet and bets
  for this session only. `PersistentWorld` leaves session players and their tickets out of the save, so nothing
  persistent is ever owned by one; a guest who comes back starts a new wallet. Persistent guest identity is a later
  task. Every rules call that changes the world (and `racing.Next`, `racing.TimeScale`, `racing.Save`) runs on the
  host only.
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
race and each horse crosses the line at its official time in its official place. Before the off the field walks the last
120 m to the start from 180 s to 125 s before it, then stands lined up there (the TVs' build-up, from 120 s, never
shows it walking); after the post each horse eases down to a trot until the race leaves the focus. Each runner keeps its draw lane (the entries' order) across the track. A two-run Grand Prix race shows the run
that counts.

## Venues

| Venue | Course | Lanes |
| --- | --- | --- |
| Hidamari hippodrome | `FHippodromeCourse` (554.2 m oval, counter-clockwise, post at x = 600) | from 5 m inside to 5 m outside the centre line |
| Belmonte racecourse | turf (1799.8 m) or sand (1703.7 m) polyline, `FRacingPolylineCourse` | lane 1 on the line, then 1.9 m steps inwards, to 10 m in |

**Rule:** Grand Prix days (days 3, 6, 9 and 12 of a season) are at Belmonte. The eight ordinary days alternate,
counting from the season's first: Hidamari, Belmonte, Hidamari... A race on sand (the rules' surface 2) at Belmonte
uses its sand track; every other Belmonte race uses the turf.

The Belmonte tracks come from Haras Valley's venue data (`tracks`: closed centrelines every 2 m in Belmonte's plan
metres). `tools/belmonte_courses.py SOURCE` writes the committed, simplified copy `world/racing/belmonte_courses.json`
(lengths are kept exactly; the finish post is `finish_s` = 240 m from the first point), which `data.stage` stages as
`Content/Data/racing/belmonte_courses.json`. At runtime the points are placed round the Belmonte region's origin (the
`ABelmonteRegion` actor's location, `layout.ORIGIN`), as the region places its zones: a point (x, y, z) lands at
`ORIGIN + (x, y, z)` metres. The finish line is at plan (-155, 607.3), the post 3.6 m outside it.

## Horses

While a player is within about 600 m of the course of the race in focus (from 180 s before its start to 180 s after),
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

## TVs

`ARacingBroadcast` (`RacingBroadcast.h/.cpp`) hangs four screens in Belmonte: two in the osteria's taproom on the piazza
(`osteria_front` on the door wall, `osteria_back` on the back wall) and two in the Salon des Paris (`salon_paris`,
`salon_bar`). Their places come from Haras Valley's `Data/tv_spots.json`: a pivot on the wall plane at the screen's
centre, facing its yaw, in Belmonte-local cm. Haras Valley's frame is the region's, so a screen hangs at the region
origin plus its pivot (the osteria's watch point is its map stop at plan (-30.4, 1.6) m). The screens are 1.4 times
Haras Valley's 70-inch one (2.17 m of picture); the Salon's bar screen is 1.3 times and 15 cm higher, to stay over the
mirror's frame. Each is a procedural frame and picture with no collision or shadow; the picture's material is
`/Game/Racing/M_RacingTv` (`unreal.belmonte`, `Scripts/racing_tv_material.py`): unlit, it decodes the picture's
display-encoded colours.

It is presentation only, on every machine that draws (never a dedicated server), from the service's replicated snapshot:
nothing of its own is replicated. The broadcast camera is a pure function of the race in focus, the shared clock and
the players' replicated pawns (`RacingTv::Direct`), so every player sees the same shot at the same moment. Until 15 s
before the off it cuts every 10 s between the whole course from above, the stand, the crowd (the one of three cameras
along the stand that frames the most players, `RacingTv::CrowdCamera`) and the field lined up at the start, head-on.
Then: side-on at the start for the off; trackside cameras every 120 m on the infield, the field galloping towards one
and past it; a view from above in the race's second and third stages; head-on past the post on the home straight
(from 400 m out); side-on at the line from 70 m out until the last runner is home; a wide shot of the field pulling up.
The stands are per venue (`RacingTv::VenueShots`). The lower third shows the event, the countdown, the distance left or
the arrival, and the first three behind their saddle cloths, in large type.

Between races (and away from a race's window, 120 s before its start to 180 s after) the screens show an idle card in
large type: the venue and distance, the event, the countdown, the three favourites with their odds and the last winner,
or the next meeting once the day's races are run.

**Performance.** One scene capture films for all four screens into a 480x270 film, 10 times a second (`racing.TvHz`),
and only while the local player is within 25 m of a screen, in front of it, during a race's window, and while a screen
near the player was drawn in the last 0.3 s (looking away pauses it). The film and the graphics are drawn into the
screens' 640x360 picture with a canvas, so the text stays sharp. It renders without Lumen (a post-process override),
dynamic shadows, reflections, ambient occlusion, volumetric or height fog, clouds, grass, translucency, motion blur,
bloom, particles, decals or temporal AA, with coarser LODs and nothing beyond 400 m except in the views from above,
with a little more contrast and colour. Otherwise nothing is captured: the card is redrawn once a second within 40 m of
a screen, and nothing at all further away. While the capture runs, the service shows the field wherever the race is
(`ARacingService::SetBroadcastAudience`): a Hidamari race is filmed from Belmonte, and the runners' poses are evaluated
though the main view does not draw them. The field is the same six runners the service shows near a venue: no proxies
to keep in step. Each camera's sightline is checked with a trace from its subject against the static world; a blocked
camera moves in front of the obstacle.

## Betting

Win bets only, on the rules' pari-mutuel pool (`HRRules` betting: `BetRefusal`, `PlaceBet`, `SettleRace`). One currency,
the rules' coins ("pièces"): a new player starts with the rules' `FHRPlayer` coins (160) and earns their daily income;
later horses and salaries use the same wallet. Balances saturate within 0..`MaxCoins`; stakes are 1 to 10, at most 30
a day and three tickets a race (`FBetLimits`).

- **The Salon des Paris.** Its three betting windows (Haras Valley's `gameplay.salon`: the central window's betting
  point and the windows 2.5 m apart along the counter) are derived from the Salon hall's committed placement
  (`SM_BM_BHip_SalonHall` in `assets/belmonte/source.json`) by `world/regions/belmonte/build.py` (`SALON_COUNTER`,
  `racing_places`), written into Belmonte's `runtime.json` as `racing_places.counter` and read by `RacingCounter`
  (`RacingBetting.h`, through `RacingPlaces`) round the region's origin, as the TVs. There is no hardcoded fallback:
  without that entry (an old `runtime.json`: run `world.belmonte` and `data.stage`) there is no counter. Within 2.6 m of the counter, on foot, the HUD offers "Parier au guichet" and Interact
  (D-pad Down, E) opens the betting window.
- **The window** (`SRacingBetWindow`, the game's forest-and-brass menu style): today's races still open to bets on the
  left (the venue, distance and countdown), the selected race's runners with their silks, jockey, stable and current
  odds on the right, the stake under them with the estimated return, then the player's open tickets and latest results.
  Gamepad first: LB / RB change the race, up / down the horse, left / right the stake, the bottom button bets (once to
  choose, again to confirm), the right button cancels or closes. The keyboard (Tab, arrows, Enter, Esc) and the mouse
  work the same rows. It exists only while open and redraws when its data changes, never every frame. Under the open
  races, "Demain · programme" previews the next race day, read-only (bets open on the day itself): its venue, event,
  number of races, first distance and the countdown to its first race. The host builds it once a day, when a window
  first opens, by running the day's close on a copy of the world (`ARacingService::BuildPreview`): the copy is taken on
  the game thread (about 2 ms), the close runs on a worker (about 0.3 s), and the card gets it when it is done.
- **Authority.** `URacingWallet`, a component on every player controller, carries the player's wallet view
  (`FRacingWalletView`: coins, the day's stakes, open tickets and the last eight results) and, while their window is
  open, the race card (`FRacingCard`), both replicated to their owner only. A guest's window sends `ServerPlaceBet`; the
  host checks the request (sizes), then `ARacingService::PlaceBet`: betting on a race closes at its start, then the
  rules' refusal decides (the runner, the stake, the day's limit, the balance, the tickets per race), and answers with
  `ClientBetReply` (the refusal in French, empty when taken). At most five requests a second are looked at. Offline and
  on the host the same calls run directly.
- **Settlement.** The rules decide and settle a race at its start (`RunNextRace` pays the winners at the pool's odds,
  refunds a race not run or a non-runner first, and the day's close refunds what is left). The wallet shows a decided
  ticket as running, and its payout not yet in the coins, until 1.5 s after the winner is home
  (`ARacingService::RevealSeconds`), so the result is never known before it is seen. Then the HUD shows one line
  ("Pari gagnant : … +N pièces", "Pari perdu", "Pari remboursé") for seven seconds; no voice.
- **HUD.** The purse sits under the health bar ("160 pièces · 1 pari en cours"). The host refreshes every wallet twice
  a second and when the world changes; a bet republishes the snapshot so the TVs show the moved odds.
- **Persistence.** The host's player's coins and tickets are part of the racing world and saved with it (`HRSave`
  admission); a session player's are not.

## HUD

Inside a racecourse's grounds the HUD shows one English line at the top: the next race and its countdown, "Race in
progress" while the field runs, the podium ("Results: 1. … 2. … 3. …") for five minutes after a finish, or where today's
races are run. The banner stays hidden outside the venue and more than 20 m above or 3 m below the track. Hidamari uses
its authored platform; Belmonte uses the closed turf track and its 30 m spectator apron. The wider racehorse rendering
radius does not enable the banner.

## Dev and live

```sh
racing.Next [lead s]        # jump to lead seconds (default 100) before the next start (host)
racing.TimeScale 10         # the racing clock ten times faster (host)
racing.Go hidamari|belmonte # stand by the post of a racecourse
racing.Save                 # write the world now
racing.Tv osteria_front     # stand at a TV's watch point (osteria_front, osteria_back, salon_paris, salon_bar)
racing.TvCapture 0          # keep the TVs' capture off (the idle card only), to measure it
```

Launch flags: `-racingnext`, `-racingseed=`, `-racingsave=`. The live bridge has `unreal.RacingLive.racing_state()`
(JSON: clock, race, each runner's distance, speed and position), `racing_next(lead)`, `racing_go(venue)` and
`racing_view_point(along, outwards)` (a point by the course and the yaw facing it), `racing_tv_state()` (JSON: the screens,
whether the capture is live, the shot, the nearest screen, frame and GPU times), `racing_tv_go(spot)`, `racing_wallet()`
(JSON: the local wallet, the race card, the last answer, whether the player is at the counter and the window's
selection), `racing_counter_go()` and `racing_bet(race, horse, stake)` (a request as the window sends it).
`unreal.YorimichiLive.pad_input('Gamepad_DPad_Down', 1)` then `0` presses Interact through the gamepad mapping; the
window takes the same pad keys.

## Tests

`Yorimichi.Racing.*`: `BelmonteCourse` (lap lengths, continuity of every lane, the finish point and the post),
`HippodromeCourse`, `Motion` (the same distances from the host's world and from a serialised snapshot, monotone, through
each split on time, places in finishing order, lined up before the off), `Snapshot` (size, the venue rule, the last
result after a race), `Save` (create, save and reload through the service on a temporary path), `SaveSafety` (an
invalid save kept aside; one that cannot be moved left untouched with no world opened; a failed save keeping the world
in memory, then succeeding), `Ground` (walls, rails, roofs and steep slopes ignored, the authored height after a miss), `TvPlacement` (the
screens round the region origin, the osteria's watch point on its map stop, each watch point in front of its screen) and
`TvDirector` (the shot list, the crowd camera, the same camera for the same clock, the leader in frame), `BetValidation`
(every refusal, closing at the start, the limits, the card), `BetSettlement` (one winner at the rules' odds, saturation,
the reveal after the post, settled once), `BetRefund` (a race not run, a non-runner), `BetPreview` (the next day from a copy, the world untouched, the same races and first start as the day the rules
open), `BetPersistence` (the host's
wallet and ticket saved and reloaded, a guest's never written) and `BetRequest` (owner-only replication, a guest's
request and answer over the wire, refusals, the closed race, the result line). `uv run pytest
games/yorimichi/tests/test_racing_courses.py -q` checks the committed course data, the simplification and the staging;
`test_racing_assets.py` the asset validation and its lists against the service's.
