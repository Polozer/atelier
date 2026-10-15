"""Exact support contacts: crossings, coplanar overlap, containment and declared bearings."""
import sys
from pathlib import Path

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
from craterpark.v2 import dsl, v4_supports as supports  # noqa: E402


def box(lo=(0., 0., 0.), hi=(2., 2., 2.)):
    lo, hi = np.asarray(lo, 'f8'), np.asarray(hi, 'f8')
    v = np.array([[lo[0], lo[1], lo[2]], [hi[0], lo[1], lo[2]],
                  [hi[0], hi[1], lo[2]], [lo[0], hi[1], lo[2]],
                  [lo[0], lo[1], hi[2]], [hi[0], lo[1], hi[2]],
                  [hi[0], hi[1], hi[2]], [lo[0], hi[1], hi[2]]])
    f = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
                  [0, 1, 5], [0, 5, 4], [3, 7, 6], [3, 6, 2],
                  [0, 4, 7], [0, 7, 3], [1, 2, 6], [1, 6, 5]])
    return v[f]


def mesh(*targets):
    pieces = [dsl.Mesh.part(box().reshape(-1, 3), np.arange(36).reshape(-1, 3),
                            feature='support', role=dsl.SIDE)]
    for feature, triangles, role in targets:
        t = np.asarray(triangles, 'f8')
        pieces.append(dsl.Mesh.part(t.reshape(-1, 3), np.arange(t.size // 3).reshape(-1, 3),
                                   feature=feature, role=role))
    return dsl.Mesh.concat(pieces)


def spec(bearings=()):
    return {'kind': 'v4_support', 'feature': 'support', 'body_triangles': box().tolist(), 'bearings': list(bearings)}


def check(target, bearings=(), **kwargs):
    return supports.check(mesh(target), [spec(bearings)], require_envelopes=False, **kwargs)


@pytest.mark.parametrize('role', [dsl.RIDING, dsl.SIDE, dsl.COPING, dsl.RAIL])
def test_nonparallel_crossing_protects_every_riding_wall_coping_deck_role(role):
    triangle = [[[-1., 1., 1.], [3., 1., 1.], [1., 3., 1.]]]
    report = check(('ride', triangle, role))
    assert not report['ok']
    assert any(f['kind'] == 'support_surface_intersection' for f in report['failures'])


def test_triangle_entirely_inside_support_is_detected_without_boundary_crossing():
    triangle = [[[.3, 1., .3], [1.7, 1., .3], [.3, 1., 1.7]]]
    report = check(('ride', triangle, dsl.RIDING))
    assert not report['ok']
    assert not report['failures'][0]['material_boundary_only']


def test_contained_support_inside_closed_target_is_detected():
    report = check(('ride-body', box((-1., -1., -1.), (3., 3., 3.)), dsl.RIDING))
    assert not report['ok']
    assert any(f['kind'] == 'support_inside_closed_target' for f in report['failures'])
    assert not any(f['kind'] == 'support_surface_intersection' for f in report['failures'])


def test_coplanar_face_overlap_requires_exact_semantic_bearing():
    top = [[[0., 2., 0.], [2., 2., 2.], [2., 2., 0.]]]
    bearing = {'target_feature': 'deck', 'polygon': [[0., 2., 0.], [2., 2., 0.], [2., 2., 2.], [0., 2., 2.]]}
    assert not check(('deck', top, dsl.RIDING))['ok']
    report = check(('deck', top, dsl.RIDING), [bearing])
    assert report['ok'] and report['allowed_contacts'] == 1
    assert not check(('different-deck', top, dsl.RIDING), [bearing])['ok']
    bearing['polygon'] = [[0., 2., 0.], [1., 2., 0.], [1., 2., 1.], [0., 2., 1.]]
    assert not check(('deck', top, dsl.RIDING), [bearing])['ok']


def test_declared_bearing_cannot_excuse_a_plane_cutting_support_interior():
    inside = [[[0., 1., 0.], [2., 1., 2.], [2., 1., 0.]]]
    bearing = {'target_feature': 'deck', 'polygon': [[0., 1., 0.], [2., 1., 0.], [2., 1., 2.], [0., 1., 2.]]}
    report = check(('deck', inside, dsl.RIDING), [bearing])
    assert not report['ok']
    assert not report['failures'][0]['material_boundary_only']


def test_bearing_chain_allows_exact_crest_edge_but_not_area_or_chain_gaps():
    crest = [[[0., 2., 0.], [2., 2., 0.], [1., 3., -1.]]]
    bearing = {'target_feature': 'rollin', 'chain': [[0., 2., 0.], [1., 2., 0.], [2., 2., 0.]]}
    assert check(('rollin', crest, dsl.RIDING), [bearing])['ok']
    bearing['chain'] = [[0., 2., 0.], [.5, 2., 0.], [.5, 3., 0.], [1.5, 3., 0.], [1.5, 2., 0.], [2., 2., 0.]]
    assert not check(('rollin', crest, dsl.RIDING), [bearing])['ok']


def test_disjoint_faces_and_unrelated_aabb_overlap_pass():
    triangle = [[[4.5, 0., 0.], [0., 4.5, 0.], [0., 0., -2.5]]]
    # AABB overlaps support but this triangle is on the far side of z=0 except one remote edge.
    report = check(('ride', triangle, dsl.RIDING))
    assert report['ok']


def test_missing_envelopes_and_closed_envelope_containment_fail_closed():
    m = mesh(('safe', [[[4., 3., 4.], [5., 3., 4.], [4., 3., 5.]]], dsl.RIDING))
    report = supports.check(m, [spec()])
    assert not report['ok'] and report['failures'][0]['kind'] == 'missing_ride_envelopes'
    report = supports.check(m, [spec()], envelopes=[{'feature': 'flight', 'triangles': box((-1., -1., -1.), (3., 3., 3.))}])
    assert not report['ok']
    assert any(f['kind'] == 'support_inside_ride_envelope' for f in report['failures'])


def test_envelope_surface_crossing_is_detected_without_any_riding_mesh_hit():
    m = mesh(('safe', [[[4., 3., 4.], [5., 3., 4.], [4., 3., 5.]]], dsl.RIDING))
    report = supports.check(m, [spec()], envelopes=[{'feature': 'flight', 'triangles': box((1., 1., 1.), (3., 3., 3.))}])
    assert not report['ok']
    assert any(f['kind'] == 'ride_envelope_intersection' for f in report['failures'])


def test_open_support_and_broadphase_exhaustion_fail_without_clearance_claim():
    m = mesh(('safe', [[[4., 3., 4.], [5., 3., 4.], [4., 3., 5.]]], dsl.RIDING))
    broken = spec()
    broken['body_triangles'] = box()[:-1]
    report = supports.check(m, [broken], require_envelopes=False)
    assert not report['ok'] and report['failures'][0]['kind'] == 'unresolved_support'
    report = supports.check(m, [spec()], require_envelopes=False, max_pairs=0)
    assert not report['ok'] and 'budget' in report['failures'][0]['detail']


def test_contained_support_in_multifeature_closed_body_is_detected():
    body = box((-1., -1., -1.), (3., 3., 3.))
    m = mesh(*[(f'face-{i}', body[i:i + 1], dsl.RIDING) for i in range(len(body))])
    report = supports.check(m, [spec()], require_envelopes=False)
    assert not report['ok']
    assert any(f['kind'] == 'support_inside_closed_target' for f in report['failures'])


def test_derived_grounded_envelopes_allow_only_declared_true_floor_bearing():
    top = [[[0., 2., 0.], [2., 2., 2.], [2., 2., 0.]]]
    bearing = {'target_feature': 'deck', 'polygon': [[0., 2., 0.], [2., 2., 0.], [2., 2., 2.], [0., 2., 2.]]}
    m, checks = mesh(('deck', top, dsl.RIDING)), [spec([bearing])]
    envelopes, coverage = supports.derive_envelopes(m, checks)
    assert coverage['ok'] and coverage['grounded_facets'] == 1
    assert envelopes
    report = supports.check(m, checks, envelopes=envelopes, envelope_coverage=coverage)
    assert report['ok'], report


def test_derived_flight_slabs_cover_speed_band_and_unknown_band_fails():
    m = mesh(('safe', [[[4., 3., 4.], [5., 3., 4.], [4., 3., 5.]]], dsl.RIDING))
    air = {'kind': 'air', 'feature': 'jump', 'lip': [0., 8., 0.], 'landing_start': [15., 2., 0.],
           'lip_degrees': 15., 'landing_t': [15., 30.], 'width': 4., 'band': [14., 20.]}
    envelopes, report = supports.derive_envelopes(m, [spec(), air])
    assert report['ok'] and report['flight_slabs'] == 15
    # Every generated envelope is closed; the exact clipping checker accepts its boundary format.
    for envelope in envelopes:
        supports._closed(np.asarray(envelope['triangles']), 1e-7)
    air.pop('band')
    _, report = supports.derive_envelopes(m, [spec(), air])
    assert not report['ok'] and report['failures'][0]['kind'] == 'unresolved_air_envelope'
