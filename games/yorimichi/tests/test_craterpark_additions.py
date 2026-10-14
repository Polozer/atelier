"""Crater Park's added pieces and its tunnel kept open (world/regions/craterpark/additions.py, tunnel.py)."""
from pathlib import Path
import math
import sys
import unittest

import numpy as np

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
from craterpark import additions, grind, tunnel  # noqa: E402


def quad(a, b, c, d):
    return [[a, c, b], [a, d, c]]


def floor(x0, z0, x1, z1, y=0.):
    return quad((x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1))


def box(x0, y0, z0, x1, y1, z1):
    """A closed box's six faces."""
    c = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    return (quad(c[0], c[4], c[6], c[2]) + quad(c[1], c[3], c[7], c[5]) + quad(c[0], c[1], c[5], c[4])
            + quad(c[2], c[6], c[7], c[3]) + quad(c[0], c[2], c[3], c[1]) + quad(c[4], c[5], c[7], c[6]))


def tube(radius, length, sides=24):
    """A round tunnel along x, from 0 to `length`, its axis at height `radius`."""
    t = []
    for k in range(sides):
        a0, a1 = 2 * math.pi * k / sides, 2 * math.pi * (k + 1) / sides
        p = lambda x, a: (x, radius - radius * math.cos(a), radius * math.sin(a))
        t += quad(p(0, a0), p(length, a0), p(length, a1), p(0, a1))
    return np.asarray(t, 'f8')


class TunnelTests(unittest.TestCase):
    def test_the_solid_in_a_tunnel_is_cut_out_and_the_block_round_it_kept(self):
        bore = tube(3., 20.)
        inside = np.asarray(box(2, .5, -1, 18, 4, 1), 'f8')              # solid filling the bore
        outside = np.asarray(box(2, 7, -1, 18, 9, 1) + box(-10, 0, -10, -5, 5, 10), 'f8')  # over the roof, beside it
        cut, parent, corners = tunnel.carve(np.concatenate([inside, outside]), tunnel.tunnels([bore]))
        self.assertTrue(cut[:len(inside)].all())
        self.assertFalse(cut[len(inside):].any())

    def test_a_long_face_crossing_the_bore_keeps_its_ends(self):
        bore = tube(3., 20.); bores = tunnel.tunnels([bore])
        sliver = np.asarray([[(10, -8, -.4), (10, 9, -.4), (10.3, -8, .4)]], 'f8')   # from under the floor to over the roof
        cut, parent, corners = tunnel.carve(sliver, bores)
        self.assertTrue(cut[0])
        parts = np.einsum('mij,mjd->mid', corners, sliver[parent])
        centres = parts.mean(1)
        self.assertFalse(tunnel.in_bore(centres, [bore]).any())        # nothing left in the bore
        self.assertTrue((centres[:, 1] < 0).any() and (centres[:, 1] > 6).any())     # both ends kept
        area = lambda t: np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() / 2
        self.assertLess(area(parts), area(sliver))

    def test_under_a_deck_is_no_tunnel(self):
        deck = np.asarray(floor(-5, -5, 5, 5, 4.) + floor(-5, -5, 5, 5, 0.), 'f8')    # open on every side
        block = np.asarray(box(-1, 1, -1, 1, 3, 1), 'f8')
        self.assertEqual(tunnel.tunnels([deck]), [])
        self.assertFalse(tunnel.carve(block, [(deck, np.zeros((1, 3)))])[0].any())


class SnakeTests(unittest.TestCase):
    def setUp(self):
        # Two floor slabs at 0 m with a 5 m slot between them along z; the hillside 20 m down.
        self.riding = np.asarray(floor(0, 0, 30, 10) + floor(0, 15, 30, 25) + floor(0, 10, 3, 15) + floor(27, 10, 30, 15), 'f8')
        self.solid = np.asarray(floor(-10, -10, 40, 35, -20.), 'f8')

    def test_a_slot_holds_a_channel_meeting_the_floor_level(self):
        v, f, uv = additions.snake_channels(self.riding, self.solid, (-2, -2, 32, 27), 0.)['channels']
        self.assertEqual(len(uv), len(v))
        mid = (v[:, 2] > 12.4) & (v[:, 2] < 12.6) & (v[:, 0] > 8) & (v[:, 0] < 22)
        self.assertAlmostEqual(float(v[mid, 1].min()), -min(additions.CHANNEL, additions.STEEPEST * min(2.5, additions.TRANSITION)), delta=.05)
        edge = (np.abs(v[:, 2] - 10) < .01) | (np.abs(v[:, 2] - 15) < .01)
        self.assertLess(float(np.abs(v[edge, 1]).max()), .02)       # flush with the floor at both edges
        n = grind.unit_normals(v[f].astype('f8'))
        self.assertTrue((n[:, 1] > 0).all())                         # faces up
        self.assertLess(float(v[:, 1].max()), .001)                  # nothing rises over the floor

    def test_a_bridge_over_the_slot_stays_and_the_channel_rises_to_it(self):
        bridge = np.asarray(box(14.5, -.3, 9.5, 15.5, 0, 15.5), 'f8')
        v, f, uv = additions.snake_channels(self.riding, np.concatenate([self.solid, bridge]), (-2, -2, 32, 27), 0.)['channels']
        under = (np.abs(v[:, 0] - 15) < .2) & (v[:, 2] > 11) & (v[:, 2] < 14)
        self.assertLess(float(np.abs(v[under, 1]).max()), .02)      # flush with the bridge's top
        far = (np.abs(v[:, 0] - 6) < .2) & (np.abs(v[:, 2] - 12.5) < .2)
        self.assertLess(float(v[far, 1].min()), -.9)                # deep again away from it


    def test_a_deck_wall_gets_a_transition_at_its_foot_up_to_its_edge(self):
        # A deck 2.5 m up beside the floor (a vertical wall at x 10), no slot.
        riding = np.asarray(floor(0, 0, 10, 10) + floor(10, 0, 20, 10, 2.5), 'f8')
        solid = np.asarray(floor(-10, -10, 30, 30, -20.), 'f8')
        made = additions.snake_channels(riding, solid, (-2, -2, 22, 12), 0., feet=True)
        v, f, uv = made['channels']                                         # the curve, in concrete
        used = v[np.unique(f)]
        if 'floor' in made:                                                 # a skirt, if any, lies flat on the floor
            self.assertLess(float(np.abs(v[made['floor'][1]][:, :, 1]).max()), additions.LIFTED * 2)
        self.assertAlmostEqual(float(used[:, 1].max()), 2.5, delta=.01)          # reaches the deck's edge
        foot = used[(np.abs(used[:, 2] - 5) < .2) & (used[:, 0] < 10)]
        self.assertLess(float(foot[:, 0].min()), 10 - 2.)                       # starts about its radius out
        n = grind.unit_normals(v[f].astype('f8'))
        self.assertTrue((n[:, 1] > 0).all())


    def test_a_filled_slot_at_a_walls_foot_is_one_curve_from_the_floor_to_the_deck(self):
        # The floor at 0 m, a 3 m slot along the foot of a deck 2.5 m up, the hillside 20 m down.
        riding = np.asarray(floor(0, 0, 30, 10) + floor(0, 10, 5, 13) + floor(25, 10, 30, 13) + floor(0, 13, 30, 20, 2.5), 'f8')
        solid = np.asarray(floor(-10, -10, 40, 35, -20.), 'f8')
        made = additions.snake_channels(riding, solid, (-2, -2, 32, 22), 0., channel=0., feet=True)
        v = np.concatenate([m[0][m[1]].reshape(-1, 3) for m in made.values()])
        self.assertGreater(float(v[:, 1].min()), -.001)                         # no gutter: nothing under the floor
        cut = v[(np.abs(v[:, 0] - 15) < .01) & (v[:, 2] > 7) & (v[:, 2] < 13.01)]
        cut = cut[np.argsort(cut[:, 2])]
        self.assertTrue((np.diff(cut[:, 1]) > -1e-4).all())                     # rises all the way across the slot
        self.assertAlmostEqual(float(cut[-1, 1]), 2.5, delta=.05)               # up to the deck's edge
        self.assertLess(float(cut[0, 1]), .01)                                  # from the floor


    def test_a_rail_on_the_floor_keeps_its_faces(self):
        # A 0.3 m wide rail 1.2 m up on the floor, 6 m from a deck 2.5 m up: the deck's foot gets a transition, the rail none.
        riding = np.asarray(floor(0, 0, 30, 20) + floor(0, 20, 30, 30, 2.5) + floor(10, 8, 20, 8.3, 1.2), 'f8')
        solid = np.asarray(floor(-10, -10, 40, 40, -20.), 'f8')
        made = additions.snake_channels(riding, solid, (-2, -2, 32, 32), 0., channel=0., feet=True)
        v = np.concatenate([m[0][m[1]].reshape(-1, 3) for m in made.values()])
        near_deck = v[(v[:, 2] > 18) & (v[:, 2] < 20)]
        self.assertGreater(float(near_deck[:, 1].max()), 1.)                    # the deck's transition
        by_rail = v[(v[:, 0] > 9) & (v[:, 0] < 21) & (v[:, 2] > 7) & (v[:, 2] < 9.3)]
        self.assertLess(float(by_rail[:, 1].max()) if len(by_rail) else 0., .01)   # nothing rises on the rail


class SolidifyTests(unittest.TestCase):
    def test_a_wall_ending_in_the_air_gets_a_cap_and_a_back_wall(self):
        # A curved sheet (a quarter pipe 2 m high along z) standing on the ground, open behind.
        t = []
        for k in range(8):
            a0, a1 = math.pi / 2 * k / 8, math.pi / 2 * (k + 1) / 8
            p = lambda z, a: (2 * math.sin(a), 2 - 2 * math.cos(a), z)      # rises from x 0 to the vertical at x 2
            t += quad(p(0, a0), p(6, a0), p(6, a1), p(0, a1))
        piece = np.asarray(t, 'f8')
        ground = np.asarray(floor(-5, -5, 10, 10, 0.), 'f8')
        heights = grind.heights(np.concatenate([piece, ground]))
        v, f, uv = additions.solidify(piece, heights, np.concatenate([piece, ground]))
        n = grind.unit_normals(v[f].astype('f8'))
        caps = f[n[:, 1] > .9]
        self.assertTrue(len(caps))
        top = v[caps].reshape(-1, 3)
        self.assertTrue(np.allclose(top[:, 1], 2., atol=1e-6))       # level with the coping
        self.assertGreater(float(top[:, 0].max()), 2 + additions.THICK - 1e-6)   # behind the wall, away from the ramp
        self.assertLess(float(v[:, 1].min()), 0.)                    # the back wall goes down into the ground



class CopingTests(unittest.TestCase):
    def test_a_tube_runs_along_the_line_its_top_just_over_the_deck_facing_out(self):
        line = np.stack([np.linspace(0, 5, 11), np.full(11, 1.), np.zeros(11)], 1)
        v, f, uv = additions.coping([line])
        self.assertAlmostEqual(float(v[:, 1].max()), 1 + additions.COPING_PROUD, delta=.002)
        self.assertAlmostEqual(float(v[:, 0].max()), 5., places=4)
        t = v[f].astype('f8'); n = grind.unit_normals(t)
        axis = np.stack([t.mean(1)[:, 0], np.full(len(t), 1 + additions.COPING_PROUD - additions.COPING_RADIUS), np.zeros(len(t))], 1)
        self.assertTrue(((n * (t.mean(1) - axis)).sum(1) > 0).all())


if __name__ == '__main__':
    unittest.main()
