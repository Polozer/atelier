#!/usr/bin/env python3
"""Belmonte skate rides (requires the normal game build): every grind family, and walls that stop the board.

    atelier qa yorimichi belmonte_grind [--port 8830] [--only NAME ...]

For each family it takes a real line from the build's runtime.json (`rails`, belmonte/skate.py): the bench seat and
backrest, a stone bench, a planter, the piazza fountain's rim, a low wall, a field wall run through its joins, a
kerb, a shop-window ledge and a market stall's counter. The rider starts 8 m short of a point 1 m along the line,
at 6 m/s, flicks the ollie 5 m before it (the board leaves the ground about 2 m later) and must lock onto it (mode 3),
grind at least half of it (or 4 m), never bail. It comes in along the line, then 25 degrees from either side: an end
can be blocked (a stall's post, a bench's leg), and the first approach that locks counts. An approach whose start is
not on the line's ground (more than 1.2 m above it) is skipped.
A screenshot is taken a moment into each grind. Then three building walls are ridden into square at 12 m/s: the
board must stop at the wall's collision (never more than 35 cm past its plane). Results go to
build/yorimichi/skateqa/belmonte/belmonte_grind.json with the screenshots beside it.
"""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

import skate as qa
from skate import yori  # noqa: F401  (world/ on the path)

OUT = yori.OUT / 'skateqa' / 'belmonte'
RUNTIME = yori.OUT / 'belmonte' / 'runtime.json'
SPEED = 600.            # cm/s
LEAD = 8.               # metres before the line where the ride starts
POP = 5.                # metres before the line where the ollie flick starts (the board leaves ~2 m later)
APPROACHES = (0., 25., -25.)  # degrees off the line's direction, tried in turn
AIM = 1.                # metres along the line where the approach aims
WALL_SPEED = 1200.      # cm/s into a wall
WALL_PAST = .35         # metres the board may sink past a wall's plane
# Family -> (id prefix, kind of line): the representative line is the longest straight one in the town.
FAMILIES = {
    'bench_seat': ('BP_Bench_', '_lip'), 'bench_backrest': ('BP_Bench_', '_bar'),
    'stone_bench': ('BP_StoneBench_', '_lip'), 'planter': ('BP_StonePlanter_', '_lip'),
    'fountain_rim': ('BH_FountainPiazza_', '_lip'), 'low_wall': ('BC_Works_', '_lip'),
    'field_wall_run': ('BVV_StoneWall_', '_lip'), 'kerb': ('BT_Terrain_', '_lip'),
    'shop_ledge': ('BT_blk_', '_bar'), 'stall_counter': ('BP_StallGoods_', '_lip'),
}
TOWN = (-171., -215., 184., 144.)     # plan metres around the town's blocks (belmonte_skate_audit's box)

# In game: place, launch and record in Belmonte plan metres (x east, y north, z up from the region's origin).
LIVE = '''
import json, math, unreal
def _bm_ue(x, y, z):
    return unreal.Vector(ORIGIN[0] + x * 100, ORIGIN[1] - y * 100, ORIGIN[2] + z * 100)
def bm_ride(x, y, z, heading, speed, pop, duration, shot=None, shot_after=.35):
    """pop: metres rolled before the ollie flick (None: no ollie)."""
    # GroundAt traces down from 20 m over its point: start the trace 1.5 m over the line, under eaves and trees.
    at = live.L.ground_at(_bm_ue(x, y, z + 1.5 - 20.))
    live.skate_place(at, -heading)
    pc = unreal.GameplayStatics.get_player_controller(live.L.game_world(), 0)
    pc.set_control_rotation(unreal.Rotator(0, -14, -heading))
    h = math.radians(heading)
    live.L.skate_launch(unreal.Vector(speed * math.cos(h), -speed * math.sin(h), 0))
    live.REC = []
    state = {'t': 0., 'lock': None, 'shot': False, 'popped': pop is None}
    def record(dt):
        s = live.L.skate_state()
        live.REC.append(s)
        state['t'] += dt
        # The flick starts once the rider has rolled `pop` metres along the heading, whatever the frame rate or speed.
        p = live.L.player().get_actor_location() - at
        if not state['popped'] and (p.x * math.cos(h) - p.y * math.sin(h)) / 100 >= pop:
            live.flick('ollie'); state['popped'] = True
        if 'mode=3' in s and state['lock'] is None:
            state['lock'] = state['t']
        if shot and not state['shot'] and state['lock'] is not None and state['t'] - state['lock'] >= shot_after:
            live.L.screenshot(shot); state['shot'] = True
        if state['t'] >= duration:
            live.stop('rec')
    live.behave('rec', record)
live.bm_ride = bm_ride
'''


def position(row):
    return np.array([float(v) for v in row['pos'].strip('()').split(',')])


def plan(origin, p):
    """UE cm -> Belmonte plan metres."""
    return (p - origin) / [100., -100., 100.]


def lines():
    data = json.loads(RUNTIME.read_text())
    out = {}
    for name, (prefix, kind) in FAMILIES.items():
        best = None
        for rail in data['rails']:
            if not rail['id'].startswith(prefix) or kind not in rail['id']:
                continue
            p = np.asarray(rail['points']) / [100., -100., 100.]
            if not ((p[:, 0] > TOWN[0]) & (p[:, 0] < TOWN[2]) & (p[:, 1] > TOWN[1]) & (p[:, 1] < TOWN[3])).all():
                if name != 'field_wall_run':
                    continue
            d = p[-1] - p[0]
            length = float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())
            straight = float(np.linalg.norm(d[:2])) / max(length, 1e-6)
            score = length * straight ** 4 + (1000 if '+' in rail['id'] and name == 'field_wall_run' else 0)
            if best is None or score > best[0]:
                best = (score, rail['id'], p)
        if best:
            out[name] = (best[1], best[2])
    return data['origin_cm'], out


def attempt(name, p, origin, offset):
    """One approach `offset` degrees off the line's direction: (rows, why skipped or None)."""
    a = p[0]; u = (p[1] - p[0]) * [1, 1, 0]; u /= np.linalg.norm(u)
    length = float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())
    c, s = math.cos(math.radians(offset)), math.sin(math.radians(offset))
    d = np.array([u[0] * c - u[1] * s, u[0] * s + u[1] * c, 0.])
    run = np.concatenate([[0.], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])
    target = np.array([np.interp(min(AIM, length / 3), run, p[:, k]) for k in range(3)])     # on the line, curved or not
    start = target - d * LEAD
    heading = math.degrees(math.atan2(d[1], d[0]))
    duration = (LEAD + length) / (SPEED / 100) + 1.5
    shot = OUT / f'{name}.png'
    qa.py(f"live.bm_ride({start[0]:.3f},{start[1]:.3f},{target[2]:.3f},{heading:.2f},{SPEED},{LEAD - POP:.3f},"
          f"{duration:.2f},{str(shot)!r})")
    time.sleep(duration + .8)
    rows = [qa.parse(r) for r in json.loads(qa.py('import json; live.stop("rec"); print(json.dumps(live.REC))').strip().splitlines()[-1])]
    above = plan(origin, position(rows[0]))[2] - target[2] if rows else 0.
    return rows, (f'start {above:.1f} m above the line' if above > 1.2 else None)


def ride(name, rail_id, p, origin):
    a = p[0]; u = (p[1] - p[0]) * [1, 1, 0]; u /= np.linalg.norm(u)
    length = float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())
    shot = OUT / f'{name}.png'
    tried = []
    for offset in APPROACHES:
        rows, skipped = attempt(name, p, origin, offset)
        locked = [i for i, r in enumerate(rows) if r.get('mode') == '3']
        bails = qa.count(rows, 'bails') if rows and 'bails' in rows[0] else 0
        tried.append(f'{offset:+.0f} deg: ' + (skipped or ('locked' if locked else 'never locked') + (f', {bails} bail(s)' if bails else '')))
        if locked and not skipped:
            break
    along, speeds = 0., (0., 0.)
    if locked:
        q = np.array([plan(origin, position(rows[i])) for i in locked])
        along = float(np.ptp((q - a) @ u))
        speeds = (float(rows[locked[0]]['speed']), float(rows[locked[-1]]['speed']))
    need = min(4., length / 2)
    ok = bool(locked) and along >= need and not bails and not skipped
    note = (f'{rail_id}: line {length:.1f} m at {a[2]:.2f} m; ' + (f'locked {len(locked) / 60:.2f} s, ground {along:.1f} m, '
            f'{speeds[0]:.0f} -> {speeds[1]:.0f} cm/s' if locked else 'never locked') + (f', {bails} bail(s)' if bails else '')
            + f'; {qa.combos(rows)}; approaches: ' + ' / '.join(tried))
    return {'ok': ok, 'note': note, 'shot': str(shot) if shot.exists() else None, 'frames': len(rows)}


def walls(origin):
    """Three building facades, ridden into square, north from the street: (name, start plan m, heading, metres to the
    wall's plane at deck height). The wall is the first face of the block's generated collision on the ride's line."""
    from belmonte import props, skate, source
    data = props.apply(source.manifest(), yori.OUT / 'belmonte' / 'props')
    glb = yori.OUT / 'belmonte' / 'glb'
    picks = []
    for _, entry, transform in skate.placements(data):
        if not entry['name'].startswith('SM_BM_BT_blk_'):
            continue
        path = glb / (entry['name'] + '_Collision.glb')
        if not path.exists():
            continue
        faces = skate.to_world(transform, source.triangles(path))
        points = faces.reshape(-1, 3)
        x, z = float(np.median(points[:, 0])), float(points[:, 2].min()) + .5
        y0 = float(points[:, 1].min()) - 10.
        hit = None
        for t in faces:
            n = np.cross(t[1] - t[0], t[2] - t[0])
            if abs(n[1]) < 1e-9:
                continue
            y = t[0][1] - (n[0] * (x - t[0][0]) + n[2] * (z - t[0][2])) / n[1]
            w = np.array([x, y, z])
            # Inside the triangle: same side of all three edges as seen along y.
            e = [np.cross(t[(k + 1) % 3] - t[k], w - t[k]) @ n for k in range(3)]
            if (all(v >= -1e-9 for v in e) or all(v <= 1e-9 for v in e)) and y > y0 and (hit is None or y < hit):
                hit = y
        if hit is not None:
            picks.append((entry['name'][6:], np.array([x, y0, z - .5]), 90., hit - y0))
        if len(picks) == 3:
            break
    return picks


def wall_ride(name, start, heading, distance, origin):
    duration = 3.
    qa.py(f"live.bm_ride({start[0]:.3f},{start[1]:.3f},{start[2]:.3f},{heading:.2f},{WALL_SPEED},None,{duration})")
    time.sleep(duration + .8)
    rows = [qa.parse(r) for r in json.loads(qa.py('import json; live.stop("rec"); print(json.dumps(live.REC))').strip().splitlines()[-1])]
    travel = max(float(plan(origin, position(r))[1] - start[1]) for r in rows)
    shot = OUT / f'wall_{name}.png'
    qa.py(f'live.L.screenshot({str(shot)!r})')
    ok = travel <= distance + WALL_PAST
    return {'ok': bool(ok), 'note': f'{name}: wall {distance:.1f} m ahead, the board went {travel:.2f} m', 'frames': len(rows),
            'shot': str(shot)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--port', type=int, default=8830)
    parser.add_argument('--only', nargs='*')
    args = parser.parse_args()
    qa.bridge.URL = f'http://127.0.0.1:{args.port}'
    OUT.mkdir(parents=True, exist_ok=True)
    origin, chosen = lines()
    origin = np.asarray(origin, float)
    qa.py(f'_O = {[float(v) for v in origin]!r}\n' + LIVE.replace('ORIGIN', '_O'))
    qa.py('live.skate_input()')
    results = {}
    first = True
    for name, (rail_id, p) in chosen.items():
        if args.only and name not in args.only:
            continue
        if first:       # streaming Belmonte in: place once and wait for a steady frame rate
            qa.py(f"live.skate_place(live.L.ground_at(unreal.Vector({origin[0] + p[0, 0] * 100},{origin[1] - p[0, 1] * 100},"
                  f"{origin[2] + (p[0, 2] + 5) * 100})), 0)")
            time.sleep(8); qa.settle(minimum=30, seconds=2, limit=120); first = False
        results[name] = ride(name, rail_id, p, origin)
        print(('PASS ' if results[name]['ok'] else 'FAIL ') + name + ': ' + results[name]['note'], flush=True)
    if not args.only or 'walls' in args.only:
        for name, start, heading, distance in walls(origin):
            results['wall_' + name] = r = wall_ride(name, start, heading, distance, origin)
            print(('PASS ' if r['ok'] else 'FAIL ') + 'wall_' + name + ': ' + r['note'], flush=True)
    (OUT / 'belmonte_grind.json').write_text(json.dumps(results, indent=1) + '\n')
    failed = [k for k, v in results.items() if not v['ok']]
    print(f'{len(results) - len(failed)}/{len(results)} passed' + (f'; failed: {failed}' if failed else ''), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
