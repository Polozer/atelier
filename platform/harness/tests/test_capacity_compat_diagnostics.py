"""Compatibility failures explain refusal without leaking exception payloads."""
import errno
import json

import pytest

from atelier.harness.capacity_broker import CapacityBroker
from atelier.harness import capacity_protocol as wire
from atelier.harness.capacity_compat_diagnostics import failure_reason


@pytest.mark.parametrize('error,reason', [
    (wire.CapacityError('Stable capacity volume UUID observation failed'),
     'Stable capacity volume UUID observation failed'),
    (wire.CapacityError('Authoritative OS boot identity unavailable'),
     'Authoritative OS boot identity unavailable'),
    (wire.CapacityError('secret-token /private/user-data'), 'Unclassified compatibility verification failure'),
    (ValueError('secret-token'), 'Unclassified compatibility verification failure'),
    (OSError(errno.EACCES, 'secret-token', '/private/user-data'),
     'Unclassified compatibility verification failure'),
])
def test_only_fixed_verifier_messages_are_loggable(error, reason):
    assert failure_reason(error) == reason


def instance(error):
    broker = object.__new__(CapacityBroker)
    broker.mode, broker.compatible = 'capacity', True
    broker.activation_id, broker.boot = 'fixture-activation', 'fixture-boot'
    broker._clock = lambda: 123.0
    broker.lease_seconds = 10
    broker._watches = {}
    def fail():
        raise error
    broker._compatibility_proof = fail
    return broker


@pytest.mark.parametrize('phase', ['refresh', 'admission'])
def test_failure_is_bound_to_grants_and_still_refuses(phase, capsys, monkeypatch):
    monkeypatch.setattr('atelier.harness.capacity_broker.time.time', lambda: 456.0)
    broker = instance(wire.CapacityError('Capacity lane changed during verification'))
    held = dict(state='running', heartbeat=123.0, roster=[], request={'resources': {'memory_mib': 10240}})
    queued = dict(state='queued', heartbeat=123.0, roster=[])
    state = dict(epoch=20, records={'held': held, 'queued': queued})
    if phase == 'refresh':
        assert broker._refresh(state, 123.0)
    else:
        with pytest.raises(wire.CapacityError, match='compatibility changed'):
            broker._validate_compatibility(state)
    message = json.loads(capsys.readouterr().err.split(': ', 1)[1])
    assert message == dict(phase=phase, reason='Capacity lane changed during verification',
                          error_type='CapacityError', errno=None, observed_at=456.0,
                          observed_monotonic=123.0, epoch=20, activation_id='fixture-activation',
                          boot_id='fixture-boot', affected_request_ids=['held'], affected_request_count=1)
    assert not broker.compatible
    assert held['state'] == 'uncertain'
    assert held['request']['resources']['memory_mib'] == 10240
    assert queued['state'] == 'queued'
    # A later successful compatibility observation does not restore uncertain grants.
    broker._compatibility_proof = lambda: {'activation_id': 'fixture-activation'}
    assert not broker._refresh(state, 123.0)
    assert held['state'] == 'uncertain'


def test_os_error_does_not_log_paths_or_arbitrary_text_and_bounds_grant_list(capsys):
    broker = instance(OSError(errno.EIO, 'secret-token', '/private/user-data'))
    state = dict(epoch=20, records={str(i): {'state': 'running'} for i in range(80)})
    broker._report_compatibility_failure(state, OSError(errno.EIO, 'secret-token', '/private/user-data'),
                                         phase='refresh')
    output = capsys.readouterr().err
    assert 'secret-token' not in output and '/private/user-data' not in output
    message = json.loads(output.split(': ', 1)[1])
    assert message['errno'] == errno.EIO
    assert len(message['affected_request_ids']) == 32
    assert message['affected_request_count'] == 80


def test_activation_mismatch_is_logged_and_keeps_the_grant_uncertain(capsys):
    broker = instance(None)
    broker._compatibility_proof = lambda: {'activation_id': 'other-activation'}
    record = dict(state='running', heartbeat=123.0, roster=[])
    assert broker._refresh(dict(epoch=20, records={'held': record}), 123.0)
    assert record['state'] == 'uncertain'
    assert not broker.compatible
    message = json.loads(capsys.readouterr().err.split(': ', 1)[1])
    assert message['reason'] == 'Capacity activation changed'
    assert message['affected_request_ids'] == ['held']


@pytest.mark.parametrize('error_type', [BrokenPipeError, ValueError, TypeError, ImportError])
@pytest.mark.parametrize('phase', ['refresh', 'admission'])
def test_broken_diagnostic_output_does_not_change_refusal_or_retention(monkeypatch, error_type, phase):
    broker = instance(wire.CapacityError('Capacity lane changed during verification'))
    record = dict(state='running', heartbeat=123.0, roster=[])
    state = dict(epoch=20, records={'held': record})
    def broken(*args, **kwargs):
        raise error_type('unavailable diagnostic sink')
    monkeypatch.setattr('builtins.print', broken)
    if phase == 'admission':
        with pytest.raises(wire.CapacityError, match='compatibility changed'):
            broker._validate_compatibility(state)
    else:
        assert broker._refresh(state, 123.0)
    assert not broker.compatible
    assert record['state'] == 'uncertain'


@pytest.mark.parametrize('failure_point', ['import', 'serialize'])
def test_diagnostic_setup_failure_cannot_keep_a_grant_running(monkeypatch, failure_point):
    import builtins
    broker = instance(wire.CapacityError('Capacity lane changed during verification'))
    record = dict(state='running', heartbeat=123.0, roster=[])
    state = dict(epoch=20, records={'held': record})
    if failure_point == 'import':
        original_import = builtins.__import__
        def failing_import(name, *args, **kwargs):
            if name == 'atelier.harness.capacity_compat_diagnostics':
                raise ImportError('diagnostic module unavailable')
            return original_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, '__import__', failing_import)
    else:
        monkeypatch.setattr('atelier.harness.capacity_broker.json.dumps',
                            lambda *args, **kwargs: (_ for _ in ()).throw(TypeError('not serializable')))
    with pytest.raises(wire.CapacityError, match='compatibility changed'):
        broker._validate_compatibility(state)
    assert not broker.compatible
    assert record['state'] == 'uncertain'
