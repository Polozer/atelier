"""Committed furniture integrity, measured geometry and clean-checkout staging (no Blender)."""
import hashlib
import json
import shutil
import sys
import tomllib
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
from train import budgets as B  # noqa: E402
from train import furniture as F  # noqa: E402
from train import layout as L  # noqa: E402

SPECS = {s['id']: s for s in L.contract()['assets']}


def test_complete_source_inventory():
    manifest = tomllib.loads((F.SOURCE / 'source.toml').read_text())
    assert manifest['licence'] == 'own'
    assert set(manifest['assets']) == set(SPECS)
    assert {p.stem for p in (F.SOURCE / 'furniture').glob('*.glb')} == set(SPECS)
    assert {p.stem for p in (F.SOURCE / 'furniture').glob('*.json')} == set(SPECS)


@pytest.mark.parametrize('aid', sorted(SPECS))
def test_mesh_dimensions_and_pivot(aid):
    spec = SPECS[aid]
    path = F.SOURCE / 'furniture' / f'{aid}.glb'
    doc, binary = B.read_glb(path)
    assert all('uri' not in v for k in ('images', 'buffers') for v in doc.get(k, []))
    # These fitted exports bake their transforms. Require that convention before measuring the vertices.
    assert all(not set(n) & {'matrix', 'translation', 'rotation', 'scale'} for n in doc['nodes'])
    points = []

    def walk(index):
        node = doc['nodes'][index]
        if 'mesh' in node:
            for primitive in doc['meshes'][node['mesh']]['primitives']:
                acc = doc['accessors'][primitive['attributes']['POSITION']]
                view = doc['bufferViews'][acc['bufferView']]
                assert acc['componentType'] == 5126 and acc['type'] == 'VEC3' and 'sparse' not in acc
                points.append(np.ndarray((acc['count'], 3), dtype='<f4', buffer=binary,
                                         offset=view.get('byteOffset', 0) + acc.get('byteOffset', 0),
                                         strides=(view.get('byteStride', 12), 4)))
        for child in node.get('children', []):
            walk(child)

    for index in doc['scenes'][doc.get('scene', 0)]['nodes']:
        walk(index)
    vertices = np.concatenate(points)
    assert np.isfinite(vertices).all()
    lo, hi = vertices.min(0), vertices.max(0)
    # Blender Z-up -> glTF Y-up: width X, height Y, depth Z.
    sizes = dict(zip(('width', 'height', 'depth'), hi - lo))
    report = json.loads(path.with_suffix('.json').read_text())
    for axis, target in spec['dimensions_m'].items():
        assert sizes[axis] == pytest.approx(target, abs=F.TOLERANCE)
        assert sizes[axis] == pytest.approx(report['fitted_m'][axis], abs=.0001)
        assert report['errors_m'][axis] == pytest.approx(abs(report['fitted_m'][axis] - target), abs=.0001)
    assert B.glb_stats(path)['triangles'] == report['triangles']
    if spec['pivot'] == 'hook_top':
        assert hi[1] == pytest.approx(0., abs=.002)
    elif spec['pivot'] == 'wall_mount_center':
        assert [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]] == pytest.approx([0., 0., 0.], abs=.002)
    else:
        assert [(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2] == pytest.approx([0., 0., 0.], abs=.002)


def test_stage_replaces_placeholders_and_copies_independent_files(tmp_path):
    destination = tmp_path / 'furniture'
    destination.mkdir()
    (destination / 'first-class-sofa.glb').write_bytes(b'old procedural box')
    assert F.stage(destination) == len(SPECS)
    for source in (F.SOURCE / 'furniture').iterdir():
        copy = destination / source.name
        assert copy.read_bytes() == source.read_bytes()
        assert copy.stat().st_ino != source.stat().st_ino
    (destination / 'first-class-sofa.glb').write_bytes(b'changed build output')
    assert (F.SOURCE / 'furniture' / 'first-class-sofa.glb').read_bytes()[:4] == b'glTF'


@pytest.fixture
def library(tmp_path):
    source = tmp_path / 'source'
    shutil.copytree(F.SOURCE / 'furniture', source / 'furniture')
    shutil.copyfile(F.SOURCE / 'source.toml', source / 'source.toml')
    return source


@pytest.mark.parametrize('name', ['wall-sconce.glb', 'wall-sconce.json'])
def test_missing_pair_fails_before_staging(library, tmp_path, name):
    (library / 'furniture' / name).unlink()
    destination = tmp_path / 'output'
    with pytest.raises(FileNotFoundError):
        F.stage(destination, library)
    assert not destination.exists()


@pytest.mark.parametrize('name', ['wall-sconce.glb', 'wall-sconce.json'])
def test_corrupt_pair_fails_before_staging(library, tmp_path, name):
    with (library / 'furniture' / name).open('ab') as stream:
        stream.write(b'corruption')
    destination = tmp_path / 'output'
    with pytest.raises(ValueError, match='checksum mismatch'):
        F.stage(destination, library)
    assert not destination.exists()


@pytest.mark.parametrize('change', ['lods', 'pivot', 'size', 'identity'])
def test_invalid_fit_is_rejected_even_with_a_matching_checksum(library, tmp_path, change):
    path = library / 'furniture' / 'wall-sconce.json'
    report = json.loads(path.read_text())
    if change == 'lods':
        report['lods'] = {'levels': [{'glb': 'unbuilt_LOD0.glb'}]}
    elif change == 'pivot':
        report['pivot'] = 'floor_footprint_center'
    elif change == 'size':
        report['fitted_m']['width'] *= 2
    else:
        report['output_id'] = 'table-lamp'
    old_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_text(json.dumps(report))
    manifest = library / 'source.toml'
    manifest.write_text(manifest.read_text().replace(old_digest, hashlib.sha256(path.read_bytes()).hexdigest()))
    destination = tmp_path / 'output'
    with pytest.raises(ValueError):
        F.stage(destination, library)
    assert not destination.exists()
