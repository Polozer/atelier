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

from . import dsl, solids
from .profile import Profile
from .sweep import sweep

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


def _side_columns(E, D, side, g, base_y):
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
