"""Assemble Brinecove as nine separate collections, then hand them to the Blender exporter."""
import math
import random
from pathlib import Path
import layout as L
from geom import Builder
from kit import (awning, balcony, barrel, bollard, building, bush, crate, door, jungle_tree,
                 lantern_post, local, market_stall, palm, person, sign, vine, window)

TAU = math.pi * 2
RNG = random.Random(49157)
ASSETS = Path(__file__).resolve().parents[1] / 'assets' / 'models'
HAS_STATUE = (ASSETS / 'pirate-queen-statue.glb').exists()
HAS_FIGUREHEAD = (ASSETS / 'galleon-figurehead.glb').exists()
HAS_WHEEL = (ASSETS / 'ships-wheel.glb').exists()


def terrain():
    b = Builder('01_terrain')
    nx, ny = 300, 240
    dx = (L.VIEW_X_MAX - L.VIEW_X_MIN) / nx
    dy = (L.VIEW_Y_MAX - L.VIEW_Y_MIN) / ny
    zs = [[L.ground(L.VIEW_X_MIN + i * dx, L.VIEW_Y_MIN + j * dy) for j in range(ny + 1)] for i in range(nx + 1)]
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
            elif zavg > 46:
                # The headland crests are dry olive grass and pale rock, not
                # the same saturated jungle floor as the sheltered slopes.
                crest = math.sin(gx * 0.018 + 1.3) * math.cos(gy * 0.013 - 0.4)
                if sl > 0.48 and crest > 0.15:
                    mat = 'rock_light' if (i + j) % 5 else 'autumn_olive'
                else:
                    mat = ('autumn_olive', 'jungle_light', 'autumn_gold')[
                        int((crest + 1.0) * 1.5) % 3]
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
        foam_ring(b, x, y, r * 1.05, 16)
    # Broken rock shelves on both headlands keep the cliff silhouette from
    # reading as one smooth sampled surface.
    for side in (-1, 1):
        for _ in range(90):
            x = side * RNG.uniform(420, 790)
            y = RNG.uniform(-220, 470)
            if L.is_water(x, y) or L.slope(x, y) < 0.45:
                continue
            z = L.height(x, y)
            if z < 4.0:
                continue
            rock_cluster(b, x, y, z - 1.2, RNG.uniform(2.0, 6.0), RNG.randint(1, 3))
    # The statue islet.
    rock_cluster(b, L.STATUE[0], L.STATUE[1], -2.5, 16.0, 10, tall=False)
    # A jagged spire lifts the statue clear of the water.
    for i in range(7):
        z = -2.0 + i * 2.0
        r = 8.5 - i * 0.8
        b.cylinder((L.STATUE[0], L.STATUE[1], z), (L.STATUE[0], L.STATUE[1], z + 2.2),
                   r, ('rock', 'rock_dark', 'rock_light')[i % 3], 9, radius_b=r * 0.86)
    for i in range(5):
        b.sphere((L.STATUE[0] + RNG.uniform(-7, 7), L.STATUE[1] + RNG.uniform(-7, 7),
                  RNG.uniform(1, 10)), RNG.uniform(1.0, 2.6), 'rock_light' if i % 2 else 'rock',
                 (1.2, 1.0, 0.8), subdiv=0)
    foam_ring(b, L.STATUE[0], L.STATUE[1], 17.5, 20)
    shoreline_foam(b)
    # A narrow, broken wet face behind the fall.  The old uniform slab read as
    # a dam from the harbor; recessed columns and side outcrops keep the cliff
    # silhouette irregular while still giving the water a dark backing.
    for i in range(11):
        t = i / 10
        x = L.WATERFALL[0] - 20 + i * 4.0
        depth = 5.0 + 2.4 * math.sin(t * math.pi)
        b.box((x, L.WATERFALL[1] + 7.0 - t * 2.0, L.WATERFALL[2] * 0.5),
              (4.2, depth, L.WATERFALL[2] * (0.86 + 0.10 * math.sin(i * 1.7))),
              ('rock_dark', 'rock_dark', 'rock', 'rock_dark')[i % 4])
    for side in (-1, 1):
        for j in range(5):
            rx = L.WATERFALL[0] + side * (24 + j * 5)
            ry = L.WATERFALL[1] - 2 + j * 2.5
            rock_cluster(b, rx, ry, L.height(rx, ry) - 1.0, RNG.uniform(3.0, 5.5), 2)
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


def foam_ring(b, x, y, radius, segments=14):
    """A broken white collar of foam around a rock or islet."""
    for i in range(segments):
        a0 = TAU * i / segments
        a1 = TAU * (i + 1) / segments
        inner = radius * (0.70 + 0.05 * math.sin(i * 2.7))
        outer = radius * (1.06 + 0.12 * math.sin(i * 1.9 + 0.7))
        z0 = 0.08 + 0.05 * math.sin(i * 3.1)
        z1 = 0.06 + 0.05 * math.cos(i * 2.3)
        p0 = (x + math.cos(a0) * inner, y + math.sin(a0) * inner, z0)
        p1 = (x + math.cos(a1) * inner, y + math.sin(a1) * inner, z1)
        p2 = (x + math.cos(a1) * outer, y + math.sin(a1) * outer, z1)
        p3 = (x + math.cos(a0) * outer, y + math.sin(a0) * outer, z0)
        b.quad(p0, p1, p2, p3, 'foam')


def shoreline_foam(b):
    for y in range(-560, 56, 13):
        hw = L.bay_half(y)
        for side in (-1, 1):
            x = side * (hw + 1.5)
            wobble = 2.2 * math.sin(y * 0.18 + side)
            b.quad((x, y - 5.5, 0.09), (x + side * (3.6 + wobble), y - 4.8, 0.06),
                   (x + side * (3.2 + wobble), y + 4.8, 0.07), (x, y + 5.5, 0.10), 'foam')
            b.quad((x + side * 3.0, y - 4.2, 0.04),
                   (x + side * (11.0 + wobble), y - 3.4, 0.03),
                   (x + side * (10.0 + wobble), y + 3.4, 0.03),
                   (x + side * 3.0, y + 4.2, 0.04), 'water_shallow')
            # Two broad shallow shelves fade the deep blue into the shore.
            b.quad((x + side * 8.0, y - 6.0, 0.02),
                   (x + side * (42.0 + wobble), y - 5.0, 0.01),
                   (x + side * (38.0 + wobble), y + 5.0, 0.01),
                   (x + side * 8.0, y + 6.0, 0.02), 'water_shallow')
            b.quad((x + side * 38.0, y - 6.0, 0.005),
                   (x + side * (82.0 + wobble), y - 5.0, 0.0),
                   (x + side * (78.0 + wobble), y + 5.0, 0.0),
                   (x + side * 38.0, y + 6.0, 0.005), 'water_mid')


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
        # A stone arch header over the door instead of a square lintel.
        for k in range(7):
            a = math.pi * (k + 0.5) / 7
            b.box((x + math.cos(a) * 3.0, L.QUAY_Y - 2.58, 4.6 + math.sin(a) * 2.4),
                  (0.95, 0.36, 1.15), 'stone_light' if k % 2 else 'stone')
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
    b.box((0, 86, 4.62), (780, 42, 0.25), 'cobble')
    for x in (-130, 135):
        for i in range(6):
            b.box((x, L.QUAY_Y - 1.0 - i * 0.8, 4.3 - i * 0.7), (9.0, 0.9, 0.3), 'stone')
    # Palms in stone planters line the working quay, as in the harbor refs.
    for px, py in ((-330, 72), (-280, 96), (-180, 72), (-110, 96), (110, 96), (180, 72),
                   (280, 96), (330, 72), (-200, 96), (200, 96), (-300, 72), (300, 72)):
        pz = L.ground(px, py)
        b.cylinder((px, py, pz + 0.05), (px, py, pz + 1.0), 1.25, 'stone_light', 9, radius_b=0.95)
        b.cylinder((px, py, pz + 0.95), (px, py, pz + 1.08), 1.12, 'clay', 9)
        palm(b, px, py, pz + 1.05, RNG.uniform(0, 360), RNG.uniform(0.62, 0.82), RNG)
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
    for cx, cy, ang in ((-334, 84, -22), (412, 128, 16)):
        b.beam((cx - 4, cy, 4.7), (cx, cy, 18.0), 0.5, 'wood_dark')
        b.beam((cx + 4, cy, 4.7), (cx, cy, 18.0), 0.5, 'wood_dark')
        b.beam((cx, cy, 15.0), (cx + math.cos(math.radians(ang)) * 16, cy + math.sin(math.radians(ang)) * 16, 17.5), 0.35, 'wood')
        b.rope((cx, cy, 17.0), (cx + math.cos(math.radians(ang)) * 14, cy + math.sin(math.radians(ang)) * 14, 9.5), 0.0, 0.06)
        crate(b, cx + math.cos(math.radians(ang)) * 14, cy + math.sin(math.radians(ang)) * 14, 7.8, 1.4)
    # Shipyard slipway and the half-built hull on it.
    slip_x, slip_y = 352, 118
    for i in range(7):
        b.box((slip_x - 12 + i * 5.2, slip_y, 7.2 + i * 0.25), (54, 1.0, 0.35), 'wood_light', 6)
    for i in range(5):
        b.beam((slip_x - 24 + i * 12, 26, 4.6), (slip_x - 24 + i * 12, 158, 8.0), 0.55, 'wood_dark')
    ship(b, slip_x, 96, 6.2, 90, 1.02, sails=False, unfinished=True)
    # Cradle blocks and staging around the half-built hull.
    for yy in (58, 78, 98, 118, 138):
        for side in (-1, 1):
            b.box((slip_x + side * 6.5, yy, 7.3), (2.2, 3.4, 2.6), 'wood_dark', 0)
            b.beam((slip_x + side * 9.5, yy, 6.0), (slip_x + side * 7.0, yy, 12.0), 0.22, 'wood')
    for yy in (52, 68, 84, 100, 116, 132, 148):
        b.beam((slip_x - 14, yy, 8.2), (slip_x + 14, yy, 8.2), 0.14, 'wood_dark')
    for i in range(8):
        crate(b, 400 + RNG.uniform(-3, 3), 112 + i * 4.8, 4.7, RNG.uniform(0.8, 1.4), RNG.uniform(0, 90))
    for i in range(2):
        b.cylinder((408, 95 + i * 5, 4.7), (408, 95 + i * 5, 4.9), 2.4, 'wood_light', 10)
    # Stacks of long planks and a shipwright's shed.
    for i in range(5):
        b.box((398, 72 + i * 2.2, 5.0 + i * 0.35), (28, 1.6, 0.32), 'wood_light', 8)
    b.box((326, 140, 8.0), (22, 14, 6.0), 'wood', 0)
    b.gable_roof((326, 140, 11.0), 23, 15, 11.0, 3.0, 'roof_terra', 0, ridge='x', overhang=0.8)
    for x, y in ((320, 146), (332, 146), (344, 146)):
        person(b, x, y, 4.8, RNG.uniform(0, 360), 1.0, RNG)
    # A working quay needs scale figures: dockhands along the promenade and a
    # few hands on the piers.
    for i in range(24):
        x = -356 + i * 30 + RNG.uniform(-5, 5)
        y = 83 + RNG.uniform(-5, 9)
        person(b, x, y, L.ground(x, y) + 0.2, RNG.uniform(0, 360), RNG.uniform(0.9, 1.1), RNG)
    for i, (px, py) in enumerate(((-6, 8), (6, -24), (238, -30), (238, -62), (-238, -42), (0, -92), (12, -112))):
        person(b, px, py, 5.35, RNG.uniform(0, 360), RNG.uniform(0.9, 1.05), RNG)
    return b


def pave_band(b, y0, y1, skip_market=True):
    """Pave a street band in terrain-following tiles, leaving the market open."""
    step = 26.0
    x = -372.0
    i = 0
    while x < 372.0:
        cx = x + step / 2
        if not (skip_market and -108.0 < cx < 108.0 and y0 < 228.0):
            cy = (y0 + y1) / 2
            z = L.ground(cx, cy)
            b.box((cx, cy, z + 0.05), (step + 0.4, y1 - y0, 0.22),
                  'cobble_dark' if i % 7 == 0 else 'cobble')
        x += step
        i += 1
    # Planters and laundry break up the paved bands and tie them to the walls.
    for px in range(-350, 351, 44):
        if skip_market and -112 < px < 112 and y0 < 228.0:
            continue
        pz = L.ground(px, y0 + 2.2)
        b.box((px, y0 + 2.2, pz + 0.38), (3.8, 1.1, 0.75), 'stone_light')
        bush(b, px, y0 + 2.2, pz + 0.75, 0.0, 0.85, RNG)
    for lx in range(-330, 331, 92):
        if skip_market and -118 < lx < 118 and y0 < 228.0:
            continue
        ly = y0 + 4.0
        lz = L.ground(lx, ly)
        b.beam((lx, ly, lz), (lx, ly, lz + 5.4), 0.12, 'wood_dark')
        b.beam((lx + 24, ly + 5.0, lz), (lx + 24, ly + 5.0, lz + 5.4), 0.12, 'wood_dark')
        b.rope((lx, ly, lz + 5.0), (lx + 24, ly + 5.0, lz + 5.0), 0.5, 0.03)
        for k in range(3):
            qx = lx + 4 + k * 6.4
            b.quad((qx, ly + k * 1.25, lz + 4.95), (qx + 4.6, ly + k * 1.25, lz + 4.95),
                   (qx + 4.6, ly + k * 1.25, lz + 2.8), (qx, ly + k * 1.25, lz + 2.8),
                   ('canvas', 'canvas_red', 'canvas_teal')[k])


def lower_town():
    b = Builder('03_town_lower')
    # Street surfaces, edges and lanes.
    roads = [(-260, 230, 34, 10), (240, 230, 34, 10), (-390, 120, 12, 58), (390, 120, 12, 58)]
    for x, y, w, d in roads:
        b.box((x, y, L.ground(x, y) + 0.04), (w, d, 0.22), 'cobble')
    for y0, y1 in ((137, 179), (210, 242), (266, 282)):
        pave_band(b, y0, y1)
    # Lower quay houses and the two lanes behind them.
    for spec in L.DENSE_LOTS:
        if spec[2] < 280:
            if spec[0].startswith(('slope-', 'ridge-')):
                b.box((spec[1], spec[2], spec[3] - 2.1), (spec[4] + 1.0, spec[5] + 1.0, 4.2),
                      'stone', spec[9])
            if spec[0].startswith('slope-') and sum(map(ord, spec[0])) % 3 == 0:
                lx, ly = local(spec[1], spec[2], spec[9], -spec[4] / 2 - 0.7, spec[5] * 0.22)
                for dz in (0.0, 1.0):
                    b.beam((lx + dz, ly, spec[3]), (lx + dz, ly, spec[3] + 5.2), 0.10, 'wood_dark')
                for r in range(6):
                    b.beam((lx, ly, spec[3] + 0.8 + r * 0.75), (lx + 1.0, ly, spec[3] + 0.8 + r * 0.75),
                           0.06, 'wood')
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
    # Street life: pairs of neighbours, porters and children along the lanes.
    for row_y, count in ((88, 22), (168, 26), (232, 18), (262, 12)):
        for i in range(count):
            x = RNG.uniform(-360, 360)
            y = row_y + RNG.uniform(-4.5, 4.5)
            if L.in_lot(x, y, 2.0) or L.on_market(x, y, 1.0):
                continue
            person(b, x, y, L.ground(x, y) + 0.2, RNG.uniform(0, 360), RNG.uniform(0.86, 1.12), RNG)
    return b


def market():
    b = Builder('04_market')
    b.box((0, 160, 4.68), (196, 132, 0.28), 'cobble')
    # Simple cobble bands.
    for y in range(102, 222, 9):
        b.box((0, y, 4.83), (188, 0.18, 0.06), 'cobble_dark')
    # A low lantern string crosses just in front of the market camera.
    for xx in (-92, 92):
        lantern_post(b, xx, 96, L.ground(xx, 96) + 0.1, 5.0)
    b.rope((-92, 96, 9.1), (92, 96, 9.1), 0.9, 0.05)
    for xx in range(-84, 85, 12):
        b.sphere((xx, 96, 8.8), 0.22, 'lantern', subdiv=0)
    for i, (x, y, w, d, cloth) in enumerate(L.MARKET_STALLS):
        yaw = RNG.uniform(-9, 9) if i % 3 else 0.0
        canvas = ('canvas', 'canvas_red', 'canvas_teal')[i % 3]
        market_stall(b, x, y, L.ground(x, y) + 0.1, w, d, canvas, yaw)
        # A vendor behind every counter and a pair of customers in front.
        person(b, x - w * 0.16, y + d * 0.27, L.ground(x, y) + 0.2, 180, RNG.uniform(0.92, 1.05), RNG)
        for side in (-1, 1):
            person(b, x + side * (w * 0.22 + RNG.uniform(0, 1.2)), y - d * 0.58,
                   L.ground(x, y) + 0.2, RNG.uniform(0, 360), RNG.uniform(0.88, 1.08), RNG)
        barrel(b, x - w * 0.58, y + d * 0.25, L.ground(x, y) + 0.1, 0.72)
        crate(b, x + w * 0.55, y - d * 0.18, L.ground(x, y) + 0.1, 0.8, RNG.uniform(0, 90))
    # South-edge stalls frame the market camera and close the empty cobbles.
    for x, cloth in ((-76, 'canvas_red'), (58, 'canvas_teal')):
        y = 98
        market_stall(b, x, y, L.ground(x, y) + 0.1, 13, 8, cloth, -7 if x < 0 else 8)
        person(b, x - 2, y + 2.4, L.ground(x, y) + 0.2, 180, 1.0, RNG)
    for x, y, cloth in ((-96, 108, 'canvas_red'), (96, 112, 'canvas_teal')):
        b.cylinder((x, y, L.ground(x, y) + 0.1), (x, y, L.ground(x, y) + 7.5), 0.12, 'wood_dark', 6)
        b.quad((x, y, L.ground(x, y) + 7.4), (x + 4.0, y, L.ground(x, y) + 6.8),
               (x + 4.0, y, L.ground(x, y) + 4.4), (x, y, L.ground(x, y) + 5.0), cloth)
    for x, y in ((-70, 105), (-30, 105), (30, 105), (70, 105)):
        barrel(b, x, y, L.ground(x, y) + 0.1, 0.8)
        crate(b, x + 2.2, y + 1.2, L.ground(x, y) + 0.1, 0.8, 12)
    # Stone arcades frame the square and give the market edges real depth.
    for side in (-1, 1):
        x = side * 96
        for y in range(106, 222, 14):
            b.cylinder((x, y, L.ground(x, y) + 0.1), (x, y, L.ground(x, y) + 4.3), 0.38, 'stone_light', 8)
            b.box((x, y, L.ground(x, y) + 4.5), (1.1, 1.1, 0.45), 'stone', 0)
        b.box((x, 164, L.ground(x, 164) + 4.85), (1.6, 122, 0.6), 'stone_light')
        b.box((x - side * 1.2, 164, L.ground(x, 164) + 5.2), (2.6, 122, 0.25), 'wood_dark')
        for y in range(110, 220, 18):
            b.quad((x - side * 1.0, y - 6, L.ground(x, y) + 5.35),
                   (x - side * 3.0, y - 6, L.ground(x, y) + 4.6),
                   (x - side * 3.0, y + 6, L.ground(x, y) + 4.6),
                   (x - side * 1.0, y + 6, L.ground(x, y) + 5.35),
                   'canvas' if (y // 18) % 2 else 'canvas_red')
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
    # A thicker, uneven crowd between the stall rows sells the market as a
    # working place rather than a paved square with a few extras.
    for _ in range(46):
        x = RNG.uniform(-88, 88)
        y = RNG.uniform(100, 223)
        person(b, x, y, L.ground(x, y) + 0.2, RNG.uniform(0, 360), RNG.uniform(0.82, 1.12), RNG)
    # Handcarts, fish baskets and sack piles fill the lanes between stalls.
    for cx, cy, cyaw in ((-66, 150, 18), (66, 152, -24), (-52, 206, 8), (54, 204, -12)):
        cz = L.ground(cx, cy) + 0.1
        b.box((cx, cy, cz + 0.75), (4.2, 2.0, 0.35), 'wood_light', cyaw)
        for side in (-1, 1):
            wx, wy = local(cx, cy, cyaw, side * 1.45, 0.35)
            b.ring((wx, wy, cz + 0.45), 0.62, 0.16, 'wood_dark', axis='x', sides=10)
            b.cylinder((wx - 0.08, wy, cz + 0.45), (wx + 0.08, wy, cz + 0.45), 0.18, 'metal', 8)
        for k in range(3):
            crate(b, cx + RNG.uniform(-1.4, 1.4), cy + RNG.uniform(-0.7, 0.7), cz + 0.4,
                  RNG.uniform(0.45, 0.7), cyaw + RNG.uniform(-20, 20))
    for fx, fy in ((-78, 120), (76, 118), (-74, 224), (74, 222)):
        fz = L.ground(fx, fy) + 0.1
        b.cylinder((fx, fy, fz), (fx, fy, fz + 0.7), 0.7, 'wood', 10, radius_b=0.55)
        for k in range(5):
            b.sphere((fx + RNG.uniform(-0.5, 0.5), fy + RNG.uniform(-0.5, 0.5), fz + 0.75),
                     RNG.uniform(0.16, 0.26), 'sail', (1.3, 0.8, 0.7), subdiv=0)
    # Potted palms soften the hard market edges and frame the two entrances.
    for px, py in ((-66, 102), (66, 102), (-66, 214), (66, 214), (0, 102), (0, 212)):
        pz = L.ground(px, py)
        b.cylinder((px, py, pz + 0.1), (px, py, pz + 1.2), 1.1, 'clay', 9, radius_b=0.8)
        palm(b, px, py, pz + 1.1, RNG.uniform(0, 360), 0.62, RNG)
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
    b.box((0, 340, L.UPPER_Z + 0.02), (640, 106, 0.4), 'cobble')
    b.box((0, 284, L.UPPER_Z + 0.02), (640, 10, 0.4), 'cobble')
    b.box((0, 340, L.UPPER_Z + 0.16), (620, 22, 0.18), 'cobble_dark')
    for y0, y1 in ((354, 400), (424, 452)):
        pave_band(b, y0, y1, skip_market=False)
    # Balustrade along the harbor edge, broken for the three stairs.
    for x in range(-310, 311, 4):
        if abs(x) < 18 or 224 < abs(x) < 262:
            continue
        b.box((x, 283, L.UPPER_Z + 0.7), (3.2, 0.55, 1.4), 'stone')
        b.box((x, 283, L.UPPER_Z + 1.45), (3.5, 0.8, 0.28), 'stone_light')
    for x in (-309, -265, -221, -18, 18, 221, 265, 309):
        b.box((x, 283, L.UPPER_Z + 0.9), (2.2, 1.2, 1.8), 'stone_light')
        b.sphere((x, 283, L.UPPER_Z + 1.95), 0.55, 'stone_dark', (1.0, 1.0, 0.8), subdiv=0)
    # Retaining wall, buttresses, niches and a coping.
    wall_mid = (L.QUAY_Z + L.UPPER_Z) / 2
    wall_h = L.UPPER_Z - L.QUAY_Z
    for x0, x1 in ((-322, -252), (-224, -26), (26, 224), (262, 342)):
        b.box(((x0 + x1) / 2, 281, wall_mid), (x1 - x0, 3.0, wall_h), 'stone')
        b.box(((x0 + x1) / 2, 279.7, L.UPPER_Z + 0.15), (x1 - x0 + 2, 4.6, 0.5), 'stone_light')
        # Warm ashlar courses and hanging greenery give the tall retaining
        # wall a human scale instead of one long grey viaduct face.
        for zz in range(7, 29, 4):
            b.box(((x0 + x1) / 2, 279.42, zz), (x1 - x0, 0.36, 0.20), 'stone_light')
        for x in range(int(x0) + 10, int(x1), 32):
            b.box((x, 278.8, wall_mid - 0.5), (5.0, 2.8, wall_h - 1.0), 'stone_light')
            b.box((x, 278.4, wall_mid + 0.4), (2.4, 0.8, 4.2), 'stone_dark')
            b.box((x, 278.2, wall_mid + 2.5), (2.4, 0.7, 2.4), 'stone_dark')
    for i in range(30):
        vx = RNG.uniform(-316, 336)
        if abs(vx) < 32:
            continue
        vine(b, vx, 278.9, L.UPPER_Z - 0.2, RNG.uniform(3.4, 9.5), RNG)
    # A planted string course halfway up breaks the 25 m wall into two tiers.
    for x0, x1 in ((-322, -252), (-224, -26), (26, 224), (262, 342)):
        b.box(((x0 + x1) / 2, 278.95, 17.5), (x1 - x0, 1.35, 0.55), 'stone_light')
        for x in range(int(x0) + 12, int(x1), 24):
            b.box((x, 278.70, 18.2), (2.8, 1.1, 0.85), 'stone')
            bush(b, x, 278.70, 18.55, 0.0, 0.62, RNG)
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
    for spec in L.DENSE_LOTS:
        if spec[2] >= 280:
            if spec[0].startswith(('slope-', 'ridge-')):
                b.box((spec[1], spec[2], spec[3] - 2.1), (spec[4] + 1.0, spec[5] + 1.0, 4.2),
                      'stone', spec[9])
            if spec[0].startswith('slope-') and sum(map(ord, spec[0])) % 3 == 0:
                lx, ly = local(spec[1], spec[2], spec[9], -spec[4] / 2 - 0.7, spec[5] * 0.22)
                for dz in (0.0, 1.0):
                    b.beam((lx + dz, ly, spec[3]), (lx + dz, ly, spec[3] + 5.2), 0.10, 'wood_dark')
                for r in range(6):
                    b.beam((lx, ly, spec[3] + 0.8 + r * 0.75), (lx + 1.0, ly, spec[3] + 0.8 + r * 0.75),
                           0.06, 'wood')
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
    # The terrace lane is a lived-in street, not a viewing platform.
    for row in (318, 352, 372):
        for i in range(24):
            x = RNG.uniform(-320, 320)
            y = row + RNG.uniform(-3.0, 3.0)
            if L.in_lot(x, y, 2.0):
                continue
            person(b, x, y, L.ground(x, y) + 0.2, RNG.uniform(0, 360), RNG.uniform(0.88, 1.1), RNG)
    # Foreground pots and a laundry line frame the terrace view.
    for x, y in ((-14, 310), (14, 310), (-34, 306), (34, 306)):
        b.cylinder((x, y, L.UPPER_Z + 0.1), (x, y, L.UPPER_Z + 1.1), 0.9, 'clay', 8, radius_b=0.7)
        palm(b, x, y, L.UPPER_Z + 1.0, 0, 0.36, RNG)
    b.rope((-36, 314, L.UPPER_Z + 4.8), (36, 314, L.UPPER_Z + 4.8), 0.5, 0.04)
    for i in range(4):
        x = -24 + i * 16
        b.quad((x, 314, L.UPPER_Z + 4.7), (x + 6, 314, L.UPPER_Z + 4.7),
               (x + 6, 314, L.UPPER_Z + 2.7), (x, 314, L.UPPER_Z + 2.7),
               ('canvas', 'canvas_red', 'canvas_teal', 'canvas')[i])
    # A secondary stair climbs from the terrace to the ridge hamlet.
    for i in range(15):
        y = 388 + i * 2.2
        z = L.UPPER_Z + 0.4 + i * 1.9
        b.box((0, y, z), (10, 2.3, 0.8), 'stone_light')
        for side in (-1, 1):
            b.beam((side * 5.2, y, z - 1.8), (side * 5.2, y, z + 0.7), 0.30, 'stone')
    return b


def landmarks():
    b = Builder('06_landmarks')
    lighthouse(b)
    if not HAS_STATUE:
        statue(b)
    watchtower(b)
    waterfall(b)
    rope_bridge(b)
    shrine(b)
    return b


def lighthouse(b):
    x, y, _ = L.LIGHTHOUSE
    z = L.ground(x, y) + 0.4
    # Broad rock plinth, then a tall tapered tower with three broad red bands.
    b.cylinder((x, y, z - 1.5), (x, y, z + 2.0), 7.2, 'stone', 14, radius_b=5.4)
    b.cylinder((x, y, z + 1.9), (x, y, z + 2.35), 6.8, 'stone_light', 14)
    z0 = z + 2.2
    bands = 11
    for i in range(bands):
        r0 = 4.35 - i * 0.13
        r1 = 4.35 - (i + 1) * 0.13
        mat = 'flag_red' if i in (1, 2, 6, 7, 10) else 'cream'
        b.cylinder((x, y, z0 + i * 2.55), (x, y, z0 + (i + 1) * 2.55), r0, mat, 14, radius_b=r1)
    # Gallery and railing.
    zz = z0 + bands * 2.55
    b.cylinder((x, y, zz), (x, y, zz + 0.55), 3.1, 'stone_dark', 14, radius_b=3.0)
    for i in range(14):
        a = i * TAU / 14
        px, py = x + math.cos(a) * 3.3, y + math.sin(a) * 3.3
        b.beam((px, py, zz + 0.5), (px, py, zz + 2.25), 0.10, 'metal')
    b.ring((x, y, zz + 2.15), 3.3, 0.10, 'metal', sides=16)
    b.ring((x, y, zz + 1.1), 3.3, 0.06, 'metal', sides=16)
    # Lantern room, glazing bars, dome and lightning rod.
    b.cylinder((x, y, zz + 0.55), (x, y, zz + 3.6), 2.35, 'glass_warm', 12)
    for i in range(8):
        a = i * TAU / 8
        px, py = x + math.cos(a) * 2.34, y + math.sin(a) * 2.34
        b.beam((px, py, zz + 0.6), (px, py, zz + 3.55), 0.08, 'metal')
    b.cylinder((x, y, zz + 3.55), (x, y, zz + 4.1), 2.75, 'metal', 12, radius_b=2.35)
    b.cylinder((x, y, zz + 4.05), (x, y, zz + 5.25), 2.55, 'roof_teal', 12, radius_b=0.15)
    b.cylinder((x, y, zz + 5.2), (x, y, zz + 6.1), 0.10, 'metal', 6)
    b.sphere((x, y, zz + 6.2), 0.35, 'gold', subdiv=0)
    # Door, small windows and the keeper's cottage at the foot.
    b.box((x, y - 4.35, z + 4.1), (1.9, 0.5, 3.6), 'wood_dark')
    for f in (0.35, 0.62):
        b.box((x - 4.2, y, z + 2.2 + f * 20), (0.25, 1.1, 1.4), 'glass_warm', 90)
    kx, ky = x + 24, y + 12
    kz = L.ground(kx, ky) + 0.2
    b.box((kx, ky, kz + 2.2), (17, 12, 4.4), 'cream')
    b.gable_roof((kx, ky, kz + 4.4), 17, 12, kz + 4.4, 3.8, 'roof_terra', 0, ridge='x')
    window(b, kx, ky, 0, -4.4, -6.05, kz + 1.5, 1.25, 1.55, True, True)
    window(b, kx, ky, 0, 4.2, -6.05, kz + 1.5, 1.25, 1.55, True, True)
    door(b, kx, ky, 0, 0, -6.05, kz, 1.5, 2.3)
    b.box((kx + 5.5, ky + 2.5, kz + 6.4), (1.1, 1.1, 3.4), 'stone')
    b.box((kx + 5.5, ky + 2.5, kz + 8.2), (1.4, 1.4, 0.3), 'stone_dark')
    lantern_post(b, kx - 10, ky - 8, kz, 3.2)
    # A low signal wall and a pair of cannon on the seaward edge.
    for i in range(10):
        px = x - 18 + i * 4.2
        b.box((px, y - 15.0, z + 1.0), (4.2, 1.2, 2.0), 'stone')
    # A lived-in headland: a stone path links cottage and tower, a rope fence
    # follows the cliff edge, and garden beds and palms break up the lawn.
    for i in range(22):
        t = i / 21
        px = x + 24 * t
        py = y + 12 * t
        pz = L.ground(px, py) + 0.10
        b.box((px, py, pz), (2.3, 2.3, 0.18),
              'stone_light' if i % 4 else 'sand', 0)
    for i in range(13):
        px = x - 30 + i * 5.0
        py = y - 27.0
        pz = L.ground(px, py)
        b.beam((px, py, pz), (px, py, pz + 2.3), 0.16, 'wood_dark')
        if i < 12:
            qx = px + 5.0
            qz = L.ground(qx, py)
            b.beam((px, py, pz + 1.8), (qx, py, qz + 1.8), 0.07, 'rope')
            b.beam((px, py, pz + 0.9), (qx, py, qz + 0.9), 0.05, 'rope')
    for side, off in ((-1, -18), (1, 18)):
        gx, gy = x + off, y + 2
        gz = L.ground(gx, gy)
        b.box((gx, gy, gz + 0.35), (7.5, 3.2, 0.7), 'stone')
        for i in range(4):
            bush(b, gx - 2.6 + i * 1.8, gy, gz + 0.7, 0.0, 0.55, RNG)
    for i in range(16):
        rx = x - 38 + RNG.uniform(0, 76)
        ry = y - 34 + RNG.uniform(-5, 2)
        rock_cluster(b, rx, ry, L.height(rx, ry) - 0.8, RNG.uniform(1.4, 3.2), 2)
    for px, py, scale in ((-30, -8, 1.0), (34, 16, 0.82), (18, -20, 0.7)):
        palm(b, x + px, y + py, L.ground(x + px, y + py), RNG.uniform(0, 360), scale, RNG)
    b.box((x + 31, y + 19, L.ground(x + 31, y + 19) + 1.1), (4.0, 3.0, 2.2), 'wood')
    b.gable_roof((x + 31, y + 19, L.ground(x + 31, y + 19) + 2.1), 4.0, 3.0,
                 L.ground(x + 31, y + 19) + 2.1, 1.4, 'roof_terra', 0, ridge='x', overhang=0.5)


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
    # Rock platform and low defensive wall.
    b.box((x, y, z + 0.4), (38, 34, 1.0), 'stone_dark')
    for i in range(22):
        a = i * TAU / 22
        px, py = x + math.cos(a) * 20, y + math.sin(a) * 17
        b.box((px, py, z + 1.9), (4.4, 1.5, 2.4), 'stone')
    # A taller, battered square tower with corner buttresses.
    b.box((x, y, z + 14.0), (12.0, 12.0, 26.0), 'stone')
    for side in (-1, 1):
        for sy in (-1, 1):
            b.box((x + side * 5.6, y + sy * 5.6, z + 8.0), (2.0, 2.0, 15.0), 'stone_light')
    b.box((x, y, z + 27.3), (14.6, 14.6, 0.8), 'stone_light')
    for i in range(7):
        for side in (-1, 1):
            b.box((x + side * 6.7, y - 6.3 + i * 2.1, z + 28.4), (1.7, 1.4, 1.8), 'stone_light')
            b.box((x - 6.3 + i * 2.1, y + side * 6.7, z + 28.4), (1.4, 1.7, 1.8), 'stone_light')
    for i in range(5):
        b.box((x, y, z + 3.8 + i * 4.2), (12.2, 12.2, 0.35), 'wood_dark')
    door(b, x, y, 0, 0, -6.1, z + 0.7, 2.4, 3.6)
    for f in (1, 2, 3):
        window(b, x, y, 0, -2.6, -6.1, z + 5.0 + f * 4.4, 1.0, 1.6, False, True)
        window(b, x, y, 0, 2.6, -6.1, z + 5.0 + f * 4.4, 1.0, 1.6, False, True)
    # Black banner and signal pole.
    b.cylinder((x, y, z + 28.7), (x, y, z + 44.0), 0.18, 'metal', 6)
    b.quad((x, y, z + 43.0), (x + 7.2, y, z + 41.4), (x + 7.2, y, z + 35.4), (x, y, z + 36.2), 'flag_black')
    b.sphere((x + 2.9, y - 0.05, z + 39.3), 0.65, 'cream', (1.0, 0.05, 1.2), subdiv=0)
    # Cannon platform on the seaward side and a second pair at the tower top.
    for cx in (-10, 0, 10):
        px = x + cx
        b.box((px, y - 18.0, z + 1.2), (3.8, 5.2, 1.1), 'wood_dark')
        b.cylinder((px, y - 17.0, z + 2.2), (px, y - 23.0, z + 3.8), 0.55, 'metal', 8)
        for side in (-1, 1):
            b.cylinder((px + side * 0.95, y - 17.8, z + 1.5), (px + side * 0.95, y - 17.8, z + 1.5),
                       0.65, 'wood', 10)
    for side in (-1, 1):
        b.box((x + side * 3.5, y - 5.0, z + 28.7), (2.4, 3.2, 0.9), 'wood_dark')
        b.cylinder((x + side * 3.5, y - 6.0, z + 29.4), (x + side * 3.5, y - 10.2, z + 30.3), 0.42, 'metal', 7)


def waterfall(b):
    x, y, z = L.WATERFALL
    # A cluster of narrow ribbons rather than one wide sheet.  Varying widths,
    # lengths and a few dry gaps read as falling water on rock from the harbor.
    ribbons = ((-13.6, 2.0, 0.94), (-10.4, 2.8, 1.0), (-7.2, 1.7, 0.82),
               (-3.8, 3.2, 0.90), (0.4, 2.4, 1.0), (3.8, 3.0, 0.86),
               (7.4, 1.9, 0.96), (10.8, 2.7, 0.88), (13.8, 1.6, 0.78))
    for i, (off, width, length) in enumerate(ribbons):
        xx = x + off
        top_z = z - 2.0 - abs(off) * 0.10
        bottom_z = 4.2 + (1.0 - length) * 8.0
        sway = math.sin(i * 1.9) * 1.4
        b.quad((xx - width, y - 1.0 + sway, top_z), (xx + width, y - 1.0 + sway, top_z),
               (xx + width * 1.16, y - 2.0, bottom_z), (xx - width * 1.16, y - 2.0, bottom_z),
               'water' if i in (1, 4, 7) else 'sail')
        b.quad((xx - width * 0.55, y - 1.25 + sway, top_z),
               (xx + width * 0.55, y - 1.25 + sway, top_z),
               (xx + width * 0.7, y - 2.25, bottom_z + 2.0),
               (xx - width * 0.7, y - 2.25, bottom_z + 2.0), 'sail')
    for i in range(22):
        b.sphere((x + RNG.uniform(-15, 15), y - 7 + RNG.uniform(-3, 3),
                  4.6 + RNG.uniform(0, 2.2)), RNG.uniform(1.2, 2.8), 'sail',
                 (1.3, 0.8, 0.55), subdiv=0)
    for i in range(10):
        rx = x + RNG.uniform(-22, 22)
        b.sphere((rx, y - RNG.uniform(5, 12), 3.6 + RNG.uniform(0, 1.4)),
                 RNG.uniform(1.2, 2.4), 'rock_dark' if i % 2 else 'rock',
                 (1.2, 0.9, 0.7), subdiv=0)
    # A shallow turquoise pool and a dark wet lip under the fall.
    b.quad((x - 30, y - 11, 4.25), (x + 30, y - 11, 4.25),
           (x + 34, y + 2, 4.25), (x - 34, y + 2, 4.25), 'water_shallow')
    b.quad((x - 26, y - 10, 4.30), (x + 26, y - 10, 4.30),
           (x + 30, y - 2, 4.30), (x - 30, y - 2, 4.30), 'foam')
    # A small jungle shrine on the east ledge.
    sx, sy, sz = 540, 168, L.ground(540, 168) + 0.2
    b.box((sx, sy, sz + 1.8), (6.0, 4.6, 3.6), 'wood')
    b.gable_roof((sx, sy, sz + 3.6), 6.0, 4.6, sz + 3.6, 2.0, 'roof_terra', 0, ridge='x', overhang=0.8)
    b.box((sx, sy - 2.4, sz + 1.3), (2.2, 0.2, 2.2), 'wood_dark')
    lantern_post(b, sx - 4, sy - 3, sz, 2.6)
    lantern_post(b, sx + 4, sy - 3, sz, 2.6)


def rope_bridge(b):
    y = 53.0
    x0, x1 = 424.0, 512.0
    z0, z1 = L.ground(x0, y) + 3.0, L.ground(x1, y) + 3.0
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
    # The broken hull on the western rocks is a dark, readable landmark from the harbor mouth.
    ship(b, -492, -246, -2.8, 34, 0.60, sails=False, unfinished=True)
    return b


def ship(b, x, y, z, yaw, scale=1.0, sails=True, unfinished=False):
    """A three-masted galleon with a lofted hull, gun deck and layered rigging.

    Local +Y is the bow.  The hull stations carry width, keel and gunwale
    height; four shell bands give the tumblehome and wale that the blockout
    lacked.
    """
    def T(lx, ly, lz):
        return local(x, y, yaw, lx * scale, ly * scale) + (z + lz * scale,)

    def box(lx, ly, lz, sx, sy, sz, mat, rot=0.0):
        b.box(T(lx, ly, lz), (sx * scale, sy * scale, sz * scale), mat, yaw + rot)

    stations = [
        (-32.0, 2.2, 3.6, 7.4), (-29.0, 4.4, 2.5, 8.1), (-25.0, 6.2, 1.7, 8.7),
        (-18.0, 7.4, 1.0, 9.0), (-8.0, 8.0, 0.6, 9.1), (2.0, 8.0, 0.5, 9.1),
        (12.0, 7.4, 0.9, 8.9), (20.0, 6.0, 1.7, 8.5), (26.0, 4.0, 2.9, 7.8),
        (30.0, 1.2, 4.6, 6.8),
    ]
    # Hull shell in four horizontal bands.  The upper bands pull inward for
    # tumblehome; the wale is a darker band with a proud rubbing strake.
    bands = ((0.24, 0.72, 0.0, 2.5, 'wood_dark'), (0.72, 1.0, 2.5, 4.7, 'wood'),
             (1.0, 0.94, 4.7, 6.6, 'wood'), (0.94, 0.82, 6.6, 8.6, 'wood_light'))
    for i in range(len(stations) - 1):
        y0, w0, k0, g0 = stations[i]
        y1, w1, k1, g1 = stations[i + 1]
        for side in (-1, 1):
            for fa, fb, za, zb, mat in bands:
                zz0 = k0 + (g0 - k0) * za / 8.6 if za else k0
                zz1 = k1 + (g1 - k1) * za / 8.6 if za else k1
                a = T(side * w0 * fa, y0, zz0)
                bb = T(side * w1 * fa, y1, zz1)
                c = T(side * w1 * fb, y1, k1 + (g1 - k1) * zb / 8.6)
                d = T(side * w0 * fb, y0, k0 + (g0 - k0) * zb / 8.6)
                b.quad(a, bb, c, d, mat)
            # Proud wale and a row of iron nail heads.
            b.beam(T(side * w0 * 1.01, y0, 4.8), T(side * w1 * 1.01, y1, 4.8), 0.20, 'wood_dark')
            b.beam(T(side * w0 * 0.96, y0, 6.55), T(side * w1 * 0.96, y1, 6.55), 0.10, 'metal')
            # Gun ports and cannon muzzles on the lower gun deck.
            for yy in (y0 + 2.0, y0 + 7.0):
                if yy < y1:
                    px, py = local(x, y, yaw, side * (w0 + 0.1) * scale, yy * scale)
                    slot = py + 0.0
                    b.box((px, slot, z + 5.7 * scale), (0.35 * scale, 1.4 * scale, 0.9 * scale), 'glass', yaw)
                    b.cylinder((px, slot, z + 5.7 * scale),
                               T(side * (w0 + 1.5), yy, 5.7), 0.20 * scale, 'metal', 7)
    # Deck planking, keel and deck beams.
    for i in range(len(stations) - 1):
        y0, w0, _, _ = stations[i]
        y1, w1, _, _ = stations[i + 1]
        b.quad(T(-w0 * 0.94, y0, 4.7), T(w0 * 0.94, y0, 4.7),
               T(w1 * 0.94, y1, 4.7), T(-w1 * 0.94, y1, 4.7), 'wood_light')
        b.beam(T(-w0 * 0.92, y0, 4.55), T(w0 * 0.92, y0, 4.55), 0.16, 'wood_dark')
    b.beam(T(0, -32, 1.1), T(0, 30, 1.1), 0.7, 'wood_dark')
    # Transom, stern galleries and the raised cabin.
    b.quad(T(-2.3, -32.1, 4.4), T(2.3, -32.1, 4.4), T(2.7, -32.1, 8.7), T(-2.7, -32.1, 8.7), 'wood')
    box(0, -24.0, 7.0, 11.0, 12.0, 3.2, 'wood')
    box(0, -24.0, 9.0, 12.0, 13.0, 0.35, 'wood_dark')
    for side in (-1, 1):
        for yy in (-29.0, -26.0, -23.0, -20.0, -17.0):
            box(side * 5.1, yy, 7.8, 0.18, 1.15, 1.25, 'glass_warm')
            box(side * 5.2, yy, 6.65, 0.22, 1.4, 0.16, 'gold')
        # Stern gallery rail and brackets.
        b.beam(T(side * 5.4, -30.0, 9.25), T(side * 5.4, -15.0, 9.25), 0.12, 'wood_dark')
        for yy in (-29, -25, -21, -17):
            b.beam(T(side * 5.4, yy, 8.9), T(side * 5.4, yy, 10.1), 0.10, 'wood')
    # Forecastle deck and its rail.
    box(0, 22.0, 6.65, 10.0, 9.0, 3.2, 'wood')
    box(0, 22.0, 8.15, 10.2, 9.2, 0.25, 'wood_dark')
    for side in (-1, 1):
        for yy in (18, 21, 24, 27):
            b.beam(T(side * 4.8, yy, 8.2), T(side * 4.8, yy, 9.25), 0.10, 'wood')
        b.beam(T(side * 4.8, 18.0, 9.2), T(side * 4.8, 27.0, 9.2), 0.13, 'wood_dark')
    # Bowsprit, stem and a carved figurehead block (a TRELLIS figurehead is
    # loaded over this when the asset is present).
    b.beam(T(0, 29, 7.6), T(0, 44, 12.4), 0.38, 'wood_dark')
    b.beam(T(0, 29, 7.6), T(0, 39, 9.6), 0.18, 'metal')
    if not HAS_FIGUREHEAD:
        b.sphere(T(0, 43.2, 11.8), 1.05, 'gold', (0.75, 1.4, 0.8), subdiv=0)
        b.sphere(T(0, 45.0, 12.6), 0.55, 'gold', (0.7, 1.1, 0.7), subdiv=0)
    # Deck furniture: hatch, capstan, ship's boat and a wheel.
    box(0, 6.0, 5.0, 6.0, 5.0, 0.35, 'wood_dark')
    box(0, 6.0, 5.2, 5.2, 4.2, 0.25, 'wood_light')
    b.cylinder(T(0, 12, 4.8), T(0, 12, 6.4), 0.85, 'wood', 10, radius_b=0.65)
    b.beam(T(-2.2, 12, 5.9), T(2.2, 12, 5.9), 0.16, 'wood_dark')
    b.beam(T(0, 9.8, 5.9), T(0, 14.2, 5.9), 0.16, 'wood_dark')
    box(0, -10.0, 5.15, 4.8, 7.2, 0.6, 'wood_light')
    if not HAS_WHEEL:
        b.ring(T(0, -16.5, 6.3), 1.05, 0.10, 'wood', axis='x', sides=12)
        for i in range(8):
            a = i * TAU / 8
            b.beam(T(0, -16.5, 6.3), T(math.cos(a) * 1.1, -16.5, 6.3 + math.sin(a) * 1.1), 0.06, 'wood')
    # Fenders and a pair of anchors stowed at the bow.
    for yy in (-18, -2, 14):
        b.cylinder(T(8.1, yy, 5.4), T(8.1, yy, 8.2), 0.34, 'rope', 7)
    for side in (-1, 1):
        b.ring(T(side * 3.4, 26.0, 5.8), 0.8, 0.12, 'metal', axis='x', sides=10)
    if unfinished:
        # Exposed ribs and staging make the shipyard hull read as work in progress.
        for y0, w0, k0, g0 in stations:
            for side in (-1, 1):
                b.beam(T(side * w0 * 0.35, y0, k0), T(side * w0, y0, g0), 0.22, 'wood_dark')
        for yy in (-24, -16, -8, 0, 8, 16, 24):
            for side in (-1, 1):
                b.beam(T(side * 8.6, yy, 0), T(side * 8.6, yy, 9.6), 0.16, 'wood_light')
        b.beam(T(-10, 24, 8.6), T(10, 24, 8.6), 0.18, 'wood_dark')
        return
    # Masts, tops, yards, layered sails and standing rigging.
    masts = [(-15.0, 21.0, 0.62), (3.0, 30.0, 1.0), (18.0, 24.0, 0.74)]
    for my, mh, strength in masts:
        b.cylinder(T(0, my, 4.7), T(0, my, 4.7 + mh), 0.50 * strength, 'wood_dark', 8,
                   radius_b=0.24 * strength)
        # Mast top and crosstrees.
        b.cylinder(T(0, my, 4.7 + mh * 0.58), T(0, my, 4.7 + mh * 0.61), 1.7 * strength,
                   'wood', 10, radius_b=1.4 * strength)
        b.beam(T(-2.4 * strength, my, 4.7 + mh * 0.605), T(2.4 * strength, my, 4.7 + mh * 0.605),
               0.16, 'wood_dark')
        if my == 3.0:
            # Crow's nest on the mainmast.
            b.cylinder(T(0, my, 4.7 + mh * 0.86), T(0, my, 4.7 + mh * 0.89), 1.55, 'wood', 10)
            for i in range(10):
                a = i * TAU / 10
                b.beam(T(math.cos(a) * 1.5, my + math.sin(a) * 1.5, 4.7 + mh * 0.89),
                       T(math.cos(a) * 1.5, my + math.sin(a) * 1.5, 4.7 + mh * 0.89 + 0.8), 0.07, 'wood_dark')
        for frac, width in ((0.34, 11.5), (0.55, 9.8), (0.76, 7.2)):
            zz = 4.7 + mh * frac
            yard_w = width * strength
            b.beam(T(-yard_w, my, zz), T(yard_w, my, zz), 0.24, 'wood')
            b.beam(T(-yard_w * 0.96, my + 0.12, zz), T(-yard_w * 0.96, my + 0.12, zz - 0.4), 0.08, 'wood_dark')
            b.beam(T(yard_w * 0.96, my + 0.12, zz), T(yard_w * 0.96, my + 0.12, zz - 0.4), 0.08, 'wood_dark')
            if sails and frac > 0.3:
                for j in range(3):
                    x0 = -yard_w + 2 * yard_w * j / 3 + 0.25
                    x1 = -yard_w + 2 * yard_w * (j + 1) / 3 - 0.25
                    b.quad(T(x0, my + 0.25, zz - 0.15), T(x1, my + 0.25, zz - 0.15),
                           T(x1, my + 1.55, zz - 4.7), T(x0, my + 1.55, zz - 4.7), 'sail_dark')
                    b.beam(T(x0 + 0.4, my + 1.2, zz - 4.3), T(x1 - 0.4, my + 1.2, zz - 4.3),
                           0.035, 'canvas_red')
                # Reef points across the sail foot.
                for j in range(6):
                    xx = -yard_w + 2 * yard_w * (j + 0.5) / 6
                    b.beam(T(xx, my + 1.0, zz - 3.4), T(xx, my + 1.25, zz - 4.5), 0.025, 'wood_dark')
        # Standing rigging to the bowsprit, stern and channels.
        top = 4.7 + mh * 0.82
        b.rope(T(0, my, top), T(0, 44, 12.4), 0.0, 0.035)
        b.rope(T(0, my, top), T(0, -30, 8.5), 0.0, 0.035)
        for side in (-1, 1):
            b.rope(T(0, my, top), T(side * 8.6, my - 10.0, 7.0), 0.15, 0.03)
            b.rope(T(0, my, top), T(side * 8.6, my + 8.0, 7.0), 0.15, 0.03)
            # Shrouds and ratlines.
            for k in range(5):
                x0 = side * (3.0 + k * 1.25)
                b.rope(T(x0, my - 2.0, top - 0.5), T(x0, my - 4.8, 8.6), 0.0, 0.025)
                for r in range(6):
                    t = r / 6
                    z0 = top - 0.5 + (8.6 - (top - 0.5)) * t
                    yy = my - 2.0 - 2.8 * t
                    b.beam(T(x0 - 0.6, yy, z0), T(x0 + 0.6, yy, z0), 0.018, 'rope')
    # A long pennant and a black stern flag with a pale skull.
    for my, mh in ((-15.0, 21.0), (3.0, 30.0), (18.0, 24.0)):
        b.cylinder(T(0, my, 4.7 + mh), T(0, my, 4.7 + mh + 1.4), 0.07, 'metal', 5)
        b.quad(T(0, my, 4.7 + mh + 1.3), T(4.6, my, 4.7 + mh + 0.7),
               T(4.6, my, 4.7 + mh + 0.25), T(0, my, 4.7 + mh + 0.55),
               'flag_black' if my == 3.0 else 'flag_red')
    b.cylinder(T(0, -30, 9.4), T(0, -30, 20.5), 0.13, 'metal', 6)
    b.quad(T(0, -30, 20.2), T(5.8, -30, 19.0), T(5.8, -30, 15.1), T(0, -30, 15.7), 'flag_black')
    b.sphere(T(2.7, -30.06, 17.6), 0.72, 'cream', (1.0, 0.06, 1.1), subdiv=0)


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
    # Cargo clusters, rope coils and net racks along the working quay.
    for cx, cy in ((-250, 94), (-170, 94), (120, 94), (270, 94), (-60, 84), (60, 84)):
        for i in range(2):
            crate(b, cx + i * 1.25, cy, 4.75, RNG.uniform(0.9, 1.3), RNG.uniform(-8, 8))
            barrel(b, cx - 1.8 - i * 1.1, cy + 1.4, 4.75, RNG.uniform(0.7, 1.0))
        b.ring((cx, cy + 3.0, 4.82), 0.85, 0.07, 'rope', sides=12)
    for x, y in ((274, 70), (286, 70)):
        for side in (-1, 1):
            b.beam((x, y + side * 3.2, 4.8), (x, y + side * 3.2, 9.2), 0.16, 'wood_dark')
        for i in range(6):
            yy = y - 3.0 + i * 1.2
            b.rope((x - 0.2, yy, 8.8), (x + 0.2, yy, 5.4), 0.35, 0.035)
            b.quad((x - 1.4, yy - 0.5, 8.7), (x + 1.4, yy - 0.5, 8.7),
                   (x + 1.6, yy + 0.5, 5.6), (x - 1.6, yy + 0.5, 5.6), 'rope')
    # Gulls over the harbor mouth.
    for i in range(18):
        gx = RNG.uniform(-320, 320)
        gy = RNG.uniform(-300, 40)
        gz = RNG.uniform(20, 58)
        b.sphere((gx, gy, gz), 0.22, 'sail', (1.0, 0.6, 0.5), subdiv=0)
        b.quad((gx - 1.1, gy, gz), (gx, gy, gz + 0.35), (gx + 1.1, gy, gz), (gx, gy, gz - 0.1), 'sail')
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
