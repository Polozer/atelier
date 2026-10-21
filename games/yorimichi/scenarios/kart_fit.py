"""All four riders in the kart, from the angles the fit review needs.

    atelier live py - < games/yorimichi/scenarios/kart_fit.py

Switches the playable character in place, summons the kart on the beach flat and captures front, rear, both sides,
an elevated seat view and a grip close-up per rider. The review camera is restored and the kart parked afterward.
Writes build/yorimichi/kart_film/kart_fit.json with each rider's mesh, car state, ride telemetry and glider state.
"""
import json
import math
import os
import unreal

L = live.L
MV = unreal.MegaParkValidation
ROOT = os.environ.get('ATELIER_BUILD_ROOT') or os.path.join(live.ROOT, 'build')
OUT = os.path.join(ROOT, 'yorimichi/kart_film/fit')
os.makedirs(OUT, exist_ok=True)

RIDERS = ['Cairo', 'Modori', 'Nox', 'Paul']
# (name, forward, right, up, aim forward, aim up, fov)
VIEWS = [
    ('front', 480.0, 0.0, 160.0, 0.0, 60.0, 50.0),
    ('rear', -480.0, 0.0, 160.0, 0.0, 60.0, 50.0),
    ('left', 0.0, -520.0, 130.0, 0.0, 60.0, 50.0),
    ('right', 0.0, 520.0, 130.0, 0.0, 60.0, 50.0),
    ('seat', 250.0, 0.0, 300.0, 0.0, 30.0, 55.0),
    ('grips', 240.0, -100.0, 110.0, 30.0, 85.0, 38.0),
]
BEACH = unreal.Vector(-23600.0, 16000.0, 0.0)


def frame(loc, yaw, forward, right, up, aim_forward, aim_up):
    r = math.radians(yaw)
    f = unreal.Vector(math.cos(r), math.sin(r), 0.0)
    rt = unreal.Vector(-math.sin(r), math.cos(r), 0.0)
    eye = loc + f * forward + rt * right + unreal.Vector(0, 0, up)
    at = loc + f * aim_forward + unreal.Vector(0, 0, aim_up)
    return eye, at


def glider_visible():
    world = unreal.LiveLibrary.game_world()
    pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
    for component in pawn.get_components_by_class(unreal.SkeletalMeshComponent):
        if component.get_name() == 'Paraglider':
            return bool(component.is_visible())
    return None


queue = []


def later(delay, fn):
    queue.append([delay, fn])


def build():
    for index, rider in enumerate(RIDERS):
        def select(rider=rider):
            print('rider %s -> %s' % (rider, L.switch_character(rider)))

        def park():
            if 'driving=1' in L.car_state():
                live.press('car')
                L.fixed_step(60)

        def place():
            ground = L.ground_at(BEACH)
            L.teleport_player(ground, 0.0)

        def summon():
            live.press('car')

        def record(rider=rider):
            world = unreal.LiveLibrary.game_world()
            pawn = unreal.GameplayStatics.get_player_pawn(world, 0)
            mesh = pawn.get_mesh().get_skeletal_mesh_asset()
            result = {'rider': rider,
                      'mesh': mesh.get_path_name() if mesh else None,
                      'car': L.car_state(),
                      'ride': L.car_ride(),
                      'glider_visible': glider_visible(),
                      'views': OUT}
            results.append(result)

        def restore():
            MV.restore_player_camera()

        def settings():
            L.fixed_step(60)

        later(0.2, settings)
        later(0.1, select)
        later(1.2, park)
        later(0.6, place)
        later(0.5, summon)
        later(0.7, lambda: L.input_key('D', 'press', 1.0))
        for view, forward, right, up, aim_forward, aim_up, fov in VIEWS:
            def shot(view=view, forward=forward, right=right, up=up, aim_forward=aim_forward,
                     aim_up=aim_up, fov=fov, rider=rider):
                loc, yaw = live.player()
                eye, at = frame(loc, yaw, forward, right, up, aim_forward, aim_up)
                MV.review_camera(eye, at, fov)
                L.screenshot(os.path.join(OUT, '%s_%s.png' % (rider.lower(), view)))
            later(0.3, shot)
        later(1.8, lambda: L.input_key('D', 'release', 0.0))
        later(0.2, restore)
        later(0.2, record)
        later(0.2, park)


results = []
build()
json_path = os.path.join(OUT, 'kart_fit.json')
clock = {'t': 0.0}


def tick(dt):
    try:
        if not queue:
            L.fixed_step(0)
            json.dump(results, open(json_path, 'w'), indent=1)
            print('kart fit done: %d riders' % len(results))
            unreal.log('KART FIT COMPLETE %d' % len(results))
            live.stop('kart_fit')
            return
        queue[0][0] -= dt
        if queue[0][0] <= 0.0:
            fn = queue.pop(0)[1]
            fn()
    except Exception as error:
        unreal.log_error('KART FIT: %s' % error)
        queue.clear()
        live.stop('kart_fit')


live.behave('kart_fit', tick)
print('kart fit armed: %d riders' % len(RIDERS))

