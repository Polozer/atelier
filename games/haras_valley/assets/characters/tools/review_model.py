"""Render a review of a downloaded character model: textured, clay and wireframe views, a turntable and a mesh report.

/Applications/Blender.app/Contents/MacOS/Blender -b --python games/haras_valley/assets/characters/tools/review_model.py -- \
    --input model.glb --output review [--turntable-frames 48]

Nothing is cleaned, remeshed or rigged: the imported mesh and materials are packed into review.blend as they came.
Cameras assume the provider's convention (the character faces +X, up +Z); check it against the renders.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Vector

VIEWS = {'front': (1, 0, 0), 'left': (0, 1, 0), 'back': (-1, 0, 0), 'right': (0, -1, 0), 'three-quarter': (1, .65, .12)}


def aim(obj, point):
    obj.rotation_euler = (Vector(point) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def material(name, color):
    result = bpy.data.materials.new(name)
    result.use_nodes = True
    shader = result.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Roughness'].default_value = .75
    return result


def render(scene, camera, center, scale, direction, path):
    camera.location = center + Vector(direction).normalized() * scale * 4
    aim(camera, center)
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--turntable-frames', type=int, default=48)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    source = args.input.resolve()
    if source.suffix.lower() in {'.glb', '.gltf'}:
        bpy.ops.import_scene.gltf(filepath=str(source))
    elif source.suffix.lower() == '.fbx':
        bpy.ops.import_scene.fbx(filepath=str(source))
    else:
        raise RuntimeError('Expected a GLB, GLTF or FBX source')
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not meshes:
        raise RuntimeError('Import produced no mesh objects')
    corners = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    low = Vector([min(point[i] for point in corners) for i in range(3)])
    high = Vector([max(point[i] for point in corners) for i in range(3)])
    center, extent = (low + high) / 2, high - low
    scale = max(extent)
    report = []
    for obj in meshes:
        topology = bmesh.new()
        topology.from_mesh(obj.data)
        report.append({'object': obj.name, 'vertices': len(obj.data.vertices), 'polygons': len(obj.data.polygons),
                       'polygon_sizes': dict(Counter(len(face.vertices) for face in obj.data.polygons)),
                       'triangles': sum(max(0, len(p.vertices) - 2) for p in obj.data.polygons),
                       'uv_layers': [layer.name for layer in obj.data.uv_layers],
                       'materials': [slot.material.name if slot.material else None for slot in obj.material_slots],
                       'boundary_edges': sum(edge.is_boundary for edge in topology.edges),
                       'non_manifold_edges': sum(not edge.is_manifold for edge in topology.edges)})
        topology.free()

    scene = bpy.context.scene
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items}
    scene.render.engine = 'BLENDER_EEVEE' if 'BLENDER_EEVEE' in engines else 'BLENDER_EEVEE_NEXT'
    scene.render.resolution_x = scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'Standard'
    world = bpy.data.worlds.new('Review world')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Color'].default_value = (.64, .66, .69, 1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = .35
    scene.world = world
    for name, position, energy, size in [('Key', (2, -2, 3), 85, 3), ('Fill', (1, 2, 1), 45, 3), ('Rear', (-2, 1, 2), 60, 2)]:
        light = bpy.data.lights.new(name, 'AREA')
        light.energy, light.shape, light.size = energy * scale * scale, 'DISK', size * scale
        obj = bpy.data.objects.new(name, light)
        scene.collection.objects.link(obj)
        obj.location = center + Vector(position) * scale
        aim(obj, center)
    camera_data = bpy.data.cameras.new('Review camera')
    camera_data.type, camera_data.ortho_scale = 'ORTHO', scale * 1.15
    camera_data.clip_start, camera_data.clip_end = scale * .001, scale * 100
    camera = bpy.data.objects.new('Review camera', camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera

    clay = material('Review clay', (.57, .61, .65))
    wire = material('Review wireframe', (.72, .75, .78))
    nodes = wire.node_tree.nodes
    frame = nodes.new('ShaderNodeWireframe')
    frame.use_pixel_size, frame.inputs['Size'].default_value = True, 1
    mix = nodes.new('ShaderNodeMixRGB')
    mix.inputs[1].default_value, mix.inputs[2].default_value = (.68, .71, .74, 1), (.035, .045, .055, 1)
    wire.node_tree.links.new(frame.outputs['Fac'], mix.inputs[0])
    wire.node_tree.links.new(mix.outputs[0], nodes['Principled BSDF'].inputs['Base Color'])

    renders = output / 'renders'
    renders.mkdir(exist_ok=True)
    layer = bpy.context.view_layer
    for mode, override in [('textured', None), ('clay', clay)]:
        layer.material_override = override
        for name, direction in VIEWS.items():
            render(scene, camera, center, scale, direction, renders / f'{mode}-{name}.png')
    layer.material_override = wire
    for name in ('front', 'three-quarter'):
        render(scene, camera, center, scale, VIEWS[name], renders / f'wireframe-{name}.png')
    layer.material_override = None
    if args.turntable_frames:
        turntable = output / 'turntable-frames'
        turntable.mkdir(exist_ok=True)
        scene.render.resolution_x = scene.render.resolution_y = 500
        for index in range(args.turntable_frames):
            angle = 2 * math.pi * index / args.turntable_frames
            render(scene, camera, center, scale, (math.cos(angle), math.sin(angle), .06), turntable / f'{index:04d}.png')
    bpy.ops.file.pack_all()
    blend = output / 'review.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    (output / 'mesh-report.json').write_text(json.dumps({
        'source': source.name, 'blender_version': bpy.app.version_string,
        'bounds_min': list(low), 'bounds_max': list(high), 'dimensions_m': list(extent),
        'front_axis_assumption': '+X (provider default); check the renders',
        'mesh_objects': report,
        'textures': [{'name': img.name, 'size': list(img.size)} for img in bpy.data.images if img.type == 'IMAGE'],
        'armatures': sum(o.type == 'ARMATURE' for o in scene.objects),
        'note': 'GLTF import is triangulated; the provider\'s quad topology is not visible here.'}, indent=2) + '\n')
    print('Review saved: ' + str(blend), flush=True)


if __name__ == '__main__':
    main()
