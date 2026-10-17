#!/usr/bin/env python3
"""Build and render the Brinecove proposal in headless Blender.

    blender -b --factory-startup --python src/build.py -- --stage all
    blender -b --factory-startup --python src/build.py -- --stage render

The build writes one GLB per proposal module, an assembled .blend, a full-scene GLB, Eevee review renders and the
viewer payload. No Unreal project, level or game asset is touched.
"""
import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
PROPOSAL = SRC.parent
REPO = PROPOSAL.parents[3]
sys.path.insert(0, str(SRC))

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Vector  # noqa: E402

import layout as L  # noqa: E402
import modules  # noqa: E402

OUT = REPO / 'build/yorimichi/pirate-coast'
SCENE_OUT = OUT / 'scene'
MODEL_OUT = OUT / 'models'
VIEWER_OUT = OUT / 'viewer'
RENDER_OUT = OUT / 'renders'


def srgb_to_linear(value):
    value = value / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def make_material(name, hex_color):
    r = srgb_to_linear(int(hex_color[1:3], 16))
    g = srgb_to_linear(int(hex_color[3:5], 16))
    b = srgb_to_linear(int(hex_color[5:7], 16))
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (r, g, b, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.88
    if name in ('metal', 'gold'):
        bsdf.inputs['Metallic'].default_value = 0.65
        bsdf.inputs['Roughness'].default_value = 0.45
    if name in ('glass', 'glass_warm'):
        bsdf.inputs['Roughness'].default_value = 0.25
    if name in ('lantern', 'glass_warm'):
        bsdf.inputs['Emission Color'].default_value = (r, g, b, 1.0)
        bsdf.inputs['Emission Strength'].default_value = 2.5
    if name == 'water':
        bsdf.inputs['Roughness'].default_value = 0.18
        bsdf.inputs['Metallic'].default_value = 0.1
    if name in ('water', 'sail') and name == 'water':
        bsdf.inputs['Alpha'].default_value = 0.78
        mat.blend_method = 'BLEND'
    return mat


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        if collection.users == 0:
            bpy.data.collections.remove(collection)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def make_object(builder, collection, materials):
    used = [name for name in materials if name in set(builder.mats)]
    index = {name: i for i, name in enumerate(used)}
    mesh = bpy.data.meshes.new(builder.name)
    mesh.from_pydata(builder.verts, [], builder.faces)
    mesh.validate(verbose=False)
    mesh.update()
    for name in used:
        mesh.materials.append(materials[name])
    for poly, mat in zip(mesh.polygons, builder.mats):
        poly.material_index = index[mat]
        poly.use_smooth = False
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(builder.name, mesh)
    collection.objects.link(obj)
    return obj, len(used)


def build_modules():
    SCENE_OUT.mkdir(parents=True, exist_ok=True)
    MODEL_OUT.mkdir(parents=True, exist_ok=True)
    clear_scene()
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.length_unit = 'METERS'
    materials = {name: make_material(name, color) for name, color in L.COLORS.items()}
    objects = {}
    report = {}
    for name, fn in modules.MODULES.items():
        started = time.time()
        builder = fn()
        collection = bpy.data.collections.new(name)
        scene.collection.children.link(collection)
        obj, mat_count = make_object(builder, collection, materials)
        obj['brinecove_module'] = name
        objects[name] = obj
        report[name] = dict(vertices=len(builder.verts), triangles=sum(len(f) - 2 for f in builder.faces),
                            materials=mat_count, seconds=round(time.time() - started, 2))
        print(f'built {name}: {report[name]}', flush=True)
    # Full scene and per-module GLBs.
    for obj in objects.values():
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects['01_terrain']
    bpy.ops.wm.save_as_mainfile(filepath=str(SCENE_OUT / 'brinecove.blend'))
    bpy.ops.export_scene.gltf(filepath=str(SCENE_OUT / 'brinecove.glb'), export_format='GLB',
                              use_selection=True, export_apply=True, export_yup=True,
                              export_animations=False, export_skins=False, export_cameras=False,
                              export_lights=False, export_extras=True)
    for name, obj in objects.items():
        for other in objects.values():
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.export_scene.gltf(filepath=str(MODEL_OUT / f'{name}.glb'), export_format='GLB',
                                  use_selection=True, export_apply=True, export_yup=True,
                                  export_animations=False, export_skins=False, export_cameras=False,
                                  export_lights=False, export_extras=True)
    for obj in objects.values():
        obj.select_set(False)
    report['_totals'] = dict(vertices=sum(v['vertices'] for k, v in report.items() if not k.startswith('_')),
                             triangles=sum(v['triangles'] for k, v in report.items() if not k.startswith('_')))
    report['_area'] = L.area()
    (OUT / 'build.json').write_text(json.dumps(report, indent=2) + '\n')
    print('BRINECOVE BUILD COMPLETE', flush=True)
    return objects, report


def sea_plane():
    bpy.ops.mesh.primitive_plane_add(size=5000, location=(0, 0, -0.35))
    obj = bpy.context.object
    obj.name = 'REVIEW_Sea'
    mat = bpy.data.materials.get('water_deep')
    obj.data.materials.append(mat)
    return obj


def add_render_objects():
    scene = bpy.context.scene
    sea_plane()
    world = bpy.data.worlds.new('Brinecove review sky')
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = (0.38, 0.58, 0.73, 1.0)
    bg.inputs['Strength'].default_value = 1.0
    sun_data = bpy.data.lights.new('Sun', 'SUN')
    sun_data.energy = 3.2
    sun_data.angle = math.radians(18)
    sun_data.color = (1.0, 0.84, 0.62)
    sun = bpy.data.objects.new('Sun', sun_data)
    scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(52), math.radians(8), math.radians(-38))
    fill_data = bpy.data.lights.new('Sky fill', 'AREA')
    fill_data.energy = 900
    fill_data.size = 700
    fill_data.color = (0.62, 0.78, 1.0)
    fill = bpy.data.objects.new('Sky fill', fill_data)
    scene.collection.objects.link(fill)
    fill.location = (-250, -350, 240)
    fill.rotation_euler = (math.radians(28), 0, math.radians(-35))
    cam_data = bpy.data.cameras.new('Review camera')
    cam = bpy.data.objects.new('Review camera', cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam
    scene.render.engine = 'BLENDER_EEVEE_NEXT'
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.eevee.taa_render_samples = 32
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'AgX - Punchy'
    scene.view_settings.exposure = 0.25
    return cam, sun, fill, bg


def look_at(cam, location, target, lens=42):
    cam.location = Vector(location)
    direction = Vector(target) - Vector(location)
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    cam.data.lens = lens


VIEWS = {
    '01-aerial-hero': ((-780, -900, 560), (0, 20, 12), 52, 'day'),
    '02-harbor-approach': ((0, -380, 9), (0, 64, 14), 42, 'day'),
    '03-market-square': ((0, 86, 8), (0, 180, 12), 36, 'day'),
    '04-upper-terrace': ((0, 362, 29), (0, 150, 7), 36, 'day'),
    '05-lighthouse-headland': ((-560, -120, 68), (-618, -38, 66), 46, 'day'),
    '06-shipyard': ((300, -235, 22), (388, 98, 14), 46, 'day'),
    '07-waterfall-bridge': ((405, 158, 44), (488, 88, 25), 48, 'day'),
    '08-night-harbor': ((0, -380, 9), (0, 64, 14), 42, 'night'),
    '09-rum-row': ((-120, 70, 8), (-120, 150, 10), 38, 'day'),
    '10-topdown': ((0, -40, 820), (0, -20, 0), 46, 'day'),
}


def render_views():
    RENDER_OUT.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(SCENE_OUT / 'brinecove.blend'))
    cam, sun, fill, bg = add_render_objects()
    scene = bpy.context.scene
    files = []
    for name, (loc, target, lens, mood) in VIEWS.items():
        if mood == 'night':
            bg.inputs['Color'].default_value = (0.035, 0.075, 0.13, 1.0)
            bg.inputs['Strength'].default_value = 0.6
            sun.data.energy = 0.35
            sun.data.color = (0.45, 0.62, 1.0)
            fill.data.energy = 350
            fill.data.color = (0.22, 0.35, 0.65)
            add_night_lights(scene)
        else:
            bg.inputs['Color'].default_value = (0.38, 0.58, 0.73, 1.0)
            bg.inputs['Strength'].default_value = 1.0
            sun.data.energy = 3.2
            sun.data.color = (1.0, 0.84, 0.62)
            fill.data.energy = 900
            fill.data.color = (0.62, 0.78, 1.0)
        look_at(cam, loc, target, lens)
        scene.render.filepath = str(RENDER_OUT / f'{name}.png')
        print('rendering', name, flush=True)
        bpy.ops.render.render(write_still=True)
        files.append(name)
    (OUT / 'renders.json').write_text(json.dumps(files, indent=2) + '\n')
    print('BRINECOVE RENDER COMPLETE', flush=True)


def add_night_lights(scene):
    # A few warm pools stand in for the lantern strings. The emissive material carries the close-up detail.
    points = [(-320, 88, 7), (-190, 88, 7), (-60, 88, 7), (70, 88, 7), (200, 88, 7), (330, 88, 7),
              (-200, 155, 8), (0, 160, 9), (200, 155, 8), (-120, 338, 26), (110, 338, 26),
              (-618, -40, 86), (355, 92, 15)]
    for i, (x, y, z) in enumerate(points):
        data = bpy.data.lights.new(f'Lantern {i}', 'POINT')
        data.energy = 450 if i < 8 else 700
        data.color = (1.0, 0.62, 0.28)
        data.shadow_soft_size = 4.0
        obj = bpy.data.objects.new(f'Lantern {i}', data)
        scene.collection.objects.link(obj)
        obj.location = (x, y, z)


def sync_viewer():
    VIEWER_OUT.mkdir(parents=True, exist_ok=True)
    for src in (PROPOSAL / 'viewer').iterdir():
        if src.is_file():
            shutil.copy2(src, VIEWER_OUT / src.name)
    vendor_src = REPO / 'games/yorimichi/tools/character_review_web/vendor'
    vendor_dst = VIEWER_OUT / 'vendor'
    if vendor_dst.exists():
        shutil.rmtree(vendor_dst)
    shutil.copytree(vendor_src, vendor_dst)
    refs_src = OUT / 'references'
    refs_dst = VIEWER_OUT / 'refs'
    if refs_dst.exists():
        shutil.rmtree(refs_dst)
    refs_dst.mkdir()
    for src in sorted(refs_src.glob('*.png')):
        shutil.copy2(src, refs_dst / src.name)
    for src in (OUT / 'renders').glob('*.png'):
        shutil.copy2(src, VIEWER_OUT / src.name)
    models_dst = VIEWER_OUT / 'models'
    if models_dst.exists():
        shutil.rmtree(models_dst)
    shutil.copytree(MODEL_OUT, models_dst)
    (VIEWER_OUT / 'build.json').write_text((OUT / 'build.json').read_text())
    print('viewer payload:', VIEWER_OUT, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', choices=('all', 'build', 'render', 'sync'), default='all')
    args = ap.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    OUT.mkdir(parents=True, exist_ok=True)
    if args.stage in ('all', 'build'):
        build_modules()
    if args.stage in ('all', 'render'):
        render_views()
    if args.stage in ('all', 'sync'):
        sync_viewer()


if __name__ == '__main__':
    main()
