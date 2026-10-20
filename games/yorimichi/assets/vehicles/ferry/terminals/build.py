"""Ferry terminals at Hidamari and Brinecove, matched to the v2 concepts. Procedural Blender build.

blender --background --factory-startup --threads 3 --python-exit-code 1 -P games/yorimichi/assets/vehicles/ferry/terminals/build.py
Reads build/yorimichi/ferry/terminals/site.json (site.py: the berths, boarding gates and fender faces). Each terminal is
modelled in its region's frame (Hidamari: world metres; Brinecove: region-local) and exported with its origin at the
anchor recorded in the manifest, on the fender face opposite the boarding gate at sea level. Writes FT_*.fbx,
terminals.blend, manifest.json and walk.json (a ray-cast walk audit from the promenade to the boarding gate).
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import build as F  # noqa: E402  (the ferry's mesh builder; importing it does not build the ship)
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

OUT = F.OUT / 'terminals'
SITE = json.loads((OUT / 'site.json').read_text())
SILL = SITE['ship']['sill_z']
GATE_W = SITE['ship']['gate_width']

# ------------------------------------------------------------------ materials (sRGB, roughness, metallic)
TIMBER, TIMBER_DARK, PLANK, PLASTER, KAWARA, RIDGE = 'FT_Timber', 'FT_TimberDark', 'FT_Plank', 'FT_Plaster', 'FT_Kawara', 'FT_KawaraRidge'
STONE, BLACK, IRON, WHITE, GLASS, PAPER = 'FT_Stone', 'FT_FenderBlack', 'FT_Iron', 'FT_WhitePaint', 'FT_Glass', 'FT_Paper'
ROPE, NET, FLOAT, CRATE, BRASS, GLOW, INK, TERRACOTTA, MOSS = ('FT_Rope', 'FT_Net', 'FT_Float', 'FT_Crate', 'FT_Brass',
                                                             'FT_LanternGlow', 'FT_Ink', 'FT_Terracotta', 'FT_Moss')
MATERIALS = {
    TIMBER: ((132, 88, 52), .7, 0.), TIMBER_DARK: ((84, 58, 40), .75, 0.), PLANK: ((168, 126, 84), .8, 0.),
    PLASTER: ((236, 230, 216), .85, 0.), KAWARA: ((74, 78, 90), .55, .1), RIDGE: ((56, 59, 70), .5, .1),
    STONE: ((150, 146, 136), .9, 0.), BLACK: ((34, 34, 36), .7, 0.), IRON: ((44, 44, 46), .45, .5),
    WHITE: ((236, 236, 232), .5, 0.), GLASS: ((70, 86, 104), .15, 0.), PAPER: ((240, 232, 210), .9, 0.),
    ROPE: ((196, 168, 118), .9, 0.), NET: ((58, 104, 108), .9, 0.), FLOAT: ((232, 112, 50), .6, 0.),
    CRATE: ((150, 108, 66), .8, 0.), BRASS: ((206, 164, 78), .35, .55), GLOW: ((255, 214, 150), .5, 0.),
    INK: ((40, 36, 34), .8, 0.), TERRACOTTA: ((176, 98, 62), .8, 0.), MOSS: ((92, 118, 70), .9, 0.),
}
F.MATERIALS.update(MATERIALS)          # the ferry's to_object orders slots by this table

RISER_MAX = 0.24
TREAD = 0.28
RAIL_H = 1.05


def frame_axes(U, V):
    """A right-handed frame from two axes: U, V and their cross product."""
    U, V = Vector(U).normalized(), Vector(V).normalized()
    return U, V, U.cross(V)


# ------------------------------------------------------------------ structural pieces
def post(m, x, y, z0, z1, s=0.26, mat=TIMBER, footing=False):
    m.box((x, y, (z0 + z1) / 2), (s, s, z1 - z0), mat, bevel=0.015)
    if footing:
        m.box((x, y, z0 + 0.12), (s + 0.22, s + 0.22, 0.24), STONE, bevel=0.03)


def rail_line(m, pts, z, h=RAIL_H, spacing=1.6, mat=TIMBER):
    """Timber railing along a polyline at floor height z: square posts, a capped top rail and a mid rail."""
    for a, b in zip(pts, pts[1:]):
        L = math.dist(a, b); n = max(1, math.ceil(L / spacing))
        for k in range(n + 1):
            if k == 0 and a is not pts[0]:
                continue
            x = a[0] + (b[0] - a[0]) * k / n; y = a[1] + (b[1] - a[1]) * k / n
            m.box((x, y, z + h / 2), (0.13, 0.13, h), mat, bevel=0.01)
            m.box((x, y, z + h + 0.03), (0.17, 0.17, 0.06), mat)
        m.beam((a[0], a[1], z + h - 0.05), (b[0], b[1], z + h - 0.05), 0.11, 0.14, mat)
        m.beam((a[0], a[1], z + h * 0.5), (b[0], b[1], z + h * 0.5), 0.07, 0.1, mat)


def solid_stair(m, foot, direction, width, z0, flights, r, tread=TREAD, landing=1.2, top_mat=PLANK, side_mat=TIMBER_DARK,
                T=0.25):
    """Flights of closed steps (treads and risers in one solid each, so there is no daylight between steps), each with
    a soffit parallel to its pitch, joined by landing slabs. foot is the centre of the first riser on the floor at z0;
    the stair climbs along direction. Returns its run, rise and top."""
    d = Vector((direction[0], direction[1], 0)).normalized()
    U, V, A = frame_axes(d, (0, 0, 1))
    u, z = 0.0, 0.0; treads = []
    with m.frame((foot[0], foot[1], z0), U, V, A):
        for fi, n in enumerate(flights):
            us, zs = u, z
            pts = [(us, zs)]
            for k in range(n):
                z += r; pts.append((u, z))
                if k < n - 1:
                    treads.append((u, u + tread, z)); u += tread; pts.append((u, z))
            pts += [(u, z - r - T), (us + T * tread / r, zs)]
            mats = {}
            for a_, b_ in zip(pts, pts[1:] + pts[:1]):
                horizontal = abs(a_[1] - b_[1]) < 1e-6 and b_[0] > a_[0]
                mats[(round((a_[0] + b_[0]) / 2, 4), round((a_[1] + b_[1]) / 2, 4))] = top_mat if horizontal else side_mat
            m.prism(pts, -width / 2, width / 2, lambda x, y, mats=mats: mats.get((round(x, 4), round(y, 4)), side_mat),
                    top=side_mat, bottom=side_mat)
            for sd in (-1, 1):            # stringers on both sides, 0.25 m proud of the pitch line
                sl = [(us, zs - 0.05), (us, zs + r + 0.25), (u, z + 0.25), (u, z - r - T - 0.05)]
                m.prism(sl, sd * width / 2 - 0.04 * (1 - sd) - 0.0, sd * width / 2 + 0.04 * (1 + sd), TIMBER)
            if fi < len(flights) - 1:
                m.prism(F.rect(u, z - T, u + landing, z), -width / 2, width / 2, side_mat, top=side_mat, bottom=side_mat)
                m.prism(F.rect(u, z - 0.02, u + landing, z), -width / 2, width / 2, top_mat)
                treads.append((u, u + landing, z)); u += landing
    top = (foot[0] + d.x * u, foot[1] + d.y * u, z0 + z)
    return {'run': round(u, 4), 'rise': round(z, 4), 'top': [round(v, 4) for v in top], 'risers': sum(flights), 'riser': round(r, 5),
            'tread': tread, 'landing': landing, 'width': width}


def stair_run(flights, tread=TREAD, landing=1.2):
    return sum((n - 1) * tread for n in flights) + landing * (len(flights) - 1)


def gable_roof(m, x0, y0, x1, y1, ze, pitch, axis='x', over=(0.9, 0.9, 0.9, 0.9), t=0.16, ribs=True, gable_mat=TIMBER_DARK):
    """Kawara gable roof over the wall rectangle; ridge along axis; eave height ze at the wall line.
    over = (west, east, south, north) overhangs. Returns the ridge height."""
    if axis == 'y':          # build along x in a rotated frame: swap axes by mirroring through x = y
        with m._push(F.Matrix(((0, 1, 0, 0), (1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))):
            return gable_roof(m, y0, x0, y1, x1, ze, pitch, 'x', (over[2], over[3], over[0], over[1]), t, ribs, gable_mat)
    yc = (y0 + y1) / 2; D = (y1 - y0) / 2; zr = ze + D * pitch
    ow, oe, os_, on = over
    for s, o in ((-1, os_), (1, on)):
        run = D + o; L = math.hypot(run, run * pitch)
        V = Vector((0, s * run, -run * pitch)).normalized()
        U, V, A = frame_axes((1, 0, 0), V)
        flip = A.z < 0
        if flip:
            U, V, A = frame_axes((-1, 0, 0), V)
        ua, ub = (-(x1 + oe), -(x0 - ow)) if flip else (x0 - ow, x1 + oe)
        with m.frame((0, yc, zr + 0.02), U, V, A):
            m.prism(F.rect(ua, 0.0, ub, L), 0.0, t, KAWARA, top=KAWARA, bottom=TIMBER_DARK)
        if ribs:
            n = int((x1 + oe - (x0 - ow)) / 0.3)
            for k in range(n + 1):
                x = x0 - ow + 0.12 + k * (x1 + oe - x0 + ow - 0.24) / n
                p0 = Vector((x, yc, zr + 0.02)) + A * (t + 0.02); p1 = p0 + V * (L - 0.05)
                m.tube([tuple(p0), tuple(p1)], 0.065, KAWARA, n=5)
            # Round eave tiles and a fascia board under the eave edge.
            e = Vector((0, yc, zr + 0.02)) + V * L
            m.beam((x0 - ow, e.y, e.z - 0.12), (x1 + oe, e.y, e.z - 0.12), 0.12, 0.22, TIMBER_DARK)
        # Rafter ends under the overhang.
        for k in range(int((x1 - x0) / 0.6) + 1):
            x = x0 + k * (x1 - x0) / int((x1 - x0) / 0.6)
            a = Vector((x, y0 if s < 0 else y1, ze - 0.12)); b = Vector((x, yc + s * (D + o - 0.1), ze - 0.12 - (o - 0.1) * pitch))
            m.beam(tuple(a), tuple(b), 0.08, 0.1, TIMBER_DARK)
    # Ridge: a capped tile ridge with onigawara end blocks.
    m.beam((x0 - ow - 0.05, yc, zr + 0.18), (x1 + oe + 0.05, yc, zr + 0.18), 0.4, 0.36, RIDGE)
    m.tube([(x0 - ow - 0.05, yc, zr + 0.4), (x1 + oe + 0.05, yc, zr + 0.4)], 0.15, RIDGE, n=8)
    for x in (x0 - ow - 0.1, x1 + oe + 0.1):
        m.box((x, yc, zr + 0.42), (0.22, 0.56, 0.62), RIDGE, bevel=0.04)
    # Gable triangles and bargeboards at both ends.
    for x, o in ((x0, -ow), (x1, oe)):
        tri = [(y0, ze), (y1, ze), (yc, zr)]
        with m.frame((x - 0.06, 0, 0), Vector((0, 1, 0)), Vector((0, 0, 1)), Vector((1, 0, 0))):
            m.prism(tri, 0.0, 0.12, gable_mat)
        for s in (-1, 1):
            ye = yc + s * (D + (os_ if s < 0 else on)); zz = ze - (os_ if s < 0 else on) * pitch
            m.beam((x + o, yc, zr + 0.12), (x + o, ye, zz + 0.05), 0.1, 0.32, TIMBER_DARK)
    return zr


def tie_truss(m, x, y0, y1, ze, zr, mat=TIMBER):
    """Exposed king-post truss across the building at x."""
    yc = (y0 + y1) / 2
    m.beam((x, y0, ze - 0.2), (x, y1, ze - 0.2), 0.22, 0.3, mat)
    m.beam((x, yc, ze - 0.05), (x, yc, zr - 0.15), 0.2, 0.2, mat)
    for s in (y0, y1):
        m.beam((x, s + (yc - s) * 0.12, ze - 0.05), (x, yc, zr - 0.25), 0.16, 0.18, mat)


def knee(m, p, q, mat=TIMBER):
    m.beam(p, q, 0.12, 0.14, mat)


def bollard(m, x, y, z, r=0.22):
    m.lathe((x, y, z), [(0, r * 1.2), (0.08, r * 1.2), (0.12, r), (0.5, r * 0.9), (0.58, r * 1.35), (0.68, r * 1.35), (0.74, 0)],
            IRON, n=12)


def tyre(m, c, normal, R=0.36, r=0.13):
    n = Vector(normal).normalized(); U, V, A = frame_axes(Vector((0, 0, 1)).cross(n) if abs(n.z) < 0.9 else Vector((1, 0, 0)), n)
    with m.frame(c, U, A, V):
        m.torus((0, 0, 0), R, r, BLACK, n=14, m=6)


def rope_coil(m, x, y, z, R=0.42, turns=3):
    for k in range(turns):
        m.torus((x, y, z + 0.05 + k * 0.075), R - k * 0.05, 0.045, ROPE, n=16, m=5)


def crate(m, x, y, z, s=0.9, yaw=0.0):
    with m.at((x, y, z), yaw):
        m.box((0, 0, s / 2), (s, s, s), CRATE, bevel=0.02)
        for h in (0.12, s - 0.12):
            m.ring_prism(F.rect(-s / 2 - 0.02, -s / 2 - 0.02, s / 2 + 0.02, s / 2 + 0.02), F.rect(-s / 2 + 0.01, -s / 2 + 0.01, s / 2 - 0.01, s / 2 - 0.01),
                         h - 0.05, h + 0.05, TIMBER_DARK)


def barrel(m, x, y, z, h=0.95):
    m.lathe((x, y, z), [(0, 0.27), (0.1, 0.31), (h / 2, 0.36), (h - 0.1, 0.31), (h, 0.27), (h, 0)], CRATE, n=14)
    for hz in (0.12, h - 0.12):
        m.lathe((x, y, z + hz - 0.03), [(0, 0.325), (0.06, 0.325), (0.06, 0)], IRON, n=14)


def net_pile(m, x, y, z, r=0.75):
    m.lathe((x, y, z), [(0, r), (r * 0.35, r * 0.9), (r * 0.6, r * 0.55), (r * 0.72, 0)], NET, n=12, sx=1.0, sy=0.8)
    for k in range(5):
        a = k * 1.3
        m.lathe((x + 0.55 * r * math.cos(a), y + 0.45 * r * math.sin(a), z + 0.18 + 0.12 * (k % 2)),
                [(0, 0.0), (0.04, 0.12), (0.14, 0.15), (0.24, 0.12), (0.28, 0.0)], FLOAT, n=10)


def lantern(m, x, y, z, h=0.42):
    m.box((x, y, z + h / 2), (0.26, 0.26, h), GLOW)
    m.box((x, y, z + 0.02), (0.32, 0.32, 0.05), TIMBER_DARK)
    m.lathe((x, y, z + h), [(0, 0.24), (0.05, 0.24), (0.14, 0.05), (0.18, 0)], TIMBER_DARK, n=4, phase=math.pi / 4)


def bench(m, a, b, z, depth=0.42, h=0.44):
    d = Vector((b[0] - a[0], b[1] - a[1], 0)); L = d.length; d.normalize(); nrm = Vector((-d.y, d.x, 0))
    m.beam((a[0], a[1], z + h), (b[0], b[1], z + h), depth, 0.07, PLANK)
    for t in (0.12, 0.5, 0.88):
        if L < 2.0 and t == 0.5:
            continue
        p = (a[0] + d.x * L * t, a[1] + d.y * L * t)
        m.box((p[0], p[1], z + h / 2 - 0.02), (0.1 + abs(nrm.x) * (depth - 0.1), 0.1 + abs(nrm.y) * (depth - 0.1), h - 0.04), TIMBER_DARK)


def wall(m, a, b, z0, h, t, mat, openings=(), frame_mat=TIMBER):
    """A straight wall from a to b (outward normal to the right of a->b) with rectangular openings
    [(u0, u1, v0, v1)] in metres along/up the wall; timber frame members at the ends and around openings."""
    d = Vector((b[0] - a[0], b[1] - a[1], 0)); L = d.length; d.normalize()
    U, V, A = frame_axes(d, (0, 0, 1))
    cuts = sorted({0.0, L, *[o[0] for o in openings], *[o[1] for o in openings]})
    with m.frame((a[0], a[1], z0), U, V, A):
        for u0, u1 in zip(cuts, cuts[1:]):
            spans = [(0.0, h)]
            for o in openings:
                if o[0] <= u0 + 1e-6 and o[1] >= u1 - 1e-6:
                    spans = [(s0, s1) for s0, s1 in [(0.0, o[2]), (o[3], h)] if s1 - s0 > 1e-3]
            for v0, v1 in spans:
                m.prism(F.rect(u0, v0, u1, v1), -t / 2, t / 2, mat)
        for u in (0.0, L):
            m.prism(F.rect(u - 0.12, 0.0, u + 0.12, h), -t / 2 - 0.03, t / 2 + 0.03, frame_mat)
        m.prism(F.rect(0.0, h - 0.18, L, h), -t / 2 - 0.03, t / 2 + 0.03, frame_mat)
        m.prism(F.rect(0.0, 0.0, L, 0.2), -t / 2 - 0.03, t / 2 + 0.03, frame_mat)
        for o in openings:
            u0, u1, v0, v1 = o[:4]
            for u in (u0 - 0.06, u1 + 0.06):
                m.prism(F.rect(u - 0.06, max(0.0, v0 - 0.06), u + 0.06, min(h, v1 + 0.06)), -t / 2 - 0.035, t / 2 + 0.035, frame_mat)
            m.prism(F.rect(u0 - 0.12, v1, u1 + 0.12, v1 + 0.1), -t / 2 - 0.035, t / 2 + 0.035, frame_mat)
            if v0 > 0.05:
                m.prism(F.rect(u0 - 0.12, v0 - 0.1, u1 + 0.12, v0), -t / 2 - 0.05, t / 2 + 0.05, frame_mat)
            kind = o[4] if len(o) > 4 else 'window'
            if kind == 'window':      # sliding glazed sash with a timber grid (inset)
                m.prism(F.rect(u0, v0, u1, v1), -0.03, 0.03, GLASS)
                nx = max(1, round((u1 - u0) / 0.45)); ny = max(1, round((v1 - v0) / 0.45))
                for i in range(1, nx):
                    uu = u0 + (u1 - u0) * i / nx
                    m.prism(F.rect(uu - 0.025, v0, uu + 0.025, v1), -0.05, 0.05, frame_mat)
                for j in range(1, ny):
                    vv = v0 + (v1 - v0) * j / ny
                    m.prism(F.rect(u0, vv - 0.025, u1, vv + 0.025), -0.05, 0.05, frame_mat)
            elif kind == 'door':
                m.prism(F.rect(u0, 0.0, u1, v1), -0.04, 0.04, TIMBER_DARK)
                m.prism(F.rect(u0 + 0.12, v1 * 0.55, u1 - 0.12, v1 - 0.12), -0.06, 0.06, GLASS)
            elif kind == 'counter':   # ticket window: an open hatch with a shelf
                m.prism(F.rect(u0, v0 - 0.08, u1, v0), 0.0, 0.42, PLANK)


def piles_under(m, xs, ys, z_top, z_bot=-4.0, s=0.34, braces=True, mat=TIMBER_DARK):
    for x in xs:
        for y in ys:
            m.box((x, y, (z_top + z_bot) / 2), (s, s, z_top - z_bot), mat)
    if braces:                       # walings just above the water and cross-braces under the deck
        for y in ys:
            m.beam((xs[0], y, 0.6), (xs[-1], y, 0.6), 0.12, 0.22, mat)
            for xa, xb in zip(xs, xs[1:]):
                m.beam((xa, y, 0.7), (xb, y, z_top - 0.55), 0.1, 0.14, mat)


def brow(m, x0, y0, x1, y1, z, width=2.2):
    """White truss gangway between two points at deck height z (level); handrails 1.0 m."""
    d = Vector((x1 - x0, y1 - y0, 0)); L = d.length; d.normalize(); nrm = Vector((-d.y, d.x, 0))
    c = Vector(((x0 + x1) / 2, (y0 + y1) / 2, z))
    U, V, A = frame_axes(d, (0, 0, 1))
    with m.frame((x0, y0, z), d, nrm, Vector((0, 0, 1))):
        m.prism(F.rect(0.0, -width / 2, L, width / 2), -0.12, 0.0, WHITE, top=PLANK)
        for s in (-1, 1):
            yy = s * (width / 2 - 0.05)
            m.prism(F.rect(0.0, yy - 0.05, L, yy + 0.05), 0.0, 0.12, WHITE)            # kick plate
            m.beam((0.0, yy, 1.0), (L, yy, 1.0), 0.06, 0.06, WHITE)
            m.beam((0.0, yy, 0.5), (L, yy, 0.5), 0.04, 0.04, WHITE)
            n = max(2, round(L / 0.55))
            for k in range(n + 1):
                m.beam((L * k / n, yy, 0.0), (L * k / n, yy, 1.0), 0.05, 0.05, WHITE)
            for k in range(n):
                a, b = (L * k / n, 0.12), (L * (k + 1) / n, 0.95)
                if k % 2:
                    a, b = (a[0], b[1]), (b[0], a[1])
                m.beam((a[0], yy, a[1]), (b[0], yy, b[1]), 0.035, 0.035, WHITE)
        # The hinge barrel on the shore end.
        m.tube([(0.0, -width / 2, -0.06), (0.0, width / 2, -0.06)], 0.07, IRON, n=8)
    return {'from': [x0, y0, z], 'to': [x1, y1, z], 'clear_width': round(width - 0.2, 3)}


def timetable(m, x, y, z, yaw, w=2.4, h=1.7):
    """Timetable notice board on two posts with a small kawara hood and two lamps, as in concept v2."""
    with m.at((x, y, z), yaw):
        for s in (-1, 1):
            post(m, s * (w / 2 + 0.12), 0, 0.0, 3.2, s=0.2, mat=TIMBER_DARK, footing=True)
        m.box((0, 0, 1.0 + h / 2), (w, 0.08, h), TIMBER_DARK)
        m.box((0, -0.05, 1.0 + h / 2), (w - 0.16, 0.04, h - 0.16), PAPER)
        for k in range(7):
            zz = 1.0 + h - 0.32 - k * 0.19
            m.box((-0.45, -0.075, zz), (w * 0.42 if k else w * 0.7, 0.01, 0.05 if k else 0.09), INK)
            if k:
                m.box((0.6, -0.075, zz), (w * 0.28, 0.01, 0.05), INK)
        m.box((0, 0, 3.05), (w + 0.7, 0.5, 0.12), TIMBER_DARK)
        with m.at((0, 0, 0)):
            gable_roof(m, -w / 2 - 0.25, -0.25, w / 2 + 0.25, 0.25, 3.12, 0.5, over=(0.15, 0.15, 0.3, 0.3), t=0.08, ribs=True)
        for s in (-1, 1):
            m.beam((s * 0.7, -0.05, 3.0), (s * 0.7, -0.35, 2.9), 0.04, 0.04, IRON)
            lantern(m, s * 0.7, -0.38, 2.55, h=0.3)


# ------------------------------------------------------------------ Hidamari (world metres)
def hidamari():
    b = SITE['hidamari']['berth']; gx, gy, _ = b['gate']; face = b['face']; quay = b['walk_level_z']
    QF = -127.7                       # quay coping outer face
    meshes = {k: F.Mesh(k) for k in ('FT_HD_Jetty', 'FT_HD_Stage', 'FT_HD_Brow', 'FT_HD_WaitingHouse', 'FT_HD_Timetable')}
    J, S, B, W, T = meshes.values()
    deck_t = 0.3
    x0, x1 = gx - 8.0, gx + 8.0
    # Jetty: plank deck flush with the coping, on timber piles, with a dark fascia, black fender piles on its face and
    # railings along its open sides.
    J.prism(F.rect(x0, face, x1, QF), quay - deck_t, quay, TIMBER_DARK, top=PLANK)
    for k in range(int((x1 - x0) / 0.5)):
        xx = x0 + 0.25 + k * 0.5
        J.box((xx, (face + QF) / 2, quay + 0.004), (0.02, QF - face - 0.1, 0.012), TIMBER_DARK)   # plank seams
    piles_under(J, [x0 + 0.3 + k * (x1 - x0 - 0.6) / 5 for k in range(6)], [face + 0.3, (face + QF) / 2, QF - 0.4], quay - deck_t)
    for k in range(9):
        xx = x0 + 0.5 + k * (x1 - x0 - 1.0) / 8
        J.box((xx, face - 0.25, (quay + 0.35 - 3.5) / 2), (0.36, 0.36, quay + 0.35 + 3.5), BLACK, bevel=0.03)
        J.box((xx, face - 0.27, quay + 0.4), (0.42, 0.42, 0.1), TIMBER_DARK)
    for xx in (gx - 5.6, gx + 5.6):  # cylindrical fenders hung on chains between the piles
        J.tube([(xx - 1.1, face - 0.42, 0.9), (xx + 1.1, face - 0.42, 0.9)], 0.38, BLACK, n=10)
    rail_line(J, [(x0 + 0.15, QF - 0.3), (x0 + 0.15, face + 0.12), (x1 - 0.15, face + 0.12), (x1 - 0.15, QF - 0.3)], quay)
    for xx in (x0 + 0.7, x1 - 0.7):
        bollard(J, xx, face + 0.7, quay)
    # Boarding stage: a timber stage on tall posts tied with nuki beams (a little Kiyomizu), its gallery flush with the
    # ship's sill; the stair climbs from the jetty straight to the gate on its axis; a kawara roof covers both.
    gal0, gal1 = face, face + 3.0
    sx0, sx1 = gx - 5.5, gx + 5.5
    foot_y = gal1 + stair_run([10, 9])
    st = solid_stair(S, (gx, foot_y), (0, -1), 2.2, quay, [10, 9], (SILL - quay) / 19, landing=1.2)
    S.prism(F.rect(sx0, gal0, sx1, gal1), SILL - 0.3, SILL, TIMBER_DARK, top=PLANK)
    ze = SILL + 2.6                            # tie beams clear the gallery by 2.25 m
    posts = [(x, y) for x in (sx0 + 0.2, gx - 1.45, gx + 1.45, sx1 - 0.2) for y in (gal0 + 0.2, gal1 - 0.1)]
    posts += [(x, foot_y - 0.2) for x in (sx0 + 0.2, sx1 - 0.2)]
    for x, y in posts:
        post(S, x, y, quay, ze, s=0.3)
    for y in (gal0 + 0.2, gal1 - 0.1):          # nuki ties through the posts, clear of the stair head
        for zz in (quay + 2.45, SILL - 0.45):
            spans = [(sx0, sx1)] if (y < gal1 - 1.0 or zz < quay + (SILL - quay) * 0.4) else [(sx0, gx - 1.25), (gx + 1.25, sx1)]
            for xa, xb in spans:
                S.beam((xa, y, zz), (xb, y, zz), 0.14, 0.24, TIMBER)
    for x in (sx0 + 0.2, sx1 - 0.2):
        for zz in (quay + 2.45, ze - 0.2):
            S.beam((x, gal0, zz), (x, foot_y - 0.2, zz), 0.14, 0.24, TIMBER)
    for x in (gx - 1.45, gx + 1.45):             # stair landing posts
        post(S, x, gal1 + 9 * TREAD + 0.6, quay, quay + (SILL - quay) * 10 / 19 - 0.05, s=0.22)
    land_y0 = gal1 + 8 * TREAD; land_y1 = land_y0 + 1.2
    # Gallery and stair railings, open at the brow and the stair head.
    rail_line(S, [(sx0 + 0.1, gal1 - 0.05), (sx0 + 0.1, gal0 + 0.1), (gx - GATE_W / 2 - 0.1, gal0 + 0.1)], SILL)
    rail_line(S, [(gx + GATE_W / 2 + 0.1, gal0 + 0.1), (sx1 - 0.1, gal0 + 0.1), (sx1 - 0.1, gal1 - 0.05)], SILL)
    rail_line(S, [(sx0 + 0.1, gal1 - 0.05), (gx - 1.2, gal1 - 0.05)], SILL)
    rail_line(S, [(gx + 1.2, gal1 - 0.05), (sx1 - 0.1, gal1 - 0.05)], SILL)
    for s in (-1, 1):                            # stair handrails following the pitch
        xs = gx + s * 1.2
        for (ua, za), (ub, zb) in (((foot_y, quay), (land_y1, quay + (SILL - quay) * 10 / 19)),
                                   ((land_y0, quay + (SILL - quay) * 10 / 19), (gal1, SILL))):
            S.beam((xs, ua, za + 0.95), (xs, ub, zb + 0.95), 0.08, 0.1, TIMBER)
            for yy, zz in ((ua, za), (ub, zb)):
                S.box((xs, yy, zz + 0.5), (0.12, 0.12, 1.0), TIMBER)
    for x in (sx0 + 0.2, gx - 1.45, gx + 1.45, sx1 - 0.2):   # knee braces under the gallery
        knee(S, (x, gal0 + 0.2, SILL - 1.2), (x, gal0 + 1.4, SILL - 0.3))
    bench(S, (sx0 + 0.6, gal1 + 0.6), (sx0 + 0.6, foot_y - 0.6), quay)
    bench(S, (sx1 - 0.6, gal1 + 0.6), (sx1 - 0.6, foot_y - 0.6), quay)
    zr = gable_roof(S, sx0, gal0, sx1, foot_y - 0.2, ze, 0.55, over=(0.9, 0.9, 0.0, 0.9))
    for x in (sx0 + 0.2, gx, sx1 - 0.2):
        tie_truss(S, x, gal0, foot_y - 0.2, ze, zr)
    for x in (gx - 1.0, gx + 1.0):
        lantern(S, x, gal1 - 0.3, ze - 0.55, h=0.3)
        S.beam((x, gal1 - 0.3, ze - 0.25), (x, gal1 - 0.3, ze - 0.2), 0.03, 0.03, IRON)
    # Brow: level, hinged on the gallery's south edge, over the fender gap and 0.9 m onto the ship's deck.
    br = brow(B, gx, face, gx, gy - 0.9, SILL, width=GATE_W)
    # Waiting house on the promenade west of the jetty root: white plaster between dark timber, sliding windows,
    # a door to the jetty side, a bench and lamp in front, kawara roof.
    hx0, hx1, hy0, hy1 = gx - 21.0, gx - 9.0, -122.0, -114.5
    hz = 2.6                                   # promenade level there (H.height ~2.6 at y -122..-115)
    W.prism(F.rect(hx0 - 0.3, hy0 - 0.3, hx1 + 0.3, hy1 + 0.3), hz - 0.3, hz + 0.18, STONE)
    wh = 2.9
    wall(W, (hx0, hy0), (hx1, hy0), hz + 0.18, wh, 0.18, PLASTER, [(1.2, 2.2, 0.0, 2.15, 'door'), (3.0, 6.0, 0.85, 2.2), (7.0, 10.6, 0.85, 2.2)])
    wall(W, (hx1, hy0), (hx1, hy1), hz + 0.18, wh, 0.18, PLASTER, [(1.4, 6.1, 0.85, 2.2)])
    wall(W, (hx1, hy1), (hx0, hy1), hz + 0.18, wh, 0.18, PLASTER, [(1.0, 4.0, 0.85, 2.2), (8.0, 11.0, 0.85, 2.2)])
    wall(W, (hx0, hy1), (hx0, hy0), hz + 0.18, wh, 0.18, PLASTER, [(2.2, 5.3, 0.85, 2.2)])
    W.prism(F.rect(hx0 + 0.1, hy0 + 0.1, hx1 - 0.1, hy1 - 0.1), hz + 0.18, hz + 0.2, PLANK)
    gable_roof(W, hx0, hy0, hx1, hy1, hz + 0.18 + wh, 0.6, over=(0.7, 0.7, 1.1, 0.8))
    bench(W, (hx0 + 3.2, hy0 - 0.7), (hx0 + 5.8, hy0 - 0.7), hz)
    bench(W, (hx0 + 7.4, hy0 - 0.7), (hx0 + 10.0, hy0 - 0.7), hz)
    lantern(W, hx0 + 2.5, hy0 - 0.18, hz + 2.3, h=0.36)
    for xx in (hx0 + 0.9, hx1 - 0.9):         # potted plants either side, as in the concept
        W.lathe((xx, hy0 - 0.8, hz), [(0, 0.22), (0.45, 0.3), (0.5, 0.0)], TERRACOTTA, n=10)
        W.lathe((xx, hy0 - 0.8, hz + 0.45), [(0, 0.3), (0.3, 0.36), (0.6, 0.0)], MOSS, n=10)
    # Timetable board on the promenade at the jetty root, facing the city.
    timetable(T, gx + 6.5, -122.5, 2.58, 0.0)
    walk = {'name': 'hidamari', 'route': [(gx, -121.0, 2.6), (gx, QF + 0.2, quay), (gx, foot_y + 1.0, quay),
                                         (gx, foot_y - 0.05, quay)] +
            [(gx, y, None) for y in (land_y1, land_y0)] + [(gx, gal1, SILL), (gx, gal0 + 0.5, SILL), (gx, face, SILL), (gx, gy - 0.8, SILL)],
            'gate': [gx, gy, SILL], 'stair': {k: v for k, v in st.items() if k != 'treads'}, 'brow': br,
            'anchor': [gx, face, 0.0], 'frame': 'world'}
    return meshes, walk


# ------------------------------------------------------------------ Brinecove (region-local metres)
def brinecove():
    b = SITE['brinecove']['berth']; gx, gy, _ = b['gate']; face = b['face']; deck = b['walk_level_z']
    PW = face + 0.5                   # the pier's west edge (x -244.5); the pier runs x -244.5..-231.5
    meshes = {k: F.Mesh(k) for k in ('FT_BC_Landing', 'FT_BC_Brow', 'FT_BC_Pavilion', 'FT_BC_TicketHut', 'FT_BC_Fenders', 'FT_BC_Props')}
    Lm, B, P, H, Fd, Pr = meshes.values()
    # Boarding landing at sill height on the pier's west edge, a 7-riser stair down to the pier deck to the east.
    lx0, lx1, ly0, ly1 = PW, PW + 3.4, gy - 3.6, gy + 3.6
    # A framed timber stage, closed underneath (nobody walks into the 1.7 m void): a plank deck overhanging a fascia,
    # posts on stone footings, recessed board infill and one diagonal brace per bay, so its faces read as joinery.
    ins, fz = 0.16, SILL - 0.22
    Lm.prism(F.rect(lx0 + ins, ly0 + ins, lx1 - ins, ly1 - ins), deck, fz, TIMBER_DARK)
    Lm.prism(F.rect(lx0, ly0, lx1, ly1), fz, SILL, TIMBER, top=PLANK)
    Lm.prism(F.rect(lx0 + 0.04, ly0 + 0.04, lx1 - 0.04, ly1 - 0.04), deck, deck + 0.18, STONE)    # plinth
    for (ax, ay), (bx, by_) in (((lx0, ly0), (lx1, ly0)), ((lx1, ly0), (lx1, ly1)), ((lx0, ly1), (lx1, ly1)),
                                ((lx0, ly0), (lx0, ly1))):
        L = math.dist((ax, ay), (bx, by_)); n = max(1, round(L / 2.0))
        ox, oy = (0.0, -1.0) if ay == by_ == ly0 else (1.0, 0.0) if ax == bx == lx1 else (0.0, 1.0) if ay == by_ else (-1.0, 0.0)
        tx, ty = (bx - ax) / L, (by_ - ay) / L
        for k in range(int(L / 0.32)):                      # infill boards, proud of the core, behind the posts
            u = (k + 0.5) * L / int(L / 0.32)
            Lm.box((ax + tx * u - ox * (ins - 0.03), ay + ty * u - oy * (ins - 0.03), (deck + 0.18 + fz) / 2),
                   (abs(tx) * 0.26 + abs(ox) * 0.03 + 0.001, abs(ty) * 0.26 + abs(oy) * 0.03 + 0.001, fz - deck - 0.18), TIMBER_DARK)
        for k in range(n + 1):
            u = k * L / n; px, py = ax + tx * u - ox * 0.06, ay + ty * u - oy * 0.06
            post(Lm, px, py, deck, fz, s=0.22, footing=True)
            if k < n:                                          # one brace per bay, alternating
                v = (k + 1) * L / n; qx, qy = ax + tx * v - ox * 0.06, ay + ty * v - oy * 0.06
                lo, hi = (deck + 0.3, fz - 0.08) if k % 2 == 0 else (fz - 0.08, deck + 0.3)
                Lm.beam((px + tx * 0.12, py + ty * 0.12, lo), (qx - tx * 0.12, qy - ty * 0.12, hi), 0.09, 0.12, TIMBER)
        Lm.beam((ax - ox * 0.05, ay - oy * 0.05, fz - 0.08), (bx - ox * 0.05, by_ - oy * 0.05, fz - 0.08), 0.12, 0.18, TIMBER)
    # The stair runs north along the pier's west edge, so the walkway between it and the pavilion stays 2.6 m wide.
    r = (SILL - deck) / 7
    sx_ = (lx0 + lx1) / 2; foot_y = ly1 + 6 * 0.30
    st = solid_stair(Lm, (sx_, foot_y), (0, -1), 2.4, deck, [7], r, tread=0.30)
    rail_line(Lm, [(sx_ - 1.25, ly1 - 0.1), (lx0 + 0.1, ly1 - 0.1), (lx0 + 0.1, gy + GATE_W / 2 + 0.1)], SILL)
    rail_line(Lm, [(lx0 + 0.1, gy - GATE_W / 2 - 0.1), (lx0 + 0.1, ly0 + 0.1), (lx1 - 0.1, ly0 + 0.1), (lx1 - 0.1, ly1 - 0.1),
                   (sx_ + 1.25, ly1 - 0.1)], SILL)
    for s in (-1, 1):
        xx = sx_ + s * 1.27
        Lm.beam((xx, foot_y + 0.1, deck + 0.95), (xx, ly1, SILL + 0.95), 0.08, 0.1, TIMBER)
        Lm.box((xx, foot_y + 0.1, deck + 0.5), (0.12, 0.12, 1.0), TIMBER)
    br = brow(B, lx0, gy, gx - 0.9, gy, SILL, width=GATE_W)
    # Fenders along the pier's west face where the hull lies (y -30..50): black piles and hung tyres.
    for k in range(11):
        yy = -30 + k * 8.0
        Fd.box((PW - 0.25, yy, (deck + 0.3 - 3.0) / 2), (0.36, 0.36, deck + 0.3 + 3.0), BLACK, bevel=0.03)
        for j in (0, 1):
            ty = yy + 2.7 + j * 2.6
            tyre(Fd, (PW - 0.2, ty, 1.9), (-1, 0, 0))
            Fd.beam((PW - 0.15, ty, 2.3), (PW - 0.05, ty, deck - 0.05), 0.04, 0.04, ROPE)
    for yy in (-22.0, 45.0):
        bollard(Fd, PW + 0.6, yy, deck)
        rope_coil(Fd, PW + 1.4, yy + 0.9, deck)
    # Pavilion on the pier beside the landing: six posts on stone footings, a long bench facing the ship, an exposed
    # truss and a kawara gable roof with its ridge along the pier.
    px0, px1, py0, py1 = PW + 6.0, PW + 12.2, gy - 9.0, gy + 3.0
    for x in (px0 + 0.2, px1 - 0.2):
        for y in (py0 + 0.2, (py0 + py1) / 2, py1 - 0.2):
            post(P, x, y, deck, deck + 3.1, s=0.28, footing=True)
    for x in (px0 + 0.2, px1 - 0.2):
        P.beam((x, py0, deck + 2.95), (x, py1, deck + 2.95), 0.2, 0.28, TIMBER)
    for y in (py0 + 0.2, (py0 + py1) / 2, py1 - 0.2):
        for x, dx in ((px0 + 0.2, 1), (px1 - 0.2, -1)):
            knee(P, (x, y, deck + 2.3), (x + dx * 0.7, y, deck + 2.9))
    zr = gable_roof(P, px0, py0, px1, py1, deck + 3.1, 0.6, axis='y', over=(0.8, 0.8, 0.9, 0.9))
    for y in (py0 + 0.2, (py0 + py1) / 2, py1 - 0.2):
        with P._push(F.Matrix(((0, 1, 0, 0), (1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))):
            tie_truss(P, y, px0, px1, deck + 3.1, zr)
    bench(P, (px0 + 0.6, py0 + 1.0), (px0 + 0.6, py1 - 1.0), deck)
    bench(P, (px1 - 0.6, py0 + 1.0), (px1 - 0.6, py1 - 1.0), deck)
    # Ticket hut north of the pavilion: stone base, dark vertical boarding, a counter window facing the walkway,
    # a door to the north, a lantern and a timetable board, kawara roof.
    hx0, hx1, hy0, hy1 = PW + 6.0, PW + 11.0, gy + 6.0, gy + 10.5
    H.prism(F.rect(hx0, hy0, hx1, hy1), deck, deck + 0.85, STONE, bevel=0.04)
    for k in range(6):                           # coursed blocks
        H.box((hx0 - 0.02, hy0 + 0.4 + k * 0.75, deck + 0.42), (0.04, 0.02, 0.8), INK)
    wh = 2.3; z1 = deck + 0.85
    wall(H, (hx0, hy0), (hx1, hy0), z1, wh, 0.16, TIMBER_DARK, [])
    wall(H, (hx1, hy0), (hx1, hy1), z1, wh, 0.16, TIMBER_DARK, [])
    wall(H, (hx1, hy1), (hx0, hy1), z1, wh, 0.16, TIMBER_DARK, [(1.0, 1.95, 0.0, 2.0, 'door')])
    wall(H, (hx0, hy1), (hx0, hy0), z1, wh, 0.16, TIMBER_DARK, [(1.1, 3.4, 0.35, 1.5, 'counter')])
    for k in range(int((hy1 - hy0) / 0.3)):      # vertical boards on the walkway face
        yy = hy0 + 0.15 + k * 0.3
        if not (hy1 - 3.4 - 0.1 < yy < hy1 - 1.1 + 0.1):
            H.box((hx0 - 0.1, yy, z1 + wh / 2), (0.03, 0.05, wh - 0.4), TIMBER)
    gable_roof(H, hx0, hy0, hx1, hy1, z1 + wh, 0.55, axis='y', over=(0.9, 0.6, 0.6, 0.6))
    lantern(H, hx0 - 0.3, hy1 - 0.6, z1 + 1.9, h=0.34)
    H.beam((hx0 - 0.08, hy1 - 0.6, z1 + 2.35), (hx0 - 0.3, hy1 - 0.6, z1 + 2.35), 0.04, 0.04, IRON)
    timetable(H, (hx0 + hx1) / 2, hy1 + 1.4, deck, 180.0, w=1.4, h=1.3)      # facing passengers coming down the pier
    H.prism(F.rect(hx0 - 1.0, hy0 + 0.2, hx0 - 0.3, hy0 + 1.4), deck, deck + 0.45, CRATE)    # flower box
    H.prism(F.rect(hx0 - 0.95, hy0 + 0.25, hx0 - 0.35, hy0 + 1.35), deck + 0.45, deck + 0.62, MOSS)
    # Harbour props as in the concept: crates, a barrel, nets with orange floats and rope coils.
    for x, y, s, yaw in ((PW + 1.0, gy - 8.0, 0.9, 10), (PW + 1.0, gy - 9.1, 0.8, -6), (PW + 1.6, gy - 8.6, 0.7, 30),
                         (PW + 12.0, gy + 13.0, 0.9, 4), (PW + 12.1, gy + 12.0, 0.75, 22)):
        crate(Pr, x, y, deck, s, yaw)
    barrel(Pr, PW + 2.2, gy - 7.0, deck)
    net_pile(Pr, PW + 11.8, gy + 15.6, deck)
    net_pile(Pr, PW + 11.6, gy + 14.6, deck, r=0.6)
    rope_coil(Pr, PW + 0.9, gy - 6.0, deck)
    rope_coil(Pr, PW + 12.0, gy - 10.6, deck, R=0.5)
    walk = {'name': 'brinecove', 'route': [(PW + 4.7, gy + 18.0, deck), (PW + 4.7, foot_y + 1.6, deck), (sx_, foot_y + 0.7, deck),
                                          (sx_, foot_y - 0.05, deck), (sx_, ly1 - 0.3, SILL), (sx_, gy + 0.6, SILL),
                                          (lx0 + 0.5, gy, SILL), (lx0, gy, SILL), (gx - 0.8, gy, SILL)],
            'gate': [gx, gy, SILL], 'stair': {k: v for k, v in st.items() if k != 'treads'}, 'brow': br,
            'anchor': [face, gy, 0.0], 'frame': 'brinecove-local (world = local + (-1500, -120))'}
    return meshes, walk


# ------------------------------------------------------------------ audit, export
def context_ground(name):
    """Audit-only stand-ins for the ground the kit stands on (not exported): Hidamari's quay coping and promenade,
    Brinecove's west pier deck."""
    m = F.Mesh('ctx_' + name)
    if name == 'hidamari':
        gx = SITE['hidamari']['berth']['gate'][0]
        m.box((gx, -126.0, 2.475 - 0.5), (60.0, 3.4, 1.0), STONE)          # coping y -127.7..-124.3, top 2.475
        m.box((gx, -117.2, 2.6 - 0.5), (60.0, 14.2, 1.0), STONE)           # promenade (H.height 2.6-2.8 there)
    else:
        PW = SITE['brinecove']['berth']['face'] + 0.5
        m.box((PW + 6.5, -26.0, 5.25 - 0.5), (13.0, 172.0, 1.0), STONE)    # west pier x -244.5..-231.5, y -112..60
    return m


def walk_audit(objs, walk):
    """March the route every 0.1 m, dropping a ray for the floor: report the largest step, the least headroom
    and the least clear width (at knee and chest height), and any point with no floor."""
    from mathutils.bvhtree import BVHTree
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    verts, polys = [], []
    for o in objs:
        me = o.evaluated_get(deps).to_mesh(); base = len(verts)
        verts += [o.matrix_world @ v.co for v in me.vertices]; polys += [[base + i for i in p.vertices] for p in me.polygons]
    bvh = BVHTree.FromPolygons(verts, polys)
    pts = walk['route']; z = pts[0][2]; rows = []
    worst = {'max_step': 0.0, 'min_headroom': 99.0, 'min_width': 99.0, 'no_floor': 0}
    for (ax, ay, _), (bx, by, _) in zip(pts, pts[1:]):
        L = math.hypot(bx - ax, by - ay); n = max(1, int(L / 0.1)); d = Vector(((bx - ax) / L, (by - ay) / L, 0))
        side = Vector((-d.y, d.x, 0))
        for k in range(n + 1):
            p = Vector((ax + (bx - ax) * k / n, ay + (by - ay) * k / n, z + 0.5))
            hit = bvh.ray_cast(p, Vector((0, 0, -1)), 1.2)
            if hit[0] is None:
                worst['no_floor'] += 1; rows.append({'at': [round(p.x, 2), round(p.y, 2)], 'issue': 'no floor'}); continue
            nz = hit[0].z
            at = [round(p.x, 2), round(p.y, 2), round(nz, 3)]
            step = nz - z; z = nz
            if abs(step) > worst['max_step']:
                worst['max_step'] = abs(step); worst['max_step_at'] = at
            up = bvh.ray_cast(Vector((p.x, p.y, z + 0.05)), Vector((0, 0, 1)), 4.0)
            head = (up[0].z - z) if up[0] is not None else 4.0
            if head < worst['min_headroom']:
                worst['min_headroom'] = head; worst['min_headroom_at'] = at
            for hgt in (0.35, 1.2):
                o = Vector((p.x, p.y, z + hgt)); w = 0.0
                for s in (1, -1):
                    h = bvh.ray_cast(o, side * s, 3.0)
                    w += (h[0] - o).length if h[0] is not None else 3.0
                if w < worst['min_width']:
                    worst['min_width'] = w; worst['min_width_at'] = at + [hgt]
    worst = {k: round(v, 3) if isinstance(v, float) else v for k, v in worst.items()}
    worst['route'] = [[round(c, 3) if c is not None else None for c in p] for p in pts]
    worst['pass'] = worst['max_step'] <= 0.25 and worst['min_headroom'] >= 2.1 and worst['min_width'] >= 0.9 and not worst['no_floor']
    worst['end_z'] = round(z, 3); worst['gate_sill'] = round(SILL, 3)
    worst['issues'] = rows[:20]
    return worst


def export(meshes, anchor, mats, objs_out):
    report = {}
    for name, m in meshes.items():
        m.verts[:] = [(x - anchor[0], y - anchor[1], z - anchor[2]) for x, y, z in m.verts]
        rep = F.check(m)
        obj, names = F.to_object(m, mats)
        obj.location = anchor
        tris = sum(len(f) - 2 for f in m.faces)
        report[name] = {'triangles': tris, 'materials': names, **rep}
        print(f'{name}: {tris} triangles, {rep}')
        bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True); bpy.context.view_layer.objects.active = obj
        loc = tuple(obj.location); obj.location = (0, 0, 0)
        bpy.ops.export_scene.fbx(filepath=str(OUT / 'assets' / f'{name}.fbx'), use_selection=True, apply_unit_scale=True,
                                 apply_scale_options='FBX_SCALE_ALL', axis_forward='-Y', axis_up='Z', object_types={'MESH'},
                                 mesh_smooth_type='EDGE', bake_anim=False, use_custom_props=False)
        obj.location = loc
        objs_out.append(obj)
    return report


def main():
    (OUT / 'assets').mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = F.make_materials()
    manifest = {'units': 'metres, z up; Hidamari in world metres, Brinecove region-local', 'sill_z': SILL, 'terminals': {}}
    walks = {}
    ok = True
    for name, fn in (('hidamari', hidamari), ('brinecove', brinecove)):
        meshes, walk = fn()
        objs = []
        coll = bpy.data.collections.new(name); bpy.context.scene.collection.children.link(coll)
        rep = export(meshes, walk['anchor'], mats, objs)
        for o in objs:
            for c in o.users_collection:
                c.objects.unlink(o)
            coll.objects.link(o)
        ctx = context_ground(name); F.check(ctx); cobj, _ = F.to_object(ctx, mats); coll.objects.link(cobj)
        for c in list(cobj.users_collection):
            if c is not coll:
                c.objects.unlink(cobj)
        cobj.hide_render = True
        audit = walk_audit(objs + [cobj], walk)
        walks[name] = {**walk, 'audit': audit}
        manifest['terminals'][name] = {'anchor': walk['anchor'], 'frame': walk['frame'], 'meshes': rep, 'stair': walk['stair'],
                                       'brow': walk['brow'], 'gate': walk['gate'], 'walk': audit,
                                       'triangles': sum(v['triangles'] for v in rep.values())}
        print(name, 'walk audit', audit)
        bad = [n for n, v in rep.items() if v['open_edges']]
        ok &= not bad and audit['pass']
        if bad:
            print('OPEN EDGES', bad)
    (OUT / 'walk.json').write_text(json.dumps(walks, indent=1) + '\n')
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n')
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'terminals.blend'))
    print('TERMINALS BUILD', 'PASS' if ok else 'FAIL')
    if not ok:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
