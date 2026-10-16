# Incremental builds

`atelier build` checks source inputs and completed outputs, then runs only the work that is out of date.
Keep generated files and caches between builds. Use the same command after an edit, a merge or a verified
worktree copy; there is no separate fast-build launcher.

## Normal workflow

```sh
uv run atelier build GAME --plan --explain
ATELIER_AGENT=OWNER nice -n 10 uv run atelier build GAME
uv run atelier build GAME --timings
```

The plan explains what would run without starting tools or writing build state. Select a step or prefix
when you need only part of the game, for example `atelier build GAME unreal.compile`. Build and play
request machine capacity themselves; follow the [capacity guide](BUILD_CAPACITY.md) for resources and failures.

A source edit must invalidate every result that consumes it. After a producer runs, unchanged output can
keep downstream consumers current. An ordering requirement alone does not make another step's output an input.
This prevents unrelated world exports and Unreal imports from rerunning while preserving actual dependencies.
A shared input, toolchain change or ownership migration can still require a broad rebuild.

Do not routinely use `--force`, clear caches or touch stamps. `--verify` checks output bytes when damage is
suspected. Missing or damaged output must be rebuilt by its owner; a successful stamp is never a substitute
for the files it certifies. See [the recipe guide](BUILD_RECIPES.md) for declaration and verification rules.

## Reuse a completed build

Each worktree owns its generated Content, Binaries and build state. To start a fresh worktree from a completed
build at the same clean source revision and engine version:

```sh
uv sync
uv run atelier fetch GAME
ATELIER_AGENT=OWNER nice -n 10 uv run atelier reuse GAME --from /path/to/completed-checkout --to "$PWD"
ATELIER_AGENT=OWNER nice -n 10 uv run atelier build GAME
```

Run these commands in the receiving worktree. Reuse verifies source fingerprints, required outputs and engine
identity before copying files independently and publishing successful stamps. It rechecks deferred inputs in
the receiver after copying. It leaves path-dependent Intermediate files behind, so a later C++ compile can
still need work. Never link mutable Content, Binaries or Intermediate between worktrees.

Reuse waits through normal guarded admission. An interrupted copy leaves a journal that blocks use of the
partial build. Follow the command's recovery instructions; `reuse --abandon` removes only its recorded partial
copy. Stamps publish only after successful verification, guard cleanup and capacity close.

## Cache portable products

A recipe can declare named products and opt into automatic verified local caching with `cache=True`.
The build restores a matching product before running its producer. Complete inventories include required
files and optional sidecar absence; restores are independent copies rather than mutable shared directories.

This is distinct from copying a complete native build with `atelier reuse`. Portable caching is for eligible
products with complete inputs and owned outputs. It does not make arbitrary Unreal packages cacheable.
Unreal's shared DDC and Zen retain derived engine data and remain separate from Atelier's product store.
Remote reads require explicit configuration; normal builds do not publish artifacts remotely.

Use [build caches and independent reuse](ARTIFACT_POOL.md) for cache inspection, transfer and retention.
Use [build recipes](BUILD_RECIPES.md) for products, read/reference edges, optional inputs, spatial queries,
access auditing and bounded batches. Features that require explicit recipe declarations are not automatically
enabled for every game action.

## Reduce tool startup without merging results

Compatible recipe actions can share a bounded Blender or Unreal process. Each action keeps its own inputs,
outputs and successful stamp. A later action's failure does not certify it or erase earlier successful work.
Recipes must reset transient state and validate cold versus warm output before opting into batching.

A build that yields with exit 75 has reached a supported boundary. Keep its outputs and rerun the printed
command to continue. In full capacity mode the next invocation waits normally; no coordinator permission is
needed. See [batch execution](BUILD_RECIPES.md#reuse-a-tool-process-without-merging-actions) for limits.

## Read the timings correctly

`--timings` separates recorded command work from restoration and reports unknown values as unknown.
A batch action's timing excludes shared tool startup; whole-step time can include admission and setup.
Cook observations split native build, cook, staging, packaging and archive work. Do not add nested times or
attribute a queue wait to the cooker. `--changes` compares retained product inventories; `--ddc` reads retained
cache observations. Neither report proves a performance improvement on its own.

Current changes narrow rebuild dependencies, reuse verified outputs and avoid repeated tool startup. They do
not establish a single whole-game speedup percentage. Normal cooking defaults remain unchanged. Optional
cook experiments are not part of this workflow or a recommended route to faster production builds.
