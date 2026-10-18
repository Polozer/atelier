# Selectable soundbank sources

`catalog.json` reserves stable choices for Original, Soft Contact, Dry Street and
Warm Motion. Only complete banks belong in the catalog. The initial catalog
contains Original alone; it delegates to the existing footstep and skate assets
without copying, regenerating or replacing them. The in-game selector is not
implemented by this preparation layer.

`atelier build yorimichi audio.soundbanks` validates committed definitions and
prepares an independently inventoried product under `build/yorimichi/audio/soundbanks`.
It performs no inference and requires no model weights or private cache. Future
Unreal consumers must declare the `audio.soundbanks` product as an actual read.

Each generated entry names `<bank-id>/bank.json` with its SHA-256. That manifest
must provide all seven existing footstep pools, all eight skate surface rolls and
landings, and powerslide friction. Other families explicitly inherit Original,
including horse hoof stand-ins, bikes, combat, ambience/voices and other skate
cues. A source cannot be silently reused for another material or cue.

Each source is `samples/<source-id>.wav`, canonical mono 48 kHz PCM16, with its
actual checksum and generation/processing provenance. Footstep pools contain
4–12 contacts; landing pools 2–4 contacts; each continuous cue has 1–2 loops.
Contacts last 70–1200 ms and loops 0.5–4 seconds. Each bank is limited to 16 MiB.
Provenance retains prompt, seed, model/source/weight identity, sampler settings,
raw checksum, processing-code checksum, source interval and loop crossfade.

Preparation validates all inputs before writing media, uses a writer lock,
publishes immutable media without replacement, rechecks inputs and products,
and publishes its index last. The build product inventories the complete output
directory. Corrupt or incomplete banks fail; they do not silently select Original.
Passing these checks establishes structural readiness, not listening acceptance.

This publication step uses normal incremental fingerprints and complete product
inventories, but deliberately does not opt into portable caching or action input
auditing: those mechanisms clear or replace product roots, conflicting with
preserving a published bank on failure. The source checks remain mandatory.

The first usable runtime slice must include Original plus one alternative, menu
selection and persistence, and verified active-loop switching. Dry Street and
Warm Motion follow that native proof as separate asset changes. Original remains
the fresh/default choice throughout.
