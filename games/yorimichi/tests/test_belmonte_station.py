"""The Belmonte station (world/train/station.py, station_site.py): its meshes within budget and closed the right way
out, its pieces at the line's end, and the ground the earthworks give it, on a straight stand-in for the line's last
kilometre (the real alignment needs the route study)."""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))

import yori  # noqa: E402,F401
from train import earthworks as E, station as ST, station_site as S, track as T  # noqa: E402

END = np.array([823.4, 4689.3])
RAIL = 207.6
HEADING = math.radians(140.)


class Straight:
    """The last kilometre of the line, straight and level into the station (track.Line's frame())."""
    length = 7661.

    def frame(self, s):
        t = np.array([math.cos(HEADING), math.sin(HEADING)])
        scalar = np.ndim(s) == 0
        s = np.atleast_1d(np.asarray(s, float))
        xy = END + (s - self.length)[:, None] * t
        p = np.c_[xy, np.full(len(s), RAIL)]
        tt = np.tile([t[0], t[1], 0.], (len(s), 1))
        n = np.tile([-t[1], t[0], 0.], (len(s), 1))
        return (p[0], tt[0], n[0]) if scalar else (p, tt, n)


def earthworks_line():
    t = np.array([math.cos(HEADING), math.sin(HEADING)])
    samples = [{'s': float(s), 'x': float(END[0] + (s - 1000.) * t[0]), 'y': float(END[1] + (s - 1000.) * t[1]),
                'rail_z': RAIL, 'ground_z': RAIL + 4., 'class': 'cutting'} for s in range(0, 1010, 10)]
    return E.Line({'samples': samples})


def volume(mesh):
    v = np.asarray(mesh.verts)
    return sum(v[f[0]] @ np.cross(v[f[k]], v[f[k + 1]]) / 6 for f in mesh.faces for k in range(1, len(f) - 1))


class Meshes(unittest.TestCase):
    meshes, doc = ST.layout(Straight())

    def test_budgets(self):
        for name, lods in self.meshes.items():
            budget = T.BUDGETS[name]
            self.assertEqual(len(lods), len(budget), name)
            for k, (mesh, limit) in enumerate(zip(lods, budget)):
                self.assertLessEqual(mesh.triangles, limit, f'{name} LOD{k}')
            self.assertGreater(lods[0].triangles, lods[-1].triangles, name)

    def test_helpers_face_outward(self):
        for build in (lambda m: ST.box(m, 0, 2, 0, 3, 0, 4, 'x'), lambda m: ST.prism_a(m, [(0, 0), (2, 0), (1, 2)], 0, 3, 'x'),
                      lambda m: ST.prism_u(m, [(0, 0), (2, 0), (1, 2)], 0, 3, 'x'),
                      lambda m: ST.rib(m, ST.arch(0, 5, 0, 4, 8), 0, .5, .4, 'x')):
            mesh = T.Mesh()
            build(mesh)
            self.assertGreater(volume(mesh), 0.)

    def test_pieces_at_the_line_end(self):
        rows = {r['name']: r for r in self.doc['pieces']}
        self.assertEqual(set(rows), set(self.meshes))
        self.assertTrue(np.allclose(rows['SM_ST_Sheds']['origin'], [*END, RAIL]))
        self.assertAlmostEqual(rows['SM_ST_Overbridge']['chainage'], Straight.length - 229., delta=3.)
        self.assertAlmostEqual(self.doc['levels']['street'], RAIL + S.STREET, places=3)

    def test_platforms_clear_the_coaches(self):
        lod2 = ST.sheds(2)
        v = np.asarray(lod2.verts)
        for track in (0., S.SIDING):
            # The scaled train: 4.30 m tall, standing 10 m short of the buffer.
            near = ((np.abs(v[:, 1] - track) < S.EDGE - 1e-6) & (v[:, 2] > .2) & (v[:, 2] < 4.3 * S.TRAIN_SCALE)
                    & (v[:, 0] > -S.TRAIN_LENGTH - 12.) & (v[:, 0] < -5.))
            self.assertFalse(near.any(), f'something stands within the platform edge of the track at u={track}')

    def test_other_lines_get_no_station(self):
        class Elsewhere(Straight):
            def frame(self, s):
                p, t, n = Straight.frame(self, s)
                return p - np.array([2000., 0., 0.]), t, n
        self.assertEqual(ST.layout(Elsewhere()), ({}, None))


class Ground(unittest.TestCase):
    ln = earthworks_line()

    def carve(self, a, u, z):
        site = self.ln.station()
        x, y = site.world(np.array([a]), np.array([u]))[0]
        return float(E.carve(np.array([x]), np.array([y]), np.array([z]), self.ln)[0])

    def test_sheds_and_headhouse_at_the_formation(self):
        for a, u in ((-100., -30.), (-20., 8.), (10., -50.)):
            self.assertAlmostEqual(self.carve(a, u, RAIL + 5.), RAIL + S.FORMATION, delta=.05)

    def test_forecourt_and_access_at_street_level(self):
        self.assertAlmostEqual(self.carve(36., S.AXIS_U, RAIL + 9.), RAIL + S.STREET, delta=.05)
        self.assertAlmostEqual(self.carve(36., S.AXIS_U, RAIL + 5.), RAIL + S.STREET, delta=.05)

    def test_ground_stands_against_the_walls(self):
        # two metres outside the sheds' south-west wall the ground keeps its natural height
        self.assertAlmostEqual(self.carve(-80., S.SHEDS[3] + 2.5, RAIL + 4.), RAIL + 4., delta=.05)

    def test_the_road_keeps_its_ground_at_the_overbridge(self):
        s = self.ln.overbridge()
        self.assertIsNotNone(s)
        site = self.ln.station()
        for u in (-9., 9.):     # behind the retaining walls, on the road's line
            a = s - self.ln.length + u / math.tan(math.radians(140. - 17.5))
            self.assertAlmostEqual(self.carve(a, u, RAIL + 8.6), RAIL + 8.6, delta=.1)


if __name__ == '__main__':
    unittest.main()
