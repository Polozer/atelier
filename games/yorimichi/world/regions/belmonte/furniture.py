"""Belmonte street furniture a skater grinds and slides on: collision from the drawn tops.

The committed hulls of benches, planters, walls and basins are single boxes stopping at the seat or a guessed
height (the bench's backrest had none), so the board rode under or through what is drawn. `generate` replaces them
with collision derived from the drawn mesh alone:

- Plates: the drawn upward faces (soft slots, the planters' foliage, excluded), grouped where they touch or
  lie within GAP_M of each other and within STEP_M in height (a seat's slats, a wall's stone tops), each fitted to
  one plane: the collision's top is planar where the drawing is. A ring (a basin's rim) is split into convex pieces.
- Columns: each plate is a closed convex solid from the plate's plane down to the prop's base, through every drawn
  vertex that no plate holds up within SIDE_M (a wall's batter, a bench's back legs). Tops are clean planes, edges
  straight; a backrest is its own column, so the board stops on it or grinds its top rail. What no plate holds up
  (a fountain's statue) collides as drawn.
- Runs: modules laid end to end (a field wall's sections) reach past their drawn ends so a run's top has no gap,
  and their grind lines (belmonte/skate.py, from these columns) join into one line (`join`).

The committed hulls are never modified: outputs go under build/ through world.belmonte.
"""
from dataclasses import dataclass, field

import numpy as np
from atelier.gltf import glb_parts

from . import planting, source

# Mesh name tail -> material keywords the board passes through (planted foliage). A basin's water carries the board
# at its drawn surface, as the committed hulls did, so no one falls into a fountain.
FURNITURE = {
    'BP_Bench': (), 'BP_StoneBench': (), 'BP_StonePlanter_A': ('vcol',), 'BP_StonePlanter_B': ('vcol',),
    'BVV_StoneWall': (), 'BE_Trough': (), 'BE_MountingBlock': (), 'BHip_HayBale': (),
    'BH_Fontanella': (), 'BH_FountainPiazza': (),
}
UP = .9            # an upward face's normal z
GAP_M = .03        # upward faces this close in plan join one plate (slats, joints)
STEP_M = .05       # ... when their heights differ by no more than this
SIDE_M = .06       # a drawn vertex within this of a plate's footprint, under it, is held up by that plate
TOP_TOL_M = .06    # a plate's plane keeps within this of its drawn top
MIN_PLATE_M = .03  # plates lower than this over the base are ground trim, not furniture
TILT = .05         # a plate's fitted slope under this is level
SEAM_M = .001      # a face within this of another column's inside is hidden by it
SECTOR_DEG = 15.   # a ring whose faces each span less than this round its centre is cut into sectors
HOLLOW = .02       # a plate whose hull is uncovered over more than this share is split into convex pieces

RAIL_TURN_DEG = 30.     # placed lines whose ends meet bend at most this much to join (a basin's rim)
JOIN_CM = 7.            # placed lines whose ends meet within this are one line
# Modules laid end to end in runs (a field wall's 10 m sections) meet with up to JOIN_CM of gap or overlap: their
# collision reaches half of that past each drawn end so the run's top has no gap at a join.
RUN_OVERLAP_M = JOIN_CM / 100 / 2
RUN_CHAMFER_M = .001
LEDGE, THIN = 'Ledge', 'ThinRail'      # runtime.json kinds: a lip, a bar's top


def tail(name):
    return name[len('SM_BM_'):]


def is_furniture(name):
    return tail(name) in FURNITURE


# ---------------------------------------------------------------------------------------------------- geometry

def solid_faces(name, path):
    """The drawn triangles the board meets (local plan metres): every slot but the soft ones."""
    doc, _ = glb_parts(path.read_bytes())
    faces = source.triangles(path)
    soft = FURNITURE[tail(name)]
    keep, start = [], 0
    for mesh in doc['meshes']:
        for primitive in mesh['primitives']:
            count = doc['accessors'][primitive['indices']]['count'] // 3
            material = doc['materials'][primitive['material']]['name'].lower()
            if not any(word in material for word in soft):
                keep.append(faces[start:start + count])
            start += count
    assert start == len(faces), name
    return np.concatenate(keep)


def cross2(a, b):
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def hull2d(points):
    """Counter-clockwise convex hull of plan points (monotone chain)."""
    p = np.unique(np.round(np.asarray(points, float)[:, :2], 5), axis=0)
    if len(p) < 3:
        return p

    def half(seq):
        out = []
        for q in seq:
            while len(out) >= 2 and cross2(out[-1] - out[-2], q - out[-2]) <= 1e-12:
                out.pop()
            out.append(q)
        return out
    lower, upper = half(p), half(p[::-1])
    return np.array(lower[:-1] + upper[:-1])


def plan_distance(poly, points):
    """Signed plan distance from a convex CCW polygon: negative inside."""
    points = np.atleast_2d(points)[:, :2]
    a, b = poly, np.roll(poly, -1, 0)
    edge = b - a
    normal = np.stack([edge[:, 1], -edge[:, 0]], 1) / np.linalg.norm(edge, axis=1, keepdims=True)
    offset = ((points[:, None, :] - a[None]) * normal[None]).sum(-1)      # (n, edges), outward positive
    inside = offset.max(1)
    t = np.clip(((points[:, None, :] - a[None]) * edge[None]).sum(-1) / (edge * edge).sum(1)[None], 0, 1)
    nearest = a[None] + t[..., None] * edge[None]
    outside = np.linalg.norm(points[:, None, :] - nearest, axis=-1).min(1)
    return np.where(inside <= 0, inside, outside)


def hull3d(points, eps=1e-5):
    """Outward-wound triangles of the convex hull of 3D points (incremental; points are snapped to 0.1 mm so
    near-coplanar drawn vertices do not leave slivers). Coplanar runs can fool one insertion order, so the result is
    checked and other fixed orders are tried."""
    p = np.unique(np.round(np.asarray(points, float), 4), axis=0)
    p = p[np.argsort(-np.linalg.norm(p - p.mean(0), axis=1))]
    rng = np.random.default_rng(0)
    for attempt in range(16):
        order = np.arange(len(p)) if attempt == 0 else np.r_[0, 1 + rng.permutation(len(p) - 1)]
        faces = _hull3d(p[order], eps)
        normal, offset = planes(faces)
        if (p @ normal.T - offset).max() < 10 * eps:
            return faces
    raise AssertionError('no convex hull')


def _hull3d(p, eps):
    i0 = 0
    i1 = int(np.argmax(np.linalg.norm(p - p[i0], axis=1)))
    line = p[i1] - p[i0]
    i2 = int(np.argmax(np.linalg.norm(np.cross(line, p - p[i0]), axis=1)))
    n = np.cross(line, p[i2] - p[i0])
    i3 = int(np.argmax(np.abs((p - p[i0]) @ n)))
    assert abs((p[i3] - p[i0]) @ n) > eps, 'flat column'
    faces = [(i0, i1, i2), (i0, i2, i3), (i0, i3, i1), (i1, i3, i2)]
    centre = p[[i0, i1, i2, i3]].mean(0)

    def plane(f):
        a, b, c = p[list(f)]
        normal = np.cross(b - a, c - a)
        return normal / np.linalg.norm(normal), a
    faces = [f if plane(f)[0] @ (p[f[0]] - centre) > 0 else (f[0], f[2], f[1]) for f in faces]
    for k in range(len(p)):
        if k in (i0, i1, i2, i3):
            continue
        visible = [f for f in faces if (lambda nm: nm[0] @ (p[k] - nm[1]) > eps)(plane(f))]
        if not visible:
            continue
        edges = {}
        for f in visible:
            for e in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
                edges[e] = edges.get(e, 0) + 1
        horizon = [e for e in edges if (e[1], e[0]) not in edges]
        faces = [f for f in faces if f not in visible] + [(a, b, k) for a, b in horizon]
    return p[np.array(faces)]


# ---------------------------------------------------------------------------------------------------- plates

@dataclass
class Plate:
    faces: np.ndarray            # the drawn upward faces
    coef: np.ndarray             # z = coef[0] + coef[1] x + coef[2] y
    poly: np.ndarray             # convex plan footprint, CCW
    sector: tuple = None         # (centre xy, angle from, angle to): one sector of a turned ring (a basin's rim)

    def z(self, xy):
        xy = np.atleast_2d(xy)
        return self.coef[0] + xy[:, 0] * self.coef[1] + xy[:, 1] * self.coef[2]


def plates(faces):
    """Group the upward faces into plates and fit each one plane."""
    n = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    area = np.linalg.norm(n, axis=1) / 2
    up = np.flatnonzero(n[:, 2] / np.maximum(2 * area, 1e-12) > UP)
    f = faces[up]
    lo, hi = f[:, :, :2].min(1), f[:, :, :2].max(1)
    z = f[:, :, 2].mean(1)
    gap = np.maximum(lo[:, None] - hi[None], lo[None] - hi[:, None]).max(-1)
    near = (gap <= GAP_M) & (np.abs(z[:, None] - z[None]) <= STEP_M)
    keys = np.round(f.reshape(-1, 3), 4)
    _, vid = np.unique(keys, axis=0, return_inverse=True)
    vid = vid.reshape(-1, 3)
    shared = (vid[:, None, :, None] == vid[None, :, None, :]).any((-1, -2))
    label = np.arange(len(f))
    link = near | shared
    while True:
        new = np.where(link, label[None, :], len(f)).min(1)
        new = np.minimum(new, label)
        new = new[new]
        if np.array_equal(new, label):
            break
        label = new
    out = []
    for value in np.unique(label):
        for part, sector in convex_parts(f[label == value]):
            plate = fit(part)
            plate.sector = sector
            if len(plate.poly) >= 3:
                out.append(plate)
    return out


def triangle_distance(tri, points):
    """Plan distance from each point to the nearest of the triangles (0 inside one)."""
    a, b, c = tri[:, 0, :2], tri[:, 1, :2], tri[:, 2, :2]
    p = points[:, None, :]
    best = np.full(points.shape[0], np.inf)
    sign = lambda u, v, w: cross2(v - u, w - u)                                    # noqa: E731
    area = sign(a, b, c)[None]
    s1, s2, s3 = sign(a[None], b[None], p) * area, sign(b[None], c[None], p) * area, sign(c[None], a[None], p) * area
    inside = (s1 >= 0) & (s2 >= 0) & (s3 >= 0)
    best = np.where(inside.any(1), 0, best)
    for u, v in ((a, b), (b, c), (c, a)):
        e = (v - u)[None]
        t = np.clip(((p - u[None]) * e).sum(-1) / np.maximum((e * e).sum(-1), 1e-12), 0, 1)
        best = np.minimum(best, np.linalg.norm(p - u[None] - t[..., None] * e, axis=-1).min(1))
    return best


def hollow(faces, samples=24):
    """The share of a group of faces' plan convex hull farther than GAP_M from every face: 0 for a solid top."""
    poly = hull2d(faces.reshape(-1, 3))
    if len(poly) < 3:
        return 0.
    lo, hi = poly.min(0), poly.max(0)
    g = np.stack(np.meshgrid(*(np.linspace(lo[k], hi[k], samples) for k in range(2)), indexing='ij'), -1).reshape(-1, 2)
    g = g[plan_distance(poly, g) < -1e-6]
    if not len(g):
        return 0.
    return float((triangle_distance(faces, g) > GAP_M).mean())


def convex_parts(faces):
    """Split a plate that is not solid across its hull (a basin's rim, a ring of steps) into convex pieces: faces
    are added to a piece, neighbour by neighbour, while the piece's hull stays covered by its faces."""
    if hollow(faces) <= HOLLOW:
        return [(faces, None)]
    sectors = turned(faces)
    if sectors is not None:
        return sectors
    centre = faces.mean(1)
    left = list(range(len(faces)))
    parts = []
    while left:
        group = [left.pop(0)]
        grown = True
        while grown:
            grown = False
            order = sorted(left, key=lambda i: np.linalg.norm(centre[group] - centre[i], axis=1).min())
            for i in order:
                trial = faces[group + [i]]
                touching = np.abs(faces[group][:, :, None, :] - faces[i][None, None]).max(-1).min() < 1e-4
                if touching and hollow(trial) <= HOLLOW:
                    group.append(i)
                    left.remove(i)
                    grown = True
                    break
        parts.append((faces[group], None))
    return parts


def angle_of(xy, centre):
    return np.arctan2(xy[..., 1] - centre[1], xy[..., 0] - centre[0])


def turned(faces):
    """A ring turned about a centre (every face spans less than SECTOR_DEG round it): its sectors between the ring's
    own vertex angles, so every sector meets its neighbours and the parts inside and outside it on shared radii."""
    centre = np.unique(np.round(faces.reshape(-1, 3), 5), axis=0)[:, :2].mean(0)
    a = angle_of(faces[:, :, :2], centre)
    span = np.ptp(np.unwrap(a, axis=1), axis=1)
    if span.max() > np.radians(SECTOR_DEG):
        return None
    cuts = np.unique(np.round(a.ravel(), 4))
    mid = angle_of(faces.mean(1)[:, :2], centre)
    out = []
    for lo, hi in zip(cuts, np.r_[cuts[1:], cuts[0] + 2 * np.pi]):
        sel = (np.mod(mid - lo, 2 * np.pi) < np.mod(hi - lo, 2 * np.pi))
        if sel.any():
            out.append((faces[sel], (centre, float(lo), float(hi))))
    return out


def fit(part):
    """A plate's plane (area-weighted) and plan footprint."""
    n = np.cross(part[:, 1] - part[:, 0], part[:, 2] - part[:, 0])
    w = np.repeat(np.linalg.norm(n, axis=1) / 6, 3)
    pts = part.reshape(-1, 3)
    free = np.ptp(pts[:, :2], 0) > .2        # a plate too narrow to tilt across stays level that way
    A = np.c_[np.ones(len(pts)), pts[:, :2][:, free]] * np.sqrt(w)[:, None]
    solution = np.linalg.lstsq(A, pts[:, 2] * np.sqrt(w), rcond=None)[0]
    coef = np.zeros(3)
    coef[0], coef[1:][free] = solution[0], solution[1:]
    if np.linalg.norm(coef[1:]) < TILT:      # uneven stones on a level wall: level, so modules meet end to end
        coef = np.array([np.average(pts[:, 2], weights=w), 0., 0.])
    plate = Plate(part, coef, np.zeros((0, 2)))
    # Faces well under the plane (a leg's top under a seat) are held up by it but do not widen it.
    top = part[part[:, :, 2].max(1) >= plate.z(part.mean(1)[:, :2]) - STEP_M / 2]
    plate.poly = hull2d(top.reshape(-1, 3))
    return plate


# ---------------------------------------------------------------------------------------------------- columns

@dataclass
class Furniture:
    name: str
    drawn: np.ndarray                         # solid drawn triangles
    base: float
    plates: list
    columns: list = field(default_factory=list)   # [(plate, triangles)]
    unheld: int = 0                               # drawn vertices no plate column takes
    run: tuple = None                             # (axis, drawn from, drawn to) when laid end to end in runs

    @property
    def faces(self):
        """The columns' surface without the faces one column hides inside or on another (the seams between a rim's
        convex pieces): the board meets one continuous top, not an edge at every seam."""
        out = []
        for i, (plate, solid) in enumerate(self.columns):
            hidden = np.zeros(len(solid), bool)
            if plate is not None:
                for j, (other, cover) in enumerate(self.columns):
                    if j != i and other is not None:
                        hidden |= inside(cover, solid.reshape(-1, 3), SEAM_M).reshape(-1, 3).all(1)
            out.append(solid[~hidden])
        return np.concatenate(out) if out else np.zeros((0, 3, 3))


def run_axis(data, entry, path=None):
    """The local axis (its longer plan side, 0 x or 1 y) along which this module's placements meet end to end
    within JOIN_CM, or None."""
    drawn = solid_faces(entry['name'], path or source.LIBRARY / entry['path']).reshape(-1, 3)
    lo, hi = drawn.min(0), drawn.max(0)
    centre = (lo + hi) / 2
    placed = [p['transform'] for p in data['placements'] if p['asset'] == entry['source_asset']]
    for axis in [int(np.argmax((hi - lo)[:2]))]:
        a, b = centre.copy(), centre.copy()
        a[axis], b[axis] = lo[axis], hi[axis]
        starts = np.array([to_region_cm(t, [a])[0] for t in placed])
        ends = np.array([to_region_cm(t, [b])[0] for t in placed])
        if len(placed) > 1 and (np.linalg.norm(ends[:, None] - starts[None], axis=-1) <= JOIN_CM).any():
            return axis
    return None


def run_ends(cloud, run, points, base):
    """A run's module (run_axis) reaches RUN_OVERLAP_M past each drawn end, its top easing RUN_CHAMFER_M down, so a
    join has no gap, and where sections overlap the wheels roll from one top to the next over a dip under a
    millimetre instead of meeting the next section's end face."""
    lo, hi = points[:, run].min(), points[:, run].max()
    end = cloud[(cloud[:, run] <= lo + 1e-4) | (cloud[:, run] >= hi - 1e-4)].copy()
    end[:, run] += np.where(end[:, run] < (lo + hi) / 2, -RUN_OVERLAP_M, RUN_OVERLAP_M)
    end[end[:, 2] > base + 1e-4, 2] -= RUN_CHAMFER_M
    return np.concatenate([cloud, end])


def generate(entry, path=None, run=None):
    """@cc [owner:fontanierh,label:correctness] belmonte-furniture-collides-as-drawn
    Skate furniture (FURNITURE) MUST collide with closed, outward convex columns derived from its drawn mesh: one per
    drawn top plate, planar within TOP_TOL_M of the drawn top, reaching down to the prop's base and out to every
    drawn vertex that no plate holds up. Every drawn solid vertex MUST lie inside the collision within TOP_TOL_M.
    A module laid end to end in runs (run_axis) MAY reach RUN_OVERLAP_M past its drawn ends along the run, so joins
    have no gap.
    """
    drawn = solid_faces(entry['name'], path or source.LIBRARY / entry['path'])
    points = np.unique(np.round(drawn.reshape(-1, 3), 5), axis=0)
    base = float(points[:, 2].min())
    tops = [p for p in plates(drawn) if p.z(p.poly).min() - base > MIN_PLATE_M]
    tops.sort(key=lambda p: -p.z(p.poly).max())
    held = np.zeros(len(points), bool)
    owner = np.full(len(points), -1)
    best = np.full(len(points), np.inf)
    reach = []
    for k, plate in enumerate(tops):
        d = plan_distance(plate.poly, points)
        under = plate.z(points[:, :2]) >= points[:, 2] - TOP_TOL_M - 2e-3
        held |= under & (d <= SIDE_M)
        closer = under & (d < best)
        owner[closer], best[closer] = k, d[closer]
        reach.append(np.where(under, d, np.inf))
    furniture = Furniture(entry['name'], drawn, base, tops)
    if run is not None:
        side = points[:, 1 - run]
        furniture.run = (run, float(points[:, run].min()), float(points[:, run].max()),
                         float(side.min() + side.max()) / 2)
    furniture.unheld = int(((owner < 0) & ~held).sum())
    for k, plate in enumerate(tops):
        mine = owner == k
        if plate.sector is not None:
            # A sector takes every drawn vertex beyond it within its angles (both edges), so neighbours agree.
            centre, lo, hi = plate.sector
            a = np.mod(angle_of(points[:, :2], centre) - lo + 1e-4, 2 * np.pi) <= np.mod(hi - lo, 2 * np.pi) + 2e-4
            mine = a & np.isfinite(best) & (reach[k] <= best + 1e-4)      # what no plate holds stays loose
        extra = points[mine if plate.sector is not None else ~held & mine]
        top = np.c_[plate.poly, plate.z(plate.poly)]
        extra = np.c_[extra[:, :2], np.minimum(extra[:, 2], plate.z(extra[:, :2]))] if len(extra) else extra
        # A column stands on the base, so each plan point only needs its highest drawn height (no collinear stacks).
        above = np.concatenate([top, extra]) if len(extra) else top
        xy, index = np.unique(np.round(above[:, :2], 4), axis=0, return_inverse=True)
        z = np.full(len(xy), -np.inf)
        np.maximum.at(z, index.reshape(-1), above[:, 2])
        cloud = np.concatenate([np.c_[xy, z], np.c_[xy, np.full(len(xy), base)]])
        if run is not None:
            cloud = run_ends(cloud, run, points, base)
        furniture.columns.append((plate, hull3d(cloud)))
    furniture.columns = [c for i, c in enumerate(furniture.columns)
                         if not any(j != i and contains(o[1], c[1]) for j, o in enumerate(furniture.columns))]
    # What no plate holds up (a statue over its plinth) collides as drawn.
    loose = (owner < 0) & ~held
    if loose.any():
        _, index = np.unique(np.round(drawn.reshape(-1, 3), 5), axis=0, return_inverse=True)
        furniture.columns.append((None, drawn[loose[index.reshape(-1, 3)].any(1)]))
    return furniture


def planes(solid):
    a, b, c = solid[:, 0], solid[:, 1], solid[:, 2]
    n = np.cross(b - a, c - a)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    return n, (n * a).sum(1)


def inside(solid, points, tol=0.):
    """Are points inside a convex outward-wound solid (within tol)?"""
    n, d = planes(solid)
    return (np.atleast_2d(points) @ n.T - d <= tol).all(1)


def contains(outer, inner, tol=.01):
    return bool(inside(outer, inner.reshape(-1, 3), tol).all()) and len(outer) and not np.array_equal(outer, inner)


def outside_m(furniture, points):
    """How far each point lies outside the furniture's collision (0 inside any column)."""
    best = np.full(len(points), np.inf)
    for plate, solid in furniture.columns:
        if plate is None:                        # drawn as is: its own vertices are on it
            on = (np.abs(points[:, None] - solid.reshape(-1, 3)[None]).max(-1) < 1e-4).any(1)
            best = np.where(on, 0, best)
            continue
        n, d = planes(solid)
        best = np.minimum(best, np.maximum((points @ n.T - d).max(1), 0))
    return best


# ---------------------------------------------------------------------------------------------------- placement

def to_region_cm(transform, points):
    """Local plan metres -> the region actor's frame in UE centimetres (as runtime.json's transforms)."""
    native = np.asarray(points, float) * [100., -100., 100.] * transform['scale']
    return planting.rotate(transform['rotation_xyzw'], native) + transform['translation_cm']


def join(rails, tol=JOIN_CM):
    """Join rails whose ends meet (within tol centimetres) and continue each other (within RAIL_TURN_DEG)."""
    if not rails:
        return rails
    ends = np.array([[r['points'][0], r['points'][-1]] for r in rails]).reshape(-1, 3)
    heading = np.array([[r['points'][0] - r['points'][1], r['points'][-1] - r['points'][-2]] for r in rails]).reshape(-1, 3)
    heading /= np.linalg.norm(heading, axis=1, keepdims=True)
    gap = np.linalg.norm(ends[:, None] - ends[None], axis=-1)
    gap[np.arange(len(ends)), np.arange(len(ends))] = np.inf
    gap[np.arange(len(ends)), np.arange(len(ends)) ^ 1] = np.inf                  # a rail's own other end
    # Two ends meet when the lines continue: each heads out of its rail, so they point opposite ways.
    gap[heading @ heading.T > -np.cos(np.radians(RAIL_TURN_DEG))] = np.inf
    nearest = gap.argmin(1)
    partner = np.where((gap.min(1) <= tol) & (nearest[nearest] == np.arange(len(ends))), nearest, -1)
    used, out = set(), []

    def walk(r, start_end):
        # start_end: which end of rail r the chain starts from (0 start, 1 end).
        points, ids, kinds = [], [], []
        while r not in used:
            used.add(r)
            p = rails[r]['points'] if start_end == 0 else rails[r]['points'][::-1]
            if points:
                points[-1] = (points[-1] + p[0]) / 2
                p = p[1:]
            points.extend(p)
            ids.append(rails[r]['id'])
            kinds.append(rails[r]['kind'])
            other = partner[2 * r + 1 - start_end]
            if other < 0:
                break
            r, start_end = other // 2, other % 2
        return {'id': ids[0] if len(ids) == 1 else f'{ids[0]}+{len(ids) - 1}', 'kind': max(set(kinds), key=kinds.count),
                'points': np.array(points)}
    for e in range(len(ends)):
        if partner[e] < 0 and e // 2 not in used:
            out.append(walk(e // 2, e % 2))
    for r in range(len(rails)):
        if r not in used:
            out.append(walk(r, 0))
    return out

