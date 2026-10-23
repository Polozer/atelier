"""T1b Blender op: build the frozen pyramid in an empty factory scene and export it as GLB.

Every face corner carries its own UV and every face its material slot, so the export proves
corner, UV and material fidelity. A probe output records what reached the job (selected bytes,
params, seed, declared code, Blender identity and hash seed) for the session's checks.
"""
import hashlib
import json
import os
import random
import socket  # noqa: F401 - network attempts use it without an import of their own
import sys

import bmesh
import bpy

STARTUP = set(sys.modules) - {'atelier_job_entry'}  # loaded by Blender before this op


def build(data, name):
    mesh = bpy.data.meshes.new(name)
    for material in data['materials']:
        mesh.materials.append(bpy.data.materials.new(material))
    shape = bmesh.new()
    verts = [shape.verts.new(position) for position in data['positions']]
    uv = shape.loops.layers.uv.new('UVMap')
    for face in data['faces']:
        made = shape.faces.new([verts[index] for index in face['corners']])
        made.material_index = face['material']
        for loop, value in zip(made.loops, face['uvs']):
            loop[uv].uv = value
    shape.to_mesh(mesh)
    shape.free()
    target = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(target)
    # The seed moves the object, never the mesh data, so fidelity holds for any seed.
    target.location = (round(random.random(), 3), 0.0, 0.0)


def run(context):
    before = sorted(bpy.data.objects.keys()), sorted(bpy.data.meshes.keys()), sorted(bpy.data.materials.keys())
    selected = context.input('mesh').read_bytes()
    build(json.loads(selected), context.params['name'])
    # The scene holds only this object; Z stays up so positions compare as declared.
    bpy.ops.export_scene.gltf(filepath=os.path.abspath(context.output('model.glb')), export_format='GLB', export_yup=False)
    for attempt in context.params.get('attempts', []):
        exec(attempt)
    if not context.params.get('skip_probe'):
        probe = {
            'blender': bpy.app.version_string,
            'build_hash': bpy.app.build_hash.decode(),
            'factory_scene_before': before,
            'addons': sorted(bpy.context.preferences.addons.keys()),
            'hash': hash('atelier-t1b'),
            'hash_seed': os.environ.get('PYTHONHASHSEED'),
            'hash_randomization': sys.flags.hash_randomization,
            'random': [random.random() for _ in range(2)],
            'seed': context.seed,
            'params': dict(context.params),
            'inputs': {name: str(path) for name, path in context.inputs.items()},
            'selected_sha256': hashlib.sha256(selected).hexdigest(),
            'listing': sorted(os.listdir('.')),
            'job_modules': sorted(name for name, module in sys.modules.items() if name not in STARTUP
                                  and os.path.realpath(getattr(module, '__file__', None) or '/').startswith(os.getcwd())),
        }
        context.output('probe.json').write_text(json.dumps(probe, sort_keys=True))
