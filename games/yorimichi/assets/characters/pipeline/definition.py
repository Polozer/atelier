"""Character definitions: `assets/characters/<id>/character.toml`, read with the defaults a new Tripo humanoid needs.

Standard library only: the build, Blender, Unreal's Python and the tests all read it. A character that plays the
merged move set has an `adventure.toml` beside it; the steps, imports and runtime records of every such character
come from these two files (docs/PLAYABLE_CHARACTER.md).
"""
from pathlib import Path
import json
import re
import tomllib

CHARS = Path(__file__).resolve().parents[1]

# [export]: how the source becomes the game's body. The defaults are a Tripo model (Mixamo names, no authored clips).
EXPORT = {
    'names': 'mixamo',              # 'mixamo' (Tripo's auto-rig) or 'contract' (already the humanoid contract's names)
    'extra_bones': 'none',          # bones the contract has no name for: 'none', 'drop' (unweighted) or 'follow'
    'followers': {},                # {name prefix: count} the 'follow' bones must include (a hair rig, say)
    'meshes': None,                 # 'skinned', 'armature' or 'outfit'; default by source: .blend skinned, .glb armature
    'mesh_names': [{'property': 'body_region'}, {'name': 'Part{index}'}],
    'measure': None,                # 'evaluated', 'evaluated-faces' or 'raw'; default by source: .blend evaluated, .glb raw
    'measure_pose': None,           # an authored action whose first frame the height is measured in (default the rest pose)
    'actions': 'discard',           # 'discard', or 'authored': keep the source's clips (and its object transform)
    'strip_simulation': True,       # drop Blender cloth and collision modifiers: the cloth is Unreal's
    'morph_names': None,            # e.g. '{slot}_{key}': rename shape keys by mesh slot and key
    'fbx': {},                      # extra options for the body FBX (colors_type, ...)
    'clips': {},                    # {action: clip} exported beside the manifest's roles
}
MATERIALS = {
    'name': 'M_{mesh}',             # {asset} {mesh} {material} (its name in the source) {source} (that name, slugged)
    'texture': 'T_{mesh}',
    'format': 'detect',             # 'detect' keeps a packed JPEG a .jpg; 'png' names every texture .png
    'two_sided': False,             # true, false, 'backface' (the material's own setting) or a list of mesh names
    'roughness': 1.0,               # a number, or 'shader' for the source's own value
    'metallic': 0.0,
    'specular': 0.0,
    'require_texture': False,
    'atlas': None,                  # every texture this size, when set
}
# [unreal]: the body import (Scripts/import_character.py).
UNREAL = {
    'camera_height': 42.0,          # the camera's pivot above the capsule centre, cm
    'cpu_access': True,             # the skin readers (skating, grips) read the mesh on the CPU
    'physics_asset': True,          # false when skating fits its own physical rider
    'vertex_colors': False,         # import vertex colours (a cloth mask, say)
    'morph_targets': False,
    'contact_morphs': [],           # morph targets the skin readers must follow (USkinMorphContactData)
}


def asset_name(character):
    """The Unreal name: 'sword-trainer' -> 'SwordTrainer'."""
    return ''.join(word.title() for word in character.split('-'))


def slug(name):
    """Asset-safe name, as atelier.character.names.slug (kept here so Unreal's Python needs no platform import)."""
    return re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_')


class Character:
    """One character's definition: `toml` (character.toml), `adventure` (adventure.toml, or None) and the resolved
    `export`, `materials` and `unreal` tables. `exporter` is the character's own export script when character.toml
    names one (`export = "export_unreal.py"`), else None: the shared pipeline (export.py) exports it."""

    def __init__(self, character, chars=CHARS):
        self.id = character
        self.folder = chars / character
        self.toml = tomllib.loads((self.folder / 'character.toml').read_text())
        assert self.toml['id'] == character, (character, self.toml['id'])
        path = self.folder / 'adventure.toml'
        self.adventure = tomllib.loads(path.read_text()) if path.exists() else None
        self.name = self.toml.get('asset_name', asset_name(character))
        self.output = self.toml.get('output', character)   # build/<game>/<output>/
        self.source = self.folder / self.toml['source'] if 'source' in self.toml else None   # None: built procedurally
        self.height = self.toml['height_cm'] / 100 if 'height_cm' in self.toml else None
        self.fps = self.toml.get('fps', 30)
        export = self.toml.get('export', {})
        self.exporter = self.folder / export if isinstance(export, str) else None
        export = {} if self.exporter else export
        unknown = set(export) - set(EXPORT) - {'materials'}
        assert not unknown, (character, 'unknown [export] keys', sorted(unknown))
        self.export = {**EXPORT, **{k: v for k, v in export.items() if k != 'materials'}}
        blend = self.source is not None and self.source.suffix == '.blend'
        self.export['meshes'] = self.export['meshes'] or ('skinned' if blend else 'armature')
        self.export['measure'] = self.export['measure'] or ('evaluated' if blend else 'raw')
        assert set(export.get('materials', {})) <= set(MATERIALS), (character, 'unknown [export.materials] keys')
        self.materials = {**MATERIALS, **export.get('materials', {})}
        assert set(self.toml.get('unreal', {})) <= set(UNREAL), (character, 'unknown [unreal] keys')
        self.unreal = {**UNREAL, **self.toml.get('unreal', {})}
        self.unreal_path = self.toml.get('unreal_path', '/Game/' + self.name)

    @property
    def manifest(self):
        return json.loads((self.folder / self.toml.get('manifest', 'source-manifest.json')).read_text())

    @property
    def plays(self):
        """Whether it plays the merged move set (it has an adventure.toml)."""
        return self.adventure is not None

    @property
    def donor(self):
        """The [donor] table of the character whose own clips the merged set plays on everyone, or None."""
        return (self.adventure or {}).get('donor')


def ids(chars=CHARS):
    """Every character with a character.toml, by id."""
    return sorted(p.parent.name for p in chars.glob('*/character.toml'))


def movers(chars=CHARS):
    """Every character that plays the merged move set (has an adventure.toml), the donor first."""
    found = [Character(i, chars) for i in ids(chars) if (chars / i / 'adventure.toml').exists()]
    return sorted(found, key=lambda c: (c.donor is None, c.id))


def load(character, chars=CHARS):
    return Character(character, chars)
