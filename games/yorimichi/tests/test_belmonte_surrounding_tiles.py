"""The surroundings are drawn as plan tiles that keep every triangle and vertex attribute of the whole surface."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402
from atelier.gltf import glb_pack, glb_parts  # noqa: E402
from belmonte import build as B  # noqa: E402


def attributes(path):
    doc, binary = glb_parts(Path(path).read_bytes())
    primitive = doc['meshes'][0]['primitives'][0]

    def read(index):
        accessor = doc['accessors'][index]
        view = doc['bufferViews'][accessor['bufferView']]
        width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[accessor['type']]
        dtype = '<u4' if accessor['componentType'] == 5125 else '<f4'
        return np.frombuffer(binary, dtype, accessor['count'] * width, view['byteOffset']).reshape(-1, width)

    faces = read(primitive['indices']).reshape(-1, 3)
    return {key: read(index)[faces].reshape(len(faces), -1) for key, index in primitive['attributes'].items()}


def corners(path):
    """Each triangle as the bytes of its three corners' attributes, order-independent across files."""
    data = attributes(path)
    rows = np.concatenate([data[key] for key in sorted(data)], axis=1)
    return sorted(row.tobytes() for row in rows)


def surface(path, columns=13, rows=7, step=100.):
    """A painted grid in the glTF frame (x east, y up, z south) with distinct attributes at every vertex."""
    x, north = np.meshgrid(np.arange(columns) * step - 150., np.arange(rows) * step - 250.)
    position = np.c_[x.ravel(), np.sin(x.ravel() / 70.) * 9., -north.ravel()].astype('<f4')
    count = len(position)
    normal = np.tile([0., 1., 0.], (count, 1)).astype('<f4')
    uv = (position[:, [0, 2]] / 400.).astype('<f4')
    colour = np.c_[np.linspace(0, 1, count), np.linspace(1, 0, count), np.full(count, .3), np.full(count, .7)].astype('<f4')
    quads = [(r * columns + c, r * columns + c + 1, (r + 1) * columns + c, (r + 1) * columns + c + 1)
             for r in range(rows - 1) for c in range(columns - 1)]
    faces = np.array([t for a, b, c, d in quads for t in ((a, c, b), (b, c, d))], '<u4')
    doc = dict(asset={'version': '2.0'}, scene=0, scenes=[{'nodes': [0]}], nodes=[{'mesh': 0}],
               materials=[{'name': 'BM_000_Ground'}], accessors=[], bufferViews=[])
    blob = b''
    for values, kind in [(position, 'VEC3'), (normal, 'VEC3'), (uv, 'VEC2'), (faces, 'SCALAR'), (colour, 'VEC4')]:
        doc['bufferViews'].append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': values.nbytes})
        doc['accessors'].append({'bufferView': len(doc['bufferViews']) - 1, 'type': kind,
                                 'componentType': 5125 if kind == 'SCALAR' else 5126,
                                 'count': int(values.size if kind == 'SCALAR' else len(values))})
        blob += values.tobytes()
    doc['meshes'] = [{'primitives': [{'attributes': {'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2, 'COLOR_0': 4},
                                      'indices': 3, 'material': 0}]}]
    doc['buffers'] = [{'byteLength': len(blob)}]
    path.write_bytes(glb_pack(doc, blob))
    return len(faces)


def test_tiles_partition_the_surface_and_keep_every_attribute(tmp_path, monkeypatch):
    monkeypatch.setattr(B, 'OUT', tmp_path)
    (tmp_path / 'glb').mkdir()
    whole = tmp_path / 'glb' / 'SM_BM_NorthCountry.glb'
    triangles = surface(whole)
    (tmp_path / 'glb' / 'SM_BM_NorthCountry_99.glb').write_bytes(b'stale')
    tiles = B.split_tiles(whole, 500.)
    assert not (tmp_path / 'glb' / 'SM_BM_NorthCountry_99.glb').exists()
    assert [t['name'] for t in tiles] == [f'SM_BM_NorthCountry_{n:02d}' for n in range(len(tiles))]
    assert len(tiles) == 4 * 2 and sum(t['triangles'] for t in tiles) == triangles
    # Every triangle lands in exactly one tile with its corners' positions, normals, UVs and colours bit for bit.
    assert sorted(sum((corners(tmp_path / t['path']) for t in tiles), [])) == corners(whole)
    for tile in tiles:
        position = attributes(tmp_path / tile['path'])['POSITION'].reshape(-1, 3)
        centre = position.reshape(-1, 3, 3).mean(axis=1)
        cells = {tuple(c) for c in np.floor(np.c_[centre[:, 0], -centre[:, 2]] / 500.).astype(int)}
        assert len(cells) == 1, tile['name']
        low, high = tile['bounds_m']
        assert np.allclose(low, [position[:, 0].min(), -position[:, 2].max(), position[:, 1].min()])
        assert np.allclose(high, [position[:, 0].max(), -position[:, 2].min(), position[:, 1].max()])


@pytest.mark.parametrize('span, metres', [(.2, 80.), (.86, 86.), (1.05, 105.), (3.58, 358.), (4.06, 406.), (6., 500.),
                                          (7.99, 500.), (8., 0.), (40., 0.)])
def test_small_props_cull_with_their_size(span, metres):
    assert B.prop_cull_cm(span) == round(metres * 100.)


def test_built_surroundings_are_drawn_as_tiles_of_the_whole_surface():
    report = yori.OUT / 'belmonte/build-report.json'
    if not report.exists():
        pytest.skip('Belmonte not built (atelier build yorimichi world.belmonte)')
    meshes = json.loads(report.read_text())['meshes']
    names = {entry['name'] for entry in meshes}
    for whole in ('SM_BM_NorthApron', 'SM_BM_NorthCountry'):
        if whole in names:
            pytest.skip('Belmonte built before the surroundings were tiled')
        tiles = [entry for entry in meshes if entry['name'].startswith(whole + '_')]
        assert tiles and f'{whole}_00' in names
        path = yori.OUT / 'belmonte/glb' / (whole + '.glb')
        assert sorted(sum((corners(yori.OUT / 'belmonte' / t['path']) for t in tiles), [])) == corners(path)
