"""Machine configuration cannot silently weaken a guarded launch's reservation."""
import copy
import json
import math
import sys
from types import SimpleNamespace

import pytest

from atelier.harness import capacity_runtime as runtime


@pytest.fixture
def client(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    path = tmp_path / 'client.json'
    profile = dict(resources=dict(memory_mib=10240, cpu_millis=4000, temp_mib=2048, io_slots=1, gpu_mib=10240),
                   locks=['graphics'])
    value = dict(schema=1, socket=str(tmp_path / 'broker.sock'),
                 profiles={kind: copy.deepcopy(profile) for kind in ('job', 'game', 'compile')})
    monkeypatch.setattr(runtime, 'DEFAULT_CONFIG', path)
    from atelier.harness import capacity_compat as compat
    monkeypatch.setattr(compat, 'DEFAULT_RECORD', tmp_path / 'cutover.json')
    monkeypatch.delenv('ATELIER_CAPACITY_CLIENT', raising=False)
    calls = []

    def session(socket, request, **kwargs):
        calls.append((socket, request))
        return request
    monkeypatch.setitem(sys.modules, 'atelier.harness.capacity_client', SimpleNamespace(AdmissionSession=session))

    def write():
        path.write_text(json.dumps(value))
        path.chmod(0o600)
    return path, value, write, calls


def test_unconfigured_machine_uses_existing_launcher(client):
    assert runtime.configured_session(kind='job', limit_gib=10, timeout=0) is None
    assert client[3] == []


def test_configured_missing_file_refuses_instead_of_falling_back(client, monkeypatch):
    monkeypatch.setenv('ATELIER_CAPACITY_CLIENT', str(client[0]))
    with pytest.raises(ValueError, match='missing'):
        runtime.configured_session(kind='job', limit_gib=10, timeout=0)


def test_configured_profiles_preserve_guard_ceiling_and_checkout_lock(client):
    path, value, write, calls = client
    write()
    result = runtime.configured_session(kind='compile', limit_gib=10, timeout=120)
    assert calls[0][0] == value['socket']
    assert result['resources'] == value['profiles']['compile']['resources']
    assert result['locks'] == sorted(['graphics', 'checkout:' + str(runtime.REPO)])
    assert result['seconds'] == 120
    assert result['performance'] is False


def test_performance_window_reaches_configured_broker_request(client):
    client[2]()
    request = runtime.configured_session(kind='game', limit_gib=10, timeout=330, performance=True)
    assert request['performance'] is True
    assert request['resources'] == client[1]['profiles']['game']['resources']


@pytest.mark.parametrize('value', [None, 0, 1, 'true'])
def test_performance_flag_must_be_boolean_even_without_configuration(client, value):
    with pytest.raises(ValueError, match='performance.*boolean'):
        runtime.configured_session(kind='game', limit_gib=10, timeout=0, performance=value)
    assert client[3] == []


def test_retry_keeps_logical_identity_while_unrelated_actions_are_distinct(client):
    client[2]()
    first = runtime.configured_session(kind='job', limit_gib=10, timeout=120, folder='logs/mesh.guard')
    retry = runtime.configured_session(kind='job', limit_gib=10, timeout=120, folder='logs/mesh.guard')
    other = runtime.configured_session(kind='job', limit_gib=10, timeout=120, folder='logs/cook.guard')
    assert first == retry
    assert first['id'] != other['id']


def test_profile_cannot_hide_a_larger_actual_guard(client):
    client[2]()
    with pytest.raises(ValueError, match='smaller than the actual guard'):
        runtime.configured_session(kind='game', limit_gib=14, timeout=0)
    assert client[3] == []


def test_capacity_profile_must_reserve_cpu(client):
    client[1]['profiles']['job']['resources']['cpu_millis'] = 0
    client[2]()
    with pytest.raises(ValueError, match='CPU capacity'):
        runtime.configured_session(kind='job', limit_gib=10, timeout=0)


def configure_schema(client, monkeypatch, schema):
    from atelier.harness import capacity_compat as compat
    value = client[1]
    monkeypatch.setattr(compat, 'read', lambda: None)
    if schema == 2:
        value.update(schema=2, cutover=str(compat.DEFAULT_RECORD))
        monkeypatch.setattr(compat, 'verify', lambda path: dict(socket=value['socket'],
            total=dict(cpu_millis=10000), reserve=dict(cpu_millis=2000)))


@pytest.mark.parametrize('limit_gib', [10, 10.0001, 10.5, 12, 14, 18, 23.9999, 24])
@pytest.mark.parametrize('profile_mib', [10240, 13312])
def test_full_game_reserves_selected_session_ceiling_without_changing_guard_or_config(
        client, monkeypatch, limit_gib, profile_mib):
    configure_schema(client, monkeypatch, 2)
    path, value, write, _ = client
    value['profiles']['game']['resources']['memory_mib'] = profile_mib
    write()
    before = path.read_bytes()
    monkeypatch.setitem(sys.modules, 'atelier.harness.capacity_client', SimpleNamespace(
        AdmissionSession=lambda socket, request, **kwargs: SimpleNamespace(request=request, **kwargs)))
    admission = runtime.configured_session(kind='game', limit_gib=limit_gib, timeout=0,
                                           command=['UnrealEditor'])
    assert admission.guard_limit_gib == limit_gib
    assert admission.request['resources'] == value['profiles']['game']['resources'] | {
        'memory_mib': max(profile_mib, math.ceil(limit_gib * 1024)), 'cpu_millis': 8000}
    assert admission.request['performance'] is True
    assert admission.request['locks'] == sorted(['graphics', 'checkout:' + str(runtime.REPO)])
    assert path.read_bytes() == before
    runtime.validate_session_profile(admission, kind='game', command=['UnrealEditor'], limit_gib=limit_gib)


@pytest.mark.parametrize('kind,schema', [('job', 2), ('compile', 2), ('game', 1), ('game', 3)])
def test_session_game_resizing_does_not_apply_to_other_profiles_or_modes(client, monkeypatch, kind, schema):
    configure_schema(client, monkeypatch, 2 if schema == 3 else schema)
    if schema == 3:
        from atelier.harness import capacity_compat as compat
        client[1].update(schema=3, mode='sealed-maintenance', seal_policy_sha256='a' * 64)
        monkeypatch.setattr(compat, 'verify_maintenance', lambda path, **kwargs: dict(
            socket=client[1]['socket'], total=dict(cpu_millis=10000), reserve=dict(cpu_millis=2000)))
    client[2]()
    with pytest.raises(ValueError, match='smaller than the actual guard'):
        runtime.configured_session(kind=kind, limit_gib=12, timeout=0)
    assert client[3] == []


@pytest.mark.parametrize('limit_gib', [24.001, 25, float('inf'), float('-inf'), float('nan'), 9.999, -1])
@pytest.mark.parametrize('profile_mib', [10240, 32768])
def test_full_game_cannot_resize_outside_the_documented_session_range(client, monkeypatch, limit_gib, profile_mib):
    configure_schema(client, monkeypatch, 2)
    client[1]['profiles']['game']['resources']['memory_mib'] = profile_mib
    client[2]()
    with pytest.raises(ValueError, match='guard ceiling'):
        runtime.configured_session(kind='game', limit_gib=limit_gib, timeout=0)
    assert client[3] == []


def test_full_game_cannot_repair_a_profile_below_the_default_guard(client, monkeypatch):
    configure_schema(client, monkeypatch, 2)
    client[1]['profiles']['game']['resources']['memory_mib'] = 4096
    client[1]['profiles']['game']['resources']['gpu_mib'] = 0
    client[2]()
    with pytest.raises(ValueError, match='smaller than the actual guard'):
        runtime.configured_session(kind='game', limit_gib=12, timeout=0)
    assert client[3] == []


@pytest.mark.parametrize('schema', [1, 2])
@pytest.mark.parametrize('io_slots', [0, 1])
def test_profiles_preserve_optional_io_reservations(client, monkeypatch, schema, io_slots):
    configure_schema(client, monkeypatch, schema)
    _, value, write, _ = client
    value['profiles']['job']['resources']['io_slots'] = io_slots
    write()
    request = runtime.configured_session(kind='job', command=['Blender', '--threads', '3'],
                                         limit_gib=10, timeout=60)
    assert request['resources']['io_slots'] == io_slots
    assert request['resources']['memory_mib'] == 10240
    assert request['resources']['cpu_millis'] == 3000
    assert 'checkout:' + str(runtime.REPO) in request['locks']


@pytest.mark.parametrize('schema', [1, 2])
@pytest.mark.parametrize('threads', [3, 6])
def test_bounded_blender_job_charges_actual_unchanged_threads(client, monkeypatch, schema, threads):
    configure_schema(client, monkeypatch, schema)
    _, value, write, _ = client
    value['profiles']['job']['resources']['cpu_millis'] = 6000
    write()
    command = ['Blender', '-b', '--threads', str(threads)]
    request = runtime.configured_session(kind='job', command=command, limit_gib=10, timeout=60)
    assert request['resources'] == value['profiles']['job']['resources'] | {'cpu_millis': threads * 1000}
    assert command == ['Blender', '-b', '--threads', str(threads)]
    assert request['performance'] is False


@pytest.mark.parametrize('schema', [1, 2])
@pytest.mark.parametrize('command', [['Blender', '-b'], ['sh', '-c', 'Blender --threads 3']])
@pytest.mark.parametrize('kind', ['job', 'game', 'compile'])
def test_unknown_or_threadless_launches_keep_conservative_cpu_policy(client, monkeypatch, schema, command, kind):
    configure_schema(client, monkeypatch, schema)
    client[1]['profiles'][kind]['resources']['cpu_millis'] = 6000
    client[2]()
    request = runtime.configured_session(kind=kind, command=command, limit_gib=10, timeout=60)
    assert request['resources']['cpu_millis'] == (8000 if schema == 2 else 6000)
    assert request['performance'] is (schema == 2)


def test_client_configuration_is_not_read_through_a_symlink(client):
    path, _, write, _ = client
    write()
    other = path.with_name('target.json')
    path.rename(other)
    path.symlink_to(other)
    with pytest.raises(OSError):
        runtime.configured_session(kind='job', limit_gib=10, timeout=0)


def test_public_configuration_is_refused(client):
    client[2]()
    client[0].chmod(0o644)
    with pytest.raises(ValueError, match='private owned regular file'):
        runtime.configured_session(kind='job', limit_gib=10, timeout=0)


def test_incomplete_profile_set_cannot_fall_back_for_other_work(client):
    del client[1]['profiles']['compile']
    client[2]()
    with pytest.raises(ValueError, match='job, game and compile'):
        runtime.configured_session(kind='job', limit_gib=10, timeout=0)
