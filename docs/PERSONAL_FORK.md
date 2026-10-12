# Personal Atelier fork

`Polozer/atelier` is the canonical Atelier repository for the owner's projects. `fontanierh/atelier` remains upstream and the brother's repository.

- `origin`: https://github.com/Polozer/atelier.git
- `upstream`: https://github.com/fontanierh/atelier.git
- Base: upstream `main`, `bf971ebe69200928b2426d7987186211f50b3140`, checked on 12 October 2026.

The owner's canonical local checkout is `AI/atelier-main`. The machine-local selector at `$HOME/.config/atelier/current` points to it, and `$HOME/.local/bin/atelier` launches its installed studio command from any project. An explicit `ATELIER` override takes precedence. Each game keeps its own source assets and generated outputs.

The older `AI/atelier` checkout retains sixteen local commits, including Haras Valley character work and an external-project LiveBridge setting. Preserve that history. Moving the default tools does not migrate those changes or replace the source-only plugins bundled with HarasValley. Their existing dependency manifest remains a historical provenance record.

To update this fork, fetch upstream and review its changes before merging them into the fork. Push owner work to `origin`; do not change the brother's default repository. Existing build and memory safeguards still apply.

The first shared design brief is [the Belmonte train prompt](../games/yorimichi/docs/BELMONTE_TRAIN_PROMPT.md). Images and assets are deferred until requested.
