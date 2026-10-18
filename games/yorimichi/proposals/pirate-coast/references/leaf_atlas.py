#!/usr/bin/env python3
"""Paint the alpha leaf-card atlases used by the Brinecove trees and palms.

    uv run python games/yorimichi/proposals/pirate-coast/references/leaf_atlas.py

Four 512-square canopies (mid, light, deep, warm) share one leaf silhouette
vocabulary; a separate atlas carries long palm fronds.  Every card in the
scene samples one 256-square cell, so the same atlas serves the whole town.
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / 'textures'
SIZE = 512
CELL = SIZE // 2

# Base leaf colour, vein colour, and the spread of shades around the base.
PALETTES = {
    'leaf_mid': ((76, 104, 48), (52, 74, 34), 26),
    'leaf_light': ((108, 138, 63), (74, 100, 44), 30),
    'leaf_deep': ((52, 72, 34), (34, 50, 23), 20),
    'leaf_warm': ((150, 112, 48), (104, 74, 34), 34),
}


def shade(color, amount):
    return tuple(max(0, min(255, int(c + amount))) for c in color)


def leaf_polygon(cx, cy, length, width, angle):
    points = []
    steps = 12
    for i in range(steps + 1):
        t = i / steps
        x = (t - 0.5) * length
        y = math.sin(math.pi * t) ** 0.72 * width * 0.5
        points.append((x, y))
    for i in range(steps, -1, -1):
        t = i / steps
        x = (t - 0.5) * length
        y = -math.sin(math.pi * t) ** 0.72 * width * 0.5
        points.append((x, y))
    ca, sa = math.cos(angle), math.sin(angle)
    return [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in points]


def paint_canopy(draw, ox, oy, base, vein, spread, rng):
    for _ in range(16):
        angle = rng.uniform(0, math.tau)
        distance = rng.uniform(10, 88)
        cx = ox + 128 + math.cos(angle) * distance
        cy = oy + 128 + math.sin(angle) * distance * 0.86
        length = rng.uniform(72, 138)
        width = length * rng.uniform(0.34, 0.52)
        tone = rng.randint(-spread, spread)
        colour = shade(base, tone)
        rotation = angle + rng.uniform(-1.2, 1.2)
        polygon = leaf_polygon(cx, cy, length, width, rotation)
        draw.polygon(polygon, fill=colour + (255,))
        # A darker midrib and two side veins keep the cards readable at distance.
        ca, sa = math.cos(rotation), math.sin(rotation)
        x0, y0 = cx - ca * length * 0.44, cy - sa * length * 0.44
        x1, y1 = cx + ca * length * 0.44, cy + sa * length * 0.44
        draw.line((x0, y0, x1, y1), fill=vein + (210,), width=2)
        for side in (-1, 1):
            vx = cx + math.cos(rotation + side * 0.7) * length * 0.25
            vy = cy + math.sin(rotation + side * 0.7) * length * 0.25
            draw.line((cx, cy, vx, vy), fill=vein + (160,), width=1)


def leaf_atlas(name, base, vein, spread):
    rng = random.Random(sum(map(ord, name)))
    image = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for cell in range(4):
        ox, oy = (cell % 2) * CELL, (cell // 2) * CELL
        paint_canopy(draw, ox, oy, base, vein, spread, rng)
    image.save(OUT / f'{name}.png')
    print(name, image.size)


def palm_frond():
    rng = random.Random(9157)
    image = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for cell in range(4):
        ox, oy = (cell % 2) * CELL, (cell // 2) * CELL
        cx = ox + CELL / 2
        base_y = oy + CELL - 14
        tip_y = oy + 12
        draw.line((cx, base_y, cx, tip_y), fill=(72, 94, 42, 255), width=4)
        for i in range(9):
            t = (i + 0.5) / 9
            y = base_y + (tip_y - base_y) * t
            span = (1.0 - t) ** 0.80 * 136 + 12
            for side in (-1, 1):
                angle = side * (0.34 - 0.14 * t)
                length = span * rng.uniform(0.86, 1.04)
                polygon = leaf_polygon(cx + side * 3, y, length,
                                       max(9, 26 * (1 - t) + 7), angle + (0 if side > 0 else math.pi))
                tone = rng.randint(-20, 20)
                draw.polygon(polygon, fill=shade((84, 116, 50), tone) + (255,))
                draw.line((cx + side * 3, y, cx + side * 3 + math.cos(angle) * length * 0.4,
                           y + math.sin(angle) * length * 0.4), fill=(62, 84, 38, 180), width=1)
    image.save(OUT / 'palm_frond.png')
    print('palm_frond', image.size)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (base, vein, spread) in PALETTES.items():
        leaf_atlas(name, base, vein, spread)
    palm_frond()


if __name__ == '__main__':
    main()

