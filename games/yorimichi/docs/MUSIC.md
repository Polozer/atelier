# Music library

Yorimichi's music is generated with Suno v6 (`chirp-hawk`) and kept outside the
repository as a tagged library release. The game can use a small selection, all
of it, or none of it. The game's soundtrack director (`UJapanMusic`, see
[Runtime](#runtime)) plays it from outside the package; the library's job is to
provide enough distinct, correctly tagged material to choose from.

The library has three parts:

| Part | Cues | Tracks | Purpose |
| --- | ---: | ---: | --- |
| Zone score | 28 zones | 168 | day, quiet and contrast takes for every zone |
| Action and set pieces | 12 | 24 | combat, pursuit, boss, storms, rituals, victory and defeat |
| Style library | 28 | 56 | lofi hip hop, percussion-heavy action, ambient, jazz and world |

Each generation returns two takes. All tracks are instrumental: no lyrics,
vocals or choir. The request asks for a 480-second arrangement, but Suno returns
different lengths, usually between three and eight minutes. That variation is
useful: the runtime can enter a track at a phrase boundary and leave it when the
scene changes instead of forcing every cue to the same clock.

## Tags

Every track is tagged in three places: its group manifest under
`build/yorimichi/music/`, the release's `catalog.json`, and the MP3 ID3 fields.
The important selectors are:

- `category`: `calm`, `moderate`, `energetic`, `action` or `contrast`.
- `style_family`: `orchestral`, `ambient`, `lofi`, `energy`, `jazz` or `world`.
- `energy`: 1 (quiet) through 5 (intense).
- `intent`: `exploration`, `ambient`, `contrast`, `combat`, `action`,
  `environment`, `set_piece`, `reward`, `story`, `calm` or `celebration`.
- `mood`, `use`, `bpm_target` and `loop`: describe the moment a cue fits.
- `zone`, `zone_name`, `role`, `group` and `clip_id`: provenance.

The `zone` tracks are deliberately similar within a zone so a quiet take can
crossfade into a day take. The action and style libraries are deliberately
different: use `category` and `style_family` to keep a lofi exploration cue out
of a boss fight.

## Generate

The credential flow and endpoint details are in
[`docs/SUNO_API.md`](../../../docs/SUNO_API.md). The ignored repository-root
`.env` holds `SUNO_CLIENT_COOKIE` and `SUNO_CLIENT_UAT`; the client rotates them
after every refresh. Never print or commit either value.

The three batch runners are resumable and write one manifest after each cue:

```sh
python3 games/yorimichi/tools/generate_music.py            # zones
python3 games/yorimichi/tools/generate_action.py           # action library
python3 games/yorimichi/tools/generate_variety.py          # style library
```

Each paid submission gets an exclusive record under `~/.cache/suno/ledger/` before the request is sent. A recorded
prompt is never submitted again automatically; an uncertain response stays recorded. Only the free Turnstile step is
retried. To deliberately pay for a new take of the same prompt, set the old ledger record aside with
`atelier.ai.ledger.set_aside`.

Add `--zone KEY --role quiet`, or `--cue KEY`, to regenerate one item. Outputs
go to the ignored `build/yorimichi/music/`:

| File | Contents |
| --- | --- |
| `<zone>/manifest.json` | zone identity, prompts, takes, durations and file paths |
| `library/<cue>/manifest.json` | action cue and its provenance |
| `variety/<cue>/manifest.json` | style cue and its selector metadata |
| `index.json` | the review page's combined index |
| `reviews.json` | ratings and notes from the review page |

Generation costs 5 credits per track. A normal request returns two takes, so a
cue costs 10 credits. The player-license decrypt path does not spend the
account's separate download credits.

## Review

Serve the page only on the Tailscale address, so it is not exposed on the LAN:

```sh
python3 games/yorimichi/tools/music_review_server.py --bind <tailscale-ip> --port 8099
```

Open `http://<tailscale-ip>:8099/`. The page has separate zone, action and style
sections, plays the MP3 review copies with seeking, and saves Good / Maybe / No
plus a note for every clip. It polls `index.json`, so newly generated cues
appear without restarting the server. The server supports HTTP range requests,
which is what lets the browser scrub multi-minute tracks.

## Download and release

The MP3 review set is large enough that it stays out of git. The repository keeps
the plans, the generators, the fetch tool and a checksum lock. Build the release
archive and lock with:

```sh
python3 games/yorimichi/assets/audio/music/tag.py
python3 games/yorimichi/assets/audio/music/bundle.py --url \
  https://github.com/<owner>/<repo>/releases/download/yorimichi-music-v1/yorimichi-music-v1.zip
```

`tag.py` writes ID3 title, artist, album, genre and custom `YORIMICHI_*` fields
without re-encoding the audio. `bundle.py` includes the MP3s, manifests,
`catalog.json` and a short `README.md`; it leaves the large decrypted `.m4a`
masters out by default. Pass `--include-masters` only when a local archive needs
them. The lock records the bundle URL, zip SHA-256 and every file's size and
hash.

Fetch and verify the published bundle into the Atelier cache:

```sh
python3 games/yorimichi/assets/audio/music/fetch.py
```

Use `--bundle PATH` for a local zip. A fresh clone can verify exactly which
bytes belong to the soundtrack without carrying the audio in git. The release
may contain far more tracks than the shipped game uses; the tags are the
selection contract.

## Optional game build

The default build does not download or import music. Name the music steps only
when the build should bake in a selection:

```sh
YORIMICHI_MUSIC_CATEGORIES=calm,moderate \
YORIMICHI_MUSIC_STYLES=lofi,ambient \
uv run atelier build yorimichi unreal.music
```

`audio.music` writes the selected list to
`build/yorimichi/audio/music/manifest.json`; `unreal.music` imports those files
as `/Game/Audio/Music/<section>/<group>/` and stages the tagged asset list at
`/Game/Data/Music/library.json`. Selectors are comma-separated and can
be combined with `YORIMICHI_MUSIC_GROUPS` and `YORIMICHI_MUSIC_LIMIT`. A build
without the music steps remains valid and contains no music assets.
Each import is an exact inventory: waves under `/Game/Audio/Music` that the new
selection does not own are deleted, while other Audio folders stay untouched.

Set `YORIMICHI_MUSIC=1` when importing the whole library with no selectors. The
same flag (or any selector) also tells `data.content` to keep the optional
`Audio/Music` and `Data/Music` assets during packaging; without it, a normal
build archives stale music before cooking.

The runtime should not play a track continuously just because one exists. Start
music on arrival or after a landmark, leave silence and ambience between cues,
and crossfade on a phrase boundary over several seconds. Calm and lofi cues fit
exploration, interiors, menus and safe travel; energy 4-5 and `action` cues fit
fights, chases and set pieces. Avoid changing tracks during dialogue, a cutscene
or an interaction prompt, and fade out before a hard scene transition. The long
takes exist to make those choices possible, not to loop as short stingers.

## Runtime

Playtest releases do not contain the music. `atelier playtest yorimichi` runs
`fetch.py --quick` before launch: a cache this lock already verified is trusted
when every file has its locked size, otherwise the bundle is downloaded and
verified once. The cache is then cloned (APFS copy-on-write, no extra disk) into
the app's sandbox container at
`Library/Application Support/Yorimichi/Music`, because the sandboxed app cannot
read `~/.cache`. A clone whose `manifest.json` matches the cache is reused. The
launcher passes `-music=<that folder>`. Development play reads
`~/.cache/atelier/yorimichi/music` directly. With no library, a failed fetch or
`-nomusic`, the game runs exactly as before, silently.

`UJapanMusic` (`Source/Yorimichi/JapanMusic.cpp`) is a client-only world
subsystem. It reads `catalog.json` and plays MP3s through two media players. It
replicates nothing and nothing waits on it.

**Which music.** Twice a second it reads the local player's scene, then picks a
pool for that scene and area:

| Scene | Pool |
| --- | --- |
| An engaged Ronin within 30 m | `combat`: skirmish, ambush, duel, taiko (no boss or siege cues) |
| Skating in Crater Park | `skate_crater`: breakbeat, drum and bass, festival, race, Crater Park's own takes |
| Skating on Sunset Pier | `skate_pier`: harbour and salon jazz, seaside, coffee and rooftop lofi |
| Skating elsewhere | `skate`: rooftop, market, train and dojo lofi, festival |
| Hidamari town | `town`: market, coffee, study and rooftop lofi, plus the zone's takes |
| Coast, harbour, cove, fishing village | `coast`: seaside and lighthouse lofi, harbour jazz |
| Brinecove's quay | `brinecove`: harbour jazz, lighthouse and seaside lofi |
| Belmonte, the Salon | `belmonte` and `salon`: salon and harbour jazz |
| Forest, temple, foothills, open country | `nature` and `wild`: dawn and high ambient, study and dojo lofi |
| Aboard the Belmonte train, seated or standing | `train`: exactly four clips (by `clip_id`): Rain on the Line (B), Harbor Lounge (A), Salon Jazz (A) and Coffee Shop (B) |
| Sailing, zeppelin, bike or horse | `sail`, `air` and `ride` |

The area comes from the nearest map zone within its radius. Calm exploring pools
also take that zone's own day and quiet takes, so a place keeps its theme among
the style cues. Only Crater Park skating uses the loud contrast takes.

**Variety with coherence.** The last ten tracks are never picked again. A track
in the style family already playing is twice as likely, and the zone's own score
1.5 times. When the scene changes, a track that also belongs to the new pool keeps
playing.

**When.** Music is not continuous:
- The first cue comes about 8 s after arrival.
- An exploring cue plays 2.5–4 minutes, or the whole track if it is shorter. It
  then fades out over 10 s and leaves 70–160 s of silence. Skating rests 30–60 s.
- Arriving somewhere new after at least 25 s of silence brings the next cue in
  after 6 s.
- A new scene must hold for 4 s first (1 s for a fight), so the music doesn't
  flap at a zone's edge.
- Nothing changes during a cinematic. Fades keep running under the pause menu.
- A pool with no tracks in the installed library (a partial library without fight cues) is never entered: the
  music keeps following the calm scene.

**Mixing.** Every start and stop is an equal-power fade:
- A change of scene crossfades over 8 s.
- A fight crossfades in over 2–2.5 s. It holds 6 s after the last enemy lets go,
  then fades out over 5 s and leaves 15–30 s of silence before calm music returns.
- The music sits under the sound effects: a base level of 0.42, times the pool's
  level (0.9 calm, 1.0 skating, 1.1 combat and Crater Park), times the player's
  **Music volume** (default 0.6).

**Options.** The menu has **Music** (on/off; off fades out within 2.5 s) and
**Music volume**, both saved with the other settings. The console command
`japan.MusicStatus` logs the pool, zone, track and remaining rest. Every start
logs a `MUSIC play` line.

