"""Faceted sea-cliff rock for Brinecove: stacked prism outcrops, and smooth value noise for terrain materials.

The concept cliffs are pale, blocky stone in vertical columns and stepped drums, with jungle on every shelf. A sampled
heightfield alone reads as a smooth ramp with a striped texture, so the steep faces are dressed with irregular prisms
that protrude from the slope, split into drums so horizontal strata catch the light. Plain Python.
"""
import math
import random

import layout as L

TAU = math.pi * 2


def _hash(ix, iy, seed):
    n = (ix * 374761393 + iy * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0


def value_noise(x, y, seed=0):
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a = _hash(ix, iy, seed)
    b = _hash(ix + 1, iy, seed)
    c = _hash(ix, iy + 1, seed)
    d = _hash(ix + 1, iy + 1, seed)
    return (a + (b - a) * sx) + ((c + (d - c) * sx) - (a + (b - a) * sx)) * sy


def fbm(x, y, scale=60.0, octaves=4, seed=0):
    """Fractal value noise in [0, 1], with features about scale metres across."""
    total, amp, norm = 0.0, 1.0, 0.0
    fx, fy = x / scale, y / scale
    for o in range(octaves):
        total += value_noise(fx, fy, seed + o * 31) * amp
        norm += amp
        amp *= 0.5
        fx, fy = fx * 2.03, fy * 2.03
    return total / norm


def uphill(x, y, step=4.0):
    gx = (L.height(x + step, y) - L.height(x - step, y)) / (2 * step)
    gy = (L.height(x, y + step) - L.height(x, y - step)) / (2 * step)
    n = math.hypot(gx, gy)
    return (gx / n, gy / n, n) if n > 1e-6 else (0.0, 1.0, 0.0)


def prism(b, centre, z0, z1, radius, along, rng, mat, top_mat=None, squash=0.72, sides=None, tilt=0.0):
    """An irregular vertical prism, elongated along the contour, with a top tilted downhill by tilt metres."""
    sides = sides or rng.randint(5, 7)
    ax, ay = along
    px, py = -ay, ax  # out of the slope (downhill is -uphill; callers pass along = contour direction)
    ring = []
    for i in range(sides):
        a = TAU * i / sides + rng.uniform(-0.25, 0.25)
        r = radius * rng.uniform(0.72, 1.12)
        u, v = math.cos(a) * r, math.sin(a) * r * squash
        ring.append((centre[0] + ax * u + px * v, centre[1] + ay * u + py * v, u, v))
    shrink = rng.uniform(0.82, 0.96)
    bottom = [(x, y, z0) for x, y, _, _ in ring]
    top = []
    for x, y, u, v in ring:
        tx = centre[0] + (x - centre[0]) * shrink
        ty = centre[1] + (y - centre[1]) * shrink
        top.append((tx, ty, z1 - tilt * (v / max(radius * squash, 1e-3)) + rng.uniform(-0.25, 0.25)))
    for i in range(sides):
        j = (i + 1) % sides
        b.quad(bottom[i], bottom[j], top[j], top[i], mat)
    c = (sum(p[0] for p in top) / sides, sum(p[1] for p in top) / sides,
         sum(p[2] for p in top) / sides + rng.uniform(0.0, 0.35))
    for i in range(sides):
        b.tri(top[i], top[(i + 1) % sides], c, top_mat or mat)


def cliff_rocks(b, rng, spacing=6.0):
    """Dress every steep, dry face with stepped prism outcrops. Returns the number of outcrops."""
    placed = {}
    cell = spacing
    count = 0

    def free(x, y):
        gx, gy = int(x // cell), int(y // cell)
        for i in range(gx - 1, gx + 2):
            for j in range(gy - 1, gy + 2):
                for ox, oy in placed.get((i, j), ()):
                    if (ox - x) ** 2 + (oy - y) ** 2 < spacing * spacing:
                        return False
        return True

    for _ in range(320000):
        x = rng.uniform(L.VIEW_X_MIN + 60, L.VIEW_X_MAX - 60)
        y = rng.uniform(-700, 760)
        if L.is_water(x, y):
            continue
        z = L.height(x, y)
        if z < 2.5:
            continue
        ux, uy, grad = uphill(x, y)
        if grad < 0.85 or L.in_lot(x, y, 4.0) or L.on_shore_walkway(x, y, 5.0) or L.on_street(x, y, 4.0):
            continue
        if abs(x - L.WATERFALL[0]) < 22 and -10 <= y <= 60:
            continue
        if not free(x, y):
            continue
        placed.setdefault((int(x // cell), int(y // cell)), []).append((x, y))
        count += 1
        along = (-uy, ux)
        radius = rng.uniform(3.2, 6.0)
        # Push the outcrop out of the slope so its downhill faces stand proud of the heightfield.
        out = radius * rng.uniform(0.25, 0.55)
        cx, cy = x - ux * out, y - uy * out
        base = L.height(cx, cy) - 2.5
        # The top stops a little above the ground uphill of the outcrop, so it reads as a ledge, not a tower.
        crest = L.height(x + ux * radius * 1.2, y + uy * radius * 1.2) + rng.uniform(-0.8, 1.6)
        height = max(3.0, min(crest - base, rng.uniform(7.0, 17.0)))
        light = fbm(x, y, 90.0, 3, 17)
        palette = ('rock_light', 'rock_light', 'rock') if light > 0.45 else ('rock', 'rock_light', 'rock_dark')
        drums = 1 if height < 6 else rng.randint(2, 3)
        z0 = base
        for k in range(drums):
            z1 = base + height * (k + 1) / drums + rng.uniform(-0.4, 0.4)
            r = radius * (1.0 - 0.1 * k) * rng.uniform(0.92, 1.05)
            jitter = (rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6))
            top = 'jungle_dark' if k == drums - 1 and rng.random() < 0.45 else None
            prism(b, (cx + jitter[0] - ux * 0.35 * k, cy + jitter[1] - uy * 0.35 * k), z0, z1, r,
                  along, rng, palette[k % len(palette)], top, tilt=rng.uniform(0.2, 1.2))
            z0 = z1 - 0.15
        # A loose block or two at the foot.
        if rng.random() < 0.4:
            fx, fy = cx - ux * radius * 1.1, cy - uy * radius * 1.1
            fz = L.height(fx, fy)
            prism(b, (fx, fy), fz - 0.8, fz + rng.uniform(1.0, 2.6), radius * rng.uniform(0.3, 0.5),
                  along, rng, 'rock', squash=0.9)
    return count


def terrain_material(gx, gy, zavg, sl, i, j):
    """Material for one terrain cell from height, slope and smooth noise, never a per-cell dither pattern."""
    n = fbm(gx, gy, 70.0, 4, 3)
    m = fbm(gx, gy, 24.0, 3, 9)
    if sl > 0.85:
        return 'rock_dark' if m > 0.42 else 'rock'
    if sl > 0.62:
        return ('rock', 'jungle_dark', 'rock_light')[int(m * 2.999)] if n > 0.5 else 'jungle_dark'
    if zavg > 46:
        if n > 0.62:
            return 'autumn_olive'
        return 'jungle_light' if m > 0.55 else 'jungle'
    if n < 0.32:
        return 'jungle_dark'
    if n > 0.68 and m > 0.6:
        return 'autumn_olive'
    return 'jungle' if m < 0.55 else 'jungle_light'


def crag(b, x, y, base, top, radius, rng, count=9):
    """A craggy sea rock: a tall core prism ringed by shorter, leaning ones, pale on top and dark at the water."""
    for k in range(count):
        if k == 0:
            cx, cy, r, h = x, y, radius * 0.55, top
        else:
            a = TAU * k / (count - 1) + rng.uniform(-0.3, 0.3)
            d = radius * rng.uniform(0.35, 0.8)
            cx, cy = x + math.cos(a) * d, y + math.sin(a) * d
            r = radius * rng.uniform(0.25, 0.45)
            h = base + (top - base) * rng.uniform(0.25, 0.75) * (1.0 - d / radius * 0.6)
        along = (math.cos(rng.uniform(0, TAU)), 0.0)
        along = (along[0], math.sqrt(max(0.0, 1 - along[0] ** 2)))
        drums = max(1, int((h - base) / 5.0))
        z0 = base
        for j in range(drums):
            z1 = base + (h - base) * (j + 1) / drums
            mat = 'rock_dark' if z0 < 1.5 else ('rock', 'rock_light')[(j + k) % 2]
            prism(b, (cx + rng.uniform(-0.4, 0.4), cy + rng.uniform(-0.4, 0.4)), z0, z1, r * (1 - 0.12 * j),
                  along, rng, mat, 'rock_light', squash=rng.uniform(0.7, 1.0), tilt=rng.uniform(0.3, 1.5))
            z0 = z1 - 0.2


def canopy_hill(b, x, y, r, sx, sz, rng, spacing=16.0):
    """Cover a distant dome with rounded crown blobs, so far hills read as forest, not a green shell."""
    count = 0
    for _ in range(int(sx * r * r * 3.1416 / (spacing * spacing) * 1.6)):
        u, v = rng.uniform(-1, 1), rng.uniform(-1, 1)
        q = u * u + v * v
        if q > 0.92:
            continue
        px, py = x + u * r * sx, y + v * r
        pz = -5.0 + sz * r * math.sqrt(1.0 - q)
        if pz < 1.0:
            continue
        n = fbm(px, py, 120.0, 3, 41)
        mat = ('jungle_dark', 'jungle', 'jungle_light', 'autumn_olive', 'autumn_gold')[
            min(4, int(n * 4.2 + rng.uniform(-0.6, 0.6)) if n > 0 else 0)]
        rad = rng.uniform(7.5, 11.5)
        b.sphere((px, py, pz + rad * 0.15), rad, mat, (1.0, 1.0, 0.8), subdiv=0)
        count += 1
    return count
