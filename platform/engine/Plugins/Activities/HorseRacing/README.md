# Horse Racing rules

`AtelierHorseRacing` contains stateless seeded random draws and a continuous racing calendar.
It has no actors, game names, UI or assets. Genetics, race outcomes and ownership rules
will be integrated separately.

`HRRandom` preserves the reference UTF-16 hash and JSON-string seed/tag keys. Use
`TryDraw` and `TryPickWeighted` when admitting external values: they reject invalid
bounds/weights without changing the output. Supported ranges and total weights are
1–`MAX_int32`, matching the returned integer type. The internal `Draw`/`PickWeighted`
convenience functions require validated arguments and fail explicitly on violation.

The enabled plugin is part of the normal game compile. Native regression
`Atelier.HorseRacing.Random` covers reference parity, string escaping, non-BMP text,
range/weight rejection and call-order independence. Native acceptance is required on
the integration head; enabling the module does not enable a racing service.

`HRClock` supplies the continuous calendar and race slots. Race days last two real
hours; seasons last twelve race days; Grand Prix dates are every third race day.
Horse age advances one year per real week. `TryScheduleAt` admits external times and
counts without mutating output on failure. Slot lookup uses a binary upper bound,
including exact floating-point boundaries. World catch-up and persistence are separate
rules/service responsibilities; the clock itself owns neither a world nor wall time.
