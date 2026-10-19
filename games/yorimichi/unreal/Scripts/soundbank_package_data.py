"""Standard-library-only admission shared by the two cold soundbank editor runs.

The normal build certifies the upstream planner. This consumer independently checks
its current source bindings, exact native slot mapping and every actual WAV before
an editor mutates packages. It must also work in Unreal's NumPy-free interpreter.
"""
from array import array
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import wave

GAME = Path(__file__).resolve().parents[2]
SOURCE = GAME / 'assets/audio/soundbanks'
FOOT = {'barefoot', 'dirt_gravel', 'grass', 'leaves', 'mud_water', 'stone', 'wood'}
SURFACES = {'concrete', 'wood', 'metal', 'asphalt', 'stone', 'dirt', 'grass', 'sand'}
CHOICES = {'original': (0, 'Original'), 'soft_contact': (1, 'Soft Contact'),
           'dry_street': (2, 'Dry Street'), 'warm_motion': (3, 'Warm Motion')}
ROOT = '/Game/AudioBanks'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path, limit=4 * 1024 * 1024):
    path = Path(path)
    if path.is_symlink() or not 0 < path.stat().st_size <= limit:
        raise ValueError('Invalid soundbank document extent')
    return json.loads(path.read_text())


def require(ok, message):
    if not ok:
        raise ValueError(message)


def asset(identity, name):
    return f'{ROOT}/{identity}/{name}.{name}'


def media(out, row):
    name = row['path']
    path = Path(out) / name
    parts = Path(name).parts
    require(isinstance(name, str) and not Path(name).is_absolute() and '..' not in parts
            and path.resolve().is_relative_to(Path(out).resolve())
            and not any(p.is_symlink() for p in (path, *path.parents)), 'Escaping soundbank media')
    require(type(row['frames']) is int and type(row['loop']) is bool, 'Invalid wave metadata')
    frames = row['frames']
    extent = (24000 <= frames <= 192000) if row['loop'] else (3360 <= frames <= 57600)
    if row['name'] == 'Audition':
        extent = frames == 16 * 48000 and row['loop'] is False
    require(extent and path.stat().st_size == 44 + frames * 2, 'Invalid soundbank wave extent')
    payload = path.read_bytes()
    require(hashlib.sha256(payload).hexdigest() == row['sha256'], 'Soundbank WAV checksum mismatch')
    with wave.open(io.BytesIO(payload), 'rb') as stream:
        require((stream.getnchannels(), stream.getsampwidth(), stream.getframerate(),
                 stream.getnframes(), stream.getcomptype()) == (1, 2, 48000, frames, 'NONE'),
                'Invalid soundbank PCM format')
        values = array('h', stream.readframes(frames))
    if sys.byteorder != 'little':
        values.byteswap()
    require(max(abs(v) for v in values) < .999 * 32768
            and sum(v * v for v in values) / frames > (.0001 * 32768) ** 2,
            'Silent or clipped soundbank PCM')
    return path


def preflight(out, source=SOURCE):
    """@cc [owner:fontanierh,label:correctness] native-soundbank-preflight
    Every source binding, slot and WAV MUST pass before package mutation. Original
    MUST import only its audition. A cold verifier MUST repeat this admission before
    publishing a registry; an import candidate alone MUST NOT become runtime data.
    """
    out, source = Path(out), Path(source)
    plan = read(out / 'audio/soundbank_import_plan/manifest.json')
    catalog = read(source / 'catalog.json', 65536)
    prepared = read(out / 'audio/soundbanks/manifest.json')
    previews = read(out / 'audio/soundbank_previews/manifest.json')
    renderer = ast.parse((GAME / 'tools/render_sound_sequences.py').read_text())
    pinned = next(ast.literal_eval(node.value) for node in renderer.body
                  if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'RUNTIME' for t in node.targets))
    require(plan['version'] == 1 and plan['default'] == 'original'
            and plan['audio_policy'] == dict(sample_rate=48000, channels=1, pcm_bits=16, loading='force_inline')
            and plan['producer_sha256'] == digest(GAME / 'soundbank_import.py')
            and plan['catalog_sha256'] == digest(source / 'catalog.json')
            and prepared['catalog_sha256'] == plan['catalog_sha256']
            and previews['catalog_sha256'] == plan['catalog_sha256']
            and previews['prepared_sha256'] == digest(out / 'audio/soundbanks/manifest.json')
            and previews['renderer_sha256'] == digest(GAME / 'tools/render_sound_sequences.py')
            and previews['producer_sha256'] == digest(GAME / 'assets/audio/soundbank_previews/build.py')
            and previews['runtime'] == pinned
            and all(digest(GAME.parents[1] / path) == sha for path, sha in previews['runtime'].items()),
            'Stale soundbank import plan')
    require(1 <= len(plan['banks']) <= 4 and len(plan['banks']) == len(catalog['banks'])
            == len(prepared['banks']) == len(previews['banks']), 'Invalid soundbank count')
    require(catalog['version'] == 1 and catalog['default'] == 'original', 'Invalid soundbank catalog')
    used = set()
    for row, definition, built, preview in zip(plan['banks'], catalog['banks'], prepared['banks'], previews['banks']):
        runtime = row['runtime']
        identity = runtime['id']
        require(identity in CHOICES and identity not in used, 'Unknown or duplicate soundbank')
        used.add(identity)
        selection, name = CHOICES[identity]
        original = identity == 'original'
        require(type(runtime['selection']) is int and runtime['selection'] == selection
                and runtime['name'] == name and runtime['legacy'] is original
                and definition['id'] == built['id'] == preview['id'] == identity
                and definition['selection'] == selection and definition['name'] == name
                and runtime['asset'] == ('' if original else asset(identity, 'DA_Bank'))
                and runtime['audition'] == asset(identity, 'Audition')
                and runtime['audition_sha256'] == preview['sha256'], 'Changed stable soundbank identity')
        if original:
            require(row is plan['banks'][0] and definition['legacy'] is True
                    and runtime['source_manifest_sha256'] == '' and len(row['waves']) == 1
                    and row['footsteps'] == row['oneshots'] == row['loops'] == {}, 'Original replacement refused')
        else:
            require(definition['manifest'] == identity + '/bank.json'
                    and definition['sha256'] == built['manifest_sha256'] == runtime['source_manifest_sha256']
                    == digest(source / definition['manifest']), 'Changed committed bank manifest')
            committed = read(source / definition['manifest'])
            require(committed['cues'] == built['cues'] and set(committed['sources']) == set(built['sources'])
                    and all(all(built['sources'][name][key] == sample[key] for key in ('file', 'sha256'))
                            for name, sample in committed['sources'].items()), 'Changed prepared source mapping')
            require(set(row['footsteps']) == FOOT
                    and set(row['oneshots']) == {'land' + ('' if s == 'concrete' else '_' + s) for s in SURFACES}
                    and set(row['loops']) == {'roll' + ('' if s == 'concrete' else '_' + s) for s in SURFACES} | {'skid'},
                    'Incomplete native soundbank coverage')
            expected = {}
            for cue, names in built['cues'].items():
                if cue.startswith('footstep.'):
                    actual = row['footsteps'][cue.removeprefix('footstep.')]
                    require(4 <= len(actual) <= 12, 'Invalid foot pool size')
                elif cue.startswith('skate.land.'):
                    surface = cue.removeprefix('skate.land.')
                    actual = row['oneshots']['land' + ('' if surface == 'concrete' else '_' + surface)]
                    require(2 <= len(actual) <= 4, 'Invalid landing pool size')
                else:
                    surface = cue.removeprefix('skate.roll.')
                    key = 'skid' if cue == 'skate.skid' else 'roll' + ('' if surface == 'concrete' else '_' + surface)
                    actual = [row['loops'][key]]
                require(actual == ['W_' + n for n in names], 'Changed native cue mapping')
                expected.update({'W_' + n: built['sources'][n] for n in names})
            require(set(expected) == {'W_' + n for n in built['sources']}, 'Unused soundbank source')
            require(len(row['waves']) == 1 + len(expected), 'Unexpected soundbank wave count')
        names, hashes, total = set(), set(), 0
        for wav in row['waves']:
            require(re.fullmatch(r'(Audition|W_[a-z0-9_]+)', wav['name']) is not None
                    and wav['name'] not in names and wav['asset'] == asset(identity, wav['name']), 'Invalid native wave name')
            names.add(wav['name'])
            if wav['name'] == 'Audition':
                require(wav['path'] == f'audio/soundbank_previews/{identity}.wav'
                        and wav['sha256'] == preview['sha256'], 'Changed audition wave')
            else:
                sample = expected[wav['name']]
                require(wav['path'] == 'audio/soundbanks/' + sample['product']
                        and sample['product'] == f"media/{sample['sha256']}/{Path(sample['file']).name}"
                        and (wav['sha256'], wav['frames'], wav['loop']) ==
                        (sample['sha256'], sample['frames'], sample['loop'])
                        and wav['sha256'] not in hashes, 'Changed or aliased source wave')
                hashes.add(wav['sha256'])
                total += 44 + wav['frames'] * 2
            media(out, wav)
        require('Audition' in names and total <= 16 * 1024 * 1024, 'Soundbank budget exceeded')
    require('original' in used, 'Missing Original')
    return plan


def receipt(plan):
    """Bind both native runs to the full plan and these exact consumer scripts."""
    return {'plan_sha256': hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
            'scripts': {name: digest(Path(__file__).parent / name) for name in
                        ('soundbank_package_data.py', 'soundbank_assets.py', 'import_soundbanks.py', 'verify_soundbanks.py')}}


def clear_packages(content, editor):
    """@cc [owner:fontanierh,label:correctness] soundbank-owned-package-cleanup
    Only the fixed AudioBanks child of Content may be cleared. Symlinks and
    unrecognized files MUST fail before editor mutation. Residual package bytes
    may be removed only after Unreal reports no registered assets in that root.
    Failure MUST prevent candidate/registry publication.
    """
    content = Path(content)
    root = content / 'AudioBanks'
    require(not root.is_symlink() and root.resolve().parent == content.resolve(), 'Invalid owned soundbank root')
    require(not root.exists() or root.is_dir(), 'Owned soundbank root is not a directory')
    paths = list(root.rglob('*')) if root.exists() else []
    require(all(not p.is_symlink() and (p.is_dir() or p.is_file() and p.suffix in ('.uasset', '.uexp', '.ubulk'))
                for p in paths), 'Unexpected file in owned soundbank root')
    if editor.does_directory_exist(ROOT):
        # UE may remove registry objects yet retain physical package files and
        # return false when its final empty-directory removal fails.
        editor.delete_directory(ROOT)
    require(not editor.list_assets(ROOT, recursive=True, include_folder=False),
            'Cannot clear registered soundbank assets')
    for path in sorted(paths, key=lambda p: len(p.parts), reverse=True):
        require(not path.is_symlink(), 'Soundbank path changed during cleanup')
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink(missing_ok=True)
    if root.exists():
        root.rmdir()


def packages(content):
    """Actual saved package bytes must survive unchanged into the cold editor."""
    root = Path(content) / 'AudioBanks'
    paths = sorted(p for p in root.rglob('*') if p.is_file())
    require(paths and all(not p.is_symlink() and p.resolve().is_relative_to(root.resolve())
                          and p.suffix in ('.uasset', '.uexp', '.ubulk') for p in paths), 'Invalid native soundbank package inventory')
    return {p.relative_to(root).as_posix(): digest(p) for p in paths}


def publish(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(document, stream, sort_keys=True, indent=2)
            stream.write('\n')
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
