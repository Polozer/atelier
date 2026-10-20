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
    assert f'ChuffLoopBeats = {make.CHUFF_BEATS_PER_S:g}, PassPeak = {make.PASS_PEAK_S:g}.;' in source
    rules = (MAKE.parents[3] / 'unreal/Source/Yorimichi/BelmonteTrainRules.h').read_text()
    assert f'WheelM = {make.CHUFF_WHEEL_M:g}, double BeatsPerRev = {make.CHUFF_BEATS_PER_REV:g}.' in rules


def test_levels_vendor_loops_and_cuts_to_the_end(make, tmp_path):
    masters, out = tmp_path / 'masters', tmp_path / 'out'
    masters.mkdir()
    master(masters / 'loop.wav', seconds=4.)
    master(masters / 'shot.wav', seconds=3.)
    spec = {cue: None for cue in make.CUES}
    spec['roll'] = {'master': 'loop.wav', 'start': 0., 'seconds': None, 'channel': 'mix', 'rms_db': -20., 'vendor_loop': True}
    spec['hiss'] = {'master': 'shot.wav', 'start': 1., 'seconds': None, 'channel': 0, 'rms_db': -24., 'fade': .1}
    report = make.build(spec, out, masters)
    assert report['roll'][0]['seconds'] == 4. and report['hiss'][0]['seconds'] == 2.      # a vendor loop whole; None: to the end
    for cue, db in (('roll', -20.), ('hiss', -24.)):
        with wave.open(str(out / f'{cue}/{cue}_01.wav')) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), '<i2') / 32768.
        if cue == 'roll':
            assert abs(20 * np.log10(np.sqrt((x ** 2).mean())) - db) < .1           # set loudness, untouched otherwise
        else:
            assert 20 * np.log10(np.sqrt((x ** 2).mean())) < db                    # faded ends only lower it
    assert json.loads((out / 'manifest.json').read_text())['chuff_beats_per_s'] == make.CHUFF_BEATS_PER_S


def test_several_cuts_a_rate_and_a_level_window(make, tmp_path):
    masters, out = tmp_path / 'masters', tmp_path / 'out'
    masters.mkdir()
    master(masters / 'shot.wav', seconds=6.)
    spec = {cue: None for cue in make.CUES}
    spec['hiss'] = {'master': 'shot.wav', 'cuts': [(0., 1.), (2., 1.5), (4., 1.)], 'channel': 'mix', 'rms_db': -24., 'fade': .1}
    spec['start'] = {'master': 'shot.wav', 'start': 0., 'seconds': 2., 'channel': 'mix', 'rate': .5, 'rms_db': -18.,
                     'rms_at': (3., 4.), 'fade': .1}
    report = make.build(spec, out, masters)
    assert [w['seconds'] for w in report['hiss']] == [1., 1.5, 1.]                   # one wave a cut
    assert sorted(p.name for p in (out / 'hiss').glob('*.wav')) == ['hiss_01.wav', 'hiss_02.wav', 'hiss_03.wav']
    assert report['start'][0]['seconds'] == 4.                                      # half speed: twice as long
    with wave.open(str(out / 'start/start_01.wav')) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), '<i2') / 32768.
    assert abs(20 * np.log10(np.sqrt((x[3 * make.SR:int(3.9 * make.SR)] ** 2).mean())) + 18.) < .5    # the window's level
    # Fewer cuts later: the extra wave goes.
    spec['hiss']['cuts'] = [(0., 1.)]
    make.build(spec, out, masters)
    assert [p.name for p in (out / 'hiss').glob('*.wav')] == ['hiss_01.wav']


def test_the_start_hands_over_to_the_loop(make):
    # The start ends where the effort loop's first beat is, and the loop is a whole number of beat cycles.
    assert make.SPEC['start']['start'] + make.SPEC['start']['seconds'] == make.SPEC['effort']['start']
    assert make.SPEC['start']['rate'] == make.START_RATE
    assert abs(12. / (make.SPEC['effort']['seconds'] - make.SPEC['effort']['fade']) - make.CHUFF_BEATS_PER_S) < 1e-3
