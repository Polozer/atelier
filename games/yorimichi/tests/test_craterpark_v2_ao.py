"""Crater Park v2: the ambient-occlusion bake (craterpark/v2/ao.py)."""
from pathlib import Path
import sys
import types
import unittest

import numpy as np

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions')); sys.path.insert(0, str(GAME / 'world'))
from craterpark.v2 import ao  # noqa: E402
from craterpark.v2.dsl import Mesh  # noqa: E402


def box(x0, z0, x1, z1, h):
    """A closed box standing on y = 0 (12 outward faces)."""
    v = np.array([[x0, 0, z0], [x1, 0, z0], [x1, 0, z1], [x0, 0, z1], [x0, h, z0], [x1, h, z0], [x1, h, z1], [x0, h, z1]], 'f8')
    q = [[0, 1, 2, 3], [4, 7, 6, 5], [0, 4, 5, 1], [2, 6, 7, 3], [1, 5, 6, 2], [3, 7, 4, 0]]
    return v, np.array([t for a, b, c, d in q for t in ((a, b, c), (a, c, d))])


def ground(n=24, size=12.):
    x = np.linspace(-size, size, n + 1)
    X, Z = np.meshgrid(x, x)
    V = np.stack([X.ravel(), np.zeros(X.size), Z.ravel()], 1)
    i = np.arange(n * n).reshape(n, n); i = i + i // n                      # the lower-left corner of each cell
    F = np.concatenate([np.stack([i, i + n + 1, i + 1], -1).reshape(-1, 3), np.stack([i + 1, i + n + 1, i + n + 2], -1).reshape(-1, 3)])
    return V, F


def scene():
    gv, gf = ground(); bv, bf = box(-2, -2, 2, 2, 3)
    return np.concatenate([gv, bv]), np.concatenate([gf, bf + len(gv)])


class BakeTests(unittest.TestCase):
    def test_identical_to_r4s_bake(self):
        for m in ('bpy', 'bmesh'):
            sys.modules.setdefault(m, types.ModuleType(m))
        from craterpark import build as r4
        V, F = scene()
        self.assertTrue(np.array_equal(ao.bake(V, F), r4.ambient_occlusion([(V, F)])[0]))

    def test_open_ground_is_open_and_a_wall_foot_is_darker(self):
        V, F = scene(); a = ao.bake(V, F)
        far = np.flatnonzero((np.abs(V[:, 0]) > 11) & (np.abs(V[:, 2]) > 11) & (V[:, 1] == 0))
        foot = np.flatnonzero((np.abs(V[:, 0] - 3) < 1e-9) & (np.abs(V[:, 2]) < 1e-9) & (V[:, 1] == 0))
        self.assertGreater(a[far].min(), .9)
        self.assertLess(a[foot].max(), a[far].min() - .05)
        self.assertTrue(((a >= 0) & (a <= 1)).all())

    def test_deterministic(self):
        V, F = scene()
        self.assertTrue(np.array_equal(ao.bake(V, F), ao.bake(V, F)))


class MeshTests(unittest.TestCase):
    def test_a_uv_seam_gets_one_value_and_a_crease_two(self):
        # ground split along x = 0 into two UV charts (twins with one normal), and a box whose vertices are split
        # per face (creases: twins with different normals)
        gv, gf = ground()
        seam = np.flatnonzero(np.abs(gv[:, 0]) < 1e-9)
        twin = len(gv) + np.arange(len(seam))
        gv2 = np.concatenate([gv, gv[seam]]); remap = np.arange(len(gv)); remap[seam] = twin
        right = gv[gf].mean(1)[:, 0] > 0
        gf2 = np.where(right[:, None], remap[gf], gf)
        g = Mesh.part(gv2, gf2, role='riding', feature='deck')
        bv, bf = box(-2, -2, 2, 2, 3)
        T = bv[bf]; b = Mesh.part(T.reshape(-1, 3), np.arange(3 * len(bf)).reshape(-1, 3), role='side', feature='block')
        m = Mesh.concat([g, b])
        m.N[:len(gv2)] = [0., 1., 0.]                                   # the ground's analytic normal
        ao.bake_mesh(m)
        self.assertTrue(np.array_equal(m.AO[seam], m.AO[twin]))         # a seam: one value
        corner = np.flatnonzero(np.linalg.norm(m.V - [2., 3., 2.], axis=1) < 1e-9)
        self.assertEqual(len(corner), 5)                                # the box's top corner, on 5 triangles
        self.assertGreater(np.ptp(m.AO[corner]), 1e-3)                  # a crease: each side its own

    def test_only_drawn_roles_are_baked(self):
        gv, gf = ground(); bv, bf = box(-2, -2, 2, 2, 3)
        m = Mesh.concat([Mesh.part(gv, gf, role='riding'), Mesh.part(bv, bf, role='base')])
        ao.bake_mesh(m, drawn=('riding',))
        self.assertTrue((m.AO[len(gv):] == 1).all())
        self.assertLess(m.AO[:len(gv)].min(), .99)                      # the base still occludes the ground


if __name__ == '__main__':
    unittest.main()
