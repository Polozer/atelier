"""Import the Belmonte train (docs/BELMONTE_TRAIN_SHELL.md) into /Game/BelmonteTrain for ABelmonteTrainService.

Reads build/yorimichi/belmonte-train/service/service.json (tools/belmonte_train_service.py) and the Train Builder's GLBs:

- each vehicle's LOD0, LOD1 and LOD2 as one static mesh SM_BT_<Vehicle> with three LODs (no Nanite; the screen sizes
  in the service's `render`), and its simple collision: the fixed (UCX) boxes from the placements, set through
  UBelmonteTrainImportLibrary.SetSimpleBoxes and used as complex collision. The switchable boxes (doors, gangway
  locks) stay named data in service.json, not merged into the mesh.
- each furniture asset as SM_BTF_<Asset>, from the LOD worker's levels (furniture/lod/) when recorded, else the
  fitted Tripo GLB: re-running this step swaps in whatever levels exist.

Then copies service.json to Content/Data/belmonte_train/ and writes import-report.json beside it in the build.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'world'))
import yori
import hashlib
import json
import shutil
import unreal

TRAIN = yori.OUT / 'belmonte-train'
SERVICE = TRAIN / 'service' / 'service.json'
ROOT = '/Game/BelmonteTrain'
DATA = Path(__file__).resolve().parents[1] / 'Content' / 'Data' / 'belmonte_train'
E = unreal.EditorAssetLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()
REGISTRY = unreal.AssetRegistryHelpers.get_asset_registry()


def pipeline():
    generic = unreal.InterchangeGenericAssetsPipeline()
    mesh = generic.get_editor_property('mesh_pipeline')
    mesh.set_editor_property('import_static_meshes', True)
    mesh.set_editor_property('import_skeletal_meshes', False)
    mesh.set_editor_property('combine_static_meshes_behavior', unreal.InterchangeCombineStaticMeshesBehavior.ALL)
    mesh.set_editor_property('build_nanite', False)
    # The vehicles' simple collision is set from the placements' boxes below; the liveries include a 3072 x 1024 sheet.
    mesh.set_editor_property('collision', False)
    mesh.set_editor_property('import_collision_according_to_mesh_name', False)
    material = generic.get_editor_property('material_pipeline')
    material.get_editor_property('texture_pipeline').set_editor_property('allow_non_power_of_two', True)
    generic.get_editor_property('animation_pipeline').set_editor_property('import_animations', False)
    stack = unreal.InterchangePipelineStackOverride()
    stack.add_pipeline(generic)
    stack.add_pipeline(unreal.InterchangeGLTFPipeline())
    return stack


def import_mesh(path, folder, target):
    """The GLB as one static mesh at `target`, its materials and textures under `folder`."""
    task = unreal.AssetImportTask()
    for key, value in dict(filename=str(path), destination_path=folder, automated=True, replace_existing=True, save=True).items():
        task.set_editor_property(key, value)
    task.set_editor_property('options', pipeline())
    AT.import_asset_tasks([task])
    meshes = [str(d.package_name) for d in REGISTRY.get_assets_by_path(folder, recursive=True)
              if str(d.asset_class_path.asset_name) == 'StaticMesh']
    assert len(meshes) == 1, (path, meshes)
    assert E.rename_asset(meshes[0], target), (path, 'rename failed', target)
    mesh = E.load_asset(target)
    assert mesh, target
    return mesh


def with_lods(name, levels, screen_sizes, meshes):
    """SM <name> from its level GLBs: LOD0 imported in place, the others attached as its LODs."""
    target = f'{ROOT}/{name}' if not name.startswith('SM_BTF_') else f'{ROOT}/Furniture/{name}'
    mesh = import_mesh(levels[0], f'{ROOT}/Source/{name}/LOD0', target)
    for level, path in enumerate(levels[1:], 1):
        source = import_mesh(path, f'{ROOT}/Source/{name}/LOD{level}', f'{ROOT}/Source/{name}/{name}_LOD{level}')
        assert meshes.set_lod_from_static_mesh(mesh, level, source, 0, True) == level, (name, level)
    assert mesh.get_num_lods() == len(levels), (name, mesh.get_num_lods())
    if len(levels) > 1:
        assert meshes.set_lod_screen_sizes(mesh, screen_sizes[:len(levels)]), name
    return mesh


def instanced_materials(mesh, two_sided=False):
    """Furniture is drawn as instanced static meshes: its materials' parents need that usage, which the glTF masters
    (engine plugin content) lack. Their copies in /Game/BelmonteTrain/Materials carry it. Thin sheets (two_sided) also
    override their instances to draw both faces."""
    slots = list(mesh.get_editor_property('static_materials'))
    for slot in slots:
        instance = slot.get_editor_property('material_interface')
        if not isinstance(instance, unreal.MaterialInstanceConstant):
            continue
        if two_sided:
            overrides = instance.get_editor_property('base_property_overrides')
            overrides.set_editor_property('override_two_sided', True)
            overrides.set_editor_property('two_sided', True)
            instance.set_editor_property('base_property_overrides', overrides)
            unreal.MaterialEditingLibrary.update_material_instance(instance)
            E.save_loaded_asset(instance, only_if_is_dirty=False)
        parent = instance.get_base_material()
        if not parent or parent.get_editor_property('used_with_instanced_static_meshes'):
            continue
        path = f'{ROOT}/Materials/{parent.get_name()}_ISM'
        if not E.does_asset_exist(path):
            copy = E.duplicate_asset(parent.get_path_name(), path)
            copy.set_editor_property('used_with_instanced_static_meshes', True)
            unreal.MaterialEditingLibrary.recompile_material(copy)
            E.save_loaded_asset(copy, only_if_is_dirty=False)
        unreal.MaterialEditingLibrary.set_material_instance_parent(instance, E.load_asset(path))
        E.save_loaded_asset(instance, only_if_is_dirty=False)


def box(values):
    lo, hi = unreal.Vector(*values[:3]), unreal.Vector(*values[3:])
    try:
        return unreal.Box(lo, hi, True)
    except TypeError:
        b = unreal.Box(); b.min = lo; b.max = hi; b.is_valid = True
        return b


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    data = json.loads(SERVICE.read_text())
    unreal.SystemLibrary.execute_console_command(None, 'Editor.AsyncStaticMeshCompilation 0')
    unreal.load_module('StaticMeshEditor')
    meshes = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    manifest = json.loads((TRAIN / 'manifest.json').read_text())['coaches']
    if E.does_directory_exist(ROOT):
        E.delete_directory(ROOT)
    E.make_directory(ROOT)
    sizes = data['render']['screen_sizes']
    report = {'vehicles': {}, 'furniture': {}}
    for vehicle in data['consist']['vehicles']:
        name = vehicle['name']
        levels = [(TRAIN / p).resolve() for p in vehicle['levels']]
        levels = [p for p in levels if p.exists()]
        assert levels and levels[0].exists(), (name, 'no LOD0')
        mesh = with_lods(name, levels, sizes, meshes)
        count = unreal.BelmonteTrainImportLibrary.set_simple_boxes(mesh, [box(b) for b in vehicle['collision']])
        assert count == len(vehicle['collision']), (name, count, len(vehicle['collision']))
        mesh.set_editor_property('lod_for_collision', 0)
        E.save_loaded_asset(mesh, only_if_is_dirty=False)
        triangles = [mesh.get_num_triangles(i) for i in range(mesh.get_num_lods())]
        expected = (manifest.get(vehicle['id']) or {}).get('triangles', {})
        if expected.get('LOD0') and abs(triangles[0] - expected['LOD0']) > expected['LOD0'] * .02:
            unreal.log_warning(f'BELMONTE TRAIN {name} LOD0 has {triangles[0]} triangles, the build says {expected["LOD0"]}')
        b = mesh.get_bounding_box()
        report['vehicles'][name] = dict(asset=mesh.get_path_name(), triangles=triangles, boxes=count,
                                        switchable=len(vehicle['switchable']),
                                        screen_sizes=list(meshes.get_lod_screen_sizes(mesh)),
                                        bounds=[[b.min.x, b.min.y, b.min.z], [b.max.x, b.max.y, b.max.z]],
                                        sources={p.name: sha(p) for p in levels})
        unreal.log(f'BELMONTE TRAIN vehicle {name} lods={len(triangles)} triangles={triangles} boxes={count}')
        # The door leaves: their own meshes in the vehicle's frame, on the vehicle's own materials (by slot name).
        slots = {str(m.get_editor_property('imported_material_slot_name')): m.get_editor_property('material_interface')
                 for m in mesh.get_editor_property('static_materials')}
        leaves = 0
        for door in vehicle['doors']:
            for leaf in door['leaves']:
                if not leaf.get('glb'):
                    continue
                leaf_name = leaf['mesh'].rsplit('/', 1)[1].split('.')[0]
                part = import_mesh((TRAIN / leaf['glb']).resolve(), f'{ROOT}/Source/{leaf_name}', f'{ROOT}/Doors/{leaf_name}')
                materials = list(part.get_editor_property('static_materials'))
                matched = True
                for m in materials:
                    shared = slots.get(str(m.get_editor_property('imported_material_slot_name')))
                    if shared:
                        m.set_editor_property('material_interface', shared)
                    else:
                        matched = False
                part.set_editor_property('static_materials', materials)
                body = part.get_editor_property('body_setup')
                if body:
                    body.set_editor_property('collision_trace_flag', unreal.CollisionTraceFlag.CTF_USE_SIMPLE_AS_COMPLEX)
                E.save_loaded_asset(part, only_if_is_dirty=False)
                if matched and E.does_directory_exist(f'{ROOT}/Source/{leaf_name}'):
                    E.delete_directory(f'{ROOT}/Source/{leaf_name}')
                leaves += 1
        report['vehicles'][name]['door_leaves'] = leaves
    for asset, spec in data['furniture'].items():
        name = spec['mesh'].rsplit('/', 1)[1].split('.')[0]
        levels = [TRAIN / 'furniture' / level['glb'] for level in spec['levels']]
        missing = [str(p) for p in levels if not p.exists()]
        assert not missing, (asset, missing)
        mesh = with_lods(name, levels, [level['screen_size'] for level in spec['levels']], meshes)
        instanced_materials(mesh, spec.get('two_sided', False))
        E.save_loaded_asset(mesh, only_if_is_dirty=False)
        report['furniture'][asset] = dict(asset=mesh.get_path_name(),
                                          triangles=[mesh.get_num_triangles(i) for i in range(mesh.get_num_lods())],
                                          cull_cm=spec['cull_cm'], shadow=spec['shadow'],
                                          two_sided=spec.get('two_sided', False))
    DATA.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SERVICE, DATA / 'service.json')
    (TRAIN / 'service' / 'import-report.json').write_text(json.dumps(report, indent=2) + '\n')
    unreal.log(f'BELMONTE TRAIN IMPORT COMPLETE vehicles={len(report["vehicles"])} furniture={len(report["furniture"])}')


main()
