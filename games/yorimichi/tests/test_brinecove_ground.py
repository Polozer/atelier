"""Brinecove's ground closes exactly onto the far hills' hole, and the far hills hide exactly that hole."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world'))
import yori  # noqa: E402,F401
import farhills_surface  # noqa: E402
from brinecove import ground, region as R  # noqa: E402
from brinecove.geom import distinct_corners  # noqa: E402


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


def test_welding_unshared_far_hills_corners_keeps_one_rim_vertex_per_position(monkeypatch):
    """The FarHills final product keeps each tile's corners separate. Unwelded, the rim repeats every shared corner
    and the zipper emits zero-length triangles (Unreal dropped 102 of 1050 on one seabed tile)."""
    monkeypatch.setattr(ground, 'STEP', 24.)
    vertices, triangles = far_hills()
    vertices = np.asarray(vertices)
    split = np.asarray([vertices[i] for t in triangles for i in t])  # every triangle owns its corners
    loose = np.arange(len(split)).reshape(-1, 3)
    raw = R.rim_from_mesh(split.tolist(), loose.tolist())[1]
    assert sum(len(side) for side in raw.values()) > sum(len(side) for side in R.rim_from_mesh(vertices, triangles)[1].values())
    welded, welded_triangles = ground.weld(split, loose)
    rim, rim_world = R.rim_from_mesh(welded.tolist(), welded_triangles.tolist())
    expected = R.rim_from_mesh(vertices, triangles)[1]
    assert {k: sorted(v) for k, v in rim_world.items()} == {k: sorted(v) for k, v in expected.items()}
    builder, _ = ground.build(rim, rim_world)
    for face in builder.faces:
        pts = [builder.verts[i] for i in face]
        assert min(math.dist(pts[k], pts[k - 1]) for k in range(len(pts))) > 1e-6, 'zero-length ground edge'


def test_distinct_corners_drops_repeats_and_faces_without_area():
    quad = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    assert distinct_corners(quad) == [0, 1, 2, 3]
    assert distinct_corners([(0, 0, 0), (1, 0, 0), (1, 1, 0), (1, 1, 0)]) == [0, 1, 2]  # a cone's apex quad
    assert distinct_corners([(0, 0, 0), (1, 0, 0), (2, 0, 0)]) is None  # collinear
    assert distinct_corners([(0, 0, 0), (0, 0, 0), (1, 0, 0), (1, 0, 0)]) is None
    assert distinct_corners([(0, 0, 0), (0.01, 0, 0), (0, 0.01, 0)]) == [0, 1, 2]  # small trim stays
