"""Ordered extraction/storage checks; full production parity is a separate gate."""
import json
from pathlib import Path
import sys
import zipfile

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME/'world'))
import yori  # noqa: E402,F401
from terrain_product import Mesh, load, save  # noqa: E402
import farhills_surface  # noqa: E402


def test_products_round_trip_every_frozen_ordered_fixture(tmp_path):
    cases = json.loads(Path(__file__).with_name('fixtures').joinpath('terrain-r8.json').read_text())['cases']
    for name, case in cases.items():
        mesh = Mesh.from_polygons(case['vertices'], case['triangles'])
        a, b = tmp_path/(name+'.npz'), tmp_path/(name+'-again.npz')
        save(a, mesh, owner='FarHills', stage='final', city=True)
        save(b, mesh, owner='FarHills', stage='final', city=True)
        assert a.read_bytes() == b.read_bytes()
        with zipfile.ZipFile(a) as archive:
            assert all(member.date_time == (1980, 1, 1, 0, 0, 0) for member in archive.infolist())
        restored = load(a, owner='FarHills', stage='final', city=True)
        np.testing.assert_array_equal(restored.vertices, case['vertices'])
        np.testing.assert_array_equal(restored.triangles(), case['triangles'])
        assert restored.polygons() == case['triangles']
        assert not restored.vertices.flags.writeable and not restored.indices.flags.writeable


def test_natural_polygon_fan_and_empty_mesh_stay_explicit(tmp_path):
    v = np.array([[0., 0., 0.], [2., 0., 1.], [2., 3., 2.], [0., 3., 3.]])
    mesh = Mesh.from_polygons(v, [[0, 1, 2, 3]])
    v[0, 2] = 7.  # The product owns an independent copy.
    assert mesh.vertices[0, 2] == 0.
    assert mesh.polygons() == [[0, 1, 2, 3]]
    np.testing.assert_array_equal(mesh.triangles(), [[0, 1, 2], [0, 2, 3]])
    path = tmp_path/'natural.npz'
    save(path, mesh, owner='FarHills', stage='natural', city=False)
    assert load(path, owner='FarHills', stage='natural', city=False).polygons() == mesh.polygons()
    empty = Mesh.from_polygons([], [])
    assert empty.triangles().shape == (0, 3)


@pytest.mark.parametrize('change', [
    {'indices': np.array([0., 1., 2.])},
    {'indices': np.array([0, 1, 9])},
    {'offsets': np.array([0, 2])},
    {'offsets': np.array([0, 3, 2], dtype='u8')},
    {'vertices': np.array([[0., 0., np.nan], [1., 0., 0.], [0., 1., 0.]])},
])
def test_mesh_rejects_invalid_geometry(change):
    values = dict(vertices=[[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]], indices=[0, 1, 2], offsets=[0, 3])
    values.update(change)
    with pytest.raises(ValueError):
        Mesh(**values)


def test_loader_fails_on_missing_corrupt_or_mismatched_products(tmp_path):
    path = tmp_path/'surface.npz'
    identity = dict(owner='FarHills', stage='final', city=True)
    with pytest.raises(FileNotFoundError):
        load(path, **identity)
    mesh = Mesh.from_polygons([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]], [[0, 1, 2]])
    save(path, mesh, **identity)
    for wrong in [dict(owner='city'), dict(stage='natural'), dict(city=False), dict(city=1)]:
        with pytest.raises(ValueError):
            load(path, **(identity | wrong))
    with np.load(path, allow_pickle=False) as source:
        arrays = dict(source)
    for bad in [arrays | {'triangles': np.array([[1, 0, 2]])},
                arrays | {'indices': arrays['indices'].astype('f8')},
                arrays | {'unexpected': np.array(1)}]:
        np.savez(path, **bad)
        with pytest.raises(ValueError):
            load(path, **identity)


def test_extraction_passes_original_polygons_to_one_carve(monkeypatch):
    import shorelines
    from hidamari import forest_backdrop, layout, mountains
    from train import earthworks
    grid = np.array([2000., 2010.]), np.array([2000., 2014.]), np.array([[1., 2.], [3., 8.]])
    calls = []
    monkeypatch.setattr(forest_backdrop, 'mesh_grid', lambda n, *, city: grid)
    monkeypatch.setattr(forest_backdrop, 'source_grid', lambda *, city: grid)
    monkeypatch.setattr(forest_backdrop, 'rail_refinement', lambda *, city: {})
    monkeypatch.setattr(layout, 'coastal_backdrop_height', lambda x, y, z: z)
    monkeypatch.setattr(shorelines, 'field', lambda x, y: (np.zeros_like(x), np.zeros_like(x)))
    monkeypatch.setattr(shorelines, 'reach', lambda x, y: np.full_like(x, 1000.))
    def carve(vertices, faces, step, *, hidden, conform_neighbors):
        assert step == 4. and hidden is mountains.contains and conform_neighbors
        assert any(len(face) == 4 for face in faces)  # Never fan before the planner.
        calls.append((np.array(vertices), [list(face) for face in faces]))
        return np.asarray(vertices)+[0., 0., 1.], faces, {'refined': 0}
    monkeypatch.setattr(earthworks, 'polygons', carve)
    natural, final, report = farhills_surface.generate(301, city=True)
    assert len(calls) == 1 and report == {'refined': 0}
    np.testing.assert_array_equal(natural.vertices, calls[0][0])
    assert natural.polygons() == calls[0][1] == final.polygons()
    np.testing.assert_array_equal(final.vertices, natural.vertices+[0., 0., 1.])
