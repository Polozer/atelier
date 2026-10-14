"""Crater Park v2 primitives (plan/pipeline.md section 4): features built on A's `sweep.sweep` riding sheets, closed
into solids with thick walls, flat caps, banks and a buried base (solids.py), each with its seams and rails.

Every primitive returns a `Built` (mesh: dsl.Mesh, rails: [dsl.Rail], checks: [dict]) whose mesh is watertight on its
welded topology (base faces included) and has no folded face; both are checked before it is returned.

Sides of a feature, where its edge meets lower ground (`Side`):
- `wall`: a vertical wall down to the ground: the solid's own side, as thick as the feature is wide;
- `curb`: a thick wall standing `height` over the riding edge with a flat cap `width` (>= 0.30 m) wide;
- `bank`: a riding slope at `degrees` down to the ground;
- `flush`: the ground or a deck continues at the riding edge (the wall is only a buried closing face).
Wherever the riding edge stands less than FLUSH over the ground, its wall is buried (role base).

Profiles are A's `profile.Profile` (('line', L) is L along the slope). `from_additions` converts the r4 RAMPS table's
profiles, whose ('line', L) is a horizontal run, so the ridden dimensions carry over exactly.
"""
import itertools
import math
from dataclasses import dataclass, field

import numpy as np

from . import coping as coping_mod
from . import dsl, solids
from .curves import Arc, Curve, Line
from .profile import Profile
from .rails import edge_rail
from .sweep import _stations, sweep

FLUSH = .05         # metres: a riding edge this close over the ground meets it flush (no visible wall)
FOOT = .01          # metres a wall's foot lies under a flush edge at least (so the wall never has zero height)
BURY = .3           # metres the base lies under the lowest ground or riding point
MIN_WALL = .30      # metres: a wall or cap's least thickness (I5)


@dataclass
class Side:
    kind: str = 'wall'          # wall, curb, bank, flush
    width: float = .4           # curb: its cap's width
    height: float = .3          # curb: how far it stands over the riding edge
    degrees: float = 30.        # bank: its slope
    material: str = dsl.CONCRETE

    def __post_init__(self):
        if self.kind not in ('wall', 'curb', 'bank', 'flush'):
            raise ValueError(f'unknown side {self.kind!r}')
        if self.kind == 'curb' and self.width < MIN_WALL:
            raise ValueError(f'a curb cap must be at least {MIN_WALL} m wide (I5), not {self.width}')


@dataclass
class Built:
    mesh: dsl.Mesh
    rails: list = field(default_factory=list)
    checks: list = field(default_factory=list)

    @staticmethod
    def concat(built):
        built = [b for b in built if b is not None]
        return Built(dsl.Mesh.concat([b.mesh for b in built]), [r for b in built for r in b.rails],
                     [c for b in built for c in b.checks])


def as_side(s):
    return s if isinstance(s, Side) else Side(s)


def as_ground(g):
    """A ground height function of plan points (x, z) arrays, from a float or a callable."""
    if callable(g):
        return g
    y = float(g)
    return lambda x, z: np.full(np.shape(x), y)


def from_additions(y, degrees, parts, **attrs):
    """A Profile from an r4 RAMPS profile (y, degrees, parts), whose ('line', L) runs L horizontally."""
    a, out = float(degrees), []
    for p in parts:
        extra = [p[-1]] if isinstance(p[-1], dict) else []
        core = p[:-1] if extra else p
        if core[0] == 'line':
            out.append(('line', core[1] / math.cos(math.radians(a)), *extra))
        else:
            out.append(tuple(core) + tuple(extra))
            if core[0] in ('arc', 'corner'):
                a = float(core[-1])
    return Profile(out, start=(0., y), degrees=degrees, **attrs)


def tagged(parts, tag, which=None):
    """The profile parts with `tag` set on the parts at indices `which` (all if None), keeping other attributes."""
    out = []
    for i, p in enumerate(parts):
        a = dict(p[-1]) if isinstance(p[-1], dict) else {}
        core = p[:-1] if isinstance(p[-1], dict) else p
        if which is None or i in which or (i - len(parts)) in which:
            a.setdefault('tag', tag)
        out.append(tuple(core) + ((a,) if a else ()))
    return out


def _dedupe(ids, V):
    """The vertex ids of a seam with consecutive duplicate positions (crease twins) dropped."""
    ids = np.asarray(ids)
    keep = np.r_[True, np.linalg.norm(np.diff(V[ids], axis=0), axis=1) > 1e-9]
    return ids[keep]


def _side_columns(E, D, side, g, base_y, under=None):
    """The cross-section points outward of a riding edge E (k, 3), outward D (k, 3) horizontal unit, for `side`:
    a list of (k, 3) rows from the edge out to the outer top, then the foot and the base rows; plus each segment's
    (role, material, outward kind) for the strips between consecutive rows."""
    Y = np.array([0., 1., 0.])
    rows, segs = [E], []
    if side.kind == 'curb':
        rows.append(E + side.height * Y); segs.append((dsl.SIDE, 'inner'))
        rows.append(E + side.height * Y + side.width * D); segs.append((dsl.RIDING, 'up'))
    elif side.kind == 'bank':
        top = rows[-1]
        drop = np.maximum(top[:, 1] - g(top[:, 0], top[:, 2]), FOOT)
        foot = top + (drop / math.tan(math.radians(side.degrees)))[:, None] * D - drop[:, None] * Y
        # the slope's foot on the ground there (one Newton step for sloping ground)
        for _ in range(3):
            gy = g(foot[:, 0], foot[:, 2])
            drop = np.maximum(top[:, 1] - gy, FOOT)
            foot = top + (drop / math.tan(math.radians(side.degrees)))[:, None] * D - drop[:, None] * Y
        rows.append(foot); segs.append((dsl.RIDING, 'bank'))
    outer = rows[-1]
    gy = g(outer[:, 0], outer[:, 2])
    foot = outer.copy(); foot[:, 1] = np.minimum(gy, outer[:, 1] - FOOT)
    if under is not None:                       # under the section's lowest point, so the end face stays simple
        foot[:, 1] = np.minimum(foot[:, 1], under - FOOT)
    if side.kind != 'bank':
        rows.append(foot); segs.append((dsl.SIDE if side.kind != 'flush' else dsl.BASE, 'out'))
    base = outer.copy(); base[:, 1] = base_y
    rows.append(base); segs.append((dsl.BASE, 'out'))
    return rows, segs


def _close(riding, rows_minus, rows_plus, ends, feature, ground, Dm, Dp, sides, T0, T1):
    """Walls, base and end caps closing a riding sheet into a solid. rows_*: per side, the list of (k, 3) rows from
    the riding edge outward and down to the base (a row per station). ends: (start, end) Side kinds."""
    Y = np.array([0., 1., 0.])
    parts = []
    for rows, segs, D, side in ((rows_minus[0], rows_minus[1], Dm, sides[0]), (rows_plus[0], rows_plus[1], Dp, sides[1])):
        for (a, b), (role, kind) in zip(itertools.pairwise(rows), segs, strict=True):
            P = np.stack([a, b], 1)
            out = {'inner': -D, 'up': np.broadcast_to(Y, D.shape), 'bank': D + Y, 'out': D}[kind]
            m = solids.grid(P, outward=out.sum(0), feature=feature, material=side.material, role=role,
                            uv='arc' if role == dsl.RIDING else 'wall')
            if role == dsl.SIDE:
                _bury_low(m, ground)
            parts.append(m)
    bm, bp = rows_minus[0][-1], rows_plus[0][-1]
    parts.append(solids.grid(np.stack([bm, bp], 1), outward=-Y, feature=feature, role=dsl.BASE, uv='world'))
    # end caps: the ring at the first and last station, split at the chord between the two feet
    for i, kind, out in ((0, ends[0], -T0), (-1, ends[1], T1)):
        top = riding[i]
        minus = [r[i] for r in rows_minus[0]]; plus = [r[i] for r in rows_plus[0]]
        upper = [minus[-2]] + minus[-3::-1] + list(top) + plus[1:-1]
        upper = _strip_dupes(np.asarray(upper))
        lower = np.asarray([plus[-2], plus[-1], minus[-1], minus[-2]])
        role = dsl.SIDE if as_side(kind).kind == 'wall' else dsl.BASE
        parts.append(solids.polygon(upper, outward=out, feature=feature, role=role))
        parts.append(solids.polygon(lower, outward=out, feature=feature, role=dsl.BASE))
    return parts


def _strip_dupes(L):
    keep = np.r_[True, np.linalg.norm(np.diff(L, axis=0), axis=1) > 1e-9]
    L = L[keep]
    if np.linalg.norm(L[0] - L[-1]) <= 1e-9:
        L = L[:-1]
    return L


def _bury_low(mesh, ground):
    """Wall faces standing less than FLUSH over the ground become buried closing faces (role base)."""
    t = mesh.triangles()
    top = t[:, :, 1].max(1)
    c = t.mean(1)
    low = top - ground(c[:, 0], c[:, 2]) < FLUSH
    mesh.role[low] = dsl.ROLE[dsl.BASE]


def _finish(parts, feature, riding=None):
    mesh = dsl.Mesh.concat(parts)
    mesh.features = (feature,)
    solids.check_closed(mesh, name=feature)
    solids.check_folds(mesh.where(role=dsl.RIDING) if riding is None else riding, name=feature)
    return mesh


# ------------------------------------------------------------------------------------------------ longitudinal ramps

def ramp(path, profile, width, *, start=0., left='wall', right='wall', ground=None, ends=('flush', 'flush'),
         feature='ramp', tess=dsl.RIDING_TESS, t=None):
    """A ramp along the plan `path` (curves.Curve) from `start` metres along it: the `profile` (its x along the path,
    y absolute) `width` wide, closed into a solid down to the `ground` (float or f(x, z); default 0 under the lowest
    point) with sides `left`/`right` (Side or kind; left is the path's +normal side) and `ends` (start, end) each
    'flush' (the next feature or deck continues there) or 'wall' (a visible end face: a kicker's back at its lip, a
    landing's front). Roll-ins, decks, kickers, landings and run-outs are ramps. Returns a Built."""
    left, right = as_side(left), as_side(right)
    riding = sweep(path, profile, mode='longitudinal', start=start, across=width, feature=feature, tess=tess, t=t)
    lo = float(riding.V[:, 1].min())
    g = as_ground(lo if ground is None else ground)
    V = riding.V
    # the edge rows (w = -W/2 is the path's right, -N; +W/2 its left, +N)
    sm = riding.seams
    e_minus = _dedupe(sm[f'{feature}.left'], V); e_plus = _dedupe(sm[f'{feature}.right'], V)
    if len(e_minus) != len(e_plus):
        raise ValueError(f'{feature}: edge rows differ ({len(e_minus)} vs {len(e_plus)})')
    Em, Ep = V[e_minus], V[e_plus]
    D = Ep - Em; D[:, 1] = 0; D /= np.linalg.norm(D, axis=1, keepdims=True)
    start_row = _dedupe(sm[f'{feature}.start'], V); end_row = _dedupe(sm[f'{feature}.end'], V)
    rows = [V[start_row], V[end_row]]
    if np.dot(rows[0][-1] - rows[0][0], D[0]) < 0:
        rows = [r[::-1] for r in rows]
    # base under everything: the lowest ground at the outer feet and the lowest riding point
    probe = []
    for E, Dd, s in ((Em, -D, right), (Ep, D, left)):
        reach = 0. if s.kind != 'curb' else s.width
        if s.kind == 'bank':
            reach = (E[:, 1] - g(E[:, 0], E[:, 2])).max() / math.tan(math.radians(s.degrees)) + 1.
        q = E + reach * Dd
        probe.append(g(q[:, 0], q[:, 2]))
    base_y = min(lo, *(float(p.min()) for p in probe), float(g(V[:, 0], V[:, 2]).min())) - BURY
    rm = _side_columns(Em, -D, right, g, base_y)
    rp = _side_columns(Ep, D, left, g, base_y)
    T0 = Em[1] - Em[0]; T0[1] = 0; T0 /= np.linalg.norm(T0)
    T1 = Em[-1] - Em[-2]; T1[1] = 0; T1 /= np.linalg.norm(T1)
    riding_rows = [rows[0], rows[1]]
    parts = [riding] + _close(riding_rows, rm, rp, ends, feature, g, -D, D, (right, left), T0, T1)
    mesh = _finish(parts, feature, riding)
    x = profile.point([0., profile.length])
    checks = [{'feature': feature, 'kind': 'ramp', 'start_t': start, 'end_t': start + float(x[1, 0] - x[0, 0]),
               'start_y': float(x[0, 1]), 'end_y': float(x[1, 1]), 'end_degrees': profile.end_degrees,
               'width': width}]
    return Built(mesh, [], checks)


def jump_line(path, launch, landing, gap, width, *, start=0., left='wall', right='wall', ground=None,
              feature='jump', tess=dsl.RIDING_TESS, land_width=None):
    """The joined line: roll-in, deck, kicker (the `launch` profile, ending at its lip), a `gap` (horizontal metres
    from the lip to the landing's start), then landing and run-out (the `landing` profile), along one plan `path`.
    The launch's last arc is tagged takeoff and the landing ramp's faces landing (unless the profiles tag them). The
    kicker's back under its lip and the landing's front are visible walls. Returns a Built whose checks hold the lip
    (point, degrees, height over the ground) and the landing zone."""
    def retag(p, tag, which):
        return Profile(tagged(p.parts, tag, which), start=tuple(p.start), degrees=p.degrees, tags=p.tags)
    arcs = [i for i, part in enumerate(launch.parts) if part[0] == 'arc']
    launch = retag(launch, 'takeoff', [arcs[-1]] if arcs else [len(launch.parts) - 1])
    landing = retag(landing, 'landing', None)
    a = ramp(path, launch, width, start=start, left=left, right=right, ground=ground, ends=('flush', 'wall'),
             feature=f'{feature}.launch', tess=tess)
    x0 = float(launch.end[0] - launch.start[0])
    b = ramp(path, landing, land_width or width, start=start + x0 + gap, left=left, right=right, ground=ground,
             ends=('wall', 'flush'), feature=f'{feature}.landing', tess=tess)
    g = as_ground(0. if ground is None else ground)
    lip_t = start + x0
    lip = path.point3([lip_t], launch.end[1])[0]
    land0 = path.point3([lip_t + gap], landing.start[1])[0]
    checks = [{'feature': feature, 'kind': 'air', 'lip': lip.tolist(), 'lip_degrees': launch.end_degrees,
               'lip_height': float(lip[1] - g(lip[:1], lip[2:])[0]), 'gap': gap, 'landing_start': land0.tolist(),
               'landing_t': (lip_t + gap, lip_t + gap + float(landing.end[0] - landing.start[0]))}]
    return Built(dsl.Mesh.concat([a.mesh, b.mesh]), [], a.checks + b.checks + checks)


# ------------------------------------------------------------------------------------------------ transverse solids

class Rounded(Curve):
    """A plan path through `points` (k, 2) whose corners are exact circular fillets of `radius` (a scalar or one per
    corner): straight legs and arcs, tangent-continuous, so a transverse sweep turns it without a mitre. `closed`
    rounds the closing corner too (a rounded-rectangle ledge, a bowl's outline). Arc ends are breaks."""

    def __init__(self, points, radius, closed=False):
        p = np.asarray(points, 'f8')
        if closed and np.linalg.norm(p[0] - p[-1]) < 1e-9:
            p = p[:-1]
        self.closed = closed
        n = len(p)
        corners = range(n) if closed else range(1, n - 1)
        r = np.broadcast_to(np.asarray(radius, 'f8'), (n,))
        fil = {}
        for i in corners:
            a, b, c = p[i - 1], p[i], p[(i + 1) % n]
            u = (b - a) / np.linalg.norm(b - a); v = (c - b) / np.linalg.norm(c - b)
            turn = math.atan2(u[0] * v[1] - u[1] * v[0], u @ v)
            if abs(turn) < 1e-9:
                continue
            cut = r[i] * math.tan(abs(turn) / 2)
            fil[i] = (b - cut * u, b + cut * v, turn, r[i], u, cut)
        for i in range(n if closed else n - 1):                 # each leg holds the cuts at both its ends
            j = (i + 1) % n
            used = fil.get(i, (0,) * 6)[5] + fil.get(j, (0,) * 6)[5]
            if used > np.linalg.norm(p[j] - p[i]) + 1e-9:
                raise ValueError(f'Rounded: the fillets at points {i} and {j} do not fit the leg between them')
        self.parts = []                          # ('line', a, b) or ('arc', centre, R, start angle, turn)
        start = fil[0][1] if closed and 0 in fil else p[0]
        order = list(range(1, n)) + ([0] if closed else [])
        cur = start
        for i in order:
            if i in fil:
                a, b, turn, R, u, _ = fil[i]
                if np.linalg.norm(a - cur) > 1e-12:
                    self.parts.append(('line', cur, a))
                nrm = np.array([-u[1], u[0]]) * math.copysign(1., turn)
                centre = a + R * nrm
                a0 = math.atan2(*(a - centre)[::-1])
                self.parts.append(('arc', centre, R, a0, turn))
                cur = b
            else:
                if np.linalg.norm(p[i] - cur) > 1e-12:
                    self.parts.append(('line', cur, p[i]))
                cur = p[i]
        if closed and np.linalg.norm(start - cur) > 1e-12:
            self.parts.append(('line', cur, start))
        self.curves = [Line(q[1], q[2]) if q[0] == 'line' else Arc(q[1], q[2], math.degrees(q[3]), math.degrees(q[4]))
                       for q in self.parts]
        self.s = np.concatenate([[0.], np.cumsum([c.length for c in self.curves])])
        self.length = float(self.s[-1])

    def _at(self, t):
        t = np.atleast_1d(np.asarray(t, 'f8'))
        k = np.clip(np.searchsorted(self.s, t, 'right') - 1, 0, len(self.curves) - 1)
        return k, t

    def _map(self, t, fn, width):
        k, t = self._at(t)
        out = np.zeros((len(t), width)) if width else np.zeros(len(t))
        for i in np.unique(k):
            m = k == i
            out[m] = getattr(self.curves[i], fn)(t[m] - self.s[i])
        return out

    def point(self, t):
        return self._map(t, 'point', 2)

    def tangent(self, t):
        return self._map(t, 'tangent', 2)

    def curvature(self, t):
        return self._map(t, 'curvature', 0)

    def breaks(self):
        return self.s.copy()


def _horizontal(v):
    v = np.asarray(v, 'f8').copy(); v[..., 1] = 0
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-300)


def _columns(profile, tess, s=None):
    """The sweep's profile stations (crease twins included), as sweep.sweep makes them."""
    st, _, _ = _stations(profile, profile.samples(tess, () if s is None else s))
    return st


def _grid_of(riding, nb):
    """The transverse sheet's vertex grid (rows: path stations, columns: profile stations)."""
    if len(riding.V) % nb:
        raise ValueError('the sweep grid does not match its profile stations')
    return riding.V.reshape(-1, nb, 3)


def _dedupe_rows(P):
    keep = np.r_[True, np.linalg.norm(np.diff(P, axis=0), axis=-1).max(-1) > 1e-9] if P.ndim == 3 else None
    return P[keep]


def _dedupe_cols(row):
    keep = np.r_[True, np.linalg.norm(np.diff(row, axis=0), axis=1) > 1e-9]
    return row[keep]


def _close_transverse(G, *, feature, ground, front, back, ends, closed):
    """Walls, base, caps and end faces closing the transverse sheet grid G (k, n, 3) (rows path stations, columns
    profile stations from front to back) into a solid. front/back: Side kinds ('wall', 'flush', 'curb', 'bank'), or
    'cap' (front only: the front column is a level loop filled as riding, a bowl's floor or a ledge's top) or 'base'
    (back only: the back column is a level loop on the support, filled as a buried base: a ledge's footprint)."""
    Y = np.array([0., 1., 0.])
    g = as_ground(ground)
    if closed:
        G = G[:-1] if np.linalg.norm(G[0] - G[-1], axis=-1).max() < 1e-9 else G
    Ef, Eb = G[:, 0], G[:, -1]
    D = _horizontal(Eb - Ef)
    lo = min(float(G[..., 1].min()), float(g(G[..., 0].ravel(), G[..., 2].ravel()).min()))
    probe = []
    for E, Dd, kind in ((Ef, -D, front), (Eb, D, back)):
        s = as_side(kind) if kind not in ('cap', 'base') else None
        if s is not None and s.kind == 'bank':
            reach = (E[:, 1] - g(E[:, 0], E[:, 2])).max() / math.tan(math.radians(s.degrees)) + 1.
            q = E + reach * Dd
            probe.append(float(g(q[:, 0], q[:, 2]).min()))
    base_y = min([lo] + probe) - BURY - FOOT
    parts = []
    cols = {}
    for name, E, Dd, kind in (('front', Ef, -D, front), ('back', Eb, D, back)):
        if kind == 'cap':
            parts.append(solids.polygon(E, outward=Y, feature=feature, role=dsl.RIDING))
            cols[name] = None
            continue
        if kind == 'base':
            if np.ptp(E[:, 1]) > 1e-9:
                raise ValueError(f'{feature}: a base loop must be level')
            parts.append(solids.polygon(E, outward=-Y, feature=feature, role=dsl.BASE))
            cols[name] = None
            continue
        side = as_side(kind)
        rows, segs = _side_columns(E, Dd, side, g, base_y, under=G[..., 1].min(1))
        for (a, b), (role, k) in zip(itertools.pairwise(rows), segs, strict=True):
            out = {'inner': -Dd, 'up': np.broadcast_to(Y, Dd.shape), 'bank': Dd + Y, 'out': Dd}[k]
            m = solids.grid(np.stack([a, b], 1), outward=out, feature=feature, material=side.material, role=role,
                            uv='arc' if role == dsl.RIDING else 'wall', closed_rows=closed)
            if role == dsl.SIDE:
                _bury_low(m, g)
            parts.append(m)
        cols[name] = rows
    if cols['front'] is not None and cols['back'] is not None:
        parts.append(solids.grid(np.stack([cols['front'][-1], cols['back'][-1]], 1), outward=-Y, feature=feature,
                                 role=dsl.BASE, uv='world', closed_rows=closed))
    elif closed and cols['back'] is not None:
        parts.append(solids.polygon(cols['back'][-1], outward=-Y, feature=feature, role=dsl.BASE))
    elif closed and cols['front'] is not None:
        raise ValueError(f'{feature}: a closed sweep needs a cap at its front or a base at its back')
    if not closed:
        if cols['front'] is None or cols['back'] is None:
            raise ValueError(f'{feature}: an open sweep closes with walls at its front and back')
        T0 = _horizontal(G[1, 0] - G[0, 0]); T1 = _horizontal(G[-1, 0] - G[-2, 0])
        for i, kind, out in ((0, ends[0], -T0), (-1, ends[1], T1)):
            f = [r[i] for r in cols['front']]; b = [r[i] for r in cols['back']]
            upper = _strip_dupes(np.asarray([f[-2]] + f[-3::-1] + list(G[i]) + b[1:-1]))
            lower = np.asarray([b[-2], b[-1], f[-1], f[-2]])
            role = dsl.SIDE if as_side(kind).kind == 'wall' else dsl.BASE
            parts.append(solids.polygon(upper, outward=out, feature=feature, role=role))
            parts.append(solids.polygon(lower, outward=out, feature=feature, role=dsl.BASE))
    return parts


def transverse(path, profile, *, side=1, offset=0., height=0., ground=None, front='flush', back='wall',
               ends=('wall', 'wall'), feature='transverse', tess=dsl.RIDING_TESS, t=None):
    """A profile swept across the plan `path` (A's transverse sweep: o = offset + side * x), closed into a solid.
    Returns (Built, the sheet's grid (k, n, 3), its profile columns)."""
    closed = bool(getattr(path, 'closed', False))
    riding = sweep(path, profile, mode='transverse', side=side, offset=offset, height=height, feature=feature,
                   tess=tess, t=t)
    st = _columns(profile, tess)
    G = _grid_of(riding, len(st))
    # the closing works on positions; crease twins are dropped (they weld)
    keep = np.r_[True, np.abs(np.diff(st)) > 1e-12]
    Gc = G[:, keep]
    lo = float(G[..., 1].min())
    parts = [riding] + _close_transverse(Gc, feature=feature, ground=lo if ground is None else ground, front=front,
                                         back=back, ends=ends, closed=closed)
    mesh = _finish(parts, feature, riding)
    return Built(mesh), G, st


def _lip_row(G, st, profile, name='lip'):
    s = profile.tags[name]
    j = int(np.flatnonzero(np.abs(st - s) < 1e-9)[0])
    return G[:, j]


def _with_coping(built, G, st, profile, *, closed, into_sign, feature, names=('lip',)):
    """Coping tubes along the profile's tagged lip rows; into_sign +1 when the transition lies toward the profile's
    front (lower s) from the lip."""
    meshes, rails = [built.mesh], []
    D = _horizontal(G[:, -1] - G[:, 0])
    for k, name in enumerate(names):
        row = _lip_row(G, st, profile, name)
        sign = into_sign[k] if np.ndim(into_sign) else into_sign
        rows = row[:-1] if closed and np.linalg.norm(row[0] - row[-1]) < 1e-9 else row
        Dd = D[:len(rows)]
        tube, rail = coping_mod.coping(rows, -sign * Dd, closed=closed, feature=f'{feature}.{name}')
        solids.check_closed(tube, name=f'{feature}.{name}')
        meshes.append(tube); rails.append(rail)
    mesh = dsl.Mesh.concat(meshes); mesh.features = (feature,)
    return Built(mesh, built.rails + rails, built.checks)


def quarter_pipe(path, *, floor_y, height, radius, deck=1.5, floor=.5, top_degrees=None, side=1, ground=None,
                 back='wall', ends=('wall', 'wall'), coping=True, feature='quarter_pipe', tess=dsl.RIDING_TESS,
                 material=dsl.CONCRETE, deck_material=dsl.DECK):
    """A quarter pipe whose lip runs along the plan `path`: a flat `floor` strip at `floor_y`, a transition of `radius`
    up to `top_degrees` (default: vertical if `height` > `radius`, else the angle the arc reaches at `height`), a
    straight extension to the lip at floor_y + height, then a flat `deck` (>= 1.2 m) on the path's `side` (+1 its
    left). The floor's front edge meets the park floor flush; the deck's back is a `back` Side; its flanks are
    `ends`. With `coping`, a steel tube along the lip and a rail on it."""
    if deck < 1.2 - 1e-9:
        raise ValueError(f'{feature}: a deck must be at least 1.2 m deep')
    if top_degrees is None:
        top_degrees = 90. if height >= radius else math.degrees(math.acos(1 - height / radius))
    a = math.radians(top_degrees)
    rise = radius * (1 - math.cos(a))
    if rise > height + 1e-9:
        raise ValueError(f'{feature}: the transition rises {rise:.3f} m, over the height {height}')
    ext = (height - rise) / math.sin(a)
    ride = {'material': material}
    parts = [('line', floor, ride), ('arc', radius, top_degrees, ride)]
    if ext > 1e-9:
        parts.append(('line', ext, ride))
    parts += [('corner', 0., {'material': deck_material, 'tag': 'lip'}), ('line', deck, {'material': deck_material})]
    prof = Profile(parts, start=(0., floor_y), tags={'lip': len(parts) - 1})
    x_lip = float(prof.point([prof.tags['lip']])[0, 0])
    built, G, st = transverse(path, prof, side=side, offset=-side * x_lip, ground=ground, front='flush', back=back,
                              ends=ends, feature=feature, tess=tess)
    built.checks.append({'feature': feature, 'kind': 'quarter_pipe', 'lip_y': floor_y + height,
                         'top_degrees': top_degrees, 'radius': radius})
    if coping:
        built = _with_coping(built, G, st, prof, closed=bool(getattr(path, 'closed', False)), into_sign=1,
                             feature=feature)
    return built


def bank(path, *, foot_y, height, degrees, foot_r=3., top_r=3., deck=1.2, floor=0., side=1, ground=None,
         back='wall', ends=('wall', 'wall'), feature='bank', tess=dsl.RIDING_TESS, material=dsl.CONCRETE):
    """A bank whose foot runs along the plan `path`, rising on its `side` (+1 left): `floor` flat, a foot transition
    (R >= 3 m) up to `degrees`, a straight slope, a crest transition (R >= 3 m) back to level and a `deck` at
    foot_y + height. Along a Rounded path with a convex corner it is a rounded hip."""
    if min(foot_r, top_r) < 3. - 1e-9:
        raise ValueError(f'{feature}: bank transitions need R >= 3 m')
    a = math.radians(degrees)
    run = (height - (foot_r + top_r) * (1 - math.cos(a))) / math.sin(a)
    if run < -1e-9:
        raise ValueError(f'{feature}: transitions of R {foot_r}/{top_r} at {degrees} deg rise over {height} m')
    ride = {'material': material}
    parts = [('line', floor, ride)] if floor > 0 else []
    parts += [('arc', foot_r, degrees, ride)] + ([('line', run, ride)] if run > 1e-9 else [])
    parts += [('arc', top_r, 0., ride), ('line', deck, ride)]
    prof = Profile(parts, start=(0., foot_y), tags={'crest': len(parts) - 1})
    built, _, _ = transverse(path, prof, side=side, ground=ground, front='flush', back=back, ends=ends,
                             feature=feature, tess=tess)
    built.checks.append({'feature': feature, 'kind': 'bank', 'degrees': degrees, 'top_y': foot_y + height})
    return built


def hip(corner, legs, *, foot_y, height, degrees, ridge_r=None, **kw):
    """A hip: two banks rising away from their feet that meet on a ridge over the `corner` (plan point), the feet
    running back along `legs` = (a, b) (plan points). The foot turns the corner on a fillet of `ridge_r` (default
    the bank's reach, so the ridge is rounded and the surface stays one smooth sweep, never mitred)."""
    a, b = np.asarray(legs[0], 'f8'), np.asarray(legs[1], 'f8'); c = np.asarray(corner, 'f8')
    u = (c - a) / np.linalg.norm(c - a); v = (b - c) / np.linalg.norm(b - c)
    turn = u[0] * v[1] - u[1] * v[0]
    # the bank rises away from the hip's outside: inward of the turn
    side = 1 if turn > 0 else -1
    if ridge_r is None:
        ridge_r = 2. * height / math.tan(math.radians(degrees)) + kw.get('deck', 1.2) + 1.
    return bank(Rounded([a, c, b], ridge_r), foot_y=foot_y, height=height, degrees=degrees, side=side, **kw)


def snake_profile(width, wall, radius, lip):
    """A snake run's cross-section from its left deck edge to its right: `lip` of deck, the coping, an arc of
    `radius` down to the floor `width` wide, and back up. Tags lip_l, lip_r. Starts at (0, wall)."""
    a = math.degrees(math.acos(1 - wall / radius)) if wall < radius else 90.
    ext = (wall - radius * (1 - math.cos(math.radians(a)))) / math.sin(math.radians(a))
    down = [('corner', -a, {'tag': 'lip'})] + ([('line', ext)] if ext > 1e-9 else []) + [('arc', radius, 0.)]
    up = [('arc', radius, a)] + ([('line', ext)] if ext > 1e-9 else []) + [('corner', 0., {'tag': 'lip'})]
    parts = [('line', lip, {'material': dsl.DECK})] + down + [('line', width)] + up + [('line', lip, {'material': dsl.DECK})]
    return Profile(parts, start=(0., wall), tags={'lip_l': 1, 'lip_r': len(parts) - 2})


def snake_run(centre, *, width, wall, radius, lip=.6, floor=0., ground=None, coping=True, ends=('flush', 'flush'),
              feature='snake', tess=dsl.RIDING_TESS):
    """A snake run along the centreline `centre` (a smooth Curve, e.g. Spline): a floor `width` wide at the height
    `floor` (float, dsl.Height or f(t)) along it, transitions of `radius` rising `wall` either side, a `lip` deck and
    a coping on both lips. The sections come from the analytic normal (no eased polyline, no snap). A centreline
    tighter than 1.5 times the section's reach is refused, and so is any fold or a self-crossing outline."""
    prof = snake_profile(width, wall, radius, lip)
    half = float(prof.end[0]) / 2
    tt = np.linspace(0, centre.length, max(64, int(centre.length * 8)))
    k = np.abs(centre.curvature(tt)).max()
    if k > 0 and 1 / k < 1.5 * half:
        raise ValueError(f'{feature}: the centreline bends to R {1 / k:.2f} m, tighter than 1.5 x the section reach '
                         f'{half:.2f} m: the section would fold')
    built, G, st = transverse(centre, prof, side=1, offset=-half, height=floor, ground=ground, front='wall',
                              back='wall', ends=ends, feature=feature, tess=tess)
    outline = np.concatenate([G[:, 0], G[-1, 1:], G[::-1][1:, -1], G[0, ::-1][1:-1]])[:, [0, 2]]
    outline = _dedupe_cols(outline)
    if solids.segments_cross(outline):
        raise ValueError(f'{feature}: its outline crosses itself in plan (a fold)')
    built.checks.append({'feature': feature, 'kind': 'snake', 'reach': half, 'least_radius': 1 / k if k else np.inf})
    if coping:
        # lip_l: the transition lies toward the back (higher s); lip_r: toward the front
        built = _with_coping(built, G, st, prof, closed=False, into_sign=(-1, 1), feature=feature,
                             names=('lip_l', 'lip_r'))
    return built


def _ccw(path):
    tt = np.linspace(0, path.length, 512, endpoint=False)
    p = path.point(tt)
    return .5 * (p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]).sum() > 0


def bowl(outline, *, floor_y, depth, radius, deck=1.2, top_degrees=None, ground=None, back='wall', coping=True,
         feature='bowl', tess=dsl.RIDING_TESS, material=dsl.CONCRETE, deck_material=dsl.DECK):
    """A bowl whose coping follows the closed plan `outline` (Spline(closed=True) or Rounded(closed=True)): a level
    floor at `floor_y`, walls of transition `radius` up to `top_degrees` (default: vertical if `depth` > `radius`),
    a straight extension to the lip at floor_y + depth, and a `deck` around it. The outline may turn inward (a
    kidney); where its inward turn is tighter than the deck, or its outward bulge tighter than the transition's reach,
    the offset rows would fold, and the bowl is refused with the place and the radius."""
    if top_degrees is None:
        top_degrees = 90. if depth >= radius else math.degrees(math.acos(1 - depth / radius))
    a = math.radians(top_degrees)
    rise = radius * (1 - math.cos(a))
    if rise > depth + 1e-9:
        raise ValueError(f'{feature}: the transition rises {rise:.3f} m, over the depth {depth}')
    ext = (depth - rise) / math.sin(a)
    ride = {'material': material}
    parts = [('arc', radius, top_degrees, ride)] + ([('line', ext, ride)] if ext > 1e-9 else [])
    parts += [('corner', 0., {'material': deck_material, 'tag': 'lip'}), ('line', deck, {'material': deck_material})]
    prof = Profile(parts, start=(0., floor_y), tags={'lip': len(parts) - 1})
    reach = float(prof.point([prof.tags['lip']])[0, 0])
    inward = 1 if _ccw(outline) else -1                 # +N points into the bowl for a counter-clockwise outline
    tt = np.linspace(0, outline.length, max(256, int(outline.length * 8)), endpoint=False)
    k = outline.curvature(tt) * inward                  # > 0 where it bulges outward (convex), < 0 where it turns in
    convex, concave = k.max(), -k.min()
    if convex > 0 and 1 / convex <= reach + 1e-6:
        i = int(np.argmax(k))
        raise ValueError(f'{feature}: the outline bulges at R {1 / convex:.2f} m near {outline.point([tt[i]])[0].round(2)}, '
                         f'tighter than the transition reach {reach:.2f} m: the floor would fold')
    if concave > 0 and 1 / concave <= deck + 1e-6:
        i = int(np.argmin(k))
        raise ValueError(f'{feature}: the outline turns inward at R {1 / concave:.2f} m near '
                         f'{outline.point([tt[i]])[0].round(2)}, tighter than the deck {deck:.2f} m: the deck would fold')
    built, G, st = transverse(outline, prof, side=-inward, offset=inward * reach, ground=ground, front='cap',
                              back=back, feature=feature, tess=tess)
    built.checks.append({'feature': feature, 'kind': 'bowl', 'lip_y': floor_y + depth, 'reach': reach,
                         'least_bulge_radius': 1 / convex if convex > 0 else np.inf,
                         'least_inward_radius': 1 / concave if concave > 0 else np.inf})
    if coping:
        built = _with_coping(built, G, st, prof, closed=True, into_sign=1, feature=feature)
    return built


SOLID_TESS = dsl.Tess(.003, 15., 4.)    # ledges and boxes: a 3 cm nose and 10 cm corners in 15 degree steps


def ledge(outline, *, support_y, height, nose=.03, feature='ledge', tess=SOLID_TESS, material=dsl.LEDGE,
          grind=True):
    """A ledge, box or manual pad over the closed plan footprint `outline` (Rounded(closed=True) or a closed Spline):
    a level ridable top at support_y + height, a rounded `nose` over vertical faces down to the support. The base
    faces close it over the footprint, which the network cuts out of the deck (review point 1: no buried faces under
    an intact deck); the footprint is the seam '<feature>.footprint'. With `grind`, a rail along the top arris."""
    if height < nose + .05:
        raise ValueError(f'{feature}: {height} m is too low for a {nose} m nose')
    top = support_y + height
    ride = {'material': material}
    prof = Profile([('arc', nose, -90., ride), ('line', height - nose, {'material': material, 'role': dsl.SIDE})],
                   start=(0., top))
    inward = 1 if _ccw(outline) else -1
    built, G, _ = transverse(outline, prof, side=-inward, offset=inward * nose, front='cap', back='base',
                              ground=support_y, feature=feature, tess=tess)
    mesh = built.mesh
    foot = G[:, -1]
    foot = foot[:-1] if np.linalg.norm(foot[0] - foot[-1]) < 1e-9 else foot
    base = np.unique(mesh.F[mesh.role == dsl.ROLE[dsl.BASE]])
    mesh.seams[f'{feature}.footprint'] = base[np.abs(mesh.V[base, 1] - support_y) < 1e-9]
    rails = []
    if grind:
        arris = G[:, 0]
        rails.append(edge_rail(arris, closed=True, feature=feature))
    built.checks.append({'feature': feature, 'kind': 'ledge', 'top_y': top, 'footprint': foot[:, [0, 2]].tolist()})
    return Built(mesh, rails, built.checks)


def box(x0, z0, x1, z1, *, support_y, height, corner=.1, nose=.03, feature='box', **kw):
    """A box or manual pad: a rounded rectangle footprint (corner radius `corner`), see ledge."""
    return ledge(Rounded([(x0, z0), (x1, z0), (x1, z1), (x0, z1)], corner, closed=True), support_y=support_y,
                 height=height, nose=nose, feature=feature, **kw)
