"""Belmonte railway track (world/train/track.py): the layout from route.json and the triangle budgets.

Needs the route study's route.json (`atelier build yorimichi world.belmonte_train_route`); skipped without it.
The built GLBs' manifest is checked when world.belmonte_track has run.
"""
import json
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402
from train import track as T  # noqa: E402

BUILT = T.ROUTE.exists()


@unittest.skipUnless(BUILT, 'route.json not built (world.belmonte_train_route)')
class Track(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.line = T.Line()
        cls.meshes, cls.doc = T.layout(cls.line)

    def test_chunks_cover_the_line(self):
        rows = [c for c in self.doc['chunks'] if c['name'].startswith('SM_TK_Chunk')]
        self.assertEqual(rows[0]['start'], 0.)
        self.assertAlmostEqual(rows[-1]['end'], self.line.length, places=1)
        for a, b in zip(rows[:-1], rows[1:]):
            self.assertAlmostEqual(a['end'], b['start'], places=2)
            self.assertLessEqual(b['end'] - b['start'], T.CHUNK + 1e-6)

    def test_rails_sit_at_gauge_on_the_rail_top(self):
        mesh = self.meshes['SM_TK_Chunk_10'][0]
        origin = np.asarray(next(c['origin'] for c in self.doc['chunks'] if c['name'] == 'SM_TK_Chunk_10'))
        v = np.asarray(mesh.verts) + origin
        s0 = next(c['start'] for c in self.doc['chunks'] if c['name'] == 'SM_TK_Chunk_10')
        p, _, n = self.line.frame(s0)
        first = v[np.linalg.norm(v[:, :2] - p[:2], axis=1) < 1.]
        tops = first[np.abs(first[:, 2] - p[2]) < 1e-3]
        across = sorted(set(np.round((tops[:, :2] - p[:2]) @ n[:2], 3)))
        self.assertAlmostEqual((across[-1] + across[-2]) / 2 - (across[0] + across[1]) / 2, T.GAUGE + .07, places=2)

    def test_sleepers_every_spacing_and_on_both_loop_tracks(self):
        groups = self.doc['instances']['SM_TK_Sleeper']
        total = sum(len(g) for g in groups.values())
        main = int(self.line.length / T.SLEEPER_SPACING)
        self.assertGreater(total, main)                       # the loop's own sleepers come on top
        self.assertLess(total, main + (self.line.loop[1] - self.line.loop[0]) / T.SLEEPER_SPACING + 2)
        scales = [r[4] for g in groups.values() for r in g]
        self.assertGreater(max(scales), 1.)                   # long timbers at the turnouts
        self.assertEqual(min(scales), 1.)

    def test_buffer_stops_and_stopping_points(self):
        stops = self.doc['instances']['SM_TK_BufferStop']
        self.assertEqual(len(stops), 2)
        start, end = self.line.frame(0.)[0], self.line.frame(self.line.length)[0]
        self.assertLess(math.dist(stops[0][:2], start[:2]), 1.5)
        self.assertLess(math.dist(stops[1][:2], end[:2]), 1.5)
        self.assertEqual(len(self.doc['instances']['SM_TK_StopBoard']), 2)

    def test_tunnels_and_portals(self):
        names = [t['name'] for t in self.doc['tunnels']]
        self.assertIn('Spiral', names)
        self.assertEqual(len(self.doc['instances']['SM_TK_Portal']), 2 * len(names))
        spiral = next(t for t in self.doc['tunnels'] if t['name'] == 'Spiral')
        covered = sum(p['end'] - p['start'] for p in spiral['lining'])
        self.assertAlmostEqual(covered, spiral['end'] - spiral['start'], places=1)
        self.assertTrue(spiral['chunks'])                     # deep chunks go on the tunnel's data layer

    def test_tunnels_are_dark_and_lit_by_wall_lamps(self):
        lighting = self.doc['tunnel_lighting']
        for tunnel in self.doc['tunnels']:
            name = tunnel['name']
            lamps, lights = self.doc['instances']['SM_TK_TunnelLamp'][name], lighting['lights'][name]
            self.assertEqual(len(lamps), len(lights))
            spacing = (tunnel['end'] - tunnel['start']) / len(lamps)
            self.assertLessEqual(spacing, T.LAMP_SPACING * 1.5)
            for (x, y, z, yaw, _), light in zip(lamps, lights):
                self.assertGreater(light[2], z - .2)
                self.assertLess(math.dist(light[:2], (x, y)), T.LAMP_REACH + .05)
            # Every lamp stands inside one of its tunnel's exposure volumes.
            for x, y, z, *_ in lamps:
                inside = False
                for piece in tunnel['lining']:
                    v = piece['volume']
                    c, h = v['centre'], v['half_extent']
                    a = math.radians(v['yaw'])
                    dx, dy = x - c[0], y - c[1]
                    u, w = dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a)
                    inside |= abs(u) <= h[0] and abs(w) <= h[1] and abs(z - c[2]) <= h[2]
                self.assertTrue(inside, (name, x, y, z))
        for name, lods in self.meshes.items():
            if name.startswith('SM_TK_Tunnel_'):
                self.assertEqual(set(lods[0].mats), {'MI_TK_TunnelLining'})
        self.assertFalse(lighting['light']['cast_shadows'])

    def test_viaduct_piers_reach_the_ground(self):
        via = self.doc['viaducts'][0]
        spans = np.diff(via['piers'])
        self.assertTrue(np.all(np.abs(spans - T.SPAN) < 2.))
        lo, hi = None, None
        for piece in via['pieces']:
            a, b = self.meshes[piece['name']][0].bounds()
            lo = a[2] + piece['origin'][2] if lo is None else min(lo, a[2] + piece['origin'][2])
            hi = b[2] + piece['origin'][2] if hi is None else max(hi, b[2] + piece['origin'][2])
        ground = self.line.ground_at(np.array(via['piers'])).min()
        self.assertLess(lo, ground)
        rail = np.interp(via['piers'], self.line.s, self.line.rail).max()
        self.assertAlmostEqual(hi, rail - T.DECK_DEPTH + T.PARAPET[1], delta=.5)

    def test_triangle_budgets(self):
        report = T.triangle_report(self.meshes)
        self.assertEqual([k for k, r in report.items() if not r['ok']], [])

    def test_closed_solids_face_outward(self):
        for name in ('SM_TK_Sleeper', 'SM_TK_BufferStop', 'SM_TK_Portal'):
            mesh = self.meshes[name][0]
            v = np.asarray(mesh.verts)
            volume = 0.
            for f in mesh.faces:
                for k in range(1, len(f) - 1):
                    volume += np.dot(v[f[0]], np.cross(v[f[k]], v[f[k + 1]])) / 6
            self.assertGreater(volume, 0., name)

    def test_manifest(self):
        path = T.OUT / 'manifest.json'
        if not path.exists():
            self.skipTest('world.belmonte_track not built')
        manifest = json.loads(path.read_text())
        self.assertTrue(manifest['checks']['budgets_ok'])
        self.assertTrue(manifest['checks']['disk_ok'])


if __name__ == '__main__':
    unittest.main()
