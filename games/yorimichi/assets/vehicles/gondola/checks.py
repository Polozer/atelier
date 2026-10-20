"""Thresholds and pass/fail decisions for the gondola audits (plain Python: no bpy, no mathutils).

Every number the README and NOTES quote for a gate is a named constant here (walk.py holds the walk rules), and
tests/test_gondola_geometry.py asserts the documented numbers equal them. build.py, stations.py and walk.py measure;
the decisions below say whether a measurement passes, so the same rule runs in the build and in the fast tests.

Rope contacts fall in two categories:
- intentional contact: the parts that carry the rope (grip jaws and the clamp body over them, tower sheave grooves,
  the bullwheel groove). They pass when the rope axis is the rope radius from them, within CONTACT_TOL: seated, neither
  pressed into the part nor lifted off it.
- clearance to unrelated hardware: everything else (the cabin, the hanger, the grip outside the jaws, the towers'
  and stations' structure). It passes when nothing comes nearer the rope axis than the rope radius + ROPE_CLEARANCE.
"""
import math

ROPE_CLEARANCE = 0.05          # m: unrelated hardware keeps this gap to the rope surface
CONTACT_TOL = 0.002            # m: an intentional contact (jaw, sheave, bullwheel groove) sits on the rope radius within this
FLOOR_TILT_TOL_DEG = 0.01      # the cabin floor stays level (it hangs plumb): largest tilt from level allowed
BUDGET = {'cabin': 15000, 'tower': 8000, 'station': 60000}   # triangles per piece (a tower: per height)

CONTACT_TAGS = {'jaw': 'rope seated in the jaw groove', 'clamp': 'rope seated in the jaw groove',
                'sheave': 'rope on the sheave grooves', 'bullwheel groove': 'rope in the bullwheel groove'}
INTENTIONAL = 'intentional contact'
UNRELATED = 'clearance to unrelated hardware'


def category(tag):
    """The contact category of a part, from its tag."""
    return INTENTIONAL if tag in CONTACT_TAGS else UNRELATED


def required_clearance(rope_radius):
    """The least distance from the rope axis that unrelated hardware may come."""
    return rope_radius + ROPE_CLEARANCE


def clearance_ok(distance, rope_radius):
    """Unrelated hardware: passes at rope radius + ROPE_CLEARANCE or more. None means nothing within the search reach."""
    return distance is None or distance >= required_clearance(rope_radius) - 1e-9


def contact_ok(distance, rope_radius):
    """Intentional contact: the rope axis is the rope radius from the part, within CONTACT_TOL. None (the rope never
    came near the part) fails: a jaw, sheave or groove that does not carry the rope is a fault."""
    return distance is not None and abs(distance - rope_radius) <= CONTACT_TOL + 1e-9


def classify(tag, distance, rope_radius):
    """One measurement (part tag, distance from the rope axis) as a report row with its category and verdict."""
    cat = category(tag)
    ok = contact_ok(distance, rope_radius) if cat == INTENTIONAL else clearance_ok(distance, rope_radius)
    row = {'tag': tag, 'category': cat, 'min_distance_from_rope_axis_m': distance, 'rope_radius_m': rope_radius, 'ok': ok}
    if cat == INTENTIONAL:
        row['contact'] = CONTACT_TAGS[tag]
        row['gap_m'] = None if distance is None else round(distance - rope_radius, 4)
    else:
        row['required_m'] = round(required_clearance(rope_radius), 3)
    return row


def _rows(M):
    return [[float(M[i][j]) for j in range(3)] for i in range(3)]


def floor_tilt_deg(C):
    """The angle between the cabin frame's up axis and world up (C: a 3x3 or 4x4 matrix, rows, or a mathutils
    Matrix). Zero when the cabin hangs plumb."""
    return math.degrees(math.acos(max(-1.0, min(1.0, _rows(C)[2][2]))))


def grip_pitch_deg(G):
    """The grip's pitch: the angle of its x axis (along the rope) above level."""
    return math.degrees(math.asin(max(-1.0, min(1.0, _rows(G)[2][0]))))


def hanging_ok(C):
    return floor_tilt_deg(C) <= FLOOR_TILT_TOL_DEG


def grip_clearances(grip, rope_radius):
    """Distances from the rope axis (the grip frame's x axis) to the grip parts that must stay off the rope, from the
    grip's dimensions alone: the running wheels (a tyre disc of wheel_radius in a plane wheel_y outboard, width
    wheel_width, centre wheel_z above the axis) and the pivot point. Each passes at rope radius + ROPE_CLEARANCE."""
    wy, wz, wr, ww = abs(grip['wheel_y']), grip['wheel_z'], grip['wheel_radius'], grip['wheel_width']
    inner_face = wy - ww / 2                                # the tyre's face nearest the rope, across the rope
    below = max(0.0, abs(wz) - wr)                          # how far the tyre disc stays above or below the axis height
    wheel = math.hypot(inner_face, below)                   # the nearest tyre point to the axis
    px, py, pz = grip['pivot']
    pivot = math.hypot(py, pz)
    need = required_clearance(rope_radius)
    return {'wheel_m': round(wheel, 4), 'pivot_point_m': round(pivot, 4), 'required_m': round(need, 3),
            'ok': wheel >= need and pivot >= need}


def point_clearance(points, path, near=None, window=1.5):
    """The least distance from the rope axis to a set of points (pure geometry, rope.RopePath.nearest). Used by the
    tests to check the decision rules on hand-built fixtures."""
    best = None
    for q in points:
        d, s = path.nearest(q, near=near, window=window)
        best = d if best is None else min(best, d)
    return best


def proxy_failures(proxies):
    """Collision proxies are exported as UCX convex hulls: each must be a convex plan polygon (Unreal would silently
    wrap a concave one) with its top above its bottom at every corner."""
    bad = []
    for pr in proxies:
        pts = [tuple(q) for q in pr['poly']]; n = len(pts)
        cross = [(pts[(i + 1) % n][0] - pts[i][0]) * (pts[(i + 2) % n][1] - pts[(i + 1) % n][1])
                 - (pts[(i + 1) % n][1] - pts[i][1]) * (pts[(i + 2) % n][0] - pts[(i + 1) % n][0]) for i in range(n)]
        if n < 3 or not (all(c >= -1e-9 for c in cross) or all(c <= 1e-9 for c in cross)):
            bad.append(f'collision proxy {pr["name"]} is not convex')
        elif any(b <= a for a, b in zip(pr['z0'], pr['z1'])):
            bad.append(f'collision proxy {pr["name"]} has its top at or below its bottom')
    if not proxies:
        bad.append('no collision proxies: the piece would export without UCX hulls')
    return bad


def budget_failures(piece, triangles):
    limit = BUDGET[piece]
    return [f'{triangles} triangles over budget {limit}'] if triangles > limit else []
