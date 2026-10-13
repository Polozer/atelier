"""A character's imported assets, recorded for comparison: proof that a change to its export or import leaves them as
they were.

    CHARACTER=nox SNAPSHOT=/path/dir UnrealEditor-Cmd Yorimichi.uproject -run=pythonscript -script=Scripts/character_snapshot.py -unattended -nosplash -NullRHI -stdout
    python games/yorimichi/unreal/Scripts/character_snapshot.py --compare OLD_DIR NEW_DIR

Writes into SNAPSHOT: mesh.txt (SK_<Name>'s LOD 0 as built: UMeshImportAudit::DumpSkeletalMesh) and snapshot.json:
the reference skeleton (bones, parents, reference pose), each material slot's binding and flags, the base definition
and, for every clip under the character's folders (its own, /Adventure and <Name>Bike), the compressed pose of every
bone, every curve and the root per frame. `--compare` matches the two, order-independently where an import may reorder
(render vertices, triangles, morph deltas), within the tolerances below; FBX and package bytes are not compared, as
they carry timestamps and paths.
"""
import json
import math
import os
import sys
from pathlib import Path

POSITION = 1e-3   # cm: the imports' float32 positions and the dump's six decimals
DIRECTION = 1e-3  # normals, UVs, weights, quaternion components and curve values
ANGLE = 1e-2      # degrees


def snapshot():
    import unreal as U
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'assets' / 'characters' / 'pipeline'))
    import definition
    character = definition.load(os.environ['CHARACTER'])
    out = Path(os.environ['SNAPSHOT'])
    out.mkdir(parents=True, exist_ok=True)
    E, P, A = U.EditorAssetLibrary, U.AnimPoseExtensions, U.AnimationLibrary
    editor = U.get_editor_subsystem(U.SkeletalMeshEditorSubsystem)
    name, dest = character.name, character.unreal_path
    mesh = E.load_asset(f'{dest}/SK_{name}')
    assert mesh, (character.id, 'no mesh')
    assert U.MeshImportAudit.dump_skeletal_mesh(mesh, str(out / 'mesh.txt'))

    def transform(t):
        return {'t': [t.translation.x, t.translation.y, t.translation.z],
                'q': [t.rotation.x, t.rotation.y, t.rotation.z, t.rotation.w], 's': [t.scale3d.x, t.scale3d.y, t.scale3d.z]}

    parents, pending = {'root': None}, ['root']
    while pending:
        bone = pending.pop()
        for child in (str(b) for b in editor.get_bone_children(mesh, bone)):
            parents[child] = bone
            pending.append(child)
    bones = sorted(parents)
    reference = P.get_reference_pose(mesh.skeleton)
    data = {'parents': parents,
            'reference': {b: transform(P.get_bone_pose(reference, b, U.AnimPoseSpaces.WORLD)) for b in bones},
            'morphs': sorted(m.get_name() for m in mesh.get_editor_property('morph_targets')),
            'physics_asset': physics.get_path_name() if (physics := mesh.get_editor_property('physics_asset')) else None,
            'materials': {}}
    for slot in mesh.materials:
        material = slot.material_interface
        data['materials'][str(slot.get_editor_property('imported_material_slot_name'))] = {
            'path': material.get_path_name() if material else None,
            **{flag: bool(material.get_editor_property(flag)) for flag in
               ('two_sided', 'used_with_skeletal_mesh', 'used_with_morph_targets', 'used_with_clothing') if material}}
    base = E.load_asset(f'{dest}/DA_{name}Base')
    if base:
        data['base'] = {'actions': {str(k): v.get_path_name() for k, v in base.get_editor_property('actions').items()},
                        **{k: str(base.get_editor_property(k)) for k in ('camera_height', 'sole_height', 'rest_ankle_heights',
                                                                         'use_authored_movement')}}
    options = U.AnimPoseEvaluationOptions()
    options.evaluation_type = U.AnimDataEvalType.COMPRESSED
    options.optional_skeletal_mesh = mesh
    clips = {}
    for folder in (dest, dest + 'Bike'):
        if not E.does_directory_exist(folder):
            continue
        for path in sorted(E.list_assets(folder, recursive=True)):
            clip = E.load_asset(path)
            if not isinstance(clip, U.AnimSequence) or clip.get_editor_property('skeleton') != mesh.skeleton:
                continue
            length = clip.get_editor_property('sequence_length')
            rate = clip.get_editor_property('target_frame_rate')
            fps = rate.numerator / rate.denominator if rate.denominator else 30.
            curves = sorted(str(c) for c in A.get_animation_curve_names(clip, U.RawCurveTrackTypes.RCT_FLOAT))
            frames = []
            for frame in range(int(round(length * fps)) + 1):
                pose = P.get_anim_pose_at_time(clip, min(frame / fps, length), options)
                frames.append({'bones': {b: transform(P.get_bone_pose(pose, b, U.AnimPoseSpaces.WORLD)) for b in bones},
                               'curves': {c: P.get_curve_weight(pose, c) for c in curves}})
            clips[path.split('.')[0]] = {'length': length, 'fps': fps, 'root_motion': bool(clip.get_editor_property('enable_root_motion')),
                                         'curves': curves, 'frames': frames}
    data['clips'] = clips
    (out / 'snapshot.json').write_text(json.dumps(data) + '\n')
    U.log(f'CHARACTER SNAPSHOT COMPLETE: {character.id} {len(clips)} clips')


def read_mesh(path):
    """(vertices, triangles, morph deltas) as sorted tuples: positions and weights rounded to the tolerances."""
    vertices, faces, morphs = [], [], []
    for line in Path(path).read_text().splitlines():
        kind, *rest = line.split()
        if kind == 'v':
            vertices.append((int(rest[0]), [float(x) for x in rest[1:9]],
                             sorted((w.rsplit(':', 1)[0], float(w.rsplit(':', 1)[1])) for w in rest[9:])))
        elif kind == 'f':
            faces.append(tuple(int(x) for x in rest))
        elif kind == 'm':
            morphs.append((rest[0], int(rest[1]), [float(x) for x in rest[2:]]))
    return vertices, faces, morphs


def close(a, b, tolerance):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b)) and len(a) == len(b)


def compare_mesh(old, new):
    """Vertices matched by their attributes (an import may reorder them); triangles and morph deltas by the matched
    vertices. Returns a list of differences."""
    (va, fa, ma), (vb, fb, mb) = read_mesh(old), read_mesh(new)
    if len(va) != len(vb):
        return [f'vertices {len(va)} != {len(vb)}']
    key = lambda v: (v[0], *(round(x / POSITION) for x in v[1][:3]), *(round(x / DIRECTION) for x in v[1][3:]))
    order_a = sorted(range(len(va)), key=lambda i: key(va[i]))
    order_b = sorted(range(len(vb)), key=lambda i: key(vb[i]))
    errors = []
    for i, j in zip(order_a, order_b):
        a, b = va[i], vb[j]
        if a[0] != b[0] or not close(a[1][:3], b[1][:3], POSITION) or not close(a[1][3:], b[1][3:], DIRECTION) \
                or [w[0] for w in a[2]] != [w[0] for w in b[2]] or not close([w[1] for w in a[2]], [w[1] for w in b[2]], DIRECTION):
            errors.append(f'vertex {i}/{j}: {a} != {b}')
            if len(errors) > 10:
                return errors
    to_b = dict(zip(order_a, order_b))
    def triangle(f):   # the same triangle, wound the same way, from its lowest vertex
        i = f.index(min(f))
        return f[i:] + f[:i]
    if sorted(triangle(tuple(to_b[x] for x in f)) for f in fa) != sorted(triangle(f) for f in fb):
        errors.append('triangles differ')
    deltas_a = sorted((m, to_b[v], *(round(x / POSITION) for x in d)) for m, v, d in ma)
    deltas_b = sorted((m, v, *(round(x / POSITION) for x in d)) for m, v, d in mb)
    if len(deltas_a) != len(deltas_b):
        errors.append(f'morph deltas {len(deltas_a)} != {len(deltas_b)}')
    else:
        bad = [(a, b) for a, b in zip(deltas_a, deltas_b) if a[:2] != b[:2] or max(abs(x - y) for x, y in zip(a[2:], b[2:])) > 1]
        if bad:
            errors.append(f'{len(bad)} morph deltas differ, e.g. {bad[:3]}')
    return errors


def angle(q, r):
    dot = min(1., abs(sum(x * y for x, y in zip(q, r))))
    return math.degrees(2 * math.acos(dot))


def compare_transform(a, b):
    return close(a['t'], b['t'], POSITION) and angle(a['q'], b['q']) <= ANGLE and close(a['s'], b['s'], DIRECTION)


def compare(old, new):
    old, new = Path(old), Path(new)
    a, b = json.loads((old / 'snapshot.json').read_text()), json.loads((new / 'snapshot.json').read_text())
    report = {'mesh': compare_mesh(old / 'mesh.txt', new / 'mesh.txt')}
    for key in ('parents', 'morphs', 'physics_asset', 'materials', 'base'):
        report[key] = [] if a.get(key) == b.get(key) else [f'{a.get(key)} != {b.get(key)}']
    report['reference'] = [bone for bone in a['reference'] if bone not in b['reference']
                           or not compare_transform(a['reference'][bone], b['reference'][bone])]
    clips = report['clips'] = {}
    for path in sorted(set(a['clips']) | set(b['clips'])):
        if path not in a['clips'] or path not in b['clips']:
            clips[path] = ['only in ' + ('new' if path not in a['clips'] else 'old')]
            continue
        x, y = a['clips'][path], b['clips'][path]
        errors = [f'{k} {x[k]} != {y[k]}' for k in ('fps', 'root_motion', 'curves') if x[k] != y[k]]
        if abs(x['length'] - y['length']) > 1e-3 or len(x['frames']) != len(y['frames']):
            errors.append(f"length {x['length']} != {y['length']}")
        else:
            for frame, (p, q) in enumerate(zip(x['frames'], y['frames'])):
                bad = [bone for bone in p['bones'] if bone not in q['bones'] or not compare_transform(p['bones'][bone], q['bones'][bone])]
                bad += [c for c in p['curves'] if abs(p['curves'][c] - q['curves'].get(c, math.inf)) > DIRECTION]
                if bad:
                    errors.append(f'frame {frame}: {bad[:5]}')
                    break
        if errors:
            clips[path] = errors
    differ = {k: v for k, v in report.items() if v}
    return {'passed': not differ, 'clips_compared': len(set(a['clips']) & set(b['clips'])), 'differ': differ}


if __name__ == '__main__' and '--compare' in sys.argv:
    first, second = sys.argv[sys.argv.index('--compare') + 1:][:2]
    result = compare(first, second)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['passed'] else 1)
else:
    snapshot()
