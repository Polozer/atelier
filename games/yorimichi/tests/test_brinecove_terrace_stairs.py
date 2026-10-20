"""Brinecove's three quay-to-terrace stairs are climbable step by step, gapless, and land flush on the terrace."""
import sys
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world'))
import yori  # noqa: E402,F401
from brinecove import layout as L, modules as M  # noqa: E402

TERRACE_TOP = L.UPPER_Z + 0.22


def test_every_riser_is_a_step_the_pawn_takes():
    for x, _ in M.TERRACE_STAIRS:
        z0, steps = M.terrace_stair_plan(x)
        # As built, each riser climbs to the nosing, which stands NOSING_LIFT above its tread.
        tops = [z0] + [top + M.NOSING_LIFT for _, _, top in steps] + [TERRACE_TOP]
        rises = [b - a for a, b in zip(tops, tops[1:])]
        assert min(rises) > 0.1 and max(rises) <= M.STAIR_RISE_MAX + 1e-9, x


def test_treads_abut_from_the_quay_street_to_the_terrace_edge():
    for x, _ in M.TERRACE_STAIRS:
        z0, steps = M.terrace_stair_plan(x)
        assert abs(z0 - M.stair_apron(x)[4]) < 1e-9
        assert steps[0][0] == M.STAIR_FOOT_Y and abs(steps[-1][1] - M.STAIR_TOP_Y) < 1e-6
        assert all(abs(b[0] - a[1]) < 1e-9 for a, b in zip(steps, steps[1:])), x
        assert min(y1 - y0 for y0, y1, _ in steps) >= 0.35, x


def test_landings_break_every_flight_and_are_flat_and_deep():
    for x, _ in M.TERRACE_STAIRS:
        _, steps = M.terrace_stair_plan(x)
        landings = [i for i, (y0, y1, _) in enumerate(steps) if y1 - y0 > M.STAIR_LANDING - 1e-6]
        assert landings, x
        bounds = [-1] + landings + [len(steps)]
        assert max(b - a - 1 for a, b in zip(bounds, bounds[1:])) <= M.STAIR_FLIGHT, x


def test_treads_are_solid_down_past_the_quay_so_no_daylight_shows_under_a_nosing():
    b = M.Builder('stair_probe')
    x, width = M.TERRACE_STAIRS[0]
    M.terrace_stair(b, x, width, cheek=1.6)
    z0, steps = M.terrace_stair_plan(x)
    assert len(b.verts) > 0
    lowest = min(v[2] for v in b.verts)
    assert lowest <= z0 - 0.5


def test_no_house_stands_in_a_terrace_stair():
    """Every house footprint (with room for its eaves and doorstep props) stays out of each stair and its parapets."""
    import math
    clear = 1.5
    for x0, width in M.TERRACE_STAIRS:
        cheek = M.TERRACE_CHEEKS[x0]
        xa, xb = x0 - width / 2 - cheek - clear, x0 + width / 2 + cheek + clear
        for key, x, y, _, w, d, _, _, _, yaw, _ in L.DENSE_LOTS:
            c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
            pts = [(x + c * dx - s * dy, y + s * dx + c * dy) for dx in (-w / 2, w / 2) for dy in (-d / 2, d / 2)]
            if max(py for _, py in pts) < M.STAIR_FOOT_Y - clear or min(py for _, py in pts) > M.STAIR_TOP_Y + clear:
                continue
            assert max(px for px, _ in pts) < xa or min(px for px, _ in pts) > xb, (x0, key)


def _floor(b, x, y):
    """The highest horizontal face of the built geometry over (x, y): what the pawn stands on there."""
    best = None
    for face in b.faces:
        pts = [b.verts[i] for i in face]
        if max(p[2] for p in pts) - min(p[2] for p in pts) > 1e-6:
            continue
        if min(p[0] for p in pts) <= x <= max(p[0] for p in pts) and min(p[1] for p in pts) <= y <= max(p[1] for p in pts):
            best = pts[0][2] if best is None else max(best, pts[0][2])
    return best


def test_the_built_street_meets_each_stair_on_a_level_apron_within_one_riser():
    """Built geometry, not the plan: the lower town's street slabs and each stair. Across the stair's apron the
    floor is the apron's top (no slab pokes through); from there to the first nosing, and from every street slab
    beside the apron onto it, is at most one riser (playtest note 410-1: the first riser off the slab was 0.26 m)."""
    b = M.Builder('stair_join_probe')
    for x, y, w, d in M.LOWER_ROADS:
        M.paving(b, x - w / 2, x + w / 2, y - d / 2, y + d / 2, kerbs=(False, False), seed=int(x))
    for y0, y1 in M.LOWER_BANDS:
        M.paving(b, -372.0, 372.0, y0, y1, seed=int(y0), skip=M.MARKET_FLOOR)
    for x, width in M.TERRACE_STAIRS:
        M.terrace_stair(b, x, width, cheek=M.TERRACE_CHEEKS[x])
    for x, width in M.TERRACE_STAIRS:
        ax0, ax1, ay0, ay1, top = M.stair_apron(x)
        z0, steps = M.terrace_stair_plan(x)
        assert top == z0
        for k in range(9):
            for j in range(5):
                px, py = ax0 + 0.05 + (ax1 - ax0 - 0.1) * k / 8, ay0 + 0.05 + (ay1 - ay0 - 0.1) * j / 4
                assert abs(_floor(b, px, py) - top) < 1e-6, (x, px, py)
        for px in (x - width / 2 + 0.3, x, x + width / 2 - 0.3):
            nosing = _floor(b, px, M.STAIR_FOOT_Y + 0.07)
            assert abs(nosing - (steps[0][2] + M.NOSING_LIFT)) < 1e-6, (x, px)
            assert 0.1 < nosing - top <= M.STAIR_RISE_MAX + 1e-9, (x, px, nosing - top)
        beside = [(ax0 + (ax1 - ax0) * k / 8, ay0 - 0.3) for k in range(9)]
        beside += [(ax0 - 0.3, ay0 + (ay1 - ay0) * j / 4) for j in range(5)] + [(ax1 + 0.3, ay0 + (ay1 - ay0) * j / 4) for j in range(5)]
        for px, py in beside:
            street = _floor(b, px, py)
            assert street is not None and abs(top - street) <= M.STAIR_RISE_MAX, (x, px, py, top - street)
