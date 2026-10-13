"""Character definitions (assets/characters/<id>/character.toml, read by assets/characters/pipeline/definition.py): the
shared body export's settings for every character that plays the merged move set, and the names its build and imports
use."""
import importlib.util
from pathlib import Path

import pytest

CHARS = Path(__file__).resolve().parents[1] / 'assets' / 'characters'
spec = importlib.util.spec_from_file_location('character_definition', CHARS / 'pipeline' / 'definition.py')
definition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(definition)

# The names each mover's build steps, output folder and Unreal folder already use.
IDENTITIES = {
    'cairo': ('Cairo', 'cairo', '/Game/Cairo'),
    'modori': ('Modori', 'modori', '/Game/Modori'),
    'nox': ('Nox', 'nox', '/Game/Nox'),
    'sword-trainer': ('SwordTrainer', 'sword-trainer', '/Game/SwordTrainer'),
}


def test_every_definition_loads():
    for character in definition.ids():
        definition.load(character)


def test_the_movers_and_the_donor():
    movers = definition.movers()
    assert {c.id for c in movers} >= set(IDENTITIES)
    assert movers[0].donor and not any(c.donor for c in movers[1:]), 'one donor, first'


@pytest.mark.parametrize('character', sorted(IDENTITIES))
def test_identity(character):
    c = definition.load(character)
    assert (c.name, c.output, c.unreal_path) == IDENTITIES[character]


@pytest.mark.parametrize('character', [c.id for c in definition.movers()])
def test_a_mover_uses_the_shared_export(character):
    c = definition.load(character)
    assert c.exporter is None and not (c.folder / 'export_unreal.py').exists()
    assert c.source.exists() and c.height
    assert c.export['names'] in ('mixamo', 'contract')
    assert c.export['meshes'] in ('skinned', 'armature', 'outfit')
    assert c.export['measure'] in ('raw', 'evaluated', 'evaluated-faces')
    assert c.export['actions'] in ('discard', 'authored')
    assert c.export['mesh_names'], 'a mesh naming rule'
    hooks = c.folder / 'export_hooks.py'
    assert not hooks.exists() or 'def body(' in hooks.read_text()


def test_unknown_keys_are_refused(tmp_path):
    folder = tmp_path / 'someone'
    folder.mkdir()
    (folder / 'character.toml').write_text('id = "someone"\nsource = "Someone.glb"\nheight_cm = 170\n[export]\nname = "x"\n')
    with pytest.raises(AssertionError, match='unknown'):
        definition.load('someone', tmp_path)


@pytest.mark.parametrize('source, meshes, measure', [('New.glb', 'armature', 'raw'), ('New.blend', 'skinned', 'evaluated')])
def test_a_new_character_needs_only_its_source_and_height(tmp_path, source, meshes, measure):
    folder = tmp_path / 'new-one'
    folder.mkdir()
    (folder / 'character.toml').write_text(f'id = "new-one"\nsource = "{source}"\nheight_cm = 170\n')
    c = definition.load('new-one', tmp_path)
    assert (c.name, c.output, c.unreal_path, c.fps) == ('NewOne', 'new-one', '/Game/NewOne', 30)
    assert (c.export['meshes'], c.export['measure'], c.export['names'], c.export['actions']) == (meshes, measure, 'mixamo', 'discard')
