"""Closed-solid mesh core and geometry audits for the gondola pieces (Blender only: bpy and mathutils).

The Mesh core follows the passenger ferry's builder (games/yorimichi/assets/vehicles/ferry/build.py): every
primitive is a closed solid, and parts are recorded so the audits can work per part. Consolidate the two copies into
one shared module when both land on main (games/CONTRACTS: one-implementation-per-mechanism).

Audits (all fail the build when violated):
- closed(): every edge of every part is shared by exactly two faces; parts wound inward are flipped (reported);
  degenerate faces are counted.
- coplanar_overlaps(): faces of different parts lying in the same plane, facing the same way and overlapping
  (they would z-fight).
- seats(): every registered fitting base is ray-cast onto the bearing parts: no gap over 1 cm, no penetration beyond
  the fitting's declared embedding.
- clearance(): a moving body (the cabin and hanger) placed along its path must not touch the static geometry.
"""
import math
from contextlib import contextmanager

import bpy
from mathutils import Matrix, Vector

# ------------------------------------------------------------------ materials: name -> (sRGB, roughness, metallic)
TIMBER, PLANK, TIMBER_DARK, PLASTER, TILE = 'GD_Timber', 'GD_TimberPlank', 'GD_TimberDark', 'GD_Plaster', 'GD_RoofTile'
SHINGLE, STEEL, IRON, GASKET, GLASS = 'GD_Shingle', 'GD_Steel', 'GD_DarkIron', 'GD_Gasket', 'GD_Glass'
BOLT, CONCRETE, STONE, BASALT, PAVING = 'GD_Bolt', 'GD_Concrete', 'GD_Stone', 'GD_Basalt', 'GD_Paving'
ROPE, BRASS, LAMP, SIGN, POT, SOIL = 'GD_Rope', 'GD_Brass', 'GD_LampGlow', 'GD_SignBoard', 'GD_Terracotta', 'GD_Soil'
DECK, RUBBER, PAINT = 'GD_DeckTimber', 'GD_Rubber', 'GD_SafetyPaint'
PANEL = 'GD_TimberPanel'
MATERIALS = {
    TIMBER: ((222, 168, 102), .55, 0.), PLANK: ((232, 184, 120), .6, 0.), TIMBER_DARK: ((96, 62, 40), .6, 0.),
    PLASTER: ((238, 230, 214), .8, 0.), TILE: ((70, 74, 88), .5, 0.), SHINGLE: ((196, 140, 82), .7, 0.),
    STEEL: ((172, 168, 160), .45, .5), IRON: ((64, 64, 68), .5, .4), GASKET: ((46, 46, 50), .6, 0.),
    GLASS: ((150, 176, 192), .08, 0.), BOLT: ((196, 194, 188), .35, .7), CONCRETE: ((178, 172, 162), .85, 0.),
    STONE: ((132, 128, 122), .85, 0.), BASALT: ((86, 82, 80), .85, 0.), PAVING: ((206, 194, 170), .85, 0.),
    ROPE: ((74, 74, 76), .6, .3), BRASS: ((206, 164, 78), .35, .55), LAMP: ((255, 214, 150), .4, 0.),
    SIGN: ((232, 228, 216), .7, 0.), POT: ((156, 100, 62), .7, 0.), SOIL: ((70, 52, 38), .9, 0.),
    DECK: ((204, 152, 96), .65, 0.), RUBBER: ((40, 40, 42), .8, 0.), PAINT: ((222, 178, 60), .6, 0.),
    PANEL: ((226, 174, 108), .75, 0.),
}
# Materials with a procedural timber texture (textures.py); their UVs are in metres with u along the grain.
TEXTURED = {TIMBER: 'wood_grain', PANEL: 'wood_panel', PLANK: 'wood_grain_light', TIMBER_DARK: 'wood_grain_dark',
            DECK: 'deck_planks', SHINGLE: 'shingle'}


# ------------------------------------------------------------------ 2D helpers
def signed_area(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))


def is_convex(pts):
    n = len(pts); sgn = 0
    for i in range(n):
        a, b, c = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cr) < 1e-12:
            continue
        s = 1 if cr > 0 else -1
        if sgn and s != sgn:
            return False
        sgn = s
    return True


def ear_clip(pts):
    """Triangulate a simple CCW polygon; returns index triples."""
    idx = list(range(len(pts))); tris = []

    def inside(p, a, b, c):
        d1 = (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])
        d2 = (p[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (p[1] - c[1])
        d3 = (p[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (p[1] - a[1])
        return not ((d1 < -1e-12 or d2 < -1e-12 or d3 < -1e-12) and (d1 > 1e-12 or d2 > 1e-12 or d3 > 1e-12))

    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1; n = len(idx); found = False
        for k in range(n):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % n]
            a, b, c = pts[i0], pts[i1], pts[i2]
            if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) <= 1e-12:
                continue
            if any(inside(pts[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2)); idx.pop(k); found = True
            break
        if not found:
            raise ValueError('ear clipping failed (self-intersecting outline?)')
    tris.append(tuple(idx))
    return tris


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
    out = []; n = len(pts)
    for i in range(n if closed else n - 1):
        a, b = Vector(pts[i]), Vector(pts[(i + 1) % n])
        k = max(1, math.ceil((b - a).length / step))
        out += [tuple(a.lerp(b, j / k)) for j in range(k)]
    if not closed:
        out.append(tuple(pts[-1]))
    return out


def circle(r, n=12, phase=0.0, sx=1.0, sy=1.0, c=(0.0, 0.0)):
    return [(c[0] + sx * r * math.cos(phase + 2 * math.pi * k / n), c[1] + sy * r * math.sin(phase + 2 * math.pi * k / n)) for k in range(n)]


def rounded_rect(w, h, r, k=3, c=(0.0, 0.0)):
    """CCW rounded rectangle centred on c, starting at the bottom-right corner arc."""
    pts = []; r = min(r, w / 2 - 1e-4, h / 2 - 1e-4)
    for cx, cy, a0 in [(w / 2 - r, -h / 2 + r, -90), (w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180)]:
        for j in range(k + 1):
            a = math.radians(a0 + 90 * j / k)
            pts.append((c[0] + cx + r * math.cos(a), c[1] + cy + r * math.sin(a)))
    return pts


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# ------------------------------------------------------------------ mesh core
def _origin():
    """file:line of the first caller outside this module (where a part was built)."""
    import os
    import sys
    f = sys._getframe(1)
    while f is not None and os.path.basename(f.f_code.co_filename) == 'solid.py':
        f = f.f_back
    return f'{os.path.basename(f.f_code.co_filename)}:{f.f_lineno}' if f is not None else '?'


class Mesh:
    def __init__(self, name):
        self.name = name; self.verts = []; self.faces = []; self.mats = []; self.parts = []
        self.xf = Matrix.Identity(4); self.tag = None; self.grain = None; self.fgrain = []
        self.origins = []                 # per part: the builder line that made it (file:line), for audit reports

    @contextmanager
    def _push(self, m):
        old = self.xf; self.xf = old @ m
        try:
            yield
        finally:
            self.xf = old

    @contextmanager
    def tagged(self, tag):
        old = self.tag; self.tag = tag
        try:
            yield
        finally:
            self.tag = old

    @contextmanager
    def grained(self, direction):
        """Faces built inside carry this grain direction (local frame) for their UVs."""
        old = self.grain; self.grain = direction
        try:
            yield
        finally:
            self.grain = old

    def at(self, pos=(0, 0, 0), yaw=0.0):
        return self._push(Matrix.Translation(Vector(pos)) @ Matrix.Rotation(math.radians(yaw), 4, 'Z'))

    def mirrored(self, axis='y', on=True):
        v = {'x': (1, 0, 0), 'y': (0, 1, 0)}[axis]
        return self._push(Matrix.Scale(-1, 4, v) if on else Matrix.Identity(4))

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
        g = None if self.grain is None else tuple((M.to_3x3() @ Vector(self.grain)).normalized())
        for k, f in enumerate(faces):
            f = [base + i for i in f]
            self.faces.append(tuple(reversed(f)) if flip else tuple(f))
            self.mats.append(mats[k] if isinstance(mats, list) else mats)
            self.fgrain.append(g)
        self.parts.append((start, len(self.faces), self.tag)); self.origins.append(_origin())
        return len(self.parts) - 1

    # ---- primitives (all closed)
    def prism(self, outline, z0, z1, side, top=None, bottom=None, bevel=0.0):
        """Vertical solid over a plan outline; z0/z1 constants or callables f(x, y)."""
        pts = [tuple(p) for p in outline]
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
        last = (len(rings) - 1) * n
        convex = is_convex(pts) and not (callable(z0) or callable(z1))
        caps = [] ; cap_mats = []
        bm = bottom or side; tm = top or side
        if convex:
            caps += [list(reversed(range(n))), [last + k for k in range(n)]]; cap_mats += [bm, tm]
        else:
            cap_pts = rings[0][0]
            for a, b, c in ear_clip(cap_pts):
                caps.append([c, b, a]); cap_mats.append(bm)
                caps.append([last + a, last + b, last + c]); cap_mats.append(tm)
        faces = caps; mats = cap_mats
        for r in range(len(rings) - 1):
            for k in range(n):
                k2 = (k + 1) % n
                faces.append([r * n + k, r * n + k2, (r + 1) * n + k2, (r + 1) * n + k]); mats.append(side)
        return self.part(verts, faces, mats)

    def ring_prism(self, outer, inner, z0, z1, mat):
        """Closed band between two CCW loops of equal count (a frame, rim or kerb)."""
        n = len(outer); verts = [(*p, z0) for p in outer] + [(*p, z0) for p in inner] + [(*p, z1) for p in outer] + [(*p, z1) for p in inner]
        O0, I0, O1, I1 = 0, n, 2 * n, 3 * n; faces = []
        for k in range(n):
            j = (k + 1) % n
            faces += [[O1 + k, O1 + j, I1 + j, I1 + k], [O0 + k, I0 + k, I0 + j, O0 + j],
                      [O0 + k, O0 + j, O1 + j, O1 + k], [I0 + k, I1 + k, I1 + j, I0 + j]]
        return self.part(verts, faces, mat)

    def band(self, outer, inner, z0, z1, mat):
        """Closed solid between two open plan paths of equal count (outer runs CCW round the inside), with end caps:
        a wall segment between openings."""
        n = len(outer)
        verts = [(*p, z0) for p in outer] + [(*p, z0) for p in inner] + [(*p, z1) for p in outer] + [(*p, z1) for p in inner]
        O0, I0, O1, I1 = 0, n, 2 * n, 3 * n; faces = []
        for k in range(n - 1):
            j = k + 1
            faces += [[O1 + k, O1 + j, I1 + j, I1 + k], [O0 + k, I0 + k, I0 + j, O0 + j],
                      [O0 + k, O0 + j, O1 + j, O1 + k], [I0 + k, I1 + k, I1 + j, I0 + j]]
        faces.append([O0, O1, I1, I0]); faces.append([O0 + n - 1, I0 + n - 1, I1 + n - 1, O1 + n - 1])
        return self.part(verts, faces, mat)

    def box(self, c, s, mat, bevel=0.0, top=None, bottom=None):
        x, y, z = c; w, d, h = s
        return self.prism(rect(x - w / 2, y - d / 2, x + w / 2, y + d / 2), z - h / 2, z + h / 2, mat, top=top, bottom=bottom, bevel=bevel)

    def beam(self, a, b, w, d, mat, up=None, bevel=0.0):
        """Rectangular member from a to b (w across, d in the 'up' direction)."""
        a, b = Vector(a), Vector(b); A = b - a; L = A.length
        if L < 1e-6:
            return None
        A.normalize(); ref = Vector(up) if up is not None else (Vector((0, 0, 1)) if abs(A.z) < 0.9 else Vector((1, 0, 0)))
        U = ref.cross(A).normalized(); V = A.cross(U)
        with self.frame(a, U, V, A), self.grained((0, 0, 1)):
            return self.prism(rect(-w / 2, -d / 2, w / 2, d / 2), 0.0, L, mat, bevel=bevel)

    def tube(self, path, r, mat, n=6, phase=0.0, sx=1.0, sy=1.0):
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
                a = phase + 2 * math.pi * k / n
                verts.append(tuple(P[i] + radii[i] * (sx * math.cos(a) * nrm[i] + sy * math.sin(a) * B)))
        faces = []
        for i in range(N - 1):
            for k in range(n):
                j = (k + 1) % n
                faces.append([i * n + k, i * n + j, (i + 1) * n + j, (i + 1) * n + k])
        faces.append(list(reversed(range(n)))); faces.append([(N - 1) * n + k for k in range(n)])
        return self.part(verts, faces, mat)

    def lathe(self, c, profile, mat, n=12, sx=1.0, sy=1.0, phase=0.0, axis=None):
        """Revolve [(z, r), ...] (bottom to top) round a local z axis through c (or along `axis`)."""
        if axis is not None:
            A = Vector(axis).normalized(); ref = Vector((0, 0, 1)) if abs(A.z) < 0.9 else Vector((1, 0, 0))
            U = ref.cross(A).normalized(); V = A.cross(U)
            with self.frame(c, U, V, A):
                return self.lathe((0, 0, 0), profile, mat, n=n, sx=sx, sy=sy, phase=phase)
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
        return self.part(verts, faces, mats)

    def cylinder(self, a, b, r, mat, n=12):
        A = Vector(b) - Vector(a)
        return self.lathe(a, [(0, r), (A.length, r)], mat, n=n, axis=tuple(A))

    def torus_arc(self, c, R, r, a0, a1, mat, n=24, m=6, z=0.0):
        """Closed swept circle along a horizontal arc of radius R round c (angles in radians), capped at both ends."""
        path = [(c[0] + R * math.cos(a0 + (a1 - a0) * k / n), c[1] + R * math.sin(a0 + (a1 - a0) * k / n), z) for k in range(n + 1)]
        return self.tube(path, r, mat, n=m)

    def loft(self, rings, mat, caps=True):
        """Closed solid through equal-count 3D loops (CCW seen from the end the loft runs towards)."""
        n = len(rings[0]); verts = [v for r in rings for v in r]; faces = []
        for i in range(len(rings) - 1):
            for k in range(n):
                j = (k + 1) % n
                faces.append([i * n + k, i * n + j, (i + 1) * n + j, (i + 1) * n + k])
        faces.append(list(reversed(range(n)))); last = (len(rings) - 1) * n; faces.append([last + k for k in range(n)])
        return self.part(verts, faces, mat)

    def rock(self, c, size, mat, seed, n=7, m=5, embed=0.0):
        """Rounded low-poly stone: a squashed, jittered ellipsoid (closed)."""
        import random
        rnd = random.Random(seed); sx, sy, sz = size; prof = []
        for i in range(m + 1):
            t = i / m; phi = -math.pi / 2 + math.pi * t
            prof.append((math.sin(phi), math.cos(phi)))
        verts = [(c[0], c[1], c[2] - sz)]; rings = []
        for i in range(1, m):
            zr, rr = prof[i]; ring = []
            for k in range(n):
                a = 2 * math.pi * (k + 0.5 * (i % 2)) / n; j = 0.82 + 0.3 * rnd.random()
                ring.append(len(verts)); verts.append((c[0] + sx * rr * j * math.cos(a), c[1] + sy * rr * j * math.sin(a), c[2] + sz * zr * (0.85 + 0.2 * rnd.random())))
            rings.append(ring)
        top = len(verts); verts.append((c[0], c[1], c[2] + sz * 0.92)); faces = []
        for k in range(n):
            faces.append([0, rings[0][(k + 1) % n], rings[0][k]])
        for i in range(len(rings) - 1):
            a, b = rings[i], rings[i + 1]
            for k in range(n):
                j = (k + 1) % n
                faces.append([a[k], a[j], b[j]]); faces.append([a[k], b[j], b[k]])
        for k in range(n):
            faces.append([rings[-1][k], rings[-1][(k + 1) % n], top])
        return self.part(verts, faces, mat)

    def tris(self):
        return sum(len(f) - 2 for f in self.faces)


# ------------------------------------------------------------------ audits
def closed(m):
    """Every part closed; any inward-wound part is flipped. Returns a report."""
    edges = {}
    for f in m.faces:
        for a, b in zip(f, f[1:] + f[:1]):
            k = (min(a, b), max(a, b)); edges[k] = edges.get(k, 0) + 1
    open_edges = sum(1 for c in edges.values() if c != 2)
    flipped = 0; V = m.verts; degenerate = 0
    for start, end, _tag in m.parts:
        vol = 0.0
        for f in m.faces[start:end]:
            a = Vector(V[f[0]])
            for i in range(1, len(f) - 1):
                vol += a.dot(Vector(V[f[i]]).cross(Vector(V[f[i + 1]]))) / 6
        if vol < 0:
            flipped += 1
            for i in range(start, end):
                m.faces[i] = tuple(reversed(m.faces[i]))
    directed = {}
    for f in m.faces:
        for a, b in zip(f, f[1:] + f[:1]):
            directed[(a, b)] = directed.get((a, b), 0) + 1
    misoriented = sum(1 for c in directed.values() if c > 1)
    for f in m.faces:
        a = Vector(V[f[0]]); area = Vector((0, 0, 0))
        for i in range(1, len(f) - 1):
            area += (Vector(V[f[i]]) - a).cross(Vector(V[f[i + 1]]) - a)
        if area.length < 1e-9:
            degenerate += 1
    return {'open_edges': open_edges, 'misoriented_edges': misoriented, 'flipped_parts': flipped, 'parts': len(m.parts), 'degenerate_faces': degenerate}


def _triangles(meshes):
    """(verts3, part key, mesh name) for every triangle of the given meshes."""
    out = []
    for m in meshes:
        for pi, (start, end, _tag) in enumerate(m.parts):
            org = m.origins[pi] if pi < len(m.origins) else '?'
            for f in m.faces[start:end]:
                for i in range(1, len(f) - 1):
                    out.append(((m.verts[f[0]], m.verts[f[i]], m.verts[f[i + 1]]), (m.name, pi, org)))
    return out


def _clip(poly, a, b):
    """Keep the part of a 2D polygon left of the directed line a->b."""
    out = []
    def side(p):
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    for i in range(len(poly)):
        p, q = poly[i], poly[(i + 1) % len(poly)]
        sp, sq = side(p), side(q)
        if sp >= 0:
            out.append(p)
        if (sp >= 0) != (sq >= 0):
            t = sp / (sp - sq); out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    return out


def _area2(poly):
    return abs(signed_area(poly)) if len(poly) >= 3 else 0.0


def coplanar_overlaps(meshes, d_tol=0.0015, min_area=2e-4, limit=60):
    """Same-facing coplanar faces of different parts that overlap (z-fighting). Returns (count, samples)."""
    tris = _triangles(meshes); buckets = {}
    for idx, ((a, b, c), key) in enumerate(tris):
        A, B, C = Vector(a), Vector(b), Vector(c); n = (B - A).cross(C - A)
        if n.length < 1e-10:
            continue
        n.normalize(); d = n.dot(A)
        k = (round(n.x * 300), round(n.y * 300), round(n.z * 300), math.floor(d / d_tol))
        buckets.setdefault(k, []).append((idx, n, d))
    count = 0; samples = []; seen = set()
    for k, items in buckets.items():
        nb = buckets.get((k[0], k[1], k[2], k[3] + 1), [])
        pool = items + nb
        if len(pool) < 2:
            continue
        for ii, (i, n, d) in enumerate(items):
            for (j, n2, d2) in pool[ii + 1:]:
                ki, kj = tris[i][1], tris[j][1]
                if ki == kj or abs(d - d2) > d_tol or n.dot(n2) < 0.9995:
                    continue
                U = n.orthogonal().normalized(); W = n.cross(U)
                P = [(Vector(v).dot(U), Vector(v).dot(W)) for v in tris[i][0]]
                Q = [(Vector(v).dot(U), Vector(v).dot(W)) for v in tris[j][0]]
                if (max(p[0] for p in P) <= min(q[0] for q in Q) or max(q[0] for q in Q) <= min(p[0] for p in P) or
                        max(p[1] for p in P) <= min(q[1] for q in Q) or max(q[1] for q in Q) <= min(p[1] for p in P)):
                    continue
                if signed_area(P) < 0:
                    P = P[::-1]
                if signed_area(Q) < 0:
                    Q = Q[::-1]
                poly = P
                for e in range(3):
                    poly = _clip(poly, Q[e], Q[(e + 1) % 3])
                    if not poly:
                        break
                ar = _area2(poly)
                if ar > min_area:
                    count += 1
                    pair = tuple(sorted((ki[2], kj[2])))
                    if len(samples) < limit and pair not in seen:     # one sample per pair of builder lines
                        seen.add(pair)
                        cen = [round(sum(v[t] for v in tris[i][0]) / 3, 3) for t in range(3)]
                        samples.append({'at': cen, 'area_m2': round(ar, 5), 'parts': [list(ki), list(kj)]})
    return count, samples


def bvh_of(meshes, tags=None, exclude_tags=(), origins=None):
    """A BVH of the meshes' parts (filtered by tag); `origins`, a list, receives each face's part origin and tag."""
    from mathutils.bvhtree import BVHTree
    verts, faces = [], []
    for m in meshes:
        for pi, (start, end, tag) in enumerate(m.parts):
            if (tags is not None and tag not in tags) or tag in exclude_tags:
                continue
            if origins is not None:
                origins += [f'{m.origins[pi] if pi < len(m.origins) else "?"} ({tag})'] * (end - start)
            vmap = {}
            for f in m.faces[start:end]:
                nf = []
                for v in f:
                    if v not in vmap:
                        vmap[v] = len(verts); verts.append(m.verts[v])
                    nf.append(vmap[v])
                faces.append(nf)
    return BVHTree.FromPolygons(verts, faces, epsilon=0.0) if faces else None


def seats(meshes, registry):
    """Ray-cast each registered fitting base down onto the parts it rests on (named by tag). Each base is probed at
    its point and 15 mm round it, so a seam between floor boards does not read as a gap."""
    cache = {}; rows = []
    for label, x, y, z, embed, probe, on in registry:
        key = tuple(sorted(on))
        if key not in cache:
            cache[key] = bvh_of(meshes, tags=set(key))
        bvh = cache[key]; hz = None
        for dx, dy in ((0, 0), (0.015, 0), (-0.015, 0), (0, 0.015), (0, -0.015)):
            hit = bvh.ray_cast(Vector((x + dx, y + dy, z + probe)), Vector((0, 0, -1)), probe + 3.0) if bvh else (None,)
            if hit[0] is not None:
                hz = hit[0].z if hz is None else max(hz, hit[0].z)
        if hz is None:
            rows.append({'label': label, 'at': [x, y, z], 'on': list(key), 'status': 'no bearing surface under base'}); continue
        gap = z - hz; ok = -(embed + 0.005) <= gap <= 0.01
        rows.append({'label': label, 'at': [round(x, 3), round(y, 3), round(z, 3)], 'on': list(key), 'surface_z': round(hz, 4), 'gap_m': round(gap, 4),
                     'embed_allowed_m': embed, 'status': 'ok' if ok else ('floating' if gap > 0.01 else 'sunk')})
    return rows


def transformed(m, M, name=None):
    """A copy of mesh m moved by matrix M (parts and tags kept)."""
    c = Mesh(name or m.name); c.verts = [tuple(M @ Vector(v)) for v in m.verts]; c.faces = list(m.faces)
    c.mats = list(m.mats); c.parts = list(m.parts)
    R3 = M.to_3x3(); c.fgrain = [None if g is None else tuple((R3 @ Vector(g)).normalized()) for g in m.fgrain]
    return c


class Pose:
    """A placement whose meshes take different matrices: the named grip meshes take G (on the rope), every other mesh
    takes C (hanging plumb from the grip's pivot)."""
    def __init__(self, G, C, grip_names):
        self.G, self.C, self.grip_names = G, C, tuple(grip_names)

    def of(self, name):
        return self.G if name in self.grip_names else self.C


def matrix_for(M, name):
    return M.of(name) if isinstance(M, Pose) else M


def rope_clearance(meshes, path, poses, exclude_tags=('jaw', 'clamp'), reach=3.0, step=0.02, near=0.6, only_tags=None):
    """Minimum distance from the rope centreline (a rope.RopePath) to the placed meshes, over poses [(label, pose, s)]
    (s = the grip's arc length on the path, or None to take the nearest). For each pose the rope is sampled every `step` within +-reach of the grip
    and the samples are taken into each mesh's own frame (rigid, so distances hold): nearest-surface distance per
    sample, and a ray along each sample segment, which counts any crossing of a surface as distance 0. Parts tagged
    exclude_tags (the jaws and the clamp body that close on the rope) are left out. Returns the overall minimum with
    where it occurs, and the minimum per pose."""
    from mathutils.bvhtree import BVHTree
    trees = []
    for m in meshes:
        verts, faces, origin = [], [], []
        for pi, (start, end, tag) in enumerate(m.parts):
            if tag in exclude_tags or (only_tags is not None and tag not in only_tags):
                continue
            vmap = {}
            for f in m.faces[start:end]:
                nf = []
                for v in f:
                    if v not in vmap:
                        vmap[v] = len(verts); verts.append(m.verts[v])
                    nf.append(vmap[v])
                faces.append(nf); origin.append(m.origins[pi] if pi < len(m.origins) else '?')
        if faces:
            trees.append((m.name, BVHTree.FromPolygons(verts, faces, epsilon=0.0), origin))
    best = {'distance_m': 1e9}; per_pose = []; per_mesh = {}
    for label, pose, s0 in poses:
        if s0 is None:                    # the grip's place on this path (its frame origin is on the grip line)
            G = pose.G if isinstance(pose, Pose) else pose
            s0 = path.nearest(tuple(G.translation))[1]
        n = max(2, int(2 * reach / step)); ss = [min(path.length, max(0.0, s0 - reach + 2 * reach * k / n)) for k in range(n + 1)]
        world = [Vector(path.rope_point(s_)) for s_ in ss]
        pose_min = 1e9
        for name, tree, origin in trees:
            Minv = matrix_for(pose, name).inverted(); loc = [Minv @ w for w in world]
            for k, q in enumerate(loc):
                hit = tree.find_nearest(q, 3.0)
                if hit[0] is not None:
                    d = hit[3]
                    if d < pose_min:
                        pose_min = d
                    if d < per_mesh.get(name, (1e9,))[0]:
                        per_mesh[name] = (d, label, origin[hit[2]])
                    if d < best['distance_m']:
                        best = {'distance_m': d, 'at': label, 'mesh': name, 'part': origin[hit[2]], 'rope_point': [round(c, 3) for c in world[k]]}
                if k:
                    seg = q - loc[k - 1]; L = seg.length
                    if L > 1e-9:
                        hit = tree.ray_cast(loc[k - 1], seg / L, L)
                        if hit[0] is not None:
                            pose_min = 0.0; per_mesh[name] = (0.0, label, origin[hit[2]])
                            if best['distance_m'] > 0.0:
                                best = {'distance_m': 0.0, 'at': label, 'mesh': name, 'part': origin[hit[2]], 'rope_point': [round(c, 3) for c in world[k]],
                                        'crossing': True}
        per_pose.append((label, round(pose_min, 4)))
    if best['distance_m'] >= 1e9:
        best['distance_m'] = None
        return best, per_pose
    best['distance_m'] = round(best['distance_m'], 4)
    best['per_mesh'] = {k: {'distance_m': round(v[0], 4), 'at': v[1], 'part': v[2]} for k, v in sorted(per_mesh.items())}
    return best, per_pose


def rope_contact_parts(meshes, path, poses, tags, reach=0.4, step=0.01):
    """Per part, the signed minimum distance from the rope axis (checks.part_minimum: negative inside the part) at
    each pose [(label, pose, s)]: one row per part tagged `tags`, so each jaw half, each sheave and the bullwheel
    groove is gated on its own (checks.part_verdicts). The rope is sampled every `step` within +-reach of s (the whole
    path when reach is None) and taken into each mesh's own frame."""
    import checks
    parts = []; count = {}
    for m in meshes:
        for pi, (start, end, tag) in enumerate(m.parts):
            if tag in tags:
                k = count[tag] = count.get(tag, 0) + 1
                parts.append((m.name, tag, f'{tag} {k} ({m.origins[pi] if pi < len(m.origins) else "?"})',
                              checks.triangles(m.verts, m.faces[start:end])))
    rows = [{'mesh': n, 'tag': t, 'part': o, 'per_pose': []} for n, t, o, _ in parts]
    for label, pose, s0 in poses:
        if reach is None:
            ss = [path.length * k / max(1, int(path.length / step)) for k in range(int(path.length / step) + 1)]
        else:
            if s0 is None:
                G = pose.G if isinstance(pose, Pose) else pose
                s0 = path.nearest(tuple(G.translation))[1]
            n = max(2, int(2 * reach / step)); ss = [min(path.length, max(0.0, s0 - reach + 2 * reach * k / n)) for k in range(n + 1)]
        world = [Vector(path.rope_point(s_)) for s_ in ss]
        for row, (name, tag, origin, tris) in zip(rows, parts):
            Minv = matrix_for(pose, name).inverted()
            d = checks.part_minimum(tris, [tuple(Minv @ w) for w in world], path.r)
            row['per_pose'].append(None if d is None else round(d, 5))
    return rows


def clearance(static, movers, placements, exclude_tags=(), mover_exclude=()):
    """Place the mover meshes at each placement (a matrix or a Pose); count triangle contacts with the static meshes
    (static parts tagged exclude_tags and mover parts tagged mover_exclude are left out)."""
    so = []; sb = bvh_of(static, exclude_tags=exclude_tags, origins=so); hits = []
    for label, M in placements:
        mb = bvh_of([transformed(m, matrix_for(M, m.name)) for m in movers], exclude_tags=mover_exclude)
        pairs = sb.overlap(mb) if (sb and mb) else []
        if pairs:
            hits.append({'at': label, 'contacts': len(pairs), 'station_parts': sorted({so[i] for i, _ in pairs})[:4]})
    return hits


# ------------------------------------------------------------------ Blender objects and export
def make_materials(textures=None):
    """Principled materials; the timber ones sample their procedural texture through the UV map (metres)."""
    mats = {}
    for name, (rgb, rough, metal) in MATERIALS.items():
        lin = tuple(((c / 255) / 12.92) if c / 255 <= 0.04045 else (((c / 255) + 0.055) / 1.055) ** 2.4 for c in rgb)
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        try:
            mat.use_nodes = True
        except Exception:
            pass
        nt = mat.node_tree; bsdf = nt.nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value = (*lin, 1)
        bsdf.inputs['Roughness'].default_value = rough
        bsdf.inputs['Metallic'].default_value = metal
        if name == LAMP:
            bsdf.inputs['Emission Color'].default_value = (*lin, 1); bsdf.inputs['Emission Strength'].default_value = 1.2
        tex = TEXTURED.get(name)
        if textures and tex and (tex, 'color') in textures:
            uv = nt.nodes.new('ShaderNodeTexCoord')
            ci = nt.nodes.new('ShaderNodeTexImage'); ci.image = bpy.data.images.load(str(textures[(tex, 'color')]), check_existing=True)
            ri = nt.nodes.new('ShaderNodeTexImage'); ri.image = bpy.data.images.load(str(textures[(tex, 'rough')]), check_existing=True)
            ri.image.colorspace_settings.name = 'Non-Color'
            for node in (ci, ri):
                nt.links.new(uv.outputs['UV'], node.inputs['Vector'])
            nt.links.new(ci.outputs['Color'], bsdf.inputs['Base Color']); nt.links.new(ri.outputs['Color'], bsdf.inputs['Roughness'])
        mat.diffuse_color = (*lin, 1)
        mats[name] = mat
    return mats


def to_object(m, mats, sharp_degrees=38, collection=None):
    """A Blender mesh object. UVs are in metres: u runs along the part's grain (or, by default, horizontally on
    upright faces and along x on level faces) and v across it, so timber textures tile at true scale."""
    names = sorted(set(m.mats), key=list(MATERIALS).index)
    data = bpy.data.meshes.new(m.name)
    data.from_pydata(m.verts, [], [list(f) for f in m.faces]); data.update()
    for n in names:
        data.materials.append(mats[n])
    index = {n: i for i, n in enumerate(names)}
    data.polygons.foreach_set('material_index', [index[n] for n in m.mats])
    data.polygons.foreach_set('use_smooth', [True] * len(data.polygons))
    data.set_sharp_from_angle(angle=math.radians(sharp_degrees))
    uv = data.uv_layers.new(name='UVMap'); Z = Vector((0, 0, 1))
    for face in data.polygons:
        n = Vector(face.normal); g = m.fgrain[face.index] if face.index < len(m.fgrain) else None
        U = None
        if g is not None:
            gv = Vector(g); U = gv - n * gv.dot(n)
            U = U.normalized() if U.length > 0.2 else None
        if U is None:
            if abs(n.z) > 0.7:
                U = Vector((1, 0, 0)) - n * n.x; U = U.normalized() if U.length > 1e-6 else Vector((0, 1, 0))
            else:
                U = Z.cross(n).normalized()
        V = n.cross(U)
        for li in face.loop_indices:
            co = data.vertices[data.loops[li].vertex_index].co
            uv.data[li].uv = (co.dot(U), co.dot(V))
    data.update()
    obj = bpy.data.objects.new(m.name, data); (collection or bpy.context.collection).objects.link(obj)
    return obj, names


def export_fbx(objs, path, smooth='EDGE'):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.fbx(filepath=str(path), use_selection=True, apply_unit_scale=True, apply_scale_options='FBX_SCALE_ALL',
                             axis_forward='-Y', axis_up='Z', object_types={'MESH'}, mesh_smooth_type=smooth, bake_anim=False,
                             use_custom_props=False)


# ------------------------------------------------------------------ collision proxies (convex prisms)
def proxy(name, poly, z0, z1):
    """A convex collision prism: plan polygon with bottom/top heights (constants or per-corner callables)."""
    pts = [tuple(p) for p in poly]
    if signed_area(pts) < 0:
        pts = pts[::-1]
    f0 = z0 if callable(z0) else (lambda x, y, c=z0: c)
    f1 = z1 if callable(z1) else (lambda x, y, c=z1: c)
    return {'name': name, 'poly': [[round(x, 4), round(y, 4)] for x, y in pts],
            'z0': [round(f0(x, y), 4) for x, y in pts], 'z1': [round(f1(x, y), 4) for x, y in pts]}


def proxy_box(name, cx, cy, sx, sy, z0, z1, yaw=0.0):
    c, s_ = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    poly = [(cx + c * u - s_ * v, cy + s_ * u + c * v) for u, v in ((-sx / 2, -sy / 2), (sx / 2, -sy / 2), (sx / 2, sy / 2), (-sx / 2, sy / 2))]
    return proxy(name, poly, z0, z1)


def proxy_strip(name, a, b, t, z0, z1):
    d = Vector((b[0] - a[0], b[1] - a[1])); n = Vector((-d.y, d.x)).normalized() * (t / 2)
    poly = [(a[0] - n.x, a[1] - n.y), (b[0] - n.x, b[1] - n.y), (b[0] + n.x, b[1] + n.y), (a[0] + n.x, a[1] + n.y)]
    return proxy(name, poly, z0, z1)


def proxy_transform(pr, M):
    """Move a proxy by a matrix that keeps z up (translation + yaw)."""
    pts = []; z0 = []; z1 = []
    for (x, y), a, b in zip(pr['poly'], pr['z0'], pr['z1']):
        p0 = M @ Vector((x, y, a)); p1 = M @ Vector((x, y, b)); pts.append((p0.x, p0.y)); z0.append(p0.z); z1.append(p1.z)
    if signed_area(pts) < 0:
        pts, z0, z1 = pts[::-1], z0[::-1], z1[::-1]
    return {'name': pr['name'], 'poly': [[round(x, 4), round(y, 4)] for x, y in pts], 'z0': [round(v, 4) for v in z0], 'z1': [round(v, 4) for v in z1]}


def proxy_mesh(proxies, name='proxies'):
    """The proxies as a Mesh (for clearance checks)."""
    m = Mesh(name)
    for pr in proxies:
        n = len(pr['poly'])
        verts = [(x, y, z) for (x, y), z in zip(pr['poly'], pr['z0'])] + [(x, y, z) for (x, y), z in zip(pr['poly'], pr['z1'])]
        faces = [list(reversed(range(n))), list(range(n, 2 * n))] + [[k, (k + 1) % n, n + (k + 1) % n, n + k] for k in range(n)]
        m.part(verts, faces, CONCRETE)
    return m


def export_collision(proxies, path, base):
    """One FBX: a tiny placeholder render mesh plus one UCX_ convex hull per proxy (Unreal custom collision)."""
    objs = []
    me = bpy.data.meshes.new(base); s_ = 0.05
    me.from_pydata([(x * s_, y * s_, z * s_) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], [],
                   [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]])
    objs.append(bpy.data.objects.new(base, me))
    for i, pr in enumerate(proxies):
        n = len(pr['poly'])
        verts = [(x, y, z) for (x, y), z in zip(pr['poly'], pr['z0'])] + [(x, y, z) for (x, y), z in zip(pr['poly'], pr['z1'])]
        faces = [list(reversed(range(n))), list(range(n, 2 * n))] + [[k, (k + 1) % n, n + (k + 1) % n, n + k] for k in range(n)]
        cm = bpy.data.meshes.new(f'UCX_{base}_{i:03d}'); cm.from_pydata(verts, [], faces); cm.update()
        objs.append(bpy.data.objects.new(cm.name, cm))
    for o in objs:
        bpy.context.collection.objects.link(o)
    export_fbx(objs, path, smooth='FACE')
    for o in objs:
        data = o.data; bpy.data.objects.remove(o); bpy.data.meshes.remove(data)
    return len(proxies)
