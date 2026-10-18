"""Reusable Brinecove pieces: houses, taverns, wharf furniture, ships, palms and landmarks."""
import math
import random
from geom import Builder

TAU = math.pi * 2


def local(cx, cy, yaw, lx, ly):
    a = math.radians(yaw)
    return cx + lx * math.cos(a) - ly * math.sin(a), cy + lx * math.sin(a) + ly * math.cos(a)


SHUTTER_COLORS = ('shutter_teal', 'shutter_blue', 'shutter_green', 'shutter_red', 'wood_dark')


def shutter_color(cx, cy, lx):
    return SHUTTER_COLORS[int(abs(cx * 3.1 + cy * 7.3 + lx * 11.7)) % len(SHUTTER_COLORS)]


def window(b, cx, cy, yaw, lx, ly, z, w=1.3, h=1.6, shutters=True, warm=False, shutter=None):
    x, y = local(cx, cy, yaw, lx, ly)
    # Recessed dark glass, a chunky painted frame and a stone sill.
    b.box((x, y, z + h / 2), (w, 0.12, h), 'glass_warm' if warm else 'glass', yaw)
    b.box((x, y, z + h / 2), (w + 0.24, 0.08, 0.15), 'cream', yaw)
    b.box((x, y, z + h), (w + 0.24, 0.08, 0.15), 'cream', yaw)
    b.box((x, y, z + h / 2), (0.12, 0.08, h), 'cream', yaw)
    b.box((x, y, z + h / 2), (w + 0.24, 0.08, 0.11), 'cream', yaw)
    b.box((x, y, z - 0.06), (w + 0.62, 0.30, 0.13), 'stone_light', yaw)
    if shutters:
        mat = shutter or shutter_color(cx, cy, lx)
        for side in (-1, 1):
            sx, sy = local(cx, cy, yaw, lx + side * (w / 2 + 0.30), ly)
            b.box((sx, sy, z + h / 2), (0.36, 0.12, h + 0.16), mat, yaw)
            for i in range(4):
                b.beam((sx - 0.13, sy - 0.08, z + 0.18 + i * (h - 0.10) / 4),
                       (sx + 0.13, sy - 0.08, z + 0.18 + i * (h - 0.10) / 4), 0.05, 'wood_dark')


def side_window(b, cx, cy, yaw, lx, ly, z, w=1.15, h=1.45, shutters=True, warm=False):
    """A window on a wall whose normal runs along local X."""
    x, y = local(cx, cy, yaw, lx, ly)
    b.box((x, y, z + h / 2), (0.12, w, h), 'glass_warm' if warm else 'glass', yaw)
    b.box((x, y, z + h / 2), (0.08, w + 0.22, 0.14), 'cream', yaw)
    b.box((x, y, z), (0.08, w + 0.22, 0.14), 'cream', yaw)
    b.box((x, y, z + h), (0.08, w + 0.22, 0.14), 'cream', yaw)
    b.box((x, y, z + h / 2), (0.08, 0.11, h), 'cream', yaw)
    b.box((x, y, z + h / 2), (0.08, w + 0.22, 0.11), 'cream', yaw)
    sx, sy = local(cx, cy, yaw, lx - 0.04, ly)
    b.box((sx, sy, z - 0.06), (0.30, w + 0.62, 0.13), 'stone_light', yaw)
    if shutters:
        mat = shutter_color(cx, cy, lx)
        for side in (-1, 1):
            sy = ly + side * (w / 2 + 0.28)
            sx, syy = local(cx, cy, yaw, lx + 0.02, sy)
            b.box((sx, syy, z + h / 2), (0.12, 0.34, h + 0.16), mat, yaw)
            for i in range(4):
                b.box((sx, syy, z + 0.18 + i * (h - 0.10) / 4), (0.13, 0.27, 0.045), 'wood_dark', yaw)


def dormer(b, cx, cy, yaw, lx, ly, z, roof='roof_terra'):
    x, y = local(cx, cy, yaw, lx, ly)
    b.box((x, y, z + 1.15), (2.8, 2.5, 2.3), 'cream', yaw)
    b.gable_roof((x, y, z + 2.25), 3.3, 3.0, z + 2.25, 1.25, roof, yaw, ridge='y', overhang=0.35)
    window(b, x, y, yaw, 0, -1.3, z + 0.35, 1.05, 1.35, False, rng_bool(cx, cy, lx))


def rng_bool(x, y, seed=0):
    return ((int(x * 17 + y * 31 + seed * 13) & 7) == 3)


def flower_box(b, cx, cy, yaw, lx, ly, z):
    x, y = local(cx, cy, yaw, lx, ly)
    b.box((x, y, z), (1.35, 0.34, 0.30), 'wood_dark', yaw)
    for i in range(2):
        px, py = local(cx, cy, yaw, lx - 0.3 + i * 0.6, ly - 0.08)
        b.sphere((px, py, z + 0.24), 0.26, 'jungle' if i else 'jungle_light',
                 (1.4, 0.9, 0.8), subdiv=0)
    for i in range(6):
        px, py = local(cx, cy, yaw, lx - 0.5 + i * 0.2, ly - 0.16)
        b.sphere((px, py, z + 0.36 + 0.05 * (i % 2)), 0.15,
                 ('blossom', 'coral', 'gold', 'blossom_pale', 'cream', 'blossom')[i % 6],
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
    leaf = ('wood_dark', 'shutter_blue', 'shutter_teal', 'shutter_red', 'wood')[int(abs(cx * 2.3 + cy * 5.1)) % 5]
    b.box((x, y, z + h / 2), (w, 0.16, h), leaf, yaw)
    b.box((x, y, z - 0.06), (w + 0.55, 0.42, 0.14), 'stone_light', yaw)
    b.box((x, y, z + h + 0.12), (w + 0.35, 0.24, 0.22), 'wood', yaw)
    for side in (-1, 1):
        sx, sy = local(cx, cy, yaw, lx + side * (w / 2 + 0.14), ly)
        b.box((sx, sy, z + h / 2), (0.18, 0.20, h + 0.16), 'wood', yaw)
    b.box((x, y + 0.02, z + h * 0.55), (0.09, 0.06, 0.09), 'gold', yaw)


def awning(b, cx, cy, yaw, width, z, depth=2.3, colors=('canvas', 'canvas_red'), poles=True):
    # Narrow alternating panels read as bold stripes from the street and the
    # harbor, which is the strongest single cue in the painted references.
    n = max(4, round(width / 1.7))
    for i in range(n):
        x0 = -width / 2 + width * i / n
        x1 = -width / 2 + width * (i + 1) / n
        a = local(cx, cy, yaw, x0, -1.0)
        c = local(cx, cy, yaw, x1, -1.0)
        d = local(cx, cy, yaw, x1, -depth)
        e = local(cx, cy, yaw, x0, -depth)
        mat = colors[i % len(colors)]
        b.quad((a[0], a[1], z), (c[0], c[1], z),
               (d[0], d[1], z - 0.55), (e[0], e[1], z - 0.55), mat)
        # Hanging valance, striped to match.
        b.quad((e[0], e[1], z - 0.55), (d[0], d[1], z - 0.55),
               (d[0], d[1], z - 0.98), (e[0], e[1], z - 0.98), mat)
    if poles:
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
    seed = int(abs(cx * 5.7 + cy * 9.1))
    # Laundry and potted plants turn the galleries into lived-in rooms.
    if seed % 3 != 0:
        a = local(cx, cy, yaw, -width * 0.38, -depth * 0.55)
        c = local(cx, cy, yaw, width * 0.38, -depth * 0.55)
        laundry_line(b, (a[0], a[1], z + 1.25), (c[0], c[1], z + 1.25), 0.35,
                     ('canvas_red', 'canvas_teal', 'canvas'))
    if seed % 2 == 0:
        for side in (-1, 1):
            px, py = local(cx, cy, yaw, side * width * 0.40, -depth * 0.60)
            potted_plant(b, px, py, z + 0.14, 0.42)


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


def shack_building(b, spec, rng):
    """A lived-in stilt cabin: planked walls, porch, ladder and patched roof."""
    key, x, y, z, w, d, h, floors, style, yaw, roof = spec

    def P(lx, ly, lz):
        px, py = local(x, y, yaw, lx, ly)
        return (px, py, z + lz)

    # Stilts, cross braces and the main deck.
    for sx in (-w / 2 + 0.4, 0.0, w / 2 - 0.4):
        for sy in (-d / 2 + 0.4, d / 2 - 0.4):
            b.beam(P(sx, sy, -3.4), P(sx, sy, 0.0), 0.24, 'wood_dark')
            if sy < 0:
                b.beam(P(sx, sy, -2.8), P(sx, 0, -0.5), 0.11, 'wood_dark')
    b.box(P(0, 0, 0.08), (w + 0.5, d + 0.5, 0.28), 'wood_light', yaw)
    b.box(P(0, 0, 0.24 + h / 2), (w, d, h), 'planks', yaw)
    # Corner posts, a belt rail and vertical battens read as plank walls.
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.box(P(sx * (w / 2 - 0.10), sy * (d / 2 - 0.10), 0.28 + h / 2),
                  (0.26, 0.26, h), 'wood_dark', yaw)
    for wall_y in (-d / 2 - 0.06, d / 2 + 0.06):
        for i in range(max(3, int(w / 1.1))):
            lx = -w / 2 + 0.55 + i * (w - 1.1) / max(1, int(w / 1.1) - 1)
            b.box(P(lx, wall_y, 0.28 + h / 2), (0.12, 0.13, h), 'wood_dark', yaw)
        b.box(P(0, wall_y, 1.35), (w, 0.16, 0.18), 'wood_dark', yaw)
    for wall_x in (-w / 2 - 0.06, w / 2 + 0.06):
        for i in range(max(2, int(d / 1.2))):
            ly = -d / 2 + 0.55 + i * (d - 1.1) / max(1, int(d / 1.2) - 1)
            b.box(P(wall_x, ly, 0.28 + h / 2), (0.13, 0.12, h), 'wood_dark', yaw)
    door(b, x, y, yaw, 0.0, -d / 2 - 0.10, z + 0.30, w=1.3, h=2.2)
    for side in (-1, 1):
        window(b, x, y, yaw, side * w * 0.30, -d / 2 - 0.06, z + 2.1,
               1.05, 1.25, shutters=True)
    # Porch deck, posts, rail and a lean-to roof.
    b.box(P(0, -d / 2 - 1.25, 0.10), (w * 0.92, 2.6, 0.24), 'wood_light', yaw)
    for side in (-1, 1):
        b.beam(P(side * w * 0.40, -d / 2 - 2.35, 0.1), P(side * w * 0.40, -d / 2 - 2.35, 2.9),
               0.14, 'wood_dark')
        b.beam(P(side * w * 0.40, -d / 2 - 0.2, 1.25), P(side * w * 0.40, -d / 2 - 2.35, 1.25),
               0.08, 'wood')
        for k in range(3):
            b.beam(P(side * w * 0.40, -d / 2 - 0.6 - k * 0.75, 1.25),
                   P(side * w * 0.40, -d / 2 - 0.6 - k * 0.75, 0.25), 0.06, 'wood')
    a0 = P(-w * 0.46, -d / 2 - 2.5, 2.85)
    a1 = P(w * 0.46, -d / 2 - 2.5, 2.85)
    c0 = P(-w * 0.46, -d / 2 + 0.1, 3.55)
    c1 = P(w * 0.46, -d / 2 + 0.1, 3.55)
    b.quad(a0, a1, c1, c0, 'roof_straw')
    # Roof with a repaired patch and a stove pipe.
    b.gable_roof((x, y, z + h + 0.30), w, d, z + h + 0.30, 2.3, roof, yaw,
                 ridge='y', overhang=1.0)
    b.cylinder(P(w * 0.26, d * 0.18, h + 0.4), P(w * 0.26, d * 0.18, h + 2.3),
               0.16, 'metal', 7)
    # Ladder down from the porch, a lantern, laundry, crates and a pot.
    for side in (-1, 1):
        b.beam(P(side * 0.55, -d / 2 - 2.45, 0.2), P(side * 0.55, -d / 2 - 2.45, -3.2),
               0.09, 'wood')
    for k in range(7):
        b.beam(P(-0.55, -d / 2 - 2.45, -0.2 - k * 0.42),
               P(0.55, -d / 2 - 2.45, -0.2 - k * 0.42), 0.07, 'wood_light')
    b.beam(P(-w * 0.34, -d / 2 - 0.25, 2.7), P(-w * 0.34, -d / 2 - 0.25, 2.25), 0.04, 'metal')
    b.box(P(-w * 0.34, -d / 2 - 0.25, 2.1), (0.28, 0.28, 0.36), 'lantern', yaw)
    a = P(-w * 0.35, -d / 2 - 1.6, 2.45)
    c = P(w * 0.35, -d / 2 - 1.6, 2.45)
    laundry_line(b, a, c, 0.22, ('canvas_red', 'canvas_teal', 'canvas'))
    for side in (-1, 1):
        crate(b, *P(side * w * 0.36, -d / 2 - 1.7, 0.30), 0.75, rng.uniform(0, 90))
        barrel(b, *P(side * w * 0.36 - 0.8, -d / 2 - 2.0, 0.25), 0.7)
    # A fish-drying rack, buoys and a rope coil finish the working porch.
    rack_y = -d / 2 - 2.15
    for side in (-1, 1):
        b.beam(P(side * w * 0.24, rack_y, 0.28), P(side * w * 0.24, rack_y, 2.15), 0.08, 'wood')
    b.beam(P(-w * 0.24, rack_y, 2.10), P(w * 0.24, rack_y, 2.10), 0.07, 'wood')
    for i in range(4):
        lx = -w * 0.19 + i * w * 0.125
        b.sphere(P(lx, rack_y, 1.88), 0.12, 'sail', (1.7, 0.5, 0.5), subdiv=0)
    b.sphere(P(w * 0.42, -d / 2 - 2.35, 0.7), 0.22, 'coral', subdiv=0)
    b.sphere(P(w * 0.42, -d / 2 - 2.35, 1.1), 0.18, 'gold', subdiv=0)
    b.ring(P(0, -d / 2 - 1.55, 0.30), 0.36, 0.05, 'rope', sides=10)
    potted_plant(b, *P(w * 0.42, -d / 2 - 0.4, 0.25), 0.45, rng)


def building(b, spec, rng):
    key, x, y, z, w, d, h, floors, style, yaw, roof = spec
    if style == 'shack':
        return shack_building(b, spec, rng)
    walls = {
        'tavern': ['cream', 'ochre', 'coral', 'plaster', 'azure_wall'],
        'house': ['plaster', 'cream', 'sage_wall', 'ochre', 'lime_wall', 'coral'],
        'shop': ['ochre', 'coral', 'teal_wall', 'cream', 'azure_wall'],
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
        has_arcade = style in ('tavern', 'shop') and w >= 9.0 and rng.random() < 0.55
        if has_arcade:
            arcade(b, x, y, yaw, w * 0.74, z + 0.15, 2.0, max(2, int(w / 6)))
        b.box((x, y, z + h - 0.18), (w + 0.5, d + 0.5, 0.5), 'wood_dark', yaw)
        # Front door, windows, awnings and gallery.
        door(b, x, y, yaw, rng.choice((-w * 0.28, 0.0, w * 0.28)), -d / 2 - 0.10, z + 0.02,
             w=1.5 if style != 'shack' else 1.2, h=2.4 if style != 'shack' else 2.1)
        if style != 'shack' and rng.random() < 0.55:
            plx = rng.choice((-w * 0.36, w * 0.36))
            px, py = local(x, y, yaw, plx, -d / 2 - 0.75)
            potted_plant(b, px, py, z + 0.05, rng.uniform(0.45, 0.70))
        if style == 'tavern' and rng.random() < 0.5:
            px, py = local(x, y, yaw, rng.uniform(-w * 0.3, w * 0.3), -d / 2 - 1.7)
            bench(b, px, py, z + 0.05, yaw)
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
                if f > 0 and rng.random() < 0.42:
                    flower_box(b, x, y, yaw, lx, -d / 2 - 0.42, zz - 0.18)
                elif f == 0 and style in ('shop', 'tavern') and rng.random() < 0.30:
                    flower_box(b, x, y, yaw, lx, -d / 2 - 0.42, zz - 0.18)
                if f > 0 and rng.random() < 0.24:
                    pair = (('canvas', 'canvas_red'), ('canvas', 'canvas_teal'),
                            ('canvas_red', 'canvas'), ('canvas_teal', 'canvas'))
                    awning(b, x, y, yaw, 2.4, zz + 1.85, 0.95,
                           pair[int(abs(lx)) % len(pair)], poles=False)
            for side in (-1, 1):
                side_window(b, x, y, yaw, side * (w / 2 + 0.04), -d * 0.24, zz,
                            1.05, 1.35, shutters=style != 'shack', warm=(rng.random() < 0.14))
                if d > 19.0:
                    side_window(b, x, y, yaw, side * (w / 2 + 0.04), d * 0.22, zz,
                                1.05, 1.35, shutters=style != 'shack', warm=(rng.random() < 0.14))
            if f == 1 and style in ('tavern', 'shop', 'house') and (style == 'tavern' or rng.random() < 0.70):
                by = z + min(h - 1.2, max(5.0, h * 0.52))
                balcony(b, face_x, face_y, yaw, w * 0.78, by)
                if rng.random() < 0.6:
                    for k in range(3):
                        px, py = local(x, y, yaw, -w * 0.22 + k * w * 0.2, -d / 2 - 2.25)
                        b.quad((px - 0.55, py, by - 0.25), (px + 0.55, py, by - 0.25),
                               (px + 0.55, py + 0.04, by - 2.4), (px - 0.55, py + 0.04, by - 2.4),
                               ('canvas', 'canvas_red', 'canvas_teal')[k])
            if f == 0 and style in ('shop', 'tavern', 'house') and not has_arcade and rng.random() < 0.82:
                pair = (('canvas', 'canvas_red'), ('canvas', 'canvas_teal'),
                        ('canvas_red', 'canvas'), ('canvas_teal', 'canvas'))
                awning(b, face_x, face_y, yaw, w * 0.78, z + 3.3, 2.2,
                       pair[int(abs(x + y)) % len(pair)])
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
    if not flat_roof and style != 'warehouse' and h > 9.5 and rng.random() < 0.72:
        dormer(b, x, y, yaw, rng.choice((-w * 0.22, 0.0, w * 0.22)), -d * 0.10,
               z + h + 0.35, roof)
    # Chimneys, roof vents, and a bracket sign on roughly every third building.
    if style != 'warehouse' and rng.random() < 0.75:
        side = rng.choice((-1, 1))
        px, py = local(x, y, yaw, side * w * 0.25, d * 0.10)
        b.box((px, py, z + h + 2.1), (0.9, 0.9, 2.8), 'stone', yaw)
        b.box((px, py, z + h + 3.55), (1.2, 1.2, 0.25), 'stone_dark', yaw)
    if style in ('tavern', 'shop') and rng.random() < 0.9:
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
    # A deep gable of striped canvas with a scalloped valance and a lantern.
    stripe = 'canvas' if cloth != 'canvas' else 'canvas_red'
    strips = 7
    for i in range(strips):
        sx0 = -w / 2 - 0.45 + (w + 0.9) * i / strips
        sx1 = -w / 2 - 0.45 + (w + 0.9) * (i + 1) / strips
        mat = cloth if i % 2 == 0 else stripe
        b.quad(P(sx0, d / 2, 3.25), P(sx1, d / 2, 3.25),
               P(sx1, -0.2, 4.35), P(sx0, -0.2, 4.35), mat)
        b.quad(P(sx0, -0.2, 4.35), P(sx1, -0.2, 4.35),
               P(sx1, -d / 2, 3.25), P(sx0, -d / 2, 3.25), mat)
    for i in range(4):
        lx0 = -w / 2 + i * w / 4
        b.quad(P(lx0, -d / 2, 3.25), P(lx0 + w / 4, -d / 2, 3.25),
               P(lx0 + w / 4, -d / 2, 2.65), P(lx0, -d / 2, 2.65),
               'canvas_red' if i % 2 else 'canvas')
    b.beam(P(0, -d / 2 - 0.15, 3.3), P(0, -d / 2 - 0.15, 2.85), 0.04, 'metal')
    b.box(P(0, -d / 2 - 0.15, 2.7), (0.32, 0.32, 0.42), 'lantern', yaw)
    for i in range(3):
        lx = -w * 0.30 + i * w * 0.30
        b.beam(P(lx, -d / 2 - 0.12, 3.18), P(lx, -d / 2 - 0.12, 2.62), 0.03, 'rope')
        b.sphere(P(lx, -d / 2 - 0.12, 2.48), 0.15, 'sail', (1.7, 0.5, 0.5), subdiv=0)
    for i in range(2):
        b.sphere(P(-w * 0.20 + i * 0.7, -d / 2 - 0.12, 2.15), 0.16, 'gold',
                 (1.0, 0.9, 0.8), subdiv=0)
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
    for i in range(3):
        px, py, pz = P(-w * 0.30 + i * w * 0.30, -d / 2 + 1.35, 0)
        fish_crate(b, px, py, pz, yaw + (i - 1) * 8, 0.95)
    for i in range(2):
        px, py, pz = P(w * 0.30 + i * 0.9, d / 2 - 1.2, 0)
        sack(b, px, py, pz + 0.2, 0.9)


def laundry_line(b, a, c, sag=0.35, colors=('canvas', 'canvas_red', 'canvas_teal')):
    """A rope with three flat cloth panels; cheap and reads at street distance."""
    b.rope(a, c, sag, 0.03, segments=6)
    for i in range(3):
        t = (i + 0.5) / 3
        px = a[0] + (c[0] - a[0]) * t
        py = a[1] + (c[1] - a[1]) * t
        pz = a[2] + (c[2] - a[2]) * t - sag * math.sin(math.pi * t)
        b.box((px, py, pz - 0.48), (0.62 + 0.10 * (i % 2), 0.035, 0.95 + 0.15 * (i % 2)),
              colors[i % len(colors)])


def pennants(b, a, c, sag=0.5, count=9, colors=('flag_red', 'cream', 'canvas_teal', 'gold')):
    """A sagging rope of small square flags across a street or the market."""
    b.rope(a, c, sag, 0.035, segments=8)
    for i in range(count):
        t = (i + 0.5) / count
        px = a[0] + (c[0] - a[0]) * t
        py = a[1] + (c[1] - a[1]) * t
        pz = a[2] + (c[2] - a[2]) * t - sag * math.sin(math.pi * t)
        b.box((px, py, pz - 0.24), (0.42, 0.03, 0.46), colors[i % len(colors)])


def fish_crate(b, x, y, z, yaw=0.0, scale=1.0):
    b.box((x, y, z + 0.24 * scale), (1.35 * scale, 0.85 * scale, 0.48 * scale),
          'wood_light', yaw)
    for i in range(4):
        px, py = local(x, y, yaw, -0.42 * scale + i * 0.28 * scale, 0)
        b.sphere((px, py, z + 0.54 * scale), 0.16 * scale, 'sail',
                 (1.9, 0.55, 0.45), subdiv=0)


def rowboat(b, x, y, z, yaw=0.0, scale=1.0):
    def P(lx, ly, lz):
        px, py = local(x, y, yaw, lx * scale, ly * scale)
        return (px, py, z + lz * scale)

    b.quad(P(-0.75, -2.4, 0.12), P(0.75, -2.4, 0.12), P(0.75, 2.4, 0.12), P(-0.75, 2.4, 0.12),
           'wood_dark')
    b.quad(P(-0.75, -2.4, 0.12), P(-0.75, 2.4, 0.12), P(-1.05, 2.6, 0.55), P(-1.05, -2.6, 0.55),
           'wood')
    b.quad(P(0.75, -2.4, 0.12), P(1.05, -2.6, 0.55), P(1.05, 2.6, 0.55), P(0.75, 2.4, 0.12),
           'wood')
    b.tri(P(-0.75, 2.4, 0.12), P(0.75, 2.4, 0.12), P(0, 3.0, 0.55), 'wood_light')
    b.tri(P(-0.75, -2.4, 0.12), P(0, -3.0, 0.55), P(0.75, -2.4, 0.12), 'wood_light')
    for side in (-1, 1):
        b.beam(P(side * 1.05, -2.6, 0.55), P(side * 1.05, 2.6, 0.55), 0.08, 'wood_dark')
    for ly in (-1.0, 0.6):
        b.beam(P(-1.0, ly, 0.50), P(1.0, ly, 0.50), 0.10, 'wood_light')
    b.beam(P(-0.6, 0.2, 0.62), P(-1.8, -1.4, 0.20), 0.05, 'wood_light')
    b.beam(P(0.6, 0.2, 0.62), P(1.8, -1.4, 0.20), 0.05, 'wood_light')


def sack(b, x, y, z, scale=1.0):
    b.sphere((x, y, z + 0.44 * scale), 0.52 * scale, 'canvas', (0.85, 0.85, 1.15), subdiv=0)
    b.cylinder((x, y, z + 0.85 * scale), (x, y, z + 1.0 * scale), 0.13 * scale, 'cream', 6)


def potted_plant(b, x, y, z, scale=1.0, rng=None):
    b.cylinder((x, y, z), (x, y, z + 0.55 * scale), 0.44 * scale, 'clay', 8,
               radius_b=0.32 * scale)
    bush(b, x, y, z + 0.52 * scale, 0.0, 0.62 * scale, rng)


def bench(b, x, y, z, yaw=0.0):
    b.box((x, y, z + 0.46), (2.1, 0.60, 0.13), 'wood_light', yaw)
    for side in (-1, 1):
        px, py = local(x, y, yaw, side * 0.82, 0)
        b.beam((px, py, z), (px, py, z + 0.46), 0.13, 'wood_dark')
        px, py = local(x, y, yaw, side * 0.82, 0.24)
        b.beam((px, py, z + 0.46), (px, py, z + 0.95), 0.11, 'wood_dark')
    b.box((x, y, z + 0.88), (2.1, 0.12, 0.34), 'wood', yaw)


LEAF_CELLS = ((0.02, 0.02, 0.48, 0.48), (0.52, 0.02, 0.98, 0.48),
              (0.02, 0.52, 0.48, 0.98), (0.52, 0.52, 0.98, 0.98))
PALM_CELLS = (2, 3)


def cell_uvs(cell):
    u0, v0, u1, v1 = LEAF_CELLS[cell]
    return ((u0, v0), (u1, v0), (u1, v1), (u0, v1))


def leaf_canopy(b, center, radii, count, size, rng, warm=0.15):
    """A cloud of small alpha leaf cards, dense on the shell and darker inside."""
    cx, cy, cz = center
    rx, ry, rz = radii
    for _ in range(count):
        while True:
            p = (rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
            length = math.sqrt(p[0] * p[0] + p[1] * p[1] + p[2] * p[2])
            if length <= 1.0:
                break
        if length < 0.55 and rng.random() < 0.45:
            scale = rng.uniform(0.62, 1.0) / max(length, 1e-3)
            p = (p[0] * scale, p[1] * scale, p[2] * scale)
            length = 1.0
        pos = (cx + p[0] * rx, cy + p[1] * ry, cz + p[2] * rz)
        normal = (p[0] + rng.uniform(-0.45, 0.45),
                  p[1] + rng.uniform(-0.45, 0.45),
                  p[2] * 0.75 + rng.uniform(-0.25, 0.85))
        if rng.random() < warm:
            mat = 'leaf_warm'
        elif length < 0.45:
            mat = 'leaf_deep'
        elif length < 0.78:
            mat = 'leaf_mid'
        else:
            mat = 'leaf_light'
        card = size * rng.uniform(0.72, 1.28)
        b.card(pos, normal, card, card * rng.uniform(0.82, 1.05), mat,
               cell_uvs(rng.randrange(4)))


def palm(b, x, y, z, yaw=0.0, scale=1.0, rng=None):
    rng = rng or random.Random(int(x * 13 + y))
    height = (8.0 + rng.random() * 4.0) * scale
    lean = rng.uniform(-1.6, 1.6) * scale
    drift = rng.uniform(-0.8, 0.8) * scale
    top = (x + lean, y + drift, z + height)
    segs = 7
    for i in range(segs):
        t0, t1 = i / segs, (i + 1) / segs
        p0 = (x + lean * t0 ** 1.7, y + drift * t0 * t0, z + height * t0)
        p1 = (x + lean * t1 ** 1.7, y + drift * t1 * t1, z + height * t1)
        b.cylinder(p0, p1, (0.36 - 0.19 * t0) * scale, 'wood', 7,
                   radius_b=(0.36 - 0.19 * t1) * scale, caps=False)
    for i in range(11):
        ang = yaw + i * TAU / 11 + rng.uniform(-0.12, 0.12)
        length = (4.6 + rng.random() * 2.4) * scale
        droop = (1.2 + rng.random() * 0.9) * scale
        direction = (math.cos(ang), math.sin(ang), -droop / length)
        centre = (top[0] + direction[0] * length * 0.52,
                  top[1] + direction[1] * length * 0.52,
                  top[2] + direction[2] * length * 0.52)
        normal = (-math.sin(ang), math.cos(ang), 0.22)
        b.card(centre, normal, 2.6 * scale, length, 'palm_frond',
               cell_uvs(PALM_CELLS[i % len(PALM_CELLS)]), up_hint=direction)
    # A shorter upright crown ring closes the silhouette seen from below.
    for i in range(4):
        ang = yaw + i * TAU / 4 + 0.6
        length = (2.4 + rng.random() * 0.9) * scale
        direction = (math.cos(ang) * 0.55, math.sin(ang) * 0.55, 0.85)
        centre = (top[0] + direction[0] * length * 0.5,
                  top[1] + direction[1] * length * 0.5,
                  top[2] + direction[2] * length * 0.5)
        normal = (-math.sin(ang), math.cos(ang), 0.15)
        b.card(centre, normal, 1.9 * scale, length, 'palm_frond',
               cell_uvs(PALM_CELLS[i % len(PALM_CELLS)]), up_hint=direction)
    for i in range(4):
        a = yaw + i * TAU / 4
        b.sphere((top[0] + math.cos(a) * 0.42, top[1] + math.sin(a) * 0.42, top[2] - 0.18),
                 0.26 * scale, ('wood_dark', 'autumn_olive')[i % 2], subdiv=0)


def jungle_tree(b, x, y, z, yaw=0.0, scale=1.0, rng=None):
    rng = rng or random.Random(int(x * 7 + y * 3))
    height = (6.2 + rng.random() * 5.0) * scale
    lean = rng.uniform(-0.7, 0.7) * scale
    drift = rng.uniform(-0.35, 0.35) * scale
    mid = (x + lean * 0.40, y + drift * 0.35, z + height * 0.55)
    top = (x + lean, y + drift, z + height)
    b.cylinder((x, y, z), mid, 0.52 * scale, 'wood_dark', 8, radius_b=0.36 * scale)
    b.cylinder(mid, top, 0.36 * scale, 'wood_dark', 7, radius_b=0.18 * scale)
    if scale > 1.10:
        for i in range(4):
            ang = yaw + i * TAU / 4 + 0.3
            ex, ey = x + math.cos(ang) * 1.05 * scale, y + math.sin(ang) * 1.05 * scale
            b.beam((x, y, z + 0.18 * scale), (ex, ey, z + 0.02), 0.17 * scale, 'wood_dark')
    fork = (x + lean * 0.32, y + drift * 0.28, z + height * 0.44)
    lobes = []
    for i in range(4):
        ang = yaw + i * TAU / 4 + rng.uniform(-0.22, 0.22)
        length = (3.0 + rng.random() * 2.0) * scale
        end = (x + lean * 0.72 + math.cos(ang) * length,
               y + drift * 0.72 + math.sin(ang) * length,
               z + height * (0.58 + 0.08 * i))
        b.cylinder(fork, end, 0.26 * scale, 'wood_dark', 6,
                   radius_b=0.09 * scale, caps=False)
        radius = (2.25 + rng.random() * 1.0) * scale
        lobes.append(((end[0], end[1], end[2] + 0.55 * scale), radius))
        # A couple of twigs give the canopy a broken edge.
        for k in range(1):
            twig_ang = ang + rng.uniform(-0.9, 0.9)
            twig_len = (1.3 + rng.random() * 0.9) * scale
            twig_end = (end[0] + math.cos(twig_ang) * twig_len,
                        end[1] + math.sin(twig_ang) * twig_len,
                        end[2] + rng.uniform(0.2, 0.9) * scale)
            b.cylinder(end, twig_end, 0.08 * scale, 'wood_dark', 5,
                       radius_b=0.03 * scale, caps=False)
            lobes.append(((twig_end[0], twig_end[1], twig_end[2] + 0.3 * scale),
                          (0.95 + rng.random() * 0.55) * scale))
    lobes.append(((top[0], top[1], top[2] - 0.25 * scale), (2.7 + rng.random() * 0.7) * scale))
    lobes.append(((top[0] - 1.5 * scale, top[1] + 1.05 * scale, top[2] - 0.95 * scale),
                  (1.9 + rng.random() * 0.5) * scale))
    for centre, radius in lobes:
        volume = radius * radius
        count = max(20, int(volume * 3.6))
        leaf_canopy(b, centre, (radius, radius, radius * 0.76), count,
                    (1.00 + rng.random() * 0.35) * scale, rng)
    if scale > 1.25 and rng.random() < 0.28:
        a = rng.uniform(0, TAU)
        vx = top[0] + math.cos(a) * 2.3 * scale
        vy = top[1] + math.sin(a) * 2.3 * scale
        vine(b, vx, vy, top[2] - 0.5 * scale, rng.uniform(1.8, 3.8) * scale, rng)


def bush(b, x, y, z, yaw=0.0, scale=1.0, rng=None):
    rng = rng or random.Random(int(x * 11 + y * 5))
    leaf_canopy(b, (x, y, z + 0.58 * scale), (0.92 * scale, 0.92 * scale, 0.62 * scale),
                max(24, int(42 * scale)), 0.58 * scale, rng, warm=0.10)
    if rng.random() < 0.20:
        for i in range(3):
            b.sphere((x + rng.uniform(-0.5, 0.5) * scale, y + rng.uniform(-0.5, 0.5) * scale,
                      z + (0.75 + rng.uniform(0, 0.3)) * scale), 0.16 * scale,
                     ('blossom', 'coral', 'gold')[i % 3], subdiv=0)


def fern(b, x, y, z, yaw=0.0, scale=1.0, rng=None):
    rng = rng or random.Random(int(x * 17 + y * 3))
    for i in range(7):
        ang = yaw + i * TAU / 7 + rng.uniform(-0.2, 0.2)
        length = (1.3 + rng.random() * 1.0) * scale
        tip = (x + math.cos(ang) * length, y + math.sin(ang) * length,
               z + (0.65 + rng.uniform(0, 0.35)) * scale)
        side = (math.cos(ang + math.pi / 2) * 0.22 * scale,
                math.sin(ang + math.pi / 2) * 0.22 * scale, 0)
        b.quad((x, y, z + 0.05), (tip[0] + side[0], tip[1] + side[1], tip[2]),
               tip, (tip[0] - side[0], tip[1] - side[1], tip[2]),
               'jungle_light' if i % 2 else 'jungle')


def banana(b, x, y, z, yaw=0.0, scale=1.0, rng=None):
    rng = rng or random.Random(int(x * 23 + y * 5))
    height = (1.5 + rng.random() * 0.8) * scale
    top = (x + rng.uniform(-0.2, 0.2), y + rng.uniform(-0.2, 0.2), z + height)
    b.cylinder((x, y, z), top, 0.16 * scale, 'jungle', 6, radius_b=0.11 * scale)
    for i in range(6):
        ang = yaw + i * TAU / 6 + rng.uniform(-0.2, 0.2)
        length = (1.5 + rng.random() * 0.6) * scale
        mid = (top[0] + math.cos(ang) * length * 0.55, top[1] + math.sin(ang) * length * 0.55,
               top[2] + 0.55 * scale)
        tip = (top[0] + math.cos(ang) * length, top[1] + math.sin(ang) * length,
               top[2] + 0.10 * scale)
        side = (math.cos(ang + math.pi / 2) * 0.42 * scale,
                math.sin(ang + math.pi / 2) * 0.42 * scale, 0)
        b.quad(top, (mid[0] + side[0], mid[1] + side[1], mid[2]),
               (tip[0] + side[0] * 0.5, tip[1] + side[1] * 0.5, tip[2]), tip, 'jungle_light')
        b.quad(top, tip, (tip[0] - side[0] * 0.5, tip[1] - side[1] * 0.5, tip[2]),
               (mid[0] - side[0], mid[1] - side[1], mid[2]), 'jungle')


def grass_tuft(b, x, y, z, yaw=0.0, scale=1.0, rng=None):
    rng = rng or random.Random(int(x * 31 + y * 7))
    for i in range(3):
        ang = yaw + i * TAU / 3 + rng.uniform(-0.3, 0.3)
        h = (0.55 + rng.random() * 0.45) * scale
        w = 0.28 * scale
        dx, dy = math.cos(ang) * w, math.sin(ang) * w
        b.quad((x - dx, y - dy, z), (x + dx, y + dy, z),
               (x + dx * 0.3, y + dy * 0.3, z + h), (x - dx * 0.3, y - dy * 0.3, z + h),
               'autumn_olive' if i % 2 else 'jungle_light')


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
    if rng.random() < 0.40:
        for i in range(3):
            t = rng.uniform(0.25, 0.85)
            px = x + math.sin(t * 5 + x) * 0.45
            b.sphere((px, y - 0.12, z - length * t), 0.13,
                     ('blossom', 'blossom_pale', 'coral')[i % 3], subdiv=0)
