"""Belmonte racecourse data for the racing service (world/racing/belmonte_courses.json, docs/RACING.md)."""
import importlib.util
import json
import math
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
DATA = GAME / 'world' / 'racing' / 'belmonte_courses.json'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _walk(points, distance):
    """The point `distance` metres along the closed run from its first point."""
    total = 0.
    for i, a in enumerate(points):
        b = points[(i + 1) % len(points)]
        step = math.dist(a[:2], b[:2])
        if total + step >= distance:
            t = (distance - total) / step
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        total += step
    raise AssertionError('distance beyond the lap')


def test_tracks_are_closed_counter_clockwise_and_measured():
    data = json.loads(DATA.read_text())
    assert set(data['tracks']) == {'turf', 'sand'}
    for name, expected in (('turf', 1799.841), ('sand', 1703.707)):
        track = data['tracks'][name]
        points = track['points']
        assert track['closed'] and len(points) > 100
        lap = sum(math.dist(points[i][:2], points[(i + 1) % len(points)][:2]) for i in range(len(points)))
        assert abs(lap - expected) < .01 and abs(lap - track['length_m']) < .01
        area = sum(points[i][0] * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * points[i][1]
                   for i in range(len(points)))
        assert area > 0, 'the course runs counter-clockwise'
        assert max(math.dist(points[i][:2], points[(i + 1) % len(points)][:2]) for i in range(len(points))) < 800


def test_finish_is_the_haras_valley_post():
    track = json.loads(DATA.read_text())['tracks']['turf']
    x, y = _walk(track['points'], track['finish_s'])
    # The post stands at (-155, 610.9), 3.6 m outside lane 1 (the line's points).
    assert math.isclose(x, -155., abs_tol=.01) and math.isclose(y, 607.3, abs_tol=.01)


def test_simplify_keeps_corners_and_drops_collinear_points():
    tool = _load('belmonte_courses', GAME / 'tools' / 'belmonte_courses.py')
    line = [[0., 0., 0.], [1., 0., 0.], [2., 0., 0.], [2., 1., 0.], [2., 2., 0.]]
    assert tool.simplify(line) == [[0., 0., 0.], [2., 0., 0.], [2., 2., 0.]]
    square = [[float(x), 0., 0.] for x in range(5)] + [[4., float(y), 0.] for y in range(1, 5)]
    square += [[float(x), 4., 0.] for x in range(3, -1, -1)] + [[0., float(y), 0.] for y in range(3, 0, -1)]
    out = tool.convert({'tracks': {name: {'points': square, 'closed': True, 'finish_s': 2., 'lane_width': -1.9}
                                   for name in ('turf', 'sand')}})
    assert out['tracks']['turf']['points'] == [[0., 0., 0.], [4., 0., 0.], [4., 4., 0.], [0., 4., 0.]]
    assert out['tracks']['turf']['length_m'] == 16.


def test_the_course_data_is_staged():
    runtime = _load('yorimichi_runtime_data_racing', GAME / 'runtime_data.py')
    assert 'racing/belmonte_courses.json' in runtime.STAGED
    assert runtime.staged_source(Path('/build'), 'racing/belmonte_courses.json') == DATA
