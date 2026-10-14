import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))

import yori  # noqa: E402,F401
from train import access as A  # noqa: E402
from train import collision as CO  # noqa: E402
from train import layout as L  # noqa: E402


class Collision(unittest.TestCase):
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
                    has = any(n == r.name or n.startswith(r.name + '-') for n in parts)    # or in pieces (the treads)
                    self.assertEqual(has, r.kind in CO.MODELLED, (c.name, r.name, r.kind))

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

    def test_the_lookout_is_open_through_the_ceiling_and_closed_above(self):
        c = L.brake_van()
        boxes = CO.collision_boxes(c)
        x0, x1, hw, _ = L.lookout_well(c.body)
        cx, cy = (x0 + x1) / 2, 0.
        for p, q in boxes:              # nothing between the guard's room and the lookout's roof over the well
            if q[0] < cx < q[1] and q[2] < cy < q[3] and q[5] > L.FLOOR_Z + 2.5:
                self.assertTrue(p.startswith('lookout-roof'), p)
        parts = dict(boxes)
        for p in ('lookout-wall-a', 'lookout-wall-b', 'lookout-wall-l', 'lookout-wall-r', 'lookout-roof',
                  'cupola-steps-lower', 'cupola-steps-upper', 'lookout-seat'):
            self.assertIn(p, parts)
        self.assertNotIn('cupola-steps', parts)          # two treads, not one block up to the upper tread
        self.assertAlmostEqual(parts['cupola-steps-lower'][5], L.FLOOR_Z + .30)
        self.assertAlmostEqual(parts['lookout-seat'][5], L.FLOOR_Z + L.LOOKOUT_SEAT[4])

    def test_seat_markers_rest_on_their_collision_tops(self):
        for c in L.vehicles():
            boxes = CO.collision_boxes(c)
            for st in c.seats:
                tops = [q[5] for _, q in boxes if q[0] <= st.x <= q[1] and q[2] <= st.y <= q[3] and q[4] < st.z]
                self.assertTrue(tops, (c.name, st.id))
                self.assertTrue(-1e-6 <= st.z - max(tops) <= CO.SEAT_GAP, (c.name, st.id, st.z - max(tops)))

    def test_first_class_sofa_markers_sit_on_the_cushion_in_front_of_the_back(self):
        # the same hip-to-backrest distance as the restaurant banquettes, from the back (or the throw pillow on the
        # sofa's own -x half), whichever way the sofa faces
        c = L.first_class()
        sofas = {p.id: p for p in c.placements if p.asset == 'first-class-sofa'}
        self.assertEqual(sum(st.furniture in sofas for st in c.seats), 16)
        sides = []
        for st in c.seats:
            p = sofas[st.furniture]
            self.assertAlmostEqual(st.z, L.FLOOR_Z + .40)
            a = math.radians(-p.yaw)
            dx, dy = st.x - p.x, st.y - p.y
            u, v = dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)
            face = L.SOFA_BACK_FACE['pillow' if u < 0 else 'plain']
            self.assertAlmostEqual(face - v, L.SEAT_FROM_BACK, places=3)
            self.assertAlmostEqual(abs(u), .46, places=3)
            sides.append(u < 0)
        self.assertEqual(sides.count(True), 8)

    def test_a_seat_marker_against_its_backrest_is_caught(self):
        c = L.first_class()
        st = c.seats[1]
        back = dict(CO.collision_boxes(c))[f'{st.furniture}-back']
        x = back[0] - .05 if st.x < back[0] else back[1] + .05          # 5 cm in front of the back slab
        c.seats[1] = type(st)(st.id, st.furniture, x, st.y, st.z, st.yaw)
        self.assertTrue(any(m.startswith(f'seat {st.id}:') and 'backrest' in m for m in CO.check_collision(c, CO.collision_boxes(c))))

    def test_a_sunken_seat_marker_is_caught(self):
        c = L.first_class()
        st = c.seats[0]
        c.seats[0] = type(st)(st.id, st.furniture, st.x, st.y, st.z - .05, st.yaw)
        self.assertTrue(any(m.startswith(f'seat {st.id}:') for m in CO.check_collision(c, CO.collision_boxes(c))))

    def test_interior_volumes_tag_every_room_gangway_and_footplate_no_sprint(self):
        for c in L.vehicles():
            vols = L.interior_volumes(c)
            names = {v['name'] for v in vols}
            self.assertTrue(all(v['tags'] == ['interior', 'no_sprint', 'no_climb'] for v in vols))
            self.assertTrue({r.name for r in c.rooms} <= names, c.name)
            for v in vols:
                x0, x1, y0, y1, z0, z1 = v['box']
                floor = L.CEIL_SPRING if v['kind'] == 'lookout' else L.FLOOR_Z      # the lookout is up in the roof
                self.assertTrue(x0 < x1 and y0 < y1 and z0 <= floor < z1, (c.name, v['name']))
            for s, end in ((-1, 'a'), (1, 'b')):
                if c.body.end(s) == 'gangway':
                    q = next(v['box'] for v in vols if v['name'] == f'gangway-{end}')
                    self.assertGreaterEqual(q[1] if s > 0 else -q[0], abs(c.body.buffer(s)))
        self.assertIn('lookout', {v['name'] for v in L.interior_volumes(L.brake_van())})
        self.assertLessEqual(L.interior_volumes(L.locomotive())[0]['box'][0], L.locomotive().body.buffer_a)
        self.assertGreaterEqual(L.interior_volumes(L.tender())[0]['box'][1], L.tender().body.buffer_b)

    def test_each_vehicle_has_a_no_climb_exterior_over_its_body_and_roof(self):
        for c in L.vehicles():
            (v,) = L.exterior_volumes(c)
            x0, x1, y0, y1, z0, z1 = v['box']
            self.assertEqual((v['name'], v['tags']), ('train_exterior', ['no_climb']))
            self.assertLessEqual(x0, c.body.buffer_a)
            self.assertGreaterEqual(x1, c.body.buffer_b)
            for i in L.interior_volumes(c):                   # it holds the whole inside too
                q = i['box']
                self.assertTrue(x0 - CO.GANGWAY_OVERLAP <= q[0] and q[1] <= x1 + CO.GANGWAY_OVERLAP and y0 <= q[2] and q[3] <= y1 and q[5] <= z1, (c.name, i['name']))
        self.assertGreaterEqual(L.exterior_volumes(L.brake_van())[0]['box'][5], L.lookout_top(L.brake_van().body)[1])

    def test_every_passenger_door_and_gate_has_a_boarding_record(self):
        for c in L.vehicles():
            recs = {b['id']: b for b in CO.boarding(c)}
            want = {d['id'] for d in CO.doors(c) if d['kind'] in ('exterior', 'gate') and not d['id'].startswith('cargo')}
            self.assertEqual(set(recs), want, c.name)
            parts = dict(CO.collision_boxes(c))
            for b in recs.values():
                with self.subTest(vehicle=c.name, door=b['id']):
                    sy = b['side']
                    self.assertIn(b['door'], parts)
                    self.assertEqual(b['opens'], 'station')
                    (up, low) = b['treads']
                    self.assertGreater(up['top_z'], low['top_z'])
                    self.assertLess(up['top_z'], L.FLOOR_Z)
                    self.assertTrue(abs(b['outside'][1]) > L.HALF and abs(b['inside'][1]) < L.IN)   # either side of the wall
                    self.assertEqual(b['outside'][1] * sy > 0, True)
                    self.assertAlmostEqual(b['inside'][2], L.FLOOR_Z)
                    fy = -math.cos(math.radians(b['board_yaw']))                  # boarding faces into the coach
                    self.assertEqual(fy, -sy)
                    self.assertEqual((b['board_yaw'] + 180) % 360, b['alight_yaw'])
                    xs = [b['outside'][0], b['inside'][0]]
                    self.assertTrue(all(up['box'][0] <= x <= up['box'][1] for x in xs))
        self.assertEqual({b['kind'] for b in CO.boarding(L.brake_van())}, {'exterior', 'gate'})

    def test_a_reachable_place_outside_the_volumes_is_caught(self):
        c = L.first_class()
        L_iv = L.interior_volumes
        try:
            L.interior_volumes = lambda c: [v for v in L_iv(c) if not v['name'].startswith('gangway')]
            self.assertTrue(any('outside every interior volume' in m for m in CO.check_collision(c, CO.collision_boxes(c))))
        finally:
            L.interior_volumes = L_iv

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
