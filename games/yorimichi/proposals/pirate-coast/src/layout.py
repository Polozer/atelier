"""Plan for Brinecove. Plain Python so the layout can be tested and reviewed without Blender.

The frame is Blender metres: x east, y north, z up. Sea level is 0. This module holds the one source of truth for
the basin silhouette, terraces, building lots, piers, landmarks and scatter masks.
"""
import math
import random

X_MIN, X_MAX = -800.0, 800.0
Y_MIN, Y_MAX = -700.0, 500.0
QUAY_Y = 60.0
QUAY_Z = 4.5
UPPER_Z = 22.5
WATCHTOWER = (-120.0, 470.0, 42.0)
LIGHTHOUSE = (-618.0, -38.0, 63.0)
STATUE = (-120.0, -245.0, 0.0)
WATERFALL = (474.0, 86.0, 58.0)

COLORS = {
    'stone': '#77786c', 'stone_light': '#969486', 'stone_dark': '#565a52',
    'plaster': '#d8c7a2', 'cream': '#e6d8b9', 'ochre': '#c89a5b', 'coral': '#b86a52',
    'teal_wall': '#5f8f8a', 'sage_wall': '#97a07a',
    'wood': '#6b4d35', 'wood_dark': '#3f3128', 'wood_light': '#95704b',
    'roof_terra': '#a8563e', 'roof_terra_light': '#bf7655', 'roof_teal': '#4f7f79',
    'roof_slate': '#4a5158', 'roof_straw': '#ad8b58',
    'jungle_dark': '#3f5a2e', 'jungle': '#4d6a36', 'jungle_light': '#6f8245',
    'palm': '#587a39', 'palm_light': '#78954a', 'sand': '#c7ad7d',
    'rock': '#6d6558', 'rock_light': '#8b8070', 'rock_dark': '#48443c',
    'seabed': '#315f63', 'water': '#2d7e88', 'water_deep': '#164c63',
    'sail': '#e1d3b3', 'sail_stripe': '#a44d3d', 'metal': '#3b3a36', 'gold': '#d5a64a',
    'lantern': '#f2c36b', 'glass': '#26424a', 'glass_warm': '#ffc46b',
    'flag_black': '#292424', 'flag_red': '#a23c32', 'rope': '#bda77c',
}


def clamp(value, lo=0.0, hi=1.0):
    return lo if value < lo else hi if value > hi else value


def smooth(value):
    value = clamp(value)
    return value * value * (3.0 - 2.0 * value)


def lerp(a, b, t):
    return a + (b - a) * t


def bay_half(y):
    """Half-width of the water at y. The cove narrows at the town and opens to the sea."""
    if y >= QUAY_Y:
        return 2000.0
    return min(620.0, 430.0 + 0.28 * (QUAY_Y - y))


def is_water(x, y):
    return y < QUAY_Y and abs(x) < bay_half(y)


def town_height(x, y):
    z = QUAY_Z + 0.6 * smooth((y - QUAY_Y) / 90.0)
    z += 18.0 * smooth((y - 252.0) / 68.0)
    z += 30.0 * smooth((y - 452.0) / 72.0)
    z += 8.0 * smooth((y - 520.0) / 90.0)
    # Gentle rise at the sides keeps the quay from reading as a ruler.
    z += 3.0 * smooth((abs(x) - 300.0) / 120.0) * smooth((y - QUAY_Y) / 130.0)
    # A knoll for the watchtower, kept inside its own pad so no roof floats.
    z += 12.0 * math.exp(-((x - WATCHTOWER[0]) ** 2 + (y - WATCHTOWER[1]) ** 2) / (72.0 ** 2))
    return z


def headland_height(x, y):
    d = abs(x) - bay_half(y)
    z = 2.0 + 56.0 * smooth(d / 105.0)
    z += 12.0 * smooth((y - 10.0) / 180.0)
    z += 3.0 * smooth((abs(x) - 600.0) / 150.0)
    return z


def raw_height(x, y):
    if y >= QUAY_Y:
        z = town_height(x, y)
        # Fade the town plateau into the natural side hills.
        side = smooth((abs(x) - 390.0) / 140.0)
        return lerp(z, headland_height(x, y), side)
    if not is_water(x, y):
        return headland_height(x, y)
    return -3.5 - 0.035 * (QUAY_Y - y) - 0.25 * smooth((120.0 - abs(x)) / 240.0)


def noise(x, y):
    return (1.15 * math.sin(x * 0.031 + 0.7) * math.sin(y * 0.027 - 0.4)
            + 0.55 * math.sin(x * 0.071 + y * 0.053)
            + 0.28 * math.cos(x * 0.13 - y * 0.09))


def height(x, y):
    z = raw_height(x, y)
    if y < QUAY_Y - 2.0:
        return z
    town = smooth((y - QUAY_Y) / 30.0) * (1.0 - smooth((abs(x) - 380.0) / 130.0))
    return z + noise(x, y) * (1.0 - 0.75 * town)


def slope(x, y, step=6.0):
    dx = (height(x + step, y) - height(x - step, y)) / (2 * step)
    dy = (height(x, y + step) - height(x, y - step)) / (2 * step)
    return math.hypot(dx, dy)


def yaw_point(x, y, cx, cy, yaw):
    a = math.radians(yaw)
    dx, dy = x - cx, y - cy
    return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)


# Lots are (key, x, y, z, width, depth, height, floors, style, yaw, roof). Fronts face south (-Y) unless yaw says
# otherwise. The market opening is x -90..90, so no lot sits inside it.
BUILDINGS = [
    ('rum-w1', -352, 122, QUAY_Z, 46, 27, 15.5, 3, 'tavern', 0, 'roof_terra'),
    ('rum-w2', -300, 122, QUAY_Z, 42, 25, 12.0, 2, 'shop', 0, 'roof_teal'),
    ('rum-w3', -253, 122, QUAY_Z, 38, 26, 16.5, 3, 'tavern', 0, 'roof_terra'),
    ('rum-w4', -205, 122, QUAY_Z, 40, 24, 11.0, 2, 'house', 0, 'roof_slate'),
    ('rum-w5', -158, 122, QUAY_Z, 38, 27, 14.0, 3, 'warehouse', 0, 'roof_terra'),
    ('rum-w6', -108, 122, QUAY_Z, 34, 25, 12.5, 2, 'shop', 0, 'roof_teal'),
    ('rum-e1', 110, 122, QUAY_Z, 34, 26, 13.0, 3, 'shop', 0, 'roof_terra'),
    ('rum-e2', 155, 122, QUAY_Z, 38, 25, 16.0, 3, 'tavern', 0, 'roof_slate'),
    ('rum-e3', 204, 122, QUAY_Z, 40, 27, 11.5, 2, 'warehouse', 0, 'roof_terra'),
    ('rum-e4', 254, 122, QUAY_Z, 38, 25, 14.5, 3, 'house', 0, 'roof_teal'),
    ('rum-e5', 303, 122, QUAY_Z, 40, 26, 12.5, 2, 'shop', 0, 'roof_terra'),
    ('rum-e6', 352, 122, QUAY_Z, 38, 24, 15.0, 3, 'tavern', 0, 'roof_slate'),
    ('back-w1', -340, 194, 5.1, 40, 26, 12.0, 2, 'house', 0, 'roof_terra'),
    ('back-w2', -294, 194, 5.2, 38, 24, 14.5, 3, 'house', 0, 'roof_teal'),
    ('back-w3', -246, 194, 5.3, 42, 27, 10.5, 2, 'warehouse', 0, 'roof_slate'),
    ('back-w4', -196, 194, 5.4, 36, 25, 13.5, 3, 'house', 0, 'roof_terra'),
    ('back-w5', -145, 194, 5.5, 40, 26, 11.0, 2, 'shop', 0, 'roof_teal'),
    ('back-e1', 132, 194, 5.2, 38, 25, 12.5, 2, 'house', 0, 'roof_terra'),
    ('back-e2', 180, 194, 5.3, 40, 26, 14.0, 3, 'tavern', 0, 'roof_slate'),
    ('back-e3', 230, 194, 5.4, 38, 24, 11.5, 2, 'house', 0, 'roof_teal'),
    ('back-e4', 280, 194, 5.5, 42, 27, 13.0, 3, 'warehouse', 0, 'roof_terra'),
    ('back-e5', 334, 194, 5.6, 38, 25, 12.0, 2, 'shop', 0, 'roof_slate'),
    ('terrace-w1', -270, 338, UPPER_Z, 44, 26, 13.0, 2, 'house', 0, 'roof_terra'),
    ('terrace-w2', -216, 338, UPPER_Z, 36, 24, 15.5, 3, 'tavern', 0, 'roof_teal'),
    ('terrace-w3', -164, 338, UPPER_Z, 38, 26, 11.5, 2, 'house', 0, 'roof_slate'),
    ('terrace-w4', -114, 338, UPPER_Z, 36, 25, 14.0, 3, 'house', 0, 'roof_terra'),
    ('terrace-w5', -64, 338, UPPER_Z, 34, 24, 10.5, 2, 'shop', 0, 'roof_teal'),
    ('terrace-e1', 58, 338, UPPER_Z, 36, 25, 12.5, 2, 'house', 0, 'roof_terra'),
    ('terrace-e2', 108, 338, UPPER_Z, 38, 26, 15.0, 3, 'tavern', 0, 'roof_slate'),
    ('terrace-e3', 158, 338, UPPER_Z, 36, 24, 11.0, 2, 'house', 0, 'roof_teal'),
    ('terrace-e4', 208, 338, UPPER_Z, 38, 25, 13.5, 3, 'house', 0, 'roof_terra'),
    ('terrace-e5', 258, 338, UPPER_Z, 36, 26, 12.0, 2, 'shop', 0, 'roof_slate'),
    ('terrace-e6', 308, 338, UPPER_Z, 38, 24, 14.5, 3, 'tavern', 0, 'roof_teal'),
    ('crest-w1', -250, 414, UPPER_Z + 0.5, 38, 24, 12.0, 2, 'house', 0, 'roof_terra'),
    ('crest-w2', -190, 414, UPPER_Z + 0.5, 36, 25, 14.0, 3, 'house', 0, 'roof_teal'),
    ('crest-e1', 70, 414, UPPER_Z + 0.5, 38, 24, 13.0, 2, 'tavern', 0, 'roof_slate'),
    ('crest-e2', 130, 414, UPPER_Z + 0.5, 36, 25, 11.0, 2, 'house', 0, 'roof_terra'),
    ('crest-e3', 190, 414, UPPER_Z + 0.5, 40, 26, 15.0, 3, 'house', 0, 'roof_teal'),
    ('crest-e4', 250, 414, UPPER_Z + 0.5, 36, 24, 12.0, 2, 'shop', 0, 'roof_slate'),
    ('cliff-w1', -398, 248, 12.0, 30, 22, 8.5, 2, 'shack', -8, 'roof_straw'),
    ('cliff-w2', -438, 292, 19.0, 26, 20, 7.5, 1, 'shack', -12, 'roof_terra'),
    ('cliff-e1', 405, 262, 14.0, 28, 20, 9.0, 2, 'shack', 8, 'roof_straw'),
]

LOTS = {b[0]: b for b in BUILDINGS}

PIERS = [
    ('central', 0.0, 60.0, -184.0, 24.0),
    ('west', -238.0, 60.0, -112.0, 13.0),
    ('east', 238.0, 60.0, -138.0, 16.0),
]

SHIPS = [
    ('galleon-adventure', -30.0, -76.0, 0.0, 0.94, True),
    ('galleon-nightjar', 34.0, -126.0, 180.0, 0.90, False),
    ('sloop-east', 252.0, -72.0, 180.0, 0.45, True),
]

MARKET_STALLS = [
    (-72, 112, 12, 7, 'roof_sail'), (-42, 116, 12, 7, 'roof_red'), (-12, 110, 12, 7, 'roof_sail'),
    (24, 116, 12, 7, 'roof_red'), (60, 112, 12, 7, 'roof_sail'),
    (-74, 196, 11, 6, 'roof_red'), (70, 196, 11, 6, 'roof_sail'), (-68, 158, 10, 6, 'roof_sail'),
    (64, 158, 10, 6, 'roof_red'),
]


def building_pads():
    return [(b[1], b[2], b[4] + 5.0, b[5] + 5.0, b[6], b[9]) for b in BUILDINGS]


PADS = building_pads() + [
    (0.0, 160.0, 200.0, 140.0, 1600.0, 0.0),   # the market stays open and flat
    (WATCHTOWER[0], WATCHTOWER[1], 46.0, 46.0, 4200.0, 0.0),
]


def pad_height(x, y):
    """The exact surface of a building or public pad at a point, or None outside every pad."""
    for cx, cy, w, d, z, yaw in PADS:
        lx, ly = yaw_point(x, y, cx, cy, -yaw)
        if abs(lx) <= w / 2 and abs(ly) <= d / 2:
            return z
    return None


def ground(x, y):
    z = height(x, y)
    # Last few metres around a lot settle onto its pad so no wall floats over a noisy sample.
    for cx, cy, w, d, pz, yaw in PADS:
        lx, ly = yaw_point(x, y, cx, cy, -yaw)
        edge = max(abs(lx) - w / 2, abs(ly) - d / 2)
        if edge <= 5.0:
            blend = smooth((5.0 - edge) / 3.0)
            z = lerp(z, pz, blend)
    return z


def in_lot(x, y, margin=2.0):
    for b in BUILDINGS:
        lx, ly = yaw_point(x, y, b[1], b[2], -b[9])
        if abs(lx) <= b[4] / 2 + margin and abs(ly) <= b[5] / 2 + margin:
            return True
    return False


def on_market(x, y, margin=2.0):
    return -98 - margin <= x <= 98 + margin and 96 - margin <= y <= 228 + margin


def on_pier(x, y, margin=3.0):
    for _, px, y0, y1, width in PIERS:
        if abs(x - px) <= width / 2 + margin and y1 - margin <= y <= y0 + margin:
            return True
    return False


def on_street(x, y, margin=1.5):
    if -392 - margin <= x <= 392 + margin and (QUAY_Y - 4 - margin <= y <= 104 + margin or 143 - margin <= y <= 177 + margin):
        return True
    if -318 - margin <= x <= 338 + margin and 312 - margin <= y <= 378 + margin:
        return True
    if abs(x) <= 20 + margin and 225 - margin <= y <= 318 + margin:
        return True
    return False


def plantable(x, y):
    if y < QUAY_Y + 2:
        return False
    if in_lot(x, y, 3.0) or on_market(x, y, 4.0) or on_street(x, y, 3.0) or on_pier(x, y, 5.0):
        return False
    if abs(x - WATCHTOWER[0]) < 28 and abs(y - WATCHTOWER[1]) < 28:
        return False
    if abs(x - LIGHTHOUSE[0]) < 20 and abs(y - LIGHTHOUSE[1]) < 20:
        return False
    if abs(x - WATERFALL[0]) < 26 and 0 <= y <= 180:
        return False
    if slope(x, y) > 1.7:
        return False
    return True


def scatter(seed=7319):
    """Deterministic positions for palms, jungle trees and bushes."""
    rng = random.Random(seed)
    palms, trees, bushes = [], [], []
    # Palms favour the lower town, the quay ends and the sunny headland margins.
    for _ in range(2600):
        x = rng.uniform(X_MIN + 20, X_MAX - 20)
        y = rng.uniform(Y_MIN + 20, Y_MAX - 20)
        if not plantable(x, y) or is_water(x, y):
            continue
        z = ground(x, y)
        if z < 1.5:
            continue
        if len(palms) < 170 and (y < 320 or abs(x) > 390) and rng.random() < 0.55:
            palms.append((x, y, z, rng.uniform(0, 360), rng.uniform(0.75, 1.25)))
        elif len(trees) < 260 and (y > 300 or abs(x) > 390 or rng.random() < 0.35):
            trees.append((x, y, z, rng.uniform(0, 360), rng.uniform(0.75, 1.35)))
        elif len(bushes) < 300:
            bushes.append((x, y, z, rng.uniform(0, 360), rng.uniform(0.6, 1.2)))
        if len(palms) >= 170 and len(trees) >= 260 and len(bushes) >= 300:
            break
    return dict(palms=palms, trees=trees, bushes=bushes)


SEA_STACKS = [(-332, -322, 0.0, 13.0), (368, -300, 0.0, 16.0), (160, -412, 0.0, 10.0),
              (-226, -382, 0.0, 7.0), (452, -238, 0.0, 9.0)]


def area():
    return dict(width=X_MAX - X_MIN, depth=Y_MAX - Y_MIN, land=sum(
        1 for x in range(-800, 801, 20) for y in range(-700, 501, 20) if not is_water(x, y)) * 400.0)
