# Horse racing

Races run in the world on the rules of the `HorseRacing` game plugin
(`games/yorimichi/unreal/Plugins/HorseRacing`, module `AtelierHorseRacing`): a continuous clock with one race day
every two real hours and up to six races a day, computer stables, jockeys and Grand Prix days. Yorimichi shows the
races at two racecourses, the same for every player. Four TVs in Belmonte show the races live, and the Salon des Paris
takes win bets ("gagnant") from every player's wallet. Each player has a stable of their own: Belmonte's "Votre écurie"
estate for the host's player, the Hidamari stable for the next one.

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

## Stables

Racing V1 gives each player a stable at once, free, with no quest; racing stays optional and the world lives on its own
(the computer stables race whatever the players do). Management is light, "stats without menus": what a player needs to
know hangs on the stable itself, read close up, and a small overlay only chooses, sorts and confirms. The rules decide
everything (`HRRules`: `BuyStable`, `FoundStable`, `SetResting`, `BuyHorse`, `ListHorse`, `BreedPlayer`, `HireRider`,
`ListRider`, `ReleaseRider`, the day's close for upkeep and salaries); `RacingStables` (`RacingStables.h/.cpp`) only asks
them and says their answers in French. Money is the wallet's pièces; Henry's economy is unchanged.

- **The sites** (`RacingStables::Sites()`, in the order they are given): `belmonte`, Haras Valley's estate 0 (Val d'Oro,
  the existing building signed "Votre écurie"), which is the rules' stable for sale `old_mill`, renamed "Écurie de la
  Vallée"; then `hidamari`, the new Hidamari stable (陽だまり厩舎, `world/regions/hidamari_stable`), stable id `hidamari`,
  "Écurie Hidamari". **Assignment:** when a player registers, the host gives them the first site no player owns that they
  may claim: Belmonte is for the host's own (persistent) player only, Hidamari for any player, so the host's player gets
  Belmonte and the next player Hidamari, whoever connects first. The stable for sale is bought for them with its three
  riders, a missing one founded (under the stand-in player `site:<id>`, then given to them), an unowned one taken over;
  the rules' price is lent and the balance restored, so it is free. Its jockeys ride (`bRides` off). A third player gets
  none in V1. Changing who gets what is changing the table.
- **Guests** have no persistent identity yet: a guest's stable is theirs for the session. When they leave (or in what
  is saved, `PersistentWorld`), it goes back to the world as a computer stable that keeps its horses and jockeys and
  races on; the next guest takes it over. The host's player's stable, horses, jockeys and coins are saved with the world
  (`HRSave` admission).
- **In the world** (`ARacingStableBoards`, drawn on every machine for its own player, never on a dedicated server, and
  only within 45 m of their stable): a name plate on every stall door (the horse's name, sex, age, card score, the four
  abilities, form, record, status and today's race), the jockeys' board (the three jockeys: country, age, the four stats
  and their overall, salary, record, the day's salaries and costs) and the transfer board (the listed and free jockeys,
  horses for sale). At Belmonte the plates hang on the eleven stall doors of the stable range's yard front and the boards
  either side of its main door (Haras Valley's `estates.json`, estate 0), derived from the estate's committed placement
  (`SM_BM_BE_0_Stables`) by `world/regions/belmonte/build.py` (`BELMONTE_STABLE`) into `runtime.json`'s
  `racing_places.belmonte_stable`, with no hardcoded fallback; at Hidamari on its stall plates and its office's
  cork board, halved (its `stable.json`, only while `AHidamariStable` stands in the world: its committed
  `bEnabled` switch on and its import run). World text is Latin-1.
- **The Hidamari stable is disabled for now.** Its geometry and runtime (#475) are behind committed switches
  (`hidamari_stable/layout.py` `ENABLED = False`, `AHidamariStable::bEnabled`), and its three build steps are explicit.
  The second player is still assigned the `hidamari` stable in the rules (its horses and jockeys race, and its
  host-validated requests work through the live `racing_stable_act` call), but it has no plates, boards, prompts or
  overlay in the world until the stable is enabled: `RacingStables::SiteAnchors` returns none while no
  `AHidamariStable` stands in the world. Enabling it is a separate change: flip both switches, put `world.hidamari_stable` and `unreal.hidamari_stable`
  into the default chain (not explicit) and their outputs into staging/cook, and rebuild the terrain chain that reads
  `hidamari_stable/layout.py` (`world.layout`, `world.hippodrome`, `world.belmonte`, `world.terrain` and the Unreal
  imports after them): a full world rebuild. The content policy already keeps `HidamariStable`/`hidamari_stable` (#482).
- **Actions.** Within reach of a plate or board the HUD offers it and Interact (D-pad Down, E) opens the overlay, a
  narrow panel in the betting window's forest and brass: at a plate, enter the horse for the coming race days or rest it
  (the rules enter a stable's best three non-resting horses each day), put it up for sale at its value or withdraw it
  (another stable buys it at a day's close), or cover it (a partner of the other sex from the stable or another stable,
  the service plus the fee; the foal is born in the stable after the rules' gestation); at the jockeys' board, list a
  jockey for transfer at its value, take it off, or release it; at the transfer board, sign a listed jockey (its price
  to its stable, the offer the rules accept at once) or a free agent, or buy a market recruit or a listed horse. Up and
  down choose, the bottom button acts (twice when it costs or commits), the right button goes back, the bumpers switch
  the transfer board between jockeys and horses, the left button sorts by price or rating. Salaries and upkeep are paid
  from the wallet at each day's close; a jockey who cannot be paid leaves.
- **Authority.** `URacingStableDesk`, on every player controller, carries the stable's view (`FRacingStableView`) and,
  while its owner is at their stable or has the overlay open, the market (`FRacingStableMarket`), both replicated to the
  owner only. A request (`FRacingStableRequest`: the action, a target, another) goes to the host (`ServerRequest`), which
  checks its sizes and action, at most five a second, then `ARacingService::ApplyStableRequest` asks the rules and
  answers (`ClientReply`, the refusal in French). The host rebuilds the views twice a second and when the world changes.

## Records hall

Every statistic of the racing world lives in one place, the "salle des courses" of Belmonte's town hall, and is read on
its objects close up, one page at a time, never in a big menu (Paul's racing vision). The town hall is Haras Valley's
Palazzo Comunale (sign MAIRIE, `heroes.json`: at Belmonte-local (0, -3150, 263) cm, turned to face the piazza); it has no
interior, so the hall is its open ground-floor loggia (24.8 x 4.2 m, 6 m high, five arches onto the piazza, its back
wall pierced by three doors and two windows). `RacingRecords` (`RacingRecords.h/.cpp`) holds it:

- **The objects** (`RacingRecords::HallAnchors`, placed from `runtime.json`'s `racing_places.records_hall`, which
  `world/regions/belmonte/build.py` (`RECORDS_HALL`) derives from the palazzo's committed placement
  `SM_BM_BH_PalazzoComunale` in `assets/belmonte/source.json`; no hardcoded fallback, so no hall without it): a black split-flap board in a brass frame over the middle door (the
  season's standings and the next races at both venues: today's races still to run, then the next three race days);
  between the doors and windows at eye height, one record panel per circuit (Hidamari's oval, Belmonte's turf, Belmonte's
  sand: the best time at each distance, the horse, its jockey, its stable, the date) and per Grand Prix (the final's and
  the heats' records and the winners by season), and the hall's plaque; the honour boards on the end walls (most wins,
  most defeats, most Grands Prix, most earnings, longest winning streaks: the top three horses, jockeys and stables on
  each); in the east corner a walnut card cabinet (a card per horse, jockey and stable), in the west corner a table of
  archive ledgers. World text is Latin-1 TextRender on boards of engine cubes (no new assets) (`ARacingRecordsHall`, on every machine that
  draws, for its own player): built only within 40 m of the hall, culled beyond, rewritten at most once a second and
  only when the texts change; no per-frame work.
- **Reading.** Within reach of an object the HUD offers it and Interact (D-pad Down, E) opens the reader, a narrow panel
  in the betting window's forest and brass. Up and down choose a line, the bottom button opens its card (a horse's,
  jockey's or stable's: totals, records held, last races, titles), the right button goes back, the bumpers switch the
  ranking (horses, jockeys, stables; on a record panel the next panel), left and right turn the page (eight lines a
  page), the left button sorts the cabinet (name, wins, earnings) and the archives (newest first, name), the top button
  picks a first letter; on a keyboard, typing searches a name (accents and case ignored).
- **Where numbers come from.** Henry's rules keep careers and totals: horses' starts, wins, Grands Prix, earnings and
  career lines, riders' rides and wins, stables' titles and earnings. Wins follow the rules (a heat is a ride, never a
  win); a defeat is a start without a win, heats included; a streak counts consecutive wins, heats skipped. A stable's
  races are its horses' career lines (each says which stable it ran for), one race counted once. What the rules do not
  keep, the host notes in a ledger (`FRacingLedger`, `Saved/racing/records.json` beside the world, written with it
  through a temporary file; admitted by `FRacingLedger::FromJson` (version, bounded collections and strings, unique
  record keys, sane counts) and kept aside as `records.json.unreadable-<unix time>` when it is not admissible or belongs
  to another seed, never written over; one that cannot be read or kept aside is left as it is and that session saves no
  ledger): each run race once its winner is home (`RacingRecords::Note`), the record
  times per circuit and distance and per Grand Prix (final, heats) and each rider's Grands Prix, earnings and streaks
  (players who ride included). The host steps the world day by day (`ARacingService::AdvanceNoting`) so a day's races
  are noted before the rules close it, also on a catch-up; record times and riders' extras start when the hall first
  opens.
- **Archives.** The rules archive a horse two in-game years after its retirement (`HRClock::ArchiveDays`, placement
  `archive`); a rider is archived by the same rule. Archived horses and riders leave the cabinet for the archive
  ledgers; the honour boards keep them (all-time). Stables are never archived.
- **Authority.** `URacingRecordsDesk`, on every player controller, carries the page the player reads
  (`FRacingRecordsPage`) and, while they are in the hall, the objects' texts (`FRacingHallBoards`), both replicated to
  the owner only and only on demand. A query (`FRacingRecordsQuery`: object, panel or board, kind, sort, search, page,
  card) goes to the host (`ServerAsk`, at most ten a second), which checks its sizes and builds it from the world and the
  ledger (`RacingRecords::BuildPage`). The hall's texts are rebuilt when a race is noted or the day changes and every
  five seconds for the countdowns, only while someone is in the hall. Text is French; the rules' horse, stable, jockey
  and event names stay English.

## HUD

Near a racecourse the HUD shows one line at the top: the next race and its countdown, "Course en cours" while the
field runs, the podium ("Arrivée : 1. … 2. … 3. …") for five minutes after a finish, or where today's races are run.

## Dev and live

```sh
racing.Next [lead s]        # jump to lead seconds (default 100) before the next start (host)
racing.TimeScale 10         # the racing clock ten times faster (host)
racing.Go hidamari|belmonte # stand by the post of a racecourse
racing.Save                 # write the world now
racing.Tv osteria_front     # stand at a TV's watch point (osteria_front, osteria_back, salon_paris, salon_bar)
racing.TvCapture 0          # keep the TVs' capture off (the idle card only), to measure it
racing.Stable plate 0       # stand before a plate (plate <n>), the jockeys' board (jockeys) or the transfer board (transfers)
racing.Records board        # stand before an object of the records hall: board, record <n>, honour <n>, cabinet, archive, plaque
```

Launch flags: `-racingnext`, `-racingseed=`, `-racingsave=`. The live bridge has `unreal.RacingLive.racing_state()`
(JSON: clock, race, each runner's distance, speed and position), `racing_next(lead)`, `racing_go(venue)` and
`racing_view_point(along, outwards)` (a point by the course and the yaw facing it), `racing_tv_state()` (JSON: the screens,
whether the capture is live, the shot, the nearest screen, frame and GPU times), `racing_tv_go(spot)`, `racing_wallet()`
(JSON: the local wallet, the race card, the last answer, whether the player is at the counter and the window's
selection), `racing_counter_go()` and `racing_bet(race, horse, stake)` (a request as the window sends it). `unreal.RacingStableLive`:
`racing_stable()` (JSON: the stable, its horses and jockeys, the market, the boards shown, the prompt and the overlay),
`racing_stable_go(spot)`, `racing_stable_open()` and `racing_stable_act(action, target, other)`. `unreal.RacingRecordsLive`:
`racing_records()` (JSON: the ledger's size, the objects shown, the object in reach, the boards' texts and the reader),
`racing_records_go(spot)`, `racing_records_open()` and `racing_records_press(key)` (`up`, `down`, `accept`, `back`,
`next`, `prev`, `kind`, `sort`, `letter`, `type:<text>`).
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
request and answer over the wire, refusals, the closed race, the result line); `StableAssign` (the host's player Belmonte, a guest Hidamari whoever comes first, free, three
jockeys, none for a third, a guest's stable back to the world and taken over), `StableEntry` (rest and enter through the
next race day, refusals, the plate's text), `StableTrade` (market and listed horses bought and paid, sale and withdrawal),
`StableBreed` (partners, cost, refusals, the foal born in the stable), `StableJockeys` (the board, listing, release,
a transfer paid to the seller, the refusals, salaries at the day's close and an unpaid jockey leaving), `StableRequest`
(owner-only replication, a guest's request and answer over the wire, refusals), `StablePersistence` (the host's stable
saved and reloaded, a guest's left to the world and taken back), `StablePlaces` (the Belmonte plates and boards on the
estate's front, reach, Hidamari's from its file) and `StableFrench`; `RecordsLedger` (noted once the winner is home,
once only; records only fall; heats never wins; the ledger's JSON), `RecordsHonours` (streaks, rankings best first, the
rules' numbers, a stable's race counted once, the riders' archive rule), `RecordsPages` (every object, paging, search,
sort, cards, refusals, formats, the boards' Latin-1 texts), `RecordsArchive` (the rules' archiving, two pages of
registers, newest first, out of the cabinet), `RecordsRequest` (owner-only replication, a page over the wire, refusals,
the ledger saved and read back, another world's set aside) and `RecordsPlaces` (the objects inside the loggia, clear of
its doors and windows, reach). `uv run pytest
games/yorimichi/tests/test_racing_courses.py -q` checks the committed course data, the simplification and the staging;
`test_racing_assets.py` the asset validation and its lists against the service's.
