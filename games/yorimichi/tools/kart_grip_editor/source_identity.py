"""Portable identities for the prepared character model that an authored grip was inspected against."""
import hashlib
import json
from pathlib import Path
import tomllib

GAME = Path(__file__).resolve().parents[2]
ROOT = GAME.parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def playable_ids():
    return tuple(sorted(p.parent.name for p in (GAME / 'assets/characters').glob('*/character.toml')
                        if (p.parent / 'adventure.toml').is_file() and
                        tomllib.loads(p.read_text()).get('role', 'player') == 'player'))


def source_paths(character):
    folder = GAME / 'assets/characters' / character
    definition = tomllib.loads((folder / 'character.toml').read_text())
    paths = {folder / definition['source']}
    paths.update(p for p in folder.iterdir() if p.suffix in ('.toml', '.json', '.py') and p.is_file())
    paths.update((GAME / 'assets/characters/pipeline').rglob('*.py'))
    paths.update((ROOT / 'platform/studio/atelier/character').rglob('*.py'))
    paths.update((ROOT / 'platform/conventions/rigs').glob('*.toml'))
    return tuple(p for p in sorted(paths) if '__pycache__' not in p.parts)


def source_identity(character):
    return digest({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in source_paths(character)})


def register(models, profiles):
    """@cc [owner:fontanierh,label:correctness] kart-prepared-model-identity
    A registered grip MUST identify the inspected model bytes and bind frames, with an
    independently verified current character-source identity. Production validation MUST
    reject stale receipts and MUST NOT derive its expected identity from the pose itself.
    """
    receipt = {}
    for path in sorted(profiles.glob('*.json')):
        if path.name == 'prepared-models.json':
            continue
        pose = json.loads(path.read_text())
        name = pose['character']
        meta = json.loads((models / f'{name}.json').read_text())
        checksum = hashlib.sha256((models / f'{name}.glb').read_bytes()).hexdigest()
        if checksum != meta['model_sha256'] or checksum != pose['model_sha256']:
            raise ValueError(f'{name}: re-author against the current prepared model')
        current = source_identity(name)
        if meta.get('source_sha256') != current:
            raise ValueError(f'{name}: re-export the prepared model after its sources changed')
        bind = digest(meta['bind_world'])
        if digest(pose['bind_world']) != bind:
            raise ValueError(f'{name}: saved bind does not match the prepared model')
        receipt[name] = {'model_sha256': checksum, 'bind_sha256': bind, 'source_sha256': current,
                         'scale': meta['scale'], 'seated_world': {n: meta['seated_world'][n]
                         for n in ('pelvis', 'upperarm_L', 'upperarm_R')}}
    temporary = profiles / '.prepared-models.tmp'
    temporary.write_text(json.dumps({'schema': 1, 'models': receipt}, indent=2)+'\n')
    temporary.replace(profiles / 'prepared-models.json')
    return receipt


if __name__ == '__main__':
    print('Registered', ', '.join(register(ROOT / 'build/yorimichi/kart-grip-editor',
                                         GAME / 'assets/vehicles/kart/grips')))
