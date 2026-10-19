"""Keep owned mountain products and attributed export on the same carve."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME/'world'))
import yori  # noqa: E402,F401
import north_mountain_surface  # noqa: E402
from hidamari import mountains  # noqa: E402
from terrain_product import load  # noqa: E402
from terrain_sheet_fixture import inputs  # noqa: E402
from train import earthworks  # noqa: E402


@pytest.mark.parametrize('carved', [False, True])
def test_publication_keeps_both_stages_and_original_export_attributes(tmp_path, monkeypatch, carved):
    natural = inputs()
    before = {k: v.copy() for k, v in natural.items() if isinstance(v, np.ndarray)}
    ln = earthworks.Line({'samples': [
        dict(s=float(s), x=float(s), y=0., rail_z=100., ground_z=104., **{'class': 'cutting'})
        for s in range(0, 410, 10)]})
    monkeypatch.setattr(earthworks, 'line', lambda: None)
    final = earthworks.sheet(natural, step=6., ln=ln if carved else None)
    final_before = {k: v.copy() for k, v in final.items() if isinstance(v, np.ndarray)}
    calls = []
    def sheets(sampler):
        calls.append(sampler)
        return natural, final
    monkeypatch.setattr(mountains, 'sheets', sheets)
    sampler = object()
    assert north_mountain_surface.generate(sampler, tmp_path) is final
    assert calls == [sampler]
    for stage, sheet in [('natural', natural), ('final', final)]:
        product = load(tmp_path/(stage+'.npz'), owner='HD_NorthMountains', stage=stage, city=True)
        np.testing.assert_array_equal(product.vertices, sheet['vertices'])
        np.testing.assert_array_equal(product.triangles(), sheet['faces'])
        assert product.polygons() == sheet['faces'].tolist()
        assert not product.vertices.flags.writeable
        with pytest.raises(ValueError, match='mode mismatch'):
            load(tmp_path/(stage+'.npz'), owner='HD_NorthGate', stage=stage, city=True)
    for key, value in before.items():
        np.testing.assert_array_equal(natural[key], value)
    for key, value in final_before.items():
        np.testing.assert_array_equal(final[key], value)
    first = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    north_mountain_surface.generate(sampler, tmp_path)
    assert first == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert json.loads((tmp_path/'manifest.json').read_text())['owner'] == 'HD_NorthMountains'


def test_existing_mesh_adapter_returns_the_final_sheet(monkeypatch):
    natural, final = object(), object()
    calls = []
    def sheets(sampler):
        calls.append(sampler)
        return natural, final
    monkeypatch.setattr(mountains, 'sheets', sheets)
    sampler = object()
    assert mountains.mesh(sampler) is final
    assert calls == [sampler]


def test_sheet_boundary_preserves_authored_inputs_to_one_carve(monkeypatch):
    axes = np.array([40., 45., 50.]), np.array([-5., 0., 5.])
    x, y = np.meshgrid(*axes)
    z = 106.+.03*x+.02*y+.01*x*y
    monkeypatch.setattr(mountains, 'BOUNDS', (40., -5., 50., 5.))
    monkeypatch.setattr(mountains, 'STEP', 5.)
    monkeypatch.setattr(mountains, 'surface_grid', lambda sampler: (x, y, z))
    monkeypatch.setattr(mountains, 'snow', lambda x, y, sampler: np.full_like(x, .75))
    monkeypatch.setattr(mountains, 'apron_grids', lambda xs, ys: [])
    from megapark import gate
    monkeypatch.setattr(gate, 'cell_inside', lambda x, y, step: x == 45. and y == 0.)
    calls = []
    final = object()
    def carve(sheet):
        calls.append(sheet)
        return final
    monkeypatch.setattr(earthworks, 'sheet', carve)
    natural, actual_final = mountains.sheets(object())
    assert actual_final is final and calls == [natural]
    np.testing.assert_array_equal(natural['vertices'], np.stack([x, y, z], -1).reshape(-1, 3)[:8])
    np.testing.assert_array_equal(natural['faces'],
                                  [[0, 1, 4], [0, 4, 3], [1, 2, 5], [1, 5, 4], [3, 4, 7], [3, 7, 6]])
    assert natural['colours'].shape == (8, 4) and natural['normals'].shape == (8, 3)
    np.testing.assert_array_equal(natural['colours'][:, 3], .75)
    dy, dx = np.gradient(z, 5., 5.)
    expected_normals = np.stack([-dx, -dy, np.ones_like(z)], -1)
    expected_normals /= np.linalg.norm(expected_normals, axis=-1, keepdims=True)
    np.testing.assert_array_equal(natural['normals'], expected_normals.reshape(-1, 3)[:8])


def test_normal_city_recipe_owns_all_mountain_products(tmp_path):
    from atelier import build, build_products
    recipe = build.load_recipe('yorimichi')
    graph = build_products.Graph(recipe.steps(SimpleNamespace(game='yorimichi', out=tmp_path, uproject=None)))
    step = graph.by_name['world.hidamari']
    for stage in ('natural', 'final', 'provenance'):
        name = 'terrain.HD_NorthMountains.'+stage
        assert graph.owners[name] == 'world.hidamari'
    assert step.heavy and not step.cache
    assert GAME/'world/north_mountain_surface.py' in step.inputs
    assert GAME/'world/terrain_product.py' in step.inputs
