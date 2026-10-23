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
  finished (`confirmed` only on a complete tree receipt after a normal or stopping unwind);
- stops its own run through the guard's normal TERM/HUP unwind when asked, or when the
  controller's liveness pipe closes.

Usage: python -m atelier.build_v2.guarded_worker --report DIR --purpose TEXT --memory-gib G
--timeout S [--queue-wait S] --events-fd E --liveness-fd L --spec-fd S --request-fd R
--response-fd W [--custody-fd C ...]. The spec descriptor carries {program, args, env}.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading


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


def cleanup(error, child, process, tree):
    """(confirmed, reason). Anything short of positive evidence is unconfirmed."""
    if error is not None and not isinstance(error, SystemExit):
        return False, f'guarded run failed: {type(error).__name__}: {error}'
    if child is None and process is None:
        return True, None  # never spawned: the unwind closed the uncharged request
    if tree is None:
        return False, 'no aggregate tree receipt'
    if child is not None and (tree.get('owner'), tree.get('owner_started')) != child:
        return False, 'the tree receipt belongs to another identity'
    if tree.get('cleanup_complete') is not True:
        return False, f"tree cleanup incomplete ({tree.get('termination_reason') or tree.get('state')})"
    if (tree.get('custody') or {}).get('held') is True:
        return False, 'the custody monitor still holds checkout exclusion'
    return True, None


def main(argv=None, run=None):
    """@cc [owner:fontanierh,label:safety] guarded-worker-bridge
    The bridge MUST run its worker only through the existing guarded run with normal admission,
    MUST give the worker only the two protocol descriptors, and MUST pass custody descriptors only
    as monitor custody. It MUST report `finished: confirmed` only after a normal or stopping unwind
    with no child, or a matching complete tree receipt with no held custody; failures, missing
    receipts and controller loss MUST be unconfirmed. See tests/test_build_v2_guarded_worker.py.
    """
    args = _parser().parse_args(argv)
    if run is None:
        from atelier.harness.safety.guarded import run
    from atelier.harness.capacity_protocol import boot_id, process_start
    for fd in (args.events_fd, args.liveness_fd, args.spec_fd, *args.custody_fd):
        os.set_inheritable(fd, False)
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
    if child is None and tree is not None and type(tree.get('owner')) is int:
        child = (tree['owner'], tree.get('owner_started'))
        if type(child[1]) is int:
            emit('child_started', pid=child[0], started=str(child[1]), boot=boot)
        else:
            child = None
    if child is not None:
        emit('child_exited', pid=child[0], started=str(child[1]), boot=boot,
             returncode=returncode if error is None else None,
             stopped_by=classify(error, process, tree, state['cancelled']))
    confirmed, reason = cleanup(error, child, process, tree)
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
