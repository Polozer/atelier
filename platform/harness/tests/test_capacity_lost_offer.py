"""Selection may change before GO; only positively unexecuted, drained launches requeue."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from atelier.harness import capacity_client as client
from atelier.harness.safety import guarded


@pytest.mark.parametrize('field,value', [('nonce', 'other'), ('epoch', 3), ('boot_id', 'other'),
    ('child', [99, 99]), ('admission', True), ('state', 'uncertain'), ('reason', 'expired')])
def test_no_go_response_must_match_the_exact_session_child(monkeypatch, tmp_path, field, value):
    admission = client.AdmissionSession(tmp_path / 'socket', {'id': 'job'})
    admission.nonce, admission.epoch, admission.boot = 'nonce', 2, 'boot'
    response = dict(state='queued', admission=False, no_go=True, reason='selection-changed',
                    nonce='nonce', epoch=2, boot_id='boot', child=[10, 20])
    response[field] = value
    monkeypatch.setattr(client, '_rpc', lambda *a, **k: (response, None))
    with pytest.raises(client.CapacityError) as error:
        admission.start(child_pid=10, child_start=20, process_guard={}, tree_guard={}, limit_bytes=100)
    assert type(error.value) is client.CapacityError
    assert not admission._acknowledged


def test_generic_start_refusal_never_becomes_a_lost_offer(monkeypatch, tmp_path):
    admission = client.AdmissionSession(tmp_path / 'socket', {'id': 'job'})
    admission.nonce, admission.epoch, admission.boot = 'nonce', 2, 'boot'
    def refused(*a, **k):
        raise client.CapacityError('Capacity offer is no longer selected')
    monkeypatch.setattr(client, '_rpc', refused)
    with pytest.raises(client.CapacityError) as error:
        admission.start(child_pid=10, child_start=20, process_guard={}, tree_guard={}, limit_bytes=100)
    assert type(error.value) is client.CapacityError


@pytest.mark.parametrize('explicit,clean', [(False, False), (True, True)])
def test_guard_requires_both_automatic_admission_and_cleanup(monkeypatch, tmp_path, explicit, clean):
    admission = SimpleNamespace(child=(10, 20))
    denial = client.CapacityOfferLost(admission)
    denial.cleanup = {} if clean else None
    calls = []
    def fail(*a, **k):
        calls.append(1)
        raise denial
    monkeypatch.setattr(guarded, '_run', fail)
    with pytest.raises(client.CapacityOfferLost):
        guarded.run(['ordinary-python'], tmp_path, admission=admission if explicit else None)
    assert calls == [1]


def test_guard_requeue_has_one_deadline_and_two_retries(monkeypatch, tmp_path):
    calls = []
    admission = SimpleNamespace(child=(10, 20))
    def fail(*a, **k):
        calls.append(k)
        for name in ('memory-health.json', 'memory-health-tree.json', 'stdout.log'):
            (tmp_path / name).write_text('{}')
        denial = client.CapacityOfferLost(admission)
        denial.cleanup = {'no_go': True, 'uncharged_close': True}
        raise denial
    monkeypatch.setattr(guarded, '_run', fail)
    with pytest.raises(client.CapacityError, match='requeue bound'):
        guarded.run(['ordinary-python'], tmp_path)
    assert len(calls) == 3
    assert len({c['_queue_deadline'] for c in calls}) == 1
    assert calls[0]['_requeue'] is None and calls[1]['_requeue'] is admission
    assert len(list(tmp_path.glob('lost-offer-*/no-go.json'))) == 3


@pytest.mark.parametrize('field,value', [('request', {'id': 'other'}), ('socket_path', Path('/other')),
                                        ('activation_id', 'other'), ('_guard_limit_gib', 4)])
def test_requeue_configuration_cannot_change(tmp_path, field, value):
    previous = client.AdmissionSession(tmp_path / 'socket', {'id': 'job'})
    previous.nonce, previous.epoch, previous.boot, previous.closed = 'nonce', 2, 'boot', True
    retry = client.AdmissionSession(tmp_path / 'socket', {'id': 'job'})
    setattr(retry, field, value)
    with pytest.raises(client.CapacityError, match='configuration changed'):
        retry.requeue_after(previous)
