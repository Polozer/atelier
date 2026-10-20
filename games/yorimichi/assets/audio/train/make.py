#!/usr/bin/env python3
"""Build the Belmonte train's sounds into build/yorimichi/audio/train/<cue>/<cue>_01.wav (48 kHz mono 16-bit) from the
Sonniss GDC masters restored by fetch.py (local signal processing only, see audio/SONNISS-LICENSE.txt).

ABelmonteTrainService plays them from the train's own motion, the same pure function of the shared service clock on
every machine (BelmonteTrainSound.cpp, BelmonteTrainRules::SoundMix):

- idle (loop): a distant steam blast: the engine's steam swelling over the last seconds of the braking, full at the stop,
  then a faint simmer gone within 10 s (a steam engine is loud stopping, not stopped);
- start (one-shot): the departure, started at the real departure: the clean build-up of an engine accelerating,
  slowed (START_RATE) so its beats roughly follow the driving wheels through the soft start, as loud as the effort;
- effort (loop): then the same engine's beats looped, played at the driving wheels' rate (CHUFF_* below) while the train
  accelerates, handing over to the roll as it reaches its cruise;
- roll (loop): on every vehicle, its volume and pitch following the speed (ROLL_SPEED_MS is the speed it was recorded
  at, pitch 1);
- clack (one-shots, six): a wheel set crossing a rail joint, fired each time one of a vehicle's bogies passes a joint
  (RAIL_LENGTH_M apart), so its rate is the train's real speed; one picked at random, varied in gain and pitch;
- brake (one-shot): started when the timetable's deceleration into a stand begins and pitched to end at the stop
  (the cut ends where the recorded train stops);
- depart (one-shot): the whistle, at the moment the train moves off;
- doors (one-shot): the coaches' doors closing DOORS_LEAD_S before the departure (BelmonteTrainSound.cpp);
- hiss (one-shot): the engine blowing off, one strong steam blast at the stop;
- pass (one-shot): a steam train passing, for a listener by the line as a train goes by at speed (PASS_PEAK_S).

SPEC holds the chosen cut of each cue: the master (a file fetch.py restores), the seconds to take (or several cuts, one
wave each: <cue>_01, _02...), the channel, a resampling rate (slower: lower and longer), the level (rms_db: the RMS in
dBFS of the cut, or of its rms_at window; or gain_db) and the fade (loops: the crossfade closing the loop, none for a
vendor loop; one-shots: the tail). A cue without a chosen cut (None) is
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
CUES = ('idle', 'start', 'effort', 'roll', 'clack', 'brake', 'depart', 'doors', 'hiss', 'pass')
ROLL_SPEED_MS = 22.     # the roll master's speed (m/s): it plays at pitch 1 there (BelmonteTrainSound.cpp RollSpeed)
RAIL_LENGTH_M = 25.     # one clack per bogie per joint (BelmonteTrainSound.cpp RailLength)
# The freerun master (dep_steam_freerun) accelerates cleanly for its first 16.2 s (onset detection on 5 ms frames: a beat
# every 0.45 s rising to every 0.10 s, the level rising 12 dB) before its decelerations. Its beats come in threes
# (strong, strong, weak: -36, -35, -43 dB peaks). The effort loop is 4 such cycles, 12 beats from the onset at 14.805 s
# to the one at 16.075 s: CHUFF_BEATS_PER_S at rate 1 (BelmonteTrainSound.cpp ChuffLoopBeats). The engine beats 4 times
# per revolution of its 1.9 m driving wheels: rate = (4 v / (pi 1.9)) / CHUFF_BEATS_PER_S.
CHUFF_BEATS_PER_S = round(12. / (16.075 - 14.805), 3)
CHUFF_BEATS_PER_REV = 4.
CHUFF_WHEEL_M = 1.9
# The start is the build-up up to that loop, resampled to half speed: a flat departure (route.py's RAMP, ACCELERATION and
# power) reaches the wheels' 4.9 beats/s after 29.6 s, when the slowed take beats 4.7/s and ends (the loop then starts at
# about rate 0.52); across it the slowed beats stay within about 25 % of the wheels' (0.75 and above drift 2x or more).
START_RATE = .5
# The pass-by's loudest moment (the engine abreast), s into its cut: the RMS (1 s frames) jumps 10 dB at 26.5-27 s of
# the master and stays within 5 dB of its top to 39 s (the coaches), the cut starts at 20 s (BelmonteTrainSound.cpp
# PassPeak).
PASS_PEAK_S = 7.
# Paul's final picks (2026-10-20) and the coordinator's idle design; masters from fetch.py. Each cut: {'master': file
# name in MASTERS, 'start': s, 'seconds': s (None: to the end) | 'cuts': [(start, seconds)...], 'channel': 0 | 1 | 'mix',
# 'rate': resampling, 'rms_db' | 'gain_db': dB, 'rms_at': (from, to) s of the result, 'fade': s, 'vendor_loop'}.
# Cut points from local DSP only (RMS envelopes, band energies, onsets): no listening model.
SPEC = {
    # the blast's steady middle (0.8-2.3 s within 1 dB; it builds up before and dies away after), looped ~10 dB under
    # the roll's cruise level
    'idle': {'master': 'idle_steam_blast_distant.wav', 'start': .7, 'seconds': 1.75, 'channel': 'mix', 'rms_db': -30.,
             'fade': .5},
    # the build-up to the loop's first beat, slowed to START_RATE; its last 4 s (as slowed) as loud as the effort loop
    'start': {'master': 'dep_steam_freerun.wav', 'start': 0., 'seconds': 14.805, 'channel': 'mix', 'rate': START_RATE,
              'rms_db': -18., 'rms_at': (25.6, 29.6), 'fade': .5},
    # 12 beats (the cut runs 20 ms past the 13th onset: the crossfade moves it onto the loop's first)
    'effort': {'master': 'dep_steam_freerun.wav', 'start': 14.805, 'seconds': 16.075 - 14.805 + .02, 'channel': 'mix',
               'rms_db': -18., 'fade': .02},
    'roll': {'master': 'roll_steam_ride.wav', 'start': 0., 'seconds': None, 'channel': 'mix', 'rms_db': -20.,
             'vendor_loop': True},
    # six single joint crossings of the passing train (onsets 12 dB over the 50 ms before, peaks -12.5..-13.7 dB, a
    # second apart), each 30 ms before its onset for 220 ms; heard over the roll loop's own clatter
    'clack': {'master': 'roll_ext_rails.wav', 'cuts': [(t - .03, .22) for t in (7.11, 8.14, 9.865, 10.865, 11.875, 12.88)],
              'channel': 'mix', 'rms_db': -20., 'fade': .08},
    # the arrival from its first clatter to the stop: the low band (< 1 kHz) falls to the standing floor and the
    # squeal ends at 21.3 s
    'brake': {'master': 'arr_steam_loco.wav', 'start': 1., 'seconds': 20.4, 'channel': 'mix', 'rms_db': -20., 'fade': .25},
    'depart': {'master': 'sig_steam_whistle.wav', 'start': 0., 'seconds': 12., 'channel': 'mix', 'rms_db': -16., 'fade': .8},
    'doors': {'master': 'sig_door_close.wav', 'start': 0., 'seconds': 1.2, 'channel': 'mix', 'rms_db': -20., 'fade': .05},
    # the master's strongest blast (the third: from 4.05 s, its peak -5 dB, silent from 6.4 s), loud
    'hiss': {'master': 'arr_steam_hiss.wav', 'start': 4.05, 'seconds': 2.4, 'channel': 'mix', 'rms_db': -16., 'fade': .2},
    # the approach and pass: from 20 s (the approach rising out of the tunnel's rumble) to 44 s (back at the floor)
    'pass': {'master': 'pass_steam_tunnel.wav', 'start': 20., 'seconds': 24., 'channel': 'mix', 'rms_db': -20., 'fade': 1.5},
}


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
    """The chosen cuts of a master (one or several), one channel (or the mix), at their gain."""
    path = Path(masters or MASTERS) / spec['master']
    if not path.is_file():
        raise SystemExit(f'train audio: missing master {path.name} (run assets/audio/train/fetch.py)')
    return [one(read(path), path, dict(spec, start=a, seconds=n)) for a, n in spec['cuts']] if 'cuts' in spec \
        else [one(read(path), path, spec)]


def one(x, path, spec):
    """One cut of a master (frames, channels) at SR."""
    a = int(spec['start'] * SR)
    b = len(x) if spec['seconds'] is None else int((spec['start'] + spec['seconds']) * SR)     # None: to the end
    if a < 0 or b > len(x) or b - a < SR // 20:
        raise SystemExit(f'train audio: {path.name} has no {spec["start"]} s + {spec["seconds"]} s')
    x = x[a:b]
    x = x.mean(1) if spec.get('channel', 'mix') == 'mix' else x[:, int(spec['channel'])]
    x = x - x.mean()
    if spec.get('rate', 1.) != 1.:          # resampled: played slower (lower, longer) or faster
        x = np.interp(np.arange(int(len(x) / spec['rate'])) * spec['rate'], np.arange(len(x)), x)
    if 'rms_db' in spec:                    # to a set loudness (of the cut or a window of it), whatever the master's level
        a, b = (int(t * SR) for t in spec.get('rms_at', (0., len(x) / SR)))
        return x * 10 ** (spec['rms_db'] / 20.) / max(float(np.sqrt((x[a:b] ** 2).mean())), 1e-9)
    return x * 10 ** (spec.get('gain_db', 0.) / 20.)


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


def write(cue, x, out=None, index=1):
    out = Path(out or OUT)
    peak = np.max(np.abs(x))
    if not np.isfinite(peak) or peak <= 1e-6:
        raise SystemExit(f'train audio: {cue} is silent')
    x = x / peak * min(peak, .891)          # never above -1 dBFS
    d = out / cue; d.mkdir(parents=True, exist_ok=True)
    path = d / f'{cue}_{index:02d}.wav'
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
        waves = []
        for x in cut(chosen, masters):
            if cue in LOOPS:
                x = x if chosen.get('vendor_loop') else loopify(x, chosen.get('fade', .5))     # a vendor loop as it is
            else:
                x = shape(x, chosen.get('fade', .05))
            waves.append(write(cue, x, out, len(waves) + 1))
        for stale in (out / cue).glob('*.wav'):         # a cut no longer chosen leaves nothing for the import
            if f'{cue}/{stale.name}' not in {w['file'] for w in waves}:
                stale.unlink()
        report[cue] = waves
    out.mkdir(parents=True, exist_ok=True)
    (out / 'manifest.json').write_text(json.dumps({
        'sample_rate': SR, 'loops': [c for c in LOOPS if c in report], 'roll_speed_ms': ROLL_SPEED_MS,
        'rail_length_m': RAIL_LENGTH_M, 'chuff_beats_per_s': CHUFF_BEATS_PER_S, 'start_rate': START_RATE, 'pass_peak_s': PASS_PEAK_S, 'pending': [c for c in CUES if c not in report], 'cues': report}, indent=1) + '\n')
    return report


def main():
    report = build()
    print('TRAIN SFX READY', len(report), 'cues; pending:', ', '.join(c for c in CUES if c not in report) or 'none')


if __name__ == '__main__':
    main()
