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
                 capsule_clear=True, crouched=False, authority=mode == 2, net_mode=mode, speed=0.)]


@pytest.mark.parametrize('mode', [2, 3])
def test_independent_native_host_and_guest_roles(mode):
    assert all(landing_checks(receipt(mode), 'indoor', mode, EXPECTED).values())


@pytest.mark.parametrize('change', [
    {'zone': 'outdoor'}, {'net_mode': 0}, {'authority': False}, {'walkable': False},
    {'on_ground': False}, {'crouched': True}, {'crouched': None}, {'capsule_clear': False}, {'landed': [100., -200., 1500.]},
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


@pytest.mark.parametrize('state', ['run', 'check-after-build'])
def test_current_data_rejects_a_stale_producer_and_incomplete_install_before_reading_files(tmp_path, monkeypatch, state):
    from types import SimpleNamespace
    from atelier import build, build_snapshot, build_plan
    import review_map_network as review
    context = SimpleNamespace(out=tmp_path, stamps=tmp_path, game='yorimichi')
    step = SimpleNamespace(name='data.network')
    (tmp_path / 'data.network.json').write_text('{"fingerprint":"old"}')
    monkeypatch.setattr(build_snapshot, 'require_complete', lambda *a, **k: None)
    monkeypatch.setattr(build, 'load_recipe', lambda game: SimpleNamespace(steps=lambda ctx: [step]))
    monkeypatch.setattr(build_plan, 'inspect', lambda *a, **k: {'steps': [{'step': 'data.network', 'status': state}]})
    with pytest.raises(RuntimeError, match='current build'):
        review.current_data(context, 'indoor')
    def incomplete(*args, **kwargs):
        raise SystemExit('incomplete verified reuse')
    monkeypatch.setattr(build_snapshot, 'require_complete', incomplete)
    with pytest.raises(SystemExit, match='incomplete verified reuse'):
        review.current_data(context, 'indoor')


@pytest.mark.parametrize('end,valid', [
    ({'zone': 'indoor', 'net_mode': 2, 'feet': [1000., -200., 300.]}, True),
    ({'zone': 'indoor', 'net_mode': 2, 'feet': [100., -200., 300.]}, False),
    ({'zone': 'indoor', 'net_mode': 2, 'feet': [100., -200., 10000.]}, False),
    ({'zone': 'other', 'net_mode': 2, 'feet': [1000., -200., 300.]}, False),
    ({'zone': 'indoor', 'net_mode': 3, 'feet': [1000., -200., 300.]}, False),
    ({'zone': 'indoor', 'net_mode': 2, 'feet': [float('nan'), -200., 300.]}, False),
    ({'zone': 'indoor', 'net_mode': 2, 'feet': None}, False),
    (None, False),
])
def test_host_must_have_measurably_vacated_before_guest_starts(end, valid):
    from review_map_network import host_vacated
    assert host_vacated(end, 'indoor', EXPECTED) is valid


@pytest.mark.parametrize('failure', [None, 'guest_nonzero', 'host_exit', 'invalid_guest', 'lost_guard', 'deadline'])
def test_guest_clean_exit_can_precede_host_disconnect_receipt(monkeypatch, failure):
    from types import SimpleNamespace
    import review_map_network as review
    clock = [0.]
    host_receipt = [False]
    polls = [0]
    rows = receipt(3)
    if failure == 'invalid_guest':
        rows[0]['walkable'] = False
    host = SimpleNamespace(poll=lambda: 0 if failure == 'host_exit' else None)
    guest = SimpleNamespace(poll=lambda: 1 if failure == 'guest_nonzero' else 0)
    host_guard = SimpleNamespace(poll=lambda: 0 if failure == 'lost_guard' else None)
    guest_guard = SimpleNamespace(poll=lambda: 0)
    monkeypatch.setattr(review.time, 'monotonic', lambda: clock[0])
    def tick(seconds):
        polls[0] += 1
        clock[0] += 100. if failure == 'deadline' else seconds
        if polls[0] == 2 and failure != 'deadline':
            host_receipt[0] = True
    monkeypatch.setattr(review.time, 'sleep', tick)
    def run():
        review.wait_for_native('guest disconnect', lambda: host_receipt[0],
                               [('host', host, host_guard), ('guest', guest, guest_guard)], 0.,
                               expected_exit=lambda role: role == 'guest' and all(
                                   review.landing_checks(rows, 'indoor', 3, EXPECTED).values()))
    if failure:
        with pytest.raises(RuntimeError, match={
            'guest_nonzero': 'guest exited 1', 'host_exit': 'Game exited before.*host',
            'invalid_guest': 'Game exited before.*guest', 'lost_guard': 'guard lost: host',
            'deadline': 'deadline expired'}[failure]):
            run()
    else:
        run()
        assert polls[0] == 2  # Guest was already exited during both pre-receipt polls.
        assert host_receipt[0]
