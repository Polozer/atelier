"""Bounded helper turnover and private released evidence; no native jobs or live activation."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time

import pytest

from atelier import capacity_broker as broker, capacity_client as client, capacity_protocol as wire
from atelier import capacity_process_history as history
from atelier.capacity import Resources


def admitted(monkeypatch, responder=None):
    calls = []
    def rpc(path, message, timeout, **kwargs):
        calls.append(message)
        response = dict(state='running', admission=True, epoch=7, boot_id='boot')
        return (responder(message, response) if responder else response), None
    monkeypatch.setattr(client, '_rpc', rpc)
    session = client.AdmissionSession(Path('/unused'), {'id': 'test'})
    session.nonce, session.epoch, session.boot = 'nonce', 7, 'boot'
    return session, calls


def test_delta_batches_preserve_parent_order_and_only_acknowledged_pins_are_omitted(monkeypatch):
    session, calls = admitted(monkeypatch)
    # Parent PID can exceed child PID; sorting would break ancestry at this batch boundary.
    pins = [(10000 - n, n + 1) for n in range(1200)]
    session.check(descendants=pins)
    assert [len(call['descendants']) for call in calls] == [512, 512, 176]
    assert [tuple(pin) for call in calls for pin in call['descendants']] == pins
    session.check(descendants=pins)
    assert calls[-1]['descendants'] == []  # Heartbeat still checks enforcement.
    assert len(wire.encode(calls[0])) <= wire.MAX_FRAME


@pytest.mark.parametrize('failure', ['refused', 'epoch', 'boot', 'transport'])
def test_failed_batch_remains_pending_after_partial_acknowledgement(monkeypatch, failure):
    failed = False
    def respond(message, response):
        nonlocal failed
        if len(message['descendants']) == 88 and not failed:
            failed = True
            if failure == 'transport':
                raise wire.CapacityError('transport')
            response.update({'refused': dict(admission=False), 'epoch': dict(epoch=8),
                             'boot': dict(boot_id='other')}.get(failure, {}))
        return response
    session, calls = admitted(monkeypatch, respond)
    pins = [(n + 1, 100) for n in range(600)]
    with pytest.raises(wire.CapacityError):
        session.check(descendants=pins)
    session.check(descendants=pins)
    assert [len(call['descendants']) for call in calls] == [512, 88, 88]


def test_close_never_chunks_or_truncates_an_oversized_unacknowledged_tail(monkeypatch):
    session, calls = admitted(monkeypatch)
    with pytest.raises(wire.CapacityError, match='Atomic capacity close'):
        session.close(descendants=[(n + 1, 100) for n in range(513)])
    assert not calls and session.closed


def test_close_sends_only_the_remaining_exact_tail(monkeypatch):
    def respond(message, response):
        if message['action'] == 'close':
            response['released'] = True
        return response
    session, calls = admitted(monkeypatch, respond)
    pins = [(n + 1, 100) for n in range(700)]
    session.check(descendants=pins[:600])
    assert session.close(descendants=pins)['released']
    assert calls[-1]['descendants'] == [list(pin) for pin in pins[600:]]


def test_cumulative_limit_rejects_before_any_partial_registration(monkeypatch):
    session, calls = admitted(monkeypatch)
    with pytest.raises(wire.CapacityError, match='Retained process roster'):
        session.check(descendants=[(n + 1, 100) for n in range(wire.MAX_RETAINED + 1)])
    assert not calls


class Watch:
    def __init__(self, pin):
        self.pin, self.exited, self.polls = pin, False, 0
    def poll(self):
        self.polls += 1
        return self.exited
    def close(self):
        pass


@pytest.fixture
def actor():
    with tempfile.TemporaryDirectory(prefix='ach-', dir='/tmp') as name:
        root = Path(name)
        value = broker.CapacityBroker(root / 'broker', total=Resources(memory_mib=4096), disk_pool=root,
                    started=lambda pid: pid * 10, boot=lambda: 'boot', alive=lambda pin: True,
                    parent=lambda pin: (100, 1000), watch=Watch, child_of=lambda *a: True,
                    guards=lambda *args: wire.GuardFacts((), 0),
                    observe=lambda: dict(observed_monotonic=time.monotonic(), available_memory_mib=4096,
                                         available_temp_mib=4096))
        try:
            yield value
        finally:
            value.close()


def send(actor, action, **fields):
    response, fd = actor.handle(dict(namespace=wire.NAMESPACE, action=action, **fields), (99, 990))
    if fd is not None:
        os.close(fd)
    return response


def begin(actor):
    request = dict(id='helpers', resources=asdict(Resources(memory_mib=128)), locks=[])
    response = send(actor, 'offer', request=request)
    fields = dict(id='helpers', nonce=response['nonce'], epoch=response['epoch'], boot_id='boot')
    _, read = actor.handle(dict(namespace=wire.NAMESPACE, action='gate', **fields), (99, 990))
    try:
        send(actor, 'start', child=[100, 1000], process_guard={}, tree_guard={}, limit_bytes=128 * 1024**2, **fields)
        assert os.read(read, 1) == b'1'
    finally:
        os.close(read)
    return fields


def read_state(actor):
    return json.loads(actor.connection.execute('SELECT value FROM state').fetchone()[0])


def test_sequential_helpers_exceed_live_bound_without_losing_positive_or_unknown_evidence(actor):
    fields = begin(actor)
    for base in range(200, 900, 100):
        pins = [[pid, pid * 10] for pid in range(base, base + 100)]
        send(actor, 'check', descendants=pins, **fields)
        for pin in pins:
            actor._watches[(fields['nonce'], tuple(pin))].exited = True
        send(actor, 'check', descendants=[], **fields)
    record = read_state(actor)['records']['helpers']
    assert len(record['roster']) == 701 and len(record['exited']) == 700
    # Positive historical watches are never polled again.
    before = {key: watch.polls for key, watch in actor._watches.items() if watch.exited}
    send(actor, 'check', descendants=[], **fields)
    assert before == {key: watch.polls for key, watch in actor._watches.items() if watch.exited}
    actor.parent = lambda pin: None
    send(actor, 'check', descendants=[[999, 9990]], **fields)
    record = read_state(actor)['records']['helpers']
    assert record['ancestry_unknown'] and [999, 9990] in record['roster']
    assert [999, 9990] not in record['exited'] and [999, 9990] not in record['verified_roster']


@pytest.mark.parametrize('pins', [None, {}, [[1, 1]] * 513])
def test_broker_rejects_unbounded_or_wrong_type_batches_without_mutating_roster(actor, pins):
    fields = begin(actor)
    before = read_state(actor)['records']['helpers']['roster']
    with pytest.raises(wire.CapacityError, match='batch'):
        send(actor, 'check', descendants=pins, **fields)
    assert read_state(actor)['records']['helpers']['roster'] == before


def released(count=100):
    pins = [[n + 1, 10**12 + n] for n in range(count)]
    return dict(state='released', sequence=1, nonce='generation', request=dict(id='request'),
                roster=pins, exited=pins, verified_roster=pins, release_witness=dict(kind='retained-kernel-exits'))


def test_released_archive_preserves_exact_generation_counts_and_witness_before_db_commit(actor, monkeypatch):
    monkeypatch.setattr(history, 'TARGET_STATE', 1)
    state = actor._load()
    state['records']['request'] = released(800)
    original = deepcopy(state['records']['request'])
    actor._save(state)
    stored = read_state(actor)['records']['request']
    summary = stored['process_history']
    path = actor.directory / 'process-history' / (summary['sha256'] + '.json')
    raw = path.read_bytes()
    proof = json.loads(raw)
    assert hashlib.sha256(raw).hexdigest() == summary['sha256']
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and path.stat().st_nlink == 1
    assert proof['nonce'] == 'generation' and proof['request_id'] == 'request'
    assert proof['release_witness'] == original['release_witness']
    for key in history.ARRAYS:
        assert key not in stored and proof[key] == original[key]
        assert history.count(stored, key) == 800
    # Identical retry is non-destructive and accepts the existing exact immutable bytes.
    state = actor._load()
    state['records']['request'] = original
    actor._save(state)
    assert path.read_bytes() == raw


@pytest.mark.parametrize('state_name', ['running', 'draining', 'uncertain'])
def test_held_history_is_never_compacted_even_when_state_is_full(actor, monkeypatch, state_name):
    monkeypatch.setattr(history, 'TARGET_STATE', 1)
    monkeypatch.setattr(history, 'MAX_STATE', 100)
    state = actor._load()
    record = released()
    record['state'] = state_name
    state['records']['request'] = record
    with pytest.raises(wire.CapacityError, match='state exceeds'):
        actor._save(state)
    actor.connection.rollback()
    assert record['roster'] and 'process_history' not in record
    assert not (actor.directory / 'process-history').exists()
    assert not read_state(actor)['records']


def test_archive_failure_cannot_commit_loss_of_exact_arrays(actor, monkeypatch):
    state = actor._load()
    state['records']['request'] = released()
    actor._save(state)
    prior = read_state(actor)
    state = actor._load()
    monkeypatch.setattr(history, 'TARGET_STATE', 1)
    monkeypatch.setattr(history, '_publish', lambda *a: (_ for _ in ()).throw(OSError('injected sync failure')))
    with pytest.raises(OSError, match='injected'):
        actor._save(state)
    actor.connection.rollback()
    assert state['records']['request']['roster']
    assert read_state(actor) == prior


@pytest.mark.parametrize('change', ['bytes', 'symlink', 'hardlink', 'public'])
def test_conflicting_archive_is_not_replaced(actor, monkeypatch, change):
    monkeypatch.setattr(history, 'TARGET_STATE', 1)
    state = dict(records={'request': released()})
    history.encode_state(actor.directory, deepcopy(state))
    path = next((actor.directory / 'process-history').glob('*.json'))
    if change == 'bytes':
        path.write_bytes(b'x' * path.stat().st_size)
    elif change == 'public':
        path.chmod(0o644)
    else:
        other = path.with_suffix('.saved')
        path.rename(other)
        if change == 'symlink':
            path.symlink_to(other)
        else:
            os.link(other, path)
    before = path.read_bytes()
    with pytest.raises((wire.CapacityError, OSError)):
        history.encode_state(actor.directory, state)
    assert path.read_bytes() == before and state['records']['request']['roster']


def test_publication_syncs_file_and_both_directories_before_summary(actor, monkeypatch):
    events = []
    actual = os.fsync
    def sync(fd):
        events.append('directory' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file')
        actual(fd)
    monkeypatch.setattr(history.os, 'fsync', sync)
    monkeypatch.setattr(history, 'TARGET_STATE', 1)
    state = dict(records={'request': released()})
    history.encode_state(actor.directory, state)
    assert events == ['file', 'file', 'directory', 'directory']
    assert 'process_history' in state['records']['request']


def test_new_generation_requires_a_new_session_without_prior_acknowledgements(monkeypatch):
    def respond(message, response):
        if message['action'] == 'offer':
            response.update(nonce='new-generation', selected=True)
        return response
    session, calls = admitted(monkeypatch, respond)
    session.check(descendants=[(10, 100)])
    with pytest.raises(wire.CapacityError, match='fenced'):
        session.offer()
    assert session.nonce == 'nonce' and session._acknowledged == {(10, 100)}
    replacement = client.AdmissionSession(Path('/unused'), {'id': 'test'})
    replacement.offer()
    replacement.check(descendants=[(10, 100)])
    assert calls[-1]['descendants'] == [[10, 100]]


def test_cumulative_limit_is_independent_of_batch_limit_and_refuses_without_new_watches(actor):
    record = dict(principal=[99, 990], nonce='bounded', child=[100, 1000],
                  roster=[[pid, pid * 10] for pid in range(100, 100 + wire.MAX_RETAINED)],
                  verified_roster=[], exited=[])
    with pytest.raises(wire.CapacityError, match='Retained process roster'):
        actor._watch(record, [[100000, 1]])
    assert len(record['roster']) == wire.MAX_RETAINED and not actor._watches


def test_parent_before_child_across_batches_does_not_require_increasing_pids(actor):
    fields = begin(actor)
    send(actor, 'check', descendants=[[10000, 100000]], **fields)
    actor.parent = lambda pin: (10000, 100000)
    send(actor, 'check', descendants=[[2, 20]], **fields)
    record = read_state(actor)['records']['helpers']
    assert not record['ancestry_unknown'] and [2, 20] in record['verified_roster']


def test_compacted_release_survives_restart_and_reoffer_resets_only_summary(actor, monkeypatch):
    fields = begin(actor)
    actor._watches[(fields['nonce'], (100, 1000))].exited = True
    monkeypatch.setattr(history, 'TARGET_STATE', 1)
    assert send(actor, 'close', descendants=[], **fields)['released']
    stored = read_state(actor)['records']['helpers']
    digest = stored['process_history']['sha256']
    directory = actor.directory
    actor.close()
    restarted = broker.CapacityBroker(directory, total=Resources(memory_mib=4096), disk_pool=directory.parent,
                                      started=lambda pid: pid * 10, alive=lambda pin: True, boot=lambda: 'boot')
    try:
        observed = send(restarted, 'status')
        assert observed['records'][0]['retained'] == observed['records'][0]['witnessed'] == 1
        response = send(restarted, 'offer', request=stored['request'])
        assert response['nonce'] != fields['nonce']
        fresh = read_state(restarted)['records']['helpers']
        assert fresh['roster'] == fresh['exited'] == fresh['verified_roster'] == []
        assert 'process_history' not in fresh
        assert (directory / 'process-history' / (digest + '.json')).is_file()
    finally:
        restarted.close()


def test_archive_publication_before_aborted_commit_is_idempotent_on_retry(actor, monkeypatch):
    state = actor._load()
    state['records']['request'] = released()
    actor._save(state)
    prior = read_state(actor)
    monkeypatch.setattr(history, 'TARGET_STATE', 1)
    state = actor._load()
    history.encode_state(actor.directory, state)  # Crash boundary: archive is durable, DB not committed.
    actor.connection.rollback()
    assert read_state(actor) == prior
    paths = list((actor.directory / 'process-history').glob('*.json'))
    assert len(paths) == 1
    raw = paths[0].read_bytes()
    actor._save(actor._load())
    assert paths[0].read_bytes() == raw
    assert 'process_history' in read_state(actor)['records']['request']


def test_archive_path_replacement_during_same_fd_validation_refuses(actor, monkeypatch):
    monkeypatch.setattr(history, 'TARGET_STATE', 1)
    original = dict(records={'request': released()})
    history.encode_state(actor.directory, deepcopy(original))
    path = next((actor.directory / 'process-history').glob('*.json'))
    calls = 0
    actual = os.fsync
    def replace_on_read(fd):
        nonlocal calls
        actual(fd)
        calls += 1
        if calls == 2:
            replacement = path.with_suffix('.replacement')
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(0o600)
            replacement.replace(path)
    monkeypatch.setattr(history.os, 'fsync', replace_on_read)
    with pytest.raises(wire.CapacityError, match='archive differs'):
        history.encode_state(actor.directory, original)
    assert original['records']['request']['roster']


@pytest.mark.parametrize('terminal', [False, True])
@pytest.mark.parametrize('damage', [None, 'epoch', 'boot', 'child', 'admission', 'state', 'both'])
def test_completion_reply_is_fenced_and_never_acknowledges_process_deltas(monkeypatch, terminal, damage):
    def respond(message, _):
        reply = dict(state='released' if terminal else 'uncertain', admission=False, epoch=7, boot_id='boot', child=[10,100])
        reply['terminal' if terminal else 'finish_required'] = True
        reply.update({'epoch': {'epoch': 8}, 'boot': {'boot_id': 'wrong'}, 'child': {'child': [11,100]},
                      'admission': {'admission': True}, 'state': {'state': 'running'},
                      'both': {'terminal': True, 'finish_required': True}}.get(damage, {}))
        return reply
    session, calls = admitted(monkeypatch, respond)
    session.child = (10,100)
    if damage is not None:
        with pytest.raises(wire.CapacityError, match='invalid or fenced'):
            session.check(descendants=[(11,110)])
    else:
        response = session.check(descendants=[(11,110)])
        assert response['admission'] is False
    assert session._acknowledged == set() and len(calls) == 1


def test_terminal_retransmission_survives_released_history_compaction(actor, monkeypatch):
    fields = begin(actor)
    send(actor, 'check', descendants=[[101,1010]], **fields)
    for watch in actor._watches.values(): watch.exited = True
    state = actor._load()
    state['records']['helpers']['state'] = 'uncertain'
    actor._save(state)
    monkeypatch.setattr(history, 'TARGET_STATE', 1)
    first = send(actor, 'check', descendants=[[101,1010]], **fields)
    assert first['terminal'] is True and first['admission'] is False
    compacted = read_state(actor)['records']['helpers']
    assert 'roster' not in compacted and compacted['terminal_observed'] == [[101,1010]]
    again = send(actor, 'check', descendants=[[101,1010]], **fields)
    assert again['terminal'] is True and again['admission'] is False
    with pytest.raises(wire.CapacityError, match='unretained process identities'):
        send(actor, 'check', descendants=[[102,1020]], **fields)
    assert read_state(actor)['records']['helpers']['state'] == 'released'
    assert send(actor, 'close', descendants=[], witness=None, **fields)['released'] is True
    assert 'terminal_observed' not in read_state(actor)['records']['helpers']
