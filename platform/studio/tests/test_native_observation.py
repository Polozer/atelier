"""Transient foreign-scan failures retry only after the owned observer positively exits."""
import os
import subprocess
from types import SimpleNamespace

import pytest

from atelier import capacity_protocol as wire
from atelier.safety import render_lock as locks


def stable_pins(monkeypatch):
    monkeypatch.setattr(wire, 'process_start', lambda pid: 123)
    monkeypatch.setattr(wire, 'live', lambda pin: True)


def test_transient_scan_uses_new_complete_snapshot_and_keeps_native_candidates(monkeypatch, capsys):
    calls = []
    def table(*, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise OSError('Native process observation timed out')
        return [(os.getpid(), 1, 'Python'), (42, 1, 'Blender')]
    monkeypatch.setattr(locks, 'process_table', table)
    stable_pins(monkeypatch)
    assert locks.native_candidates() == [[42, 123]]
    assert calls == [2., 2.]
    assert 'retrying once with a fresh snapshot' in capsys.readouterr().out


def test_persistent_observation_failure_has_only_one_retry(monkeypatch):
    calls = []
    def failed(**kwargs):
        calls.append(kwargs)
        raise OSError('Native process observation timed out')
    monkeypatch.setattr(locks, 'process_table', failed)
    with pytest.raises(OSError, match='timed out'):
        locks.native_candidates()
    assert len(calls) == 2


@pytest.mark.parametrize('settled', [True, False])
def test_pending_observer_must_positively_exit_before_fresh_scan(monkeypatch, settled):
    calls = []
    def wait(*, timeout):
        calls.append(('wait', timeout))
        if not settled:
            raise subprocess.TimeoutExpired('owned-ps', timeout)
        return -9
    error = locks.ObserverReapError(SimpleNamespace(wait=wait))
    def table(**kwargs):
        calls.append(('scan',))
        if calls == [('scan',)]:
            raise error
        return [(os.getpid(), 1, 'Python')]
    monkeypatch.setattr(locks, 'process_table', table)
    if settled:
        assert locks.native_candidates() == []
        assert calls == [('scan',), ('wait', 1.), ('scan',)]
    else:
        with pytest.raises(locks.ObserverReapError) as stopped:
            locks.native_candidates()
        assert stopped.value is error
        assert calls == [('scan',), ('wait', 1.)]


def test_failed_second_observer_does_not_start_a_third(monkeypatch):
    calls = []
    def table(**kwargs):
        calls.append('scan')
        if len(calls) == 1:
            raise OSError('initial failure')
        raise locks.ObserverReapError(SimpleNamespace(wait=lambda **kw: pytest.fail('third attempt')))
    monkeypatch.setattr(locks, 'process_table', table)
    with pytest.raises(locks.ObserverReapError):
        locks.native_candidates()
    assert calls == ['scan', 'scan']


@pytest.mark.parametrize('failure', ['unstable', 'lookup-error'])
def test_native_identity_failures_are_not_retried(monkeypatch, failure):
    calls = []
    def table(**kwargs):
        calls.append('scan')
        return [(os.getpid(), 1, 'Python'), (42, 1, 'Blender')]
    monkeypatch.setattr(locks, 'process_table', table)
    stable_pins(monkeypatch)
    if failure == 'unstable':
        monkeypatch.setattr(wire, 'live', lambda pin: False)
        expected = wire.CapacityError
    else:
        def missing(pid):
            raise ProcessLookupError('identity vanished')
        monkeypatch.setattr(wire, 'process_start', missing)
        expected = ProcessLookupError
    with pytest.raises(expected):
        locks.native_candidates()
    assert calls == ['scan']


def test_incomplete_listing_is_discarded_before_a_complete_retry(monkeypatch):
    listings = iter([f'{os.getpid()} 1 Python\n88 1 Blender\npartial',
                     f'{os.getpid()} 1 Python\n42 1 Blender\n'])
    monkeypatch.setattr(locks, '_bounded_process_listing', lambda timeout: next(listings))
    stable_pins(monkeypatch)
    assert locks.native_candidates() == [[42, 123]]


@pytest.mark.parametrize('failure', ['close-error', 'kill-race', 'reap-timeout'])
def test_observer_cleanup_runs_even_when_pipe_close_fails(monkeypatch, failure):
    calls = []
    class Ready:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def register(self, *args): pass
        def select(self, timeout): return [True]
    def close():
        calls.append('close')
        if failure == 'close-error':
            raise OSError('pipe close failed')
    def kill():
        calls.append('kill')
        if failure == 'kill-race':
            raise ProcessLookupError('already exited')
    def wait(*, timeout):
        calls.append(('wait', timeout))
        if failure == 'reap-timeout':
            raise subprocess.TimeoutExpired('owned-ps', timeout)
        return -9
    process = SimpleNamespace(stdout=SimpleNamespace(fileno=lambda: 123, close=close),
                              poll=lambda: None, kill=kill, wait=wait)
    monkeypatch.setattr(locks.subprocess, 'Popen', lambda *args, **kwargs: process)
    monkeypatch.setattr(locks.selectors, 'DefaultSelector', Ready)
    monkeypatch.setattr(locks.os, 'read', lambda *args: b'x' * (1024*1024 + 1))
    expected = locks.ObserverReapError if failure == 'reap-timeout' else OSError
    with pytest.raises(expected) as error:
        locks._bounded_process_listing(2.)
    assert calls == ['close', 'kill', ('wait', 1.)]
    if failure == 'reap-timeout':
        assert error.value.process is process
