# Sound preview sequences

The listening page streams short prerecorded AAC/M4A examples through one native
HTML audio player. It downloads no media until a user chooses an example. Repeat
uses the same buffered URL. Raw takes and individual contacts are optional, with
twelve audio controls per library page.

The current prepared candidate pool yields 44 eight-second examples: walk/run on
12 surfaces, plus rolling, powersliding, landing and a combined transition on five
skate surfaces. Each file is limited to 160 KiB, the bank to 10 MiB, and its index
to 64 KiB. AAC is mono 48 kHz at 96 kbit/s in a fast-start MP4 container. The server
supports single byte ranges and immutable caching for versioned media; mutable
indexes and pages are not cached.

`tools/render_sound_sequences.py` uses the prepared PCM candidates, without model
inference. It verifies every source hash and format before rendering, locks out
other bank writers, publishes media without replacement, rechecks inputs, and
publishes the index last. Failed/interrupted builds preserve the previous index
and all the files it references. Output is generated under the review root, not
committed as game assets.

The renderer pins the source identities of `JapanFootsteps.cpp`,
`SkateComponent.cpp` and `SkateRuntime.cpp`; changes require explicit profile
revalidation. Footstep gain/pitch follow the runtime speed mapping and variation.
The examples choose 120/180 steps per minute as an audition approximation: actual
game contacts come from descending foot bones and are not a fixed cadence timer.
Skate examples use speed-driven gain/pitch, the runtime 60 Hz attack/release
interpolation, full-angle powerslides, air/ground transitions and landing gain0.8.
A shared headroom scale preserves relative walk/run and material levels.

Render an existing complete prepared bank through normal admission:

```sh
ATELIER_AGENT=YOUR_OWNER nice -n 10 uv run python -m atelier.harness.safety.guarded \
  --report build/yorimichi/sound-sequences.guard --timeout 600 \
  --purpose "Compact sound review sequences from existing prepared samples" -- \
  .venv/bin/python games/yorimichi/tools/render_sound_sequences.py \
  --root build/yorimichi/stable-audio-review
```

The encoder uses one FFmpeg worker. Each file is decoded again to check duration,
finite nonzero signal and its size budget. Detailed source/event provenance stays
in an unserved dotfile; the small public index contains only review metadata.

Browser acceptance against a populated served bank:

```sh
AUDIO_REVIEW_URL=REVIEW_ORIGIN node platform/web/audio-review/tests/sequences.mjs
AUDIO_REVIEW_URL=REVIEW_ORIGIN AUDIO_REVIEW_BROWSER=webkit \
  node platform/web/audio-review/tests/sequences.mjs
```

The test uses a fresh phone-sized touch page, disallows Web Audio construction,
checks zero initial media requests, all six activities, native decoder readiness,
advancing unmuted playback, buffered repeat without another media request, initial
page size and the optional paginated library. Browser-engine checks do not certify
a physical phone's speaker, silent switch or external audio route. Candidate
selection and installation in the game remain separate work.
