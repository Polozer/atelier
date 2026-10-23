"""Stand-in for the guarded bridge in hosted T0 tests. It admits nothing and guards nothing.

It accepts the real bridge's arguments and descriptors, records what it inherited, and reports
scripted guard observations as JSON lines on the events descriptor. The real bridge
(`atelier.build_v2.guarded_worker`) calls `guarded.run`; this fixture only spawns the worker
directly so the Rust adapter and lifecycle can be exercised on any host. Stdlib only.

Usage: fake_bridge.py SCENARIO --report DIR ... -- (the real bridge flags). Scenarios:
normal, queue_forever (never admitted; holds until stopped), guard_stop (the "guard" kills the
worker), foreign_exit (reports another identity's exit), unconfirmed (cleanup not confirmed),
spec_closed (closes its spec descriptor unread, so the launcher's spec write fails after the spawn;
it then waits to be stopped and reports nothing).
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

stopping = threading.Event()


def descriptors():
    folder = '/dev/fd' if sys.platform == 'darwin' else '/proc/self/fd'
    found = {}
    for name in os.listdir(folder):
        fd = int(name)
        if fd < 3:
            continue
        try:
            value = os.fstat(fd)
        except OSError:
            continue
        found[fd] = [value.st_dev, value.st_ino]
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('scenario')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--purpose', required=True)
    parser.add_argument('--memory-gib', type=int, required=True)
    parser.add_argument('--timeout', type=float, required=True)
    parser.add_argument('--queue-wait', type=float)
    for name in ('events', 'liveness', 'spec', 'request', 'response'):
        parser.add_argument(f'--{name}-fd', type=int, required=True)
    parser.add_argument('--custody-fd', type=int, action='append', default=[])
    args = parser.parse_args()
    (args.report / 'inherited.json').write_text(json.dumps({
        'open': descriptors(), 'cwd': os.getcwd(), 'custody': args.custody_fd,
        'events': args.events_fd, 'liveness': args.liveness_fd, 'spec': args.spec_fd,
        'request': args.request_fd, 'response': args.response_fd}))
    for fd in (args.events_fd, args.liveness_fd, args.spec_fd, *args.custody_fd):
        os.set_inheritable(fd, False)
    if args.scenario == 'spec_closed':
        os.close(args.spec_fd)
        while True:
            time.sleep(.02)  # until the launcher's SIGTERM; no receipt is ever written
    with os.fdopen(args.spec_fd, 'rb') as stream:
        spec = json.loads(stream.read())
    events = os.fdopen(args.events_fd, 'w', buffering=1)

    def emit(event, **fields):
        try:
            events.write(json.dumps({'event': event, **fields}) + '\n')
        except BrokenPipeError:
            pass  # the controller is gone; keep cleaning up

    def stop(number, frame):
        stopping.set()
    signal.signal(signal.SIGTERM, stop)

    def watch_liveness():
        while os.read(args.liveness_fd, 1):
            pass
        (args.report / 'liveness-eof').write_text('controller gone\n')
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=watch_liveness, daemon=True).start()

    emit('queued')
    if args.scenario == 'queue_forever':
        while not stopping.wait(timeout=0.02):
            pass
        emit('finished', cleanup='confirmed', reason=None)
        return 0
    emit('admitted')
    command = [spec['program'], *spec['args'], '--request-fd', str(args.request_fd),
               '--response-fd', str(args.response_fd)]
    with (args.report / 'stdout.log').open('w') as log:
        child = subprocess.Popen(command, env=spec['env'], pass_fds=(args.request_fd, args.response_fd),
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    os.close(args.request_fd)
    os.close(args.response_fd)
    identity = dict(pid=child.pid, started=f'fake-{child.pid}-{time.monotonic_ns()}', boot='fake-boot')
    emit('child_started', **identity)
    stopped_by = None
    if args.scenario == 'guard_stop':
        child.kill()
        stopped_by = 'guard'
    while child.poll() is None:
        if stopping.wait(timeout=0.02):
            child.kill()
            stopped_by = stopped_by or 'cancel'
            break
    code = child.wait()
    if args.scenario == 'foreign_exit':
        identity['pid'] += 100000
    emit('child_exited', returncode=code if stopped_by is None else None, stopped_by=stopped_by, **identity)
    if args.scenario == 'unconfirmed':
        emit('finished', cleanup='unconfirmed', reason='scripted uncertain cleanup')
    else:
        emit('finished', cleanup='confirmed', reason=None)
    return 0


if __name__ == '__main__':
    sys.exit(main())
