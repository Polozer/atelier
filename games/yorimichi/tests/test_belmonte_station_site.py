"""The Belmonte station's site (world/train/station_site.py) and what it asks of the ground and the planting, on a
straight stand-in for the line's last kilometre ending at the site. A line that ends elsewhere (the committed riverside
terminus, made-up lines) gets nothing: its earthworks, corridor and route ground stay as they were."""
import json
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))

import yori  # noqa: E402,F401
from train import corridor as C, earthworks as E, station_site as S  # noqa: E402

END = np.array([823.4, 4689.3])
RAIL = 207.6
HEADING = math.radians(140.)


def rows(end=END):
    t = np.array([math.cos(HEADING), math.sin(HEADING)])
    return [{'s': float(s), 'x': float(end[0] + (s - 1000.) * t[0]), 'y': float(end[1] + (s - 1000.) * t[1]),
             'rail_z': RAIL, 'ground_z': RAIL + 4., 'class': 'cutting'} for s in range(0, 1010, 10)]


def committed_route():
    return json.loads(C.LINE.read_text())


class Site(unittest.TestCase):
    def test_only_a_line_ending_at_the_site_gets_a_station(self):
        self.assertIsNotNone(E.Line({'samples': rows()}).station())
        self.assertIsNone(E.Line({'samples': rows(END + [2000., 0.])}).station())

    def test_the_committed_line_is_untouched(self):
        ln = E.Line(committed_route())
        self.assertIsNone(ln.station())
        self.assertIsNone(ln.overbridge())
        self.assertIsNone(C.Corridor(committed_route()).site)

    def test_frame(self):
        site = E.Line({'samples': rows()}).station()
        self.assertTrue(np.allclose(site.origin, END))
        a, u = site.local(*site.world(np.array([-30.]), np.array([5.]))[0])
        self.assertAlmostEqual(float(a), -30.)
        self.assertAlmostEqual(float(u), 5.)
        self.assertTrue(S.inside(site, *site.world(np.array([-100.]), np.array([0.]))[0]))
        self.assertFalse(S.inside(site, *site.world(np.array([-100.]), np.array([40.]))[0]))

    def test_sheds_take_the_scaled_train(self):
        self.assertGreaterEqual(-S.SHEDS[0], S.TRAIN_LENGTH + 10.)
        self.assertGreaterEqual(S.EDGE, 1.80 * S.TRAIN_SCALE)


class Ground(unittest.TestCase):
    ln = E.Line({'samples': rows()})

    def carve(self, a, u, z):
        x, y = self.ln.station().world(np.array([a]), np.array([u]))[0]
        return float(E.carve(np.array([x]), np.array([y]), np.array([z]), self.ln)[0])

    def test_sheds_and_headhouse_at_the_formation(self):
        for a, u in ((-100., -30.), (-20., 8.), (10., -50.)):
            self.assertAlmostEqual(self.carve(a, u, RAIL + 5.), RAIL + S.FORMATION, delta=.05)

    def test_forecourt_at_street_level(self):
        self.assertAlmostEqual(self.carve(36., S.AXIS_U, RAIL + 9.), RAIL + S.STREET, delta=.05)    # cut
        self.assertAlmostEqual(self.carve(36., S.AXIS_U, RAIL + 5.), RAIL + S.STREET, delta=.05)    # fill

    def test_ground_stands_against_the_walls(self):
        # two metres and a half outside the sheds' wall the ground keeps its natural height
        self.assertAlmostEqual(self.carve(-80., S.SHEDS[3] + 2.5, RAIL + 4.), RAIL + 4., delta=.05)

    def test_the_road_keeps_its_ground_at_the_overbridge(self):
        s = self.ln.overbridge()
        self.assertIsNotNone(s)
        for u in (-9., 9.):     # behind the retaining walls, on the road's line
            a = s - self.ln.length + u / math.tan(math.radians(140. - 17.5))
            self.assertAlmostEqual(self.carve(a, u, RAIL + 8.6), RAIL + 8.6, delta=.1)

    def test_far_ground_untouched(self):
        self.assertEqual(self.carve(-100., 120., RAIL + 4.), RAIL + 4.)


class Planting(unittest.TestCase):
    route = {'samples': rows()}

    def test_no_plants_on_the_station(self):
        c = C.Corridor(self.route)
        site = c.site
        on = site.world(np.array([-60., 36., -60.]), np.array([-30., S.AXIS_U, 60.]))
        margin = c.station_margin(on[:, 0], on[:, 1])
        self.assertLess(margin[0], 0.)
        self.assertLess(margin[1], 0.)
        self.assertGreater(margin[2], 0.)
        for name in ('Tree_Tuscan_Test', C.SHRUBS[0] if isinstance(C.SHRUBS, tuple) else C.SHRUBS):
            with patch.object(E, 'line', return_value=E.Line(self.route)):
                keep, _ = C.settle(name, on[:, 0], on[:, 1], np.full(3, RAIL + 4.), c)
            self.assertEqual(keep.tolist(), [False, False, True], name)

    def test_committed_corridor_has_no_station_margin(self):
        c = C.Corridor(committed_route())
        self.assertTrue(np.isinf(c.station_margin(np.array([900.]), np.array([4625.]))).all())


class RouteGround(unittest.TestCase):
    def test_natural_terrain_is_the_committed_one_until_carved(self):
        from belmonte import source
        carved = [e for e in source.manifest()['meshes'] if e.get('railway_carved')]
        if carved:
            self.skipTest('valley tiles already carved')
        x, y = np.array([0., 300., -400.]), np.array([0., 200., 500.])
        self.assertTrue(np.array_equal(source.terrain(natural=True).height(x, y), source.terrain().height(x, y)))


class Tool(unittest.TestCase):
    def test_refuses_a_line_without_station(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
        import belmonte_station_terrain as tool
        if E.line() is None or E.line().station() is not None:
            self.skipTest('the committed line ends at the station')
        with self.assertRaises(SystemExit):
            tool.main(['--dry-run'])


if __name__ == '__main__':
    unittest.main()
