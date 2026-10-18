"""The east river and its two-tier waterfall: slot-canyon river, upper cascade, ledge pool and the 30 m sea fall.

layout.py carves the canyon, pool and lip notch into the terrain and owns the water levels; this module draws the
water and its dressing on top: curved ribbon sheets that follow the cliff, plunge foam and mist, wet rock, a rope
bridge over the slot and the ledge shrine. Plain Python.
"""
import math
import random

import layout as L
import rocks
from kit import bush, cell_uvs, fern, lantern_post, vine

TAU = math.pi * 2


def face_x(y, z, x_hi, x_lo=425.0):
    """The cliff face's x at height z on row y, searching seaward from x_hi."""
    if L.height(x_hi, y) <= z:
        return x_hi
    lo, hi = x_lo, x_hi
    for _ in range(24):
        mid = (lo + hi) / 2
        if L.height(mid, y) > z:
            hi = mid
        else:
            lo = mid
    return lo


def sheet(b, lip_x, y0, y1, top, bottom, rng, throw=4.0, segments=12):
    """One continuous curtain of falling water from a lip at lip_x toward -x, widening as it falls.

    The streak texture's alpha breaks the curtain up; a darker water body sits just behind it. Strips of separate
    ribbons overlapped into a shattered-glass staircase.
    """
    cols = max(4, int((y1 - y0) / 1.1))
    rows = max(segments, 20)
    u_span = (y1 - y0) / 5.0
    phase = rng.uniform(0, TAU)
    grid = []
    for k in range(rows + 1):
        s = k / rows
        z = top - (top - bottom) * s
        spread = 0.18 * (y1 - y0) * s * s
        row = []
        for c in range(cols + 1):
            t = c / cols
            y = y0 - spread + (y1 - y0 + 2 * spread) * t
            # Ballistic throw off the lip, a little ripple across the width, and never inside the rock.
            x = lip_x - throw * math.sqrt(s) - 0.3 + 0.35 * math.sin(t * 9.0 + phase) * s
            x = min(x, face_x(y, z, lip_x) - 0.8)
            row.append((x, y, z, t * u_span, (top - z) / 7.0))
        grid.append(row)
    out = (-1.0, 0.0, 0.1)
    for k in range(rows):
        for c in range(cols):
            p = (grid[k][c], grid[k][c + 1], grid[k + 1][c + 1], grid[k + 1][c])
            b.face([q[:3] for q in p], 'waterfall', [(q[3], q[4]) for q in p], (out, out, out, out))
    # Loose strands peel off both edges, so the curtain has ragged sides instead of a cut slab.
    for side in (0, cols):
        for _ in range(3):
            y = grid[0][side][1] + (rng.uniform(-1.6, -0.3) if side == 0 else rng.uniform(0.3, 1.6))
            w = rng.uniform(0.4, 0.9)
            reach = rng.uniform(0.5, 1.0)
            u0 = rng.uniform(0, 3)
            prev = None
            for k in range(rows + 1):
                s = k / rows * reach
                z = top - (top - bottom) * s
                x = min(lip_x - throw * math.sqrt(s) - 0.2, face_x(y, z, lip_x) - 0.6)
                cur = ((x, y - w / 2, z), (x, y + w / 2, z), (top - z) / 7.0)
                if prev:
                    b.face((prev[0], prev[1], cur[1], cur[0]), 'waterfall',
                           ((u0, prev[2]), (u0 + 0.15, prev[2]), (u0 + 0.15, cur[2]), (u0, cur[2])), (out,) * 4)
                prev = cur


def mist(b, x, y, z, radius, count, rng):
    """Spray at a plunge: squashed foam domes and crossed alpha mist cards."""
    for _ in range(count):
        a = rng.uniform(0, TAU)
        d = rng.uniform(0, radius)
        px, py = x + math.cos(a) * d, y + math.sin(a) * d
        pz = z + rng.uniform(0.2, 2.5) + d * 0.25
        size = rng.uniform(3.0, 8.0)
        for k in range(3):
            yaw = k * math.pi / 3 + rng.uniform(-0.2, 0.2)
            b.card((px, py, pz + size * 0.3), (math.cos(yaw), math.sin(yaw), 0.0), size, size * 0.8, 'mist',
                   ((0, 0), (1, 0), (1, 1), (0, 1)))
        if rng.random() < 0.5:
            foam_patch(b, px, py, z + 0.06, rng.uniform(3.0, 7.0), rng)


def foam_patch(b, x, y, z, size, rng):
    """A soft, ragged foam patch lying on the water: a flat alpha card at a random angle, never a white tile."""
    a = rng.uniform(0, TAU)
    ca, sa = math.cos(a), math.sin(a)
    hx, hy = size / 2, size * rng.uniform(0.3, 0.5)
    pts = [(x + ca * u - sa * v, y + sa * u + ca * v, z) for u, v in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))]
    b.face(pts, 'spray', ((0, 0), (1, 0), (1, 1), (0, 1)))


def pool_surface(b, x0, x1, y_half, level, mat, step=3.0):
    """A flat water grid clipped to the carved bed, so the shoreline follows the terrain."""
    x = x0
    while x < x1:
        y = L.GORGE_Y - y_half
        while y < L.GORGE_Y + y_half:
            corners = ((x, y), (x + step, y), (x + step, y + step), (x, y + step))
            if any(L.height(cx, cy) < level for cx, cy in corners):
                b.quad(*[(cx, cy, level) for cx, cy in corners], mat)
            y += step
        x += step


def river_surface(b, x0, x1, half=5.6, step=4.0):
    x = x0
    while x < x1:
        za, zb = L.river_level(x), L.river_level(x + step)
        b.quad((x, L.GORGE_Y - half, za), (x + step, L.GORGE_Y - half, zb),
               (x + step, L.GORGE_Y + half, zb), (x, L.GORGE_Y + half, za), 'water_mid')
        x += step


def waterfall(b):
    rng = random.Random(5501)
    g = L.gorge_levels()
    lower, upper, pool, river = g['lower'], g['upper'], g['pool'], g['river']
    # River down the slot canyon, with broken white water where it steepens toward the lip.
    river_surface(b, upper - 3.0, 690.0)
    for _ in range(26):
        x = rng.uniform(upper - 2.0, upper + 40.0)
        y = L.GORGE_Y + rng.uniform(-4.0, 4.0)
        zz = L.river_level(x) + 0.05
        s = rng.uniform(0.8, 2.2)
        foam_patch(b, x, y, zz, s * 1.4, rng)
    # Upper cascade: out of the slot onto the ledge pool.
    upper_lip = face_x(L.GORGE_Y, river - 0.5, upper + 4.0) + 0.6
    sheet(b, upper_lip, L.GORGE_Y - 4.8, L.GORGE_Y + 4.8, river + 0.2, pool - 0.3, rng, throw=2.5, segments=8)
    mist(b, upper_lip - 4.0, L.GORGE_Y, pool, 5.0, 18, rng)
    pool_surface(b, lower - 4.0, upper_lip, 14.0, pool, 'water_shallow')
    # Lower fall: the pool spills through the notch in a wide, 30 m sheet into the sea.
    lower_lip = face_x(L.GORGE_Y, pool - 0.6, lower + 4.0) + 0.4
    sheet(b, lower_lip, L.GORGE_Y - 8.0, L.GORGE_Y + 8.0, pool, -0.4, rng, throw=4.5, segments=24)
    # A second, slightly proud layer fills the gaps, so the curtain reads white and continuous.
    sheet(b, lower_lip - 0.5, L.GORGE_Y - 6.5, L.GORGE_Y + 6.5, pool - 0.3, -0.4, rng, throw=5.2, segments=24)
    # A narrower second ribbon set beside it, as in the painting's paired falls.
    sheet(b, face_x(L.GORGE_Y + 10.5, pool - 2.5, lower + 2.0) + 0.3, L.GORGE_Y + 9.0, L.GORGE_Y + 12.0,
          pool - 2.0, 0.0, rng, throw=3.0, segments=12)
    base_x = face_x(L.GORGE_Y, 0.5, lower) - 6.0
    mist(b, base_x, L.GORGE_Y, 0.0, 13.0, 40, rng)
    for k in range(3):
        rocks_ring = 10.0 + k * 5.0
        for j in range(16):
            a = TAU * j / 16 + k * 0.3
            px, py = base_x + math.cos(a) * rocks_ring * 0.8, L.GORGE_Y + math.sin(a) * rocks_ring
            if L.height(px, py) > 1.0:
                continue
            foam_patch(b, px, py, 0.08, rng.uniform(2.5, 5.5), rng)
    # Wet boulders in the plunge and on the pool lip, and dark stone framing the falls.
    for _ in range(14):
        a = rng.uniform(0, TAU)
        d = rng.uniform(7.0, 16.0)
        px, py = base_x + math.cos(a) * d * 0.7, L.GORGE_Y + math.sin(a) * d
        rocks.prism(b, (px, py), -2.0, rng.uniform(0.8, 3.2), rng.uniform(1.2, 2.8), (0.0, 1.0), rng, 'rock_dark',
                    'rock', squash=0.9, tilt=0.5)
    for side in (-1, 1):
        for k in range(7):
            yy = L.GORGE_Y + side * rng.uniform(9.5, 15.0)
            xx = lower - rng.uniform(1.0, 9.0)
            top = L.height(xx + 3.0, yy) + rng.uniform(-1.0, 1.5)
            rocks.prism(b, (xx, yy), L.height(xx, yy) - 3.0, top, rng.uniform(2.2, 3.6), (0.0, 1.0), rng,
                        'rock_dark', 'jungle_dark', squash=0.8, tilt=0.8)
    for _ in range(10):
        px = rng.uniform(lower + 2.0, upper_lip - 3.0)
        py = L.GORGE_Y + rng.choice((-1, 1)) * rng.uniform(4.0, 11.0)
        rocks.prism(b, (px, py), pool - 1.6, pool + rng.uniform(0.3, 1.4), rng.uniform(0.8, 1.8), (1.0, 0.0), rng,
                    'rock_dark', 'rock', squash=0.9, tilt=0.3)
    # Ferns, moss mounds and hanging vines on the wet canyon walls.
    for _ in range(60):
        px = rng.uniform(lower - 6.0, upper + 60.0)
        py = L.GORGE_Y + rng.choice((-1, 1)) * rng.uniform(6.0, 16.0)
        pz = L.height(px, py)
        if L.slope(px, py) > 1.6:
            vine(b, px, py, pz + 0.5, rng.uniform(4.0, 12.0), rng)
        elif rng.random() < 0.5:
            fern(b, px, py, pz, rng.uniform(0, 360), rng.uniform(0.9, 1.5), rng)
        else:
            bush(b, px, py, pz, 0.0, rng.uniform(0.6, 1.1), rng)
    rope_bridge(b, upper + 9.0)
    shrine(b, rng, lower, upper_lip)


def rope_bridge(b, x):
    """A sagging plank bridge across the slot canyon above the upper cascade."""
    y0, y1 = L.GORGE_Y - 17.0, L.GORGE_Y + 17.0
    z0, z1 = L.height(x, y0) + 0.6, L.height(x, y1) + 0.6
    for y, z in ((y0, z0), (y1, z1)):
        for side in (-1, 1):
            b.beam((x + side * 1.3, y, z - 2.5), (x + side * 1.3, y, z + 1.6), 0.26, 'wood_dark')
    planks = 22
    for i in range(planks + 1):
        t = i / planks
        y = y0 + (y1 - y0) * t
        z = z0 + (z1 - z0) * t - 2.4 * math.sin(math.pi * t)
        b.box((x, y, z), (2.6, 0.62, 0.12), 'wood_light' if i % 4 else 'wood', (i % 3 - 1) * 3.0)
    for side in (-1, 1):
        b.rope((x + side * 1.3, y0, z0 + 1.2), (x + side * 1.3, y1, z1 + 1.2), 2.3, 0.07, segments=12)
        b.rope((x + side * 1.3, y0, z0), (x + side * 1.3, y1, z1), 2.4, 0.06, segments=12)
        for i in range(1, 9):
            t = i / 9
            y = y0 + (y1 - y0) * t
            z = z0 + (z1 - z0) * t - 2.4 * math.sin(math.pi * t)
            b.beam((x + side * 1.3, y, z), (x + side * 1.3, y, z + 1.2 + 0.1 * math.sin(math.pi * t)), 0.04, 'rope')


def shrine(b, rng, lower, upper_lip):
    """A small stone shrine with lanterns on the ledge beside the pool, facing the harbor."""
    sx, sy = (lower + upper_lip) / 2 + 2.0, L.GORGE_Y + 21.0
    sz = L.height(sx, sy)
    b.box((sx, sy, sz + 0.3), (7.4, 6.2, 0.8), 'stone')
    b.box((sx, sy, sz + 2.1), (4.4, 3.6, 3.0), 'stone_light')
    b.box((sx - 2.25, sy, sz + 1.6), (0.3, 1.6, 2.2), 'wood_dark')
    b.hip_roof((sx, sy, sz + 3.6), 4.4, 3.6, sz + 3.6, 1.8, 'roof_teal', 0, overhang=0.7)
    for dy in (-2.4, 2.4):
        lantern_post(b, sx - 3.4, sy + dy, sz + 0.6, 2.2)
    for k in range(4):
        b.box((sx - 4.2 - k * 0.8, sy, sz + 0.5 - k * 0.35), (0.8, 2.4, 0.3), 'stone')
    for _ in range(5):
        b.card((sx + rng.uniform(-3, 3), sy + 3.2, sz + rng.uniform(1.5, 3.5)), (0, -1, 0.2), 1.4, 1.4,
               'leaf_mid', cell_uvs(rng.randrange(4)))
