"""Only uncharged or fenced idempotent session operations reconcile a lost transport response."""
from copy import deepcopy
import errno
from pathlib import Path
from unittest.mock import Mock

import pytest

from atelier.harness import capacity_client as client


@pytest.mark.parametrize('action', ['offer', 'owned', 'check', 'close'])
def test_transient_failure_replays_identical_request_once(monkeypatch, action, capsys):
    message = dict(action=action, nonce='private', epoch=3, descendants=[[123, 456]])
    calls = []
    def rpc(path, value, timeout, *, descriptor):
        calls.append((path, deepcopy(value), timeout, descriptor))
        if len(calls) == 1:
            raise client.CapacityTransportError('lost response')
        return {'released': True}, None
    monkeypatch.setattr(client, '_rpc', rpc)
    assert client._session_rpc('/socket', message, 2.) == ({'released': True}, None)
    assert len(calls) == 2 and calls[0] == calls[1] == ('/socket', message, 2., False)
    assert capsys.readouterr().out.count('reconciling') == 1


def test_two_transport_failures_do_not_make_a_third_attempt(monkeypatch):
    rpc = Mock(side_effect=client.CapacityTransportError('still unknown'))
    monkeypatch.setattr(client, '_rpc', rpc)
    with pytest.raises(client.CapacityTransportError):
        client._session_rpc('/socket', {'action': 'close'}, 2.)
    assert rpc.call_count == 2


@pytest.mark.parametrize('action', ['gate', 'start', 'replace', 'status', 'reconcile', 'unknown'])
def test_non_replayable_actions_are_single_shot(monkeypatch, action):
    rpc = Mock(side_effect=client.CapacityTransportError('unknown outcome'))
    monkeypatch.setattr(client, '_rpc', rpc)
    with pytest.raises(client.CapacityTransportError):
        client._session_rpc('/socket', {'action': action}, 2., descriptor=(action == 'gate'))
    assert rpc.call_count == 1


@pytest.mark.parametrize('error', [client.CapacityError('fenced'), client.CapacityError('policy'),
                                 ValueError('malformed'), PermissionError(errno.EACCES, 'private')])
def test_untyped_or_negative_response_is_never_replayed(monkeypatch, error):
    rpc = Mock(side_effect=error)
    monkeypatch.setattr(client, '_rpc', rpc)
    with pytest.raises(type(error)) as caught:
        client._session_rpc('/socket', {'action': 'check'}, 2.)
    assert caught.value is error and rpc.call_count == 1


@pytest.mark.parametrize('error,transient', [(TimeoutError('private'), True),
    (ConnectionResetError(errno.ECONNRESET, 'private'), True),
    (OSError(errno.EIO, 'private'), False), (PermissionError(errno.EACCES, 'private'), False),
    (ValueError('private'), False), (client.CapacityError('invalid protocol'), False)])
def test_rpc_classifies_only_known_transport_failures(monkeypatch, error, transient):
    channel = Mock()
    channel.__enter__ = Mock(return_value=channel)
    channel.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(client, '_endpoint', lambda _: Path('/socket'))
    monkeypatch.setattr(client.socket, 'socket', Mock(return_value=channel))
    monkeypatch.setattr(client.wire, 'send', Mock())
    monkeypatch.setattr(client.wire, 'receive', Mock(side_effect=error))
    with pytest.raises(client.CapacityError) as caught:
        client._rpc('/socket', {'action': 'close'}, 2.)
    assert isinstance(caught.value, client.CapacityTransportError) is transient


def test_replayed_check_does_not_acknowledge_fenced_response(monkeypatch, tmp_path):
    admission = client.AdmissionSession(tmp_path/'socket', {'id': 'job'})
    admission.nonce, admission.epoch, admission.boot, admission.child = 'nonce', 2, 'boot', (10, 20)
    rpc = Mock(side_effect=[client.CapacityTransportError('lost response'),
                           ({'epoch': 3, 'boot_id': 'boot', 'state': 'running', 'admission': True}, None)])
    monkeypatch.setattr(client, '_rpc', rpc)
    with pytest.raises(client.CapacityError, match='fenced'):
        admission.check(descendants=[(30, 40)])
    assert rpc.call_count == 2 and not admission._acknowledged


def test_replayed_close_still_requires_affirmative_release(monkeypatch, tmp_path):
    admission = client.AdmissionSession(tmp_path/'socket', {'id': 'job'})
    admission.nonce, admission.epoch, admission.boot = 'nonce', 2, 'boot'
    rpc = Mock(side_effect=[client.CapacityTransportError('lost response'),
                           ({'released': False, 'state': 'uncertain'}, None)])
    monkeypatch.setattr(client, '_rpc', rpc)
    with pytest.raises(client.CapacityError, match='reservation and named locks retained'):
        admission.close()
    assert admission.closed and rpc.call_count == 2
