"""The Belmonte train's sound recipe (assets/audio/train/make.py): chosen cuts of the Sonniss masters become seamless
loops and faded one-shots, deterministically; an unchosen cue is not built (and a stale one is removed); a chosen cut
with a missing master fails; the constants the game mirrors (BelmonteTrainSound.cpp) agree."""
import importlib.util
import json
import wave
from pathlib import Path

import numpy as np
import pytest

MAKE = Path(__file__).resolve().parents[1] / 'assets/audio/train/make.py'


@pytest.fixture(scope='module')
def make():
    spec = importlib.util.spec_from_file_location('train_audio_make', MAKE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def master(path, seconds=6., rate=44100, channels=2, width=3):
    """A stand-in master: a rumble with a ticking, in the masters' formats (24-bit stereo at 44.1 kHz)."""
    t = np.arange(int(seconds * rate)) / rate
    x = .3 * np.sin(2 * np.pi * 55 * t) + .2 * np.sin(2 * np.pi * 7 * t) * np.sin(2 * np.pi * 900 * t)
    data = np.stack([x] * channels, 1)
    q = np.round(data * (2 ** (8 * width - 1) - 1)).astype(np.int32).ravel()
    raw = np.frombuffer(q.astype('<i4').tobytes(), np.uint8).reshape(-1, 4)[:, :3].tobytes() if width == 3 else q.astype('<i2').tobytes()
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(channels); w.setsampwidth(width); w.setframerate(rate); w.writeframes(raw)


def test_chosen_cuts_build_loops_and_one_shots(make, tmp_path):
    masters, out = tmp_path / 'masters', tmp_path / 'out'
    masters.mkdir()
    master(masters / 'roll.wav')
    master(masters / 'brake.wav', width=2, channels=1, rate=48000)
    spec = {cue: None for cue in make.CUES}
    spec['roll'] = {'master': 'roll.wav', 'start': .5, 'seconds': 4., 'channel': 0, 'gain_db': -3., 'fade': .5}
    spec['brake'] = {'master': 'brake.wav', 'start': 0., 'seconds': 3., 'channel': 'mix', 'fade': .2}
    report = make.build(spec, out, masters)
    assert sorted(report) == ['brake', 'roll']
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['loops'] == ['roll'] and set(manifest['pending']) == set(make.CUES) - {'roll', 'brake'}
    with wave.open(str(out / 'roll/roll_01.wav')) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, make.SR)
        roll = np.frombuffer(w.readframes(w.getnframes()), '<i2') / 32768.
    assert abs(len(roll) / make.SR - 3.5) < 1e-3                       # 4 s less the crossfade
    assert abs(roll[0] - roll[-1]) <= np.percentile(np.abs(np.diff(roll)), 99.9) + 1e-4   # no click at the wrap
    assert np.max(np.abs(roll)) <= .892
    first = (out / 'brake/brake_01.wav').read_bytes()
    make.build(spec, out, masters)
    assert (out / 'brake/brake_01.wav').read_bytes() == first           # deterministic
    # Unchosen again: the stale cue goes, so the import never brings back a rejected sound.
    spec['brake'] = None
    make.build(spec, out, masters)
    assert not list((out / 'brake').glob('*.wav'))


def test_a_chosen_cut_without_its_master_fails(make, tmp_path):
    spec = {cue: None for cue in make.CUES}
    spec['depart'] = {'master': 'absent.wav', 'start': 0., 'seconds': 1.}
    with pytest.raises(SystemExit):
        make.build(spec, tmp_path / 'out', tmp_path)


def test_the_game_mirrors_the_recipe(make):
    source = (MAKE.parents[3] / 'unreal/Source/Yorimichi/BelmonteTrainSound.cpp').read_text()
    assert f'RollSpeed = {make.ROLL_SPEED_MS:g}.' in source and f'RailLength = {make.RAIL_LENGTH_M:g}.' in source
    for cue in make.CUES:
        assert f'TEXT("{cue}")' in source
