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
st = {'frames': [], 'errors': [], 'facing_samples': [], 'sim': 0, 'film': 0, 'rec': False, 'label': '', 'cam_eye': None, 't': 0., 'next': 0.}

# Camp center in Blender (-54.0, -94.0, 8.1) -> UE cm (-5400.0, 9400.0, 810.0)
CAMP_UE = unreal.Vector(-5400.0, 9400.0, 810.0)
APPROACH_UE = unreal.Vector(-5450.0, 8350.0, 950.0)


def camp_ronin():
    actors = unreal.GameplayStatics.get_all_actors_of_class(L.game_world(), unreal.SwordTrainer)
    out = []
    for a in actors:
        loc = a.get_actor_location()
        if math.hypot(loc.x - CAMP_UE.x, loc.y - CAMP_UE.y) < 3200.0:
            out.append(a)
    out.sort(key=lambda a: a.get_actor_scale3d().z)
    return out


def wrap_deg(d):
    return (d + 180.0) % 360.0 - 180.0


def trainer():
    try:
        d = json.loads(YL.trainer_state())
        loc = d.get('location')
        if loc and math.hypot(loc[0] - CAMP_UE.x, loc[1] - CAMP_UE.y) < 3500.0:
            return d
    except Exception:
        pass
    return {'location': [CAMP_UE.x, CAMP_UE.y, CAMP_UE.z + 90.0]}


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
    ronin = camp_ronin()
    k = trainer().get('location') or [CAMP_UE.x, CAMP_UE.y, CAMP_UE.z + 90.0]
    if mode == 'overview':
        eye = unreal.Vector(CAMP_UE.x + 110.0, CAMP_UE.y - 640.0, CAMP_UE.z + 240.0)
        at = unreal.Vector(CAMP_UE.x - 20.0, CAMP_UE.y + 110.0, CAMP_UE.z + 95.0)
        MV.review_camera(eye, at, 60.0)
        return
    if mode == 'squad_closeup' and ronin:
        cx = sum(a.get_actor_location().x for a in ronin) / len(ronin)
        cy = sum(a.get_actor_location().y for a in ronin) / len(ronin)
        cz = sum(a.get_actor_location().z for a in ronin) / len(ronin)
        dx, dy = p.x - cx, p.y - cy
        n = math.hypot(dx, dy) or 1.0
        ux, uy = dx / n, dy / n
        rx, ry = -uy, ux
        eye = unreal.Vector(cx + ux * 280.0 + rx * 95.0, cy + uy * 280.0 + ry * 95.0, cz + 52.0)
        at = unreal.Vector(cx, cy, cz + 28.0)
        MV.review_camera(eye, at, 50.0)
        return
    if ronin:
        cx = (p.x + sum(a.get_actor_location().x for a in ronin)) / (1 + len(ronin))
        cy = (p.y + sum(a.get_actor_location().y for a in ronin)) / (1 + len(ronin))
        cz = (p.z + sum(a.get_actor_location().z for a in ronin)) / (1 + len(ronin))
        mx, my, mz = (p.x + cx) * 0.5, (p.y + cy) * 0.5, (p.z + cz) * 0.5
    else:
        mx, my, mz = (p.x + k[0]) * 0.5, (p.y + k[1]) * 0.5, (p.z + k[2]) * 0.5
    dx, dy = k[0] - p.x, k[1] - p.y
    n = math.hypot(dx, dy) or 1.0
    ex, ey = mx - dy / n * 310.0 - dx / n * 85.0, my + dx / n * 310.0 - dy / n * 85.0
    eye = unreal.Vector(ex, ey, mz + 95.0)
    st['cam_eye'] = eye if st.get('cam_eye') is None else st['cam_eye'] * 0.88 + eye * 0.12
    at = unreal.Vector(mx, my, mz + 24.0)
    MV.review_camera(st['cam_eye'], at, 56.0)


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
    label('Camp Alert: Scout (Indigo Kasa), Guard (Jade Jingasa) & Captain (Crimson Kabuto)')
    t = 0.0
    while t < 12.0:
        dt = (yield)
        st['t'] += dt
        t += dt
        p = L.player().get_actor_location()
        ronin = camp_ronin()
        if t > 1.2 and ronin:
            errs = []
            for a in ronin:
                al = a.get_actor_location()
                want_yaw = math.degrees(math.atan2(p.y - al.y, p.x - al.x))
                cur_yaw = a.get_actor_rotation().yaw
                errs.append(round(abs(wrap_deg(want_yaw - cur_yaw)), 1))
            st['facing_samples'].append(errs)
        k = trainer().get('location') or [CAMP_UE.x, CAMP_UE.y, CAMP_UE.z + 90.0]
        yaw = math.degrees(math.atan2(k[1] - p.y, k[0] - p.x))
        pc.set_control_rotation(unreal.Rotator(roll=0, pitch=-8, yaw=yaw))
        d = math.hypot(k[0] - p.x, k[1] - p.y)
        if t > 2.4 and t < 7.2:
            st['label'] = 'Crescent Flank & Sword Clash: 360-deg lock-on, parries & blade sweeps'
        elif t >= 7.2:
            st['label'] = 'Warlord Duel: Charged Spin & Guard Break against the Ronin squad'
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
        if t < 2.2:
            camp_camera('squad_closeup')
        else:
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
    json.dump({'frames': st['frames'], 'errors': st['errors'], 'facing_samples': st['facing_samples']}, open(os.path.join(OUT, 'done.json'), 'w'))
    unreal.log('RONIN FILM DONE')


live.behave('ronin_camp_film', run)
print('RONIN FILM started', OUT)
