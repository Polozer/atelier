# Horse Racing

Pure, deterministic rules for a horse racing world: stables, horses with genetics and visual genomes, three jockeys per
stable, meetings and races, win-only pari-mutuel betting, breeding, training, a horse market and rider transfers. The
module (`AtelierHorseRacing`) holds plain `USTRUCT` data and free functions only: no actors, no UI, no assets. A game
draws, replicates and presents the state; the rules decide everything else.

## Using it

1. Enable `HorseRacing` in the game's `.uproject` and add `AtelierHorseRacing` to the game module's dependencies.
2. On the authority, build or load a world: `HRRules::CreateWorld(Seed)` or `HRSave::FromJson(Json, State)`.
3. Register players with `HRRules::AddPlayer(State, PlayerId, Name)`. A player id is an opaque string (an online
   subsystem id, a guest id...). Any number of players can own a stable (`BuyStable` or `FoundStable`) alongside the
   computer stables.
4. Anchor the clock once with `HRRules::StartClock(State, NowUnix)`, then call
   `HRRules::AdvanceTo(State, HRRules::WorldSeconds(State, NowUnix))` from the host tick. It runs every race whose slot
   has started and closes finished days, so a host that was offline catches up deterministically.
5. Player actions (`PlaceBet`, `BuyHorse`, `ListHorse`, `HireRider`, `ListRider`, `TrainHorse`, `BreedPlayer`...) take the
   player id and return a refusal reason or apply the change.
6. Save and replicate with `HRSave::ToJson` / `HRSave::FromJson`; the whole world state round-trips.

## Time

| Clock | Rule |
| --- | --- |
| World | Continuous. One race day every 2 real hours; a season of 12 days (8 ordinary, 4 Grand Prix) lasts 24 hours. |
| Races | Up to 6 slots per day (more on Grand Prix days, whose barrages and final take the last two slots). `HRClock::ScheduleAt` maps any second to its season, day, slot and phase. |
| Horses | One horse year = one real week (84 race days). Adult after one week; careers of 6 to 9 weeks. Gestation is 21 race days. |
| Archive | A retired horse stays 48 hours (24 race days) for breeding, then leaves the world. |

Money is a generic in-game currency. Each stable keeps 3 jockeys on fixed salaries; between seasons computer stables list,
buy and swap riders on the transfer market, which players use too.

Balances (coins, debts, prices) stay within `0..HRRules::MaxCoins`: credits saturate and pools are summed in int64. A
ticket is settled once (refunds first, so every winner of a race gets the same odds); a race not run refunds its stakes.
`AdvanceTo` simulates at most `MaxCatchUpDays` (one real week) per call: a longer absence moves the clock anchor forward
(`LimitCatchUp`), deterministically.

`HRSave::FromJson` admits a save before replacing anything: schema and rules versions, required fields, no repeated JSON
key, unique stables, races and tickets, valid owners, parents, riders, entrants and bets, numeric ranges (abilities,
alleles, coins, stakes) and collection bounds (`HRSave::Max*`). A refused save gives its reason.

## Tests

`Atelier.HorseRacing.*` automation tests cover the reference vectors in `Tests/`, the schedule mapping, ageing,
archiving, betting, riders, owners, visual genetics, the JSON round trip, save admission (malformed saves), the economy's
invariants and determinism.
