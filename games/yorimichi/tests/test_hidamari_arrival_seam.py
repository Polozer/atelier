"""The arrival road ribbon runs on from the island road flush, with no step, and its shoulders meet the ground drawn
under them on both terrains."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from hidamari import arrival  # noqa: E402

N, SIZE = 301, 600.
END = (294.51, 59.69, .05*294.51 + .25)   # the island road, its strip a little above the terrain


def is_skirt(points):
    return any(p[:2] == q[:2] and p[2] != q[2] for p in points for q in points)


class Mesh:
    def __init__(self):
        self.polys = []

    def poly(self, points, key):
        self.polys.append((points, key))


def hillside(x, y):
    # Hidamari's ground: it meets the island terrain at x 300 and rolls away east of it.
    return .05*np.asarray(x) + .5*np.sin((np.asarray(x) - 300)/7.)


@pytest.fixture
def island(monkeypatch):
    # A slope rising east with alternating twisted quads (their two diagonals differ by 0.2 m), untwisted on its east
    # edge, where it meets Hidamari's ground.
    axis = np.linspace(-SIZE/2, SIZE/2, N); x, y = np.meshgrid(axis, axis)
    H = .05*x + .1*((np.arange(N)[:, None]+np.arange(N)[None, :]) % 2)*(np.arange(N)[None, :] < N-1)
    road = [[250., 60., .05*250 + .25], list(END)]
    monkeypatch.setattr(arrival, '_world', lambda: {'road': road, 'n': N, 'size': SIZE})
    monkeypatch.setattr(arrival, '_island', lambda: (H, N, SIZE))
    xs = tuple(np.arange(300., 420.1, 4.)); ys = tuple(np.arange(0., 240.1, 4.))
    monkeypatch.setattr(arrival, '_hidamari_axes', lambda: (xs, ys))
    for cached in (arrival._road, arrival._samples):
        cached.cache_clear()
    yield H
    for cached in (arrival._road, arrival._samples):
        cached.cache_clear()


def test_drawn_follows_the_importers_a_c_diagonal():
    a, b, c, d = 0., 1., 5., 2.
    for tx, ty in [(.2, .1), (.9, .3), (.1, .8), (.4, .6), (.5, .5)]:
        if tx >= ty:   # triangle a b c
            expected = a + (b-a)*tx + (c-b)*ty
        else:          # triangle a c d
            expected = a + (c-d)*tx + (d-a)*ty
        assert arrival._drawn(a, b, c, d, tx, ty) == pytest.approx(expected)
    assert arrival._drawn(a, b, c, d, .5, .5) == pytest.approx((a+c)/2)   # on the diagonal itself


def test_island_height_is_the_drawn_island_mesh(island):
    for x, y in [(294.3, 60.1), (295.7, 61.9), (293.1, 62.6), (296.9, 57.2)]:
        fx, fy = (x+SIZE/2)/2, (y+SIZE/2)/2; i, j = int(fx), int(fy)
        a, b, c, d = island[j, i], island[j, i+1], island[j+1, i+1], island[j+1, i]
        assert arrival.island_height(x, y) == pytest.approx(arrival._drawn(a, b, c, d, fx-i, fy-j))


def test_the_ribbon_starts_as_the_island_roads_own_flat_strip(island):
    c, n, z = arrival._sections(hillside)[0]
    road = [z[s] for s in arrival.ASPHALT]
    assert road == pytest.approx([END[2] + arrival.ROAD_LIFT] * len(road))   # its height, flat across like the island strip
    assert c == pytest.approx(END[:2])


def test_asphalt_eases_onto_the_hillside_without_steps(island):
    sections = arrival._sections(hillside)
    g = arrival.ground(hillside)
    centre = [z[0.] for _, _, z in sections]
    assert max(abs(q - p) for p, q in zip(centre, centre[1:])) < .05       # every 0.25 m: no step
    for c, n, z in sections:
        for s in arrival.ASPHALT:
            assert z[s] >= g(c[0]+n[0]*s, c[1]+n[1]*s) + .02 - 1e-9          # never under the ground drawn there
    far = [(c, n, z) for c, n, z, t in zip(*zip(*sections), arrival._samples()[2]) if t > arrival.BLEND]
    assert far and all(z[0.] == pytest.approx(g(*c) + .12) for c, n, z in far)


def test_shoulders_meet_the_drawn_ground_flush(island):
    g = arrival.ground(hillside)
    at = lambda c, n, s: g(c[0]+n[0]*s, c[1]+n[1]*s)
    for c, n, z in arrival._sections(hillside):
        for side in (-1, 1):
            edge, *between, outer = arrival._shoulder(side)
            assert z[outer] == pytest.approx(at(c, n, outer) + arrival.FLUSH)
            assert all(z[s] >= at(c, n, s) + arrival.FLUSH - 1e-9 for s in between)
            assert at(c, n, edge) < z[edge] <= z[side*arrival.SHOULDER[0]]   # just under the asphalt's edge


def test_skirts_hang_only_below_the_shoulders_outer_edges_and_start(island):
    m = Mesh()
    arrival._ribbon(m, hillside)
    g = arrival.ground(hillside)
    skirts = [points for points, key in m.polys if is_skirt(points)]
    assert all(key == 'ar_road_gravel' for points, key in m.polys if is_skirt(points))
    pts, _, _ = arrival._samples()
    c, n = pts[0], arrival._samples()[1][0]
    start = [s for s in skirts if all(abs((x - c[0])*n[1] - (y - c[1])*n[0]) < 1e-6 for x, y, _ in s)]
    for s in skirts:   # no raised face: along the road a skirt's top is a shoulder's outer edge, FLUSH above the ground
        if s not in start:
            assert all(z <= g(x, y) + arrival.FLUSH + 1e-9 for x, y, z in s)
    across = len(arrival.SHOULDER) - 1
    assert len(skirts) == 2 * 2 * (len(pts) - 1 + across)   # each outer edge per segment and across each start,
    #                                                       in both windings
    assert len(start) == 2 * 2 * across
    for s in start:   # under the shoulders only, never a lip across the road
        assert all(abs((x - c[0])*n[0] + (y - c[1])*n[1]) > arrival.SHOULDER[0] for x, y, _ in s)
