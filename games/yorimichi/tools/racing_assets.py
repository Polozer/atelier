"""Validate the assets the racing service loads at runtime (docs/RACING.md, "Horses"), before multiplayer identity and cooking.

ARacingService loads its runners by path, so nothing references them for the cooker and a missing one would only show at
runtime. This check fails the build instead: every racing breed has its mesh, its six gait clips, the first tack set's
saddle and its seat contacts in the staged roster; every coat the service names has a texture; the default character has
its six horseback clips; each of these assets exists in Content and lies in a folder DefaultGame.ini always cooks.

The breed, coat and clip lists mirror RacingService.cpp's RacingLooks (tests/test_racing_assets.py keeps them in step).
"""
import json
import re
from pathlib import Path

GAME = Path(__file__).resolve().parents[1]
CONTENT = GAME / 'unreal' / 'Content'
ROSTER = CONTENT / 'Data' / 'horses' / 'roster.json'
CONFIG = GAME / 'unreal' / 'Config' / 'DefaultGame.ini'

BREEDS = ('thoroughbred', 'friesian', 'andalusian', 'arabian')
HORSE_CLIPS = ('Idle', 'Walk', 'Trot', 'Canter', 'Gallop', 'Sprint')
RIDER_CLIPS = ('HorseIdle', 'HorseWalk', 'HorseTrot', 'HorseCanter', 'HorseGallop', 'HorseSprint')
COATS = ('kestrel-bay', 'kestrel-seal-brown', 'kestrel-black', 'kestrel-chestnut', 'kestrel-sorrel', 'kestrel-palomino',
         'kestrel-buckskin', 'kestrel-perlino', 'kestrel-blue-roan', 'kestrel-red-roan', 'kestrel-dapple-grey',
         'kestrel-silver-dun', 'kestrel-bay-tobiano', 'kestrel-chestnut-overo', 'kestrel-leopard', 'kestrel-blanket')


def always_cooked(ini_text):
    """The /Game folders DefaultGame.ini always cooks."""
    return re.findall(r'^\+DirectoriesToAlwaysCook=\(Path="([^"]+)"\)', ini_text, re.MULTILINE)


def asset_file(content, path):
    """/Game/A/B.B -> Content/A/B.uasset."""
    package = path.split('.', 1)[0]
    if not package.startswith('/Game/'):
        return None
    return content / (package.removeprefix('/Game/') + '.uasset')


def rider_clip_paths(rig):
    return [f'/Game/{rig}Horse/A_{clip}.A_{clip}' for clip in RIDER_CLIPS]


def required_paths(roster, rig):
    """Every asset path the service loads, and the problems in the roster's description of them."""
    paths, problems = [], []
    breeds = roster.get('breeds') or {}
    tack = (roster.get('tack_sets') or [None])[0]
    if tack is None:
        problems.append('the roster has no tack set')

    def contacts_ok(breed):
        contacts = breed.get('contacts') or {}
        root = contacts.get('saddle_root')
        return isinstance(root, list) and len(root) == 3 and isinstance(contacts.get('seat_z'), (int, float))

    reference = breeds.get(roster.get('reference_breed', ''))
    if not reference or not contacts_ok(reference):
        problems.append('the roster has no reference breed with seat contacts')
    for slug in BREEDS:
        breed = breeds.get(slug)
        if not breed:
            problems.append(f'breed {slug} is missing from the roster')
            continue
        if not breed.get('mesh'):
            problems.append(f'breed {slug} has no mesh')
        else:
            paths.append(breed['mesh'])
        clips = breed.get('clips') or {}
        for clip in HORSE_CLIPS:
            path = (clips.get(clip) or {}).get('path')
            if not path:
                problems.append(f'breed {slug} has no {clip} clip')
            else:
                paths.append(path)
        saddle = (breed.get('saddles') or {}).get(tack)
        if not saddle:
            problems.append(f'breed {slug} has no saddle for tack set {tack}')
        else:
            paths.append(saddle)
        if not contacts_ok(breed):
            problems.append(f'breed {slug} has no saddle_root and seat_z contacts')
    textures = {v.get('id'): v.get('texture') for v in roster.get('coat_variants') or []}
    for coat in COATS:
        if not textures.get(coat):
            problems.append(f'coat {coat} has no texture in the roster')
        else:
            paths.append(textures[coat])
    if not rig:
        problems.append('the default character has no rig')
    else:
        paths += rider_clip_paths(rig)
    return paths, problems


def problems(roster, content, ini_text, rig):
    """Everything that would leave a runner missing, riderless or in another breed or coat, or out of the cook."""
    paths, found = required_paths(roster, rig)
    cooked = always_cooked(ini_text)
    for path in paths:
        file = asset_file(content, path)
        if file is None:
            found.append(f'{path} is not a /Game asset')
            continue
        if not file.is_file():
            found.append(f'{path} is missing ({file.relative_to(content)})')
        if not any(path.startswith(folder.rstrip('/') + '/') for folder in cooked):
            found.append(f'{path} is not in a folder DefaultGame.ini always cooks')
    return found


def default_rig(definition):
    """The default character's riding rig: its horse clips are in /Game/<rig>Horse."""
    chosen = [c for c in definition.movers() if c.game.get('default')]
    if len(chosen) != 1:
        raise RuntimeError(f'expected one default character, found {len(chosen)}')
    return chosen[0].game['bike_rig']


def check(out, rig, log):
    """Fails (RuntimeError) on any problem; otherwise writes out/racing/assets.json, the receipt. `log` has write()."""
    roster = json.loads(ROSTER.read_text()) if ROSTER.is_file() else {}
    if not roster:
        raise RuntimeError(f'racing assets: no staged roster at {ROSTER.relative_to(GAME)} (run unreal.horses)')
    found = problems(roster, CONTENT, CONFIG.read_text(), rig)
    if found:
        raise RuntimeError('racing assets are incomplete:\n  ' + '\n  '.join(found))
    paths, _ = required_paths(roster, rig)
    receipt = out / 'racing' / 'assets.json'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({'rig': rig, 'assets': sorted(paths)}, indent=1) + '\n')
    log.write(f'racing assets: {len(paths)} assets present and always cooked\n')
