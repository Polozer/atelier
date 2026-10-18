# Polozer integration backlog

This tracks implemented work in the fork that is missing from upstream, and the
acceptance required before integration. Source delivery is not merge approval.
No audited fork PR is accepted for direct merge as written.

The audit on 2026-10-18 compared upstream main
`cba74a0bfbec8310f01f7def2b59faebb8952df9` with the five open fork heads below.
The fork's `upstream-main` was `b8a05e43827f0535c55fd031447dfad8b51722f2`.
Recheck these boundaries before integrating later fork changes.

## Delivered source missing from upstream

| Fork PR and frozen head | Implemented scope | Readiness at the audit |
| --- | --- | --- |
| [#2](https://github.com/Polozer/atelier/pull/2), `52377189225ca2082390bd238c73387474982192` | Osteria indoor map stop | Complete small source change; Python CI fails an unchanged expected destination list. Landing geometry needs correction and verification. |
| [#4](https://github.com/Polozer/atelier/pull/4), `2b8e6c4e8afcea31cfbdb88934272a60a4bc22e7` | Faster hidden tunnel travel and passing-loop timetable | Author reports a full-cycle playtest. Python CI fails atlas provenance. Full-consist tunnel containment needs hardening. |
| [#6](https://github.com/Polozer/atelier/pull/6), `31f7a9679fe1f6c5acd9052cfa4f54d17209b63f` | Boarding-only admission, vehicle prohibition, intruder recovery, passenger first-person camera | Python CI passes. Author reports 21/22 network fixtures on an older base; BikeSupport lacked Content. Intruder recovery and visibility restoration need repairs. |
| [#3](https://github.com/Polozer/atelier/pull/3), `cf3af1977621a2d42fea2f20bb5dd4bd6ffbd0f0` | Standalone deterministic racing rules, genetics, biology, stables, jockeys, markets, economy and serialization | Python CI passes; 20 native tests are author-reported. Save admission, arithmetic, ordering and ownership require independent review. No game UI or network service is delivered here. |
| [#5](https://github.com/Polozer/atelier/pull/5), `614a437d35796b585efd33d6e847ad7ba7c97c59` | Host racing service, replicated snapshots, venue courses, animated runners and spectator HUD | Python CI passes; native tests and performance are author-reported. The actual two-player run is explicitly absent. Persistence, collision, content validation and packaging need repairs/proof. |

PR #5 is stacked on #3. Its own delta is 18 files; do not import or count the
rules plugin twice. All five fork contract-review runs failed to start/read server
information; those failures provide no semantic approval. Native claims above have
not been independently reproduced by this audit.

## Atomic upstream changes

These PRs are drafts, outside r8. None has merged. Native work is deferred until
verified r8 publication; no capacity is reserved while waiting. A Python CI pass
does not certify C++ compilation, UHT, native behavior or multiplayer behavior.

| Upstream PR | Fork scope | Remaining acceptance |
| --- | --- | --- |
| [#409](https://github.com/fontanierh/atelier/pull/409) | #2: Osteria map stop | Eight source geometry/placement tests pass. Landing now follows the committed taproom transform. New-head hosted CI, native host/guest landing, controller/phone selection and peer approval remain. |
| [#410](https://github.com/fontanierh/atelier/pull/410) | #4: tunnel timing | Focused timing tests pass. Regenerate genuine atlas references, validate the full route/profile and native timetable in both directions and multiplayer. |
| [#411](https://github.com/fontanierh/atelier/pull/411) | #6: vehicle deployment gates | Exact-head hosted CI passes. Compile and run actual handler regressions, then verify boarding stairs, requests and stowing with host/guest. Admission/intruder recovery is separate. |
| [#412](https://github.com/fontanierh/atelier/pull/412) | #6: passenger camera | Compile/run native camera regressions and verify all rigs, seats, transitions, pawn replacement, input focus, cinematic views and other players' visibility. |
| [#413](https://github.com/fontanierh/atelier/pull/413) | #5: course data and staging | Focused data/staging tests pass, including six lane offsets sampled against committed course geometry. Imported collision and packaged consumption remain. No races are enabled. |
| [#414](https://github.com/fontanierh/atelier/pull/414) | #3: deterministic random foundation | Compile enabled plugin and run native reference/rejection tests. |
| [#415](https://github.com/fontanierh/atelier/pull/415) | #3: clock/calendar | Stacked on #414. Compile/run native schedule boundaries and reference cases. Catch-up/world advancement is separate. |
| [#416](https://github.com/fontanierh/atelier/pull/416) | #3: horse value structures | Stacked on #414. Verify UHT, exported structures and native arithmetic tests. Structures are not admitted saves or requests. |
| [#417](https://github.com/fontanierh/atelier/pull/417) | #3: breed dominance/inheritance | Stacked on #416. Compile/run complete dominance table, reference draws and malformed-parent rejection tests. Migration and scaling are separate. |

Every code PR still needs final exact-head hosted CI, paid contract review,
independent peer approval and the relevant native acceptance before merging.
Restack dependent PRs after their parent merges and repeat affected final-head checks.

## Coordinate ownership audit

The source audit of the nine drafts found one duplicated placement to repair:
#409 originally followed the region origin but not the Osteria building. Head
`82cd22bf` derives its position and facing from the committed taproom placement
plus an authored local landing offset. Focused tests cover region movement,
building translation/rotation/scale and missing/ambiguous placements, alongside
the existing floor, roof and standing-volume geometry checks.

#413 stores authored course points in the declared region-local frame, pinned to
the venue-scene checksum. Its future runtime consumer must use the generated region
origin; this consumer is not delivered or certified by the data-only PR. Imported
collision and packaged consumption remain acceptance requirements.

#412 derives its view from the rider transform and head bone. Eye offsets and
smoothing values are camera authoring parameters, not world placements; all-rig,
seat and cinematic validation still requires native execution. #410 uses line
distance and classified tunnel intervals. #411 and #414–417 add no production world
placements. Synthetic native-test locations are fixtures, not runtime destinations.

This does not certify the still-unintegrated boarding recovery or racing service.
Those changes must derive positions from shared authored data and prove terrain
support and clearance before acceptance.

## Remaining integration units

### Boarding admission and safe recovery (#6)

- Maintain admission through door walk, gangway grace, seats, cancellation, exit,
  travel, respawn, pawn replacement and disconnect.
- Replace the fork's final unverified `TravelTo` fallback with a defined safe
  recovery policy requiring walkable ground and standing capsule clearance.
  A height trace alone is insufficient, particularly on tunnels and viaducts.
- Use authoritative activity and trusted remote-skater presentation correctly;
  the host capsule need not follow the rendered skater.
- Avoid relocating platform bystanders merely intersected by a passing coach.
- Verify real host/guest requests, epochs, normal boarding and imported BikeSupport.

### Racing rules beyond the foundation (#3)

- Split stable/jockey/player, race/result and world/economy state into coherent
  data owners. Keep reusable rules free of game actors, UI and asset names.
- Integrate genetics, appearance, ageing/retirement, breeding and training with
  explicit shape/range admission before indexing or arithmetic.
- Integrate race outcomes, season/catch-up, markets, ownership, rider progression,
  currency and win-bet settlement. Check deterministic ordering, bounded catch-up,
  overflow and duplicate/refund/settlement invariants.
- Admit saves by schema and rules version, required fields, unique identities,
  valid references, ranges and collection bounds before mutating accepted state.
  JSON conversion plus a rules-version check is insufficient.
- Independently reproduce reference vectors and the fork's native rules tests,
  adding malformed-state and economic-invariant coverage where necessary.
  An in-memory multiplayer rules fixture is not network certification.

### Live races beyond committed course data (#5)

- Separate host persistence, replicated state, course loading and presentation.
- Preserve the original corrupt save if backup rename fails; do not replace it
  with a new world. Propagate open/save errors without losing accepted state.
- Validate all lanes on imported course collision: ground continuity/normals,
  rails/buildings, hoof contact, and safe behavior after failed traces. The fork
  accepts arbitrary static hits and retains stale ground height after misses.
- Require the normal build/cook graph to validate horse, breed, jockey and coat
  assets. Remove silent missing-runner, riderless and different-breed fallbacks.
- Verify fresh build, cook and packaged run, including dynamically loaded assets,
  staged courses, memory and frame budgets.
- Test actual host/guest join, late join, rejoin, clock/race/finish and venue changes
  under latency and packet loss. Binary serialization round-trips are insufficient.
- Establish persistent guest identity before exposing persistent ownership/wallets.

## Exclusions

The Salon stop/indoor trace support, original railway and station arrival,
production train furniture/LODs and Zeppelin clearance were already integrated at
the compared upstream boundary.

Race TVs, betting-counter/wallet UI, stable buildings/management UI, records hall
and persistent guest ownership are future work described by the fork, not completed
deliveries in these five heads. Do not include them in the delivered-source total.

## Fork completion notices

After a fork PR's **entire delivered scope** reaches upstream main, comment on that
fork PR with upstream PR links, actual merge SHAs and material fixes/differences.
Do not announce completion from an open draft, branch push, partial slice or tests
alone. In particular, vehicle gates and the camera do not complete #6 while
boarding admission and safe recovery remain outstanding.

| Fork PR | Integrated into upstream main | Completion notice |
| --- | --- | --- |
| #2 | Pending #409 acceptance/merge | Pending |
| #4 | Pending #410 acceptance/merge | Pending |
| #6 | Pending #411/#412 and admission/recovery | Pending |
| #3 | Pending foundation and remaining rules | Pending |
| #5 | Pending #3, course data and live-race integration | Pending |
