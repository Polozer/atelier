#!/usr/bin/env python3
"""Generate GPT Image 2.5 Sunburst (quality=high) UV textures for the procedural Kasa Ronin & Mini-Camp assets."""
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'platform' / 'studio'))
from atelier import env  # noqa: E402
from atelier.ai import images  # noqa: E402

CONCEPTS_DIR = REPO / 'games' / 'yorimichi' / 'assets' / 'swordcamp' / 'concepts'
TEX_DIR = REPO / 'games' / 'yorimichi' / 'assets' / 'swordcamp' / 'textures'
SITE_ASSETS = REPO / 'build' / 'yorimichi' / 'swordcamp' / 'site'

RONIN_REF = CONCEPTS_DIR / 'ronin_armor_kit.jpg'
CAMP_REF = CONCEPTS_DIR / 'camp_kit.jpg'

SURFACE_PREFIX = (
    "A seamless flat texture for a stylised Japanese countryside game, seen perfectly straight-on and filling the whole "
    "square edge to edge: no background, no perspective, no object outline, no text or letters, even studio lighting, "
    "matching the exact warm hand-painted materials in Image 1. "
)

TEXTURES = {
    'sashimono_maple': (
        [RONIN_REF],
        SURFACE_PREFIX
        + "A flat straight-on texture of the indigo sashimono banner cloth from Image 1: deep hand-dyed indigo cotton weave "
        "filling the whole frame, a horizontal warm cream stripe near the top and another near the bottom, and in the exact "
        "centre a large warm cream circle containing a bold autumn crimson seven-pointed Japanese maple leaf (momiji emblem)."
    ),
    'sandogasa_weave': (
        [RONIN_REF],
        SURFACE_PREFIX
        + "A flat top-down polar texture of the conical woven bamboo sandogasa hat from Image 1, filling the square: "
        "concentric rings of warm golden woven rice straw and split bamboo slats radiating from the centre, with thin radial "
        "bamboo ribs and a dark indigo-black cloth binding band around the outer border."
    ),
    'sode_lacquer': (
        [RONIN_REF],
        SURFACE_PREFIX
        + "A flat straight-on trim-sheet texture of the layered sode shoulder armour from Image 1, filling the square: "
        "four horizontal rows of weathered dark charcoal-iron lacquer armour lames separated by rows of vertical crimson "
        "and deep indigo braided silk odoshi lacing cords, with two small warm brass rivet bosses near the top."
    ),
    'jinmaku_stripe': (
        [CAMP_REF],
        SURFACE_PREFIX
        + "A flat straight-on texture of the jinmaku camp curtain cloth from Image 1, filling the square edge to edge: "
        "alternating wide vertical panels of weathered deep indigo cotton and warm unbleached cream linen cloth, with subtle "
        "hand-painted fabric weave, gentle vertical fold shading, and a double-stitched hem line along the bottom edge."
    ),
}


def paint_one(item):
    slug, (refs, prompt) = item
    TEX_DIR.mkdir(parents=True, exist_ok=True)
    SITE_ASSETS.mkdir(parents=True, exist_ok=True)
    png_path = TEX_DIR / f'{slug}.png'
    jpg_path = TEX_DIR / f'{slug}.jpg'
    prompt_path = TEX_DIR / f'{slug}.prompt.txt'
    record_path = TEX_DIR / f'{slug}.provenance.json'
    prompt_path.write_text(prompt + '\n')
    if not record_path.exists():
        print(f'[sunburst-tex] Starting {slug}...', flush=True)
        images.paint(
            png_path,
            prompt,
            '1024x1024',
            images=refs,
            record=record_path,
            metadata={'stage': 'swordcamp-texture', 'slug': slug, 'prompt_file': prompt_path.name},
        )
    if png_path.exists():
        images.compact(png_path, jpg_path, 1024, 92)
        shutil.copy2(jpg_path, SITE_ASSETS / f'tex_{slug}.jpg')
        png_path.unlink(missing_ok=True)
        print(f'[sunburst-tex] Completed {slug} -> {jpg_path}', flush=True)


def main():
    env.load(REPO / '.env')
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(paint_one, TEXTURES.items()))


if __name__ == '__main__':
    main()
