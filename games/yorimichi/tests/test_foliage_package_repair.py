"""Invalid packages are preserved before their exact owned paths become importable."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def repair(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'unreal/Scripts/foliage_package_repair.py'
    spec = importlib.util.spec_from_file_location('fixture_foliage_package_repair', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.content = tmp_path / 'Content'
    module.output = tmp_path / 'build'
    module.member = module.content / 'Japan/Assets/Tree_Test.uasset'
    module.member.parent.mkdir(parents=True)
    return module


def run(repair):
    return repair.quarantine_invalid_package(repair.content, repair.output, 'Tree_Test', require_unloaded=lambda: None)


@pytest.mark.parametrize('data', [None, b'\xc1\x83\x2a\x9e', b'\x9e\x2a\x83\xc1invalid body'])
def test_missing_or_valid_tag_never_removes_or_preserves_a_package(repair, data):
    if data is not None:
        repair.member.write_bytes(data)
    sidecar = repair.member.with_suffix('.ubulk')
    sidecar.write_bytes(b'keep')
    assert run(repair) is None
    assert repair.member.exists() is (data is not None)
    if data is not None:
        assert repair.member.read_bytes() == data
    assert sidecar.read_bytes() == b'keep'
    assert not repair.output.exists()


def test_valid_header_does_not_enter_the_unloaded_package_repair_path(repair):
    repair.member.write_bytes(b'\xc1\x83\x2a\x9e')
    def refuse_check():
        pytest.fail('Valid-header reimport must not require an unloaded package')
    assert repair.quarantine_invalid_package(repair.content, repair.output, 'Tree_Test',
                                             require_unloaded=refuse_check) is None


@pytest.mark.parametrize('fail_at', [1, 2])
def test_loaded_package_refusal_preserves_every_original_leaf(repair, fail_at):
    repair.member.write_bytes(b'bad header')
    sidecar = repair.member.with_suffix('.ubulk')
    sidecar.write_bytes(b'bulk')
    calls = 0
    def require_unloaded():
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise RuntimeError('Package already loaded')
    with pytest.raises(RuntimeError, match='already loaded'):
        repair.quarantine_invalid_package(repair.content, repair.output, 'Tree_Test',
                                           require_unloaded=require_unloaded)
    assert repair.member.read_bytes() == b'bad header'
    assert sidecar.read_bytes() == b'bulk'
    assert calls == fail_at


@pytest.mark.parametrize('data', [b'', b'bad', b'invalid package bytes'])
def test_invalid_header_preserves_every_byte_before_removing_only_the_owned_leaves(repair, data, monkeypatch):
    original = {'.uasset': data, '.uexp': b'exports', '.ubulk': b'bulk'}
    for suffix, value in original.items():
        repair.member.with_suffix(suffix).write_bytes(value)
    neighbor = repair.member.with_name('Tree_Other.uasset')
    neighbor.write_bytes(b'unrelated')
    original_unlink = Path.unlink
    removed = []

    def checked_unlink(path, *args, **kwargs):
        folders = list((repair.output / 'logs/foliage-repair/Tree_Test').iterdir())
        assert len(folders) == 1
        folder = folders[0]
        receipt = json.loads((folder / 'receipt.json').read_text())
        assert receipt['state'] == 'preserved'
        for suffix, value in original.items():
            saved = folder / repair.member.with_suffix(suffix).name
            assert saved.read_bytes() == value
            assert receipt['files'][saved.name]['sha256'] == hashlib.sha256(value).hexdigest()
        removed.append(path.suffix)
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', checked_unlink)
    folder = run(repair)
    assert removed == ['.uexp', '.ubulk', '.uasset']
    assert json.loads((folder / 'receipt.json').read_text())['state'] == 'quarantined'
    assert neighbor.read_bytes() == b'unrelated'
    assert not repair.member.exists()
    assert folder.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize('suffix', ['.uasset', '.uexp', '.ubulk'])
@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'directory'])
def test_linked_or_nonregular_leaf_refuses_before_any_package_mutation(repair, suffix, kind):
    repair.member.write_bytes(b'bad header')
    member = repair.member.with_suffix(suffix)
    target = repair.member.parent / 'unrelated.bin'
    target.write_bytes(b'keep unrelated')
    if member.exists():
        member.unlink()
    if kind == 'symlink':
        member.symlink_to(target)
    elif kind == 'hardlink':
        os.link(target, member)
    else:
        member.mkdir()
    with pytest.raises(ValueError, match='regular single-link'):
        run(repair)
    assert target.read_bytes() == b'keep unrelated'
    assert member.exists()
    if suffix != '.uasset':
        assert repair.member.read_bytes() == b'bad header'
    assert not repair.output.exists()


def test_failed_backup_keeps_all_original_files(repair, monkeypatch):
    repair.member.write_bytes(b'bad header')
    sidecar = repair.member.with_suffix('.ubulk')
    sidecar.write_bytes(b'keep sidecar')
    real_open = Path.open

    def refuse_backup(path, mode='r', *args, **kwargs):
        if mode == 'xb':
            raise OSError('disk full')
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', refuse_backup)
    with pytest.raises(OSError, match='disk full'):
        run(repair)
    assert repair.member.read_bytes() == b'bad header'
    assert sidecar.read_bytes() == b'keep sidecar'


def test_new_archive_ancestors_are_synced_before_any_original_is_removed(repair, monkeypatch):
    repair.member.write_bytes(b'bad header')
    synced = []
    real_sync, real_unlink = repair._sync, Path.unlink

    def sync(directory):
        synced.append(directory)
        real_sync(directory)

    def unlink(path, *args, **kwargs):
        assert repair.output.parent in synced
        assert repair.output in synced
        assert repair.output / 'logs' in synced
        assert repair.output / 'logs/foliage-repair' in synced
        assert repair.output / 'logs/foliage-repair/Tree_Test' in synced
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(repair, '_sync', sync)
    monkeypatch.setattr(Path, 'unlink', unlink)
    run(repair)


def test_linked_archive_parent_refuses_before_writing_or_removing_files(repair):
    repair.member.write_bytes(b'bad header')
    other = repair.content / 'unrelated'
    other.mkdir()
    repair.output.mkdir()
    (repair.output / 'logs').symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match='must not contain links'):
        run(repair)
    assert list(other.iterdir()) == []
    assert repair.member.read_bytes() == b'bad header'


def test_main_changed_to_valid_after_detection_is_preserved(repair, monkeypatch):
    repair.member.write_bytes(b'bad header')
    real_open = repair._open
    count = 0

    def change_before_second_open(path):
        nonlocal count
        if path == repair.member:
            count += 1
            if count == 2:
                path.write_bytes(b'\xc1\x83\x2a\x9enew valid package')
        return real_open(path)

    monkeypatch.setattr(repair, '_open', change_before_second_open)
    with pytest.raises(ValueError, match='changed before preservation'):
        run(repair)
    assert repair.member.read_bytes() == b'\xc1\x83\x2a\x9enew valid package'
    assert not repair.output.exists()


def test_changed_leaf_after_backup_is_not_removed(repair, monkeypatch):
    repair.member.write_bytes(b'bad header')
    real_receipt = repair._receipt

    def change_after_preservation(folder, value):
        real_receipt(folder, value)
        if value['state'] == 'preserved':
            repair.member.write_bytes(b'concurrent new content')

    monkeypatch.setattr(repair, '_receipt', change_after_preservation)
    with pytest.raises(ValueError, match='changed before quarantine'):
        run(repair)
    assert repair.member.read_bytes() == b'concurrent new content'
    folder, = (repair.output / 'logs/foliage-repair/Tree_Test').iterdir()
    assert (folder / repair.member.name).read_bytes() == b'bad header'


def test_interruption_keeps_invalid_main_until_all_sidecars_are_preserved(repair, monkeypatch):
    repair.member.write_bytes(b'bad header')
    sidecar = repair.member.with_suffix('.ubulk')
    sidecar.write_bytes(b'bulk')
    real_unlink = Path.unlink

    def interrupt_after_sidecar(path, *args, **kwargs):
        real_unlink(path, *args, **kwargs)
        raise RuntimeError('interrupted')

    monkeypatch.setattr(Path, 'unlink', interrupt_after_sidecar)
    with pytest.raises(RuntimeError, match='interrupted'):
        run(repair)
    assert repair.member.read_bytes() == b'bad header'
    first, = (repair.output / 'logs/foliage-repair/Tree_Test').iterdir()
    assert (first / sidecar.name).read_bytes() == b'bulk'
    assert (first / repair.member.name).read_bytes() == b'bad header'
    monkeypatch.setattr(Path, 'unlink', real_unlink)
    second = run(repair)
    assert second != first and (second / repair.member.name).read_bytes() == b'bad header'
    assert not repair.member.exists()
