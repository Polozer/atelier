"""The Belmonte station's buildings (world/train/station.py): its meshes within budget and closed the right way out,
its pieces at the line's end, the scaled train's gauge clear along the platforms, and the train service standing its
arrivals on the station's own platform (no makeshift one), on a straight stand-in for the line's last kilometre."""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import yori  # noqa: E402,F401
from train import station as ST, station_site as S, track as T  # noqa: E402

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


def volume(mesh):
    v = np.asarray(mesh.verts)
    return sum(v[f[0]] @ np.cross(v[f[k]], v[f[k + 1]]) / 6 for f in mesh.faces for k in range(1, len(f) - 1))


class Meshes(unittest.TestCase):
    meshes, doc = ST.layout(Straight())

    def test_budgets(self):
        self.assertEqual(set(self.meshes), {'SM_ST_Headhouse', 'SM_ST_Sheds', 'SM_ST_Coaches', 'SM_ST_Forecourt'})
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

    def test_materials_are_known(self):
        for name, lods in self.meshes.items():
            self.assertLessEqual({m for mesh in lods for m in mesh.mats}, set(T.MATERIALS) | {
                'MI_B_ashlar', 'MI_B_stone', 'MI_B_gravel', 'MI_B_iron', 'MI_B_wood'}, name)

    def test_pieces_at_the_line_end(self):
        rows = {r['name']: r for r in self.doc['pieces']}
        self.assertEqual(set(rows), set(self.meshes))
        for row in rows.values():
            self.assertTrue(np.allclose(row['origin'], [*END, RAIL]))
            self.assertEqual(row['collision'], 'LOD2')
        self.assertAlmostEqual(self.doc['levels']['street'], RAIL + S.STREET, places=3)
        self.assertAlmostEqual(self.doc['levels']['platform'], RAIL + S.PLATFORM, places=3)

    def test_vestibule_floor_at_street_level(self):
        """The collision's vestibule floor: an upward face at street level under every point behind the facade."""
        mesh = ST.headhouse(2)
        v = np.asarray(mesh.verts)
        tris = np.asarray([(v[f[0]], v[f[k]], v[f[k + 1]]) for f in mesh.faces for k in range(1, len(f) - 1)])
        normal = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        floor = tris[(np.abs(tris[:, :, 2] - S.STREET).max(1) < 1e-6) & (normal[:, 2] > 0)]

        def covered(a, u):
            p = np.array([a, u])
            d = [np.cross(floor[:, (k + 1) % 3, :2] - floor[:, k, :2], p - floor[:, k, :2]) for k in range(3)]
            return bool(((d[0] >= -1e-9) & (d[1] >= -1e-9) & (d[2] >= -1e-9)).any())
        for u in np.linspace(-40.5, 11.5, 30):
            self.assertTrue(covered(S.HEADHOUSE[1] - 1.5, u), u)

    def test_forecourt_and_access_at_street_level(self):
        p = Straight().frame(np.array([Straight.length - 10., Straight.length]))[0]
        site = S.for_line(p[:, :2], p[:, 2])
        v = np.asarray(ST.forecourt(site, 2).verts)
        square = v[v[:, 0] <= S.FORECOURT[1]]
        self.assertAlmostEqual(float(square[:, 2].max()), S.STREET + ST.PAVING, places=3)   # flush with the vestibule
        self.assertAlmostEqual(float(v[:, 2].max()), S.ACCESS_END_Z - RAIL + ST.PAVING, places=3)     # the road's far end
        self.assertEqual(self.doc['access'][-1], [797., 4816.])

    def test_platforms_clear_the_scaled_train(self):
        for lod in range(3):
            v = np.asarray(ST.sheds(lod).verts)
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


class TrainService(unittest.TestCase):
    def test_belmonte_arrives_on_the_station_platform(self):
        import belmonte_train_service as service
        line = Straight()
        s = np.arange(line.length - 1000., line.length + 1e-6, 10.)
        p, _, _ = line.frame(s)
        samples = [dict(s=float(c - s[0]), x=float(x), y=float(y), rail_z=RAIL, ground_z=RAIL + 4.)
                   for c, (x, y, _) in zip(s, p)]
        route = dict(samples=samples, stations={'Hidamari': {'centre': [0., 0.]}, 'Belmonte': {'centre': [0., 1.]}})
        train = dict(length=150.7, vehicles=[dict(id='first-class', offset=0., doors=[])])
        end = samples[-1]['s']
        out = service.stations(route, train, [0., end - 10.])
        belmonte = next(r for r in out if r['key'] == 'belmonte_station')
        self.assertNotIn('platform', belmonte)          # the station brings its own (BUILT)
        self.assertIn('platform', next(r for r in out if r['key'] == 'hidamari_station'))
        x, y, z = (c / 100. for c in belmonte['arrival']['location'])
        site = S.for_line([p[-2][:2], p[-1][:2]], [RAIL, RAIL])
        a, u = site.local(np.array([x]), np.array([-y]))
        self.assertTrue(-S.SHED_LENGTH < float(a[0]) < 0.)
        self.assertTrue(S.EDGE < float(u[0]) < 10.5)                       # on platform 1, beside the line's track
        self.assertAlmostEqual(z, RAIL + S.PLATFORM, places=2)


if __name__ == '__main__':
    unittest.main()
