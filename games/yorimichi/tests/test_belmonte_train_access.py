"""The Belmonte train against the playable characters, and who may walk where (world/train/access.py)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from train import access as A  # noqa: E402
from train import layout as L  # noqa: E402


class Players(unittest.TestCase):
    def test_the_walking_checks_are_wider_than_every_player(self):
        ps = A.players()
        self.assertEqual({p[0] for p in ps} >= {'cairo', 'paul', 'modori', 'nox'}, True)
        for who, _, radius, _ in ps:
            self.assertLessEqual(radius, L.HUMAN['radius'], who)     # layout.check() walks at HUMAN's radius
        self.assertEqual(min(p[2] for p in ps), L.CAIRO['radius'])

    def test_every_vehicle_fits_every_player(self):
        for c in L.vehicles():
            with self.subTest(c.name):
                self.assertEqual(A.check_fit(c), [])

    def test_a_low_net_is_caught(self):
        c = L.second_class()
        for m in c.mounts:
            if m.kind == 'rack':
                m.z -= .15
        self.assertTrue(any('RackNets' in b for b in A.check_fit(c)))


class Access(unittest.TestCase):
    def test_the_rules_hold(self):
        self.assertEqual(A.check_access(), [])

    def test_second_class_is_on_its_own(self):
        groups = [sorted(g) for g in A.passenger_groups()]
        self.assertIn(['second-class'], groups)
        self.assertIn(['first-class', 'restaurant'], groups)
        self.assertFalse(any(A.ACCESS[v] == 'staff' for g in A.passenger_groups() for v in g))

    def test_locked_doors(self):
        locked = set(A.locked_gangways())
        self.assertEqual(locked, {('first-class', 'gangway-door-a'), ('second-class', 'gangway-door-b'),
                                  ('second-class', 'gangway-door-a'), ('brake-van', 'gangway-door-b'),
                                  ('baggage-van', 'gangway-door-a'), ('restaurant', 'gangway-door-b')})
        for v, door in locked:
            c = next(c for c in L.vehicles() if c.name == v)
            self.assertIn(door, {d.name for d in c.doors}, (v, door))

    def test_staff_can_still_walk_through(self):
        joined = {(f, r) for f, r, _, joined, _ in A.junctions() if joined}
        self.assertTrue({('baggage-van', 'restaurant'), ('restaurant', 'first-class'), ('first-class', 'second-class'),
                         ('second-class', 'brake-van'), ('locomotive', 'tender')} <= joined)

    def test_opening_second_class_is_caught(self):
        saved = A.ACCESS['second-class']
        try:
            A.ACCESS['second-class'] = 'first'
            self.assertTrue(A.check_access() or len(A.passenger_groups()) == 1)
            self.assertIn(['first-class', 'restaurant', 'second-class'], [sorted(g) for g in A.passenger_groups()])
        finally:
            A.ACCESS['second-class'] = saved


if __name__ == '__main__':
    unittest.main()
