"""Crater Park v2 ground landform: the constrained Delaunay mesher, conforming foot loops, a closed site, gentle slopes."""
import sys
from pathlib import Path

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
sys.path.insert(0, str(GAME / 'world'))

from craterpark.v2 import cdt, dsl, ground  # noqa: E402


def edges(F):
    return np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])


def test_cdt_keeps_every_constraint_and_fills_the_region_exactly():
    o = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)
    a = np.linspace(0, 2 * np.pi, 40, endpoint=False); h = np.c_[5 + 2 * np.cos(a), 5 + 2 * np.sin(a)]
    g = np.stack(np.meshgrid(np.arange(.5, 10, 1.), np.arange(.5, 10, 1.)), -1).reshape(-1, 2)
    g = g[np.linalg.norm(g - 5, axis=1) > 2.4]
    P = np.vstack([o, h, g]); loops = [np.arange(4), 4 + np.arange(40)]
    F = cdt.triangulate(P, loops)
    t = P[F]
    area = ((t[:, 1, 0] - t[:, 0, 0]) * (t[:, 2, 1] - t[:, 0, 1]) - (t[:, 1, 1] - t[:, 0, 1]) * (t[:, 2, 0] - t[:, 0, 0])) / 2
    assert (area > 0).all()
    assert area.sum() == pytest.approx(100 - abs(ground.signed_area(h)))
    E = set(map(tuple, np.sort(edges(F), 1).tolist()))
    for L in loops:
        assert all(tuple(sorted((int(L[i]), int(L[(i + 1) % len(L)])))) in E for i in range(len(L)))


def test_cdt_recovers_a_segment_that_cuts_through_a_lattice():
    g = np.stack(np.meshgrid(np.arange(0, 10.1, .5), np.arange(0, 10.1, .5)), -1).reshape(-1, 2) + [.013, .007]
    o = np.array([[-1, -1], [11, -1], [11, 11], [-1, 11]], float); s = np.array([[.2, .3], [9.7, 9.1], [9.8, .4]])
    F = cdt.triangulate(np.vstack([o, s, g]), [np.arange(4), [4, 5, 6]])
    E = set(map(tuple, np.sort(edges(F), 1).tolist()))
    assert {(4, 5), (5, 6), (4, 6)} <= E


def site():
    o = np.array([[0, 0], [120, 0], [120, 100], [0, 100]], float)
    controls = np.array([[110, 20, 50], [10, 0, 50], [60, 10, 90], [60, 10, 10]], float)
    a = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    foot = np.c_[60 + 8 * np.cos(a), 11 + .5 * np.sin(a), 50 + 8 * np.sin(a)]
    return o, [foot], controls


def test_ground_meets_a_foot_loop_exactly_and_closes_the_site():
    o, holes, controls = site()
    m = ground.ground(o, holes, controls)
    foot = holes[0]
    # the foot loop's vertices are the ground's own, exactly
    key = {tuple(p) for p in np.round(m.V, 9).tolist()}
    assert all(tuple(p) in key for p in np.round(foot, 9).tolist())
    # a stand-in feature on the foot loop closes it: the whole is watertight and outward
    V, F = ground.fill_mesh(foot, [0, 1, 0])
    whole = dsl.Mesh.concat([m, dsl.Mesh.part(V, F, role=dsl.RIDING)])
    P, W = whole.welded(1e-7)
    _, count = np.unique(np.sort(edges(W), 1), axis=0, return_counts=True)
    _, directed = np.unique(edges(W), axis=0, return_counts=True)
    assert (count == 2).all() and directed.max() == 1
    t = P[W]
    assert np.einsum('ij,ij->i', t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() > 0
    g = m.where(role=dsl.GROUND)
    assert (g.face_normals()[:, 1] > 0).all()
    assert len(m.where(role=dsl.BASE).F) and len(m.where(role=dsl.SIDE).F)


def test_ground_is_graded_gentle_and_sliver_free():
    o, holes, controls = site()
    m = ground.ground(o, holes, controls)
    g = m.where(role=dsl.GROUND)
    t = g.triangles(); L = np.linalg.norm(t - np.roll(t, 1, 1), axis=2)
    q = 4 * np.sqrt(3) * g.areas() / (L ** 2).sum(1)
    assert q.min() > .01 and L.max() <= 8. * 1.5
    rep = ground.report(m)
    assert rep['max_slope_deg'] < 30.
    # fine at the seam, coarse far from it
    c = t.mean(1); d = np.linalg.norm(c[:, [0, 2]] - [60, 50], axis=1)
    assert L[d < 9].max(1).mean() < L[d > 30].max(1).mean() / 3


def test_fill_mesh_keeps_the_loop_and_has_no_slivers():
    s = np.linspace(0, np.pi / 2, 46)
    arc = np.c_[3.5 * np.sin(s), 3.5 * (1 - np.cos(s))]
    def line(a, b, step=2.):
        n = int(np.ceil(np.linalg.norm(np.subtract(b, a)) / step))
        return np.linspace(a, b, n + 1)[1:]
    section = np.vstack([arc, line(arc[-1], [3.5, 3.8]), line([3.5, 3.8], [11.5, 3.8]), line([11.5, 3.8], [11.5, -.3]),
                         line([11.5, -.3], [0., -.3]), line([0., -.3], [0., 0.])[:-1]])
    loop = np.c_[np.zeros(len(section)), section[:, 1], section[:, 0]]
    V, F = ground.fill_mesh(loop, [1, 0, 0])
    assert np.array_equal(V[:len(loop)], loop)
    t = V[F]; L = np.linalg.norm(t - np.roll(t, 1, 1), axis=2)
    area = .5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
    assert (4 * np.sqrt(3) * area / (L ** 2).sum(1)).min() > .01 and L.max() <= 4.
    assert (np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])[:, 0] > 0).all()


def test_controls_are_met_exactly_and_edges_stay_short_on_a_hilly_field():
    o = np.array([[0, 0], [200, 0], [200, 160], [0, 160]], float)
    rng = np.random.default_rng(3)
    xz = rng.random((12, 2)) * [180, 140] + 10
    controls = np.c_[xz[:, 0], 8 * np.sin(xz[:, 0] / 30) + 5 * np.cos(xz[:, 1] / 25), xz[:, 1]]
    m = ground.ground(o, [], controls)
    g = m.where(role=dsl.GROUND)
    for c in controls:
        d = np.linalg.norm(g.V - c, axis=1)
        assert d.min() < .01
    t = g.triangles()
    assert np.linalg.norm(t - np.roll(t, 1, 1), axis=2).max() <= 8. + 1e-9


def test_collinear_controls_and_a_guide_do_not_break_the_trend():
    o = np.array([[0, 0], [100, 0], [100, 80], [0, 80]], float)
    fall = np.c_[np.linspace(10, 90, 9), np.linspace(20, 0, 9), np.full(9, 40.)]
    m = ground.ground(o, [], fall)
    m2 = ground.ground(o, [], [[50, 12, 40]], guide=fall)
    assert np.isfinite(m.V).all() and np.isfinite(m2.V).all()
    assert np.linalg.norm(m2.V - [50, 12, 40], axis=1).min() < .01


def test_a_60_m_ridge_rises_smoothly_with_no_slope_over_30_degrees():
    """The raised landforms (owner, 780 m tower): a ridge 60 m over a gently falling site, guided by a spline of
    points, its flanks falling to the outline with no cliff."""
    o = np.array([[0, 0], [400, 0], [400, 300], [0, 300]], float)
    x = np.linspace(40, 360, 9)
    ridge = np.c_[x, 60 - x * .02, np.full(len(x), 150.)]
    rim = np.c_[np.linspace(0, 400, 9), np.full(9, -5.), np.full(9, 5.)]
    rim2 = rim + [0, 0, 290]
    guide = np.vstack([ridge, rim, rim2])
    m = ground.ground(o, [], [[200, 62, 150]], guide=guide)
    g = m.where(role=dsl.GROUND)
    rep = ground.report(m)
    assert rep['max_slope_deg'] <= 30.
    assert np.linalg.norm(g.V - [200, 62, 150], axis=1).min() < .01         # the exact control (a deck height)
    assert g.V[:, 1].max() >= 58.
    t = g.triangles()
    assert np.linalg.norm(t - np.roll(t, 1, 1), axis=2).max() <= 8. + 1e-9
    # no cliff: neighbouring vertices never differ by more than the slope allows over their distance
    P, F = g.welded(1e-7)
    e = np.unique(np.sort(edges(F), 1), axis=0)
    d = P[e[:, 0]] - P[e[:, 1]]
    assert (np.abs(d[:, 1]) <= np.tan(np.radians(30.)) * np.linalg.norm(d[:, [0, 2]], axis=1) + 1e-6).all()


def test_slope_limit_cuts_a_spike_but_keeps_fixed_heights():
    P2 = np.array([[0, 0], [10, 0], [0, 10], [10, 10], [5, 5]], float)
    F = np.array([[0, 1, 4], [1, 3, 4], [3, 2, 4], [2, 0, 4]])
    y = np.array([0, 0, 0, 0, 50.])
    out = ground.limit_slope(P2, F, y, np.array([1, 1, 1, 1, 0], bool), 30.)
    assert np.allclose(out[:4], 0) and 2.6 < out[4] <= np.tan(np.radians(30)) * 5 + 1e-9   # the face rule


def test_the_apron_is_pale_concrete_within_6_m_and_its_edge_is_a_smooth_curve():
    o, holes, controls = site()
    m = ground.ground(o, holes, controls, apron=6.)
    g = m.where(role=dsl.GROUND)
    c = g.triangles().mean(1)
    r = np.linalg.norm(c[:, [0, 2]] - [60, 50], axis=1)          # the foot is a circle of radius 8 about (60, 50)
    concrete = g.material == dsl.MATERIAL[dsl.CONCRETE]
    assert concrete[r < 8 + 5.5].all() and not concrete[r > 8 + 6.5].any()
    # the edge between the two materials: edges shared by a concrete and an earth face lie on one circle of radius 14
    F = g.F; e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]); owner = np.tile(np.arange(len(F)), 3)
    key = np.sort(e, 1); order = np.lexsort((key[:, 1], key[:, 0])); key, owner = key[order], owner[order]
    same = (key[1:] == key[:-1]).all(1)
    a, b = owner[:-1][same], owner[1:][same]
    border = key[:-1][same][concrete[a] != concrete[b]]
    rad = np.linalg.norm(g.V[border.ravel()][:, [0, 2]] - [60, 50], axis=1)
    assert len(border) > 20 and np.ptp(rad) < .3 and abs(rad.mean() - 14) < .3


def square(c, r, y=0., n=4):
    a = np.linspace(0, 2 * np.pi, 4 * n, endpoint=False)
    p = np.c_[np.cos(a), np.sin(a)]; p = p / np.abs(p).max(1, keepdims=True) * r + c
    return np.c_[p[:, 0], np.full(len(p), y), p[:, 1]]


def test_bad_foot_loops_are_refused_by_name():
    o = square([0., 0.], 40.)
    with pytest.raises(ValueError, match='foot loop 0 leaves the site outline'):
        ground.ground(o, [square([38., 0.], 5.)])
    with pytest.raises(ValueError, match='foot loop 1 overlaps foot loop 0|foot loop 0 overlaps foot loop 1'):
        ground.ground(o, [square([0., 0.], 5.), square([6., 0.], 5.)])
    # two feet sharing a seam edge are not an overlap
    ground._check_loops(o[:, [0, 2]], [square([0., 0.], 5.)[:, [0, 2]], square([10., 0.], 5.)[:, [0, 2]]])


def test_an_infeasible_foot_is_reported_and_the_base_stays_below_the_surface():
    o = square([0., 0.], 40., n=16)                 # a 3D outline at y 0: its heights are kept
    foot = square([-30., 0.], 6., y=25.)            # 25 m up, 4 m from the edge: no 30 degree slope reaches it
    with pytest.warns(UserWarning, match='spots over'):
        m = ground.ground(o, [foot], skirt=3.)
    spots = ground.steep_spots(m)
    assert spots and spots[0]['max_deg'] > 60 and spots[0]['where'][0] < -30
    g = m.where(role=dsl.GROUND); base = m.where(role=dsl.BASE)
    assert base.V[:, 1].max() <= 0 - 3 + 1e-9 and base.V[:, 1].min() < g.V[:, 1].min()
    # a feasible site reports nothing
    assert not ground.steep_spots(ground.ground(o, [square([0., 0.], 6., y=5.)]))
