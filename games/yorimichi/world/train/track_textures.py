"""Detail textures for the Belmonte track's ballast bed, drawn with numpy (no image model, no paid call).

- T_TK_Ballast: crushed stone, 4-7 cm angular pieces in warm greys with dark voids between them, for the ballast's top
  and upper shoulders (MI_TK_Ballast);
- T_TK_Cess: the shoulder's foot, where the ballast thins out over the formation's earth: scattered smaller stones,
  dust and earth with sparse grass, so the bed meets the grass of the slopes and the cess instead of ending in a flat
  band (MI_TK_Cess).

Both tile seamlessly over TILE metres (TEXTURED), the track meshes' UVs being planar in metres (track_build.py).
Each function returns float RGBA rows, bottom row first (Blender's image order), sRGB values 0..1, mid-grey on average
so that M_Belmonte's detail (doubled) keeps the instance's colour on average.
"""
import numpy as np

from train.textures import _noise, _rgba

SIZE = 1024


def _cells(size, count, seed):
    """Tileable Worley noise on a count x count jittered grid: (F1, F2, id of the nearest cell)."""
    rng = np.random.default_rng(seed)
    jitter = rng.random((count, count, 2))
    y, x = np.mgrid[0:size, 0:size] / size * count
    cx, cy = np.floor(x).astype(int), np.floor(y).astype(int)
    f1 = np.full((size, size), np.inf)
    f2 = np.full((size, size), np.inf)
    ids = np.zeros((size, size), int)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            gx, gy = cx + dx, cy + dy
            j = jitter[gy % count, gx % count]
            d = np.hypot(gx + j[..., 0] - x, gy + j[..., 1] - y)
            nearer = d < f1
            f2 = np.where(nearer, f1, np.minimum(f2, d))
            ids = np.where(nearer, (gy % count) * count + gx % count, ids)
            f1 = np.where(nearer, d, f1)
    return f1, f2, ids


def ballast(size=SIZE, seed=21):
    """Crushed-stone ballast: angular stones (Worley cells, flattened facets), each its own grey, dark voids."""
    rng = np.random.default_rng(seed)
    f1, f2, ids = _cells(size, 18, seed)
    edge = f2 - f1                                  # 0 on the boundary between two stones
    void = np.clip(edge / .3, 0., 1.) ** .9         # dark gaps between the stones
    pocket = np.where(rng.random(18 * 18)[ids] < .2, .35, 1.)   # stones sunk into the bed, in shadow
    tone = rng.uniform(.5, 1.05, 18 * 18)[ids]      # each stone its own grey
    warm = rng.uniform(-.04, .06, 18 * 18)[ids]
    facet = .7 + .45 * np.clip(1. - f1 * 1.3, 0., 1.)       # stones lit on their crowns
    grain = .85 + .3 * _noise(size, size, (96, 96), seed + 1, 2)
    v = (.12 + .7 * tone * facet * grain * pocket) * (.12 + .88 * void)
    rgb = np.stack([v * (1. + warm), v * (1. + .3 * warm), v * (1. - .4 * warm)], -1)
    # Dust and rust stains at the scale of a metre, so the bed does not repeat visibly.
    stain = _noise(size, size, (3, 3), seed + 2, 3)[..., None]
    rgb = rgb * (.85 + .3 * stain) * np.array([1.02, .98, .93])
    return _rgba(rgb)


def cess(size=SIZE, seed=33):
    """The bed's foot: smaller stones scattered over trodden earth, dust, and grass creeping in from the outside."""
    rng = np.random.default_rng(seed)
    f1, f2, ids = _cells(size, 26, seed)
    stone = (f1 < rng.uniform(.25, .5, 26 * 26)[ids]) & (rng.random(26 * 26)[ids] < .55)
    edge = np.clip((f2 - f1) / .2, 0., 1.)
    earth_n = _noise(size, size, (6, 6), seed + 1, 4)
    earth = np.stack([.45 + .1 * earth_n, .39 + .09 * earth_n, .31 + .07 * earth_n], -1)
    grey = rng.uniform(.38, .68, 26 * 26)[ids][..., None] * (.35 + .65 * edge[..., None])
    rgb = np.where(stone[..., None], grey * np.array([.95, .93, .88]), earth)
    grass_mask = np.clip((_noise(size, size, (5, 5), seed + 2, 3) - .52) * 5., 0., 1.)
    blades = _noise(size, size, (96, 96), seed + 3, 2)
    grass = np.stack([.27 + .1 * blades, .34 + .14 * blades, .14 + .05 * blades], -1)
    rgb = rgb * (1 - grass_mask[..., None] * (blades[..., None] > .45)) + \
        grass * (grass_mask[..., None] * (blades[..., None] > .45))
    rgb = rgb * (.88 + .24 * _noise(size, size, (48, 48), seed + 4, 2))[..., None]
    return _rgba(rgb)


ALL = {'T_TK_Ballast': ballast, 'T_TK_Cess': cess}
TEXTURED = {                # MI_TK_* instances with a detail texture: texture, metres per tile
    'MI_TK_Ballast': ('T_TK_Ballast', 1.),
    'MI_TK_Cess': ('T_TK_Cess', 1.5),
}
