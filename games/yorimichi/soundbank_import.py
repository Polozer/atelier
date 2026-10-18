"""Prepare a portable checked plan for the future owned /Game/AudioBanks import.

Run outside Unreal: its embedded Python has no NumPy. The native consumer must
recheck this plan and its media before mutation and require current build stamps.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import wave

import numpy as np

GAME = Path(__file__).resolve().parent
SOURCE = GAME / 'assets/audio/soundbanks'
ROOT = '/Game/AudioBanks'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


prepare = module('soundbank_source_preparation', SOURCE / 'prepare.py')
renderer = module('soundbank_audition_renderer', GAME / 'tools/render_sound_sequences.py')


def object_path(folder, name):
    return f'{ROOT}/{folder}/{name}.{name}'


def plan(out, source=SOURCE):
    """@cc [owner:fontanierh,label:correctness] soundbank-import-preflight
    All committed definitions, prepared wave identities, audition PCM and current
    profile/producer bindings MUST validate before any Unreal asset mutation.
    Original MUST have only an explicit audition asset, with no replacement cue
    library. Runtime entries MUST retain stable catalog selections and bind each
    alternative's actual source manifest. Unrepresentable loop counts MUST fail.
    """
    out, source = Path(out).absolute(), Path(source).absolute()
    checked = prepare.catalog(source / 'catalog.json')
    prepared_root = out / 'audio/soundbanks'
    prepared_path = prepared_root / 'manifest.json'
    prepared = prepare.document(prepared_path, 4 * 1024 * 1024)
    stripped = json.loads(json.dumps(prepared))
    for entry in stripped['banks']:
        for sample in entry.get('sources', {}).values():
            sample.pop('product', None)
    if stripped != checked:
        raise ValueError('Stale prepared soundbank definitions')
    preview_root = out / 'audio/soundbank_previews'
    previews = prepare.document(preview_root / 'manifest.json', 1024 * 1024)
    if (previews['version'] != 1 or previews['catalog_sha256'] != checked['catalog_sha256']
            or previews['prepared_sha256'] != prepare.digest(prepared_path)
            or previews['runtime'] != renderer.runtime_identity()
            or previews['renderer_sha256'] != prepare.digest(GAME / 'tools/render_sound_sequences.py')
            or previews['producer_sha256'] != prepare.digest(GAME / 'assets/audio/soundbank_previews/build.py')
            or [b['id'] for b in previews['banks']] != [b['id'] for b in checked['banks']]):
        raise ValueError('Stale or mismatched soundbank auditions')
    rows = []
    for entry, preview in zip(checked['banks'], previews['banks'], strict=True):
        identity = entry['id']
        if preview['file'] != identity + '.wav':
            raise ValueError('Unexpected audition path')
        path = preview_root / preview['file']
        if path.is_symlink() or path.stat().st_size != 44 + 16 * prepare.RATE * 2:
            raise ValueError('Invalid audition extent')
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != preview['sha256']:
            raise ValueError('Audition checksum mismatch')
        with wave.open(io.BytesIO(payload), 'rb') as stream:
            if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getnframes(), stream.getcomptype()) != (1, 2, prepare.RATE, 16 * prepare.RATE, 'NONE'):
                raise ValueError('Invalid canonical audition format')
            signal = np.frombuffer(stream.readframes(stream.getnframes()), '<i2').astype(float) / 32768
        if np.max(np.abs(signal)) >= .999 or np.sqrt(np.mean(signal ** 2)) < .0001:
            raise ValueError('Clipped or silent audition')
        audition = object_path(identity, 'Audition')
        runtime = {k: entry[k] for k in ('id', 'name', 'selection')}
        runtime.update(legacy=identity == 'original', audition=audition,
                       asset='' if identity == 'original' else object_path(identity, 'DA_Bank'),
                       source_manifest_sha256=entry.get('manifest_sha256', ''),
                       audition_sha256=preview['sha256'])
        waves = [{'name': 'Audition', 'path': path.relative_to(out).as_posix(), 'sha256': preview['sha256'],
                  'frames': 16 * prepare.RATE, 'loop': False, 'asset': audition}]
        foot, shots, loops = {}, {}, {}
        for cue, names in entry.get('cues', {}).items():
            if cue.startswith('footstep.'):
                foot[cue.removeprefix('footstep.')] = ['W_' + n for n in names]
            elif cue.startswith('skate.land.'):
                surface = cue.removeprefix('skate.land.')
                shots['land' + ('' if surface == 'concrete' else '_' + surface)] = ['W_' + n for n in names]
            else:
                if len(names) != 1:
                    raise ValueError('The runtime currently requires one continuous loop per cue')
                surface = cue.removeprefix('skate.roll.')
                key = 'skid' if cue == 'skate.skid' else 'roll' + ('' if surface == 'concrete' else '_' + surface)
                loops[key] = 'W_' + names[0]
        for name, sample in entry.get('sources', {}).items():
            expected = f"media/{sample['sha256']}/{Path(sample['file']).name}"
            published = next(b for b in prepared['banks'] if b['id'] == identity)['sources'][name]
            if published['product'] != expected:
                raise ValueError('Unexpected prepared media path')
            path = prepared_root / expected
            details = prepare.sample(path, sample['sha256'], sample['loop'], prepared_root)
            if details['frames'] != sample['frames']:
                raise ValueError('Prepared media frame mismatch')
            waves.append({'name': 'W_' + name, 'path': path.relative_to(out).as_posix(), 'sha256': sample['sha256'],
                          'frames': details['frames'], 'loop': sample['loop'],
                          'asset': object_path(identity, 'W_' + name)})
        rows.append(dict(runtime=runtime, waves=waves, footsteps=foot, oneshots=shots, loops=loops))
    return {'version': 1, 'default': 'original', 'catalog_sha256': checked['catalog_sha256'],
            'audio_policy': {'sample_rate': 48000, 'channels': 1, 'pcm_bits': 16, 'loading': 'force_inline'},
            'producer_sha256': prepare.digest(Path(__file__)), 'banks': rows}


def registry(plan):
    """Only portable runtime metadata leaves the import planner; source paths stay private."""
    return {**{k: plan[k] for k in ('version', 'default', 'catalog_sha256')},
            'banks': [row['runtime'] for row in plan['banks']]}


def build(out, source=SOURCE):
    out = Path(out)
    checked = plan(out, source)
    if plan(out, source) != checked:
        raise ValueError('Soundbank inputs changed before plan publication')
    folder = out / 'audio/soundbank_import_plan'
    folder.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=folder)
    os.close(fd)
    try:
        Path(temporary).write_text(json.dumps(checked, sort_keys=True, indent=2) + '\n')
        os.replace(temporary, folder / 'manifest.json')
    finally:
        Path(temporary).unlink(missing_ok=True)
    return checked


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.out)
    print(f"Checked {len(result['banks'])} soundbank import plans; no native import or selection", flush=True)
