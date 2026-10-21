"""The transport bank's train cues (assets/audio/transport/make.py TRAIN_SPEC): chosen cuts of the Sonniss recordings
become seamless loops and faded one-shots, deterministically; a cut whose recording is missing fails; the constants the
game mirrors (BelmonteTrainSound.cpp, BelmonteTrainRules.h) agree. Stand-in recordings, numpy only."""
import importlib.util
import json
import wave
from pathlib import Path

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
MAKE = GAME / 'assets/audio/transport/make.py'
SOURCE = GAME / 'unreal/Source/Yorimichi'


@pytest.fixture(scope='module')
def make():
    spec = importlib.util.spec_from_file_location('transport_make_train', MAKE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def recording(path, seconds=6., rate=44100, channels=2, width=3):
    """A stand-in recording: a rumble with a ticking, in the recordings' formats (24-bit stereo at 44.1 kHz)."""
    t = np.arange(int(seconds * rate)) / rate
    x = .3 * np.sin(2 * np.pi * 55 * t) + .2 * np.sin(2 * np.pi * 7 * t) * np.sin(2 * np.pi * 900 * t)
    data = np.stack([x] * channels, 1)
    q = np.round(data * (2 ** (8 * width - 1) - 1)).astype(np.int32).ravel()
    raw = np.frombuffer(q.astype('<i4').tobytes(), np.uint8).reshape(-1, 4)[:, :3].tobytes() if width == 3 else q.astype('<i2').tobytes()
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(channels); w.setsampwidth(width); w.setframerate(rate); w.writeframes(raw)


def rms_db(x):
    return 20 * np.log10(np.sqrt((x ** 2).mean()))


def test_cuts_become_seamless_loops_and_faded_one_shots(make, tmp_path):
    recording(tmp_path / 'roll.wav')
    recording(tmp_path / 'brake.wav', width=2, channels=1, rate=48000)
    spec = {'train_roll': {'master': 'roll.wav', 'start': .5, 'seconds': 4., 'gain_db': -3., 'fade': .5},
            'train_brake': {'master': 'brake.wav', 'start': 0., 'seconds': 3., 'fade': .2}}
    cues = make.train_cues(tmp_path, spec)
    roll, = cues['train_roll']
    assert abs(len(roll) / make.SR - 3.5) < 1e-3                       # 4 s less the crossfade
    assert abs(roll[0] - roll[-1]) <= np.percentile(np.abs(np.diff(roll)), 99.9) + 1e-4   # no click at the wrap
    brake, = cues['train_brake']
    assert abs(brake[0]) < 1e-3 and abs(brake[-1]) < 1e-3              # faded in and out
    assert np.array_equal(make.train_cues(tmp_path, spec)['train_brake'][0], brake)        # deterministic
    # Written as every transport cue is, never above -1 dBFS.
    assert np.max(np.abs(make.finish('train_roll', roll * 10))) <= .892


def test_a_cut_without_its_recording_fails(make, tmp_path):
    with pytest.raises(SystemExit):
        make.train_cues(tmp_path, {'train_depart': {'master': 'absent.wav', 'start': 0., 'seconds': 1.}})


def test_levels_vendor_loops_cuts_to_the_end_rates_and_level_windows(make, tmp_path):
    recording(tmp_path / 'loop.wav', seconds=4.)
    recording(tmp_path / 'shot.wav', seconds=6.)
    cues = make.train_cues(tmp_path, {
        'train_roll': {'master': 'loop.wav', 'start': 0., 'seconds': None, 'rms_db': -20., 'vendor_loop': True},
        'train_hiss': {'master': 'shot.wav', 'start': 1., 'seconds': None, 'rms_db': -24., 'fade': .1},
        'train_clack': {'master': 'shot.wav', 'cuts': [(0., 1.), (2., 1.5), (4., 1.)], 'rms_db': -24., 'fade': .1},
        'train_start': {'master': 'shot.wav', 'start': 0., 'seconds': 2., 'rate': .5, 'rms_db': -18., 'rms_at': (3., 4.),
                        'fade': .1}})
    roll, = cues['train_roll']
    assert len(roll) == 4 * make.SR and abs(rms_db(roll) + 20.) < .1     # a vendor loop whole, at its set loudness
    hiss, = cues['train_hiss']
    assert len(hiss) == 5 * make.SR and rms_db(hiss) < -24.               # None: to the end; faded ends only lower it
    assert [len(x) / make.SR for x in cues['train_clack']] == [1., 1.5, 1.]  # one wave a cut
    start, = cues['train_start']
    assert len(start) == 4 * make.SR                                      # half speed: twice as long
    assert abs(rms_db(start[3 * make.SR:int(3.9 * make.SR)]) + 18.) < .5   # the window's level


def test_the_game_mirrors_the_recipe(make):
    source = (SOURCE / 'BelmonteTrainSound.cpp').read_text()
    assert f'RollSpeed = {make.TRAIN_ROLL_SPEED_MS:g}.' in source and f'RailLength = {make.TRAIN_RAIL_LENGTH_M:g}.' in source
    for cue in make.TRAIN:
        assert f'TEXT("{cue}")' in source
    assert f'ChuffLoopBeats = {make.TRAIN_CHUFF_BEATS_PER_S:g}, PassPeak = {make.TRAIN_PASS_PEAK_S:g}.;' in source
    rules = (SOURCE / 'BelmonteTrainRules.h').read_text()
    assert f'WheelM = {make.TRAIN_CHUFF_WHEEL_M:g}, double BeatsPerRev = {make.TRAIN_CHUFF_BEATS_PER_REV:g}.' in rules


def test_the_start_hands_over_to_the_loop(make):
    # The start ends where the effort loop's first beat is, and the loop is a whole number of beat cycles.
    start, effort = make.TRAIN_SPEC['train_start'], make.TRAIN_SPEC['train_effort']
    assert start['start'] + start['seconds'] == effort['start']
    assert start['rate'] == make.TRAIN_START_RATE
    assert abs(12. / (effort['seconds'] - effort['fade']) - make.TRAIN_CHUFF_BEATS_PER_S) < 1e-3


def test_the_manifest_carries_the_train_constants(make, tmp_path):
    manifest = make.build(tmp_path / 'audio' / 'transport', None, None)
    assert json.loads((tmp_path / 'audio/transport/manifest.json').read_text())['train'] == manifest['train'] == {
        'roll_speed_ms': make.TRAIN_ROLL_SPEED_MS, 'rail_length_m': make.TRAIN_RAIL_LENGTH_M,
        'chuff_beats_per_s': make.TRAIN_CHUFF_BEATS_PER_S, 'start_rate': make.TRAIN_START_RATE,
        'pass_peak_s': make.TRAIN_PASS_PEAK_S}
    assert not set(manifest['cues']) & set(make.TRAIN)                     # no recordings: no train cues
