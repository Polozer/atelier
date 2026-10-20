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
        tops = [z0] + [top for _, _, top in steps] + [TERRACE_TOP]
        rises = [b - a for a, b in zip(tops, tops[1:])]
        assert min(rises) > 0.1 and max(rises) <= M.STAIR_RISE_MAX + 1e-9, x


def test_treads_abut_from_the_quay_street_to_the_terrace_edge():
    for x, _ in M.TERRACE_STAIRS:
        z0, steps = M.terrace_stair_plan(x)
        assert abs(z0 - (L.ground(x, M.STAIR_FOOT_Y) + 0.16)) < 1e-9
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
