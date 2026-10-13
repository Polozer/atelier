"""Import a character's body (assets/characters/pipeline/export.py) into its Unreal folder, and check it.

    CHARACTER=nox UnrealEditor-Cmd Yorimichi.uproject -run=pythonscript -script=Scripts/import_character.py -unattended -nosplash -NullRHI -stdout

Reads build/yorimichi/<output>/export.json and character.toml [unreal] (assets/characters/pipeline/definition.py UNREAL)
and writes, in its unreal_path: SK_<Name> with its skeleton (and physics asset, unless skating fits its own rider), its
materials in the game's character look (base colour with a 30% emissive fill), its own clips (A_<Clip>) and
DA_<Name>Base: the mesh, the clips and its measurements. The merged move set comes on top (import_adventure_moveset.py
copies the base into DA_<Name> with every move).

What export.json carries adds to it:
- `cloth`: the mesh's Chaos cloth (YorimichiCloth.cpp), pinned by its vertex colour, colliding with the capsules it lists;
- `contact_morphs`, with [unreal] contact_morphs: the morph targets whose exact deltas are kept for the skin readers
  (USkinMorphContactData), as desktop cooking otherwise drops them from the CPU;
- clips with `expected_morph_curves`: their compressed morph curves are read back per frame and checked.

Every import then checks the saved assets (unreal_validation.json): the skeleton's bones and parents, each material's
binding and flags, the definition's clips and every recorded morph curve.
"""
import sys as _sys; from pathlib import Path as _Path; _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'world')); import yori  # noqa: E402
import json
import os
import sys
from pathlib import Path

import unreal as U

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'assets' / 'characters' / 'pipeline'))
import animation_compression  # noqa: E402
import definition as character_definition  # noqa: E402
from skin_morph_contacts import validate_contact_data  # noqa: E402

CHARACTER = character_definition.load(os.environ['CHARACTER'])
NAME = CHARACTER.name
SETTINGS = CHARACTER.unreal
OUT = yori.OUT / CHARACTER.output
CONFIG = json.loads((OUT / 'export.json').read_text())
DEST = CHARACTER.unreal_path
CLOTH = CONFIG.get('cloth')
CONTACTS = [*SETTINGS['contact_morphs'], *CONFIG.get('contact_morphs', [])]
MORPHS = SETTINGS['morph_targets']
# How far the cloth hangs free of its skinned position below where it is pinned, cm.
CLOTH_MAX_DISTANCE = 30.
# The largest difference allowed between a recorded morph curve and its compressed read-back.
MORPH_CURVE_ERROR = .002
E = U.EditorAssetLibrary; AT = U.AssetToolsHelpers.get_asset_tools(); M = U.MaterialEditingLibrary; A = U.AnimationLibrary
P = U.AnimPoseExtensions
editor = U.get_editor_subsystem(U.SkeletalMeshEditorSubsystem)
E.make_directory(DEST)


def asset(name, cls, factory):
    path = DEST + '/' + name
    return E.load_asset(path) if E.does_asset_exist(path) else AT.create_asset(name, DEST, cls, factory)


def material(name, cfg):
    mat = asset(name, U.Material, U.MaterialFactoryNew())
    M.delete_all_material_expressions(mat)
    # Opaque until see_through.py masks it again: the opacity mask may still point at its deleted nodes.
    mat.set_editor_property('blend_mode', U.BlendMode.BLEND_OPAQUE)
    mat.set_editor_property('two_sided', cfg['two_sided'])
    mat.set_editor_property('used_with_skeletal_mesh', True)
    if MORPHS:
        mat.set_editor_property('used_with_morph_targets', True)
    if CLOTH and CLOTH['mesh'] in cfg.get('meshes', ()):
        mat.set_editor_property('used_with_clothing', True)   # without it the engine draws the cloth in the default material
    if cfg['texture']:
        task = U.AssetImportTask()
        for k, v in dict(filename=str(OUT / cfg['texture']), destination_path=DEST + '/Textures', automated=True, replace_existing=True, save=True).items():
            task.set_editor_property(k, v)
        AT.import_asset_tasks([task])
        node = M.create_material_expression(mat, U.MaterialExpressionTextureSample)
        node.set_editor_property('texture', E.load_asset(task.imported_object_paths[0]))
        assert M.connect_material_property(node, 'RGB', U.MaterialProperty.MP_BASE_COLOR)
    else:
        node = M.create_material_expression(mat, U.MaterialExpressionConstant3Vector)
        node.set_editor_property('constant', U.LinearColor(*cfg['base_color']))
        assert M.connect_material_property(node, '', U.MaterialProperty.MP_BASE_COLOR)
    # The characters' small albedo fill keeps the unbaked dynamic character readable against baked, environment-lit art.
    fill = M.create_material_expression(mat, U.MaterialExpressionMultiply)
    fill.set_editor_property('const_b', .30)
    assert M.connect_material_expressions(node, 'RGB' if cfg['texture'] else '', fill, 'A')
    assert M.connect_material_property(fill, '', U.MaterialProperty.MP_EMISSIVE_COLOR)
    for field, prop in [('roughness', U.MaterialProperty.MP_ROUGHNESS), ('metallic', U.MaterialProperty.MP_METALLIC), ('specular', U.MaterialProperty.MP_SPECULAR)]:
        c = M.create_material_expression(mat, U.MaterialExpressionConstant)
        c.set_editor_property('r', cfg[field])
        assert M.connect_material_property(c, '', prop)
    M.recompile_material(mat)
    E.save_loaded_asset(mat)
    return mat


def fbx(filename, name, skeleton=None, sample_rate=30):
    task = U.AssetImportTask()
    for prop, value in dict(filename=str(OUT / 'fbx' / filename), destination_path=DEST, destination_name=name,
                            automated=True, replace_existing=True, save=True).items():
        task.set_editor_property(prop, value)
    options = U.FbxImportUI()
    for prop, value in dict(automated_import_should_detect_type=False, import_materials=False, import_textures=False,
                            import_as_skeletal=True, import_mesh=skeleton is None, import_animations=skeleton is not None).items():
        options.set_editor_property(prop, value)
    if skeleton:
        options.set_editor_property('skeleton', skeleton)
        options.set_editor_property('mesh_type_to_import', U.FBXImportType.FBXIT_ANIMATION)
        data = options.get_editor_property('anim_sequence_import_data')
        for k, v in dict(animation_length=U.FBXAnimationLengthImportType.FBXALIT_EXPORTED_TIME, use_default_sample_rate=False,
                         custom_sample_rate=sample_rate, import_bone_tracks=True).items():
            data.set_editor_property(k, v)
        if MORPHS:
            # A revision can turn a formerly animated morph into a constant zero: do not leave the previous clip's curve
            # active when the FBX omits that track.
            data.set_editor_property('delete_existing_morph_target_curves', True)
            data.set_editor_property('do_not_import_curve_with_zero', False)
    else:
        options.set_editor_property('mesh_type_to_import', U.FBXImportType.FBXIT_SKELETAL_MESH)
        options.set_editor_property('create_physics_asset', SETTINGS['physics_asset'])
        data = options.get_editor_property('skeletal_mesh_import_data')
        # The character owns its skeleton and all its clips are rebuilt together, so its bind pose is refreshed.
        for k, v in dict(normal_import_method=U.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS, use_t0_as_ref_pose=False,
                         update_skeleton_reference_pose=True, import_meshes_in_bone_hierarchy=True).items():
            data.set_editor_property(k, v)
        if MORPHS:
            data.set_editor_property('import_morph_targets', True)
        if SETTINGS['vertex_colors']:
            data.set_editor_property('vertex_color_import_option', U.VertexColorImportOption.REPLACE)
    data.set_editor_property('convert_scene', True)
    task.set_editor_property('options', options)
    AT.import_asset_tasks([task])
    imported = [E.load_asset(p) for p in task.get_editor_property('imported_object_paths')]
    result = next((a for a in imported if isinstance(a, U.AnimSequence if skeleton else U.SkeletalMesh)), None)
    assert result is not None, ('import failed', filename)
    return result


def native_morph(names, name):
    """The mesh's morph target for an exported shape key: the importer may prefix a mesh identifier."""
    matches = [native for native in names if native == name or native.endswith('_' + name)]
    assert len(matches) == 1, (NAME, 'morph target', name, matches)
    return matches[0]


def skeleton_tree(mesh):
    """{bone: parent} from root down, each bone once."""
    parents, pending = {'root': None}, ['root']
    while pending:
        bone = pending.pop()
        children = [str(b) for b in editor.get_bone_children(mesh, bone)]
        assert not set(children) & set(parents), (NAME, 'a bone appears twice', children)
        parents.update({child: bone for child in children})
        pending.extend(children)
    return parents


materials = {name: material(name, cfg) for name, cfg in CONFIG['materials'].items()}
mesh = fbx(NAME + '.fbx', 'SK_' + NAME)
if SETTINGS['cpu_access']:   # the skin readers (skating's bail clearance, grips) sample the rider's skin
    U.SkeletalMeshEditorSubsystem.set_allow_cpu_access(mesh, True)
skeleton = mesh.skeleton
slots = list(mesh.materials)
for slot in slots:
    name = str(slot.get_editor_property('imported_material_slot_name'))
    assert name in materials, ('unknown material', name, list(materials))
    slot.set_editor_property('material_interface', materials[name])
mesh.set_editor_property('materials', slots)

cloth = None
if CLOTH:
    # The import rebuilds the mesh, so the cloth is made again every time. Its colliders are a physics asset of their own
    # (PA_<Name>_Cloth): the mesh may keep none, so the skating rider still fits its bodies to the skin.
    capsules = CLOTH['colliders']
    colliders = U.YorimichiClothLibrary.make_capsule_colliders(mesh, f'{DEST}/PA_{NAME}_Cloth', [c['bone'] for c in capsules],
                                                               [c['from'] for c in capsules], [c['to'] for c in capsules],
                                                               [c['radius_cm'] for c in capsules])
    assert colliders, 'the cloth colliders could not be built (see the log)'
    E.save_loaded_asset(colliders)
    section = next(name for name, cfg in CONFIG['materials'].items() if CLOTH['mesh'] in cfg['meshes'])
    cloth = U.YorimichiClothLibrary.add_section_cloth(mesh, section, CLOTH_MAX_DISTANCE, colliders, True)
    assert cloth, 'the cloth could not be built (see the log)'
    U.log(f'{NAME} CLOTH: ' + cloth)
    U.log(f'{NAME} CLOTH DATA: ' + U.YorimichiClothLibrary.describe_cloth(mesh))

contacts, contact_data, contact_receipt = {}, None, None
if CONTACTS:
    names = [str(n) for n in mesh.get_all_morph_target_names()]
    contacts = {name: native_morph(names, name) for name in CONTACTS}
    # After the material and CPU-access setup finish the native mesh build: keep the exact LOD0 deltas.
    contact_data, contact_receipt = U.SkinMorphContactLibrary.capture_skin_morph_contacts(mesh, list(contacts.values()))
    assert contact_data is not None, (NAME, 'contact morph capture failed', contact_receipt)
    contact_receipt = validate_contact_data(U.SkinMorphContactLibrary, mesh, list(contacts.values()), f'{NAME} contact morph data')
elif MORPHS:
    U.SkinMorphContactLibrary.clear_skin_morph_contacts(mesh)
E.save_loaded_asset(mesh)
if CONTACTS:
    contact_receipt = validate_contact_data(U.SkinMorphContactLibrary, mesh, list(contacts.values()), f'Saved {NAME} contact morph data')

parents = skeleton_tree(mesh)
assert parents == CONFIG['parents'], ('imported skeleton mismatch', sorted(set(parents.items()) ^ set(CONFIG['parents'].items())))
clips, report_clips = {}, {}
for name, cfg in CONFIG['clips'].items():
    clip = fbx('A_' + name + '.fbx', 'A_' + name, skeleton, cfg['sample_rate'])
    assert clip.get_editor_property('skeleton') == skeleton
    assert abs(clip.get_editor_property('sequence_length') - cfg['duration']) < .001, (name, clip.get_editor_property('sequence_length'), cfg)
    clip.set_editor_property('enable_root_motion', False)
    animation_compression.apply_to(clip)
    E.save_loaded_asset(clip)
    clips[name] = clip
    curves = {}
    for curve in A.get_animation_curve_names(clip, U.RawCurveTrackTypes.RCT_FLOAT):
        times, values = A.get_float_keys(clip, curve)
        curves[str(curve)] = {'count': len(values), 'min': min(values, default=0), 'max': max(values, default=0), 'values': list(values)}
    report_clips[name] = {'path': clip.get_path_name(), 'duration': clip.get_editor_property('sequence_length'), 'curves': curves}
# The base supplies only the body, framing and the character's own clips; the merged move set's importer adds every move.
factory = U.DataAssetFactory(); factory.set_editor_property('data_asset_class', U.WandererDefinition)
base = asset(f'DA_{NAME}Base', U.WandererDefinition, factory)
for k, v in dict(mesh=mesh, actions=clips, use_authored_movement=True,
                 rest_ankle_heights=U.Vector2D(CONFIG['rest_ankles_cm']['L'], CONFIG['rest_ankles_cm']['R']),
                 sole_height=CONFIG['sole_cm'], camera_height=SETTINGS['camera_height']).items():
    base.set_editor_property(k, v)
E.save_loaded_asset(base)
E.save_loaded_asset(skeleton)
report = {'mesh': mesh.get_path_name(), 'bones': len(parents), 'parents': parents, 'materials': [str(s.material_slot_name) for s in slots],
          'lod_vertices': [editor.get_num_verts(mesh, i) for i in range(editor.get_lod_count(mesh))],
          'morphs': [m.get_name() for m in mesh.get_editor_property('morph_targets')], 'cloth': cloth, 'clips': report_clips,
          'source': CONFIG['source_sha256'], 'contact_morphs': contacts,
          'contact_morph_data': contact_data.get_path_name() if contact_data else None, 'contact_morph_validation': contact_receipt}
(OUT / 'unreal_import.json').write_text(json.dumps(report, indent=2) + '\n')
U.log(f'CHARACTER IMPORTED: {CHARACTER.id}')


# ---- The saved assets, read back --------------------------------------------------------------------------------------
mesh = E.load_asset(f'{DEST}/SK_{NAME}')
base = E.load_asset(f'{DEST}/DA_{NAME}Base')
assert {str(k) for k in base.get_editor_property('actions')} == set(CONFIG['clips']), (NAME, 'the base definition lost clips')
assert base.get_editor_property('use_authored_movement')
for slot in mesh.materials:
    name = str(slot.get_editor_property('imported_material_slot_name'))
    mat = slot.material_interface
    assert mat and mat.get_path_name() == f'{DEST}/{name}.{name}', ('unsaved material binding', name, mat)
    assert mat.get_editor_property('used_with_skeletal_mesh')
    assert not MORPHS or mat.get_editor_property('used_with_morph_targets')
    assert mat.get_editor_property('two_sided') == CONFIG['materials'][name]['two_sided']
options = U.AnimPoseEvaluationOptions()
options.evaluation_type = U.AnimDataEvalType.COMPRESSED
options.optional_skeletal_mesh = mesh
reference = P.get_reference_pose(mesh.skeleton)
rest = {b: [getattr(P.get_bone_pose(reference, b, U.AnimPoseSpaces.WORLD).translation, a) for a in 'xyz']
        for b in ['root', 'pelvis', 'head', 'foot_L', 'foot_R', 'toe_L', 'toe_R']}
morphs = [m.get_name() for m in mesh.get_editor_property('morph_targets')]
errors, rows, max_error = [], {}, 0
for name, cfg in CONFIG['clips'].items():
    expected = cfg.get('expected_morph_curves')
    if not expected:
        continue
    clip = E.load_asset(f'{DEST}/A_{name}')
    targets = {key: native_morph(morphs, key) for key in expected}
    worst, checked, worst_sample = 0, 0, None
    for frame in range(cfg['frames']):
        pose = P.get_anim_pose_at_time(clip, frame / cfg['fps'], options)
        assert P.is_valid(pose)
        for key, values in expected.items():
            actual = P.get_curve_weight(pose, targets[key])
            error = abs(actual - values[frame]); checked += 1
            if error > worst:
                worst, worst_sample = error, {'frame': frame, 'curve': key, 'expected': values[frame], 'actual': actual}
    if worst > MORPH_CURVE_ERROR:
        errors.append(f'{name}: morph curve error {worst}')
    max_error = max(max_error, worst)
    rows[name] = {'frames': cfg['frames'], 'checked_curve_samples': checked, 'max_curve_error': worst, 'worst_sample': worst_sample}
validation = {'passed': not errors, 'errors': errors, 'rest_bones_cm': rest, 'morph_targets': morphs, 'clips': rows,
              'max_curve_error': max_error}
(OUT / 'unreal_validation.json').write_text(json.dumps(validation, indent=2) + '\n')
U.log(f'{NAME} VALIDATION ' + json.dumps(validation))
assert not errors, errors
U.log(f'CHARACTER IMPORT COMPLETE: {CHARACTER.id}')
