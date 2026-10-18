"""Reusable Brinecove pieces: houses, taverns, wharf furniture, ships, palms and landmarks."""
import math
import random
from geom import Builder

TAU = math.pi * 2


def local(cx, cy, yaw, lx, ly):
    a = math.radians(yaw)
    return cx + lx * math.cos(a) - ly * math.sin(a), cy + lx * math.sin(a) + ly * math.cos(a)


def window(b, cx, cy, yaw, lx, ly, z, w=1.3, h=1.6, shutters=True, warm=False):
    x, y = local(cx, cy, yaw, lx, ly)
    # Recessed dark glass and a chunky painted frame.
    b.box((x, y, z + h / 2), (w, 0.12, h), 'glass_warm' if warm else 'glass', yaw)
    b.box((x, y, z + h / 2), (w + 0.22, 0.08, 0.14), 'cream', yaw)
    b.box((x, y, z), (w + 0.22, 0.08, 0.14), 'cream', yaw)
    b.box((x, y, z + h), (w + 0.22, 0.08, 0.14), 'cream', yaw)
    b.box((x, y, z + h / 2), (0.11, 0.08, h), 'cream', yaw)
    b.box((x, y, z + h / 2), (w + 0.22, 0.08, 0.11), 'cream', yaw)
    if shutters:
        for side in (-1, 1):
            sx, sy = local(cx, cy, yaw, lx + side * (w / 2 + 0.26), ly)
            b.box((sx, sy, z + h / 2), (0.22, 0.10, h + 0.12), 'wood', yaw)
            for i in range(3):
                b.beam((sx - 0.08, sy - 0.07, z + 0.25 + i * h / 3),
                       (sx + 0.08, sy - 0.07, z + 0.25 + i * h / 3), 0.05, 'wood_dark')


def side_window(b, cx, cy, yaw, lx, ly, z, w=1.15, h=1.45, shutters=True, warm=False):
    """A window on a wall whose normal runs along local X."""
    x, y = local(cx, cy, yaw, lx, ly)
    b.box((x, y, z + h / 2), (0.12, w, h), 'glass_warm' if warm else 'glass', yaw)
    b.box((x, y, z + h / 2), (0.08, w + 0.22, 0.14), 'cream', yaw)
    b.box((x, y, z), (0.08, w + 0.22, 0.14), 'cream', yaw)
    b.box((x, y, z + h), (0.08, w + 0.22, 0.14), 'cream', yaw)
    b.box((x, y, z + h / 2), (0.08, 0.11, h), 'cream', yaw)
    b.box((x, y, z + h / 2), (0.08, w + 0.22, 0.11), 'cream', yaw)
    if shutters:
        for side in (-1, 1):
            sy = ly + side * (w / 2 + 0.25)
            sx, syy = local(cx, cy, yaw, lx + 0.02, sy)
            b.box((sx, syy, z + h / 2), (0.10, 0.22, h + 0.12), 'wood', yaw)
            for i in range(3):
                b.box((sx, syy, z + 0.24 + i * h / 3), (0.12, 0.17, 0.04), 'wood_dark', yaw)


def dormer(b, cx, cy, yaw, lx, ly, z, roof='roof_terra'):
    x, y = local(cx, cy, yaw, lx, ly)
    b.box((x, y, z + 1.15), (2.8, 2.5, 2.3), 'cream', yaw)
    b.gable_roof((x, y, z + 2.25), 3.3, 3.0, z + 2.25, 1.25, roof, yaw, ridge='y', overhang=0.35)
    window(b, x, y, yaw, 0, -1.3, z + 0.35, 1.05, 1.35, False, rng_bool(cx, cy, lx))


def rng_bool(x, y, seed=0):
    return ((int(x * 17 + y * 31 + seed * 13) & 7) == 3)


def flower_box(b, cx, cy, yaw, lx, ly, z):
    x, y = local(cx, cy, yaw, lx, ly)
    b.box((x, y, z), (1.25, 0.32, 0.28), 'wood_dark', yaw)
    for i in range(4):
        px, py = local(cx, cy, yaw, lx - 0.45 + i * 0.3, ly - 0.1)
        b.sphere((px, py, z + 0.22), 0.18, ('coral', 'gold', 'cream', 'jungle')[i % 4],
                 (1.0, 0.9, 0.9), subdiv=0)


def arcade(b, cx, cy, yaw, width, z, depth=2.0, columns=4):
    """A shallow stone arcade in front of a shop: depth and shadow at street level."""
    for i in range(columns + 1):
        lx = -width / 2 + width * i / columns
        px, py = local(cx, cy, yaw, lx, -depth)
        b.cylinder((px, py, z), (px, py, z + 3.05), 0.24, 'stone_light', 8)
        b.box((px, py, z + 0.2), (0.75, 0.75, 0.35), 'stone', yaw)
        b.box((px, py, z + 3.2), (0.75, 0.75, 0.3), 'stone', yaw)
    px, py = local(cx, cy, yaw, 0, -depth)
    b.box((px, py, z + 3.5), (width + 0.8, depth + 0.5, 0.5), 'stone_light', yaw)
    b.box((px, py, z + 3.85), (width + 1.0, depth + 0.7, 0.22), 'stone_dark', yaw)
    # A dark recess behind the columns keeps the arcade from reading as a fence.
    rx, ry = local(cx, cy, yaw, 0, -depth * 0.15)
    b.box((rx, ry, z + 1.55), (width - 2.5, 0.14, 3.0), 'wood_dark', yaw)


def door(b, cx, cy, yaw, lx, ly, z, w=1.6, h=2.6):
    x, y = local(cx, cy, yaw, lx, ly)
    b.box((x, y, z + h / 2), (w, 0.16, h), 'wood_dark', yaw)
    b.box((x, y, z + h + 0.12), (w + 0.35, 0.24, 0.22), 'wood', yaw)
    for side in (-1, 1):
        sx, sy = local(cx, cy, yaw, lx + side * (w / 2 + 0.14), ly)
        b.box((sx, sy, z + h / 2), (0.18, 0.20, h + 0.16), 'wood', yaw)
    b.box((x, y + 0.02, z + h * 0.55), (0.09, 0.06, 0.09), 'gold', yaw)


def awning(b, cx, cy, yaw, width, z, depth=2.3, colors=('canvas', 'canvas_red')):
    n = max(3, round(width / 2.2))
    for i in range(n):
        x0 = -width / 2 + width * i / n
        x1 = -width / 2 + width * (i + 1) / n
        a = local(cx, cy, yaw, x0, -1.0)
        c = local(cx, cy, yaw, x1, -1.0)
        d = local(cx, cy, yaw, x1, -depth)
        e = local(cx, cy, yaw, x0, -depth)
        b.quad((a[0], a[1], z), (c[0], c[1], z),
               (d[0], d[1], z - 0.55), (e[0], e[1], z - 0.55), colors[i % len(colors)])
    # Hanging valance and support poles.
    for i in range(n + 1):
        x0 = -width / 2 + width * i / n
        p = local(cx, cy, yaw, x0, -depth)
        b.box((p[0], p[1], z - 0.75), (0.06, 0.06, 0.40), colors[i % len(colors)])
    for side in (-1, 1):
        p = local(cx, cy, yaw, side * width * 0.46, -depth)
        b.beam((p[0], p[1], groundless(z)), (p[0], p[1], z - 0.45), 0.12, 'wood_dark')


def groundless(z):
    """A safety floor for awning poles: the caller has already placed the building on its pad."""
    return max(0.0, z - 3.0)


def balcony(b, cx, cy, yaw, width, z, depth=1.8):
    # Deck, brackets, rail.
    x, y = local(cx, cy, yaw, 0, -depth / 2 - 0.2)
    b.box((x, y, z), (width, depth, 0.24), 'wood', yaw)
    for side in (-1, 1):
        px, py = local(cx, cy, yaw, side * width * 0.42, -0.35)
        b.beam((px, py, z - 1.8), (px, py, z), 0.20, 'wood_dark')
    for i in range(7):
        lx = -width / 2 + width * i / 6
        px, py = local(cx, cy, yaw, lx, -depth + 0.05)
        b.beam((px, py, z), (px, py, z + 1.1), 0.10, 'wood')
    px, py = local(cx, cy, yaw, 0, -depth + 0.05)
    b.beam((px - width / 2, py, z + 1.05), (px + width / 2, py, z + 1.05), 0.14, 'wood')
    # A couple of hanging lanterns under the balcony.
    for lx in (-width * 0.3, width * 0.3):
        px, py = local(cx, cy, yaw, lx, -depth + 0.05)
        b.beam((px, py, z), (px, py, z - 0.42), 0.04, 'metal')
        b.box((px, py, z - 0.62), (0.28, 0.28, 0.38), 'lantern', yaw)


def sign(b, cx, cy, yaw, z, side=1, icon='fish'):
    """A hanging tavern sign; the painted icon is simplified to a few readable shapes."""
    ax, ay = local(cx, cy, yaw, side * 0.4, -0.2)
    bx, by = local(cx, cy, yaw, side * (0.4 + 2.0), -0.2)
    b.beam((ax, ay, z + 1.7), (bx, by, z + 1.7), 0.11, 'wood_dark')
    b.beam((bx, by, z + 1.7), (bx, by, z + 0.4), 0.06, 'metal')
    hx, hy = local(cx, cy, yaw, side * (0.4 + 1.5), -0.2)
    b.box((hx, hy, z + 0.6), (0.95, 0.12, 1.15), 'wood_dark', yaw)
    if icon == 'fish':
        b.sphere((hx, hy - 0.09, z + 0.66), 0.34, 'cream', (1.5, 0.25, 0.72))
        b.tri((hx + 0.46, hy - 0.10, z + 0.66), (hx + 0.78, hy - 0.10, z + 0.92),
              (hx + 0.78, hy - 0.10, z + 0.40), 'cream')
    elif icon == 'mug':
        b.cylinder((hx, hy - 0.10, z + 0.35), (hx, hy - 0.10, z + 0.92), 0.26, 'gold', 8)
        b.ring((hx + 0.27, hy - 0.10, z + 0.63), 0.19, 0.05, 'gold', axis='x', sides=8)
    else:
        b.sphere((hx, hy - 0.10, z + 0.68), 0.33, 'cream', (1.0, 0.25, 1.0))


def timber_frame(b, x, y, z, w, d, h, yaw, floors):
    # Front and back posts, floor bands and corner braces.
    for yy in (-d / 2 + 0.10, d / 2 - 0.10):
        n = max(3, round(w / 4.2))
        for i in range(n + 1):
            lx = -w / 2 + w * i / n
            px, py = local(x, y, yaw, lx, yy)
            b.beam((px, py, z + 1.1), (px, py, z + h - 0.45), 0.18, 'wood_dark')
        for f in range(1, floors + 1):
            zz = z + h * f / (floors + 0.2)
            px, py = local(x, y, yaw, 0, yy)
            b.beam((px - w / 2, py, zz), (px + w / 2, py, zz), 0.16, 'wood')
        for side in (-1, 1):
            px, py = local(x, y, yaw, side * (w / 2 - 0.12), yy)
            b.beam((px, py, z + 1.1), (px, py, z + h - 0.4), 0.20, 'wood_dark')
            qx, qy = local(x, y, yaw, side * (w / 2 - 2.2), yy)
            b.beam((qx, qy, z + 1.2), (px, py, z + 4.0), 0.14, 'wood_dark')


def building(b, spec, rng):
    key, x, y, z, w, d, h, floors, style, yaw, roof = spec
    walls = {
        'tavern': ['cream', 'ochre', 'coral', 'plaster'],
        'house': ['plaster', 'cream', 'sage_wall', 'ochre'],
        'shop': ['ochre', 'coral', 'teal_wall', 'cream'],
        'warehouse': ['wood_light', 'wood', 'stone_light'],
        'shack': ['wood_light', 'wood', 'plaster'],
    }[style]
    wall = walls[sum(map(ord, key)) % len(walls)]
    if style == 'warehouse':
        b.box((x, y, z + h / 2), (w, d, h), wall, yaw)
        b.box((x, y, z + 1.0), (w + 0.5, d + 0.5, 2.0), 'stone', yaw)
        b.box((x, y, z + h - 0.2), (w + 0.4, d + 0.4, 0.45), 'wood_dark', yaw)
        for i in range(4):
            px, py = local(x, y, yaw, -w / 2 + 0.5 + i * (w - 1) / 3, -d / 2 - 0.04)
            b.beam((px, py, z + 2.0), (px, py, z + h - 0.4), 0.22, 'wood_dark')
        # Big loading doors and a hoist beam.
        b.box((x, y - d / 2 - 0.06, z + 2.4), (w * 0.46, 0.14, 4.2), 'wood', yaw)
        b.box((x, y, z + h + 0.15), (w * 0.18, 0.25, 0.4), 'wood_dark', yaw)
        bx, by = local(x, y, yaw, 0, -d / 2 - 2.8)
        b.beam((x, y, z + h + 0.15), (bx, by, z + h + 0.15), 0.22, 'wood_dark')
        b.rope((bx, by, z + h + 0.1), (bx, by, z + 4.2), sag=0.0, radius=0.05)
    else:
        b.box((x, y, z + h / 2), (w, d, h), wall, yaw)
        b.box((x, y, z + 0.65), (w + 0.4, d + 0.4, 1.3), 'stone', yaw)
        if style in ('tavern', 'house', 'shop'):
            timber_frame(b, x, y, z, w, d, h, yaw, floors)
        has_arcade = style in ('tavern', 'shop') and w >= 14.0 and rng.random() < 0.48
        if has_arcade:
            arcade(b, x, y, yaw, w * 0.74, z + 0.15, 2.0, max(2, int(w / 6)))
        b.box((x, y, z + h - 0.18), (w + 0.5, d + 0.5, 0.5), 'wood_dark', yaw)
        # Front door, windows, awnings and gallery.
        door(b, x, y, yaw, rng.choice((-w * 0.28, 0.0, w * 0.28)), -d / 2 - 0.10, z + 0.02,
             w=1.5 if style != 'shack' else 1.2, h=2.4 if style != 'shack' else 2.1)
        face_x, face_y = local(x, y, yaw, 0, -d / 2)
        cols = max(2, int(w / 7))
        for f in range(floors):
            zz = z + 2.0 + f * (h - 2.2) / max(1, floors)
            for i in range(cols):
                lx = -w / 2 + w * (i + 0.5) / cols
                if f == 0 and abs(lx) < 2.2:
                    continue
                window(b, x, y, yaw, lx, -d / 2 - 0.05, zz, 1.15, 1.45,
                       shutters=style != 'shack', warm=(rng.random() < 0.18))
                if f > 0 and rng.random() < 0.22:
                    flower_box(b, x, y, yaw, lx, -d / 2 - 0.42, zz - 0.18)
            for side in (-1, 1):
                side_window(b, x, y, yaw, side * (w / 2 + 0.04), -d * 0.24, zz,
                            1.05, 1.35, shutters=style != 'shack', warm=(rng.random() < 0.14))
                if d > 19.0:
                    side_window(b, x, y, yaw, side * (w / 2 + 0.04), d * 0.22, zz,
                                1.05, 1.35, shutters=style != 'shack', warm=(rng.random() < 0.14))
            if f == 1 and style in ('tavern', 'shop', 'house') and (style == 'tavern' or rng.random() < 0.48):
                by = z + min(h - 1.2, max(5.0, h * 0.52))
                balcony(b, face_x, face_y, yaw, w * 0.78, by)
                if rng.random() < 0.6:
                    for k in range(3):
                        px, py = local(x, y, yaw, -w * 0.22 + k * w * 0.2, -d / 2 - 2.25)
                        b.quad((px - 0.55, py, by - 0.25), (px + 0.55, py, by - 0.25),
                               (px + 0.55, py + 0.04, by - 2.4), (px - 0.55, py + 0.04, by - 2.4),
                               ('canvas', 'canvas_red', 'canvas_teal')[k])
            if f == 0 and style in ('shop', 'tavern') and not has_arcade:
                awning(b, face_x, face_y, yaw, w * 0.72, z + 3.0, 2.1,
                       ('canvas', 'canvas_red') if rng.random() < 0.55 else ('canvas', 'canvas_teal'))
        # Bougainvillea and creepers break up the flat plaster and tie the
        # dressed waterfront to the jungle above it.
        if rng.random() < 0.34:
            for _ in range(rng.randint(1, 2)):
                lx = rng.uniform(-w * 0.44, w * 0.44)
                px, py = local(x, y, yaw, lx, -d / 2 - 0.16)
                vine(b, px, py, z + h - 0.4, rng.uniform(2.4, 6.2), rng)
    # Roof chooses a flat terrace, gable or hip silhouette.
    flat_roof = style not in ('warehouse', 'shack') and h > 9.0 and rng.random() < 0.14
    if flat_roof:
        b.box((x, y, z + h + 0.28), (w + 0.55, d + 0.55, 0.55), 'stone', yaw)
        for sx in (-1, 1):
            px, py = local(x, y, yaw, sx * (w / 2 + 0.1), 0)
            b.box((px, py, z + h + 0.95), (0.45, d + 0.5, 0.9), 'stone_light', yaw)
        for sy in (-1, 1):
            px, py = local(x, y, yaw, 0, sy * (d / 2 + 0.1))
            b.box((px, py, z + h + 0.95), (w + 0.5, 0.45, 0.9), 'stone_light', yaw)
        for k in range(2):
            px, py = local(x, y, yaw, -w * 0.25 + k * w * 0.5, -d * 0.18)
            b.cylinder((px, py, z + h + 0.6), (px, py, z + h + 1.4), 0.55, 'clay', 8, radius_b=0.45)
            palm(b, px, py, z + h + 1.3, 0, 0.30, rng)
    elif style == 'warehouse':
        b.gable_roof((x, y, z + h + 0.2), w, d, z + h + 0.2, min(4.2, w * 0.13), roof, yaw, ridge='x', overhang=1.0)
    elif style == 'shack':
        b.gable_roof((x, y, z + h + 0.1), w, d, z + h + 0.1, 2.4, roof, yaw, ridge='y', overhang=0.9)
    elif rng.random() < 0.45:
        b.gable_roof((x, y, z + h + 0.2), w, d, z + h + 0.2, 2.8 + (h % 3) * 0.25, roof, yaw,
                     ridge='y' if rng.random() < 0.5 else 'x', overhang=0.9)
    else:
        b.hip_roof((x, y, z + h + 0.2), w, d, z + h + 0.2, 2.6 + (h % 4) * 0.2, roof, yaw, overhang=0.9)
    if not flat_roof and style != 'warehouse' and h > 9.5 and rng.random() < 0.5:
        dormer(b, x, y, yaw, rng.choice((-w * 0.22, 0.0, w * 0.22)), -d * 0.10,
               z + h + 0.35, roof)
    # Chimneys, roof vents, and a bracket sign on roughly every third building.
    if style != 'warehouse' and rng.random() < 0.75:
        side = rng.choice((-1, 1))
        px, py = local(x, y, yaw, side * w * 0.25, d * 0.10)
        b.box((px, py, z + h + 2.1), (0.9, 0.9, 2.8), 'stone', yaw)
        b.box((px, py, z + h + 3.55), (1.2, 1.2, 0.25), 'stone_dark', yaw)
    if style in ('tavern', 'shop') and rng.random() < 0.8:
        sign(b, face_x, face_y, yaw, z + 2.8, side=rng.choice((-1, 1)),
             icon=rng.choice(('fish', 'mug', 'wheel', 'fish')))
    if style in ('tavern', 'shop', 'house') and rng.random() < 0.45:
        lx = rng.choice((-w * 0.38, w * 0.38))
        px, py = local(x, y, yaw, lx, -d / 2 - 0.35)
        b.beam((px, py, z + 4.05), (px, py, z + 3.65), 0.05, 'metal')
        b.box((px, py, z + 3.48), (0.36, 0.36, 0.48), 'lantern', yaw)
    # Barrels and crates against the facade make the street feel occupied.
    if style in ('tavern', 'shop', 'house') and rng.random() < 0.55:
        for _ in range(rng.randint(1, 3)):
            lx = rng.uniform(-w * 0.42, w * 0.42)
            px, py = local(x, y, yaw, lx, -d / 2 - rng.uniform(0.8, 1.8))
            barrel(b, px, py, z, rng.uniform(0.75, 1.0))


def barrel(b, x, y, z, s=1.0):
    b.cylinder((x, y, z), (x, y, z + 1.05 * s), 0.42 * s, 'wood', 9, radius_b=0.36 * s)
    for zz in (0.18, 0.55, 0.9):
        b.cylinder((x, y, z + zz * s), (x, y, z + (zz + 0.04) * s), 0.44 * s, 'metal', 9)


def crate(b, x, y, z, size=0.9, yaw=0.0):
    b.box((x, y, z + size / 2), (size, size * 0.9, size), 'wood_light', yaw)
    for dz in (0.16, size - 0.16):
        b.box((x, y, z + dz), (size + 0.04, size * 0.9 + 0.04, 0.08), 'wood_dark', yaw)


def lantern_post(b, x, y, z, height=3.2, yaw=0.0):
    b.cylinder((x, y, z), (x, y, z + height), 0.09, 'metal', 6)
    b.box((x, y, z + height + 0.28), (0.46, 0.46, 0.56), 'lantern', yaw)
    b.box((x, y, z + height + 0.62), (0.58, 0.58, 0.10), 'metal', yaw)


def bollard(b, x, y, z):
    b.cylinder((x, y, z), (x, y, z + 0.9), 0.28, 'metal', 8, radius_b=0.22)
    b.cylinder((x, y, z + 0.88), (x, y, z + 1.02), 0.38, 'metal', 8)


def market_stall(b, x, y, z, w=10, d=6, cloth='canvas', yaw=0.0):
    """A loaded market stall: posts, deep canvas, shelves, produce and clutter."""
    def P(lx, ly, lz):
        px, py = local(x, y, yaw, lx, ly)
        return (px, py, z + lz)

    for sx in (-w / 2, w / 2):
        for sy in (-d / 2, d / 2):
            b.beam(P(sx, sy, 0), P(sx, sy, 3.25), 0.16, 'wood_dark')
            b.beam(P(sx, sy, 2.55), P(sx, sy * 0.70, 3.20), 0.09, 'wood_dark')
    # Counter, front skirt and a back shelf.
    b.box(P(0, -0.25, 0.8), (w - 0.7, 1.25, 0.24), 'wood_light', yaw)
    b.box(P(0, -0.25, 0.38), (w - 0.9, 1.05, 0.76), 'wood', yaw)
    b.box(P(0, -0.78, 0.4), (w - 1.0, 0.10, 0.66), cloth, yaw)
    b.box(P(0, d / 2 - 0.85, 1.45), (w - 1.0, 0.28, 2.2), 'wood', yaw)
    for i in range(max(3, int(w / 3))):
        lx = -w * 0.40 + i * w * 0.8 / max(1, int(w / 3) - 1)
        b.cylinder(P(lx, d / 2 - 1.0, 2.45), P(lx, d / 2 - 1.0, 2.85), 0.14,
                   ('glass_warm', 'clay', 'teal_wall')[i % 3], 7)
    # A deep gable of canvas with a scalloped valance and a lantern.
    b.quad(P(-w / 2 - 0.45, d / 2, 3.25), P(w / 2 + 0.45, d / 2, 3.25),
           P(w / 2 + 0.45, -0.2, 4.35), P(-w / 2 - 0.45, -0.2, 4.35), cloth)
    b.quad(P(-w / 2 - 0.45, -0.2, 4.35), P(w / 2 + 0.45, -0.2, 4.35),
           P(w / 2 + 0.45, -d / 2, 3.25), P(-w / 2 - 0.45, -d / 2, 3.25), cloth)
    for i in range(4):
        lx0 = -w / 2 + i * w / 4
        b.quad(P(lx0, -d / 2, 3.25), P(lx0 + w / 4, -d / 2, 3.25),
               P(lx0 + w / 4, -d / 2, 2.65), P(lx0, -d / 2, 2.65),
               'canvas_red' if i % 2 else 'canvas')
    b.beam(P(0, -d / 2 - 0.15, 3.3), P(0, -d / 2 - 0.15, 2.85), 0.04, 'metal')
    b.box(P(0, -d / 2 - 0.15, 2.7), (0.32, 0.32, 0.42), 'lantern', yaw)
    # Produce, fish and sacks in readable masses along the counter.
    for i in range(6):
        lx = -w * 0.37 + i * w * 0.15
        kind = i % 4
        if kind == 0:
            b.cylinder(P(lx, -0.2, 0.96), P(lx, -0.2, 1.18), 0.31, 'wood_light', 8)
            for j in range(4):
                b.sphere(P(lx - 0.18 + j * 0.12, -0.2, 1.24), 0.12, 'gold', (1, 1, 0.8), subdiv=0)
        elif kind == 1:
            b.sphere(P(lx, -0.2, 1.15), 0.26, 'coral', (1.35, 0.62, 0.55), subdiv=0)
            b.sphere(P(lx + 0.24, -0.2, 1.1), 0.18, 'gold', (1.0, 0.8, 0.8), subdiv=0)
        elif kind == 2:
            for j in range(3):
                b.sphere(P(lx - 0.18 + j * 0.18, -0.2, 1.1), 0.11, 'sail', (1.7, 0.45, 0.45), subdiv=0)
        else:
            b.box(P(lx, -0.2, 1.05), (0.62, 0.5, 0.36), 'wood_light', yaw)
            b.sphere(P(lx, -0.2, 1.28), 0.22, 'sage_wall', (1.0, 0.8, 0.8), subdiv=0)
    # Crates and sacks around the feet.
    for i in range(2):
        b.box(P(-w / 2 + 0.5, d / 2 - 0.3 - i * 1.1, 0.42), (1.2, 0.9, 0.8), 'wood_light', yaw)
        b.sphere(P(w / 2 - 0.7, -d / 2 + 0.9 + i * 1.0, 0.5), 0.5, 'canvas', (0.8, 0.7, 1.1), subdiv=0)


def palm(b, x, y, z, yaw=0.0, scale=1.0, rng=None):
    rng = rng or random.Random(int(x * 13 + y))
    height = (7.5 + rng.random() * 3.5) * scale
    lean = rng.uniform(-1.2, 1.2) * scale
    top = (x + lean, y + rng.uniform(-0.6, 0.6), z + height)
    segs = 6
    for i in range(segs):
        t0, t1 = i / segs, (i + 1) / segs
        p0 = (x + lean * t0 * t0, y + 0.0, z + height * t0)
        p1 = (x + lean * t1 * t1, y + 0.0, z + height * t1)
        b.cylinder(p0, p1, (0.33 - 0.18 * t0) * scale, 'wood', 7, radius_b=(0.33 - 0.18 * t1) * scale, caps=False)
    for i in range(9):
        ang = yaw + i * TAU / 9 + rng.uniform(-0.18, 0.18)
        length = (4.8 + rng.random() * 2.2) * scale
        tip = (top[0] + math.cos(ang) * length, top[1] + math.sin(ang) * length,
               top[2] - 1.1 * scale + rng.uniform(-0.4, 0.4))
        mid = (top[0] + math.cos(ang) * length * 0.48, top[1] + math.sin(ang) * length * 0.48,
               top[2] + 0.35 * scale)
        side = (math.cos(ang + math.pi / 2) * 0.7 * scale, math.sin(ang + math.pi / 2) * 0.7 * scale, 0)
        b.quad(top, (mid[0] + side[0], mid[1] + side[1], mid[2]),
               (tip[0] + side[0] * 0.35, tip[1] + side[1] * 0.35, tip[2]), tip, 'palm')
        b.quad(top, tip, (tip[0] - side[0] * 0.35, tip[1] - side[1] * 0.35, tip[2]),
               (mid[0] - side[0], mid[1] - side[1], mid[2]), 'palm_light')
    for i in range(3):
        a = yaw + i * TAU / 3
        b.sphere((top[0] + math.cos(a) * 0.45, top[1] + math.sin(a) * 0.45, top[2] - 0.15), 0.28 * scale,
                 'wood_dark', subdiv=0)


def jungle_tree(b, x, y, z, yaw=0.0, scale=1.0, rng=None):
    rng = rng or random.Random(int(x * 7 + y * 3))
    height = (5.5 + rng.random() * 4.5) * scale
    b.cylinder((x, y, z), (x, y, z + height * 0.62), 0.45 * scale, 'wood_dark', 7, radius_b=0.28 * scale)
    for i in range(4):
        ang = yaw + i * TAU / 4 + rng.uniform(-0.2, 0.2)
        length = (2.8 + rng.random() * 1.6) * scale
        end = (x + math.cos(ang) * length, y + math.sin(ang) * length, z + height * (0.55 + 0.08 * i))
        b.beam((x, y, z + height * 0.45), end, 0.24 * scale, 'wood_dark')
        leaf = rng.choice(('jungle', 'jungle_light', 'jungle_dark'))
        if rng.random() < 0.08:
            leaf = rng.choice(('autumn_rust', 'autumn_gold', 'autumn_olive'))
        b.sphere((end[0], end[1], end[2] + 0.7 * scale), (2.6 + rng.random() * 1.3) * scale,
                 leaf, (1.0, 0.9, 0.72), subdiv=0)
    leaf = rng.choice(('jungle', 'jungle_light'))
    if rng.random() < 0.08:
        leaf = rng.choice(('autumn_rust', 'autumn_gold', 'autumn_olive'))
    b.sphere((x, y, z + height), 2.6 * scale, leaf, (1.05, 1.0, 0.7), subdiv=0)


def bush(b, x, y, z, yaw=0.0, scale=1.0, rng=None):
    rng = rng or random.Random(int(x * 11 + y * 5))
    for i in range(3):
        b.sphere((x + rng.uniform(-0.6, 0.6) * scale, y + rng.uniform(-0.6, 0.6) * scale,
                  z + (0.35 + rng.uniform(0, 0.35)) * scale), (0.75 + rng.random() * 0.35) * scale,
                 rng.choice(('jungle', 'jungle_light', 'jungle_dark')), (1.0, 0.9, 0.75), subdiv=0)


def person(b, x, y, z, yaw=0.0, scale=1.0, rng=None):
    """A tiny low-poly market-goer, enough to give the square a human scale."""
    rng = rng or random.Random(int(x * 17 + y * 3))
    if rng.random() < 0.10:
        scale *= 0.68
    shirt = rng.choice(('cream', 'teal_wall', 'sage_wall', 'coral', 'ochre'))
    trousers = rng.choice(('wood_dark', 'roof_slate', 'stone_dark'))
    b.cylinder((x, y, z), (x, y, z + 0.9 * scale), 0.24 * scale, trousers, 6)
    b.cylinder((x, y, z + 0.82 * scale), (x, y, z + 1.4 * scale), 0.32 * scale, shirt, 6,
               radius_b=0.27 * scale)
    b.sphere((x, y, z + 1.53 * scale), 0.22 * scale, 'skin', (1.0, 0.9, 1.0), subdiv=0)
    if rng.random() < 0.55:
        b.cylinder((x, y, z + 1.63 * scale), (x, y, z + 1.68 * scale), 0.35 * scale,
                   rng.choice(('wood_dark', 'flag_red', 'flag_black', 'roof_straw')), 7)
    else:
        b.sphere((x, y, z + 1.62 * scale), 0.24 * scale, 'wood_dark', (1.0, 1.0, 0.45), subdiv=0)
    # Relaxed arms at the sides.
    for side in (-1, 1):
        b.beam((x + side * 0.25 * scale, y, z + 1.3 * scale),
               (x + side * 0.33 * scale, y + 0.04 * scale, z + 0.85 * scale), 0.07 * scale, 'skin')
    if rng.random() < 0.24:
        # A porter's basket or a fishwife's bundle.
        b.cylinder((x, y, z + 1.72 * scale), (x, y, z + 1.92 * scale), 0.24 * scale, 'wood_light', 7)
        b.sphere((x, y, z + 1.95 * scale), 0.20 * scale, rng.choice(('gold', 'coral', 'sail')),
                 (1.2, 0.8, 0.7), subdiv=0)
    if rng.random() < 0.18:
        b.box((x, y - 0.25 * scale, z + 0.85 * scale), (0.48 * scale, 0.08 * scale, 0.85 * scale),
              rng.choice(('canvas', 'canvas_red', 'sage_wall')), yaw)


def vine(b, x, y, z, length=8.0, rng=None):
    rng = rng or random.Random(int(x * 3 + y * 7))
    segs = max(3, int(length / 1.5))
    prev = (x, y, z)
    for i in range(1, segs + 1):
        t = i / segs
        p = (x + math.sin(t * 5 + x) * 0.35, y + rng.uniform(-0.2, 0.2), z - length * t)
        b.beam(prev, p, 0.07, 'jungle_light')
        prev = p
    for _ in range(3):
        t = rng.uniform(0.2, 0.9)
        px = x + math.sin(t * 5 + x) * 0.4
        b.sphere((px, y - 0.05, z - length * t), 0.20, 'jungle', (1.3, 0.4, 0.7), subdiv=0)
