"""Ordinary network map travel needs measured floor, clearance and facing evidence."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from review_map_network import landing_checks  # noqa: E402

EXPECTED = dict(target=[100., -200., 300.], yaw=-4., above_cm=150.)


def receipt(mode=2):
    return [dict(zone='indoor', target=EXPECTED['target'].copy(), landed=[100., -200., 318.],
                 target_yaw=-4., yaw=-4., above_cm=150., on_ground=True, walkable=True,
                 capsule_clear=True, authority=mode == 2, net_mode=mode, speed=0.)]


@pytest.mark.parametrize('mode', [2, 3])
def test_independent_native_host_and_guest_roles(mode):
    assert all(landing_checks(receipt(mode), 'indoor', mode, EXPECTED).values())


@pytest.mark.parametrize('change', [
    {'zone': 'outdoor'}, {'net_mode': 0}, {'authority': False}, {'walkable': False},
    {'on_ground': False}, {'capsule_clear': False}, {'landed': [100., -200., 1500.]},
    {'landed': [200., -200., 318.]}, {'yaw': 4.}, {'yaw': float('nan')},
    {'speed': 50.}, {'speed': float('inf')}, {'above_cm': 2500.},
    {'target': [100., -200., 1500.], 'landed': [100., -200., 1500.]},
    {'target_yaw': 4., 'yaw': 4.}, {'landed': None}, {'landed': [100., -200., True]},
    {'speed': 10**1000},
])
def test_rejects_wrong_floor_facing_clearance_role_or_self_consistent_wrong_target(change):
    rows = copy.deepcopy(receipt())
    rows[0].update(change)
    assert not all(landing_checks(rows, 'indoor', 2, EXPECTED).values())


@pytest.mark.parametrize('rows', [None, {}, [], [None], receipt() * 2])
def test_missing_or_duplicate_native_destination_is_not_acceptance(rows):
    assert not all(landing_checks(rows, 'indoor', 2, EXPECTED).values())


def test_equivalent_wrapped_runtime_yaw_is_valid():
    rows = receipt()
    rows[0]['yaw'] += 360.
    assert all(landing_checks(rows, 'indoor', 2, EXPECTED).values())


def test_current_data_rejects_a_stale_producer_and_incomplete_install_before_reading_files(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from atelier import build, build_snapshot
    import review_map_network as review
    context = SimpleNamespace(out=tmp_path, stamps=tmp_path, game='yorimichi')
    step = SimpleNamespace(name='data.network')
    (tmp_path / 'data.network.json').write_text('{"fingerprint":"old"}')
    monkeypatch.setattr(build_snapshot, 'require_complete', lambda *a, **k: None)
    monkeypatch.setattr(build, 'load_recipe', lambda game: SimpleNamespace(steps=lambda ctx: [step]))
    monkeypatch.setattr(build, 'order', lambda steps, targets: steps)
    monkeypatch.setattr(build, 'fingerprint', lambda step, done: 'current')
    with pytest.raises(RuntimeError, match='current build'):
        review.current_data(context, 'indoor')
    def incomplete(*args, **kwargs):
        raise SystemExit('incomplete verified reuse')
    monkeypatch.setattr(build_snapshot, 'require_complete', incomplete)
    with pytest.raises(SystemExit, match='incomplete verified reuse'):
        review.current_data(context, 'indoor')
