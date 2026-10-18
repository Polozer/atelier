"""Brinecove's ground closes exactly onto the far hills' hole, and the far hills hide exactly that hole."""
import sys
from pathlib import Path

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world'))
import yori  # noqa: E402,F401
import farhills_surface  # noqa: E402
from brinecove import ground, region as R  # noqa: E402


def far_hills(extra_y=(300., 500.)):
    """A FarHills-like quad mesh on the 96-knot axis with inserted rows, hiding cells by their centres."""
    axis = np.linspace(-3200., 3200., 96)
    x0, y0, x1, y1 = R.OUTER_WORLD
    xs = axis[(axis > x0 - 200) & (axis < x1 + 200)]
    ys = np.unique(np.r_[axis, extra_y])
    ys = ys[(ys > y0 - 200) & (ys < y1 + 200)]
    vertices, index, triangles = [], {}, []

    def vertex(x, y):
        key = (round(x, 6), round(y, 6))
        if key not in index:
            index[key] = len(vertices)
            vertices.append((x, y, 40. * np.tanh(y / 150.) + 3. * np.sin(x / 90.)))
        return index[key]

    for a, b in zip(xs[:-1], xs[1:]):
        for c, d in zip(ys[:-1], ys[1:]):
            if farhills_surface.owns_fine_ground((a + b) / 2, (c + d) / 2, city=True):
                continue
            p = [vertex(a, c), vertex(b, c), vertex(b, d), vertex(a, d)]
            triangles += [(p[0], p[1], p[2]), (p[0], p[2], p[3])]
    return vertices, triangles


def test_far_hills_hide_exactly_the_region_rectangle_with_the_city():
    x0, y0, x1, y1 = R.OUTER_WORLD
    assert farhills_surface.owns_fine_ground((x0 + x1) / 2, (y0 + y1) / 2, city=True)
    assert not farhills_surface.owns_fine_ground((x0 + x1) / 2, (y0 + y1) / 2, city=False)
    for x, y in [(x0 - 1, -100), (x1 + 1, -100), (-1500, y0 - 1), (-1500, y1 + 1)]:
        assert not farhills_surface.owns_fine_ground(x, y, city=True)
    axis = np.linspace(-3200., 3200., 96)
    for value in R.OUTER_WORLD:
        assert np.isclose(np.abs(axis - value).min(), 0.)


def test_ground_shares_every_rim_vertex_and_fills_the_hole_without_overlap(monkeypatch):
    monkeypatch.setattr(ground, 'STEP', 24.)  # a coarse grid keeps the check quick; the seam logic is the same
    vertices, triangles = far_hills()
    rim, rim_world = R.rim_from_mesh(vertices, triangles)
    builder, info = ground.build(rim, rim_world)
    ox0, oy0, ox1, oy1 = R.OUTER
    area = 0.
    for face in builder.faces:
        pts = [builder.verts[i] for i in face]
        for k in range(1, len(pts) - 1):
            (ax, ay, _), (bx, by, _), (cx, cy, _) = pts[0], pts[k], pts[k + 1]
            cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            assert cross > -1e-9, 'a ground triangle faces down'
            area += cross / 2
    assert area == pytest.approx((ox1 - ox0) * (oy1 - oy0), rel=1e-9)
    edge = {(round(p[0], 4), round(p[1], 4), round(p[2], 4)) for p in builder.verts
            if min(abs(p[0] - ox0), abs(p[0] - ox1), abs(p[1] - oy0), abs(p[1] - oy1)) < 1e-6}
    expected = {(round(x - R.ORIGIN[0], 4), round(y - R.ORIGIN[1], 4), round(z, 4))
                for side in rim_world.values() for x, y, z in side}
    assert edge == expected
    assert info['rim_vertices'] == len(expected)
