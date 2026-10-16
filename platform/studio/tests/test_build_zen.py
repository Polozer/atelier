"""Zen sponsor lifetime and staging failure boundaries, without native tools or services."""
from concurrent.futures import Future
import io
import json
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

import pytest

from atelier import build, build_zen
from atelier.build_cook import CookMode, Observer

READ = 'Reading oplog from http://[::1]:8558/prj/Example/oplog/Mac/entries?trim_by_referencedset=true'


@pytest.fixture
def live(tmp_path, monkeypatch):
    clock = [0.]
    birth = [1234]
    state = dict(healthy=True, attached=True, error=None)
    calls = []

    class Pool:
        def __init__(self, **kwargs):
            calls.append(('pool', kwargs))

        def submit(self, fn, *args):
            calls.append(('check', args))
            future = Future()
            result = dict(state)
            if not args[-1]:
                result.update(attached=False, error=None)
            future.set_result(result)
            return future

        def shutdown(self, **kwargs):
            calls.append(('shutdown', kwargs))

    monkeypatch.setattr(build_zen, 'started', lambda pid: birth[0])
    monkeypatch.setattr(build_zen.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(build_zen, 'ThreadPoolExecutor', Pool)
    lifecycle = build_zen.Lifecycle(tmp_path, tmp_path / 'engine', {'SAFE': 'input'})
    return SimpleNamespace(watch=lifecycle, clock=clock, birth=birth, state=state, calls=calls)


def tick(live, seconds=2):
    live.clock[0] += seconds
    live.watch.poll(55)


def test_nothing_starts_before_admission_and_closed_receipt_is_honest(live):
    assert not live.calls and live.watch.pid is None
    live.watch.close()
    report = json.loads(live.watch.path.read_text())
    assert report['child'] is None and report['health_checks'] == 0
    assert not live.calls


def test_sponsor_uses_admitted_root_through_cook_completion(live):
    tick(live)
    tick(live)
    live.watch.line('********** COOK COMMAND COMPLETED **********')
    tick(live)
    assert len([c for c in live.calls if c[0] == 'check']) == 3
    for _, args in [c for c in live.calls if c[0] == 'check']:
        assert args[2:4] == (55, 1234)
    tick(live, 31)
    tick(live)
    live.watch.close()
    report = json.loads(live.watch.path.read_text())
    assert report['attached_count'] == 2 and report['child'] == dict(pid=55, started=1234)
    assert report['first_attached_at'] <= report['cook_completed_at'] < report['last_attached_at']


def test_health_keeps_polling_but_attach_is_not_repeated_every_two_seconds(live):
    for _ in range(14):
        tick(live)
    assert live.watch.report['health_checks'] == 13
    assert live.watch.report['attached_count'] == 1
    assert sum(call[1][-1] for call in live.calls if call[0] == 'check') == 1


def test_failed_refresh_keeps_established_sponsorship(live):
    tick(live)
    tick(live)
    live.state.update(attached=False, error='zen attach exited 1')
    for _ in range(6):
        tick(live, 31)
    assert live.watch.sponsored and live.watch.report['failure'] is None


def test_server_recovery_requires_immediate_fresh_sponsorship(live):
    tick(live)
    tick(live)
    live.state.update(healthy=False, attached=False)
    tick(live)
    tick(live)
    assert not live.watch.sponsored and live.watch.next_attach == 0
    live.state.update(healthy=True, error='zen attach exited 1')
    tick(live)
    tick(live)
    with pytest.raises(RuntimeError, match='Cannot sponsor Zen'):
        tick(live, 60)


def test_healthy_slow_zen_read_has_no_elapsed_timeout(live):
    live.watch.line(READ)
    for _ in range(200):
        tick(live, 10)
    assert live.watch.report['failure'] is None


def test_unavailable_read_fails_at_observed_60_seconds(live):
    live.state.update(healthy=False, attached=False)
    live.watch.line(READ)
    tick(live)  # submit
    tick(live)  # first observed failure, t=4
    tick(live, 59)
    with pytest.raises(RuntimeError, match='60 seconds during staging reads'):
        tick(live, 1)
    live.watch.close()
    assert json.loads(live.watch.path.read_text())['failure']


def test_healthy_probe_resets_failure_window(live):
    live.state.update(healthy=False, attached=False)
    live.watch.line(READ)
    tick(live)
    tick(live)
    live.state.update(healthy=True, attached=True)
    tick(live, 58)  # consumes old failed check, submits healthy check
    tick(live)
    assert live.watch.unavailable_since is None
    live.state.update(healthy=False, attached=False)
    tick(live)
    tick(live)
    assert live.watch.unavailable_since == live.clock[0]


@pytest.mark.parametrize('line', ['Parsed 3 package entries from oplog.', 'unrelated stdout heartbeat'])
def test_later_chunk_reads_still_require_zen(live, line):
    live.state.update(healthy=False, attached=False)
    live.watch.line(READ)
    live.watch.line(line)
    tick(live)
    tick(live)
    with pytest.raises(RuntimeError, match='during staging reads'):
        tick(live, 60)


def test_stage_end_clears_watchdog_but_not_sponsorship(live):
    live.state.update(healthy=False, attached=False)
    live.watch.line(READ)
    tick(live)
    tick(live)
    live.watch.line('********** STAGE COMMAND COMPLETED **********')
    tick(live, 100)
    assert live.watch.unavailable_since is None and not live.watch.reading


def test_non_zen_build_does_not_fail_when_no_server_exists(live):
    live.state.update(healthy=False, attached=False)
    for _ in range(5):
        tick(live, 100)
    assert live.watch.report['failure'] is None


def test_repeated_attach_failure_is_reported_even_before_staging(live):
    live.state.update(attached=False, error='zen attach exited 1')
    tick(live)
    tick(live)
    with pytest.raises(RuntimeError, match='Cannot sponsor Zen'):
        tick(live, 60)


def test_root_exit_final_callback_never_submits_new_attach(live):
    tick(live)
    count = len(live.calls)
    live.birth[0] = None
    tick(live)
    assert len(live.calls) == count
    live.watch.close()
    assert live.watch.stopped.is_set()
    with pytest.raises(RuntimeError, match='closed'):
        tick(live)


def test_reused_root_pid_refuses(live):
    tick(live)
    live.birth[0] = 9999
    with pytest.raises(RuntimeError, match='identity changed'):
        tick(live)


def test_pending_network_task_never_blocks_guard_poll(live, monkeypatch):
    future = Future()
    class Pending:
        def __init__(self, **kwargs):
            pass
        def submit(self, *args):
            return future
        def shutdown(self, **kwargs):
            future.cancel()
    monkeypatch.setattr(build_zen, 'ThreadPoolExecutor', Pending)
    tick(live)
    tick(live, 100)
    assert not future.done()
    live.watch.close()
    assert future.cancelled()


@pytest.fixture
def client(monkeypatch):
    calls = []
    class Connection:
        def __init__(self, host, port, timeout):
            calls.append((host, port, timeout))
        def request(self, method, path):
            calls.append((method, path))
        def getresponse(self):
            return SimpleNamespace(status=200)
        def close(self):
            calls.append('closed')
    monkeypatch.setattr(build_zen.http.client, 'HTTPConnection', Connection)
    monkeypatch.setattr(build_zen, 'started', lambda pid: 1234)
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(build_zen.subprocess, 'run', run)
    return calls


def test_attach_only_runs_installed_client_with_owned_pid_and_finite_bounds(client):
    result = build_zen.check(Path('/engine/zen'), {'EXACT': 'env'}, 55, 1234, threading.Event())
    assert result == dict(healthy=True, attached=True, error=None)
    argv, options = client[-1]
    assert argv == ['/engine/zen', 'attach', '--port', '8558', '--owner-pid', '55']
    assert options['timeout'] == 3 and options['env'] == {'EXACT': 'env'}
    assert client[0] == ('::1', 8558, .5) and 'closed' in client


def test_health_only_check_does_not_launch_attach_client(client):
    result = build_zen.check(Path('/engine/zen'), {}, 55, 1234, threading.Event(), False)
    assert result == dict(healthy=True, attached=False, error=None)
    assert client[-1] == 'closed'


@pytest.mark.parametrize('dead', [True, False])
def test_no_attach_if_owner_exited_or_lifecycle_closed(client, monkeypatch, dead):
    stopped = threading.Event()
    if dead:
        monkeypatch.setattr(build_zen, 'started', lambda pid: 9999)
    else:
        stopped.set()
    result = build_zen.check(Path('/engine/zen'), {}, 55, 1234, stopped)
    assert result['healthy'] and not result['attached']
    assert not any(isinstance(call, tuple) and isinstance(call[0], list) for call in client)


def test_unavailable_health_never_runs_attach(client, monkeypatch):
    monkeypatch.setattr(build_zen.http.client.HTTPConnection, 'getresponse', lambda _: SimpleNamespace(status=503))
    assert not build_zen.check(Path('/engine/zen'), {}, 55, 1234, threading.Event())['healthy']
    assert client[-1] == 'closed'


def test_attach_timeout_is_a_failed_sponsor_attempt(client, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('zen attach', 3)
    monkeypatch.setattr(build_zen.subprocess, 'run', timeout)
    result = build_zen.check(Path('/engine/zen'), {}, 55, 1234, threading.Event())
    assert result == dict(healthy=True, attached=False, error='TimeoutExpired')


def test_log_observer_forwards_only_new_guard_output(tmp_path):
    output = tmp_path / 'stdout.log'
    output.write_text(READ + '\n')
    lines = []
    observer = Observer(tmp_path, CookMode.DEFAULT, on_line=lines.append)
    observer.poll(55)
    observer.poll(55)
    assert lines == [READ]
    observer.finish(success=False)


@pytest.mark.parametrize('failure', [False, True])
def test_package_guard_callback_wires_sponsorship_and_failure_without_new_lifecycle(tmp_path, monkeypatch, failure):
    events = []
    class Lifecycle:
        def __init__(self, folder, engine, env):
            events.append('construct')
        def line(self, line):
            events.append(line)
        def poll(self, pid):
            events.append(('poll', pid))
            if failure:
                raise RuntimeError('Zen unavailable test')
        def close(self):
            events.append('close')
    monkeypatch.setattr(build_zen, 'Lifecycle', Lifecycle)
    ctx = SimpleNamespace(unreal_root=tmp_path / 'engine', game='fixture', logs=tmp_path / 'logs',
                          env=lambda extra: {})
    cmd = build.UnrealPackage('Fixture', Path('archive'))
    step = build.Step('unreal.package', [cmd], heavy=True)
    def guard(argv, folder, **kwargs):
        assert argv == ['original-UAT'] and kwargs['kind'] == 'compile'
        assert kwargs['timeout'] == cmd.timeout and kwargs['watch'] == cmd.watch
        folder.mkdir(parents=True)
        (folder / 'stdout.log').write_text(READ + '\nBUILD SUCCESSFUL\n')
        try:
            kwargs['on_poll'](55)
        except BaseException:
            events.append('normal-guard-unwind')
            raise
        return 0
    monkeypatch.setattr(build.guarded, 'run', guard)
    if failure:
        with pytest.raises(RuntimeError, match='Zen unavailable test'):
            build.run_argv(ctx, step, cmd, ['original-UAT'], (), io.StringIO(), None, None)
        assert events[-2:] == ['normal-guard-unwind', 'close']
        assert not json.loads((ctx.logs / 'unreal.package.guard/cook-observation.json').read_text())['validated']
    else:
        build.run_argv(ctx, step, cmd, ['original-UAT'], (), io.StringIO(), None, None)
        assert ('poll', 55) in events and READ in events and events[-1] == 'close'
