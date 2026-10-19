"""Brinecove's procedural landmarks: the crest fort, the shipyard slip, the hill stair and the sea cannon.

The 2026-10-19 playtest notes 8, 10, 11 and 12 flagged a TRELLIS cannon that imported as broken triangles, a
shipyard whose lofted hull had gone (only poles were left), a stair of floating slabs and a boxy watchtower. Each is
rebuilt here after its Sunburst redesign concept (assets/brinecove/references/redesign/{cannon,shipyard,stairs,
fort}.jpg). Local metres, z up. Every mass stands on L.ground with its base sunk below it, so nothing floats when
the terrain moves. Plain Python: stair_route() and the tests run without Blender.
"""
import functools
import math

from brinecove import layout as L
from brinecove.kit import barrel, bush, crate, door, lantern_post, potted_plant

TAU = math.pi * 2


# --- shared pieces ---------------------------------------------------------------------------------------------

def _block(b, bot, top, mat):
    """Six faces between a counter-clockwise bottom quad and the quad above it."""
    b.face(tuple(reversed(bot)), mat)
    b.face(tuple(top), mat)
    for i in range(4):
        j = (i + 1) % 4
        b.quad(bot[i], bot[j], top[j], top[i], mat)


def _slab(b, x0, x1, y0, y1, z0, t0, t1, mat):
    """An axis-aligned block from z0 up to a top running linearly from t0 at x0 to t1 at x1."""
    if x0 > x1:
        x0, x1, t0, t1 = x1, x0, t1, t0
    if y0 > y1:
        y0, y1 = y1, y0
    _block(b, [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)],
           [(x0, y0, t0), (x1, y0, t1), (x1, y1, t1), (x0, y1, t0)], mat)


def _ground_range(x0, x1, y0, y1, step=1.5):
    """(lowest, highest) layout ground under a rectangle."""
    nx = max(1, int(abs(x1 - x0) / step))
    ny = max(1, int(abs(y1 - y0) / step))
    zs = [L.ground(x0 + (x1 - x0) * i / nx, y0 + (y1 - y0) * j / ny) for i in range(nx + 1) for j in range(ny + 1)]
    return min(zs), max(zs)


def _lathe(b, origin, d, profile, sides=12):
    """A surface of revolution about origin + s*d. profile is [(s, r, mat)]; each mat colours the band from the
    previous point. Cylindrical UVs in metres keep the iron texture continuous round the barrel."""
    up = (0.0, 0.0, 1.0) if abs(d[2]) < 0.94 else (0.0, 1.0, 0.0)
    u = _unit(_cross(d, up))
    v = _unit(_cross(d, u))

    def ring(s, r):
        c = [origin[k] + d[k] * s for k in range(3)]
        return [tuple(c[k] + (u[k] * math.cos(TAU * i / sides) + v[k] * math.sin(TAU * i / sides)) * r
                      for k in range(3)) for i in range(sides + 1)]

    rings = [ring(s, r) for s, r, _ in profile]
    for i in range(1, len(profile)):
        (s0, r0, _), (s1, r1, mat) = profile[i - 1], profile[i]
        circ = TAU * max(0.05, (r0 + r1) / 2)
        for k in range(sides):
            a, bb, c, dd = rings[i - 1][k], rings[i - 1][k + 1], rings[i][k + 1], rings[i][k]
            u0, u1 = circ * k / sides, circ * (k + 1) / sides
            va, vb = s0 + r0 * 0.3, s1 + r1 * 0.3
            if r0 < 1e-6:
                b.face((a, c, dd), mat, [(u0, va), (u1, vb), (u0, vb)])
            elif r1 < 1e-6:
                b.face((a, bb, c), mat, [(u0, va), (u1, va), (u1, vb)])
            else:
                b.face((a, bb, c, dd), mat, [(u0, va), (u1, va), (u1, vb), (u0, vb)])


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v) if n > 1e-9 else (1.0, 0.0, 0.0)


def _cross(a, c):
    return (a[1] * c[2] - a[2] * c[1], a[2] * c[0] - a[0] * c[2], a[0] * c[1] - a[1] * c[0])


def _place(b, start, x, y, z, yaw, scale):
    """Turn, scale and move every vertex added since start (built about the origin)."""
    a = math.radians(yaw)
    c, s = math.cos(a), math.sin(a)
    for i in range(start, len(b.verts)):
        vx, vy, vz = b.verts[i]
        b.verts[i] = (x + (vx * c - vy * s) * scale, y + (vx * s + vy * c) * scale, z + vz * scale)


def _pennant(b, top, length, height, mat, waves=3):
    """A two-sided tapering pennant flying +x from a pole at top."""
    x, y, z = top
    for k in range(waves):
        f0, f1 = k / waves, (k + 1) / waves
        h0, h1 = height * (1 - 0.8 * f0), height * (1 - 0.8 * f1)
        w0, w1 = 0.25 * math.sin(f0 * 5.0), 0.25 * math.sin(f1 * 5.0)
        p = [(x + length * f0, y + w0, z - (height - h0) / 2), (x + length * f1, y + w1, z - (height - h1) / 2),
             (x + length * f1, y + w1, z - (height + h1) / 2), (x + length * f0, y + w0, z - (height + h0) / 2)]
        b.quad(p[0], p[1], p[2], p[3], mat)
        b.quad(p[3], p[2], p[1], p[0], mat)


def _wall_lantern(b, x, y, z, ny):
    """A bracket lantern on a wall facing ny (+1 north, -1 south)."""
    b.beam((x, y, z + 0.5), (x, y + ny * 0.55, z + 0.5), 0.08, 'metal')
    b.box((x, y + ny * 0.55, z + 0.1), (0.34, 0.34, 0.5), 'lantern')
    b.box((x, y + ny * 0.55, z + 0.4), (0.44, 0.44, 0.08), 'metal')


# --- the cannon ------------------------------------------------------------------------------------------------

def cannon(b, x, y, z, yaw=0.0, scale=1.0):
    """An iron gun on a stepped oak sea carriage, about 3.2 m overall. yaw 0 aims the muzzle seaward (-y)."""
    start = len(b.verts)
    k = 1.06                       # barrel scale: 3.2 m from muzzle to cascabel
    tz, ty = 1.0, -0.30            # trunnion axis height and position
    lift = math.radians(3.0)
    d = (0.0, -math.cos(lift), math.sin(lift))
    s_t = 1.12 * k                 # trunnions sit 3/7 of the way along
    origin = (0.0, ty - d[1] * s_t, tz - d[2] * s_t)
    iron, bore = 'metal', 'flag_black'
    prof = [(-0.36, 0.0, iron), (-0.345, 0.06, iron), (-0.31, 0.095, iron), (-0.27, 0.105, iron),
            (-0.23, 0.09, iron), (-0.20, 0.055, iron), (-0.13, 0.06, iron), (-0.08, 0.17, iron),
            (-0.035, 0.27, iron), (0.0, 0.31, iron), (0.0, 0.335, iron), (0.07, 0.335, iron), (0.07, 0.31, iron),
            (0.10, 0.305, iron), (0.88, 0.29, iron), (0.88, 0.315, iron), (0.95, 0.315, iron), (0.95, 0.27, iron),
            (1.52, 0.255, iron), (1.52, 0.28, iron), (1.58, 0.28, iron), (1.58, 0.225, iron), (2.30, 0.20, iron),
            (2.36, 0.185, iron), (2.40, 0.205, iron), (2.46, 0.205, iron), (2.52, 0.24, iron), (2.62, 0.265, iron),
            (2.68, 0.265, iron), (2.68, 0.14, iron), (2.40, 0.14, bore), (2.40, 0.0, bore)]
    _lathe(b, origin, d, [(s * k, r * k, m) for s, r, m in prof], sides=14)
    # Trunnions, cap squares and their bolts.
    for side in (-1, 1):
        b.cylinder((side * 0.25, ty, tz), (side * 0.58, ty, tz), 0.10, iron, 10)
        b.box((side * 0.44, ty, tz + 0.10), (0.18, 0.34, 0.07), iron)
        for dy in (-0.13, 0.13):
            b.box((side * 0.44, ty + dy, tz + 0.15), (0.07, 0.07, 0.05), iron)
    # Oak cheeks stepping down to the rear, the trunnions seated on the front step.
    wood = 'wood'
    for side in (-1, 1):
        cx = side * 0.44
        for y1, top in ((1.02, 0.50), (0.72, 0.66), (0.38, 0.82), (0.02, 0.98)):
            z0 = 0.30 if top == 0.50 else top - 0.16
            b.box((cx, (-0.62 + y1) / 2, (z0 + top) / 2), (0.14, y1 + 0.62, top - z0), wood)
        # Iron straps, a bottom band and bolt heads on the outer face.
        ox = side * 0.515
        for sy, top in ((-0.40, 0.98), (0.20, 0.82), (0.56, 0.66)):
            b.box((ox, sy, (0.30 + top) / 2), (0.025, 0.08, top - 0.30), iron)
        b.box((ox, 0.20, 0.37), (0.025, 1.62, 0.07), iron)
        for sy, sz in ((-0.40, 0.55), (-0.40, 0.85), (0.20, 0.55), (0.56, 0.45), (0.86, 0.40), (-0.10, 0.70)):
            b.box((side * 0.53, sy, sz), (0.03, 0.05, 0.05), iron)
        # Eye bolt for the breeching.
        b.ring((side * 0.56, 0.62, 0.56), 0.055, 0.014, iron, axis='y', sides=8, tube_sides=4)
    # Transoms, the stool bed and a quoin under the breech.
    b.box((0.0, -0.52, 0.50), (0.76, 0.20, 0.34), wood)
    b.box((0.0, 0.70, 0.43), (0.76, 0.62, 0.10), 'wood_dark')
    b.box((0.0, 0.88, 0.54), (0.36, 0.30, 0.12), 'wood_dark', top=0.85)
    # Axletrees and four solid trucks with iron tyres and hubs.
    for ay, r in ((-0.42, 0.25), (0.80, 0.22)):
        b.box((0.0, ay, r), (1.24, 0.17, 0.15), 'wood_dark')
        for side in (-1, 1):
            b.cylinder((side * 0.52, ay, r), (side * 0.64, ay, r), r - 0.012, wood, 12)
            b.ring((side * 0.58, ay, r), r - 0.005, 0.032, iron, axis='x', sides=12, tube_sides=4)
            b.cylinder((side * 0.48, ay, r), (side * 0.70, ay, r), 0.06, iron, 8)
            b.box((side * 0.715, ay, r), (0.02, 0.025, 0.14), iron)
    # Breeching rope from each eye bolt round the cascabel neck.
    neck = (0.0, origin[1] + d[1] * -0.2 * k, origin[2] + d[2] * -0.2 * k)
    for side in (-1, 1):
        b.rope((side * 0.60, 0.62, 0.56), neck, sag=0.14, radius=0.035, segments=6)
    _place(b, start, x, y, z, yaw, scale)


# --- the crest fort --------------------------------------------------------------------------------------------

FORT_HW, FORT_HD = 17.0, 14.0     # curtain half-extents: the old watchtower's footprint
CURTAIN_H, CURTAIN_T = 8.0, 1.8


def fort(b):
    """The crest fort after fort.jpg: a tapered keep with machicolations and a slate pyramid, round corner towers
    with conical roofs, battered curtain walls stepping with the knoll, cannon embrasures, an arched gatehouse and
    a stepped ramp down to the seaward (-y) path."""
    x0, y0, _ = L.WATCHTOWER
    hw, hd = FORT_HW, FORT_HD
    # Curtain walls run between the tower centres; outward normals point away from the fort.
    sides = (((-hw, -hd), (hw, -hd), (0.0, -1.0)), ((hw, -hd), (hw, hd), (1.0, 0.0)),
             ((hw, hd), (-hw, hd), (0.0, 1.0)), ((-hw, hd), (-hw, -hd), (-1.0, 0.0)))
    for (ax, ay), (cx, cy), (nx, ny) in sides:
        length = math.hypot(cx - ax, cy - ay)
        ux, uy = (cx - ax) / length, (cy - ay) / length
        # Skip the tower drums at both ends; the gatehouse fills the south wall's middle.
        segs = max(2, round((length - 7.0) / 6.0))
        for k in range(segs):
            t0 = 3.4 + (length - 6.8) * k / segs
            t1 = 3.4 + (length - 6.8) * (k + 1) / segs
            _curtain_segment(b, x0, y0, ax, ay, ux, uy, nx, ny, t0, t1)
        # Cannon embrasures and buttresses on the outer face.
        if ny < 0:
            ports, props = (-9.5, 9.5), (-12.2, 12.2)
        elif ny > 0:
            ports, props = (-8.0, 0.0, 8.0), (-4.0, 4.0)
        else:
            ports, props = (-6.0, 6.0), (0.0,)
        mid_x, mid_y = (ax + cx) / 2, (ay + cy) / 2
        for p in ports:
            px, py = mid_x + abs(ux) * p, mid_y + abs(uy) * p
            _embrasure(b, x0 + px + nx * CURTAIN_T / 2, y0 + py + ny * CURTAIN_T / 2, nx, ny)
        for p in props:
            px, py = mid_x + abs(ux) * p, mid_y + abs(uy) * p
            _buttress(b, x0 + px + nx * CURTAIN_T / 2, y0 + py + ny * CURTAIN_T / 2, nx, ny)
    for sx in (-1, 1):
        for sy in (-1, 1):
            _round_tower(b, x0 + sx * hw, y0 + sy * hd, 3.6, 12.5 if sy < 0 else 11.0, (sx, sy))
    _courtyard(b, x0, y0)
    _keep(b, x0, y0 + 3.0)
    _gatehouse(b, x0, y0 - hd)
    _forecourt(b, x0, y0)


def _curtain_segment(b, x0, y0, ax, ay, ux, uy, nx, ny, t0, t1):
    """One stretch of curtain: a battered plinth, the wall, a string course, a parapet and merlons, its base sunk
    a metre below the lowest ground and its top stepped to the ground under it."""
    th = CURTAIN_T / 2
    p0 = (x0 + ax + ux * t0, y0 + ay + uy * t0)
    p1 = (x0 + ax + ux * t1, y0 + ay + uy * t1)
    xs = sorted((p0[0] - th, p0[0] + th, p1[0] - th, p1[0] + th))
    ys = sorted((p0[1] - th, p0[1] + th, p1[1] - th, p1[1] + th))
    lo, hi = _ground_range(xs[0] - abs(nx) * 1.2, xs[-1] + abs(nx) * 1.2, ys[0] - abs(ny) * 1.2,
                           ys[-1] + abs(ny) * 1.2)
    base = lo - 1.0
    top = round((hi + CURTAIN_H) / 0.75) * 0.75

    def quad(off_in, off_out, extra=0.0):
        """Corners of the strip between off_in and off_out along the normal, extended by extra along the wall."""
        e0 = (p0[0] - ux * extra, p0[1] - uy * extra)
        e1 = (p1[0] + ux * extra, p1[1] + uy * extra)
        pts = [(e0[0] + nx * off_in, e0[1] + ny * off_in), (e1[0] + nx * off_in, e1[1] + ny * off_in),
               (e1[0] + nx * off_out, e1[1] + ny * off_out), (e0[0] + nx * off_out, e0[1] + ny * off_out)]
        # Keep the corners counter-clockwise seen from above.
        area = sum(pts[i][0] * pts[(i + 1) % 4][1] - pts[(i + 1) % 4][0] * pts[i][1] for i in range(4))
        return pts if area > 0 else pts[::-1]

    def lift(pts, z):
        return [(px, py, z) for px, py in pts]

    _block(b, lift(quad(-th, th), base), lift(quad(-th, th), top), 'stone_light')
    # Battered plinth: a metre proud at the foot, flush 2.4 m up.
    foot = quad(-th - 0.4, th + 1.0)
    head = quad(-th - 0.05, th + 0.05)
    _block(b, lift(foot, base), lift(head, hi + 2.4), 'stone')
    b_course = quad(th - 0.05, th + 0.18, 0.0)
    _block(b, lift(b_course, top - 2.6), lift(b_course, top - 2.3), 'stone')
    # Parapet on the outer edge with merlons over it.
    par = quad(th - 0.6, th + 0.08)
    _block(b, lift(par, top), lift(par, top + 1.0), 'stone_light')
    length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    n = max(1, round(length / 2.3))
    for k in range(n):
        t = (k + 0.5) / n
        mx, my = p0[0] + (p1[0] - p0[0]) * t + nx * (th - 0.26), p0[1] + (p1[1] - p0[1]) * t + ny * (th - 0.26)
        b.box((mx, my, top + 1.5), (1.15 if ny else 0.68, 0.68 if ny else 1.15, 1.0), 'stone_light')


def _embrasure(b, x, y, nx, ny):
    """A dark gun port framed in dressed stone, with a short barrel out of it, on a wall face at (x, y)."""
    z = L.ground(x, y) + 3.4
    along = (abs(ny), abs(nx))
    def at(o, a):
        return x + nx * o + along[0] * a, y + ny * o + along[1] * a
    size = lambda a, o: (a, o) if ny else (o, a)  # noqa: E731
    b.box((*at(0.03, 0.0), z), (*size(1.0, 0.08), 0.85), 'flag_black')
    for a in (-0.62, 0.62):
        b.box((*at(0.12, a), z), (*size(0.32, 0.26), 1.25), 'stone')
    for dz in (-0.55, 0.55):
        b.box((*at(0.12, 0.0), z + dz), (*size(1.56, 0.30), 0.26), 'stone')
    b.cylinder(at(0.0, 0.0) + (z - 0.05,), at(0.95, 0.0) + (z,), 0.16, 'metal', 8, radius_b=0.15)
    b.cylinder(at(0.85, 0.0) + (z,), at(1.02, 0.0) + (z,), 0.2, 'metal', 8)


def _buttress(b, x, y, nx, ny):
    """A battered buttress against a wall face at (x, y)."""
    lo, hi = _ground_range(x - 1.5, x + 1.5, y - 1.5, y + 1.5)
    along = (abs(ny), abs(nx))

    def ring(out, half):
        pts = [(x + along[0] * -half, y + along[1] * -half), (x + along[0] * half, y + along[1] * half),
               (x + along[0] * half + nx * out, y + along[1] * half + ny * out),
               (x + along[0] * -half + nx * out, y + along[1] * -half + ny * out)]
        area = sum(pts[i][0] * pts[(i + 1) % 4][1] - pts[(i + 1) % 4][0] * pts[i][1] for i in range(4))
        return pts if area > 0 else pts[::-1]

    foot, head = ring(1.9, 0.8), ring(0.45, 0.7)
    _block(b, [(px, py, lo - 1.0) for px, py in foot], [(px, py, hi + 5.6) for px, py in head], 'stone')
    cap = ring(0.6, 0.78)
    _block(b, [(px, py, hi + 5.5) for px, py in cap], [(px, py, hi + 5.85) for px, py in cap], 'stone_light')


def _round_tower(b, x, y, r, height, facing):
    """A round corner tower: battered drum, string courses, corbel ring, parapet band and a conical tile roof."""
    lo, hi = _ground_range(x - r, x + r, y - r, y + r)
    top = hi + height
    b.cylinder((x, y, lo - 1.0), (x, y, hi + 3.0), r + 0.75, 'stone', 16, radius_b=r)
    b.cylinder((x, y, hi + 3.0), (x, y, top), r, 'stone_light', 16, radius_b=r - 0.15)
    for zz in (hi + 3.0, hi + height * 0.62):
        b.cylinder((x, y, zz - 0.15), (x, y, zz + 0.15), r + 0.1, 'stone', 16)
    # Corbels carry a parapet band 0.5 m proud of the drum.
    for k in range(16):
        a = TAU * (k + 0.5) / 16
        ca, sa = math.cos(a), math.sin(a)
        b.box((x + ca * (r - 0.05), y + sa * (r - 0.05), top - 0.55), (0.5, 0.42, 0.45), 'stone_light',
              math.degrees(a))
        b.box((x + ca * (r + 0.12), y + sa * (r + 0.12), top - 0.15), (0.62, 0.42, 0.35), 'stone_light',
              math.degrees(a))
    b.cylinder((x, y, top), (x, y, top + 1.3), r + 0.45, 'stone_light', 16)
    b.cylinder((x, y, top + 1.2), (x, y, top + 1.45), r + 0.62, 'stone', 16)
    b.cylinder((x, y, top + 1.45), (x, y, top + 1.45 + (r + 0.9) * 1.3), r + 0.9, 'roof_terra', 16, radius_b=0.06)
    b.cylinder((x, y, top + 1.3 + (r + 0.9) * 1.3), (x, y, top + 2.3 + (r + 0.9) * 1.3), 0.08, 'metal', 6)
    b.sphere((x, y, top + 2.35 + (r + 0.9) * 1.3), 0.16, 'gold', subdiv=0)
    # Arrow slits round the field side and a gun port facing out of the corner.
    out = math.atan2(facing[1], facing[0])
    for da, zz in ((-0.9, hi + 6.5), (0.0, hi + 8.6), (0.9, hi + 6.5)):
        a = out + da
        b.box((x + math.cos(a) * (r - 0.12), y + math.sin(a) * (r - 0.12), zz), (0.16, 0.24, 1.3), 'flag_black',
              math.degrees(a))
        b.box((x + math.cos(a) * (r - 0.08), y + math.sin(a) * (r - 0.08), zz - 0.72), (0.2, 0.5, 0.14),
              'stone', math.degrees(a))
    for da in (-0.45, 0.45):
        a = out + da
        cx, cy = x + math.cos(a) * r, y + math.sin(a) * r
        b.box((cx, cy, hi + 3.9), (0.24, 0.85, 0.8), 'flag_black', math.degrees(a))
        b.box((x + math.cos(a) * (r + 0.05), y + math.sin(a) * (r + 0.05), hi + 4.4), (0.3, 1.2, 0.22), 'stone',
              math.degrees(a))
        b.cylinder((cx, cy, hi + 3.85), (cx + math.cos(a) * 0.9, cy + math.sin(a) * 0.9, hi + 3.9), 0.15, 'metal', 8)


def _keep(b, x, y):
    """The tall keep: battered base, tapered shaft with string courses, corbelled machicolation under a
    crenellated parapet, a shallow slate pyramid, arrow slits, a hanging banner and a pennant on a pole."""
    lo, hi = _ground_range(x - 6.5, x + 6.5, y - 6.5, y + 6.5)
    base_w, shaft_w, top_w, shaft_h = 13.2, 11.0, 10.3, 24.0
    b.box((x, y, (lo - 1.0 + hi + 4.0) / 2), (base_w, base_w, hi + 5.0 - lo), 'stone', top=shaft_w / base_w)
    b.box((x, y, hi + 4.0 + shaft_h / 2 - 2.0), (shaft_w, shaft_w, shaft_h - 4.0), 'stone_light',
          top=top_w / shaft_w)

    def width(z):
        return shaft_w + (top_w - shaft_w) * (z - hi - 4.0) / (shaft_h - 4.0)

    for zz in (hi + 4.0, hi + 11.5, hi + 18.0):
        w = width(zz) + 0.3
        b.box((x, y, zz), (w, w, 0.35), 'stone')
    top = hi + shaft_h
    # Machicolation: paired corbels every 1.15 m under a parapet 0.8 m proud of the shaft.
    n = 9
    for side in range(4):
        a = side * 90.0
        for k in range(n):
            t = -top_w / 2 + top_w * (k + 0.5) / n
            for out, zz, size in ((0.22, top - 0.75, (0.45, 0.48, 0.5)), (0.5, top - 0.3, (1.0, 0.48, 0.42))):
                ox = math.cos(math.radians(a)) * (top_w / 2 + out - size[0] / 2 + 0.1) - math.sin(math.radians(a)) * t
                oy = math.sin(math.radians(a)) * (top_w / 2 + out - size[0] / 2 + 0.1) + math.cos(math.radians(a)) * t
                b.box((x + ox, y + oy, zz), size, 'stone_light', a)
    par_w = top_w + 1.6
    b.box((x, y, top + 0.6), (par_w, par_w, 1.3), 'stone_light')
    b.box((x, y, top + 0.02), (par_w + 0.12, par_w + 0.12, 0.22), 'stone')
    n = 8
    for side in range(4):
        a = math.radians(side * 90.0)
        for k in range(n):
            t = -par_w / 2 + par_w * (k + 0.5) / n
            ox = math.cos(a) * (par_w / 2 - 0.3) - math.sin(a) * t
            oy = math.sin(a) * (par_w / 2 - 0.3) + math.cos(a) * t
            b.box((x + ox, y + oy, top + 1.75), (0.6, 0.85, 1.0), 'stone_light', side * 90.0)
    # Shallow slate pyramid inside the parapet, hip ridges and a pole with the red pennant.
    roof_z, half, apex = top + 1.0, top_w / 2, top + 5.6
    corners = [(x - half, y - half, roof_z), (x + half, y - half, roof_z), (x + half, y + half, roof_z),
               (x - half, y + half, roof_z)]
    peak = (x, y, apex)
    for k in range(4):
        b.tri(corners[k], corners[(k + 1) % 4], peak, 'roof_slate')
        b.beam(corners[k], peak, 0.22, 'roof_slate')
    b.cylinder((x, y, apex - 0.6), (x, y, apex + 8.0), 0.12, 'metal', 6)
    b.sphere((x, y, apex + 8.1), 0.22, 'gold', subdiv=0)
    _pennant(b, (x + 0.1, y, apex + 7.6), 5.6, 1.5, 'flag_red')
    # Arrow slits on every face, and the banner of Brinecove on the harbour face.
    for side in range(4):
        a = math.radians(side * 90.0 - 90.0)
        for t, zz in ((-2.4, hi + 14.5), (2.4, hi + 14.5), (-1.6, hi + 20.5), (1.6, hi + 20.5), (0.0, hi + 8.5)):
            if side == 0 and t == 0.0:
                continue
            o = width(zz) / 2 + 0.02
            sx = x + math.cos(a) * o - math.sin(a) * t
            sy = y + math.sin(a) * o + math.cos(a) * t
            b.box((sx, sy, zz), (0.12, 0.26, 1.5), 'flag_black', math.degrees(a))
            b.box((sx, sy, zz - 0.82), (0.2, 0.55, 0.14), 'stone', math.degrees(a))
    fy = y - width(hi + 16.0) / 2 - 0.06
    b.box((x, fy, hi + 16.6), (2.3, 0.08, 6.4), 'canvas_red')
    b.tri((x - 1.15, fy - 0.045, hi + 13.4), (x, fy - 0.045, hi + 12.3), (x + 1.15, fy - 0.045, hi + 13.4),
          'canvas_red')
    b.tri((x + 1.15, fy + 0.045, hi + 13.4), (x, fy + 0.045, hi + 12.3), (x - 1.15, fy + 0.045, hi + 13.4),
          'canvas_red')
    sy, sz = fy - 0.06, hi + 17.0
    b.quad((x, sy, sz + 0.75), (x - 0.42, sy, sz), (x, sy, sz - 0.75), (x + 0.42, sy, sz), 'gold')
    b.quad((x, sy, sz + 0.3), (x - 0.75, sy - 0.01, sz), (x, sy, sz - 0.3), (x + 0.75, sy - 0.01, sz), 'gold')
    b.beam((x - 1.4, fy, hi + 19.85), (x + 1.4, fy, hi + 19.85), 0.1, 'wood_dark')
    # The keep's own door off the courtyard.
    b.box((x, y - base_w / 2 - 0.05, hi + 1.95), (3.4, 1.5, 3.9 + 0.2), 'stone_light')
    b.box((x, y - base_w / 2 - 0.1, hi + 4.0), (3.8, 1.7, 0.3), 'stone')
    door(b, x, y, 0, 0, -base_w / 2 - 0.88, hi + 0.12, 2.0, 3.0, surround=True)


def _gatehouse(b, x, y):
    """The arched gatehouse proud of the south curtain: plinth, string course, crenellations, voussoirs round a
    studded oak door, and a lantern either side."""
    lo, hi = _ground_range(x - 5.0, x + 5.0, y - 2.5, y + 1.5)
    front = y - CURTAIN_T / 2 - 1.3
    back = y + CURTAIN_T / 2 + 0.4
    top = round((hi + CURTAIN_H) / 0.75) * 0.75 + 2.2
    _slab(b, x - 4.6, x + 4.6, front, back, lo - 1.0, top, top, 'stone_light')
    _block(b, [(x - 5.1, front - 0.9, lo - 1.0), (x + 5.1, front - 0.9, lo - 1.0), (x + 5.1, back, lo - 1.0),
               (x - 5.1, back, lo - 1.0)],
           [(x - 4.65, front - 0.05, hi + 1.6), (x + 4.65, front - 0.05, hi + 1.6), (x + 4.65, back, hi + 1.6),
            (x - 4.65, back, hi + 1.6)], 'stone')
    _slab(b, x - 4.8, x + 4.8, front - 0.2, back, top - 2.6, top - 2.3, top - 2.3, 'stone')
    # Machicolation over the gate and a crenellated top.
    for k in range(7):
        bx = x - 3.6 + k * 1.2
        b.box((bx, front - 0.2, top - 1.0), (0.45, 0.4, 0.5), 'stone_light')
    _slab(b, x - 4.8, x + 4.8, front - 0.5, back, top - 0.75, top, top, 'stone_light')
    for k in range(5):
        b.box((x - 3.9 + k * 1.95, front - 0.2, top + 0.55), (1.1, 0.6, 1.1), 'stone_light')
    # Arch: jambs and voussoirs proud of the face so the door reads as recessed.
    gw, gh = 3.4, 3.4
    z = hi + 0.15
    for side in (-1, 1):
        b.box((x + side * (gw / 2 + 0.35), front - 0.3, z + gh / 2), (0.7, 0.6, gh), 'stone')
    for k in range(9):
        a = math.pi * (k + 0.5) / 9
        b.box((x + math.cos(a) * (gw / 2 + 0.35), front - 0.3, z + gh + math.sin(a) * (gw / 2 + 0.35)),
              (0.72, 0.6, 0.62), 'stone' if k % 2 else 'stone_light')
    leaf = front - 0.02
    b.box((x, leaf + 0.05, z + gh / 2), (gw, 0.12, gh), 'wood')
    fan = [(x + math.cos(math.pi * k / 8) * gw / 2, leaf - 0.01, z + gh + math.sin(math.pi * k / 8) * gw / 2)
           for k in range(9)]
    for k in range(8):
        b.tri((x, leaf - 0.01, z + gh), fan[k], fan[k + 1], 'wood')
    for k in range(-2, 3):
        b.box((x + k * 0.68, leaf - 0.04, z + gh / 2 + 0.6), (0.06, 0.04, gh + 1.2 - abs(k) * 0.35), 'wood_dark')
    for zz in (0.6, 1.9, 3.1):
        b.box((x, leaf - 0.06, z + zz), (gw - 0.2, 0.04, 0.12), 'metal')
        for k in range(-3, 4):
            b.box((x + k * 0.46, leaf - 0.09, z + zz), (0.07, 0.04, 0.07), 'metal')
    b.box((x, front - 0.4, z - 0.08), (gw + 1.4, 0.8, 0.16), 'stone_light')
    for side in (-1, 1):
        _wall_lantern(b, x + side * 2.9, front, z + 3.0, -1)


def _courtyard(b, x0, y0):
    """Worn flagstones inside the curtain, following the ground."""
    for i in range(5):
        for j in range(4):
            cx = x0 - FORT_HW + 1.2 + (2 * FORT_HW - 2.4) * (i + 0.5) / 5
            cy = y0 - FORT_HD + 1.2 + (2 * FORT_HD - 2.4) * (j + 0.5) / 4
            sx, sy = (2 * FORT_HW - 2.4) / 5, (2 * FORT_HD - 2.4) / 4
            lo, hi = _ground_range(cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2)
            _slab(b, cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, lo - 0.3, hi + 0.12, hi + 0.12,
                  'cobble' if (i + j) % 3 else 'stone')


@functools.lru_cache(maxsize=None)
def _ramp_plan():
    """The fort's stepped ramp: (x0, edge, court, start, tops, foot_y): a landing at the forecourt level from its
    edge to where the knoll starts to fall, then step tops down to the seaward path."""
    x0, y0, _ = L.WATCHTOWER
    edge = y0 - FORT_HD - 9.0
    court = L.ground(x0, edge + 1.0) + 0.18
    start = edge
    while start > edge - 8.0 and max(L.ground(x0 + dx, start - 0.75) for dx in (-2.2, 0.0, 2.2)) > court - 0.3:
        start -= 0.5
    tops, y = [], start
    z = court
    while True:
        y -= 0.42
        z -= 0.22
        g = max(L.ground(x0 + dx, y - 0.21) for dx in (-2.2, 0.0, 2.2))
        if z <= g + 0.2 or len(tops) > 80:
            break
        tops.append((y, z))
    return x0, edge, court, start, tops, y


def _forecourt(b, x0, y0):
    """A paved terrace before the gate with a parapet, two cannon aimed seaward and the stepped ramp down."""
    xs, edge, court, start, tops, foot = _ramp_plan()
    front = y0 - FORT_HD - CURTAIN_T / 2 - 0.3
    lo, _ = _ground_range(x0 - 13.0, x0 + 13.0, edge, front)
    _slab(b, x0 - 13.0, x0 + 13.0, edge, front, lo - 0.6, court, court, 'cobble')
    for side in (-1, 1):
        # Parapet along the terrace edge, open at the ramp and at a gun embrasure for each cannon.
        for a, c in ((2.6, 7.3), (8.7, 13.0)):
            sx0, sx1 = x0 + side * a, x0 + side * c
            plo, _ = _ground_range(sx0, sx1, edge - 0.8, edge)
            _slab(b, sx0, sx1, edge - 0.8, edge, plo - 1.0, court + 0.9, court + 0.9, 'stone')
            _slab(b, sx0, sx1, edge - 0.9, edge + 0.1, court + 0.9, court + 1.08, court + 1.08, 'stone_light')
        plo, _ = _ground_range(x0 + side * 7.3, x0 + side * 8.7, edge - 0.8, edge)
        _slab(b, x0 + side * 7.3, x0 + side * 8.7, edge - 0.8, edge, plo - 1.0, court + 0.35, court + 0.35, 'stone')
        cx = x0 + side * 13.0 - side * 0.4
        _slab(b, cx - 0.4, cx + 0.4, edge, front, plo - 1.0, court + 0.9, court + 0.9, 'stone')
        cannon(b, x0 + side * 8.0, edge + 2.0, court, 0.0)
    # Stepped ramp: a landing off the terrace, then each step a solid block down into the ground, between low
    # side walls.
    if start < edge:
        glo, _ = _ground_range(x0 - 2.2, x0 + 2.2, start, edge)
        _slab(b, x0 - 2.2, x0 + 2.2, start, edge, glo - 0.8, court, court, 'stone_light')
    prev = start
    for y, z in tops:
        glo, _ = _ground_range(x0 - 2.2, x0 + 2.2, y, prev)
        _slab(b, x0 - 2.2, x0 + 2.2, y, prev, glo - 0.8, z, z, 'stone_light')
        prev = y
    zf = tops[-1][1] if tops else court
    for side in (-1, 1):
        wx0, wx1 = x0 + side * 2.2, x0 + side * 2.9
        glo, _ = _ground_range(wx0, wx1, prev, edge)
        _block(b, [(min(wx0, wx1), prev, glo - 1.0), (max(wx0, wx1), prev, glo - 1.0),
                   (max(wx0, wx1), edge, glo - 1.0), (min(wx0, wx1), edge, glo - 1.0)],
               [(min(wx0, wx1), prev, zf + 0.75), (max(wx0, wx1), prev, zf + 0.75),
                (max(wx0, wx1), edge, court + 0.9), (min(wx0, wx1), edge, court + 0.9)], 'stone')
        # Gate piers at the foot with a lantern on each.
        px = x0 + side * 2.75
        pz = L.ground(px, prev - 0.5)
        b.box((px, prev - 0.5, pz + 0.5), (1.1, 1.1, 3.0), 'stone')
        b.box((px, prev - 0.5, pz + 2.1), (1.35, 1.35, 0.25), 'stone_light')
        lantern_post(b, px, prev - 0.5, pz + 2.2, 0.6)


def fort_triangles():
    from brinecove.geom import Builder
    b = Builder('fort')
    fort(b)
    return sum(len(f) - 2 for f in b.faces)


# --- the shipyard ----------------------------------------------------------------------------------------------

SLIP_X = 352.0
KEEL_Y0, KEEL_Y1 = 66.0, 100.0   # sternpost and stem foot; the stern faces the water
QUAY_TOP = 4.745                 # the harbour promenade paving's top (modules.harbor)
WATER_FACE = L.QUAY_Y - 2.1      # the quay wall's seaward face


def _floor(x, y):
    return QUAY_TOP if 62.5 <= y <= 107.0 else L.ground(x, y) + 0.16


def _keel_z(y):
    """Keel bottom: blocked up 1.3-1.9 m and falling gently toward the water."""
    return QUAY_TOP + 1.3 + 0.6 * (y - KEEL_Y0) / (KEEL_Y1 - KEEL_Y0)


HULL_B, HULL_D = 4.9, 7.2
SECTION = ((0.10, 0.0), (0.45, 0.06), (0.78, 0.18), (0.95, 0.34), (1.0, 0.52), (0.98, 0.70), (0.93, 0.86),
           (0.88, 1.0))


def _station(y):
    """Section points (x offset, z) of the hull at y, fining toward the stem and less so toward the transom."""
    t = (y - 84.0) / 18.0
    breadth = HULL_B * math.sqrt(max(0.0, 1.0 - t * t)) if t > 0 else HULL_B * math.sqrt(max(0.0, 1.0 - 0.75 * t * t))
    sheer = HULL_D + 1.1 * t * t
    fine = abs(t) ** 2
    pts = []
    for fx, fz in SECTION:
        fz = fz + (1.0 - fz) * 0.3 * fine * (1.0 - fz)
        pts.append((fx * breadth, _keel_z(y) + fz * sheer))
    return pts


def _stem(u):
    """The stem curve, u from the keel (0) to the head (1)."""
    return KEEL_Y1 + 4.4 * u * u, _keel_z(KEEL_Y1) + 0.2 + (HULL_D + 2.4) * u


def shipyard(b):
    """The slip after shipyard.jpg: a half-built hull (keel, stem, sternpost, bent ribs, ribbands, lower strakes)
    on keel blocks and a launching cradle, two ground ways running off the quay and down a piled ramp into the sea,
    scaffold decks with rails and ladders on both sides, a shear-leg crane with its tackle and a slung timber, and
    the yard's stacks, bench, barrels and shed."""
    x = SLIP_X
    frames = [67.2 + k * 2.6 for k in range(13)]
    _slipway(b, x)
    _hull(b, x, frames)
    _cradle(b, x, frames)
    for side in (-1, 1):
        _scaffold(b, x, side)
    _shear_legs(b, x)
    _yard(b, x)


def _slipway(b, x):
    # Sleepers and the two ground ways along the quay.
    for k in range(15):
        yy = 105.0 - k * 3.0
        b.box((x, yy, QUAY_TOP + 0.12), (7.6, 0.5, 0.26), 'wood_dark')
    for side in (-1, 1):
        rx = x + side * 2.6
        b.box((rx, (106.5 + WATER_FACE) / 2, QUAY_TOP + 0.42), (0.55, 106.5 - WATER_FACE, 0.36), 'wood')
    # The ramp: a plank deck on pile bents from the quay face down past the waterline.
    y1, z1 = WATER_FACE, QUAY_TOP + 0.24
    y2, z2 = 24.0, -2.0
    _block(b, [(x - 4.5, y2, z2 - 0.35), (x + 4.5, y2, z2 - 0.35), (x + 4.5, y1, z1 - 0.35), (x - 4.5, y1, z1 - 0.35)],
           [(x - 4.5, y2, z2), (x + 4.5, y2, z2), (x + 4.5, y1, z1), (x - 4.5, y1, z1)], 'wood_light')
    for side in (-1, 1):
        rx = x + side * 2.6
        b.beam((rx, y1 + 0.3, z1 + 0.17), (rx, y2, z2 + 0.17), 0.55, 'wood', depth=0.36)
        b.beam((x + side * 4.6, y1, z1 + 0.15), (x + side * 4.6, y2, z2 + 0.15), 0.3, 'wood_dark')
    for k in range(6):
        t = (k + 0.5) / 6
        yy, zz = y1 + (y2 - y1) * t, z1 + (z2 - z1) * t
        bed = L.ground(x, yy) - 1.0
        b.beam((x - 4.4, yy, zz - 0.45), (x + 4.4, yy, zz - 0.45), 0.4, 'wood_dark')
        for side in (-1, 0, 1):
            b.cylinder((x + side * 4.0, yy, bed), (x + side * 4.0, yy, zz - 0.3), 0.3, 'wood_dark', 7)
        b.beam((x - 4.0, yy, bed + 1.0), (x + 4.0, yy, zz - 0.7), 0.18, 'wood')
    # A launching stop and two bollards at the quay edge.
    b.box((x, y1 + 0.6, QUAY_TOP + 0.9), (6.4, 0.5, 0.5), 'wood_dark')
    for side in (-1, 1):
        b.cylinder((x + side * 6.2, y1 + 1.4, QUAY_TOP), (x + side * 6.2, y1 + 1.4, QUAY_TOP + 0.9), 0.35, 'metal', 8)


def _hull(b, x, frames):
    zk = _keel_z
    # Keel, keelson, stem and raked sternpost.
    b.beam((x, KEEL_Y0 - 0.6, zk(KEEL_Y0) + 0.38), (x, KEEL_Y1 + 0.3, zk(KEEL_Y1) + 0.38), 0.55, 'wood_dark',
           depth=0.76)
    b.beam((x, KEEL_Y0 + 0.5, zk(KEEL_Y0) + 0.95), (x, KEEL_Y1 - 1.0, zk(KEEL_Y1) + 0.95), 0.4, 'wood', depth=0.36)
    prev = _stem(0.0)
    for k in range(1, 9):
        cur = _stem(k / 8)
        b.beam((x, prev[0], prev[1]), (x, cur[0], cur[1]), 0.5, 'wood_dark', depth=0.6)
        prev = cur
    b.beam((x, KEEL_Y0, zk(KEEL_Y0) + 0.4), (x, KEEL_Y0 - 1.8, zk(KEEL_Y0) + HULL_D + 2.0), 0.55, 'wood_dark')
    # Transom framing across the stern.
    st = _station(KEEL_Y0 + 0.4)
    for i in (2, 4, 6, 7):
        sx, sz = st[i]
        yy = KEEL_Y0 + 0.4 - 1.8 * (sz - zk(KEEL_Y0)) / (HULL_D + 2.0)
        b.beam((x - sx, yy, sz), (x + sx, yy, sz), 0.3, 'wood_dark')
    # Ribs: each frame a bent chain of timbers up both sides, a floor across the keel and heads above the sheer.
    sections = [_station(y) for y in frames]
    for y, pts in zip(frames, sections):
        for side in (-1, 1):
            chain = [(x + side * px, y, pz) for px, pz in pts]
            head = (x + side * pts[-1][0] * 0.98, y, pts[-1][1] + 0.6)
            for a, c in zip(chain, chain[1:] + [head]):
                b.beam(a, c, 0.3, 'wood', depth=0.34)
        b.beam((x - pts[1][0], y, pts[1][1] + 0.1), (x + pts[1][0], y, pts[1][1] + 0.1), 0.3, 'wood_dark')
    # Deck beams on every other frame, the ribbands tying the frames and a sheer clamp along the heads.
    for y, pts in list(zip(frames, sections))[1:-1:2]:
        b.beam((x - pts[5][0], y, pts[5][1]), (x + pts[5][0], y, pts[5][1]), 0.28, 'wood_dark')
    for side in (-1, 1):
        for i, mat in ((5, 'wood_light'), (7, 'wood_light')):
            chain = [(x + side * (pts[i][0] + 0.2), y, pts[i][1]) for y, pts in zip(frames, sections)]
            for a, c in zip(chain, chain[1:]):
                b.beam(a, c, 0.18, mat, depth=0.24)
    # Strakes: the lower third planked full length into the stem, one more strake amidships, each two-sided.
    stem_pts = []
    for px, pz in sections[-1]:
        u = max(0.0, min(1.0, (pz - zk(KEEL_Y1) - 0.2) / (HULL_D + 2.4)))
        stem_pts.append((0.26, _stem(u)[0], pz))
    rows = [(i, 0, len(frames)) for i in range(4)] + [(4, 3, 10)]
    for side in (-1, 1):
        for i, f0, f1 in rows:
            stations = [(frames[f], sections[f]) for f in range(f0, f1)]
            for (ya, pa), (yb, pb) in zip(stations, stations[1:]):
                _strake(b, x, side, (pa[i][0], ya, pa[i][1]), (pa[i + 1][0], ya, pa[i + 1][1]),
                        (pb[i][0], yb, pb[i][1]), (pb[i + 1][0], yb, pb[i + 1][1]))
            if f1 == len(frames):
                pa, ya = sections[-1], frames[-1]
                _strake(b, x, side, (pa[i][0], ya, pa[i][1]), (pa[i + 1][0], ya, pa[i + 1][1]),
                        (stem_pts[i][0], stem_pts[i][1], stem_pts[i][2]),
                        (stem_pts[i + 1][0], stem_pts[i + 1][1], stem_pts[i + 1][2]))


def _strake(b, x, side, a0, a1, b0, b1, out=0.18, thick=0.09):
    """One plank band on the outside of the frames between two stations: outer face hull planking, inner face
    plain timber so the hull reads from the scaffold too."""
    def p(pt, off):
        px, py, pz = pt
        return (x + side * (px + off), py, pz - off * 0.5 * (1.0 - min(1.0, px / HULL_B)))
    o = [p(a0, out), p(b0, out), p(b1, out), p(a1, out)]
    i = [p(a0, out - thick), p(b0, out - thick), p(b1, out - thick), p(a1, out - thick)]
    if side > 0:
        b.quad(o[0], o[1], o[2], o[3], 'hull')
        b.quad(i[3], i[2], i[1], i[0], 'wood')
    else:
        b.quad(o[3], o[2], o[1], o[0], 'hull')
        b.quad(i[0], i[1], i[2], i[3], 'wood')


def _hull_z_at(pts, half):
    """Height of the hull bottom at |x| = half on a section, or None if the section is narrower."""
    for (xa, za), (xb, zb) in zip(pts, pts[1:]):
        if xa <= half <= xb and xb > xa:
            return za + (zb - za) * (half - xa) / (xb - xa)
    return None


def _cradle(b, x, frames):
    # Keel blocks: cross-stacked oak from the quay up to the keel.
    for k in range(11):
        yy = KEEL_Y0 + 1.2 + k * 3.2
        z0, z1 = QUAY_TOP + 0.25, _keel_z(yy)
        h = (z1 - z0) / 3
        for j, (sx, sy, mat) in enumerate(((2.0, 0.9, 'wood_dark'), (0.9, 1.6, 'wood'), (1.5, 0.8, 'wood_dark'))):
            b.box((x, yy, z0 + h * (j + 0.5)), (sx, sy, h), mat)
    # Sliding ways on the ground ways, with poppets up to the bilge and wedges between.
    for side in (-1, 1):
        rx = x + side * 2.6
        b.box((rx, (KEEL_Y0 + KEEL_Y1) / 2, QUAY_TOP + 0.75), (0.5, KEEL_Y1 - KEEL_Y0 + 1.0, 0.3), 'wood_dark')
        for y in frames[::2]:
            hz = _hull_z_at(_station(y), 2.6 + 0.25)
            if hz is None:
                continue
            b.box((rx, y, (QUAY_TOP + 0.9 + hz) / 2), (0.42, 0.42, hz - QUAY_TOP - 0.9), 'wood')
            b.box((rx, y + 0.45, QUAY_TOP + 1.05), (0.46, 0.5, 0.3), 'wood_light', top=0.7)
        # Bilge shores from the quay to the turn of the bilge.
        for y in frames[1::3]:
            pts = _station(y)
            hx, hz = pts[3]
            b.beam((x + side * (hx + 1.6), y, QUAY_TOP), (x + side * (hx + 0.2), y, hz), 0.24, 'wood_dark')


SCAFFOLD_YS = [66.0 + k * 4.25 for k in range(9)]


def _scaffold(b, x, side):
    """A trestle deck along one side of the hull: posts to the quay, ledgers, X-bracing, rails and a ladder. The
    west deck covers only the bow half so the hull reads from the quay; the east side carries a second, shorter
    deck by the crane."""
    xi, xo = x + side * 5.6, x + side * 8.2
    levels = [(QUAY_TOP + 4.6, SCAFFOLD_YS if side > 0 else SCAFFOLD_YS[4:])]
    if side > 0:
        levels.append((QUAY_TOP + 7.8, SCAFFOLD_YS[3:]))
    for zd, ys in levels:
        for y in ys:
            for px in (xi, xo):
                top = zd + (1.15 if px == xo else 0.0)
                b.box((px, y, (QUAY_TOP - 0.3 + top) / 2), (0.28, 0.28, top - QUAY_TOP + 0.3), 'wood_dark')
            b.beam((xi - side * 0.2, y, zd - 0.22), (xo + side * 0.2, y, zd - 0.22), 0.2, 'wood')
        for px in (xi, xo):
            b.beam((px, ys[0], zd - 0.4), (px, ys[-1], zd - 0.4), 0.22, 'wood')
        for j, (ya, yb) in enumerate(zip(ys, ys[1:])):
            b.box(((xi + xo) / 2, (ya + yb) / 2, zd - 0.06), (abs(xo - xi) + 0.4, yb - ya, 0.13), 'wood_light')
            if j % 2:
                continue
            zb = zd - 4.4 if zd - 4.4 > QUAY_TOP else QUAY_TOP + 0.2
            b.beam((xo + side * 0.18, ya, zb), (xo + side * 0.18, yb, zd - 0.5), 0.12, 'wood')
            b.beam((xo + side * 0.18, yb, zb), (xo + side * 0.18, ya, zd - 0.5), 0.12, 'wood')
        for dz in (0.55, 1.05):
            b.beam((xo, ys[0], zd + dz), (xo, ys[-1], zd + dz), 0.11, 'wood')
    # A ladder from the quay to the lower deck at the landward end, and one up to the top deck.
    _ladder(b, (xo + xi) / 2 + side * 0.4, SCAFFOLD_YS[-1] + 2.0, QUAY_TOP, SCAFFOLD_YS[-1] + 0.2,
            QUAY_TOP + 4.6 + 1.0)
    if side > 0:
        _ladder(b, (xo + xi) / 2, SCAFFOLD_YS[3] + 1.6, QUAY_TOP + 4.6, SCAFFOLD_YS[3] + 0.1, QUAY_TOP + 7.8 + 1.0)


def _ladder(b, x, y0, z0, y1, z1, width=0.6):
    for side in (-1, 1):
        b.beam((x + side * width / 2, y0, z0), (x + side * width / 2, y1, z1), 0.09, 'wood')
    n = int((z1 - z0) / 0.35)
    for k in range(1, n):
        t = k / n
        yy, zz = y0 + (y1 - y0) * t, z0 + (z1 - z0) * t
        b.beam((x - width / 2, yy, zz), (x + width / 2, yy, zz), 0.06, 'wood_dark')


def _shear_legs(b, x):
    """A shear-leg crane over the east side: two splayed legs lashed at the head, a backstay, a block and tackle
    whose fall runs to a windlass, and a long timber slung in a rope bridle."""
    head = (x + 3.4, 88.0, QUAY_TOP + 18.5)
    feet = [(x + 14.0, 80.5, QUAY_TOP), (x + 14.0, 95.5, QUAY_TOP)]
    for f in feet:
        b.beam(f, head, 0.55, 'wood_dark')
        b.box((f[0], f[1], QUAY_TOP + 0.2), (1.2, 1.2, 0.4), 'wood')
    b.beam((head[0] + 0.3, head[1] - 1.0, head[2] - 0.4), (head[0] + 0.3, head[1] + 1.0, head[2] - 0.4), 0.3,
           'wood')
    for k in range(3):
        b.ring((head[0] + 0.15, head[1], head[2] - 0.9 - k * 0.22), 0.42, 0.06, 'rope', sides=8, tube_sides=4)
    # Cross brace and the backstay to a stake.
    b.beam((x + 11.7, 82.1, QUAY_TOP + 4.0), (x + 11.7, 93.9, QUAY_TOP + 4.0), 0.3, 'wood')
    stake = (x + 24.0, 88.0, QUAY_TOP)
    b.box((stake[0], stake[1], QUAY_TOP + 0.5), (0.5, 0.5, 1.2), 'wood_dark')
    b.ring((stake[0], stake[1], QUAY_TOP + 0.9), 0.3, 0.05, 'metal', sides=8, tube_sides=4)
    b.rope((head[0] + 0.3, head[1], head[2] - 0.6), (stake[0], stake[1], QUAY_TOP + 0.9), sag=1.2, radius=0.07)
    # Block, hook, bridle and the slung beam.
    block = (head[0], head[1], head[2] - 5.0)
    b.beam((head[0], head[1], head[2] - 0.8), (block[0], block[1], block[2] + 0.4), 0.07, 'rope')
    b.box((block[0], block[1], block[2]), (0.38, 0.5, 0.85), 'wood_dark')
    b.cylinder((block[0] - 0.22, block[1], block[2] + 0.1), (block[0] + 0.22, block[1], block[2] + 0.1), 0.2,
               'metal', 10)
    hook = (block[0], block[1], block[2] - 0.9)
    b.beam((block[0], block[1], block[2] - 0.4), hook, 0.08, 'metal')
    beam_z = block[2] - 3.4
    ends = [(block[0], block[1] - 3.6, beam_z), (block[0], block[1] + 3.6, beam_z)]
    b.beam((ends[0][0], ends[0][1] - 0.4, beam_z), (ends[1][0], ends[1][1] + 0.4, beam_z), 0.5, 'wood')
    for e in ends:
        b.beam(hook, (e[0], e[1], e[2] + 0.3), 0.06, 'rope')
        b.ring((e[0], e[1], e[2]), 0.32, 0.05, 'rope', axis='y', sides=8, tube_sides=4)
    # The fall down to a windlass between the legs' feet.
    wx, wy = x + 13.0, 88.0
    b.beam((block[0] + 0.15, block[1], block[2] + 0.1), (wx, wy, QUAY_TOP + 1.25), 0.06, 'rope')
    for dy in (-1.1, 1.1):
        b.box((wx, wy + dy, QUAY_TOP + 0.65), (0.6, 0.25, 1.3), 'wood_dark')
    b.cylinder((wx, wy - 1.1, QUAY_TOP + 1.15), (wx, wy + 1.1, QUAY_TOP + 1.15), 0.32, 'wood', 10)
    for dy in (-0.6, 0.0, 0.6):
        b.cylinder((wx, wy + dy - 0.05, QUAY_TOP + 1.15), (wx, wy + dy + 0.05, QUAY_TOP + 1.15), 0.36, 'rope', 10)
    b.beam((wx, wy + 1.25, QUAY_TOP + 1.15), (wx + 0.6, wy + 1.25, QUAY_TOP + 1.6), 0.08, 'metal')


def _yard(b, x):
    """Stacks of squared timber and planks, a workbench with a sawhorse, barrels and crates, and the shipwright's
    open shed on the west side."""
    # Squared timbers in crossed layers on the east side, by the crane.
    tx, ty = x + 16.0, 70.0
    for layer in range(4):
        z = QUAY_TOP + 0.25 + layer * 0.5
        for k in range(3 - layer % 2):
            b.box((tx - 1.0 + k * 1.0 + (layer % 2) * 0.5, ty, z + 0.22), (0.46, 9.0 - layer * 0.8, 0.46), 'wood')
        b.box((tx, ty - 3.4, z + 0.47), (3.2, 0.2, 0.05), 'wood_dark')
        b.box((tx, ty + 3.4, z + 0.47), (3.2, 0.2, 0.05), 'wood_dark')
    # The old long plank stacks north of the shed.
    for i in range(5):
        b.box((398, 72 + i * 2.2, 5.0 + i * 0.35), (28, 1.6, 0.32), 'wood_light', 8)
    # Workbench, vice and sawhorse with a log.
    bx, by = x + 15.0, 99.5
    b.box((bx, by, QUAY_TOP + 0.92), (3.2, 1.0, 0.14), 'wood_light')
    for dx in (-1.45, 1.45):
        for dy in (-0.4, 0.4):
            b.box((bx + dx, by + dy, QUAY_TOP + 0.43), (0.14, 0.14, 0.86), 'wood_dark')
    b.box((bx, by, QUAY_TOP + 0.3), (2.9, 0.8, 0.06), 'wood')
    b.box((bx + 1.2, by - 0.42, QUAY_TOP + 1.06), (0.3, 0.2, 0.2), 'metal')
    b.box((bx - 0.6, by, QUAY_TOP + 1.04), (0.7, 0.18, 0.1), 'wood')
    sx, sy = x + 18.5, 93.0
    for dy in (-0.9, 0.9):
        for dx in (-0.4, 0.4):
            b.beam((sx + dx, sy + dy, QUAY_TOP), (sx, sy + dy, QUAY_TOP + 0.85), 0.1, 'wood_dark')
    b.cylinder((sx, sy - 1.6, QUAY_TOP + 1.05), (sx, sy + 1.8, QUAY_TOP + 1.05), 0.3, 'wood', 9)
    for k, (px, py) in enumerate(((x + 13.0, 103.0), (x + 13.9, 103.6), (x + 12.4, 104.2), (x - 10.4, 66.0),
                                  (x - 11.3, 66.8))):
        barrel(b, px, py, QUAY_TOP, 0.85 + 0.08 * (k % 2))
    for px, py, s, yaw in ((x + 17.6, 103.4, 1.0, 12.0), (x + 17.4, 102.2, 0.8, 30.0), (x - 10.6, 68.4, 0.9, 5.0)):
        crate(b, px, py, QUAY_TOP, s, yaw)
    # Shipwright's open shed: posts, a tile roof, a back wall and a bench under it.
    cx, cy = x - 15.5, 98.0
    for dx in (-5.5, 5.5):
        for dy in (-3.5, 3.5):
            b.box((cx + dx, cy + dy, QUAY_TOP + 2.0), (0.3, 0.3, 4.2), 'wood_dark')
    b.box((cx, cy + 3.6, QUAY_TOP + 1.6), (11.2, 0.2, 3.2), 'planks')
    b.gable_roof((cx, cy, QUAY_TOP + 4.1), 11.0, 7.0, QUAY_TOP + 4.1, 2.2, 'roof_terra', 0, ridge='x', overhang=0.7)
    b.box((cx, cy + 2.6, QUAY_TOP + 0.85), (8.0, 1.2, 0.12), 'wood_light')
    for dx in (-3.6, 0.0, 3.6):
        b.box((cx + dx, cy + 2.6, QUAY_TOP + 0.4), (0.14, 1.0, 0.8), 'wood_dark')
    for k in range(4):
        b.box((cx - 2.5 + k * 1.6, cy - 0.5, QUAY_TOP + 0.12 + 0.0 * k), (0.4, 5.0, 0.24), 'wood_light', 4.0 * k)


def shipyard_triangles():
    from brinecove.geom import Builder
    b = Builder('shipyard')
    shipyard(b)
    return sum(len(f) - 2 for f in b.faces)


# --- the hill stair --------------------------------------------------------------------------------------------

STAIR_PATH_X = 8.0            # the approach walk climbs north off the upper terrace here
STAIR_W, STAIR_WALL, STAIR_LANDING, STAIR_RUN = 3.4, 0.7, 3.6, 7.0
STAIR_PITCH = 6.5              # row spacing up the slope
RISE_MAX, TREAD_MIN = 0.28, 0.45
PLAZA_Y, PLAZA_D = 524.0, 7.0  # the plaza's north edge, on the hamlet shelf, and its depth


@functools.lru_cache(maxsize=None)
def _stair_plan():
    """The switchback in plan: approach walk, flights, landings and plaza, all from the layout ground.

    Flights run along x and alternate direction, each on its own row up the slope; the landing at a flight's end
    spans its row and the next. A row's treads clear the ground under its uphill edge, so the masonry below every
    flight reaches down into the slope rather than standing on posts."""
    w, run, lnd, wall = STAIR_W, STAIR_RUN, STAIR_LANDING, STAIR_WALL
    xc = STAIR_PATH_X - lnd / 2 - run / 2
    xa, xb = xc - run / 2 - lnd - wall, xc + run / 2 + lnd + wall

    def gmax(y):
        return max(L.ground(xa + (xb - xa) * i / 12, y) for i in range(13))

    plaza_z = L.ground(xc, PLAZA_Y) + 0.1
    ys = [PLAZA_Y - PLAZA_D - wall - w / 2]
    while ys[-1] - STAIR_PITCH > 430.0:
        ys.append(ys[-1] - STAIR_PITCH)
    ys.reverse()
    # The approach walk: terrain-following slabs from the terrace edge north to the foot.
    def walk_z(y):
        return max(L.ground(STAIR_PATH_X + dx, y + dy) for dx in (-1.6, 0.0, 1.6) for dy in (-1.0, 0.0, 1.0)) + 0.22

    need = [gmax(y + w / 2) + 0.05 for y in ys]
    while len(ys) > 1 and need[1] <= walk_z(ys[1] - w / 2 - 1.0) + 0.8:
        ys.pop(0)
        need.pop(0)
    walk = []
    y = 386.0
    while y < ys[0] - w / 2 - 1.0:
        walk.append((y, walk_z(y)))
        y += 2.0
    z0 = max(need[0], walk[-1][1])
    # No step on the walk may exceed a riser: raise slabs to ramp into each other and up to the bottom landing.
    levels = [z for _, z in walk] + [z0]
    for i in range(len(levels) - 2, -1, -1):
        levels[i] = max(levels[i], levels[i + 1] - (RISE_MAX - 0.02))
    for i in range(1, len(levels)):
        levels[i] = max(levels[i], levels[i - 1] - (RISE_MAX - 0.02))
    walk = [(y, z) for (y, _), z in zip(walk, levels)]
    z0 = levels[-1]
    n = len(ys)
    zs = [z0]
    for k in range(1, n):
        zs.append(max(need[k], z0 + (plaza_z - z0) * k / n, zs[-1] + 0.6))
    # A last flight under 1.6 m is folded into the plaza, which grows a row deeper.
    while n > 2 and plaza_z - zs[-1] < 1.6:
        ys.pop()
        zs.pop()
        n -= 1
    zs.append(plaza_z)
    flights = []
    for k in range(n):
        rise = zs[k + 1] - zs[k]
        risers = max(2, math.ceil(rise / (RISE_MAX - 0.02)))
        d = -1 if k % 2 == 0 else 1
        x_start = xc - d * run / 2
        flights.append(dict(y=ys[k], z=zs[k], rise=rise, risers=risers, dir=d, x_start=x_start,
                            x_end=xc + d * run / 2))
    return dict(xc=xc, xa=xa + wall, xb=xb - wall, walk=walk, flights=flights, plaza_z=plaza_z,
                plaza_y0=ys[-1] + w / 2 + wall, plaza_y1=PLAZA_Y)


def stair_route():
    """The walking line of the hill stair, bottom to top: (x, y, z) on every walk slab, landing and tread."""
    p = _stair_plan()
    pts = [(STAIR_PATH_X, y, z) for y, z in p['walk']]
    f0 = p['flights'][0]
    pts.append((f0['x_start'] - f0['dir'] * STAIR_LANDING / 2, f0['y'], f0['z']))
    for k, f in enumerate(p['flights']):
        n = f['risers']
        tread = STAIR_RUN / (n - 1)
        for i in range(1, n):
            pts.append((f['x_start'] + f['dir'] * tread * (i - 0.5), f['y'], f['z'] + f['rise'] * i / n))
        top = f['z'] + f['rise']
        nxt = p['flights'][k + 1]['y'] if k + 1 < len(p['flights']) else p['plaza_y0'] + 1.0
        pts.append((f['x_end'] + f['dir'] * STAIR_LANDING / 2, (f['y'] + nxt) / 2, top))
    pts.append((p['xc'], (p['plaza_y0'] + p['plaza_y1']) / 2, p['plaza_z']))
    pts.append((p['xc'], p['plaza_y1'] - 0.3, p['plaza_z']))
    return pts


def hill_stair(b):
    """The switchback stone stair after stairs.jpg: a kerbed walk off the upper terrace, solid flights on
    retaining walls with capped parapets and planted terraces between the rows, flat landings at every turn,
    lantern posts, and a plaza on the hamlet shelf with an arch onto the hamlet's ground."""
    p = _stair_plan()
    w, run, lnd, wall = STAIR_W, STAIR_RUN, STAIR_LANDING, STAIR_WALL
    xc, flights = p['xc'], p['flights']
    xw = STAIR_PATH_X
    # Approach walk.
    for y, z in p['walk']:
        lo, _ = _ground_range(xw - 1.6, xw + 1.6, y - 1.0, y + 1.0)
        _slab(b, xw - 1.6, xw + 1.6, y - 1.0, y + 1.0, lo - 0.4, z, z, 'stone_light' if int(y) % 4 else 'stone')
        for side in (-1, 1):
            _slab(b, xw + side * 1.6, xw + side * 1.95, y - 1.0, y + 1.0, lo - 0.4, z + 0.14, z + 0.14, 'stone')
    f0 = flights[0]
    y_walk_end = p['walk'][-1][0] + 1.0 if p['walk'] else f0['y'] - w / 2
    # Bottom landing, reached from the walk, the walk's last stretch filled up to it.
    lx0, lx1 = f0['x_start'], f0['x_start'] - f0['dir'] * lnd
    lo, _ = _ground_range(lx0, lx1, y_walk_end, f0['y'] + w / 2)
    _slab(b, lx0, lx1, y_walk_end, f0['y'] + w / 2, lo - 1.0, f0['z'], f0['z'], 'stone_light')
    _slab(b, lx1, lx1 - f0['dir'] * wall, y_walk_end, f0['y'] + w / 2 + wall, lo - 1.0, f0['z'] + 0.95,
          f0['z'] + 0.95, 'stone')
    _slab(b, lx1 + f0['dir'] * 0.05, lx1 - f0['dir'] * (wall + 0.05), y_walk_end, f0['y'] + w / 2 + wall,
          f0['z'] + 0.95, f0['z'] + 1.1, f0['z'] + 1.1, 'stone_light')
    for k, f in enumerate(flights):
        n, d = f['risers'], f['dir']
        tread = run / (n - 1)
        y0, y1 = f['y'] - w / 2, f['y'] + w / 2
        top = f['z'] + f['rise']
        # Treads: solid blocks into the ground, nosed in pale stone.
        for i in range(1, n):
            ta, tb = f['x_start'] + d * tread * (i - 1), f['x_start'] + d * tread * i
            z = f['z'] + f['rise'] * i / n
            lo, _ = _ground_range(ta, tb, y0, y1, 1.0)
            _slab(b, ta, tb, y0, y1, lo - 1.0, z, z, 'stone_light')
        # The landing at the flight's end spans this row and the next (or the plaza).
        y_next = flights[k + 1]['y'] + w / 2 if k + 1 < len(flights) else p['plaza_y0']
        ea, eb = f['x_end'], f['x_end'] + d * lnd
        lo, _ = _ground_range(ea, eb, y0, y_next)
        _slab(b, ea, eb, y0, y_next, lo - 1.0, top, top, 'stone_light')
        # Outer parapet round the landing's far end.
        _slab(b, eb, eb + d * wall, y0 - wall, y_next, lo - 1.0, top + 0.95, top + 0.95, 'stone')
        _slab(b, eb - d * 0.05, eb + d * (wall + 0.05), y0 - wall, y_next, top + 0.95, top + 1.1, top + 1.1,
              'stone_light')
        if k % 2 == 0:
            lantern_post(b, eb - d * 0.5, y0 + 0.5, top, 2.8)
        # The wall below this row: the lower row's (or the hillside's) retaining wall and this row's parapet,
        # with a planted terrace between when the rows stand apart.
        prev_top = flights[k - 1]['y'] + w / 2 if k > 0 else y0 - wall
        _row_wall(b, f, prev_top, y0, wall)
    # The plaza and its arch.
    _plaza(b, p, flights[-1])


def _row_wall(b, f, y_lo, y_hi, wall):
    """Masonry between y_lo (the lower row's uphill edge) and y_hi (this row's downhill edge): a capped parapet
    0.95 m over this row's treads and landing, and a planted terrace behind it."""
    d, run, lnd = f['dir'], STAIR_RUN, STAIR_LANDING
    top = f['z'] + f['rise']
    xs, xe = f['x_start'], f['x_end']
    outer = xe + d * lnd
    lo, _ = _ground_range(min(xs, outer), max(xs, outer), y_lo - 0.5, y_hi)
    base = lo - 1.0
    for ya, yb, add, mat in ((y_hi - wall, y_hi, 0.95, 'stone'), (y_lo, y_hi - wall, 0.4, 'stone')):
        if yb - ya < 0.05:
            continue
        _slab(b, xs, xe, ya, yb, base, f['z'] + add, top + add, mat)
        _slab(b, xe, outer, ya, yb, base, top + add, top + add, mat)
        if add > 0.9:
            _slab(b, xs, xe, ya - 0.05, yb + 0.05, f['z'] + add, f['z'] + add + 0.15, top + add + 0.15,
                  'stone_light')
            _slab(b, xe, outer, ya - 0.05, yb + 0.05, top + add, top + add + 0.15, top + add + 0.15, 'stone_light')
        else:
            _slab(b, xs, xe, ya, yb, f['z'] + add, f['z'] + add + 0.12, top + add + 0.12, 'moss')
            _slab(b, xe, outer, ya, yb, top + add, top + add + 0.12, top + add + 0.12, 'moss')
            if yb - ya > 1.6:
                for t in (0.25, 0.75):
                    bx = xs + (xe - xs) * t
                    bush(b, bx, (ya + yb) / 2, f['z'] + (top - f['z']) * t + add + 0.1, 0.0, 0.9)


def _plaza(b, p, last):
    """The plaza on the hamlet shelf: flagstones over a retained terrace, parapets east and west, potted palms,
    lantern posts and an arch on its north edge opening onto the hamlet's ground."""
    xa, xb = p['xa'], p['xb']
    y0, y1, z = p['plaza_y0'], p['plaza_y1'], p['plaza_z']
    lo, _ = _ground_range(xa, xb, y0, y1)
    _slab(b, xa, xb, y0, y1, lo - 1.0, z, z, 'stone_light')
    for i in range(4):
        sx = xa + (xb - xa) * (i + 0.5) / 4
        b.box((sx, (y0 + y1) / 2, z + 0.01), (0.12, y1 - y0 - 0.4, 0.04), 'stone')
    # The parapet over the last flight, retaining the plaza.
    d, lnd = last['dir'], STAIR_LANDING
    wa, wb = last['x_start'] - d * lnd, last['x_end']
    wy0, wy1 = last['y'] + STAIR_W / 2, y0
    wlo, _ = _ground_range(min(wa, wb), max(wa, wb), wy0, wy1)
    _slab(b, wa, wb, wy0, wy1, wlo - 1.0, z + 0.95, z + 0.95, 'stone')
    _slab(b, wa, wb, wy0 - 0.05, wy1 + 0.05, z + 0.95, z + 1.1, z + 1.1, 'stone_light')
    for x0, x1 in ((xa - STAIR_WALL, xa), (xb, xb + STAIR_WALL)):
        _slab(b, x0, x1, y0 - STAIR_WALL, y1, lo - 1.0, z + 0.95, z + 0.95, 'stone')
        _slab(b, x0 - 0.05, x1 + 0.05, y0 - STAIR_WALL, y1, z + 0.95, z + 1.1, z + 1.1, 'stone_light')
    # The arch: piers, voussoirs, a cornice and lanterns, with low walls either side along the north edge.
    xc = p['xc']
    span, pier, yy = 2.6, 1.3, y1 - 0.6
    for side in (-1, 1):
        px = xc + side * (span + pier / 2)
        b.box((px, yy, z + 2.1), (pier, 1.2, 4.2), 'stone_light')
        b.box((px, yy, z + 0.25), (pier + 0.3, 1.5, 0.5), 'stone')
        b.box((px, yy, z + 4.1), (pier + 0.2, 1.35, 0.25), 'stone')
        _wall_lantern(b, px, yy - 0.6, z + 2.6, -1)
        wx0, wx1 = (xa, px - pier / 2) if side < 0 else (px + pier / 2, xb)
        _slab(b, wx0, wx1, yy - 0.35, yy + 0.35, lo - 1.0, z + 0.95, z + 0.95, 'stone')
        _slab(b, wx0 - 0.05, wx1 + 0.05, yy - 0.42, yy + 0.42, z + 0.95, z + 1.1, z + 1.1, 'stone_light')
        potted_plant(b, px + side * 2.2, yy - 1.6, z, 1.1)
        lantern_post(b, (xa + 0.6) if side < 0 else (xb - 0.6), y0 + 0.6, z, 3.0)
    for k in range(11):
        a = math.pi * k / 10
        b.box((xc + math.cos(a) * (span + 0.4), yy, z + 4.2 + math.sin(a) * (span + 0.4)), (0.8, 1.2, 0.8),
              'stone_light' if k % 2 else 'stone')
    b.box((xc, yy, z + 4.2 + span + 1.1), (2 * (span + pier) + 0.6, 1.4, 0.8), 'stone_light')
    b.box((xc, yy, z + 4.2 + span + 1.6), (2 * (span + pier) + 1.0, 1.6, 0.25), 'stone')
    # Flagstones carry on through the arch onto the shelf.
    for k in range(6):
        fy = y1 + 0.8 + k * 2.2
        fz = L.ground(xc, fy)
        b.box((xc + (0.5 if k % 2 else -0.4), fy, fz + 0.05), (2.6, 1.7, 0.3), 'stone')


def stair_triangles():
    from brinecove.geom import Builder
    b = Builder('stair')
    hill_stair(b)
    return sum(len(f) - 2 for f in b.faces)


def footprint(x, y, margin=2.0):
    """True on the hill stair or the fort's forecourt and ramp, for planting masks (trees must not grow through)."""
    p = _stair_plan()
    f0 = p['flights'][0]
    if abs(x - STAIR_PATH_X) <= 2.0 + margin and 380.0 <= y <= f0['y'] + STAIR_W / 2:
        return True
    if (p['xa'] - STAIR_WALL - margin <= x <= p['xb'] + STAIR_WALL + margin
            and f0['y'] - STAIR_W / 2 - STAIR_WALL - margin <= y <= p['plaza_y1'] + margin):
        return True
    x0, edge, _, _, _, foot = _ramp_plan()
    return abs(x - x0) <= 3.5 + margin and foot - 1.5 - margin <= y <= edge + margin
