"""Validate all authored source grips before the native import publishes matching cockpit assets."""
import argparse
import json
from pathlib import Path

from grip_data import bone_names, neutral_reach
from server import validate
from source_identity import digest, playable_ids, source_identity


def validate_profile(pose, layout, prepared=None):
    character = pose.get('character')
    checksum = pose.get('model_sha256', '')
    if pose.get('layout') != layout or len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
        raise ValueError(f'{character}: stale cockpit or invalid prepared model checksum')
    if prepared is not None and digest(pose.get('bind_world')) != prepared.get('bind_sha256'):
        raise ValueError(f'{character}: grip differs from the registered prepared bind')
    scale = pose.get('scale', 0)
    if not isinstance(scale, (int, float)) or not layout['scale_range'][0] <= scale <= layout['scale_range'][1]:
        raise ValueError(f'{character}: unsupported kart scale')
    parents = {}
    for side in 'LR':
        names = bone_names(side)
        for index, name in enumerate(names):
            parents[name] = None if index == 0 else f'hand_{side}' if (index-1) % 3 == 0 else names[index-1]
    meta = {'id': character, 'model_sha256': checksum, 'scale': scale, 'layout': layout,
            'bind_world': pose['bind_world'], 'parents': parents}
    validate(pose, meta)
    if prepared is not None:
        if abs(pose['scale']-prepared['scale']) > 1e-5:
            raise ValueError(f'{character}: prepared scale changed')
        replay = dict(meta, seated_world=prepared['seated_world'])
        misses = neutral_reach(pose, replay)
        if max(misses.values()) > .01:
            raise ValueError(f'{character}: arm reach exceeded by {max(misses.values())*1000:.0f} mm')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layout', type=Path, required=True)
    args = parser.parse_args()
    layout = json.loads(args.layout.read_text())
    source = Path(__file__).resolve().parents[2] / 'assets/vehicles/kart/grips'
    receipt = json.loads((source / 'prepared-models.json').read_text())
    if receipt.get('schema') != 1:
        raise ValueError('Invalid prepared-model receipt')
    for name in playable_ids():
        path = source / f'{name}.json'
        if not path.is_file():
            raise ValueError(f'Save the {name} grip in the kart grip editor before importing the kart')
        pose = json.loads(path.read_text())
        if pose.get('character') != name:
            raise ValueError(f'Wrong character in {path.name}')
        prepared = receipt['models'].get(name, {})
        if prepared.get('source_sha256') != source_identity(name):
            raise ValueError(f'{name}: character sources changed; prepare and review the grip again')
        validate_profile(pose, layout, prepared)
        print(f'KART GRIP VALIDATED {name}', flush=True)


if __name__ == '__main__':
    main()
