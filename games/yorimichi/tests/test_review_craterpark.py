"""The Crater Park tour's shot plan follows the generated park: its line starts, airs and features (no game)."""
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
sys.path.insert(0, str(GAME / 'world'))

from craterpark import placement  # noqa: E402
from craterpark.v2 import export, generate, layout_m0, spawns  # noqa: E402

spec = importlib.util.spec_from_file_location('review_craterpark', GAME / 'tools' / 'review_craterpark.py')
tour = importlib.util.module_from_spec(spec); spec.loader.exec_module(tour)


def built(tmp_path):
    """A craterpark build folder from the M0 layout, with one air and the quarter pipe's check."""
    park = layout_m0.park()
    lines = spawns.entries(park.mesh, park.lines, placement)
    arrays, _ = generate.bundle(park, lines)
    (tmp_path / 'v2' / 'lines').mkdir(parents=True)
    np.savez(tmp_path / 'v2' / 'geometry.npz', **arrays)
    export.line_npz(park.mesh, park.lines[0], tmp_path / 'v2' / 'lines' / 'm0.npz')
    drop = np.array(layout_m0.DROP)
    checks = [{'feature': 'test_air', 'kind': 'air', 'lip': (drop + [10, 2, 0]).tolist(),
               'landing_start': (drop + [35, -1, 0]).tolist(), 'lip_degrees': 24., 'gap': 25.},
              {'feature': 'm0_quarter', 'kind': 'quarter_pipe'}]
    (tmp_path / 'v2' / 'geometry-report.json').write_text(json.dumps({'checks': checks}))
    (tmp_path / 'park.json').write_text(json.dumps({'spawn': lines[0]['spawn'], 'lines': lines}))
    return park, lines


def test_the_plan_follows_the_generated_park(tmp_path):
    park, lines = built(tmp_path)
    shots = {s['name']: s for s in tour.plan(tmp_path)}
    assert {'aerial', 'aerial_plan', 'tower_m0', 'gap_test_air', 'feature_m0_quarter'} <= set(shots)
    # the tower shot stands just behind and over the start, looking down the line
    t = shots['tower_m0']; at = np.array(lines[0]['spawn']['location_cm']); yaw = math.radians(lines[0]['spawn']['yaw_deg'])
    cam, tgt = np.array(t['camera_cm']), np.array(t['target_cm'])
    assert np.linalg.norm(cam[:2] - at[:2]) < 400 and cam[2] > at[2] + 150
    look = (tgt - cam)[:2] / np.linalg.norm((tgt - cam)[:2])
    assert look @ [math.cos(yaw), math.sin(yaw)] > .99 and tgt[2] < cam[2]
    # the gap: seen square from the side, at least 30 m off; the launch climbs at the lip angle toward the landing
    g = shots['gap_test_air']
    lip = np.array(g['lip_cm']); mid = np.array(g['target_cm']); cam = np.array(g['camera_cm'])
    across = (cam - mid)[:2]; ahead = np.array(placement.to_unreal(np.array(layout_m0.DROP) + [35, -1, 0]))[:2] - lip[:2]
    assert np.linalg.norm(across) >= 3000 and abs(across @ ahead) / np.linalg.norm(across) / np.linalg.norm(ahead) < .05
    v = np.array(g['launch_cm_s'])
    assert abs(np.linalg.norm(v) - tour.LIP_SPEED * 100) < 1
    assert math.degrees(math.atan2(v[2], np.linalg.norm(v[:2]))) == pytest.approx(24., abs=.1)
    assert v[:2] @ ahead > 0 and 0.5 < g['apex_s'] < 1.
    # the quarter pipe is looked at from in front of its transition
    q = shots['feature_m0_quarter']
    assert np.linalg.norm(np.array(q['camera_cm']) - np.array(q['target_cm'])) > 800


def test_the_flythrough_chases_each_line(tmp_path):
    built(tmp_path)
    np.savez(tmp_path / 'v2' / 'lines' / 'old.npz', path=np.zeros((3, 3)))     # left from an earlier layout
    paths = tour.line_paths(tmp_path)
    assert list(paths) == ['m0']
    frames = tour.chase(paths['m0'], step=.5)
    assert len(frames) >= 10
    for cam, tgt in frames:
        assert cam[2] > tgt[2]                      # above, looking ahead and down a little


def test_without_v2_outputs_the_tour_still_plans(tmp_path):
    """An r4 park.json (a drop-in spawn, no lines, no v2 folder): aerials and the drop-in view."""
    spawn = {'location_cm': placement.to_unreal(np.array(layout_m0.DROP)).tolist(), 'yaw_deg': 5.}
    (tmp_path / 'park.json').write_text(json.dumps({'spawn': spawn}))
    names = [s['name'] for s in tour.plan(tmp_path)]
    assert names[:3] == ['aerial', 'aerial_plan', 'tower_drop-in']


def test_the_contact_sheet_lists_only_taken_shots(tmp_path):
    shots = [tour.shot('aerial', 'a', (0, 0, 0), (1, 0, 0), 60., 'one'), tour.shot('aerial', 'b', (0, 0, 0), (1, 0, 0), 60., 'two')]
    (tmp_path / 'a.png').write_bytes(b'png')
    tour.contact_sheet(tmp_path, shots, ['flythrough_L1.mp4'])
    text = (tmp_path / 'index.html').read_text()
    assert 'a.png' in text and 'b.png' not in text and 'flythrough_L1.mp4' in text


@pytest.mark.parametrize('memory_gib', [18., 24.])
def test_tour_forwards_selected_memory_to_worker_and_guard(monkeypatch, tmp_path, memory_gib):
    from atelier.harness.safety import guarded
    monkeypatch.setattr(sys, 'argv', ['review_craterpark.py', '--memory-gib', str(memory_gib), '--out', str(tmp_path)])
    monkeypatch.setattr(tour, 'plan', lambda: [])
    calls = []
    monkeypatch.setattr(guarded, 'run', lambda command, folder, **kwargs: calls.append((command, kwargs)) or 0)
    assert tour.main() == 0
    command, options = calls[0]
    assert command[command.index('--memory-gib') + 1] == str(memory_gib)
    assert options['kind'] == 'game' and options['limit_gib'] == memory_gib


@pytest.mark.parametrize('memory_gib', ['9.999', '24.001', 'nan', 'inf'])
def test_tour_refuses_invalid_memory_before_planning(monkeypatch, memory_gib):
    monkeypatch.setattr(sys, 'argv', ['review_craterpark.py', '--memory-gib', memory_gib])
    monkeypatch.setattr(tour, 'plan', lambda: pytest.fail('invalid ceiling reached planning'))
    with pytest.raises(SystemExit, match='10 to 24'):
        tour.main()
