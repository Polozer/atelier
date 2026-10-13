"""Make a playable character's pawn, BP_<Name>, and register it with the game.

    CHARACTER=paul UnrealEditor-Cmd Yorimichi.uproject -run=pythonscript -script=Scripts/character_pawn.py -unattended -nosplash -NullRHI -stdout

BP_<Name>, in the character's unreal_path, is a Blueprint of AMoverCharacter (Source/Yorimichi/MoverCharacter.h) holding
character.toml's [game] table (assets/characters/pipeline/definition.py GAME): its names, merged move set, bike rig and
skating, sailboat, cloth, hair and seat values on the class defaults, and its capsule, crouch and mesh offset on the
inherited component templates, where a crouch restores them from. Each value is read back after the package reloads.

Content/Data/<id>/character.json is written last, once the Blueprint and the move record (adventure.json) are saved:
FPlayableCharacter::Scan (CharacterRoster.cpp) registers the character from it at startup or on
yorimichi.RescanCharacters, so -rider=, the character switch and shared games know it.
"""
import json
import os
import sys
from pathlib import Path

import unreal as U

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'assets' / 'characters' / 'pipeline'))
import definition  # noqa: E402

CHARACTER = definition.load(os.environ['CHARACTER'])
assert CHARACTER.playable and CHARACTER.plays, (CHARACTER.id, 'a pawn is for a playable mover')
GAME = CHARACTER.game
NAME = CHARACTER.name
BLUEPRINT = f'{CHARACTER.unreal_path}/BP_{NAME}'
CONTENT = Path(__file__).resolve().parents[1] / 'Content'
DATA = CONTENT / 'Data' / CHARACTER.id
SOLE = 0.65   # the export puts the soles this far under the floor (pipeline/rig.py)


def object_path(package):
    return f"{package}.{package.rsplit('/', 1)[1]}"


DEFINITION = object_path(CHARACTER.adventure['definition'])
assert U.EditorAssetLibrary.does_asset_exist(CHARACTER.adventure['definition']), (DEFINITION, 'no merged move set')
assert (DATA / 'adventure.json').exists(), (DATA / 'adventure.json', 'no move record')

cloth = GAME['cloth_teleport'] or [0.0, 0.0]
DEFAULTS = {
    'character_id': CHARACTER.id,
    'display_name': CHARACTER.toml['display_name'],
    'definition': DEFINITION,
    'bike_rig': GAME['bike_rig'],
    'skate_clothing_clearance': float(GAME['skate_clothing_clearance']),
    'skate_collision_hull_directions': int(GAME['skate_hull_directions']),
    'leg_scaled_sailboat': bool(GAME['leg_scaled_sailboat']),
    'cloth_teleport_distance': float(cloth[0]),
    'cloth_teleport_rotation': float(cloth[1]),
    'hair_spring_morphs': [str(m) for m in GAME['hair_spring_morphs']],
    'seat_corrective_prefix': GAME['seat_correctives'],
}
assert len(DEFAULTS['hair_spring_morphs']) in (0, 2), (CHARACTER.id, 'hair_spring_morphs is [forward, sideways]')
HALF = float(GAME['half_height'])
COMPONENTS = {
    'capsule_component': {'capsule_radius': float(GAME['capsule_radius']), 'capsule_half_height': HALF},
    'character_movement': {'crouched_half_height': float(GAME['crouched_half_height'])},
    'mesh': {'relative_location': U.Vector(0.0, 0.0, -(HALF + SOLE))},
}


def blueprint():
    """BP_<Name>, made once and kept: the same asset, its values set again on every build."""
    parent = U.MoverCharacter.static_class()
    if U.EditorAssetLibrary.does_asset_exist(BLUEPRINT):
        bp = U.load_asset(BLUEPRINT)
        assert isinstance(U.get_default_object(U.BlueprintEditorLibrary.generated_class(bp)), U.MoverCharacter), \
            (BLUEPRINT, 'not a MoverCharacter')
        return bp
    factory = U.BlueprintFactory()
    factory.set_editor_property('parent_class', parent)
    path, name = BLUEPRINT.rsplit('/', 1)
    bp = U.AssetToolsHelpers.get_asset_tools().create_asset(name, path, U.Blueprint, factory)
    assert bp, (BLUEPRINT, 'not created')
    return bp


def apply(cdo):
    for key, value in DEFAULTS.items():
        cdo.set_editor_property(key, value)
    for component, values in COMPONENTS.items():
        template = cdo.get_editor_property(component)
        for key, value in values.items():
            template.set_editor_property(key, value)


def same(a, b):
    if isinstance(b, U.Vector):
        return abs(a.x - b.x) + abs(a.y - b.y) + abs(a.z - b.z) < 1e-4
    if isinstance(b, float):
        return abs(a - b) < 1e-4
    if isinstance(b, list):
        return [str(x) for x in a] == b
    return a == b


def check(cdo):
    wrong = [(k, cdo.get_editor_property(k), v) for k, v in DEFAULTS.items() if not same(cdo.get_editor_property(k), v)]
    for component, values in COMPONENTS.items():
        template = cdo.get_editor_property(component)
        wrong += [(f'{component}.{k}', template.get_editor_property(k), v) for k, v in values.items()
                  if not same(template.get_editor_property(k), v)]
    assert not wrong, (BLUEPRINT, 'class defaults differ from [game]', wrong)


bp = blueprint()
U.BlueprintEditorLibrary.compile_blueprint(bp)
apply(U.get_default_object(U.BlueprintEditorLibrary.generated_class(bp)))
bp.modify()
U.BlueprintEditorLibrary.compile_blueprint(bp)
assert U.EditorAssetLibrary.save_asset(BLUEPRINT, only_if_is_dirty=False), (BLUEPRINT, 'not saved')
# What was saved, not what this session holds: reload the package and read every value back.
U.EditorLoadingAndSavingUtils.reload_packages([U.find_package(BLUEPRINT)])
bp = U.load_asset(BLUEPRINT)
generated = U.BlueprintEditorLibrary.generated_class(bp)
check(U.get_default_object(generated))
assert generated.get_path_name() == CHARACTER.pawn, (generated.get_path_name(), CHARACTER.pawn)   # as the tools name it

record = {
    'name': CHARACTER.toml['display_name'],
    'id': CHARACTER.id,
    'class': generated.get_path_name(),
    'definition': DEFINITION,
    'build_step': f"unreal.{CHARACTER.id.replace('-', '_')}_pawn",
    'default': bool(GAME['default']),
    'aliases': list(GAME['aliases']),
}
DATA.mkdir(parents=True, exist_ok=True)
temporary = DATA / 'character.json.partial'
temporary.write_text(json.dumps(record, indent=1) + '\n')
os.replace(temporary, DATA / 'character.json')   # whole or absent: a running game may scan at any moment
print(f'CHARACTER PAWN COMPLETE: {CHARACTER.id} {record["class"]}')
