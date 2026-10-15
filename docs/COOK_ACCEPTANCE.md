# Sandbox native cook acceptance preparation

This prepares the opt-in [modern cook experiment](COOK_EXPERIMENT.md). **Native acceptance is unrun.**
Nothing enables incremental cooking by default or claims a speedup. The evidence helper launches no
native process, takes no lock, changes no stamp and always leaves `native_parity: false`.

## Admission and fixtures

Use a separate reviewed current-main checkout and the same installed engine for every sample. Preserve
the earlier private fixture checkout's three dirty files. The private fixture bundle retains their exact
blobs/hashes, reversible baseline/case patches, asset-edit scripts and expected runtime JSON. Its generated
native code has not been compiled or run. Review it before applying it to the disposable acceptance checkout;
never apply it to a live game checkout or frozen capacity release. Normal sandbox sources remain unchanged.

Native work waits for the owner's complete build/smoke/upload handoff, approved engine repair, full capacity
cutover and its controlled native trial. Check Holding, Waiting, latest Log, actual broker mode, charged or
uncertain jobs and supervisor telemetry at each child boundary. Follow the current [agent workflow](BUILD_CAPACITY.md#agent-workflow).
Only after the operator announces full mode use its installed default client. Never edit profiles, bypass
refusals, remove locks, lower reserves or hold a reservation while waiting.

Name the owner, checkout, row, expected duration and next boundary in each request. No native duration has
been measured. Package commands retain their existing **four-hour guard deadline and three UBT workers**;
editor/import prerequisites retain their existing deadlines. Set a **10-minute first progress review** and
inspect logs/guards immediately if progress stops; report a revised ETA or cancel only the owned caller
through normal cleanup. Do not invent a shorter build timeout unsupported by the CLI. Scripts below have
900-second, listing/registry jobs300-second, and packaged loads60-second guard deadlines. The private fixture
requests a normal exit five seconds after BeginPlay. Crash, timeout, guard refusal or incomplete cleanup fails.

## One cook sample at a time

Variables below name reviewed disposable source and new private evidence locations, not installed paths:

```sh
FIXTURES=/path/to/reviewed/cook-fixture-bundle
EVIDENCE=/path/to/new/cook-evidence
mkdir -p "$EVIDENCE"
git apply --check "$FIXTURES/00-baseline.patch"
git apply "$FIXTURES/00-baseline.patch"
uv sync
uv run atelier build sandbox unreal.cook --cook-mode modern-full --plan --explain
```

The baseline creates `CookProbe=4` once and **never resaves it**, even when a header rebuild reruns level
generation. Separate `GeneratorProbe` consumes declared `block.shape`; initially unreferenced `MutableProbe=7`
has no saved hard reference. `NeverCreated` must remain missing. Tagged mesh transforms and explicit runtime
markers report loaded/missing probes, native type/value, map, referenced config and GI/reflection CVars.

Choose a fresh label/directory for each row; record the tracked source patch before launching:

```sh
LABEL=full-0
MODE=modern-full
PRE="$EVIDENCE/pre-$LABEL"
mkdir "$PRE"
uv run python games/sandbox/tools/cook_acceptance.py record "$PWD" "$PRE/source-record.json"
nice -n 10 uv run atelier build sandbox unreal.cook --cook-mode "$MODE" \
  --force --cook-reason "$LABEL" --max-heavy-commands 1
```

Exit75 means a child boundary: recheck Waiting and resume that exact command from real stamps. It does not
mean the cook finished. Retain only after exit0 and a fresh observation whose `reason` equals the row label.
Before the next invocation can replace the archive/logs:

```sh
uv run atelier build sandbox unreal.cook --timings --json > "$PRE/timings.json"
uv run atelier build sandbox unreal.cook --ddc --json > "$PRE/ddc.json"
nice -n 10 uv run python games/sandbox/tools/cook_acceptance.py retain build/sandbox "$EVIDENCE/$LABEL" \
  --source "$PWD" --source-record "$PRE/source-record.json" --label "$LABEL" \
  --extra "$PRE/timings.json" --extra "$PRE/ddc.json"
```

Also retain initial editor/import logs and successful receipts; UAT's first game-target compilation is not
cooker runtime. The helper checks receipt/observed raw-log hash, pre-run source record, native execution stamp,
and source/copied app inventories before writing `evidence.json` last. Destinations cannot be reused. Copies
are independent and retain the `.app` name; never seed Content, Saved, Intermediate, Zen or stamps from them.
Keep enough disk headroom for baseline/candidate copies without deleting evidence or lowering reserves.

After the baseline first creates the probe, record its SHA-256:

```sh
PROBE=games/sandbox/unreal/Content/Sandbox/CookProbe.uasset
shasum -a 256 "$PROBE" > "$EVIDENCE/frozen-probe.SHA256"
```

Set `FROZEN_SHA` to that digest. For serialization rows use `cook_acceptance.py frozen "$PROBE" "$FROZEN_SHA"`
before/after each compile, level import and cook; add `--frozen-asset "$PROBE" --frozen-sha "$FROZEN_SHA"` to
`retain`. Changed bytes invalidate the row. Never resave it, update the expected digest, touch stamps or disable
executable/header invalidation to make the row pass.

## Controls and mutations

Run `full-0`, then `prime-0` with `modern-incremental`, followed by unchanged `warm-1` and `warm-2` with
`modern-incremental`. A settings-wide full invalidation during prime is legitimate and remains labeled full.
Warm controls need an actual supported incremental decision, not just an incremental request.

For every changed case retain its incremental app, then make a new `modern-full` cook of **the exact same
changed inputs** under a distinct label (`delete-inc`, `delete-full`, for example). Require the full control's
observed `explicit-full` decision. Preserve Saved/Zen/caches; explicit full recooking supplies this control.
Fresh empty-state/corrupt-state behavior is a separate still-unrun acceptance gate, not permission to delete
machine-wide caches. Compare both retained apps, never a previous archive already replaced by the next cook.

| Case | Intentional operation from baseline | Required outcome in incremental and full |
| --- | --- | --- |
| Local asset | Guarded `local-asset.py` | MutableProbe float9; other probes/map/config unchanged |
| Generator input | Apply `generator.patch` | Block input400→500; GeneratorProbe5, Block scale5,4,2; frozen CookProbe4 |
| Referenced config/renderer | Apply `config.patch` | Config `config-edit`, GI0/reflection0; baseline is `baseline`, GI1/reflection1 |
| Header serialization | Apply `serialization.patch` | Actual UBT rebuild, property double, unchanged saved CookProbe bytes and value4 |
| Logical rename | Guarded `rename.py` duplicates then deletes the old source package, without redirector | MutableProbe missing, RenamedProbe float7; old registry/container entry absent |
| Deletion | Guarded `delete.py` | MutableProbe missing in load, shipped registry and container; NeverCreated still missing |

Apply/reverse only the named patch with `git apply --check` / `git apply -R`. Guarded `restore.py` restores
MutableProbe7 and removes RenamedProbe, without touching CookProbe. Verify baseline again before another
independent case. The rename case covers removal/new identity, not UE redirector migration semantics.

Use the editor/project chosen by normal discovery. Exact guarded authoring shape (change script per row):

```sh
UNREAL_CMD="$(uv run python -c 'from atelier import engine; print(engine.unreal_cmd())')"
PROJECT="$PWD/games/sandbox/unreal/Sandbox.uproject"
nice -n 10 uv run python -m atelier.safety.guarded --kind compile --timeout 900 \
  --report "$PRE/asset-edit.guard" --purpose "cook acceptance asset edit" -- \
  "$UNREAL_CMD" "$PROJECT" -run=pythonscript "-script=$FIXTURES/local-asset.py" \
  -unattended -nop4 -nosplash -stdout -AllowStdOutLogVerbosity -NullRHI
```

Require exit0 and `COOK ACCEPTANCE EDIT COMPLETE`; every edit gets a new report directory and normal exclusive
guarded admission. This never skips importer/cook prerequisites or changes their worker/guard settings.

## Packaged loads and semantic inventories

Request a separate owned game turn for each retained app:

```sh
APP="$EVIDENCE/$LABEL/app/Sandbox.app"
nice -n 10 uv run python -m atelier.safety.guarded --kind game --timeout 60 \
  --report "$EVIDENCE/load-$LABEL.guard" --purpose "cook acceptance packaged load" -- \
  "$APP/Contents/MacOS/Sandbox" -CookAcceptance -windowed -ResX=1600 -ResY=900 \
  -unattended -stdout -FullStdOutLogOutput
uv run python games/sandbox/tools/cook_acceptance.py runtime \
  "$EVIDENCE/load-$LABEL.guard/stdout.log" "$FIXTURES/baseline.expected.json"
```

Use that case's expected JSON. Require clean owned exit, normal guards, explicit map/assets/type/config/renderer
and transform matches, plus frame/log evidence. Missing observations fail. No NullRHI or forced renderer CVars
for packaged-load/renderer proof. The fixture's native compilation and first actual load remain acceptance work.

Inspect the retained app's actual IoStore inventory in a separate admitted command:

```sh
nice -n 10 uv run python -m atelier.safety.guarded --kind compile --timeout 300 \
  --report "$EVIDENCE/list-$LABEL.guard" --purpose "cook acceptance container inventory" -- \
  "$UNREAL_CMD" "$PROJECT" -run=IoStore "-List=$APP/Contents/UE/Sandbox/Content/Paks/*.utoc" \
  "-CSV=$EVIDENCE/$LABEL.containers.csv" -unattended -NullRHI
```

Installed UE5.8 `IoStoreCommandlet::Main` delegates to `CreateIoStoreContainerFiles`; its `-List=... -CSV=...`
emits PackageName/Filename/ChunkType/Hash/Size and physical layout fields. Require nonempty readable coverage and
all expected probe/map packages. Compare normalized package identities and unexplained content differences;
offset/order/compression/archive hashes alone cannot establish semantic parity. Missing package names block proof.

Use the **shipped** AssetRegistry.bin, not the editor's live registry. If packed, run installed
`UnrealPak PAK -Extract NEW_DIRECTORY -Filter=*AssetRegistry.bin` through the normal compile guard with a
300-second timeout. Then guarded editor `-run=DumpAssetRegistry -Path=FILE -OutDir=NEW_DIRECTORY -All
-unattended -NullRHI` (300 seconds) dumps it. These argument shapes were checked in installed UE5.8 source,
but remain unrun here. Require nonempty package/object/class/tag/dependency output. Old MutableProbe must be
absent after rename/delete in both shipped registry and IoStore inventory, with matching explicit load outcomes.
A quiet failed load alone cannot prove registry cleanup.

## Decision and handoff

Record admission+guard setup, gated child lifetime, actual execution, editor/game UBT action counts and build
time, cooker-session time, UAT cook/stage/package/archive/total, evidence/inventory-copy time and total wall time
separately. Unknown execution time remains unknown. Stage includes pak/IoStore subprocesses: never add nested
metrics twice. Historical DDC observations can be partial, backend counters overlap, and missing totals stay null.

Every mutation needs matching intended semantics and native loads in incremental/full results. Skips and hashes
alone do not pass acceptance. Missing/corrupt previous state and independent native review remain open gates.
Repeated warm native and end-to-end observations must demonstrate improvement before any proposal to change
defaults. Until then retain `native_parity: false`, publish evidence, finish owned cleanup, release capacity and
make a named handoff with the next row, readiness condition and ETA.
