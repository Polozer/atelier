"""Belmonte building collision, generated from what is drawn, and the audit that measures it.

The committed scene's collision hulls (assets/belmonte/meshes/*_Collision.glb) are coarse boxes: they miss upper
storeys, roofs, chimneys and the grandstand tiers, so a fast player or a board ends up inside the drawn building.
`generate` replaces them, per building, with the drawn surface the open air touches (walls, roofs, soffits,
chimneys, tiers: exactly what the player sees) and solid plugs that close every door and window opening into an
unfurnished interior. Furnished interiors (meshes that carry no hulls, such as the osteria's taproom and the
salon's hall) collide as drawn and stay open. The committed hulls are never modified: the shells are written under
build/ by world.belmonte.

Everything works on a voxel grid in the building's local plan frame (metres, z up). The rendered ground under each
column blocks what lies below it. A walker is a box about CAPSULE_RADIUS_M by CAPSULE_HALF_M about its centre;
"reachable" means its centre can get there from the open air around the building.
"""
from dataclasses import dataclass, field

import numpy as np

from . import planting, source

VOXEL = .2                # metres; the audit tool and the build use this, the fast regression test a coarser grid
MARGIN = 3.
# The walker is 0.44 m wide and 1.51 m tall (AWandererCharacter); at 0.2 m voxels it is a 0.6 m by 1.4 m box.
CAPSULE_RADIUS_M = .2     # metres each side of the centre column
CAPSULE_HALF_M = .6       # metres above and below the centre
DOOR_M = 1.               # openings up to twice this wide are doors and windows; wider ones are open sides
PLUG_M = .2               # plugs fill an interior this deep behind its openings
SIMPLIFY_M = .25          # metres: the cell the kept drawn surface is simplified to
KEEP_M = .3               # metres: drawn surface further than this from the hulls joins the collision
COVER = .30               # metres: a drawn outer wall within this of collision is covered
MAX_UNCOVERED = .002      # the share of drawn outer wall or roof a building's collision may leave uncovered
ROOF_DROP = .50           # metres: a roof whose collision top lies further below it is uncovered
BUILDING_KINDS = ('BT_blk_', 'BH_', 'BHip_', 'BVV_Farm_', 'BE_')
NOT_BUILDINGS = ('Fountain', 'Pozzo', 'Fontanella', 'Grounds', 'Accent', 'Course', 'Infield', 'Arenas', 'Pond',
                 'Yard', 'Gardens', 'Terrace', 'Emblem', 'RailSeg', 'TieRail', 'HayBale', 'GatePier', 'Dist',
                 'FinishPost', 'Jump', 'StartingStalls', 'BaleStack', 'HayCart', 'MountingBlock', 'SaddleRack',
                 'Trough', 'Wheelbarrow', 'OsteriaPergola')


def is_building(name):
    tail = name[len('SM_BM_'):]
    return tail == 'BP_Kiosk' or (tail.startswith(BUILDING_KINDS) and not any(w in tail for w in NOT_BUILDINGS))


def buildings(data=None):
    """{name: (transform, [mesh entries])}: building meshes placed with one transform form one building, named
    after its first hull-carrying mesh."""
    data = data or source.manifest()
    by_asset = {m['source_asset']: m for m in data['meshes']}
    groups = {}
    for placement in data['placements']:
        entry = by_asset[placement['asset']]
        if not is_building(entry['name']):
            continue
        t = placement['transform']
        key = (tuple(round(v, 1) for v in t['translation_cm']), tuple(round(v, 4) for v in t['rotation_xyzw']))
        groups.setdefault(key, (t, []))[1].append(entry)
    out = {}
    for t, entries in groups.values():
        entries.sort(key=lambda e: ('collision' not in e, e['name']))
        out[entries[0]['name']] = (t, entries)
    return dict(sorted(out.items()))


def to_world(transform, points):
    """Local plan metres -> region plan metres."""
    native = np.asarray(points, float) * [100., -100., 100.] * transform['scale']
    native = planting.rotate(transform['rotation_xyzw'], native) + transform['translation_cm']
    return native / [100., -100., 100.]


# ---------------------------------------------------------------------------------------------------- voxels

def _samples(faces, h):
    """Yield (triangle indices, (k, m, 3) sample points) with spacing <= h/3 over each triangle."""
    a, b, c = faces[:, 0], faces[:, 1], faces[:, 2]
    longest = np.max([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)], 0)
    steps = np.maximum(1, np.ceil(longest / (h / 3.))).astype(int)
    for n in np.unique(steps):
        sel = np.flatnonzero(steps == n)
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing='ij')
        keep = i + j <= n
        u, v = i[keep] / n, j[keep] / n
        A, B, C = a[sel, None], b[sel, None], c[sel, None]
        chunk = max(1, 2_000_000 // len(u))       # about 50 MB of sample points at a time
        for start in range(0, len(sel), chunk):
            part = slice(start, start + chunk)
            yield sel[part], A[part] + (B[part] - A[part]) * u[None, :, None] + (C[part] - A[part]) * v[None, :, None]


def dilate(grid, rx=0, rz=0):
    """Box dilation by rx voxels in x and y and rz in z."""
    out = grid.copy()
    for axis, r in ((0, rx), (1, rx), (2, rz)):
        if r <= 0:
            continue
        src = out.copy()
        for k in range(1, r + 1):
            a = [slice(None)] * 3
            b = [slice(None)] * 3
            a[axis], b[axis] = slice(k, None), slice(None, -k)
            out[tuple(a)] |= src[tuple(b)]
            out[tuple(b)] |= src[tuple(a)]
    return out


def grow(grid):
    """6-connected dilation by one voxel."""
    out = grid.copy()
    for axis in range(3):
        a = [slice(None)] * 3
        b = [slice(None)] * 3
        a[axis], b[axis] = slice(1, None), slice(None, -1)
        out[tuple(a)] |= grid[tuple(b)]
        out[tuple(b)] |= grid[tuple(a)]
    return out


def flood(free, seed):
    """6-connected flood of `free` from `seed`: whole free runs along each axis in turn, until nothing changes."""
    assert free.size < 2 ** 30, free.shape
    reach = seed & free
    while True:
        before = int(reach.sum())
        for axis in range(free.ndim):
            f = np.moveaxis(free, axis, -1)
            r = np.moveaxis(reach, axis, -1)
            start = f & ~np.concatenate([np.zeros(f.shape[:-1] + (1,), bool), f[..., :-1]], -1)
            rows = np.arange(int(np.prod(f.shape[:-1])), dtype=np.int32).reshape(f.shape[:-1] + (1,))
            label = np.where(f, rows * np.int32(f.shape[-1] + 1) + np.cumsum(start, -1, dtype=np.int32), np.int32(0))
            hit = np.zeros(int(np.prod(f.shape[:-1])) * (f.shape[-1] + 1) + 1, bool)
            hit[label[r]] = True
            hit[0] = False
            reach = np.moveaxis(hit[label], -1, axis)
        if int(reach.sum()) == before:
            return reach


def mirror(faces):
    """Reverse each triangle's winding. The committed hulls are wound into their solids (all of the library's, unlike
    the drawn meshes): readers that keep a face's side, such as the skate surface, need them turned outward."""
    return np.asarray(faces)[:, [0, 2, 1]]


def cluster(faces, cell):
    """Vertex-clustering simplification: every vertex moves to the mean of its cell's vertices (at most a cell's
    diagonal), and triangles that collapse or repeat go. Surfaces keep their shape to within a cell."""
    if not len(faces):
        return faces
    points = faces.reshape(-1, 3)
    cells, index = np.unique(np.floor(points / cell).astype(np.int64), axis=0, return_inverse=True)
    index = index.ravel()
    mean = np.zeros((len(cells), 3))
    np.add.at(mean, index, points)
    mean /= np.bincount(index, minlength=len(cells))[:, None]
    tri = index.reshape(-1, 3)
    keep = (tri[:, 0] != tri[:, 1]) & (tri[:, 1] != tri[:, 2]) & (tri[:, 2] != tri[:, 0])
    tri = tri[keep]
    _, first = np.unique(np.sort(tri, 1), axis=0, return_index=True)
    tri = tri[np.sort(first)]
    # Clustering can pull a surface in by up to half a cell: push every vertex out along its area-weighted normal
    # (the drawn faces wind outward) by that much, so the collision never sinks into what is drawn.
    a, b, c = mean[tri[:, 0]], mean[tri[:, 1]], mean[tri[:, 2]]
    n = np.cross(b - a, c - a)
    normal = np.zeros_like(mean)
    for k in range(3):
        np.add.at(normal, tri[:, k], n)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    return (mean + normal * cell / 2)[tri]


def components(cells):
    """6-connected components of voxel index rows: a list of (n, 3) arrays."""
    dims = cells.max(0) + 2
    key = (cells[:, 0] * dims[1] + cells[:, 1]) * dims[2] + cells[:, 2]
    order = np.argsort(key)
    cells, key = cells[order], key[order]
    label = np.arange(len(key))
    pairs = []
    for step in (dims[1] * dims[2], dims[2], 1):
        at = np.searchsorted(key, key + step)
        ok = (at < len(key)) & (key[np.minimum(at, len(key) - 1)] == key + step)
        pairs.append(np.stack([np.flatnonzero(ok), at[ok]], 1))
    pairs = np.concatenate(pairs)
    while len(pairs):
        low = np.minimum(label[pairs[:, 0]], label[pairs[:, 1]])
        new = label.copy()
        np.minimum.at(new, pairs[:, 0], low)
        np.minimum.at(new, pairs[:, 1], low)
        new = new[new]
        if np.array_equal(new, label):
            break
        label = new
    return [cells[label == value] for value in np.unique(label)]


def boxes2d(sheet):
    """Greedy rectangles covering a 2D mask exactly: [((u0, v0), (u1, v1))], exclusive upper corners."""
    todo = sheet.copy()
    out = []
    for a, b in np.argwhere(sheet):
        if not todo[a, b]:
            continue
        b1 = b + 1
        while b1 < sheet.shape[1] and todo[a, b1]:
            b1 += 1
        a1 = a + 1
        while a1 < sheet.shape[0] and todo[a1, b:b1].all():
            a1 += 1
        todo[a:a1, b:b1] = False
        out.append(((a, b), (a1, b1)))
    return out


# Twelve outward-wound triangles of a box, corners numbered by their (x, y, z) bits.
_BOX = np.array([[0, 2, 3], [0, 3, 1], [4, 5, 7], [4, 7, 6], [0, 1, 5], [0, 5, 4],
                 [2, 6, 7], [2, 7, 3], [0, 4, 6], [0, 6, 2], [1, 3, 7], [1, 7, 5]])
_CORNERS = np.array([[i & 1, i >> 1 & 1, i >> 2 & 1] for i in range(8)], float)


@dataclass
class Building:
    """One building on its voxel grid: what is drawn, the closed envelope and its furnished rooms."""
    name: str
    transform: dict
    entries: list
    drawn: dict                   # mesh name -> local triangles
    lo: np.ndarray
    shape: tuple
    ground: np.ndarray            # (nx, ny) rendered ground height, local metres
    below: np.ndarray             # voxels under the rendered ground
    visual: np.ndarray
    interior: np.ndarray          # roofed space behind openings up to 2 m wide, not furnished
    outside: np.ndarray           # open air, reaching into openings
    solid: np.ndarray             # everything the envelope closes (walls and interiors)
    rooms: np.ndarray             # furnished interiors, which the player may enter
    h: float = VOXEL

    def voxels(self, metres):
        return max(1, int(round(metres / self.h)))

    def index(self, points):
        return np.clip(np.floor((points - self.lo) / self.h).astype(int), 0, np.array(self.shape) - 1)

    def rasterise(self, faces):
        grid = np.zeros(self.shape, bool)
        if len(faces):
            for _, pts in _samples(np.asarray(faces, float), self.h):
                idx = np.floor((pts.reshape(-1, 3) - self.lo) / self.h).astype(int)
                idx = idx[np.all((idx >= 0) & (idx < self.shape), 1)]
                grid[idx[:, 0], idx[:, 1], idx[:, 2]] = True
        return grid

    def touching(self, faces, mask):
        out = np.zeros(len(faces), bool)
        for sel, pts in _samples(faces, self.h):
            idx = self.index(pts.reshape(-1, 3))
            out[sel] = mask[idx[:, 0], idx[:, 1], idx[:, 2]].reshape(len(sel), -1).any(1)
        return out

    def open_air(self):
        """Air the player may be in: outside, courtyards and furnished rooms; not walls, ground or interiors."""
        return ~self.visual & ~self.below & ~self.interior

    def forbidden(self):
        """Where a walker's centre must never be: inside a drawn wall or an unfurnished interior."""
        return (self.interior | (self.visual & self.solid)) & ~self.rooms

    def border(self):
        seed = np.zeros(self.shape, bool)
        seed[0], seed[-1], seed[:, 0], seed[:, -1], seed[:, :, -1] = True, True, True, True, True
        return seed

    def reachable(self, occupied):
        free = ~dilate(occupied | self.below, self.voxels(CAPSULE_RADIUS_M), self.voxels(CAPSULE_HALF_M))
        return flood(free, self.border())

    def clear(self):
        """Open air more than a voxel from anything drawn or enclosed: where no collision may stand."""
        return self.outside & ~dilate(self.visual | self.interior, 1, 1)

    def stands_off(self, lo, hi, frame, origin, clear):
        """Does the oriented box (local lo..hi in `frame` about `origin`) reach a voxel of `clear`?"""
        corners = (lo + (hi - lo) * _CORNERS) @ frame + origin
        a, z = self.index(corners.min(0) - self.h), self.index(corners.max(0) + self.h) + 1
        grid = np.stack(np.meshgrid(*(np.arange(a[k], z[k]) for k in range(3)), indexing='ij'), -1).reshape(-1, 3)
        local = (self.lo + (grid + .5) * self.h - origin) @ frame.T
        inside = np.all((local > lo - self.h / 2) & (local < hi + self.h / 2), 1)   # every voxel the box touches
        cells = grid[inside]
        return bool(clear[cells[:, 0], cells[:, 1], cells[:, 2]].any())

    def plug_faces(self, mask, smallest=1):
        """Closed solids filling a plug mask: each connected piece is its voxels' oriented box (principal axes across
        the plan, z upright) when that box stays out of the open air, or else the merged surface of its voxels."""
        cells = np.argwhere(mask)
        if not len(cells):
            return np.zeros((0, 3, 3))
        clear = self.clear()
        out = []
        for part in components(cells):
            if len(part) >= smallest:
                self._slab(part, clear, out)
        if not out:
            return np.zeros((0, 3, 3))
        return np.concatenate(out)

    def _slab(self, part, clear, out):
        centres = self.lo + (part + .5) * self.h
        origin = centres.mean(0)
        xy = centres[:, :2] - origin[:2]
        axes = np.linalg.svd(xy, full_matrices=False)[2] if len(xy) > 1 else np.eye(2)
        frame = np.eye(3)
        frame[:2, :2] = axes
        local = (centres - origin) @ frame.T
        lo, hi = local.min(0) - self.h / 2, local.max(0) + self.h / 2
        if not self.stands_off(lo, hi, frame, origin, clear):
            corners = (lo + 1e-3 + (hi - lo - 2e-3) * _CORNERS) @ frame + origin
            if np.linalg.det(frame) < 0:           # keep the boxes wound outward
                corners = corners[[1, 0, 3, 2, 5, 4, 7, 6]]
            out.append(corners[_BOX])
            return
        # Not a slab (an L round a corner, a ragged leak): the closed surface of its voxels, nothing in the open air.
        start = part.min(0)
        voxels = np.zeros(tuple(part.max(0) - start + 3), bool)
        voxels[tuple((part - start + 1).T)] = True
        out.append(self.voxel_surface(voxels, start - 1))

    def voxel_surface(self, voxels, offset):
        """The closed, outward-wound surface of a voxel solid, each face plane merged into greedy rectangles."""
        quads = []
        for axis in range(3):
            u, v = [k for k in range(3) if k != axis]
            for sign in (1, -1):
                exposed = voxels & ~np.roll(voxels, -sign, axis)
                for layer in np.flatnonzero(exposed.any(tuple(k for k in range(3) if k != axis))):
                    sheet = np.take(exposed, layer, axis)
                    plane = layer + (1 if sign > 0 else 0)
                    for (a0, b0), (a1, b1) in boxes2d(sheet):
                        corner = np.zeros((4, 3))
                        corner[:, axis] = plane
                        corner[:, u] = [a0, a1, a1, a0]
                        corner[:, v] = [b0, b0, b1, b1]
                        quads.append(corner if (sign > 0) == ((axis == 1) ^ True) else corner[::-1])
        if not quads:
            return np.zeros((0, 3, 3))
        q = np.array(quads) + offset
        faces = np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])
        # Draw every vertex a hair into the solid, so the surface rasterises into its own voxels only.
        keys, index = np.unique(faces.reshape(-1, 3).round(3), axis=0, return_inverse=True)
        n = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
        normal = np.zeros_like(keys)
        for k in range(3):
            np.add.at(normal, index.reshape(-1, 3)[:, k], n)
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
        points = keys - normal * 5e-3
        return points[index.reshape(-1, 3)] * self.h + self.lo


def furnished(entries):
    """Meshes without hulls are furnished interiors the player enters: they collide as drawn."""
    return [e for e in entries if 'collision' not in e]


def load(name, transform, entries, ground=None, h=VOXEL):
    drawn = {e['name']: source.triangles(source.LIBRARY / e['path']) for e in entries}
    faces = np.concatenate(list(drawn.values()))
    lo = faces.reshape(-1, 3).min(0) - MARGIN
    shape = tuple(np.ceil((faces.reshape(-1, 3).max(0) + MARGIN - lo) / h).astype(int))
    x = lo[0] + (np.arange(shape[0]) + .5) * h
    y = lo[1] + (np.arange(shape[1]) + .5) * h
    X, Y = np.meshgrid(x, y, indexing='ij')
    world = to_world(transform, np.stack([X.ravel(), Y.ravel(), np.zeros(X.size)], 1))
    origin_z = to_world(transform, np.zeros((1, 3)))[0, 2]
    gz = (ground or source.terrain()).height(world[:, 0], world[:, 1]) - origin_z
    gz = np.where(np.isfinite(gz), gz, -np.inf).reshape(shape[:2])
    z = lo[2] + (np.arange(shape[2]) + .5) * h
    below = z[None, None, :] < gz[:, :, None]
    b = Building(name, transform, entries, drawn, lo, shape, gz, below, *(np.zeros(shape, bool) for _ in range(5)), h=h)
    b.visual = b.rasterise(faces)
    # Close openings up to 2 m and fill from the open air around the building, never from underground.
    door = b.voxels(DOOR_M)
    walls = dilate(b.visual, door, 0)
    outside = flood(~walls & ~below, b.border() & ~below)
    b.outside = dilate(outside, door, 0) & ~b.visual & ~below
    b.solid = ~b.outside & ~below
    roofed = np.flip(np.logical_or.accumulate(np.flip(b.visual, 2), 2), 2)   # a courtyard is open to the sky
    for e in furnished(entries):
        f = drawn[e['name']].reshape(-1, 3)
        lo_i, hi_i = b.index(f.min(0) - 1.), b.index(f.max(0) + 1.) + 1
        b.rooms[lo_i[0]:hi_i[0], lo_i[1]:hi_i[1], lo_i[2]:hi_i[2]] = True
    b.interior = b.solid & ~b.visual & roofed & ~b.rooms
    return b


# ---------------------------------------------------------------------------------------------------- shells

@dataclass
class Shell:
    """Generated collision for one building: per mesh name, local plan-metre triangles."""
    name: str
    faces: dict
    skin_triangles: int
    plugs: int
    plug_triangles: int = 0


def generate(b):
    """@cc [owner:fontanierh,label:correctness] belmonte-buildings-collide-as-drawn
    A building MUST collide with its committed hulls plus every drawn triangle the open air touches further than
    KEEP_M from them (upper storeys, roofs, chimneys, stand tiers the hulls miss), plus plugs closing every opening
    up to 2 m into an unfurnished interior a walker fits in. A walker MUST NOT reach inside a drawn wall or such an
    interior. Furnished meshes (no committed hulls) MUST collide as drawn and stay open to walk into.
    The kept drawn surface is simplified to SIMPLIFY_M where that makes the whole collision lighter.
    """
    shells = [_shell(b, cell) for cell in (SIMPLIFY_M, None)]
    return min(shells, key=lambda shell: sum(len(f) for f in shell.faces.values()))


def _shell(b, cell):
    open_air = b.open_air()
    air = dilate(open_air, 1, 1)
    hulls = committed([e for e in b.entries if 'collision' in e])
    near = dilate(b.rasterise(np.concatenate(list(hulls.values()))), b.voxels(KEEP_M), b.voxels(KEEP_M))
    bare = air & ~near
    faces, skin = {}, 0
    for e in b.entries:
        f = b.drawn[e['name']]
        if 'collision' in e:
            kept = f[b.touching(f, bare)]
            kept = cluster(kept, cell) if cell else kept
            skin += len(kept)
            f = np.concatenate([mirror(hulls[e['name']]), kept])     # every face outward, as drawn
        faces[e['name']] = f
    # Close only interiors a walker fits in, as this collision bounds them; cavities inside walls stay as they are.
    blocked = b.rasterise(np.concatenate(list(faces.values()))) | b.below
    r, half = b.voxels(CAPSULE_RADIUS_M), b.voxels(CAPSULE_HALF_M)
    fits = b.interior & ~dilate(blocked, r, half)
    room = dilate(fits, r, half) & b.interior & ~blocked
    plug = open_air
    for _ in range(b.voxels(PLUG_M)):     # grow face to face through the openings, never across a drawn wall
        plug = plug | (grow(plug) & room)
    # Crevices smaller than a walker's opening need no plug; anything still reached is closed just below.
    plugs = [b.plug_faces(plug & room, smallest=b.voxels(.6) ** 2)]
    # Simplification can open a slit a walker squeezes into: close whatever is still reached, where it is reached.
    for _ in range(4):
        occupied = blocked | b.rasterise(plugs[-1])
        blocked = occupied
        reach = b.reachable(occupied)
        leak = reach & b.forbidden()
        if not leak.any():
            break
        plugs.append(b.plug_faces(leak & grow(reach & ~leak)))     # close where the walker gets in
    plugs = np.concatenate(plugs)
    owner = next(e['name'] for e in b.entries if 'collision' in e)
    faces[owner] = np.concatenate([faces[owner], plugs])
    return Shell(b.name, faces, skin, len(plugs) // 12, len(plugs))


def write_glb(path, faces):
    """One flat-shaded triangle mesh in glTF's y-up frame (source.FRAME inverted)."""
    from atelier.gltf import glb_pack
    faces = np.asarray(faces, float)
    position = (faces.reshape(-1, 3) @ source.FRAME).astype('<f4')
    n = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    normal = np.repeat(n @ source.FRAME, 3, 0).astype('<f4')
    index = np.arange(len(position), dtype='<u4')
    blobs = [position.tobytes(), normal.tobytes(), index.tobytes()]
    offsets = np.cumsum([0] + [len(blob) for blob in blobs])
    doc = {'asset': {'version': '2.0', 'generator': 'yorimichi world.belmonte collision'},
           'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0, 'name': 'UCX_' + path.stem}],
           'materials': [{'name': 'M_00_Collision'}],
           'meshes': [{'name': path.stem, 'primitives': [{'attributes': {'POSITION': 0, 'NORMAL': 1}, 'indices': 2,
                                                          'material': 0, 'mode': 4}]}],
           'buffers': [{'byteLength': int(offsets[-1])}],
           'bufferViews': [{'buffer': 0, 'byteOffset': int(offsets[k]), 'byteLength': len(blobs[k]),
                            'target': 34963 if k == 2 else 34962} for k in range(3)],
           'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': len(position), 'type': 'VEC3',
                          'min': position.min(0).tolist(), 'max': position.max(0).tolist()},
                         {'bufferView': 1, 'componentType': 5126, 'count': len(normal), 'type': 'VEC3'},
                         {'bufferView': 2, 'componentType': 5125, 'count': len(index), 'type': 'SCALAR'}]}
    path.write_bytes(glb_pack(doc, b''.join(blobs)))


# ---------------------------------------------------------------------------------------------------- audit

def committed(entries):
    """What the committed scene collides with: its hulls, or the drawn mesh where a mesh has none."""
    return {e['name']: source.triangles(source.LIBRARY / (e['collision']['path'] if 'collision' in e else e['path']))
            for e in entries}


def hull_stats(faces):
    """Connected pieces, edges used by one triangle only, and the thinnest piece of wall height (its least width
    along its own face normals: exact for the convex hulls the scene was authored with)."""
    if not len(faces):
        return 0, 0, 0.
    _, inverse = np.unique(np.round(faces.reshape(-1, 3), 4), axis=0, return_inverse=True)
    tri = inverse.reshape(-1, 3)
    edges = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), 1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    label = np.arange(inverse.max() + 1)
    while True:
        low = np.minimum(label[edges[:, 0]], label[edges[:, 1]])
        new = label.copy()
        np.minimum.at(new, edges[:, 0], low)
        np.minimum.at(new, edges[:, 1], low)
        new = new[new]
        if np.array_equal(new, label):
            break
        label = new
    piece = label[tri[:, 0]]
    thinnest = np.inf
    for p in np.unique(piece):
        f = faces[piece == p]
        pts = f.reshape(-1, 3)
        if len(f) > 64 or np.ptp(pts[:, 2]) < 1.5:
            continue
        n = np.cross(f[:, 1] - f[:, 0], f[:, 2] - f[:, 0])
        n = n[np.linalg.norm(n, axis=1) > 1e-9]
        n /= np.linalg.norm(n, axis=1, keepdims=True)
        proj = pts @ n.T
        thinnest = min(thinnest, float((proj.max(0) - proj.min(0)).min()))
    return len(np.unique(piece)), int((counts == 1).sum()), (0. if not np.isfinite(thinnest) else thinnest)


@dataclass
class Audit:
    name: str
    triangles: int                 # drawn
    collision_triangles: int       # of the meshes that carry their own collision
    pieces: int
    open_edges: int
    thinnest_m: float              # thinnest closed hull of wall height (hull collision only)
    interior_m3: float             # unfurnished interior: roofed, behind openings up to 2 m
    intrusion_m3: float            # interior or drawn wall volume a walker's centre can reach
    intrusion_area_m2: float
    deepest_m: float               # how far past the outer wall the walker gets
    wall_m2: float                 # drawn outer wall
    uncovered_wall_m2: float       # outer wall further than COVER from any collision
    roof_m2: float
    uncovered_roof_m2: float       # roof whose collision top is more than ROOF_DROP lower, or absent
    worst: list = field(default_factory=list)

    @property
    def uncovered_wall(self):
        return self.uncovered_wall_m2 / max(self.wall_m2, 1e-6)

    @property
    def uncovered_roof(self):
        return self.uncovered_roof_m2 / max(self.roof_m2, 1e-6)

    def row(self):
        out = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.__dict__.items()}
        return out | {'uncovered_wall': round(self.uncovered_wall, 4), 'uncovered_roof': round(self.uncovered_roof, 4)}


def audit(b, collision, stats=True):
    """Measure a building's collision ({mesh name: local triangles}) against what is drawn."""
    h = b.h
    occupied = b.rasterise(np.concatenate(list(collision.values())))
    intrusion = b.reachable(occupied) & b.forbidden()
    depth, ring = np.zeros(b.shape, np.int16), b.open_air()
    for d in range(1, 80):
        grown = dilate(ring, 1, 0)
        new = grown & ~ring & intrusion
        if not new.any():
            break
        depth[new] = d
        ring = grown
    worst = []
    if depth.max() > 0:
        worst = to_world(b.transform, b.lo + (np.argwhere(depth == depth.max())[:3] + .5) * h).round(2).tolist()
    wall = dilate(b.outside, 1, 0) & b.visual & ~b.below
    uncovered_wall = wall & ~dilate(occupied, int(np.ceil(COVER / h)), int(np.ceil(COVER / h)))
    zs = np.arange(b.shape[2])
    vtop = np.where(b.visual.any(2), np.max(np.where(b.visual, zs, -1), 2), -1)
    # Collision within COVER sideways holds a roof's edge up (an eave over a wall's hull).
    held = dilate(occupied, int(np.ceil(COVER / h)), 0)
    ctop = np.where(held.any(2), np.max(np.where(held, zs, -1), 2), -1)
    roof = (vtop >= 0) & ((vtop + .5) * h + b.lo[2] - b.ground > 2.5)
    uncovered_roof = roof & ((ctop < 0) | ((vtop - ctop) * h > ROOF_DROP))
    owned = [collision[e['name']] for e in b.entries if 'collision' in e]
    owned = np.concatenate(owned) if owned else np.zeros((0, 3, 3))
    pieces, open_edges, thinnest = hull_stats(owned) if stats else (0, 0, 0.)
    return Audit(name=b.name, triangles=sum(len(f) for f in b.drawn.values()), collision_triangles=len(owned),
                 pieces=pieces, open_edges=open_edges, thinnest_m=thinnest,
                 interior_m3=float(b.interior.sum()) * h ** 3, intrusion_m3=float(intrusion.sum()) * h ** 3,
                 intrusion_area_m2=float(intrusion.any(2).sum()) * h ** 2, deepest_m=float(depth.max()) * h,
                 wall_m2=float(wall.sum()) * h ** 2, uncovered_wall_m2=float(uncovered_wall.sum()) * h ** 2,
                 roof_m2=float(roof.sum()) * h ** 2, uncovered_roof_m2=float(uncovered_roof.sum()) * h ** 2,
                 worst=worst)
