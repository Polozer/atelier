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


    def test_tender_couples_to_the_baggage_van_and_its_footplate_is_walkable(self):
        t = L.tender()
        self.assertEqual(L.check(t), [])
        self.assertAlmostEqual(t.body.length, L.TENDER_LENGTH)
        self.assertEqual((t.body.end_a, t.body.end_b), ('closed', 'footplate'))
        self.assertEqual(L.baggage_van().body.end_b, 'closed')
        lo, hi = t.body.walk_limits()
        self.assertGreater(hi - lo, 1.5)
        self.assertGreater(2 * t.body.walk_y, 2 * L.HUMAN['radius'] + .5)


    def test_locomotive_cab_is_walkable_and_its_controls_are_mounted(self):
        loco, tender = L.locomotive(), L.tender()
        self.assertEqual(L.check(loco), [])
        self.assertAlmostEqual(loco.body.length, L.LOCO_LENGTH)
        self.assertEqual(loco.body.end_a, tender.body.end_b)      # the cab's open back meets the tender's footplate
        controls = {m.id for m in loco.mounts if m.kind == 'control'}
        self.assertTrue({'regulator', 'reverser', 'brake', 'whistle', 'fire-door'} <= controls)
        from train import fittings as F
        lamp = next(m for m in loco.mounts if m.id == 'cab-lamp')
        self.assertAlmostEqual(lamp.z, L.cab_ceiling_z(lamp.y))   # hung from the roof, not in mid-air
        parts = {p.name: p for p in F.fittings(loco)}
        self.assertEqual(parts['Fittings_Lamps'].lods, (0,))
        self.assertEqual([s[0] for s in parts['Fittings_Lamps'].sockets], ['SOCKET_Light_CabLamp'])

    def test_cab_pipes_go_somewhere(self):
        # every run is axis-aligned, stays within the backhead's pipework (out of the crew's head room) and ends on a
        # Tripo pipe, a fitting, the boiler's back end or the footplate
        F, loco = L.FLOOR_Z, L.locomotive()
        runs = L.cab_pipes()
        ends = {(round(x, 3), round(s * y, 3), round(F + z, 3)) for s in (1, -1) for x, y, z, _ in L.BACKHEAD_FEET}
        ends |= {(L.BACKHEAD_STUBS[0], round(s * L.BACKHEAD_STUBS[1], 3), round(F + L.BACKHEAD_STUBS[2], 3)) for s in (1, -1)}
        fountain = next(r for r in runs if r['name'] == 'fountain')['pts']
        for run in runs:
            pts = run['pts']
            for a, b in zip(pts, pts[1:]):
                self.assertEqual(sum(abs(a[i] - b[i]) > 1e-9 for i in range(3)), 1, run['name'])
            for p in pts:
                self.assertGreaterEqual(p[0], L.BACKHEAD_X - L.PIPEWORK, run['name'])
                self.assertLess(p[0], L.CAB[1], run['name'])
            for end, p in zip(run['ends'], (pts[0], pts[-1])):
                if end == 'flange':     # on the boiler's back end or the footplate
                    self.assertTrue(abs(p[0] - L.CAB[1]) < .01 or abs(p[2] - F) < 1e-9, (run['name'], p))
                elif end == 'union':    # on a Tripo pipe end (a little inside it), the fountain or the whistle valve
                    on_fountain = abs(p[0] - fountain[0][0]) < 1e-9 and abs(p[2] - fountain[0][2]) < 1e-9 and abs(p[1]) <= fountain[1][1] + 1e-9
                    on_valve = abs(p[0] - L.WHISTLE_VALVE[0]) < 1e-9
                    on_tripo = any(abs(p[0] - e[0]) < 1e-3 and abs(p[1] - e[1]) < 1e-3 and -1e-3 < p[2] - e[2] < .02 for e in ends)
                    self.assertTrue(on_fountain or on_valve or on_tripo, (run['name'], p))
        whistle = next(m for m in loco.mounts if m.id == 'whistle')
        self.assertTrue(any(r['pts'][0][:2] == (L.WHISTLE_VALVE[0], whistle.y) for r in runs))
        self.assertEqual(sum(r['name'].startswith('injector') for r in runs), 4)


    def test_canteen_serving_line(self):
        import math
        c = L.second_class()
        m = {mt.id: mt for mt in c.mounts}
        for anchor in ('canteen-npc-spot', 'canteen-serve-point', 'canteen-queue'):
            self.assertIn(anchor, m)
        counter = next(p for p in c.placements if p.id == 'canteen-counter')
        x0, x1, y0, y1 = L.footprint(counter)
        serve = m['canteen-serve-point']
        self.assertTrue(x0 <= serve.x <= x1 and y0 <= serve.y <= y1)             # the tray lands on the counter
        # the counter passes through the hatch: body in the kitchen, its tray ledge out in the saloon, filling the opening
        wall = c.wall('canteen-front')
        hatch = next(o for o in wall.openings if o.name == 'canteen-hatch')
        self.assertEqual(counter.through, 'canteen-front')
        self.assertTrue(counter.x - L.COUNTER_BACK < wall.c0 and counter.x + L.COUNTER_BODY_FRONT > wall.c1)
        self.assertTrue(counter.y - L.COUNTER_HALF <= hatch.a0 and hatch.a1 <= counter.y + L.COUNTER_HALF)
        # Tripo's flat tray ledge runs the counter's length on the saloon side, deep enough in front of the body for a
        # 0.45 x 0.33 m tray, under the top; the tray lands on it beyond the top's edge and the queue stands clear of it
        ledge_x = counter.x + L.COUNTER_LEDGE_FRONT
        self.assertGreater(counter.x + L.COUNTER_BODY_FRONT, wall.c1)
        self.assertGreaterEqual(L.COUNTER_LEDGE_FRONT - L.COUNTER_BODY_FRONT, .30)
        self.assertLess(L.COUNTER_LEDGE_Z, L.COUNTER_H)
        self.assertTrue(counter.x + L.COUNTER_TOP_FRONT < serve.x < ledge_x)
        self.assertAlmostEqual(serve.z, L.FLOOR_Z + L.COUNTER_LEDGE_Z)
        self.assertGreaterEqual(m['canteen-queue'].x - L.HUMAN['radius'], ledge_x)
        spot, pot = m['canteen-npc-spot'], next(p for p in c.placements if p.id == 'canteen-pot')
        hatch_y = (L.HATCH[0] + L.HATCH[1]) / 2
        self.assertLessEqual(math.hypot(spot.x - pot.x, spot.y - pot.y), L.LADY_REACH)
        self.assertLessEqual(math.hypot(spot.x - L.CANTEEN_X1, spot.y - hatch_y), L.LADY_REACH)
        ladle = m['canteen-ladle']                                       # the big ladle's hook, within her reach
        self.assertLessEqual(math.hypot(spot.x - ladle.x, spot.y - ladle.y), L.LADY_REACH)
        self.assertGreater(ladle.z - L.FLOOR_Z, 1.5)                     # high enough for a long ladle to hang clear
        hung = next(p for p in c.placements if p.id == 'canteen-ladle')   # the ladle itself, its own placement on the hook
        self.assertEqual(hung.asset, 'canteen-ladle')
        self.assertLess(math.hypot(hung.x - ladle.x, hung.y - ladle.y), .10)
        self.assertTrue(0 <= hung.z - ladle.z <= .04)
        self.assertGreater(hung.z - L.asset_dims('canteen-ladle')[2], L.FLOOR_Z + .80)
        # the empty shelves replace their reservation, clear of the canteen door; mugs are separate placements of one
        # asset, five hanging by their handles from the shelf hooks and a few on the middle tray
        shelf = next(p for p in c.placements if p.id == 'canteen-shelves')
        self.assertFalse(any(b.kind == 'canteen-shelves' for b in c.reservations))
        door = next(o for o in c.wall('canteen-side').openings if o.name == 'door-canteen')
        self.assertLess(L.footprint(shelf)[1], door.a0)
        mugs = [p for p in c.placements if p.asset == 'canteen-mug']
        hooked = [p for p in mugs if p.id.startswith('canteen-mug-hook-')]
        self.assertEqual(len(hooked), len(L.SHELF_HOOKS))
        self.assertGreaterEqual(len(mugs) - len(hooked), 3)
        self.assertEqual(len({p.id for p in mugs}), len(mugs))
        for mug, hx in zip(hooked, L.SHELF_HOOKS):                       # the handle's loop on the hook's tip
            a = math.radians(mug.yaw)
            hx_w = mug.x + L.MUG_HANDLE[0] * math.cos(a)
            hy_w = mug.y + L.MUG_HANDLE[0] * math.sin(a)
            tip = (shelf.x - L.SHELF_HOOK_TIP[0], shelf.y + hx)
            self.assertLess(math.hypot(hx_w - tip[0], hy_w - tip[1]), .01)
            self.assertAlmostEqual(mug.z + L.MUG_HANDLE[1], L.FLOOR_Z + L.SHELF_HOOK_TIP[1])
        sink = next(p for p in c.placements if p.id == 'canteen-sink')    # the Tripo sink replaces its reservation
        self.assertFalse(any(b.kind == 'canteen-sink' for b in c.reservations))
        self.assertLessEqual(L.footprint(sink)[3], L.IN)
        # the counter's back is clear of the stove, and check() would say so if it were not
        moved = copy.deepcopy(c)
        next(p for p in moved.placements if p.id == 'canteen-stove').x += .20
        self.assertIn('canteen-stove overlaps canteen-counter', L.check(moved))
        # she stands, turns and walks about the kitchen; the passenger reaches the queue in front of the hatch
        self.assertTrue(all(L.reachable(c, L.LADY_RADIUS, (spot.x, spot.y), {'kitchen': (-8.9, .05)}).values()))
        self.assertEqual(L.check(c), [])

    def test_second_class_fittings(self):
        """Every second-class mount that is not a gameplay anchor gets its modelled fitting, inside the body, next to
        its mount; the bulbs clear an adult's head in the aisle and each has a light socket."""
        import math
        from train import fittings as F
        c = L.second_class()
        parts = {p.name: p for p in F.fittings(c)}
        self.assertEqual({mt.kind for mt in c.mounts} - F.ANCHORS, set(F.KINDS))
        for kind, names in F.KINDS.items():
            for name in names:
                self.assertTrue(parts[name].faces, name)
            pts = [q for name in names for f in parts[name].faces for q in f[0]]
            for mt in (m for m in c.mounts if m.kind == kind):
                self.assertTrue(any(math.hypot(x - mt.x, y - mt.y) <= mt.length / 2 + .5 and abs(z - mt.z) <= 1.2 for x, y, z in pts), mt.id)
            for x, y, z in pts:
                self.assertLessEqual(abs(y), L.IN + 1e-6)
                self.assertTrue(L.FLOOR_Z < z <= L.ceiling_z(y) + .03, (kind, x, y, z))
        boxes = [(L.footprint(pl), F._top(pl)) for pl in c.placements]
        for x, y, z in (q for f in parts['Fittings_Curtains'].faces for q in f[0]):       # curtains hang clear of the benches
            self.assertFalse(any(x0 < x < x1 and y0 < y < y1 and z < top for (x0, x1, y0, y1), top in boxes), (x, y, z))
        for name in ('Fittings_RackNets', 'Fittings_Racks', 'Fittings_MenuBoard'):   # overhead: clear of the tallest player
            self.assertGreaterEqual(min(q[2] for f in parts[name].faces for q in f[0]), L.FLOOR_Z + L.OVERHEAD_CLEAR - 1e-9, name)
        lamps = parts['Fittings_Lamps']
        self.assertEqual(len(lamps.sockets), sum(1 for m in c.mounts if m.kind == 'ceiling-lamp'))
        self.assertGreaterEqual(min(q[2] for f in lamps.faces for q in f[0]), L.FLOOR_Z + L.HUMAN['height'] + .10)

    def test_every_coach_has_its_fittings_in_its_style(self):
        """Every vehicle with a style gets geometry for each mount that isn't an anchor or built with the shell, next to
        its mount and inside the body, its curtains clear of the furniture; brass and velvet in the restaurant and first
        class, dull brass and worn cloth elsewhere. First class's racks are modelled, not reserved."""
        import math
        from train import fittings as F
        for c in L.vehicles():
            parts = {p.name: p for p in F.fittings(c)}
            kinds = {m.kind for m in c.mounts} - F.ANCHORS - F.BUILT
            if c.name not in F.COACHES:
                self.assertEqual(parts, {}, c.name)
                continue
            st = F.STYLES[c.name]
            ceiling = L.cab_ceiling_z if c.name == 'locomotive' else L.ceiling_z
            for kind in kinds:
                with self.subTest(coach=c.name, kind=kind):
                    self.assertIn(kind, F.KINDS)
                    pts = [q for name in F.KINDS[kind] if name in parts for f in parts[name].faces for q in f[0]]
                    for mt in (m for m in c.mounts if m.kind == kind):
                        self.assertTrue(any(math.hypot(x - mt.x, y - mt.y) <= mt.length / 2 + .5 and abs(z - mt.z) <= 1.2
                                            for x, y, z in pts), mt.id)
                    for x, y, z in pts:
                        self.assertLessEqual(abs(y), L.IN + 1e-6)
                        self.assertTrue(L.FLOOR_Z < z <= ceiling(y) + .03, (x, y, z))
            mats = {f[1] for p in parts.values() for f in p.faces}
            if 'curtain-rail' in kinds:
                self.assertIn(st['cloth'], mats)
            if 'rack' in kinds:
                self.assertIn(st['net'], mats)
            if kinds & {'rack', 'curtain-rail'}:
                self.assertIn(st['metal'], mats)
            boxes = [(L.footprint(pl), F._top(pl)) for pl in c.placements]
            for x, y, z in (q for f in parts.get('Fittings_Curtains', F.Part('')).faces for q in f[0]):
                self.assertFalse(any(x0 < x < x1 and y0 < y < y1 and z < top for (x0, x1, y0, y1), top in boxes), (c.name, x, y, z))
        self.assertFalse(any(b.kind == 'rack' for b in L.first_class().reservations))


if __name__ == '__main__':
    unittest.main()
