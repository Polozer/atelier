#!/usr/bin/env python3
"""Generate GPT Image 2.5 Sunburst (quality=high) concept sheets for the Kasa Ronin & Mini-Camp procedural assets."""
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'platform' / 'studio'))
from atelier import env  # noqa: E402
from atelier.ai import images  # noqa: E402

CONCEPTS_DIR = REPO / 'games' / 'yorimichi' / 'assets' / 'swordcamp' / 'concepts'
SITE_ASSETS = REPO / 'build' / 'yorimichi' / 'swordcamp' / 'site'

REFS = [
    REPO / 'games' / 'yorimichi' / 'assets' / 'houses' / 'concepts' / 'street.jpg',
    REPO / 'games' / 'yorimichi' / 'assets' / 'treehouse' / 'props' / 'kamado' / 'concept.jpg',
]

SPECS = {
    'ronin_armor_kit': (
        "Paint a clean 3D-modeling concept reference sheet on a plain warm light-grey studio background, soft even daylight, "
        "no text, no letters, no numbers, no watermarks. Images 1 and 2 show the exact warm hand-painted Japanese countryside "
        "art style of our game Yorimichi: chunky readable geometry, gently bevelled timber and lacquer edges, matte hand-painted "
        "surfaces with subtle colour variation, no photorealistic noise, no harsh specular glare. "
        "Show the modular procedural Kasa Ronin equipment kit arranged clearly with space between each piece: "
        "(1) a wide conical woven bamboo and straw sandogasa hat with radial bamboo ribs, dark cloth rim binding, and crimson chin cord; "
        "(2) a dark wrought-iron menpo half-mask and a pair of layered rectangular sode shoulder armour plates laced with crimson and deep indigo odoshi cords; "
        "(3) a tall dorsal bamboo sashimono banner frame holding a vertical indigo-and-cream cloth pennant with a simple autumn maple emblem; "
        "(4) a curved uchigatana sword and a longer nodachi greatsword with brass circular tsuba handguards, diamond-wrapped dark tsuka hilts, and lacquered scabbards."
    ),
    'camp_kit': (
        "Paint a clean 3D-modeling concept reference sheet on a plain warm light-grey studio background, soft even daylight, "
        "no text, no letters, no numbers, no watermarks. Images 1 and 2 show the exact warm hand-painted Japanese countryside "
        "art style of our game Yorimichi: chunky readable geometry, gently bevelled timber and stone edges, matte hand-painted "
        "surfaces with subtle colour variation, no photorealistic noise. "
        "Show the four modular props of a roadside Kasa Ronin mini-camp arranged clearly in three-quarter view from slightly above: "
        "(1) a timber jinmaku field curtain hung between charred cedar posts with hemp tie-ropes, cream and deep indigo vertical cloth panels, and a warm glowing paper chochin lantern hanging from the corner post; "
        "(2) a circle of river cobbles around a glowing wood-ember campfire with a three-pole lashed bamboo tripod suspending a black cast-iron tetsubin kettle over the flames; "
        "(3) a two-tier dark timber katana-kake sword rack holding two sheathed katanas beside a thick vertical makiwara wooden strike post wrapped in braided rice straw bound with crimson rope; "
        "(4) two cylindrical woven straw tawara rice bales bound with thick rope knots stacked beside a weathered cedar supply chest with iron corner brackets."
    ),
}


def generate_one(item):
    slug, prompt = item
    CONCEPTS_DIR.mkdir(parents=True, exist_ok=True)
    SITE_ASSETS.mkdir(parents=True, exist_ok=True)
    png_path = CONCEPTS_DIR / f'{slug}.png'
    jpg_path = CONCEPTS_DIR / f'{slug}.jpg'
    prompt_path = CONCEPTS_DIR / f'{slug}.prompt.txt'
    record_path = CONCEPTS_DIR / f'{slug}.provenance.json'
    prompt_path.write_text(prompt + '\n')
    if not record_path.exists():
        print(f'[sunburst] Starting {slug} (gpt-image-2.5-sunburst, quality=high)...', flush=True)
        images.paint(
            png_path,
            prompt,
            '1536x1024',
            images=REFS,
            record=record_path,
            metadata={'stage': 'swordcamp-concept', 'concept': slug, 'prompt_file': prompt_path.name},
        )
    if png_path.exists():
        images.compact(png_path, jpg_path, 1536, 90)
        shutil.copy2(jpg_path, SITE_ASSETS / f'{slug}.jpg')
        png_path.unlink(missing_ok=True)
        print(f'[sunburst] Completed {slug} -> {jpg_path}', flush=True)


def main():
    env.load(REPO / '.env')
    with ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(generate_one, SPECS.items()))


if __name__ == '__main__':
    main()
