"""The shared closed-solid mesh builder: plan-outline prisms, lofts, boxes, beams, tubes, lathes and tori, every part a
closed solid with outward normals, built in nested local frames and turned into a Blender object by to_object.

Vehicle and building kits build on this one implementation (the ferry and its terminals today). A kit keeps its own
materials and passes them in; it does not copy these primitives.
"""
import math
from contextlib import contextmanager

import bpy
from mathutils import Matrix, Vector


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
    def __init__(self, name, default_mat=None):
        self.name = name; self.verts = []; self.faces = []; self.mats = []; self.parts = []
        self.xf = Matrix.Identity(4)
        self.default_mat = default_mat     # the cap material of a prism whose side material is per-edge

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
        mats = [bottom or (side if isinstance(side, str) else self.default_mat), top or (side if isinstance(side, str) else self.default_mat)]
        for r in range(len(rings) - 1):
            for k in range(n):
                k2 = (k + 1) % n
                faces.append([r * n + k, r * n + k2, (r + 1) * n + k2, (r + 1) * n + k])
                if callable(side):
                    mats.append(side((pts[k][0] + pts[k2][0]) / 2, (pts[k][1] + pts[k2][1]) / 2))
                else:
                    mats.append(side)
        self.part(verts, faces, mats)

    def loft_prism(self, outline, f0, f1, side, top=None, bottom=None, bevel=0.0, dx=0.5):
        """Solid over an x-monotone plan outline, lofted through x stations so a top that follows the sheer is
        built from quads across the deck (no non-planar n-gon caps)."""
        pts = [tuple(p) for p in outline]; xmin = min(p[0] for p in pts); xmax = max(p[0] for p in pts)
        xs = sorted({round(p[0], 5) for p in pts} | {round(xmin + k * dx, 5) for k in range(int((xmax - xmin) / dx) + 1)})
        xs = [x for x in xs if xmin <= x <= xmax]; xs[0] = xmin + 1e-4; xs[-1] = xmax - 1e-3
        rings = []
        for x in xs:
            ys = []
            for k in range(len(pts)):
                (x0, y0), (x1, y1) = pts[k], pts[(k + 1) % len(pts)]
                if (x0 - x) * (x1 - x) <= 0 and x0 != x1:
                    ys.append(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
            lo, hi = min(ys), max(ys)
            b = min(bevel, (hi - lo) * 0.3)
            rings.append([(x, lo, f0(x, lo)), (x, hi, f0(x, hi)), (x, hi, f1(x, hi) - b), (x, hi - b, f1(x, hi)), (x, lo + b, f1(x, lo)), (x, lo, f1(x, lo) - b)])
        sm = side if callable(side) else (lambda x, y: side)
        verts = [v for r in rings for v in r]; faces = []; mats = []; n = 6
        for i in range(len(rings) - 1):
            xm = (rings[i][0][0] + rings[i + 1][0][0]) / 2
            for k in range(n):
                j = (k + 1) % n
                faces.append([i * n + k, (i + 1) * n + k, (i + 1) * n + j, i * n + j])
                if k == 0:
                    mats.append(bottom or sm(xm, 0))
                elif k == 3:
                    mats.append(top or sm(xm, 0))
                else:
                    mats.append(sm(xm, rings[i][1][1] if k in (1, 2) else rings[i][0][1]))
        faces.append(list(range(n))); mats.append(sm(xs[0], 0))
        last = (len(rings) - 1) * n; faces.append([last + k for k in range(n)][::-1]); mats.append(sm(xs[-1], 0))
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


def to_object(m, mats, order, sharp_degrees=38.0):
    """A Blender object from a Mesh: materials in the kit's order, smooth shading split at sharp_degrees, planar UVs
    in half metres. Returns the object and its material names."""
    names = sorted(set(m.mats), key=list(order).index)
    data = bpy.data.meshes.new(m.name)
    data.from_pydata(m.verts, [], [list(f) for f in m.faces]); data.update()
    for n in names:
        data.materials.append(mats[n])
    index = {n: i for i, n in enumerate(names)}
    data.polygons.foreach_set('material_index', [index[n] for n in m.mats])
    data.polygons.foreach_set('use_smooth', [True] * len(data.polygons))
    data.set_sharp_from_angle(angle=math.radians(sharp_degrees))
    uv = data.uv_layers.new(name='UVMap')
    for face in data.polygons:
        drop = max(range(3), key=lambda i: abs(face.normal[i])); axes = [i for i in range(3) if i != drop]
        for li in face.loop_indices:
            co = data.vertices[data.loops[li].vertex_index].co
            uv.data[li].uv = (co[axes[0]] * 0.5, co[axes[1]] * 0.5)
    data.update()
    obj = bpy.data.objects.new(m.name, data); bpy.context.collection.objects.link(obj)
    return obj, names
