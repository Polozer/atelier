"""Remove the wooden bench's armrests from the committed Belmonte library (the owner's decision, 2026-10-21).

    uv run python games/yorimichi/tools/belmonte_armless_bench.py

The armrests stand on the seat at both ends and stop the board's nose, so the seat could not be ground. This removes
the four boxes that make them (the two front arm posts, from the seat up, and the two arm bars) from
assets/belmonte/meshes/SM_BM_BP_Bench.glb and records the edit in source.json. Legs, seat slats, back posts and
backrest stay. It refuses a model that is neither the extracted original nor the armless result.
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from atelier.gltf import glb_pack, glb_parts  # noqa: E402
from belmonte import source  # noqa: E402

NAME = 'SM_BM_BP_Bench'
ORIGINAL = 'a8d51d9eca3d9b1c3c1016b66c89a11e0041225d5d1bc8c656b2f4dacc090b2e'
EDIT = 'armrests removed so the seat can be ground (owner decision 2026-10-21)'
# Local plan metres (x along the seat, y front +, z up): what an armrest box lies within.
ARM_X = (.74, .82)          # |x|: the ends of the seat
POSTS = ((.14, .22), (.43, .67))    # (y, z): the front arm posts, from the seat to the arm
ARMS = ((-.24, .22), (.65, .70))    # (y, z): the arm bars


def armrests(vertices, faces):
    """Mask of the faces (k, 3) of the boxes (closed pieces, welded at a millimetre) lying wholly in an armrest box."""
    key = np.unique(np.round(vertices * 1000).astype(np.int64), axis=0, return_inverse=True)[1].ravel()
    parent = np.arange(key.max() + 1)

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for f in key[faces]:
        for j in f[1:]:
            parent[find(j)] = find(f[0])
    piece = np.array([find(key[f[0]]) for f in faces])
    out = np.zeros(len(faces), bool)
    for p in np.unique(piece):
        points = vertices[faces[piece == p].ravel()]
        end = (np.abs(points[:, 0]) >= ARM_X[0]) & (np.abs(points[:, 0]) <= ARM_X[1])
        within = lambda box: ((points[:, 1] >= box[0][0]) & (points[:, 1] <= box[0][1]) &
                              (points[:, 2] >= box[1][0]) & (points[:, 2] <= box[1][1]))
        out[piece == p] = bool((end & within(POSTS)).all() or (end & within(ARMS)).all())
    return out


def main():
    manifest = source.MANIFEST
    data = json.loads(manifest.read_text())
    entry = next(m for m in data['meshes'] if m['name'] == NAME)
    path = source.LIBRARY / entry['path']
    payload = path.read_bytes()
    sha = hashlib.sha256(payload).hexdigest()
    if EDIT in entry.get('edits', ()) and sha == entry['sha256']:
        print(f'{NAME}: already armless ({entry["triangles"]} triangles)')
        return 0
    if sha != ORIGINAL:
        raise SystemExit(f'{NAME}: unexpected model {sha}; refusing to edit it')
    doc, binary = glb_parts(payload)
    binary = bytearray(binary)
    removed = 0
    for node in doc['nodes']:
        if 'mesh' not in node:
            continue
        for primitive in doc['meshes'][node['mesh']]['primitives']:
            pos = doc['accessors'][primitive['attributes']['POSITION']]
            view = doc['bufferViews'][pos['bufferView']]
            vertices = np.frombuffer(binary, '<f4', pos['count'] * 3, view.get('byteOffset', 0) + pos.get('byteOffset', 0))
            vertices = vertices.reshape(-1, 3).astype(float) @ source.FRAME.T
            acc = doc['accessors'][primitive['indices']]
            iview = doc['bufferViews'][acc['bufferView']]
            dtype = {5121: 'u1', 5123: '<u2', 5125: '<u4'}[acc['componentType']]
            offset = iview.get('byteOffset', 0) + acc.get('byteOffset', 0)
            faces = np.frombuffer(binary, dtype, acc['count'], offset).reshape(-1, 3)
            keep = ~armrests(vertices, faces)
            kept = faces[keep].ravel()
            # Rewrite the index run in place: the kept faces first, the accessor shortened to them.
            binary[offset:offset + kept.nbytes] = kept.astype(dtype).tobytes()
            acc['count'] = int(kept.size)
            removed += int((~keep).sum())
    if removed != 48:
        raise SystemExit(f'{NAME}: expected the 4 armrest boxes (48 triangles), found {removed}')
    out = glb_pack(doc, bytes(binary))
    path.write_bytes(out)
    faces = source.triangles(path).reshape(-1, 3)
    entry.update(sha256=hashlib.sha256(out).hexdigest(), triangles=entry['triangles'] - removed,
                 bounds_m=[faces.min(0).tolist(), faces.max(0).tolist()], edits=[EDIT])
    manifest.write_text(json.dumps(data, separators=(',', ':'), ensure_ascii=False) + '\n')
    print(f'{NAME}: removed {removed} armrest triangles, {entry["triangles"]} left')
    return 0


if __name__ == '__main__':
    sys.exit(main())
