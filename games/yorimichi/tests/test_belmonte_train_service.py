"""The Belmonte train service data (tools/belmonte_train_service.py) from a small synthetic route and consist."""
import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import belmonte_train_service as S  # noqa: E402


def profile(start, stop, seconds, top=60.):
    """[chainage, seconds, km/h] every 10 m: accelerate, cruise, brake (shape only; times scale to `seconds`)."""
    sign = 1 if stop > start else -1
    length = abs(stop - start)
    rows = []
    for k in range(int(length // 10) + 1):
        d = k * 10.
        v = min(top, 8 * math.sqrt(d), 8 * math.sqrt(max(length - d, 0)))
        rows.append([start + sign * d, round(seconds * d / length, 2), round(v, 1)])
    return rows


def route(schedule=True):
    samples = [{'s': float(s), 'x': 100. + s, 'y': 50., 'rail_z': 10. + s / 100, 'ground_z': 25. if 400 <= s <= 600 else 9.,
                'class': 'cutting' if 400 <= s <= 600 else 'embankment'} for s in range(0, 1210, 10)]
    loop = {'start': 500., 'end': 700., 'second_track': [[c, 100. + c, 50. + (4. if 520 <= c <= 680 else 0.)]
                                                         for c in range(500, 705, 5)]}
    service = {'trains': 2, 'dwell_s': 90.0, 'cycle_s': 600.0, 'waiting_direction': 'down', 'schedule': [
        {'train': 'A', 'legs': [
            {'direction': 'Hidamari -> Belmonte', 'depart_s': 0.0, 'loop_arrive_s': 100.0, 'loop_leave_s': 110.0, 'arrive_s': 200.0},
            {'direction': 'Belmonte -> Hidamari', 'depart_s': 290.0, 'loop_arrive_s': 380.0, 'loop_leave_s': 420.0, 'arrive_s': 510.0}]},
        {'train': 'B', 'legs': [
            {'direction': 'Belmonte -> Hidamari', 'depart_s': -10.0, 'loop_arrive_s': 80.0, 'loop_leave_s': 110.0, 'arrive_s': 210.0},
            {'direction': 'Hidamari -> Belmonte', 'depart_s': 300.0, 'loop_arrive_s': 400.0, 'loop_leave_s': 410.0, 'arrive_s': 500.0}]}]}
    return {'samples': samples, 'passing_loop': loop,
            'speed_profile': profile(100., 1100., 180.), 'speed_profile_down': profile(1100., 100., 180.),
            'summary': {'service': service if schedule else {'dwell_s': 60.0}}}


def write_fixture(root, schedule=True):
    (root / 'route').mkdir(parents=True)
    (root / 'route' / 'route.json').write_text(json.dumps(route(schedule)))
    vehicles = [
        {'id': 'locomotive', 'x': -7.0, 'length': 14.0, 'glb': 'SM_BT_Locomotive_LOD0.glb'},
        {'id': 'second-class', 'x': -26.0, 'length': 24.0, 'glb': 'SM_BT_SecondClass_LOD0.glb'},
    ]
    (root / 'assembly').mkdir()
    (root / 'assembly' / 'consist.json').write_text(json.dumps({'vehicles': vehicles, 'furniture': {
        'second-class-bench': {'dimensions_m': {'width': 1.2, 'depth': 0.56, 'height': 0.91}},
        'canteen-mug': {'dimensions_m': {'width': .13, 'depth': .09, 'height': .1}}}}))
    for v, body, placements in [
            ('locomotive', {'bogies': []}, []),
            ('second-class', {'bogies': [-8.5, 8.5]},
             [{'asset': 'second-class-bench', 'x': 1.0, 'y': 1.1, 'z': 1.25, 'yaw': 90},
              {'asset': 'second-class-bench', 'x': 2.0, 'y': 1.1, 'z': 1.25, 'yaw': -90},
              {'asset': 'canteen-mug', 'x': 0.0, 'y': -1.0, 'z': 2.0, 'yaw': 0}])]:
        (root / v).mkdir()
        boxes = [{'name': 'UCX_SM_X_00', 'group': 'fixed', 'part': 'floor', 'box': [-11.5, 11.5, -1.7, 1.6, 1.05, 1.25]},
                 {'name': 'COL_SM_X_door-a', 'group': 'door', 'part': 'door-a', 'box': [-11.6, -11.5, -.4, .4, 1.25, 3.25]}]
        doors = [{'id': 'exterior-al', 'kind': 'exterior', 'opens': 'station', 'box': [-11.3, -10.6, 1.72, 1.8, 1.25, 3.2],
                  'handles': [{'point': [-10.8, 1.85, 2.2]}], 'collision': 'COL_SM_X_door-a', 'leaves': []}]
        records = [{'id': 'exterior-al', 'outside': [-10.95, 2.3, 0.], 'inside': [-10.95, 1.35, 1.25],
                    'treads': [{'box': [-11.2, -10.7, 1.7, 1.88], 'top_z': .96}, {'box': [-11.2, -10.7, 1.82, 2.12], 'top_z': .66}]}]
        extra = {'door_interactions': doors, 'boarding': records} if v == 'second-class' else {}
        (root / v / f'{v}-placements.json').write_text(json.dumps({'body': body, 'placements': placements, 'collision_boxes': boxes, **extra}))
    from train_furniture_fixtures import bake
    baked = bake(root / 'furniture')
    path = root / 'assembly' / 'consist.json'
    assembly = json.loads(path.read_text())
    assembly['furniture_bake_sha256'] = S.BM.sha(root / 'furniture' / 'lod' / 'summary.json')
    for aid, entry in assembly['furniture'].items():
        entry['lods'] = [dict(r, glb='lod/' + r['glb']) for r in baked[aid]['levels']]
    path.write_text(json.dumps(assembly))



class BelmonteTrainServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name) / 'scheduled'
        write_fixture(root)
        cls.data = S.build(root)
        plain = Path(cls.tmp.name) / 'plain'
        write_fixture(plain, schedule=False)
        cls.plain = S.build(plain)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_line_is_in_unreal_centimetres_with_y_flipped(self):
        main = self.data['line']['main']
        self.assertEqual(main[0], [0.0, 10000.0, -5000.0, 1000.0])
        loop = self.data['line']['loop']
        self.assertEqual((loop['start'], loop['end']), (500.0, 700.0))
        middle = next(p for p in loop['points'] if p[0] == 600.0)
        self.assertEqual(middle[2], -5400.0)                       # 4 m north of the main line
        self.assertAlmostEqual(middle[3], (10. + 6.) * 100, places=1)   # the main line's rail height there

    def test_viewpoints_are_stretches_above_ground(self):
        stretches = self.data['line']['viewpoints']
        self.assertTrue(stretches)
        for v in stretches:
            self.assertFalse(400 <= v['s'] <= 600, v)
        self.assertGreaterEqual(stretches[0]['end'] - stretches[0]['start'], stretches[-1]['end'] - stretches[-1]['start'])

    def test_consist_offsets_bogies_and_collision(self):
        loco, coach = self.data['consist']['vehicles']
        self.assertEqual(self.data['consist']['length'], 38.0)
        self.assertEqual((loco['offset'], coach['offset']), (12.0, -7.0))   # from the consist centre, head (+x) up the line
        self.assertEqual(loco['bogies'], [-4.2, 4.2])                     # rigid: default pivots
        self.assertEqual(coach['bogies'], [-8.5, 8.5])
        self.assertEqual(coach['mesh'], '/Game/BelmonteTrain/SM_BT_SecondClass.SM_BT_SecondClass')
        self.assertEqual(coach['collision'], [[-1150.0, -160.0, 105.0, 1150.0, 170.0, 125.0]])
        self.assertEqual([b['name'] for b in coach['switchable']], ['COL_SM_X_door-a'])
        bench = next(f for f in coach['furniture'] if f['asset'] == 'second-class-bench')
        self.assertEqual(bench['instances'][0], [100.0, -110.0, 125.0, -90.0])

    def test_furniture_uses_recorded_lods_and_cull(self):
        bench = self.data['furniture']['second-class-bench']
        self.assertEqual([l['glb'] for l in bench['levels']], ['lod/second-class-bench_LOD0.glb', 'lod/second-class-bench_LOD1.glb'])
        self.assertAlmostEqual(bench['cull_cm'], 4000.0)
        self.assertTrue(bench['shadow'])
        mug = self.data['furniture']['canteen-mug']
        self.assertEqual([l['glb'] for l in mug['levels']], ['lod/canteen-mug_LOD0.glb'])
        self.assertFalse(mug['shadow'])

    def test_thin_sheets_are_two_sided(self):
        record = S.BM.read(Path(self.tmp.name) / 'scheduled' / 'furniture')['table-lamp']
        spec = {'dimensions_m': {'width': .2, 'depth': .2, 'height': .4},
                'lods': [dict(r, glb='lod/' + r['glb']) for r in record['levels']]}
        lamp = S.furniture_entry('table-lamp', spec, record)
        self.assertTrue(lamp['two_sided'])
        self.assertFalse(self.data['furniture']['second-class-bench']['two_sided'])

    def test_a_seated_passenger_faces_the_way_the_layout_says(self):
        # layout: 0 faces -Y, 90 faces +X; Unreal: a character faces +X at yaw 0, with Y mirrored (-Y is +90 there)
        self.assertEqual([S.seat_yaw(y) for y in (90, -90, 0, 180)], [0., -180., 90., -90.])

    def test_boarding_path_runs_up_the_treads(self):
        coach = self.data['consist']['vehicles'][1]
        self.assertEqual(coach['doors'][0]['side'], 'l')
        way = coach['boarding'][0]
        self.assertEqual((way['door'], way['source']), ('exterior-al', 'record'))
        # Outside on the ground, the lower tread before the upper, the floor inside; y flipped to Unreal.
        self.assertEqual([round(q[2]) for q in way['path']], [0, 66, 96, 125])
        self.assertEqual(way['path'][0][:2], [-1095.0, -230.0])
        self.assertEqual(self.data['consist']['vehicles'][0]['boarding'], [])

    def test_head_referenced_profiles_place_the_consist_by_its_centre(self):
        r = route(schedule=False)
        r['speed_profile'] = profile(140., 1140., 180.)          # the head leads: up it ends 40 m past the centre ...
        r['speed_profile_down'] = profile(1060., 60., 180.)      # ... and down it leads 40 m ahead of it
        r['summary']['service'] = {'profile_reference': 'head', 'train_length_m': 80.0, 'dwell_s': 90.0}
        out = S.service(r)
        self.assertEqual(out['terminals'], [100.0, 1100.0])       # the centre, half a train behind each head
        a = out['trains'][0]
        self.assertAlmostEqual(S.position(a, out['cycle_s'], a['t0']), 100.0, places=3)
        self.assertAlmostEqual(max(a['s']), 1100.0, places=3)     # stops with its centre where the down run starts

    def test_schedule_is_followed(self):
        service = self.data['service']
        self.assertEqual(service['cycle_s'], 600.0)
        a, b = service['trains']
        self.assertEqual(len(a['s']), int(600 / S.DT))
        at = lambda train, t: S.position(train, 600.0, t)
        self.assertAlmostEqual(at(a, 0.0), 100.0, places=3)        # leaves Hidamari's centre
        self.assertAlmostEqual(at(a, 200.0), 1100.0, places=2)     # arrives at Belmonte's on time
        self.assertAlmostEqual(at(a, 250.0), 1100.0, places=2)     # dwells
        self.assertAlmostEqual(at(a, 395.0), 600.0, places=2)      # waits in the loop (down)
        self.assertAlmostEqual(at(a, 510.0), 100.0, places=2)
        self.assertAlmostEqual(at(b, 100.0), 600.0, places=2)      # B waits in the loop going down
        positions = [at(a, t) for t in range(0, 200)]
        self.assertTrue(all(q >= p - 1e-6 for p, q in zip(positions, positions[1:])))   # never runs backwards
        self.assertEqual(b['loop_track'], [[0.0, 220.0]])          # the waiting (down) leg uses the second track

    def test_trains_cross_only_in_the_loop(self):
        crossings = self.data['service']['crossings']
        self.assertTrue(crossings)
        self.assertTrue(all(c['in_loop'] for c in crossings), crossings)

    def test_without_a_schedule_two_trains_run_half_a_cycle_apart(self):
        service = self.plain['service']
        self.assertEqual(len(service['trains']), 2)
        cycle = service['cycle_s']
        self.assertAlmostEqual(cycle, 2 * 180.0 + 2 * 60.0, delta=1.0)
        a, b = service['trains']
        self.assertAlmostEqual(S.position(a, cycle, 10.0), S.position(b, cycle, 10.0 + cycle / 2), places=3)


if __name__ == '__main__':
    unittest.main()


def test_service_rejects_missing_bake_before_writing(tmp_path):
    import pytest
    root = tmp_path / 'train'
    write_fixture(root)
    (root / 'furniture/lod/summary.json').unlink()
    with pytest.raises(FileNotFoundError):
        S.build(root)
    assert not (root / 'service').exists()


def test_service_rejects_stale_assembly_before_writing(tmp_path):
    import pytest
    root = tmp_path / 'train'
    write_fixture(root)
    path = root / 'assembly/consist.json'
    data = json.loads(path.read_text())
    data['furniture_bake_sha256'] = '0' * 64
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='assembly is stale'):
        S.build(root)
    assert not (root / 'service').exists()


def test_service_has_no_unbaked_furniture_fallback():
    import pytest
    with pytest.raises(ValueError, match='bake is required'):
        S.furniture_entry('canteen-mug', {'dimensions_m': {'width': .1}}, None)


def test_service_cli_uses_the_production_bake(tmp_path):
    root = tmp_path / 'train'
    write_fixture(root)
    output = root / 'service/service.json'
    assert S.main(['--root', str(root), '--output', str(output)]) == 0
    data = json.loads(output.read_text())
    assert data['furniture']
    assert all(level['glb'].startswith('lod/') for asset in data['furniture'].values() for level in asset['levels'])


def test_assembly_requires_bake_before_publishing(tmp_path, monkeypatch):
    import pytest
    from train import consist as C
    monkeypatch.setattr(C, 'OUT', tmp_path)
    monkeypatch.setattr(C, 'ASSEMBLY', tmp_path / 'assembly')
    with pytest.raises(FileNotFoundError):
        C.assembly()
    assert not (tmp_path / 'assembly').exists()


def test_viewpoints_name_the_viaducts_for_train_recovery():
    """ABelmonteTrainService reads class "viaduct" stretches (start/end chainage) as places where nobody is set down
    beside a coach (BelmonteTrainRules::RecoveryOrder)."""
    samples = [{'s': float(s), 'rail_z': 10., 'ground_z': 30. if s < 300 or s > 600 else -20.,
                'class': 'cutting' if s < 300 else 'viaduct' if s <= 600 else 'tunnel'} for s in range(0, 1000, 10)]
    stretches = S.viewpoints(samples)
    viaducts = [v for v in stretches if v['class'] == 'viaduct']
    assert len(viaducts) == 1 and viaducts[0]['start'] == 300. and viaducts[0]['end'] == 600.
    assert all(v['class'] == 'viaduct' for v in stretches)     # cuttings and tunnels are not viewpoints


def test_track_runtime_keeps_tunnel_chainages_for_train_recovery():
    """The staged track data keeps each tunnel's chainage range (FBelmonteTrainLine::AddTunnels)."""
    import belmonte_track_data as D
    track = {'meshes': {}, 'chunks': [], 'viaducts': [], 'instances': {},
             'tunnels': [{'name': 'T1', 'start': 635.0, 'end': 1005.0, 'lining': []}]}
    tunnels = D.build(track)['tunnels']
    assert [(t['name'], t['start'], t['end']) for t in tunnels] == [('T1', 635.0, 1005.0)]
