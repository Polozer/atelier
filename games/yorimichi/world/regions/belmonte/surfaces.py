"""What each part of Belmonte's ground is made of, for the skateboard, the bike, footsteps and hooves.

Those read the surface from the material instance a trace hits (USkateSettings::SurfaceKey): a Belmonte instance is
named MI_BM_<hash>__<Key>, and Key is a row of the game's surface tables (DefaultGame.ini SurfaceMaterials,
unreal/Scripts/import_footsteps.py MATERIAL_SURFACES). The key comes from the authored source material the slot was
made with (RULES). The terrain tiles blend four layers in one material by vertex weight: dry grass, green grass, the
pale gravel of the roads and paths, and limestone. Each terrain face goes by its strongest layer (TERRAIN), so the build
writes a tile's faces as one primitive per key, each bound to an identical instance named after its key.
"""
import re

import numpy as np
from atelier.gltf import glb_pack, glb_parts

# Source material (its name without MI_B_ / MID_MI_B_) -> surface key. A material no rule names has no key: its
# instance rides as the tables' default. Water, glass, glows, foliage, painted accents and props are never ground.
RULES = (
    ('Grass', r'^turf$'),
    ('Stone', r'^(cobble|piazza|flag|stone|ashlar|rubble|plaster|plaster_rough|roof|farwall)$'),
    ('Rock', r'^rock_town$'),
    ('Dirt', r'^(gravel|dirt)$'),
    ('Sand', r'^sand$'),
    ('Wood', r'^(wood|floor)$'),
    ('Metal', r'^iron$'),
)
# The terrain's vertex weights (RGBA) in source.TERRAIN_LAYERS order -> the key of a face whose strongest layer it is.
TERRAIN = ('Grass', 'Grass', 'Road', 'Rock')
TERRAIN_KEYS = tuple(dict.fromkeys(TERRAIN))
# The country around the valley (build.surroundings): meadow and forest floor.
COUNTRY = 'Grass'
KEYS = tuple(dict.fromkeys([key for key, _ in RULES] + list(TERRAIN_KEYS) + [COUNTRY]))


def leaf(path):
    """'/Game/Haras/Belmonte/Materials/MI_B_cobble.MI_B_cobble' -> 'cobble'."""
    name = path.rsplit('/', 1)[-1].rsplit('.', 1)[-1]
    return re.sub(r'^(MID_)?MI_B_', '', name)


def terrain_material(path):
    return 'terrain_' in path


def material_key(path):
    """The surface key of a whole source material, None for the terrain (per face) and for what is never ground."""
    if terrain_material(path):
        return None
    name = leaf(path)
    return next((key for key, pattern in RULES if re.search(pattern, name)), None)


def instance_name(base, key):
    return f'{base}__{key}' if key else base


def slot_key(material_name):
    """The key a split GLB material carries ('BM_000_M_terrain.024__Grass' -> 'Grass'), else None."""
    return material_name.rpartition('__')[2] if '__' in material_name else None


def face_keys(weights, faces):
    """The key of each face, by the layer with the largest summed weight over its corners (the shader's blend)."""
    w = np.asarray(weights, float)[:, :4]
    w = w / np.maximum(w.sum(1, keepdims=True), 1e-6)
    layer = w[np.asarray(faces)].sum(1).argmax(1)
    return np.asarray(TERRAIN, object)[layer]


def _accessor(doc, binary, index):
    accessor = doc['accessors'][index]
    view = doc['bufferViews'][accessor['bufferView']]
    dtype = np.dtype({5121: 'u1', 5123: '<u2', 5125: '<u4', 5126: '<f4'}[accessor['componentType']])
    width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[accessor['type']]
    data = np.frombuffer(binary, dtype, accessor['count'] * width, view.get('byteOffset', 0) + accessor.get('byteOffset', 0))
    data = data.reshape(-1, width).astype(float)
    if accessor.get('normalized'):
        data /= {5121: 255., 5123: 65535.}[accessor['componentType']]
    return data


def split_terrain(source, destination):
    """Write a terrain tile with one primitive per surface key; {key: triangles}.

    Every vertex attribute and byte stays as authored: only the faces are reordered within their own index buffer,
    each key's run read by its own accessor, and the tile's material is repeated once per key as <name>__<Key>."""
    doc, binary = glb_parts(source.read_bytes())
    assert len(doc['meshes']) == 1 and len(doc['meshes'][0]['primitives']) == 1, source
    primitive = doc['meshes'][0]['primitives'][0]
    assert primitive.get('mode', 4) == 4 and len(doc['materials']) == 1 and primitive['material'] == 0, source
    index = doc['accessors'][primitive['indices']]
    view = doc['bufferViews'][index['bufferView']]
    faces = _accessor(doc, binary, primitive['indices']).astype(np.int64).reshape(-1, 3)
    keys = face_keys(_accessor(doc, binary, primitive['attributes']['COLOR_0']), faces)
    order = [key for key in TERRAIN_KEYS if (keys == key).any()]
    dtype = {5123: '<u2', 5125: '<u4', 5121: 'u1'}[index['componentType']]
    runs = [faces[keys == key] for key in order]
    packed = np.concatenate(runs).astype(dtype).tobytes()
    start = view.get('byteOffset', 0) + index.get('byteOffset', 0)
    assert len(packed) == index['count'] * np.dtype(dtype).itemsize
    binary = binary[:start] + packed + binary[start + len(packed):]
    base, material = doc['materials'][0]['name'], doc['materials'][0]
    doc['materials'] = [dict(material, name=f'{base}__{key}') for key in order]
    primitives, offset, counts = [], index.get('byteOffset', 0), {}
    for slot, (key, run) in enumerate(zip(order, runs)):
        accessor = {k: v for k, v in index.items() if k not in ('min', 'max')}
        accessor.update(byteOffset=offset, count=int(run.size))
        # The first run keeps the original index accessor, so no other accessor moves.
        if slot == 0:
            doc['accessors'][primitive['indices']] = accessor
            at = primitive['indices']
        else:
            doc['accessors'].append(accessor)
            at = len(doc['accessors']) - 1
        primitives.append(dict(primitive, indices=at, material=slot))
        offset += run.size * np.dtype(dtype).itemsize
        counts[key] = int(len(run))
    doc['meshes'][0]['primitives'] = primitives
    destination.write_bytes(glb_pack(doc, binary))
    return counts


def sample(points, meshes):
    """The surface key under each plan point (local metres from the region origin): the highest of the given
    meshes' upward faces there, as a trace from above finds it. meshes: [(faces (n,3,3), keys (n,))]; '' where
    nothing is under the point."""
    points = np.asarray(points, float)
    best = np.full(len(points), -np.inf)
    result = np.full(len(points), '', object)
    for tris, keys in meshes:
        tris = np.asarray(tris, float)
        lo, hi = tris[:, :, :2].min(1), tris[:, :, :2].max(1)
        for i, (x, y) in enumerate(points):
            near = np.flatnonzero((lo[:, 0] <= x) & (hi[:, 0] >= x) & (lo[:, 1] <= y) & (hi[:, 1] >= y))
            if not len(near):
                continue
            a, b, c = tris[near, 0], tris[near, 1], tris[near, 2]
            e, f = b[:, :2] - a[:, :2], c[:, :2] - a[:, :2]
            det = e[:, 0] * f[:, 1] - e[:, 1] * f[:, 0]
            ok = np.abs(det) > 1e-10
            px, py = x - a[:, 0], y - a[:, 1]
            u = np.where(ok, (px * f[:, 1] - py * f[:, 0]) / np.where(ok, det, 1), -1)
            v = np.where(ok, (e[:, 0] * py - e[:, 1] * px) / np.where(ok, det, 1), -1)
            inside = ok & (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7)
            if not inside.any():
                continue
            z = a[:, 2] + u * (b[:, 2] - a[:, 2]) + v * (c[:, 2] - a[:, 2])
            z = np.where(inside, z, -np.inf)
            top = int(np.argmax(z))
            if z[top] > best[i]:
                best[i], result[i] = z[top], keys[near[top]] or ''
    return result


def ground(data, library, names):
    """[(faces, keys)] of the committed meshes named by names (a predicate), placed by their source placements in
    plan metres from the region origin, as the build binds them: the terrain per face, the rest per slot."""
    from belmonte import planting, source
    placements = {}
    for placement in data['placements']:
        placements.setdefault(placement['asset'], []).append(placement)
    result = []
    for entry in data['meshes']:
        if not names(entry['name']):
            continue
        doc, binary = glb_parts((library / entry['path']).read_bytes())
        for placement in placements.get(entry['source_asset'], ()):
            t = placement['transform']
            for node in doc['nodes']:
                if 'mesh' not in node:
                    continue
                for primitive in doc['meshes'][node['mesh']]['primitives']:
                    local = _accessor(doc, binary, primitive['attributes']['POSITION']) @ source.FRAME.T
                    faces = _accessor(doc, binary, primitive['indices']).astype(np.int64).reshape(-1, 3)
                    native = planting.rotate(t['rotation_xyzw'], local * [100., -100., 100.] * t['scale'])
                    plan = (native + t['translation_cm']) / [100., -100., 100.]
                    slot = int(doc['materials'][primitive['material']]['name'].split('_')[1])
                    path = placement['materials'][slot]
                    if terrain_material(path):
                        keys = face_keys(_accessor(doc, binary, primitive['attributes']['COLOR_0']), faces)
                    else:
                        keys = np.full(len(faces), material_key(path) or '', object)
                    result.append((plan[faces], keys))
    return result
