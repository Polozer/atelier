"""Fast checks of the gondola kit's pure geometry and gate decisions: no Blender, no world build.

The rope path (straight, sagging, over a tower, round a station), the plumb hang of the cabin, the grip's clearance
from its dimensions, and the decisions in checks.py and walk.py that make the build fail. Fixtures marked MUST FAIL
are faults the gates exist to catch: a hanger 0.05 m from the rope, a jaw contact 3 mm off the rope radius, and a
tilted cabin floor.
"""
import math

import pytest

from gondola_kit_fixture import gondola_modules, load

KIT = load('rope', 'checks', 'params', 'walk')              # pure: importing bpy or mathutils would raise here
R, C, W = KIT.rope, KIT.checks, KIT.walk
RR = KIT.params.DEFAULTS['rope_radius']


@pytest.fixture(scope='module')
def grip():
    with gondola_modules('cabin', pure=False) as kit:        # cabin.py uses mathutils inside its builders only
        return dict(kit.cabin.GRIP)


def apply(M, q):
    return tuple(M[i][0] * q[0] + M[i][1] * q[1] + M[i][2] * q[2] + M[i][3] for i in range(3))


def column(M, j):
    return tuple(M[i][j] for i in range(3))


def paths():
    yield 'level', R.straight((-5, 0, 0), (5, 0, 0), RR)
    yield 'grade 40%', R.straight((-5, 0, -2), (5, 0, 2), RR)
    yield 'grade 75%', R.straight((-5, 0, -3.75), (5, 0, 3.75), RR)
    yield 'grade 100%', R.straight((-5, 0, -5), (5, 0, 5), RR)
    yield 'sagging span', R.sagging_span(40.0, 4.0, RR)
    yield 'tower pass', R.over_tower(16.0, 3.0, RR, span=6.0)
    yield 'station loop', R.station_loop(3.0, 3.77, 3.62, 8.2, RR)


# ------------------------------------------------------------------ rope geometry
def test_pure_kit_modules_import_without_blender():
    with gondola_modules('rope', 'checks', 'params', 'walk', pure=True) as kit:
        assert kit.rope.RopePath and kit.checks.ROPE_CLEARANCE and kit.walk.STEP


def test_grip_frame_follows_the_rope_with_the_door_side_outward():
    path = R.straight((-5, 0, -2), (5, 0, 2), RR)
    for out in ((0, -1, 0), (0, 1, 0)):
        G = path.grip_frame(path.length / 2, out)
        x, y, z = column(G, 0), column(G, 1), column(G, 2)
        t = path.rope_tangent(path.length / 2)
        assert abs(abs(sum(a * b for a, b in zip(x, t))) - 1) < 1e-9          # x along the rope
        assert z[2] > 0 and abs(sum(a * b for a, b in zip(x, z))) < 1e-9      # z up, square to the rope
        assert sum(a * b for a, b in zip(y, out)) < 0                           # door side (-y) faces outward


def test_sagging_span_is_the_small_sag_catenary():
    half, sag = 40.0, 4.0
    path = R.sagging_span(half, sag, RR)
    assert path.pts[0][2] == pytest.approx(sag) and path.pts[-1][2] == pytest.approx(sag)
    assert min(p[2] for p in path.pts) == pytest.approx(0.0, abs=1e-9)
    t = path.rope_tangent(path.length, h=0.5)
    assert t[2] / t[0] == pytest.approx(2 * sag / half, rel=0.02)              # end slope of the parabola
    lo, hi = 1.0, 1e5                                                           # the catenary through the same supports
    for _ in range(200):
        a = (lo + hi) / 2
        lo, hi = (a, hi) if a * (math.cosh(half / a) - 1) > sag else (lo, a)
    worst = max(abs(p[2] - a * (math.cosh(p[0] / a) - 1)) for p in path.pts)
    assert worst < 0.02 * sag                                                   # within 2 % of the sag everywhere


def test_tower_pass_is_level_over_the_train_and_smooth():
    H, half_train, defl = 16.0, 1.6, 3.0
    path = R.over_tower(H, 3.0, RR, half_train=half_train, deflection_deg=defl, span=8.0)
    for p in path.pts:
        assert p[1] == 3.0
        if abs(p[0]) <= half_train:
            assert p[2] == pytest.approx(H)
        assert p[2] <= H + 1e-12
    t_end = path.rope_tangent(0.0, h=0.2)
    assert math.degrees(math.atan2(-t_end[2], -t_end[0])) == pytest.approx(-defl, abs=0.05) or \
        math.degrees(math.atan2(t_end[2], t_end[0])) == pytest.approx(defl, abs=0.05)
    turns = []
    for i in range(1, len(path.pts) - 1):
        a, b, c = path.pts[i - 1], path.pts[i], path.pts[i + 1]
        u = [b[k] - a[k] for k in range(3)]; v = [c[k] - b[k] for k in range(3)]
        cos = sum(x * y for x, y in zip(u, v)) / (math.hypot(*u) * math.hypot(*v))
        turns.append(math.degrees(math.acos(max(-1.0, min(1.0, cos)))))
    assert max(turns) < 0.1                                                     # filleted: no kink over the end sheaves


def test_station_loop_drops_inside_the_mouth_and_rounds_the_bullwheel():
    Rb, z_line, drop, mouth = 3.0, 3.77, 0.15, 8.2
    path = R.station_loop(Rb, z_line, z_line - drop, mouth, RR)
    for p in path.pts:
        if p[0] >= mouth:
            assert p[2] == pytest.approx(z_line)
        elif p[0] <= mouth - 1.6:
            assert p[2] == pytest.approx(z_line - drop)
        if p[0] < -1e-6:
            assert math.hypot(p[0], p[1]) == pytest.approx(Rb, abs=1e-6)       # on the bullwheel's rope circle


# ------------------------------------------------------------------ hanging plumb
def test_cabin_hangs_plumb_on_every_path(grip):
    for name, path in paths():
        for k in range(1, 8):
            s = path.length * k / 8
            G = path.grip_frame(s, (0, -1, 0))
            H = R.hang_frame(G, grip['pivot'])
            assert C.floor_tilt_deg(H) < 1e-6, name
            assert C.hanging_ok(H), name
            pg, ph = apply(G, grip['pivot']), apply(H, grip['pivot'])
            assert math.dist(pg, ph) < 1e-9, name                              # the pivot pin is shared
            hx, gx = column(H, 0), column(G, 0)
            assert hx[2] == 0.0 and (hx[0] * gx[1] - hx[1] * gx[0]) == pytest.approx(0.0, abs=1e-9), name   # same heading


def test_tilted_cabin_floor_fails():
    """MUST FAIL: a cabin that takes the rope's frame (pitched with the grip) on a 40 % grade, and a 0.02 deg tilt."""
    path = R.straight((-5, 0, -2), (5, 0, 2), RR)
    G = path.grip_frame(path.length / 2, (0, -1, 0))
    assert C.floor_tilt_deg(G) == pytest.approx(math.degrees(math.atan(0.4)), abs=1e-6)
    assert not C.hanging_ok(G)
    a = math.radians(2 * C.FLOOR_TILT_TOL_DEG)
    slight = [[math.cos(a), 0, math.sin(a), 0], [0, 1, 0, 0], [-math.sin(a), 0, math.cos(a), 0], [0, 0, 0, 1]]
    assert not C.hanging_ok(slight)


# ------------------------------------------------------------------ rope contacts and clearance
def test_contact_categories():
    for tag in ('jaw', 'clamp', 'sheave', 'bullwheel groove'):
        assert C.category(tag) == C.INTENTIONAL
    for tag in ('hanger', 'wheel', 'rail', 'roof', None):
        assert C.category(tag) == C.UNRELATED


def test_seated_contacts_pass():
    for off in (0.0, 0.0019, -0.0019):
        for tag in ('jaw', 'sheave', 'bullwheel groove'):
            row = C.classify(tag, RR + off, RR)
            assert row['ok'] and row['category'] == C.INTENTIONAL, (tag, off)


@pytest.mark.parametrize('off', [0.003, -0.003])
def test_contact_three_mm_off_the_rope_radius_fails(off):
    """MUST FAIL: a jaw (or sheave, or bullwheel groove) 3 mm off the rope radius, lifted off or pressed in."""
    for tag in ('jaw', 'sheave', 'bullwheel groove'):
        row = C.classify(tag, RR + off, RR)
        assert row['category'] == C.INTENTIONAL and not row['ok'], (tag, off)


def test_contact_that_never_meets_the_rope_fails():
    assert not C.contact_ok(None, RR)


def test_unrelated_hardware_clearance_rule():
    need = C.required_clearance(RR)
    assert need == pytest.approx(RR + C.ROPE_CLEARANCE)
    assert C.clearance_ok(need, RR) and C.clearance_ok(None, RR) and C.clearance_ok(0.5, RR)
    assert not C.clearance_ok(need - 0.001, RR) and not C.clearance_ok(0.0, RR)


def test_hanger_five_cm_from_the_rope_fails():
    """MUST FAIL: a hanger post whose face runs 0.05 m from the rope axis (inside the rope radius + 0.05 m)."""
    path = R.straight((-5, 0, 0), (5, 0, 0), RR)
    post = [(x * 0.05, -0.05, z * 0.05) for x in range(-4, 5) for z in range(0, 20)]   # the face nearest the rope
    d = C.point_clearance(post, path)
    assert d == pytest.approx(0.05, abs=1e-9)
    row = C.classify('hanger', d, RR)
    assert row['category'] == C.UNRELATED and not row['ok']
    clear = [(x, y - 0.15, z) for x, y, z in post]
    assert C.classify('hanger', C.point_clearance(clear, path), RR)['ok']


def test_grip_wheels_and_pivot_clear_the_rope(grip):
    res = C.grip_clearances(grip, RR)
    assert res['ok'], res
    assert res['wheel_m'] == pytest.approx(abs(grip['wheel_y']) - grip['wheel_width'] / 2, abs=1e-4)
    assert res['pivot_point_m'] == pytest.approx(math.hypot(grip['pivot'][1], grip['pivot'][2]), abs=1e-4)


def test_grip_wheel_against_the_rope_fails(grip):
    """MUST FAIL: running wheels pulled in so their tyres come within the rope clearance."""
    tight = dict(grip, wheel_y=-0.12)
    assert not C.grip_clearances(tight, RR)['ok']


# ------------------------------------------------------------------ other gates
def test_budgets():
    assert C.budget_failures('cabin', C.BUDGET['cabin']) == []
    assert C.budget_failures('station', C.BUDGET['station'] + 1)


def test_collision_proxies_must_be_convex_hulls():
    box = {'name': 'box', 'poly': [[0, 0], [1, 0], [1, 1], [0, 1]], 'z0': [0] * 4, 'z1': [1] * 4}
    ell = {'name': 'ell', 'poly': [[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]], 'z0': [0] * 6, 'z1': [1] * 6}
    flat = dict(box, name='flat', z1=[0] * 4)
    assert C.proxy_failures([box]) == []
    assert C.proxy_failures([ell]) and C.proxy_failures([flat]) and C.proxy_failures([])


def piece(**kw):
    good = {'routes': [{'route': 'a -> b', 'connected': True, 'meets_0.9': True, 'bottleneck_width_m': 1.4}],
            'pinch_points': [], 'trapping_pockets': [], 'stairs': [], 'boarding': []}
    return good | kw


def test_walk_verdict_passes_a_clean_piece():
    assert W.verdict(piece()) == []


def test_walk_verdict_fails_each_fault():
    assert W.verdict(piece(routes=[{'route': 'a -> b', 'connected': False}]))
    assert W.verdict(piece(routes=[{'route': 'a -> b', 'connected': True, 'meets_0.9': False, 'bottleneck_width_m': 0.7}]))
    assert W.verdict(piece(pinch_points=[{'status': 'too narrow', 'clear_width_m': 0.6, 'at': [0, 0]}]))
    assert W.verdict(piece(trapping_pockets=[{'at': [0, 0]}]))
    steep = {'x': [0, 1], 'y': [0, 1], 'riser_m': W.RISER_MAX + 0.05, 'tread_m': 0.3, 'width_m': 1.2,
             'riser_ok': False, 'tread_ok': True, 'width_ok': True}
    assert W.verdict(piece(stairs=[steep]))
    assert W.verdict(piece(door={'clear_width_m': 0.8, 'clear_height_m': 2.0, 'ok': False}))
    assert W.verdict(piece(boarding=[{'side': 1, 'door_within_gate': False}]))


def test_walk_exits_nonzero_on_failure(monkeypatch):
    monkeypatch.setattr(W, 'audit', lambda quiet=False: ({}, ['valley: route a -> b: not connected']))
    with pytest.raises(SystemExit) as e:
        W.main()
    assert e.value.code == 1
    monkeypatch.setattr(W, 'audit', lambda quiet=False: ({}, []))
    W.main()
