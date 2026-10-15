"""Portable v4 schema/profile/graph tests use only synthetic design data."""
import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
from craterpark.v2.v4_design import (DesignError, DesignAcceptanceError, UnsupportedDesignError,
                                     load_design, resolve_design, sample_profile, terrain_from_document)


def design(segments):
    return {'tower': {'deck_y': 100., 'roll_ins': [{'id': 'T', 'pos': [0., 0.], 'heading': 0.}]},
            'lines': [{'id': 'A', 'start': 'T', 'defaults': {'width': 18.}, 'segments': segments}]}


def test_exact_profile_circle_and_horizontal_breaks():
    p, breaks, parts = sample_profile(100., 0., [('arc', 80., -35.), ('line', 12.), ('arc', 60., 0.)], step=.37)
    end_arc = 80. * math.sin(math.radians(35.))
    ids = p[:, 0] <= end_arc
    assert np.max(abs(p[ids, 1] - (20. + np.sqrt(80.**2-p[ids, 0]**2)))) < 1e-10
    assert breaks[1] == pytest.approx(end_arc)
    assert breaks[-1] == pytest.approx(end_arc + 12. + 60.*math.sin(math.radians(35.)))
    assert np.all(np.diff(p[:, 0]) > 0)
    for endpoint in breaks:
        assert np.min(abs(p[:, 0] - endpoint)) < 1e-10


def test_defaults_templates_elements_walls_and_no_aliasing():
    d = design([{'id': 's', 'kind': 'straight', 'template': 'child', 'len': 40., 'grade': 0.}])
    d['elements'] = {'straight': {'width': 16., 'walls': {'L': {'h': 2.}}}}
    d['templates'] = {'base': {'width': 20., 'walls': {'R': {'h': 4.}}}, 'child': {'template': 'base', 'walls': {'L': {'R': 8.}}}}
    r = resolve_design(d)
    s = r.segments['s']
    assert s['width'] == 20.
    assert s['walls']['L']['h'] == 2.
    assert s['walls']['L']['R'] == 8.
    assert s['walls']['R']['h'] == 4.
    assert 'after' not in d['lines'][0]['segments'][0]
    assert r.geo['s']['end'] == dict(x=40., z=0., h=0., y=100., a=0.)


@pytest.mark.parametrize('change,match', [
    ({'after': 'missing'}, 'dangling'), ({'next': ['missing']}, 'dangling'),
    ({'len': '@missing'}, 'dangling'), ({'template': 'missing'}, 'unknown template'),
    ({'kind': 'imaginary'}, 'unknown segment kind')])
def test_unknown_and_dangling_references_fail(change, match):
    s = {'id': 's', 'kind': 'straight', 'len': 20., 'grade': 0., **change}
    with pytest.raises(DesignError, match=match):
        resolve_design(design([s]))


def test_cycles_fail_in_route_pose_and_template_graphs():
    with pytest.raises(DesignError, match='cyclic'):
        resolve_design(design([{'id': 'a', 'kind': 'straight', 'after': 'b'}, {'id': 'b', 'kind': 'straight', 'after': 'a'}]))
    with pytest.raises(DesignError, match='cyclic'):
        resolve_design(design([{'id': 'a', 'kind': 'straight', 'next': ['b']}, {'id': 'b', 'kind': 'straight', 'next': ['a']}]))
    d = design([{'id': 'a', 'kind': 'straight', 'template': 'x'}])
    d['templates'] = {'x': {'template': 'y'}, 'y': {'template': 'x'}}
    with pytest.raises(DesignError, match='cyclic'):
        resolve_design(d)


def test_reference_start_and_branches_are_distinct_from_route_edges():
    d = design([{'id': 'a', 'kind': 'straight', 'len': 20., 'grade': 0., 'next': ['b', 'c']},
                {'id': 'b', 'kind': 'straight', 'len': 30., 'grade': 0.},
                {'id': 'c', 'kind': 'straight', 'after': 'a', 'len': 40., 'grade': 0.}])
    r = resolve_design(d)
    assert r.segments['b']['next'] == []
    assert r.preds['b'] == ['a'] and r.preds['c'] == ['a']
    assert r.geo['b']['start'] == r.geo['c']['start']
    d['lines'].append({'id': 'B', 'start': 'T', 'segments': [{'id': 'ref', 'kind': 'straight', 'len': '@b', 'y1': '@b'}]})
    r = resolve_design(d)
    assert r.geo['ref']['end']['x'] == pytest.approx(20.)
    assert r.geo['ref']['end']['y'] == pytest.approx(100.)


def test_gap_retains_exact_grounded_parts_and_nonriding_open_interval():
    r = resolve_design(design([{'id': 'g', 'kind': 'gap', 'kicker': [['arc', 30., 18.], ['line', 3.]],
                               'open': 40., 'drop': 4., 'receiver': [['arc', 20., -25.], ['line', 20.], ['arc', 60., 0.]]}]))
    g = r.geo['g']
    lo, hi = g['air_intervals'][0]
    assert hi-lo == pytest.approx(40.)
    assert np.all(g['air'] == ((g['s'] > lo) & (g['s'] < hi)))
    assert not g['air'][np.argmin(abs(g['s']-lo))]
    assert not g['air'][np.argmin(abs(g['s']-hi))]
    assert g['info']['landing_y'] == pytest.approx(g['info']['lip_y']-4.)
    assert g['profile_parts']['receiver'][0] == ('arc', 20., -25.)
    assert g['end']['a'] == 0.


def test_acceptance_failure_is_distinct_from_syntax_error():
    with pytest.raises(DesignAcceptanceError):
        resolve_design(design([{'id': 's', 'kind': 'straight', 'len': 1., 'grade': -30.}]))
    with pytest.raises(DesignError):
        sample_profile(0., 0., [('arc', -4., 20.)])
    with pytest.raises(DesignAcceptanceError):
        resolve_design(design([{'id': 's', 'kind': 'straight', 'len': 10., 'y1': 1000.}]))


def test_turn_and_exact180_elbow_ports():
    r = resolve_design(design([{'id': 't', 'kind': 'turn', 'R': 20., 'angle': 90., 'grade': 0.},
                               {'id': 'e', 'kind': 'elbow', 'angle': 180., 'approach': 10.}]))
    t, e = r.geo['t'], r.geo['e']
    assert t['end']['x'] == pytest.approx(20.) and t['end']['z'] == pytest.approx(20.)
    assert t['end']['h'] == pytest.approx(90.)
    assert e['end']['h'] == pytest.approx(270.)
    assert e['corner'] in e['breakpoints']


def test_relative_terrain_depth_and_environment_loader(tmp_path, monkeypatch):
    x, z = np.arange(100., 110., 2.), np.arange(200., 210., 2.)
    h = np.add.outer(z, x)
    np.savez(tmp_path/'terrain.npz', native_x=x, native_z=z, natural=h, natural_d65=h-20.)
    d = design([{'id': 's', 'kind': 'straight', 'len': 20., 'grade': 0.}])
    d['ground'] = {'heightmap': 'terrain.npz', 'layer': 'natural', 'dig': {'kind': 'depth', 'DEPTH': 65}}
    p = tmp_path/'design.json'
    p.write_text(json.dumps(d))
    monkeypatch.setenv('ATELIER_CRATERPARK_V4_DESIGN', str(p))
    r = load_design()
    assert r.ground_at(103., 205.) == pytest.approx(288.)
    assert np.all(r.terrain.original_heights-r.terrain.heights == 20.)
    assert set(r.inputs) == {p, tmp_path/'terrain.npz'}
    d['ground']['dig']['DEPTH'] = 70
    with pytest.raises(DesignError, match='depth layer'):
        terrain_from_document(d, tmp_path)


def test_contour_explicit_terrain_never_straight_fallback():
    d = design([{'id': 'c', 'kind': 'contour', 'len': 10., 'grade': 0., 'aim': False, 'Rmin': 80.}])
    d['tower']['roll_ins'][0]['pos'] = [300., 0.]
    d['tower']['deck_y'] = 10.
    d['crater_centre'] = [0., 0.]
    with pytest.raises(UnsupportedDesignError, match='contour_resolver'):
        resolve_design(d)
    def terrain(x, z):
        return np.hypot(x,z)/10.-20.
    r = resolve_design(d, terrain=terrain)
    g = r.geo['c']
    assert abs(g['end']['h']) > 1.
    assert np.max(abs(np.diff(g['h']))) <= math.degrees(.5/80.)+1e-10
    assert np.allclose(g['x'][0], 300.)
    assert g['info']['plan_source'].startswith('explicit contour')


def test_link_resolves_target_start_with_exact_port_height_and_heading():
    d = design([{'id': 'target', 'kind': 'straight', 'grade': 0., 'len': 20.},
                {'id': 'branch', 'kind': 'turn', 'after': '@T', 'R': 30., 'angle': 90., 'grade': 0., 'next': ['join']},
                {'id': 'join', 'kind': 'link', 'to': '@target', 'next': ['target']}])
    r = resolve_design(d)
    e, t = r.geo['join']['end'], r.geo['target']['start']
    assert e == pytest.approx(t, abs=1e-8)
    assert r.geo['join']['info']['plan_source'].startswith('801-station')


def test_invalid_contour_terrain_and_unreferenced_template_cycle_fail():
    d = design([{'id': 'c', 'kind': 'contour', 'len': 10., 'grade': 0.}])
    with pytest.raises(DesignError, match='no valid heights'):
        resolve_design(d, terrain=lambda x,z: np.full_like(x,np.nan))
    d['templates'] = {'unused': {'template': 'unused'}}
    with pytest.raises(DesignError, match='cyclic'):
        resolve_design(d)


def test_bowl_entry_targets_rotated_shallow_floor_without_explicit_y1():
    d = design([{'id': 'in', 'kind': 'bowl_entry', 'len': 100., 'grade': 0.}])
    d['tower']['deck_y'] = 0.
    d['bowl'] = {'floor_y': -4., 'shallow_y': -2., 'centre': [0., 0.], 'scale': [1.,1.], 'axis_deg': 0.}
    r = resolve_design(d)
    assert r.geo['in']['end']['y'] == pytest.approx(-2.)
    assert r.geo['in']['end']['a'] == pytest.approx(0.)


def test_loader_rejects_nonobject_before_accessing_schema(tmp_path):
    p = tmp_path/'design.json'
    p.write_text('[]')
    with pytest.raises(DesignError, match='must be an object'):
        load_design(p)


def test_bowl_floor_blend_uses_same_explicit_length_as_geometry():
    from craterpark.v2.v4_design import bowl_floor_at
    d = {'bowl': {'floor_y': -10., 'shallow_y': -6., 'centre': [0.,0.],
                   'axis_deg': 0., 'scale': [1.,1.], 'floor_blend_m': 40.}}
    assert bowl_floor_at(d, [[20.,0.]])[0] == pytest.approx(-8.)
