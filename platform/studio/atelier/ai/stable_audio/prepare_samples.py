"""Extract contact one-shots and continuous loop candidates from generated takes.

No model inference or game-bank replacement. The output keeps exact source
offsets and processing settings for listening review and later bank acceptance.
"""

import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import wave

import numpy as np

from atelier.ai.stable_audio.review import digest, verify_plan, write_json


RATE = 48000
HOP = 96
SURFACES = {
    'smooth concrete': 'concrete', 'smooth skatepark concrete': 'concrete',
    'rough concrete': 'concrete', 'asphalt': 'asphalt', 'coarse asphalt': 'asphalt',
    'dry asphalt': 'asphalt', 'loose gravel': 'gravel', 'short grass': 'grass',
    'wet mud': 'mud', 'dry sand': 'sand', 'wooden floorboards': 'wood',
    'ceramic tiles': 'tile', 'hollow metal grating': 'metal', 'shallow water': 'water',
    'crunchy snow': 'snow', 'soft carpet': 'carpet', 'brick paving': 'stone',
    'brick pavement': 'stone', 'stone pavers': 'stone', 'stone paving': 'stone',
    'stone slabs': 'stone', 'wooden boardwalk': 'wood', 'wooden deck': 'wood',
    'hollow plywood ramp': 'wood', 'polished wood': 'wood', 'metal ramp': 'metal',
}


def read_mono(path):
    with tempfile.TemporaryDirectory() as temporary:
        converted = Path(temporary) / 'mono.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path),
                        '-ac', '1', '-ar', str(RATE), '-c:a', 'pcm_s16le', str(converted)],
                       check=True, timeout=20)
        with wave.open(str(converted), 'rb') as handle:
            return np.frombuffer(handle.readframes(handle.getnframes()), '<i2').astype(np.float64) / 32768


def envelope(samples):
    size = len(samples) // HOP
    return np.sqrt(np.mean(samples[:size * HOP].reshape(size, HOP) ** 2, axis=1))


def contacts(samples, single=False):
    """Find separated attack/decay events; never cut across a following contact."""
    env = envelope(samples)
    if len(env) < 2 or env.max() < 1e-4:
        return []
    floor, peak = np.percentile(env, 20), env.max()
    if single:
        candidates = [int(np.argmax(env))]
    else:
        threshold = max(floor * 1.8, peak * .14)
        candidates = []
        for index in range(1, len(env) - 1):
            if env[index] < threshold:
                continue
            lo, hi = max(0, index - 25), min(len(env), index + 26)
            if env[index] != env[lo:hi].max():
                continue
            # A sustained bed is not a new footfall.
            before = env[max(0, index - 80):index]
            if len(before) and env[index] < max(before.min() * 1.8, 1e-4):
                continue
            if candidates and (index - candidates[-1]) * HOP < .24 * RATE:
                if env[index] > env[candidates[-1]]:
                    candidates[-1] = index
            else:
                candidates.append(index)
    spans = []
    for number, centre in enumerate(candidates):
        start = centre
        while start > 0 and env[start] > env[centre] * .12 and centre - start < 60:
            start -= 1
        start = max(0, start * HOP - int(.003 * RATE))
        limit = min(len(samples), int((.9 if single else .55) * RATE) + centre * HOP)
        if number + 1 < len(candidates):
            following = candidates[number + 1]
            valley = centre + int(np.argmin(env[centre:following]))
            limit = min(limit, valley * HOP)
        end = centre
        while end * HOP < limit and env[min(end, len(env) - 1)] > env[centre] * .045:
            end += 1
        end = min(limit, end * HOP + int(.03 * RATE))
        if end - start >= int(.07 * RATE):
            spans.append((start, end, centre * HOP))
    # Shorten an earlier tail if the following attack begins before its gate.
    bounded = [(start, min(end, spans[i + 1][0]) if i + 1 < len(spans) else end, peak)
               for i, (start, end, peak) in enumerate(spans)]
    clean = []
    for start, end, peak in bounded:
        event = samples[start:end]
        if len(event) < .07 * RATE:
            continue
        shaped = shape_contact(event - np.mean(event))
        # A late maximum usually means a clipped or merged footfall. Keep the
        # same conservative acceptance rule as the existing footstep bank.
        if not single and np.argmax(np.abs(shaped)) > .55 * len(shaped):
            continue
        clean.append((start, end, peak))
    return clean


def shape_contact(samples):
    samples = samples.copy()
    fade_in = min(int(.001 * RATE), len(samples) // 4)
    fade_out = min(int(.025 * RATE), len(samples) // 3)
    samples[:fade_in] *= np.linspace(0, 1, fade_in)
    samples[-fade_out:] *= np.linspace(1, 0, fade_out)
    return samples


def loop_candidate(samples, seconds):
    """@cc [owner:fontanierh,label:correctness] continuous-loop-extraction
    A loop MUST contain a continuous source interval with a documented circular
    crossfade. It MUST NOT concatenate unrelated events or claim exact action
    labels without listening acceptance. Constant/empty inputs MUST be rejected.
    """
    if not len(samples) or not np.isfinite(samples).all() or np.ptp(samples) < 1e-4:
        raise ValueError('Empty, non-finite or constant source')
    length = min(round(seconds * RATE), len(samples) - RATE)
    if length < RATE // 2:
        raise ValueError('Not enough sustained source audio')
    # Prefer a loud, steady interval; penalize isolated transients. Search at
    # 100ms intervals, excluding recording starts/ends and their approach sounds.
    best = None
    for start in range(RATE // 2, len(samples) - length - RATE // 4, RATE // 10):
        env = envelope(samples[start:start + length])
        score = np.median(env) - .35 * np.std(env)
        if best is None or score > best[0]:
            best = (score, start)
    if best is None or best[0] < 1e-5:
        raise ValueError('No stable audible loop interval')
    start = best[1]
    source = samples[start:start + length].copy()
    overlap = min(round(.12 * RATE), length // 8)
    phase = np.linspace(0, np.pi / 2, overlap)
    blend = source[-overlap:] * np.cos(phase) + source[:overlap] * np.sin(phase)
    result = source[overlap:].copy()
    result[-overlap:] = blend
    return result, start, start + length, overlap


def write_sample(path, samples, loop=False):
    if not len(samples) or not np.isfinite(samples).all() or np.max(np.abs(samples)) < 1e-4:
        raise ValueError('Invalid sample')
    samples = samples - np.mean(samples)
    if not loop:
        samples = shape_contact(samples)
    peak = np.max(np.abs(samples))
    if peak < 1e-4:
        raise ValueError('Constant sample')
    samples = samples * (10 ** (-3 / 20) / peak)
    pcm = np.rint(samples * 32767).astype('<i2')
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(pcm.tobytes())
    payload = buffer.getvalue()
    expected = hashlib.sha256(payload).hexdigest()
    if path.is_symlink():
        raise ValueError('Sample path must not be a symlink')
    if path.exists():
        if digest(path) != expected:
            raise ValueError('Existing sample bytes differ; immutable namespace cannot be overwritten')
    else:
        temporary = path.with_suffix('.partial.wav')
        temporary.write_bytes(payload)
        try:
            # Publish complete bytes without replacing an existing name, even
            # if an external writer creates it after the existence check.
            os.link(temporary, path)
        finally:
            temporary.unlink()
    return {'sha256': digest(path), 'frames': len(pcm), 'sample_rate': RATE,
            'channels': 1, 'sample_width': 2, 'bytes': path.stat().st_size,
            'peak_dbfs': -3, 'rms_dbfs': round(20 * np.log10(np.sqrt(np.mean(samples ** 2))), 2)}


def source_identities(root, raw):
    identities = []
    for clip in raw['clips']:
        path = (root / clip['file']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Raw source escapes review root')
        actual = digest(path)
        if actual != clip['audio']['sha256']:
            raise ValueError('Raw source checksum changed')
        identities.append({'id': clip['id'], 'file': clip['file'], 'sha256': actual})
    return identities


def _prepare(root):
    root = Path(root).resolve()
    raw = json.loads((root / 'manifest.json').read_text())
    verify_plan(raw)
    if any(c['status'] != 'ready' for c in raw['clips']):
        raise ValueError('Finish raw generation before preparing a sample bank')
    processor_hash = digest(Path(__file__))
    sources = source_identities(root, raw)
    bank_identity = {'raw_plan_hash': raw['plan_hash'], 'processing_sha256': processor_hash,
                     'sources': sources}
    bank_hash = hashlib.sha256(json.dumps(bank_identity, sort_keys=True).encode()).hexdigest()
    output = root / 'samples' / bank_hash
    output.mkdir(parents=True, exist_ok=True)
    prepared = []
    rejected = []
    for clip in raw['clips']:
        if clip['category'] not in {'Footsteps', 'Skate landings', 'Skate rolling', 'Skate powerslides'}:
            continue
        source = root / clip['file']
        if digest(source) != clip['audio']['sha256']:
            raise ValueError('Raw source checksum changed')
        samples = read_mono(source)
        surface_name = clip['label'].split(' · ', 1)[1]
        surface = SURFACES[surface_name]
        events = []
        if clip['category'] in {'Footsteps', 'Skate landings'}:
            for start, end, peak in contacts(samples, single=clip['category'] == 'Skate landings'):
                events.append((samples[start:end], start, end, 0, peak))
            cue = f'footstep.{surface}' if clip['category'] == 'Footsteps' else f'skate.land.{surface}'
            trigger = 'animated_foot_plant' if clip['category'] == 'Footsteps' else 'board_air_to_ground_contact'
        else:
            try:
                event, start, end, overlap = loop_candidate(samples, 3 if clip['category'] == 'Skate rolling' else 1.2)
                events.append((event, start, end, overlap, None))
            except ValueError as error:
                rejected.append({'source_id': clip['id'], 'reason': str(error)})
            cue = f'skate.roll.{surface}' if clip['category'] == 'Skate rolling' else f'skate.skid.{surface}'
            trigger = 'grounded_wheel_speed' if clip['category'] == 'Skate rolling' else 'grounded_powerslide_state'
        if not events and not any(r['source_id'] == clip['id'] for r in rejected):
            rejected.append({'source_id': clip['id'], 'reason': 'No isolated contact detected'})
        for variant, (event, start, end, overlap, peak) in enumerate(events, 1):
            sample_id = f'sample-{len(prepared) + 1:04d}'
            path = output / f'{sample_id}.wav'
            loop = overlap > 0
            audio = write_sample(path, event, loop=loop)
            prepared.append({**{k: clip[k] for k in ('label', 'category', 'prompt', 'seed', 'take')},
                             'id': sample_id, 'file': f'samples/{bank_hash}/{sample_id}.wav', 'status': 'ready',
                             'label': f"{clip['label']} · {'Loop' if loop else 'Hit'} {variant}",
                             'seconds': round(len(event) / RATE, 6), 'audio': audio,
                             'cue': cue, 'surface': surface, 'loop': loop, 'trigger': trigger,
                             'source_id': clip['id'], 'source_sha256': clip['audio']['sha256'],
                             'source_interval_frames_48k': [start, end],
                             'contact_preroll_seconds': None if loop else .003,
                             'contact_peak_frame': None if peak is None else peak - start,
                             'crossfade_frames': overlap, 'acceptance': 'listening_review_required'})
        print(f"Prepared {clip['id']}: {len(events)} samples", flush=True)
    manifest = {k: raw[k] for k in ('source_revision', 'weight_revision', 'model', 'runtime', 'steps', 'cfg', 'dit_dtype')}
    manifest.update(title=f"{raw['title']} · Contact samples and loops",
                    plan_hash=bank_hash,
                    raw_plan_hash=raw['plan_hash'], processing_sha256=processor_hash,
                    source_identities=sources,
                    clips=prepared, rejected=rejected)
    if source_identities(root, raw) != sources:
        raise ValueError('Raw source identity changed during preparation')
    write_json(root / 'prepared.json', manifest)
    print(f'Prepared {len(prepared)} samples; {len(rejected)} sources need manual segmentation', flush=True)


def prepare(root):
    """@cc [owner:fontanierh,label:correctness] atomic-sample-bank-publication
    Preparation MUST exclude other writers and publish a complete manifest only
    after all its samples exist and source hashes have been revalidated. Changed
    source bytes, processor or raw plan MUST write a distinct sample namespace.
    Existing namespace files MUST be verified/reused or fail without overwrite,
    so an interrupted refresh cannot change audio referenced by the old manifest.
    """
    with (Path(root) / '.writer.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _prepare(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    prepare(parser.parse_args().root)
