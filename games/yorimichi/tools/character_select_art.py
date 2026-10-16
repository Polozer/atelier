#!/usr/bin/env python3
"""Character selection UI concept and playable character profile pictures on Sunburst.

    uv run python games/yorimichi/tools/character_select_art.py [--only slug,slug] [--dry-run]

Paints the Sunburst UI reference for Yorimichi's startup character selection screen
(games/yorimichi/assets/characters/concepts/character-select.jpg) and matching bust profile
pictures for every playable character (games/yorimichi/assets/characters/portraits/<id>.png),
each recorded through atelier.ai.ledger with gpt-image-2.5-sunburst at quality=high.
"""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402
_sys.path.insert(0, str(_Path(__file__).resolve().parent))

import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import shutil
import sys
import time
from pathlib import Path
from PIL import Image

from atelier.ai.ledger import run_once
from treehouse_art import MODEL, QUALITY, compact, redact, rel, sha, sheet, sunburst

CHARS = yori.ASSETS / 'characters'
CONCEPTS = CHARS / 'concepts'
CONCEPT_ORIGINALS = yori.OUT / 'characters' / 'concepts' / 'originals'
PORTRAIT_ORIGINALS = yori.OUT / 'characters' / 'portraits' / 'originals'
PORTRAIT_REFS = yori.OUT / 'characters' / 'portraits' / 'refs'
REVIEW = yori.REVIEW / 'characters'
PORTRAIT_SIZE = (440, 520)

UI_PROMPT = """Production 16:9 UI design reference sheet (2560x1440 layout proportion) for the startup Character Selection Screen of Yorimichi, a stylised 3D Japanese coastal island exploration game in Unreal Engine. Use the attached character references for the four playable characters and the island overview for the world atmosphere.

BACKDROP & FRAME: Behind the UI, show a softly dimmed golden-hour view of Yorimichi's coastal road, autumn ginkgo trees and distant sea under a deep forest-green glass vignette (#0b1713 at 75% opacity). Centred on screen is an architectural dark forest-slate and warm cedar selection board (#0f221b surface, #163026 card wells) framed with thin brushed-brass hairline rules (#c9a05a) and subtle bevelled corners.

HEADER: Top eyebrow in tracked warm brass capitals: "YORIMICHI". Below it, a clean display title in warm cream (#fff6e5): "Choose Your Wanderer".

FOUR PLAYABLE CHARACTER CARDS (equal-width vertical cards side by side in a 4-column row, with VERY SHORT text):
1. CAIRO (left card, highlighted as selected with a warm mustard-gold #e2b44c border glow and top badge "DEFAULT"): bust portrait of Cairo (boy with dark-chocolate sculpted hair, dark vertical pill eyes, warm peach skin, mustard-yellow tee over white long sleeves). Plaque text: name "Cairo", short line "Knows every shortcut.", bottom brass button "Selected  ·  Play".
2. MODORI (second card, frost-blue #8fb8d8 accent and badge "RIVAL"): bust portrait of Modori (Image 1: dark sculpted hair with one thin frost-white streak over one eye, half-lidded pill eyes, charcoal coat-haori with braided rope and bell weight). Plaque text: name "Modori", short line "Came back from the woods.", bottom button "Select".
3. NOX (third card, violet-silver #9b7fd4 accent and badge "NIGHT RIDER"): bust portrait of Nox (Images 2 & 3: warm brown skin, black-charcoal shoulder-length locs, heavy-lidded eyes, temple star mark, black leather bomber over dark hoodie and silver chain). Plaque text: name "Nox", short line "Up all night.", bottom button "Select".
4. PAUL (right card, moss-emerald #6eb37e accent and badge "CHALLENGER"): bust portrait of Paul (Image 4: tousled dark-brown hair, golden-hazel eyes, warm sunlit skin, moss-green crew-neck tee). Plaque text: name "Paul", short line "New in town.", bottom button "Select".

FOOTER BAR: Bottom control legend bar in warm brass and cream: "Left / Right or Mouse: Choose   ·   Enter / Space / A: Play   ·   1–4: Quick Pick". Keep card text ultra-short (only the name and 3-5 word line, no outfit descriptions). Clean editorial game UI design with cohesive painted 3D character portraits."""

PORTRAITS = {
    'cairo': {
        'refs': [
            CHARS / 'concepts' / 'modori.jpg',
            CHARS / 'wanderer' / 'references' / 'design-sheet.png',
        ],
        'prompt': (
            'Chest-up front three-quarter bust profile portrait of CAIRO, the default playable character of '
            'Yorimichi, for the game\'s character selection screen. Match the softly sculpted matte 3D '
            'game-character finish and lighting craft of Image 1 and the dark vertical pill-eye face language of '
            'Image 2. Cairo is a lively 148 cm boy with an oversized head, dark-chocolate hair in bold sculpted '
            'clumps with a small upward tuft at the crown, warm peach skin, dark vertical pill eyes without whites '
            'or irises, a small nose, and a warm confident slight smile. He wears his signature huge boxy '
            'mustard-yellow short-sleeve crew-neck T-shirt over a crisp white long-sleeve undershirt, with his '
            'shoulders and arms hanging naturally at his sides in a relaxed standing pose (never a T-pose). '
            'Background: a rich, softly painted warm golden-hour coastal sky and sunlit autumn ginkgo/pine bokeh '
            'gradient (#1c3329 deep forest-slate at the bottom rising to warm amber-gold #d8b46a rim light behind '
            'his shoulders). Centred bust framing with comfortable headroom above the hair tuft. No text, no labels, '
            'no UI borders, no watermark.'
        ),
    },
    'modori': {
        'refs': [
            CHARS / 'concepts' / 'modori.jpg',
            CHARS / 'concepts' / 'modori-tpose' / 'front.jpg',
        ],
        'prompt': (
            'Chest-up front three-quarter bust profile portrait of MODORI, the playable rival of Yorimichi, for the '
            'game\'s character selection screen. Preserve the exact character identity, face, hair and outfit from '
            'Images 1 and 2: lean 18-year-old young man, softly sculpted matte 3D game-character finish, near-black '
            'hair in large sculpted clumps with a long side-swept fringe covering one eye and one thin frost-white '
            'streak running through the front fringe. Half-lidded dark pill eyes with a calm, knowing, nonchalant '
            'expression and a faint lopsided almost-smile. He wears his tall stiff-collared charcoal coat-haori '
            'over a dark high-necked shirt, with the thick braided brown rope and dull-gold bell-metal weight '
            'coiled over his shoulder, arms relaxed naturally at his sides (not a T-pose). Background: a softly '
            'painted cool misted cedar-and-slate mountain twilight bokeh gradient (#13242b to pale icy-blue #8fb8d8 '
            'rim light). Centred bust framing with comfortable headroom. No text, no labels, no UI borders.'
        ),
    },
    'nox': {
        'refs': [
            CHARS / 'nox' / 'references' / 'head' / 'front.png',
            CHARS / 'nox' / 'references' / 'body' / 'front.png',
            CHARS / 'nox' / 'references' / 'chain.png',
        ],
        'prompt': (
            'Chest-up front three-quarter bust profile portrait of NOX, playable character in Yorimichi, for the '
            'game\'s character selection screen. Combine his exact head from Image 1, his jacket and hoodie from '
            'Image 2, and his silver chain from Image 3 in the same smooth painted stylised 3D-game finish. Adult '
            'man in his mid-twenties with warm brown skin, broad nose, full closed lips with a neat thin moustache '
            'and chin goatee, heavy-lidded almond eyes with a cool self-possessed gaze, a small dark four-point star '
            'tattoo at his anatomical left temple (screen right) and two short dark ticks beneath his left eye, and '
            'one square silver stud on his left ear. Shoulder-length black-charcoal sculpted locs with two longer '
            'front locks falling naturally over his right brow. He wears his black leather bomber jacket open over a '
            'dark charcoal hoodie with the muted violet jagged chest motif and the silver chain at his collar, with '
            'shoulders and arms relaxed naturally down at his sides (no T-pose). Background: a softly painted '
            'late-night harbor indigo and muted violet-amber bokeh gradient (#161828 to #7c68a8 rim light). Centred '
            'bust framing with comfortable headroom. No text, no labels, no UI borders.'
        ),
    },
    'paul': {
        'refs': [
            CHARS / 'paul' / 'portrait.png',
            CHARS / 'paul' / 'references' / 'body' / 'front.png',
        ],
        'prompt': (
            'Chest-up front three-quarter bust profile portrait of PAUL, playable character in Yorimichi, for the '
            'game\'s character selection screen. Preserve the exact boy from the attached references: stylised '
            'painted 3D game-character finish, tousled dark-brown hair in clean layered clumps, thick dark eyebrows, '
            'expressive golden-hazel eyes with warm catchlights, warm sunlit peach-tan skin, and a calm, ready '
            'expression. He wears his moss-green crew-neck T-shirt with his shoulders and arms hanging naturally '
            'down at his sides in a relaxed portrait stance (replace the outstretched T-pose arms with a natural '
            'relaxed bust pose). Background: a softly painted sunlit coastal meadow and emerald pine bokeh gradient '
            '(#182e22 to warm sunlit sage #78b084 rim light). Centred bust framing with comfortable headroom. No '
            'text, no labels, no UI borders.'
        ),
    },
}


def save_portrait_png(png_bytes, dest):
    """Crop and downsample a 1024x1024 square bust painting to the 440x520 portrait frame (11:13)."""
    im = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
    w, h = im.size
    target_ratio = PORTRAIT_SIZE[0] / PORTRAIT_SIZE[1]
    crop_w = min(w, round(h * target_ratio))
    left = (w - crop_w) // 2
    im = im.crop((left, 0, left + crop_w, h)).resize(PORTRAIT_SIZE, Image.LANCZOS)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, 'PNG', optimize=True)
    raw = dest.read_bytes()
    return dict(file=dest.name, size=f'{PORTRAIT_SIZE[0]}x{PORTRAIT_SIZE[1]}', bytes=len(raw), sha256=sha(raw))


def run_ui_concept():
    refs = [
        CHARS / 'concepts' / 'modori.jpg',
        CHARS / 'nox' / 'references' / 'head' / 'front.png',
        CHARS / 'nox' / 'references' / 'body' / 'front.png',
        CHARS / 'paul' / 'portrait.png',
        CHARS / 'wanderer' / 'references' / 'design-sheet.png',
        yori.ASSETS / 'treehouse' / 'concepts' / 'overview-day.jpg',
    ]
    prompt_path = CONCEPTS / 'character-select.prompt.txt'
    prov_path = CONCEPTS / 'character-select.provenance.json'
    jpg_path = CONCEPTS / 'character-select.jpg'
    prompt_path.write_text(UI_PROMPT + '\n')
    metadata = dict(
        stage='ui-concept',
        concept='character-select',
        requested_model=MODEL,
        quality=QUALITY,
        size='1536x1024',
        endpoint='/v1/images/edits',
        execution='games/yorimichi/tools/character_select_art.py',
        prompt_file=prompt_path.name,
        prompt_sha256=sha(UI_PROMPT.encode()),
        reference_files={rel(p): sha(p.read_bytes()) for p in refs},
    )

    def paint():
        t = time.time()
        png, usage = sunburst(UI_PROMPT, '1536x1024', refs)
        CONCEPT_ORIGINALS.mkdir(parents=True, exist_ok=True)
        (CONCEPT_ORIGINALS / 'character-select.png').write_bytes(png)
        comp = compact(png, jpg_path, 'concepts')
        comp['sha256'] = sha(jpg_path.read_bytes())
        return dict(
            usage=usage,
            outputs={'character-select.png': sha(png)},
            compact_copy=comp,
            elapsed_seconds=round(time.time() - t, 1),
        )

    return run_once(prov_path, metadata, paint)


def run_portrait(cid):
    spec = PORTRAITS[cid]
    refs = list(spec['refs'])
    prompt = spec['prompt']
    portraits_dir = CHARS / 'portraits'
    portraits_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = portraits_dir / f'{cid}.prompt.txt'
    prov_path = portraits_dir / f'{cid}.provenance.json'
    out_path = portraits_dir / f'{cid}.png'
    prompt_path.write_text(prompt + '\n')
    metadata = dict(
        stage='character-portrait',
        character=cid,
        requested_model=MODEL,
        quality=QUALITY,
        size='1024x1024',
        endpoint='/v1/images/edits',
        execution='games/yorimichi/tools/character_select_art.py',
        prompt_file=prompt_path.name,
        prompt_sha256=sha(prompt.encode()),
        reference_files={rel(p): sha(p.read_bytes()) for p in refs},
    )

    def paint():
        t = time.time()
        png, usage = sunburst(prompt, '1024x1024', refs)
        PORTRAIT_ORIGINALS.mkdir(parents=True, exist_ok=True)
        (PORTRAIT_ORIGINALS / f'{cid}.png').write_bytes(png)
        portrait_info = save_portrait_png(png, out_path)
        return dict(
            usage=usage,
            outputs={f'{cid}.png': sha(png)},
            portrait=portrait_info,
            elapsed_seconds=round(time.time() - t, 1),
        )

    return run_once(prov_path, metadata, paint)


def main():
    all_targets = ['character-select', *PORTRAITS.keys()]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--only', default='', help='comma-separated targets: ' + ', '.join(all_targets))
    ap.add_argument('--dry-run', action='store_true', help='print prompts and stop')
    args = ap.parse_args()
    wanted = [t for t in all_targets if not args.only or t in args.only.split(',')]
    if args.dry_run:
        for t in wanted:
            p = UI_PROMPT if t == 'character-select' else PORTRAITS[t]['prompt']
            print(f'--- {t}\n{p}\n')
        return

    todo = []
    for t in wanted:
        prov = (CONCEPTS / 'character-select.provenance.json') if t == 'character-select' else (CHARS / 'portraits' / f'{t}.provenance.json')
        if not prov.exists():
            todo.append(t)
    if todo:
        from atelier.env import require
        require('OPENAI_API_KEY')
    print(f'painting {len(todo)} Sunburst target(s) in parallel: {", ".join(todo) or "none"}', flush=True)
    failed = []

    def one(target):
        start = time.time()
        try:
            record = run_ui_concept() if target == 'character-select' else run_portrait(target)
            print(f'{target}: done ({record["elapsed_seconds"]} s)', flush=True)
        except Exception as e:  # noqa: BLE001
            failed.append(target)
            print(f'{target}: failed after {round(time.time() - start)} s: {redact(e)[:300]}', flush=True)

    with ThreadPoolExecutor(len(todo) or 1) as pool:
        futures = [pool.submit(one, t) for t in todo]
        start = time.time()
        while not all(f.done() for f in futures):
            time.sleep(1)
            if int(time.time() - start) % 15 == 0:
                waiting = [t for t, f in zip(todo, futures) if not f.done()]
                print(f'{round(time.time() - start)} s: waiting on Sunburst for {", ".join(waiting)}', flush=True)
                time.sleep(1)

    portraits = [(CHARS / 'portraits' / f'{cid}.png', cid) for cid in PORTRAITS if (CHARS / 'portraits' / f'{cid}.png').exists()]
    if portraits:
        sheet(portraits, REVIEW / 'character-portraits.jpg', 440, 520, 4)
    if failed:
        sys.exit(f'stopped: {", ".join(failed)} failed and are not retried')


if __name__ == '__main__':
    main()

