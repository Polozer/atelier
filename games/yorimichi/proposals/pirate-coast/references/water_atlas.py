#!/usr/bin/env python3
"""Paint the falling-water and mist textures for the Brinecove waterfall.

    uv run python games/yorimichi/proposals/pirate-coast/references/water_atlas.py

waterfall.png tiles vertically: dense white streaks over a pale body with ragged alpha, so stacked ribbons read as
broken falling water rather than a painted slab. mist.png holds soft spray puffs for crossed cards at the plunge
pools. Both are drawn procedurally; no paid call is involved.
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / 'textures'


def waterfall():
    rng = random.Random(4471)
    w, h = 256, 512
    image = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Body: a translucent blue-grey curtain; the white streaks on top carry the read. A flat pale body made the
    # whole fall one white slab.
    for x in range(w):
        band = 0.5 + 0.5 * math.sin(x * 0.11) * math.sin(x * 0.037 + 1.3)
        tone = int(150 + 50 * band)
        draw.line((x, 0, x, h), fill=(tone - 30, tone + 12, tone + 18, int(120 + 70 * band)))
    # Streaks: long vertical strokes, wrapped so the tile repeats top to bottom.
    for _ in range(190):
        x = rng.uniform(0, w)
        length = rng.uniform(60, 300)
        y0 = rng.uniform(0, h)
        width = rng.uniform(2, 9)
        tone = rng.randint(205, 255)
        colour = (tone, min(255, tone + 4), min(255, tone + 2), rng.randint(190, 255))
        for dy in (0, -h, h):
            draw.line((x, y0 + dy, x + rng.uniform(-3, 3), y0 + length + dy), fill=colour, width=int(width))
    image = image.filter(ImageFilter.GaussianBlur(1.2))
    # Ragged holes so the sheet breaks into ribbons; the material clips below about 45 % alpha.
    holes = Image.new('L', (w, h), 255)
    hd = ImageDraw.Draw(holes)
    for _ in range(16):
        x = rng.uniform(0, w)
        y0 = rng.uniform(0, h)
        length = rng.uniform(30, 140)
        for dy in (0, -h, h):
            hd.line((x, y0 + dy, x, y0 + length + dy), fill=0, width=int(rng.uniform(3, 10)))
    holes = holes.filter(ImageFilter.GaussianBlur(2.0))
    r, g, b, a = image.split()
    a = Image.composite(a, Image.new('L', (w, h), 0), holes)
    Image.merge('RGBA', (r, g, b, a)).save(OUT / 'waterfall.png')
    print('waterfall', (w, h))


def mist():
    rng = random.Random(8819)
    size = 256
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for _ in range(70):
        a = rng.uniform(0, math.tau)
        d = rng.uniform(0, 70) ** 0.9
        cx, cy = size / 2 + math.cos(a) * d, size / 2 + math.sin(a) * d * 0.8
        r = rng.uniform(14, 40)
        tone = rng.randint(232, 255)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(tone, tone, min(255, tone + 3), rng.randint(25, 70)))
    image = image.filter(ImageFilter.GaussianBlur(5))
    image.save(OUT / 'mist.png')
    print('mist', (size, size))


def spray():
    """Ragged white foam lace for patches lying on the water; clipped, so it keeps crisp edges."""
    rng = random.Random(3307)
    size = 256
    lace = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(lace)
    for _ in range(220):
        a = rng.uniform(0, math.tau)
        d = rng.uniform(0, 1) ** 0.7 * 110
        cx, cy = size / 2 + math.cos(a) * d, size / 2 + math.sin(a) * d * 0.7
        r = rng.uniform(3, 14) * (1.2 - d / 140)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=rng.randint(150, 255))
    lace = lace.filter(ImageFilter.GaussianBlur(2.5))
    tone = Image.new('RGB', (size, size), (240, 246, 244))
    image = Image.merge('RGBA', (*tone.split(), lace))
    image.save(OUT / 'spray.png')
    print('spray', (size, size))


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    waterfall()
    mist()
    spray()
