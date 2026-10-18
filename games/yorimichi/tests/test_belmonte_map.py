"""Indoor map travel must hit clear floors beneath the committed building roofs."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from belmonte import build, layout, planting, source  # noqa: E402


def indoor_zone(key):
    return next(zone for zone in build.map_zones(241.) if zone['key'] == key)


@pytest.mark.parametrize('key,yaw', [('belmonte_salon', 0.), ('belmonte_osteria', 4.)])
def test_indoor_stop_follows_the_region_origin(monkeypatch, key, yaw):
    before = indoor_zone(key)
    offset = np.array([13., 41., 7.])
    monkeypatch.setattr(layout, 'ORIGIN', layout.ORIGIN + offset)
    after = indoor_zone(key)
    np.testing.assert_allclose([after[k] - before[k] for k in ('x', 'y', 'z')], offset)
    assert after['yaw'] == before['yaw'] == yaw


def test_outdoor_stops_keep_their_positions_and_default_trace():
    zones = json.loads(json.dumps(build.map_zones(241.)))
    assert [z['key'] for z in zones] == [
        'belmonte', 'belmonte_course', 'belmonte_training', 'belmonte_salon', 'belmonte_osteria',
    ]
    outdoor = [z for z in zones if z['key'] in ('belmonte', 'belmonte_course', 'belmonte_training')]
    assert all('above_m' not in z for z in outdoor)
    np.testing.assert_allclose([[z[k] for k in ('x', 'y', 'z', 'yaw')] for z in outdoor], [
        [layout.ORIGIN[0], layout.ORIGIN[1] - 18., 241., 90.],
        [385., 4255. + layout.NORTH_SHIFT, layout.ORIGIN[2] + 30.2, 90.],
        [230., 4560. + layout.NORTH_SHIFT, layout.ORIGIN[2] + 30.2, 0.],
    ])


def placed_surfaces(names):
    data = source.manifest()
    models = {m['source_asset']: m for m in data['meshes']}
    surfaces = []
    for placement in data['placements']:
        model = models[placement['asset']]
        if model['name'] not in names:
            continue
        faces = source.triangles(source.LIBRARY / model['path'])
        transform = placement['transform']
        native = faces * [100., -100., 100.] * transform['scale']
        native = planting.rotate(transform['rotation_xyzw'], native) + transform['translation_cm']
        surfaces.append(native / [100., -100., 100.] + layout.ORIGIN)
    return np.concatenate(surfaces)


@pytest.mark.parametrize('key,names,floor_offset', [
    ('belmonte_salon', ('SM_BM_BHip_Salon', 'SM_BM_BHip_SalonHall'), 30.15),
    ('belmonte_osteria', ('SM_BM_BH_Osteria', 'SM_BM_BH_Osteria_Taproom'), .18),
])
def test_indoor_trace_hits_floor_across_the_standing_footprint(key, names, floor_offset):
    surfaces = placed_surfaces(names)
    zone = indoor_zone(key)
    top = zone['z'] + zone['above_m']
    # Include the whole standing footprint, not only a ray that might graze a fixture.
    angle = np.linspace(0., 2. * np.pi, 17)
    x = np.r_[zone['x'], zone['x'] + .5 * np.cos(angle), zone['x'] + .25 * np.cos(angle)]
    y = np.r_[zone['y'], zone['y'] + .5 * np.sin(angle), zone['y'] + .25 * np.sin(angle)]
    below = surfaces[surfaces[:, :, 2].max(1) < top]
    floor = source.Surface(below).height(x, y)
    np.testing.assert_allclose(floor, layout.ORIGIN[2] + floor_offset, atol=.01)
    roof = source.Surface(surfaces).height(x, y)
    assert np.all(roof > top + 2.)
    assert np.all(roof < zone['z'] + 25.), 'The old outdoor trace must reproduce the roof landing'
    # Conservatively reject any wall or furnishing triangle whose box overlaps a
    # 1 m wide, 1.9 m tall standing volume above the floor (also catches vertical faces).
    low, high = surfaces.min(1), surfaces.max(1)
    foot = layout.ORIGIN[2] + floor_offset
    obstacle = ((low[:, 0] < zone['x'] + .5) & (high[:, 0] > zone['x'] - .5)
                & (low[:, 1] < zone['y'] + .5) & (high[:, 1] > zone['y'] - .5)
                & (low[:, 2] < foot + 1.9) & (high[:, 2] > foot + .05))
    assert not obstacle.any(), 'The landing must clear walls and furniture across the standing volume'
