"""Pure evidence retention/parsing tests. No Unreal, process, lock, socket or cooker state is used."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def load(name):
    path = Path(__file__).parents[1] / 'tools' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.fixture
def sample(tmp_path, monkeypatch):
    tool = load('cook_acceptance')
    experiment = load('cook_experiment')
    build = tmp_path / 'build'
    app = build / 'package/archive/Mac/Sandbox.app'
    for name in ['Contents/MacOS/Sandbox', 'Contents/UE/Sandbox/Content/Paks/game.utoc', 'Contents/UE/Sandbox/Content/Paks/game.ucas']:
        path = app / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(name.encode())
    guard = build / 'logs/unreal.cook.guard'; guard.mkdir(parents=True)
    (guard / 'stdout.log').write_bytes(b'completed observed log\n')
    from atelier.build_cook import Observer, CookMode
    (guard / 'stdout.log').write_text('''LogCook: Display: INCREMENTAL COOK DEPENDENCIES: Enabled. Incremental Cook Dependencies are enabled in Editor.ini:[CookSettings]:LegacyIterative=false.
LogCook: Display: FULL COOK: -forcerecook=true (or an equivalent) was specified.
Cook command time: 1.5 s
********** COOK COMMAND COMPLETED **********
''')
    observer = Observer(guard, CookMode.FULL); observer.reason = 'full'; observer.poll(123)
    observation = observer.finish(success=True)
    source = dict(revision='a'*40, dirty=True, fingerprint='native-source', mode='modern-full', engine=dict(MajorVersion=5, MinorVersion=8))
    ctx = SimpleNamespace(out=build, logs=build / 'logs', cook_mode=CookMode.FULL, cook_source=source, cook_observation=observation)
    monkeypatch.setattr(experiment, 'source_snapshot', lambda _: dict(source))
    experiment.finish(ctx, io.StringIO())  # Real producer output, not a hand-authored receipt shape.
    value = dict(fingerprint='native-source', seconds=2, time=1, input_state={},
                 commands=[dict(kind='Call', seconds=.1, scope='command invocation'),
                           dict(kind='UnrealPackage', seconds=1.5, scope='command invocation', phases=dict(cook=observation)),
                           dict(kind='Call', seconds=.1, scope='command invocation')])
    (build / 'stamps').mkdir(); (build / 'stamps/unreal.cook.json').write_text(json.dumps(value))
    identity = dict(revision='a'*40, patch='intentional fixture diff')
    record = tmp_path / 'source-record.json'; record.write_text(json.dumps(identity))
    monkeypatch.setattr(tool, 'source_record', lambda _: dict(identity))
    return tool, build, app, record, identity


def retain(sample, tmp_path, **options):
    tool, build, _, record, _ = sample
    return tool.retain(build, tmp_path / 'retained', source=tmp_path, recorded_source=record, label='full', **options)


def test_retention_copies_independent_archive_before_reused_paths_are_cleaned(sample, tmp_path):
    tool, build, app, _, _ = sample
    report = retain(sample, tmp_path)
    copy = tmp_path / 'retained/app/Sandbox.app/Contents/MacOS/Sandbox'
    original = app / 'Contents/MacOS/Sandbox'
    assert copy.stat().st_ino != original.stat().st_ino
    original.write_bytes(b'next cook')
    assert copy.read_bytes() == b'Contents/MacOS/Sandbox'
    assert not report['native_parity'] and report['retained_only']
    assert report['files']['app/Sandbox.app/Contents/MacOS/Sandbox'] == tool.digest(copy)
    assert json.loads((build / 'stamps/unreal.cook.json').read_text())['fingerprint'] == 'native-source'
    with pytest.raises(ValueError, match='never overwrite'):
        retain(sample, tmp_path)


@pytest.mark.parametrize('damage', ['log', 'source', 'app', 'stamp', 'touched', 'frozen'])
def test_changed_or_uncertified_evidence_never_gets_a_completed_manifest(sample, tmp_path, damage):
    tool, build, app, _, identity = sample
    options = {}
    if damage == 'log': (build / 'logs/unreal.cook.guard/stdout.log').write_text('changed')
    elif damage == 'source': identity['patch'] = 'a different edit'
    elif damage == 'app': (app / 'Contents/MacOS/Sandbox').write_text('changed')
    elif damage == 'stamp': (build / 'stamps/unreal.cook.json').write_text('{"fingerprint":"old"}')
    elif damage == 'touched': (build / 'stamps/unreal.cook.json').write_text('{"fingerprint":"native-source","touched":true}')
    else:
        asset = tmp_path / 'CookProbe.uasset'; asset.write_bytes(b'resaved')
        options = dict(frozen_asset=asset, frozen_sha='0'*64)
    with pytest.raises(ValueError): retain(sample, tmp_path, **options)
    assert not (tmp_path / 'retained/evidence.json').exists()


def test_source_record_binds_exact_tracked_patch_and_refuses_untracked_source(tmp_path, monkeypatch):
    from atelier import provenance
    tool = load('cook_acceptance')
    monkeypatch.setattr(provenance, 'head', lambda **kwargs: 'a'*40)
    monkeypatch.setattr(provenance, 'git', lambda *args, **kwargs: 'exact patch')
    monkeypatch.setattr(provenance, 'status', lambda **kwargs: ' M intentional.cpp\n')
    assert tool.source_record(tmp_path) == dict(revision='a'*40, patch='exact patch')
    monkeypatch.setattr(provenance, 'status', lambda **kwargs: '?? unknown.cpp\n')
    with pytest.raises(ValueError, match='untracked'): tool.source_record(tmp_path)


RUNTIME = '''LogTemp: Display: ATELIER_COOK_ASSET name=CookProbe state=loaded type=double value=4
LogTemp: Display: ATELIER_COOK_ASSET name=MutableProbe state=missing
LogTemp: Display: ATELIER_COOK_IDENTITY map=Sandbox config=config-edit gi=0 reflection=0
LogTemp: Display: ATELIER_COOK_ACTOR tag=Block scale=4,4,2 location=800,600,100
'''


def test_runtime_requires_explicit_missing_type_config_renderer_and_map_evidence(tmp_path):
    tool = load('cook_acceptance')
    observed = tool.runtime(RUNTIME)
    assert observed['assets']['MutableProbe'] == dict(state='missing')
    assert observed['assets']['CookProbe'] == dict(state='loaded', type='double', value=4)
    log = tmp_path / 'runtime.log'; log.write_text(RUNTIME)
    expected = tmp_path / 'expected.json'; expected.write_text(json.dumps(observed))
    assert tool.check_runtime(log, expected)['native_parity'] is False
    expected.write_text(json.dumps({**observed, 'identity': dict(map='Sandbox', config='baseline', gi=1, reflection=1)}))
    with pytest.raises(ValueError, match='differ'): tool.check_runtime(log, expected)


@pytest.mark.parametrize('text', [RUNTIME.split('ATELIER_COOK_IDENTITY')[0], RUNTIME.replace('value=4', 'value=nan'),
    RUNTIME + RUNTIME.replace('value=4', 'value=7'), RUNTIME.replace('state=missing', 'state=loaded')])
def test_incomplete_or_conflicting_runtime_is_not_parity_evidence(text):
    with pytest.raises(ValueError): load('cook_acceptance').runtime(text)


@pytest.mark.parametrize('which', ['cook.json', 'unreal.cook.json', 'cook-observation.json', 'stdout.log'])
def test_concurrent_receipt_stamp_or_log_replacement_never_certifies_mixed_sample(sample, tmp_path, monkeypatch, which):
    tool, _, _, _, _ = sample
    copy = tool.shutil.copy2
    changed = []
    def replace_after_copy(source, target, *args, **kwargs):
        result = copy(source, target, *args, **kwargs)
        if Path(source).name == which and not changed:
            changed.append(True)
            Path(source).write_bytes(Path(source).read_bytes() + b'\n')
        return result
    monkeypatch.setattr(tool.shutil, 'copy2', replace_after_copy)
    # copytree binds its default copy function at definition time; explicit receipt/stamp copies
    # trigger guard mutations too so all four races are exercised without real concurrency.
    if which in ('cook-observation.json', 'stdout.log'):
        def mutate_guard(source, target, *args, **kwargs):
            result = copy(source, target, *args, **kwargs)
            if Path(source).name == 'cook.json' and not changed:
                changed.append(True)
                path = sample[1] / 'logs/unreal.cook.guard' / which
                path.write_bytes(path.read_bytes() + b'\n')
            return result
        monkeypatch.setattr(tool.shutil, 'copy2', mutate_guard)
    with pytest.raises(ValueError, match='changed'): retain(sample, tmp_path)
    assert changed and not (tmp_path / 'retained/evidence.json').exists()


@pytest.mark.parametrize('marker', ['restored_from', 'reused_from', 'pooled_from'])
def test_actual_build_restoration_markers_refuse_as_native_samples(sample, tmp_path, marker):
    path = sample[1] / 'stamps/unreal.cook.json'
    value = json.loads(path.read_text()); value[marker] = 'origin'; path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='actual native execution'): retain(sample, tmp_path)


def test_label_must_match_real_observer_cook_reason(sample, tmp_path):
    tool, build, _, record, _ = sample
    with pytest.raises(ValueError, match='label differs'):
        tool.retain(build, tmp_path / 'wrong-label', source=tmp_path, recorded_source=record, label='warm-1')


@pytest.mark.parametrize('target', ['relative', 'absolute', 'external'])
def test_only_relative_internal_app_symlinks_are_retained(sample, tmp_path, target):
    tool, build, app, _, _ = sample
    link = app / 'executable-link'
    if target == 'relative': link.symlink_to('Contents/MacOS/Sandbox')
    elif target == 'absolute': link.symlink_to(app / 'Contents/MacOS/Sandbox')
    else:
        outside = tmp_path / 'outside'; outside.write_bytes(b'not owned by the app'); link.symlink_to(outside)
    path = build / 'package/cook.json'; receipt = json.loads(path.read_text())
    receipt['files'] = load('cook_experiment').inventory(app)
    path.write_text(json.dumps(receipt))
    if target == 'relative':
        retain(sample, tmp_path)
        assert (tmp_path / 'retained/app/Sandbox.app/executable-link').resolve().is_relative_to(tmp_path / 'retained/app')
    else:
        with pytest.raises(ValueError, match='symlink'): retain(sample, tmp_path)
        assert not (tmp_path / 'retained').exists()
