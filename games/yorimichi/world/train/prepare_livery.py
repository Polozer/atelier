"""Prepare the livery swatches generated in ChatGPT for the train build (plain Python with Pillow, run once by hand).

    python3 games/yorimichi/world/train/prepare_livery.py BLUE IVORY ROOF UNDERFRAME [BACKHEAD SMOKEBOX_DOOR]

Writes games/yorimichi/assets/vehicles/belmonte-train/textures/*.jpg, the committed sources build.py reads:
- livery-blue-panel.jpg: one lined lower-body panel (rivet strips, brass beading), 2048 x 1024, mapped once per
  panel between the doors, skirt to belt;
- livery-ivory.jpg: the upper-body enamel without the swatch's brass line (the shell models its own), cropped above
  that line and cross-faded top to bottom so it tiles both ways, 2048 x 1024 for 2.00 x 1.00 m;
- roof-canvas.jpg: the canvas roof cropped to a whole number of seam pitches (seven) so it tiles, turned a quarter so
  the seams run across the coach, 1024 x 1024;
- underframe.jpg: the riveted black steel of the bogies and underframe, 1024 x 1024;
- backhead.jpg and smokebox-door.jpg: the locomotive's firebox backhead (gauges, water glasses, valves and the
  fire-door arch painted on) and its round smokebox door, 1024 x 1024 each, mapped whole on their faces.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parents[2] / 'assets' / 'vehicles' / 'belmonte-train' / 'textures'
IVORY_CROP = 800              # rows above the swatch's brass line (rows 821-833 of 887)
FADE = 64
ROOF_CROP = (32, 1222)        # seven seam pitches of 170 px


def save(img, name, size):
    OUT.mkdir(parents=True, exist_ok=True)
    img.convert('RGB').resize(size, Image.LANCZOS).save(OUT / name, quality=90, optimize=True)
    print(name, size)


def main(blue, ivory, roof, underframe, backhead=None, smokebox_door=None):
    save(Image.open(blue), 'livery-blue-panel.jpg', (2048, 1024))
    a = np.asarray(Image.open(ivory).convert('RGB'), float)[:IVORY_CROP]
    body = a[:-FADE].copy()
    t = np.linspace(0, 1, FADE)[:, None, None]
    body[:FADE] = a[-FADE:] * (1 - t) + a[:FADE] * t
    save(Image.fromarray(body.clip(0, 255).astype(np.uint8)), 'livery-ivory.jpg', (2048, 1024))
    r = Image.open(roof).convert('RGB')
    r = r.crop((0, ROOF_CROP[0], r.width, ROOF_CROP[1])).rotate(90, expand=True)
    save(r, 'roof-canvas.jpg', (1024, 1024))
    save(Image.open(underframe), 'underframe.jpg', (1024, 1024))
    if backhead:
        save(Image.open(backhead), 'backhead.jpg', (1024, 1024))
    if smokebox_door:
        save(Image.open(smokebox_door), 'smokebox-door.jpg', (1024, 1024))


if __name__ == '__main__':
    main(*sys.argv[1:7])
