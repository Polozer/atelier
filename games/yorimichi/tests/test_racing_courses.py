"""Committed racecourses must match both their schema and the actual venue surface."""
import copy
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from atelier import build as recipes

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from racing import courses  # noqa: E402
from belmonte import source, planting  # noqa: E402


def test_committed_lap_lengths_and_finish():
    data = courses.load()
    assert data['tracks']['turf']['length_m'] == 1799.841
    assert data['tracks']['sand']['length_m'] == 1703.707
    assert data['tracks']['turf']['finish_s'] == 240.


@pytest.mark.parametrize('change', [
    lambda d: d.update(version=True),
    lambda d: d.update(frame='Unreal centimetres'),
    lambda d: d.update(source={}),
    lambda d: d['tracks'].pop('sand'),
    lambda d: d['tracks']['turf'].update(closed=False),
    lambda d: d['tracks']['turf'].update(points=[[0., 0., 0.]] * 3),
    lambda d: d['tracks']['turf']['points'][0].__setitem__(0, float('nan')),
    lambda d: d['tracks']['turf']['points'][0].__setitem__(0, True),
    lambda d: d['tracks']['turf'].update(finish_s=-1.),
    lambda d: d['tracks']['turf'].update(length_m=1800.),
    lambda d: d['tracks']['turf'].update(lane_width_m=1.9),
    lambda d: d['tracks']['turf']['points'].reverse(),
])
def test_invalid_course_data_is_rejected(tmp_path, change):
    data = copy.deepcopy(courses.load())
    change(data)
    path = tmp_path / 'courses.json'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        courses.load(path)


def test_every_racing_lane_stays_on_the_committed_course():
    scene = source.manifest()
    model = next(m for m in scene['meshes'] if m['name'] == 'SM_BM_BHip_Course')
    placed = next(p for p in scene['placements'] if p['asset'] == model['source_asset'])
    transform = placed['transform']
    faces = source.triangles(source.LIBRARY / model['path']) * [100., -100., 100.] * transform['scale']
    faces = (planting.rotate(transform['rotation_xyzw'], faces) + transform['translation_cm']) / [100., -100., 100.]
    surface = source.Surface(faces)
    for name, track in courses.load()['tracks'].items():
        points = np.asarray(track['points'])
        ends = np.roll(points, -1, axis=0)
        lengths = np.linalg.norm(ends[:, :2] - points[:, :2], axis=1)
        cumulative = np.r_[0., np.cumsum(lengths)]
        s = np.arange(0., cumulative[-1], 2.)
        segment = np.searchsorted(cumulative, s, side='right') - 1
        fraction = (s - cumulative[segment]) / lengths[segment]
        centres = points[segment] + (ends[segment] - points[segment]) * fraction[:, None]
        tangent = (ends[segment, :2] - points[segment, :2]) / lengths[segment, None]
        outward = np.c_[tangent[:, 1], -tangent[:, 0]]
        # Six runners, from the inner to outer lane, in the existing rail corridor.
        for offset in np.linspace(-10., -.5, 6):
            xy = centres[:, :2] + outward * offset
            ground = surface.height(xy[:, 0], xy[:, 1])
            assert np.isfinite(ground).all(), f'{name} lane {offset}: missing committed course surface'
            np.testing.assert_allclose(ground, centres[:, 2], atol=.05)


def test_invalid_courses_fail_before_staging_writes(tmp_path, monkeypatch):
    recipe = recipes.load_recipe('yorimichi')
    runtime = recipe.runtime_data
    bad = tmp_path / 'courses.json'
    bad.write_text('{}')
    destination = tmp_path / 'Data'
    monkeypatch.setattr(runtime, 'RACING_COURSES', bad)
    monkeypatch.setattr(runtime.paths, 'content_data', lambda game: destination)
    with pytest.raises(ValueError):
        runtime.stage_data(SimpleNamespace(game='yorimichi', out=tmp_path), io.StringIO())
    assert not destination.exists()


def test_staging_tracks_all_course_inputs(tmp_path):
    recipe = recipes.load_recipe('yorimichi')
    ctx = SimpleNamespace(game='yorimichi', out=tmp_path, uproject=None)
    step = next(s for s in recipe.steps(ctx) if s.name == 'data.stage')
    runtime = recipe.runtime_data
    assert runtime.staged_source(tmp_path, 'racing/belmonte_courses.json') == courses.DATA
    assert courses.DATA in step.inputs
    assert runtime.RACING_VALIDATOR in step.inputs
    assert courses.SCENE in step.inputs
    assert recipe.GAME / 'unreal/Content/Data/racing/belmonte_courses.json' in step.outputs
