"""Audit Belmonte as a skater meets it (no Unreal): what looks grindable against the lines the game registers.

    uv run python games/yorimichi/tools/belmonte_skate_audit.py --out DIR [--buildings BUILDINGS.json]

Writes DIR/audit.json and DIR/map.png (a top view of the town, one pixel per MAP_CELL metres):

- `lips`: the deck edges Crater Park's lip finder (craterpark/grind.py, the runtime's grind probes) accepts in the
  town's drawn surfaces, each with the mesh it lies on and whether a registered line follows it;
- `nosings`: the stair edges that finder leaves out on purpose (an ollie down a set is not pulled onto a step);
- `bars`: thin iron or wooden members (railings, tie rails, balustrades) standing at grind height over the ground,
  which have no deck and so are no lip;
- `registered`: the lines world.belmonte registers (runtime.json `rails`, belmonte/furniture.py);
- `props`: every placed piece of street furniture with its family and its registered lines;
- `buildings`: the building collision audit (belmonte_collision_audit.py --json), when given.

Plan metres throughout: x east, y north, z up, from Belmonte's local origin.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
import yori  # noqa: E402,F401
from atelier.gltf import glb_parts  # noqa: E402
from belmonte import collision, furniture, source  # noqa: E402
from craterpark import grind  # noqa: E402

MAP_CELL = .25          # metres per map pixel
TOWN_MARGIN = 25.       # metres around the town's building blocks
BAR_LENGTH = 1.2        # metres: a thinner member at least this long along its top is a bar
BAR_HEIGHT = (.25, 1.4) # metres its top stands over the ground under it
BAR_THICK = .25         # metres: at most this across
FOLLOW = .2             # metres: a registered line within this of a lip follows it
STREET_M = 2.5          # metres around a line where the street under it is looked for (its lowest point counts)
STREETS = ('SM_BM_BT_Terrain', 'SM_BM_BC_Pave', 'SM_BM_BC_Piazza')
SOFT = ('water', 'glass', 'window', 'foliage', 'flag.0', 'leaf')
FAMILIES = (            # mesh name tail prefix -> family
    ('BP_Bench', 'bench'), ('BP_StoneBench', 'bench'),
    ('BP_StonePlanter', 'planter'), ('BP_PotLarge', 'planter'), ('BP_BarrelPlanter', 'planter'),
    ('BVV_StoneWall', 'low wall'), ('BC_Mura', 'town wall'), ('BC_QuayWall', 'quay'),
    ('BC_Ponte', 'bridge'), ('BC_Passerella', 'bridge'),
    ('BE_TieRail', 'bar'), ('BHip_TieRail', 'bar'), ('BHip_RailSeg', 'bar'),
    ('BH_FountainPiazza', 'fountain'), ('BH_Fontanella', 'fountain'), ('BH_Pozzo', 'fountain'), ('BE_Trough', 'fountain'),
    ('BE_MountingBlock', 'block'), ('BHip_HayBale', 'block'), ('BVV_HayRoll', 'block'), ('BE_BaleStack', 'block'),
    ('BC_Pave', 'ground'), ('BC_Piazza', 'ground'), ('BC_Works', 'ground'), ('BT_Terrain', 'ground'),
)
TO_NATIVE = np.array([[1., 0., 0.], [0., 0., 1.], [0., -1., 0.]])      # plan (z up) -> grind.py's frame (y up)


def family(name):
    t = name[len('SM_BM_'):]
    if collision.is_building(name):
        return 'building'
    return next((f for prefix, f in FAMILIES if t.startswith(prefix)), 'other')


_slots = {}


def slotted(entry):
    """(local plan triangles, material name per triangle) of a mesh entry, cached."""
    if entry['name'] not in _slots:
        path = source.LIBRARY / entry['path']
        doc, _ = glb_parts(path.read_bytes())
        faces = source.triangles(path)
        names = []
        for node in doc['nodes']:
            if 'mesh' in node:
                for p in doc['meshes'][node['mesh']]['primitives']:
                    names += [doc['materials'][p['material']]['name'].lower()] * (doc['accessors'][p['indices']]['count'] // 3)
        assert len(names) == len(faces), entry['name']
        _slots[entry['name']] = faces, np.array(names)
    return _slots[entry['name']]


def placed(data):
    """Every placement: (index, entry, transform, world triangles, material per triangle)."""
    by_asset = {m['source_asset']: m for m in data['meshes']}
    for index, p in enumerate(data['placements']):
        entry = by_asset[p['asset']]
        faces, names = slotted(entry)
        yield index, entry, p['transform'], collision.to_world(p['transform'], faces.reshape(-1, 3)).reshape(-1, 3, 3), names


def colour(names):
    """A map colour per triangle from its material."""
    table = (('water', (88, 140, 190)), ('roof', (176, 92, 64)), ('terrain', (132, 146, 92)), ('ground', (132, 146, 92)),
             ('cobble', (196, 180, 150)), ('flag', (212, 198, 170)), ('piazza', (216, 200, 168)),
             ('plaster', (226, 206, 170)), ('ashlar', (188, 182, 168)), ('stone', (170, 164, 150)),
             ('rubble', (150, 144, 130)), ('wood', (132, 96, 62)), ('iron', (60, 60, 64)), ('vcol', (110, 140, 80)))
    out = np.tile(np.array([180, 175, 165], float), (len(names), 1))
    for word, rgb in table[::-1]:
        out[np.char.find(names.astype(str), word) >= 0] = rgb
    return out


def rasterise(faces, rgb, box, cell=MAP_CELL):
    """Top view: the highest face's height and colour per cell over `box` (x0, y0, x1, y1)."""
    w, h = int((box[2] - box[0]) / cell), int((box[3] - box[1]) / cell)
    top = np.full(w * h, -np.inf); col = np.zeros((w * h, 3))
    span = np.linalg.norm(faces[:, [1, 2, 0]] - faces, axis=2).max(1)
    k = np.clip(np.ceil(span / cell * 1.5), 1, 400).astype(int)
    for n in np.unique(k):
        sel = np.flatnonzero(k == n)
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1)); m = i + j <= n
        bc = np.stack([i[m], j[m], n - i[m] - j[m]], 1) / n
        for chunk in np.array_split(sel, max(1, len(sel) * len(bc) // 2_000_000)):
            p = np.einsum('kb,tbd->tkd', bc, faces[chunk]).reshape(-1, 3)
            c = np.repeat(rgb[chunk], len(bc), 0)
            x = ((p[:, 0] - box[0]) / cell).astype(int); y = ((box[3] - p[:, 1]) / cell).astype(int)
            ok = (x >= 0) & (x < w) & (y >= 0) & (y < h)
            idx = y[ok] * w + x[ok]; z = p[ok, 2]; c = c[ok]
            order = np.argsort(z)
            idx, z, c = idx[order], z[order], c[order]
            better = z > top[idx]
            top[idx[better]] = z[better]; col[idx[better]] = c[better]   # sorted: the last write per cell is the highest
    top = top.reshape(h, w); col = col.reshape(h, w, 3)
    filled = np.isfinite(top); z = np.where(filled, top, np.nanmin(np.where(filled, top, np.nan)))
    gy, gx = np.gradient(z, cell)
    shade = np.clip(.75 + (-gx * .6 + gy * .6) / np.sqrt(1 + gx ** 2 + gy ** 2) * .5, .35, 1.15)
    img = np.where(filled[..., None], col * shade[..., None], 245)
    return Image.fromarray(np.clip(img, 0, 255).astype('u1'))


def owner_lookup(faces, owner, cell=1.):
    """owner_of(points): the owner of the nearest triangle centroid within a metre of each plan point (-1 if none)."""
    c = faces.mean(1)
    keys = {}
    for i, k in enumerate(map(tuple, np.floor(c[:, :2] / cell).astype(int))):
        keys.setdefault(k, []).append(i)

    def owner_of(points):
        out = []
        for p in points:
            k = np.floor(p[:2] / cell).astype(int); best, who = 1e9, -1
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for i in keys.get((k[0] + dx, k[1] + dy), ()):
                        d = np.linalg.norm(c[i] - p)
                        if d < best:
                            best, who = d, owner[i]
            out.append(int(who))
        return out
    return owner_of


def nosings(riding_t, solid_t):
    """Stair edges (plan metres): deck edges that would be lips but for grind.lips' stair test."""
    riding = grind.heights(riding_t); solid = grind.heights(np.concatenate([riding_t, solid_t]))
    a, b, out = grind.deck_edges(riding_t)
    m = (a + b) / 2; y = m[:, 1]
    inner = m - grind.NEAR * out; outer = m + grind.NEAR * out
    ok = riding(inner, y - grind.SNAP, y + grind.SNAP) & ~solid(outer, y - grind.SNAP, y + grind.SNAP)
    a, b, out, m, y = a[ok], b[ok], out[ok], m[ok], y[ok]
    depth = np.minimum(np.stack([y - solid(m + d * out, y - grind.DROP[1], y - grind.SNAP, top=True) for d in grind.TREAD], 1), 1e3)
    flat = np.abs(depth[:, 1] - depth[:, 0]) < grind.SNAP / 4
    stair = flat & (depth[:, 0] < grind.RISER) & (depth[:, 0] > grind.SNAP) & (depth[:, 2:].max(1) - depth[:, 1] > grind.SNAP * 2)
    return [np.array(l) @ TO_NATIVE for l in grind.chain(a[stair], b[stair])
            if np.linalg.norm(np.diff(l, axis=0), axis=1).sum() >= 1.]


def bars(faces, names, owner, ground):
    """Thin iron or wooden members whose top runs at grind height over the ground: [(owner, top line (2, 3))]."""
    out = []
    thin = np.flatnonzero((np.char.find(names.astype(str), 'iron') >= 0) | (np.char.find(names.astype(str), 'wood') >= 0))
    if not len(thin):
        return out
    v = faces[thin].reshape(-1, 3); key = np.round(v * 200).astype(np.int64)     # welded at 5 mm
    _, inv = np.unique(key, axis=0, return_inverse=True); inv = inv.ravel().reshape(-1, 3)
    parent = np.arange(inv.max() + 1)

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for t in inv:
        r = [find(i) for i in t]
        for x in r[1:]:
            parent[x] = r[0]
    comp = np.array([find(t[0]) for t in inv])
    for c in np.unique(comp):
        sel = thin[comp == c]; p = faces[sel].reshape(-1, 3)
        xy = p[:, :2] - p[:, :2].mean(0)
        _, _, axes = np.linalg.svd(xy, full_matrices=False)
        along = xy @ axes[0]; across = xy @ axes[1]
        length = along.max() - along.min()
        if length < BAR_LENGTH or across.max() - across.min() > BAR_THICK:
            continue
        top = p[:, 2].max()
        ends = p[:, :2].mean(0) + np.outer([along.min(), along.max()], axes[0])
        mid = p[:, :2].mean(0)
        g = ground(np.array([[mid[0], mid[1], top]]))[0]
        if not BAR_HEIGHT[0] <= top - g <= BAR_HEIGHT[1]:
            continue
        out.append((int(owner[sel[0]]), np.c_[ends, [top, top]], float(top - g), float(length)))
    return out


def street_query(rows):
    """above(line): a line's median height over the street (the lowest street or terrain top within STREET_M of each
    point), None where there is none: what a skater rolling by has to clear."""
    ground = grind.heights(np.concatenate([f for _, e, _, f, _ in rows if e['name'].startswith(STREETS)]) @ TO_NATIVE.T)

    def above(line):
        line = np.asarray(line, float); low = np.full(len(line), np.inf)
        for dx in (-STREET_M, 0., STREET_M):
            for dy in (-STREET_M, 0., STREET_M):
                q = (line + [dx, dy, 0.]) @ TO_NATIVE.T
                top = ground(q, q[:, 1] - 30., q[:, 1] + .05, top=True)
                low = np.minimum(low, np.where(np.isfinite(top), top, np.inf))
        ok = np.isfinite(low)
        return round(float(np.median(line[ok, 2] - low[ok])), 2) if ok.any() else None
    return above


def follows(line, registered):
    """Share of a line's points within FOLLOW of a registered line."""
    if not registered:
        return 0.
    seg = np.concatenate([np.stack([r[:-1], r[1:]], 1) for r in registered])
    a, b = seg[:, 0], seg[:, 1]; ab = b - a
    t = np.clip(np.einsum('pkd,kd->pk', line[:, None] - a[None], ab) / np.maximum((ab * ab).sum(1), 1e-9), 0, 1)
    d = np.linalg.norm(line[:, None] - (a[None] + t[..., None] * ab[None]), axis=2).min(1)
    return float((d <= FOLLOW).mean())


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--buildings', type=Path, help='belmonte_collision_audit.py --json output')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    log = lambda *a: print(f'[{time.time() - t0:6.1f}s]', *a, flush=True)
    data = source.manifest()
    rows = list(placed(data))
    blocks = np.concatenate([f.reshape(-1, 3) for _, e, _, f, _ in rows if e['name'].startswith('SM_BM_BT_blk_')])
    box = (*(blocks[:, :2].min(0) - TOWN_MARGIN), *(blocks[:, :2].max(0) + TOWN_MARGIN))
    box = tuple(float(np.floor(v)) for v in box)
    log('town box', box)

    def inside(points):
        return (points[..., 0] >= box[0]) & (points[..., 0] <= box[2]) & (points[..., 1] >= box[1]) & (points[..., 1] <= box[3])
    faces, names, owner = [], [], []
    for index, entry, _, f, n in rows:
        keep = inside(f).any(1)
        if keep.any():
            faces.append(f[keep]); names.append(n[keep]); owner.append(np.full(keep.sum(), index))
    faces, names, owner = np.concatenate(faces), np.concatenate(names), np.concatenate(owner)
    log(f'{len(faces)} drawn triangles in town')
    rasterise(faces, colour(names), box).save(args.out / 'map.png')
    log('map drawn')

    hard = np.array([not any(w in n for w in SOFT) for n in names])
    native = faces[hard] @ TO_NATIVE.T
    lines = grind.grind_lines(native, native[:0])
    lips_plan = [l @ TO_NATIVE for l in lines]
    log(f'{len(lips_plan)} lips')
    stairs = nosings(native, native[:0])
    log(f'{len(stairs)} stair nosings')
    riding = grind.heights(native)

    def ground(points):     # the highest hard surface under each plan point, below its z less 5 cm
        q = points @ TO_NATIVE.T
        return riding(q, q[:, 1] - 20., q[:, 1] - .05, top=True)
    found_bars = bars(faces[hard], names[hard], owner[hard], ground)
    log(f'{len(found_bars)} bars')

    by_asset = {m['source_asset']: m for m in data['meshes']}
    registered, report = [], {}
    for entry in data['meshes']:
        if furniture.is_furniture(entry['name']):
            path = source.LIBRARY / entry['path']
            item = furniture.generate(entry, path, run=furniture.run_axis(data, entry, path))
            report[entry['name']] = furniture.rails(item)
    for r in furniture.placed_rails(data, report):
        registered.append({'id': r['id'], 'kind': r['kind'], 'points': np.asarray(r['points']) / [100., -100., 100.]})
    log(f'{len(registered)} registered lines')
    town_registered = [r for r in registered if inside(r['points']).any()]
    reg_points = [r['points'] for r in town_registered]
    owner_of = owner_lookup(faces[hard], owner[hard])
    above = street_query(rows)
    name_of = lambda i: by_asset[data['placements'][i]['asset']]['name'] if i >= 0 else ''
    round_line = lambda l: np.round(np.asarray(l)[:, :3], 2).tolist()
    lips_out = []
    for l in lips_plan:
        o = owner_of([l[len(l) // 2]])[0]
        lips_out.append({'owner': name_of(o), 'placement': o, 'family': family(name_of(o)) if o >= 0 else 'other',
                         'length_m': round(float(np.linalg.norm(np.diff(l, axis=0), axis=1).sum()), 2),
                         'height_m': round(float(l[:, 2].mean()), 2), 'followed': round(follows(l, reg_points), 2),
                         'above_street_m': above(l), 'points': round_line(l)})
    stairs_out = [{'owner': name_of(o), 'length_m': round(float(np.linalg.norm(np.diff(l, axis=0), axis=1).sum()), 2),
                   'above_street_m': above(l), 'points': round_line(l)} for l in stairs for o in owner_of([l[len(l) // 2]])]
    bars_out = [{'owner': name_of(o), 'placement': o, 'family': family(name_of(o)), 'height_m': round(h, 2),
                 'length_m': round(n, 2), 'points': round_line(l), 'followed': round(follows(l, reg_points), 2),
                 'above_street_m': above(l)}
                for o, l, h, n in found_bars]
    props = []
    reg_by_index = {}
    for r in town_registered:
        reg_by_index.setdefault(int(r['id'].rsplit('_', 2)[1]), []).append(r['id'])
    for index, entry, t, f, _ in rows:
        fam = family(entry['name'])
        if fam in ('ground', 'building', 'other') or not inside(f.reshape(-1, 3)).any():
            continue
        c = f.reshape(-1, 3)
        props.append({'name': entry['name'], 'placement': index, 'family': fam,
                      'centre': np.round(c.mean(0), 2).tolist(), 'size_m': np.round(np.ptp(c, 0), 2).tolist(),
                      'lines': reg_by_index.get(index, [])})
    buildings = []
    if args.buildings and args.buildings.exists():
        audit = {r['name']: r for r in json.loads(args.buildings.read_text())}
        for name, (transform, entries) in collision.buildings(data).items():
            pts = np.concatenate([collision.to_world(transform, slotted(e)[0].reshape(-1, 3)) for e in entries])
            if not inside(pts).any():
                continue
            row = audit.get(name, {})
            hull = furniture.hull2d(pts[:, :2])
            buildings.append({'name': name, 'footprint': np.round(hull, 1).tolist(),
                              'hulls': row.get('hulls'), 'generated': row.get('generated')})
    out = {'box': box, 'cell_m': MAP_CELL, 'lips': lips_out, 'nosings': stairs_out, 'bars': bars_out,
           'registered': [{'id': r['id'], 'kind': r['kind'], 'points': round_line(r['points'])} for r in town_registered],
           'props': props, 'buildings': buildings}
    (args.out / 'audit.json').write_text(json.dumps(out, separators=(',', ':')) + '\n')
    log(f"done: {len(lips_out)} lips ({sum(l['followed'] > .5 for l in lips_out)} followed), {len(stairs_out)} nosings, "
        f"{len(bars_out)} bars, {len(town_registered)} registered, {len(props)} props, {len(buildings)} buildings")


if __name__ == '__main__':
    main()
