"""Crater Park v2 primitives: every one a watertight solid with its profile's heights exact at the knots, its lips at
their angles and walls at least 0.30 m thick (craterpark/v2/primitives.py, solids.py, coping.py, rails.py)."""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
from craterpark import additions
from craterpark.v2 import dsl, rails, solids
from craterpark.v2 import primitives as pr
from craterpark.v2.curves import Line, Spline


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


def lip_rows(mesh, y):
    return np.abs(mesh.V[:, 1] - y) < 1e-9


class QuarterPipeTests(unittest.TestCase, Common):
    def test_a_quarter_pipe_has_its_lip_at_height_vertical_on_top_and_one_coping(self):
        for height, radius, top in ((3., 3.5, None), (4., 3.5, 90.)):
            built = pr.quarter_pipe(Line((0., 0.), (12., 0.)), floor_y=-1., height=height, radius=radius, deck=1.5)
            self.assertSolid(built)
            mesh = built.mesh
            riding = mesh.where(role=dsl.RIDING)
            lip = lip_rows(riding, -1. + height)
            self.assertTrue(lip.any())
            # the transition's last row (before the lip's crease) has the top angle's analytic normal
            want = top if top is not None else math.degrees(math.acos(1 - height / radius))
            ang = np.degrees(np.arccos(np.clip(riding.N[lip][:, 1], -1, 1)))
            self.assertTrue(np.isclose(ang, want, atol=1e-6).any() and np.isclose(ang, 0., atol=1e-9).any())
            self.assertTrue(np.allclose(riding.V[lip_rows(riding, -1.)][:, 1], -1.))      # the floor knot
            cop = mesh.where(role=dsl.COPING)
            self.assertGreater(solids.check_closed(cop), 0)
            self.assertEqual(len(built.rails), 1)
            self.assertTrue(np.allclose(built.rails[0].points[:, 1], -1. + height + .012))
            # the deck lies on the path's left (+z for a path along +x), the floor on its right
            deck = riding.V[lip_rows(riding, -1. + height)]
            self.assertGreater(deck[:, 2].max(), 1.4)

    def test_a_short_deck_is_refused(self):
        with self.assertRaises(ValueError):
            pr.quarter_pipe(Line((0., 0.), (4., 0.)), floor_y=0., height=2., radius=3., deck=.8)


class BankAndHipTests(unittest.TestCase, Common):
    def test_a_bank_rises_to_its_deck_at_its_angle(self):
        built = pr.bank(Line((0., 0.), (12., 0.)), foot_y=0., height=2., degrees=30.)
        self.assertSolid(built)
        riding = built.mesh.where(role=dsl.RIDING)
        self.assertAlmostEqual(riding.V[:, 1].max(), 2., places=9)
        ang = np.degrees(np.arccos(np.clip(riding.N[:, 1], -1, 1)))
        self.assertAlmostEqual(ang.max(), 30., places=6)

    def test_a_hip_is_one_smooth_closed_sweep_round_its_corner(self):
        built = pr.hip((10., 0.), ((0., 0.), (10., 10.)), foot_y=0., height=1.5, degrees=30.)
        self.assertSolid(built)
        self.assertAlmostEqual(built.mesh.where(role=dsl.RIDING).V[:, 1].max(), 1.5, places=9)

    def test_a_bank_with_too_tight_transitions_is_refused(self):
        with self.assertRaises(ValueError):
            pr.bank(Line((0., 0.), (5., 0.)), foot_y=0., height=1., degrees=60., foot_r=2.)


def ribbon_snake():
    """park-assist's invalid snake (cleanpark/harness/review_ribbon_fold_regressions.py)."""
    t = np.linspace(0, 1, 97)
    line = np.stack([1300 + 48 * t, 900 + 9 * np.sin(2 * np.pi * t)], 1)
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(line, axis=0), axis=1))]
    return line, s, 5 - s / 25 + .6 * np.exp(-((s - s[-1] / 2) / 4) ** 2)


class SnakeTests(unittest.TestCase, Common):
    def test_a_snake_run_is_closed_with_two_copings_and_its_lips_at_the_walls_height(self):
        centre = Spline([(0, 0), (15, 6), (30, 0), (45, -6), (60, 0)])
        built = pr.snake_run(centre, width=3., wall=1.5, radius=3.5, floor=dsl.Height.linear(0, 5., centre.length, 2.6))
        self.assertSolid(built)
        self.assertEqual(len(built.rails), 2)
        cop = built.mesh.where(role=dsl.COPING)
        self.assertGreater(solids.check_closed(cop), 0)
        # each rail point stands the wall's height plus the proud over the floor at its station
        for r in built.rails:
            self.assertTrue(((r.points[:, 1] - 2.6) > 1.5).all())
        solids.check_folds(built.mesh.where(role=dsl.RIDING))

    def test_park_assists_ribbon_regressions_straight_both_ways_pass_the_tight_snake_is_refused(self):
        for a, b, y0, y1 in (((1300., 900.), (1348., 900.), 5., 3.), ((1348., 900.), (1300., 900.), 3., 5.)):
            built = pr.snake_run(Line(a, b), width=3., wall=1.5, radius=additions.RADIUS[1],
                                 floor=dsl.Height.linear(0., y0, 48., y1))
            self.assertSolid(built)
        line, s, y = ribbon_snake()
        for pts, ss, ys in ((line, s, y), (line[::-1], s[-1] - s[::-1], y[::-1])):
            with self.assertRaises(ValueError) as e:
                pr.snake_run(Spline(pts), width=3., wall=1.5, radius=additions.RADIUS[1],
                             floor=lambda t, ss=ss, ys=ys: np.interp(t, ss, ys))
            self.assertIn('fold', str(e.exception))

    def test_a_mixed_projected_orientation_is_refused_whatever_the_majority(self):
        built = pr.snake_run(Line((0., 0.), (20., 0.)), width=3., wall=1.5, radius=3.5)
        riding = built.mesh.where(role=dsl.RIDING)
        for flip in (slice(0, 3), slice(3, None)):                 # a minority and a majority turned over
            bad = riding.subset(np.ones(len(riding.F), bool)); bad.F = bad.F.copy()
            bad.F[flip] = bad.F[flip][:, ::-1]
            with self.assertRaises(ValueError):
                solids.check_folds(bad)


KIDNEY = [(0, 0), (20, 0), (20, 14), (11, 9), (0, 14)]


class BowlTests(unittest.TestCase, Common):
    def test_a_kidney_bowl_that_turns_inward_is_closed_with_a_closed_coping(self):
        for inward in (2.5, 1.5):
            built = pr.bowl(pr.Rounded(KIDNEY, [4.5, 4.5, 4.5, inward, 4.5], closed=True), floor_y=-3., depth=3.,
                            radius=3., deck=1.2)
            self.assertSolid(built)
            riding = built.mesh.where(role=dsl.RIDING)
            self.assertAlmostEqual(riding.V[:, 1].min(), -3., places=9)            # the floor knot
            self.assertAlmostEqual(riding.V[:, 1].max(), 0., places=9)             # the lip and deck
            ang = np.degrees(np.arccos(np.clip(riding.N[:, 1], -1, 1)))
            self.assertAlmostEqual(ang.max(), 90., places=6)                       # vertical at the top
            cop = built.mesh.where(role=dsl.COPING)
            _, F = cop.welded(solids.WELD)
            self.assertEqual(solids.edge_report(F)['open'], 0)
            self.assertTrue(built.rails[0].closed)

    def test_an_outline_turning_in_tighter_than_the_deck_or_bulging_tighter_than_the_reach_is_refused(self):
        for radii, word in (([4.5, 4.5, 4.5, .8, 4.5], 'inward'), ([2.5, 4.5, 4.5, 2.5, 4.5], 'bulges')):
            with self.assertRaises(ValueError) as e:
                pr.bowl(pr.Rounded(KIDNEY, radii, closed=True), floor_y=-3., depth=3., radius=3., deck=1.2)
            self.assertIn(word, str(e.exception))


class SolidTests(unittest.TestCase, Common):
    def test_a_ledge_has_a_ridable_level_top_a_footprint_seam_and_a_rail(self):
        built = pr.ledge(pr.Rounded([(0, 0), (8, 0), (8, .6), (0, .6)], .1, closed=True), support_y=1., height=.45)
        self.assertSolid(built)
        mesh = built.mesh
        top = mesh.where(role=dsl.RIDING)
        self.assertAlmostEqual(top.V[:, 1].max(), 1.45, places=9)
        foot = mesh.seams['ledge.footprint']
        self.assertTrue(np.allclose(mesh.V[foot, 1], 1.))
        self.assertTrue(built.rails[0].closed)
        self.assertTrue(np.allclose(built.rails[0].points[:, 1], 1.45))
        self.assertGreaterEqual(solids.thickness(mesh, dsl.SIDE), .6 - 1e-5)

    def test_a_box_and_a_kinked_rail_are_closed(self):
        self.assertSolid(pr.box(0, 0, 3, 2, support_y=0., height=.4))
        mesh, rail = rails.round_rail(np.array([[0, .6, 0], [6, .6, 0], [10, -.6, 0.]]),
                                      ground=lambda x, z: np.where(x < 6, 0., -.3 * (x - 6)))
        self.assertGreater(solids.check_closed(mesh), 0)
        self.assertTrue(np.allclose(np.linalg.norm(np.diff(rail.points, axis=0), axis=1).max(), .5, atol=.01))


def quality(mesh):
    t = mesh.triangles()
    l2 = ((t[:, [1, 2, 0]] - t) ** 2).sum(-1).sum(1)
    return 4 * np.sqrt(3) * mesh.areas() / np.maximum(l2, 1e-300)


class ShapeTests(unittest.TestCase):
    def test_every_drawn_face_of_every_primitive_is_well_shaped(self):
        k, l = additions.RAMPS['pool_gap_kicker'][2], additions.RAMPS['pool_gap_landing'][2]
        built = [
            pr.jump_line(Line((1144., 931.4), (1380., 902.6)), pr.from_additions(*k), pr.from_additions(*l), 1.5, 7.,
                         ground=-27., right=pr.Side('curb', .4, .3)),
            pr.quarter_pipe(Line((0., 0.), (12., 0.)), floor_y=0., height=4., radius=3.5, deck=1.5),
            pr.bank(Line((0., 0.), (12., 0.)), foot_y=0., height=2., degrees=30.),
            pr.hip((10., 0.), ((0., 0.), (10., 10.)), foot_y=0., height=1.5, degrees=30.),
            pr.snake_run(Spline([(0, 0), (15, 6), (30, 0), (45, -6), (60, 0)]), width=3., wall=1.5, radius=3.5),
            pr.bowl(pr.Rounded(KIDNEY, [4.5, 4.5, 4.5, 2.5, 4.5], closed=True), floor_y=-3., depth=3., radius=3.),
            pr.ledge(pr.Rounded([(0, 0), (8, 0), (8, .6), (0, .6)], .1, closed=True), support_y=0., height=.45),
        ]
        for b in built:
            drawn = b.mesh.subset(b.mesh.role != dsl.ROLE[dsl.BASE])
            self.assertGreaterEqual(quality(drawn).min(), .01, b.mesh.features)


class GroundTests(unittest.TestCase):
    def test_on_the_ground_a_feature_is_open_only_along_its_foot_loops_on_the_ground(self):
        ground = lambda x, z: -.02 * np.asarray(x)
        k, l = additions.RAMPS['pool_gap_kicker'][2], additions.RAMPS['pool_gap_landing'][2]
        built = [pr.jump_line(Line((0., 0.), (200., 0.)), pr.from_additions(*k), pr.from_additions(*l), 1.5, 7.,
                              ground=lambda x, z: np.full(np.shape(x), -27.), on_ground=True),
                 pr.bowl(pr.Rounded(KIDNEY, 4.5, closed=True), floor_y=-3., depth=3., radius=3., ground=-1.,
                         on_ground=True)]
        built.append(pr.quarter_pipe(Line((0., 0.), (12., 0.)), floor_y=0., height=3., radius=3.5, ground=ground,
                                     on_ground=True))
        for b in built:
            self.assertTrue(b.foot)
            for loop in b.foot:
                self.assertGreaterEqual(len(loop), 3)
        # the bowl's foot is its deck's outer foot, on the ground at -1
        self.assertEqual(len(built[1].foot), 1)
        self.assertTrue(np.allclose(built[1].foot[0][:, 1], -1.))


class AssemblyTests(unittest.TestCase):
    def test_a_quarter_pipe_a_snake_and_a_bowl_concat_and_validate(self):
        from craterpark.v2 import validate
        built = pr.Built.concat([
            pr.quarter_pipe(Line((0., 0.), (12., 0.)), floor_y=0., height=3., radius=3.5, feature='qp'),
            pr.snake_run(Spline([(0, 30), (15, 36), (30, 30)]), width=3., wall=1.5, radius=3.5, feature='snake'),
            pr.bowl(pr.Rounded([(40, 0), (60, 0), (60, 14), (51, 9), (40, 14)], 4.5, closed=True), floor_y=-3.,
                    depth=3., radius=3., feature='bowl')])
        mesh = built.mesh
        self.assertEqual(mesh.features, ('qp', 'snake', 'bowl'))
        self.assertLess(int(mesh.feature.max()), len(mesh.features))
        report, _ = validate.validate_park(dsl.Park(mesh, built.rails), log=lambda *a: None,
                                           skip=('ownership', 'uv_stretch'))
        checks = report['checks']
        for name in ('topology', 'overlaps', 'buried', 'thin_walls', 'slivers', 'facets', 'outlines'):
            self.assertTrue(checks[name]['ok'], (name, checks[name].get('failures', [])[:2]))

    def test_a_quarter_pipe_on_a_curve_tighter_than_its_reach_is_refused_with_a_reason(self):
        with self.assertRaises(ValueError) as e:
            pr.quarter_pipe(pr.Rounded([(0, 0), (10, 0), (10, 10)], 2.), floor_y=0., height=3., radius=3.5, side=-1)
        self.assertIn('fold', str(e.exception))


if __name__ == '__main__':
    unittest.main()
