"""Validate committed soundbanks and prepare independently owned build products.

Original delegates to the unchanged legacy banks. This producer does not generate
audio, import Unreal assets, select a bank, or claim listening acceptance.
"""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import wave

import numpy as np


ROOT = Path(__file__).resolve().parent
RATE = 48000
MAX_BANK_BYTES = 16 * 1024 * 1024
NAMES = {'original': (0, 'Original'), 'soft_contact': (1, 'Soft Contact'),
         'dry_street': (2, 'Dry Street'), 'warm_motion': (3, 'Warm Motion')}
FOOT_SURFACES = ('barefoot', 'dirt_gravel', 'grass', 'leaves', 'mud_water', 'stone', 'wood')
SKATE_SURFACES = ('concrete', 'wood', 'metal', 'asphalt', 'stone', 'dirt', 'grass', 'sand')
CUES = {**{f'footstep.{s}': (False, 4, 12) for s in FOOT_SURFACES},
        **{f'skate.roll.{s}': (True, 1, 2) for s in SKATE_SURFACES},
        **{f'skate.land.{s}': (False, 2, 4) for s in SKATE_SURFACES},
        'skate.skid': (True, 1, 2)}
INHERITED = ('horse.hoof', 'bike.*', 'combat.*', 'ambience.*', 'voice.*', 'ui.*',
             'skate.pop', 'skate.pop.*', 'skate.catch', 'skate.push', 'skate.flick',
             'skate.clatter', 'skate.fall', 'skate.grind', 'skate.grind.*', 'skate.slide', 'skate.scrape')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def document(path, maximum=256 * 1024):
    if path.is_symlink() or not 0 < path.stat().st_size <= maximum:
        raise ValueError('Invalid manifest file or size')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON field: ' + key)
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=unique)


def keys(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise ValueError('Invalid soundbank fields')


def provenance(value, frames, loop):
    keys(value, ('model', 'source_revision', 'weight_revision', 'prompt', 'seed',
                 'raw_sha256', 'interval_frames_48k', 'crossfade_frames', 'sampler', 'processor_sha256'))
    if (value['model'] != 'stable-audio-3-small-sfx'
            or not all(isinstance(value[k], str) and re.fullmatch('[0-9a-f]{40}', value[k])
                       for k in ('source_revision', 'weight_revision'))
            or not isinstance(value['raw_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', value['raw_sha256'])
            or not isinstance(value['processor_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', value['processor_sha256'])
            or not isinstance(value['prompt'], str) or not value['prompt'].strip()
            or len(value['prompt']) > 2000
            or type(value['seed']) is not int or not 0 <= value['seed'] < 2**31):
        raise ValueError('Invalid generation provenance')
    sampler = value['sampler']
    keys(sampler, ('steps', 'cfg', 'dit_dtype', 'decoder'))
    if (type(sampler['steps']) is not int or sampler['steps'] != 8
            or type(sampler['cfg']) not in (int, float) or sampler['cfg'] != 1
            or sampler['dit_dtype'] != 'fp16' or sampler['decoder'] != 'same-s'):
        raise ValueError('Unsupported generation sampler')
    interval, overlap = value['interval_frames_48k'], value['crossfade_frames']
    if (not isinstance(interval, list) or len(interval) != 2
            or any(type(x) is not int for x in interval)
            or not 0 <= interval[0] < interval[1] <= 120 * RATE
            or type(overlap) is not int
            or (not loop and overlap != 0)
            or (loop and not 240 <= overlap <= (interval[1] - interval[0]) // 8)
            or frames != interval[1] - interval[0] - overlap):
        raise ValueError('Invalid contact/loop source interval')


def sample(path, expected, loop, origin):
    if (path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(origin.resolve())
            or not 44 < path.stat().st_size <= 44 + 4 * RATE * 2):
        raise ValueError('Invalid WAV path or size')
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError('Source WAV checksum changed')
    with wave.open(io.BytesIO(payload), 'rb') as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, RATE, 'NONE'):
            raise ValueError('Expected canonical mono 48 kHz PCM16')
        frames = stream.getnframes()
        lo, hi = (.5, 4.) if loop else (.07, 1.2)
        if not lo * RATE <= frames <= hi * RATE or len(payload) != 44 + frames * 2:
            raise ValueError('Invalid canonical WAV event/loop duration')
        signal = np.frombuffer(stream.readframes(frames), '<i2').astype(np.float64) / 32768
    if len(signal) != frames or np.max(np.abs(signal)) >= .999 or np.sqrt(np.mean(signal ** 2)) < .0001:
        raise ValueError('Truncated, clipped or silent source WAV')
    return {'sha256': expected, 'frames': frames, 'bytes': len(payload), 'loop': loop}


def bank(path, identity):
    data = document(path)
    keys(data, ('version', 'id', 'cues', 'sources', 'inherit_original'))
    if type(data['version']) is not int or data['version'] != 1 or data['id'] != identity:
        raise ValueError('Invalid generated bank identity')
    if (not isinstance(data['inherit_original'], list)
            or any(not isinstance(x, str) for x in data['inherit_original'])
            or len(data['inherit_original']) != len(INHERITED)
            or set(data['inherit_original']) != set(INHERITED)):
        raise ValueError('Untouched cue families must explicitly inherit Original')
    keys(data['cues'], CUES)
    sources = data['sources']
    if not isinstance(sources, dict) or not 1 <= len(sources) <= 256:
        raise ValueError('Invalid source inventory')
    used, hashes, validated = set(), set(), {}
    for cue, (loop, minimum, maximum) in CUES.items():
        variants = data['cues'][cue]
        if not isinstance(variants, list) or not minimum <= len(variants) <= maximum:
            raise ValueError('Invalid variant coverage: ' + cue)
        for name in variants:
            if (not isinstance(name, str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}', name)
                    or name in used or name not in sources):
                raise ValueError('Missing, duplicate or aliased source')
            used.add(name)
            source = sources[name]
            keys(source, ('file', 'sha256', 'provenance'))
            if (source['file'] != f'samples/{name}.wav'
                    or not isinstance(source['sha256'], str)
                    or not re.fullmatch('[0-9a-f]{64}', source['sha256'])):
                raise ValueError('Invalid committed source path/hash')
            details = sample(path.parent / source['file'], source['sha256'], loop, path.parent)
            if details['sha256'] in hashes:
                raise ValueError('Aliased WAV bytes across source variants')
            hashes.add(details['sha256'])
            provenance(source['provenance'], details['frames'], loop)
            validated[name] = {**details, 'file': source['file'], 'cue': cue}
    if used != set(sources) or sum(s['bytes'] for s in validated.values()) > MAX_BANK_BYTES:
        raise ValueError('Unused sources or bank exceeds 16 MiB')
    return {'manifest_sha256': digest(path), 'cues': data['cues'], 'sources': validated,
            'inherit_original': list(INHERITED)}


def catalog(path):
    data = document(path, 64 * 1024)
    keys(data, ('version', 'default', 'banks'))
    if (type(data['version']) is not int or data['version'] != 1 or data['default'] != 'original'
            or not isinstance(data['banks'], list) or not 1 <= len(data['banks']) <= 4):
        raise ValueError('Original must remain the default bank')
    result, used = [], set()
    for entry in data['banks']:
        if not isinstance(entry, dict) or entry.get('id') not in NAMES:
            raise ValueError('Unknown bank identity')
        identity = entry['id']
        selection, name = NAMES[identity]
        fields = ('id', 'name', 'selection', 'legacy') if identity == 'original' else ('id', 'name', 'selection', 'manifest', 'sha256')
        keys(entry, fields)
        if (identity in used or type(entry['selection']) is not int
                or entry['selection'] != selection or entry['name'] != name):
            raise ValueError('Duplicate or changed stable bank selection')
        used.add(identity)
        if identity == 'original':
            if entry['legacy'] is not True or result:
                raise ValueError('Original must delegate unchanged and appear first')
            result.append(dict(entry))
        else:
            if entry['manifest'] != f'{identity}/bank.json':
                raise ValueError('Invalid bank manifest path')
            manifest = path.parent / entry['manifest']
            if manifest.parent.is_symlink() or not manifest.resolve().is_relative_to(path.parent.resolve()):
                raise ValueError('Bank manifest escapes committed source root')
            checked = bank(manifest, identity)
            if checked['manifest_sha256'] != entry['sha256']:
                raise ValueError('Bank manifest checksum changed')
            result.append({**entry, **checked})
    if 'original' not in used:
        raise ValueError('Original is required')
    return {'version': 1, 'default': 'original', 'catalog_sha256': digest(path), 'banks': result}


def _prepare(path, output):
    validated = catalog(path)
    for entry in validated['banks']:
        for source in entry.get('sources', {}).values():
            origin = path.parent / entry['id'] / source['file']
            name = Path('media') / source['sha256'] / Path(source['file']).name
            destination = output / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            payload = origin.read_bytes()
            if hashlib.sha256(payload).hexdigest() != source['sha256']:
                raise ValueError('Source changed before copying')
            if destination.exists():
                if destination.is_symlink() or digest(destination) != source['sha256']:
                    raise ValueError('Existing immutable product differs')
            else:
                fd, temporary = tempfile.mkstemp(dir=destination.parent)
                os.close(fd)
                try:
                    Path(temporary).write_bytes(payload)
                    os.link(temporary, destination)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            source['product'] = name.as_posix()
    rechecked = catalog(path)
    clean = json.loads(json.dumps(validated))
    for entry in clean['banks']:
        for source in entry.get('sources', {}).values():
            source.pop('product', None)
    if rechecked != clean:
        raise ValueError('Soundbank inputs changed before publication')
    for entry in validated['banks']:
        for source in entry.get('sources', {}).values():
            target = output / source['product']
            if target.is_symlink() or digest(target) != source['sha256']:
                raise ValueError('Product changed before publication')
    fd, temporary = tempfile.mkstemp(dir=output)
    os.close(fd)
    try:
        with Path(temporary).open('w') as stream:
            json.dump(validated, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write('\n')
        os.replace(temporary, output / 'manifest.json')
    finally:
        Path(temporary).unlink(missing_ok=True)
    return validated


def prepare(path, output):
    """Publish immutable verified media, then its index; never infer or select."""
    path, output = Path(path).absolute(), Path(output).absolute()
    if output.resolve().is_relative_to(path.parent.resolve()) or path.parent.resolve().is_relative_to(output.resolve()):
        raise ValueError('Generated products must be separate from committed sources')
    output.mkdir(parents=True, exist_ok=True)
    with (output / '.writer.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _prepare(path, output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=ROOT / 'catalog.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.catalog, args.output)
    print(f"Prepared {len(report['banks'])} soundbank definitions; Original remains default")
