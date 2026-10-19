"""Brinecove's hill stair is walkable from the terrace to the hamlet shelf, and the landmarks stay in budget."""
import sys
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world'))
import yori  # noqa: E402,F401
from brinecove import landmarks as LM, layout as L  # noqa: E402
from brinecove.geom import Builder  # noqa: E402


def test_stair_rises_never_exceed_a_step():
    route = LM.stair_route()
    rises = [abs(b[2] - a[2]) for a, b in zip(route, route[1:])]
    assert max(rises) <= 0.30


def test_stair_never_dips_below_the_ground():
    for x, y, z in LM.stair_route():
        assert z >= L.ground(x, y) - 0.05, (x, y, z)


def test_stair_joins_the_terrace_and_the_hamlet_shelf():
    route = LM.stair_route()
    x, y, z = route[0]
    assert abs(z - L.UPPER_Z) <= 0.5
    x, y, z = route[-1]
    assert abs(z - L.ground(x, y)) <= 0.6
    # The plaza is on the shelf the hamlet stands on.
    assert y > max(h[2] for h in L.HILLSIDE_BUILDINGS) - 20.0


def test_stair_treads_are_deep_enough_and_landings_flat():
    plan = LM._stair_plan()
    for f in plan['flights']:
        assert LM.STAIR_RUN / (f['risers'] - 1) >= LM.TREAD_MIN
        assert f['rise'] / f['risers'] <= 0.30
    assert LM.STAIR_LANDING >= 3.0


def test_no_building_stands_in_the_stair():
    for spec in list(L.BUILDINGS) + list(L.HILLSIDE_BUILDINGS):
        for x, y, _ in LM.stair_route():
            lx, ly = L.local_point(x, y, spec[1], spec[2], -spec[9])
            assert not (abs(lx) <= spec[4] / 2 + 1.0 and abs(ly) <= spec[5] / 2 + 1.0), spec[0]


def triangles(build, *args):
    b = Builder('t')
    build(b, *args)
    return sum(len(f) - 2 for f in b.faces)


def test_landmarks_stay_in_budget():
    assert triangles(LM.fort) <= 25000
    assert triangles(LM.shipyard) <= 20000
    assert 1500 <= triangles(LM.cannon, 0.0, 0.0, 0.0) <= 3000


def test_cannon_is_about_three_metres_long_and_stands_on_its_trucks():
    b = Builder('c')
    LM.cannon(b, 10.0, 20.0, 5.0, 90.0)
    xs, ys, zs = zip(*b.verts)
    assert 2.9 <= max(xs) - min(xs) <= 3.5   # yaw 90 turns the barrel onto x
    assert min(zs) >= 5.0 - 0.05
