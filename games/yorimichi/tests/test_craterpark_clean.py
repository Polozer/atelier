"""Crater Park's clean geometry: overlaps cut out exactly, seams split, prism walls and reachable space (craterpark/clean.py)."""
from pathlib import Path
import sys
import unittest

import numpy as np

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
from craterpark import additions, clean, remesh  # noqa: E402


def area(t):
    return float(np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() / 2)


class CleanTests(unittest.TestCase):
    def test_subtract_leaves_exactly_the_part_outside(self):
        tri = np.array([[0., 0, 0], [2, 0, 0], [0, 0, 2]])
        over = np.array([[[0., .004, 0], [1, .004, 0], [0, .004, 1]]])        # 4 mm above, parallel
        parts = clean.subtract(tri, over)
        self.assertAlmostEqual(area(parts), 1.5, places=9)
        self.assertTrue(np.allclose(parts[:, :, 1], 0))                       # on the face's own plane
        n = np.cross(parts[:, 1] - parts[:, 0], parts[:, 2] - parts[:, 0])
        self.assertTrue((n[:, 1] * np.cross(tri[1] - tri[0], tri[2] - tri[0])[1] > 0).all())   # its winding

    def test_overlap_pairs_rank_the_lower_face_only(self):
        a = np.array([[0., 0, 0], [0, 0, 2], [2, 0, 0]]); b = a + [.2, .003, .2]; c = a + [0, .5, 0]
        pairs = clean.overlap_pairs(np.stack([a, b, c]), np.array([0, 1, 2]))
        self.assertEqual(pairs.tolist(), [[1, 0]])                            # b lies on a; c is 0.5 m above

    def test_a_vertex_on_an_edge_splits_both_faces(self):
        P = np.array([[0., 0, 0], [1, 0, 0], [0, 0, 1], [1, 0, 1]]); F = np.array([[0, 2, 1], [1, 2, 3]])
        P2, F2, added = clean.fix_tjunctions(P, F, np.array([[.5, 0, .5]]))
        self.assertEqual(added, 1)
        self.assertEqual(len(F2), 4)
        self.assertTrue(all((F2 == len(P)).any(1)))                            # every face uses the new vertex
        self.assertAlmostEqual(area(P2[F2]), 1., places=12)

    def test_a_split_vertex_takes_its_edges_attributes(self):
        # a vertical face (no use projecting it on the ground): the new vertex's UV is the edge's, a quarter along
        P = np.array([[0., 0, 0], [0, 1, 0], [0, 0, 1]]); F = np.array([[0, 1, 2]])
        UV = np.array([[0., 0], [4, 0], [0, 4]])
        P2, F2, added, UV2 = clean.fix_tjunctions(P, F, np.array([[0, .25, 0]]), attrs=UV)
        self.assertEqual((added, len(F2), len(UV2)), (1, 2, 4))
        self.assertTrue(np.allclose(UV2[3], [1, 0]))

    def test_a_point_in_a_cell_the_edge_only_grazes_is_found(self):
        # the edge crosses cell [1, 0, 0] for a sliver between samples (park-assist's case)
        a = np.array([[.01, .0099, .1]]); b = np.array([[1.01, 1.0099, .1]]); q = np.array([[.50005, .49995, .1]])
        e, p, t = clean._edge_hits(a, b, q, 1e-6)
        self.assertEqual((e.tolist(), p.tolist()), ([0], [0]))

    def test_a_cap_is_cut_exactly_where_a_ramp_rises_through_it(self):
        # a flat cap at y = .3 over a ramp rising 1 in 2 along x: only the part over the ramp (x < .6 + lift) goes
        cap = np.array([[0., .3, 0], [2, .3, 0], [0, .3, 2]])
        skin = np.array([[[0., 0, 0], [0, 0, 2], [2, 1, 0]], [[2., 1, 0], [0, 0, 2], [2, 1, 2]]])
        parts = clean.cut_under(cap, skin, lift=.002)
        self.assertAlmostEqual(area(parts), (2 - .604) ** 2 / 2, places=9)
        self.assertGreaterEqual(parts[:, :, 0].min(), .604 - 1e-12)

    def test_shared_prism_walls_are_inner(self):
        # two unit boxes side by side, each closed: the wall they share (both ways round) is inner, nothing else
        def box(x):
            v = np.array([[x, 0, 0], [x + 1, 0, 0], [x + 1, 0, 1], [x, 0, 1], [x, 1, 0], [x + 1, 1, 0], [x + 1, 1, 1], [x, 1, 1]], 'f8')
            q = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [2, 3, 7, 6], [1, 2, 6, 5], [3, 0, 4, 7]]
            return np.array([[v[a], v[b], v[c]] for a, b, c, d in q for a, b, c in ((a, b, c), (a, c, d))])
        T = np.concatenate([box(0.), box(1.)])
        inner = clean.inner_walls(T, np.zeros(len(T), 'i8'))
        self.assertEqual(int(inner.sum()), 4)
        self.assertTrue(np.allclose(T[inner][:, :, 0], 1.))

    def test_a_closed_box_is_unreachable(self):
        v = np.array([[0, 0, 0], [4, 0, 0], [4, 0, 4], [0, 0, 4], [0, 4, 0], [4, 4, 0], [4, 4, 4], [0, 4, 4]], 'f8')
        q = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [2, 3, 7, 6], [1, 2, 6, 5], [3, 0, 4, 7]]
        T = np.array([[v[a], v[b], v[c]] for a, b, c, d in q for a, b, c in ((a, b, c), (a, c, d))])
        grid, lo, h = clean.reachable(T, .5, log=lambda m: None)
        inside = np.floor((np.array([2., 2, 2]) - lo) / h).astype(int)
        outside = np.floor((np.array([-.7, 2, 2]) - lo) / h).astype(int)
        self.assertFalse(grid[tuple(inside)]); self.assertTrue(grid[tuple(outside)])


class RibbonTests(unittest.TestCase):
    def test_a_straight_run_has_a_straight_outline_square_ends_and_its_profile(self):
        line = np.stack([np.linspace(0, 10, 21), np.zeros(21), np.zeros(21)], 1)
        width, wall, radius = 4., 1., 2.
        v, f, uv = additions.run_mesh(line, np.zeros(21), width, wall, radius)
        v = v.astype('f8')
        reach = np.sqrt(radius ** 2 - (radius - wall) ** 2); edge = width / 2 + reach + additions.SNAKE_LIP
        self.assertAlmostEqual(np.abs(v[:, 2]).max(), edge, places=5)            # the outline: the run's edge
        self.assertAlmostEqual(v[:, 0].min(), 0., places=5); self.assertAlmostEqual(v[:, 0].max(), 10., places=5)
        e = np.clip(np.abs(v[:, 2]) - width / 2, 0, reach)
        self.assertLess(np.abs(v[:, 1] - (radius - np.sqrt(radius ** 2 - e ** 2))).max(), 1e-5)   # on the profile
        key, face, inv, cnt = remesh.edges_of(f)
        self.assertTrue((cnt <= 2).all())                                            # a clean sheet
        n = np.cross(v[f][:, 1] - v[f][:, 0], v[f][:, 2] - v[f][:, 0])
        self.assertTrue((n[:, 1] > 0).all())                                         # facing up


class RemeshTests(unittest.TestCase):
    def test_chains_and_simplification(self):
        # a straight open edge of 11 points simplifies to its ends; a bend over the tolerance stays
        P = np.stack([np.linspace(0, 1, 11), np.zeros(11), np.zeros(11)], 1)
        self.assertEqual(remesh.dp_chain(np.arange(11), P, None, .001, None).tolist(), [0, 10])
        P[5, 1] = .01
        self.assertEqual(remesh.dp_chain(np.arange(11), P, None, .001, None).tolist(), [0, 4, 5, 6, 10])

    def test_a_patch_that_leaves_a_vertex_uncovered_fails_closed(self):
        # a triangulation that never reaches the fourth vertex: never certified (park-assist's case)
        P2 = np.array([[0., 0], [1, 0], [0, 1], [2, 2]]); H = np.zeros(4)
        real = remesh.cdt
        remesh.cdt = lambda Q, e: np.array([[0, 1, 2]])
        try:
            T = remesh.remesh_patch(P2, H, None, .003, None, [0, 1, 2], [(0, 1), (1, 2), (2, 0)], np.arange(4),
                                    lambda c: np.ones(len(c), bool), max_rounds=3)
        finally:
            remesh.cdt = real
        self.assertIsNone(T)

    def test_planar_patches_join_coplanar_faces_only(self):
        P = np.array([[0., 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1], [2, 0, 0], [2, .5, 1]])
        F = np.array([[0, 2, 1], [0, 3, 2], [1, 2, 4], [2, 5, 4]])
        lab = remesh.planar_patches(P, F)
        self.assertEqual(lab[0], lab[1]); self.assertEqual(lab[1], lab[2]); self.assertNotEqual(lab[2], lab[3])


if __name__ == '__main__':
    unittest.main()
