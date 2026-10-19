# Polozer integration backlog

This tracks implemented work in the fork that is missing from upstream, and the
acceptance required before integration. Source delivery is not merge approval.
No audited fork PR is accepted for direct merge as written.

The audit on 2026-10-18 compared upstream main
`cba74a0bfbec8310f01f7def2b59faebb8952df9` with the five open fork heads below.
The fork's `upstream-main` was `b8a05e43827f0535c55fd031447dfad8b51722f2`.
The follow-up inventory compared current main
`d132d4df1ac220a2631836b8262d45f27816375f` on the same date. The original five fork
heads remain unchanged; fork PRs #7 and #8 below are additional deliveries.
The original audit's checks and author-reported results are historical evidence,
not acceptance against the newer main. Recheck these boundaries before integration.

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

## Additional fork deliveries since the original audit

| Fork PR and frozen head | Delivered source scope | Required integration and acceptance |
| --- | --- | --- |
| [#7](https://github.com/Polozer/atelier/pull/7), `6ec2817759a6b021c32a4575947cbc0ebf6435ed` | Relocated Belmonte terminus, station buildings/platforms, overbridge, station earthworks and Salon walking path | Source audit pending. Split placement/route, terrain, station meshes/LODs/collision and access paths into reviewable units. Preserve upstream shoreline ownership and the Hidamari endpoint. Independently validate route reproducibility, final terrain support, road/rail/capsule clearances, vegetation exclusion, budgets, atlas references, host/guest and packaged consumption. Author-reported screenshots/tests do not establish upstream readiness. |
| [#8](https://github.com/Polozer/atelier/pull/8), `3908ce16958d079ea9cbda6668ea4d3748cc3ffa` | Shared racing TV capture/materials, camera direction, idle/live overlays and osteria/Salon screens | Stacked on #5; not an independent rules/runtime delivery. Source audit pending. Derive screens from authored building transforms, validate asset/cook dependencies, deterministic host/guest direction and clock behavior, joins/venue changes, visibility gating and measured capture cost. No TV slice lands before the race state it consumes is accepted. |

These two PRs were absent from the initial five-head audit. They extend the todo
list; they do not make the existing rules, saves or network service accepted.

## Atomic upstream changes

The nine implementation PRs below remain drafts and none has merged at this
inventory boundary. Release r8 is published at source
`4ff62dabbc1a20350a3a849e58f00196db8a3dff`, tag
[`yorimichi-macos-2026-10-18-r8`](https://github.com/fontanierh/atelier/releases/tag/yorimichi-macos-2026-10-18-r8).
The publication-dependent native deferral has ended. Every slice must now rebase
onto actual main, complete its acceptance and land independently. A Python CI pass
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

### Pre-refresh head inventory

These are the heads before the current-main rebase pass. Their successful hosted
checks apply only to these old revisions. No code PR below yet has final paid
review or complete native acceptance; earlier peer source reviews must be
reconfirmed after substantive changes.

| PR | Pre-refresh head | Hosted Studio check | Dependency |
| --- | --- | --- | --- |
| #409 | `82cd22bf39cb770252f5f76aeada0129f9ba85d0` | Passed | Independent building-relative indoor landing |
| #410 | `3963f11fe0e4fd2e0dc3701aa0820e93e5eb3d93` | Failed: atlas provenance | Independent route/timetable change; genuine reference refresh required |
| #411 | `77975053aacc88bed13fbe7c35cde900da2a562a` | Passed | Independent vehicle request gates; not boarding recovery |
| #412 | `5698c28c06f89a6183896cd0122bc30e14cc8a74` | Passed | Independent local camera; not boarding recovery |
| #413 | `1682246159e7dd61df8662cf495559f439cac4d2` | Passed | Independent course data; no race runtime enabled |
| #414 | `670093d129ed2fbbae125eca361c9c9da53b4e7c` | Passed | Random foundation |
| #415 | `3ade21c823f55759f1ddceb38ec5dbcbee1a7f72` | Passed | #414 |
| #416 | `c774144e7e90bc0ef8048033a41ac4e8a371a6d9` | Passed | #414 |
| #417 | `8639725c549fdc13256dccc7e3385b188e4e1714` | Passed | #416 |

The docs-only tracker is PR #418. It records acceptance, not completion of any
fork scope. The first landing sequence is the refreshed tracker, random foundation
#414, then its clock/value/inheritance dependents #415/#416/#417, each restacked
and validated after its parent lands. In parallel with hosted checks, prepare
#409 and #411/#412 for bounded native host/guest validation. Refresh #410's real
atlas witnesses without weakening provenance. Keep #413's data acceptance
separate from the future persistent/networked racing service. The station/terrain
work in fork #7 requires explicit coordination with the terrain owner and must
not absorb their ongoing PR #425.

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

Race TVs are now delivered as source in additional fork #8, not in the original
five heads. Betting-counter/wallet UI, stable buildings/management UI, records hall
and persistent guest ownership remain future work described by the fork. Do not
count those unimplemented features as delivered source.

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
| #7 | Pending independent station/route/terrain/access integration | Pending |
| #8 | Pending #3/#5 and TV presentation integration | Pending |
