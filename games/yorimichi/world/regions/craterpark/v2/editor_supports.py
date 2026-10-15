"""Supports for the owner's editor park: stone viaducts, after the approved Sunburst design
(assets/craterpark/concepts/editor/support-design-viaduct.jpg).

Every ramp rides on one arcade as wide as the ramp: solid piers of dark basalt masonry, battered wider toward their
foot, linked by round arches whose crowns sit a constant ring below the ramp, so the stone always meets the wood in one
clean line. A few piers per piece (SPAN_MIN to SPAN_MAX apart, wider for the high pieces), never a forest of posts; a
run too low for an arch rests on a solid wall. Where another piece passes underneath, the arcade lifts clear of it and
no pier stands there.

The arcade is lofted along the piece's own stations, its top just under the piece's underside (the pieces' own
vertices) and its foot sunk into the cut ground the volcano follows, so nothing floats. Bowls (in their own pits) and
decks get none.
"""
import math

import numpy as np

from . import dsl

STONE = 'material_029'        # basalt ashlar masonry, a world-aligned Sunburst painting (tools/craterpark_textures.py)

DS = 1.               # metres between loft sections along a piece
INSET = .4            # the arcade is this much narrower than the piece on each side
SINK = 2.             # the arcade goes this far into the ground (the volcano samples the cut ground every 5 m)
EMBED = -.25          # its top stops just under the ramp (the pieces are single sheets, no thickness)
MIN_BODY = 1.         # metres of stone at least, or no arcade at that section
SPAN_MIN, SPAN_MAX = 12., 30.   # clear arch openings, scaled with the piece's clearance
PIER_MIN, PIER_MAX = 4., 7.     # pier thickness along the piece
BATTER = .05          # each pier side leans out this much per metre down to its foot
BATTER_MAX = 6.       # metres: at most
RING_MIN, RING_MAX = 1.6, 3.5   # stone kept above an arch's crown
MIN_RISE = 2.        # an opening lower than this is left solid
OVER = 2.5            # metres kept clear above another piece running underneath
TIER = 26.           # an opening taller than this gets a lower tier of arches (as an aqueduct's)
TALL_BLOCK = 25.     # a stretch too short for a span but this tall gets one arch through it
# the concept's relief (support-design-viaduct.jpg): piers standing proud of the faces, arch rings, a cornice under the
# ramp, plinths and boulders at the feet
ROCK = 'material_027'         # the volcano's restyled rock, for the boulders round the feet
PROUD = .35           # the top of a pier stands this far out of the arcade's faces
SETBACK = .3          # each ledge up a pier steps in this much (so its lower stages stand further out)
CORNER = .8           # rounded pier corners (radius, m)
PLINTH = .8           # a pier's plinth rises this far above the highest ground under it...
PLINTH_OUT = .5       # ...and steps out this much round it
CORNICE = 1.1         # the cornice band under the ramp: its height...
OVERHANG = .45        # ...and how far it stands out of the faces (just under the ramp's edge)
RING_DEPTH = 1.1      # the arch rings (archivolts): their depth round the opening...
RING_PROUD = .2       # ...and how far they stand out of the faces


class Ground:
    """Bilinear lookup in the cut-ground grid (native y at native x, z)."""

    def __init__(self, heights, grid):
        self.H, self.g = np.asarray(heights, 'f8').reshape(grid['nz'], grid['nx']), grid

    def __call__(self, x, z):
        g = self.g
        fi = np.clip((np.asarray(x) - g['x0']) / g['G'] - .5, 0, g['nx'] - 1.001)
        fj = np.clip((np.asarray(z) - g['z0']) / g['G'] - .5, 0, g['nz'] - 1.001)
        i, j = np.floor(fi).astype(int), np.floor(fj).astype(int)
        a, c = fi - i, fj - j
        H = self.H
        return ((1 - a) * (1 - c) * H[j, i] + a * (1 - c) * H[j, i + 1]
                + (1 - a) * c * H[j + 1, i] + a * c * H[j + 1, i + 1])


class Plan:
    """Every kept piece's triangles hashed on a plan grid: the piece surfaces right above or below any point."""

    def __init__(self, pieces, cell=4.):
        tris, owner = [], []
        for k, p in enumerate(pieces):
            T = np.asarray(p.mesh.V, 'f8')[np.asarray(p.mesh.F)]
            tris.append(T)
            owner.append(np.full(len(T), k))
        self.T, self.owner, self.cell = np.concatenate(tris), np.concatenate(owner), cell
        lo = np.floor(self.T[:, :, [0, 2]].min(1) / cell).astype(int)
        hi = np.floor(self.T[:, :, [0, 2]].max(1) / cell).astype(int)
        cells = {}
        for t, (i0, j0), (i1, j1) in zip(range(len(self.T)), lo, hi):
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    cells.setdefault((i, j), []).append(t)
        self.cells = {key: np.array(v) for key, v in cells.items()}

    def heights(self, x, z):
        """(piece, y) of every piece surface straight above or below the point."""
        t = self.cells.get((math.floor(x / self.cell), math.floor(z / self.cell)))
        if t is None:
            return np.zeros(0, int), np.zeros(0)
        T = self.T[t]
        a, b, c = T[:, 0], T[:, 1], T[:, 2]
        e1, e2 = (b - a)[:, [0, 2]], (c - a)[:, [0, 2]]
        q = np.array([x, z]) - a[:, [0, 2]]
        det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
        ok = np.abs(det) > 1e-9                         # vertical faces have no plan area
        det = np.where(ok, det, 1.)
        u = (q[:, 0] * e2[:, 1] - q[:, 1] * e2[:, 0]) / det
        v = (e1[:, 0] * q[:, 1] - e1[:, 1] * q[:, 0]) / det
        hit = ok & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6)
        y = a[:, 1] + u * (b[:, 1] - a[:, 1]) + v * (c[:, 1] - a[:, 1])
        return self.owner[t][hit], y[hit]

    def span(self, x, z, piece):
        """(underside of `piece` above the point, highest surface of any other piece below that underside) or None."""
        who, y = self.heights(x, z)
        own = y[who == piece]
        if not len(own):
            return None
        under = own.min()
        other = y[(who != piece) & (y < under)]
        return under, (other.max() if len(other) else -np.inf)


def _orient(V, F, N):
    """Faces counter-clockwise seen from their normal's side."""
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    flip = (np.cross(b - a, c - a) * (N[F[:, 0]] + N[F[:, 1]] + N[F[:, 2]])).sum(1) < 0
    F = F.copy()
    F[flip] = F[flip][:, [0, 2, 1]]
    return F


class Builder:
    def __init__(self):
        self.parts = {}

    def add(self, material, VFN):
        V, F, N = VFN
        self.parts.setdefault(material, []).append(VFN)

    def meshes(self, feature):
        out = []
        for material, items in self.parts.items():
            V, F, N, base = [], [], [], 0
            for v, f, n in items:
                V.append(v), F.append(f + base), N.append(n)
                base += len(v)
            V, F, N = np.concatenate(V), np.concatenate(F), np.concatenate(N)
            F = _orient(V, F, N)
            ax = np.abs(N).argmax(1)
            UV = np.where(ax[:, None] == 1, V[:, [0, 2]], np.where(ax[:, None] == 0, V[:, [2, 1]], V[:, [0, 1]])) / 4.
            out.append(dsl.Mesh.part(V, F, N=N, UV=UV, role=dsl.SIDE, material=material, feature=feature))
        return out


def _outer_half(s):
    """Half the piece's full width at a station: floor, wall reach and coping deck on each side."""
    reach = []
    for w in (s['wl'], s['wr']):
        h, R = w['h'], max(w['R'], 1e-3)
        reach.append(R if h >= R else R * math.sin(math.acos(max(-1., 1 - h / R))))
    return s['w'] / 2 + max(reach) + s.get('deck', 0)


def _rand(*key):
    """Deterministic uniform [0, 1) from a position: the same park always gets the same stones."""
    h = 2166136261
    for k in key:
        h = ((h ^ (int(round(k * 100)) & 0xffffffff)) * 16777619) & 0xffffffff
    return ((h * 2654435761) & 0xffffffff) / 2 ** 32


def _rings(b, material, rings, normals=None):
    """Loft through closed cross-sections (each (k, 3)), with end caps: flat faces outward, or the given per-ring
    vertex normals (each (k, 3)) on the sides for a smooth (rounded) surface."""
    V, F, N = [], [], []
    for i in range(len(rings) - 1):
        A, B = rings[i], rings[i + 1]
        mid = np.concatenate([A, B]).mean(0)
        k = len(A)
        for e in range(k):
            q = np.array([A[e], A[(e + 1) % k], B[(e + 1) % k], B[e]])
            n = np.cross(q[1] - q[0], q[2] - q[0]) + np.cross(q[2] - q[0], q[3] - q[0])
            size = np.linalg.norm(n)
            if size < 1e-6:
                continue
            n = n / size
            if n @ (q.mean(0) - mid) < 0:
                n = -n
            o = len(V)
            V.extend(q)
            if normals is not None:
                N.extend([normals[i][e], normals[i][(e + 1) % k], normals[i + 1][(e + 1) % k], normals[i + 1][e]])
            else:
                N.extend([n] * 4)
            F.extend([(o, o + 1, o + 2), (o, o + 2, o + 3)])
    for R, other in ((rings[0], rings[1]), (rings[-1], rings[-2])):
        out = R.mean(0) - other.mean(0)
        size = np.linalg.norm(out)
        if size < 1e-9:
            continue
        o = len(V)
        V.extend([R.mean(0)] + list(R))
        N.extend([out / size] * (len(R) + 1))
        F.extend([(o, o + 1 + e, o + 1 + (e + 1) % len(R)) for e in range(len(R))])
    if F:
        b.add(material, (np.array(V, 'f8'), np.array(F, 'i8'), np.array(N, 'f8')))


def _rounded(c, fwd, acr, a, w, y, r=CORNER, seg=3):
    """A rounded rectangle at height y, `a` long (half, along fwd) and `w` wide (half, along acr): points and their
    outward horizontal normals."""
    r = min(r, a * .9, w * .9)
    pts, nrm = [], []
    for su, sv, a0 in ((1, 1, 0.), (-1, 1, .5 * np.pi), (-1, -1, np.pi), (1, -1, 1.5 * np.pi)):
        for k in range(seg + 1):
            ang = a0 + .5 * np.pi * k / seg
            du, dv = math.cos(ang), math.sin(ang)
            u, v = su * (a - r) + r * du, sv * (w - r) + r * dv
            pts.append((c[0] + u * fwd[0] + v * acr[0], y, c[1] + u * fwd[1] + v * acr[1]))
            nrm.append((du * fwd[0] + dv * acr[0], 0., du * fwd[1] + dv * acr[1]))
    return np.array(pts), np.array(nrm)


def _lean(s, y):
    """The arcade's half width at height y in section s: its faces lean out BATTER per metre below the ramp."""
    return s.half + min(BATTER * max(s.top - y, 0.), BATTER_MAX)


_ICO = None


def _boulder(b, plan, ground, x, z, r, seed):
    """A half-buried, faceted boulder of radius r at (x, z); none where a piece lies within reach above the ground."""
    global _ICO
    g = float(ground(x, z))
    who, y = plan.heights(x, z)
    if len(y) and (y < g + 2.5 * r + 1.).any():
        return 0
    if _ICO is None:
        t = (1 + 5 ** .5) / 2
        P = np.array([(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
                      (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)], 'f8')
        F = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6),
             (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10),
             (8, 6, 7), (9, 8, 1)]
        P = list(P / np.linalg.norm(P[0]))
        mids, F2 = {}, []
        for a, bb, c in F:                                   # one subdivision: 80 faces
            m = []
            for i, j in ((a, bb), (bb, c), (c, a)):
                key = (min(i, j), max(i, j))
                if key not in mids:
                    q = P[i] + P[j]
                    P.append(q / np.linalg.norm(q))
                    mids[key] = len(P) - 1
                m.append(mids[key])
            F2 += [(a, m[0], m[2]), (bb, m[1], m[0]), (c, m[2], m[1]), (m[0], m[1], m[2])]
        _ICO = np.array(P), np.array(F2)
    P, F = _ICO
    bump = np.array([1 + .32 * (_rand(seed, i, 7.) - .5) for i in range(len(P))])
    yaw = _rand(seed, 3.) * 2 * np.pi
    S = P * bump[:, None] * [r * (1 + .3 * _rand(seed, 5.)), r * .62, r]
    S = S @ np.array([[math.cos(yaw), 0, -math.sin(yaw)], [0, 1, 0], [math.sin(yaw), 0, math.cos(yaw)]])
    S += [x, g - .3 * r, z]
    T = S[F]
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    b.add(ROCK, (T.reshape(-1, 3), np.arange(len(F) * 3).reshape(-1, 3), np.repeat(n, 3, axis=0)))
    return 1


def _samples(stations):
    """The piece resampled every DS metres: d, x, z, heading (radians) and the arcade's half width; None if too short."""
    d = np.array([s['d'] for s in stations], 'f8')
    if len(d) < 2 or d[-1] - d[0] < 3 * DS:
        return None
    t = np.arange(d[0], d[-1] + 1e-6, DS)
    if t[-1] < d[-1] - 1e-6:
        t = np.append(t, d[-1])
    h = np.interp(t, d, np.unwrap(np.radians([s['h'] for s in stations])))
    half = np.interp(t, d, [_outer_half(s) - INSET for s in stations])
    return t, np.interp(t, d, [s['x'] for s in stations]), np.interp(t, d, [s['z'] for s in stations]), h, half


class Section:
    """What the arcade meets at one sample: the underside on each side, the ground, and any piece running below."""

    def __init__(self, plan, ground, piece, x, z, h, half):
        self.c, self.across, self.half = np.array([x, z]), np.array([-math.sin(h), math.cos(h)]), half
        under, self.over = {}, -np.inf
        for v in (-1., -.5, 0., .5, 1.):
            got = plan.span(*(self.c + v * half * self.across), piece)
            if got is None:
                self.ok = False
                return
            under[v], self.over = got[0], max(self.over, got[1])
        self.top_l = min(under[-1.], under[-.5], under[0.]) + EMBED
        self.top_r = min(under[0.], under[.5], under[1.]) + EMBED
        self.top = min(self.top_l, self.top_r)
        g = [float(ground(*(self.c + v * half * self.across))) for v in (-1., -.5, 0., .5, 1.)]
        self.g_lo, self.g_hi = min(g), max(g)
        self.blocked = self.over > self.g_lo - SINK           # another piece runs between the ground and this one
        self.lo = self.over + OVER if self.blocked else self.g_lo - SINK
        self.ok = self.top - self.lo >= MIN_BODY and self.top - self.g_hi > .5

    def foot(self, ground):
        """A pier's foot level: its lowest level, sunk under the ground at its battered corners too."""
        if self.blocked:
            return self.lo
        wide = self.half + min(BATTER * max(self.top - self.lo, 0.), BATTER_MAX)
        return min(self.lo, min(float(ground(*(self.c + v * wide * self.across))) for v in (-1., 1.)) - SINK)


def _piers(ts, blocked, clear):
    """Sample index ranges [(i0, i1)] of the piers along one stretch of arcade, about one span apart; a pier that
    would stand on another piece moves aside, or is left out."""
    n = len(ts)
    span = float(np.clip(.8 * clear, SPAN_MIN, SPAN_MAX))
    pier = float(np.clip(3. + .06 * clear, PIER_MIN, PIER_MAX))
    length = ts[-1] - ts[0]
    if length <= 2 * pier + .6 * SPAN_MIN:
        if clear > TALL_BLOCK and length >= 16.:              # a tall block: one arch through it
            w = max(2, int(round(.3 * length / DS)))
            return [(0, w), (n - 1 - w, n - 1)]
        return [(0, n - 1)]                                   # too short for an arch: one solid block
    gaps = max(1, int(round((length - pier) / (span + pier))))
    step = (length - pier) / gaps
    w = max(1, int(round(pier / DS)))
    out = []
    for k in range(gaps + 1):
        centre = ts[0] + pier / 2 + k * step
        i = int(np.argmin(np.abs(ts - centre)))
        for shift in sorted(range(-int(step / 3 / DS), int(step / 3 / DS) + 1), key=abs):
            i0 = min(max(i + shift - w // 2, 0), n - 1 - w)
            if not blocked[i0:i0 + w + 1].any():
                out.append((i0, i0 + w))
                break
    merged = []
    for a, b in out:
        if merged and a - merged[-1][1] < 3:                  # no room for an arch between them
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def _arch(secs, ts, f0, f1, top0=None, top1=None):
    """The intrados over the opening between samples f0 and f1 (pier faces), per sample f0..f1, or None if too low.
    The arch rakes with the ramp: its crown stays a ring's depth under the line between the two pier tops (top0 and
    top1 for a lower tier, whose band is level with them)."""
    a, b = secs[f0], secs[f1]
    top0 = a.top if top0 is None else top0
    top1 = b.top if top1 is None else top1
    half = (ts[f1] - ts[f0]) / 2
    ring = float(np.clip(.12 * 2 * half, RING_MIN, RING_MAX))
    rise = min(half, top0 - ring - a.g_hi, top1 - ring - b.g_hi)
    if rise < MIN_RISE:
        return None
    radius = (half * half + rise * rise) / (2 * rise)
    mid = (ts[f0] + ts[f1]) / 2
    out = []
    for k in range(f0, f1 + 1):
        line = top0 + (top1 - top0) * (ts[k] - ts[f0]) / (2 * half)
        arc = math.sqrt(max(radius * radius - (ts[k] - mid) ** 2, 0.)) - (radius - rise)
        y = min(line - ring - rise + arc, min(secs[k].top, line) - RING_MIN)
        out.append(max(y, secs[k].lo))
    return out


def _tiers(secs, ts, f0, f1, arc):
    """Lower tiers under a tall opening: each a level band halfway down with its own arch, while room remains.
    [(band top per sample f0..f1, intrados per sample)]."""
    out = []
    while min(arc[0] - secs[f0].g_hi, arc[-1] - secs[f1].g_hi) > TIER:
        t0 = secs[f0].g_hi + .5 * (arc[0] - secs[f0].g_hi)
        t1 = secs[f1].g_hi + .5 * (arc[-1] - secs[f1].g_hi)
        lower = _arch(secs, ts, f0, f1, t0, t1)
        if lower is None:
            break
        band = [t0 + (t1 - t0) * (ts[k] - ts[f0]) / (ts[f1] - ts[f0]) for k in range(f0, f1 + 1)]
        out.append((band, lower))
        arc = lower
    return out


def _loft(b, rows):
    """Loft the arcade through its sections [(Section, bottom[, top left, top right])], with flat-shaded closed faces.
    Its sides lean out BATTER per metre below the ramp, so piers, arches and tiers share one battered face."""
    corners = []
    for s, bot, *top in rows:
        (x, z), u = s.c, s.across
        top_l, top_r = top or (s.top_l, s.top_r)
        lean = lambda y: s.half + min(BATTER * max(s.top - y, 0.), BATTER_MAX)   # one battered plane each side
        wl, wr, wb = lean(top_l), lean(top_r), lean(bot)
        corners.append(np.array([(x - wb * u[0], bot, z - wb * u[1]), (x + wb * u[0], bot, z + wb * u[1]),
                                 (x + wr * u[0], top_r, z + wr * u[1]), (x - wl * u[0], top_l, z - wl * u[1])]))
    V, F, N = [], [], []

    def quad(q, outward):
        n = np.cross(q[1] - q[0], q[2] - q[0]) + np.cross(q[2] - q[0], q[3] - q[0])
        size = np.linalg.norm(n)
        if size < 1e-6:
            return
        n = n / size
        if n @ outward < 0:
            n = -n
        o = len(V)
        V.extend(q), N.extend([n] * 4), F.extend([(o, o + 1, o + 2), (o, o + 2, o + 3)])

    for i in range(len(rows) - 1):
        A, B = corners[i], corners[i + 1]
        fwd = np.array([*(rows[i + 1][0].c - rows[i][0].c)])[[0, 0, 1]] * [1, 0, 1]
        if np.linalg.norm(fwd) < 1e-9:                       # a pier face: both sections at one sample
            s = rows[i][0]
            fwd = np.array([-s.across[1], 0., s.across[0]]) * (1 if rows[i + 1][1] > rows[i][1] else -1)
            for e in range(4):
                quad(np.array([A[e], A[(e + 1) % 4], B[(e + 1) % 4], B[e]]), fwd)
            continue
        mid = np.concatenate([A, B]).mean(0)
        for e in range(4):
            q = np.array([A[e], A[(e + 1) % 4], B[(e + 1) % 4], B[e]])
            quad(q, q.mean(0) - mid)
    for C, sign, k in ((corners[0], -1, 0), (corners[-1], 1, -1)):
        s = rows[k][0]
        quad(C, sign * np.array([-s.across[1], 0., s.across[0]]))
    if F:
        b.add(STONE, (np.array(V, 'f8'), np.array(F, 'i8'), np.array(N, 'f8')))


def _at(S, ts, t):
    """The arcade's frame at distance t along a stretch: centre (x, z), across (unit), the section nearest."""
    i = int(np.clip(np.searchsorted(ts, t) - 1, 0, len(ts) - 2))
    f = float(np.clip((t - ts[i]) / max(ts[i + 1] - ts[i], 1e-9), 0., 1.))
    c = S[i].c * (1 - f) + S[i + 1].c * f
    u = S[i].across * (1 - f) + S[i + 1].across * f
    return c, u / np.linalg.norm(u), S[i if f < .5 else i + 1]


def _pier(b, plan, ground, S, ts, a, c):
    """A pier over samples a..c: rounded stages standing proud of the faces, stepping in at a ledge or two on the
    way up to the cornice, on a plinth, with boulders round its foot. Returns the boulders placed."""
    mid = (ts[a] + ts[c]) / 2
    centre, acr, s = _at(S, ts, mid)
    fwd = np.array([acr[1], -acr[0]])
    half_len = max((ts[c] - ts[a]) / 2, 1.5)
    top = min(min(S[j].top_l, S[j].top_r) for j in range(a, c + 1)) - CORNICE + .1
    corners = [centre + u * fwd + v * acr for u in (-half_len, half_len) for v in (-s.half, s.half)]
    g_hi = max(float(ground(*q)) for q in corners)
    foot = min(float(ground(*q)) for q in corners) - SINK - 1.
    base = g_hi + PLINTH
    if top - base < 1.5:
        return 0
    height = top - base
    stages = 1 + (height > 14.) + (height > 32.)
    out = PROUD + (stages - 1) * SETBACK

    def block(y0, y1, extra):
        rings, normals = [], []
        for y in (y0, y1):
            along = half_len + .5 * BATTER * max(top - y, 0.) + extra
            pts, nrm = _rounded(centre, fwd, acr, along, _lean(s, y) + extra, y)
            rings.append(pts)
            normals.append(nrm)
        _rings(b, STONE, rings, normals)

    block(foot, base, out + PLINTH_OUT)
    for k in range(stages):
        y0 = base + height * k / stages
        y1 = base + height * (k + 1) / stages
        block(y0 - (.05 if k else 0.), y1, out - k * SETBACK)
    placed = 0
    n = 3 + min(6, int(height / 8))
    for k in range(n):
        ang = 2 * np.pi * (k + _rand(mid, k, 1.)) / n
        reach = np.array([(half_len + out + PLINTH_OUT) * math.cos(ang), (s.half + out + PLINTH_OUT) * math.sin(ang)])
        reach *= 1.05 + .35 * _rand(mid, k, 2.)
        q = centre + reach[0] * fwd + reach[1] * acr
        r = min(.9 + .9 * _rand(mid, k, 3.) + .025 * height, 3.2)
        placed += _boulder(b, plan, ground, q[0], q[1], r, mid * 7 + k)
    return placed


def _archivolt(b, S, ts, f0, f1, arc):
    """The stone ring round an arch: RING_DEPTH deep round the intrados, standing RING_PROUD out of both faces."""
    t = np.asarray(ts[f0:f1 + 1], 'f8')
    y = np.asarray(arc, 'f8')
    if len(t) < 4:
        return
    dt, dy = np.gradient(t), np.gradient(y)
    norm = np.hypot(dt, dy)
    nt, ny = -dy / norm, dt / norm
    rings = []
    for k in range(len(t)):
        c_in, u_in, s = _at(S, ts, t[k])
        c_out, u_out, _ = _at(S, ts, t[k] + RING_DEPTH * nt[k])
        y_out = y[k] + RING_DEPTH * ny[k]
        w_in, w_out = _lean(s, y[k]) + RING_PROUD, _lean(s, y_out) + RING_PROUD
        rings.append(np.array([(c_in[0] - w_in * u_in[0], y[k], c_in[1] - w_in * u_in[1]),
                               (c_in[0] + w_in * u_in[0], y[k], c_in[1] + w_in * u_in[1]),
                               (c_out[0] + w_out * u_out[0], y_out, c_out[1] + w_out * u_out[1]),
                               (c_out[0] - w_out * u_out[0], y_out, c_out[1] - w_out * u_out[1])]))
    _rings(b, STONE, rings)


def _cornice(b, S):
    """The cornice band along the top of a stretch: it stands OVERHANG out of the faces, a bevel below it."""
    rings = []
    for s in S:
        (x, z), u = s.c, s.across
        yb = s.top - CORNICE
        wall, out = _lean(s, yb) - .05, s.half + OVERHANG
        prof = [(-wall, yb), (-out, yb + .45 * CORNICE), (-out, s.top_l), (out, s.top_r), (out, yb + .45 * CORNICE),
                (wall, yb)]
        rings.append(np.array([(x + v * u[0], y, z + v * u[1]) for v, y in prof]))
    _rings(b, STONE, rings)


def arcade(b, plan, ground, piece, stations):
    """The viaduct under one piece: (piers, arches, metres of arcade, boulders)."""
    got = _samples(stations)
    if got is None:
        return 0, 0, 0., 0
    t, x, z, h, half = got
    secs = [Section(plan, ground, piece, *a) for a in zip(x, z, h, half)]
    piers = arches = rocks = 0
    metres = 0.
    k, n = 0, len(secs)
    while k < n:                                              # stretches of consecutive good sections
        if not secs[k].ok:
            k += 1
            continue
        e = k
        while e + 1 < n and secs[e + 1].ok:
            e += 1
        if e - k >= 2:
            S, ts = secs[k:e + 1], t[k:e + 1]
            clear = float(np.median([s.top - s.g_hi for s in S]))
            rows, P = [], _piers(ts, np.array([s.blocked for s in S]), clear)
            first, last = P[0][0], P[-1][1]
            # a stretch's ends beyond its first and last piers spring from the stretch end
            spans = ([(0, first)] if first > 1 else []) + [(P[j][1], P[j + 1][0]) for j in range(len(P) - 1)] \
                + ([(last, len(S) - 1)] if last < len(S) - 2 else [])
            bots = {}
            for f0, f1 in spans:
                arc = _arch(S, ts, f0, f1)
                if arc is not None:
                    bots[(f0, f1)] = arc
                    arches += 1
                    _archivolt(b, S, ts, f0, f1, arc)
                    for band, lower in _tiers(S, ts, f0, f1, arc):
                        _loft(b, [(S[j], lower[j - f0], band[j - f0], band[j - f0])
                                  for j in range(f0, f1 + 1)])
                        _archivolt(b, S, ts, f0, f1, lower)
                        arches += 1
            solid = np.ones(len(S), bool)
            for f0, f1 in bots:
                solid[f0 + 1:f1] = False
            i = 0
            while i < len(S):
                if solid[i]:
                    rows.append((S[i], S[i].foot(ground)))
                    i += 1
                    continue
                f0 = i - 1
                f1 = next(f for a, f in bots if a == f0)
                arc = bots[(f0, f1)]
                for j in range(f0, f1 + 1):
                    rows.append((S[j], arc[j - f0]))
                i = f1
            _loft(b, rows)
            _cornice(b, S)
            if bots:
                for a, c in P:
                    if c - a >= 1 and not any(S[j].blocked for j in range(a, c + 1)):
                        rocks += _pier(b, plan, ground, S, ts, a, c)
                        piers += 1
            # boulders along the foot of the solid walls
            for j in range(0, len(S), 6):
                if solid[j] and not S[j].blocked and S[j].top - S[j].g_hi > 1.:
                    for side in (-1., 1.):
                        if _rand(ts[j], side, 4.) < .55:
                            q = S[j].c + side * (_lean(S[j], S[j].g_lo) + .3 + _rand(ts[j], side, 5.)) * S[j].across
                            rocks += _boulder(b, plan, ground, q[0], q[1], .7 + .8 * _rand(ts[j], side, 6.),
                                              ts[j] * 3 + side)
            metres += ts[-1] - ts[0]
        k = e + 1
    return piers, arches, metres, rocks


def build(pieces, heights, grid):
    """The supports for the kept editor pieces (bridge Pieces), as dsl Mesh parts, and a summary."""
    ground = Ground(heights, grid)
    plan = Plan(pieces)
    out, summary = [], {'piers': 0, 'arches': 0, 'metres': 0., 'boulders': 0, 'pieces': {}}
    for k, piece in enumerate(pieces):
        meta = piece.metadata
        if meta['type'] in ('bowl', 'deck', 'rail') or not meta.get('stations'):
            continue
        b = Builder()
        piers, arches, metres, rocks = arcade(b, plan, ground, k, meta['stations'])
        if not metres:
            continue
        out += b.meshes(f"{meta['id']}_supports")
        summary['piers'] += piers
        summary['arches'] += arches
        summary['boulders'] += rocks
        summary['metres'] += round(metres, 1)
        summary['pieces'][meta['id']] = 'viaduct'
    summary['metres'] = round(summary['metres'], 1)
    return out, summary
