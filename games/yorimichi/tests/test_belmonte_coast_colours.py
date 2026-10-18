"""Unchanged country and beach ground keep their colours after railway painting."""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from atelier.gltf import glb_parts

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
import shorelines  # noqa: E402
from belmonte import appearance, layout, source  # noqa: E402
from hippodrome.build import Mesh  # noqa: E402
from train import earthworks  # noqa: E402


@pytest.mark.parametrize('name,beach', [
    ('SM_BM_NorthCountry', False), ('SM_BM_NorthCountry', True),
    ('SM_BM_NorthApron', False),
])
def test_unchanged_export_retains_its_palette_with_a_nonzero_region_origin(tmp_path, monkeypatch, name, beach):
    monkeypatch.setattr(source, 'terrain_colours', lambda: SimpleNamespace(
        colour=lambda x, y: np.broadcast_to([.1, .14, .04], (*np.broadcast(x, y).shape, 3))))
    x, y, z = -2600., 5000., 40.
    if beach:
        xs = np.linspace(2800., 3100., 3001)
        distance, _ = shorelines.field(xs, y)
        x = float(xs[np.argmin(abs(distance - 12.))])
        z = float(shorelines.height(x, y, 10.))
    points = np.array([[x, y, z], [x + 1., y, z], [x + 1., y + 1., z], [x, y + 1., z]])
    mesh = Mesh()
    mesh.quad(*(points - layout.ORIGIN))
    earthworks.quads(mesh, layout.ORIGIN, 4.)
    actual_points = np.asarray(mesh.p) + layout.ORIGIN
    np.testing.assert_allclose(mesh.natural, actual_points[:, 2])
    # Isolate the height-frame contract from the line projection: unchanged
    # ground must not acquire a new-slope tint even when no line is present.
    monkeypatch.setattr(earthworks, 'line', lambda: None)
    expected = appearance.far_palette(actual_points[:, 0], actual_points[:, 1])
    if name == 'SM_BM_NorthCountry':
        expected = shorelines.colours(*actual_points.T, np.asarray(mesh.n)[:, 2], expected)
    path = tmp_path / (name + '.glb')
    mesh.save(path, 'Ground')
    appearance.paint_join(path, mesh)
    doc, binary = glb_parts(path.read_bytes())
    attribute = doc['meshes'][0]['primitives'][0]['attributes']['COLOR_0']
    accessor = doc['accessors'][attribute]
    view = doc['bufferViews'][accessor['bufferView']]
    rgba = np.frombuffer(binary, '<f4', accessor['count'] * 4,
                         view.get('byteOffset', 0) + accessor.get('byteOffset', 0)).reshape(-1, 4)
    np.testing.assert_allclose(rgba[:, :3], source.srgb(expected), atol=1e-6)
