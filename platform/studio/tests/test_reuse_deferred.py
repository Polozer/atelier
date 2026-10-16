"""Reuse of a step whose deferred input membership is read from generated files the receiver lacks until copied."""
import json
import shutil

import pytest

from atelier import paths, reuse


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    source, target, engine = (tmp_path / name for name in ('source', 'target', 'engine'))
    shutil.copytree(paths.STUDIO / 'atelier', source / 'platform/studio/atelier',
                    ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(paths.HARNESS / 'harness', source / 'platform/harness/harness',
                    ignore=shutil.ignore_patterns('__pycache__'))
    game = source / 'games/standin'
    write(game / 'game.toml', 'editor_target = "StandinEditor"\n')
    write(game / 'unreal/Standin.uproject', '{}')
    write(game / 'listed.txt', 'listed source')
    write(game / 'build.py', '''import json
from pathlib import Path
from atelier.build import Step
from atelier.build_deferred import DeferredInputs
def listed(out, game):
    """The generated identity names the real sources; extra/ holds sources found by listing."""
    identity = Path(out) / 'identity.json'
    names = json.loads(identity.read_text())['sources'] if identity.is_file() else []
    return [identity, *(Path(game) / name for name in names), *sorted((Path(game) / 'extra').glob('*.txt'))]
def steps(ctx):
    return [Step('digest', [], deferred_inputs=[DeferredInputs('identity', listed, (ctx.out, Path(__file__).parent),
                                                               support=(Path(__file__),))],
                 outputs=[ctx.out / 'digest.json'])]
''')
    shutil.copytree(source, target)
    write(engine / 'Engine/Build/Build.version', '{}')
    write(engine / 'Engine/Binaries/Mac/UnrealEditor.modules', '{"BuildId":"same"}')
    monkeypatch.setenv('UE_ROOT', str(engine))
    monkeypatch.delenv('ATELIER_BUILD_ROOT', raising=False)
    monkeypatch.setattr(reuse, 'git', lambda repo, *args: 'revision' if args[0] == 'rev-parse' else '')
    monkeypatch.setattr(reuse, 'occupied', lambda *args: [])
    for name, content in [('libUnrealEditor-Standin.dylib', 'module'), ('StandinEditor.target', '{"Version":{}}'),
                          ('UnrealEditor.modules', '{"BuildId":"same"}')]:
        write(game / 'unreal/Binaries/Mac' / name, content)
    write(source / 'build/standin/identity.json', json.dumps({'sources': ['listed.txt']}))
    write(source / 'build/standin/digest.json', 'digest')
    for step in reuse.inspect(source, 'standin')['steps']:
        write(source / 'build/standin/stamps' / (step['name'] + '.json'), json.dumps({'fingerprint': step['fingerprint']}))
    return source, target


def copy(source, target):
    return reuse._copy('standin', source, target, operation_id='0' * 32)


def test_fresh_receiver_compares_its_own_bytes_at_the_donors_generated_membership(snapshot):
    source, target = snapshot
    before = reuse.inspect(source, 'standin')
    assert reuse.differing_sources(before, reuse.inspect(target, 'standin')) == ['digest']   # the collector sees no identity
    assert reuse.differing_sources(before, reuse.inspect(target, 'standin', reuse.deferred_memberships(before))) == []
    assert copy(source, target) == 0
    reuse._publish('standin', target, '0' * 32)
    stamp = json.loads((target / 'build/standin/stamps/digest.json').read_text())
    assert stamp['fingerprint'] == next(s['fingerprint'] for s in reuse.inspect(target, 'standin')['steps'])


@pytest.mark.parametrize('change', ['changed_source', 'missing_source', 'receiver_only_source'])
def test_real_source_differences_outside_the_copy_still_refuse_before_copying(snapshot, change):
    source, target = snapshot
    if change == 'changed_source':
        write(target / 'games/standin/listed.txt', 'different source')
    elif change == 'missing_source':
        (target / 'games/standin/listed.txt').unlink()
    else:                                   # a deferred read the donor never observed, outside the copied roots
        write(target / 'games/standin/extra/new.txt', 'receiver only')
    with pytest.raises(ValueError, match='Source inputs differ'):
        copy(source, target)
    assert not (target / 'build/standin/identity.json').exists()
    assert not (target / 'build/standin/stamps').exists()


def test_donor_membership_never_names_a_path_the_receiver_would_copy(snapshot):
    source, target = snapshot
    before = reuse.inspect(source, 'standin')
    known = reuse.deferred_memberships(before)
    assert known['digest']['paths'] and all('<build>' not in p for p in known['digest']['paths'])
    poisoned = {'digest': dict(known['digest'], paths=[*known['digest']['paths'], '<build>/identity.json'])}
    assert reuse.differing_sources(before, reuse.inspect(target, 'standin', poisoned)) == ['digest']


def test_receiver_input_changed_after_copying_refuses_before_publication(snapshot, monkeypatch):
    source, target = snapshot
    real = reuse.copy_tree
    def copy_then_edit(item, destination, *args):
        real(item, destination, *args)
        write(target / 'games/standin/listed.txt', 'edited while copying')
    monkeypatch.setattr(reuse, 'copy_tree', copy_then_edit)
    with pytest.raises(ValueError, match='after copying|changed during copying'):
        copy(source, target)
    assert not (target / 'build/standin/stamps').exists()
