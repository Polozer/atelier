"""Detail textures for the Belmonte train, drawn with numpy (no image model, no paid call): walnut grain, two
marquetry panels with an olive sprig in gold inlay, burgundy and emerald carpets, the vestibule tiles and the
sun-and-olive crest. Each function returns float RGBA rows, bottom row first (Blender's image order), values 0..1.
Tileable textures wrap seamlessly; panels are mapped 0..1 on each panel face.
"""
import math

import numpy as np

WALNUT_DARK = np.array([.115, .042, .016])
WALNUT_MID = np.array([.235, .095, .036])
WALNUT_LIGHT = np.array([.36, .165, .07])
INLAY = np.array([.80, .56, .25])          # pale olive wood / satinwood inlay
GOLD = np.array([.86, .62, .26])


def _noise(h, w, cells, seed, octaves=4):
    """Tileable value noise in 0..1."""
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w))
    amp, total = 1., 0.
    for o in range(octaves):
        cy, cx = cells[0] * 2 ** o, cells[1] * 2 ** o
        g = rng.random((cy, cx))
        y = np.linspace(0, cy, h, endpoint=False); x = np.linspace(0, cx, w, endpoint=False)
        y0 = np.floor(y).astype(int); x0 = np.floor(x).astype(int)
        fy = (y - y0)[:, None]; fx = (x - x0)[None, :]
        fy = fy * fy * (3 - 2 * fy); fx = fx * fx * (3 - 2 * fx)
        a = g[y0 % cy][:, x0 % cx]; b = g[y0 % cy][:, (x0 + 1) % cx]
        c = g[(y0 + 1) % cy][:, x0 % cx]; d = g[(y0 + 1) % cy][:, (x0 + 1) % cx]
        out += amp * ((a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy)
        total += amp; amp *= .5
    return out / total


def _rgba(rgb, alpha=None):
    h, w, _ = rgb.shape
    a = np.ones((h, w, 1)) if alpha is None else alpha[..., None]
    return np.concatenate([np.clip(rgb, 0, 1), a], axis=2)


def walnut(size=1024, seed=3, figure=1.):
    """Tileable straight-grained walnut: wavy stripes along U with darker pores."""
    n = _noise(size, size, (4, 2), seed)
    fine = _noise(size, size, (64, 8), seed + 1, 2)
    v = np.linspace(0, 1, size, endpoint=False)[:, None]
    stripes = .5 + .5 * np.sin(2 * math.pi * (v * 22 + n * 3.2 * figure))
    t = np.clip(.15 + .6 * stripes + .25 * (fine - .5), 0, 1)[..., None]
    rgb = WALNUT_DARK * (1 - t) + WALNUT_MID * t
    rgb = rgb * (.92 + .16 * _noise(size, size, (2, 2), seed + 2, 2))[..., None]
    return _rgba(rgb)


def _stroke(img, mask, color):
    img[mask] = color


def _leaf_mask(X, Y, cx, cy, length, width, angle):
    ca, sa = math.cos(angle), math.sin(angle)
    u = (X - cx) * ca + (Y - cy) * sa
    w = -(X - cx) * sa + (Y - cy) * ca
    # a pointed leaf: ellipse narrowed towards its tip
    t = np.clip(u / length, 0, 1)
    half = width * np.sin(math.pi * t) ** .8
    return (u >= 0) & (u <= length) & (np.abs(w) <= half)


def _sprig(img, X, Y, x0, y0, x1, y1, scale, leaves=7):
    """An olive sprig from (x0, y0) to (x1, y1) (pixels): a slender stem with paired leaves, inlaid."""
    length = math.hypot(x1 - x0, y1 - y0)
    ang = math.atan2(y1 - y0, x1 - x0)
    stem = np.zeros(X.shape, bool)
    for k in range(200):
        t = k / 199
        bend = math.sin(t * math.pi) * .05 * length
        px = x0 + (x1 - x0) * t - math.sin(ang) * bend
        py = y0 + (y1 - y0) * t + math.cos(ang) * bend
        stem |= (X - px) ** 2 + (Y - py) ** 2 <= (scale * (1.6 - .9 * t)) ** 2
    mask = stem.copy()
    for k in range(leaves):
        t = .12 + .80 * k / (leaves - 1)
        bend = math.sin(t * math.pi) * .05 * length
        px = x0 + (x1 - x0) * t - math.sin(ang) * bend
        py = y0 + (y1 - y0) * t + math.cos(ang) * bend
        size = scale * (17 - 8 * t)
        for side in (-1, 1):
            mask |= _leaf_mask(X, Y, px, py, size, size * .26, ang + side * .75)
    mask |= _leaf_mask(X, Y, x1 - math.cos(ang) * scale * 2, y1 - math.sin(ang) * scale * 2, scale * 11, scale * 2.6, ang)
    # olives: two small ovals near the base
    for side in (-1, 1):
        t = .38
        px = x0 + (x1 - x0) * t + side * math.sin(ang) * scale * 9
        py = y0 + (y1 - y0) * t - side * math.cos(ang) * scale * 9
        mask |= ((X - px) / (scale * 3.2)) ** 2 + ((Y - py) / (scale * 4.2)) ** 2 <= 1
    edge = mask & ~(np.roll(mask, 2, 0) & np.roll(mask, -2, 0) & np.roll(mask, 2, 1) & np.roll(mask, -2, 1))
    shade = (.86 + .14 * np.sin(X * .05 + Y * .03))[..., None]
    img[mask] = (INLAY * shade)[mask]
    img[edge] = WALNUT_DARK * .8


def _border(img, X, Y, w, h, inset, line, color):
    m = ((np.abs(X - inset) < line) | (np.abs(X - (w - inset)) < line)) & (Y > inset - line) & (Y < h - inset + line)
    m |= ((np.abs(Y - inset) < line) | (np.abs(Y - (h - inset)) < line)) & (X > inset - line) & (X < w - inset + line)
    img[m] = color


def panel(w=512, h=1024, seed=11, horizontal=False):
    """A marquetry panel: burr walnut field, darker cross-banded edge, double gold line and a central olive sprig."""
    rng_n = _noise(h, w, (3, 3), seed, 5)
    burr = .5 + .5 * np.sin(rng_n * 40)
    t = (.25 + .5 * burr)[..., None]
    img = WALNUT_MID * (1 - t) + WALNUT_LIGHT * t
    Y, X = np.mgrid[0:h, 0:w].astype(float)
    band = min(w, h) * .07
    edge = (X < band) | (X > w - band) | (Y < band) | (Y > h - band)
    img[edge] = (WALNUT_DARK * 1.3 * (.9 + .2 * rng_n[..., None]))[edge]
    _border(img, X, Y, w, h, band * 1.25, 2.2, GOLD)
    _border(img, X, Y, w, h, band * 1.6, 1.2, GOLD * .85)
    s = min(w, h) / 512 * 1.6
    if horizontal:
        _sprig(img, X, Y, w * .22, h * .5, w * .78, h * .5, s * .9, leaves=8)
    else:
        _sprig(img, X, Y, w * .5, h * .18, w * .5, h * .84, s, leaves=8)
    return _rgba(img)


def carpet(size=1024, field=(.30, .035, .04), motif=GOLD * .85, seed=5):
    """Tileable carpet: a diamond trellis of fine gold lines with a four-petal flower in each lozenge."""
    Y, X = np.mgrid[0:size, 0:size].astype(float) / size
    n = _noise(size, size, (16, 16), seed, 3)
    img = np.array(field)[None, None, :] * (.85 + .3 * n[..., None])
    u, v = (X * 4) % 1, (Y * 4) % 1
    d = np.abs(u - .5) + np.abs(v - .5)
    trellis = np.abs(d - .5) < .018
    img[trellis] = motif
    r = np.hypot(u - .5, v - .5); a = np.arctan2(v - .5, u - .5)
    petals = r < .11 * (.55 + .45 * np.abs(np.cos(2 * a)))
    img[petals] = motif * 1.05
    img[r < .03] = np.array(field) * .6
    corner = np.hypot(np.minimum(u, 1 - u), np.minimum(v, 1 - v)) < .045
    img[corner] = motif * .9
    return _rgba(img)


def tiles(size=512):
    """Vestibule floor: ivory and charcoal stone squares set on the diagonal."""
    Y, X = np.mgrid[0:size, 0:size].astype(float) / size
    n = _noise(size, size, (8, 8), 21, 3)[..., None]
    u, v = (X + Y) * 4, (X - Y) * 4
    check = (np.floor(u) + np.floor(v)) % 2 == 0
    ivory = np.array([.62, .58, .50]) * (.9 + .2 * n)
    dark = np.array([.07, .07, .075]) * (.8 + .4 * n)
    img = np.where(check[..., None], ivory, dark)
    grout = (np.abs(u - np.round(u)) < .02) | (np.abs(v - np.round(v)) < .02)
    img[grout] = (.30, .28, .25)
    return _rgba(img)


def crest(size=512):
    """The original crest: a sun disc with alternating rays above two olive branches, gold on transparent."""
    Y, X = np.mgrid[0:size, 0:size].astype(float)
    cx, cy = size / 2, size * .58
    r = np.hypot(X - cx, Y - cy); a = np.arctan2(Y - cy, X - cx)
    rays = (r < size * (.20 + .06 * (np.cos(a * 16) > 0))) & (np.abs(np.sin(a * 16)) < .55)
    disc = r < size * .12
    ring = np.abs(r - size * .135) < size * .008
    mask = rays | disc | ring
    img = np.zeros((size, size, 3)) + GOLD
    sh = (.85 + .15 * np.cos(a * 32))[..., None]
    img = img * sh
    branches = np.zeros_like(mask)
    tmp = np.zeros((size, size, 3))
    for side in (-1, 1):
        x0, y0 = cx + side * size * .05, size * .17
        x1, y1 = cx + side * size * .40, size * .52
        sub = np.zeros((size, size, 3))
        _sprig(sub, X, Y, x0, y0, x1, y1, size / 512 * 1.4, leaves=7)
        m = sub.sum(2) > 0
        branches |= m
    img[branches] = GOLD * .95
    alpha = (mask | branches).astype(float)
    img[disc] = GOLD * 1.08
    return _rgba(img, alpha)


ALL = {
    'T_BT_Walnut': lambda: walnut(),
    'T_BT_PanelTall': lambda: panel(512, 1024, 11),
    'T_BT_PanelWide': lambda: panel(1024, 512, 13, horizontal=True),
    'T_BT_CarpetBurgundy': lambda: carpet(1024, (.30, .035, .045), GOLD * .80, 5),
    'T_BT_CarpetEmerald': lambda: carpet(1024, (.035, .17, .12), GOLD * .80, 7),
    'T_BT_Tiles': lambda: tiles(),
    'T_BT_Crest': lambda: crest(),
}
