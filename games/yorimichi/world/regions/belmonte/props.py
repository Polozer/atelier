"""Belmonte props made for the game (tools/belmonte_props.py, assets/belmonte/props/<slug>/), each standing in for an
extracted model at every placement the scene gave it.

The owner's decision (2026-10-22): one real armless bench, used at every bench of Belmonte, so its seat grinds. The
extracted library and source.json stay as they are: world.belmonte fits the prop to the model it replaces (the same
height and back plane, facing the same way), writes it under build/, and points that model's entry, its material
slot and its placements at it. Its collision and grind lines then come from the general furniture and skate rules.
"""
import hashlib
import json

import numpy as np
from atelier.gltf import glb_pack, glb_parts

from . import collision, source

LIBRARY = source.LIBRARY / 'props'
# Extracted model -> the prop that stands in for it.
REPLACES = {'SM_BM_BP_Bench': 'bench_armless'}
SLOT = 'Prop'
# '/Atelier/' marks an atlas material (build.finish_surfaces): the prop's own texture on its own UVs.
MATERIAL = '/Atelier/Belmonte/Props/{slug}'


def _accessor(doc, binary, index, width):
    acc = doc['accessors'][index]
    view = doc['bufferViews'][acc['bufferView']]
    offset = view.get('byteOffset', 0) + acc.get('byteOffset', 0)
    assert acc['componentType'] == 5126 and view.get('byteStride', 4 * width) == 4 * width
    return acc, offset


def fit(slug, replaced):
    """(GLB bytes, plan triangles) of the prop fitted to the extracted entry `replaced`: scaled to its height, turned
    to face the same way (its backrest on the same side) and its back on the same plane, centred along its length."""
    data = (LIBRARY / slug / f'{slug}.glb').read_bytes()
    record = json.loads((LIBRARY / slug / 'job.json').read_text())
    assert record['slug'] == slug
    doc, binary = glb_parts(data)
    binary = bytearray(binary)
    faces = source.triangles(LIBRARY / slug / f'{slug}.glb')
    points = faces.reshape(-1, 3)
    lo, hi = np.asarray(replaced['bounds_m'])
    scale = (hi[2] - lo[2]) / np.ptp(points[:, 2])
    # The backrest is what stands over the seat: the side of its tallest quarter.
    tall = points[points[:, 2] > points[:, 2].max() * .75]
    old = source.triangles(source.LIBRARY / replaced['path']).reshape(-1, 3)
    old_tall = old[old[:, 2] > old[:, 2].max() * .75]
    turn = np.sign(tall[:, 1].mean() - points[:, 1].mean()) != np.sign(old_tall[:, 1].mean() - old[:, 1].mean())
    rotate = np.diag([-1., -1., 1.]) if turn else np.eye(3)
    moved = points @ (rotate * scale).T
    back = lo[1] if np.sign(old_tall[:, 1].mean() - old[:, 1].mean()) < 0 else hi[1]
    shift = np.array([-(moved[:, 0].min() + moved[:, 0].max()) / 2,
                      back - (moved[:, 1].min() if back == lo[1] else moved[:, 1].max()),
                      lo[2] - moved[:, 2].min()])
    # The same move in the glTF frame (plan = FRAME @ gltf).
    linear = source.FRAME.T @ (rotate * scale) @ source.FRAME
    turn_only = source.FRAME.T @ rotate @ source.FRAME
    offset_g = source.FRAME.T @ shift
    for node in doc['nodes']:
        assert not any(k in node for k in ('matrix', 'rotation', 'scale', 'translation')), 'a transformed node'
    for mesh in doc['meshes']:
        for primitive in mesh['primitives']:
            acc, at = _accessor(doc, binary, primitive['attributes']['POSITION'], 3)
            v = np.frombuffer(binary, '<f4', acc['count'] * 3, at).reshape(-1, 3).astype(float) @ linear.T + offset_g
            binary[at:at + v.size * 4] = v.astype('<f4').tobytes()
            acc['min'], acc['max'] = v.min(0).tolist(), v.max(0).tolist()
            if 'NORMAL' in primitive['attributes']:
                acc, at = _accessor(doc, binary, primitive['attributes']['NORMAL'], 3)
                n = np.frombuffer(binary, '<f4', acc['count'] * 3, at).reshape(-1, 3).astype(float) @ turn_only.T
                binary[at:at + n.size * 4] = n.astype('<f4').tobytes()
            primitive.pop('material', None)
            primitive['material'] = 0
    doc['materials'] = [dict(doc['materials'][0], name=f'BM_000_{SLOT}')]
    return glb_pack(doc, bytes(binary)), (faces.reshape(-1, 3) @ (rotate * scale).T + shift).reshape(-1, 3, 3)


def texture(glb):
    """The prop's base colour image (bytes, extension)."""
    doc, binary = glb_parts(glb)
    index = doc['materials'][0]['pbrMetallicRoughness']['baseColorTexture']['index']
    image = doc['images'][doc['textures'][index]['source']]
    view = doc['bufferViews'][image['bufferView']]
    start = view.get('byteOffset', 0)
    return bytes(binary[start:start + view['byteLength']]), {'image/jpeg': '.jpg', 'image/png': '.png'}[image['mimeType']]


def apply(data, directory):
    """The manifest with each REPLACES entry standing for its prop: the fitted model and its texture written to
    `directory` (under build/), the entry, its one material slot and its placements pointing at them."""
    data = dict(data, meshes=[dict(m) for m in data['meshes']], materials=dict(data['materials']),
                textures=dict(data['textures']), placements=list(data['placements']))
    directory.mkdir(parents=True, exist_ok=True)
    for entry in data['meshes']:
        slug = REPLACES.get(entry['name'])
        if slug is None:
            continue
        glb, faces = fit(slug, entry)
        model = directory / f"{entry['name']}.glb"
        model.write_bytes(glb)
        image, suffix = texture(glb)
        picture = directory / f'{slug}{suffix}'
        picture.write_bytes(image)
        key = f'props/{slug}'
        data['textures'][key] = {'file': str(picture.resolve()), 'sha256': hashlib.sha256(image).hexdigest()}
        material = MATERIAL.format(slug=slug)
        data['materials'][material] = {'scalars': {}, 'vectors': {'Color': [1., 1., 1., 1.]},
                                       'textures': {'BaseColor': key}}
        points = faces.reshape(-1, 3)
        entry.update(path=str(model.resolve()), sha256=source.sha(model), triangles=len(faces), source_triangles=len(faces),
                     bounds_m=[points.min(0).tolist(), points.max(0).tolist()], slots=[SLOT], prop=slug)
        data['placements'] = [dict(p, materials=[material]) if p['asset'] == entry['source_asset'] else p
                              for p in data['placements']]
    return data


SEAT_BAND_M = .08       # the seat's depth under its top (slats and the steel strip)


def boxes(faces):
    """A seated prop's collision, boxes over what is drawn (plan triangles): the seat from its top (the level with the
    most up-facing area in the lower two thirds) down SEAT_BAND_M, the backrest above it, a leg each side under it.
    Returns (box triangles, metres of drawing left outside, the seat's top)."""
    points = faces.reshape(-1, 3)
    normal = np.cross(faces[:, 1] - faces[:, 0], faces[:, 2] - faces[:, 0])
    area = np.linalg.norm(normal, axis=1) / 2
    up = normal[:, 2] / np.maximum(2 * area, 1e-12) > .9
    z = faces.mean(1)[:, 2]
    low = up & (z < points[:, 2].max() * 2 / 3)
    bins = np.round(z[low] / .01).astype(int)
    seat = float(np.bincount(bins, area[low]).argmax() * .01)
    top = float(z[low & (np.abs(z - seat) <= .03)].max())
    bottom = top - SEAT_BAND_M
    parts = [points[(points[:, 2] >= bottom) & (points[:, 2] <= top)], points[points[:, 2] > top],
             *(points[(points[:, 2] < bottom) & side] for side in (points[:, 0] < 0, points[:, 0] >= 0))]
    spans = [(p.min(0), p.max(0)) for p in parts]
    spans[0] = (np.r_[spans[0][0][:2], bottom], np.r_[spans[0][1][:2], top])
    spans[1] = (np.r_[spans[1][0][:2], top], spans[1][1])
    spans[2:] = [(np.r_[lo[:2], min(lo[2], 0.)], np.r_[hi[:2], bottom]) for lo, hi in spans[2:]]
    out = []
    for lo, hi in spans:
        f = (collision._CORNERS * (hi - lo) + lo)[collision._BOX]
        if np.einsum('ij,ij->i', f[:, 0], np.cross(f[:, 1], f[:, 2])).sum() < 0:
            f = f[:, ::-1]                  # wound outward like the town's collision
        out.append(f)
    outside = np.min([np.maximum(np.maximum(lo - points, points - hi), 0).max(1) for lo, hi in spans], axis=0)
    return np.concatenate(out), float(outside.max()), top
