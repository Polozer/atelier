"""Place the processed TRELLIS town assets into the assembled Brinecove scene."""
import math
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

import layout as L
import kit

PROPOSAL = Path(__file__).resolve().parents[1]
MODELS = PROPOSAL / 'assets/models'


def _import(slug):
    source = MODELS / f'{slug}.glb'
    if not source.exists():
        return None
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(source))
    imported = [obj for obj in bpy.data.objects if obj not in before and obj.type == 'MESH']
    if not imported:
        return None
    bpy.ops.object.select_all(action='DESELECT')
    for obj in imported:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = imported[0]
    if len(imported) > 1:
        bpy.ops.object.join()
    obj = bpy.context.object
    obj.parent = None
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def _place(obj, collection, x, y, z, yaw=0.0, scale=1.0, pitch=0.0):
    dup = obj.copy()
    dup.data = obj.data
    collection.objects.link(dup)
    dup.location = (x, y, z)
    dup.rotation_euler = (math.radians(pitch), 0.0, math.radians(yaw))
    dup.scale = (scale, scale, scale)
    return dup


def add_hero_assets(collection):
    placed = []
    # The statue replaces the blockout figure on the harbor islet.
    statue = _import('pirate-queen-statue')
    if statue:
        placed.append(_place(statue, collection, L.STATUE[0], L.STATUE[1], 12.0, 0.0, 1.0))
        bpy.data.objects.remove(statue, do_unlink=True)
    # The Tripo hero hull under each moored galleon's procedural rig: keel a third of the hull below the sea.
    hull = _import('galleon-hull')
    if hull:
        depth = max(v.co.z for v in hull.data.vertices) * 0.24
        for name, x, y, yaw, scale, sails in L.SHIPS:
            placed.append(_place(hull, collection, x, y, -0.35 - depth * scale, yaw, scale))
        bpy.data.objects.remove(hull, do_unlink=True)
    # Two carved figureheads on the moored galleons.
    figurehead = None if hull else _import('galleon-figurehead')  # the Tripo hull carries its own mermaid
    if figurehead:
        for name, x, y, yaw, scale, sails in L.SHIPS[:2]:
            # The carving brackets onto the stem and leans forward under the
            # bowsprit; the old offset put it 26 m ahead of the hull.
            bx, by = kit.local(x, y, yaw, 0.0, 30.4 * scale)
            placed.append(_place(figurehead, collection, bx, by, -1.1 + 4.6 * scale,
                                 yaw, 0.78, pitch=-32))
        bpy.data.objects.remove(figurehead, do_unlink=True)
    # Quay and watchtower cannon.
    cannon = _import('harbor-cannon')
    if cannon:
        for x, y, yaw in ((-206, 88.0, 18), (210, 88.0, -14)):
            placed.append(_place(cannon, collection, x, y, L.ground(x, y) + 0.1, yaw, 0.82))
        bpy.data.objects.remove(cannon, do_unlink=True)
    anchor = _import('ship-anchor')
    if anchor:
        placed.append(_place(anchor, collection, -292, 90, L.ground(-292, 90) + 0.1, 28, 1.0))
        bpy.data.objects.remove(anchor, do_unlink=True)
    capstan = _import('harbor-capstan')
    if capstan:
        for x, y, yaw in ((8, -24, 0), (238, -50, 34)):
            placed.append(_place(capstan, collection, x, y, 5.35, yaw, 1.0))
        bpy.data.objects.remove(capstan, do_unlink=True)
    wheel = None if hull else _import('ships-wheel')  # the Tripo hull has its own deck furniture
    if wheel:
        # The central galleon's stern deck.
        name, x, y, yaw, scale, sails = L.SHIPS[0]
        wx, wy = kit.local(x, y, yaw, 0.0, -16.5 * scale)
        placed.append(_place(wheel, collection, wx, wy, -1.1 + 4.72 * scale, yaw + 90, 0.9))
        bpy.data.objects.remove(wheel, do_unlink=True)
    if not placed:
        return None
    bpy.ops.object.select_all(action='DESELECT')
    for obj in placed:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = placed[0]
    bpy.ops.object.join()
    result = bpy.context.object
    result.name = '10_hero_assets'
    result['brinecove_module'] = '10_hero_assets'
    return result
