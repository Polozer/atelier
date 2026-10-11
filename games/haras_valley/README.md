# Haras Valley

A game in development in its own Unreal project, which is not in this repository yet: there is no `game.toml` or build
recipe here. The folder holds assets made for it with Atelier's tools, starting with the Garçon in
`assets/characters/boy`, which the game's character creation offers.

When the game moves here, `atelier new` makes the game skeleton from the sandbox; the assets here are then wired into
its `game.toml` and `build.py` the way Yorimichi wires Cairo (`games/yorimichi/game.toml`, `characters.cairo`).
