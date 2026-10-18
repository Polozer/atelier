"""Assemble Brinecove as nine separate collections, then hand them to the Blender exporter."""
import math
import random
import layout as L
from geom import Builder
from kit import (awning, balcony, barrel, bollard, building, bush, crate, door, jungle_tree,
                 lantern_post, local, market_stall, palm, person, sign, vine, window)

TAU = math.pi * 2
RNG = random.Random(49157)


def terrain():
    b = Builder('01_terrain')
    nx, ny = 196, 158
    dx = (L.VIEW_X_MAX - L.VIEW_X_MIN) / nx
    dy = (L.VIEW_Y_MAX - L.VIEW_Y_MIN) / ny
    zs = [[L.height(L.VIEW_X_MIN + i * dx, L.VIEW_Y_MIN + j * dy) for j in range(ny + 1)] for i in range(nx + 1)]
    for i in range(nx):
        for j in range(ny):
            x0 = L.VIEW_X_MIN + i * dx; x1 = x0 + dx
            y0 = L.VIEW_Y_MIN + j * dy; y1 = y0 + dy
            a = (x0, y0, zs[i][j]); bb = (x1, y0, zs[i + 1][j])
            c = (x1, y1, zs[i + 1][j + 1]); d = (x0, y1, zs[i][j + 1])
            zavg = (a[2] + bb[2] + c[2] + d[2]) / 4
            gx = (x0 + x1) / 2; gy = (y0 + y1) / 2
            sl = L.slope(gx, gy)
            if zavg < 0.15:
                mat = 'seabed'
            elif zavg < 2.2:
                mat = 'sand'
            elif sl > 1.25:
                # Near-vertical faces stay bare rock.
                mat = 'rock_dark' if (i + j) % 3 == 0 else 'rock'
            elif sl > 0.95:
                # On the steep cliff bands, leave ledges of jungle between the
                # exposed rock so the shoreline does not read as a grey wall.
                ledge = (i * 3 + j * 7) % 9
                mat = 'jungle_dark' if ledge == 0 else ('rock_dark' if ledge < 3 else 'rock')
            elif zavg > 42 and sl > 0.62:
                # Broken outcrops on the upper slopes, mixed into the canopy.
                mat = ('rock_light', 'rock', 'jungle_dark')[(i * 5 + j * 3) % 3]
            elif L.is_water(gx, gy):
                mat = 'seabed'
            else:
                pattern = math.sin(gx * 0.012 + 0.4) * math.cos(gy * 0.009 - 0.7)
                mat = ('jungle', 'jungle_light', 'jungle_dark')[int((pattern + 1.0) * 1.5) % 3]
                if pattern > 0.55 and (i * 7 + j * 5) % 17 == 0:
                    mat = 'autumn_olive'
                elif pattern < -0.6 and (i * 3 + j * 11) % 19 == 0:
                    mat = 'autumn_rust'
            b.tri(a, bb, c, mat)
            b.tri(a, c, d, mat)
    # Angular coastal rock shelves break up the sampled heightfield edge.
    rock_points = []
    for y in range(-620, 61, 26):
        hw = L.bay_half(y)
        for side in (-1, 1):
            x = side * (hw + RNG.uniform(1, 12))
            rock_points.append((x, y + RNG.uniform(-8, 8), L.height(x, y), RNG.uniform(3.5, 8.5)))
    for x, y, z, r in rock_points:
        rock_cluster(b, x, y, z - 1.0, r, RNG.randint(2, 4))
    for x, y, _, r in L.SEA_STACKS:
        rock_cluster(b, x, y, -3.0, r, 7, tall=True)
    # The statue islet.
    rock_cluster(b, L.STATUE[0], L.STATUE[1], -2.5, 16.0, 10, tall=False)
    # A wet, dark face behind the waterfall, set back far enough that the
    # white sheet reads from the harbor instead of being buried in the cliff.
    for i in range(8):
        x = 444 + i * 8.5
        b.box((x, 97 - i * 0.2, 27), (10.0, 8.0, 58), 'rock_dark' if i % 2 else 'rock')
    # Distant forested hills, low and rounded so they frame rather than
    # dominate the cove. Several overlapping domes make each ridge.
    for x, y, r, mat in [
        (-720, 640, 210, 'jungle_dark'), (-470, 700, 240, 'jungle_dark'),
        (-210, 740, 220, 'jungle'), (60, 720, 250, 'jungle_dark'),
        (330, 690, 230, 'jungle'), (590, 650, 205, 'jungle_dark'),
        (-880, 240, 210, 'rock'), (890, 260, 220, 'rock'),
        (-870, -30, 180, 'jungle_dark'), (880, -10, 190, 'jungle_dark'),
    ]:
        b.sphere((x, y, -5), r, mat, (1.35, 1.0, 0.27), subdiv=1)
        b.sphere((x + r * 0.55, y + r * 0.2, -5), r * 0.72, mat, (1.2, 1.0, 0.24), subdiv=1)
    return b


def rock_cluster(b, x, y, z, radius, count, tall=False):
    for i in range(count):
        ang = RNG.uniform(0, TAU)
        rr = RNG.uniform(0, radius * 0.75)
        px, py = x + math.cos(ang) * rr, y + math.sin(ang) * rr
        sx = RNG.uniform(0.55, 1.15) * radius
        sy = RNG.uniform(0.55, 1.15) * radius
        sz = RNG.uniform(0.55, 1.3) * radius * (1.8 if tall else 1.0)
        b.sphere((px, py, z + sz * 0.38), max(1.0, radius * 0.45),
                 ('rock', 'rock_light', 'rock_dark')[i % 3], (sx / max(1, radius), sy / max(1, radius), sz / max(1, radius)))


def harbor():
    b = Builder('02_harbor')
    # Quay wall and its cap.
    b.box((0, L.QUAY_Y, 0.35), (780, 4.2, 9.4), 'stone')
    b.box((0, L.QUAY_Y + 1.9, 4.65), (784, 1.6, 0.45), 'stone_light')
    # The seaward face needs a scale and rhythm of its own: a wet base,
    # horizontal courses and recessed arch-headed doors between the buttresses.
    b.box((0, L.QUAY_Y - 2.18, 0.75), (780, 0.35, 1.5), 'stone_dark')
    for zz, mat in ((2.7, 'stone_light'), (5.25, 'stone'), (7.55, 'stone_light')):
        b.box((0, L.QUAY_Y - 2.18, zz), (780, 0.35, 0.28), mat)
    for x in range(-342, 343, 76):
        if abs(x) < 22:
            continue
        b.box((x, L.QUAY_Y - 2.28, 2.55), (8.2, 0.35, 4.5), 'stone_dark')
        b.box((x, L.QUAY_Y - 2.38, 4.7), (9.4, 0.45, 0.75), 'stone_light')
        b.box((x, L.QUAY_Y - 2.38, 2.25), (9.8, 0.45, 0.45), 'stone_light')
        b.box((x, L.QUAY_Y - 2.46, 2.25), (6.0, 0.28, 3.35), 'wood_dark')
        for dx in (-2.0, 0.0, 2.0):
            b.box((x + dx, L.QUAY_Y - 2.62, 2.25), (0.16, 0.12, 3.3), 'metal')
        b.cylinder((x - 6.4, L.QUAY_Y - 2.42, 5.4), (x - 6.4, L.QUAY_Y - 2.42, 5.4), 0.18, 'metal', 8)
    for x in range(-390, 391, 38):
        b.box((x, L.QUAY_Y - 2.5, 0.4), (5.2, 2.4, 9.0), 'stone_light')
        b.cylinder((x, L.QUAY_Y - 3.9, 1.0), (x, L.QUAY_Y - 3.9, 1.0), 0.65, 'metal', 10)
    for x in range(-360, 361, 90):
        b.box((x, L.QUAY_Y - 0.2, 5.2), (12, 1.2, 0.6), 'stone_dark')
    # The three piers, with piles down into the water.
    for name, px, y0, y1, width in L.PIERS:
        length = y0 - y1
        b.box((px, (y0 + y1) / 2, 4.9), (width, length, 0.7), 'wood_light')
        for yy in [y0 - 1.5 - i * 8 for i in range(int(length / 8) + 1)]:
            for side in (-1, 1):
                bx = px + side * (width / 2 - 1.0)
                b.cylinder((bx, yy, -4.5), (bx, yy, 5.0), 0.55, 'wood_dark', 7)
                b.beam((bx, yy, 0.5), (px, yy, 3.9), 0.25, 'wood_dark')
        for i in range(int(length / 9)):
            yy = y0 - 4 - i * 9
            b.box((px, yy, 5.28), (width - 0.4, 0.18, 0.08), 'wood_dark')
        # T-head on the main and east piers.
        if name in ('central', 'east'):
            tw = 40 if name == 'central' else 26
            b.box((px, y1 + 2, 4.9), (tw, 14, 0.7), 'wood_light')
            for xx in (-tw / 2 + 2, tw / 2 - 2):
                b.cylinder((px + xx, y1 - 3, -4.5), (px + xx, y1 - 3, 5.0), 0.6, 'wood_dark', 7)
        for i in range(max(2, int(length / 42))):
            yy = y0 - 14 - i * 42
            for side in (-1, 1):
                if i % 2:
                    bollard(b, px + side * (width / 2 - 1.2), yy, 5.3)
        lantern_post(b, px - width / 2 + 1.4, y1 + 3, 5.3, 3.0)
        lantern_post(b, px + width / 2 - 1.4, y0 - 16, 5.3, 3.0)
    # Quay promenade paving and steps into the water.
    b.box((0, 86, 4.62), (780, 42, 0.25), 'stone_light')
    for x in (-130, 135):
        for i in range(6):
            b.box((x, L.QUAY_Y - 1.0 - i * 0.8, 4.3 - i * 0.7), (9.0, 0.9, 0.3), 'stone')
    # Fish market shed by the east pier.
    shed_x, shed_y = 305, 86
    for xx in (-16, 16):
        for yy in (-6, 6):
            b.beam((shed_x + xx, shed_y + yy, 5.0), (shed_x + xx, shed_y + yy, 11.0), 0.34, 'wood_dark')
    b.gable_roof((shed_x, shed_y, 11.0), 34, 14, 11.0, 3.0, 'roof_terra', 0, ridge='x', overhang=1.0)
    b.box((shed_x, shed_y - 2.0, 5.7), (30, 2.0, 1.2), 'wood_light')
    for i in range(6):
        b.box((shed_x - 12 + i * 4.8, shed_y - 2.3, 6.5), (2.2, 1.0, 0.5), 'sail_stripe' if i % 2 else 'cream')
    # Cargo cranes: a timber A-frame, jib, rope and a hanging crate.
    for cx, cy, ang in ((-334, 84, -22), (330, 78, 16)):
        b.beam((cx - 4, cy, 4.7), (cx, cy, 18.0), 0.5, 'wood_dark')
        b.beam((cx + 4, cy, 4.7), (cx, cy, 18.0), 0.5, 'wood_dark')
        b.beam((cx, cy, 15.0), (cx + math.cos(math.radians(ang)) * 16, cy + math.sin(math.radians(ang)) * 16, 17.5), 0.35, 'wood')
        b.rope((cx, cy, 17.0), (cx + math.cos(math.radians(ang)) * 14, cy + math.sin(math.radians(ang)) * 14, 9.5), 0.0, 0.06)
        crate(b, cx + math.cos(math.radians(ang)) * 14, cy + math.sin(math.radians(ang)) * 14, 7.8, 1.4)
    # Shipyard slipway and the half-built hull on it.
    slip_x, slip_y = 355, 116
    for i in range(7):
        b.box((slip_x - 12 + i * 5.2, slip_y, 7.8 + i * 0.25), (51, 1.0, 0.35), 'wood_light', 6)
    for i in range(5):
        b.beam((slip_x - 24 + i * 12, 26, 4.6), (slip_x - 24 + i * 12, 158, 8.2), 0.5, 'wood_dark')
    ship(b, 355, 92, 7.8, 90, 0.78, sails=False, unfinished=True)
    for i in range(8):
        crate(b, 400 + RNG.uniform(-3, 3), 112 + i * 4.8, 4.7, RNG.uniform(0.8, 1.4), RNG.uniform(0, 90))
    for i in range(2):
        b.cylinder((408, 95 + i * 5, 4.7), (408, 95 + i * 5, 4.9), 2.4, 'wood_light', 10)
    # A working quay needs scale figures: dockhands along the promenade and a
    # few hands on the piers.
    for i in range(24):
        x = -356 + i * 30 + RNG.uniform(-5, 5)
        y = 83 + RNG.uniform(-5, 9)
        person(b, x, y, L.ground(x, y) + 0.2, RNG.uniform(0, 360), RNG.uniform(0.9, 1.1), RNG)
    for i, (px, py) in enumerate(((-6, 8), (6, -24), (238, -30), (238, -62), (-238, -42), (0, -92), (12, -112))):
        person(b, px, py, 5.35, RNG.uniform(0, 360), RNG.uniform(0.9, 1.05), RNG)
    return b


def lower_town():
    b = Builder('03_town_lower')
    # Street surfaces, edges and lanes.
    roads = [(-2, 158, 790, 32), (-260, 230, 40, 42), (240, 230, 40, 42), (-390, 120, 18, 58), (390, 120, 18, 58)]
    for x, y, w, d in roads:
        b.box((x, y, L.ground(x, y) + 0.04), (w, d, 0.22), 'stone_light')
    for x, y, w, d in [(-2, 141, 790, 1.4), (-2, 176, 790, 1.4)]:
        b.box((x, y, L.ground(x, y) + 0.18), (w, d, 0.25), 'stone')
    # Lower quay houses and the two lanes behind them.
    for spec in L.BUILDINGS:
        if spec[2] < 280:
            if spec[8] == 'shack':
                spec = (*spec[:3], L.ground(spec[1], spec[2]) + 0.1, *spec[4:])
            building(b, spec, RNG)
    # Stilt houses on the headland shores.
    for spec in L.SHORE_BUILDINGS:
        key, x, y, _, w, d, h, floors, style, yaw, roof = spec
        z = L.height(x, y) + 1.2
        b.box((x, y, z - 2.0), (w + 3.0, d + 3.0, 4.0), 'stone', yaw)
        for side in (-1, 1):
            px, py = local(x, y, yaw, side * (w * 0.36), 0)
            b.cylinder((px, py, z - 6.0), (px, py, z - 1.0), 0.35, 'wood_dark', 6)
        building(b, (key, x, y, z, w, d, h, floors, style, yaw, roof), RNG)
    # Timber walkways link the stilt houses along each headland.
    for side in (-1, 1):
        specs = sorted([s for s in L.SHORE_BUILDINGS if s[1] * side > 0], key=lambda s: s[2])
        for a, c in zip(specs, specs[1:]):
            ax, ay, az = a[1], a[2], L.height(a[1], a[2]) + 2.2
            cx, cy, cz = c[1], c[2], L.height(c[1], c[2]) + 2.2
            b.beam((ax, ay, az), (cx, cy, cz), 0.8, 'wood_light')
            for off in (-0.6, 0.6):
                b.rope((ax, ay + off, az + 1.0), (cx, cy + off, cz + 1.0), 1.4, 0.06)
    # Low garden walls, cisterns and a few steps at the terrace foot.
    for x in range(-360, 370, 46):
        y = 236
        if abs(x) < 30:
            continue
        b.box((x, y, L.ground(x, y) + 0.65), (34, 1.0, 1.3), 'stone')
        if x % 3 == 0:
            b.sphere((x + RNG.uniform(-8, 8), y + 3.5, L.ground(x, y) + 0.5), 1.1, 'jungle', (1.2, 1, 0.8), subdiv=0)
    return b


def market():
    b = Builder('04_market')
    b.box((0, 160, 4.68), (196, 132, 0.28), 'stone_light')
    # Simple cobble bands.
    for y in range(102, 222, 9):
        b.box((0, y, 4.83), (188, 0.18, 0.06), 'stone')
    for x, y, w, d, cloth in L.MARKET_STALLS:
        market_stall(b, x, y, L.ground(x, y) + 0.1, w, d,
                     'cream' if cloth == 'roof_sail' else 'flag_red')
    # Lantern strings and a loose crowd make the open square read as a working
    # market rather than an empty plaza from the harbor camera.
    for yy in (118, 168, 214):
        for xx in (-92, 92):
            lantern_post(b, xx, yy, L.ground(xx, yy) + 0.1, 5.5)
        b.rope((-92, yy, 9.6), (92, yy, 9.6), 0.8, 0.06)
        for xx in range(-84, 85, 12):
            b.sphere((xx, yy, 9.3), 0.22, 'lantern', subdiv=0)
    for row, count in ((110, 11), (146, 9), (184, 8), (208, 5)):
        for i in range(count):
            x = -78 + i * (156 / max(1, count - 1))
            y = row + RNG.uniform(-2.2, 2.2)
            person(b, x, y, L.ground(x, y) + 0.2, RNG.uniform(0, 360), RNG.uniform(0.9, 1.12), RNG)
    for row, count in ((126, 13), (160, 12), (196, 10), (220, 7)):
        for i in range(count):
            x = -82 + i * (164 / max(1, count - 1)) + RNG.uniform(-1.8, 1.8)
            y = row + RNG.uniform(-2.6, 2.6)
            person(b, x, y, L.ground(x, y) + 0.2, RNG.uniform(0, 360), RNG.uniform(0.88, 1.1), RNG)
    # Signal mast, crossyard, rigging, bunting and a crow's nest.
    mx, my, mz = 0, 158, 4.9
    b.cylinder((mx, my, mz), (mx, my, mz + 23), 0.32, 'wood_dark', 8, radius_b=0.18)
    b.beam((mx - 6, my, mz + 18), (mx + 6, my, mz + 18), 0.28, 'wood')
    b.beam((mx, my, mz + 22.4), (mx + 9, my - 4, mz + 15.5), 0.16, 'wood')
    b.ring((mx, my, mz + 18.5), 1.2, 0.10, 'wood', axis='z', sides=10)
    for i in range(5):
        xx = -4.5 + i * 2.25
        b.quad((mx + xx, my, mz + 19.5), (mx + xx + 1.0, my, mz + 19.5),
               (mx + xx + 1.0, my, mz + 18.1), (mx + xx, my, mz + 18.1),
               ('flag_red', 'cream', 'roof_teal')[i % 3])
    b.rope((mx, my, mz + 17), (mx - 18, my + 6, 9.0), 0.7, 0.05)
    b.rope((mx, my, mz + 17), (mx + 18, my - 6, 9.0), 0.7, 0.05)
    for i in range(7):
        xx = -15 + i * 5
        yy = my + 6 - (abs(xx) / 18) * 12
        b.quad((mx + xx, yy, 9.0 - (abs(xx) / 18) * 0.8), (mx + xx + 2.0, yy - 0.8, 8.8),
               (mx + xx + 2.0, yy - 0.8, 7.8), (mx + xx, yy, 8.0), ('flag_red', 'cream')[i % 2])
    # Well.
    wx, wy = 47, 137
    b.cylinder((wx, wy, 4.8), (wx, wy, 6.1), 2.2, 'stone', 12)
    b.cylinder((wx, wy, 6.0), (wx, wy, 6.15), 2.35, 'water_deep', 12)
    for sx in (-1.5, 1.5):
        b.beam((wx + sx, wy, 6.0), (wx + sx, wy, 8.9), 0.16, 'wood_dark')
    b.gable_roof((wx, wy, 8.8), 4.6, 4.0, 8.8, 1.4, 'roof_terra', 0, ridge='x', overhang=0.4)
    # Auction block with steps and a small canopy.
    ax, ay = -44, 188
    b.box((ax, ay, 5.25), (8, 5, 1.0), 'wood_light')
    b.box((ax - 3.5, ay, 4.9), (2.8, 5.2, 0.4), 'stone')
    for sx in (-3.4, 3.4):
        for sy in (-2.1, 2.1):
            b.beam((ax + sx, ay + sy, 5.7), (ax + sx, ay + sy, 9.4), 0.16, 'wood_dark')
    b.gable_roof((ax, ay, 9.3), 9, 6.2, 9.3, 1.8, 'roof_teal', 0, ridge='x', overhang=0.5)
    # Benches, ropes and market clutter.
    for i in range(8):
        x = -82 + i * 23
        y = 210 if i % 2 else 106
        b.box((x, y, 5.2), (5.4, 1.1, 0.25), 'wood_light')
        for sx in (-2.2, 2.2):
            b.beam((x + sx, y, 4.4), (x + sx, y, 5.2), 0.14, 'wood_dark')
    return b


def upper_town():
    b = Builder('05_town_upper')
    # Terrace surface and street.
    b.box((0, 340, L.UPPER_Z + 0.02), (640, 106, 0.4), 'stone_light')
    b.box((0, 340, L.UPPER_Z + 0.16), (620, 22, 0.18), 'stone')
    # Balustrade along the harbor edge, broken for the three stairs.
    for x in range(-310, 311, 4):
        if abs(x) < 18 or 224 < abs(x) < 262:
            continue
        b.box((x, 296, L.UPPER_Z + 0.7), (3.2, 0.55, 1.4), 'stone')
        b.box((x, 296, L.UPPER_Z + 1.45), (3.5, 0.8, 0.28), 'stone_light')
    for x in (-309, -265, -221, -18, 18, 221, 265, 309):
        b.box((x, 296, L.UPPER_Z + 0.9), (2.2, 1.2, 1.8), 'stone_light')
        b.sphere((x, 296, L.UPPER_Z + 1.95), 0.55, 'stone_dark', (1.0, 1.0, 0.8), subdiv=0)
    # Retaining wall, buttresses, niches and a coping.
    wall_mid = (L.QUAY_Z + L.UPPER_Z) / 2
    wall_h = L.UPPER_Z - L.QUAY_Z
    for x0, x1 in ((-322, -26), (26, 342)):
        b.box(((x0 + x1) / 2, 286, wall_mid), (x1 - x0, 3.0, wall_h), 'stone')
        b.box(((x0 + x1) / 2, 284.7, L.UPPER_Z + 0.15), (x1 - x0 + 2, 4.6, 0.5), 'stone_light')
        for x in range(int(x0) + 10, int(x1), 32):
            b.box((x, 283.8, wall_mid - 0.5), (5.0, 2.8, wall_h - 1.0), 'stone_light')
            b.box((x, 283.4, wall_mid + 0.4), (2.4, 0.8, 4.2), 'stone_dark')
            b.box((x, 283.2, wall_mid + 2.5), (2.4, 0.7, 2.4), 'stone_dark')
    # Grand stair, 24 steps and two landings.
    for i in range(24):
        y = 240 + i * 2.0
        z = L.QUAY_Z + (L.UPPER_Z - L.QUAY_Z) * (i + 1) / 24
        b.box((0, y, z - 0.4), (22, 2.1, 0.8), 'stone_light')
        b.box((0, y + 0.9, z - 0.05), (22, 0.25, 0.16), 'stone')
        for side in (-1, 1):
            b.beam((side * 11.2, y, z - 2.0), (side * 11.2, y, z + 1.1), 0.45, 'stone')
    for i, (x, width) in enumerate(((-238, 8), (252, 8))):
        for j in range(20):
            y = 242 + j * 2.2
            z = L.QUAY_Z + (L.UPPER_Z - L.QUAY_Z) * (j + 1) / 20
            b.box((x, y, z - 0.4), (width, 2.3, 0.8), 'stone')
            for side in (-1, 1):
                b.beam((x + side * (width / 2 + 0.2), y, z - 2.0),
                       (x + side * (width / 2 + 0.2), y, z + 0.8), 0.32, 'stone')
    # Upper buildings.
    for spec in L.BUILDINGS:
        if spec[2] >= 280:
            if spec[8] == 'shack':
                spec = (*spec[:3], L.ground(spec[1], spec[2]) + 0.1, *spec[4:])
            building(b, spec, RNG)
    # The stilted hamlet perched on the upper slope. Long foundations and
    # posts keep every hut grounded on the uneven ridge.
    for spec in L.HILLSIDE_BUILDINGS:
        key, x, y, _, w, d, h, floors, style, yaw, roof = spec
        z = L.ground(x, y) + 0.4
        b.box((x, y, z - 3.8), (w + 4.0, d + 4.0, 7.6), 'stone', yaw)
        for side in (-1, 1):
            px, py = local(x, y, yaw, side * (w * 0.34), 0)
            b.cylinder((px, py, z - 8.0), (px, py, z - 1.0), 0.38, 'wood_dark', 6)
        building(b, (key, x, y, z, w, d, h, floors, style, yaw, roof), RNG)
    # A cistern and a laundry line on the terrace.
    cx, cy = -24, 360
    b.cylinder((cx, cy, L.UPPER_Z), (cx, cy, L.UPPER_Z + 2.6), 2.8, 'stone', 12)
    b.cylinder((cx, cy, L.UPPER_Z + 2.5), (cx, cy, L.UPPER_Z + 2.65), 3.0, 'stone_light', 12)
    for i in range(3):
        b.rope((cx - 7, cy + 4 + i * 0.4, L.UPPER_Z + 4.5), (cx - 1, cy + 4 + i * 0.4, L.UPPER_Z + 4.5), 0.3, 0.03)
        b.quad((cx - 6, cy + 4 + i * 0.4, L.UPPER_Z + 4.45), (cx - 4.3, cy + 4 + i * 0.4, L.UPPER_Z + 4.45),
               (cx - 4.3, cy + 4 + i * 0.4, L.UPPER_Z + 2.9), (cx - 6, cy + 4 + i * 0.4, L.UPPER_Z + 2.9),
               ('cream', 'flag_red', 'roof_teal')[i])
    return b


def landmarks():
    b = Builder('06_landmarks')
    lighthouse(b)
    statue(b)
    watchtower(b)
    waterfall(b)
    rope_bridge(b)
    shrine(b)
    return b


def lighthouse(b):
    x, y, _ = L.LIGHTHOUSE
    z = L.ground(x, y) + 0.4
    b.cylinder((x, y, z), (x, y, z + 18.0), 3.4, 'stone', 12, radius_b=2.4)
    for i in range(6):
        z0 = z + i * 3.0
        b.cylinder((x, y, z0), (x, y, z0 + 3.0), 3.1 - i * 0.12, 'stone_light', 12,
                   radius_b=3.1 - (i + 1) * 0.12)
    for i in (1, 3, 5):
        z0 = z + i * 3.0
        b.cylinder((x, y, z0), (x, y, z0 + 2.9), 3.15 - i * 0.12, 'flag_red', 12,
                   radius_b=3.15 - (i + 1) * 0.12)
    # Gallery, lantern room and roof.
    zz = z + 18.0
    b.cylinder((x, y, zz), (x, y, zz + 0.5), 3.6, 'stone_dark', 12)
    for i in range(12):
        a = i * TAU / 12
        b.beam((x + math.cos(a) * 3.4, y + math.sin(a) * 3.4, zz + 0.5),
               (x + math.cos(a) * 3.4, y + math.sin(a) * 3.4, zz + 2.1), 0.10, 'metal')
    b.ring((x, y, zz + 2.0), 3.35, 0.09, 'metal', sides=14)
    b.cylinder((x, y, zz + 0.5), (x, y, zz + 4.5), 2.3, 'glass_warm', 10)
    b.cylinder((x, y, zz + 4.4), (x, y, zz + 5.8), 2.8, 'metal', 10, radius_b=0.2)
    b.cylinder((x, y, zz + 5.7), (x, y, zz + 6.5), 0.18, 'metal', 6)
    # Door and keeper's cottage.
    b.box((x, y - 3.1, z + 2.2), (1.8, 0.5, 3.4), 'wood_dark')
    kx, ky = x + 25, y + 9
    b.box((kx, ky, z + 2.0), (15, 11, 4.0), 'cream')
    b.gable_roof((kx, ky, z + 4.0), 15, 11, z + 4.0, 3.4, 'roof_terra', 0, ridge='x')
    window(b, kx, ky, 0, -4, -5.55, z + 1.4, 1.2, 1.5, False, True)
    window(b, kx, ky, 0, 3, -5.55, z + 1.4, 1.2, 1.5, False, True)
    door(b, kx, ky, 0, 0, -5.55, z, 1.4, 2.2)
    lantern_post(b, kx - 9, ky - 7, z, 3.0)


def statue(b):
    x, y, _ = L.STATUE
    z = 8.0
    start = len(b.verts)
    # Plinth and figure, all in one stone material so the silhouette reads from the harbor.
    b.box((x, y, z + 2.2), (11, 11, 4.4), 'stone')
    b.box((x, y, z + 4.5), (13, 13, 0.5), 'stone_light')
    base = z + 4.8
    # Boots, legs and coat.
    for side in (-1, 1):
        b.box((x + side * 1.2, y, base + 2.0), (2.0, 3.2, 4.0), 'stone')
    b.box((x, y, base + 6.8), (5.6, 3.6, 6.8), 'stone_light')
    b.sphere((x, y, base + 8.2), 1.8, 'stone', (1.8, 0.9, 2.0), subdiv=1)
    # Torso, shoulders and head.
    b.box((x, y, base + 11.4), (5.2, 3.0, 3.4), 'stone')
    b.box((x, y, base + 13.0), (7.2, 3.3, 1.3), 'stone')
    b.sphere((x, y, base + 14.4), 1.45, 'stone_light', (0.95, 0.9, 1.1), subdiv=1)
    # Tricorn hat: brim and three raised points.
    b.cylinder((x, y, base + 15.2), (x, y, base + 15.55), 2.4, 'stone_dark', 3)
    b.sphere((x, y, base + 15.9), 1.15, 'stone_dark', (1.1, 1.1, 0.55), subdiv=0)
    # Cape billowing behind.
    for i in range(3):
        b.quad((x - 2.8 + i * 2.8, y + 1.6, base + 12.8),
               (x - 2.8 + i * 2.8, y + 2.1, base + 12.8),
               (x - 4.2 + i * 3.2, y + 5.6 + i * 0.8, base + 5.5),
               (x - 5.2 + i * 3.2, y + 5.2 + i * 0.8, base + 5.5), 'stone_dark')
    # Right arm raised with a cutlass; left hand on the hip.
    b.beam((x + 2.8, y, base + 12.9), (x + 5.8, y - 0.2, base + 15.8), 0.55, 'stone')
    b.beam((x + 5.8, y - 0.2, base + 15.8), (x + 6.6, y - 0.4, base + 18.7), 0.35, 'stone_light')
    b.beam((x + 6.2, y - 0.3, base + 18.0), (x + 10.2, y - 1.8, base + 22.0), 0.18, 'metal')
    b.beam((x + 9.2, y - 1.5, base + 20.5), (x + 10.8, y - 2.1, base + 22.4), 0.25, 'metal')
    b.beam((x - 2.8, y, base + 12.9), (x - 4.5, y - 1.2, base + 9.3), 0.55, 'stone')
    b.beam((x - 4.5, y - 1.2, base + 9.3), (x - 1.4, y - 1.7, base + 7.8), 0.35, 'stone')
    # A lantern held low on the seaward side.
    b.box((x - 5.0, y - 2.3, base + 8.4), (0.9, 0.9, 1.2), 'lantern')
    # The queen is a harbor landmark: make her a little larger than life.
    scale = 1.5
    for i in range(start, len(b.verts)):
        vx, vy, vz = b.verts[i]
        b.verts[i] = (x + (vx - x) * scale, y + (vy - y) * scale, z + (vz - z) * scale)


def watchtower(b):
    x, y, _ = L.WATCHTOWER
    z = L.ground(x, y)
    # Rock platform and low wall.
    b.box((x, y, z + 0.4), (34, 30, 1.0), 'stone_dark')
    for i in range(18):
        a = i * TAU / 18
        px, py = x + math.cos(a) * 18, y + math.sin(a) * 15
        b.box((px, py, z + 1.7), (4.2, 1.4, 2.2), 'stone')
    # Tower.
    b.box((x, y, z + 11.5), (10.5, 10.5, 22.0), 'stone')
    b.box((x, y, z + 22.8), (13.0, 13.0, 0.8), 'stone_light')
    for i in range(6):
        for side in (-1, 1):
            b.box((x + side * 5.8, y - 5.5 + i * 2.2, z + 23.9), (1.5, 1.2, 1.5), 'stone_light')
            b.box((x - 5.5 + i * 2.2, y + side * 5.8, z + 23.9), (1.2, 1.5, 1.5), 'stone_light')
    for i in range(4):
        b.box((x, y, z + 4.0 + i * 4.0), (11.0, 11.0, 0.35), 'wood_dark')
    door(b, x, y, 0, 0, -5.35, z + 0.7, 2.0, 3.2)
    window(b, x, y, 0, -3.0, -5.4, z + 13.0, 1.0, 1.5, False, True)
    window(b, x, y, 0, 3.0, -5.4, z + 13.0, 1.0, 1.5, False, True)
    # Flagpole and black flag.
    b.cylinder((x, y, z + 24.6), (x, y, z + 39.0), 0.16, 'metal', 6)
    b.quad((x, y, z + 38.0), (x + 6.4, y, z + 36.6), (x + 6.4, y, z + 33.0), (x, y, z + 33.6), 'flag_black')
    b.sphere((x + 2.6, y - 0.03, z + 35.6), 0.55, 'cream', (1.0, 0.05, 1.1), subdiv=0)
    # Cannon platform on the seaward side.
    for cx in (-9, 0, 9):
        px = x + cx
        b.box((px, y - 16.0, z + 1.1), (3.6, 5.0, 1.0), 'wood_dark')
        b.cylinder((px, y - 15.0, z + 2.0), (px, y - 21.0, z + 3.6), 0.55, 'metal', 8)
        for side in (-1, 1):
            b.cylinder((px + side * 0.9, y - 15.8, z + 1.4), (px + side * 0.9, y - 15.8, z + 1.4), 0.65, 'wood', 10)


def waterfall(b):
    x, y, z = L.WATERFALL
    # A white sheet in four ribbons, with dark wet rock behind and a foaming pool.
    for i in range(7):
        xx = x - 12 + i * 4
        top = (xx, 92, 56 - i * 0.7)
        bottom = (xx + (i - 3) * 1.1, 74, 2.0)
        mid = (xx + (i - 3) * 0.5, 84, 29)
        b.quad((top[0] - 3.2, top[1], top[2]), (top[0] + 3.2, top[1], top[2]),
               (bottom[0] + 4.8, bottom[1], bottom[2]), (bottom[0] - 4.8, bottom[1], bottom[2]),
               'water' if i % 2 else 'sail')
        b.quad((top[0] - 2.0, top[1] - 0.2, top[2]), (top[0] + 2.0, top[1] - 0.2, top[2]),
               (mid[0] + 2.6, mid[1] - 0.2, mid[2]), (mid[0] - 2.6, mid[1] - 0.2, mid[2]), 'sail')
    for i in range(14):
        b.sphere((x + RNG.uniform(-10, 10), 72 + RNG.uniform(-4, 4), 2.2 + RNG.uniform(0, 1.6)),
                 RNG.uniform(1.2, 2.6), 'sail', (1.2, 0.8, 0.6), subdiv=0)
    # A small jungle shrine on the east ledge.
    sx, sy, sz = 540, 168, L.ground(540, 168) + 0.2
    b.box((sx, sy, sz + 1.8), (6.0, 4.6, 3.6), 'wood')
    b.gable_roof((sx, sy, sz + 3.6), 6.0, 4.6, sz + 3.6, 2.0, 'roof_terra', 0, ridge='x', overhang=0.8)
    b.box((sx, sy - 2.4, sz + 1.3), (2.2, 0.2, 2.2), 'wood_dark')
    lantern_post(b, sx - 4, sy - 3, sz, 2.6)
    lantern_post(b, sx + 4, sy - 3, sz, 2.6)


def rope_bridge(b):
    y = 152
    x0, x1 = 468, 534
    z0, z1 = L.ground(468, 152) + 3.0, L.ground(534, 152) + 3.0
    for x, z in ((x0, z0), (x1, z1)):
        for side in (-1, 1):
            b.beam((x, y + side * 2.0, z - 4), (x, y + side * 2.0, z + 4.0), 0.24, 'wood_dark')
    for i in range(12):
        t = i / 11
        x = x0 + (x1 - x0) * t
        z = z0 + (z1 - z0) * t - 2.0 * math.sin(math.pi * t)
        b.box((x, y, z - 0.2), (7.2, 2.4, 0.18), 'wood_light', 0)
        b.beam((x - 3.4, y, z - 0.25), (x + 3.4, y, z - 0.25), 0.10, 'wood_dark')
    for side in (-1, 1):
        b.rope((x0, y + side * 2.0, z0 + 4), (x1, y + side * 2.0, z1 + 4), 1.6, 0.10)
        b.rope((x0, y + side * 2.0, z0), (x1, y + side * 2.0, z1), 1.3, 0.10)
        for i in range(7):
            t = i / 6
            x = x0 + (x1 - x0) * t
            z = z0 + (z1 - z0) * t - 1.4 * math.sin(math.pi * t)
            b.beam((x, y + side * 2.0, z), (x, y + side * 2.0, z + 3.6), 0.07, 'rope')


def shrine(b):
    # This is the cliffside shrine; kept separate so the waterfall module can move it later.
    return


def ships():
    b = Builder('07_ships')
    for spec in L.SHIPS:
        name, x, y, yaw, scale, sails = spec
        ship(b, x, y, -1.1, yaw, scale, sails=sails, unfinished=False)
    return b


def ship(b, x, y, z, yaw, scale=1.0, sails=True, unfinished=False):
    """A stylised three-masted galleon, hull stations along local y (bow at +y)."""
    def T(lx, ly, lz):
        return local(x, y, yaw, lx * scale, ly * scale) + (z + lz * scale,)

    stations = [(-30, 3.0, 5.0, 7.2), (-26, 5.0, 3.0, 8.2), (-20, 6.6, 2.0, 8.8),
                (-10, 7.2, 1.3, 9.0), (0, 7.4, 1.1, 9.0), (10, 7.0, 1.4, 8.9),
                (20, 5.8, 2.2, 8.5), (26, 3.5, 3.5, 8.0), (30, 0.6, 5.2, 7.2)]
    # Side shell, two bands per station pair.
    for i in range(len(stations) - 1):
        y0, w0, k0, g0 = stations[i]
        y1, w1, k1, g1 = stations[i + 1]
        for side in (-1, 1):
            # lower hull from keel to waterline
            a = T(side * w0 * 0.30, y0, k0)
            bb = T(side * w1 * 0.30, y1, k1)
            c = T(side * w1, y1, 4.3)
            d = T(side * w0, y0, 4.3)
            b.quad(a, bb, c, d, 'wood_dark' if side < 0 else 'wood')
            # upper shell from waterline to gunwale
            e = T(side * w0 * 0.99, y0, g0)
            f = T(side * w1 * 0.99, y1, g1)
            b.quad(d, c, f, e, 'wood')
            # gunwale rail and a few exposed ribs
            b.beam(T(side * w0, y0, g0), T(side * w1, y1, g1), 0.22, 'wood_dark')
            if i % 2 == 0:
                b.beam(T(side * w0 * 0.94, y0, 4.4), T(side * w0 * 0.94, y0, g0 - 0.3), 0.16, 'wood_dark')
    # Deck, keel and transom.
    for i in range(len(stations) - 1):
        y0, w0, _, _ = stations[i]; y1, w1, _, _ = stations[i + 1]
        b.quad(T(-w0 * 0.92, y0, 4.6), T(w0 * 0.92, y0, 4.6),
               T(w1 * 0.92, y1, 4.6), T(-w1 * 0.92, y1, 4.6), 'wood_light')
    b.box((*local(x, y, yaw, 0, 0), z + 1.4), (1.0 * scale, 55 * scale, 1.0 * scale), 'wood_dark', yaw)
    b.quad(T(-2.4, -30, 5.0), T(2.4, -30, 5.0), T(2.8, -30, 8.4), T(-2.8, -30, 8.4), 'wood')
    # Forecastle and stern castle.
    b.box((*local(x, y, yaw, 0, 19), z + 6.1 * scale), (11.5 * scale, 9 * scale, 3.0 * scale), 'wood', yaw)
    b.box((*local(x, y, yaw, 0, -21), z + 6.4 * scale), (12.0 * scale, 13 * scale, 3.8 * scale), 'wood', yaw)
    b.box((*local(x, y, yaw, 0, -21), z + 8.4 * scale), (12.8 * scale, 14 * scale, 0.35 * scale), 'wood_dark', yaw)
    for side in (-1, 1):
        for yy in (-26, -23, -20, -17):
            b.box((*local(x, y, yaw, side * 4.8, yy), z + 7.1 * scale), (0.2 * scale, 1.1 * scale, 1.1 * scale), 'glass_warm', yaw)
    # Bowsprit and figurehead.
    b.beam(T(0, 28, 7.0), T(0, 43, 11.0), 0.34, 'wood_dark')
    b.sphere(T(0, 43.5, 11.2), 1.1 * scale, 'gold', (0.8, 1.4, 0.8), subdiv=0)
    # Masts, yards, sails and rigging.
    masts = [(-12, 25.0), (1, 31.0), (14, 23.0)]
    for my, mh in masts:
        b.cylinder(T(0, my, 4.7), T(0, my, 4.7 + mh), 0.42, 'wood_dark', 8, radius_b=0.22)
        for level, frac in ((0.32, 0.68), (0.55, 0.58), (0.76, 0.48)):
            zz = 4.7 + mh * frac
            width = 10.5 * (1 - 0.12 * level) * scale
            b.beam(T(-width, my, zz), T(width, my, zz), 0.22, 'wood')
            if sails and not unfinished:
                # Two rows of billowed cloth per yard.
                for side in (-1, 1):
                    for j in range(2):
                        x0 = side * width * (0.1 + 0.45 * j)
                        x1 = side * width * (0.1 + 0.45 * (j + 1))
                        b.quad(T(x0, my + 0.35, zz - 0.1), T(x1, my + 0.35, zz - 0.1),
                               T(x1, my + 1.4, zz - 4.4), T(x0, my + 1.4, zz - 4.4), 'sail')
                        if j == 0:
                            b.quad(T(x0, my + 0.38, zz - 2.3), T(x1, my + 0.38, zz - 2.3),
                                   T(x1, my + 0.9, zz - 2.8), T(x0, my + 0.9, zz - 2.8), 'sail_stripe')
            elif not sails and not unfinished:
                b.cylinder(T(-width * 0.85, my + 0.4, zz - 0.25), T(width * 0.85, my + 0.4, zz - 0.25),
                           0.32, 'sail', 7)
        b.rope(T(0, my, 4.7 + mh * 0.55), T(0, 30, 7.0), 0.0, 0.035)
        b.rope(T(0, my, 4.7 + mh * 0.7), T(0, -29, 8.2), 0.0, 0.035)
        for side in (-1, 1):
            b.rope(T(0, my, 4.7 + mh * 0.62), T(side * 8.2, my - 12, 5.0), 0.2, 0.03)
    # Stern flag and a skull-ish emblem.
    b.cylinder(T(0, -28, 9.3), T(0, -28, 20.0), 0.14, 'metal', 6)
    b.quad(T(0, -28, 19.7), T(5.8, -28, 18.6), T(5.8, -28, 14.8), T(0, -28, 15.4), 'flag_black')
    b.sphere(T(2.6, -28.05, 17.2), 0.7, 'cream', (1.0, 0.06, 1.1), subdiv=0)
    # Fenders, anchor and a ship's wheel near the stern.
    for yy in (-16, 2, 18):
        b.cylinder(T(7.0, yy, 5.8), T(7.0, yy, 8.4), 0.35, 'rope', 7)
    b.ring(T(0, -24, 9.8), 1.2, 0.12, 'wood', axis='x', sides=12)


def props():
    b = Builder('08_props')
    # Quay and street furniture.
    for x in range(-360, 361, 44):
        if abs(x) < 16:
            continue
        lantern_post(b, x, 103, 4.7, 3.4)
    for x in (-320, -270, -210, 150, 205, 270, 320):
        for y in (146, 184):
            barrel(b, x + RNG.uniform(-1.5, 1.5), y + RNG.uniform(-1, 1), 4.7, RNG.uniform(0.8, 1.1))
        crate(b, x + RNG.uniform(-2, 2), 176 + RNG.uniform(-1, 1), 4.7, RNG.uniform(0.7, 1.2), RNG.uniform(0, 90))
    for x in range(-300, 321, 40):
        lantern_post(b, x, 326, L.UPPER_Z, 3.4)
    for x in (-250, -190, 70, 130, 190, 250):
        barrel(b, x, 370, L.UPPER_Z, 0.9)
        crate(b, x + 3, 366, L.UPPER_Z, 0.8, 12)
    # Pier clutter and fenders.
    for _, px, y0, y1, width in L.PIERS:
        for yy in (y0 - 24, y1 + 18):
            barrel(b, px + width * 0.25, yy, 5.25, 0.9)
            crate(b, px - width * 0.25, yy - 3, 5.25, 1.0, 20)
    # Buoys, rowboats and fish baskets in the water.
    for x, y, z, yaw, scale in [(-155, -205, 0.0, 20, 1.0), (145, -228, 0.0, -14, 0.9),
                                 (-270, -145, 0.0, 65, 0.8), (270, -182, 0.0, -70, 0.9)]:
        rowboat(b, x, y, 0.0, yaw, scale)
    for x, y in [(-200, -160), (190, -190), (-90, -210)]:
        b.sphere((x, y, 0.45), 0.7, 'flag_red', (1.0, 1.0, 1.0), subdiv=1)
        b.cylinder((x, y, 0.2), (x, y, 1.6), 0.12, 'metal', 6)
    # Fish baskets and nets near the market shed.
    for i in range(7):
        bx = 290 + i * 4.2
        b.cylinder((bx, 78, 4.8), (bx, 78, 5.35), 1.0, 'wood_light', 9)
        b.sphere((bx, 78, 5.4), 0.5, 'sail', (1.3, 0.6, 0.5), subdiv=0)
    for i in range(3):
        b.ring((330 + i * 3, 70, 4.9), 1.6, 0.08, 'rope', sides=12)
    # Potted palms on the upper terrace and by tavern doors.
    for x, y in [(-300, 300), (-170, 300), (120, 300), (280, 300), (-40, 236), (45, 236)]:
        b.cylinder((x, y, L.ground(x, y) + 0.3), (x, y, L.ground(x, y) + 1.2), 1.0, 'clay' if 'clay' in L.COLORS else 'coral', 8, radius_b=0.8)
        palm(b, x, y, L.ground(x, y) + 1.1, 0, 0.38, RNG)
    return b


def rowboat(b, x, y, z, yaw, scale=1.0):
    # A simple clinker rowboat: two side strips, a floor and a transom.
    def T(lx, ly, lz):
        return local(x, y, yaw, lx * scale, ly * scale) + (z + lz * scale,)
    for side in (-1, 1):
        b.quad(T(side * 1.4, -4.2, 1.2), T(side * 1.4, 4.2, 1.4),
               T(side * 1.0, 4.8, 0.4), T(side * 1.0, -4.8, 0.4), 'wood')
        b.quad(T(side * 1.4, -4.2, 1.2), T(side * 1.4, 4.2, 1.4),
               T(side * 1.45, 4.2, 1.8), T(side * 1.45, -4.2, 1.6), 'wood_dark')
    b.box((*local(x, y, yaw, 0, 0), z + 0.7 * scale), (2.0 * scale, 8.0 * scale, 0.2 * scale), 'wood_light', yaw)
    b.quad(T(-1.4, -4.2, 1.2), T(1.4, -4.2, 1.2), T(1.0, -4.8, 0.4), T(-1.0, -4.8, 0.4), 'wood')
    b.beam(T(-1.6, 0, 1.5), T(1.6, 0, 1.5), 0.12, 'wood_dark')
    b.beam(T(0, -3.0, 1.1), T(0, 3.0, 1.3), 0.08, 'wood_dark')


def vegetation():
    b = Builder('09_vegetation')
    sc = L.scatter()
    for x, y, z, yaw, scale in sc['palms']:
        palm(b, x, y, z, yaw, scale, RNG)
    for x, y, z, yaw, scale in sc['trees']:
        jungle_tree(b, x, y, z, yaw, scale, RNG)
    for x, y, z, yaw, scale in sc['bushes']:
        bush(b, x, y, z, yaw, scale, RNG)
    # Vines on the wet east cliff and the west headland.
    for y in range(90, 230, 12):
        vine(b, 438 - RNG.uniform(0, 8), y, 48 - RNG.uniform(0, 8), RNG.uniform(12, 26), RNG)
    for y in range(-80, 150, 16):
        vine(b, -430 - RNG.uniform(0, 12), y, 42 - RNG.uniform(0, 12), RNG.uniform(8, 18), RNG)
    # Hanging green breaks up the bare cliff bands along both headland shores.
    for side in (-1, 1):
        for y in range(-220, 62, 11):
            x = side * (L.bay_half(y) + RNG.uniform(16.0, 58.0))
            z = L.height(x, y)
            if z > 8.0:
                vine(b, x, y, z + RNG.uniform(0.5, 3.0), RNG.uniform(10, 24), RNG)
    # Frame the waterfall with vines and a few crown trees; the water itself
    # stays clear so the white ribbons remain the focal point.
    for side in (-1, 1):
        for y in range(40, 170, 12):
            x = L.WATERFALL[0] + side * RNG.uniform(18.0, 32.0)
            z = L.height(x, y)
            if z > 6.0:
                vine(b, x, y, z + RNG.uniform(1.0, 3.0), RNG.uniform(8, 19), RNG)
    for x, y in ((446, 120), (502, 132), (438, 150)):
        if L.slope(x, y) < 1.2:
            jungle_tree(b, x, y, L.ground(x, y), RNG.uniform(0, 360), 1.25, RNG)
    # Flowers at the market and along the upper lane.
    for x, y, z, _, _ in sc['bushes'][:80]:
        if RNG.random() < 0.25:
            for i in range(4):
                b.sphere((x + RNG.uniform(-0.8, 0.8), y + RNG.uniform(-0.8, 0.8), z + 0.45 + RNG.uniform(0, 0.4)),
                         0.16, ('coral', 'gold', 'cream')[i % 3], subdiv=0)
    return b


MODULES = {
    '01_terrain': terrain,
    '02_harbor': harbor,
    '03_town_lower': lower_town,
    '04_market': market,
    '05_town_upper': upper_town,
    '06_landmarks': landmarks,
    '07_ships': ships,
    '08_props': props,
    '09_vegetation': vegetation,
}
