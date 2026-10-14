"""No tree or bush where the Belmonte train runs (train/corridor.py), over every planted source along route v3:
Hidamari's city.json, Belmonte's runtime.json and the world's world.json."""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))

import yori  # noqa: E402
from train import corridor as C  # noqa: E402


def planted():
    """{source: {name: array of (x, y)}} for the built sources that exist."""
    out = {}
    city = yori.OUT / 'hidamari' / 'city.json'
    if city.exists():
        out['hidamari'] = {n: np.asarray(v, float).reshape(len(v), -1)[:, :2]
                           for n, v in json.loads(city.read_text())['instances'].items() if v}
    world = yori.OUT / 'world.json'
    if world.exists():
        out['world'] = {n: np.asarray(v, float).reshape(len(v), -1)[:, :2]
                        for n, v in json.loads(world.read_text()).get('instances', {}).items() if v}
    runtime = yori.OUT / 'belmonte' / 'runtime.json'
    if runtime.exists():
        from belmonte import layout as BM
        rows = {}
        for g in json.loads(runtime.read_text())['groups']:
            if not g.get('plant'):
                continue
            name = g['asset'].split('.')[-1]
            xy = [(t['translation_cm'][0] / 100 + BM.ORIGIN[0], -t['translation_cm'][1] / 100 + BM.ORIGIN[1]) for t in g['transforms']]
            if xy:
                rows[name] = np.concatenate([rows[name], xy]) if name in rows else np.asarray(xy, float)
        out['belmonte'] = rows
    return out


class Corridor(unittest.TestCase):
    def test_tunnels_stay_wooded_and_earthworks_widen_it(self):
        self.assertIsNone(C.half_width({'class': 'tunnel', 'rail_z': 0, 'ground_z': 40}))
        self.assertEqual(C.half_width({'class': 'cutting', 'rail_z': 10, 'ground_z': 10.5}), C.HALF_WIDTH)
        self.assertGreater(C.half_width({'class': 'embankment', 'rail_z': 20, 'ground_z': 12}), C.HALF_WIDTH)
        self.assertEqual(C.half_width({'class': 'deep cutting', 'rail_z': 0, 'ground_z': 80}), C.MAX_HALF_WIDTH)

    def test_a_point_on_the_line_is_blocked_and_one_far_away_is_not(self):
        route = {'samples': [{'s': s, 'x': s, 'y': 0., 'rail_z': 0., 'ground_z': 0., 'class': 'embankment' if s < 100 else 'tunnel'}
                             for s in range(0, 210, 10)]}
        c = C.Corridor(route)
        self.assertEqual(c.blocked([50., 50., 50., 150.], [0., 9., 30., 0.]).tolist(), [True, True, False, False])

    def test_no_route_means_no_change(self):
        self.assertIsNone(C.load(Path('/nonexistent/route.json')))
        self.assertTrue(C.keep([0.], [0.]).all() or C.load() is not None)


class Clearance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.line = C.load()
        if cls.line is None:
            raise unittest.SkipTest('route not built (atelier build yorimichi world.belmonte_train_route)')
        cls.sources = planted()
        if not cls.sources:
            raise unittest.SkipTest('no planted source built')

    def test_no_tree_or_bush_stands_where_the_train_runs(self):
        for source, names in self.sources.items():
            for name, xy in names.items():
                if not name.replace('Tree_Tuscan', 'Tree').startswith(C.PLANTS) or not len(xy):
                    continue
                with self.subTest(source=source, plant=name):
                    bad = self.line.blocked(xy[:, 0], xy[:, 1])
                    if bad.any():
                        self.fail(f'{int(bad.sum())} in the corridor, e.g. {xy[bad][0].round(1).tolist()}')


if __name__ == '__main__':
    unittest.main()
