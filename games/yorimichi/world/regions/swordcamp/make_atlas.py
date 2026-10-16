#!/usr/bin/env python3
"""Assemble the 2048x2048 Sunburst UV texture atlas for the procedural Kasa Ronin & Mini-Camp assets."""
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[5]
CONCEPTS = REPO / 'games' / 'yorimichi' / 'assets' / 'swordcamp' / 'concepts'
TEX = REPO / 'games' / 'yorimichi' / 'assets' / 'swordcamp' / 'textures'
TH_TEX = REPO / 'games' / 'yorimichi' / 'assets' / 'treehouse' / 'textures'
SITE_ASSETS = REPO / 'build' / 'yorimichi' / 'swordcamp' / 'site'


def clean_sandogasa(im):
    """Replace the exterior corners outside the circular hat rim with the dark indigo cloth rim tone so UV mipmaps never sample background."""
    arr = np.asarray(im.convert('RGB'), dtype=np.uint8).copy()
    h, w, _ = arr.shape
    yy, xx = np.indices((h, w), dtype=np.float32)
    r = np.hypot((xx - w * 0.5) / (w * 0.5), (yy - h * 0.5) / (h * 0.5))
    outer = r > 0.965
    arr[outer] = np.array([38, 43, 58], dtype=np.uint8)
    return Image.fromarray(arr)


def build_atlas():
    TEX.mkdir(parents=True, exist_ok=True)
    SITE_ASSETS.mkdir(parents=True, exist_ok=True)
    atlas = Image.new('RGB', (2048, 2048), (45, 42, 38))

    # Quadrant (0, 0) [top-left, y: 0..1024, x: 0..1024]: sandogasa_weave (UV u: 0..0.5, v: 0.5..1.0 in Blender bottom-up)
    sando = clean_sandogasa(Image.open(TEX / 'sandogasa_weave.jpg').resize((1024, 1024), Image.LANCZOS))
    atlas.paste(sando, (0, 0))

    # Quadrant (1, 0) [top-right, y: 0..1024, x: 1024..2048]: sode_lacquer (UV u: 0.5..1.0, v: 0.5..1.0)
    sode = Image.open(TEX / 'sode_lacquer.jpg').convert('RGB').resize((1024, 1024), Image.LANCZOS)
    atlas.paste(sode, (1024, 0))

    # Quadrant (0, 1) [bottom-left, y: 1024..2048, x: 0..1024]: sashimono_maple (UV u: 0..0.5, v: 0.0..0.5)
    sashi = Image.open(TEX / 'sashimono_maple.jpg').convert('RGB').resize((1024, 1024), Image.LANCZOS)
    atlas.paste(sashi, (0, 1024))

    # Quadrant (1, 1) [bottom-right, y: 1024..2048, x: 1024..2048]: 4 subtiles of 512x512
    # Subtile (1024, 1024) [u: 0.5..0.75, v: 0.25..0.5]: jinmaku_stripe
    jin = Image.open(TEX / 'jinmaku_stripe.jpg').convert('RGB').resize((512, 512), Image.LANCZOS)
    atlas.paste(jin, (1024, 1024))

    # Subtile (1536, 1024) [u: 0.75..1.0, v: 0.25..0.5]: Orthographic Pixel-Match crops from ronin_armor_kit & camp_kit
    #   - (1536, 1024) 256x256: Menpo Iron Mask orthographic front projection
    #   - (1792, 1024) 256x256: Cedar chest front orthographic projection
    #   - (1536, 1280) 256x256: Tawara straw bale weave & rope projection
    #   - (1792, 1280) 256x256: Tsuka diamond hilt wrap & blade hamon strip
    im_r = Image.open(CONCEPTS / 'ronin_armor_kit.jpg').convert('RGB')
    im_c = Image.open(CONCEPTS / 'camp_kit.jpg').convert('RGB')

    menpo_crop = im_r.crop((110, 438, 422, 686)).resize((256, 256), Image.LANCZOS)
    # Replace light studio background pixels in menpo_crop with dark wrought iron
    m_arr = np.asarray(menpo_crop, dtype=np.uint8).copy()
    bg_mask = (m_arr[:, :, 0] > 175) & (m_arr[:, :, 1] > 175) & (m_arr[:, :, 2] > 175)
    m_arr[bg_mask] = np.array([46, 42, 40], dtype=np.uint8)
    atlas.paste(Image.fromarray(m_arr), (1536, 1024))

    chest_crop = im_c.crop((1035, 625, 1475, 945)).resize((256, 256), Image.LANCZOS)
    c_arr = np.asarray(chest_crop, dtype=np.uint8).copy()
    c_bg = (c_arr[:, :, 0] > 180) & (c_arr[:, :, 1] > 180) & (c_arr[:, :, 2] > 180)
    c_arr[c_bg] = np.array([76, 52, 36], dtype=np.uint8)
    atlas.paste(Image.fromarray(c_arr), (1792, 1024))

    bale_crop = im_c.crop((790, 585, 1045, 795)).resize((256, 256), Image.LANCZOS)
    b_arr = np.asarray(bale_crop, dtype=np.uint8).copy()
    b_bg = (b_arr[:, :, 0] > 185) & (b_arr[:, :, 1] > 185) & (b_arr[:, :, 2] > 185)
    b_arr[b_bg] = np.array([188, 152, 88], dtype=np.uint8)
    atlas.paste(Image.fromarray(b_arr), (1536, 1280))

    tsuka_crop = im_r.crop((65, 730, 275, 785)).resize((256, 256), Image.LANCZOS)
    t_arr = np.asarray(tsuka_crop, dtype=np.uint8).copy()
    t_bg = (t_arr[:, :, 0] > 180) & (t_arr[:, :, 1] > 180) & (t_arr[:, :, 2] > 180)
    t_arr[t_bg] = np.array([38, 42, 54], dtype=np.uint8)
    atlas.paste(Image.fromarray(t_arr), (1792, 1280))

    # Subtile (1024, 1536) [u: 0.5..0.75, v: 0.0..0.25]: Treehouse Sunburst surfaces (wood_timber, straw, stone, iron)
    for idx, (slug, box) in enumerate([
        ('wood_timber', (1024, 1536)),
        ('straw', (1280, 1536)),
        ('stone', (1024, 1792)),
        ('iron', (1280, 1792)),
    ]):
        src = TH_TEX / f'{slug}.jpg'
        if src.exists():
            tile = Image.open(src).convert('RGB').resize((256, 256), Image.LANCZOS)
            atlas.paste(tile, box)

    # Subtile (1536, 1536) [u: 0.75..1.0, v: 0.0..0.25]: 4x4 grid of 128x128 hand-painted material swatches & gradients
    draw = ImageDraw.Draw(atlas)
    swatches = [
        (0, 0, (196, 158, 72), (148, 114, 42)),   # 0: Warm Bamboo / Gold-Green Culm
        (1, 0, (198, 52, 46), (138, 28, 26)),     # 1: Crimson Braided Odoshi / Cord
        (2, 0, (42, 54, 84), (24, 32, 52)),       # 2: Deep Indigo Lacquer / Cloth
        (3, 0, (214, 172, 74), (162, 122, 36)),   # 3: Brushed Antique Brass (Tsuba / Habaki)
        (0, 1, (226, 234, 244), (142, 154, 172)), # 4: Forged Steel Blade & Hamon Edge
        (1, 1, (44, 42, 46), (26, 24, 28)),       # 5: Black Cast Iron (Kettle / Brackets)
        (2, 1, (82, 54, 36), (52, 32, 20)),       # 6: Charred Cedar / Keyaki Dark Wood
        (3, 1, (195, 168, 112), (154, 128, 78)),  # 7: Hemp Rope & Twine
        (0, 2, (255, 208, 112), (242, 138, 42)),  # 8: Glowing Chochin Lantern Paper
        (1, 2, (255, 142, 32), (168, 36, 12)),    # 9: Glowing Campfire Embers
        (2, 2, (112, 34, 30), (68, 18, 16)),      # 10: Crimson Lacquer Saya
        (3, 2, (232, 224, 204), (196, 186, 164)), # 11: Unbleached Cream Linen Loop
        (0, 3, (118, 126, 92), (76, 82, 62)),     # 12: Mossy River Cobble Stone
        (1, 3, (165, 182, 112), (118, 138, 74)),  # 13: Fresh Green Bamboo Culm
        (2, 3, (64, 44, 32), (38, 26, 18)),       # 14: Charred Firewood Bark
        (3, 3, (218, 184, 148), (186, 148, 112)), # 15: Warm Skin / Wood Dowel
    ]
    rng = np.random.default_rng(42)
    for gx, gy, c_top, c_bot in swatches:
        x0 = 1536 + gx * 128
        y0 = 1536 + gy * 128
        block = np.zeros((128, 128, 3), dtype=np.float32)
        for row in range(128):
            t = row / 127.0
            block[row, :] = np.array(c_top) * (1.0 - t) + np.array(c_bot) * t
        noise = rng.normal(0.0, 4.5, (128, 128, 1))
        block = np.clip(block + noise, 0, 255).astype(np.uint8)
        atlas.paste(Image.fromarray(block), (x0, y0))

    out_jpg = TEX / 'swordcamp_atlas.jpg'
    atlas.save(out_jpg, 'JPEG', quality=93)
    atlas.save(SITE_ASSETS / 'swordcamp_atlas.jpg', 'JPEG', quality=92)
    print(f'Built 2048x2048 Sunburst UV atlas -> {out_jpg}')


if __name__ == '__main__':
    build_atlas()
