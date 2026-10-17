"""Indoor map travel must hit clear hall paving beneath the committed salon roof."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from belmonte import build, layout, planting, source  # noqa: E402


def salon_zone():
    return next(zone for zone in build.map_zones(241.) if zone['key'] == 'belmonte_salon')


def test_salon_follows_the_region_origin(monkeypatch):
    before = salon_zone()
    offset = np.array([13., 41., 7.])
    monkeypatch.setattr(layout, 'ORIGIN', layout.ORIGIN + offset)
    after = salon_zone()
    np.testing.assert_allclose([after[k] - before[k] for k in ('x', 'y', 'z')], offset)
    assert after['yaw'] == before['yaw'] == 0.


def test_outdoor_stops_keep_their_positions_and_default_trace():
    zones = json.loads(json.dumps(build.map_zones(241.)))
    assert [z['key'] for z in zones] == ['belmonte', 'belmonte_course', 'belmonte_training', 'belmonte_salon']
    assert all('above_m' not in z for z in zones[:-1])
    np.testing.assert_allclose([[z[k] for k in ('x', 'y', 'z', 'yaw')] for z in zones[:-1]], [
        [layout.ORIGIN[0], layout.ORIGIN[1] - 18., 241., 90.],
        [385., 4255. + layout.NORTH_SHIFT, layout.ORIGIN[2] + 30.2, 90.],
        [230., 4560. + layout.NORTH_SHIFT, layout.ORIGIN[2] + 30.2, 0.],
    ])


@pytest.fixture(scope='module')
def salon_surfaces():
    data = source.manifest()
    models = {m['source_asset']: m for m in data['meshes']}
    surfaces = []
    for placement in data['placements']:
        model = models[placement['asset']]
        if model['name'] not in ('SM_BM_BHip_Salon', 'SM_BM_BHip_SalonHall'):
            continue
        faces = source.triangles(source.LIBRARY / model['path'])
        transform = placement['transform']
        native = faces * [100., -100., 100.] * transform['scale']
        native = planting.rotate(transform['rotation_xyzw'], native) + transform['translation_cm']
        surfaces.append(native / [100., -100., 100.] + layout.ORIGIN)
    return np.concatenate(surfaces)


def test_salon_trace_hits_floor_with_standing_clearance(salon_surfaces):
    zone = salon_zone()
    top = zone['z'] + zone['above_m']
    # Include the whole standing footprint, not only a ray that might graze a fixture.
    angle = np.linspace(0., 2. * np.pi, 17)
    x = np.r_[zone['x'], zone['x'] + .5 * np.cos(angle)]
    y = np.r_[zone['y'], zone['y'] + .5 * np.sin(angle)]
    below = salon_surfaces[salon_surfaces[:, :, 2].max(1) < top]
    floor = source.Surface(below).height(x, y)
    np.testing.assert_allclose(floor, layout.ORIGIN[2] + 30.15, atol=.01)
    roof = source.Surface(salon_surfaces).height(x, y)
    assert np.all(roof > top + 2.)
    assert np.all(roof < zone['z'] + 25.), 'The old outdoor trace must reproduce the roof landing'
