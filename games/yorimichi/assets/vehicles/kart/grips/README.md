# Authored kart grips

The grip studio saves one source file per character: `cairo.json`, `modori.json`,
`nox.json` and `paul.json`. Author the left hand; the right is derived anatomically.
Save all hand/finger joints, the mirrored elbow guide and the character's wheel fit.

These are authored source inputs. The kart import validates and stages all four;
it refuses missing files or a profile from a different cockpit revision. Starting
poses in the editor are provisional seeds, not approved grips. Inspect both sides
and steering extremes before accepting a save for the game.

See `games/yorimichi/docs/DRIVING.md` for the editor and native replay workflow.

The initial Cairo profile was authored in the studio. The other three were seeded
from it using anatomical palm/finger directions, their own bone lengths, matching
elbow flexion and a fitted column height. They are starting points for individual
review, rather than evidence that all skin contacts are identical.
