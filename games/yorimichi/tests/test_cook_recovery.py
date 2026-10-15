"""Interrupted native certification recovery; native work and admission are mocked."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
from types import SimpleNamespace
import zipfile

import pytest

from atelier import build, build_cook_recovery as recovery, provenance
from atelier.build_cook import CookMode
from atelier.build_hashes import HashIndex
from atelier.safety import guarded


def tool(name):
    path = Path(__file__).parents[1] / 'tools' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.fixture
def sample(tmp_path, monkeypatch):
    cook = tool('package_cook')
    monkeypatch.setattr(cook, 'recovery_config_inputs', lambda _: [])
    out = tmp_path / 'build'; out.mkdir()
    content = tmp_path / 'Content'; content.mkdir(); (content / 'probe.uasset').write_bytes(b'original asset')
    source = tmp_path / 'source.cpp'; source.write_text('source')
    adapter = tmp_path / 'tool'; adapter.write_text('tool')
    prerequisite = tmp_path / 'editor.dylib'; prerequisite.write_bytes(b'editor')
    ctx = SimpleNamespace(game='fixture', out=out, logs=out / 'logs', stamps=out / 'stamps',
        cook_mode=CookMode.DEFAULT, cook_reason=None, recover_cook=None, record_cook_recovery=True, unreal_root=tmp_path / 'engine',
        game_dir=tmp_path, uproject=tmp_path / 'Fixture.uproject', env=lambda extra=(): {**os.environ, **dict(extra)}, cook_source=None)
    ctx.stamps.mkdir()
    monkeypatch.setenv('UE_HEADLESS_USER_DIR', 'test-headless')
    monkeypatch.setattr(provenance, 'head', lambda: 'a'*40)
    monkeypatch.setattr(provenance, 'status', lambda **_: '')
    monkeypatch.setattr(provenance, 'git', lambda *_, **__: '')
    identity = dict(revision='a'*40, source_dirty=False, fingerprint='source-proof', engine={'BuildId':'fixture'})
    monkeypatch.setattr(cook, 'source_snapshot', lambda _: dict(identity))
    need = build.Step('unreal.editor', [], inputs=[source], outputs=[prerequisite])
    (ctx.stamps / 'unreal.editor.json').write_text(json.dumps(dict(fingerprint=build.fingerprint(need, {}))))
    command = build.UnrealPackage('Fixture', out / 'package/archive')
    step = build.Step('unreal.cook', [build.Call('prepare', cook.prepare), command, build.Call('certify', cook.finish)],
        inputs=[source], needs=[need.name], outputs=[out / 'package/cook.json'], heavy=True,
        verify=lambda: cook.cook_present(out / 'package'),
        cook_recovery=recovery.CookRecovery(cook.source_snapshot, cook.finish, lambda _: [content, adapter]))
    steps = [need, step]
    monkeypatch.setattr(build, 'load_recipe', lambda _: SimpleNamespace(steps=lambda _: steps))
    monkeypatch.setattr(build, 'Context', lambda *args, **kwargs: ctx)
    monkeypatch.setattr(build, 'slot_count', lambda: 1)
    calls = []
    execs = []
    monkeypatch.setattr(recovery.os, 'execvpe', lambda executable, argv, environment: execs.append((executable, argv, environment)))
    def native(argv, folder, **kwargs):
        calls.append(argv)
        attempt = kwargs['completion_path'].parent
        assert not (attempt / 'prepared.json').exists(), 'no expensive inventory before guarded execution'
        recovery.prepare_exec(attempt)
        request = recovery.read(attempt / 'launch-request.json')
        assert execs[-1] == (request['argv'][0], request['argv'], kwargs['env'])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'stdout.log').write_text('Cook command time: 1 s\n********** COOK COMMAND COMPLETED **********\nBUILD SUCCESSFUL\n')
        kwargs['on_slot']('big', '')
        kwargs['on_poll'](123)
        app = command.archive / 'Mac/Fixture.app'
        for name, data in {'Contents/MacOS/Fixture': b'game', 'Contents/UE/Fixture/Content/Data/world.json':b'{}',
            'Contents/UE/Fixture/Content/Data/heightmap.bin': b'height', 'Contents/UE/Fixture/Content/Data/map/map.json':b'{}'}.items():
            path = app / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        terminal = dict(owner=123, owner_started=456, state='child_exited', cleanup_complete=True)
        recovery.write(kwargs['completion_path'], dict(schema=1, kind='guarded-success', returncode=0,
            cleanup_and_capacity_close=True, invocation_id=kwargs['invocation_id'], root=[123,456],
            monitors=dict(process=[12,34], tree=[56,78]), terminal=terminal,
            command_sha256=recovery.identity(argv), environment_sha256=recovery.identity(kwargs['env'])))
        return 0
    monkeypatch.setattr(build.guarded, 'run', native)
    def run(wanted='unreal.cook'):
        with HashIndex(out / 'hashes.sqlite3') as index:
            return build._build(ctx, [wanted], force=False, touch=False, echo=lambda *_: None, index=index, steps=steps)
    return SimpleNamespace(cook=cook, ctx=ctx, step=step, steps=steps, calls=calls, run=run,
                           content=content, source=source, adapter=adapter, prerequisite=prerequisite)


def interrupted(sample, monkeypatch):
    inventory = sample.cook.inventory
    def fail_during_hash(*args, **kwargs):
        if kwargs.get('hashes'):
            raise RuntimeError('certification hashing interrupted')
        return inventory(*args, **kwargs)
    monkeypatch.setattr(sample.cook, 'inventory', fail_during_hash)
    assert sample.run() == 1
    attempt = next((sample.ctx.out / 'cook-attempts').iterdir())
    assert (attempt / 'completed.json').exists() and (attempt / 'guarded-success.json').exists()
    assert not (sample.ctx.stamps / 'unreal.cook.json').exists()
    monkeypatch.setattr(sample.cook, 'inventory', inventory)
    sample.ctx.recover_cook = attempt.name
    return attempt


def test_interruption_during_hash_recovers_and_normal_package_consumes_without_uat(sample, monkeypatch):
    attempt = interrupted(sample, monkeypatch)
    archive = tool('package_archive')
    monkeypatch.setattr(archive, 'audio_compatibility', lambda *args: None)
    def bounded(argv, log, label, watch):
        if label == 'copy cooked app':
            shutil.copytree(argv[1], argv[2], symlinks=True)
        elif label == 'zip':
            with zipfile.ZipFile(argv[-1], 'w') as output:
                for path in Path(argv[-2]).rglob('*'):
                    if path.is_file(): output.write(path, path.relative_to(Path(argv[-2]).parent))
        else: raise AssertionError(label)
    monkeypatch.setattr(archive, 'bounded', bounded)
    package = build.Step('unreal.package', [build.Call('assemble', lambda ctx, log: archive.package_zip(ctx.out / 'package', log, cook_receipt=True))],
        needs=['unreal.cook'], outputs=[sample.ctx.out / 'package/manifest.json'])
    sample.steps.append(package)
    assert sample.run('unreal.package') == 0
    stamp = json.loads((sample.ctx.stamps / 'unreal.cook.json').read_text())
    assert stamp['commands'] == [dict(kind='CookCertificationRecovery', attempt_id=attempt.name,
        guarded_sha256=json.loads((attempt / 'completed.json').read_text())['guarded_sha256'], scope='certification recovery only')]
    manifest = json.loads((sample.ctx.out / 'package/manifest.json').read_text())
    assert manifest['cook']['revision'] == 'a'*40 and (sample.ctx.out / 'package' / manifest['zip']).is_file()
    assert len(sample.calls) == 1
    assert sample.run('unreal.package') == 0 and len(sample.calls) == 1


@pytest.mark.parametrize('damage', ['source', 'tool', 'prerequisite', 'native', 'archive', 'archive-restored-mtime',
    'missing-positive', 'missing-prepared', 'wrong-invocation', 'guard-failure', 'wrong-root'])
def test_changed_or_unproven_attempt_refuses_without_native_fallback(sample, monkeypatch, damage):
    attempt = interrupted(sample, monkeypatch)
    paths = dict(source=sample.source, tool=sample.adapter, prerequisite=sample.prerequisite,
                 native=sample.content / 'probe.uasset', archive=sample.step.commands[1].archive / 'Mac/Fixture.app/Contents/MacOS/Fixture')
    if damage == 'archive-restored-mtime':
        path = paths['archive']; before = path.stat(); path.write_bytes(b'evil')
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif damage in paths: paths[damage].write_bytes(b'changed')
    elif damage == 'missing-positive': (attempt / 'guarded-success.json').unlink()
    elif damage == 'missing-prepared': (attempt / 'prepared.json').unlink()
    else:
        proof = json.loads((attempt / 'guarded-success.json').read_text())
        if damage == 'wrong-invocation': proof['invocation_id'] = '0'*32
        elif damage == 'guard-failure': proof['returncode'] = 1
        else: proof['root'] = [999,999]
        (attempt / 'guarded-success.json').write_text(json.dumps(proof))
    assert sample.run() == 1 and len(sample.calls) == 1
    assert not (sample.ctx.stamps / 'unreal.cook.json').exists()


def test_textual_uat_success_after_guard_failure_has_no_recoverable_completion(sample, monkeypatch):
    native = build.guarded.run
    def failed(*args, **kwargs):
        native(*args, **kwargs)
        kwargs['completion_path'].unlink()
        raise RuntimeError('aggregate memory guard did not finish')
    monkeypatch.setattr(build.guarded, 'run', failed)
    assert sample.run() == 1
    attempt = next((sample.ctx.out / 'cook-attempts').iterdir())
    assert not (attempt / 'completed.json').exists()
    sample.ctx.recover_cook = attempt.name
    assert sample.run() == 1 and len(sample.calls) == 1


@pytest.mark.parametrize('failure', [None, 'capacity-close', 'nonzero'])
def test_positive_guard_receipt_is_after_cleanup_and_never_published_on_failure(tmp_path, monkeypatch, failure):
    destination = tmp_path / 'completion.json'
    order = []
    def run(*args, _completion, **kwargs):
        assert not destination.exists()
        _completion.update(root=[123,456], monitors={'process':[1,2],'tree':[3,4]},
                           terminal=dict(owner=123, owner_started=456, state='child_exited', cleanup_complete=True))
        order.append('cleanup')
        if failure == 'capacity-close': raise RuntimeError('capacity close failed')
        return 1 if failure == 'nonzero' else 0
    monkeypatch.setattr(guarded, '_run', run)
    if failure == 'capacity-close':
        with pytest.raises(RuntimeError): guarded.run(['UAT'], tmp_path, kind='compile', completion_path=destination)
    else:
        assert guarded.run(['UAT'], tmp_path, kind='compile', completion_path=destination) == int(failure == 'nonzero')
    assert order == ['cleanup'] and destination.exists() is (failure is None)


@pytest.mark.parametrize('kind', ['journal', 'guard'])
def test_completion_publication_syncs_file_before_link_and_directory_before_return(tmp_path, monkeypatch, kind):
    events = []
    fsync, link = os.fsync, os.link
    def synced(descriptor):
        events.append('directory' if stat.S_ISDIR(os.fstat(descriptor).st_mode) else 'file')
        fsync(descriptor)
    def published(*args, **kwargs):
        events.append('publish')
        return link(*args, **kwargs)
    monkeypatch.setattr(os, 'fsync', synced)
    monkeypatch.setattr(os, 'link', published)
    destination = tmp_path / 'completion.json'
    if kind == 'journal':
        recovery.write(destination, {'completed': True})
    else:
        def completed(*args, _completion, **kwargs):
            _completion.update(root=[123, 456], terminal={'state': 'child_exited'})
            return 0
        monkeypatch.setattr(guarded, '_run', completed)
        assert guarded.run(['UAT'], tmp_path, kind='compile', completion_path=destination) == 0
    assert destination.is_file()
    assert events == ['file', 'publish', 'directory']


def test_default_cook_keeps_recording_opt_in(sample):
    sample.ctx.record_cook_recovery = False
    # A nonrecording native stub has no completion-path argument and cannot create a journal.
    def native(argv, folder, **kwargs):
        assert 'completion_path' not in kwargs and 'invocation_id' not in kwargs
        raise RuntimeError('stop before native work')
    from unittest.mock import patch
    with patch.object(build.guarded, 'run', native):
        assert sample.run() == 1
    assert not (sample.ctx.out / 'cook-attempts').exists()


def test_missing_ubt_defaults_refuse_recording_before_old_archive_is_removed(tmp_path, monkeypatch):
    cook = tool('package_cook')
    monkeypatch.setenv('UE_HEADLESS_USER_DIR', str(tmp_path / 'headless'))
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'home')
    ctx = SimpleNamespace(game_dir=tmp_path / 'game', unreal_root=tmp_path / 'engine',
                          out=tmp_path / 'build', record_cook_recovery=True)
    old = ctx.out / 'package/archive/retained.app'; old.mkdir(parents=True)
    (old / 'marker').write_bytes(b'old archive')
    with pytest.raises(RuntimeError, match='existing UBT default XML'):
        cook.prepare(ctx, io.StringIO())
    assert (old / 'marker').read_bytes() == b'old archive'
    installed = ctx.unreal_root / 'Engine/Build/InstalledBuild.txt'
    installed.parent.mkdir(parents=True); installed.write_text('installed')
    for config in (ctx.game_dir / 'unreal/Saved/UnrealBuildTool/BuildConfiguration.xml',
                   Path.home() / 'Library/Application Support/Unreal Engine/UnrealBuildTool/BuildConfiguration.xml'):
        config.parent.mkdir(parents=True); config.write_text('<Configuration/>')
    inputs = cook.recovery_config_inputs(ctx)
    assert ctx.game_dir / 'unreal/Saved/UnrealBuildTool/BuildConfiguration.xml' in inputs


@pytest.mark.parametrize('flags', [['--force'], ['--touch'], ['--plan'], ['--timings'], ['--max-heavy-commands','1'], ['--record-cook-recovery']])
def test_recovery_cli_refuses_combined_execution_modes(flags):
    from atelier.cli import main
    with pytest.raises(SystemExit, match='requires'):
        main(['build', 'yorimichi', 'unreal.cook', '--recover-cook', '0'*32, *flags])


def test_changed_inputs_after_certifier_removes_receipt_and_stamp(sample, monkeypatch):
    interrupted(sample, monkeypatch)
    certify = sample.step.cook_recovery.certify
    def changing(ctx, log):
        certify(ctx, log)
        sample.adapter.write_bytes(b'changed after certification')
    sample.step.cook_recovery = recovery.CookRecovery(sample.cook.source_snapshot, changing, lambda _: [sample.content,sample.adapter])
    assert sample.run() == 1
    assert not (sample.ctx.out / 'package/cook.json').exists()
    assert not (sample.ctx.stamps / 'unreal.cook.json').exists()


def test_real_product_graph_reads_and_references_are_part_of_prerequisite_proof(sample, monkeypatch):
    from atelier import build_products
    texture = sample.ctx.out / 'texture.bin'; texture.write_bytes(b'texture')
    metadata = sample.ctx.out / 'metadata.bin'; metadata.write_bytes(b'reference')
    world = sample.ctx.out / 'world.bin'; world.write_bytes(b'world')
    owner = build.Step('texture.source', [], products=[build.Product('texture', (texture,))])
    reference = build.Step('reference.source', [], products=[build.Product('reference', (metadata,))])
    consumer = build.Step('world.product', [], reads=['texture'], references=['reference'], outputs=[world])
    additional = [owner, reference, consumer]
    done = {}
    for step in build.order(additional, ['world.product']):
        stamp = dict(fingerprint=build.fingerprint(step, done))
        if step.products:
            stamp['products'] = build_products.records(step)
            build_products.feed_results(done, stamp['products'])
        done[step.name] = stamp['fingerprint']
        (sample.ctx.stamps / (step.name + '.json')).write_text(json.dumps(stamp))
    sample.steps[:0] = additional
    sample.step.needs.append(consumer.name)
    interrupted(sample, monkeypatch)
    assert sample.run() == 0 and len(sample.calls) == 1


def test_changed_source_during_uat_never_publishes_completed_proof_even_after_restore(sample, monkeypatch):
    native = build.guarded.run
    original = sample.source.read_bytes()
    def changed(*args, **kwargs):
        status = native(*args, **kwargs)
        sample.source.write_bytes(b'changed while UAT ran')
        return status
    monkeypatch.setattr(build.guarded, 'run', changed)
    assert sample.run() == 1
    attempt = next((sample.ctx.out / 'cook-attempts').iterdir())
    assert not (attempt / 'completed.json').exists()
    sample.source.write_bytes(original)
    sample.ctx.recover_cook = attempt.name
    assert sample.run() == 1 and len(sample.calls) == 1


def test_guarded_adapter_refuses_changed_request_without_exec_or_completed_proof(sample, monkeypatch):
    def refused(argv, folder, **kwargs):
        attempt = kwargs['completion_path'].parent
        request = json.loads((attempt / 'launch-request.json').read_text())
        request['source']['revision'] = 'b'*40
        (attempt / 'launch-request.json').write_text(json.dumps(request))
        recovery.prepare_exec(attempt)
        raise AssertionError('must not return from refused adapter')
    monkeypatch.setattr(build.guarded, 'run', refused)
    assert sample.run() == 1
    attempt = next((sample.ctx.out / 'cook-attempts').iterdir())
    assert not (attempt / 'prepared.json').exists() and not (attempt / 'completed.json').exists()


@pytest.mark.parametrize('state', ['memory_limit', 'test_duration'])
def test_disappeared_watched_child_stop_cannot_certify_uat_text_success(tmp_path, state):
    record = dict(pid=123, process_start=456, state=state)
    (tmp_path / 'memory-health-dotnet-123.json').write_text(json.dumps(record))
    tree = SimpleNamespace(folder=tmp_path, guarded={(123,456): ('dotnet', SimpleNamespace(poll=lambda: 0))})
    with pytest.raises(RuntimeError, match='stopped its child'): guarded.completion_watches(tree)


@pytest.mark.parametrize('failure', ['memory_limit', 'test_duration', 'nonzero', 'timeout'])
def test_watched_guard_must_settle_before_final_completion_evidence(tmp_path, failure):
    import subprocess
    report = tmp_path / 'memory-health-UnrealEditor-123.json'
    report.write_text(json.dumps(dict(pid=123, process_start=456, state='running')))
    def settled(timeout):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired('guard', timeout)
        if failure in ('memory_limit', 'test_duration'):
            # A guard can kill a watched helper, then finish writing only after UAT exits0.
            report.write_text(json.dumps(dict(pid=123, process_start=456, state=failure)))
        return 1 if failure == 'nonzero' else 0
    process = SimpleNamespace(wait=settled, poll=lambda: 0)
    tree = SimpleNamespace(folder=tmp_path, guarded={(123, 456): ('UnrealEditor', process)})
    root = SimpleNamespace(wait=lambda timeout: 0)
    with pytest.raises(RuntimeError, match='guard'):
        guarded.settle_completion_guards(root, tree)
        guarded.completion_watches(tree)


def test_first_input_inventory_runs_only_inside_guarded_adapter(sample, monkeypatch):
    snapshot = recovery.snapshot
    inside, events = [], []
    native = build.guarded.run
    def running(*args, **kwargs):
        inside.append(True)
        try: return native(*args, **kwargs)
        finally: inside.pop()
    def observed(*args, **kwargs):
        events.append(bool(inside))
        return snapshot(*args, **kwargs)
    monkeypatch.setattr(build.guarded, 'run', running)
    monkeypatch.setattr(recovery, 'snapshot', observed)
    assert sample.run() == 0
    assert events[0] is True and events[1:] == [False]


def test_declared_tool_owner_closes_cross_root_links_without_relaxing_archive_links(tmp_path):
    owner = tmp_path / 'Xcode'; tools = owner / 'Developer/usr'; tools.mkdir(parents=True)
    library = owner / 'Library'; library.mkdir(); binary = library / 'tool'; binary.write_bytes(b'tool')
    (tools / 'tool').symlink_to('../../Library/tool')
    with pytest.raises(RuntimeError, match='external'): recovery.inventory([tools], hashes=False)
    proof = recovery.inventory([tools], hashes=True, link_owners=[owner])
    assert any(value.get('sha256') == recovery.hashlib.sha256(b'tool').hexdigest() for value in proof.values())
    binary.write_bytes(b'changed')
    assert recovery.inventory([tools], hashes=True, link_owners=[owner]) != proof
    external = tmp_path / 'external'; external.write_bytes(b'outside owner')
    (tools / 'external').symlink_to(external)
    with pytest.raises(RuntimeError, match='external'): recovery.inventory([tools], hashes=True, link_owners=[owner])


def test_private_attempt_files_are_immutable_and_not_symlink_authority(tmp_path):
    path = tmp_path / 'journal.json'; recovery.write(path, {'first': True})
    with pytest.raises(FileExistsError): recovery.write(path, {'second': True})
    assert recovery.read(path) == {'first': True}
    link = tmp_path / 'link.json'; link.symlink_to(path)
    with pytest.raises(OSError): recovery.read(link)


def test_verified_restored_portable_product_is_valid_input_to_a_new_guarded_cook(sample, monkeypatch):
    from atelier import build_products
    product = sample.ctx.out / 'generated/data.json'; product.parent.mkdir(); product.write_text('{}')
    script = sample.ctx.out.parent / 'generate.py'; script.write_text('pass\n')
    owner = build.Step('portable.source', [build.Python(script)], products=[build.Product('portable.data', (product,))], cache=True)
    key = build.fingerprint(owner, {})
    (sample.ctx.stamps / (owner.name + '.json')).write_text(json.dumps(dict(
        fingerprint=key, restored_from=key, products=build_products.records(owner))))
    sample.steps.insert(0, owner); sample.step.needs.append(owner.name)
    interrupted(sample, monkeypatch)
    assert sample.run() == 0 and len(sample.calls) == 1
    product.write_text('{"changed":true}')
    assert sample.run() == 1 and len(sample.calls) == 1


@pytest.mark.parametrize('kind', ['touched', 'legacy-restored', 'native-unproven'])
def test_touched_or_unproven_native_prerequisite_cannot_create_recovery_proof(sample, kind):
    from atelier import build_products
    prerequisite = sample.steps[0]
    if kind == 'native-unproven':
        prerequisite.products = [build.Product('editor.native', (sample.prerequisite,))]
    stamp = dict(fingerprint=build.fingerprint(prerequisite, {}))
    if prerequisite.products: stamp['products'] = build_products.records(prerequisite)
    stamp['touched' if kind == 'touched' else 'restored_from'] = True
    (sample.ctx.stamps / (prerequisite.name + '.json')).write_text(json.dumps(stamp))
    assert sample.run() == 1
    attempt = next((sample.ctx.out / 'cook-attempts').iterdir())
    assert not (attempt / 'prepared.json').exists() and not (attempt / 'completed.json').exists()


@pytest.mark.parametrize('state', ['memory_limit', 'test_duration'])
def test_late_process_guard_stop_after_final_check_never_publishes_positive_receipt(tmp_path, monkeypatch, state):
    from contextlib import contextmanager
    from atelier import capacity_runtime
    monkeypatch.setattr(capacity_runtime, 'configured_session', lambda **kwargs: None)
    @contextmanager
    def admitted(*args, **kwargs):
        kwargs['on_slot']('big', ''); yield
    monkeypatch.setattr(guarded, 'render_lock', admitted)
    monkeypatch.setattr(guarded.process_tree, 'started', lambda pid: pid * 10)
    held = []
    child = SimpleNamespace(pid=123, returncode=0, poll=lambda: 0, wait=lambda timeout=None: 0)
    def spawn(*args, **kwargs):
        held.append(os.dup(kwargs['pass_fds'][0]))
        return child
    monkeypatch.setattr(guarded, 'spawn', spawn)
    monkeypatch.setattr(guarded, 'reap', lambda *args, **kwargs: None)
    monkeypatch.setattr(guarded, 'Descendants', lambda *args: SimpleNamespace(
        guarded={}, depth={}, shared_now=lambda: set(), unwind=lambda **kwargs: None, check=lambda: None))
    @contextmanager
    def memory(pid, report, **kwargs):
        Path(report).write_text(json.dumps(dict(pid=pid, process_start=pid*10, state='running')))
        yield SimpleNamespace(pid=200, poll=lambda: None, wait=lambda timeout: 0)
    @contextmanager
    def aggregate(pid, report, **kwargs):
        def finish():
            Path(report).write_text(json.dumps(dict(owner=pid, owner_started=pid*10, state='child_exited', cleanup_complete=True)))
        yield SimpleNamespace(process=SimpleNamespace(pid=300), report=report, ready=lambda: None,
                              finish=finish, receipt=lambda state: True)
    monkeypatch.setattr(guarded, 'attach_memory_guard', memory)
    monkeypatch.setattr(guarded, 'attach_tree', aggregate)
    monkeypatch.setattr(guarded, 'wait_ready', lambda *args: None)
    def late_stop(pid):
        # The actual final callback runs AFTER check_root_guard; emulate the atomic replacement
        # racing the later proof capture, with matching PID and birth identity.
        (tmp_path / 'memory-health.json').write_text(json.dumps(dict(pid=pid, process_start=pid*10, state=state)))
    try:
        with pytest.raises(RuntimeError, match='Completion process guard stopped'):
            guarded.run(['UAT'], tmp_path, kind='compile', on_poll=late_stop,
                        completion_path=tmp_path / 'positive.json')
    finally:
        for descriptor in held: os.close(descriptor)
    assert not (tmp_path / 'positive.json').exists()
