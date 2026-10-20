"""Old-school passenger ferry, concept C (ferry_oldschool_c.jpg). Procedural Blender build.

blender --background --factory-startup --threads 3 -P games/yorimichi/assets/vehicles/ferry/build.py
Metres; +X is the bow, z is up and the waterline is z=0. Writes one FBX per mesh, ferry.blend and manifest.json
into build/yorimichi/ferry/. Every part is a closed solid with outward normals (checked before export).
"""
import sys as _sys; from pathlib import Path as _Path; _sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / 'world')); import yori  # noqa: E402,F401
import json
import math
from contextlib import contextmanager

import bpy
from mathutils import Matrix, Vector

OUT = yori.OUT / 'ferry'

# ------------------------------------------------------------------ materials (sRGB, roughness, metallic)
WHITE, BLUE, GOLD, TIMBER, DECK = 'FY_WhitePaint', 'FY_BootTopBlue', 'FY_GoldMoulding', 'FY_VarnishedTimber', 'FY_DeckTimber'
CREAM, BLACK, BRASS, CANVAS, GLASS = 'FY_CreamFunnel', 'FY_Black', 'FY_Brass', 'FY_Canvas', 'FY_Glass'
IRON, BUOY, BOAT, ROPE = 'FY_DarkIron', 'FY_Lifebuoy', 'FY_BoatTimber', 'FY_TarredRope'
MATERIALS = {
    WHITE: ((238, 232, 229), .55, 0.), BLUE: ((46, 84, 158), .5, 0.), GOLD: ((214, 168, 82), .4, .3),
    TIMBER: ((172, 112, 58), .45, 0.), DECK: ((196, 152, 104), .7, 0.), CREAM: ((240, 230, 208), .55, 0.),
    BLACK: ((40, 38, 42), .6, 0.), BRASS: ((206, 164, 78), .35, .55), CANVAS: ((228, 210, 176), .85, 0.),
    GLASS: ((66, 84, 112), .15, 0.), IRON: ((60, 60, 64), .5, .3), BUOY: ((232, 112, 50), .6, 0.),
    BOAT: ((180, 108, 54), .4, 0.), ROPE: ((66, 50, 38), .8, 0.),
}

# ------------------------------------------------------------------ hull lines (fitted to the concept camera)
STERN, STEM = -40.0, 40.0
BEAM = 5.6                    # half-beam of the parallel middle body
PAR_AFT, PAR_FWD = -20.0, 14.0
Z_BOTTOM = -2.6
ZL = 1.0                      # freeboard lift: the concept shows a deep blue boot-top above the water
BOOT = 1.6 + ZL               # top of the blue boot-top band
H1 = 3.9                      # main deck to boat deck
SLAB = 0.42


def clamp(v, a=0.0, b=1.0):
    return max(a, min(b, v))


def deck_z(x):
    """Main deck sheer: low aft, rising to a high raked bow."""
    if x < -8.0:
        return ZL + 5.6 - 0.7 * ((x + 8.0) / 32.0) ** 2
    return ZL + 5.6 + 3.0 * ((x + 8.0) / 48.0) ** 3


def boat_z(x):
    return deck_z(x) + H1


def rope_z(x):
    return deck_z(x) - 2.15 + 0.25 * clamp((x - 10.0) / 30.0)


def stem_x(z):
    top = deck_z(STEM)
    if z >= 0.0:
        return STEM - (top - z) * 0.5
    return STEM - top * 0.5 - (-z / -Z_BOTTOM) ** 1.5 * 5.0


def stern_x(z):
    top = deck_z(STERN)
    if z >= 0.0:
        return STERN + (top - z) * 0.3
    return STERN + top * 0.3 + (-z / -Z_BOTTOM) ** 1.4 * 6.0


def section(z):
    if z >= 0.6:
        return 1.0
    t = (0.6 - z) / (0.6 - Z_BOTTOM)
    return 0.5 + 0.5 * math.sqrt(max(0.0, 1 - t * t))


def half_width(x, z):
    w = BEAM * section(z)
    if x < PAR_AFT:
        u = clamp((x - PAR_AFT) / (stern_x(z) - PAR_AFT))
        w *= math.sqrt(max(0.0, 1 - u * u))
    elif x > PAR_FWD:
        u = clamp((x - PAR_FWD) / (stem_x(z) - PAR_FWD))
        p = 1.8 + 1.4 * clamp(z / deck_z(x))
        w *= 1 - u ** p
    return max(0.07, w)


def deck_half(x):
    return half_width(x, deck_z(x))


def hull_normal(x, z, side=-1):
    """Outward plan normal of the hull side at (x, z); side -1 is starboard."""
    h = 0.05
    dw = (half_width(x + h, z) - half_width(x - h, z)) / (2 * h)
    n = Vector((-dw, side * 1.0, 0.0))
    return n.normalized()


# ------------------------------------------------------------------ layout
HW1 = 3.7                     # forward (timber) deckhouse half-width
HW_MID = 3.3                  # midship deckhouse half-width: a wider walk under the lifeboats
STEP = (13.2, 13.6)           # where the midship house widens into the forward house
T1_AFT, T1_FWD, T1_FRONT = -22.0, 27.0, 4.6
FRONT_P = 2.5                 # superellipse exponent of the rounded house fronts in plan
OVERHANG = 0.26               # boat-deck slab overhang beyond the tier-1 walls
WH_AFT, WH_FWD, WH_HW, WH_H, WH_FRONT = 14.2, 21.4, 2.85, 3.0, 2.2
FUNNEL_X = 2.0
CASING = (-1.6, 5.8, 2.55, 2.0)           # x0, x1, half-width, height
AFT_HOUSE = (-12.6, -9.8, 2.4, 2.45)
BOATS = [-12.0, 9.4]                      # lifeboat centres, both sides
BOAT_Y = 4.86
BOAT_L, BOAT_HB = 9.0, 1.05
FWD_HOUSE_X = 16.6                        # the varnished forward house starts here
MID_BAYS = [-19.4 + 3.4 * k for k in range(10)]
GATES = [(15.2, 2.2)]                     # boarding openings (centre x, width), both sides
FOREMAST_X, AFTMAST_X = 20.4, -20.9
CANOPY = (-38.6, -23.6, 9.5 + ZL)        # aft x, fwd x, roof underside z
STAIR_X = (-23.45, -22.25)


# ------------------------------------------------------------------ mesh core
def signed_area(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))


def offset_loop(pts, d):
    """Offset a CCW loop outward by d (negative insets) with mitred corners."""
    n = len(pts); out = []
    for i in range(n):
        p0, p1, p2 = Vector(pts[i - 1]), Vector(pts[i]), Vector(pts[(i + 1) % n])
        e1, e2 = (p1 - p0).normalized(), (p2 - p1).normalized()
        n1, n2 = Vector((e1.y, -e1.x)), Vector((e2.y, -e2.x))
        m = (n1 + n2) / max(0.25, 1 + n1.dot(n2))
        out.append(tuple(p1 + m * d))
    return out


def resample(pts, step, closed=True):
    out = []
    n = len(pts)
    for i in range(n if closed else n - 1):
        a, b = Vector(pts[i]), Vector(pts[(i + 1) % n])
        k = max(1, math.ceil((b - a).length / step))
        out += [tuple(a.lerp(b, j / k)) for j in range(k)]
    if not closed:
        out.append(tuple(pts[-1]))
    return out


def circle(r, n=12, phase=0.0, sx=1.0, sy=1.0):
    return [(sx * r * math.cos(phase + 2 * math.pi * k / n), sy * r * math.sin(phase + 2 * math.pi * k / n)) for k in range(n)]


def rounded_rect(w, h, r, k=3):
    pts = []
    for cx, cy, a0 in [(w / 2 - r, -h / 2 + r, -90), (w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180)]:
        for j in range(k + 1):
            a = math.radians(a0 + 90 * j / k)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


class Mesh:
    def __init__(self, name):
        self.name = name; self.verts = []; self.faces = []; self.mats = []; self.parts = []
        self.xf = Matrix.Identity(4)

    @contextmanager
    def _push(self, m):
        old = self.xf; self.xf = old @ m
        try:
            yield
        finally:
            self.xf = old

    def at(self, pos=(0, 0, 0), yaw=0.0):
        return self._push(Matrix.Translation(Vector(pos)) @ Matrix.Rotation(math.radians(yaw), 4, 'Z'))

    def mirrored(self, on=True):
        return self._push(Matrix.Scale(-1, 4, (0, 1, 0)) if on else Matrix.Identity(4))

    def frame(self, origin, U, V, A):
        r = Matrix((tuple(U), tuple(V), tuple(A))).transposed().to_4x4()
        return self._push(Matrix.Translation(Vector(origin)) @ r)

    def wall(self, origin, normal):
        """Local frame on a wall: x along the wall, y up, z out of the wall."""
        A = Vector((normal[0], normal[1], 0)).normalized(); V = Vector((0, 0, 1)); U = V.cross(A)
        return self.frame(origin, U, V, A)

    def part(self, verts, faces, mats):
        M = self.xf; flip = M.to_3x3().determinant() < 0
        base = len(self.verts)
        self.verts.extend(tuple(M @ Vector(v)) for v in verts)
        start = len(self.faces)
        for k, f in enumerate(faces):
            f = [base + i for i in f]
            self.faces.append(tuple(reversed(f)) if flip else tuple(f))
            self.mats.append(mats[k] if isinstance(mats, list) else mats)
        self.parts.append((start, len(self.faces)))

    # ---- primitives (all closed)
    def prism(self, outline, z0, z1, side, top=None, bottom=None, bevel=0.0, step=None):
        pts = [tuple(p) for p in outline]
        if step:
            pts = resample(pts, step)
        if signed_area(pts) < 0:
            pts = pts[::-1]
        f0 = z0 if callable(z0) else (lambda x, y, c=z0: c)
        f1 = z1 if callable(z1) else (lambda x, y, c=z1: c)
        if bevel > 0:
            inner = offset_loop(pts, -bevel)
            rings = [(inner, f0, 0.0), (pts, f0, bevel), (pts, f1, -bevel), (inner, f1, 0.0)]
        else:
            rings = [(pts, f0, 0.0), (pts, f1, 0.0)]
        n = len(pts); verts = []
        for ring, fz, dz in rings:
            verts += [(x, y, fz(x, y) + dz) for x, y in ring]
        faces = [list(reversed(range(n))), [(len(rings) - 1) * n + k for k in range(n)]]
        mats = [bottom or (side if isinstance(side, str) else WHITE), top or (side if isinstance(side, str) else WHITE)]
        for r in range(len(rings) - 1):
            for k in range(n):
                k2 = (k + 1) % n
                faces.append([r * n + k, r * n + k2, (r + 1) * n + k2, (r + 1) * n + k])
                if callable(side):
                    mats.append(side((pts[k][0] + pts[k2][0]) / 2, (pts[k][1] + pts[k2][1]) / 2))
                else:
                    mats.append(side)
        self.part(verts, faces, mats)

    def ring_prism(self, outer, inner, z0, z1, mat):
        """Closed band between two CCW loops of equal count (a frame, rim or valance)."""
        n = len(outer); verts = [(*p, z0) for p in outer] + [(*p, z0) for p in inner] + [(*p, z1) for p in outer] + [(*p, z1) for p in inner]
        O0, I0, O1, I1 = 0, n, 2 * n, 3 * n; faces = []
        for k in range(n):
            j = (k + 1) % n
            faces += [[O1 + k, O1 + j, I1 + j, I1 + k], [O0 + k, I0 + k, I0 + j, O0 + j],
                      [O0 + k, O0 + j, O1 + j, O1 + k], [I0 + k, I1 + k, I1 + j, I0 + j]]
        self.part(verts, faces, mat)

    def box(self, c, s, mat, bevel=0.0, top=None):
        x, y, z = c; w, d, h = s
        self.prism(rect(x - w / 2, y - d / 2, x + w / 2, y + d / 2), z - h / 2, z + h / 2, mat, top=top, bevel=bevel)

    def beam(self, a, b, w, d, mat):
        a, b = Vector(a), Vector(b); A = b - a; L = A.length
        if L < 1e-6:
            return
        A.normalize(); ref = Vector((0, 0, 1)) if abs(A.z) < 0.9 else Vector((1, 0, 0))
        U = A.cross(ref).normalized(); V = A.cross(U)
        with self.frame(a, U, V, A):
            self.prism(rect(-w / 2, -d / 2, w / 2, d / 2), 0.0, L, mat)

    def tube(self, path, r, mat, n=6, star=1.0, twist=0.0, phase=0.0, sx=1.0, sy=1.0):
        P = [Vector(p) for p in path]; N = len(P)
        radii = r if isinstance(r, (list, tuple)) else [r] * N
        T = [(P[min(i + 1, N - 1)] - P[max(i - 1, 0)]).normalized() for i in range(N)]
        ref = Vector((0, 0, 1)) if abs(T[0].z) < 0.9 else Vector((1, 0, 0))
        nrm = [(ref - T[0] * ref.dot(T[0])).normalized()]
        for i in range(1, N):
            q = nrm[-1] - T[i] * nrm[-1].dot(T[i])
            nrm.append(q.normalized() if q.length > 1e-6 else nrm[-1])
        verts = []
        for i in range(N):
            B = T[i].cross(nrm[i])
            for k in range(n):
                a = phase + twist * i + 2 * math.pi * k / n; rr = radii[i] * (1.0 if k % 2 == 0 else star)
                verts.append(tuple(P[i] + rr * (sx * math.cos(a) * nrm[i] + sy * math.sin(a) * B)))
        faces = []
        for i in range(N - 1):
            for k in range(n):
                j = (k + 1) % n
                faces.append([i * n + k, i * n + j, (i + 1) * n + j, (i + 1) * n + k])
        faces.append(list(reversed(range(n)))); faces.append([(N - 1) * n + k for k in range(n)])
        self.part(verts, faces, mat)

    def lathe(self, c, profile, mat, n=12, sx=1.0, sy=1.0, phase=0.0):
        """Revolve [(z, r), ...] (bottom to top) around a local z axis through c. r=0 ends close to a point."""
        cx, cy, cz = c; verts = []; rings = []
        for z, r in profile:
            if r <= 0:
                rings.append([len(verts)]); verts.append((cx, cy, cz + z))
            else:
                rings.append(list(range(len(verts), len(verts) + n)))
                verts += [(cx + sx * r * math.cos(phase + 2 * math.pi * k / n), cy + sy * r * math.sin(phase + 2 * math.pi * k / n), cz + z) for k in range(n)]
        faces = []; mats = []
        band = (lambda i: mat[i]) if isinstance(mat, list) else (lambda i: mat)
        for i in range(len(rings) - 1):
            a, b = rings[i], rings[i + 1]
            for k in range(n):
                j = (k + 1) % n
                if len(a) == 1:
                    faces.append([a[0], b[j], b[k]])
                elif len(b) == 1:
                    faces.append([a[k], a[j], b[0]])
                else:
                    faces.append([a[k], a[j], b[j], b[k]])
                mats.append(band(i))
        if len(rings[0]) > 1:
            faces.append(list(reversed(rings[0]))); mats.append(band(0))
        if len(rings[-1]) > 1:
            faces.append(list(rings[-1])); mats.append(band(len(rings) - 2))
        self.part(verts, faces, mats)

    def torus(self, c, R, r, mat, n=16, m=6, mats=None):
        cx, cy, cz = c; verts = []
        for i in range(n):
            a = 2 * math.pi * i / n
            for j in range(m):
                b = 2 * math.pi * j / m; rr = R + r * math.cos(b)
                verts.append((cx + rr * math.cos(a), cy + rr * math.sin(a), cz + r * math.sin(b)))
        faces = []; fm = []
        for i in range(n):
            for j in range(m):
                i2, j2 = (i + 1) % n, (j + 1) % m
                faces.append([i * m + j, i2 * m + j, i2 * m + j2, i * m + j2]); fm.append(mats(i) if mats else mat)
        self.part(verts, faces, fm)


# ------------------------------------------------------------------ helpers
def window(m, w, h, frame_mat, t=0.09, d=0.11, transom=True):
    """Framed window in the current wall frame, centred on the origin, glass set back inside the frame."""
    m.box((0, 0, 0.0), (w, h, 0.08), GLASS)
    m.box((-(w + t) / 2, 0, d / 2), (t, h + 2 * t, d), frame_mat)
    m.box(((w + t) / 2, 0, d / 2), (t, h + 2 * t, d), frame_mat)
    m.box((0, (h + t) / 2, d / 2), (w, t, d), frame_mat)
    m.box((0, -(h + t) / 2 - 0.02, d / 2 + 0.02), (w + 2 * t + 0.12, t + 0.04, d + 0.04), frame_mat)
    m.box((0, 0, d / 2 - 0.02), (t * 0.55, h, d - 0.04), frame_mat)
    if transom:
        m.box((0, h * 0.24, d / 2 - 0.02), (w, t * 0.55, d - 0.04), frame_mat)


def door(m, w, h, mat=TIMBER, frame_mat=WHITE):
    """Door panel standing on the wall-frame origin's y (bottom at y=0)."""
    m.box((0, h / 2, 0.05), (w, h, 0.1), mat, bevel=0.02)
    m.box((0, h * 0.72, 0.12), (w * 0.5, h * 0.25, 0.06), GLASS)
    m.box((-(w / 2 + 0.07), h / 2 + 0.035, 0.08), (0.14, h + 0.07, 0.16), frame_mat)
    m.box(((w / 2 + 0.07), h / 2 + 0.035, 0.08), (0.14, h + 0.07, 0.16), frame_mat)
    m.box((0, h + 0.07, 0.08), (w + 0.28, 0.14, 0.16), frame_mat)
    m.lathe((w * 0.32, h * 0.47, 0.1), [(0, 0.04), (0.08, 0.04), (0.12, 0)], BRASS, n=6)


def loop_points(outline, step):
    pts = resample(outline, step)
    return pts + [pts[0]]


# ------------------------------------------------------------------ hull
NCOL = 76
HULL_ROWS = [
    lambda x: Z_BOTTOM, lambda x: -1.9, lambda x: -0.8, lambda x: 0.4, lambda x: BOOT,
    lambda x: (BOOT + rope_z(x)) / 2, rope_z, lambda x: (rope_z(x) + deck_z(x)) / 2, lambda x: deck_z(x) - 0.14, deck_z,
]
BOOT_ROW = 4


def col_x(s, z):
    a, b = stern_x(z), stem_x(z)
    if s < 0.24:
        return a + (PAR_AFT - a) * (1 - math.cos(s / 0.24 * math.pi / 2))
    if s < 0.6:
        return PAR_AFT + (PAR_FWD - PAR_AFT) * (s - 0.24) / 0.36
    return PAR_FWD + (b - PAR_FWD) * math.sin((s - 0.6) / 0.4 * math.pi / 2)


def hull_point(s, row):
    z = 2.0
    for _ in range(6):
        x = col_x(s, z); z = row(x)
    x = col_x(s, z)
    return x, half_width(x, z), z


def hull(m):
    cols = [i / NCOL for i in range(NCOL + 1)]
    grid = [[hull_point(s, row) for row in HULL_ROWS] for s in cols]
    R = len(HULL_ROWS); C = len(cols)
    verts = []
    for side in (-1, 1):
        for i in range(C):
            for j in range(R):
                x, w, z = grid[i][j]; verts.append((x, side * w, z))
    S = lambda i, j: i * R + j
    P = lambda i, j: C * R + i * R + j
    faces = []; mats = []
    band = lambda j: BLUE if j < BOOT_ROW else WHITE
    for i in range(C - 1):
        for j in range(R - 1):
            faces.append([S(i, j), S(i + 1, j), S(i + 1, j + 1), S(i, j + 1)]); mats.append(band(j))
            faces.append([P(i, j), P(i, j + 1), P(i + 1, j + 1), P(i + 1, j)]); mats.append(band(j))
        t = R - 1
        faces.append([S(i, t), S(i + 1, t), P(i + 1, t), P(i, t)]); mats.append(DECK)
        faces.append([S(i, 0), P(i, 0), P(i + 1, 0), S(i + 1, 0)]); mats.append(BLUE)
    for j in range(R - 1):
        faces.append([S(0, j), S(0, j + 1), P(0, j + 1), P(0, j)]); mats.append(band(j))
        faces.append([S(C - 1, j), P(C - 1, j), P(C - 1, j + 1), S(C - 1, j + 1)]); mats.append(band(j))
    m.part(verts, faces, mats)

    # Rounded covering board along the deck edge, both sides.
    for side in (-1, 1):
        edge = [(x, side * max(0.0, w - 0.05), z + 0.03) for x, w, z in (g[R - 1] for g in grid)]
        m.tube(edge, 0.1, WHITE, n=6)

    # Gold rope moulding: one twisted rope from bow to bow around the stern.
    rope = [g[6] for g in grid]
    end = max(i for i, (x, w, z) in enumerate(rope) if x < stem_x(z) - 0.55)
    loop = [(x, -w, z) for x, w, z in rope[end::-1]] + [(x, w, z) for x, w, z in rope[1:end + 1]]
    loop = resample(loop, 0.4, closed=False)
    path = []
    for i, p in enumerate(loop):
        a, b = Vector(loop[max(0, i - 1)]), Vector(loop[min(len(loop) - 1, i + 1)])
        t = (b - a); t.z = 0; t.normalize()
        nrm = Vector((-t.y, t.x, 0))
        path.append(tuple(Vector(p) + nrm * 0.07))
    m.tube(path, 0.15, GOLD, n=8, star=0.9, twist=0.35)
    for side in (-1, 1):
        x = loop[0][0] + 0.2; z = rope_z(x); w = half_width(x, z)
        n = hull_normal(x, z, side)
        with m.wall((x, side * w, z), n):
            m.lathe((0, 0, -0.08), [(0, 0.46), (0.14, 0.46), (0.2, 0.36), (0.26, 0.22), (0.28, 0)], BRASS, n=12)
            m.torus((0, 0, 0.16), 0.36, 0.06, BRASS, n=12, m=5)

    # Portholes: rounded rectangles aft, round forward.
    rects = [-37.2, -34.7, -32.2, -29.7, -27.2, -24.7, -22.2, -19.7, -17.2, -14.7, -12.2, -9.7]
    rounds = [-6.4, -3.5, -0.6, 2.3, 5.2, 8.0, 10.8, 13.5, 16.2, 19.0, 22.0, 25.2, 28.8, 32.6]
    for side in (-1, 1):
        for x in rects + rounds:
            z = (deck_z(x) + rope_z(x)) / 2 - 0.05
            w = half_width(x, z); n = hull_normal(x, z, side)
            with m.wall((x, side * w, z), n):
                if x in rects:
                    o = rounded_rect(0.42, 0.66, 0.16)
                    m.prism(o, -0.12, 0.03, GLASS)
                    m.ring_prism(offset_loop(o, 0.1), offset_loop(o, -0.02), -0.06, 0.08, WHITE)
                else:
                    m.prism(circle(0.31, 12), -0.12, 0.03, GLASS)
                    m.ring_prism(circle(0.42, 12), circle(0.29, 12), -0.06, 0.08, WHITE)
        # Anchor pocket with a bronze anchor, raked with the stem.
        x, z = 36.4, 4.4 + ZL
        w = half_width(x, z); n = hull_normal(x, z, side)
        with m.wall((x, side * w, z), n), m._push(Matrix.Scale(1.4, 4)):
            o = [(-0.62, -0.55), (0.42, -0.55), (0.72, 0.55), (-0.32, 0.55)]
            m.prism(o, -0.15, 0.02, IRON)
            m.ring_prism(offset_loop(o, 0.1), offset_loop(o, -0.01), -0.08, 0.07, WHITE)
            m.beam((0.0, -0.32, 0.06), (0.14, 0.34, 0.06), 0.09, 0.07, BRASS)
            m.beam((-0.14, 0.24, 0.07), (0.38, 0.32, 0.07), 0.07, 0.07, BRASS)
            m.beam((0.0, -0.32, 0.06), (-0.26, -0.12, 0.06), 0.08, 0.07, BRASS)
            m.beam((0.0, -0.32, 0.06), (0.24, -0.2, 0.06), 0.08, 0.07, BRASS)

    # Boarding openings: brass landing plates at the gates in the main-deck rail.
    for x, width in GATES:
        for side in (-1, 1):
            w = deck_half(x)
            m.box((x, side * (w - 0.35), deck_z(x) + 0.02), (width, 0.6, 0.06), BRASS)


# ------------------------------------------------------------------ superstructure
def superellipse_front(xc, rx, hw, n, p=FRONT_P):
    """Rounded front in plan from (xc, -hw) round the bow-facing end to (xc, hw), endpoints excluded."""
    out = []
    for k in range(1, n):
        a = -math.pi / 2 + math.pi * k / n; c, s = math.cos(a), math.sin(a)
        out.append((xc + rx * abs(c) ** (2 / p), hw * math.copysign(abs(s) ** (2 / p), s)))
    return out


def t1_half(x):
    """Half-width of the tier-1 deckhouse walls at x (midship house, then the wider forward house)."""
    return HW_MID + (HW1 - HW_MID) * clamp((x - STEP[0]) / (STEP[1] - STEP[0]))


def t1_outline(grow=0.0, n=28):
    hm, hf = HW_MID + grow, HW1 + grow; xa = T1_AFT - grow; xc = T1_FWD - T1_FRONT; rx = T1_FRONT + grow
    s0, s1 = STEP[0] - grow * 0.4, STEP[1] - grow * 0.4
    starboard = [(xa, -hm), (s0, -hm), (s1, -hf), (xc, -hf)]
    port = [(x, -y) for x, y in reversed(starboard)]
    return starboard + superellipse_front(xc, rx, hf, n) + port


def slab_outline():
    """Boat deck: the tier-1 roof with a narrow white overhang that follows the rounded front."""
    return t1_outline(OVERHANG)


def slab_half(x):
    return t1_half(x) + OVERHANG


def wh_outline(grow=0.0, n=16):
    """Wheelhouse: shorter and narrower than the house below, set well back, with a rounded front."""
    hw = WH_HW + grow; xa = WH_AFT - grow; xc = WH_FWD - WH_FRONT; rx = WH_FRONT + grow
    return [(xa, -hw), (xc, -hw)] + superellipse_front(xc, rx, hw, n, p=2.8) + [(xc, hw), (xa, hw)]


def outline_walk(outline, step, corner=35.0, clear=0.5):
    """Evenly spaced points along a CCW outline, with outward normals, kept clear of sharp corners."""
    pts = [Vector(p) for p in outline]; n = len(pts); sharp = []
    for i in range(n):
        e1, e2 = pts[i] - pts[i - 1], pts[(i + 1) % n] - pts[i]
        if e1.length > 1e-6 and e2.length > 1e-6 and math.degrees(e1.angle(e2)) > corner:
            sharp.append(pts[i])
    segs = []; total = 0.0
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]; L = (b - a).length
        if L > 1e-6:
            segs.append((a, b, L, total)); total += L
    out = []; s = step / 2
    while s < total:
        for a, b, L, s0 in segs:
            if s0 <= s < s0 + L:
                p = a.lerp(b, (s - s0) / L); e = (b - a) / L
                if all((p - c).length > clear for c in sharp):
                    out.append((p.x, p.y, e.y, -e.x))
                break
        s += step
    return out


def superstructure(m):
    sheer0 = lambda x, y: deck_z(x) - 0.3
    t1_top = lambda x, y: boat_z(x) - SLAB + 0.02
    wall_mat = lambda x, y: TIMBER if x > FWD_HOUSE_X else WHITE
    m.prism(t1_outline(), sheer0, t1_top, wall_mat, top=WHITE, bottom=WHITE, bevel=0.08, step=2.0)
    # Boat deck: a thick white slab whose fascia follows the rounded front.
    m.prism(slab_outline(), lambda x, y: boat_z(x) - SLAB, lambda x, y: boat_z(x), WHITE, top=DECK, bottom=WHITE, bevel=0.1, step=1.0)

    # Midship house: white walls; each bay is a raised white portal round a varnished panel with two big
    # white-framed windows, and white pilasters stand between the bays.
    wall_h = H1 - SLAB + 0.3
    for side in (-1, 1):
        with m.mirrored(side > 0):
            for k, x in enumerate(MID_BAYS):
                z0 = deck_z(x) - 0.3
                with m.wall((x, -HW_MID, z0), (0, -1)):
                    pw, ph, f = 2.5, 2.95, 0.22
                    m.box((0, 0.3 + ph / 2, 0.025), (pw - 2 * f + 0.02, ph - f, 0.05), TIMBER)
                    m.box((-(pw - f) / 2, 0.3 + ph / 2, 0.08), (f, ph, 0.16), WHITE, bevel=0.03)
                    m.box(((pw - f) / 2, 0.3 + ph / 2, 0.08), (f, ph, 0.16), WHITE, bevel=0.03)
                    m.box((0, 0.3 + ph - f / 2, 0.09), (pw + 0.08, f, 0.18), WHITE, bevel=0.03)
                    m.box((0, 0.36, 0.09), (pw + 0.08, 0.14, 0.18), WHITE, bevel=0.03)
                    for u in (-0.5, 0.5):
                        m.box((u, 0.95, 0.07), (0.7, 0.72, 0.04), TIMBER, bevel=0.02)
                        with m.at((u, 2.1, 0.06)):
                            window(m, 0.62, 1.4, TIMBER, t=0.09, d=0.1)
                    if k < len(MID_BAYS) - 1:
                        m.box(((MID_BAYS[k + 1] - x) / 2, wall_h / 2, 0.05), (0.42, wall_h - 0.1, 0.1), WHITE, bevel=0.03)
            # Boarding door in its white portal, facing the gate.
            x = GATES[0][0]; z0 = deck_z(x)
            with m.wall((x, -HW1, z0), (0, -1)):
                m.box((0, 1.5, 0.12), (2.2, 3.0, 0.26), WHITE, bevel=0.04)
                with m.at((0, 0.02, 0.24)):
                    door(m, 1.05, 2.2, TIMBER, WHITE)
            # White pilaster where the forward timber house begins.
            x = FWD_HOUSE_X
            m.box((x, -HW1 - 0.06, deck_z(x) - 0.3 + wall_h / 2), (0.5, 0.2, wall_h), WHITE, bevel=0.04)
    # Forward timber house: a continuous band of tall framed windows wrapping round the rounded front, varnished
    # pilasters between them, an oval window on each side.
    for x, y, nx, ny in outline_walk(t1_outline(), 1.22, corner=60.0, clear=0.3):
        if x < FWD_HOUSE_X + 0.75:
            continue
        z0 = deck_z(x) - 0.3
        with m.wall((x, y, z0), (nx, ny)):
            m.box((0, 0.95, 0.04), (0.92, 0.72, 0.05), TIMBER, bevel=0.02)
            m.box((0.61, wall_h / 2 + 0.1, 0.05), (0.2, wall_h - 0.4, 0.1), TIMBER, bevel=0.02)
            if abs(x - 19.2) < 0.61 and abs(ny) > 0.9:
                with m.at((0, 2.25, 0)), m._push(Matrix.Diagonal((0.8, 1.0, 1.0, 1.0))):
                    m.prism(circle(0.62, 16), -0.02, 0.07, GLASS)
                    m.ring_prism(circle(0.76, 16), circle(0.6, 16), 0.0, 0.14, TIMBER)
            else:
                with m.at((0, 2.28, 0.03)):
                    window(m, 0.84, 1.78, TIMBER, transom=False)

    # Tier 2: a shorter, narrower, set-back wheelhouse with a rounded front and a band of tall windows, under a white
    # roof slab whose railed top is the monkey island.
    m.prism(wh_outline(), lambda x, y: boat_z(x) - 0.12, lambda x, y: boat_z(x) + WH_H, TIMBER, top=WHITE, bevel=0.07, step=1.0)
    m.prism(wh_outline(0.3), lambda x, y: boat_z(x) + WH_H - 0.04, lambda x, y: boat_z(x) + WH_H + 0.3, WHITE, top=DECK, bevel=0.08, step=1.0)
    for x, y, nx, ny in outline_walk(wh_outline(), 1.0, corner=60.0, clear=0.3):
        if nx < -0.9:
            continue
        z0 = boat_z(x)
        with m.wall((x, y, z0), (nx, ny)):
            m.box((0, 0.5, 0.03), (0.78, 0.62, 0.05), TIMBER, bevel=0.02)
            m.box((0.5, WH_H / 2, 0.05), (0.16, WH_H - 0.2, 0.1), TIMBER, bevel=0.02)
            with m.at((0, 1.0 + 0.78, 0.03)):
                window(m, 0.7, 1.5, TIMBER, transom=False)
    with m.wall((WH_AFT, 0, boat_z(WH_AFT)), (-1, 0)):
        door(m, 0.95, 2.15, TIMBER, TIMBER)
    # Funnel casing and the aft timber house.
    x0, x1, hw, h = CASING
    m.prism(rect(x0, -hw, x1, hw), lambda x, y: boat_z(x) - 0.1, lambda x, y: boat_z(x) + h, WHITE, bevel=0.1, step=2.0)
    for side in (-1, 1):
        with m.mirrored(side > 0):
            for x in (x0 + 1.4, x1 - 1.6):
                with m.wall((x, -hw, boat_z(x)), (0, -1)):
                    door(m, 0.85, 1.75, TIMBER, WHITE)
    x0, x1, hw, h = AFT_HOUSE
    m.prism(rect(x0, -hw, x1, hw), lambda x, y: boat_z(x) - 0.1, lambda x, y: boat_z(x) + h, TIMBER, top=WHITE, bevel=0.07, step=2.0)
    m.prism(offset_loop(rect(x0, -hw, x1, hw), 0.25), lambda x, y: boat_z(x) + h - 0.04, lambda x, y: boat_z(x) + h + 0.22, WHITE, top=DECK, bevel=0.05, step=2.0)
    for x, y, nx, ny in outline_walk(rect(x0, -hw, x1, hw), 1.1):
        with m.wall((x, y, boat_z(x)), (nx, ny)):
            with m.at((0, 1.0 + 0.6, 0.03)):
                window(m, 0.62, 1.2, TIMBER, t=0.08)

    # Stern canopy over the open aft deck: canvas roof with a valance, brass posts.
    xa, xf, zc = CANOPY
    xs = [xa + (xf - xa) * k / 10 for k in range(11)]
    outline = [(x, -(deck_half(x) - 0.55)) for x in xs] + [(x, deck_half(x) - 0.55) for x in reversed(xs)]
    m.prism(outline, zc, zc + 0.16, CANVAS, bevel=0.04)
    m.prism(offset_loop(outline, -0.4), zc + 0.12, zc + 0.3, CANVAS, bevel=0.06)
    m.ring_prism(offset_loop(outline, 0.04), offset_loop(outline, -0.03), zc - 0.28, zc + 0.02, CANVAS)

    # Stair from the aft deck up to the boat deck, against the deckhouse's aft face.
    sx0, sx1 = STAIR_X
    y_bot, y_top = 2.9, -2.75
    zb, zt = deck_z((sx0 + sx1) / 2), boat_z(T1_AFT)
    steps = 16
    for k in range(steps):
        t = (k + 1) / steps
        y = y_bot + (y_top - y_bot) * t; z = zb + (zt - zb) * t
        m.box(((sx0 + sx1) / 2, y + 0.06, z - 0.04), (sx1 - sx0, 0.42, 0.08), DECK)
    for x in (sx0 - 0.04, sx1 + 0.04):
        m.beam((x, y_bot + 0.35, zb - 0.1), (x, y_top - 0.25, zt - 0.1), 0.08, 0.32, WHITE)
    m.box(((sx0 + sx1) / 2, y_top - 0.55, zt - 0.06), (sx1 - sx0 + 0.16, 0.9, 0.12), DECK)
    # Ladder up the wheelhouse's aft face to the monkey island.
    zb2 = boat_z(WH_AFT)
    lx = WH_AFT - 0.46
    for y in (1.25, 1.85):
        m.box((lx, y, zb2 + (WH_H + 1.25) / 2), (0.08, 0.08, WH_H + 1.25), WHITE)
    for k in range(11):
        m.box((lx, 1.55, zb2 + 0.3 + k * 0.32), (0.07, 0.6, 0.06), BRASS)
    m.box(((lx + WH_AFT) / 2, 1.55, zb2 + WH_H - 0.5), (WH_AFT - lx + 0.04, 0.68, 0.08), WHITE)


# ------------------------------------------------------------------ funnel
def funnel(m):
    """Fat, faceted, slightly raked oval funnel: a cream barrel tapering to a black top band, and a smaller black
    inner stack standing above the band, as painted."""
    x = FUNNEL_X; base = boat_z(x) + CASING[3] - 0.25
    top = 18.6 + ZL; black = 16.4 + ZL; rake = -0.5
    def centre(z):
        return x + rake * (z - base) / (top - base)
    inner_top = top + 0.75
    prof = [(base, 1.0, CREAM), (base + 1.2, 0.975, CREAM), (black, 0.89, CREAM), (black, 0.91, BLACK), (top, 0.89, BLACK),
            (top, 0.66, BLACK), (inner_top, 0.64, BLACK), (inner_top, 0.5, BLACK)]
    n = 12; a, b = 2.75, 2.2; verts = []; rings = []
    for z, s, _ in prof:
        rings.append(list(range(len(verts), len(verts) + n)))
        verts += [(centre(z) + a * s * math.cos(2 * math.pi * (k + 0.5) / n), b * s * math.sin(2 * math.pi * (k + 0.5) / n), z) for k in range(n)]
    bottom = rings[-1]; cz = inner_top - 0.5
    inner = list(range(len(verts), len(verts) + n))
    verts += [(centre(cz) + a * 0.5 * math.cos(2 * math.pi * (k + 0.5) / n), b * 0.5 * math.sin(2 * math.pi * (k + 0.5) / n), cz) for k in range(n)]
    faces = []; fm = []
    for i in range(len(rings) - 1):
        r0, r1 = rings[i], rings[i + 1]
        for k in range(n):
            j = (k + 1) % n
            faces.append([r0[k], r0[j], r1[j], r1[k]]); fm.append(prof[i + 1][2] if prof[i][2] != prof[i + 1][2] else prof[i][2])
    for k in range(n):
        j = (k + 1) % n
        faces.append([bottom[k], bottom[j], inner[j], inner[k]]); fm.append(BLACK)
    faces.append(list(reversed(rings[0]))); fm.append(CREAM)
    faces.append(list(inner)); fm.append(BLACK)
    m.part(verts, faces, fm)
    # Steam whistle and pipe on the funnel's front.
    fz = 15.4 + ZL; fx = centre(fz) + a * 0.92
    m.lathe((fx + 0.25, 0, fz), [(0, 0.12), (0.7, 0.12), (0.75, 0.2), (1.0, 0.2), (1.1, 0)], BRASS, n=8)
    m.beam((fx - 0.05, 0, fz + 0.2), (fx + 0.25, 0, fz + 0.2), 0.12, 0.12, BRASS)
    m.lathe((fx + 0.25, 0, base), [(0, 0.09), (fz - base, 0.09)], CREAM, n=6)


# ------------------------------------------------------------------ lifeboats and davits
BOAT_D, BOAT_SHEER = 1.55, 0.26          # lifeboat depth amidships and rise of the gunwale at the ends


def boat_half(t):
    return max(0.05, BOAT_HB * (1 - abs(t) ** 2.2) ** 0.62)


def boat_gunwale(t):
    return BOAT_D + BOAT_SHEER * t * t


def lifeboat(m, L=BOAT_L):
    """Clinker-built double-ended boat, keel at z=0: varnished strakes, a dark varnished gunwale, a beige cover."""
    stations = 21; NS = 5
    rings = []
    for i in range(stations):
        t = -1 + 2 * i / (stations - 1); x = t * L / 2; w = boat_half(t); g = boat_gunwale(t); k = 0.16 * t ** 4 * BOAT_D
        lap = 0.045 * min(1.0, w / 0.35)
        def p(u):
            return (w * math.sin(u * math.pi / 2) ** 0.75, k + (g - k) * (1 - math.cos(u * math.pi / 2)) ** 1.1)
        side = []
        for j in range(NS):
            u0, u1 = j / NS, (j + 1) / NS
            y0, z0 = p(u0); y1, z1 = p(u1)
            if j:   # proud lower edge of the strake: the clinker lap
                ty, tz = y1 - y0, z1 - z0; L2 = math.hypot(ty, tz) or 1.0
                side.append((y0 + lap * tz / L2, z0 - lap * ty / L2))
            side.append((y1, z1))
        rub = [(w + 0.07, g - 0.15), (w + 0.07, g + 0.03), (max(0.02, w - 0.06), g + 0.06)]
        right = side + rub; rseg = [BOAT] * len(side) + [TIMBER] * len(rub); N = len(right)
        ring = [(-y, z) for y, z in reversed(right)] + [(0.0, k - 0.14)] + right
        rings.append([(x, y, z) for y, z in ring])
        seg_mat = [rseg[N - 1 - q] for q in range(N)] + rseg + [TIMBER]
    loft(m, rings, lambda q: seg_mat[q])
    # Cover: a loaf of beige canvas laced over the gunwale, flat on top, rounded down at the ends.
    cov = []
    for i in range(stations - 2):
        t = -0.94 + 1.88 * i / (stations - 3); x = t * L / 2; w = boat_half(t) + 0.06; g = boat_gunwale(t)
        H = 0.66 * (1 - 0.55 * t ** 6) + 0.04
        arch = [(w, g - 0.18), (w + 0.02, g + 0.06)]
        for a in [math.pi * q / 10 for q in range(1, 10)]:
            c, s_ = math.cos(a), math.sin(a)
            arch.append((w * math.copysign(abs(c) ** (2 / 3.2), c), g + 0.06 + H * abs(s_) ** (2 / 3.2)))
        arch += [(-w - 0.02, g + 0.06), (-w, g - 0.18)]
        cov.append([(x, y, z) for y, z in arch])
    loft(m, cov, CANVAS)


def loft(m, rings, mat):
    n = len(rings[0]); verts = [p for r in rings for p in r]; faces = []; mats = []
    for i in range(len(rings) - 1):
        for k in range(n):
            j = (k + 1) % n
            faces.append([i * n + k, i * n + j, (i + 1) * n + j, (i + 1) * n + k]); mats.append(mat(k) if callable(mat) else mat)
    faces.append(list(reversed(range(n)))); faces.append([(len(rings) - 1) * n + k for k in range(n)])
    end = mat(0) if callable(mat) else mat
    m.part(verts, faces, mats + [end, end])


def davit_path(x, yb, zb, side=-1):
    """Curved (crook) davit arm from the boat-deck edge, over the top and out above the boat's centreline."""
    R = (BOAT_Y - yb) / (1 - math.cos(math.radians(150))); cz = zb + 1.45; oc = yb + R
    pts = [(x, side * yb, zb - 0.05), (x, side * yb, zb + 0.7), (x, side * yb, cz)]
    for k in range(1, 11):
        f = math.radians(150 * k / 10)
        pts.append((x, side * (oc - R * math.cos(f)), cz + R * math.sin(f)))
    return pts, (x, side * oc, cz + R)


def lifeboats(m):
    L = BOAT_L
    for side in (-1, 1):
        with m.mirrored(side > 0):
            for xc in BOATS:
                keel = boat_z(xc) - 0.25 - BOAT_D
                with m.at((xc, -BOAT_Y, keel)):
                    lifeboat(m, L)
                for dx in (-L / 2 + 0.15, L / 2 - 0.15):
                    x = xc + dx; zb = boat_z(x); yb = slab_half(x) - 0.2
                    pts, crown = davit_path(x, yb, zb)
                    m.tube(pts, [0.21 - 0.08 * i / (len(pts) - 1) for i in range(len(pts))], GOLD, n=8, sx=0.7, sy=1.35)
                    m.box((x, -yb, zb + 0.06), (0.62, 0.5, 0.16), GOLD, bevel=0.05)
                    m.lathe((crown[0], crown[1], crown[2] + 0.02), [(0, 0.1), (0.12, 0.19), (0.3, 0.17), (0.4, 0.06), (0.45, 0)], GOLD, n=8)
                    tip = Vector(pts[-1]); t = dx / (L / 2)
                    m.beam(tip - Vector((0, 0, 0.1)), (x - 0.25 * math.copysign(1, dx), -BOAT_Y, keel + boat_gunwale(t) + 0.15), 0.05, 0.05, BLACK)


# ------------------------------------------------------------------ rails
RAIL_H = 1.05


def even(pts, step):
    """Resample a polyline at an even arc-length spacing close to step, keeping both ends."""
    P = [Vector(p) for p in pts]; cum = [0.0]
    for a, b in zip(P[:-1], P[1:]):
        cum.append(cum[-1] + (b - a).length)
    total = cum[-1]; k = max(1, round(total / step)); out = []; j = 0
    for i in range(k + 1):
        s = total * i / k
        while j < len(P) - 2 and cum[j + 1] < s:
            j += 1
        seg = cum[j + 1] - cum[j]
        out.append(tuple(P[j].lerp(P[j + 1], 0 if seg < 1e-9 else (s - cum[j]) / seg)))
    return out


def rail_run(m, pts, h=RAIL_H, spacing=1.25, cap=TIMBER, post=WHITE):
    """White stanchions, two white rails and a varnished cap rail along a polyline of deck points."""
    if len(pts) < 2:
        return
    for p in even(pts, spacing):
        m.box((p[0], p[1], p[2] + (h - 0.04) / 2 - 0.03), (0.065, 0.065, h - 0.02), post)
    path = even(pts, 0.6)
    q = math.pi / 4; c = math.sqrt(2)
    for z in (0.36, 0.7):
        m.tube([(x, y, zz + z) for x, y, zz in path], 1.0, post, n=4, phase=q, sx=0.02 * c, sy=0.02 * c)
    m.tube([(x, y, zz + h) for x, y, zz in path], 1.0, cap, n=4, phase=q, sx=0.038 * c, sy=0.066 * c)


def split_loop(loop, gaps):
    """Split a polyline wherever a gap(x0, x1, side) covers a segment."""
    runs = [[]]
    for p in loop:
        inside = any(x0 <= p[0] <= x1 and (p[1] * side > 0) for x0, x1, side in gaps)
        if inside:
            if runs[-1]:
                runs.append([])
        else:
            runs[-1].append(p)
    return [r for r in runs if len(r) > 1]


def rails(m):
    # Main deck: one loop round the hull, open at the boarding gates.
    s_pts = []
    for i in range(0, 241):
        x = STERN + 0.15 + (STEM - 0.4 - STERN - 0.15) * i / 240
        w = max(0.0, deck_half(x) - 0.2)
        s_pts.append((x, -w, deck_z(x)))
    loop = s_pts + [(x, -y, z) for x, y, z in reversed(s_pts)]
    loop = resample(loop, 0.25, closed=False)
    gaps = []
    for x, width in GATES:
        for side in (-1, 1):
            gaps.append((x - width / 2, x + width / 2, side))
    for run in split_loop(loop, gaps):
        rail_run(m, run)
    for x, width in GATES:
        for side in (-1, 1):
            for gx in (x - width / 2 - 0.05, x + width / 2 + 0.05):
                y = side * (deck_half(gx) - 0.2)
                m.lathe((gx, y, deck_z(gx) - 0.05), [(0, 0.09), (RAIL_H + 0.1, 0.07), (RAIL_H + 0.16, 0.11), (RAIL_H + 0.3, 0.09), (RAIL_H + 0.38, 0)], BRASS, n=8)
    # Boat deck perimeter, open at the stair head.
    so = offset_loop(slab_outline(), -0.14)
    loop = [(x, y, boat_z(x)) for x, y in resample(so, 0.25)]
    loop = loop + [loop[0]]
    sx0, sx1 = STAIR_X
    gap = [(T1_AFT - 1.0, T1_AFT + 0.3, -1)]
    runs = [[]]
    for p in loop:
        if p[0] < T1_AFT + 0.0 and -3.75 < p[1] < -1.95:
            if runs[-1]:
                runs.append([])
        else:
            runs[-1].append(p)
    for run in runs:
        rail_run(m, run)
    # Monkey island and the aft house roof.
    loop = [(x, y, boat_z(x) + WH_H + 0.3) for x, y in resample(offset_loop(wh_outline(0.3), -0.14), 0.25)]
    loop = [p for p in loop + [loop[0]]]
    runs = [[]]
    for p in loop:
        if p[0] < WH_AFT + 0.0 and 1.1 < p[1] < 2.0:
            if runs[-1]:
                runs.append([])
        else:
            runs[-1].append(p)
    for run in runs:
        rail_run(m, run, h=0.95, cap=BRASS, post=BRASS)
    x0, x1, hw, h = AFT_HOUSE
    loop = [(x, y, boat_z(x) + h + 0.22) for x, y in resample(offset_loop(rect(x0, -hw, x1, hw), 0.12), 0.25)]
    rail_run(m, loop + [loop[0]], h=0.9)
    # Stair handrails.
    sx0, sx1 = STAIR_X
    zb, zt = deck_z((sx0 + sx1) / 2), boat_z(T1_AFT)
    for x in (sx0 - 0.04,):
        m.beam((x, 2.9, zb + 1.0), (x, -2.75, zt + 1.0), 0.12, 0.07, TIMBER)
        for t in (0.0, 0.33, 0.66, 1.0):
            y = 2.9 + (-2.75 - 2.9) * t; z = zb + (zt - zb) * t
            m.box((x, y, z + 0.5), (0.065, 0.065, 1.0), WHITE)


# ------------------------------------------------------------------ masts and rigging
def masts(m):
    zb = boat_z(FOREMAST_X) - 0.1; top = 22.4 + ZL; rake = -0.06
    mx = lambda z: FOREMAST_X + rake * (z - zb)
    pts = [(mx(z), 0, z) for z in [zb + (top - zb) * k / 8 for k in range(9)]]
    m.tube(pts, [0.3 - 0.15 * k / 8 for k in range(9)], TIMBER, n=8)
    xtree, plat = top - 0.45, 19.2 + ZL           # masthead crosstree; lamp platform with the lower shroud band
    for z in (zb + WH_H + 0.6, 17.0 + ZL, plat - 0.12, xtree - 0.12):
        r = 0.3 - 0.15 * (z - zb) / (top - zb) + 0.035
        m.lathe((mx(z), 0, z - 0.1), [(0, r), (0.2, r)], BRASS, n=8)
    m.lathe((mx(top), 0, top - 0.05), [(0, 0.15), (0.15, 0.2), (0.32, 0.17), (0.45, 0.06), (0.62, 0.0)], BRASS, n=8)
    # Short crosstree under the truck, and the lamp platform bracketed forward of the mast.
    m.beam((mx(xtree), -0.5, xtree), (mx(xtree), 0.5, xtree), 0.12, 0.12, TIMBER)
    m.beam((mx(plat) - 0.15, -0.38, plat), (mx(plat) - 0.15, 0.38, plat), 0.14, 0.14, TIMBER)
    m.box((mx(plat) + 0.5, 0, plat + 0.02), (1.1, 0.42, 0.1), TIMBER)
    lx = mx(plat) + 0.82
    m.lathe((lx, 0, plat + 0.1), [(0, 0.2), (0.08, 0.2), (0.12, 0.15), (0.5, 0.17), (0.56, 0.22), (0.62, 0.22)], [BRASS, BRASS, GOLD, BRASS, BRASS], n=8)
    m.lathe((lx, 0, plat + 0.6), [(0, 0.24), (0.1, 0.24), (0.32, 0.08), (0.42, 0)], BRASS, n=8)
    m.box((lx, 0, plat + 0.12), (0.4, 0.4, 0.08), BRASS)
    # Aft mast with a small crosstree.
    zb2 = boat_z(AFTMAST_X) - 0.1; top2 = 15.8 + ZL
    ax = lambda z: AFTMAST_X - 0.06 * (z - zb2)
    m.tube([(ax(z), 0, z) for z in [zb2 + (top2 - zb2) * k / 6 for k in range(7)]], [0.18 - 0.08 * k / 6 for k in range(7)], TIMBER, n=8)
    m.lathe((ax(top2), 0, top2 - 0.05), [(0, 0.11), (0.12, 0.15), (0.26, 0.13), (0.36, 0.05), (0.5, 0.0)], BRASS, n=8)
    ay = top2 - 0.9
    m.beam((ax(ay), -0.42, ay), (ax(ay), 0.42, ay), 0.1, 0.1, TIMBER)
    m.lathe((ax(ay), 0, ay - 0.2), [(0, 0.13), (0.16, 0.13)], BRASS, n=8)
    # Standing rigging, as painted: a few fine, taut, tarred stays. The fore shrouds set up on the monkey island
    # inside its rail (landing points fitted to the concept camera), the forestay pair on the foredeck, and a pair
    # of shrouds each side of the aft mast on the boat deck. Brass turnbuckles and eye plates at the deck ends.
    zr = lambda x: boat_z(x) + WH_H + 0.3
    for side in (-1, 1):
        stay(m, (mx(xtree), side * 0.45, xtree - 0.02), (16.85, side * 2.8, zr(16.85)))
        stay(m, (mx(plat) - 0.15, side * 0.3, plat - 0.02), (17.3, side * 2.8, zr(17.3)))
        stay(m, (mx(plat) - 0.15, side * 0.3, plat - 0.02), (20.05, side * 2.8, zr(20.05)))
        stay(m, (mx(plat) + 0.05, side * 0.12, plat - 0.1), (33.6, side * 0.45, deck_z(33.6)))
        for xs in (-22.0, -19.6):
            stay(m, (ax(ay), side * 0.38, ay - 0.02), (xs, side * (slab_half(xs) - 0.3), boat_z(xs)), r=0.016)


def stay(m, top, foot, r=0.02):
    """A taut tarred stay from a mast fitting down to a brass turnbuckle on an eye plate at the deck."""
    a, b = Vector(top), Vector(foot); d = (b - a).normalized()
    tb0, tb1 = b - d * 0.62, b - d * 0.08
    m.tube([tuple(a), tuple(tb0 + d * 0.05)], r, ROPE, n=4, phase=math.pi / 4)
    with m.frame(tb0, *_perp(d), d):
        m.lathe((0, 0, 0), [(0, 0.03), (0.08, 0.045), (0.46, 0.045), (0.54, 0.03), (0.54, 0.0)], BRASS, n=6)
    m.tube([tuple(tb0 + d * 0.5), tuple(b + Vector((0, 0, 0.02)))], 0.022, BRASS, n=4)
    m.box((b.x, b.y, b.z + 0.02), (0.22, 0.12, 0.06), BRASS, bevel=0.015)


def _perp(d):
    ref = Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))
    u = ref.cross(d).normalized(); return u, d.cross(u)


# ------------------------------------------------------------------ fittings
def cowl(m, x, y, z, h=3.2, r=0.34, R=0.7, yaw=0.0):
    """Brass cowl ventilator: a trunk with collars, a 90-degree bend and a deep flared bell mouth, dark inside."""
    f = Vector((math.cos(math.radians(yaw)), math.sin(math.radians(yaw)), 0)); up = Vector((0, 0, 1))
    rb = 0.55; zt = z + h - rb - 0.35
    base = Vector((x, y, z)); path = [base - up * 0.1, base + up * (zt - z)]
    for k in range(1, 7):
        a = math.pi / 2 * k / 6
        path.append(base + up * (zt - z + rb * math.sin(a)) + f * rb * (1 - math.cos(a)))
    m.tube([tuple(p) for p in path], r, BRASS, n=12)
    m.lathe((x, y, z - 0.05), [(0, r + 0.3), (0.12, r + 0.3), (0.2, r + 0.1), (0.45, r + 0.02)], BRASS, n=12)
    for zc in (z + 0.9, zt - 0.3):
        m.lathe((x, y, zc), [(0, r + 0.05), (0.14, r + 0.05)], BRASS, n=12)
    mouth = path[-1] - f * 0.02
    with m.frame(mouth, up.cross(f).normalized(), up, f):
        m.lathe((0, 0, 0), [(0, r), (0.18, r * 1.12), (0.38, R * 0.8), (0.52, R * 0.97), (0.58, R), (0.58, R - 0.07), (0.46, R * 0.82),
                            (0.3, R * 0.55), (0.24, R * 0.3)], [BRASS, BRASS, BRASS, BRASS, BRASS, GOLD, GOLD, GOLD], n=16)


def lifebuoy(m, x, side):
    y = side * (deck_half(x) - 0.2); z = deck_z(x)
    m.box((x, y, z + 0.62), (0.9, 0.42, 1.24), WHITE, bevel=0.05)
    with m.frame((x, y + side * 0.27, z + 0.78), Vector((-side, 0, 0)), Vector((0, 0, 1)), Vector((0, side, 0))):
        m.torus((0, 0, 0.05), 0.3, 0.09, BUOY, n=16, m=6, mats=lambda i: WHITE if i % 4 == 0 else BUOY)


def fittings(m):
    # Foredeck: windlass, capstan, bollards and the jackstaff at the stem.
    x = 32.6; z = deck_z(x)
    m.box((x, 0, z + 0.25), (1.2, 2.4, 0.5), IRON, bevel=0.06)
    for y in (-0.75, 0.75):
        with m.frame((x, y - 0.35, z + 0.75), Vector((1, 0, 0)), Vector((0, 0, 1)), Vector((0, 1, 0))):
            m.lathe((0, 0, 0), [(0, 0.5), (0.1, 0.38), (0.6, 0.38), (0.7, 0.5)], IRON, n=12)
    m.lathe((x, 0, z + 0.4), [(0, 0.3), (0.5, 0.3), (0.6, 0.38), (0.8, 0.38), (0.9, 0.2), (1.0, 0)], BRASS, n=10)
    x = 35.4; z = deck_z(x)
    m.lathe((x, 0, z - 0.05), [(0, 0.45), (0.2, 0.42), (0.3, 0.3), (0.8, 0.3), (0.9, 0.42), (1.05, 0.42), (1.15, 0)], BRASS, n=12)
    for bx, by in [(30.6, 3.1), (34.2, 2.2), (-36.5, 2.6), (-30.0, 4.2)]:
        for side in (-1, 1):
            z = deck_z(bx)
            m.box((bx, side * by, z + 0.08), (1.1, 0.5, 0.16), BRASS, bevel=0.04)
            for dx in (-0.3, 0.3):
                m.lathe((bx + dx, side * by, z), [(0, 0.17), (0.55, 0.15), (0.62, 0.22), (0.72, 0.22), (0.76, 0)], BRASS, n=8)
    x = STEM - 0.9; z = deck_z(x)
    m.lathe((x, 0, z - 0.05), [(0, 0.16), (0.3, 0.14), (2.1, 0.09), (2.15, 0.15), (2.35, 0.17), (2.55, 0.08), (2.7, 0)], BRASS, n=8)
    # Ventilator box with a cap in front of the deckhouse.
    x = 30.4
    m.box((x, -2.4, deck_z(x) + 0.55), (0.9, 0.9, 1.1), WHITE, bevel=0.06)
    m.box((x, -2.4, deck_z(x) + 1.2), (1.05, 1.05, 0.22), WHITE, bevel=0.05)
    # Lifebuoys on white lockers at the rail.
    for side in (-1, 1):
        for x in (-6.2, 17.8, -27.0):
            lifebuoy(m, x, side)
    # Big brass cowl ventilators round the funnel and aft on the boat deck, white vent trunks beside the casing.
    for side in (-1, 1):
        cowl(m, 7.0, side * 2.45, boat_z(7.0), h=3.5, r=0.36, R=0.74, yaw=side * 35)
        cowl(m, -2.9, side * 2.45, boat_z(-2.9), h=3.3, r=0.34, R=0.7, yaw=180 - side * 40)
        cowl(m, -17.6, side * 1.6, boat_z(-17.6), h=2.7, r=0.28, R=0.58, yaw=180 - side * 30)
        for x in (-4.6, 8.6):
            m.box((x, side * 1.3, boat_z(x) + 0.7), (1.0, 1.1, 1.5), WHITE, bevel=0.08)
            with m.frame((x - 0.5, side * 1.3, boat_z(x) + 1.45), Vector((0, 1, 0)), Vector((0, 0, 1)), Vector((1, 0, 0))):
                m.prism([(0.55 * math.cos(math.pi * k / 10), 0.5 * math.sin(math.pi * k / 10)) for k in range(11)], 0.0, 1.0, WHITE)
        # Brass lamps on white pedestals at the front of the boat deck.
        x = T1_FWD - T1_FRONT + 0.6; y = side * (HW1 - 0.25); z = boat_z(x)
        m.box((x, y, z + 0.55), (0.45, 0.45, 1.1), WHITE, bevel=0.05)
        m.lathe((x, y, z + 1.08), [(0, 0.12), (0.2, 0.12)], BRASS, n=8)
        searchlight(m, (x, y, z + 1.55))
    # Monkey island: binnacle, bell and a brass searchlight on a post at the aft corner.
    zt = boat_z(18.4) + WH_H + 0.3
    m.lathe((18.4, 0.4, zt), [(0, 0.3), (0.15, 0.26), (0.9, 0.2), (1.0, 0.3), (1.15, 0.3), (1.35, 0.18), (1.45, 0)], BRASS, n=10)
    m.box((20.3, -1.7, zt + 0.5), (0.12, 0.12, 1.0), WHITE)
    m.lathe((20.3, -1.7, zt + 0.95), [(0, 0.08), (0.05, 0.32), (0.32, 0.28), (0.48, 0.14), (0.54, 0)], BRASS, n=12)
    m.lathe((15.3, -1.9, zt), [(0, 0.2), (0.15, 0.12), (1.2, 0.1), (1.3, 0.16)], BRASS, n=8)
    searchlight(m, (15.3, -1.9, zt + 1.7))
    # Stern deck benches and a lantern on the stern.
    xa, xf, zc = CANOPY
    for x0 in (-36.0, -32.6, -29.2, -25.8):
        for side in (-1, 1):
            y = side * (deck_half(x0) - 1.25); z = deck_z(x0)
            bench(m, x0, y, z, side)
    x = -39.2; z = deck_z(x)
    m.box((x, 0, z + 0.55), (0.12, 0.12, 1.1), BRASS)
    m.box((x, 0, z + 1.3), (0.3, 0.3, 0.42), GLASS)
    m.lathe((x, 0, z + 1.5), [(0, 0.22), (0.08, 0.22), (0.28, 0.06), (0.38, 0)], BRASS, n=8)
    m.box((x, 0, z + 1.08), (0.36, 0.36, 0.06), BRASS)
    # Canopy posts: brass, with finials on the forward corners.
    pts = [(x, -(deck_half(x) - 0.62)) for x in (xa + 0.4, xa + 3.8, xa + 7.3, xf - 0.3)]
    for side in (-1, 1):
        for i, (x, y) in enumerate(pts):
            z = deck_z(x); tall = 0.85 if i == len(pts) - 1 else 0.35
            m.lathe((x, side * -y, z - 0.05), [(0, 0.11), (0.25, 0.08), (zc - z - 0.1, 0.07), (zc - z + tall - 0.15, 0.07), (zc - z + tall, 0.13), (zc - z + tall + 0.2, 0)], BRASS, n=8)
    for x in (xa + 0.15,):
        z = deck_z(x)
        m.lathe((x, 0, z - 0.05), [(0, 0.1), (zc - z + 0.4, 0.07), (zc - z + 0.55, 0.13), (zc - z + 0.75, 0)], BRASS, n=8)


def searchlight(m, c):
    x, y, z = c
    with m.frame((x - 0.2, y, z), Vector((0, 1, 0)), Vector((0, 0, 1)), Vector((1, 0, 0))):
        m.lathe((0, 0, 0), [(0, 0.22), (0.4, 0.26), (0.48, 0.3), (0.55, 0.3)], BRASS, n=12)
        m.prism(circle(0.25, 12), 0.5, 0.58, GLASS)
    m.box((x - 0.05, y, z - 0.3), (0.12, 0.12, 0.3), BRASS)


def bench(m, x, y, z, side):
    m.box((x, y, z + 0.45), (2.2, 0.5, 0.08), DECK)
    m.box((x, y + side * 0.24, z + 0.75), (2.2, 0.08, 0.5), TIMBER)
    for dx in (-0.9, 0.9):
        m.box((x + dx, y, z + 0.22), (0.1, 0.45, 0.48), BRASS)


# ------------------------------------------------------------------ validation and export
def check(m):
    """Every part closed; any inward-wound part is flipped. Returns a report."""
    edges = {}
    for f in m.faces:
        for a, b in zip(f, f[1:] + f[:1]):
            k = (min(a, b), max(a, b))
            edges[k] = edges.get(k, 0) + 1
    open_edges = sum(1 for c in edges.values() if c != 2)
    flipped = 0
    V = m.verts
    for start, end in m.parts:
        vol = 0.0
        for f in m.faces[start:end]:
            a = Vector(V[f[0]])
            for i in range(1, len(f) - 1):
                vol += a.dot(Vector(V[f[i]]).cross(Vector(V[f[i + 1]]))) / 6
        if vol < 0:
            flipped += 1
            for i in range(start, end):
                m.faces[i] = tuple(reversed(m.faces[i]))
    return {'open_edges': open_edges, 'flipped_parts': flipped, 'parts': len(m.parts)}


def make_materials():
    mats = {}
    for name, (rgb, rough, metal) in MATERIALS.items():
        lin = tuple(((c / 255) / 12.92) if c / 255 <= 0.04045 else (((c / 255) + 0.055) / 1.055) ** 2.4 for c in rgb)
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        try:
            mat.use_nodes = True
        except Exception:
            pass
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value = (*lin, 1)
        bsdf.inputs['Roughness'].default_value = rough
        bsdf.inputs['Metallic'].default_value = metal
        mat.diffuse_color = (*lin, 1)
        mats[name] = mat
    return mats


SHARP_DEGREES = {'FY_Funnel': 15}  # the funnel keeps its flat facets, as painted


def to_object(m, mats):
    names = sorted(set(m.mats), key=list(MATERIALS).index)
    data = bpy.data.meshes.new(m.name)
    data.from_pydata(m.verts, [], [list(f) for f in m.faces]); data.update()
    for n in names:
        data.materials.append(mats[n])
    index = {n: i for i, n in enumerate(names)}
    data.polygons.foreach_set('material_index', [index[n] for n in m.mats])
    data.polygons.foreach_set('use_smooth', [True] * len(data.polygons))
    data.set_sharp_from_angle(angle=math.radians(SHARP_DEGREES.get(m.name, 38)))
    uv = data.uv_layers.new(name='UVMap')
    for face in data.polygons:
        drop = max(range(3), key=lambda i: abs(face.normal[i])); axes = [i for i in range(3) if i != drop]
        for li in face.loop_indices:
            co = data.vertices[data.loops[li].vertex_index].co
            uv.data[li].uv = (co[axes[0]] * 0.5, co[axes[1]] * 0.5)
    data.update()
    obj = bpy.data.objects.new(m.name, data); bpy.context.collection.objects.link(obj)
    return obj, names


def main():
    (OUT / 'assets').mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mats = make_materials()
    builders = [('FY_Hull', hull), ('FY_Superstructure', superstructure), ('FY_Funnel', funnel), ('FY_Lifeboats', lifeboats),
                ('FY_Rails', rails), ('FY_Masts', masts), ('FY_Fittings', fittings)]
    manifest = {'meshes': {}, 'units': 'metres, +X bow, z up, waterline z=0'}
    lo = Vector((1e9, 1e9, 1e9)); hi = -lo
    for name, fn in builders:
        m = Mesh(name); fn(m)
        report = check(m)
        obj, names = to_object(m, mats)
        tris = sum(len(f) - 2 for f in m.faces)
        bmin = [min(v[i] for v in m.verts) for i in range(3)]; bmax = [max(v[i] for v in m.verts) for i in range(3)]
        lo = Vector([min(lo[i], bmin[i]) for i in range(3)]); hi = Vector([max(hi[i], bmax[i]) for i in range(3)])
        manifest['meshes'][name] = {'triangles': tris, 'vertices': len(m.verts), 'materials': names,
                                    'min': [round(v, 3) for v in bmin], 'max': [round(v, 3) for v in bmax], **report}
        print(f'{name}: {tris} triangles, {report}')
        bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True); bpy.context.view_layer.objects.active = obj
        bpy.ops.export_scene.fbx(filepath=str(OUT / 'assets' / f'{name}.fbx'), use_selection=True, apply_unit_scale=True,
                                 apply_scale_options='FBX_SCALE_ALL', axis_forward='-Y', axis_up='Z', object_types={'MESH'},
                                 mesh_smooth_type='EDGE', bake_anim=False, use_custom_props=False)
    gate_x, gate_w = GATES[0]
    manifest['dimensions'] = {'min': [round(v, 3) for v in lo], 'max': [round(v, 3) for v in hi],
                              'length': round(hi.x - lo.x, 2), 'beam': round(hi.y - lo.y, 2), 'height_above_waterline': round(hi.z, 2),
                              'draft': round(-lo.z, 2)}
    manifest['boarding_openings'] = [
        {'side': s, 'centre': [gate_x, round(sign * deck_half(gate_x), 3), round(deck_z(gate_x), 3)], 'width': gate_w,
         'clear_height': 'open above', 'outward': [0, sign, 0]}
        for s, sign in (('starboard', -1), ('port', 1))]
    manifest['decks'] = {'main_deck_z': {'stern': round(deck_z(-38), 2), 'midships': round(deck_z(0), 2), 'bow': round(deck_z(38), 2)},
                         'boat_deck_z_midships': round(boat_z(0), 2), 'monkey_island_z': round(boat_z(19) + WH_H + 0.3, 2),
                         'rail_height': RAIL_H}
    manifest['triangles'] = sum(v['triangles'] for v in manifest['meshes'].values())
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / 'ferry.blend'))
    bad = [n for n, v in manifest['meshes'].items() if v['open_edges']]
    print('FERRY BUILD COMPLETE', manifest['triangles'], 'triangles', 'open edges in' if bad else 'all parts closed', bad or '')
    if bad:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
