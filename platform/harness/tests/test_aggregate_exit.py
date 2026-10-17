"""Kernel aggregate exit may precede waitpid; unknown or surviving work still fails."""
import json
from types import SimpleNamespace
import time

import pytest

from atelier.harness.safety import guard, guarded


class Child:
    def __init__(self, *, outcome=0, survives=False):
        self.returncode = None
        self.outcome, self.survives = outcome, survives
        self.waits = []

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.waits.append(timeout)
        if self.survives:
            raise guarded.subprocess.TimeoutExpired('owned child', timeout)
        self.returncode = self.outcome
        return self.returncode


def terminal(tmp_path, *, status=0, **changes):
    report = tmp_path / 'tree.json'
    value = dict(owner=123, owner_started=456, observed_monotonic=time.monotonic(),
                 state='child_exited', cleanup_complete=True, processes=[], footprint_bytes=0)
    value.update(changes)
    report.write_text(json.dumps(value))
    process = SimpleNamespace(poll=lambda: status)
    return guard.TreeMonitor(process, 123, 456, report)


@pytest.mark.parametrize('status', [None, 0])
@pytest.mark.parametrize('outcome', [0, 7])
def test_positive_aggregate_terminal_gets_bounded_actual_child_wait(tmp_path, status, outcome):
    monitor, child = terminal(tmp_path, status=status), Child(outcome=outcome)
    guarded.check_aggregate_guard(child, monitor)
    assert child.waits == [guarded.CHILD_EXIT_SECONDS]
    assert child.returncode == outcome  # A failed native workload is never turned into success.


@pytest.mark.parametrize('changes', [dict(owner=999), dict(owner_started=999), dict(cleanup_complete=False),
                                    dict(state='memory_limit'), dict(observed_monotonic=time.monotonic()-60)])
def test_unbound_failed_or_stale_receipt_cannot_wait_without_a_live_guard(tmp_path, changes):
    child = Child()
    with pytest.raises(RuntimeError):
        guarded.check_aggregate_guard(child, terminal(tmp_path, **changes))
    assert child.waits == []


def test_unexpected_monitor_death_still_refuses_even_with_a_terminal_file(tmp_path):
    child = Child()
    with pytest.raises(RuntimeError):
        guarded.check_aggregate_guard(child, terminal(tmp_path, status=2))
    assert child.waits == []


def test_positive_receipt_never_accepts_a_surviving_launcher(tmp_path):
    child = Child(survives=True)
    with pytest.raises(RuntimeError, match='surviving launcher'):
        guarded.check_aggregate_guard(child, terminal(tmp_path))
    assert child.waits == [guarded.CHILD_EXIT_SECONDS] and child.returncode is None


def test_running_monitor_needs_no_wait(tmp_path):
    child = Child()
    guarded.check_aggregate_guard(child, terminal(tmp_path, status=None, state='running'))
    assert child.waits == [] and child.returncode is None
