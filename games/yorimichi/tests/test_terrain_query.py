"""Owned query behavior against frozen production cases and explicit surfaces."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'world'))
from terrain_product import Mesh  # noqa: E402
from terrain_query import Surface  # noqa: E402


def surface(vertices, polygons, **kwargs):
    return Surface(Mesh.from_polygons(vertices, polygons), owner='fixture', stage='final', **kwargs)


def test_every_frozen_r8_query_including_the_portal_hole():
    cases = json.loads(Path(__file__).with_name('fixtures').joinpath('terrain-r8.json').read_text())['cases']
    for name, case in cases.items():
        mesh = Mesh.from_polygons(case['vertices'], case['triangles'])
        before = mesh.vertices.tobytes(), mesh.indices.tobytes(), mesh.offsets.tobytes()
        index = Surface(mesh, owner=name, stage='final')
        points = np.asarray(case['queries'])
        result = index.upper(*points.T, require=False)
        expected = np.array([np.nan if value is None else value for value in case['heights']])
        np.testing.assert_array_equal(result.covered, np.isfinite(expected))
        np.testing.assert_allclose(result.height, expected, atol=1e-12, rtol=0, equal_nan=True)
        assert before == (mesh.vertices.tobytes(), mesh.indices.tobytes(), mesh.offsets.tobytes())
        covered = result.covered
        triangles = mesh.vertices[mesh.triangles()[result.face_ids[covered]]]
        reconstructed = (result.barycentric[covered, :, None]*triangles).sum(1)
        np.testing.assert_allclose(reconstructed[:, :2], points[covered], atol=1e-12, rtol=0)
        np.testing.assert_allclose(reconstructed[:, 2], result.height[covered], atol=1e-12, rtol=0)
        np.testing.assert_allclose(np.linalg.norm(result.normal[covered], axis=1), 1., atol=1e-15)


def test_parent_kink_face_identity_normals_and_shared_edge_tie():
    index = surface([[0, 0, 0], [1, 0, 0], [1, 1, 4], [0, 1, 0]], [[0, 1, 2, 3]], cell=.5)
    result = index.upper([.75, .25, .5], [.25, .75, .5])
    np.testing.assert_array_equal(result.face_ids, [0, 1, 0])
    np.testing.assert_allclose(result.height, [1, 1, 2], atol=0, rtol=0)
    np.testing.assert_allclose(result.normal[:2], np.array([[0, -4, 1], [-4, 0, 1]])/np.sqrt(17))
    hits = index.intersections(.5, .5)
    assert hits.owner == 'fixture' and hits.stage == 'final' and hits.query_shape == ()
    np.testing.assert_array_equal(hits.face_ids, [0, 1])
    np.testing.assert_array_equal(hits.query_ids, [0, 0])
    assert not hits.height.flags.writeable and not result.barycentric.flags.writeable


def test_all_overlaps_are_explicit_upper_preserves_winding_and_original_ids():
    # Face 0 is vertical; face 3 is degenerate. The upper face has downward
    # winding, which is reported rather than silently reoriented or discarded.
    index = surface([[0, 0, 0], [0, 0, 2], [0, 1, 0],
                     [0, 0, 2], [2, 0, 2], [0, 2, 2],
                     [0, 0, 5], [0, 2, 5], [2, 0, 5]],
                    [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 0, 0]])
    hits = index.intersections(.25, .25)
    np.testing.assert_array_equal(hits.face_ids, [1, 2])
    np.testing.assert_array_equal(hits.height, [2, 5])
    assert index.upper(.25, .25).face_ids == 2
    np.testing.assert_array_equal(index.upper(.25, .25).normal, [0, 0, -1])
    other = Surface(Mesh.from_polygons([[0, 0, 90], [2, 0, 90], [0, 2, 90]], [[0, 1, 2]]),
                    owner='another-owner', stage='natural')
    assert other.upper(.25, .25).height == 90
    assert index.upper(.25, .25).height == 5  # Owners are never combined.


def test_missing_support_broadcast_empty_and_chunked_queries():
    index = surface([[0, 0, 0], [1, 0, 0], [1, 1, 4], [0, 1, 0]], [[0, 1, 2, 3]])
    index.MAX_PAIRS = 2  # Force multiple chunks without changing geometry.
    x, y = np.array([[.25], [.75]]), np.array([.125, .5, .875])
    result = index.upper(x, y)
    assert result.height.shape == (2, 3) and result.normal.shape == (2, 3, 3)
    np.testing.assert_allclose(result.height, 4*np.minimum(x, y))
    hits = index.intersections(x, y)
    assert list(zip(hits.query_ids, hits.face_ids)) == sorted(zip(hits.query_ids, hits.face_ids))
    with pytest.raises(ValueError, match='no triangle support'):
        index.upper([.5, 3], [.5, 3])
    result = index.upper([.5, 3, 1e300], [.5, 3, 1e300], require=False)
    np.testing.assert_array_equal(result.covered, [True, False, False])
    np.testing.assert_array_equal(result.face_ids, [0, -1, -1])
    assert np.isnan(result.barycentric[1:]).all() and np.isnan(result.normal[1:]).all()
    empty = surface([], [])
    assert empty.intersections(0, 0).face_ids.size == 0
    assert empty.upper([], []).height.shape == (0,)


@pytest.mark.parametrize('cell', [0, -1, float('nan'), float('inf'), True])
def test_invalid_index_configuration_fails(cell):
    with pytest.raises(ValueError, match='cell width'):
        surface([], [], cell=cell)


def test_nonfinite_queries_and_missing_owner_stage_fail():
    index = surface([], [])
    with pytest.raises(ValueError, match='finite'):
        index.intersections(float('nan'), 0)
    for identity in [dict(owner='', stage='final'), dict(owner='terrain', stage='unknown')]:
        with pytest.raises(ValueError, match='owner and stage'):
            Surface(Mesh.from_polygons([], []), **identity)


def test_finite_large_triangle_still_has_a_unit_normal():
    index = surface([[0, 0, 0], [1e150, 0, 0], [0, 1e150, 0]], [[0, 1, 2]], cell=1e151)
    result = index.upper(1e149, 1e149)
    np.testing.assert_array_equal(result.normal, [0, 0, 1])
