"""Prior-boot migration promotion uses temporary sealed files, never machine activation."""
from copy import deepcopy
from dataclasses import asdict
import fcntl
import hashlib
import json
import os
import time

import pytest

from atelier.harness import capacity_client as client
from atelier.harness import capacity_compat as compat
from atelier.harness import capacity_protocol as wire
from atelier.harness.capacity import Resources
from test_capacity_shared import barrier, short_path, legacy_seal, BOOT_A, BOOT_B, BOOT_C  # noqa: F401 - isolated seal fixtures


def migrated(barrier):
    old = legacy_seal(barrier)
    barrier.boot[0] = BOOT_B
    value = compat.migrate_volume_seal(barrier.config)
    return old, value


def healthy(value):
    return dict(mode='sealed-maintenance', activation_id=value['activation_id'], boot_id=BOOT_B,
                epoch=8, observed_monotonic=time.monotonic(), charged_count=0,
                charged_resources=asdict(Resources()), compatibility_healthy=True, recovering=False)


def test_prior_boot_promotion_keeps_original_seal_dates_bytes_and_lane_identities(barrier, monkeypatch):
    old, value = migrated(barrier)
    raw = compat.DEFAULT_RECORD.read_bytes()
    older = compat.DEFAULT_RECORD.with_name(f'cutover.schema1.{value["activation_id"]}.json')
    older_raw = older.read_bytes()
    before = {name: (p.stat().st_ino, p.stat().st_ctime_ns, p.read_bytes()) for name, p in barrier.paths.items()}
    def status(path):
        assert path == value['socket']
        # Status MUST be read while all lanes are held exclusively, never before the barrier.
        for p in barrier.paths.values():
            with p.open('rb') as handle:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return healthy(value)
    monkeypatch.setattr(client, 'status', status)
    with pytest.raises(wire.CapacityError, match='new OS boot'):
        compat.activate(barrier.config)  # Ordinary schema2 activation is unchanged.
    result = compat.promote_prior_boot(barrier.config)
    assert result['schema'] == 3 and result['state'] == 'active'
    assert result['seal_boot_id'] == BOOT_B and old['seal_boot_id'] == BOOT_A
    assert result['activation_id'] == old['activation_id']
    assert result['total'] == old['total'] and result['reserve'] == old['reserve']
    archive = compat.DEFAULT_RECORD.with_name(f'cutover.schema2.{value["activation_id"]}.json')
    assert archive.read_bytes() == raw and older.read_bytes() == older_raw
    assert result['activation_proof']['migrated_seal_sha256'] == hashlib.sha256(raw).hexdigest()
    assert result['activation_proof']['original_seal_sha256'] == hashlib.sha256(older_raw).hexdigest()
    assert before == {name: (p.stat().st_ino, p.stat().st_ctime_ns, p.read_bytes()) for name, p in barrier.paths.items()}
    assert compat.verify() == result
    with pytest.raises(wire.CapacityError, match='not sealed'):
        compat.verify_maintenance(policy_sha256=value['policy_sha256'])
    barrier.boot[0] = BOOT_C
    assert compat.verify() == result  # Provenance survives another later boot.


def test_fresh_current_boot_prepare_cannot_promote_without_archived_earlier_boot(barrier, monkeypatch):
    compat.prepare(barrier.config)
    monkeypatch.setattr(client, 'status', lambda *a: pytest.fail('not eligible before drain status'))
    with pytest.raises(wire.CapacityError, match='archived prior-boot'):
        compat.promote_prior_boot(barrier.config)
    assert compat.read()['state'] == 'sealed'


@pytest.mark.parametrize('change', [dict(charged_count=1), dict(recovering=True), dict(compatibility_healthy=False),
    dict(mode='capacity'), dict(activation_id='other'), dict(boot_id=BOOT_A), dict(observed_monotonic=0),
    dict(observed_monotonic=float('nan')), dict(epoch=0), dict(charged_count=False),
    dict(charged_resources=asdict(Resources(memory_mib=1)))])
def test_non_drained_stale_or_mismatched_broker_cannot_promote(barrier, monkeypatch, change):
    _, value = migrated(barrier)
    before = compat.DEFAULT_RECORD.read_bytes()
    monkeypatch.setattr(client, 'status', lambda *a: healthy(value) | change)
    with pytest.raises(wire.CapacityError):
        compat.promote_prior_boot(barrier.config)
    assert compat.DEFAULT_RECORD.read_bytes() == before


def test_held_lane_prevents_even_requesting_status(barrier, monkeypatch):
    migrated(barrier)
    monkeypatch.setattr(client, 'status', lambda *a: pytest.fail('holder has not drained'))
    with barrier.paths['small'].open('rb') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            compat.promote_prior_boot(barrier.config)
    assert compat.read()['state'] == 'sealed'


@pytest.mark.parametrize('schema', [1, 2])
@pytest.mark.parametrize('change', ['absent', 'bytes', 'public', 'hardlink', 'symlink'])
def test_active_proof_requires_both_original_private_exact_archives(barrier, monkeypatch, schema, change):
    _, value = migrated(barrier)
    monkeypatch.setattr(client, 'status', lambda *a: healthy(value))
    compat.promote_prior_boot(barrier.config)
    archive = compat.DEFAULT_RECORD.with_name(f'cutover.schema{schema}.{value["activation_id"]}.json')
    if change == 'absent':
        archive.unlink()
    elif change == 'bytes':
        data = json.loads(archive.read_bytes())
        data['seal_boot_id'] = BOOT_C
        archive.write_bytes(wire.encode(data))
    elif change == 'public':
        archive.chmod(0o644)
    else:
        other = archive.with_suffix('.original')
        archive.rename(other)
        if change == 'hardlink':
            os.link(other, archive)
        else:
            archive.symlink_to(other)
    with pytest.raises((wire.CapacityError, OSError)):
        compat.verify()


def test_promotion_recovers_durable_archives_before_active_publication_failure(barrier, monkeypatch):
    _, value = migrated(barrier)
    monkeypatch.setattr(client, 'status', lambda *a: healthy(value))
    before = compat.DEFAULT_RECORD.read_bytes()
    save = compat._save
    def fail(path, value):
        assert value['schema'] == 3
        raise OSError('injected before ACTIVE')
    monkeypatch.setattr(compat, '_save', fail)
    with pytest.raises(OSError, match='before ACTIVE'):
        compat.promote_prior_boot(barrier.config)
    assert compat.DEFAULT_RECORD.read_bytes() == before
    monkeypatch.setattr(compat, '_save', save)
    assert compat.promote_prior_boot(barrier.config)['schema'] == 3


def test_published_active_rolls_forward_without_requiring_old_maintenance_broker(barrier, monkeypatch):
    _, value = migrated(barrier)
    monkeypatch.setattr(client, 'status', lambda *a: healthy(value))
    result = compat.promote_prior_boot(barrier.config)
    before = compat.DEFAULT_RECORD.read_bytes()
    monkeypatch.setattr(client, 'status', lambda *a: pytest.fail('old maintenance mode cannot resume ACTIVE'))
    assert compat.promote_prior_boot(barrier.config) == result
    assert compat.DEFAULT_RECORD.read_bytes() == before


@pytest.mark.parametrize('field,changed', [('promotion_boot_id', BOOT_A), ('original_seal_sha256', '0' * 64),
                                           ('migrated_seal_sha256', '0' * 64), ('broker_epoch', 0), ('kind', 'scan')])
def test_provenance_mutation_never_becomes_an_alternate_closure_witness(barrier, monkeypatch, field, changed):
    _, value = migrated(barrier)
    monkeypatch.setattr(client, 'status', lambda *a: healthy(value))
    result = compat.promote_prior_boot(barrier.config)
    result['activation_proof'][field] = changed
    compat._save(compat.DEFAULT_RECORD, result)
    with pytest.raises(wire.CapacityError):
        compat.verify()


def test_active_replace_before_failed_directory_sync_has_safe_roll_forward(barrier, monkeypatch):
    import stat
    _, value = migrated(barrier)
    monkeypatch.setattr(client, 'status', lambda *a: healthy(value))
    actual = os.fsync
    directories = 0
    def fail_active_directory(fd):
        nonlocal directories
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directories += 1
            if directories == 2:  # Archive sync completed; ACTIVE was replaced but parent sync fails.
                raise OSError('injected active directory sync')
        actual(fd)
    monkeypatch.setattr(compat.os, 'fsync', fail_active_directory)
    with pytest.raises(OSError, match='active directory sync'):
        compat.promote_prior_boot(barrier.config)
    assert compat.read()['schema'] == 3
    monkeypatch.setattr(compat.os, 'fsync', actual)
    monkeypatch.setattr(client, 'status', lambda *a: pytest.fail('old broker is intentionally fenced'))
    assert compat.promote_prior_boot(barrier.config) == compat.verify()


def test_active_proof_cannot_rewrite_policy_or_historical_seal_date(barrier, monkeypatch):
    _, value = migrated(barrier)
    monkeypatch.setattr(client, 'status', lambda *a: healthy(value))
    result = compat.promote_prior_boot(barrier.config)
    for key, changed in [('seal_boot_id', BOOT_A), ('reserve', asdict(Resources(memory_mib=1)))]:
        modified = deepcopy(result)
        modified[key] = changed
        compat._save(compat.DEFAULT_RECORD, modified)
        with pytest.raises(wire.CapacityError):
            compat.verify()
    compat._save(compat.DEFAULT_RECORD, result)
    assert compat.verify() == result


def test_admission_mutex_prevents_status_and_proof_publication(barrier, monkeypatch):
    migrated(barrier)
    monkeypatch.setattr(client, 'status', lambda *a: pytest.fail('admission has not drained'))
    big = barrier.paths['big']
    with big.with_name(f'{big.stem}.admission{big.suffix}').open('a+') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            compat.promote_prior_boot(barrier.config)
    assert compat.read()['state'] == 'sealed'


def test_partial_archive_write_leaves_no_final_name_and_retry_needs_no_deletion(barrier, monkeypatch):
    _, value = migrated(barrier)
    monkeypatch.setattr(client, 'status', lambda *a: healthy(value))
    raw = compat.DEFAULT_RECORD.read_bytes()
    archive = compat.DEFAULT_RECORD.with_name(f'cutover.schema2.{value["activation_id"]}.json')
    actual = os.write
    writes = 0
    def fail_mid_write(fd, data):
        nonlocal writes
        writes += 1
        if writes == 1:
            return actual(fd, data[:17])
        raise OSError('injected partial archive write')
    monkeypatch.setattr(compat.os, 'write', fail_mid_write)
    with pytest.raises(OSError, match='partial archive write'):
        compat.promote_prior_boot(barrier.config)
    assert not archive.exists() and compat.DEFAULT_RECORD.read_bytes() == raw
    monkeypatch.setattr(compat.os, 'write', actual)
    assert compat.promote_prior_boot(barrier.config)['schema'] == 3
    assert archive.read_bytes() == raw


def test_real_maintenance_to_full_broker_keeps_database_and_fences_old_gate(barrier):
    import select
    import threading
    from atelier.harness import capacity_broker as server
    from test_capacity_shared import maintenance_settings
    settings, proof = maintenance_settings(barrier)
    errors = []
    def start(config):
        instance = server.CapacityBroker(**config, boot=lambda: barrier.boot[0],
            observe=lambda: dict(observed_monotonic=time.monotonic(), available_memory_mib=99999))
        def serve():
            try:
                instance.serve_forever()
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        return instance, worker
    def stop(instance, worker):
        instance._stop.set()
        worker.join(timeout=3)
        instance.close()
        assert not worker.is_alive() and not errors
    instance, worker = start(settings)
    gate = None
    request = dict(id='old', phase='job', checkout=str(barrier.root), performance=True,
                   resources=asdict(Resources(memory_mib=128, cpu_millis=11000)),
                   locks=['checkout:' + str(barrier.root)], seconds=60)
    old = client.AdmissionSession(instance.socket_path, request, cutover=compat.DEFAULT_RECORD,
                                  mode='sealed-maintenance', seal_policy_sha256=proof['policy_sha256'])
    database = instance.database_path
    try:
        old.offer()
        gate = old.gate()  # Offered/gated work is uncharged and has not received GO.
        before = client.status(instance.socket_path)
        inode = database.stat().st_ino
        active = compat.promote_prior_boot(barrier.config)  # Real private socket status, no stub.
        assert active['schema'] == 3
        with pytest.raises(wire.CapacityError, match='compatibility'):
            old.offer()
        with pytest.raises(wire.CapacityError, match='compatibility'):
            old._call('start', child=[101, 1000], process_guard={}, tree_guard={}, limit_bytes=128 * 1024**2)
        assert select.select([gate], [], [], 1)[0] and os.read(gate, 1) == b''  # No useful GO byte.
    finally:
        if gate is not None:
            os.close(gate)
        stop(instance, worker)
    full, worker = start(server.load_config(barrier.config))
    try:
        observed = client.status(full.socket_path)
        assert full.database_path == database and database.stat().st_ino == inode
        assert observed['mode'] == 'capacity' and observed['epoch'] == before['epoch'] + 1
        assert observed['charged_count'] == 0 and not observed['recovering']
        assert any(item['id'] == 'old' for item in observed['records'])
        with pytest.raises(wire.CapacityError, match='fenced'):
            old._call('start', child=[101, 1000], process_guard={}, tree_guard={}, limit_bytes=128 * 1024**2)
        fresh = client.AdmissionSession(full.socket_path, request | dict(id='fresh'), cutover=compat.DEFAULT_RECORD)
        assert fresh.offer()['selected']
        assert fresh.close()['released']
    finally:
        stop(full, worker)
