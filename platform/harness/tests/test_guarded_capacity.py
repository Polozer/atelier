"""Exercise the actual guarded launcher hook with small owned Python children."""
from contextlib import contextmanager
import os
import sys
from types import SimpleNamespace

import pytest

from atelier.harness.safety import guarded


class Admission:
    def __init__(self, events, *, fail=None):
        self.events, self.fail = events, fail
        self.writer = None
        self.child = None
        self.final = None

    def offer(self):
        self.events.append('offer')
        if self.fail == 'offer':
            raise RuntimeError('broker unavailable')

    def gate(self):
        reader, self.writer = os.pipe()
        self.events.append('gate')
        return reader

    def start(self, **binding):
        self.events.append('grant')
        self.child = binding
        assert self.events.index('process-ready') < self.events.index('grant')
        assert self.events.index('tree-ready') < self.events.index('grant')
        if self.fail == 'grant':
            raise RuntimeError('broker restarted before GO')
        os.write(self.writer, b'1')
        os.close(self.writer)
        self.writer = None

    def check(self, *, descendants):
        self.events.append('heartbeat')
        if self.fail == 'heartbeat':
            raise RuntimeError('broker lost during run')
        return {'state': 'running', 'admission': True}

    def close(self, *, child=None, child_start=None, descendants=()):
        self.events.append('close')
        if self.writer is not None:
            os.close(self.writer)
            self.writer = None
        if child is not None:
            assert child.poll() is not None, 'capacity closed before child reap'
        self.final = (child, child_start, descendants)


@pytest.fixture
def guards(monkeypatch):
    events = []

    @contextmanager
    def locked(purpose, **kwargs):
        assert kwargs['exclusive_bridge'] is True
        assert kwargs['small_gib'] is None
        events.append('bridge')
        kwargs['on_slot']('big', 'test bridge')
        try:
            yield
        finally:
            events.append('unlock')

    @contextmanager
    def process_monitor(*args, **kwargs):
        events.append('process-attach')
        try:
            monitor = SimpleNamespace(pid=os.getpid(), returncode=None)
            monitor.poll = lambda: monitor.returncode
            def wait(timeout):
                events.append('process-finish'); monitor.returncode = 0; return 0
            monitor.wait = wait
            yield monitor
        finally:
            events.append('process-detach')

    @contextmanager
    def tree_monitor(*args, **kwargs):
        events.append('tree-attach')
        try:
            yield SimpleNamespace(process=SimpleNamespace(pid=os.getpid()),
                                  ready=lambda: events.append('tree-ready'),
                                  check=lambda: events.append('tree-check'),
                                  finish=lambda: events.append('tree-finish'))
        finally:
            events.append('tree-detach')

    monkeypatch.setattr(guarded, 'render_lock', locked)
    monkeypatch.setattr(guarded, 'attach_memory_guard', process_monitor)
    monkeypatch.setattr(guarded, 'attach_tree', tree_monitor)
    monkeypatch.setattr(guarded, 'wait_ready', lambda *args: events.append('process-ready'))
    return events


def test_capacity_go_follows_guards_and_close_follows_reap(tmp_path, guards):
    session = Admission(guards)
    result = guarded.run([sys.executable, '-c', 'print("executed")'], tmp_path / 'guard',
                         admission=session, small_gib=1)
    assert result == 0
    assert 'executed' in (tmp_path / 'guard/stdout.log').read_text()
    assert guards.index('offer') < guards.index('bridge') < guards.index('gate')
    assert guards.index('close') < guards.index('tree-detach') < guards.index('unlock')
    assert guards.count('close') == 1
    assert guards.count('tree-finish') == 1
    assert session.child['limit_bytes'] == 10 * 1024**3
    assert session.final[0].returncode == 0


@pytest.mark.parametrize('performance', [False, True])
def test_configured_guarded_launch_forwards_performance_before_admission(tmp_path, guards, monkeypatch, performance):
    from atelier.harness import capacity_runtime
    requested = []
    session = Admission(guards)

    def configured(**options):
        requested.append(options)
        return session

    monkeypatch.setattr(capacity_runtime, 'configured_session', configured)
    assert guarded.run([sys.executable, '-c', 'pass'], tmp_path / 'guard', performance=performance) == 0
    assert len(requested) == 1 and requested[0]['performance'] is performance
    assert guards.count('offer') == guards.count('bridge') == guards.count('close') == 1


def test_explicit_session_cannot_silently_ignore_performance_window(tmp_path, guards):
    with pytest.raises(ValueError, match='must request performance exclusion'):
        guarded.run([sys.executable, '-c', 'pass'], tmp_path, admission=Admission(guards), performance=True)
    assert guards == []


def test_explicit_performance_session_uses_its_one_existing_admission(tmp_path, guards):
    session = Admission(guards)
    session.request = {'performance': True}
    assert guarded.run([sys.executable, '-c', 'pass'], tmp_path, admission=session, performance=True) == 0
    assert guards.count('offer') == guards.count('close') == 1


@pytest.mark.parametrize('failure', ['offer', 'grant', 'heartbeat'])
def test_capacity_failure_does_not_fall_back_and_owned_child_is_reaped(tmp_path, guards, failure):
    session = Admission(guards, fail=failure)
    marker = tmp_path / 'executed'
    code = f'from pathlib import Path; import time; Path({str(marker)!r}).touch(); time.sleep(30)'
    with pytest.raises(RuntimeError, match='broker'):
        guarded.run([sys.executable, '-c', code], tmp_path / 'guard', admission=session)
    assert guards.count('close') == 1
    if failure == 'offer':
        assert 'bridge' not in guards
    if failure in ('offer', 'grant'):
        assert not marker.exists()
    if session.final[0] is not None:
        assert session.final[0].returncode is not None
        assert guards.index('close') < guards.index('process-detach') < guards.index('unlock')


@pytest.mark.parametrize('failure', ['grant', 'heartbeat'])
def test_failed_workload_settles_monitor_once_before_capacity_close(tmp_path, guards, failure):
    session = Admission(guards, fail=failure)
    close = session.close
    def release_only_after_terminal(**kwargs):
        assert guards.count('tree-finish') == 1, 'broker close preceded terminal publication'
        close(**kwargs)
    session.close = release_only_after_terminal
    with pytest.raises(RuntimeError, match='broker'):
        guarded.run([sys.executable, '-c', 'import time; time.sleep(30)'],
                    tmp_path/'guard', admission=session)
    assert session.final[0].returncode is not None
    assert guards.index('tree-finish') < guards.index('close') < guards.index('tree-detach')
    assert guards.count('tree-finish') == 1 and guards.count('close') == 1


def test_failed_terminal_settlement_is_not_retried_and_still_attempts_close(tmp_path, guards, monkeypatch):
    original = guarded.attach_tree
    @contextmanager
    def failed(*args, **kwargs):
        with original(*args, **kwargs) as monitor:
            def finish():
                guards.append('tree-finish')
                raise RuntimeError('terminal monitor failed')
            monitor.finish = finish
            yield monitor
    monkeypatch.setattr(guarded, 'attach_tree', failed)
    session = Admission(guards)
    with pytest.raises(RuntimeError, match='terminal monitor failed'):
        guarded.run([sys.executable, '-c', 'pass'], tmp_path/'guard', admission=session)
    assert session.final[0].returncode == 0
    assert guards.count('tree-finish') == guards.count('close') == 1
    assert guards.index('tree-finish') < guards.index('close') < guards.index('tree-detach')


def test_lock_refusal_cancels_unallocated_offer(tmp_path, guards, monkeypatch):
    @contextmanager
    def refused(*args, **kwargs):
        raise RuntimeError('legacy lane occupied')
        yield
    monkeypatch.setattr(guarded, 'render_lock', refused)
    session = Admission(guards)
    with pytest.raises(RuntimeError, match='lane occupied'):
        guarded.run([sys.executable, '-c', 'pass'], tmp_path / 'guard', admission=session)
    assert guards == ['offer', 'close']
    assert session.final == (None, None, ())


def test_missing_launcher_identity_refuses_before_tree_or_guards(tmp_path, guards, monkeypatch):
    monkeypatch.setattr(guarded.process_tree, 'started', lambda pid: None)
    monkeypatch.setattr(guarded, 'Descendants', lambda *args: pytest.fail('an unpinned tree was constructed'))
    session = Admission(guards)
    marker = tmp_path / 'executed'
    with pytest.raises(RuntimeError, match='could not pin'):
        guarded.run([sys.executable, '-c', f'open({str(marker)!r},"w").write("ran")'],
                    tmp_path / 'guard', admission=session)
    assert not marker.exists()
    assert session.final[0].returncode is not None
    assert 'process-attach' not in guards and 'grant' not in guards


@pytest.mark.parametrize('failed_guard', ['process', 'tree'])
def test_guard_readiness_failure_never_executes_and_closes_before_detach(tmp_path, guards, monkeypatch, failed_guard):
    def refuse(*args):
        raise RuntimeError('guard readiness failed')

    if failed_guard == 'process':
        monkeypatch.setattr(guarded, 'wait_ready', refuse)
    else:
        original = guarded.attach_tree

        @contextmanager
        def unready(*args, **kwargs):
            with original(*args, **kwargs) as monitor:
                monitor.ready = refuse
                yield monitor
        monkeypatch.setattr(guarded, 'attach_tree', unready)
    session = Admission(guards)
    marker = tmp_path / 'executed'
    with pytest.raises(RuntimeError, match='guard readiness'):
        guarded.run([sys.executable, '-c', f'open({str(marker)!r},"w").write("ran")'],
                    tmp_path / 'guard', admission=session)
    assert not marker.exists() and 'grant' not in guards
    assert session.final[0].returncode is not None
    assert guards.index('close') < guards.index('tree-detach') < guards.index('unlock')


def test_uncertain_release_fails_successful_command_and_still_unwinds(tmp_path, guards):
    session = Admission(guards)
    close = session.close

    def uncertain(**kwargs):
        close(**kwargs)
        raise RuntimeError('capacity release uncertain')
    session.close = uncertain
    with pytest.raises(RuntimeError, match='release uncertain'):
        guarded.run([sys.executable, '-c', 'pass'], tmp_path / 'guard', admission=session)
    assert session.final[0].returncode == 0
    assert guards.count('close') == 1
    assert guards.index('close') < guards.index('tree-detach') < guards.index('unlock')


@pytest.mark.parametrize('options', [dict(lock=False), dict(fitting_gib=1)])
def test_capacity_hook_cannot_bypass_legacy_bridge(tmp_path, options):
    with pytest.raises(ValueError, match='legacy bridge'):
        guarded.run([sys.executable, '-c', 'pass'], tmp_path, admission=object(), **options)


@pytest.mark.parametrize('case', ['success', 'nonzero-root', 'surviving-root', 'failed-final-root',
                                   'failed-final-tree', 'missing-terminal', 'broker-error', 'late-root-stop',
                                   'unfinished-root-monitor', 'failed-root-monitor'])
def test_terminal_heartbeat_requires_actual_wait_final_guards_and_close(tmp_path, guards, monkeypatch, case):
    from atelier.harness.capacity_client import CapacityError
    class Finishing(Admission):
        checks = 0
        def check(self, *, descendants):
            self.checks += 1
            guards.append('capacity-check-' + str(self.checks))
            if case == 'broker-error': raise CapacityError('broker unavailable')
            if self.checks == 1:
                return dict(state='uncertain', admission=False, finish_required=True)
            if case == 'missing-terminal': return dict(state='uncertain', admission=False, finish_required=True)
            return dict(state='released', admission=False, terminal=True)
    session = Finishing(guards)
    original_check = guarded.check_root_guard
    def final_root(child, monitor, report, *, final=False):
        if final:
            guards.append('final-root')
            if case == 'failed-final-root': raise RuntimeError('root guard memory_limit')
        if case == 'late-root-stop': original_check(child, monitor, report, final=final)
    monkeypatch.setattr(guarded, 'check_root_guard', final_root)
    if case in ('late-root-stop', 'unfinished-root-monitor', 'failed-root-monitor'):
        import json, subprocess
        original_process = guarded.attach_memory_guard
        @contextmanager
        def late_monitor(pid, report, **kwargs):
            with original_process(pid, report, **kwargs) as monitor:
                def wait(timeout):
                    if case == 'unfinished-root-monitor': raise subprocess.TimeoutExpired('guard', timeout)
                    monitor.returncode = 1 if case == 'failed-root-monitor' else 0
                    if case == 'late-root-stop':
                        report.write_text(json.dumps(dict(pid=pid, state='memory_limit')))
                    return monitor.returncode
                monitor.wait = wait
                yield monitor
        monkeypatch.setattr(guarded, 'attach_memory_guard', late_monitor)
    if case == 'failed-final-tree':
        original = guarded.attach_tree
        @contextmanager
        def broken(*args, **kwargs):
            with original(*args, **kwargs) as tree:
                def finish(): raise RuntimeError('aggregate memory_limit')
                tree.finish = finish
                yield tree
        monkeypatch.setattr(guarded, 'attach_tree', broken)
    seconds = 10 if case == 'surviving-root' else .15
    code = 5 if case == 'nonzero-root' else 0
    command = [sys.executable, '-c', f'import time; time.sleep({seconds}); raise SystemExit({code})']
    if case in ('success', 'nonzero-root'):
        assert guarded.run(command, tmp_path / 'guard', admission=session) == code
        assert guards.index('tree-finish') < guards.index('final-root') < guards.index('capacity-check-2') < guards.index('close')
        assert session.final[0].returncode == code
    else:
        with pytest.raises((RuntimeError, CapacityError, SystemExit), match='surviving launcher|memory_limit|not affirmatively|broker unavailable|memory guard .*after capacity completion'):
            guarded.run(command, tmp_path / 'guard', admission=session)
    assert guards.count('close') == 1 and session.final[0].poll() is not None
