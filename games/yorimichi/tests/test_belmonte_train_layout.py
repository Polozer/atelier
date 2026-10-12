"""The Belmonte train's measured plan (world/train/layout.py): envelope, rooms, circulation and furniture fits."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from train import layout as L  # noqa: E402


class Envelope(unittest.TestCase):
    def test_widths_add_up(self):
        self.assertAlmostEqual(2 * L.IN, 3.45)
        self.assertAlmostEqual(L.CORRIDOR + L.PART + (L.IN - L.ROOM_Y), 3.45)
        self.assertGreaterEqual(L.CORRIDOR, 1.20)
        self.assertAlmostEqual(L.CLEAR, 2.30)
        self.assertAlmostEqual(2 * L.BUFFER_X, 24.0)

    def test_ceiling_and_roof(self):
        self.assertAlmostEqual(L.ceiling_z(0), L.CEIL_APEX)
        self.assertAlmostEqual(L.ceiling_z(L.IN), L.CEIL_SPRING)
        self.assertAlmostEqual(L.roof_z(0), L.ROOF_TOP)
        self.assertGreater(L.ceiling_z(L.CORR_Y), L.FLOOR_Z + L.DOOR_H + .1)


class Coaches(unittest.TestCase):
    def test_both_coaches_pass_their_checks(self):
        for c in L.coaches():
            self.assertEqual(L.check(c), [], c.name)

    def test_first_class(self):
        c = L.first_class()
        cabins = [r for r in c.rooms if r.kind == 'cabin']
        self.assertEqual(len(cabins), 4)
        self.assertTrue(all(abs(r.y1 - r.y0 - L.CABIN_W) < 1e-9 for r in cabins))
        self.assertEqual(len(c.seats), 16)
        self.assertEqual(sum(p.asset == 'first-class-sofa' for p in c.placements), 8)
        # the bays fill the span between the vestibule bulkheads exactly, symmetric about the centre
        xs = sorted((r.x0, r.x1) for r in c.rooms if r.y0 == L.ROOM_Y)
        self.assertAlmostEqual(xs[0][0], -L.SPAN_X)
        self.assertAlmostEqual(xs[-1][1], L.SPAN_X)
        self.assertAlmostEqual(xs[0][0] + xs[-1][1], 0)

    def test_restaurant(self):
        c = L.restaurant()
        aisle = min(min(abs(v) for v in L.footprint(p)[2:]) for p in c.placements if p.asset == 'restaurant-banquette')
        self.assertGreaterEqual(2 * aisle, 1.15)
        self.assertEqual(sum(p.asset == 'restaurant-table' for p in c.placements), 8)
        self.assertEqual(len(c.seats), 16)
        bays = sorted((w for w in c.windows if w.side > 0 and w.sill == L.PANO_SILL), key=lambda w: w.x)
        self.assertEqual(len(bays), 5)
        # the panoramic bays are centred on the tables, and the piers between them sit behind the banquette backs
        tables = sorted({p.x for p in c.placements if p.asset == 'restaurant-table'})
        for t, w in zip(tables, bays):
            self.assertAlmostEqual(t, w.x)
        for a, b in zip(bays, bays[1:]):
            pier = (a.x + a.width / 2, b.x - b.width / 2)
            self.assertGreaterEqual(pier[1] - pier[0], L.PIER - 1e-6)
            backs = [p for p in c.placements if p.asset == 'restaurant-banquette' and p.y > 0 and pier[0] - .4 < p.x < pier[1] + .4]
            joint = (max(L.footprint(p)[0] for p in backs) + min(L.footprint(p)[1] for p in backs)) / 2 if len(backs) == 2 else None
            if joint is not None:
                self.assertTrue(pier[0] < joint < pier[1])

    def test_a_narrow_door_is_caught(self):
        c = copy.deepcopy(L.first_class())
        part = c.wall('corridor-partition')
        op = next(o for o in part.openings if o.name == 'door-cabin-2')
        op.a1 = op.a0 + .40
        self.assertIn('adult cannot reach cabin-2', L.check(c))

    def test_furniture_matches_the_contract(self):
        spec = {a['id']: a for a in L.contract()['assets']}
        for c in L.coaches():
            for p in c.placements:
                self.assertIn(p.asset, spec)
                self.assertIn(round(p.yaw) % 90, (0,))


if __name__ == '__main__':
    unittest.main()
