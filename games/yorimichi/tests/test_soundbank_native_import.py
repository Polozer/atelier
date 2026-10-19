"""The NumPy-free editor boundary rejects changed bytes/mapping before mutation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from atelier import build, build_products
from test_soundbank_import_plan import planned, planner  # noqa: F401 (shared real producer fixture)
from test_soundbank_previews import inputs  # noqa: F401
from test_soundbank_sources import source  # noqa: F401

GAME = Path(__file__).resolve().parents[1]
SCRIPTS = GAME / 'unreal/Scripts'
spec = importlib.util.spec_from_file_location('soundbank_package_data', SCRIPTS / 'soundbank_package_data.py')
consumer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(consumer)


def test_actual_complete_plan_passes_editor_preflight_without_importing_numpy(planned):
    out, source, _, _ = planned
    expected = planner.build(out, source)
    assert consumer.preflight(out, source) == expected
    # Isolated Python has neither this venv's third-party libraries nor Atelier.
    code = ('import sys; sys.path.insert(0, sys.argv[1]); import soundbank_package_data as data; '
            'data.preflight(sys.argv[2], sys.argv[3]); assert "numpy" not in sys.modules')
    subprocess.run([sys.executable, '-I', '-S', '-c', code, str(SCRIPTS), str(out), str(source)], check=True, timeout=10)


@pytest.mark.parametrize('failure', ['source_bytes', 'unused_surface_mapping', 'escape', 'original_replacement', 'producer'])
def test_changed_inputs_fail_editor_admission(planned, failure):
    out, source, _, _ = planned
    plan = planner.build(out, source)
    row = plan['banks'][1]
    if failure == 'source_bytes':
        wav = next(w for w in row['waves'] if w['name'] in row['footsteps']['leaves'])
        path = out / wav['path']
        payload = bytearray(path.read_bytes())
        payload[-1] ^= 1
        path.write_bytes(payload)
    elif failure == 'unused_surface_mapping':
        row['footsteps']['leaves'] = row['footsteps']['stone']
    elif failure == 'escape':
        row['waves'][0]['path'] = '../escape.wav'
    elif failure == 'original_replacement':
        plan['banks'][0]['runtime']['asset'] = '/Game/Audio/Original.Original'
    else:
        plan['producer_sha256'] = '0' * 64
    (out / 'audio/soundbank_import_plan/manifest.json').write_text(json.dumps(plan))
    with pytest.raises(ValueError):
        consumer.preflight(out, source)
    assert not (out / 'soundbank_import').exists()


def test_import_and_cold_reload_are_normal_owned_products_without_world_rebuild(tmp_path):
    recipe = build.load_recipe('yorimichi')
    graph = build_products.Graph(recipe.steps(SimpleNamespace(game='yorimichi', out=tmp_path, uproject=None)))
    step = graph.by_name['unreal.soundbanks']
    assert len(step.commands) == 2
    assert [command.script.name for command in step.commands] == ['import_soundbanks.py', 'verify_soundbanks.py']
    assert all(command.timeout == 600 and command.null_rhi
               and set(command.modules) == {'YorimichiAssets', 'AtelierSkate'} for command in step.commands)
    selected = {s.name for s in graph.select([step.name])}
    assert not any(n.startswith(('world.', 'characters.')) for n in selected)
    assert {'audio.soundbanks', 'audio.soundbank_import_plan', 'audio.soundbank_previews', 'unreal.compile'} <= selected
    assert 'soundbanks.native' in graph.by_name['data.soundbanks'].reads
    assert 'soundbanks.staged' in graph.by_name['data.stage'].reads
    staged = {s.name for s in graph.select(['data.soundbanks'])}
    assert selected | {'data.soundbanks'} == staged


def test_registry_stage_path_and_cook_ownership(tmp_path):
    spec = importlib.util.spec_from_file_location('soundbank_runtime_data', GAME / 'runtime_data.py')
    stage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    assert 'Soundbanks/registry.json' not in stage.staged(tmp_path)
    assert '+DirectoriesToAlwaysCook=(Path="/Game/AudioBanks")' in (GAME / 'unreal/Config/DefaultGame.ini').read_text()


def test_cleanup_handles_unreal_false_after_registry_deletion(tmp_path):
    content = tmp_path / 'Content'
    wave = content / 'AudioBanks/original/Audition.uasset'
    wave.parent.mkdir(parents=True)
    wave.write_bytes(b'old owned package')
    untouched = content / 'Audio/Original.uasset'
    untouched.parent.mkdir()
    untouched.write_bytes(b'legacy cue')
    editor = SimpleNamespace(does_directory_exist=lambda _: True, delete_directory=lambda _: False,
                             list_assets=lambda *a, **k: [])
    consumer.clear_packages(content, editor)
    assert not (content / 'AudioBanks').exists()
    assert untouched.read_bytes() == b'legacy cue'


@pytest.mark.parametrize('failure', ['registered', 'unknown_file', 'symlink'])
def test_cleanup_refuses_uncleared_or_unowned_files(tmp_path, failure):
    content = tmp_path / 'Content'
    wave = content / 'AudioBanks/original/Audition.uasset'
    wave.parent.mkdir(parents=True)
    wave.write_bytes(b'old owned package')
    calls = []
    editor = SimpleNamespace(does_directory_exist=lambda _: True,
                             delete_directory=lambda _: calls.append('delete') or False,
                             list_assets=lambda *a, **k: ['/Game/AudioBanks/original/Audition'])
    if failure == 'unknown_file':
        (wave.parent / 'keep.txt').write_text('unexpected')
    elif failure == 'symlink':
        (wave.parent / 'linked.uasset').symlink_to(wave)
    with pytest.raises(ValueError):
        consumer.clear_packages(content, editor)
    assert wave.read_bytes() == b'old owned package'
    assert calls == (['delete'] if failure == 'registered' else [])
