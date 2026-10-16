"""Keep an admitted BuildCookRun alive as Zen's sponsor; bound unavailable staging reads.

Only the installed ``zen attach`` client runs here. This never starts, stops or signals a
Zen server. Network/client work runs off the guard's polling thread so capacity heartbeats
and memory checks keep running. UAT's original argv and completion protocol are unchanged.
"""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time

INTERVAL = 2.
UNAVAILABLE_SECONDS = 60.
ATTACH_TIMEOUT = 3.
READ = re.compile(r'Reading oplog from (?:Zen|http://(?:\[::1\]|127\.0\.0\.1|localhost):8558/)')


def started(pid):
    # Native birth identity, without a subprocess or a process-name ownership guess.
    from atelier.harness.safety.process_tree import started as birth
    return birth(pid)


def check(zen, env, pid, birth, stopped):
    """One bounded health/attach attempt; never launch a server or target another process."""
    connection = http.client.HTTPConnection('127.0.0.1', 8558, timeout=.5)
    try:
        connection.request('GET', '/health/ready')
        healthy = connection.getresponse().status == 200
    except (OSError, http.client.HTTPException):
        healthy = False
    finally:
        connection.close()
    if not healthy:
        return dict(healthy=False, attached=False, error=None)
    if stopped.is_set() or started(pid) != birth:
        return dict(healthy=True, attached=False, error=None)
    try:
        result = subprocess.run([str(zen), 'attach', '--port', '8558', '--owner-pid', str(pid)],
                                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=ATTACH_TIMEOUT)
        error = None if result.returncode == 0 else f'zen attach exited {result.returncode}'
    except (OSError, subprocess.TimeoutExpired) as exc:
        # subprocess.run kills and reaps only its own timed-out attach client.
        error = type(exc).__name__
    return dict(healthy=True, attached=error is None, error=error)


class Lifecycle:
    """@cc [owner:fontanierh,label:safety] admitted-zen-lifetime
    Zen sponsorship MUST name the pinned admitted UAT root, never an idle controller.
    It MUST NOT launch or signal a shared server or block the guard polling thread.
    Sixty seconds of observed Zen unavailability during staging reads MUST fail the owned
    step through normal guard cleanup. Healthy slow reads MUST NOT fail on elapsed time.
    """
    def __init__(self, folder, engine, env):
        self.path = Path(folder) / 'zen-lifecycle.json'
        self.zen = Path(engine) / 'Engine/Binaries/Mac/zen'
        self.env = env
        self.pool = None
        self.future = None
        self.stopped = threading.Event()
        self.pid = self.birth = None
        self.next_check = 0.
        self.reading = False
        self.unavailable_since = self.attach_failed_since = None
        self.report = dict(schema=1, port=8558, child=None, attached_count=0,
                           health_checks=0, reading=False, failure=None)

    def line(self, line):
        if READ.search(line):
            # Keep health required through the stage: subsequent chunk reads use the same
            # Zen store and need not print another oplog URL.
            self.reading = True
            self.report.setdefault('first_read_at', time.monotonic())
        if 'COOK COMMAND COMPLETED' in line:
            self.report.setdefault('cook_completed_at', time.monotonic())
        if 'STAGE COMMAND COMPLETED' in line:
            self.reading = False
            self.unavailable_since = None
            self.report['stage_completed_at'] = time.monotonic()

    def poll(self, pid):
        if self.stopped.is_set():
            raise RuntimeError('Zen lifecycle already closed')
        birth = started(pid)
        if birth is None:
            return  # The guard also calls on_poll after a successful root exit.
        if self.pid is None:
            self.pid, self.birth = pid, birth
            self.report['child'] = dict(pid=pid, started=birth)
        elif (pid, birth) != (self.pid, self.birth):
            raise RuntimeError('Zen lifecycle root identity changed')
        now = time.monotonic()
        if self.future is not None and self.future.done():
            result = self.future.result()
            self.future = None
            self.report.update(last_check=result, health_checks=self.report['health_checks'] + 1)
            if result['attached']:
                self.report['attached_count'] += 1
                self.report.setdefault('first_attached_at', now)
                self.report['last_attached_at'] = now
            self.unavailable_since = (None if result['healthy'] or not self.reading else
                                      self.unavailable_since if self.unavailable_since is not None else now)
            self.attach_failed_since = (None if not result['error'] else
                                        self.attach_failed_since if self.attach_failed_since is not None else now)
            if self.unavailable_since is not None and now - self.unavailable_since >= UNAVAILABLE_SECONDS:
                self.fail('Zen is unavailable for 60 seconds during staging reads; ending owned package step')
            if self.attach_failed_since is not None and now - self.attach_failed_since >= UNAVAILABLE_SECONDS:
                self.fail('Cannot sponsor Zen for 60 seconds; ending owned package step')
        if self.future is None and now >= self.next_check:
            if self.pool is None:
                self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='atelier-zen')
            self.future = self.pool.submit(check, self.zen, self.env, pid, birth, self.stopped)
            self.next_check = now + INTERVAL

    def fail(self, message):
        self.report['failure'] = message
        raise RuntimeError(message)

    def close(self):
        self.stopped.set()
        if self.pool is not None:
            # Every task is bounded by a numeric loopback HTTP timeout plus attach's timeout.
            # No client may keep attaching after the owned step has been unwound.
            self.pool.shutdown(wait=True, cancel_futures=True)
        self.report['reading'] = self.reading
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent, prefix='.zen-', delete=False) as stream:
            temporary = Path(stream.name)
            try:
                stream.write(json.dumps(self.report, indent=2) + '\n')
                stream.close()
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
