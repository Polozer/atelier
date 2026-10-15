"""Crater Park v2 bowl complex (v2/bowls.py): sections, ports, and the built Crater Bowl as a closed solid."""
import math
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))

from craterpark.v2 import bowls, dsl, solids  # noqa: E402


class SectionTests(unittest.TestCase):
    def test_floor_ports_above_and_below_floor_have_finite_exact_endpoints(self):
        for delta in (-1.8, 1.8):
            section = bowls.flat_section(-6., -6. + delta, reach=3.)
            self.assertAlmostEqual(section.reach, 3., places=8)
            np.testing.assert_allclose(section.at([0., 1.]), [[3., -6.], [0., -6. + delta]], atol=1e-8)

    def test_wall_reaches_its_height_vertically(self):
        s = bowls.wall_section(-20.2, 10.2, 9., 1.2)
        self.assertAlmostEqual(s.height, 10.2, places=6)
        self.assertAlmostEqual(s.reach, 9., places=6)
        self.assertAlmostEqual(s.top_deg, 90., places=6)
        d, y = s.at(np.array([0., 1.])).T
        self.assertAlmostEqual(d[1], 0., places=9)
        self.assertAlmostEqual(y[0], -20.2, places=9)

    def test_low_wall_is_a_cut_transition(self):
        s = bowls.wall_section(0., 1., 3., .3)
        self.assertAlmostEqual(s.height, 1., places=6)
        self.assertLess(s.top_deg, 90.)

    def test_rollin_meets_line_slope_and_floor(self):
        s = bowls.rollin_section(-20.2, 8.6, 5., 70.)
        self.assertAlmostEqual(s.height, 8.6, places=4)
        self.assertAlmostEqual(s.top_deg, 5., places=6)

    def test_columns_keep_turn_per_column(self):
        s = bowls.wall_section(0., 10.2, 9., 1.2)
        n = s.columns_needed() + 1
        P = s.at(np.linspace(0, 1, n))
        a = np.degrees(np.arctan2(np.diff(P[:, 1]), -np.diff(P[:, 0])))
        self.assertLessEqual(np.abs(np.diff(a)).max(), 2.)


class PortTests(unittest.TestCase):
    def test_port_uses_built_end_instead_of_unbuilt_tail(self):
        bowl = SimpleNamespace(id='crater_bowl', rim_y=0., floor_y=-10.)
        line = SimpleNamespace(id='test', y0=20., path=SimpleNamespace(at=lambda s: (np.array([s, 0.]), np.array([1., 0.]))),
                               features=[SimpleNamespace(width=18., s0=0., s1=40., kind='run')])
        data = SimpleNamespace(BOWLS=[bowl], LINES=[line],
                               knots=lambda line, step: [(0., 20., -10.), (20., 0., -5.), (40., -20., 0.)],
                               build_stop=lambda line: 20.)
        port = bowls.ports(data)[0]
        self.assertEqual(port.kind, 'rim')
        self.assertEqual(port.y, 0.)
        self.assertEqual(port.slope_deg, -5.)
        np.testing.assert_allclose(port.point, [20., 0.])

    def test_every_line_has_a_port_row_across_its_width(self):
        for p in bowls.ports():
            self.assertIn(p.kind, ('floor', 'rim', 'mid', 'skip'))
            self.assertAlmostEqual(np.linalg.norm(p.row[0, [0, 2]] - p.row[-1, [0, 2]]), p.width, places=6)
            gaps = np.linalg.norm(np.diff(p.row, axis=0), axis=1)
            self.assertLessEqual(gaps.max(), dsl.RIDING_TESS.max_edge / math.sqrt(2) + 1e-9)


class CraterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.built = bowls.complex(only=('crater_bowl',))

    def test_closed_solid(self):
        P, F = self.built.mesh.welded(solids.WELD)
        r = solids.edge_report(F)
        self.assertEqual((r['open'], r['nonmanifold']), (0, 0), r)

    def test_feature_ids_and_palette(self):
        m = self.built.mesh
        self.assertLess(int(m.feature.max()), len(m.features))
        used = {dsl.MATERIALS[i] for i in np.unique(m.material)}
        self.assertFalse(used & set(bowls.FORBIDDEN))

    def test_ports_reach_the_lip(self):
        V = self.built.mesh.V
        for p in bowls.ports():
            if p.kind == 'skip':
                continue
            d = np.linalg.norm(V[None] - p.row[:, None], axis=-1).min(1)
            self.assertLess(d.max(), 1e-6, p.line)

    def test_coping_rails(self):
        self.assertTrue(self.built.rails)


if __name__ == '__main__':
    unittest.main()
