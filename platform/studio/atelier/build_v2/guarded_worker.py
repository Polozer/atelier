"""Bridge one build-v2 worker attempt through the existing guard (C7).

The Rust guard adapter starts this module once per attempt. It calls the existing
`atelier.harness.safety.guarded.run` exactly as any guarded job would: normal admission, the
process and aggregate tree guards, reaping and capacity close all stay there. This bridge adds
no broker, lock, reservation or reaper. It only:

- passes the worker's two protocol pipe ends as `pass_fds` and appends `--request-fd N
  --response-fd M` to the worker command;
- passes checkout-lock custody descriptors as `custody_fds`, so the aggregate monitor keeps its
  own duplicates until owned cleanup is verified; the worker never receives them;
- reports what the guard observed as JSON lines on the events descriptor: queued, admitted
  (`on_slot`), child_started (`on_poll`, with the guard's pinned identity), child_exited and
  finished (`confirmed` only on fresh, matching, empty receipts; see `cleanup`);
- stops its own run through the guard's normal TERM/HUP unwind when asked, or when the
  controller's liveness pipe closes.

Usage: python -m atelier.build_v2.guarded_worker --report DIR --purpose TEXT --memory-gib G
--timeout S [--queue-wait S] --events-fd E --liveness-fd L --spec-fd S --request-fd R
--response-fd W [--custody-fd C ...]. The spec descriptor carries {program, args, env}.
"""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import sys
import threading
import time
import uuid


def _parser():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--purpose', required=True)
    parser.add_argument('--memory-gib', type=int, required=True)
    parser.add_argument('--timeout', type=float, required=True)
    parser.add_argument('--queue-wait', type=float)
    for name in ('events', 'liveness', 'spec', 'request', 'response'):
        parser.add_argument(f'--{name}-fd', type=int, required=True)
    parser.add_argument('--custody-fd', type=int, action='append', default=[])
    return parser


def _read(path):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def classify(error, process, tree, cancelled):
    """Who stopped the worker, from the guard's receipts and the unwind that ended the run."""
    states = {(process or {}).get('state'), (tree or {}).get('state'), (tree or {}).get('termination_reason')}
    if 'memory_limit' in states:
        return 'guard'
    message = error.code if isinstance(error, SystemExit) else None
    if 'test_duration' in states or (isinstance(message, str) and message.startswith('child exceeded')):
        return 'deadline'
    if cancelled or message in (128 + signal.SIGTERM, 128 + signal.SIGHUP) or 'terminated' in states:
        return 'cancel'
    return None


STOPPED = ('memory_limit', 'test_duration', 'terminated', 'controller_exited')


def _describe(error):
    try:
        return f'{type(error).__name__}: {error}'[:500]
    except Exception:
        return type(error).__name__


def _empty(value):
    return type(value) is list and not value


def _zero(value):
    return type(value) is int and value == 0


CLOCK_SKEW_SECONDS = 2.  # a guard receipt may not claim a time later than this past the bridge's clock


def _fresh(value, since, now):
    """Written during this invocation: a finite observation time between `since` and `now`."""
    observed = value.get('time')
    return (type(observed) in (int, float) and math.isfinite(observed)
            and since <= observed <= now + CLOCK_SKEW_SECONDS)


def _same_files(recorded, expected):
    try:
        return type(recorded) is list and sorted(map(list, recorded)) == expected
    except TypeError:
        return False


def cleanup(error, child, process, tree, *, admitted, since, now, invocation, timings, custody):
    """(confirmed, reason). Only affirmative, mutually consistent evidence confirms.

    `admitted` says whether the guard ever reported a slot; the guard spawns only after that, so a
    run that unwound before admission spawned nothing. `since` is this bridge's start time, so a
    receipt older than it is stale, and `now` bounds it from the future (with a small clock skew);
    a non-finite time is malformed. `invocation` is the id this bridge gave the guarded run.
    `custody` is None without custody, else the sorted [device, inode] pairs of the bridge's own
    custody descriptors. Everything else, including a malformed receipt, is unconfirmed.
    """
    if error is not None and not isinstance(error, SystemExit):
        return False, 'guarded run failed: ' + _describe(error)
    if child is None:
        if admitted:
            return False, 'admitted without a pinned child; a spawn cannot be ruled out'
        if error is None:
            return False, 'the guarded run returned without admission'
        if process is not None or tree is not None:
            return False, 'guard receipts exist for a run that was never admitted'
        if timings is not None and (not isinstance(timings, dict) or timings.get('invocation_id') != invocation):
            return False, 'the execution receipt belongs to another invocation'
        return True, None  # unwound while queued: no slot, so nothing was spawned
    if not admitted:
        return False, 'a pinned child without admission'
    if not isinstance(tree, dict):
        return False, 'no aggregate tree receipt'
    if not isinstance(process, dict):
        return False, 'no process guard receipt'
    if (tree.get('owner'), tree.get('owner_started')) != child:
        return False, 'the tree receipt belongs to another identity'
    if (process.get('pid'), process.get('process_start')) != child:
        return False, 'the process receipt belongs to another identity'
    if not isinstance(timings, dict) or timings.get('invocation_id') != invocation:
        return False, 'no execution receipt for this invocation'
    if not _fresh(tree, since, now) or not _fresh(process, since, now):
        return False, 'a guard receipt is not from this invocation'
    if tree.get('cleanup_complete') is not True or 'error' in tree or 'termination_reason' in tree:
        return False, 'tree cleanup incomplete'
    state = tree.get('state')
    if state == 'child_exited':
        if not (_empty(tree.get('processes')) and _zero(tree.get('footprint_bytes'))):
            return False, 'the exited tree receipt is not empty'
        if 'cleanup_processes' in tree or 'cleanup_footprint_bytes' in tree:
            return False, 'the exited tree receipt is contradictory'
    elif state in STOPPED:
        if not (_empty(tree.get('cleanup_processes')) and _zero(tree.get('cleanup_footprint_bytes'))):
            return False, 'the stopped tree did not drain to empty'
    else:
        return False, 'unsupported tree terminal state'
    if 'late_reporters' in tree:
        late = tree['late_reporters']
        if not (isinstance(late, dict) and late.get('scan_failed') is False and _empty(late.get('unresolved'))
                and _empty(late.get('unresolved_pids'))):
            return False, 'late crash reporters are unresolved'
    record = tree.get('custody')
    if custody is None:
        if 'custody' in tree:
            return False, 'custody evidence for a run without custody'
    elif not (isinstance(record, dict) and record.get('held') is False
              and record.get('released') == 'cleanup_complete' and _same_files(record.get('lock_files'), custody)):
        return False, 'no custody release evidence for these lock files'
    return True, None


def main(argv=None, run=None):
    """@cc [owner:fontanierh,label:safety] guarded-worker-bridge
    The bridge MUST run its worker only through the existing guarded run with normal admission,
    MUST give the worker only the two protocol descriptors, and MUST pass custody descriptors only
    as monitor custody. It MUST report `finished: confirmed` only for an unwind before admission
    with no receipts, or for fresh process, tree and execution receipts that match its pinned child
    and invocation, where the tree is in a supported terminal form with an explicitly empty, zero
    post-drain sample, no unresolved reporters and, when custody was requested, explicit release of
    exactly its lock files. Failures and missing, stale, malformed or contradictory receipts MUST be
    unconfirmed, whatever stopped the run. See tests/test_build_v2_guarded_worker.py.
    """
    args = _parser().parse_args(argv)
    if run is None:
        from atelier.harness.safety.guarded import run
    from atelier.harness.capacity_protocol import boot_id, process_start
    since = time.time()
    invocation = uuid.uuid4().hex
    for fd in (args.events_fd, args.liveness_fd, args.spec_fd, *args.custody_fd):
        os.set_inheritable(fd, False)
    custody = sorted([os.fstat(fd).st_dev, os.fstat(fd).st_ino] for fd in args.custody_fd) if args.custody_fd else None
    events = os.fdopen(args.events_fd, 'w', buffering=1)
    lock = threading.Lock()

    def emit(event, **fields):
        with lock:
            try:
                events.write(json.dumps({'event': event, **fields}) + '\n')
            except (BrokenPipeError, ValueError):
                pass  # the controller is gone; the guard's cleanup still runs

    with os.fdopen(args.spec_fd, 'rb') as stream:
        spec = json.loads(stream.read())
    command = [spec['program'], *spec['args'], '--request-fd', str(args.request_fd),
               '--response-fd', str(args.response_fd)]
    boot = boot_id()
    state = dict(admitted=False, child=None, cancelled=False, finished=False)

    def stop(number, frame):
        raise SystemExit(128 + number)
    for number in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, stop)  # guarded.run installs its own unwind while it runs

    def watch_liveness():
        try:
            while os.read(args.liveness_fd, 1):
                pass
        except OSError:
            pass
        if not state['finished']:
            state['cancelled'] = True
            os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=watch_liveness, daemon=True).start()

    def on_slot(slot, why):
        if not state['admitted']:
            state['admitted'] = True
            emit('admitted')

    def on_poll(pid):
        if state['child'] is None:
            try:
                state['child'] = (pid, process_start(pid))
            except Exception:
                return  # exited already; the tree receipt pins it below
            emit('child_started', pid=pid, started=str(state['child'][1]), boot=boot)

    emit('queued')
    returncode, error = None, None
    try:
        returncode = run(command, args.report, timeout=args.timeout, purpose=args.purpose, env=spec['env'],
                         limit_gib=args.memory_gib, kind='job', on_slot=on_slot, on_poll=on_poll,
                         pass_fds=(args.request_fd, args.response_fd), queue_seconds=args.queue_wait,
                         invocation_id=invocation,
                         **({'custody_fds': tuple(args.custody_fd)} if args.custody_fd else {}))
    except BaseException as caught:  # every unwind is classified below; nothing is retried here
        error = caught
    for fd in (args.request_fd, args.response_fd):
        try:
            os.close(fd)
        except OSError:
            pass
    process = _read(args.report / 'memory-health.json')
    tree = _read(args.report / 'memory-health-tree.json')
    child = state['child']
    now = time.time()
    if (child is None and tree is not None and process is not None and _fresh(tree, since, now)
            and type(tree.get('owner')) is int and type(tree.get('owner_started')) is int
            and (process.get('pid'), process.get('process_start')) == (tree['owner'], tree['owner_started'])):
        # The child exited before the first poll: only a fresh, corroborated receipt pins it.
        child = (tree['owner'], tree['owner_started'])
        emit('child_started', pid=child[0], started=str(child[1]), boot=boot)
    if child is not None:
        emit('child_exited', pid=child[0], started=str(child[1]), boot=boot,
             returncode=returncode if error is None else None,
             stopped_by=classify(error, process, tree, state['cancelled']))
    confirmed, reason = cleanup(error, child, process, tree, admitted=state['admitted'], since=since, now=now,
                                invocation=invocation, timings=_read(args.report / 'execution-timings.json'),
                                custody=custody)
    state['finished'] = True
    emit('finished', cleanup='confirmed' if confirmed else 'unconfirmed', reason=reason)
    # The monitor holds its own custody duplicates; closing ours never ends exclusion early.
    for fd in args.custody_fd:
        try:
            os.close(fd)
        except OSError:
            pass
    return 0 if confirmed and returncode == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
