"""Crater Park v2 validators (craterpark/v2/validate.py, plan_png.py): clean fixtures pass, each defect fails with its
location, and every check flags the real r4 defects the owner noted (when r4's imported geometry is on this machine)."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

import numpy as np

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
from craterpark.v2 import plan_png, validate as V  # noqa: E402

R4 = Path.home() / 'dev' / 'atelier-jim5-volcano' / 'build' / 'yorimichi' / 'craterpark' / 'imported-geometry'


def grid(x0, z0, x1, z1, n=4, y=0.):
    """A conforming up-facing grid surface."""
    xs = np.linspace(x0, x1, n + 1); zs = np.linspace(z0, z1, n + 1)
    X, Z = np.meshgrid(xs, zs, indexing='ij')
    P = np.stack([X.ravel(), np.full(X.size, y), Z.ravel()], 1)
    F = []
    for i in range(n):
        for j in range(n):
            a, b, c, d = i * (n + 1) + j, (i + 1) * (n + 1) + j, (i + 1) * (n + 1) + j + 1, i * (n + 1) + j + 1
            F += [[a, d, c], [a, c, b]]
    return P, np.array(F)


def box(lo, hi):
    """A closed, outward-wound box."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    P = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], 'f8')
    F = [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4],
         [1, 5, 7], [1, 7, 3]]
    return P, np.array(F)


def on_square(x0, z0, x1, z1, tol=1e-6):
    """allow_open: edges lying on the square's outline (the fixture site's outer boundary)."""
    def ok(a, b):
        m = []
        for p in (a, b):
            m.append((np.abs(p[:, 0] - x0) < tol) | (np.abs(p[:, 0] - x1) < tol) | (np.abs(p[:, 2] - z0) < tol)
                     | (np.abs(p[:, 2] - z1) < tol))
        same = ((np.abs(a[:, 0] - b[:, 0]) < tol) | (np.abs(a[:, 2] - b[:, 2]) < tol))
        return m[0] & m[1] & same
    return ok


def clean_park():
    """A deck with a ledge (closed, sunk 3 cm into it) on a lane: everything clean by construction."""
    deck = V.Mesh('SM_deck', *grid(0, 0, 8, 8, 8), role='riding', feature=0)
    ledge = V.Mesh('SM_ledge', *box((3, -.03, 2), (3.6, .45, 6)), role='solid', feature=1, closed=True)
    col = V.Mesh('UC_deck', *grid(0, 0, 8, 8, 8), domain='collision', feature=0)
    lane = V.Lane('line', [(1, 4), (7, 4)], 1.5, features=(0, 1))
    return [deck, ledge, col], lane


class OverlapTests(unittest.TestCase):
    def test_parallel_faces_3mm_apart_overlap_and_10mm_do_not(self):
        a = V.Mesh('a', *grid(0, 0, 2, 2, 1))
        r = V.overlaps([a, V.Mesh('b', *grid(1, 1, 3, 3, 1, y=.003))])
        self.assertFalse(r['ok'])
        self.assertEqual(r['between_mesh_pairs'], r['pairs'])
        self.assertAlmostEqual(r['area_m2'], 1., places=6)                      # the 1 x 1 m overlap, exactly
        w = r['failures'][0]['where']
        self.assertTrue(1 <= w[0] <= 2 and 1 <= w[2] <= 2 and abs(w[1]) < 1e-9, w)
        self.assertTrue(V.overlaps([a, V.Mesh('b', *grid(1, 1, 3, 3, 1, y=.01))])['ok'])

    def test_neighbours_sharing_edges_and_a_tilted_face_do_not_overlap(self):
        self.assertTrue(V.overlaps([V.Mesh('deck', *grid(0, 0, 4, 4, 8))])['ok'])
        P, F = grid(1, 1, 3, 3, 1, y=.002)
        P[:, 1] += (P[:, 0] - 2) * np.tan(np.radians(1.))                       # 1 degree: a ramp, not a duplicate
        self.assertTrue(V.overlaps([V.Mesh('a', *grid(0, 0, 4, 4, 1)), V.Mesh('b', P, F)])['ok'])

    def test_a_double_sided_sheet_and_a_duplicate_inside_one_mesh_overlap(self):
        P, F = grid(0, 0, 1, 1, 1)
        r = V.overlaps([V.Mesh('sheet', np.r_[P, P], np.r_[F, F[:, ::-1] + len(P)])])
        self.assertEqual((r['ok'], r['within_mesh_pairs'] > 0), (False, True))


class TopologyTests(unittest.TestCase):
    def test_a_clean_surface_and_a_closed_solid_pass(self):
        r = V.topology([V.Mesh('deck', *grid(0, 0, 4, 4, 4)), V.Mesh('box', *box((1, -.03, 1), (2, .5, 2)), closed=True)],
                       allow_open=on_square(0, 0, 4, 4))
        self.assertTrue(r['ok'], r['failures'][:3])
        self.assertEqual(r['surface']['open_edges_allowed'], 16)

    def test_a_t_junction_between_two_meshes_is_found_where_it_is(self):
        a = V.Mesh('a', *grid(0, 0, 1, 1, 1)); b = V.Mesh('b', *grid(1, 0, 2, 1, 2))   # b splits the shared edge
        r = V.topology([a, b], allow_open=on_square(0, 0, 2, 1))
        self.assertFalse(r['ok'])
        self.assertEqual(r['surface']['t_junction_vertices'], 1)
        t = [f for f in r['failures'] if f['kind'] == 't_junction'][0]
        self.assertEqual(t['where'], [1., 0., .5])

    def test_a_receded_corner_cracks_the_surface(self):
        P, F = grid(0, 0, 1, 1, 2)
        P = P[F].reshape(-1, 3); F = np.arange(len(P)).reshape(-1, 3)           # r4's soup: every face its own corners
        P[F[::2]] -= [0, .005, 0]                                               # every other face 5 mm back
        r = V.topology([V.Mesh('soup', P, F)], allow_open=on_square(0, 0, 1, 1))
        self.assertFalse(r['ok'])
        self.assertGreater(r['surface']['open_edges'], 0)

    def test_flipped_open_and_inside_out_solids_fail(self):
        P, F = grid(0, 0, 2, 2, 2); F[3] = F[3, ::-1]
        self.assertEqual(V.topology([V.Mesh('d', P, F)], allow_open=on_square(0, 0, 2, 2))['surface']['miswound_edges'], 3)
        P, F = box((0, 0, 0), (1, 1, 1))
        self.assertFalse(V.topology([V.Mesh('open', P, F[1:], closed=True)])['solids']['open']['ok'])
        r = V.topology([V.Mesh('inside_out', P, F[:, ::-1], closed=True)])
        self.assertLess(r['solids']['inside_out']['volume_m3'], 0)
        self.assertEqual(r['failures'][0]['kind'], 'solid_inside_out')


class ProtrusionTests(unittest.TestCase):
    def setUp(self):
        self.deck = V.Mesh('deck', *grid(0, 0, 10, 4, 10), feature=0)
        self.lane = V.Lane('line', [(0, 2), (10, 2)], 1., features=(0,))

    def test_a_slab_5cm_proud_in_the_corridor_pops_out_where_it_is(self):
        slab = V.Mesh('tile', *box((4, -.2, 1.5), (5, .05, 2.5)), feature=7)
        r = V.protrusions([self.deck, slab], [self.lane])
        self.assertFalse(r['ok'])
        f = r['failures'][0]
        self.assertAlmostEqual(f['height_m'], .05, places=6)
        self.assertTrue(4 <= f['where'][0] <= 5 and 1.5 <= f['where'][2] <= 2.5, f)
        self.assertEqual((f['mesh'], f['feature']), ('tile', 7))

    def test_outside_buried_overhead_and_own_features_do_not(self):
        for name, lo, hi, feat in (('outside', (4, 0, 3.2), (5, .5, 3.8), 7), ('buried', (4, -.5, 1.5), (5, -.01, 2.5), 7),
                                   ('roof', (4, 5, 0), (5, 5.5, 4), 7), ('own_ledge', (4, -.03, 1.8), (6, .45, 2.4), 0)):
            r = V.protrusions([self.deck, V.Mesh(name, *box(lo, hi), feature=feat)], [self.lane])
            self.assertTrue(r['ok'], (name, r['failures'][:1]))

    def test_a_beam_at_head_height_obstructs(self):
        r = V.protrusions([self.deck, V.Mesh('beam', *box((4, 1.8, 0), (4.5, 2.2, 4)), feature=9)], [self.lane])
        self.assertAlmostEqual(r['lanes']['line']['max_height_m'], 2.2, places=6)


class ThicknessTests(unittest.TestCase):
    def test_a_20cm_slab_is_thin_and_a_50cm_one_is_not(self):
        r = V.thin_walls([V.Mesh('slab', *box((0, 0, 0), (2, 1, .2)))])
        self.assertFalse(r['ok'])
        self.assertAlmostEqual(r['min_thickness_m'], .2, places=9)
        self.assertTrue(V.thin_walls([V.Mesh('wall', *box((0, 0, 0), (2, 1, .5)))])['ok'])

    def test_a_double_sided_sheet_is_zero_thick_and_coping_is_exempt(self):
        P, F = grid(0, 0, 1, 1, 1)
        r = V.thin_walls([V.Mesh('sheet', np.r_[P, P], np.r_[F, F[:, ::-1] + len(P)])])
        self.assertEqual(r['min_thickness_m'], 0.)
        self.assertTrue(V.thin_walls([V.Mesh('tube', *box((0, 0, 0), (2, .07, .07)), role='coping')])['ok'])
        # a ledge sunk 3 cm into its deck is a contact, not a 3 cm wall
        sunk = [V.Mesh('deck', *grid(0, 0, 4, 4, 4)), V.Mesh('ledge', *box((1, -.03, 1), (1.6, .45, 3)), closed=True)]
        self.assertTrue(V.thin_walls(sunk)['ok'])

    def test_plan_width_is_exact_on_necks_and_ignores_curves_and_corners(self):
        r = V.plan_width([[(0, 0), (5, 0), (5, .2), (0, .2)]])
        self.assertAlmostEqual(r['min_width_m'], .2, places=12)
        self.assertTrue(V.plan_width([[(0, 0), (5, 0), (5, 1), (0, 1)]])['ok'])
        t = np.linspace(0, 2 * np.pi, 400, endpoint=False)
        self.assertTrue(V.plan_width([np.c_[2 * np.cos(t), 2 * np.sin(t)]])['ok'])            # finely sampled circle
        # an annulus 0.25 m wide: holes count, and the neck is measured across, not along
        r = V.plan_width([np.c_[2 * np.cos(t), 2 * np.sin(t)], np.c_[1.75 * np.cos(t), 1.75 * np.sin(t)]])
        self.assertAlmostEqual(r['min_width_m'], .25, places=3)
        # an S-curve band 0.5 m wide passes: alternating curvature is not a neck
        s = np.linspace(0, 1, 200); c = np.c_[s * 20, 3 * np.sin(s * 2 * np.pi)]
        d = np.gradient(c, axis=0); n = np.c_[-d[:, 1], d[:, 0]] / np.linalg.norm(d, axis=1)[:, None]
        self.assertTrue(V.plan_width([np.r_[c - .25 * n, (c + .25 * n)[::-1]]])['ok'])
        # an L whose arm is 0.29 m, and a 20 degree spike
        self.assertAlmostEqual(V.plan_width([[(0, 0), (3, 0), (3, .29), (.5, .29), (.5, 3), (0, 3)]])['min_width_m'], .29, places=12)
        r = V.plan_width([[(0, 0), (4, 0), (0, 4 * np.tan(np.radians(20)))]])
        self.assertGreater(r['sharp_corners'], 0)


class BudgetTests(unittest.TestCase):
    def test_counts_pass_under_the_limits_and_name_the_worst_cube(self):
        park, _ = clean_park()
        self.assertTrue(V.budgets(park)['ok'])
        r = V.budgets(park, limits={'collision_cube': 10, 'render': 100})
        self.assertEqual(sorted(f['kind'] for f in r['failures']), ['collision_cube', 'render'])
        self.assertEqual(r['collision_cube_max'], 128)


class EntryPointTests(unittest.TestCase):
    def test_the_clean_park_passes_and_writes_its_report(self):
        park, lane = clean_park()
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'geometry-report.json'
            rep, ok = V.validate(park, lanes=[lane], regions={'ledge': [[(3, 2), (3.6, 2), (3.6, 6), (3, 6)]]},
                                 allow_open=on_square(0, 0, 8, 8), out=out, log=None)
            self.assertTrue(ok, rep['failed'])
            self.assertEqual(json.loads(out.read_text())['ok'], True)
            self.assertEqual(set(rep['checks']), {'overlaps', 'overlaps_collision', 'topology', 'topology_collision',
                                                  'thin_walls', 'plan_width', 'protrusions', 'budgets'})
            png, px, _ = plan_png.render_plan(park, Path(d) / 'plan.png', lanes=[lane], report=rep,
                                              airs=[{'lip': (1, .5, 4), 'land': (7, 0, 4), 'apex': 2.}])
            from PIL import Image
            im = Image.open(png)
            self.assertGreater(min(im.size), 100)
            self.assertGreater(len(np.unique(np.asarray(im.convert('RGB')).reshape(-1, 3), axis=0)), 50)          # shaded, not blank

    def test_a_dirty_park_fails_naming_each_check(self):
        park, lane = clean_park()
        park.append(V.Mesh('tile', *box((5, -.2, 3.5), (6, .05, 4.5)), feature=-1))   # pokes out, and lies on the deck
        park.append(V.Mesh('dup', *grid(0, 0, 2, 2, 2, y=.002), feature=0))
        rep, ok = V.validate(park, lanes=[lane], allow_open=on_square(0, 0, 8, 8), log=None)
        self.assertFalse(ok)
        self.assertTrue({'overlaps', 'protrusions', 'topology'} <= set(rep['failed']), rep['failed'])


class ParkEntryTests(unittest.TestCase):
    """validate_park on agent A's dsl.Park, as generate.run_validators calls it."""

    def setUp(self):
        from craterpark.v2 import dsl, layout_m0
        self.dsl = dsl
        self.park = layout_m0.park()

    def test_the_m0_park_passes_closed_and_renders_its_plan(self):
        with tempfile.TemporaryDirectory() as d:
            rep, ok = V.validate_park(self.park, Path(d) / 'validation.json', log=None)
            self.assertTrue(ok, rep['failed'])
            self.assertEqual(rep['checks']['topology']['surface']['open_edges'], 0)      # base faces close it
            self.assertTrue((Path(d) / 'validation.json').exists())
            png, _, _ = plan_png.render_park(self.park, Path(d) / 'plan.png', report=rep)
            self.assertTrue(Path(png).stat().st_size > 1000)

    def test_a_slab_in_the_line_fails_the_park_where_it_is(self):
        dsl = self.dsl
        line = self.park.lines[0]
        x, y, z = np.asarray(line.path)[0]
        P, F = box((x + .5, y - .3, z - .5), (x + 1.5, y + .1, z + .5))
        slab = dsl.Mesh.part(P, F, role=dsl.SIDE, feature='old_planter', material=dsl.SIDE_WALL)
        park = dsl.Park(dsl.Mesh.concat([self.park.mesh, slab]), self.park.rails, self.park.lines)
        rep, ok = V.validate_park(park, log=None)
        self.assertFalse(ok)
        self.assertIn('protrusions', rep['failed'])
        f = rep['checks']['protrusions']['failures'][0]
        self.assertEqual(f['mesh'], 'old_planter/side')
        self.assertTrue(x + .5 - 1e-9 <= f['where'][0] <= x + 1.5 + 1e-9, f)


@unittest.skipUnless(R4.is_dir(), 'r4 imported geometry not on this machine')
class R4DefectTests(unittest.TestCase):
    """The checks flag r4's real defects at the places the owner's notes name (native metres)."""

    @staticmethod
    def near(box, names=None, prefix='SM_CP_'):
        out = []
        for f in sorted(R4.glob(prefix + '*.bin')):
            if names and not any(n in f.stem for n in names):
                continue
            T = np.fromfile(f, 'f8').reshape(-1, 3, 3)[:, :, [0, 2, 1]] / 100.
            c = T.mean(1)
            k = (c[:, 0] >= box[0]) & (c[:, 0] <= box[2]) & (c[:, 2] >= box[1]) & (c[:, 2] <= box[3])
            if k.any():
                out.append(V.soup_to_mesh(T[k], f.stem))
        return out

    def test_notes_25_28_retaining_walls_lie_on_the_foundation(self):
        r = V.overlaps(self.near((1395, 1010, 1406, 1130), ['0110', '0118', '0160', '0178', '0179']))
        self.assertFalse(r['ok'])
        self.assertGreater(r['mesh_pairs']['SM_CP_mesh_0118_000 | SM_CP_mesh_0178_000']['area_m2'], 50)
        self.assertGreater(r['mesh_pairs']['SM_CP_mesh_0110_000 | SM_CP_mesh_0178_000']['area_m2'], 20)
        xs = [f['where'][0] for f in r['failures'] if 'SM_CP_mesh_0178_000' in f['meshes'] and 'SM_CP_mesh_0118_000' in f['meshes']]
        self.assertTrue(all(abs(x - 1400.6) < .2 for x in xs), xs)

    def test_note_1_the_receded_roll_in_is_cracked(self):
        r = V.topology(self.near((1140, 1070, 1160, 1090), ['mesh_0016']))
        self.assertFalse(r['ok'])
        self.assertGreater(r['surface']['open_edges'], r['surface']['faces'])     # nearly every edge split open

    def test_note_23_tiles_and_planters_poke_through_the_pump_track(self):
        lane = V.Lane('valley_pump_track', [(1322, 1134), (1322, 1056)], 3.5, surface=('SM_CP_add_run_valley_pump_track',))
        r = V.protrusions(self.near((1314, 1050, 1330, 1140)), [lane])
        found = r['lanes']['valley_pump_track']['meshes']
        for m in ('SM_CP_mesh_0152_000', 'SM_CP_mesh_0154_000', 'SM_CP_mesh_0128_000'):   # tile strip, planters
            self.assertIn(m, found)
            self.assertGreater(found[m]['max_height_m'], .2)

    def test_notes_3_8_the_channel_wall_is_a_shell_on_its_foundation(self):
        # the riding sheet mesh_0020 lies centimetres off foundation mesh_0170, back to back: a paper-thin wall whose
        # foundation shows through as shards; the foundation prisms' shared walls are zero thick
        r = V.thin_walls(self.near((1138, 1040, 1160, 1065), ['mesh_0020', 'add_solid_0020', 'mesh_0170']), limit=100_000)
        self.assertFalse(r['ok'])
        shell = [f['thickness_m'] for f in r['failures'] if sorted(f['meshes']) == ['SM_CP_mesh_0020_000', 'SM_CP_mesh_0170_000']]
        self.assertGreater(len(shell), 1000)
        self.assertLess(float(np.median(shell)), .1)
        self.assertEqual(r['meshes']['SM_CP_mesh_0170_000']['min_thickness_m'], 0.)

    def test_r4_blows_every_budget(self):
        meshes = []
        for f in sorted(R4.glob('*.bin')):
            T = np.fromfile(f, 'f8').reshape(-1, 3)[:, [0, 2, 1]] / 100.
            meshes.append(V.Mesh(f.stem, T, np.arange(len(T)).reshape(-1, 3),
                                 domain='collision' if f.stem.startswith('UC_') else 'render',
                                 role='coping' if 'coping' in f.stem else 'riding'))
        r = V.budgets(meshes)
        self.assertEqual((r['render_triangles'] > 1_300_000, r['collision_triangles']), (True, 848_916))
        self.assertGreater(r['collision_cube_max'], 400_000)                     # one snapshot cube, 4x its budget
        self.assertTrue({f['kind'] for f in r['failures']} >= {'render', 'collision', 'coping', 'render_meshes',
                                                              'collision_cube', 'render_mesh'})

if __name__ == '__main__':
    unittest.main()
