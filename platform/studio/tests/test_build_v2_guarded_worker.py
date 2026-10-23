"""The build-v2 guarded bridge reports guard facts honestly and passes descriptors narrowly.

The bridge runs in a subprocess with a fake `run` standing in for `guarded.run` (no admission is
requested). The worker is the disposable protocol fixture with one descendant.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from atelier.build_v2.guarded_worker import classify, cleanup

ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT / 'platform/build-v2/tests/fixtures/disposable_worker.py'
darwin = pytest.mark.skipif(sys.platform != 'darwin', reason='process identities use macOS libproc')

FAKE_GUARD = r'''
import json, os, signal, subprocess, sys, time
from pathlib import Path
from atelier.harness.capacity_protocol import process_start

def run(command, folder, timeout=0., purpose=None, env=None, limit_gib=10., kind='job', on_slot=None,
        on_poll=None, pass_fds=(), queue_seconds=None, custody_fds=()):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    scenario = os.environ['FAKE_GUARD']
    (folder / 'fake-call.json').write_text(json.dumps(dict(
        pass_fds=list(pass_fds), custody=[list(os.fstat(fd)[1:3][::-1]) for fd in custody_fds],
        kind=kind, limit_gib=limit_gib, timeout=timeout, queue_seconds=queue_seconds)))
    if scenario == 'queue':
        while True:
            time.sleep(.02)  # stands in for waiting on the broker; TERM unwinds it
    on_slot('capacity', 'fake admission')
    with (folder / 'stdout.log').open('w') as log:
        child = subprocess.Popen(command, env=env, pass_fds=pass_fds, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT)
    start = process_start(child.pid)
    state = 'memory_limit' if scenario == 'memory' else 'running'
    (folder / 'memory-health.json').write_text(json.dumps(dict(pid=child.pid, process_start=start, state=state)))
    tree = dict(owner=child.pid, owner_started=start, state='child_exited', cleanup_complete=scenario != 'unconfirmed',
                processes=[])
    try:
        on_poll(child.pid)
        if scenario == 'memory':
            child.kill()
            child.wait()
            tree.update(state='memory_limit')
            raise SystemExit('process memory guard stopped the child')
        code = child.wait()
        if scenario == 'capacity':
            raise RuntimeError('Capacity exit remains uncertain; reservation and named locks retained')
        return code
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
            tree.update(state='terminated')
        (folder / 'memory-health-tree.json').write_text(json.dumps(tree))
'''


class Bridge:
    def __init__(self, tmp_path, scenario, custody=()):
        (tmp_path / 'fakeguard.py').write_text(FAKE_GUARD)
        self.report = tmp_path / 'attempt-1'
        self.report.mkdir()
        request_r, self.request_w = os.pipe()
        self.response_r, response_w = os.pipe()
        events_r, events_w = os.pipe()
        liveness_r, self.liveness_w = os.pipe()
        spec_r, spec_w = os.pipe()
        self.fd_report = tmp_path / 'worker-fds.json'
        spec = dict(program=sys.executable, args=[str(WORKER), 'normal'],
                    env=dict(PATH=os.environ['PATH'], WORKER_FD_REPORT=str(self.fd_report)))
        os.write(spec_w, json.dumps(spec).encode())
        os.close(spec_w)
        inherited = [request_r, response_w, events_w, liveness_r, spec_r, *custody]
        argv = ['--report', str(self.report), '--purpose', 'bridge test', '--memory-gib', '1', '--timeout', '30',
                '--events-fd', str(events_w), '--liveness-fd', str(liveness_r), '--spec-fd', str(spec_r),
                '--request-fd', str(request_r), '--response-fd', str(response_w)]
        for fd in custody:
            argv += ['--custody-fd', str(fd)]
        code = ('import sys; sys.path.insert(0, sys.argv[1]); import fakeguard; '
                'from atelier.build_v2 import guarded_worker; sys.exit(guarded_worker.main(sys.argv[2:], run=fakeguard.run))')
        self.process = subprocess.Popen([sys.executable, '-c', code, str(tmp_path), *argv], pass_fds=inherited,
                                        env={**os.environ, 'FAKE_GUARD': scenario})
        for fd in (request_r, response_w, events_w, liveness_r, spec_r):
            os.close(fd)
        self.events = os.fdopen(events_r, 'r')

    def next(self):
        line = self.events.readline()
        assert line, 'the bridge closed its events before finishing'
        return json.loads(line)

    def hello_then_close(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('v2protocol', ROOT / 'platform/studio/atelier/build_v2/protocol.py')
        protocol = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(protocol)
        with os.fdopen(self.response_r, 'rb', buffering=0) as stream:
            payload = protocol.read_payload(stream)
        assert protocol.decode_payload(protocol.RESPONSE, payload)['type'] == 'hello'
        os.close(self.request_w)

    def finish(self):
        return self.process.wait(timeout=30)


@darwin
def test_normal_attempt_reports_pinned_identity_and_confirmed_cleanup(tmp_path):
    import fcntl
    lock = os.open(tmp_path / 'checkout.lock', os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    custody = fcntl.fcntl(lock, fcntl.F_DUPFD_CLOEXEC, 3)
    bridge = Bridge(tmp_path, 'normal', custody=[custody])
    os.close(custody)
    assert bridge.next() == {'event': 'queued'}
    assert bridge.next() == {'event': 'admitted'}
    started = bridge.next()
    assert started['event'] == 'child_started' and started['pid'] > 0 and started['started'] and started['boot']
    bridge.hello_then_close()
    exited = bridge.next()
    assert exited == dict(event='child_exited', pid=started['pid'], started=started['started'], boot=started['boot'],
                          returncode=0, stopped_by=None)
    assert bridge.next() == dict(event='finished', cleanup='confirmed', reason=None)
    assert bridge.finish() == 0
    call = json.loads((bridge.report / 'fake-call.json').read_text())
    info = os.fstat(lock)
    assert call['kind'] == 'job' and call['limit_gib'] == 1 and len(call['pass_fds']) == 2
    assert call['custody'] == [[info.st_dev, info.st_ino]], 'custody goes to the monitor, not pass_fds'
    worker = json.loads(bridge.fd_report.read_text())
    assert sorted(map(int, worker['open'])) == sorted([worker['request_fd'], worker['response_fd']])
    assert [info.st_dev, info.st_ino] not in worker['open'].values()
    os.close(lock)


@darwin
def test_queued_cancel_and_controller_loss_spawn_nothing_and_confirm_the_withdrawal(tmp_path):
    for how in ('signal', 'liveness'):
        folder = tmp_path / how
        folder.mkdir()
        bridge = Bridge(folder, 'queue')
        assert bridge.next() == {'event': 'queued'}
        if how == 'signal':
            bridge.process.send_signal(signal.SIGTERM)
        else:
            os.close(bridge.liveness_w)
        assert bridge.next() == dict(event='finished', cleanup='confirmed', reason=None)
        assert bridge.finish() == 1
        assert not (bridge.report / 'stdout.log').exists()


@darwin
@pytest.mark.parametrize('scenario,stopped_by,confirmed', [
    ('memory', 'guard', True), ('unconfirmed', None, False), ('capacity', None, False)])
def test_guard_stops_and_uncertain_cleanup_are_reported_as_such(tmp_path, scenario, stopped_by, confirmed):
    bridge = Bridge(tmp_path, scenario)
    assert bridge.next()['event'] == 'queued'
    assert bridge.next()['event'] == 'admitted'
    assert bridge.next()['event'] == 'child_started'
    if scenario != 'memory':
        bridge.hello_then_close()
    exited = bridge.next()
    assert exited['event'] == 'child_exited' and exited['stopped_by'] == stopped_by
    finished = bridge.next()
    assert finished['cleanup'] == ('confirmed' if confirmed else 'unconfirmed')
    assert confirmed or finished['reason']
    assert bridge.finish() == 1


def test_classification_and_cleanup_rules_are_conservative():
    assert classify(None, {'state': 'memory_limit'}, None, False) == 'guard'
    assert classify(SystemExit('child exceeded 30 s'), {'state': 'running'}, None, False) == 'deadline'
    assert classify(SystemExit(143), None, None, False) == 'cancel'
    assert classify(None, None, None, True) == 'cancel'
    assert classify(None, {'state': 'running'}, {'state': 'child_exited'}, False) is None
    tree = dict(owner=7, owner_started=70, state='child_exited', cleanup_complete=True, processes=[])
    assert cleanup(None, (7, 70), {}, tree) == (True, None)
    assert cleanup(SystemExit(143), None, None, None) == (True, None)
    assert not cleanup(RuntimeError('broker'), None, None, None)[0]
    assert not cleanup(None, (7, 70), {}, None)[0]
    assert not cleanup(None, (8, 80), {}, tree)[0]
    assert not cleanup(None, (7, 70), {}, {**tree, 'cleanup_complete': False})[0]
    assert not cleanup(None, (7, 70), {}, {**tree, 'custody': {'held': True}})[0]
