"""Brinecove's quay is paved up to the market floor and the stair foot, and the stair nosings never z-fight.

Op410 review: the street band skipped a 216 m column over the market, leaving bare terrain (blending to sand) with
straight edges between the market floor and the grand stair; and each nosing's front face was coplanar with its
tread's riser, which showed as streaks along every step edge.
"""
import sys
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world'))
import yori  # noqa: E402,F401
from brinecove import modules as M  # noqa: E402


class Boxes:
    """Records box() calls; every other builder call is ignored."""
    def __init__(self):
        self.boxes = []

    def box(self, center, size, mat, yaw=0.0, top=None):
        self.boxes.append((center, size, mat))

    def __getattr__(self, name):
        return lambda *a, **k: None


def inside(box, x, y):
    (cx, cy, _), (sx, sy, _), _ = box
    return abs(x - cx) <= sx / 2 + 1e-6 and abs(y - cy) <= sy / 2 + 1e-6


def test_market_street_band_leaves_no_bare_ground_beside_the_market_floor():
    b = Boxes()
    M.pave_band(b, 210, 242)
    slabs = [box for box in b.boxes if abs(box[1][2] - 0.22) < 1e-9]
    x0, x1, y0, y1 = M.MARKET_FLOOR
    bare = [(x, y) for x in range(-120, 121, 2) for y in (210.5, 214, 218, 222, 225.9, 226.5, 228, 229.8, 234, 241.5)
            if not (x0 <= x <= x1 and y0 <= y <= y1) and not any(inside(s, x, y) for s in slabs)]
    assert not bare, bare[:8]


def test_market_floor_is_not_paved_over():
    b = Boxes()
    M.pave_band(b, 210, 242)
    x0, x1, y0, y1 = M.MARKET_FLOOR
    for (cx, cy, _), (sx, sy, sz), _ in b.boxes:
        if abs(sz - 0.22) < 1e-9:
            assert not (x0 <= cx - sx / 2 and cx + sx / 2 <= x1 and y0 <= cy - sy / 2 and cy + sy / 2 <= y1)


def test_nosings_stand_proud_of_their_treads():
    for x, width in M.TERRACE_STAIRS:
        b = Boxes()
        M.terrace_stair(b, x, width, cheek=1.0)
        _, steps = M.terrace_stair_plan(x)
        nosings = [box for box in b.boxes if box[2] == 'stone' and abs(box[1][2] - 0.08) < 1e-9]
        assert len(nosings) == len(steps), x
        for ((cx, cy, _), (sx, sy, _), _), (y0, _, _) in zip(nosings, steps):
            assert cy - sy / 2 <= y0 - 0.01, (x, y0)          # its front face is ahead of the riser, not on it
            assert sx <= width - 0.01 and abs(cx - x) < 1e-9   # its ends are inside the tread's sides
