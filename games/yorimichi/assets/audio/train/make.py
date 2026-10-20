#!/usr/bin/env python3
"""Build the Belmonte train's sounds into build/yorimichi/audio/train/<cue>/<cue>_01.wav (48 kHz mono 16-bit) from the
Sonniss GDC masters restored by fetch.py (local signal processing only, see audio/SONNISS-LICENSE.txt).

ABelmonteTrainService plays them from the train's own motion, the same pure function of the shared service clock on
every machine (BelmonteTrainSound.cpp, BelmonteTrainRules::SoundMix):

- idle (loop): the locomotive standing, faded out as it moves off;
- effort (loop): the locomotive working while the train accelerates;
- roll (loop): on every vehicle, its volume and pitch following the speed (ROLL_SPEED_MS is the speed it was recorded
  at, pitch 1);
- clack (one-shot): a bogie crossing a rail joint, fired each time one of a vehicle's bogies passes a joint
  (RAIL_LENGTH_M apart), so its rate is the train's real speed;
- brake (one-shot): started when the timetable's deceleration into a stand begins and pitched to end at the stop;
- depart (one-shot): the departure signal, at the moment the train moves off.

SPEC holds the chosen cut of each cue: the master (a file fetch.py restores), the seconds to take, the channel, the
gain and the fade (loops: the crossfade closing the loop; one-shots: the tail). A cue without a chosen cut (None) is
not built and the game leaves that layer silent; a chosen cut whose master is missing or too short fails the build.
Deterministic: the same masters give the same bytes.
"""
import json, wave
from pathlib import Path
import numpy as np

import sys as _sys; from pathlib import Path as _Path; _sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / 'world')); import yori  # noqa: E402
from atelier.paths import cache_dir  # noqa: E402

ROOT = yori.OUT
OUT = ROOT / 'audio/train'
MASTERS = cache_dir('sonniss', 'train', create=False)
SR = 48000
LOOPS = ('idle', 'effort', 'roll')
CUES = ('idle', 'effort', 'roll', 'clack', 'brake', 'depart')
ROLL_SPEED_MS = 22.     # the roll master's speed (m/s): it plays at pitch 1 there (BelmonteTrainSound.cpp RollSpeed)
RAIL_LENGTH_M = 25.     # one clack per bogie per joint (BelmonteTrainSound.cpp RailLength)
# The chosen cuts, filled in once the masters are picked: {'master': file name in MASTERS, 'start': s, 'seconds': s,
# 'channel': 0 | 1 | 'mix', 'gain_db': dB, 'fade': s}.
SPEC = {cue: None for cue in CUES}


def read(path):
    """A WAV master as float64 (frames, channels) at SR."""
    with wave.open(str(path)) as w:
        n, ch, width, rate = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = np.frombuffer(w.readframes(n), np.uint8)
    if width == 3:
        b = raw.reshape(-1, 3).astype(np.int32)
        x = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = np.where(x >= 1 << 23, x - (1 << 24), x) / float(1 << 23)
    elif width == 2:
        x = np.frombuffer(raw.tobytes(), '<i2') / 32768.
    elif width == 4:
        x = np.frombuffer(raw.tobytes(), '<i4') / float(1 << 31)
    else:
        raise ValueError(f'{path.name}: unsupported sample width {width}')
    x = x.reshape(-1, ch)
    if rate != SR:
        t = np.arange(int(len(x) * SR / rate)) * rate / SR
        x = np.stack([np.interp(t, np.arange(len(x)), x[:, c]) for c in range(ch)], 1)
    return x


def cut(spec, masters=None):
    """The chosen seconds of a master, one channel (or the mix), at its gain."""
    path = Path(masters or MASTERS) / spec['master']
    if not path.is_file():
        raise SystemExit(f'train audio: missing master {path.name} (run assets/audio/train/fetch.py)')
    x = read(path)
    a, b = int(spec['start'] * SR), int((spec['start'] + spec['seconds']) * SR)
    if a < 0 or b > len(x) or b - a < SR // 20:
        raise SystemExit(f'train audio: {path.name} has no {spec["start"]}..{spec["start"] + spec["seconds"]} s')
    x = x[a:b]
    x = x.mean(1) if spec.get('channel', 'mix') == 'mix' else x[:, int(spec['channel'])]
    return (x - x.mean()) * 10 ** (spec.get('gain_db', 0.) / 20.)


def loopify(x, fade):
    """A seamless loop: the head crossfaded (equal power) into the tail."""
    n = int(fade * SR)
    if n <= 0 or 2 * n >= len(x):
        raise SystemExit('train audio: a loop needs a crossfade shorter than half its length')
    w = np.linspace(0., np.pi / 2, n)
    head, x = x[:n].copy(), x[n:].copy()
    x[-n:] = x[-n:] * np.cos(w) + head * np.sin(w)
    return x


def shape(x, fade):
    """A one-shot: 2 ms fade in, `fade` s fade out."""
    x = x.copy()
    a, b = min(len(x), int(.002 * SR)), min(len(x), int(max(fade, .005) * SR))
    x[:a] *= np.linspace(0., 1., a)
    x[len(x) - b:] *= np.linspace(1., 0., b)
    return x


def write(cue, x, out=None):
    out = Path(out or OUT)
    peak = np.max(np.abs(x))
    if not np.isfinite(peak) or peak <= 1e-6:
        raise SystemExit(f'train audio: {cue} is silent')
    x = x / peak * min(peak, .891)          # never above -1 dBFS
    d = out / cue; d.mkdir(parents=True, exist_ok=True)
    path = d / f'{cue}_01.wav'
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes())
    return {'file': f'{cue}/{path.name}', 'seconds': round(len(x) / SR, 3)}


def build(spec=None, out=None, masters=None):
    spec, out = (SPEC if spec is None else spec), Path(out or OUT)
    report = {}
    for cue in CUES:
        chosen = spec.get(cue)
        if chosen is None:
            for stale in (out / cue).glob('*.wav'):     # a cue no longer chosen leaves nothing for the import
                stale.unlink()
            continue
        x = cut(chosen, masters)
        x = loopify(x, chosen.get('fade', .5)) if cue in LOOPS else shape(x, chosen.get('fade', .05))
        report[cue] = [write(cue, x, out)]
    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').write_text(json.dumps({
        'sample_rate': SR, 'loops': [c for c in LOOPS if c in report], 'roll_speed_ms': ROLL_SPEED_MS,
        'rail_length_m': RAIL_LENGTH_M, 'pending': [c for c in CUES if c not in report], 'cues': report}, indent=1) + '\n')
    return report


def main():
    report = build()
    print('TRAIN SFX READY', len(report), 'cues; pending:', ', '.join(c for c in CUES if c not in report) or 'none')


if __name__ == '__main__':
    main()
