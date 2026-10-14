"""Crater Park v2 primitives: every one a watertight solid with its profile's heights exact at the knots, its lips at
their angles and walls at least 0.30 m thick (craterpark/v2/primitives.py, solids.py, coping.py, rails.py)."""
import sys
import unittest
from pathlib import Path

import numpy as np

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
from craterpark import additions
from craterpark.v2 import dsl, solids
from craterpark.v2 import primitives as pr
from craterpark.v2.curves import Line


def knots_xy(profile):
    return profile.point(np.asarray(profile.knots))


class Common:
    def assertSolid(self, built):
        mesh = built.mesh
        self.assertGreater(solids.check_closed(mesh), 0)
        _, F = mesh.welded(solids.WELD)
        self.assertEqual(solids.edge_report(F), {'open': 0, 'nonmanifold': 0, 'flipped': 0})
        self.assertGreaterEqual(solids.thickness(mesh, dsl.SIDE), pr.MIN_WALL)
        self.assertTrue(np.allclose(np.linalg.norm(mesh.N, axis=1), 1))


class JoinedLineTests(unittest.TestCase, Common):
    def build(self):
        k, l = additions.RAMPS['pool_gap_kicker'][2], additions.RAMPS['pool_gap_landing'][2]
        self.launch, self.landing = pr.from_additions(*k), pr.from_additions(*l)
        self.path = Line((1144., 931.4), (1380., 902.6))
        self.gap = 100.2 - float(self.launch.end[0])
        return pr.jump_line(self.path, self.launch, self.landing, self.gap, 7., ground=-27.,
                            right=pr.Side('curb', .4, .3))

    def test_the_r4_gap_profiles_carry_over_exactly(self):
        # additions.profile's knots (horizontal runs) against the converted profile's: same x and y at every knot
        for name in ('pool_gap_kicker', 'pool_gap_landing', 'plaza_gap_kicker', 'half_pipe_roll_in'):
            y, deg, parts = additions.RAMPS[name][2]
            old = np.asarray(additions.profile(y, deg, parts, step=1e9))
            new = pr.from_additions(y, deg, parts)
            ends = knots_xy(new)
            self.assertTrue(np.allclose(ends[-1], old[-1, :2], atol=1e-9), name)
            self.assertAlmostEqual(new.end_degrees, old[-1, 2], places=9)

    def test_a_joined_line_is_a_closed_solid_with_exact_knots_lip_and_walls(self):
        built = self.build()
        self.assertSolid(built)
        mesh = built.mesh
        riding = mesh.where(role=dsl.RIDING)
        d = self.path.d; a = self.path.a
        along = (riding.V[:, [0, 2]] - a) @ d
        inside = np.abs((riding.V[:, [0, 2]] - a) @ np.array([-d[1], d[0]])) < 3.5 - 1e-6   # not the curb's cap
        for profile, start in ((self.launch, 0.), (self.landing, 100.2)):
            for x, y in knots_xy(profile):
                at = (np.abs(along - (start + x - profile.start[0])) < 1e-9) & inside
                self.assertTrue(at.any(), (x, y))
                self.assertTrue(np.allclose(riding.V[at, 1], y, atol=1e-9))
        air = next(c for c in built.checks if c['kind'] == 'air')
        self.assertAlmostEqual(air['lip_degrees'], 15., places=9)
        # the lip row's analytic normal is the 15 degree slope's, and the last chord within one step of it
        lip = np.abs(along - (self.launch.end[0] - self.launch.start[0])) < 1e-9
        n = riding.N[lip & inside]
        up = n @ np.array([0., 1., 0.]); fwd = n @ np.array([d[0], 0., d[1]])
        self.assertTrue(np.allclose(np.degrees(np.arctan2(-fwd, up)), 15., atol=1e-6))
        take = mesh.tag == dsl.TAG['takeoff']; land = mesh.tag == dsl.TAG['landing']
        self.assertTrue(take.any() and land.any())
        t = mesh.triangles()[take]
        self.assertLess(np.abs(t[:, :, 1].max() - air['lip'][1]), 1e-9)       # the takeoff ends at the lip
        # the curb's cap is flat and 0.4 m wide; the kicker's back under the lip is a visible wall
        side = mesh.where(role=dsl.SIDE)
        self.assertGreater(len(side.F), 0)
        self.assertAlmostEqual(solids.thickness(mesh, dsl.SIDE), .4, places=5)

    def test_a_curb_narrower_than_the_rule_is_refused(self):
        with self.assertRaises(ValueError):
            pr.Side('curb', .2, .3)


if __name__ == '__main__':
    unittest.main()
