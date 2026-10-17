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


@pytest.fixture(scope='module')
def recipe():
    from atelier.build import load_recipe
    return load_recipe('yorimichi')


@pytest.fixture
def baked_furniture(tmp_path):
    from train_furniture_fixtures import bake
    root = tmp_path / 'belmonte-train' / 'furniture'
    bake(root)
    return root


def test_source_report_reset_preserves_an_existing_lod_bake(recipe, baked_furniture, tmp_path):
    assert recipe.belmonte_train_furniture_lods_present(tmp_path)
    old = {p: p.read_bytes() for p in baked_furniture.iterdir() if p.is_file()}
    summary = (baked_furniture / 'lod' / 'summary.json').read_bytes()
    F.stage(baked_furniture)
    assert all(p.read_bytes() == raw for p, raw in old.items())
    assert (baked_furniture / 'lod' / 'summary.json').read_bytes() == summary
    assert recipe.belmonte_train_furniture_lods_present(tmp_path)


def test_review_sheets_use_bake_summary_without_mutating_source_reports(baked_furniture, monkeypatch):
    from PIL import Image
    from train import review_sheets as review
    summary_path = baked_furniture / 'lod' / 'summary.json'
    summary = json.loads(summary_path.read_text())
    aid = 'wall-sconce'
    summary[aid].update(source_triangles=1234, textures={'base': [4, 4]})
    summary_path.write_text(json.dumps(summary))
    source = baked_furniture / f'{aid}.json'
    before = source.read_bytes()
    assert 'lods' not in json.loads(before)
    frames = baked_furniture.parent / 'review-perf' / 'frames'
    frames.mkdir(parents=True)
    Image.new('RGB', (32, 32), '#876543').save(frames / f'{aid}-lod0.png')
    monkeypatch.setattr(review, 'OUT', baked_furniture.parent)
    monkeypatch.setattr(review, 'REVIEW', frames.parent)
    monkeypatch.setattr(review, 'FRAMES', frames)
    review.main()
    assert (frames.parent / f'{aid}.png').is_file()
    assert source.read_bytes() == before


@pytest.mark.parametrize('change', ['stale-source', 'checksum', 'incomplete-summary', 'empty-summary', 'empty-levels',
                                    'missing-level', 'unbaked-level', 'truncated-glb', 'triangle-budget'])
def test_incomplete_lod_bake_is_not_current(recipe, baked_furniture, tmp_path, change):
    path = baked_furniture / 'lod' / 'summary.json'
    summary = json.loads(path.read_text())
    if change == 'stale-source':
        (baked_furniture / 'wall-sconce.glb').write_bytes(b'new source')
    elif change == 'checksum':
        summary['wall-sconce']['levels'][0]['sha256'] = '0' * 64
    elif change == 'incomplete-summary':
        del summary['wall-sconce']
    elif change == 'empty-summary':
        summary = {}
    elif change == 'empty-levels':
        summary['wall-sconce']['levels'] = []
    elif change == 'missing-level':
        summary['second-class-bench']['levels'].pop()
    elif change == 'unbaked-level':
        summary['wall-sconce']['levels'][0]['glb'] = 'wall-sconce.glb'
    elif change == 'triangle-budget':
        summary['wall-sconce']['levels'][0]['triangles'] = 100000
    else:
        (baked_furniture / 'lod' / 'wall-sconce_LOD0.glb').write_bytes(b'truncated')
    path.write_text(json.dumps(summary))
    assert not recipe.belmonte_train_furniture_lods_present(tmp_path)


def test_default_and_import_dependency_closure_requires_furniture_bake(recipe, tmp_path):
    from types import SimpleNamespace
    steps = {s.name: s for s in recipe.steps(SimpleNamespace(game='yorimichi', out=tmp_path, uproject=None))}
    bake = steps['world.belmonte_train_furniture_lods']
    assert not bake.explicit
    assert 'world.belmonte_train_furniture_lods' in steps['world.belmonte_train_assembly'].needs
    assert 'world.belmonte_train_assembly' in steps['world.belmonte_train_service'].needs
    assert 'world.belmonte_train_service' in steps['unreal.belmonte_train'].needs
    assert steps['world.belmonte_train_furniture_review'].explicit
    assert steps['world.belmonte_train_review'].explicit
    assert len([p for p in bake.outputs if p.suffix == '.glb']) == sum(2 if cap[1] else 1 for cap in B.FURNITURE.values())
