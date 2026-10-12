"""Fit a Tripo Studio furniture export to the train's dimension contract (Blender, headless).

    blender -b --python games/yorimichi/world/train/fit_furniture.py -- ASSET_ID SOURCE.fbx|.glb [--column Z0 Z1]

Imports the mesh, puts its origin at the contract's pivot (floor footprint centre, table lamp base, sconce wall
mount), scales it uniformly so its width matches the contract, then, with --column, lengthens only the part between
heights Z0 and Z1 (fractions of the scaled height) to reach the contract height: a pedestal or legs grow, the top
and the base keep their shape. It never stretches the whole object along one axis. Depth must then match within
the tolerance, or the script stops and reports it.

Writes build/yorimichi/belmonte-train/furniture/<asset>.glb and <asset>.json (dimensions before and after,
scale, column stretch, triangles, checksum) and a check render <asset>.png against a wireframe of the target box.
"""
import sys as _sys; from pathlib import Path as _Path; _sys.path.insert(0, str(_Path(__file__).resolve().parents[1])); import yori  # noqa: E402,F401
import hashlib
import json
import math
import sys

import bpy
from mathutils import Vector

from train import layout as L

OUT = yori.OUT / 'belmonte-train' / 'furniture'
TOLERANCE = .02          # metres, on width/depth/height after fitting


def bounds(objs):
    """From the vertices themselves (bound_box lags behind direct vertex edits)."""
    pts = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
    lo = Vector([min(p[i] for p in pts) for i in range(3)]); hi = Vector([max(p[i] for p in pts) for i in range(3)])
    return lo, hi


def main():
    args = sys.argv[sys.argv.index('--') + 1:]
    asset, src = args[0], _Path(args[1])
    column = None
    if '--column' in args:
        i = args.index('--column'); column = float(args[i + 1]), float(args[i + 2])
    spec = next(a for a in L.contract()['assets'] if a['id'] == asset)
    tw, td, th = (spec['dimensions_m'][k] for k in ('width', 'depth', 'height'))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if src.suffix.lower() == '.fbx':
        bpy.ops.import_scene.fbx(filepath=str(src))
    else:
        bpy.ops.import_scene.gltf(filepath=str(src))
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    # bake every transform into the mesh, then join into one object named after the asset
    for o in meshes:
        o.data = o.data.copy() if o.data.users > 1 else o.data
        o.data.transform(o.matrix_world); o.parent = None; o.matrix_world.identity()
    for o in list(bpy.context.scene.objects):
        if o.type != 'MESH':
            bpy.data.objects.remove(o)
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    obj.name = obj.data.name = f'SM_BT_{"".join(p.title() for p in asset.split("-"))}'
    lo, hi = bounds([obj]); before = hi - lo
    swapped = before.y > before.x * 1.15 and tw > td * 1.15
    if swapped:                          # the width came out along Y: turn it a quarter so width runs along X
        from mathutils import Matrix
        obj.data.transform(Matrix.Rotation(math.radians(90), 4, 'Z'))
        lo, hi = bounds([obj])
    s = tw / (hi.x - lo.x)
    centre = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for v in obj.data.vertices:
        v.co = (v.co - centre) * s
    lo, hi = bounds([obj])
    stretch = 0.
    if column:
        h = hi.z - lo.z
        z0, z1 = column[0] * h, column[1] * h
        stretch = th - h
        for v in obj.data.vertices:
            if v.co.z >= z1:
                v.co.z += stretch
            elif v.co.z > z0:
                v.co.z += stretch * (v.co.z - z0) / (z1 - z0)
    if spec['pivot'] == 'wall_mount_center':
        lo, hi = bounds([obj])
        for v in obj.data.vertices:          # back of the sconce on y = 0, front towards -Y, centred in height
            v.co.y -= hi.y; v.co.z -= (lo.z + hi.z) / 2
    obj.data.update()
    lo, hi = bounds([obj]); after = hi - lo
    errors = {k: round(abs(a - t), 4) for k, a, t in (('width', after.x, tw), ('depth', after.y, td), ('height', after.z, th))}
    ok = all(e <= TOLERANCE for e in errors.values())
    OUT.mkdir(parents=True, exist_ok=True)
    # check render: the fitted mesh inside a wireframe of the target box
    tgt = bpy.data.objects.new('target', bpy.data.meshes.new('target'))
    z0 = 0 if spec['pivot'] != 'wall_mount_center' else -th / 2
    y0, y1 = (-td / 2, td / 2) if spec['pivot'] != 'wall_mount_center' else (-td, 0)
    vs = [(x, y, z) for x in (-tw / 2, tw / 2) for y in (y0, y1) for z in (z0, z0 + th)]
    tgt.data.from_pydata(vs, [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)], [])
    bpy.context.scene.collection.objects.link(tgt)
    wire = tgt.modifiers.new('w', 'SKIN')
    for sv in tgt.data.skin_vertices[0].data:
        sv.radius = (.004, .004)
    mat = bpy.data.materials.new('target'); mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (1, .2, .1, 1)
    tgt.data.materials.append(mat)
    sc = bpy.context.scene; sc.render.engine = 'BLENDER_EEVEE'; sc.render.resolution_x, sc.render.resolution_y = 1200, 800
    sc.view_settings.view_transform = 'Standard'
    w = bpy.data.worlds.new('w'); sc.world = w; w.node_tree.nodes['Background'].inputs[0].default_value = (1, 1, 1, 1)
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera = cam
    size = max(tw, td, th)
    c = Vector((0, (y0 + y1) / 2, z0 + th / 2))
    cam.location = c + Vector((1.1, -1.6, .8)).normalized() * size * 2.6
    cam.rotation_euler = (c - cam.location).to_track_quat('-Z', 'Y').to_euler()
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN')); sun.data.energy = 2.5; sun.rotation_euler = (.7, .2, .8)
    sc.collection.objects.link(sun)
    sc.render.filepath = str(OUT / f'{asset}.png'); bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(tgt)
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True)
    glb = OUT / f'{asset}.glb'
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format='GLB', use_selection=True, export_yup=True, export_apply=True)
    report = dict(asset=asset, source=src.name, source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
                  target_m=dict(width=tw, depth=td, height=th), source_size=[round(v, 4) for v in before],
                  quarter_turn=swapped, uniform_scale=round(s, 5), column_fraction=column, column_stretch_m=round(stretch, 4),
                  fitted_m=dict(width=round(after.x, 4), depth=round(after.y, 4), height=round(after.z, 4)), errors_m=errors, ok=ok,
                  triangles=sum(len(p.vertices) - 2 for p in obj.data.polygons), pivot=spec['pivot'],
                  glb=dict(file=glb.name, bytes=glb.stat().st_size, sha256=hashlib.sha256(glb.read_bytes()).hexdigest()))
    (OUT / f'{asset}.json').write_text(json.dumps(report, indent=1))
    print('FIT', json.dumps(report), flush=True)
    if not ok:
        raise SystemExit(f'{asset}: fitted size misses the contract by {errors}')


if __name__ == '__main__':
    main()
