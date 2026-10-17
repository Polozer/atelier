"""A character's prepared body, recorded for comparison: proof that a change to the rig steps (rig.py) leaves it as it was.

    blender -b --python games/yorimichi/assets/characters/pipeline/fingerprint.py -- --character nox --out nox.npz
        [--legacy OLD/export_unreal.py]       # a former per-character `prepare(source)`, opened on the same source
    python games/yorimichi/assets/characters/pipeline/fingerprint.py --compare old.npz new.npz

Records, after `prepare`: the armature's bones (names, parents, rest matrices), each body mesh (world matrix, vertex
positions and normals, faces, UV and colour layers, weights by group name, shape-key deltas, material slots and
modifiers), and every authored clip sampled per frame (each bone's pose matrix and each shape key's value). `--compare`
prints, per array, whether the two match: names and topology exactly, floats within TOLERANCE.
"""
from pathlib import Path
import argparse
import json
import sys

import numpy as np

TOLERANCE = 1e-5   # metres, or matrix entries: float32 rounding over a 2 m body is about 1e-7


def compare(a, b):
    """{array: None (equal) or a description of the difference}, for two fingerprints."""
    a, b = np.load(a, allow_pickle=False), np.load(b, allow_pickle=False)
    out = {}
    for key in sorted(set(a.files) | set(b.files)):
        if key not in a.files or key not in b.files:
            out[key] = 'only in ' + ('the second' if key not in a.files else 'the first')
            continue
        x, y = a[key], b[key]
        if x.shape != y.shape:
            out[key] = f'shape {x.shape} != {y.shape}'
        elif x.dtype.kind in 'fc':
            error = float(np.max(np.abs(x - y))) if x.size else 0.
            out[key] = None if error <= TOLERANCE else f'max difference {error:.3g}'
        else:
            out[key] = None if np.array_equal(x, y) else f'{int(np.sum(x != y))} entries differ'
    return out


def record(prepared, fps):
    import bpy
    scene, arm, meshes = prepared.scene, prepared.arm, sorted(prepared.meshes, key=lambda o: o.name)
    out = {}
    bones = sorted(b.name for b in arm.data.bones)
    out['bones'] = np.array(bones)
    out['bone_parents'] = np.array([arm.data.bones[n].parent.name if arm.data.bones[n].parent else '' for n in bones])
    out['bone_rest'] = np.array([np.array(arm.matrix_world @ arm.data.bones[n].matrix_local) for n in bones])
    out['armature_world'] = np.array(arm.matrix_world)
    out['meshes'] = np.array([o.name for o in meshes])
    for i, obj in enumerate(meshes):
        key, mesh = f'mesh{i}_', obj.data
        world = np.array(obj.matrix_world)
        co = np.array([v.co for v in mesh.vertices]).reshape(-1, 3)
        out[key + 'world'] = world
        out[key + 'positions'] = co @ world[:3, :3].T + world[:3, 3]
        out[key + 'normals'] = np.array([v.normal for v in mesh.vertices]).reshape(-1, 3)
        out[key + 'faces'] = np.array([i for p in mesh.polygons for i in p.vertices], dtype=np.int64)
        out[key + 'face_sizes'] = np.array([p.loop_total for p in mesh.polygons], dtype=np.int64)
        out[key + 'face_materials'] = np.array([p.material_index for p in mesh.polygons], dtype=np.int64)
        out[key + 'materials'] = np.array([m.name if m else '' for m in mesh.materials])
        out[key + 'modifiers'] = np.array([f'{m.type}:{m.name}' for m in obj.modifiers])
        for layer in mesh.uv_layers:
            out[f'{key}uv_{layer.name}'] = np.array([d.uv for d in layer.data]).reshape(-1, 2)
        for layer in mesh.color_attributes:
            out[f'{key}color_{layer.name}'] = np.array([d.color for d in layer.data]).reshape(-1, 4)
        groups = {g.index: g.name for g in obj.vertex_groups}
        out[key + 'groups'] = np.array(sorted(groups.values()))
        weights = sorted((v.index, groups[g.group], g.weight) for v in mesh.vertices for g in v.groups)
        out[key + 'weight_vertices'] = np.array([w[0] for w in weights], dtype=np.int64)
        out[key + 'weight_groups'] = np.array([w[1] for w in weights])
        out[key + 'weight_values'] = np.array([w[2] for w in weights])
        if mesh.shape_keys:
            blocks = mesh.shape_keys.key_blocks
            basis = np.array([d.co for d in blocks[0].data]).reshape(-1, 3)
            out[key + 'shape_keys'] = np.array([k.name for k in blocks])
            out[key + 'shape_values'] = np.array([k.value for k in blocks])
            for j, block in enumerate(blocks[1:], 1):
                out[f'{key}shape{j}_delta'] = np.array([d.co for d in block.data]).reshape(-1, 3) - basis
    clips = sorted({r['clip'] for r in prepared.record.get('roles', [])} & {a.name for a in bpy.data.actions})
    out['clips'] = np.array(clips)
    keyed = [o for o in meshes if o.data.shape_keys]
    for i, name in enumerate(clips):
        action = bpy.data.actions[name]
        prepared.set_clip(arm, action)
        start, end = map(int, action.frame_range)
        poses, values = [], []
        for frame in range(start, end + 1):
            scene.frame_set(frame)
            poses.append([np.array(arm.pose.bones[n].matrix) for n in bones])
            values.append([k.value for o in keyed for k in o.data.shape_keys.key_blocks[1:]])
        out[f'clip{i}_poses'] = np.array(poses)
        out[f'clip{i}_shape_values'] = np.array(values)
    out['transform'] = np.array(prepared.transform)
    out['scale_floor'] = np.array([prepared.scale, prepared.floor])
    out['fps'] = np.array([fps])
    return out


def main(args):
    import importlib.util
    from types import SimpleNamespace
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import definition
    import rig
    character = definition.load(args.character)
    if args.legacy:
        spec = importlib.util.spec_from_file_location('legacy_export', args.legacy)
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        prepared = legacy.prepare(character.folder)
    else:
        prepared = rig.load(character).prepare()
    import bpy
    prepared = SimpleNamespace(**vars(prepared), set_clip=rig.set_clip)
    data = record(prepared, bpy.context.scene.render.fps)
    np.savez_compressed(args.out, **data)
    print('FINGERPRINT', args.character, 'legacy' if args.legacy else 'shared', len(data), 'arrays', args.out, flush=True)


if __name__ == '__main__':
    if '--compare' in sys.argv:
        first, second = sys.argv[sys.argv.index('--compare') + 1:][:2]
        result = compare(first, second)
        differ = {k: v for k, v in result.items() if v}
        print(json.dumps({'arrays': len(result), 'differ': differ}, indent=2))
        sys.exit(1 if differ else 0)
    parser = argparse.ArgumentParser()
    parser.add_argument('--character', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--legacy', help='a former per-character export_unreal.py, whose prepare(source) is compared')
    main(parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
