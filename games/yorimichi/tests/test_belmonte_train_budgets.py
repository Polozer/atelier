"""Performance budgets of the Belmonte train, checked from the GLBs and JSON alone (no Blender, no Unreal).

The checks on build outputs skip when `atelier build yorimichi world.belmonte_train` (shells) or
`world.belmonte_train_furniture_lods` (furniture levels of detail) has not been run in this checkout.
"""
import json
import struct
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))

import yori  # noqa: E402,F401
from train import budgets as B  # noqa: E402
from train import layout as L  # noqa: E402
from train import textures as T  # noqa: E402

OUT = yori.OUT / 'belmonte-train'
FURN = OUT / 'furniture'
LOD = FURN / 'lod'


def placements():
    return {c.name: Counter(p.asset for p in c.placements) for c in L.vehicles()}


def coach_total(counts, per_asset):
    return sum(n * per_asset[a] for a, n in counts.items())


class Targets(unittest.TestCase):
    """The budget table itself: every contract asset has one, and the coaches fit with every asset at its cap."""

    def test_every_contract_asset_has_a_budget(self):
        self.assertEqual({a['id'] for a in L.contract()['assets']}, set(B.FURNITURE))

    def test_texture_caps_are_powers_of_two(self):
        for a, (_, _, px) in B.FURNITURE.items():
            self.assertTrue(B.is_power_of_two(px) and px <= (2048 if a in B.LARGE_TEXTURES else 1024), a)

    def test_coaches_fit_at_the_caps(self):
        lod0 = {a: v[0] for a, v in B.FURNITURE.items()}
        lod1 = {a: B.LOD1_AIM.get(a, v[1]) or 0 for a, v in B.FURNITURE.items()}
        for coach, counts in placements().items():
            with self.subTest(coach=coach):
                self.assertLessEqual(coach_total(counts, lod0), B.COACH_LOD0)
                self.assertLessEqual(coach_total(counts, lod1), B.COACH_LOD1)

    def test_aims_stay_under_the_caps(self):
        for a, aim in B.LOD1_AIM.items():
            self.assertLessEqual(aim, B.FURNITURE[a][1])


class FurnitureLods(unittest.TestCase):
    """The decimated furniture (lod_furniture.py): triangles, one material, texture sizes, screen sizes."""

    @classmethod
    def setUpClass(cls):
        cls.fitted = [a for a in B.FURNITURE if (FURN / f'{a}.glb').exists()]
        if not LOD.exists() or not cls.fitted:
            raise unittest.SkipTest('furniture LODs not built (atelier build yorimichi world.belmonte_train_furniture_lods)')
        cls.stats = {}
        for a in cls.fitted:
            for k in (0, 1):
                p = LOD / f'{a}_LOD{k}.glb'
                if p.exists():
                    cls.stats[a, k] = B.glb_stats(p)

    def test_every_fitted_asset_has_its_levels(self):
        for a in self.fitted:
            with self.subTest(asset=a):
                self.assertIn((a, 0), self.stats)
                self.assertEqual((a, 1) in self.stats, B.FURNITURE[a][1] is not None)

    def test_triangle_caps(self):
        for (a, k), s in self.stats.items():
            with self.subTest(asset=a, lod=k):
                self.assertLessEqual(s['triangles'], B.FURNITURE[a][k])

    def test_one_material(self):
        for (a, k), s in self.stats.items():
            with self.subTest(asset=a, lod=k):
                extra = [m for m in s['materials'] if m in B.EXTRA_MATERIALS.get(a, ())]
                self.assertLessEqual(len(s['materials']) - len(extra), 1, s['materials'])

    def test_textures_are_powers_of_two_within_the_cap(self):
        for (a, k), s in self.stats.items():
            with self.subTest(asset=a, lod=k):
                self.assertTrue(s['images'])
                for w, h in s['images']:
                    self.assertTrue(B.is_power_of_two(w) and B.is_power_of_two(h), (w, h))
                    self.assertLessEqual(max(w, h), B.texture_cap(a))

    def test_reports_carry_the_screen_sizes(self):
        for a in self.fitted:
            with self.subTest(asset=a):
                lods = json.loads((FURN / f'{a}.json').read_text())['lods']
                sizes = [r['screen_size'] for r in lods['levels']] + [lods['cull_screen_size']]
                self.assertEqual(sizes, sorted(sizes, reverse=True))
                self.assertEqual(sizes[0], 1.0)
                self.assertGreater(sizes[-1], 0)
                self.assertEqual([r['level'] for r in lods['levels']], [0, 1] if B.FURNITURE[a][1] else [0])

    def test_coach_furniture_totals(self):
        if set(self.fitted) != set(B.FURNITURE):
            self.skipTest('not every asset is fitted yet')
        lod0 = {a: self.stats[a, 0]['triangles'] for a in B.FURNITURE}
        lod1 = {a: self.stats[a, 1]['triangles'] if (a, 1) in self.stats else 0 for a in B.FURNITURE}
        for coach in L.vehicles():
            p = OUT / coach.name / f'{coach.name}-placements.json'
            counts = Counter(x['asset'] for x in json.loads(p.read_text())['placements']) if p.exists() else placements()[coach.name]
            with self.subTest(coach=coach.name):
                self.assertLessEqual(coach_total(counts, lod0), B.COACH_LOD0)
                self.assertLessEqual(coach_total(counts, lod1), B.COACH_LOD1)


class Shells(unittest.TestCase):
    """The shell manifest's budgets, as they stand (the tighter shell split comes later)."""

    @classmethod
    def setUpClass(cls):
        path = OUT / 'manifest.json'
        if not path.exists():
            raise unittest.SkipTest('train shells not built (atelier build yorimichi world.belmonte_train)')
        cls.manifest = json.loads(path.read_text())

    def test_budgets_are_the_agreed_ones(self):
        b = self.manifest['budgets']
        self.assertEqual({k: b[f'{k}_triangles'] for k in B.SHELL}, B.SHELL)

    def test_every_vehicle_is_within_budget(self):
        for name, c in self.manifest['coaches'].items():
            for k, cap in B.SHELL.items():
                with self.subTest(vehicle=name, lod=k):
                    self.assertLessEqual(c['triangles'][k], cap)

    def test_shell_textures_are_powers_of_two(self):
        from PIL import Image
        for name in self.manifest['textures']:
            path = OUT / 'textures' / f'{name}.{"jpg" if name in T.JPEG else "png"}'
            if not path.exists():
                continue
            with self.subTest(texture=name), Image.open(path) as img:
                w, h = img.size
                self.assertTrue(B.is_power_of_two(w) and B.is_power_of_two(h), (w, h))
                self.assertLessEqual(max(w, h), 2048)


class ShellParts(unittest.TestCase):
    """The engine's cut of each shell (parts.py): exterior and interior add up to the combined mesh, within the shell
    budgets; a small shadow proxy; the windows' interior atlas."""

    @classmethod
    def setUpClass(cls):
        path = OUT / 'manifest.json'
        if not path.exists():
            raise unittest.SkipTest('train shells not built (atelier build yorimichi world.belmonte_train)')
        cls.manifest = json.loads(path.read_text())
        if any('parts' not in c for c in cls.manifest['coaches'].values()):
            raise unittest.SkipTest('shells built before the parts')

    def test_exterior_and_interior_add_up_to_the_combined_mesh(self):
        for name, c in self.manifest['coaches'].items():
            p = c['parts']
            for k in ('LOD0', 'LOD1'):
                with self.subTest(vehicle=name, lod=k):
                    total = sum(p[side].get(k, {}).get('triangles', 0) for side in ('exterior', 'interior'))
                    self.assertEqual(total, c['triangles'][k])
                    self.assertLessEqual(total, B.SHELL[k])
            self.assertEqual(p['exterior']['LOD2']['triangles'], c['triangles']['LOD2'])
            self.assertNotIn('LOD2', p['interior'])

    def test_every_part_file_is_built_and_stated(self):
        for name, c in self.manifest['coaches'].items():
            p = c['parts']
            recs = [*p['exterior'].values(), *p['interior'].values(), p['shadow_proxy']] + ([p['window_cards']] if 'window_cards' in p else [])
            for r in recs:
                with self.subTest(vehicle=name, file=r['file']):
                    path = OUT / name / r['file']
                    self.assertTrue(path.exists())
                    self.assertEqual(B.glb_stats(path)['triangles'], r['triangles'])

    def test_the_shadow_proxy_is_small_and_closed(self):
        for name, c in self.manifest['coaches'].items():
            with self.subTest(vehicle=name):
                path = OUT / name / c['parts']['shadow_proxy']['file']
                doc, binary = B.read_glb(path)
                self.assertLessEqual(B.glb_stats(path)['triangles'], B.SHELL_PROXY)
                prim = doc['meshes'][0]['primitives'][0]
                acc = doc['accessors'][prim['indices']]
                view = doc['bufferViews'][acc['bufferView']]
                fmt = {5121: 'B', 5123: 'H', 5125: 'I'}[acc['componentType']]
                idx = struct.unpack_from(f'<{acc["count"]}{fmt}', binary, view.get('byteOffset', 0) + acc.get('byteOffset', 0))
                pos_acc = doc['accessors'][prim['attributes']['POSITION']]
                pv = doc['bufferViews'][pos_acc['bufferView']]
                pts = struct.unpack_from(f'<{pos_acc["count"] * 3}f', binary, pv.get('byteOffset', 0) + pos_acc.get('byteOffset', 0))
                key = [tuple(round(v, 4) for v in pts[3 * i:3 * i + 3]) for i in range(pos_acc['count'])]
                edges = Counter()
                for t in range(0, len(idx), 3):
                    a, b_, c_ = (key[i] for i in idx[t:t + 3])
                    for e in ((a, b_), (b_, c_), (c_, a)):
                        edges[tuple(sorted(e))] += 1
                self.assertTrue(all(n % 2 == 0 for n in edges.values()), 'open edges')    # closed pieces

    def test_window_atlases_are_powers_of_two(self):
        from PIL import Image
        for name, c in self.manifest['coaches'].items():
            cards = c['parts'].get('window_cards')
            if not cards:
                continue
            with self.subTest(vehicle=name), Image.open(OUT / 'textures' / cards['atlas']) as img:
                self.assertEqual(list(img.size), cards['atlas_px'])
                self.assertTrue(all(B.is_power_of_two(n) for n in img.size))
                self.assertTrue(cards['tiles'] and all(t['depth_m'] > 0 for t in cards['tiles']))


if __name__ == '__main__':
    unittest.main()
