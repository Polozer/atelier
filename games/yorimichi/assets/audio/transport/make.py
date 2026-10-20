#!/usr/bin/env python3
"""Build the transport sounds (README.md) into build/yorimichi/audio/transport/<cue>/<cue>_NN.wav (48 kHz mono 16-bit).

One bank for the three passenger vehicles: the ferry, the gondola lines and the zeppelin. Loops are periodic by
construction, as the skateboard's and the bike's are: noise is shaped in the frequency domain, tones are snapped to a
whole number of cycles per loop and every hit train wraps round the loop's end, so a loop has no seam to click. The
game sets each loop's volume and pitch from the vehicle's state (the ferry's throttle, the zeppelin's propeller RPM, a
cabin's line speed) and fades it in and out. One-shots mark the state changes: horns, bells and chimes, gangways,
gates, grips and doors, a fender or a mooring taking the weight. Metal clanks, heavy thumps and wooden knocks are built
around four Sonniss GDC masters already in sonniss/combat (local signal processing only, see audio/SONNISS-LICENSE.txt);
everything else is synthesis. Deterministic: fixed seeds. The DSP helpers are the skateboard's (audio/skate/make.py)
and the bike's struck-metal `ring` and `rattle` (audio/bike/make.py).
"""
import importlib.util, json, sys, wave
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


sk = _load('skate_make', HERE.parent / 'skate' / 'make.py')
bk = _load('bike_make', HERE.parent / 'bike' / 'make.py')
SR, shaped_noise, band, peak, periodic_mod, env, thump, click, filtered, mix, fade_tail, resample, read = (
    sk.SR, sk.shaped_noise, sk.band, sk.peak, sk.periodic_mod, sk.env, sk.thump, sk.click, sk.filtered, sk.mix,
    sk.fade_tail, sk.resample, sk.read)
ring, rattle = bk.ring, bk.rattle
ROOT = sk.ROOT
OUT = ROOT / 'audio/transport'
SONNISS = sk.SONNISS

# Every cue the runtime plays (Source/Yorimichi/TransportAudio.cpp), its variant count and the Sonniss combat masters
# it is built around. A cue that names no master is pure synthesis.
METAL, THUMP, DRUM, STICK = ('smartsound_sword_hit_metal_02.wav', 'gamemaster_body_thump_02.wav',
                             'baxter_hit_big_drum_03.wav', 'audioville_stick_hit_13_wild.wav')
CUES = {
    # ferry
    'ferry_engine': dict(loop=True, variants=1, sonniss=()),
    'ferry_thruster': dict(loop=True, variants=1, sonniss=()),
    'ferry_wash': dict(loop=True, variants=1, sonniss=()),
    'ferry_moorings': dict(loop=True, variants=1, sonniss=()),
    'ferry_horn_depart': dict(loop=False, variants=1, sonniss=()),
    'ferry_horn_arrive': dict(loop=False, variants=1, sonniss=()),
    'ferry_brow_open': dict(loop=False, variants=3, sonniss=(METAL, DRUM)),
    'ferry_brow_close': dict(loop=False, variants=3, sonniss=(METAL,)),
    'ferry_fender': dict(loop=False, variants=3, sonniss=(THUMP,)),
    # gondola
    'gondola_station': dict(loop=True, variants=1, sonniss=()),
    'gondola_cabin': dict(loop=True, variants=1, sonniss=()),
    'gondola_sheave': dict(loop=False, variants=3, sonniss=()),
    'gondola_grip_attach': dict(loop=False, variants=3, sonniss=(METAL,)),
    'gondola_grip_release': dict(loop=False, variants=3, sonniss=(METAL,)),
    'gondola_door_open': dict(loop=False, variants=2, sonniss=()),
    'gondola_door_close': dict(loop=False, variants=2, sonniss=(STICK,)),
    'gondola_chime': dict(loop=False, variants=1, sonniss=()),
    # zeppelin
    'zeppelin_engine_idle': dict(loop=True, variants=1, sonniss=()),
    'zeppelin_engine': dict(loop=True, variants=1, sonniss=()),
    'zeppelin_envelope': dict(loop=True, variants=1, sonniss=()),
    'zeppelin_gate_open': dict(loop=False, variants=3, sonniss=(METAL,)),
    'zeppelin_gate_close': dict(loop=False, variants=3, sonniss=(METAL,)),
    'zeppelin_moor': dict(loop=False, variants=3, sonniss=(THUMP, DRUM)),
    'zeppelin_bell': dict(loop=False, variants=2, sonniss=()),
}
LOOPS = [cue for cue, spec in CUES.items() if spec['loop']]
# The propeller RPM each zeppelin engine loop is authored at (pitch 1): the runtime plays it at RPM / this.
ZEPPELIN_IDLE_RPM, ZEPPELIN_CRUISE_RPM = 90, 480


def n_of(seconds):
    return int(round(seconds * SR))


def noise(n, envelope, seed):
    """Exactly n samples of the skateboard's shaped noise."""
    return shaped_noise((n + .5) / SR, envelope, seed)[:n]


def tone(seconds, freq, phase=0.):
    """A sine that closes on itself over `seconds` (its frequency snapped to whole cycles): a seamless loop layer."""
    n = n_of(seconds)
    return np.sin(2 * np.pi * max(1, round(freq * seconds)) * np.arange(n) / n + phase)


def train(seconds, rate, shape, seed, jitter=0., accents=(1.,)):
    """`shape` hits at a steady `rate` (a whole number per loop), each wrapping round the loop's end; `accents` repeat
    hit by hit (an engine's cylinders do not fire quite alike)."""
    r = np.random.default_rng(seed)
    n = n_of(seconds); out = np.zeros(n); count = max(1, round(rate * seconds))
    for k in range(count):
        at = int(((k + r.uniform(-jitter, jitter)) / count % 1) * n)
        hit = shape(r) * accents[k % len(accents)]
        np.add.at(out, (at + np.arange(len(hit))) % n, hit)
    return out


def scattered(seconds, rate, shape, seed):
    """`shape` hits at random times about `rate` per second, wrapping round the loop's end (creaks, slaps)."""
    r = np.random.default_rng(seed)
    n = n_of(seconds); out = np.zeros(n)
    for _ in range(max(1, round(rate * seconds))):
        hit = shape(r) * r.uniform(.5, 1.)
        np.add.at(out, (int(r.uniform(0, n)) + np.arange(len(hit))) % n, hit)
    return out


def creak(seconds, f_from, f_to, chatter, seed):
    """Stick-slip friction (a rope on a bollard, a timber joint, a hinge): a gliding tone that chatters."""
    r = np.random.default_rng(seed)
    n = n_of(seconds); t = np.arange(n) / SR
    glide = np.sin(2 * np.pi * np.cumsum(np.geomspace(f_from, f_to, n)) / SR)
    grain = 1 + .7 * (np.sin(2 * np.pi * chatter * t + r.uniform(0, 6.3)) > .3)
    fizz = noise(n, lambda f: band(f, f_from, 6 * f_from), int(r.integers(1 << 30)))
    return fade_tail((glide * grain + .35 * fizz) * env(n, seconds * .25, seconds * .3), .03)


def strokes(seconds, fire, knock, seed, decay=.4, accents=(1., .86, .95, .8, .92, .88)):
    """An engine's firing strokes: a damped knock and an exhaust puff per stroke, `fire` strokes a second."""
    def stroke(r):
        m = n_of(min(.12, 3 / fire)); t = np.arange(m) / SR
        tau = decay / fire
        body = np.sin(2 * np.pi * knock * r.uniform(.97, 1.03) * t) * np.exp(-t / tau)
        puff = noise(m, lambda f: band(f, 60, 1400), int(r.integers(1 << 30))) * np.exp(-t / (.7 * tau))
        return body + .6 * puff
    return train(seconds, fire, stroke, seed, .02, accents)


def clatter_env(seconds, fire, seed, sharp=.12):
    """The valve train's tick on each stroke, as an amplitude envelope for a band of noise."""
    def tick(r):
        m = n_of(min(.06, 2 / fire)); return np.exp(-np.arange(m) / SR / (sharp / fire))
    return train(seconds, fire, tick, seed, .03)


def blades(seconds, rate, sharp=3.):
    """A propeller's blade pass as an amplitude envelope: a soft 'whup' `rate` times a second."""
    return ((1 + tone(seconds, rate)) / 2) ** sharp


def echo(x, delays):
    """Open-water slap-back: low-passed copies of x after each (seconds, gain)."""
    tail = max(d for d, _ in delays)
    soft = filtered(np.pad(x, (0, n_of(.3))), 60, 2200)   # padded, so the circular filter cannot wrap a click round
    out = np.pad(x, (0, n_of(tail + .3)))
    for d, g in delays:
        s = n_of(d); out[s:s + len(soft)] += g * soft
    return out


def horn(blasts, f0s, seed):
    """A ship's whistle: a chord of rich reed tones, each blast starting a little flat and rising to pitch as the steam
    builds, with a breathy edge, sounding for each (start, length) in `blasts`, then echoing back off the water."""
    r = np.random.default_rng(seed)
    total = max(s + d for s, d in blasts) + .6
    n = n_of(total); t = np.arange(n) / SR
    gate, since = np.zeros(n), np.full(n, 10.)
    for s, d in blasts:
        a, b = n_of(s), n_of(s + d)
        seg = np.arange(b - a) / SR
        gate[a:b] = np.maximum(gate[a:b], (1 - np.exp(-seg / .07)) * np.clip((d - seg) / .35, 0, 1) ** 1.5)
        since[a:b] = seg
    sag = 1 - .03 * np.exp(-since / .09)
    x = np.zeros(n)
    for f0, g in f0s:
        freq = f0 * sag * (1 + .0025 * np.sin(2 * np.pi * 4.7 * t + r.uniform(0, 6.3)))
        ph = 2 * np.pi * np.cumsum(freq) / SR
        for k in range(1, int(5000 / f0)):
            fk = k * f0
            x += g * np.sin(k * ph) / k ** 1.1 * (1 + 1.6 * np.exp(-.5 * ((fk - 480) / 160) ** 2) + .8 * np.exp(-.5 * ((fk - 1150) / 320) ** 2))
    breath = noise(n, lambda f: band(f, 500, 3500), int(r.integers(1 << 30)))
    x = (x + .05 * np.max(np.abs(x)) * breath) * gate
    return echo(x, [(.42, .22), (.95, .09)])


def ship_bell(f0, strikes, seed):
    """A bronze bell: hum, prime, tierce, quint and nominal partials ringing on after each clapper strike."""
    r = np.random.default_rng(seed)
    one = ring([f0 * .5, f0, f0 * 1.19, f0 * 1.5, f0 * 2., f0 * 2.52, f0 * 2.98], 2.6,
               [2.2, 1.6, 1.1, .8, .7, .45, .3], [.35, 1., .55, .3, .5, .22, .12], beat=1.6)
    one = fade_tail(mix((one, 1.), (click(.012, .0015, 2000, 9000, int(r.integers(1 << 30))), .25)), .5)
    out = np.zeros(n_of(.55 * strikes + 2.65))
    for k in range(strikes):
        s = n_of(.55 * k + r.uniform(0, .03)); out[s:s + len(one)] += one[:len(out) - s] * (1 if k == 0 else .8)
    return out


def transient(x, seconds):
    start = int(np.argmax(np.abs(x) > .2 * np.max(np.abs(x))))
    return fade_tail(x[max(0, start - 48): start + n_of(seconds)])


def at(x, seconds):
    return np.pad(x, (n_of(seconds), 0))


# --------------------------------------------------------------------------------------------- loops
def loops():
    """Every loop, each periodic over its own length."""
    out = {}
    # ferry_engine: the old-school ferry's slow six-cylinder diesel at cruise (30 strokes a second at pitch 1; the game
    # drops it to about .62 at idle): a deep thrum, the exhaust's puffs, a valve tick and the hull's rumble (3 s)
    thrum = filtered(strokes(3., 30, 62, 11), 25, 900)
    valves = shaped_noise(3., lambda f: band(f, 1400, 5500), 12) * clatter_env(3., 30, 13)
    rumble = shaped_noise(3., lambda f: band(f, 18, 140, 1.5), 14) * periodic_mod(3., .3, 1.5, .2, 15)
    whine = .05 * tone(3., 418) + .03 * tone(3., 836, 1.)
    out['ferry_engine'] = (thrum + .05 * valves + .5 * rumble + whine) * periodic_mod(3., .5, 2, .08, 16)
    # ferry_thruster: the bow tunnel thruster crabbing the ship onto its berth: the electric motor's whine, four blades
    # churning water in the tunnel and a cavitation fizz (2 s)
    motor = tone(2., 300) + .45 * tone(2., 600, .7) + .2 * tone(2., 903, 2.)
    churn = shaped_noise(2., lambda f: band(f, 70, 1600, 1.5) * (1 + peak(f, 320, 120, 1.)), 21) * (.55 + .45 * blades(2., 22, 2.))
    fizz = shaped_noise(2., lambda f: band(f, 2500, 9000), 22) * periodic_mod(2., 6, 30, .8, 23)
    out['ferry_thruster'] = .12 * motor + churn + .12 * fizz
    # ferry_wash: water parting at the bow and running down the hull, the wake churning astern; the game raises it
    # with the ship's speed (4 s)
    hull = shaped_noise(4., lambda f: band(f, 90, 3500, 1.2) * (1 / np.maximum(f, 90) ** .35), 31) * periodic_mod(4., .25, 1.2, .45, 32)
    spray = shaped_noise(4., lambda f: band(f, 1800, 9000), 33) * periodic_mod(4., 1.5, 7, .9, 34)
    slosh = shaped_noise(4., lambda f: band(f, 35, 220), 35) * periodic_mod(4., .2, .8, .6, 36)
    out['ferry_wash'] = hull + .3 * spray + .6 * slosh
    # ferry_moorings: at berth: water lapping between hull and quay, slaps under the pier, the mooring lines creaking
    # on their bollards and the rubber fenders groaning as the ship works (6 s)
    lap = shaped_noise(6., lambda f: band(f, 150, 1400) * (1 + peak(f, 420, 150, .6)), 41) * periodic_mod(6., .3, 1.1, .9, 42)
    slap = scattered(6., .9, lambda r: mix((thump(r.uniform(70, 110), .25, .06, .3), .6),
                                           (click(.12, .03, 200, 1800, int(r.integers(1 << 30))), 1.)), 43)
    rope = scattered(6., .45, lambda r: creak(r.uniform(.35, .6), r.uniform(260, 340), r.uniform(180, 230), r.uniform(28, 45), int(r.integers(1 << 30))), 44)
    groan = scattered(6., .25, lambda r: creak(r.uniform(.5, .8), r.uniform(85, 110), r.uniform(60, 75), r.uniform(14, 20), int(r.integers(1 << 30))), 45)
    out['ferry_moorings'] = lap + .8 * slap + .5 * rope + .6 * groan
    # gondola_station: the drive terminal: the motor's mains hum, the gearbox's whine, the bullwheel's slow rumble and
    # the haul rope ticking over the station's roller batteries (3 s)
    hum = tone(3., 100) + .5 * tone(3., 200, .4) + .25 * tone(3., 300, 1.1)
    gears = tone(3., 437) * (1 + .3 * tone(3., 1.)) + .4 * tone(3., 874, .5)
    bull = shaped_noise(3., lambda f: band(f, 22, 180, 1.5), 51) * periodic_mod(3., .3, 1.5, .4, 52)
    rollers = train(3., 6, lambda r: mix((click(.03, .005, 700, 4500, int(r.integers(1 << 30))), 1.), (thump(r.uniform(150, 175), .05, .012, .3), .6)), 53, .04)
    out['gondola_station'] = .1 * hum + .05 * gears + bull + .5 * rollers
    # gondola_cabin: riding along the line: air rushing round the timber cabin, a thin whistle at the window seals, the
    # hanger creaking at its pivot and the rope's low hum above (3 s)
    rush = shaped_noise(3., lambda f: band(f, 150, 2600, 1.2) * (1 / np.maximum(f, 150) ** .3), 61) * periodic_mod(3., .3, 1.5, .5, 62)
    whistle = shaped_noise(3., lambda f: peak(f, 1250, 40), 63) * periodic_mod(3., .4, 1.2, .9, 64)
    hanger = scattered(3., .7, lambda r: creak(r.uniform(.2, .35), r.uniform(520, 640), r.uniform(400, 470), r.uniform(30, 50), int(r.integers(1 << 30))), 65)
    rope_hum = shaped_noise(3., lambda f: band(f, 50, 260), 66)
    out['gondola_cabin'] = rush + .08 * whistle + .35 * hanger + .3 * rope_hum
    # zeppelin_engine_idle: the two small motors ticking over at 90 propeller RPM (pitch 1): their strokes a little out
    # of step, so they beat, and each two-bladed propeller's slow whup (2 s)
    port, starboard = strokes(2., 15, 88, 71, .5), strokes(2., 15.5, 93, 72, .5)
    whup = shaped_noise(2., lambda f: band(f, 120, 1800), 73) * blades(2., 2 * ZEPPELIN_IDLE_RPM / 60, 2.)
    out['zeppelin_engine_idle'] = filtered(port + .85 * starboard, 30, 1600) + .5 * whup
    # zeppelin_engine: both motors at the cruise's 480 propeller RPM (pitch 1): a buzzing drone of strokes, the blades'
    # sixteen-a-second throb and the propeller roar (2 s)
    port, starboard = strokes(2., 48, 140, 74, .6), strokes(2., 49.5, 147, 75, .6)
    roar = shaped_noise(2., lambda f: band(f, 70, 2400, 1.2) * (1 / np.maximum(f, 70) ** .3), 76) * (.6 + .4 * blades(2., 2 * ZEPPELIN_CRUISE_RPM / 60, 1.5))
    out['zeppelin_engine'] = filtered(port + .85 * starboard, 30, 2500) + .8 * roar
    # zeppelin_envelope: in flight, wind over the fabric envelope in slow gusts, the rigging wires singing faintly and
    # the frame creaking as the ship works (4 s)
    gust = shaped_noise(4., lambda f: band(f, 45, 1500, 1.2) * (1 / np.maximum(f, 45) ** .35), 81) * periodic_mod(4., .2, .9, .55, 82)
    wires = shaped_noise(4., lambda f: peak(f, 880, 25) + .6 * peak(f, 1320, 30), 83) * periodic_mod(4., .3, 1., .9, 84)
    frame = scattered(4., .6, lambda r: creak(r.uniform(.3, .5), r.uniform(190, 260), r.uniform(140, 180), r.uniform(18, 30), int(r.integers(1 << 30))), 85)
    out['zeppelin_envelope'] = gust + .05 * wires + .45 * frame
    return {cue: x - np.mean(x) for cue, x in out.items()}


# --------------------------------------------------------------------------------------------- one-shots
def one_shots(sonniss):
    """Every one-shot variant, as {cue: [samples, ...]}. `sonniss` is the folder holding the combat masters; with None
    only the cues that are pure synthesis are returned (the tests, where the masters are not fetched)."""
    master = lambda name: read(sonniss / name) if sonniss else np.r_[1., np.zeros(SR)]
    metal = transient(master(METAL), .4)
    body = transient(master(THUMP), .45)
    drum = filtered(transient(master(DRUM), 1.2), 25, 260)
    stick = transient(master(STICK), .3)
    out = {cue: [] for cue, spec in CUES.items() if not spec['loop']}
    out['ferry_horn_depart'].append(horn([(0, 3.4)], [(98, 1.), (147, .55)], 101))         # one prolonged blast
    out['ferry_horn_arrive'].append(horn([(0, 1.), (1.45, 2.2)], [(98, 1.), (147, .55)], 102))  # a short and a long
    # chime: the cabin's soft two-tone 'ding-dong' (E5, C5), struck bars with their fourth and tenth partials
    bar = lambda f, decay, beat: fade_tail(ring([f, f * 4, f * 10], 2.4, [decay, .25, .06], [1., .18, .05], beat=beat) * env(n_of(2.4), .004, 1e9), .5)
    out['gondola_chime'].append(mix((bar(659.3, .9, 1.1), 1.), (at(bar(523.3, 1., .9), .48), .9)))
    for i in range(3):
        r = np.random.default_rng(500 + i)
        # brow open: the steel gangway swings down onto the quay: its hinge groans, the handrail chains rattle and it
        # lands with a heavy clank
        clank = mix((filtered(resample(metal, [1.7, 1.85, 1.6][i]), 60, 4000), 1.), (drum, .9), (thump([58, 64, 54][i], .6, .12, .4), .7))
        out['ferry_brow_open'].append(mix((creak(.7, [140, 150, 132][i], [96, 104, 90][i], 22, 510 + i), .5),
                                          (at(rattle(.5, 9, 515 + i, 500, 4500, .006), .4), .35), (at(clank, .62), 1.)))
        # brow close: the winch lifts it clear and it drops into its cradle on deck with a lighter clank
        winch = (tone(1.2, 180) + .4 * tone(1.2, 360)) * env(n_of(1.2), .15, .5) * .4 + noise(n_of(1.2), lambda f: band(f, 400, 2500), 520 + i) * env(n_of(1.2), .1, .4) * .3
        out['ferry_brow_close'].append(mix((winch, .6), (at(rattle(.4, 7, 525 + i, 600, 5000, .005), .5), .3),
                                           (at(mix((filtered(resample(metal, [1.35, 1.45, 1.3][i]), 80, 5000), 1.), (thump([82, 90, 76][i], .4, .08, .4), .6)), .95), 1.)))
        # fender: the hull coming alongside: a deep thump into the rubber, which squeals and groans as it takes her weight
        out['ferry_fender'].append(mix((filtered(resample(body, [2.2, 2.4, 2.0][i]), 25, 600), 1.), (thump([42, 46, 39][i], 1.1, .3, .25), .8),
                                       (at(creak(.9, [120, 132, 110][i], [70, 76, 66][i], 16, 530 + i), .08), .55)))
        # sheave: the grip rolling over a tower's sheave train: a run of roller knocks swelling and fading, a rolling
        # rumble, and the cabin swinging on its hanger after it
        count = [8, 10, 9][i]; spacing = [.105, .09, .1][i]
        run = np.zeros(n_of(spacing * count + 1.4))
        for k in range(count):
            swell = np.sin(np.pi * (k + .5) / count) ** .8
            hit = mix((click(.05, .007, 600, 5000, 540 + 10 * i + k), 1.), (thump(r.uniform(95, 120), .12, .03, .4), .9),
                      (ring([r.uniform(1300, 1500)], .15, [.04], [1.]), .12))
            s = n_of(.006 + k * spacing + r.uniform(-.006, .006)); run[s:s + len(hit)] += swell * hit
        roll = noise(len(run), lambda f: band(f, 40, 500), 560 + i) * np.clip(np.sin(np.pi * np.arange(len(run)) / SR / (spacing * count + .1)), 0, 1) ** 1.5 * (np.arange(len(run)) / SR < spacing * count + .1)
        out['gondola_sheave'].append(mix((run, 1.), (roll, .45), (at(creak(.45, 560, 430, 36, 570 + i), spacing * count + .25), .3)))
        # grip attach: the detachable grip's spring jaws snapping shut on the haul rope: a hard clack and a chunk
        out['gondola_grip_attach'].append(mix((filtered(resample(metal, [1.05, 1.12, 1.0][i]), 300, 7000), .7), (click(.04, .006, 1500, 9000, 580 + i), .6),
                                              (at(thump([150, 162, 142][i], .25, .05, .5), .015), 1.), (at(rattle(.25, 4, 585 + i, 800, 5000, .004), .06), .35)))
        # grip release: the opening rail pries the jaws off: a spring's clunk and the cabin's wheels taking the rail
        out['gondola_grip_release'].append(mix((filtered(resample(metal, [1.3, 1.38, 1.25][i]), 200, 5000), .55), (thump([118, 126, 110][i], .3, .06, .4), 1.),
                                               (at(train(.4, 10, lambda rr: click(.03, .006, 500, 3500, int(rr.integers(1 << 30))), 590 + i), .08), .45)))
        # gate open: the airship deck's steel gate: the latch lifts, the hinge squeaks and it swings back to its stop
        latch = mix((filtered(resample(metal, [.8, .85, .78][i]), 600, 9000), .4), (click(.03, .004, 2000, 9000, 600 + i), .7))
        out['zeppelin_gate_open'].append(mix((latch, 1.), (at(creak(.55, [880, 940, 850][i], [1180, 1250, 1120][i], 40, 605 + i), .08), .3),
                                             (at(mix((filtered(resample(metal, [1.5, 1.6, 1.45][i]), 150, 4000), .7), (thump([170, 182, 160][i], .2, .04, .4), .6)), .62), .8)))
        # gate close: it swings shut and the latch drops home with a firm clack
        out['zeppelin_gate_close'].append(mix((creak(.45, [1150, 1210, 1100][i], [900, 950, 860][i], 40, 610 + i), .3),
                                              (at(mix((filtered(resample(metal, [1.15, 1.2, 1.1][i]), 200, 7000), 1.), (thump([190, 205, 180][i], .18, .035, .4), .8),
                                                      (click(.03, .004, 2000, 9000, 615 + i), .5)), .42), 1.)))
        # moor: the ship's car settling onto the landing stage: a big soft thump, the frame creaking and the lines
        # taking up the slack
        out['zeppelin_moor'].append(mix((filtered(resample(body, [2.6, 2.8, 2.4][i]), 25, 700), 1.), (drum, .8), (thump([40, 44, 37][i], 1.3, .35, .3), .7),
                                        (at(creak(.8, [210, 230, 200][i], [150, 160, 140][i], 20, 620 + i), .2), .4),
                                        (at(rattle(.4, 6, 625 + i, 400, 3500, .006), .15), .2)))
    for i in range(2):
        # door open: the cabin's sliding door rolling back on its track to a soft rubber stop
        n = n_of(.75)
        slide = noise(n, lambda f: band(f, 250, 3500), 630 + i) * (1 + .6 * np.sin(2 * np.pi * [24, 27][i] * np.arange(n) / SR)) * env(n, .12, .35)
        out['gondola_door_open'].append(mix((click(.03, .005, 1500, 7000, 635 + i), .4), (at(slide, .05), .6), (at(thump([120, 130][i], .2, .05, .4), .7), .6)))
        # door close: it rolls shut and meets the timber frame with a wooden knock, the latch clicking after it
        out['gondola_door_close'].append(mix((slide, .6), (at(filtered(resample(stick, [1.5, 1.6][i]), 80, 4000), .62), 1.),
                                             (at(thump([105, 112][i], .25, .06, .4), .62), .6), (at(click(.03, .004, 2500, 9000, 640 + i), .78), .45)))
        # bell: the ship's bronze bell rung twice, for departure and arrival
        out['zeppelin_bell'].append(ship_bell([830, 790][i], 2, 650 + i))
    return out if sonniss else {cue: x for cue, x in out.items() if not CUES[cue]['sonniss']}


# Peak (linear) each cue is written at: the transport bank sits inside the bike's and the skateboard's level range
# (games/yorimichi/tests/test_transport_audio.py checks it); the game balances them further with its own gains.
PEAKS = {
    'ferry_engine': .5, 'ferry_thruster': .45, 'ferry_wash': .45, 'ferry_moorings': .45,
    'gondola_station': .45, 'gondola_cabin': .4, 'zeppelin_engine_idle': .5, 'zeppelin_engine': .5, 'zeppelin_envelope': .4,
    'ferry_horn_depart': .38, 'ferry_horn_arrive': .38, 'ferry_brow_open': .8, 'ferry_brow_close': .7, 'ferry_fender': .75,
    'gondola_sheave': .6, 'gondola_grip_attach': .7, 'gondola_grip_release': .6, 'gondola_door_open': .45,
    'gondola_door_close': .6, 'gondola_chime': .45, 'zeppelin_gate_open': .55, 'zeppelin_gate_close': .65,
    'zeppelin_moor': .72, 'zeppelin_bell': .6,
}


def finish(cue, x):
    """Normalise to the cue's peak. One-shots get a 2 ms fade-in and a 20 ms fade-out; loops are left whole, since
    any fade would put a dip at the seam."""
    x = np.asarray(x, np.float64)
    if not CUES[cue]['loop']:
        x = fade_tail(x); x[:96] *= np.linspace(0, 1, 96)
    return x / max(np.max(np.abs(x)), 1e-9) * PEAKS[cue]


def write(out, cue, index, x):
    d = out / cue; d.mkdir(parents=True, exist_ok=True)
    path = d / f'{cue}_{index:02d}.wav'
    w = wave.open(str(path), 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()); w.close()
    return path


def levels(x):
    """Peak and loudest-400 ms RMS in dBFS (a file shorter than 400 ms is one window)."""
    window = n_of(.4)
    if len(x) <= window: rms = np.sqrt(np.mean(x ** 2))
    else:
        c = np.cumsum(np.r_[0, x ** 2]); rms = np.sqrt(np.max(c[window:] - c[:-window]) / window)
    return {'peak_dbfs': round(20 * np.log10(np.max(np.abs(x)) + 1e-12), 2), 'loudest_400ms_dbfs': round(20 * np.log10(rms + 1e-12), 2)}


def provenance(cue, picks):
    """Where a cue's sound comes from: synthesis here, plus each Sonniss master with its archive item, path and md5."""
    sources = [{'kind': 'synthesis', 'script': 'assets/audio/transport/make.py'}]
    for name in CUES[cue]['sonniss']:
        item, path, md5 = picks[name]
        sources.append({'kind': 'sonniss', 'file': f'sonniss/combat/{name}', 'source_item': item, 'source_path': path, 'md5': md5})
    return sources


def combat_picks():
    """The combat bank's fetched masters, {local name: (archive item, path in item, md5)}."""
    fetch = _load('combat_fetch', HERE.parent / 'combat' / 'fetch.py')
    return {name: (item, path, md5) for name, item, path, md5, _ in fetch.PICKS}


def build(out=OUT, sonniss=SONNISS):
    """@cc [owner:fontanierh,label:correctness] transport-bank-provenance
    Every transport sound MUST come from this script's synthesis or from Sonniss combat masters declared in CUES and
    fetched md5-checked by combat/fetch.py, with each source recorded in the manifest; no generated (AI) or music
    audio MAY enter the bank. Loops MUST stay periodic over their length, so they repeat without a seam.
    """
    out = Path(out); picks = combat_picks()
    sounds = {cue: [x] for cue, x in loops().items()}
    sounds.update(one_shots(Path(sonniss) if sonniss else None))
    if sonniss and set(sounds) != set(CUES): raise SystemExit(f'transport audio: missing cues {sorted(set(CUES) - set(sounds))}')
    manifest = {'sample_rate': SR, 'loops': LOOPS, 'cues': {}, 'sources': {}, 'zeppelin_rpm': {'idle': ZEPPELIN_IDLE_RPM, 'cruise': ZEPPELIN_CRUISE_RPM}}
    for cue, variants in sounds.items():
        if len(variants) != CUES[cue]['variants']: raise SystemExit(f'transport audio: {cue} has {len(variants)} variants')
        files = []
        for index, x in enumerate(variants, 1):
            x = finish(cue, x); path = write(out, cue, index, x)
            files.append({'file': str(path.relative_to(out.parent.parent)), 'seconds': round(len(x) / SR, 3), **levels(x)})
        manifest['cues'][cue] = files
        manifest['sources'][cue] = provenance(cue, picks)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n')
    return manifest


def main():
    manifest = build()
    print('TRANSPORT SFX READY', sum(len(v) for v in manifest['cues'].values()), 'files', flush=True)


if __name__ == '__main__':
    sys.exit(main())
