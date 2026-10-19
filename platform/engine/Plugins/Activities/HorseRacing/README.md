# Horse Racing rules

The initial `AtelierHorseRacing` runtime module contains stateless seeded random draws.
It has no actors, game names, UI or assets. Genetics, scheduling, race outcomes and
ownership rules will be integrated separately.

`HRRandom` preserves the reference UTF-16 hash and JSON-string seed/tag keys. Use
`TryDraw` and `TryPickWeighted` when admitting external values: they reject invalid
bounds/weights without changing the output. Supported ranges and total weights are
1–`MAX_int32`, matching the returned integer type. The internal `Draw`/`PickWeighted`
convenience functions require validated arguments and fail explicitly on violation.

The enabled plugin is part of the normal game compile. Native regression
`Atelier.HorseRacing.Random` covers reference parity, string escaping, non-BMP text,
range/weight rejection and call-order independence. Native acceptance is required on
the integration head; enabling the module does not enable a racing service.

`HRHorseTypes` defines reflected horse, gene-pair, injury, appearance and career values.
These are data structures, not validated saves or requests; boundary validation belongs
to persistence and the authoritative rules. Public structures are exported across module
boundaries. Allele and ability sums widen before arithmetic, so malformed values cannot
overflow before boundary validation. A gene-pair index is strictly 0 or 1.
