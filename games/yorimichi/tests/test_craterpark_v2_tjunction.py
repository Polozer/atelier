"""Crater Park v2: the T-junction validator and its split (craterpark/v2/tjunction.py)."""
from pathlib import Path
import sys
import unittest

import numpy as np

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
from craterpark.v2 import tjunction as tj  # noqa: E402
from craterpark.v2.dsl import Mesh  # noqa: E402


def area(t):
    return float(np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() / 2)


def strip(x0, x1, n, z0=0., z1=1.):
    """A flat strip from x0 to x1 (n columns) between z0 and z1, facing up."""
    x = np.linspace(x0, x1, n + 1)
    V = np.concatenate([np.stack([x, np.zeros_like(x), np.full_like(x, z0)], 1),
                        np.stack([x, np.zeros_like(x), np.full_like(x, z1)], 1)])
    m = n + 1
    F = np.array([f for i in range(n) for f in ([i, m + i, i + 1], [i + 1, m + i, m + i + 1])])
    return V, F


class FindTests(unittest.TestCase):
    def test_a_conforming_seam_has_none(self):
        # two features side by side sharing the seam's samples
        a = Mesh.part(*strip(0, 2, 4), feature='deck'); b = Mesh.part(*strip(0, 2, 4, 1., 2.), feature='ramp')
        self.assertEqual(tj.check(Mesh.concat([a, b]))['tjunctions'], 0)

    def test_a_seam_sampled_differently_on_each_side_is_found(self):
        # the second strip samples the seam z = 1 at 8 columns, the first at 4: 4 extra points lie inside open edges
        a = Mesh.part(*strip(0, 2, 4), feature='deck'); b = Mesh.part(*strip(0, 2, 8, 1., 2.), feature='ramp')
        r = tj.check(Mesh.concat([a, b]))
        self.assertEqual(r['tjunctions'], 4)
        self.assertEqual(r['examples'][0]['feature'], 'deck')            # the face with the crack is the coarse side's
        self.assertLess(r['max_distance'], 1e-9)

    def test_a_crease_is_not_a_tjunction(self):
        # a crease splits vertices (one per side, each its own normal): welded, it conforms
        V, F = strip(0, 2, 4)
        V2 = V.copy(); V2[:, 1] = V2[:, 2] - 1.; V2[:, 2] = 1.                      # a wall rising from the strip's far edge
        wall = Mesh.part(V2, F[:, [0, 2, 1]], role='side', feature='wall')
        self.assertEqual(tj.check(Mesh.concat([Mesh.part(V, F, feature='deck'), wall]))['tjunctions'], 0)

    def test_a_point_on_a_shared_edge_is_not_one(self):
        P = np.array([[0., 0, 0], [1, 0, 0], [0, 0, 1], [1, 0, 1], [.5, 0, .5]]); F = np.array([[0, 2, 1], [1, 2, 3]])
        self.assertEqual(len(tj.find(P, F)[0]), 0)

    def test_a_slivers_own_apex_is_not_one(self):
        P = np.array([[0., 0, 0], [2, 0, 1e-4], [1, 0, 2e-4]]); F = np.array([[0, 1, 2]])
        self.assertEqual(len(tj.find(P, F)[0]), 0)


class SplitTests(unittest.TestCase):
    """The safety net: the clean-geometry branch's proven cases."""

    def test_points_on_every_edge_split_without_new_vertices(self):
        P = np.array([[0., 0, 0], [0, 0, 2], [2, 0, 0], [0, 0, 1], [1, 0, 1], [1, 0, 0]]); F = np.array([[0, 1, 2]])
        P2, F2, added = tj.fix_tjunctions(P, F)
        self.assertEqual((added, len(P2), len(F2)), (0, 6, 4))
        self.assertAlmostEqual(area(P2[F2]), 2., places=12)
        n = np.cross(P2[F2][:, 1] - P2[F2][:, 0], P2[F2][:, 2] - P2[F2][:, 0])
        self.assertTrue((n[:, 1] > 0).all())

    def test_a_sliver_fan_keeps_its_area_and_winding(self):
        rng = np.random.default_rng(3)
        T = np.array([[o, o + [2, 0, 1e-4], o + [1, 0, 2e-4]] for o in (np.array([i * 3., 0, 0]) for i in range(200))])
        P = T.reshape(-1, 3); F = np.arange(len(P)).reshape(-1, 3)
        pts = np.concatenate([T[:, 0] + rng.uniform(.1, .9, (200, 1)) * (T[:, 1] - T[:, 0]),
                              T[:, 1] + rng.uniform(.1, .9, (200, 1)) * (T[:, 2] - T[:, 1])])
        P2, F2, added = tj.fix_tjunctions(np.concatenate([P, pts]), F, tol=5e-4)
        self.assertEqual(added, 0)
        self.assertAlmostEqual(area(P2[F2]), area(T), places=12)
        n = np.cross(P2[F2][:, 1] - P2[F2][:, 0], P2[F2][:, 2] - P2[F2][:, 0])
        self.assertTrue((n[:, 1] < 0).all())

    def test_a_uv_seam_keeps_a_vertex_per_chart(self):
        P = np.array([[0., 0, 0], [0, 0, 1], [1, 0, 0], [1, 0, 0], [0, 0, 1], [1, 0, 1]])
        F = np.array([[0, 1, 2], [3, 4, 5]])
        UV = np.array([[0., 0], [0, 1], [1, 0], [11, 0], [10, 1], [11, 1]])
        P2, F2, added, UV2 = tj.fix_tjunctions(P, F, np.array([[.5, 0, .5]]), attrs=UV)
        self.assertEqual((added, len(F2)), (2, 4))
        self.assertEqual(sorted(UV2[6:].tolist()), [[.5, .5], [10.5, .5]])

    def test_a_split_seam_then_finds_none(self):
        a = Mesh.part(*strip(0, 2, 4), feature='deck'); b = Mesh.part(*strip(0, 2, 8, 1., 2.), feature='ramp')
        P, F = Mesh.concat([a, b]).welded()
        P2, F2, _ = tj.fix_tjunctions(P, F, tol=tj.TOL)
        self.assertEqual(len(tj.find(P2, F2)[0]), 0)
        self.assertAlmostEqual(area(P2[F2]), 4., places=12)


if __name__ == '__main__':
    unittest.main()
