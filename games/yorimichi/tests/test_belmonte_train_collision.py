import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))

import yori  # noqa: E402,F401
from train import access as A  # noqa: E402
from train import collision as CO  # noqa: E402
from train import layout as L  # noqa: E402


class Collision(unittest.TestCase):
    @unittest.expectedFailure      # until the collision fix list lands (furniture, gangways, doors, lookout, seats)
    def test_every_vehicle_is_clean(self):
        for c in L.vehicles():
            with self.subTest(vehicle=c.name):
                self.assertEqual(CO.check_collision(c, CO.collision_boxes(c)), [])

    def test_only_modelled_reservations_get_collision(self):
        # a box with nothing in it yet (WC pan, bar, back bar, range, stoves) must not be an invisible wall
        for c in L.vehicles():
            if c.body.kind in ('tender', 'locomotive'):
                continue
            parts = {n for n, _ in CO.collision_boxes(c)}
            for r in c.reservations:
                if r.z0 - L.FLOOR_Z < 1.0:
                    self.assertEqual(r.name in parts, r.kind in CO.MODELLED, (c.name, r.name, r.kind))

    def test_gangways_overlap_past_the_buffers_and_locked_ones_are_shut_in_their_own_group(self):
        for c in L.vehicles():
            boxes = dict(CO.collision_boxes(c))
            for s, end in ((-1, 'a'), (1, 'b')):
                if c.body.end(s) != 'gangway':
                    continue
                for part in ('floor', 'side-l', 'side-r', 'roof'):
                    q = boxes[f'gangway-{end}-{part}']
                    self.assertAlmostEqual(q[1] if s > 0 else -q[0], abs(c.body.buffer(s)) + CO.GANGWAY_OVERLAP, msg=(c.name, end, part))
        locked = A.locked_gangways()
        self.assertTrue(locked)
        for v, door in locked:
            c = next(c for c in L.vehicles() if c.name == v)
            self.assertIn(f'gangway-lock-{door[-1]}', dict(CO.collision_boxes(c)), (v, door))
            self.assertEqual(CO.group(f'gangway-lock-{door[-1]}'), 'gangway-lock')
            named = [n for n, p, g, _ in CO.named_boxes(c, 'SM') if g == 'gangway-lock']
            self.assertTrue(named and all(n.startswith('COL_SM_gangway-lock-') for n in named))

    def test_every_door_and_gate_has_its_own_switchable_box_and_interact_points(self):
        for c in L.vehicles():
            boxes = dict(CO.collision_boxes(c))
            ds = CO.doors(c)
            extra = [d for d in ds if d['kind'] in ('gate', 'staff')]       # not layout doors: no leaf in c.doors
            self.assertEqual(len(ds), len(c.doors) + len(extra), c.name)
            self.assertEqual(len({d['part'] for d in ds}), len(ds), c.name)      # one box per door, opened one at a time
            for d in ds:
                self.assertEqual(boxes[d['part']], d['box'], (c.name, d['id']))
                self.assertEqual(CO.group(d['part']), 'gangway-lock' if d['locked'] else 'door', (c.name, d['id']))
                self.assertEqual(d['opens'], 'station' if d['kind'] in ('exterior', 'gate', 'staff') else 'any')
                self.assertEqual(d['default'], 'closed')
                self.assertEqual(len(d['handles']), 2)
                q = d['box']
                for h in d['handles']:                  # the prompt points face the leaf, one on each side
                    x, y, _ = h['point']
                    self.assertTrue(q[0] - .5 <= x <= q[1] + .5 and q[2] - .5 <= y <= q[3] + .5, (c.name, d['id'], h))
            self.assertEqual({d['door'] for d in ds if d['locked']},
                             {door for v, door in A.locked_gangways() if v == c.name})
            for name, sy, x0, x1, z0, z1 in L.exterior_openings(c):
                q = boxes[f'door-{name}']
                self.assertEqual((q[0], q[1], q[4], q[5]), (x0, x1, z0, z1), (c.name, name))
            for i, r in enumerate(L.railings(c.body)):
                q = boxes[f'railing-{i}-above']
                self.assertEqual(q[:4], r)
                self.assertLessEqual(q[4], L.FLOOR_Z + 1.05)
                self.assertGreaterEqual(q[5], L.ROOF_TOP)
                self.assertEqual(CO.group(f'railing-{i}-above'), 'fixed')
            named = [n for n, p, g, _ in CO.named_boxes(c, 'SM') if g == 'door']
            self.assertTrue(all(n.startswith('COL_SM_door-') for n in named))
        gates = {d['id']: d for d in CO.doors(L.brake_van()) if d['kind'] == 'gate'}
        self.assertEqual(sorted(gates), ['gate-al', 'gate-ar'])
        for d in gates.values():
            self.assertGreaterEqual(d['box'][5], L.ROOF_TOP)

    def test_the_cab_floor_and_the_footplate_meet_past_the_buffers_and_the_cab_doors_are_staff_doors(self):
        loco, tender = L.locomotive(), L.tender()
        lf, tf = dict(CO.collision_boxes(loco))['floor'], dict(CO.collision_boxes(tender))['floor']
        self.assertLessEqual(lf[0], loco.body.buffer_a - .01)
        self.assertGreaterEqual(tf[1], tender.body.buffer_b + .01)
        tb = dict(CO.collision_boxes(tender))
        for side in 'lr':
            self.assertGreaterEqual(tb[f'handrail-{side}'][1], L.TENDER_FALL_PLATE)
        ds = {d['id']: d for d in CO.doors(loco)}
        self.assertEqual(sorted(ds), ['cab-l', 'cab-r'])
        for d in ds.values():
            self.assertEqual((d['kind'], d['opens'], CO.group(d['part'])), ('staff', 'station', 'door'))

    def test_a_shut_inside_door_does_not_cut_the_walk_but_a_missing_one_is_caught(self):
        c = L.first_class()
        self.assertEqual(CO.check_collision(c, CO.collision_boxes(c)), [])
        boxes = [(n, q) for n, q in CO.collision_boxes(c) if n != 'door-cabin-2']
        self.assertIn('door-cabin-2 has no collision', CO.check_collision(c, boxes))

    def test_a_missing_door_is_caught(self):
        c = L.brake_van()
        boxes = [(n, q) for n, q in CO.collision_boxes(c) if n != 'door-gate-al']
        self.assertIn('door-gate-al has no collision', CO.check_collision(c, boxes))

    def test_a_missing_bench_is_caught(self):
        c = L.second_class()
        boxes = [(n, q) for n, q in CO.collision_boxes(c) if not n.startswith('bench-1la')]
        self.assertTrue(any(m.startswith('bench-1la ') for m in CO.check_collision(c, boxes)))

    def test_an_open_gangway_side_is_caught(self):
        c = L.first_class()
        bf, fx = c.body.buffer(1), c.body.face(1)
        mid, y = (bf + fx) / 2, L.GANGWAY_W / 2 + .07
        boxes = [(n, q) for n, q in CO.collision_boxes(c)
                 if not (q[0] <= mid <= q[1] and q[2] <= y <= q[3] and q[4] <= L.FLOOR_Z + 1. <= q[5])]
        self.assertTrue(any(m.startswith('gangway b: no side+') for m in CO.check_collision(c, boxes)))

    def test_a_closed_lookout_ceiling_is_caught(self):
        c = L.brake_van()
        x0, x1 = c.body.cupola
        boxes = CO.collision_boxes(c) + [('ceiling', (x0, x1, -L.IN, L.IN, L.CEIL_SPRING, L.CEIL_SPRING + .15))]
        self.assertIn('the ceiling collision closes the lookout well', CO.check_collision(c, boxes))


if __name__ == '__main__':
    unittest.main()
