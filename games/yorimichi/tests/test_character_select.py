"""Verify the Sunburst character selection screen concept, character portraits, staging, and C++ wiring."""
import hashlib
import importlib.util
import json
from pathlib import Path
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
GAME = REPO / 'games' / 'yorimichi'
ASSETS = GAME / 'assets'
CHARS = ASSETS / 'characters'
CONCEPTS = CHARS / 'concepts'
SOURCE = GAME / 'unreal' / 'Source' / 'Yorimichi'

_def_spec = importlib.util.spec_from_file_location('character_definition', CHARS / 'pipeline' / 'definition.py')
definition = importlib.util.module_from_spec(_def_spec)
_def_spec.loader.exec_module(definition)

_rt_spec = importlib.util.spec_from_file_location('yorimichi_runtime_data', GAME / 'runtime_data.py')
runtime_data = importlib.util.module_from_spec(_rt_spec)
_rt_spec.loader.exec_module(runtime_data)

_cp_spec = importlib.util.spec_from_file_location('yorimichi_content_policy', GAME / 'content_policy.py')
content_policy = importlib.util.module_from_spec(_cp_spec)
_cp_spec.loader.exec_module(content_policy)


def test_sunburst_character_select_concept_and_provenance():
    jpg = CONCEPTS / 'character-select.jpg'
    prov = CONCEPTS / 'character-select.provenance.json'
    prompt = CONCEPTS / 'character-select.prompt.txt'
    assert jpg.is_file() and prov.is_file() and prompt.is_file()
    data = json.loads(prov.read_text())
    assert data['requested_model'] == 'gpt-image-2.5-sunburst'
    assert data['quality'] == 'high'
    assert data['status'] == 'done'
    assert data['compact_copy']['file'] == jpg.name
    assert data['compact_copy']['sha256'] == hashlib.sha256(jpg.read_bytes()).hexdigest()


def test_playable_character_portraits_and_staging():
    playable = [c for c in definition.movers() if c.playable]
    assert [c.id for c in playable] == ['cairo', 'modori', 'nox', 'paul']
    for char in playable:
        png = CHARS / 'portraits' / f'{char.id}.png'
        prov = CHARS / 'portraits' / f'{char.id}.provenance.json'
        prompt = CHARS / 'portraits' / f'{char.id}.prompt.txt'
        assert png.is_file() and prov.is_file() and prompt.is_file()
        im = Image.open(png)
        assert im.size == (440, 520)
        data = json.loads(prov.read_text())
        assert data['requested_model'] == 'gpt-image-2.5-sunburst'
        assert data['quality'] == 'high'
        assert data['status'] == 'done'
        assert data['portrait']['sha256'] == hashlib.sha256(png.read_bytes()).hexdigest()
        rel = f'{char.id}/portrait.png'
        assert rel in runtime_data.STAGED
        assert runtime_data.staged_source(Path('/tmp/out'), rel) == png
        assert 'portrait.png' in content_policy.CHARACTER_DATA[char.id]


def test_character_select_cpp_and_release_launcher_wired():
    header = (SOURCE / 'JapanCharacterSelect.h').read_text()
    impl = (SOURCE / 'JapanCharacterSelect.cpp').read_text()
    wanderer = (SOURCE / 'WandererCharacter.cpp').read_text()
    hud = (SOURCE / 'JapanHUD.cpp').read_text()
    live = (SOURCE / 'YorimichiLive.cpp').read_text()
    assert 'struct YORIMICHI_API FJapanCharacterSelect' in header
    assert 'PortraitBrush(const FString& CharacterId)' in impl
    assert 'Knows every shortcut.' in impl
    assert 'Came back from the woods.' in impl
    assert 'Up all night.' in impl
    assert 'New in town.' in impl
    assert 'FJapanCharacterSelect::ShouldOpenAtStartup' in wanderer
    assert '!IsNpc() && Cast<APlayerController>(Controller)' in wanderer
    assert 'FJapanCharacterSelect::Close(this)' in wanderer
    assert 'FApp::IsUnattended()' in impl
    assert 'bStartupShownInProcess' in impl
    assert 'if (FJapanCharacterSelect::IsOpen()) return;' in hud
    assert 'UYorimichiLive::CharacterSelectState()' in live

