"""A busy broker queue is an uncharged wait, while unknown/refused admission still fails."""
from types import SimpleNamespace

import pytest

from atelier import capacity_client as client
from atelier.safety import guarded


def clock(monkeypatch):
    now = [0.]
    monkeypatch.setattr(client.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(client.time, 'sleep', lambda seconds: now.__setitem__(0, now[0]+seconds))
    return now


def test_queue_wait_reuses_the_same_offer_and_stops_as_soon_as_selected(monkeypatch, capsys):
    now = clock(monkeypatch)
    calls = []
    def offer():
        calls.append(now[0])
        if len(calls) < 3:
            raise client.CapacityQueued('busy')
        return {'selected': True}
    admission = SimpleNamespace(offer=offer)
    assert client.wait_for_offer(admission, seconds=5) == {'selected': True}
    assert calls == [0., 1., 2.]
    assert 'no resources or child held' in capsys.readouterr().out


def test_queue_wait_deadline_and_progress_are_bounded(monkeypatch, capsys):
    now = clock(monkeypatch)
    calls = []
    def queued():
        calls.append(now[0])
        raise client.CapacityQueued('busy')
    with pytest.raises(client.CapacityError, match='deadline reached'):
        client.wait_for_offer(SimpleNamespace(offer=queued), seconds=51.5)
    assert now[0] == 51.5 and len(calls) == 53
    assert capsys.readouterr().out.count('Waiting for capacity:') == 3


@pytest.mark.parametrize('error', [client.CapacityError('transport'), OSError('observer'), ValueError('policy')])
def test_only_positive_queue_responses_retry(monkeypatch, error):
    calls = []
    def refuse():
        calls.append(1)
        raise error
    monkeypatch.setattr(client.time, 'sleep', lambda seconds: pytest.fail('refusal retried'))
    with pytest.raises(type(error)) as caught:
        client.wait_for_offer(SimpleNamespace(offer=refuse))
    assert caught.value is error and calls == [1]


@pytest.mark.parametrize('value', [0, -1, 1801, float('inf'), float('nan'), True, '30'])
def test_invalid_wait_bounds_do_not_offer(value):
    with pytest.raises(ValueError, match='queue wait'):
        client.wait_for_offer(SimpleNamespace(offer=lambda: pytest.fail('offered')), seconds=value)


@pytest.mark.parametrize('selected,state,queued', [(False, 'queued', True), (False, 'offered', False),
                                                 (None, 'queued', False), (0, 'queued', False)])
def test_offer_distinguishes_positive_queued_from_invalid_responses(monkeypatch, tmp_path, selected, state, queued):
    response = dict(selected=selected, state=state, nonce='nonce', epoch=2, boot_id='boot')
    monkeypatch.setattr(client, '_rpc', lambda *args, **kwargs: (response, None))
    admission = client.AdmissionSession(tmp_path/'socket', {'id': 'job'})
    with pytest.raises(client.CapacityError) as error:
        admission.offer()
    assert isinstance(error.value, client.CapacityQueued) is queued
    assert admission.nonce == 'nonce' and admission.epoch == 2


@pytest.mark.parametrize('field,value', [('nonce', 'new-nonce'), ('epoch', 3), ('boot_id', 'new-boot')])
def test_reoffer_fences_changed_session_without_rebinding(monkeypatch, tmp_path, field, value):
    response = dict(selected=True, state='offered', nonce='nonce', epoch=2, boot_id='boot')
    monkeypatch.setattr(client, '_rpc', lambda *args, **kwargs: (dict(response), None))
    admission = client.AdmissionSession(tmp_path/'socket', {'id': 'job'})
    admission.offer()
    admission.child = (100, 200)
    admission._acknowledged.add(admission.child)
    response[field] = value
    with pytest.raises(client.CapacityError, match='fenced'):
        admission.offer()
    assert (admission.nonce, admission.epoch, admission.boot) == ('nonce', 2, 'boot')
    assert admission.child == (100, 200) and admission._acknowledged == {(100, 200)}


def test_closed_session_cannot_reoffer(monkeypatch, tmp_path):
    admission = client.AdmissionSession(tmp_path/'socket', {'id': 'job'})
    admission.close()
    monkeypatch.setattr(client, '_rpc', lambda *args, **kwargs: pytest.fail('closed session offered'))
    with pytest.raises(client.CapacityError, match='closed'):
        admission.offer()


def test_guard_cancellation_closes_queued_session_before_any_child_or_lock(monkeypatch, tmp_path):
    events = []
    class Admission:
        mode = 'legacy-bridge'
        def offer(self):
            events.append('offer')
            raise client.CapacityQueued('busy')
        def close(self, **kwargs):
            assert kwargs == {'child': None, 'child_start': None, 'descendants': ()}
            events.append('close')
    def interrupt(seconds):
        events.append('sleep')
        raise KeyboardInterrupt
    monkeypatch.setattr(client.time, 'sleep', interrupt)
    monkeypatch.setattr(guarded, 'spawn', lambda *args, **kwargs: pytest.fail('child started while queued'))
    monkeypatch.setattr(guarded, 'render_lock', lambda *args, **kwargs: pytest.fail('lock taken while queued'))
    with pytest.raises(KeyboardInterrupt):
        guarded.run(['python', '-c', 'pass'], tmp_path/'guard', kind='job', admission=Admission())
    assert events == ['offer', 'sleep', 'close']
