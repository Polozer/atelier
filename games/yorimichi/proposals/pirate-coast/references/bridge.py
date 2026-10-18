#!/usr/bin/env python3
"""Paint middle-ground targets that bridge the Sunburst concepts and the built scene.

    uv run python games/yorimichi/proposals/pirate-coast/references/bridge.py [--only slug]

Each call edits with two references: the current low-poly Blender render of a
view, and the original Sunburst concept for the same place.  The result keeps
the built camera and blocky construction but adopts the concept's warmth and
lived-in detail, so it describes something the existing kit can actually build.
Every paid call is recorded by atelier.ai.ledger.
"""
import argparse
import hashlib
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO / 'platform/studio'))

from atelier.ai import images, ledger  # noqa: E402

MODEL = 'gpt-image-2.5-sunburst'
QUALITY = 'high'
SIZE = '1536x1024'
BUILD = REPO / 'build/yorimichi/pirate-coast'
OUT = BUILD / 'references-bridge'

PROMPT = (
    "IMAGE 1 is the current in-engine low-poly render of a place in our game Yorimichi. IMAGE 2 is the "
    "painted concept for the same place. Produce a MIDDLE-GROUND TARGET that shows how image 1 can move "
    "toward image 2 while staying buildable from the same primitives. Keep image 1's exact camera, layout, "
    "architecture, scale and faceted low-poly construction: flat-shaded boxes, simple cylinders, chunky "
    "roof planes, no bevelled curves and no new buildings. Replace image 1's washed grey-green look with "
    "image 2's warm storybook palette: sunlit cream, ochre and faded coral plaster, sage and teal accents, "
    "terracotta and oxidised-teal roofs, saturated blue-green water, warm late-afternoon light with clear "
    "sun and shade. Add only detail that flat primitives can carry: coloured shutters and window surrounds, "
    "striped canvas awnings, timber galleries and balconies, hanging laundry, painted sign boards, potted "
    "palms and flowering plants, crates, barrels, rope, fish baskets, lamps, pennants and more people. "
    "Keep shapes crisp and readable, no watercolour texture bleeding, no outlines, no photoreal detail, no "
    "text or labels. The result should look like our game after a strong art-direction pass, not like a "
    "different game. VIEW: "
)

VIEWS = {
    '02-harbor-approach': (
        "the quay seen from a boat inside the harbor mouth. Keep the statue on its islet at left, the "
        "central pier and the moored galleons, the long retaining wall, the terraced roofs, the watchtower "
        "and the waterfall at right. Show the waterfront reading as a continuous lived-in street: awnings, "
        "galleries, signs, laundry, lamps, cargo and colour along the whole quay."
    ),
    '03-market-square': (
        "eye level in the cobbled market square. Keep the signal mast, the stalls, the well, the retaining "
        "wall and stair behind. Make the market dense and working: striped canvas, crates of fish and fruit, "
        "sacks, rope, pottery, hanging pennants, potted palms, and a crowd that reads at a glance. The "
        "taverns around the square should have coloured shutters, awnings, signs and flower boxes."
    ),
    '04-upper-terrace': (
        "from the upper terrace looking down over the roofs to the bay. Keep the foreground roofs, the "
        "market below, the piers, the galleons and the far headland. Add roof variety the kit can build: "
        "ridge caps, chimneys with pots, dormers, a rooftop terrace with a railing and plants, laundry "
        "lines, potted palms and crates in the lane. Roofs should read as overlapping warm terracotta and "
        "teal planes with strong sunlight and shadow."
    ),
    '09-rum-row': (
        "street level in the waterfront tavern street. Keep the tall three-storey facades, timber frames, "
        "galleries, shutters and the narrow gap to the water. Push the street life: deep canvas awnings, "
        "painted hanging signs, laundry, flower boxes, barrels and crates, a fishmonger table, benches, "
        "lanterns and people. Facades should alternate cream, ochre, coral and muted teal with dark timber "
        "and crisp shadow."
    ),
}

REFERENCES = BUILD / 'references'
RENDERS = BUILD / 'renders'


def key():
    from atelier.env import load
    load()
    import os
    value = os.environ.get('OPENAI_API_KEY')
    if not value:
        raise SystemExit('OPENAI_API_KEY is not set')
    return value


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def paint_one(slug):
    render = RENDERS / f'{slug}.png'
    concept = REFERENCES / f'{slug}.png'
    for path in (render, concept):
        if not path.exists():
            return slug, None, f'missing input {path}'
    target = OUT / f'{slug}.png'
    record = OUT / f'{slug}.provenance.json'
    prompt_file = OUT / f'{slug}.prompt.txt'
    prompt = PROMPT + VIEWS[slug]
    prompt_file.write_text(prompt + '\n')
    if record.exists():
        data = json.loads(record.read_text())
        if data.get('status') == 'done' and target.exists():
            return slug, str(target), None
        return slug, None, 'already recorded; set the record aside to pay again'

    def call():
        blobs, body, seconds = images.sunburst(prompt, SIZE, [render, concept], 1, model=MODEL,
                                               quality=QUALITY, key=key())
        target.write_bytes(blobs[0])
        return dict(elapsed_seconds=seconds, outputs={target.name: sha(target)}, usage=body.get('usage'))

    prov, error = ledger.try_once(record, dict(
        stage='brinecove-bridge', view=slug, requested_model=MODEL, quality=QUALITY, size=SIZE, n=1,
        endpoint='/v1/images/edits', execution='games/yorimichi/proposals/pirate-coast/references/bridge.py',
        prompt_file=prompt_file.name, prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        reference_files={
            str(render.relative_to(REPO)): sha(render),
            str(concept.relative_to(REPO)): sha(concept),
        }), call)
    return slug, str(target) if prov else None, error


def contact_sheet():
    from PIL import Image, ImageDraw
    files = sorted(OUT.glob('*.png'))
    if not files:
        return
    cols, thumb_w = 2, 700
    thumbs = []
    for path in files:
        im = Image.open(path).convert('RGB')
        im = im.resize((thumb_w, round(im.height * thumb_w / im.width)), Image.LANCZOS)
        thumbs.append((path, im))
    pad = 16
    rows = math.ceil(len(thumbs) / cols)
    cell_h = max(im.height for _, im in thumbs) + 42
    canvas = Image.new('RGB', (cols * thumb_w + (cols + 1) * pad, rows * cell_h + (rows + 1) * pad), (235, 227, 208))
    draw = ImageDraw.Draw(canvas)
    for i, (path, im) in enumerate(thumbs):
        x = pad + (i % cols) * (thumb_w + pad)
        y = pad + (i // cols) * cell_h
        canvas.paste(im, (x, y + 26))
        draw.text((x, y + 4), path.stem, fill=(63, 49, 40))
    canvas.save(OUT / 'contact-sheet.jpg', quality=90)
    print('contact sheet:', OUT / 'contact-sheet.jpg')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    ap.add_argument('--jobs', type=int, default=2)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    key()
    slugs = [s for s in args.only.split(',') if s] or list(VIEWS)
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for slug, path, error in pool.map(paint_one, slugs):
            print(f'{slug}: {path or "not painted"}{(" (" + error + ")") if error else ""}', flush=True)
    contact_sheet()


if __name__ == '__main__':
    main()

