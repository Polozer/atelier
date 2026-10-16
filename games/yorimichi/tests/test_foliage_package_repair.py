"""Invalid packages are preserved before their exact owned paths become importable."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType

import pytest


@pytest.fixture
def preflight(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[1] / 'unreal/Scripts/prepare_foliage.py'
    yori = ModuleType('yori')
    yori.GAME, yori.OUT = tmp_path / 'game', tmp_path / 'build'
    catalog = ModuleType('asset_catalog')
    catalog.FOLIAGE = {'Tree_Test': {}}
    helper = ModuleType('foliage_package_repair')
    calls = []
    def quarantine(*args, require_unloaded):
        require_unloaded()
        calls.append(args)
        return tmp_path / 'preserved'
    helper.quarantine_invalid_package = quarantine
    for name, module in [('yori', yori), ('asset_catalog', catalog), ('foliage_package_repair', helper)]:
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.setenv('ATELIER_FOLIAGE', 'Tree_Test')
    monkeypatch.delitem(sys.modules, 'unreal', raising=False)
    spec = importlib.util.spec_from_file_location('fixture_prepare_foliage', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, calls, yori


def test_actual_pre_editor_hook_selects_only_its_catalog_owner(preflight, capsys):
    module, calls, yori = preflight
    module.main()
    assert calls == [(yori.GAME / 'unreal/Content', yori.OUT, 'Tree_Test')]
    assert capsys.readouterr().out.startswith('Preserved invalid foliage package before fresh import: ')


@pytest.mark.parametrize('bad', ['unknown-owner', 'editor-loaded'])
def test_pre_editor_hook_refuses_before_preservation(preflight, monkeypatch, bad):
    module, calls, _ = preflight
    if bad == 'unknown-owner':
        monkeypatch.setenv('ATELIER_FOLIAGE', '../Tree_Test')
    else:
        monkeypatch.setitem(sys.modules, 'unreal', ModuleType('unreal'))
    with pytest.raises((ValueError, RuntimeError)):
        module.main()
    assert calls == []


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


@pytest.mark.parametrize('data', [None, b'\xc1\x83\x2a\x9e', b'\x9e\x2a\x83\xc1bad body', b'bad tag'])
def test_editor_refuses_new_invalid_tag_without_mutating_files(repair, data):
    if data is not None:
        repair.member.write_bytes(data)
    if data == b'bad tag':
        with pytest.raises(RuntimeError, match='after pre-editor'):
            repair.require_valid_or_missing(repair.content, 'Tree_Test')
    else:
        repair.require_valid_or_missing(repair.content, 'Tree_Test')
    assert repair.member.exists() is (data is not None)
    if data is not None:
        assert repair.member.read_bytes() == data
    assert not repair.output.exists()


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
    original_claim = repair._claim
    removed = []

    def checked_claim(path, destination):
        folders = list((repair.output / 'logs/foliage-repair/Tree_Test').iterdir())
        assert len(folders) == 1
        folder = folders[0]
        receipt = json.loads((folder / 'receipt.json').read_text())
        assert receipt['state'] == 'claiming'
        for suffix, value in original.items():
            saved = folder / repair.member.with_suffix(suffix).name
            assert saved.read_bytes() == value
            assert receipt['files'][saved.name]['sha256'] == hashlib.sha256(value).hexdigest()
        removed.append(path.suffix)
        return original_claim(path, destination)

    monkeypatch.setattr(repair, '_claim', checked_claim)
    folder = run(repair)
    assert removed == ['.uexp', '.ubulk', '.uasset']
    assert json.loads((folder / 'receipt.json').read_text())['state'] == 'quarantined'
    assert neighbor.read_bytes() == b'unrelated'
    assert not repair.member.exists()
    assert folder.stat().st_mode & 0o077 == 0
    for suffix, value in original.items():
        assert (folder / ('claimed-' + repair.member.with_suffix(suffix).name)).read_bytes() == value


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
    real_sync, real_claim = repair._sync, repair._claim

    def sync(directory):
        synced.append(directory)
        real_sync(directory)

    def claim(path, destination):
        assert repair.output.parent in synced
        assert repair.output in synced
        assert repair.output / 'logs' in synced
        assert repair.output / 'logs/foliage-repair' in synced
        assert repair.output / 'logs/foliage-repair/Tree_Test' in synced
        return real_claim(path, destination)

    monkeypatch.setattr(repair, '_sync', sync)
    monkeypatch.setattr(repair, '_claim', claim)
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
    real_claim = repair._claim

    def interrupt_after_sidecar(path, destination):
        real_claim(path, destination)
        raise RuntimeError('interrupted')

    monkeypatch.setattr(repair, '_claim', interrupt_after_sidecar)
    with pytest.raises(RuntimeError, match='interrupted'):
        run(repair)
    assert repair.member.read_bytes() == b'bad header'
    first, = (repair.output / 'logs/foliage-repair/Tree_Test').iterdir()
    assert (first / sidecar.name).read_bytes() == b'bulk'
    assert (first / repair.member.name).read_bytes() == b'bad header'
    assert (first / ('claimed-' + sidecar.name)).read_bytes() == b'bulk'
    monkeypatch.setattr(repair, '_claim', real_claim)
    second = run(repair)
    assert second != first and (second / repair.member.name).read_bytes() == b'bad header'
    assert not repair.member.exists()


def test_replacement_after_final_pin_is_claimed_and_retained_instead_of_unlinked(repair, monkeypatch):
    repair.member.write_bytes(b'old invalid header')
    replacement = b'\xc1\x83\x2a\x9enew valid concurrent package'
    real_claim = repair._claim
    def replace_before_claim(path, destination):
        fresh = path.with_suffix('.new')
        fresh.write_bytes(replacement)
        fresh.replace(path)
        real_claim(path, destination)
    monkeypatch.setattr(repair, '_claim', replace_before_claim)
    with pytest.raises(ValueError, match='changed at atomic quarantine'):
        run(repair)
    folder, = (repair.output / 'logs/foliage-repair/Tree_Test').iterdir()
    assert (folder / repair.member.name).read_bytes() == b'old invalid header'
    assert (folder / ('claimed-' + repair.member.name)).read_bytes() == replacement
    receipt = json.loads((folder / 'receipt.json').read_text())
    assert receipt['state'] == 'claim_failed'
    assert receipt['claims'][repair.member.name]['sha256'] == hashlib.sha256(replacement).hexdigest()


def test_replacement_after_final_open_is_never_discarded(repair, monkeypatch):
    """The fifth main-file open is the final pin check, in both the old unlink and new claim paths."""
    from types import SimpleNamespace
    repair.member.write_bytes(b'old invalid header')
    replacement = b'\xc1\x83\x2a\x9enew valid concurrent package'
    real_open = repair._open
    calls = 0
    def open_then_swap(path):
        nonlocal calls
        source, info = real_open(path)
        if path == repair.member:
            calls += 1
            if calls == 5:
                def close_and_replace():
                    source.close()
                    fresh = path.with_suffix('.new')
                    fresh.write_bytes(replacement)
                    fresh.replace(path)
                return SimpleNamespace(close=close_and_replace), info
        return source, info
    monkeypatch.setattr(repair, '_open', open_then_swap)
    with pytest.raises(ValueError, match='changed at atomic quarantine'):
        run(repair)
    folder, = (repair.output / 'logs/foliage-repair/Tree_Test').iterdir()
    assert (folder / ('claimed-' + repair.member.name)).read_bytes() == replacement
    assert (folder / repair.member.name).read_bytes() == b'old invalid header'


def test_replacement_after_claim_keeps_both_files_and_refuses(repair, monkeypatch):
    repair.member.write_bytes(b'old invalid header')
    replacement = b'\xc1\x83\x2a\x9enew replacement'
    real_claim = repair._claim
    def replace_after_claim(path, destination):
        real_claim(path, destination)
        path.write_bytes(replacement)
    monkeypatch.setattr(repair, '_claim', replace_after_claim)
    with pytest.raises(ValueError, match='replaced after atomic quarantine'):
        run(repair)
    assert repair.member.read_bytes() == replacement
    folder, = (repair.output / 'logs/foliage-repair/Tree_Test').iterdir()
    assert (folder / ('claimed-' + repair.member.name)).read_bytes() == b'old invalid header'


def test_atomic_claim_never_replaces_an_existing_destination(repair):
    repair.member.write_bytes(b'keep source')
    destination = repair.member.with_suffix('.claimed')
    destination.write_bytes(b'keep destination')
    with pytest.raises(FileExistsError):
        repair._claim(repair.member, destination)
    assert repair.member.read_bytes() == b'keep source'
    assert destination.read_bytes() == b'keep destination'


def test_failed_receipt_write_cleans_only_its_temporary_and_allows_failure_receipt(repair, tmp_path, monkeypatch):
    folder = tmp_path / 'receipt'
    folder.mkdir()
    repair._receipt(folder, {'state': 'preserved'})
    def interrupted(value, stream, **kwargs):
        stream.write('{"state":')
        raise OSError('interrupted receipt write')
    with monkeypatch.context() as change:
        change.setattr(repair.json, 'dump', interrupted)
        with pytest.raises(OSError, match='interrupted receipt'):
            repair._receipt(folder, {'state': 'claiming'})
    assert not (folder / 'receipt.next').exists()
    assert json.loads((folder / 'receipt.json').read_text()) == {'state': 'preserved'}
    repair._receipt(folder, {'state': 'claim_failed'})
    assert json.loads((folder / 'receipt.json').read_text()) == {'state': 'claim_failed'}
