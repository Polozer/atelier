"""Prepare and generate a resumable Stable Audio MLX listening library.

Generation must run inside atelier.harness.safety.guarded. This module never
publishes game assets or modifies build stamps. The review root is public to
its tailnet audience: keep logs, credentials and absolute paths elsewhere.
"""

import argparse
import fcntl
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
import wave


SOURCE_REVISION = '77e0398c26f7d22d801ec1bb036307e8b231f741'
WEIGHT_REVISION = '08b17423649b5714b22eab20f96bf00751f2358a'
WEIGHT_SHA256 = {
    'dit_sm-sfx_f16.npz': '7e702d2640699a57fe436ca975fda16832040ba568c1e092c2ae826987558118',
    'same_s_decoder_f32.npz': '909928a8e6937c1ebe6ac4b729f0462bd3773704a11ea18278e42671dc69bfe4',
    'same_s_encoder_f32.npz': 'a48f80d81c30d74c45e2a3047082c4891f715e24c44645adb9c1f4f07afdaf0c',
    't5gemma_f16.npz': '8deb20489f36d9aec539f26c9c67321f99bc5fe300d470435ed6e76be4f16bbd',
}
SETTINGS = {'source_revision': SOURCE_REVISION, 'weight_revision': WEIGHT_REVISION,
            'model': 'small-sfx', 'runtime': 'mlx', 'steps': 8,
            'cfg': 1.0, 'dit_dtype': 'fp16', 'decoder': 'same-s'}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def write_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def verify_plan(manifest):
    if any(manifest.get(k) != v for k, v in SETTINGS.items()):
        raise ValueError('Unsupported generation settings')
    clips = [{**{k: v for k, v in clip.items() if k not in {'status', 'audio', 'elapsed_seconds'}},
              'status': 'pending'} for clip in manifest['clips']]
    identity = {**SETTINGS, 'clips': clips}
    actual = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    if manifest['plan_hash'] != actual:
        raise ValueError('Manifest plan was modified')


def prepare(catalog, output, web):
    """@cc [owner:fontanierh,label:correctness] immutable-review-plan
    An existing library MUST reject a changed catalog or generation identity.
    Clip paths MUST be generated identifiers beneath the dedicated audio folder.
    """
    catalog = json.loads(Path(catalog).read_text())
    clips = []
    for item in catalog['sounds']:
        if (not isinstance(item['prompt'], str) or not item['prompt'].strip()
                or not isinstance(item['seconds'], (int, float))
                or not math.isfinite(item['seconds']) or not 0 < item['seconds'] <= 120):
            raise ValueError('Invalid prompt or duration')
        for take, seed in enumerate(catalog['seeds'], 1):
            if type(seed) is not int or not 0 <= seed < 2**31:
                raise ValueError('Seed must be a nonnegative int32')
            clip_id = f'clip-{len(clips) + 1:04d}'
            clips.append({**item, 'id': clip_id, 'take': take, 'seed': seed,
                          'file': f'audio/{clip_id}.wav', 'status': 'pending'})
    identity = {**SETTINGS, 'clips': clips}
    plan_hash = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'audio').mkdir(exist_ok=True)
    manifest = output / 'manifest.json'
    if manifest.exists():
        existing = json.loads(manifest.read_text())
        verify_plan(existing)
        if existing['plan_hash'] != plan_hash:
            raise ValueError('Existing library has a different plan; use a fresh output root')
    else:
        write_json(manifest, {**identity, 'plan_hash': plan_hash, 'title': catalog['title']})
    for name in ('index.html', 'review.js', 'preview.js', 'review.css'):
        shutil.copyfile(Path(web) / name, output / name)
    return json.loads(manifest.read_text())


def wav_details(path, seconds):
    with wave.open(str(path), 'rb') as handle:
        if (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) != (2, 2, 44100):
            raise ValueError('Expected stereo 16-bit PCM at 44.1 kHz')
        frames = handle.getnframes()
        if abs(frames - round(seconds * 44100)) > 1:
            raise ValueError('Unexpected WAV duration')
        data = handle.readframes(frames)
        if len(data) != frames * 4:
            raise ValueError('Truncated WAV')
        # This catches a failed silent decode without altering or normalizing it.
        if not any(data):
            raise ValueError('Silent WAV')
    return {'sha256': digest(path), 'frames': frames, 'sample_rate': 44100,
            'channels': 2, 'sample_width': 2, 'bytes': path.stat().st_size}


def validate_runtime(runtime):
    actual = subprocess.check_output(
        ['git', '-C', str(runtime), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(
        ['git', '-C', str(runtime), 'status', '--porcelain', '--untracked-files=no'], text=True)
    if actual != SOURCE_REVISION or dirty:
        raise ValueError('Runtime must be the pinned clean official source')
    weights = {}
    for name, expected in WEIGHT_SHA256.items():
        path = runtime / 'optimized/mlx/models/mlx' / name
        if not path.is_symlink() or WEIGHT_REVISION not in path.readlink().parts:
            raise ValueError('Weights must resolve to the pinned Hugging Face snapshot')
        weights[name] = digest(path)
        if weights[name] != expected:
            raise ValueError('Weight checksum differs from the pinned official release')
    return weights


def generate(output, runtime, logs, limit=None):
    """@cc [owner:fontanierh,label:correctness] verified-review-takes
    A take MUST become ready only after successful native generation and complete
    WAV validation. Resume MUST verify hashes and runtime identity, and MUST NOT
    replay failed or interrupted takes automatically. Logs MUST stay outside the
    served review root. Generation MUST preserve an explicit seed for every take.
    Every ready take MUST be verified before any manifest update or generation,
    including ready takes beyond the requested batch limit.
    """
    output, runtime, logs = Path(output).resolve(), Path(runtime).resolve(), Path(logs).resolve()
    if logs.is_relative_to(output):
        raise ValueError('Logs must be outside the review root')
    logs.mkdir(parents=True, exist_ok=True)
    with (output / '.writer.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest_path = output / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        verify_plan(manifest)
        for clip in manifest['clips']:
            if clip['file'] != f"audio/{clip['id']}.wav" or not clip['id'].startswith('clip-') or not clip['id'][5:].isdigit():
                raise ValueError('Invalid clip path')
            if clip['status'] == 'ready':
                if wav_details(output / clip['file'], clip['seconds']) != clip['audio']:
                    raise ValueError('Previously generated take changed')
            elif clip['status'] != 'pending':
                raise ValueError('Failed/interrupted take requires diagnosis and explicit reset')
        weights = validate_runtime(runtime)
        if manifest.get('weight_sha256', weights) != weights:
            raise ValueError('Weight bytes changed')
        manifest['weight_sha256'] = weights
        write_json(manifest_path, manifest)
        count = 0
        for clip in manifest['clips']:
            target = output / clip['file']
            if clip['status'] == 'ready':
                continue
            if limit is not None and count >= limit:
                break
            clip['status'] = 'generating'
            write_json(manifest_path, manifest)
            temporary = target.with_suffix('.partial.wav')
            command = [str(runtime / 'optimized/mlx/.venv/bin/python'), '-u',
                       str(runtime / 'optimized/mlx/scripts/sa3_mlx.py'),
                       '--dit', 'sm-sfx', '--decoder', 'same-s', '--dit-dtype', 'fp16',
                       '--seconds', str(clip['seconds']), '--steps', '8', '--cfg', '1',
                       '--seed', str(clip['seed']), '--prompt', clip['prompt'], '--out', str(temporary)]
            print(f"Generate {clip['id']} / {len(manifest['clips'])}: {clip['label']}, take {clip['take']}", flush=True)
            started = time.monotonic()
            try:
                with (logs / f"{clip['id']}.log").open('w') as log:
                    child = subprocess.Popen(command, cwd=runtime / 'optimized/mlx', stdout=log, stderr=subprocess.STDOUT)
                    while True:
                        try:
                            code = child.wait(timeout=10)
                            break
                        except subprocess.TimeoutExpired:
                            print(f"  {clip['id']}: {time.monotonic() - started:.0f}s elapsed; native child still running", flush=True)
                            if time.monotonic() - started > 120:
                                child.terminate()
                                try:
                                    child.wait(timeout=10)
                                except subprocess.TimeoutExpired:
                                    child.kill()
                                    child.wait()
                                raise TimeoutError('Take exceeded 120 seconds')
                if code != 0:
                    raise RuntimeError(f'Native generator exited {code}; inspect private take log')
                details = wav_details(temporary, clip['seconds'])
                temporary.replace(target)
                clip.update(status='ready', audio=details, elapsed_seconds=round(time.monotonic() - started, 3))
            except BaseException:
                clip['status'] = 'failed'
                write_json(manifest_path, manifest)
                raise
            write_json(manifest_path, manifest)
            count += 1
            print(f"Ready {clip['id']} in {clip['elapsed_seconds']}s", flush=True)
        print(f"Library: {sum(c['status'] == 'ready' for c in manifest['clips'])}/{len(manifest['clips'])} ready", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    plan = sub.add_parser('prepare')
    plan.add_argument('--catalog', type=Path, required=True)
    plan.add_argument('--web', type=Path, required=True)
    plan.add_argument('--output', type=Path, required=True)
    run = sub.add_parser('generate')
    run.add_argument('--output', type=Path, required=True)
    run.add_argument('--runtime', type=Path, required=True)
    run.add_argument('--logs', type=Path, required=True)
    run.add_argument('--limit', type=int)
    args = parser.parse_args()
    if args.action == 'prepare':
        manifest = prepare(args.catalog, args.output, args.web)
        print(f"Prepared {len(manifest['clips'])} takes")
    else:
        if args.limit is not None and args.limit < 1:
            parser.error('--limit must be positive')
        generate(args.output, args.runtime, args.logs, args.limit)


if __name__ == '__main__':
    main()
