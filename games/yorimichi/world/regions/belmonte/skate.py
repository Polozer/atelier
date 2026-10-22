"""Belmonte's grind lines: what looks grindable grinds, on the collision the board rides.

- Lips come from Crater Park's lip finder (craterpark/grind.py), the edges the runtime's grind probes accept: the
  edge of a level deck where the ground falls away and nothing hangs over it (ledges, low walls, planters, bench
  seats, fountain rims, curbs). It runs over the placed collision of the town, and around each piece of skate
  furniture outside it. Stair nosings stay out, as at Crater Park.
- Bars: thin wooden or iron members (shop-window ledges, stall shelves, terrace rails) whose top runs at grind height
  over the street. They have no deck for a lip, so their line is the member's top, and the member gets a box of
  collision (its own oriented bounds) so the board meets what it grinds.

Only what a skater can reach counts: lines and bars REACH_M or less over the street they rise from. Wall modules laid
end to end (furniture.join) become one line. Every line comes from the authored geometry and placements.
"""
from dataclasses import dataclass

import numpy as np
from atelier.gltf import glb_parts

from . import collision, furniture, source
from craterpark import grind

TO_NATIVE = np.array([[1., 0., 0.], [0., 0., 1.], [0., -1., 0.]])      # plan (z up) -> grind.py's frame (y up)
TOWN_MARGIN_M = 25.     # around the town's building blocks
PROP_MARGIN_M = 4.      # around a piece of skate furniture outside the town
EDGE_M = 1.             # lines this close to an area's edge are cut (what lies past it was not looked at)
REACH_M = 1.5           # metres over the street a skater ollies onto (a lip's or a bar's top)
STREET_M = 2.5          # around a line, where the street it rises from is looked for (its highest point under the line)
STREETS = ('SM_BM_BT_Terrain', 'SM_BM_BC_Pave', 'SM_BM_BC_Piazza',      # the ground a skater rolls on: streets,
           'SM_BM_BHip_StableYard', 'SM_BM_BHip_Course', 'SM_BM_BHip_Infield',  # the racecourse's yards and tracks,
           'SM_BM_BHip_Arenas', 'SM_BM_BHip_SalonGrounds', 'SM_BM_BHip_StandTerrace',
           'SM_BM_BE_0_Grounds', 'SM_BM_BE_1_Grounds', 'SM_BM_BE_2_Grounds',    # and the estates' grounds
           'SM_BM_BE_3_Grounds', 'SM_BM_BE_4_Grounds', 'SM_BM_BE_5_Grounds', 'SM_BM_BE_6_Grounds')
SOFT = ('water', 'glass', 'window', 'foam')                  # drawn faces the board passes or never meets
BAR_SLOTS = ('iron', 'wood')
# Props whose committed hull is one solid block over an open frame that a skater grinds (a market stall's counter and
# shelf under its canopy): they collide as drawn instead, as the streets do.
AS_DRAWN = ('SM_BM_BP_Stall_',)
# Props whose committed hull stops under what is drawn above it (the well's hull is its kerb block, so a skater rode
# through its posts and roof): what is drawn over the hull's top collides too, the hull still closing the shaft.
OVER_HULL = ('SM_BM_BH_Pozzo',)
BAR_LENGTH_M = 1.2      # a bar is at least this long along its top
BAR_THICK_M = .25       # and at most this across
BAR_LOW_M = .25         # metres a bar's top stands over the street at least (lower is trim)
BAR_SIDE_M = (.02, .05, grind.NEAR)  # metres past a bar's side where a deck at its height makes it a deck's slat
BAR_FOLLOWED = .15      # a bar whose top a lip already follows within this is that lip
WELD_M = .005
# Wall sections laid end to end on a slope turn a little at each join: their top edges' ends meet within this (cm).
LINE_JOIN_CM = 12.


def slotted(entry, cache={}):
    """(local plan triangles, material name per triangle) of a library mesh (or a prop standing for one)."""
    if (entry['name'], entry['sha256']) not in cache:
        path = source.LIBRARY / entry['path']
        doc, _ = glb_parts(path.read_bytes())
        faces = source.triangles(path)
        names = []
        for node in doc['nodes']:
            for p in doc['meshes'][node['mesh']]['primitives'] if 'mesh' in node else ():
                names += [doc['materials'][p['material']]['name'].lower()] * (doc['accessors'][p['indices']]['count'] // 3)
        assert len(names) == len(faces), entry['name']
        cache[entry['name'], entry['sha256']] = faces, np.array(names)
    return cache[entry['name'], entry['sha256']]


def as_drawn(name):
    return name.startswith(AS_DRAWN)


def over_hull(entry, hulls):
    """The drawn hard faces of an OVER_HULL prop wholly over its committed hull's top (local plan metres)."""
    if not entry['name'].startswith(OVER_HULL):
        return np.zeros((0, 3, 3))
    faces, names = slotted(entry)
    faces = faces[hard(names)]
    return faces[faces[:, :, 2].min(1) >= source.triangles(hulls).reshape(-1, 3)[:, 2].max() - 1e-3]


def hard(names):
    return np.array([not any(w in n for w in SOFT) for n in names], bool)


def to_world(transform, faces):
    return collision.to_world(transform, np.asarray(faces).reshape(-1, 3)).reshape(-1, 3, 3)


def to_local(transform, points):
    """Region plan metres -> a placement's local plan metres (collision.to_world inverted)."""
    native = np.asarray(points, float) * [100., -100., 100.] - transform['translation_cm']
    q = np.asarray(transform['rotation_xyzw'], float) * [-1., -1., -1., 1.]
    from . import planting
    return planting.rotate(q, native) / transform['scale'] / [100., -100., 100.]


def placements(data):
    """[(index, mesh entry, transform)] of every placement."""
    by_asset = {m['source_asset']: m for m in data['meshes']}
    return [(i, by_asset[p['asset']], p['transform']) for i, p in enumerate(data['placements'])]


def areas(data):
    """Where lines are looked for, as plan boxes (x0, y0, x1, y1): the town (its building blocks and TOWN_MARGIN_M),
    and PROP_MARGIN_M around each piece of skate furniture outside it."""
    rows = placements(data)
    blocks = np.concatenate([to_world(t, slotted(e)[0]).reshape(-1, 3) for _, e, t in rows
                             if e['name'].startswith('SM_BM_BT_blk_')])
    town = (*(blocks[:, :2].min(0) - TOWN_MARGIN_M), *(blocks[:, :2].max(0) + TOWN_MARGIN_M))
    out = [tuple(float(v) for v in town)]
    for _, e, t in rows:
        if furniture.is_furniture(e['name']):
            p = to_world(t, slotted(e)[0]).reshape(-1, 3)
            box = (*(p[:, :2].min(0) - PROP_MARGIN_M), *(p[:, :2].max(0) + PROP_MARGIN_M))
            if not (box[0] >= town[0] and box[1] >= town[1] and box[2] <= town[2] and box[3] <= town[3]):
                out.append(tuple(float(v) for v in box))
    return out


def inside(points, boxes, shrink=0.):
    points = np.asarray(points)
    ok = np.zeros(points.shape[:-1], bool)
    for b in boxes:
        ok |= ((points[..., 0] >= b[0] + shrink) & (points[..., 0] <= b[2] - shrink) &
               (points[..., 1] >= b[1] + shrink) & (points[..., 1] <= b[3] - shrink))
    return ok


def street_query(data):
    """above(line): a line's median height over the street it rises from (the highest street or terrain top within
    STREET_M of each point and not over it), None where there is none: what a skater rolling up has to ollie. A wall
    whose top is the upper street's kerb is low, a market stall's roof is high."""
    faces = [to_world(t, slotted(e)[0]) for _, e, t in placements(data) if e['name'].startswith(STREETS)]
    ground = grind.heights(np.concatenate(faces) @ TO_NATIVE.T)

    def above(line):
        line = np.asarray(line, float); high = np.full(len(line), -np.inf)
        for dx in (-STREET_M, 0., STREET_M):
            for dy in (-STREET_M, 0., STREET_M):
                q = (line + [dx, dy, 0.]) @ TO_NATIVE.T
                high = np.maximum(high, ground(q, q[:, 1] - 30., q[:, 1] + .05, top=True))
        ok = np.isfinite(high)
        return float(np.median(line[ok, 2] - high[ok])) if ok.any() else None
    return above


# ---------------------------------------------------------------------------------------------------- bars

@dataclass
class Bar:
    mesh: str
    corners: np.ndarray         # (8, 3) local plan metres, ordered as collision._CORNERS (x bit 0, y bit 1, z bit 2)
    top: np.ndarray             # (2, 3) local plan metres: the line along the member's top

    def faces(self):
        return self.corners[collision._BOX]


def pieces(faces):
    """Connected pieces of a triangle soup (welded at WELD_M): a label per triangle."""
    key = np.unique(np.round(faces.reshape(-1, 3) / WELD_M).astype(np.int64), axis=0, return_inverse=True)[1].ravel()
    parent = np.arange(key.max() + 1 if len(key) else 0)

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for t in key.reshape(-1, 3):
        r = find(t[0])
        for j in t[1:]:
            parent[find(j)] = r
    return np.array([find(t[0]) for t in key.reshape(-1, 3)])


def mesh_bars(entry):
    """The thin wooden or iron members of a mesh (local frame) that are bars by their own geometry: [Bar]. Nothing of
    the mesh stands within grind.CLEAR over a bar's top or grind.NEAR either side of it (the lips' rule: the
    backrest's lower board under its top board, a ledge under a shutter), and no deck of the mesh lies at its height
    just past its sides (BAR_SIDE_M: a seat's slat is part of a deck, whose edge is a lip). Other props near it do not
    count: they collide, and a skater who meets one falls."""
    faces, names = slotted(entry)
    thin = np.flatnonzero(np.array([any(w in n for w in BAR_SLOTS) for n in names]))
    out = []
    if not len(thin):
        return out
    solid = grind.heights(faces[hard(names)] @ TO_NATIVE.T)
    label = pieces(faces[thin])
    for c in np.unique(label):
        p = faces[thin[label == c]].reshape(-1, 3)
        centre = p[:, :2].mean(0)
        _, _, axes = np.linalg.svd(p[:, :2] - centre, full_matrices=False)
        u = axes[0]; v = np.array([-u[1], u[0]])         # u x v = +z: collision._BOX winds outward
        along, across = (p[:, :2] - centre) @ u, (p[:, :2] - centre) @ v
        if np.ptp(along) < BAR_LENGTH_M or np.ptp(across) > BAR_THICK_M:
            continue
        lo = np.array([along.min(), across.min(), p[:, 2].min()]); hi = np.array([along.max(), across.max(), p[:, 2].max()])
        corners = np.array([[(hi if b >> k & 1 else lo)[k] for k in range(3)] for b in range(8)])
        corners = np.c_[centre + corners[:, :1] * u + corners[:, 1:2] * v, corners[:, 2]]
        mid = (lo[1] + hi[1]) / 2
        top = np.array([np.r_[centre + along.min() * u + mid * v, hi[2]], np.r_[centre + along.max() * u + mid * v, hi[2]]])
        q = np.linspace(top[0], top[1], 9); y = q[:, 2]
        side = np.r_[v, 0.]; half = (hi[1] - lo[1]) / 2
        if any(solid((q + s * side) @ TO_NATIVE.T, y + grind.SNAP, y + grind.CLEAR).any()
               for s in np.linspace(-grind.NEAR - half, grind.NEAR + half, 9)):
            continue
        if any(solid((q + s * (half + d) * side) @ TO_NATIVE.T, y - grind.SNAP, y + grind.SNAP).mean() > .5
               for s in (-1, 1) for d in BAR_SIDE_M):
            continue
        out.append(Bar(entry['name'], corners, top))
    return out


def bars(data, above=None):
    """Every bar a skater can reach: ({mesh name: [Bar]}, [(placement index, Bar, top line (2, 3) region plan m)]).
    A placement's bar (mesh_bars) has a line where its top stands BAR_LOW_M to REACH_M over the street. Its mesh then
    collides with the bar's box on every placement (a mesh's collision is shared)."""
    above = above or street_query(data)
    found, lines, cache = {}, [], {}
    for index, entry, transform in placements(data):
        if entry['name'] not in cache:
            cache[entry['name']] = mesh_bars(entry)
        for bar in cache[entry['name']]:
            top = collision.to_world(transform, bar.top)
            h = above(top)
            if h is None or not BAR_LOW_M <= h <= REACH_M:
                continue
            found.setdefault(entry['name'], {})[id(bar)] = bar
            lines.append((index, bar, top))
    return {name: list(b.values()) for name, b in found.items()}, lines


# ---------------------------------------------------------------------------------------------------- lips

def collision_faces(data, collisions, boxes):
    """The placed collision the board rides inside `boxes` (and a margin): (faces (n, 3, 3) region plan m, placement
    per face). `collisions` maps a mesh name to its collision GLB; a mesh without one collides as drawn."""
    faces, owner = [], []
    cache = {}
    grown = [(b[0] - EDGE_M * 3, b[1] - EDGE_M * 3, b[2] + EDGE_M * 3, b[3] + EDGE_M * 3) for b in boxes]
    for index, entry, transform in placements(data):
        name = entry['name']
        if any(w in name for w in ('Water', 'Foam', 'Waterfall', 'Lake')):
            continue
        if name not in cache:
            if name in collisions:
                cache[name] = source.triangles(collisions[name])
            else:
                f, n = slotted(entry)
                cache[name] = f[hard(n)]
        f = to_world(transform, cache[name])
        keep = inside(f, grown).any(1)
        if keep.any():
            faces.append(f[keep]); owner.append(np.full(int(keep.sum()), index))
    return np.concatenate(faces), np.concatenate(owner)


def lips(faces, boxes, above):
    """Crater Park's lips in the placed collision `faces` (region plan m), cut to `boxes` and to a skater's reach."""
    native = faces @ TO_NATIVE.T
    out = []
    for line in grind.grind_lines(native, native[:0]):
        line = line @ TO_NATIVE
        ok = inside(line, boxes, EDGE_M)
        for run in np.split(line, np.flatnonzero(np.diff(ok.astype(int)) != 0) + 1):
            if not inside(run[:1], boxes, EDGE_M).all() or len(run) < 2:
                continue
            if np.linalg.norm(np.diff(run, axis=0), axis=1).sum() < grind.SHORTEST:
                continue
            h = above(run)
            if h is not None and h <= REACH_M:
                out.append(run)
    return out


def near(points, lines, tol):
    """Share of `points` within tol of any of `lines`."""
    if not lines:
        return 0.
    seg = np.concatenate([np.stack([l[:-1], l[1:]], 1) for l in lines])
    a, ab = seg[:, 0], seg[:, 1] - seg[:, 0]
    t = np.clip(np.einsum('pkd,kd->pk', points[:, None] - a[None], ab) / np.maximum((ab * ab).sum(1), 1e-12), 0, 1)
    d = np.linalg.norm(points[:, None] - (a[None] + t[..., None] * ab[None]), axis=2).min(1)
    return float((d <= tol).mean())


def owners(faces, owner, lines):
    """The placement whose collision lies nearest each line's middle."""
    c = faces.mean(1)
    out = []
    for line in lines:
        m = line[len(line) // 2]
        out.append(int(owner[np.argmin(np.linalg.norm(c - m, axis=1))]))
    return out


def rails(data, collisions, bar_lines, above):
    """@cc [owner:fontanierh,label:correctness] belmonte-grind-lines-from-geometry
    Belmonte's grind lines (runtime.json rails, region cm) MUST come from the authored geometry and placements, never
    from coordinates: Crater Park's lips (craterpark/grind.py) over the placed collision the board rides, and the
    tops of reachable bars (bars) whose boxes their meshes collide with. Every line MUST lie within REACH_M of the
    street; a bar a lip already follows MUST NOT add a second line. Returns (rails, report)."""
    boxes = areas(data)
    faces, owner = collision_faces(data, collisions, boxes)
    found = lips(faces, boxes, above)
    names = {i: e['name'] for i, e, _ in placements(data)}
    out, report = [], {'lips': 0, 'bars': 0, 'bars_on_lips': 0, 'lip_m': 0., 'bar_m': 0.}
    for k, (line, who) in enumerate(zip(found, owners(faces, owner, found))):
        out.append({'id': f'{furniture.tail(names[who])}_{who}_lip{k}', 'kind': furniture.LEDGE,
                    'points': line * [100., -100., 100.]})
        report['lips'] += 1; report['lip_m'] += float(np.linalg.norm(np.diff(line, axis=0), axis=1).sum())
    for k, (index, bar, top) in enumerate(bar_lines):
        if near(np.linspace(top[0], top[1], 9), found, BAR_FOLLOWED) > .5:
            report['bars_on_lips'] += 1
            continue
        out.append({'id': f'{furniture.tail(bar.mesh)}_{index}_bar{k}', 'kind': furniture.THIN,
                    'points': top * [100., -100., 100.]})
        report['bars'] += 1; report['bar_m'] += float(np.linalg.norm(top[1] - top[0]))
    out = furniture.join(out, LINE_JOIN_CM)
    for rail in out:
        rail['points'] = np.round(rail['points'], 1).tolist()
    report.update(lines=len(out), lip_m=round(report['lip_m'], 1), bar_m=round(report['bar_m'], 1), areas=len(boxes))
    return out, report
