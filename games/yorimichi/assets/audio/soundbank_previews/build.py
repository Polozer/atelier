"""Build small PCM menu auditions; never modify or select the runtime bank.

The walking/running cadence approximates animation plants. Skate speed, gain,
pitch and loop envelopes use the independently pinned review renderer.
"""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import os
import wave

import numpy as np

GAME = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('soundbank_preparation', Path(__file__).parents[1] / 'soundbanks/prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
RENDERER = GAME / 'tools/render_sound_sequences.py'
spec = importlib.util.spec_from_file_location('soundbank_sequence_renderer', RENDERER)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def read(path, identities, root, expected=None):
    if (path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
            or not 44 < path.stat().st_size <= 44 + 4 * prepare.RATE * 2):
        raise ValueError('Invalid audition source path/size')
    payload = path.read_bytes()
    sha = hashlib.sha256(payload).hexdigest()
    if expected is not None and sha != expected:
        raise ValueError('Audition source checksum changed')
    with wave.open(io.BytesIO(payload), 'rb') as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, prepare.RATE, 'NONE'):
            raise ValueError('Audition source must be mono 48 kHz PCM16')
        frames = stream.getnframes()
        if len(payload) != 44 + frames * 2:
            raise ValueError('Truncated/noncanonical audition source')
        samples = np.frombuffer(stream.readframes(frames), '<i2').astype(np.float64) / 32768
    if np.max(np.abs(samples)) >= .999 or np.sqrt(np.mean(samples ** 2)) < .0001:
        raise ValueError('Clipped/silent audition source')
    identities.append((path, sha))
    return path.name, samples


def pools(entry, prepared, footsteps, skate, identities):
    if entry['id'] == 'original':
        # Use the same stone footstep pool and concrete skate assets the game
        # loads. There is no normalization or regenerated replacement here.
        files = sorted((footsteps / 'stone').glob('*.wav'))
        if not 4 <= len(files) <= 256:
            raise ValueError('Original stone footstep pool is incomplete')
        result = {'footstep.stone': [read(p, identities, footsteps) for p in files]}
        for kind, folder in (('roll', 'roll'), ('skid', 'skid'), ('land', 'land')):
            files = sorted((skate / folder).glob('*.wav'))
            if not 1 <= len(files) <= 12:
                raise ValueError('Original concrete skate pool is incomplete')
            result['skate.' + kind + '.concrete'] = [read(p, identities, skate) for p in files]
        return result
    result = {}
    for cue in ('footstep.stone', 'skate.roll.concrete', 'skate.skid', 'skate.land.concrete'):
        sources = []
        for name in entry['cues'][cue]:
            source = entry['sources'][name]
            product = prepared / 'media' / source['sha256'] / Path(source['file']).name
            sources.append(read(product, identities, prepared, source['sha256']))
        result[cue if cue != 'skate.skid' else 'skate.skid.concrete'] = sources
    return result


def render(pools):
    walk, _, _ = renderer.render('walk', 'stone', pools, 1729)
    run, _, _ = renderer.render('run', 'stone', pools, 1730)
    skate, _, _ = renderer.render('transition', 'concrete', pools, 1731)
    # Four seconds of walking, four running, then the full eight-second skate
    # transition. Short independent fades avoid a discontinuity at each join.
    sections = [walk[:4 * prepare.RATE].copy(), run[:4 * prepare.RATE].copy(), skate]
    for section in sections:
        section[:960] *= np.linspace(0, 1, 960)
        section[-960:] *= np.linspace(1, 0, 960)
    signal = np.concatenate(sections)
    if not np.isfinite(signal).all() or np.max(np.abs(signal)) >= .999:
        raise ValueError('Invalid audition mix')
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as stream:
        stream.setparams((1, 2, prepare.RATE, 0, 'NONE', 'not compressed'))
        stream.writeframes(np.rint(signal * 32767).astype('<i2').tobytes())
    return buffer.getvalue()


def build(catalog, prepared, footsteps, skate, output):
    """@cc [owner:fontanierh,label:correctness] soundbank-audition-production
    Auditions MUST use actual verified bank media and the pinned runtime profile,
    with the same cadence, headroom and seeds across banks. Original MUST use
    unchanged legacy sources. All sources MUST validate before output writes and
    be rechecked before index publication. These replaceable derived products
    MUST NOT imply listening acceptance or change runtime sound selection.
    """
    catalog, prepared, footsteps, skate, output = (Path(p).absolute() for p in (catalog, prepared, footsteps, skate, output))
    if any(output.resolve().is_relative_to(p.resolve()) or p.resolve().is_relative_to(output.resolve())
           for p in (catalog.parent, prepared, footsteps, skate)):
        raise ValueError('Audition output must be separate from its inputs')
    runtime = renderer.runtime_identity()
    renderer_hash, producer_hash = prepare.digest(RENDERER), prepare.digest(Path(__file__))
    prepared_hash = prepare.digest(prepared / 'manifest.json')
    checked = prepare.catalog(catalog)
    product = prepare.document(prepared / 'manifest.json', 4 * 1024 * 1024)
    stripped = json.loads(json.dumps(product))
    for entry in stripped['banks']:
        for source in entry.get('sources', {}).values():
            source.pop('product', None)
    if stripped != checked:
        raise ValueError('Prepared soundbank index is stale')
    identities = []
    jobs = [(entry, pools(entry, prepared, footsteps, skate, identities)) for entry in checked['banks']]
    rendered = [(entry, render(pool)) for entry, pool in jobs]
    report = {'version': 1, 'catalog_sha256': checked['catalog_sha256'],
              'renderer_sha256': renderer_hash, 'producer_sha256': producer_hash,
              'prepared_sha256': prepared_hash,
              'runtime': runtime, 'cadence': '120/180 steps per minute; animation-plant approximation',
              'timeline': ['walk stone 0–4 s', 'run stone 4–8 s', 'skate concrete transition 8–16 s'],
              'sources': [{'file': p.relative_to(root).as_posix(), 'sha256': sha, 'root': label}
                          for p, sha in identities
                          for label, root in [('prepared', prepared), ('footsteps', footsteps), ('skate', skate)]
                          if p.is_relative_to(root)], 'banks': []}
    output.mkdir(parents=True, exist_ok=True)
    for entry, payload in rendered:
        sha = hashlib.sha256(payload).hexdigest()
        name = entry['id'] + '.wav'
        (output / name).write_bytes(payload)
        report['banks'].append({'id': entry['id'], 'file': name, 'sha256': sha,
                                'frames': 16 * prepare.RATE, 'bytes': len(payload)})
    if prepare.catalog(catalog) != checked or renderer.runtime_identity() != runtime:
        raise ValueError('Audition inputs changed during rendering')
    if (prepare.digest(RENDERER) != renderer_hash or prepare.digest(Path(__file__)) != producer_hash
            or prepare.digest(prepared / 'manifest.json') != prepared_hash):
        raise ValueError('Audition producer/index identity changed during rendering')
    if any(prepare.digest(p) != sha for p, sha in identities):
        raise ValueError('Audition media changed during rendering')
    for entry in report['banks']:
        if prepare.digest(output / entry['file']) != entry['sha256']:
            raise ValueError('Audition output changed before publication')
    fd, temporary = tempfile.mkstemp(dir=output)
    os.close(fd)
    try:
        Path(temporary).write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
        os.replace(temporary, output / 'manifest.json')
    finally:
        Path(temporary).unlink(missing_ok=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--footsteps', type=Path, required=True)
    parser.add_argument('--skate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.catalog, args.prepared, args.footsteps, args.skate, args.output)
    print(f"Prepared {len(result['banks'])} menu auditions (16 seconds each)", flush=True)
