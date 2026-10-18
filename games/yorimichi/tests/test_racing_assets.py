"""The racing service's runtime assets (tools/racing_assets.py, docs/RACING.md "Horses"): validated before the cook."""
import importlib.util
import inspect
import json
import re
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
SOURCE = GAME / 'unreal' / 'Source' / 'Yorimichi' / 'RacingService.cpp'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


racing_assets = _load('racing_assets_under_test', GAME / 'tools' / 'racing_assets.py')


def _cpp_list(text, name):
    body = re.search(rf'{name}\[\] = \{{(.*?)\}};', text, re.S).group(1)
    return tuple(re.findall(r'TEXT\("([^"]*)"\)', body))


def test_lists_mirror_the_service():
    text = SOURCE.read_text()
    assert _cpp_list(text, 'Breeds') == racing_assets.BREEDS
    assert _cpp_list(text, 'HorseClips') == racing_assets.HORSE_CLIPS
    assert _cpp_list(text, 'RiderClips') == racing_assets.RIDER_CLIPS
    assert _cpp_list(text, 'Coats') == ('', *racing_assets.COATS)


def _roster():
    breeds = {}
    for slug in racing_assets.BREEDS:
        name = slug.capitalize()
        breeds[slug] = {
            'mesh': f'/Game/Horses/{name}/SK_Horse_{name}.SK_Horse_{name}',
            'contacts': {'saddle_root': [0.04, 0., 1.6], 'seat_z': 1.43},
            'clips': {clip: {'path': f'/Game/Horses/{name}/A_{clip}.A_{clip}'} for clip in racing_assets.HORSE_CLIPS},
            'saddles': {'00': f'/Game/Horses/{name}/Tack/SK_Saddle.SK_Saddle'},
        }
    coats = [{'id': coat, 'texture': f'/Game/Horses/Coats/Variants/{coat}.{coat}'} for coat in racing_assets.COATS]
    return {'reference_breed': 'arabian', 'breeds': breeds, 'tack_sets': ['00', '01'], 'coat_variants': coats}


def _content(tmp_path, roster, rig):
    content = tmp_path / 'Content'
    paths, problems = racing_assets.required_paths(roster, rig)
    assert problems == []
    for path in paths:
        file = racing_assets.asset_file(content, path)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b'uasset')
    return content


INI = '+DirectoriesToAlwaysCook=(Path="/Game/Horses")\n+DirectoriesToAlwaysCook=(Path="/Game/CairoHorse")\n'


def test_a_complete_roster_passes(tmp_path):
    roster = _roster()
    content = _content(tmp_path, roster, 'Cairo')
    assert racing_assets.problems(roster, content, INI, 'Cairo') == []


def test_missing_breed_coat_clip_and_jockey_fail_loudly(tmp_path):
    roster = _roster()
    content = _content(tmp_path, roster, 'Cairo')
    broken = json.loads(json.dumps(roster))
    del broken['breeds']['friesian']
    del broken['breeds']['arabian']['clips']['Sprint']
    broken['coat_variants'] = [c for c in broken['coat_variants'] if c['id'] != 'kestrel-leopard']
    found = racing_assets.problems(broken, content, INI, 'Cairo')
    assert 'breed friesian is missing from the roster' in found
    assert 'breed arabian has no Sprint clip' in found
    assert 'coat kestrel-leopard has no texture in the roster' in found
    (content / 'CairoHorse' / 'A_HorseGallop.uasset').unlink()
    assert any('A_HorseGallop' in p and 'is missing' in p for p in racing_assets.problems(roster, content, INI, 'Cairo'))


def test_assets_outside_the_cook_fail(tmp_path):
    roster = _roster()
    content = _content(tmp_path, roster, 'Cairo')
    found = racing_assets.problems(roster, content, '+DirectoriesToAlwaysCook=(Path="/Game/Horses")\n', 'Cairo')
    assert found and all('/Game/CairoHorse/' in p and 'always cooks' in p for p in found)


def test_the_game_cooks_the_racing_folders_and_checks_them_before_the_cook(tmp_path):
    build = _load('yorimichi_build_racing_assets', GAME / 'build.py')
    rig = racing_assets.default_rig(build.definition)
    cooked = racing_assets.always_cooked(racing_assets.CONFIG.read_text())
    assert '/Game/Horses' in cooked and f'/Game/{rig}Horse' in cooked
    step = build.racing_assets_step(tmp_path)
    assert 'unreal.horses' in step.needs and any(n.endswith('_horse') and n.startswith('unreal.') for n in step.needs)
    assert "'data.racing_assets'" in inspect.getsource(build.cook_step)
