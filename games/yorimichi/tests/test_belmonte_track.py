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

    def test_ballast_bed_is_textured_and_faces_the_train(self):
        """The bed is crushed-stone ballast over its top and shoulders and a dusty cess at its foot, both textured
        (never one flat colour), every face turned up and out so it shows from the train and the line side."""
        mesh = self.meshes['SM_TK_Chunk_000'][0] if 'SM_TK_Chunk_000' in self.meshes else \
            self.meshes[next(n for n in self.meshes if n.startswith('SM_TK_Chunk'))][0]
        self.assertEqual(set(mesh.mats), {'MI_TK_Ballast', 'MI_TK_Cess', 'MI_B_iron'})
        for lod in range(3):
            section = T.ballast_profile(lod)
            parts = T.ballast_parts(section)
            self.assertEqual([m for _, m in parts], ['MI_TK_Cess', 'MI_TK_Ballast', 'MI_TK_Cess'])
            # The parts share their edges and together are the whole section.
            self.assertEqual(parts[0][0][-1], parts[1][0][0])
            self.assertEqual(parts[1][0][-1], parts[2][0][0])
            self.assertEqual(parts[0][0] + parts[1][0][1:-1] + parts[2][0], section)
            for points, mat in parts:
                for (u0, v0), (u1, v1) in zip(points[:-1], points[1:]):
                    # The section runs right to left (u rising): faces point to its left, i.e. normal (-dv, du).
                    nu, nv = -(v1 - v0), u1 - u0
                    self.assertGreater(nv, 0., (lod, mat))                       # up
                    self.assertGreaterEqual(nu * np.sign(u0 + u1), 0., (lod, mat))   # and out, never in
        v = np.asarray(mesh.verts)
        for f, mat in zip(mesh.faces, mesh.mats):
            if mat in T.TEXTURED and len(f) == 4:     # the swept faces (the end cap stands across the line)
                n = np.cross(v[f[1]] - v[f[0]], v[f[2]] - v[f[0]])
                self.assertGreater(n[2], 0., mat)
        # At both ends of the line the bed is closed by an end face looking along the line, out of the bed.
        for s0, s1, at, out in ((0., 50., 0., -1.), (self.line.length - 50., self.line.length, self.line.length, 1.)):
            m = T.chunk_mesh(self.line, s0, s1, 0, np.zeros(3))
            w = np.asarray(m.verts)
            caps = [f for f in m.faces if len(f) == len(T.ballast_profile(0))]
            self.assertEqual(len(caps), 1, at)
            p = w[list(caps[0])]
            normal = sum(np.cross(p[i], p[(i + 1) % len(p)]) for i in range(len(p)))
            self.assertGreater(float(np.dot(normal / np.linalg.norm(normal), self.line.frame(at)[1])) * out, .99)
        from train import track_textures as TT
        for mat, (name, tile) in T.TEXTURED.items():
            self.assertIn(mat, T.MATERIALS)
            self.assertGreater(tile, 0.)
            px = TT.ALL[name](size=256)[..., :3]
            self.assertGreater(float(px.mean(axis=2).std()), .05, name)          # detail, not a flat colour
            # Seamless: the wrap-around step is no larger than the steps inside the image.
            inner = np.abs(np.diff(px, axis=1)).mean()
            self.assertLess(float(np.abs(px[:, 0] - px[:, -1]).mean()), 3 * inner, name)

    def test_banks_end_in_the_ground(self):
        """A bank built over ground the earthworks cannot carve (the Belmonte valley) never ends hanging in the air:
        next to a viaduct it runs on under the deck as the end cone until its whole section is down in the ground."""
        from train import route as R
        ends = 0
        for a, b in T.bank_ranges(self.line):
            for va, vb in self.line.ranges('viaduct'):
                for end, inward in ((a, 1.), (b, -1.)):
                    if not va - 1. <= end <= vb + 1.:
                        continue
                    ends += 1
                    mesh = T.bank_mesh(self.line, *sorted((end, end + inward)), 0, (0., 0., 0.))
                    v = np.asarray(mesh.verts)
                    row = v[:len(v) // 2] if inward > 0 else v[len(v) // 2:]
                    ground = R.ground(row[:, 0], row[:, 1])
                    self.assertLess(float((row[:, 2] - ground).max()), .05, (a, b, end))
        self.assertGreater(ends, 0)

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
