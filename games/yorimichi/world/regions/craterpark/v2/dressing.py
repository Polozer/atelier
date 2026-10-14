"""Crater Park v2 against the caldera's dressing, and its own planting (docs/CRATERPARK.md, "Dressing"). Pure numpy.

The island's dressing (hidamari/layout.py, city.json) never stands on the r4 block: every instance on it or near it is
dropped (`craterpark.contains(margin=3)`: the block's 5 m cell mask grown by one cell), and the caldera's own groves,
boulders, scree and shrubs keep 7-16 m off it. In the r5 build the nearest instance is 5.5 m from the mask, and 17 m
or more from the tower and the lines' edges. `check` holds v2 to that rule. Every drawn face lies on the mask. Every
riding, side, coping and rail face lies at least RING metres inside the grown mask, the area no dressing instance may
enter. So nothing pokes through a ramp or floats over one, whatever the hidamari dressing does inside its own rules.
hidamari/layout.py is not edited: no world.hidamari rerun, and so no unreal.world rerun.

`plant` dresses the park's own ground, as layout.md 5 asks (planted ground between the lines): autumn and ochre
bushes on its upward ground faces, set on those faces and kept clear of every riding, side, coping and rail face by
CLEAR plus their own reach. They go into park.json `trees` (park-local Unreal cm, [x, y, z, yaw, scale]), which
ASuperUltraMegaPark::Spawn already plants as collision-free instances, like the Mega Park's. Only the craterpark steps
rerun when they change.
"""
import math

import numpy as np

from . import dsl

SPACING = 1.          # m between samples of a face when testing the footprint
CLEAR = 4.            # m: a bush's reach stays this far (in plan) from any riding, side, coping or rail face
CELL = 1.             # m: the plan grid that marks the park's built faces
FREE_MARGIN = 3.      # hidamari/layout.py drops every city instance within contains(margin=3) of the block
RING = 4.             # m: riding, side, coping and rail faces stay this far inside that dressing-free ground
BUSHES = (('Bush_HD_Autumn', .45, (.8, 1.5), 1.1), ('Bush_Ochre_A', .33, (1.1, 2.), .9), ('Bush_Ochre_B', .22, (1.1, 2.), .9))
"""(mesh, share, scale range, reach m per unit scale): the r4 hillside's mix (hidamari/layout.py)."""


class DressingError(ValueError):
    pass


def samples(triangles, spacing):
    """Points covering every triangle no farther than about `spacing` apart (megapark.placement.surface_samples)."""
    t = np.asarray(triangles, 'f8')
    if not len(t):
        return np.zeros((0, 3))
    edge = np.linalg.norm(t - np.roll(t, 1, 1), axis=-1).max(1)
    steps = np.maximum(np.ceil(edge / spacing).astype(int), 1)
    out = []
    for n in np.unique(steps):
        tri = t[steps == n]
        i, j = np.array([(i, j) for i in range(n + 1) for j in range(n + 1 - i)]).T / n
        w = np.stack([1 - i - j, i, j], -1)
        out.append(np.einsum('kv,tvc->tkc', w, tri).reshape(-1, 3))
    return np.concatenate(out)


def drawn(mesh):
    """(m, 3, 3) every face but the buried base, native metres."""
    return mesh.triangles()[mesh.role != dsl.ROLE[dsl.BASE]]


def check(mesh, placement, spacing=SPACING, ring=None):
    """Every drawn face of the park lies on the r4 block's footprint mask, and every riding, side, coping and rail face
    `ring` m (RING) inside the mask grown by one cell, where the island admits no dressing: {'ok', 'samples',
    'outside', 'near_edge', 'examples' (island x, y)}. Raises DressingError on either."""
    ring = RING if ring is None else ring

    def island(triangles):
        pts = samples(triangles, spacing)
        return placement.native_to_island(pts)[:, :2] if len(pts) else np.zeros((0, 2))
    every = island(drawn(mesh))
    built = np.isin(mesh.role, [dsl.ROLE[r] for r in (dsl.RIDING, dsl.SIDE, dsl.COPING, dsl.RAIL)])
    riding = island(mesh.triangles()[built])
    outside = every[~placement.contains(every[:, 0], every[:, 1])] if len(every) else every
    deep = np.ones(len(riding), bool)
    for k in range(16):
        a = 2 * math.pi * k / 16
        q = riding + ring * np.array([math.cos(a), math.sin(a)])
        if len(q):
            deep &= placement.contains(q[:, 0], q[:, 1], margin=FREE_MARGIN)
    edge = riding[~deep]
    report = {'ok': not len(outside) and not len(edge), 'samples': int(len(every)), 'outside': int(len(outside)),
              'near_edge': int(len(edge)), 'examples': np.round(np.concatenate([outside, edge])[:5], 2).tolist()}
    if len(outside):
        raise DressingError(f'{len(outside)} of {len(every)} face samples lie off the r4 block, where the caldera is '
                            f'dressed (island x, y e.g. {report["examples"]}); keep the park on placement.contains')
    if len(edge):
        raise DressingError(f'{len(edge)} riding, side, coping or rail samples lie within {ring:g} m of where the caldera '
                            f'may be dressed, at the r4 block\'s edge (island x, y e.g. {report["examples"]})')
    return report


def _noise(x, y, scale, seed):
    """Smooth value noise in [0, 1) (hidamari/mountains.py's kind), so bushes clump instead of spreading evenly."""
    q = np.stack([x, y], -1) / scale + seed * .618
    i = np.floor(q); f = q - i; f = f * f * (3 - 2 * f)

    def h(o):
        k = i + o
        return np.modf(np.abs(np.sin(k[..., 0] * 127.1 + k[..., 1] * 311.7 + seed) * 43758.5453))[0]
    a, b, c, d = h(np.array([0, 0])), h(np.array([1, 0])), h(np.array([0, 1])), h(np.array([1, 1]))
    return (a * (1 - f[..., 0]) + b * f[..., 0]) * (1 - f[..., 1]) + (c * (1 - f[..., 0]) + d * f[..., 0]) * f[..., 1]


def plant(mesh, seed=771, spacing=3., density=.1):
    """park.json `trees` for the park's own ground: {mesh name: [[x, y, z cm, yaw, scale], ...]} in park-local Unreal
    cm (ue(native) = 100 (x, z, y)). Each bush stands on an upward ground face (normal 0.55-0.97 up, as r4's
    hillside), 0.15 m into it, its reach plus CLEAR clear in plan of every riding, side, coping and rail face."""
    rng = np.random.default_rng(seed)
    t = mesh.triangles()
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    length = np.linalg.norm(n, axis=1)
    up = np.where(length > 0, n[:, 1] / np.maximum(length, 1e-12), 0.)
    ground = (mesh.role == dsl.ROLE[dsl.GROUND]) & (up > .55) & (up < .97)
    built = np.isin(mesh.role, [dsl.ROLE[r] for r in (dsl.RIDING, dsl.SIDE, dsl.COPING, dsl.RAIL)])
    seats = samples(t[ground], spacing)
    if not len(seats):
        return {}
    marks = samples(t[built], CELL / 2)
    taken = np.zeros((0, 2), 'i8') if not len(marks) else np.unique(np.floor(marks[:, [0, 2]] / CELL).astype('i8'), axis=0)
    occupied = {tuple(c) for c in taken.tolist()}
    clump = _noise(seats[:, 0], seats[:, 2], 26., 763) + .4 * _noise(seats[:, 0], seats[:, 2], 9., 764)
    keep = rng.random(len(seats)) < density * np.clip((clump / 1.4 - .35) / .25, 0., 1.)
    names = [b[0] for b in BUSHES]; shares = np.array([b[1] for b in BUSHES]); shares /= shares.sum()
    out = {}
    for x, y, z in seats[keep]:
        k = int(rng.choice(len(BUSHES), p=shares))
        name, _, (lo, hi), reach = BUSHES[k]
        scale = float(rng.uniform(lo, hi))
        r = int(math.ceil((CLEAR + reach * scale) / CELL))
        i, j = int(math.floor(x / CELL)), int(math.floor(z / CELL))
        if any((i + di, j + dj) in occupied for di in range(-r, r + 1) for dj in range(-r, r + 1)
               if di * di + dj * dj <= (r + 1) ** 2):
            continue
        out.setdefault(names[k], []).append([round(100 * x, 1), round(100 * z, 1), round(100 * (y - .15), 1),
                                             round(float(rng.uniform(0, 360)), 1), round(scale, 3)])
    return out


def clearance(instances, placement, near=60.):
    """The island's dressing near the block (city.json `instances`): {mesh: nearest distance in m from the block's
    footprint mask} for every instance within `near` m, for the record (all are 10 m or more)."""
    x0, y0, cell, _, mask = placement.footprint()
    cy, cx = np.nonzero(mask)
    centres = np.stack([x0 + (cx + .5) * cell, y0 + (cy + .5) * cell], -1)
    result = {}
    lo, hi = centres.min(0) - near, centres.max(0) + near
    for name, items in instances.items():
        a = np.asarray(items, 'f8').reshape(-1, 5)[:, :2]
        a = a[((a >= lo) & (a <= hi)).all(1)]
        if not len(a):
            continue
        d = np.full(len(a), np.inf)
        for s in range(0, len(centres), 2048):
            c = centres[s:s + 2048]
            # distance to a cell's square, not its centre
            dx = np.maximum(np.abs(a[:, None, 0] - c[None, :, 0]) - cell / 2, 0)
            dy = np.maximum(np.abs(a[:, None, 1] - c[None, :, 1]) - cell / 2, 0)
            d = np.minimum(d, np.hypot(dx, dy).min(1))
        if (d < near).any():
            result[name] = round(float(d.min()), 2)
    return result
