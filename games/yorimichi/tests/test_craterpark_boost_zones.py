"""Crater Park boost zones (docs/CRATERPARK.md, "Boost zones"): the bowls and runs the owner gave params.boost become
boxes round their own mesh in park.json, and nothing else does."""
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
from craterpark.v2 import editor_generate, export  # noqa: E402

SHIPPED = Path(__file__).resolve().parents[1] / 'tools' / 'craterpark_editor' / 'shipped.json'


class Placement:
    """Native metres (x, y up, z) -> centimetres (x, z, y up), as the island placement turns them (no offset)."""
    @staticmethod
    def to_unreal(p):
        p = np.asarray(p, 'f8')
        return np.stack([p[..., 0] * 100, p[..., 2] * 100, p[..., 1] * 100], -1)


def piece(pid, kind, V, stations=None):
    return SimpleNamespace(mesh=SimpleNamespace(V=np.asarray(V, 'f8')),
                           metadata={'id': pid, 'type': kind, 'stations': stations or []})


def test_shipped_park_boosts_the_orange_flow_bowl_its_u_turns_and_the_prado():
    doc = json.loads(SHIPPED.read_text())
    boosted = {p['id']: p for p in doc['pieces'] if p.get('params', {}).get('boost')}
    assert set(boosted) == {'p45', 'p47', 'p51', 'p5'}
    assert {p['line'] for p in boosted.values() if p['id'] != 'p5'} == {'L1'}
    assert boosted['p45']['type'] == 'bowl' and boosted['p47']['type'] == boosted['p51']['type'] == 'run'
    assert boosted['p5']['type'] == 'bowl' and 'Prado' in boosted['p5']['name']     # owner, r4 notes: all boost walls


def test_a_bowl_is_one_box_round_its_mesh_and_unboosted_pieces_none():
    ring = [[20 * math.cos(a), 4 * (i % 2), 10 * math.sin(a)] for i, a in enumerate(np.linspace(0, 2 * math.pi, 40))]
    doc = {'pieces': [{'id': 'b', 'params': {'boost': 1}}, {'id': 'r', 'params': {}}, {'id': 'z', 'params': {'boost': 0}}]}
    zones = editor_generate.boost_zones([piece('b', 'bowl', ring), piece('r', 'run', ring), piece('z', 'bowl', ring)], doc)
    assert [z['id'] for z in zones] == ['b_0']
    [box] = export.boost_boxes(zones, Placement)
    assert box['boost'] == 1.0
    # The long axis is x (40 m across), the short z (20 m); the pad is a metre each way, two up and down.
    assert abs(abs(box['yaw_deg']) % 180) < 1e-6 or abs(abs(box['yaw_deg']) % 180 - 180) < 1e-6
    assert np.allclose(box['half_extent_cm'], [2000 + 100, 1000 + 100, 200 + 200], atol=10)   # the ring's 40 samples fall just short of 20 m
    assert np.allclose(box['center_cm'], [0, 0, 200], atol=10)


def test_a_u_turn_run_is_cut_along_its_length_so_its_boxes_hug_the_curve():
    # A 180 degree turn of radius 15 m, 47 m long: its stations, and the run's mesh 4 m either side of them.
    a = np.linspace(0, math.pi, 48)
    centre = np.stack([15 * np.sin(a), np.zeros_like(a), 15 - 15 * np.cos(a)], 1)
    stations = [{'d': 15 * t, 'x': x, 'y': y, 'z': z} for t, (x, y, z) in zip(a, centre)]
    normal = np.stack([np.sin(a), np.zeros_like(a), -np.cos(a)], 1)   # out from the turn's centre
    V = np.concatenate([centre + 4 * normal, centre - 4 * normal, centre + [0, 3, 0]])
    doc = {'pieces': [{'id': 'u', 'params': {'boost': 2}}]}
    zones = editor_generate.boost_zones([piece('u', 'run', V, stations)], doc)
    assert len(zones) == 5                        # 47 m in 10 m cuts
    boxes = export.boost_boxes(zones, Placement)
    assert all(b['boost'] == 2.0 for b in boxes)
    # Together the boxes cover every mesh point, but far less ground than one box round the whole U-turn would.
    def inside(b, p):
        c, h, yaw = np.asarray(b['center_cm']), np.asarray(b['half_extent_cm']), math.radians(b['yaw_deg'])
        d = p - c
        local = [d[0] * math.cos(yaw) + d[1] * math.sin(yaw), -d[0] * math.sin(yaw) + d[1] * math.cos(yaw), d[2]]
        return all(abs(local[i]) <= h[i] + 1e-6 for i in range(3))
    for p in Placement.to_unreal(V):
        assert any(inside(b, p) for b in boxes)
    area = sum(4 * b['half_extent_cm'][0] * b['half_extent_cm'][1] for b in boxes) / 1e4
    assert area < 0.75 * (38 * 34)               # one box round it all is about 38 x 34 m
    assert not any(inside(b, np.asarray([0., 1500., 0.])) for b in boxes)   # the U-turn's middle is not in a box
