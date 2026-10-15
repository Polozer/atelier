"""Real joined geometry, not overlapping rectangles with decorative turn walls."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
from craterpark.v2 import dsl, junctions as J, layout as L, primitives as P, solids  # noqa: E402
from craterpark.v2.curves import Line  # noqa: E402


def turn(degrees=90.):
    line = L.LineSpec('T', 'test', L.Turtle((0., 0.), 0.,
                       (('straight', 80.), ('elbow', degrees, {'drift': 26., 'width': 20., 'r': 6.,
                                                            'vert': 1., 'deck': 2.}), ('straight', 80.))),
                      0., (('line', 186.),), (), 'test', 'test', rollin=0)
    return L.elbow_spec(line, 0)


@pytest.mark.parametrize('degrees', [90., -90., 140., -140., 180., -180.])
def test_elbow_floor_and_wall_share_one_edge_without_overlap(degrees):
    spec = turn(degrees)
    built = J.elbow(spec, ground=-2.)
    # One continuous outer boundary; coping is a separate closed tube.
    assert len(solids.check_open(built.mesh)) == 1
    c = next(c for c in built.checks if c['kind'] == 'junction')
    assert c['wall_height_m'] == 7.
    assert c['wall_length_m'] >= 12.
    floor = built.mesh.subset(built.mesh.feature == built.mesh.features.index('T.elbow0.apron'))
    assert np.abs(floor.V[floor.F][:, :, 1]).max() < 1e-8
    assert floor.areas().min() > 1e-9
    # The transition starts at the apron boundary, and has no flat footprint
    # extending into it or buried upright face across that shared floor seam.
    wall = built.mesh.subset((built.mesh.feature == built.mesh.features.index('T.elbow0')) &
                             (built.mesh.role == dsl.ROLE[dsl.RIDING]))
    tri = wall.V[wall.F]
    assert not ((np.abs(tri[:, :, 1]) < 1e-8).all(1)).any()


def test_actual_approach_caps_join_the_turn_without_tjunctions():
    spec = turn()
    A, B = J.direction(spec['heading_in']), J.direction(spec['heading_out'])
    pin = np.asarray(spec['corner']) - A * (spec['s'] - spec['s_in'])
    pout = np.asarray(spec['exit_corner']) + B * (spec['s_out'] - spec['s'] - spec['drift'])
    approach = P.ramp(Line(pin - 30 * A, pin), P.from_additions(0., 0., [('line', 30.)]), 18.,
                      left=P.Side('bowl', fade=(0., 20.)), right=P.Side('bowl', fade=(0., 20.)),
                      ground=-2., feature='in', on_ground=True)
    exit_ = P.ramp(Line(pout, pout + 30 * B), P.from_additions(0., 0., [('line', 30.)]), 18.,
                   left=P.Side('bowl', fade=(20., 0.)), right=P.Side('bowl', fade=(20., 0.)),
                   ground=-2., feature='out', on_ground=True)
    rows = [J.boundary_row(approach.mesh, pin, A), J.boundary_row(exit_.mesh, pout, B)]
    built = J.elbow(spec, ground=-2., rows=rows)
    mesh = dsl.Mesh.concat([approach.mesh, built.mesh, exit_.mesh])
    loops = solids.check_open(mesh)
    assert len(loops) == 1
    # No port edge is still open after assembly, including the extra 1 m caps.
    V, F = mesh.welded(1e-7)
    edges = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    edges, counts = np.unique(np.sort(edges, axis=1), axis=0, return_counts=True)
    for row in rows:
        ids = [int(np.argmin(np.linalg.norm(V - p, axis=1))) for p in row]
        for a, b in zip(ids[:-1], ids[1:], strict=True):
            match = (edges == sorted((a, b))).all(1)
            assert match.sum() == 1 and counts[match][0] == 2


def test_gap_length_and_drop_are_kept_in_elbow_height_lookup():
    line = L.LineSpec('T', 'test', L.Turtle((0., 0.), 0., (('straight', 100.),)), 30.,
                      (('line', 10.), ('gap', 20., -7., 'jump'), ('line', 30.)), (), '', '', rollin=0)
    assert L._profile_at(line, 40.) == pytest.approx((23., 0.))
    with pytest.raises(ValueError, match='not on a built profile'):
        L._profile_at(line, 15.)


def test_nonlevel_turn_is_rejected_instead_of_covering_a_bad_join():
    spec = turn()
    spec['grade_t'] = .1
    with pytest.raises(ValueError, match='level the complete elbow'):
        J.elbow(spec, ground=-2.)


def test_merge_has_tangent_and_curvature_continuity_at_both_ports():
    p = J.MergeCurve((100., 200.), 322.3, -1)
    assert p.length > 80.
    assert np.allclose(p.tangent([0., p.length]), J.direction(322.3), atol=1e-10)
    assert np.abs(p.curvature([0., p.length])).max() < 1e-10
    assert np.abs(p.curvature(np.linspace(0., p.length, 1001))).max() < 1 / 80.
    # Integrate the actual arc-length parameter independently.
    assert np.linalg.norm(np.diff(p.point(np.linspace(0., p.length, 10001)), axis=0), axis=1).sum() == pytest.approx(p.length, abs=1e-6)


def test_shared_merge_has_one_floor_and_no_internal_dividing_wall():
    built = J.shared_merge((100., 200.), 322.3, 7.)
    assert len(solids.check_open(built.mesh)) == 1
    assert built.mesh.features.count('S14.shared') == 1
    # At the merge seam every input floor segment is used twice: the arm and
    # one body, including the two flat inner shoulder caps meeting at centre.
    forward, left = J.direction(322.3), J.direction(412.3)
    V, F = built.mesh.welded(1e-7)
    edges = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    edges, count = np.unique(np.sort(edges, axis=1), axis=0, return_counts=True)
    at = np.abs((V[:, [0, 2]] - [100., 200.]) @ forward) < 1e-6
    lat = (V[:, [0, 2]] - [100., 200.]) @ left
    seam = at & (np.abs(lat) <= 19.00001) & (np.abs(V[:, 1] - 7.) < 1e-6)
    match = seam[edges].all(1)
    assert match.sum() > 10 and (count[match] == 2).all()


def test_short_high_speed_merge_cannot_silently_make_a_tight_s_bend():
    with pytest.raises(ValueError, match='at least 80 m'):
        J.shared_merge((0., 0.), 0., 0., approach=30.)


def test_fixed_radius_inner_walls_clear_each_other_along_the_whole_merge():
    path = J.MergeCurve((0., 0.), 0., 1)
    s = np.linspace(0., path.length, 4001)
    E = path.point(s)
    tangent = path.tangent(s)
    # P._bowl_rows fades by the riding edge's own plan length, not centre s.
    normal = path.normal(s)
    inner_floor = E - 9. * normal
    u = np.r_[0., np.cumsum(np.linalg.norm(np.diff(inner_floor, axis=0), axis=1))]
    h = 7. * P._bowl_scale(u, (0., path.length)) ** 3
    reach = np.sqrt(np.minimum(h, 6.) * (12. - np.minimum(h, 6.)))
    cap = inner_floor - (reach + 1.)[:, None] * normal
    assert cap[:, 1].min() >= -1e-6
    assert cap[-1, 1] == pytest.approx(0., abs=1e-7)


def test_analytic_semicircle_has_no_infinite_tangent_intersection():
    path = L.Turtle((0., 0.), 0., (('straight', 40.), ('turn', 20., 180.), ('straight', 40.)))
    curve = L.curve(path)
    s = np.linspace(0., path.length, 1001)
    expected = np.array([path.at(t)[0] for t in s])
    assert np.allclose(curve.point(s), expected, atol=1e-9)
    projected, distance = path.project(expected)
    assert np.allclose(projected, s, atol=1e-8)
    assert distance.max() < 1e-9
    assert np.abs(curve.point(s)).max() <= 60. + 1e-9


def test_half_bowl_is_a_continuous_large_outer_shoulder():
    path = L.Turtle((0., 0.), 0., (('straight', 60.), ('turn', 26., -90.), ('straight', 60.)))
    feature = L.Feature('T.HB', 'half_bowl', 60., 60. + 13. * np.pi, 18.)
    line = L.LineSpec('T', 'test', path, 0., (('line', path.length),), (feature,), '', '', rollin=0)
    left, right = L.run_sides(line, 18.)
    centre, tangent = path.at((feature.s0 + feature.s1) / 2)
    normal = np.array([-tangent[1], tangent[0]])
    height, radius = left.shape(np.array([[*(centre + 9 * normal), 0.]])[:, [0, 2, 1]])
    assert height == pytest.approx([8.]) and radius == pytest.approx([7.])
    assert right.height == 3. and right.radius == 3.5
    assert L.breaks(line) == []


def test_overlapping_fades_have_no_crease_where_their_weights_meet():
    u = np.linspace(0., 23., 23001)
    h = 3. * P._bowl_scale(u, (20., 15.))
    slope = np.gradient(h, u)
    assert np.abs(np.diff(slope)).max() < .001
    assert h[0] == h[-1] == 0.
