import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))

import yori  # noqa: E402,F401
from train import collision as CO  # noqa: E402
from train import layout as L  # noqa: E402


class Collision(unittest.TestCase):
    @unittest.expectedFailure      # until the collision fix list lands (furniture, gangways, doors, lookout, seats)
    def test_every_vehicle_is_clean(self):
        for c in L.vehicles():
            with self.subTest(vehicle=c.name):
                self.assertEqual(CO.check_collision(c, CO.collision_boxes(c)), [])

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
