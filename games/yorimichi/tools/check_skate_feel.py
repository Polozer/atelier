#!/usr/bin/env python3
"""Measure the skate feel (FSkateFeel / FeelTuning) on the simulation offline QA session.

Each case rides the same inputs with stock feel and with one value changed, and checks that the change does what the
menu says: the defaults are bit-exact with no feel at all, gravity keeps jump heights but stretches air time, a gentler
flick pops higher with a lower flick pace, the 120 Hz flick reading reads the same flicks with the same window and pace
and keeps a fast hardflip's bottom point that 60 Hz misses, rolling resistance and braking change the coast, and rail magnetism catches
a rail from farther. Drift powerslides start with the stick straight down, grip as far as it is pulled and keep the
speed and the line when let go, a lower powerslide turn turns the board less, an assist zone's vert assist limit
rides as that much assist, and wall follow brings an air off a curved vert wall back down onto its transition to ride away (stock lands on the
deck behind the lip) while a zero-assist zone or no vert assist rides exactly as stock. In a boost zone, pumping across a halfpipe's walls gains
speed wall after wall even where the physical pump adds nothing, a trigger held through them or a hard turn's crouch gains nothing, a powerslide
gains, and outside every zone or on flat ground nothing changes, bit for bit. Requires the assembled simulation package (skate.runtime) and the
explicitly built test-only gameplay-session-cli
(Tests/build_simulation_session_cli.py --compile, under the render lock and memory guard). Results go to
build/yorimichi/skate-simulation/feel.
"""
import argparse
import json
import math
from pathlib import Path
import selectors
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SIMULATION_PACKAGE = ROOT / 'build/yorimichi/skate-simulation/package'  # atelier build yorimichi skate.runtime
BINARY = ROOT / 'build/skate-simulation-session-cli' / ('gameplay-session-cli.exe' if sys.platform == 'win32' else 'gameplay-session-cli')
OUTPUT = ROOT / 'build/yorimichi/skate-simulation/feel'
FLAT = [[[-200, 0, -200], [-200, 0, 200], [200, 0, 200]], [[-200, 0, -200], [200, 0, 200], [200, 0, -200]]]
FLAT_WORLD = {'triangles': FLAT, 'rails': [], 'spawn': [0, 0, 0], 'heading': 0}
PUSH, BRAKE = 0x1000, 0x2000
BOOST_WALL_MIN, BOOST_AHEAD_MIN = 3., 1.  # m/s: a pumped wall's boost at scale 1, and how far ahead per wall it keeps the ride


class Session:
    """A gameplay-session-cli process over a world: activate with a feel, then step 60 Hz frames. A session's state
    carries over from one ride to the next, so every ride after the first starts a fresh process."""

    def __init__(self, binary, package, world, name):
        self.command = [str(binary), str(package), str(OUTPUT / f'{name}.json')]
        (OUTPUT / f'{name}.json').write_text(json.dumps(world))
        self.log = (OUTPUT / f'{name}.log').open('w')
        self.start()

    def start(self):
        self.proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                                     text=True, bufsize=1)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)
        self.ready = self.read()
        assert self.ready['type'] == 'ready'
        self.deck = self.ready['names'].index('SKATEBOARD_ROOT')
        self.generation = 0

    def stop(self):
        try:
            self.send('quit')
            self.proc.wait(timeout=10)
        finally:
            self.selector.close()
            if self.proc.poll() is None:
                self.proc.terminate()
                self.proc.wait(timeout=10)

    def read(self):
        if not self.selector.select(60):
            raise TimeoutError('No simulation QA response within 60 seconds')
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError('Simulation QA exited; see its log in ' + str(OUTPUT))
        result = json.loads(line)
        if result['type'] == 'error':
            raise RuntimeError(result['message'])
        return result

    def send(self, op, **values):
        self.proc.stdin.write(json.dumps({'op': op, **values}) + '\n')
        self.proc.stdin.flush()

    def ride(self, frames, controls, feel=None, velocity=(0, 0, 0), spawn=(0, 0, 0), difficulty='normal', tune=None, limit=None):
        """Rows of every frame, from a fresh session; controls(frame) gives (buttons, left, right), or with the frame's
        120 Hz stick readings after them (with_readings)."""
        if self.generation:
            self.stop()
            self.start()
        self.generation += 1
        extra = {} if feel is None else {'feel': feel}
        self.send('activate', spawn=list(spawn), heading=0, goofy=False, difficulty=difficulty, trucks=.5,
                  generation=self.generation, velocity=list(velocity), **extra, **(tune or {}))
        self.read()
        if limit is not None:
            self.send('vert_assist_limit', limit=limit)
        rows = []
        for frame in range(frames):
            buttons, left, right, *readings = controls(frame)
            extra = {'readings': readings[0]} if readings else {}
            self.send('step', dt=1 / 60, buttons=buttons, left=left, right=right, triggers=[0, 0], **extra)
            rows.append(self.read())
        return rows

    def deck_height(self, row):
        a, b = row['root'], row['bones'][self.deck]
        return sum(a[k * 4 + 1] * b[3 * 4 + k] for k in range(4))

    def close(self):
        try:
            self.stop()
        finally:
            self.log.close()


def speed(row):
    return math.hypot(row['velocity'][0], row['velocity'][2])


def flick(load, snap):
    """A straight ollie: the stick held down from frame 150 for `load` frames, then up over `snap` frames."""
    def controls(frame):
        if 150 <= frame < 150 + load:
            return 0, [0, 0], [0, -32767]
        if 150 + load <= frame < 150 + load + snap:
            t = (frame - 150 - load + 1) / snap
            return 0, [0, 0], [0, int(-32767 + 65534 * t)]
        return 0, [0, 0], [0, 0]
    return controls


def arc(angles):
    """A flip flick from frame 150 through stick angles in degrees (0 right, 90 up): out to the first, round to each
    middle one, then a straight snap to the last."""
    point = lambda degrees, r=1.: (r * math.cos(math.radians(degrees)), r * math.sin(math.radians(degrees)))
    path = [point(angles[0], k / 3) for k in (1, 2, 3)] + [point(angles[0])] * 4
    for a, b in zip(angles[:-2], angles[1:-1]):
        path += [point(a + (b - a) * k / 5) for k in range(1, 6)]
    (ax, ay), (bx, by) = point(angles[-2]), point(angles[-1])
    path += [(ax + (bx - ax) * k / 3, ay + (by - ay) * k / 3) for k in (1, 2, 3)] + [point(angles[-1])] * 2
    def controls(frame):
        if 150 <= frame < 150 + len(path):
            x, y = path[frame - 150]
            return 0, [0, 0], [round(x * 32767), round(y * 32767)]
        return 0, [0, 0], [0, 0]
    return controls


def with_readings(controls, half=None):
    """controls with the host's 120 Hz stick readings: each frame's sticks half a frame before its end (half(frame),
    by default midway from the last frame's) and at its end. Ages sit a hair past each tick's end, as a reading taken
    just before it would be."""
    def stick(frame):
        buttons, left, right = controls(frame)[:3]
        return left + right
    def fine(frame):
        buttons, left, right = controls(frame)[:3]
        middle = half(frame) if half else [round((a + b) / 2) for a, b in zip(stick(frame - 1), left + right)]
        return buttons, left, right, [[1 / 120 + 1e-4, *middle], [1e-4, *left, *right]]
    return fine


def traced(path, start=150):
    """A right-stick flick traced at 120 Hz from frame `start`: the frame's sticks are every second point, the
    readings half a frame before them the points between."""
    stick = lambda p: [round(p[0] * 32767), round(p[1] * 32767)]
    point = lambda k: path[k] if 0 <= k < len(path) else (0, 0)
    controls = lambda frame: (0, [0, 0], stick(point(2 * (frame - start) + 1)))
    return with_readings(controls, lambda frame: [0, 0, *stick(point(2 * (frame - start)))])


def sampled(stick, phase):
    """A continuous right stick, stick(t) in frames, read at frame ends `phase` of a frame late: each frame's packet
    and the 120 Hz reading half a frame before it."""
    to = lambda p: [round(p[0] * 32767), round(p[1] * 32767)]
    return with_readings(lambda frame: (0, [0, 0], to(stick(frame - phase))),
                         lambda frame: [0, 0, *to(stick(frame - .5 - phase))])


def stretched(controls, by, start=150):
    """controls slowed `by` times from frame `start`, each stick moving linearly between the original frames."""
    def slow(frame):
        if frame < start:
            return controls(frame)
        at = start + (frame - start) / by
        (b, l0, r0), (_, l1, r1) = controls(math.floor(at))[:3], controls(math.floor(at) + 1)[:3]
        t = at - math.floor(at)
        mix = lambda p, q: [round(a + (c - a) * t) for a, c in zip(p, q)]
        return b, mix(l0, l1), mix(r0, r1)
    return slow


def first_trick(session, controls, feel):
    """The trick named on the frame the board leaves the ground (the label sticks afterwards)."""
    rows = session.ride(240, controls, feel, velocity=(0, 0, 5))
    for before, row in zip(rows, rows[1:]):
        if 'Air' in row['state'] and 'Air' not in before['state']:
            return row['trick'].replace('ID_TRICK_FLIP_', '') or 'blank'
    return 'none'


def takeoff_trick(session, angles, feel):
    return first_trick(session, arc(angles), feel)


def jump(session, feel, load=18, snap=2, fine=False):
    controls = flick(load, snap)
    rows = session.ride(330, with_readings(controls) if fine else controls, feel, velocity=(0, 0, 5))
    air = [r for r in rows if 'Air' in r['state']]
    return {'height_m': max(session.deck_height(r) for r in rows), 'airtime_s': len(air) / 60,
            'bailed': any('Wipeout' in r['state'] for r in rows), 'states': sorted({r['state'] for r in rows})}


def powerslide(session, feel, degrees, depth, start=10, hold=60):
    """The left stick held `hold` frames from frame 60 at `degrees` off straight down (positive right) and `depth`, from
    `start` m/s: the frames in SlideGround, the speed it lost a second sliding, the board's widest angle across its
    travel, and half a second after letting go the speed and how far the line has turned (degrees)."""
    x, y = math.sin(math.radians(degrees)) * depth, -math.cos(math.radians(degrees)) * depth
    stick = [round(x * 32767), round(y * 32767)]
    rows = session.ride(90 + hold, lambda frame: (0, stick if 60 <= frame < 60 + hold else [0, 0], [0, 0]), feel, velocity=(0, 0, start))
    slid = [i for i, r in enumerate(rows) if r['state'] == 'SlideGround']
    if not slid:
        return {'frames': 0}
    heading = lambda r: math.degrees(math.atan2(r['velocity'][0], r['velocity'][2]))
    wrap = lambda a: abs((a + 180) % 360 - 180)
    def across(r):
        a, b = r['root'], r['bones'][session.deck]
        forward = [sum(a[j * 4 + k] * b[2 * 4 + j] for j in range(4)) for k in range(3)]
        return wrap(math.degrees(math.atan2(forward[0], forward[2])) - heading(r))
    return {'frames': len(slid), 'loss_mps_per_s': (speed(rows[slid[0]]) - speed(rows[slid[-1]])) / max(1, len(slid) - 1) * 60,
            'board_peak_deg': max(across(rows[i]) for i in slid), 'speed_after': speed(rows[-1]),
            'line_turn_deg': wrap(heading(rows[-1]) - heading(rows[59]))}


def halfpipe(radius, height, flat=6., width=40., steps=24):
    """Two transitions of `radius` facing across `flat` m along z, rising to `height` (vertical above the radius)."""
    arc = math.pi / 2 if height >= radius else math.acos(1 - height / radius)
    side = [(flat / 2 + radius * math.sin(arc * k / steps), radius * (1 - math.cos(arc * k / steps))) for k in range(steps + 1)]
    side += [(flat / 2 + radius, height)] if height > radius else []
    profile = [(-z, y) for z, y in reversed(side)] + side
    triangles = [t for (z0, y0), (z1, y1) in zip(profile, profile[1:])
                 for t in ([[-width / 2, y0, z0], [-width / 2, y1, z1], [width / 2, y1, z1]],
                           [[-width / 2, y0, z0], [width / 2, y1, z1], [width / 2, y0, z0]])]
    return {'triangles': triangles, 'rails': [], 'spawn': [0, 0, 0], 'heading': 0}


GROUND = ('PhysicsGround', 'RevertGround')
PUMP_PULL = 200                 # of 255 on R2, as the simulation's reference pumps pull a trigger
SLIDE_STICK = [round(math.sin(math.radians(25)) * 32767), -32767]
HARD_TURN = [30000, -16000]    # a full stick about 1.1 rad from backward: a hard turn's crouch, short of a slide
# Yorimichi's skate settings (DefaultGame.ini): pop, spin and push scales, vert assist 1, drift powerslides, wall follow.
YORIMICHI_TUNE = {'pop': 1.15, 'spin': 1.6, 'push_speed': 1.15, 'push_power': 1.45, 'vert_assist': 1}
YORIMICHI_FEEL = {'drift_powerslide': 1, 'grind_tolerance': 2, 'camera_follow': 2, 'tight_flicks': 1, 'wall_follow': 1}


def carve(row, angle, radius, height, flat):
    """A player's left stick x carving the halfpipe: across the flat, the travel held `angle` degrees off straight
    across (either way); on a wall, a turn downhill about the wall's normal, as far as the climb would take the board
    past 75% of the wall's height. Positive x turns the board right (its heading atan2(vx, vz) falls on the flat)."""
    vx, vy, vz = row['velocity']
    y, z = row['root'][13], row['root'][14]
    if abs(z) <= flat / 2 + .05 and y < .2:
        error = ((angle if vz >= 0 else 180 - angle) - math.degrees(math.atan2(vx, vz)) + 180) % 360 - 180
        return max(-32767, min(32767, round(-error * 32767 / 10)))
    side = 1 if z > 0 else -1
    if y < radius:
        ny, nz = radius - y, side * flat / 2 - z
        k = math.hypot(ny, nz) or 1
        n = (0, ny / k, nz / k)
    else:
        n = (0, 0, -side)
    down = (0, -1 + n[1] * n[1], n[1] * n[2])   # gravity less its part along the normal
    v = (vx, vy, vz)
    cross = (v[1] * down[2] - v[2] * down[1], v[2] * down[0] - v[0] * down[2], v[0] * down[1] - v[1] * down[0])
    turn = 1 if sum(a * b for a, b in zip(cross, n)) > 0 else -1
    want = min(1, max(0, (y + max(vy, 0) ** 2 / 19.62 - .75 * height) / .5))
    return max(-32767, min(32767, round(-turn * want * 32767)))


def boost_ride(session, start, zone, recipe, wall=(4, 4), flat=6., frames=900):
    """Across the halfpipe of `wall` (radius, height) from `start` m/s in a boost zone of `zone` (None: no boost command
    at all), set off at the angle whose climb reaches 75% of the wall, carving as a player does, with Yorimichi's skate
    settings. `recipe`: 'pump' crouches (R2) on the flat and stands up through each wall, 'held' keeps R2 pulled, 'slide'
    powerslides on each wall, 'hard' holds a hard turn on each wall with no trigger, 'pump_hard' pumps and then holds a
    hard turn on each wall, 'coast' does none. Each frame's controls read the last frame's state. Returns the speed at
    each crossing of the flat's middle (between two of them is one wall) and the boost and physical pump over each wall."""
    radius, height = wall
    angle = math.degrees(math.acos(min(1, math.sqrt(2 * 9.81 * .75 * height) / start)))
    if session.generation:
        session.stop()
        session.start()
    session.generation += 1
    session.send('activate', spawn=[0, 0, 0], heading=math.radians(angle), goofy=False, difficulty='normal', trucks=.5,
                 generation=session.generation, feel=YORIMICHI_FEEL, **YORIMICHI_TUNE,
                 velocity=[start * math.sin(math.radians(angle)), 0, start * math.cos(math.radians(angle))])
    last, rows = session.read(), []
    if zone is not None:
        session.send('boost', zone=zone)
    for frame in range(frames):
        up, state = last['boost']['up'], last['state']
        ground = state in GROUND or state == 'SlideGround'
        trigger = PUMP_PULL if (recipe in ('pump', 'pump_hard') and ground and up > .985) or recipe == 'held' else 0
        wall = ground and up < .978
        left = (SLIDE_STICK if recipe == 'slide' and wall else HARD_TURN if recipe in ('hard', 'pump_hard') and wall
                else [carve(last, angle, radius, height, flat) if ground else 0, 0])
        session.send('step', dt=1 / 60, buttons=0, left=left, right=[0, 0], triggers=[0, trigger])
        last = session.read()
        rows.append(last)
    z = [r['root'][14] for r in rows]
    at = [i for i in range(1, len(rows)) if (z[i - 1] < 0) != (z[i] < 0)]
    speed3 = lambda r: math.sqrt(sum(v * v for v in r['velocity']))
    walls = [{'boost_mps': rows[j]['boost']['total'] - rows[i]['boost']['total'],
              'physical_pump_mps': sum(r['boost']['pump'] for r in rows[i + 1:j + 1]
                                       if r['state'] in GROUND and r['boost']['intentional'] and r['boost']['pump'] > 0),
              # ticks on the wall the simulation calls an intentional pump (a crouch, the trigger's or a hard turn's)
              'flagged_ticks': sum(1 for r in rows[i + 1:j + 1] if r['state'] in GROUND and r['boost']['up'] < .978
                                   and r['boost']['intentional'])}
             for i, j in zip(at, at[1:])]
    return {'crossings': [speed3(rows[i]) for i in at], 'walls': walls, 'boost': rows[-1]['boost']['total'], 'rows': rows,
            'bailed': any('Wipeout' in r['state'] for r in rows)}


def coast(session, feel, buttons=0, seconds=3, start=6):
    rows = session.ride(int(seconds * 60), lambda frame: (buttons, [0, 0], [0, 0]), feel, velocity=(0, 0, start))
    return {'end_speed_mps': speed(rows[-1]), 'distance_m': rows[-1]['root'][14] - rows[0]['root'][14]}


LIP = 95.


def bowl_wall(lip, transition=12., vert=2., start=-20., end=200., step=1.):
    """A bowl's outer wall round the origin: a floor ring, a `transition` m quarter rising to vertical at the lip `lip` m
    from the centre, `vert` m of vert and a deck behind, swept from `start` to `end` degrees in `step` degree facets."""
    base = lip - transition
    profile = ([(base - 30, 0.)] + [(base + transition * math.sin(math.radians(a)), transition * (1 - math.cos(math.radians(a))))
                                   for a in range(0, 91, 2)] + [(lip, transition + vert), (lip + 35, transition + vert)])
    point = lambda r, y, a: [r * math.cos(a), y, r * math.sin(a)]
    triangles = []
    for i in range(int((end - start) / step)):
        a0, a1 = math.radians(start + i * step), math.radians(start + (i + 1) * step)
        for (r0, y0), (r1, y1) in zip(profile, profile[1:]):
            q00, q01, q10, q11 = point(r0, y0, a0), point(r0, y0, a1), point(r1, y1, a0), point(r1, y1, a1)
            triangles += [[q00, q11, q10], [q00, q01, q11]]
    return triangles


RECOVER = 30  # frames (0.5 s) a landing must ride on afterwards without a wipeout


def wall_height(radius, lip=LIP, transition=12.):
    """The height of bowl_wall's transition `radius` m from the centre, or None off it (the floor, or behind the lip)."""
    base = lip - transition
    if not base < radius <= lip:
        return None
    return transition * (1 - math.sqrt(max(0., 1 - ((radius - base) / transition) ** 2)))


def landing(rows, deck):
    """The first air after riding the wall: its time, and where the board comes down (deck(row) its position; distance
    from the bowl's centre, height, and the wall's transition height there) on the first frame out of the air. An air
    that never leaves the air within the ride is not landed, and reports its last frame."""
    start = next((i for i, r in enumerate(rows) if 'Air' in r['state']), None)
    if start is None:
        return {'landed': False, 'air_s': 0, 'radius_m': 0, 'height_m': 0, 'states': sorted({r['state'] for r in rows})}
    end = next((i for i in range(start, len(rows)) if 'Air' not in rows[i]['state']), None)
    landed = end is not None
    end = len(rows) - 1 if end is None else end
    p = deck(rows[end])
    after = rows[end:end + RECOVER]
    return {'landed': landed, 'air_s': (end - start) / 60, 'radius_m': math.hypot(p[0], p[2]), 'height_m': p[1],
            'wall_height_m': wall_height(math.hypot(p[0], p[2])), 'state_after': rows[end]['state'],
            'launch_speed_along_mps': speed(rows[start]),
            'recovered': landed and len(after) == RECOVER and all('Ground' in r['state'] and 'Wipeout' not in r['state'] for r in after),
            'bailed': any('Wipeout' in r['state'] for r in rows[start:end + RECOVER])}


def on_wall(land):
    """A landing back on the wall: out of the air onto riding ground, on the transition (not the floor, not behind the
    lip, the board within 1 m of the wall's surface there) and riding on for RECOVER frames without a wipeout."""
    surface = land.get('wall_height_m')
    return bool(land['landed'] and land['recovered'] and not land['bailed'] and land['air_s'] > 1
                and 'Ground' in land['state_after'] and 'Wipeout' not in land['state_after']
                and surface is not None and land['height_m'] > 1 and abs(land['height_m'] - surface) < 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulation-package', type=Path, default=SIMULATION_PACKAGE)
    parser.add_argument('--binary', type=Path, default=BINARY, help='Already built offline simulation QA executable')
    args = parser.parse_args()
    if not args.binary.is_file():
        parser.error('Simulation QA executable is missing; build Tests/build_simulation_session_cli.py --compile under the render lock and memory guard first')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report, failures = {}, []

    def check(name, ok, detail):
        report.setdefault('checks', {})[name] = {'ok': bool(ok), 'detail': detail}
        if not ok:
            failures.append(name)

    flat = Session(args.binary, args.simulation_package, FLAT_WORLD, 'flat')
    try:
        # Stock feel, spelled out, is the session with no feel at all, bit for bit.
        ones = {k: 1 for k in ('flick_radius', 'flick_window', 'flick_pace', 'gravity', 'boneless', 'hippy',
                               'rail_magnetism', 'grind_pop', 'grind_friction', 'braking', 'steering', 'carve', 'grip',
                               'powerslide', 'rolling_friction', 'hill_speed', 'pump', 'wobble', 'wobble_onset',
                               'manual_drift', 'landing', 'impact', 'powerslide_turn', 'grind_tolerance', 'camera_follow')}
        ones.update(auto_push=-1, assisted_air=-1, tight_flicks=0, flick_120hz=0, drift_powerslide=0, drift_grip=.3, drift_full_grip=.6,
                    wall_follow=0)
        rides = [flat.ride(330, flick(18, 2), feel, velocity=(0, 0, 5)) for feel in (None, ones)]
        same = all(a['root'] == b['root'] and a['bones'] == b['bones'] and a['velocity'] == b['velocity'] for a, b in zip(*rides))
        check('defaults_exact', same, 'stock feel spelled out matches no feel over 330 frames, bit for bit')

        stock = jump(flat, None)
        report['stock_ollie'] = stock
        check('stock_ollie', not stock['bailed'] and stock['airtime_s'] > .3, stock)

        # Gravity: the height stays, the air time goes as 1/sqrt(gravity).
        report['gravity'] = {}
        for g in (.7, .85, 1.25):
            result = jump(flat, {'gravity': g})
            result['airtime_ratio'] = result['airtime_s'] / stock['airtime_s']
            result['expected_ratio'] = 1 / math.sqrt(g)
            report['gravity'][str(g)] = result
            check(f'gravity_{g}_height', abs(result['height_m'] - stock['height_m']) < .06 * stock['height_m'] + .02, result)
            check(f'gravity_{g}_airtime', abs(result['airtime_ratio'] - result['expected_ratio']) < .08 and not result['bailed'], result)

        # Flick pace: a slow snap (12 frames) pops higher with a lower pace, lower with a higher one.
        slow = {str(p): jump(flat, {'flick_pace': p}, snap=12) for p in (.6, 1, 1.6)}
        report['flick_pace_slow_snap'] = slow
        check('flick_pace_order', slow['0.6']['height_m'] >= slow['1']['height_m'] >= slow['1.6']['height_m']
              and slow['0.6']['height_m'] > slow['1.6']['height_m'], slow)

        # Tight flicks: a hardflip or inward heelflip flicked close to straight down then up (regular stance) reads as the
        # flip with the switch on; the authored wide arcs and a straight ollie read the same either way.
        flips = {'tight_hardflip': ([-110, -88, 112], 'HARDFLIP'), 'tight_inward_heelflip': ([-70, -92, 68], 'INWARD_HEELFLIP'),
                 'hardflip': ([-138, -82, 128], 'HARDFLIP'), 'inward_heelflip': ([-42, -98, 41], 'INWARD_HEELFLIP'),
                 'ollie': ([-90, 90], 'OLLIE')}
        tight = {name: {str(on): takeoff_trick(flat, angles, {'tight_flicks': on}) for on in (0, 1)}
                 for name, (angles, _) in flips.items()}
        report['tight_flicks'] = tight
        check('tight_flicks_read', all(tight[name]['1'] == trick for name, (_, trick) in flips.items()), tight)
        check('tight_flicks_keep_authored', all(tight[name]['0'] == trick for name, (_, trick) in flips.items()
                                                if not name.startswith('tight')), tight)

        # 120 Hz flicks: every flick above reads as at 60 Hz, from the host's readings between frames or (no readings:
        # another platform, injected input) from each frame's packet (read once a tick), with tight flicks off and on.
        fine = {}
        for name, (angles, _) in flips.items():
            for on in (0, 1):
                feel = {'tight_flicks': on, 'flick_120hz': 1}
                fine[f'{name}_{on}'] = {'readings': first_trick(flat, with_readings(arc(angles)), feel),
                                        'packet': first_trick(flat, arc(angles), feel), '60hz': tight[name][str(on)]}
        report['flick_120hz_tricks'] = fine
        check('flick_120hz_same_tricks', all(r['readings'] == r['60hz'] and r['packet'] == r['60hz'] for r in fine.values()), fine)

        # The window is a time at either rate: a hardflip slowed down reads at the same windows at 60 and 120 Hz,
        # and more window reads slower flicks.
        slowed = {}
        for by in (2, 3, 4):
            for window in (.5, 1, 2, 3):
                feel = {'flick_window': window}
                controls = stretched(arc(flips['hardflip'][0]), by)
                slowed[f'x{by}_{window}'] = {'60hz': first_trick(flat, controls, feel),
                                             '120hz': first_trick(flat, with_readings(controls), {**feel, 'flick_120hz': 1})}
        report['flick_120hz_window'] = slowed
        reads = lambda rate, by: [slowed[f'x{by}_{w}'][rate] == 'HARDFLIP' for w in (.5, 1, 2, 3)]
        check('flick_120hz_window_matches', all(reads('120hz', by) == reads('60hz', by) for by in (2, 3, 4)), slowed)
        check('flick_120hz_window_order', all(reads('120hz', by) == sorted(reads('120hz', by)) for by in (2, 3, 4))
              and any(not all(reads('120hz', by)) and any(reads('120hz', by)) for by in (2, 3, 4)), slowed)

        # The pace is a time too: read from the packet, a flick pops exactly as high at either rate; from the readings
        # its ends are found up to half a tick apart from 60 Hz's, so close to it; and a lower pace pops a slow snap
        # higher.
        paced = {f'{p}_{snap}': {'60hz': jump(flat, {'flick_pace': p}, snap=snap)['height_m'],
                                 '120hz_packet': jump(flat, {'flick_pace': p, 'flick_120hz': 1}, snap=snap)['height_m'],
                                 '120hz': jump(flat, {'flick_pace': p, 'flick_120hz': 1}, snap=snap, fine=True)['height_m']}
                 for p in (.6, 1, 1.6) for snap in (2, 12)}
        report['flick_120hz_pace'] = paced
        check('flick_120hz_pace_matches', all(r['120hz_packet'] == r['60hz'] and abs(r['120hz'] - r['60hz']) <= .12 * r['60hz']
                                              for r in paced.values()), paced)
        # On average over where a flick falls between frames, it pops as high at either rate (the tick count is unbiased).
        def snap_over(frames):
            return lambda t: (0, -1) if 150 <= t < 168 else (0, min(1, -1 + 2 * (t - 168) / frames)) if 168 <= t < 168 + frames + 1 else (0, 0)
        phases = [k / 8 for k in range(8)]
        unbiased = {}
        for frames in (6, 9):
            rides = {rate: [max(flat.deck_height(r) for r in flat.ride(330, sampled(snap_over(frames), phase), feel, velocity=(0, 0, 5)))
                            for phase in phases] for rate, feel in (('60hz', None), ('120hz', {'flick_120hz': 1}))}
            unbiased[str(frames)] = {rate: sum(h) / len(h) for rate, h in rides.items()}
        report['flick_120hz_pace_unbiased'] = unbiased
        check('flick_120hz_pace_unbiased', all(abs(r['120hz'] - r['60hz']) <= .04 * r['60hz'] for r in unbiased.values()), unbiased)
        check('flick_120hz_pace_order', paced['0.6_12']['120hz'] >= paced['1_12']['120hz'] >= paced['1.6_12']['120hz']
              and paced['0.6_12']['120hz'] > paced['1.6_12']['120hz'], paced)

        # A hardflip flicked in a sixtieth of a second through its bottom: the stick passes straight down between two
        # frames, so 60 Hz never sees it, and the 120 Hz readings do.
        point = lambda degrees, r=1.: (r * math.cos(math.radians(degrees)), r * math.sin(math.radians(degrees)))
        quick = [point(-138, r) for r in (.25, .5, .75)] + [point(-138)] * 5 + [point(-82)]
        (ax, ay), (bx, by) = point(-82), point(128)
        quick += [(ax + (bx - ax) * k / 2, ay + (by - ay) * k / 2) for k in (1, 2)] + [point(128)] * 5
        fast = {'60hz': first_trick(flat, traced(quick), {'tight_flicks': 1}),
                '120hz': first_trick(flat, traced(quick), {'tight_flicks': 1, 'flick_120hz': 1}),
                '120hz_packet': first_trick(flat, lambda frame: traced(quick)(frame)[:3], {'tight_flicks': 1, 'flick_120hz': 1})}
        report['flick_120hz_fast_hardflip'] = fast
        check('flick_120hz_fast_hardflip', fast['120hz'] == 'HARDFLIP' and fast['60hz'] != 'HARDFLIP'
              and fast['120hz_packet'] == fast['60hz'], fast)

        # Rolling resistance: the board holds its cruising speed on the flat, and rolling resistance bleeds off the speed
        # above it, so coast from 14 m/s. Then braking.
        rolling = {str(f): coast(flat, {'rolling_friction': f}, seconds=5, start=14) for f in (0, .5, 1, 2)}
        report['rolling_friction'] = rolling
        check('rolling_friction_order', rolling['0']['end_speed_mps'] >= rolling['0.5']['end_speed_mps']
              >= rolling['1']['end_speed_mps'] >= rolling['2']['end_speed_mps']
              and rolling['0']['end_speed_mps'] > rolling['2']['end_speed_mps'] + 1, rolling)
        braking = {str(b): coast(flat, {'braking': b}, buttons=BRAKE, seconds=1.5) for b in (.5, 1, 2)}
        report['braking'] = braking
        check('braking_order', braking['0.5']['distance_m'] >= braking['1']['distance_m'] >= braking['2']['distance_m']
              and braking['0.5']['distance_m'] > braking['2']['distance_m'], braking)

        # Powerslides. The stick dead straight down (inside the per-axis dead zone sideways) slides only as a drift, which
        # also takes a slide from part tilt (stock wants full tilt) and grips as far as the stick is pulled down. Let go,
        # a drift brings the board back round under the rider, so it keeps its speed and its line where stock's line
        # swings round to the board and scrubs. A lower powerslide turn turns the board across its travel less.
        drift = {'drift_powerslide': 1}
        slides = {'stock_straight': powerslide(flat, None, 0, 1), 'stock_part': powerslide(flat, None, 0, .7),
                  'drift_straight': powerslide(flat, drift, 0, 1), 'drift_part': powerslide(flat, drift, 0, .7),
                  'stock_short_14': powerslide(flat, None, -2, 1, 14, 30), 'drift_short_14': powerslide(flat, drift, 0, 1, 14, 30),
                  'stock_diagonal': powerslide(flat, None, 25, 1), 'turn_0.6': powerslide(flat, {'powerslide_turn': .6}, 25, 1)}
        report['powerslide'] = slides
        check('powerslide_drift_straight_down', not slides['stock_straight']['frames'] and slides['drift_straight']['frames']
              and not slides['stock_part']['frames'] and slides['drift_part']['frames'], slides)
        check('powerslide_drift_depth', slides['drift_part']['loss_mps_per_s'] < slides['drift_straight']['loss_mps_per_s'], slides)
        check('powerslide_drift_line', slides['drift_short_14']['speed_after'] > slides['stock_short_14']['speed_after'] + 3
              and slides['drift_short_14']['line_turn_deg'] < slides['stock_short_14']['line_turn_deg'] - 20, slides)
        check('powerslide_turn', slides['turn_0.6']['frames'] and slides['turn_0.6']['board_peak_deg'] < slides['stock_diagonal']['board_peak_deg'], slides)
    finally:
        flat.close()

    # An assist zone's limit on the vert assist: a straight air up a 55-degree quarter with assist 1 and the limit at L
    # rides exactly as assist L; the limit at 1 changes nothing.
    radius, lip = 4., math.radians(55)
    quarter = [(-40, 0), (10, 0)] + [(10 + radius * math.sin(lip * k / 24), radius * (1 - math.cos(lip * k / 24))) for k in range(1, 25)]
    triangles = [t for (z0, y0), (z1, y1) in zip(quarter, quarter[1:])
                 for t in ([[-20, y0, z0], [-20, y1, z1], [20, y1, z1]], [[-20, y0, z0], [20, y1, z1], [20, y0, z0]])]
    session = Session(args.binary, args.simulation_package, {'triangles': triangles, 'rails': [], 'spawn': [0, 0, -30], 'heading': 0}, 'quarter')
    try:
        still = lambda frame: (0, [0, 0], [0, 0])
        air = lambda va, limit=None: session.ride(300, still, None, velocity=(0, 0, 11), spawn=(0, 0, -30), tune={'vert_assist': va}, limit=limit)
        same = lambda a, b: all(x['root'] == y['root'] and x['velocity'] == y['velocity'] for x, y in zip(a, b))
        full, half, none = air(1), air(.5), air(0)
        limited = {'1': same(air(1, 1), full), '0.5': same(air(1, .5), half), '0': same(air(1, 0), none)}
        report['vert_assist_limit'] = limited
        check('vert_assist_limit', all(limited.values()) and not same(full, none), limited)
    finally:
        session.close()

    # Boost zones (README "Boost zones"): across a halfpipe of 4 m transitions from 20 m/s as a player carves it,
    # pumping (R2 pulled on the flat, let go through each wall). At this speed the physical pump adds almost nothing, and
    # a boost that only multiplied it added nothing either. Now each wall a pump stands up on gains its own boost, so the
    # ride in a zone of scale 1 stays well ahead of the same ride out of one, wall after wall, below the cap (20 m/s x
    # 1.8, BowlBoost::CapRise); holding R2 through the walls is a crouch and gains nothing; out of every zone (scale 0)
    # the ride is the plain one, bit for bit. A powerslide on a 3 m bank gains 3 m/s or more over the wall, where out of
    # a zone it scrubs off more than that. On a flat world the zone adds nothing, bit for bit.
    session = Session(args.binary, args.simulation_package, halfpipe(4, 4, width=1200), 'boost_halfpipe')
    try:
        plain, outside, pumped, held, held_plain = (boost_ride(session, 20, zone, recipe) for zone, recipe in
                                                    ((None, 'pump'), (0, 'pump'), (1, 'pump'), (1, 'held'), (0, 'held')))
        same = lambda a, b: all(x['root'] == y['root'] and x['velocity'] == y['velocity'] for x, y in zip(a['rows'], b['rows']))
        summary = lambda ride: {'crossings_mps': [round(v, 2) for v in ride['crossings'][:6]], 'boost_mps': round(ride['boost'], 2),
                                'walls': [{k: round(v, 2) for k, v in w.items()} for w in ride['walls'][:5]], 'bailed': ride['bailed']}
        report['boost_halfpipe'] = {'plain': summary(plain), 'zone_0': summary(outside), 'zone_1': summary(pumped),
                                    'held_zone_1': summary(held), 'held_zone_0': summary(held_plain)}
        check('boost_outside_exact', same(plain, outside) and plain['boost'] == outside['boost'] == 0, report['boost_halfpipe'])
        walls = pumped['walls'][:3]
        check('boost_pump_gains', len(walls) >= 2 and all(w['boost_mps'] >= BOOST_WALL_MIN and w['physical_pump_mps'] < .5 for w in walls)
              and len(outside['crossings']) >= 3 and not pumped['bailed']
              and pumped['crossings'][2] >= outside['crossings'][2] + 2 * BOOST_AHEAD_MIN, report['boost_halfpipe'])
        check('boost_held_none', held['boost'] < .5 and len(held['crossings']) >= 2 and len(held_plain['crossings']) >= 2
              and abs(held['crossings'][1] - held_plain['crossings'][1]) < .5, report['boost_halfpipe'])
        check('boost_pump_cap', max(pumped['crossings']) <= 20 * 1.8, report['boost_halfpipe'])
        # A hard turn crouches the rider and the simulation calls it an intentional pump; with no trigger it is no pump,
        # however long it is held: the ride is the plain one, bit for bit. After a real R2 pump, a hard turn held on
        # through the wall gains only that pump's stand-up (0.7 s x 6 m/s^2, BowlBoost::StandTime), not the turn's.
        hard, hard_plain, pump_hard = (boost_ride(session, 20, zone, recipe) for zone, recipe in
                                       ((1, 'hard'), (0, 'hard'), (1, 'pump_hard')))
        report['boost_hard_turn'] = {'hard_zone_1': summary(hard), 'pump_hard_zone_1': summary(pump_hard)}
        check('boost_hard_turn_none', same(hard, hard_plain) and hard['boost'] == 0
              and sum(w['flagged_ticks'] for w in hard['walls']) > 30, report['boost_hard_turn'])
        check('boost_pump_expires', len(pump_hard['walls']) >= 2 and all(w['boost_mps'] <= .7 * 6 + .1 for w in pump_hard['walls'])
              and any(w['flagged_ticks'] > 42 for w in pump_hard['walls']) and pump_hard['walls'][0]['boost_mps'] >= BOOST_WALL_MIN,
              report['boost_hard_turn'])
    finally:
        session.close()
    session = Session(args.binary, args.simulation_package, halfpipe(8, 3, width=1200), 'boost_bank')
    try:
        slid, slid_plain = (boost_ride(session, 10, zone, 'slide', wall=(8, 3), frames=600) for zone in (1, 0))
        report['boost_slide'] = {'zone_1': {'crossings_mps': [round(v, 2) for v in slid['crossings'][:3]], 'boost_mps': round(slid['boost'], 2)},
                                 'zone_0': {'crossings_mps': [round(v, 2) for v in slid_plain['crossings'][:3]]}}
        check('boost_slide_gains', len(slid['crossings']) >= 2 and len(slid_plain['crossings']) >= 2
              and slid['crossings'][1] > slid['crossings'][0] + 3 and slid['crossings'][1] > slid_plain['crossings'][1] + 3, report['boost_slide'])
    finally:
        session.close()
    session = Session(args.binary, args.simulation_package, FLAT_WORLD, 'boost_flat')
    try:
        flat_plain, flat_zone = (boost_ride(session, 12, zone, 'pump', frames=240) for zone in (None, 1))
        report['boost_flat'] = {'boost_mps': flat_zone['boost']}
        check('boost_flat_none', all(x['root'] == y['root'] and x['velocity'] == y['velocity']
                                     for x, y in zip(flat_plain['rows'], flat_zone['rows'])) and flat_zone['boost'] == 0, report['boost_flat'])
    finally:
        session.close()

    # Wall follow: a bowl's outer wall swept round a 95 m lip in 1 degree facets (a 12 m transition, 2 m of vert, a deck
    # behind), ridden into from the floor at 38 and 40 m/s along it with no input: about 28 and 30 m/s along the lip and
    # 3 s of air. Stock flies on along the tangent and lands behind the lip, or off the deck; with wall_follow 1 the air
    # turns round the bowl and comes back down onto the wall. A zero-assist zone, or no vert assist, rides
    # wall_follow 1 exactly as 0, bit for bit.
    # The landing check itself first, on made-up frames: an air still flying at the end of the ride (30 frames riding,
    # then 390 in the air 95 m out and 50 m up) or one landing on the floor is not a landing on the wall.
    frame = lambda state, p: {'state': state, 'p': p, 'velocity': [0, 0, 30]}
    still_flying = [frame('PhysicsGround', [LIP, 50, 0])] * 30 + [frame('PhysicsAir', [LIP, 50, 0])] * 390
    on_floor = [frame('PhysicsGround', [LIP, 0, 0])] * 30 + [frame('PhysicsAir', [LIP, 20, 0])] * 120 + [frame('PhysicsGround', [80, .1, 0])] * 60
    on_transition = [frame('PhysicsGround', [LIP, 0, 0])] * 30 + [frame('PhysicsAir', [LIP, 20, 0])] * 120 + [frame('PhysicsGround', [94.3, 8.2, 0])] * 60
    synthetic = {name: on_wall(landing(rows, lambda r: r['p'])) for name, rows in
                 (('still_flying', still_flying), ('on_floor', on_floor), ('on_transition', on_transition))}
    check('wall_follow_landing_check', synthetic == {'still_flying': False, 'on_floor': False, 'on_transition': True}, synthetic)

    triangles = bowl_wall(LIP)
    spawn = [LIP - 12.5, 0, 0]
    session = Session(args.binary, args.simulation_package, {'triangles': triangles, 'rails': [], 'spawn': spawn, 'heading': 0}, 'bowl')
    try:
        still = lambda frame: (0, [0, 0], [0, 0])
        ride = lambda wall, speed, limit=None, assist=1: session.ride(420, still, {'wall_follow': wall}, velocity=(0, 0, speed),
                                                                     spawn=spawn, tune={'vert_assist': assist}, limit=limit)
        same = lambda a, b: all(x['root'] == y['root'] and x['bones'] == y['bones'] and x['velocity'] == y['velocity'] for x, y in zip(a, b))
        deck = lambda r: [sum(r['bones'][session.deck][12 + k] * r['root'][k * 4 + j] for k in range(4)) for j in range(3)]
        walls = {str(v): {'stock': landing(ride(0, v), deck), 'followed': landing(ride(1, v), deck)} for v in (38, 40)}
        exact = {'zero_assist_zone': same(ride(1, 40, 0), ride(0, 40, 0)), 'no_assist': same(ride(1, 40, None, 0), ride(0, 40, None, 0))}
        report['wall_follow'] = {**walls, 'exact': exact}
        check('wall_follow_stock_lands_behind', all(w['stock']['air_s'] > 1 and w['stock']['radius_m'] > LIP + 3
                                                    and not on_wall(w['stock']) for w in walls.values()), walls)
        check('wall_follow_lands_on_wall', all(on_wall(w['followed']) for w in walls.values()), walls)
        check('wall_follow_zero_assist_exact', all(exact.values()), exact)
    finally:
        session.close()

    # Rail magnetism: a 40 cm rail beside the line of travel, from close (stock grinds) to beyond stock's reach. More
    # magnetism grinds from farther, less from nearer.
    report['rail'] = {}
    for offset in (1.5, 2, 2.5, 3, 3.5):
        rail = [[offset, .4, -20], [offset, .4, 60]]
        session = Session(args.binary, args.simulation_package,
                          {'triangles': FLAT, 'rails': [rail], 'spawn': [0, 0, 0], 'heading': 0}, f'rail_{offset}')
        try:
            row = {}
            for magnetism in (.5, 1, 2, 3):
                rows = session.ride(330, flick(18, 2), {'rail_magnetism': magnetism}, velocity=(0, 0, 5))
                row[str(magnetism)] = any('Grind' in r['state'] for r in rows)
            report['rail'][str(offset)] = row
        finally:
            session.close()
    rails = report['rail']
    widened = any(not r['1'] and (r['2'] or r['3']) for r in rails.values())
    narrowed = any(r['1'] and not r['0.5'] for r in rails.values())
    monotonic = all(not (r['1'] and not r['3']) and not (r['0.5'] and not r['1']) for r in rails.values())
    check('rail_magnetism_widens', widened and monotonic, rails)
    check('rail_magnetism_narrows', narrowed and monotonic, rails)

    report['passed'] = not failures
    report['failures'] = failures
    (OUTPUT / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
