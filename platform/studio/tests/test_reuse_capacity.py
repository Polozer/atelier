"""Reuse enters the common guard; it never falls back to a direct legacy file lock."""
import sys
import json

import pytest

from atelier import build_snapshot, capacity_compat, reuse, reuse_worker
from atelier.capacity_protocol import CapacityError
from atelier.safety import guarded


@pytest.mark.parametrize('action,code', [('copy', 0), ('copy', 7), ('abandon', 7)])
def test_full_mode_transfer_uses_one_guarded_owned_child(tmp_path, monkeypatch, action, code):
    source, target = tmp_path / 'donor', tmp_path / 'receiver'
    monkeypatch.setattr(reuse, 'git', lambda *args: 'same' if args[1] == 'rev-parse' else '')
    monkeypatch.delenv('ATELIER_BUILD_ROOT', raising=False)
    monkeypatch.setattr(capacity_compat, 'read', lambda: {'state': 'active'})
    def legacy(*args, **kwargs):
        pytest.fail('reuse must not enter a direct legacy lock')
    monkeypatch.setattr(reuse, 'render_lock', legacy, raising=False)
    calls = []
    def run(command, folder, **options):
        assert not target.exists()  # No copy/journal before admission invokes its child.
        calls.append((command, folder, options))
        if action == 'copy':
            out = target / 'build/standin'
            out.mkdir(parents=True)
            record = dict(schema=1, operation_id=options['invocation_id'], revision='same', steps=[], stamp_sha256={})
            (out / build_snapshot.JOURNAL).write_text(json.dumps(record))
            (out / build_snapshot.COMPLETE).write_text(json.dumps(record))
            reuse._staging('standin', target, options['invocation_id']).mkdir(parents=True)
        return code
    monkeypatch.setattr(guarded, 'run', run)
    result = reuse.main('standin', source, target) if action == 'copy' else reuse.abandon('standin', target)
    assert result == code
    assert len(calls) == 1
    command, folder, options = calls[0]
    assert command == [sys.executable, '-m', 'atelier.reuse_worker', action, 'standin', str(target),
                       *([str(source)] if action == 'copy' else []), '--invocation', options['invocation_id']]
    assert folder.parent == target / 'build/standin/logs'
    assert options['kind'] == 'job' and options['aggregate_tree'] is True
    assert options['timeout'] == 1800 and options['progress'] == 30
    assert 'admission' not in options and 'lock' not in options and 'small_gib' not in options
    if action == 'copy':
        assert (target / 'build/standin' / build_snapshot.JOURNAL).exists() is (code != 0)
        assert (target / 'build/standin/stamps').exists() is (code == 0)
    else:
        assert not target.exists()


def test_capacity_refusal_propagates_without_copy_or_legacy_fallback(tmp_path, monkeypatch):
    source, target = tmp_path / 'donor', tmp_path / 'receiver'
    monkeypatch.setattr(reuse, 'git', lambda *args: 'same' if args[1] == 'rev-parse' else '')
    monkeypatch.delenv('ATELIER_BUILD_ROOT', raising=False)
    monkeypatch.setattr(reuse, '_copy', lambda *args: pytest.fail('must not copy after refusal'))
    def refuse(*args, **kwargs):
        raise CapacityError('broker unavailable')
    monkeypatch.setattr(guarded, 'run', refuse)
    with pytest.raises(CapacityError, match='broker unavailable'):
        reuse.main('standin', source, target)
    assert not target.exists()


@pytest.mark.parametrize('failure', ['capacity-close', 'wrong-operation'])
def test_completed_child_cannot_unblock_receiver_after_failed_guard_or_wrong_identity(
        tmp_path, monkeypatch, failure):
    source, target = tmp_path / 'donor', tmp_path / 'receiver'
    monkeypatch.setattr(reuse, 'git', lambda *args: 'same' if args[1] == 'rev-parse' else '')
    monkeypatch.delenv('ATELIER_BUILD_ROOT', raising=False)
    out = target / 'build/standin'
    def run(command, folder, **options):
        out.mkdir(parents=True)
        record = dict(schema=1, revision='same', steps=[], operation_id=options['invocation_id'])
        (out / build_snapshot.JOURNAL).write_text(json.dumps(record))
        if failure == 'wrong-operation':
            record['operation_id'] = 'f' * 32
        (out / build_snapshot.COMPLETE).write_text(json.dumps(record))
        if failure == 'capacity-close':
            raise CapacityError('capacity close remains uncertain')
        return 0
    monkeypatch.setattr(guarded, 'run', run)
    with pytest.raises((CapacityError, ValueError), match='uncertain|completion differs'):
        reuse.main('standin', source, target)
    assert (out / build_snapshot.JOURNAL).exists()
    with pytest.raises(SystemExit, match='--abandon'):
        build_snapshot.require_complete(out, game='standin', repo=target)


@pytest.mark.parametrize('action', ['copy', 'abandon'])
def test_worker_calls_canonical_transfer_body_once(monkeypatch, action):
    calls = []
    def body(*args, **kwargs):
        calls.append((args, kwargs))
        return 5
    monkeypatch.setattr(reuse, '_copy' if action == 'copy' else '_abandon', body)
    monkeypatch.setattr(guarded, 'run', lambda *args, **kwargs: pytest.fail('no nested guard'))
    monkeypatch.setattr(sys, 'argv', ['reuse_worker', action, 'standin', 'receiver',
                                    *(['donor'] if action == 'copy' else []), '--invocation', '0' * 32])
    assert reuse_worker.main() == 5
    assert calls == [(('standin', 'donor', 'receiver'), {'operation_id': '0' * 32})
                     if action == 'copy' else (('standin', 'receiver'), {})]
