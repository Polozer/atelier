"""Record an in-game gameplay film of the Kasa Ronin Mini-Camp and the upgraded sword-fighting mechanics.

Usage (inside live py):
    atelier live py - < games/yorimichi/scenarios/ronin_camp_film.py
"""
import json
import math
import os
import random
import traceback
import unreal

L = live.L
YL = unreal.YorimichiLive
MV = unreal.MegaParkValidation
OUT = os.path.join(os.environ.get('ATELIER_BUILD_ROOT') or os.path.join(live.ROOT, 'build'), 'yorimichi/swordcamp/film')
os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):
    if f.endswith(('.jpg', '.png', '.json')):
        os.remove(os.path.join(OUT, f))

pc = unreal.GameplayStatics.get_player_controller(L.game_world(), 0)
rng = random.Random(19)
st = {'frames': [], 'errors': [], 'sim': 0, 'film': 0, 'rec': False, 'label': '', 'cam_eye': None, 't': 0., 'next': 0.}

# Camp center in Blender (-54.0, -94.0, 8.1) -> UE cm (-5400.0, 9400.0, 810.0)
CAMP_UE = unreal.Vector(-5400.0, 9400.0, 810.0)
APPROACH_UE = unreal.Vector(-5500.0, 7600.0, 1050.0)


def trainer():
    try:
        return json.loads(YL.trainer_state())
    except Exception:
        return {}


def wait(seconds):
    t = 0.0
    while t < seconds:
        t += (yield)


def label(text):
    st['label'] = text
    st['rec'] = True
    unreal.log(f'RONIN FILM | {text}')


def cut():
    st['rec'] = False


def camp_camera(mode='side'):
    p = L.player().get_actor_location()
    k = trainer().get('location') or [CAMP_UE.x, CAMP_UE.y, CAMP_UE.z + 90.0]
    if mode == 'overview':
        eye = unreal.Vector(CAMP_UE.x - 620.0, CAMP_UE.y - 680.0, CAMP_UE.z + 360.0)
        at = unreal.Vector(CAMP_UE.x + 40.0, CAMP_UE.y + 80.0, CAMP_UE.z + 110.0)
        MV.review_camera(eye, at, 60.0)
        return
    mx, my, mz = (p.x + k[0]) * 0.5, (p.y + k[1]) * 0.5, (p.z + k[2]) * 0.5
    dx, dy = k[0] - p.x, k[1] - p.y
    n = math.hypot(dx, dy) or 1.0
    ex, ey = mx - dy / n * 480.0, my + dx / n * 480.0
    eye = unreal.Vector(ex, ey, mz + 145.0)
    st['cam_eye'] = eye if st.get('cam_eye') is None else st['cam_eye'] * 0.88 + eye * 0.12
    at = unreal.Vector(mx, my, mz + 30.0)
    MV.review_camera(st['cam_eye'], at, 58.0)


def approach_scene():
    """Scene 1: Overview of the Kasa Ronin Mini-Camp and approaching from the coastal road."""
    MV.restore_player_camera()
    L.teleport_player(L.ground_at(APPROACH_UE), 90.0)
    pc.set_control_rotation(unreal.Rotator(roll=0, pitch=-8, yaw=90.0))
    yield from wait(1.0)
    label('Coastal Bluff Mini-Camp: 3 Kasa Ronin & Sunburst Procedural Props')
    t = 0.0
    while t < 2.2:
        camp_camera('overview')
        t += (yield)
    MV.restore_player_camera()
    label('Approaching from the coastal road: Guard practices on the Makiwara post')
    live.drive(1.0, 0.0, 'run')
    t = 0.0
    while t < 2.8:
        p = L.player().get_actor_location()
        yaw = math.degrees(math.atan2(CAMP_UE.y - p.y, CAMP_UE.x - p.x))
        pc.set_control_rotation(unreal.Rotator(roll=0, pitch=-6, yaw=yaw))
        t += (yield)
    live.drive(0.0)
    cut()


def combat_scene():
    """Scene 2 & 3: Camp alert, sword combos, parries, whiff-punishes, and charged spin."""
    st['cam_eye'] = None
    label('Camp Alert: Kasa Ronin draw their blades & coordinate via UJapanEncounters')
    t = 0.0
    while t < 11.0:
        dt = (yield)
        st['t'] += dt
        t += dt
        p = L.player().get_actor_location()
        k = trainer().get('location') or [CAMP_UE.x, CAMP_UE.y, CAMP_UE.z + 90.0]
        yaw = math.degrees(math.atan2(k[1] - p.y, k[0] - p.x))
        pc.set_control_rotation(unreal.Rotator(roll=0, pitch=-8, yaw=yaw))
        d = math.hypot(k[0] - p.x, k[1] - p.y)
        if t > 3.5 and t < 7.0:
            st['label'] = 'Sword Clash: Pre-primed blade sweeps, directional staggers & parries'
        elif t >= 7.0:
            st['label'] = 'Charged Spin & Guard Break against the Kasa Ronin squad'
        if st.get('release') and st['t'] > st['release']:
            live.press('guard_release')
            st['release'] = None
        if st.get('charge_until') and st['t'] > st['charge_until']:
            live.press('attack_release')
            st['charge_until'] = None
        if st['t'] >= st['next']:
            if d > 220.0:
                live.press('guard_release')
                live.drive(1.0, 0.0, 'run')
                st['next'] = st['t'] + 0.15
            else:
                live.drive(0.0)
                r = rng.random()
                if t >= 7.2 and not st.get('did_spin'):
                    st['did_spin'] = True
                    live.press('attack')
                    st['charge_until'] = st['t'] + 1.25
                    st['next'] = st['t'] + 1.8
                elif r < 0.58:
                    for _ in range(rng.randint(2, 3)):
                        live.press('attack')
                        live.press('attack_release')
                    st['next'] = st['t'] + rng.uniform(0.75, 1.2)
                elif r < 0.82:
                    live.press('guard')
                    live.press('jump')
                    live.press('jump_release')
                    st['next'] = st['t'] + 0.85
                    st['release'] = st['next']
                else:
                    live.drive(rng.choice([-1.0, 1.0]), 0.0, 'run')
                    live.press('dodge')
                    st['next'] = st['t'] + 0.9
        camp_camera('side')
    cut()


def steps():
    for name, fn in [('approach', approach_scene), ('combat', combat_scene)]:
        try:
            L.fixed_step(60)
            yield from fn()
        except Exception:
            st['errors'].append({'section': name, 'error': traceback.format_exc()})
            unreal.log_warning(f'RONIN FILM {name} failed: {traceback.format_exc()}')
        cut()
        live.drive(0.0)
        L.fixed_step(0)


def run(dt):
    dt = unreal.GameplayStatics.get_world_delta_seconds(L.game_world())
    if st.get('gen') is None:
        st['gen'] = steps()
        next(st['gen'])
        return
    try:
        st['gen'].send(dt)
    except StopIteration:
        return finish()
    if st['rec']:
        if st['sim'] % 2 == 0:
            L.screenshot(os.path.join(OUT, 'frame_%05d.jpg' % st['film']))
            st['frames'].append([st['film'], st['label']])
            st['film'] += 1
        st['sim'] += 1


def finish():
    live.stop('ronin_camp_film')
    live.drive(0.0)
    L.fixed_step(0)
    MV.restore_player_camera()
    json.dump({'frames': st['frames'], 'errors': st['errors']}, open(os.path.join(OUT, 'done.json'), 'w'))
    unreal.log('RONIN FILM DONE')


live.behave('ronin_camp_film', run)
print('RONIN FILM started', OUT)
