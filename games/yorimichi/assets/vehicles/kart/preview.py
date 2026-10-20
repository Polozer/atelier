"""Render a character seated on the kart, posed with the driving stance's targets.

    blender -b --threads 3 --python-exit-code 1 --python preview.py -- cairo /abs/out

The kart's three meshes come from build/yorimichi/kart/assets (world.kart). The character is loaded from its
.blend or .glb, moved so its pelvis sits at the kart's seat, turned to face the nose, and given two-bone IK on
the legs (feet on the pedals) and arms (hands on the wheel's rim). Diagnostic render only; nothing here is part
of the game's build graph.
"""
import sys as _sys; from pathlib import Path as _Path; _sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / 'world')); import yori  # noqa: E402
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

from atelier.blender import renderdev

ARGS = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
CHARACTER = ARGS[0] if ARGS else 'cairo'
OUT = Path(ARGS[1]) if len(ARGS) > 1 else Path('/tmp/kart-preview')
OUT.mkdir(parents=True, exist_ok=True)

SOURCES = {
    'cairo': yori.ASSETS / 'characters/cairo/Cairo-Game-r18.blend',
    'modori': yori.ASSETS / 'characters/modori/Modori-Rig-r01.blend',
    'nox': yori.ASSETS / 'characters/nox/Nox.glb',
    'paul': yori.ASSETS / 'characters/paul/Paul.glb',
}
KART = yori.OUT / 'kart/assets'
HEIGHT = {'cairo': 1.48, 'modori': 1.75, 'nox': 1.78, 'paul': 1.65}
BONES = {
    'pelvis': 'mixamorig:Hips', 'spine': 'mixamorig:Spine',
    'thigh_L': 'mixamorig:LeftUpLeg', 'shin_L': 'mixamorig:LeftLeg', 'foot_L': 'mixamorig:LeftFoot',
    'thigh_R': 'mixamorig:RightUpLeg', 'shin_R': 'mixamorig:RightLeg', 'foot_R': 'mixamorig:RightFoot',
    'upperarm_L': 'mixamorig:LeftArm', 'forearm_L': 'mixamorig:LeftForeArm', 'hand_L': 'mixamorig:LeftHand',
    'upperarm_R': 'mixamorig:RightArm', 'forearm_R': 'mixamorig:RightForeArm', 'hand_R': 'mixamorig:RightHand',
    'fingers_L': ('mixamorig:LeftHandIndex', 'mixamorig:LeftHandMiddle', 'mixamorig:LeftHandRing',
                  'mixamorig:LeftHandPinky', 'mixamorig:LeftHandThumb'),
    'fingers_R': ('mixamorig:RightHandIndex', 'mixamorig:RightHandMiddle', 'mixamorig:RightHandRing',
                  'mixamorig:RightHandPinky', 'mixamorig:RightHandThumb'),
}


def bone(arm, name):
    for candidate in (name, BONES.get(name), f'mixamorig:{name}'):
        if candidate and candidate in arm.pose.bones:
            return arm.pose.bones[candidate]
    return None

SEAT = Vector((-0.30, 0.0, 0.33))
WHEEL_HUB = Vector((0.02, 0.0, 0.60))
RIM = 0.12
PEDAL = [Vector((0.32, 0.14, 0.13)), Vector((0.32, -0.14, 0.13))]
KNEE = [Vector((0.16, 0.18, 0.34)), Vector((0.16, -0.18, 0.34))]
HAND = [Vector((0.02, 0.12, 0.60)), Vector((0.02, -0.12, 0.60))]
ELBOW = [Vector((-0.05, 0.32, 0.50)), Vector((-0.05, -0.32, 0.50))]


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    renderdev.enable_metal()
    scene.cycles.samples = 32
    scene.render.resolution_x = scene.render.resolution_y = 960
    scene.render.film_transparent = False
    scene.world = bpy.data.worlds.new('KartWorld')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.55, .60, .66, 1)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .7
    return scene


def kart_material():
    mat = bpy.data.materials.new('KartVertexColour')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    colour = nodes.new('ShaderNodeVertexColor')
    colour.layer_name = 'Color'
    mat.node_tree.links.new(colour.outputs['Color'], nodes['Principled BSDF'].inputs['Base Color'])
    return mat


def import_kart():
    mat = kart_material()
    pieces = {}
    for name, at, spin_y in (('SM_Kart_Body', (0, 0, 0), 0.0), ('SM_Kart_Wheel', None, 0.0),
                             ('SM_Kart_SteeringWheel', WHEEL_HUB, -18.0)):
        before = set(bpy.data.objects)
        bpy.ops.import_scene.fbx(filepath=str(KART / f'{name}.fbx'))
        added = [o for o in bpy.data.objects if o not in before]
        keep = []
        for ob in list(added):
            if ob.name.startswith('UCX'):
                bpy.data.objects.remove(ob, do_unlink=True)
            else:
                keep.append(ob)
        imported = [o for o in keep if o.type == 'MESH']
        for ob in imported:
            ob.data.materials.clear(); ob.data.materials.append(mat)
        pieces[name] = imported
    placed = []
    for ob in pieces['SM_Kart_Body']:
        placed.append(ob)
    wheels = pieces['SM_Kart_Wheel']
    for source, at in ((0, Vector((0.75, 0.56, 0.14))), (0, Vector((0.75, -0.56, 0.14))),
                       (0, Vector((-0.75, 0.59, 0.14))), (0, Vector((-0.75, -0.59, 0.14)))):
        ob = wheels[source].copy(); ob.data = wheels[source].data.copy()
        bpy.context.scene.collection.objects.link(ob)
        ob.location = at
        placed.append(ob)
    for source in pieces['SM_Kart_SteeringWheel']:
        source.location = WHEEL_HUB
        source.rotation_euler = (0, math.radians(-18), 0)
        placed.append(source)
    for ob in wheels:
        ob.hide_render = True
    return placed


def load_character(path):
    if path.suffix == '.blend':
        with bpy.data.libraries.load(str(path)) as (data_from, data_to):
            data_to.objects = data_from.objects
        for ob in data_to.objects:
            if ob and ob.type in ('ARMATURE', 'MESH') and not ob.name.startswith(('Review', 'Preview')):
                bpy.context.scene.collection.objects.link(ob)
                if any(word in ob.name for word in ('Bokken', 'Sword', 'sword', 'bokken')):
                    ob.hide_render = True
    else:
        bpy.ops.import_scene.gltf(filepath=str(path))
    armatures = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    if not armatures:
        raise RuntimeError(f'no armature in {path}')
    return max(armatures, key=lambda a: len(a.data.bones))


def character_objects(arm):
    root = arm
    while root.parent:
        root = root.parent
    family = {root}
    changed = True
    while changed:
        changed = False
        for ob in bpy.context.scene.objects:
            if ob.parent in family and ob not in family:
                family.add(ob); changed = True
    return [o for o in family if o.type in ('MESH', 'ARMATURE')]


def goal(name, at):
    empty = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(empty)
    empty.location = at
    return empty


def pose(arm):
    arm.data.pose_position = 'POSE'
    for ob in character_objects(arm):
        if ob.animation_data:
            ob.animation_data_clear()   # a stored idle action would overwrite the stance at render time
    root = arm
    while root.parent:
        root = root.parent
    # The sources are modelled at their review size; the game scales each one to its authored height.
    visible = [o for o in character_objects(arm) if o.type == 'MESH' and not o.hide_render]
    corners = [o.matrix_world @ Vector(c) for o in visible for c in o.bound_box]
    if corners:
        current = max(v.z for v in corners) - min(v.z for v in corners)
        if current > .01:
            root.scale = [s * HEIGHT[CHARACTER] / current for s in root.scale]
            bpy.context.view_layer.update()
    # Face the kart's nose (+X) from Blender's usual -Y facing, then put the pelvis on the seat.
    root.rotation_mode = 'XYZ'
    root.rotation_euler.z -= math.radians(90)   # the sources face +Y; the kart's nose is +X
    bpy.context.view_layer.update()
    pelvis = bone(arm, 'pelvis')
    if pelvis:
        root.location += SEAT - (arm.matrix_world @ pelvis.head)
        bpy.context.view_layer.update()
        if 'diag' in ARGS:
            print('PELVIS after', tuple(round(v, 3) for v in (arm.matrix_world @ pelvis.head)), 'seat', tuple(SEAT),
                  'root', root.name, 'parent', root.parent.name if root.parent else None,
                  'loc', tuple(round(v, 3) for v in root.location), 'scale', tuple(round(v, 4) for v in root.scale))
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='POSE')
    for posed in arm.pose.bones:
        posed.rotation_mode = 'XYZ'
    for side, suffix in ((0, 'L'), (1, 'R')):
        shin = bone(arm, f'shin_{suffix}')
        fore = bone(arm, f'forearm_{suffix}')
        if shin:
            c = shin.constraints.new('IK'); c.target = goal(f'foot_{suffix}', PEDAL[side]); c.chain_count = 2
        if fore:
            c = fore.constraints.new('IK'); c.target = goal(f'hand_{suffix}', HAND[side]); c.chain_count = 2
    spine = bone(arm, 'spine')
    if spine:
        spine.rotation_euler.x = math.radians(-12)
    # Curl the fingers around the rim, whichever names the source rig uses.
    for side in ('L', 'R'):
        for prefix in BONES[f'fingers_{side}']:
            for part in (1, 2, 3):
                pb = arm.pose.bones.get(f'{prefix}{part}')
                if pb:
                    pb.rotation_euler.x = math.radians(25 if 'Thumb' in prefix else -45)
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.update()
    for label, bone_name, goal_obj in (('footL', 'foot_L', 'foot_L'), ('footR', 'foot_R', 'foot_R'),
                                       ('handL', 'hand_L', 'hand_L'), ('handR', 'hand_R', 'hand_R')):
        pb = bone(arm, bone_name)
        target = bpy.data.objects.get(goal_obj)
        if pb and target:
            at = arm.matrix_world @ pb.tail
            print('POSE', label, 'bone', tuple(round(v, 3) for v in at),
                  'target', tuple(round(v, 3) for v in target.location),
                  'miss', round((at - target.location).length, 3))


def light(scene):
    sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
    scene.collection.objects.link(sun)
    sun.data.energy = 4.0
    sun.rotation_euler = (math.radians(55), 0, math.radians(35))
    fill = bpy.data.objects.new('Fill', bpy.data.lights.new('Fill', 'AREA'))
    scene.collection.objects.link(fill)
    fill.data.energy = 300
    fill.data.size = 4
    fill.location = (-2.5, -2.5, 3)
    fill.rotation_euler = (math.radians(55), 0, math.radians(-135))


def camera(scene, at, look):
    cam = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
    scene.collection.objects.link(cam)
    cam.location = at
    direction = Vector(look) - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    cam.data.lens = 55
    scene.camera = cam
    return cam


def render(scene, path, at, look):
    remove = [o for o in scene.objects if o.type == 'CAMERA']
    for o in remove:
        bpy.data.objects.remove(o, do_unlink=True)
    camera(scene, Vector(at), Vector(look))
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    print('RENDERED', path)


def main():
    scene = fresh()
    import_kart()
    arm = load_character(SOURCES[CHARACTER])
    print('CHARACTER', CHARACTER, 'ARMATURE', arm.name, 'BONES', len(arm.data.bones))
    if 'diag' in ARGS:
        print('BONE NAMES', ', '.join(b.name for b in arm.data.bones))
    for ob in character_objects(arm):
        print('  OBJECT', ob.name, ob.type, 'hide', ob.hide_render, 'dims', tuple(round(v, 3) for v in ob.dimensions))
        if ob.type == 'MESH' and 'diag' in ARGS:
            print('    MODIFIERS', [(m.type, getattr(m, 'object', None).name if getattr(m, 'object', None) else None) for m in ob.modifiers],
                  'groups', len(ob.vertex_groups), 'render', [(m.show_render, m.show_viewport) for m in ob.modifiers],
                  'parent', ob.parent.name if ob.parent else None, ob.parent_type)
    pose(arm)
    if 'diag' in ARGS:
        print('DIAGNOSTIC ONLY')
        return
    light(scene)
    render(scene, OUT / f'{CHARACTER}-kart-front.png', (2.6, -2.4, 1.55), (-0.15, 0, 0.5))
    render(scene, OUT / f'{CHARACTER}-kart-side.png', (0.4, -3.2, 1.2), (-0.1, 0, 0.5))
    print('KART PREVIEW COMPLETE', CHARACTER)


if __name__ == '__main__':
    main()
