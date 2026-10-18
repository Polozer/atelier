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


def door(b, cx, cy, yaw, lx, ly, z, w=1.6, h=2.6):
    x, y = local(cx, cy, yaw, lx, ly)
    b.box((x, y, z + h / 2), (w, 0.16, h), 'wood_dark', yaw)
    b.box((x, y, z + h + 0.12), (w + 0.35, 0.24, 0.22), 'wood', yaw)
    for side in (-1, 1):
        sx, sy = local(cx, cy, yaw, lx + side * (w / 2 + 0.14), ly)
        b.box((sx, sy, z + h / 2), (0.18, 0.20, h + 0.16), 'wood', yaw)
    b.box((x, y + 0.02, z + h * 0.55), (0.09, 0.06, 0.09), 'gold', yaw)


def awning(b, cx, cy, yaw, width, z, depth=2.3, colors=('cream', 'flag_red')):
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
            if style == 'tavern' and f == 1:
                balcony(b, face_x, face_y, yaw, w * 0.72, z + 6.2)
            if f == 0 and style in ('shop', 'tavern'):
                awning(b, face_x, face_y, yaw, w * 0.72, z + 3.0, 2.1,
                       ('cream', 'flag_red') if rng.random() < 0.55 else ('cream', 'roof_teal'))
    # Roof chooses a gable or hip silhouette, with ridge direction varied.
    if style == 'warehouse':
        b.gable_roof((x, y, z + h + 0.2), w, d, z + h + 0.2, min(4.2, w * 0.13), roof, yaw, ridge='x', overhang=1.0)
    elif style == 'shack':
        b.gable_roof((x, y, z + h + 0.1), w, d, z + h + 0.1, 2.4, roof, yaw, ridge='y', overhang=0.9)
    elif rng.random() < 0.45:
        b.gable_roof((x, y, z + h + 0.2), w, d, z + h + 0.2, 2.8 + (h % 3) * 0.25, roof, yaw,
                     ridge='y' if rng.random() < 0.5 else 'x', overhang=0.9)
    else:
        b.hip_roof((x, y, z + h + 0.2), w, d, z + h + 0.2, 2.6 + (h % 4) * 0.2, roof, yaw, overhang=0.9)
    # Chimneys, roof vents, and a bracket sign on roughly every third building.
    if style != 'warehouse' and rng.random() < 0.75:
        side = rng.choice((-1, 1))
        px, py = local(x, y, yaw, side * w * 0.25, d * 0.10)
        b.box((px, py, z + h + 2.1), (0.9, 0.9, 2.8), 'stone', yaw)
        b.box((px, py, z + h + 3.55), (1.2, 1.2, 0.25), 'stone_dark', yaw)
    if style in ('tavern', 'shop') and rng.random() < 0.8:
        sign(b, face_x, face_y, yaw, z + 2.8, side=rng.choice((-1, 1)),
             icon=rng.choice(('fish', 'mug', 'wheel', 'fish')))
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


def market_stall(b, x, y, z, w=10, d=6, cloth='cream'):
    for sx in (-w / 2, w / 2):
        for sy in (-d / 2, d / 2):
            b.beam((x + sx, y + sy, z), (x + sx, y + sy, z + 3.0), 0.16, 'wood_dark')
    # Counter and a shallow gable canvas.
    b.box((x, y - 0.2, z + 0.75), (w - 0.8, 1.2, 0.22), 'wood_light')
    b.box((x, y - 0.2, z + 0.35), (w - 0.8, 1.0, 0.7), 'wood')
    b.quad((x - w / 2 - 0.4, y + d / 2, z + 3.0), (x + w / 2 + 0.4, y + d / 2, z + 3.0),
           (x + w / 2 + 0.4, y, z + 3.9), (x - w / 2 - 0.4, y, z + 3.9), cloth)
    b.quad((x - w / 2 - 0.4, y, z + 3.9), (x + w / 2 + 0.4, y, z + 3.9),
           (x + w / 2 + 0.4, y - d / 2, z + 3.0), (x - w / 2 - 0.4, y - d / 2, z + 3.0), cloth)
    for i in range(3):
        b.quad((x - w / 2 + i * w / 3, y - d / 2, z + 3.0),
               (x - w / 2 + (i + 1) * w / 3, y - d / 2, z + 3.0),
               (x - w / 2 + (i + 1) * w / 3, y - d / 2, z + 2.55),
               (x - w / 2 + i * w / 3, y - d / 2, z + 2.55),
               'flag_red' if i % 2 else 'cream')
    # Goods: baskets, fish and fruit in strong readable colours.
    for i in range(5):
        gx = x - w * 0.34 + i * w * 0.17
        b.cylinder((gx, y - 0.15, z + 0.86), (gx, y - 0.15, z + 1.14), 0.34, 'wood_light', 8)
        if i % 2:
            for j in range(3):
                b.sphere((gx + (j - 1) * 0.20, y - 0.15, z + 1.22), 0.13, 'gold', (1, 1, 0.8))
        else:
            b.sphere((gx, y - 0.15, z + 1.2), 0.24, 'coral', (1.2, 0.55, 0.45))


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
