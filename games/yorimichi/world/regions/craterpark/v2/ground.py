"""The ground landform every feature stands on (plan/pipeline.md 4.15, 6), native metres, y up.

ground(outline, holes, controls) -> dsl.Mesh: one continuous sculpted surface over the site.
- `holes` are the features' foot loops, their exact 3D seam vertices: the ground uses them as its own boundary, so
  every seam conforms (no T-junction, no crack), nothing is buried under the ground and nothing overlaps it.
- Heights: a harmonic field (multigrid raster solve, Dirichlet on the outline, the foot loops and the control points),
  then relaxed on the mesh itself with the seam vertices fixed, so the surface meets every foot loop exactly.
- Plan mesh: a constrained Delaunay triangulation (cdt.py) of the seam vertices plus graded interior points: spacing
  = the nearest seam segment's length + grade x distance, never over `coarse`, and finer where the field curves
  (the chord rule of `tess`).
- A `skirt` deep wall (role side) round the outline and a base (role base, never drawn) close the site, so the ground
  plus its features is one closed surface.
"""
import math

import numpy as np

from . import cdt, dsl


# ---------------------------------------------------------------- plan geometry helpers
def _loop2(loop):
    loop = np.asarray(loop, 'f8')
    return loop[:, [0, 2]] if loop.shape[1] == 3 else loop


def _segments(loops):
    A = np.concatenate([lp for lp in loops]); B = np.concatenate([np.roll(lp, -1, 0) for lp in loops])
    return A, B


def signed_area(p):
    p = np.asarray(p, 'f8')
    return .5 * np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])


def seg_distance(Q, A, B, reach, bucket=4.):
    """Distance from each point Q (n, 2) to the nearest segment A-B (s, 2) within `reach` (inf beyond), and that
    segment's length. Bucketed by candidate pairs (bounded memory)."""
    Q = np.asarray(Q, 'f8'); n = len(Q)
    best = np.full(n, np.inf); length = np.full(n, np.inf)
    if not len(A) or not n:
        return best, length
    lo = np.floor((np.minimum(A, B) - reach) / bucket).astype('i8'); hi = np.floor((np.maximum(A, B) + reach) / bucket).astype('i8')
    size = hi - lo + 1; count = size.prod(1)
    owner = np.repeat(np.arange(len(A)), count)
    local = np.arange(count.sum()) - np.repeat(np.cumsum(count) - count, count)
    cells = lo[owner] + np.stack([local % size[owner, 0], local // size[owner, 0]], 1)
    keys = (cells[:, 0] + (1 << 30)) * (1 << 31) + (cells[:, 1] + (1 << 30))
    order = np.argsort(keys, kind='stable'); keys, owner = keys[order], owner[order]
    qc = np.floor(Q / bucket).astype('i8'); qk = (qc[:, 0] + (1 << 30)) * (1 << 31) + (qc[:, 1] + (1 << 30))
    first = np.searchsorted(keys, qk, 'left'); last = np.searchsorted(keys, qk, 'right')
    reps = last - first; total = np.cumsum(reps)
    cuts = np.unique(np.concatenate([[0], np.searchsorted(total, np.arange(1_000_000, total[-1] if n else 0, 1_000_000)), [n]]))
    L = np.linalg.norm(B - A, axis=1)
    for i0, i1 in zip(cuts[:-1], cuts[1:]):
        r = reps[i0:i1]
        if not r.sum():
            continue
        which = np.repeat(np.arange(i0, i1), r)
        cand = owner[np.repeat(first[i0:i1], r) + np.arange(r.sum()) - np.repeat(np.cumsum(r) - r, r)]
        a, b = A[cand], B[cand]; d = b - a
        u = np.clip(((Q[which] - a) * d).sum(1) / np.maximum((d * d).sum(1), 1e-18), 0, 1)
        dist = np.linalg.norm(Q[which] - (a + u[:, None] * d), axis=1)
        o = np.lexsort((dist, which)); w, dd, cc = which[o], dist[o], cand[o]
        firsts = np.r_[True, w[1:] != w[:-1]]
        better = dd[firsts] < best[w[firsts]]
        best[w[firsts][better]] = dd[firsts][better]; length[w[firsts][better]] = L[cc[firsts][better]]
    best[best > reach] = np.inf
    return best, length


def even_odd(Q, loops, band=2.):
    """Mask of the points Q (n, 2) inside the loops by the even-odd rule (a +x ray), in y bands."""
    Q = np.asarray(Q, 'f8'); A, B = _segments(loops)
    inside = np.zeros(len(Q), bool)
    if not len(Q):
        return inside
    ylo, yhi = np.minimum(A[:, 1], B[:, 1]), np.maximum(A[:, 1], B[:, 1])
    k = np.floor(Q[:, 1] / band).astype('i8')
    for kb in np.unique(k):
        pts = np.flatnonzero(k == kb)
        segs = np.flatnonzero((ylo <= (kb + 1) * band) & (yhi >= kb * band))
        if not len(segs):
            continue
        for c in np.array_split(pts, max(1, len(pts) * len(segs) // 2_000_000 + 1)):
            p = Q[c][:, None, :]; a = A[segs][None]; b = B[segs][None]
            straddle = (a[..., 1] > p[..., 1]) != (b[..., 1] > p[..., 1])
            with np.errstate(divide='ignore', invalid='ignore'):
                x = a[..., 0] + (p[..., 1] - a[..., 1]) * (b[..., 0] - a[..., 0]) / (b[..., 1] - a[..., 1])
            inside[c] = (straddle & (x > p[..., 0])).sum(1) % 2 == 1
    return inside


# ---------------------------------------------------------------- the height field
class Field:
    """A raster height field over a box: Dirichlet constraints, multigrid-cascade harmonic solve, bilinear sampling,
    curvature."""

    def __init__(self, lo, hi, cell):
        self.cell = cell
        self.lo = np.floor(np.asarray(lo, 'f8') / cell) * cell - 2 * cell
        n = np.ceil((np.asarray(hi, 'f8') - self.lo) / cell).astype(int) + 3
        self.n = (int(n[0]), int(n[1]))
        self.h = None

    def index(self, p):
        return np.floor((np.asarray(p, 'f8') - self.lo) / self.cell).astype('i8')

    def solve(self, points, values, iterations=80, blend=None):
        """Harmonic heights with the cells holding `points` (k, 2) fixed to the mean of their `values`; with `blend`
        (metres), screened: the free field decays to 0 over about that distance."""
        nx, nz = self.n
        idx = self.index(points); ok = (idx >= 0).all(1) & (idx[:, 0] < nx) & (idx[:, 1] < nz)
        idx, values = idx[ok], np.asarray(values, 'f8')[ok]
        flat = idx[:, 0] * nz + idx[:, 1]
        s = np.bincount(flat, values, nx * nz); c = np.bincount(flat, None, nx * nz)
        fixed = (c > 0).reshape(nx, nz); val = np.where(c > 0, s / np.maximum(c, 1), 0.).reshape(nx, nz)
        # pyramid
        levels = [(fixed, val)]
        while min(levels[-1][0].shape) > 8:
            f, v = levels[-1]
            px, pz = f.shape[0] % 2, f.shape[1] % 2
            f2 = np.pad(f, ((0, px), (0, pz))); v2 = np.pad(v * f, ((0, px), (0, pz)))
            cnt = f2.reshape(f2.shape[0] // 2, 2, f2.shape[1] // 2, 2).sum((1, 3))
            sm = v2.reshape(v2.shape[0] // 2, 2, v2.shape[1] // 2, 2).sum((1, 3))
            levels.append((cnt > 0, np.where(cnt > 0, sm / np.maximum(cnt, 1), 0.)))
        f, v = levels[-1]
        h = np.where(f, v, (v[f].mean() if f.any() else 0.) if blend is None else 0.)
        for li in range(len(levels) - 1, -1, -1):
            f, v = levels[li]
            if h.shape != f.shape:
                h = np.repeat(np.repeat(h, 2, 0), 2, 1)[:f.shape[0], :f.shape[1]]
            h = np.where(f, v, h)
            screen = 0. if blend is None else (self.cell * 2 ** li / blend) ** 2
            h = _relax(h, f, v, iterations if li == 0 else 3 * iterations, screen=screen)
        self.h = h
        return h

    def sample(self, p):
        p = (np.asarray(p, 'f8') - self.lo) / self.cell - .5
        i = np.clip(np.floor(p).astype('i8'), 0, np.array(self.n) - 2); f = np.clip(p - i, 0, 1)
        h = self.h
        return ((1 - f[:, 0]) * (1 - f[:, 1]) * h[i[:, 0], i[:, 1]] + f[:, 0] * (1 - f[:, 1]) * h[i[:, 0] + 1, i[:, 1]]
                + (1 - f[:, 0]) * f[:, 1] * h[i[:, 0], i[:, 1] + 1] + f[:, 0] * f[:, 1] * h[i[:, 0] + 1, i[:, 1] + 1])

    def curvature(self):
        """Raster of the largest absolute principal curvature (1/m) of the field (small-slope approximation)."""
        h = np.pad(self.h, 1, mode='edge'); c = self.cell
        hxx = (h[2:, 1:-1] - 2 * h[1:-1, 1:-1] + h[:-2, 1:-1]) / c ** 2
        hzz = (h[1:-1, 2:] - 2 * h[1:-1, 1:-1] + h[1:-1, :-2]) / c ** 2
        hxz = (h[2:, 2:] - h[2:, :-2] - h[:-2, 2:] + h[:-2, :-2]) / (4 * c ** 2)
        m = (hxx + hzz) / 2; r = np.sqrt(((hxx - hzz) / 2) ** 2 + hxz ** 2)
        k = np.maximum(np.abs(m + r), np.abs(m - r))
        # the cells next to a constraint carry the field's kink there: smooth over 3 cells so it reads as a band
        for _ in range(2):
            kp = np.pad(k, 1, mode='edge')
            k = (kp[1:-1, 1:-1] * 4 + kp[2:, 1:-1] + kp[:-2, 1:-1] + kp[1:-1, 2:] + kp[1:-1, :-2]) / 8
        return k

    def raster_sample(self, raster, p):
        i = np.clip(self.index(p), 0, np.array(self.n) - 1)
        return raster[i[:, 0], i[:, 1]]


def _relax(h, fixed, val, iterations, omega=1.85, screen=0.):
    """Red-black SOR on the 5-point (screened) Laplacian with Neumann edges, fixed cells held. `screen` = (cell / L)^2:
    a free value decays to 0 over about L metres away from the fixed cells."""
    nx, nz = h.shape
    ii, jj = np.meshgrid(np.arange(nx), np.arange(nz), indexing='ij')
    colours = [((ii + jj) % 2 == c) & ~fixed for c in (0, 1)]
    for _ in range(iterations):
        for m in colours:
            p = np.pad(h, 1, mode='edge')
            avg = (p[2:, 1:-1] + p[:-2, 1:-1] + p[1:-1, 2:] + p[1:-1, :-2]) / (4 + screen)
            h = np.where(m, h + omega * (avg - h), h)
    return h


class Trend:
    """A smoothing thin-plate spline through control points (x, y, z): the broad landform (the fall line). `smooth`
    trades exactness for smoothness (metres^2 of bending per metre of misfit). With no controls, a constant."""

    def __init__(self, controls, smooth=10., const=0.):
        c = np.asarray(controls, 'f8').reshape(-1, 3)
        self.c = c[:, [0, 2]]; self.const = const
        if len(c) < 3:
            self.w = None; self.const = c[:, 1].mean() if len(c) else const; return
        self.mu = self.c.mean(0); self.sc = max(np.ptp(self.c, 0).max(), 1.)
        q = (self.c - self.mu) / self.sc
        K = self._k(q[:, None] - q[None])
        n = len(q); Pm = np.c_[np.ones(n), q]
        M = np.zeros((n + 3, n + 3)); M[:n, :n] = K + smooth / self.sc ** 2 * np.eye(n); M[:n, n:] = Pm; M[n:, :n] = Pm.T
        sol = np.linalg.solve(M, np.r_[c[:, 1], np.zeros(3)])
        self.w, self.a, self.q = sol[:n], sol[n:], q

    @staticmethod
    def _k(d):
        r2 = (d ** 2).sum(-1)
        return np.where(r2 > 0, .5 * r2 * np.log(np.maximum(r2, 1e-300)), 0.)

    def __call__(self, P):
        P = np.asarray(P, 'f8').reshape(-1, 2)
        if self.w is None:
            return np.full(len(P), self.const)
        out = np.empty(len(P))
        for i in range(0, len(P), max(1, 2_000_000 // len(self.q))):
            q = (P[i:i + 2_000_000 // len(self.q)] - self.mu) / self.sc
            out[i:i + len(q)] = self._k(q[:, None] - self.q[None]) @ self.w + self.a[0] + q @ self.a[1:]
        return out


# ---------------------------------------------------------------- interior points
def _quadtree(lo, hi, size_of, region_of, coarse, hmin):
    """Leaf-cell centres of a quadtree over [lo, hi] split until each cell is no larger than the size field anywhere at
    its centre and corners. `region_of(points)` -> (inside mask, seam distance, seam segment length)."""
    lo = np.asarray(lo, 'f8'); hi = np.asarray(hi, 'f8')
    nx, nz = np.ceil((hi - lo) / coarse).astype(int) + 1
    g = np.stack(np.meshgrid(np.arange(nx), np.arange(nz), indexing='ij'), -1).reshape(-1, 2)
    C = lo + (g + .5) * coarse; s = coarse
    out = []
    corners = np.array([[0, 0], [-.5, -.5], [.5, -.5], [-.5, .5], [.5, .5]])
    while len(C):
        probe = (C[:, None, :] + corners[None] * s).reshape(-1, 2)
        need = size_of(probe).reshape(-1, 5).min(1)
        inside, d, _ = region_of(C)
        outside = ~inside & (d > s * .75)                  # wholly outside the region (or in a hole)
        split = (need < s) & (s / 2 >= hmin) & ~outside
        leaf = ~split & ~outside
        if leaf.any():
            out.append((C[leaf], np.full(leaf.sum(), s)))
        C = (C[split][:, None, :] + np.array([[-.25, -.25], [.25, -.25], [-.25, .25], [.25, .25]])[None] * s).reshape(-1, 2)
        s /= 2
    if not out:
        return np.zeros((0, 2)), np.zeros(0)
    return np.concatenate([p for p, _ in out]), np.concatenate([q for _, q in out])


def _curv_size(field, kappa, tess, P):
    k = field.raster_sample(kappa, P)
    return np.where(k > 1e-9, np.sqrt(8 * tess.chord / np.maximum(k, 1e-9)), np.inf)


def plan_mesh(loops2, *, coarse=8., grade=.35, hmin=.05, size=None, lo=None, hi=None):
    """A graded constrained Delaunay mesh of the region inside loops2[0] and outside the other loops (even-odd), with
    every loop vertex kept: (points (n, 2), faces (m, 3) plan counter-clockwise, loop start offsets). Interior points
    come from a quadtree: spacing = nearest boundary segment length + grade x distance, at most `coarse` and at most
    `size(points)` if given; none closer to the boundary than 0.45 x their spacing (no slivers)."""
    loops2 = [np.asarray(lp, 'f8') for lp in loops2]
    A, B = _segments(loops2)
    lo = loops2[0].min(0) - coarse if lo is None else lo
    hi = loops2[0].max(0) + coarse if hi is None else hi
    reach = coarse / grade + coarse

    def region_of(P):
        d, length = seg_distance(P, A, B, reach)
        return even_odd(P, loops2), d, length

    def size_of(P):
        d, length = seg_distance(P, A, B, reach)
        near = np.maximum(np.where(np.isfinite(length), length, coarse), hmin) + grade * np.where(np.isfinite(d), d, reach)
        out = np.minimum(near, coarse)
        return out if size is None else np.minimum(out, size(P))
    C, s = _quadtree(lo, hi, size_of, region_of, coarse, hmin)
    inside, d, length = region_of(C)
    keep = inside & (d >= np.maximum(.45 * s, .3 * np.where(np.isfinite(length), length, 0.)))
    C, s = C[keep], s[keep]
    # a tiny deterministic jitter: no exact collinear or cocircular lattice runs
    j = np.sin(C @ [12.9898, 78.233]) * 43758.5453
    C = C + (np.stack([j - np.floor(j), (j * 7.31) - np.floor(j * 7.31)], 1) - .5) * 2e-3 * s[:, None]
    counts = [len(lp) for lp in loops2]
    starts = np.cumsum([0] + counts)
    P2 = np.concatenate(loops2 + [C])
    loops = [np.arange(starts[i], starts[i + 1]) for i in range(len(counts))]
    return P2, cdt.triangulate(P2, loops), starts


def fill_mesh(loop, normal, *, coarse=None, grade=.35):
    """A planar polygon through the 3D `loop` (n, 3) (boundary order, not repeated), facing `normal`: (V, F) with the
    loop's vertices first, exactly, then graded interior points (no fans, no slivers)."""
    loop = np.asarray(loop, 'f8'); n = np.asarray(normal, 'f8'); n = n / np.linalg.norm(n)
    a = np.cross(n, [1., 0., 0.] if abs(n[0]) < .9 else [0., 1., 0.]); a /= np.linalg.norm(a); b = np.cross(n, a)
    origin = loop.mean(0)
    p = np.stack([(loop - origin) @ a, (loop - origin) @ b], 1)
    edge = np.linalg.norm(np.diff(np.vstack([p, p[:1]]), axis=0), axis=1)
    coarse = float(np.clip(edge.max() * 2, .25, 1.8)) if coarse is None else coarse
    P2, F, _ = plan_mesh([p], coarse=coarse, grade=grade, hmin=max(edge.min() / 2, 1e-3))
    V = origin + P2[:, :1] * a + P2[:, 1:] * b
    V[:len(loop)] = loop
    t = V[F]
    if (np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]) @ n).sum() < 0:
        F = F[:, ::-1].copy()
    return V, F


# ---------------------------------------------------------------- the ground
def ground(outline, holes=(), controls=(), *, skirt=4., coarse=8., grade=.35, hmin=.05, tess=dsl.GROUND_TESS,
           raster=1., blend=25., smooth=10., feature='ground', material=dsl.GROUND_MAT, side_material=dsl.GROUND_MAT,
           relax=60):
    """The site's ground as a dsl.Mesh (module docstring). `outline` (k, 2|3) the outer loop; `holes` [(k, 3)] the
    features' foot loops (their vertices are kept exactly); `controls` (n, 3) height targets."""
    outline = np.asarray(outline, 'f8')
    o2 = _loop2(outline)
    holes = [np.asarray(h, 'f8') for h in holes]
    h2 = [h[:, [0, 2]] for h in holes]
    loops2 = [o2] + h2
    A, B = _segments(loops2)
    controls = np.asarray(controls, 'f8').reshape(-1, 3)
    lo = o2.min(0) - coarse; hi = o2.max(0) + coarse
    # heights = trend (a smoothing spline through the controls: the broad landform) + residual (a screened harmonic
    # field, Dirichlet on the outline when it has heights and on the foot loops, fading to 0 over `blend` metres)
    trend = Trend(controls, smooth, const=float(np.mean([h[:, 1].mean() for h in holes])) if holes else 0.)
    fpts, fval = [], []

    def dense(loop3):
        a = loop3; b = np.roll(loop3, -1, 0)
        n = np.maximum(1, np.ceil(np.linalg.norm((b - a)[:, [0, 2]], axis=1) / (raster / 3)).astype(int))
        f = np.concatenate([np.arange(k) / k for k in n]); r = np.repeat(np.arange(len(a)), n)
        return a[r] + f[:, None] * (b - a)[r]
    if outline.shape[1] == 3:
        d = dense(outline); fpts.append(d[:, [0, 2]]); fval.append(d[:, 1] - trend(d[:, [0, 2]]))
    for h in holes:
        d = dense(h); fpts.append(d[:, [0, 2]]); fval.append(d[:, 1] - trend(d[:, [0, 2]]))
    if not len(controls) and not holes and outline.shape[1] != 3:
        raise ValueError('ground needs heights: an outline with y, foot loops or controls')
    field = Field(lo, hi, raster)
    if fpts:
        field.solve(np.concatenate(fpts), np.concatenate(fval), blend=blend)
    else:
        field.h = np.zeros(field.n)
    # the curvature of the whole surface, on the raster
    cells = field.lo + (np.stack(np.meshgrid(np.arange(field.n[0]), np.arange(field.n[1]), indexing='ij'), -1)
                        .reshape(-1, 2) + .5) * raster
    residual = field.h
    field.h = residual + trend(cells).reshape(field.n)
    kappa = field.curvature()
    P2, F, starts = plan_mesh([o2] + h2, coarse=coarse, grade=grade, hmin=hmin,
                              size=lambda P: _curv_size(field, kappa, tess, P), lo=lo, hi=hi)
    F = F[:, ::-1].copy()                                 # plan counter-clockwise -> upward faces
    # heights: seam vertices exact, the rest from the field relaxed on the mesh
    nb = starts[-1]
    counts = np.diff(starts)
    y = np.empty(len(P2))
    field.h = residual
    y[:len(o2)] = outline[:, 1] if outline.shape[1] == 3 else field.sample(o2) + trend(o2)
    for i, h in enumerate(holes):
        y[starts[i + 1]:starts[i + 2]] = h[:, 1]
    free = np.arange(nb, len(P2))
    base_y = trend(P2)
    y -= base_y * (np.arange(len(P2)) < nb)          # relax the residual; seam residuals fixed
    y[free] = field.sample(P2[free])
    anchor = y.copy()
    dist = seg_distance(P2, A, B, 3 * coarse)[0]
    alpha = np.clip(np.where(np.isfinite(dist), dist, 3 * coarse) / (3 * coarse), 0, 1) * .3
    del field
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    deg = np.bincount(e[:, 0], minlength=len(P2)).astype('f8')
    for _ in range(relax):
        avg = np.bincount(e[:, 0], y[e[:, 1]], len(P2)) / np.maximum(deg, 1)
        new = (1 - alpha) * avg + alpha * anchor
        y[free] = new[free]
    y = y + base_y
    for i, h in enumerate(holes):                     # exact, not round-tripped through the trend
        y[starts[i + 1]:starts[i + 2]] = h[:, 1]
    if outline.shape[1] == 3:
        y[:len(o2)] = outline[:, 1]
    V = np.stack([P2[:, 0], y, P2[:, 1]], 1)
    surface = dsl.Mesh.part(V, F, material=material, role=dsl.GROUND, feature=feature,
                            UV=P2 / dsl.UV_METRES)
    parts = [surface]
    if skirt:
        top = V[:len(o2)]
        bottom = top - [0., skirt, 0.]
        k = len(o2)
        Vs = np.concatenate([top, bottom])
        Fs = []
        for i in range(k):
            a, b = i, (i + 1) % k
            Fs += [(a, k + a, k + b), (a, k + b, b)]
        Fs = np.asarray(Fs, 'i8')
        # outward: away from the outline's interior
        mid = (top + np.roll(top, -1, 0)) / 2
        t = Vs[Fs]; fn = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        centre = top.mean(0)
        ccw = signed_area(o2) > 0
        tang = (np.roll(top, -1, 0) - top)[:, [0, 2]]
        outward = np.stack([tang[:, 1], -tang[:, 0]], 1) if ccw else np.stack([-tang[:, 1], tang[:, 0]], 1)
        o3 = np.repeat(np.stack([outward[:, 0], np.zeros(k), outward[:, 1]], 1), 2, 0)
        if (fn * o3).sum() < 0:
            Fs = Fs[:, ::-1].copy()
        del mid, centre
        u = np.concatenate([[0.], np.cumsum(np.linalg.norm(np.diff(o2, axis=0), axis=1))])
        UV = np.concatenate([np.stack([u, top[:, 1]], 1), np.stack([u, bottom[:, 1]], 1)]) / dsl.UV_METRES
        side = dsl.Mesh.part(Vs, Fs, material=side_material, role=dsl.SIDE, feature=feature, UV=UV)
        side.N = dsl.vertex_normals(Vs, Fs) * [1, 0, 1]
        side.N /= np.maximum(np.linalg.norm(side.N, axis=1, keepdims=True), 1e-12)
        Fb = cdt.triangulate(o2, [np.arange(k)])          # plan counter-clockwise: downward, as a base faces
        base = dsl.Mesh.part(bottom, Fb, material=side_material, role=dsl.BASE, feature=feature,
                             N=np.broadcast_to([0., -1., 0.], bottom.shape))
        parts += [side, base]
    return dsl.Mesh.concat(parts)


def report(mesh, limit=30.):
    """Slope statistics of the ground faces: max degrees, area over `limit`, total area, triangle count."""
    g = mesh.role == dsl.ROLE[dsl.GROUND]
    n = mesh.face_normals()[g]; a = mesh.areas()[g]
    slope = np.degrees(np.arccos(np.clip(n[:, 1], -1, 1)))
    return {'triangles': int(g.sum()), 'area_m2': float(a.sum()), 'max_slope_deg': float(slope.max()) if len(a) else 0.,
            'area_over_limit_m2': float(a[slope > limit].sum()), 'limit_deg': limit,
            'min_edge_m': float(np.linalg.norm(mesh.triangles()[g] - np.roll(mesh.triangles()[g], 1, 1), axis=2).min())
            if len(a) else 0.}


def boundary_loops(mesh, tol=1e-6):
    """The open boundary loops of a mesh (welded within tol): [(k, 3)] positions in order. A feature built without a
    base gives its foot loop this way."""
    P, F = mesh.welded(tol)
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    key = np.sort(e, 1)
    uniq, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
    open_ = e[cnt[inv.ravel()] == 1]
    nxt = {int(a): int(b) for a, b in open_}
    loops, seen = [], set()
    for s in list(nxt):
        if s in seen:
            continue
        loop = [s]; seen.add(s); v = nxt[s]
        while v != s and v not in seen and v in nxt:
            loop.append(v); seen.add(v); v = nxt[v]
        loops.append(P[loop])
    return loops


def r4_block_controls(spacing=12.):
    """The r4 hillside block's top, sampled every `spacing` metres in native (x, y, z): the fall line the new ground
    keeps (layout.md 1)."""
    from craterpark import placement
    pts = []
    for entry in placement.meshes(placement.GROUND):
        a = placement.arrays(entry)
        pts.append(a['positions'].astype('f8'))
    p = np.concatenate(pts)
    k = np.floor(p[:, [0, 2]] / spacing).astype('i8')
    order = np.lexsort((-p[:, 1], k[:, 1], k[:, 0]))
    k, p = k[order], p[order]
    first = np.r_[True, (k[1:] != k[:-1]).any(1)]
    top = p[first]
    centre = (k[first] + .5) * spacing
    return np.stack([centre[:, 0], top[:, 1], centre[:, 1]], 1)


__all__ = ['ground', 'report', 'boundary_loops', 'r4_block_controls', 'Field', 'seg_distance', 'even_odd']
_ = math
