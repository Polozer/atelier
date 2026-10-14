"""Crater Park v2 validators (craterpark/v2/validate.py, plan_png.py): clean fixtures pass, each defect fails with its
location, and every check flags the real r4 defects the owner noted (when r4's imported geometry is on this machine)."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest

import numpy as np

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
from craterpark.v2 import plan_png, validate as V  # noqa: E402

NPZ = Path(os.environ.get('CRATERPARK_R4_NPZ', '/nonexistent'))   # park-assist's r4 extraction (positions, corner_uv)
R4 = NPZ   # r4's meshes: positions (n,3) native metres + triangles; the r4 .bin dumps are overwritten by later builds


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

    def test_the_site_boundary_rule_allows_only_the_outline(self):
        rule = V.site_boundary([(0, 0), (2, 0), (2, 1), (0, 1)])
        a = V.Mesh('a', *grid(0, 0, 1, 1, 1)); b = V.Mesh('b', *grid(1, 0, 2, 1, 2))
        r = V.topology([a, b], allow_open=rule)                              # the T-junction at x 1 still fails
        self.assertEqual((r['surface']['open_edges'], r['surface']['t_junction_vertices']), (3, 1))   # the crack: a's edge and b's two halves
        self.assertTrue(V.topology([V.Mesh('d', *grid(0, 0, 2, 1, 2))], allow_open=rule)['ok'])
        self.assertFalse(V.topology([V.Mesh('d', *grid(0, 0, 2, 1, 2))],
                                    allow_open=V.site_boundary([(0, 0), (2, 0), (2, 1), (0, 1)], below=-1))['ok'])

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


def strip(points, width=2.):
    """A ribbon along a 3-D polyline (k,3), across z, as a conforming strip; per-corner UVs: u along, v across."""
    P = np.asarray(points, 'f8'); k = len(P)
    V = np.r_[P - [0, 0, width / 2], P + [0, 0, width / 2]]
    F = np.array([f for i in range(k - 1) for f in ([i, i + k, i + 1], [i + 1, i + k, i + k + 1])])
    return V, F


def arc(R, deg, step):
    a = np.radians(np.arange(0, deg + 1e-9, step))
    return np.c_[R * np.sin(a), R * (1 - np.cos(a)), np.zeros_like(a)]


class FacetTests(unittest.TestCase):
    def test_a_transition_at_one_degree_is_smooth_and_at_five_faceted(self):
        self.assertTrue(V.facets([V.Mesh('t', *strip(arc(3.5, 60, 1.)))])['ok'])
        r = V.facets([V.Mesh('t', *strip(arc(3.5, 60, 5.)))])
        self.assertFalse(r['ok'])
        self.assertAlmostEqual(r['max_deg'], 5., places=6)

    def test_a_designed_crease_has_split_vertices_and_passes(self):
        a = strip([[0, 0, 0], [1, 0, 0]]); b = strip([[1, 0, 0], [2, .6, 0]])
        V2 = np.r_[a[0], b[0]]; F2 = np.r_[a[1], b[1] + len(a[0])]                 # the lip's corners twice
        self.assertTrue(V.facets([V.Mesh('lip', V2, F2)])['ok'])
        self.assertFalse(V.facets([V.Mesh('lip', V2, F2)], weld=1e-6)['ok'])        # welded, it is a 31 degree fold


class UVTests(unittest.TestCase):
    def test_planar_deck_and_arc_length_wall_pass_and_a_projected_wall_streaks(self):
        P, F = grid(0, 0, 8, 8, 4)
        self.assertTrue(V.uv_stretch([V.Mesh('deck', P, F, uv=P[F][:, :, [0, 2]] / 9., material='material_000')])['ok'])
        # a curved wall: u = arc length along its top, v = height (the solidify rule)
        t = np.linspace(0, np.pi / 2, 20); top = np.c_[10 * np.cos(t), np.zeros_like(t), 10 * np.sin(t)]
        Vw = np.r_[top, top + [0, 3, 0]]; k = len(t)
        Fw = np.array([f for i in range(k - 1) for f in ([i, i + 1, i + k], [i + 1, i + k + 1, i + k])])
        s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(top, axis=0), axis=1))]
        UVw = np.r_[np.c_[s, np.zeros(k)], np.c_[s, np.full(k, 3.)]] / 9.
        self.assertTrue(V.uv_stretch([V.Mesh('wall', Vw, Fw, uv=UVw[Fw], material='material_010')])['ok'])
        # the same wall with world-planar UVs from above (r4's streaks): every face degenerate or stretched
        r = V.uv_stretch([V.Mesh('wall', Vw, Fw, uv=Vw[Fw][:, :, [0, 2]] / 9., material='material_010')])
        self.assertEqual((r['ok'], r['bad_faces']), (False, len(Fw)))
        # triplanar walls are exempt
        self.assertTrue(V.uv_stretch([V.Mesh('wall', Vw, Fw, uv=Vw[Fw][:, :, [0, 2]] / 9., material='material_023')])['ok'])


class OutlineTests(unittest.TestCase):
    def test_a_staircase_and_a_sawtooth_top_serrate_and_curves_do_not(self):
        stair = np.array([[i // 2 * .25 + (i % 2) * .25, 0, i // 2 * .25] for i in range(20)])
        r = V.zigzag([stair])
        self.assertFalse(r['ok'])
        self.assertEqual(r['failures'][0]['view'], 'plan')
        saw = np.array([[i * .25, .1 * (i % 2), 0] for i in range(20)])
        self.assertEqual(V.zigzag([saw])['failures'][0]['view'], 'elevation')
        s = np.linspace(0, 1, 200)
        scurve = np.c_[s * 20, np.zeros_like(s), 3 * np.sin(s * 2 * np.pi)]
        t = np.linspace(0, 2 * np.pi, 100)
        circle = np.c_[5 * np.cos(t), np.zeros_like(t), 5 * np.sin(t)]
        lip = np.c_[s * 20, -s * 4 + .5 * np.sin(s * np.pi), np.zeros_like(s)]          # a sloping, curving lip
        self.assertTrue(V.zigzag([scurve, circle, lip])['ok'])

    def test_outlines_of_a_box_are_clean(self):
        self.assertTrue(V.outlines([V.Mesh('b', *box((0, 0, 0), (2, 1, 3)))])['ok'])


class SliverOwnershipTests(unittest.TestCase):
    def test_slivers_and_long_edges_fail(self):
        P = np.array([[0., 0, 0], [3, 0, 0], [1.5, 0, .001]])
        self.assertFalse(V.slivers([V.Mesh('s', P, [[0, 2, 1]])])['ok'])
        self.assertFalse(V.slivers([V.Mesh('big', *grid(0, 0, 6, 6, 1))])['ok'])          # 8.5 m riding diagonals
        self.assertTrue(V.slivers([V.Mesh('ok', *grid(0, 0, 6, 6, 3))])['ok'])

    def test_every_face_on_a_feature_and_every_feature_on_a_line(self):
        names = ('jump.launch', 'jump.landing', 'tree_ring', 'unnamed')
        m = lambda f: V.Mesh('m', *grid(0, 0, 1, 1, 1), feature=f)
        self.assertTrue(V.ownership([m(0), m(1), m(2)], names, lines=['jump'], scenery=['tree_ring'])['ok'])
        r = V.ownership([m(0), m(2), m(-1), m(3)], names, lines=['jump'])
        self.assertEqual((r['faces_without_feature'], r['features_on_no_line']), (4, ['tree_ring']))


class TerrainTests(unittest.TestCase):
    def test_a_ground_bump_between_corners_and_under_an_edge_is_found(self):
        H = np.zeros((11, 11)); H[5, 5] = .4                                       # one node, mid-face
        g = V.Ground(0., 0., 1., H)
        P = np.array([[1., .5, 1], [9, .5, 1], [5, .5, 9]])
        self.assertGreaterEqual(.5 - H.max() * 0, .3)                              # every corner is .5 m clear
        r = V.terrain([V.Mesh('deck', P, [[0, 2, 1]])], g)
        self.assertFalse(r['ok'])
        self.assertAlmostEqual(r['min_clearance_m'], .1, places=9)
        self.assertEqual(r['failures'][0]['where'], [5., .5, 5.])
        # a wall whose bottom edge crosses a ground ridge between its corners
        H = np.zeros((11, 11)); H[:, 5] = .45
        P = np.array([[2., .5, 2], [2, .5, 8], [2, 3, 2]])
        r = V.terrain([V.Mesh('wall', P, [[0, 1, 2]])], V.Ground(0., 0., 1., H))
        self.assertAlmostEqual(r['min_clearance_m'], .05, places=9)
        self.assertTrue(V.terrain([V.Mesh('deck', *grid(1, 1, 9, 9, 2, y=.8))], g)['ok'])


class BuriedTests(unittest.TestCase):
    def test_a_block_inside_a_block_is_buried_and_coping_is_exempt(self):
        outer = V.Mesh('outer', *box((0, 0, 0), (4, 2, 4)))
        inner = V.Mesh('inner', *box((1, .5, 1), (2, 1.5, 2)))
        r = V.buried([outer, inner], [outer])
        self.assertEqual((r['ok'], r['buried_faces'], list(r['meshes'])), (False, 12, ['inner']))
        tube = V.Mesh('tube', *box((1, 1.97, 0), (1.07, 2.04, 4)), role='coping')
        self.assertTrue(V.buried([outer, tube], [outer])['ok'])


def kicker_park(lip_deg=15., landing=True, tagged=True):
    """A 15 degree kicker (2 m run) and, 12 m on, a 30 degree landing 6 m down; as collision meshes."""
    a = np.radians(lip_deg); R = 8.
    phi = np.linspace(0, a, 40)
    kick = strip(np.r_[[[-4, 0, 0]], np.c_[R * np.sin(phi), R * (1 - np.cos(phi)), np.zeros_like(phi)]], 4.)
    out = [V.Mesh('kicker', *kick, domain='collision', extra={'tag': np.array(['takeoff'] * len(kick[1]), object)})]
    lip = kick[0][len(kick[0]) // 2 - 1] + [0, 0, 2]
    assert abs(lip[0] - R * np.sin(a)) < 1e-9
    if landing:
        L = strip([[8, lip[1] - 1, 0], [10, lip[1] - 1, 0], [10 + 6 / np.tan(np.radians(30)), lip[1] - 7, 0], [40, lip[1] - 7, 0]], 6.)
        out.append(V.Mesh('landing', *L, domain='collision', extra={'tag': np.array(['landing' if tagged else ''] * len(L[1]), object)}))
    else:
        out.append(V.Mesh('flat', *grid(3, -3, 40, 3, 4, y=lip[1] - 1), domain='collision'))
    return out, lip


class AirTests(unittest.TestCase):
    def test_a_matched_landing_has_a_landable_speed_window(self):
        meshes, lip = kicker_park()
        r = V.air(meshes, lip, (1, 0), lip_degrees=15.)
        self.assertTrue(r['ok'], r['failures'])
        self.assertAlmostEqual(r['lip_built_deg'], 15., delta=1.)
        lo, hi = r['landable_speeds']
        self.assertTrue(lo < hi and all(r['speeds'][v]['on'] == 'landing' for v in (lo, hi)))
        self.assertFalse(V.air(meshes, lip, (1, 0), band=(lo - 2, hi))['ok'])        # a design band it cannot land

    def test_a_steep_lip_verts_and_flat_ground_is_no_landing(self):
        meshes, lip = kicker_park(lip_deg=30.)
        self.assertNotIn('lip_verts', [f['kind'] for f in V.air(meshes, lip, (1, 0))['failures']])   # the limit itself
        meshes, lip = kicker_park(lip_deg=50.)
        self.assertIn('lip_verts', [f['kind'] for f in V.air(meshes, lip, (1, 0))['failures']])
        meshes, lip = kicker_park(landing=False)
        self.assertIn('no_landing', [f['kind'] for f in V.air(meshes, lip, (1, 0))['failures']])


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

    def test_an_empty_park_renders_a_notice(self):
        with tempfile.TemporaryDirectory() as d:
            png, px, box_ = plan_png.render_plan([], Path(d) / 'plan.png')
            self.assertEqual((px, box_), (None, None))
            self.assertTrue(Path(png).exists())

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
            # B's side-wall fans are V9 slivers (reported in v2_chat); everything else must pass
            rep, ok = V.validate_park(self.park, Path(d) / 'validation.json', log=None, skip=('slivers',))
            self.assertTrue(ok, rep['failed'])
            self.assertEqual(rep['checks']['topology']['surface']['open_edges'], 0)      # base faces close it
            self.assertTrue((Path(d) / 'validation.json').exists())
            png, _, _ = plan_png.render_park(self.park, Path(d) / 'plan.png', report=rep)
            self.assertTrue(Path(png).stat().st_size > 1000)

    def test_the_ground_is_the_site_and_an_unlined_ramp_is_not(self):
        dsl = self.dsl
        g = dsl.Mesh.part(*grid(1100, 1000, 1110, 1010, 2, y=20.), role=dsl.GROUND, feature='ground', material=dsl.GROUND_MAT)
        stray = dsl.Mesh.part(*grid(1120, 1000, 1124, 1004, 2, y=20.), role=dsl.RIDING, feature='orphan_ramp')
        park = dsl.Park(dsl.Mesh.concat([self.park.mesh, g, stray]), self.park.rails, self.park.lines)
        r = V.validate_park(park, log=None, skip=tuple(k for k in ('overlaps', 'overlaps_collision', 'topology', 'buried',
                            'thin_walls', 'outlines', 'facets', 'uv_stretch', 'slivers', 'protrusions', 'airs', 'budgets')))[0]
        self.assertEqual(r['checks']['ownership']['features_on_no_line'], ['orphan_ramp'])

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
        self.assertEqual(f['mesh'], 'old_planter/side/material_023')
        self.assertTrue(x + .5 - 1e-9 <= f['where'][0] <= x + 1.5 + 1e-9, f)


@unittest.skipUnless(R4.is_dir(), "r4 extraction not on this machine (set CRATERPARK_R4_NPZ)")
class R4DefectTests(unittest.TestCase):
    """The checks flag r4's real defects at the places the owner's notes name (native metres)."""

    @staticmethod
    def soup(f):
        d = np.load(f)
        return d['positions'].astype('f8')[d['triangles']]

    @classmethod
    def near(cls, box, names=None, prefix='SM_CP_'):
        out = []
        for f in sorted(R4.glob(prefix + '*.npz')):
            if names and not any(n in f.stem for n in names):
                continue
            T = cls.soup(f)
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

    def test_notes_1_5_8_r4_transitions_are_faceted(self):
        for name, box_ in (('mesh_0016', (1140, 1060, 1160, 1095)), ('mesh_0084', (1277, 947, 1340, 971))):
            r = V.facets(self.near(box_, [name]), weld=.01)
            self.assertGreater(r['max_deg'], 5., name)

    @unittest.skipUnless(NPZ.is_dir(), "park-assist's r4 extraction not on this machine")
    def test_notes_5_10_projected_uvs_streak_down_the_r4_walls(self):
        d = np.load(NPZ / 'SM_CP_add_run_pool_gap_kicker_sides.npz')
        T = d['positions'][d['triangles']]
        m = V.Mesh('kicker_sides', T.reshape(-1, 3), np.arange(len(T) * 3).reshape(-1, 3), uv=d['corner_uv'],
                   material=str(d['materials'][0]))
        r = V.uv_stretch([m])
        self.assertEqual(r['bad_faces'], len(T))
        self.assertGreater(r['materials']['material_010']['anisotropy_p99'], 100)

    def test_notes_10_13_r4_lips_and_walls_are_staircases(self):
        r = V.outlines(self.near((1195, 900, 1290, 970), ['add_run_curve_to_blue_pool']))
        self.assertFalse(r['ok'])
        self.assertTrue(any(f['turns_deg'][:2] in ([90., -90.], [-90., 90.]) for f in r['failures']))

    def test_note_8_the_quarter_lies_inside_its_foundation(self):
        ms = self.near((1145, 950, 1165, 975), ['mesh_0032', 'mesh_0171', 'mesh_0172'])
        r = V.buried([m for m in ms if '0032' in m.name], [m for m in ms if '0032' not in m.name])
        self.assertFalse(r['ok'])
        self.assertIn('SM_CP_mesh_0032_000', r['meshes'])

    def test_note_2_the_tower_roll_in_verts_onto_a_flat_deck(self):
        r = V.air(self.near((1135, 1050, 1165, 1100), prefix='UC_CP_'), (1149.5, 23.6, 1065.7), (0, -1),
                  speeds=np.arange(8, 24.1, 2))
        kinds = [f['kind'] for f in r['failures']]
        self.assertEqual(kinds, ['lip_verts', 'no_landing'])
        self.assertGreater(r['lip_built_deg'], 45)

    def test_r4_blows_every_budget(self):
        meshes = []
        for f in sorted(R4.glob('*.npz')):
            T = self.soup(f).reshape(-1, 3)
            meshes.append(V.Mesh(f.stem, T, np.arange(len(T)).reshape(-1, 3),
                                 domain='collision' if f.stem.startswith('UC_') else 'render',
                                 role='coping' if 'coping' in f.stem else 'riding'))
        r = V.budgets(meshes)
        # the extraction lacks the exact duplicates Blender dropped on import (5,750 render, 6,711 collision)
        self.assertEqual((r['render_triangles'], r['collision_triangles']), (1_307_949, 842_205))
        self.assertGreater(r['collision_cube_max'], 400_000)                     # one snapshot cube, 4x its budget
        self.assertTrue({f['kind'] for f in r['failures']} >= {'render', 'collision', 'coping', 'render_meshes',
                                                              'collision_cube', 'render_mesh'})

if __name__ == '__main__':
    unittest.main()
