"""Import the Sunburst-textured Kasa Ronin equipment and Roadside Mini-Camp meshes into /Game/SwordCamp."""
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'world'))
import yori  # noqa: E402
import json
from pathlib import Path
import unreal

_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import atmosphere  # noqa: E402
from mesh_import import import_mesh as import_fbx  # noqa: E402

OUT = yori.OUT / 'swordcamp'
FBX_DIR = OUT / 'fbx'
SEED = FBX_DIR / 'SM_RoninKatana.fbx'
DEST_MESH = '/Game/SwordCamp/Assets'
DEST_TEX = '/Game/SwordCamp/Textures'
DEST_MAT = '/Game/SwordCamp/Materials'

EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
AT = unreal.AssetToolsHelpers.get_asset_tools()

SOLID_PROPS = {'SM_CampJinmaku', 'SM_CampFirePit', 'SM_CampWeaponRack', 'SM_CampBales'}


def import_atlas():
    task = unreal.AssetImportTask()
    task.filename = str(OUT / 'swordcamp_atlas.jpg')
    task.destination_path = DEST_TEX
    task.destination_name = 'T_SwordCampAtlas'
    task.automated = True
    task.replace_existing = True
    task.save = True
    AT.import_asset_tasks([task])
    tex = EAL.load_asset(f'{DEST_TEX}/T_SwordCampAtlas')
    assert tex, 'Failed to import T_SwordCampAtlas'
    tex.set_editor_property('srgb', True)
    tex.set_editor_property('max_texture_size', 2048)
    tex.set_editor_property('lod_group', unreal.TextureGroup.TEXTUREGROUP_WORLD)
    EAL.save_loaded_asset(tex)
    return tex


def build_material(atlas_tex):
    path = f'{DEST_MAT}/M_SwordCamp'
    m = EAL.load_asset(path) if EAL.does_asset_exist(path) else None
    if not m:
        m = AT.create_asset('M_SwordCamp', DEST_MAT, unreal.Material, unreal.MaterialFactoryNew())
    MEL.delete_all_material_expressions(m)

    def node(cls, x, y, **kwargs):
        e = MEL.create_material_expression(m, cls, x, y)
        for k, v in kwargs.items():
            e.set_editor_property(k, v)
        return e

    def link(a, ao, b, bi):
        assert MEL.connect_material_expressions(a, ao, b, bi)

    tex = node(unreal.MaterialExpressionTextureSampleParameter2D, -700, 0, parameter_name='Tex', texture=atlas_tex)
    vc = node(unreal.MaterialExpressionVertexColor, -700, 260)
    fill = node(
        unreal.MaterialExpressionCustom,
        -320,
        120,
        code='return C*(.06+saturate(G)*.95);',
        output_type=unreal.CustomMaterialOutputType.CMOT_FLOAT3,
    )
    fill_inputs = []
    for key in ('C', 'G'):
        arg = unreal.CustomInput()
        arg.set_editor_property('input_name', key)
        fill_inputs.append(arg)
    fill.set_editor_property('inputs', fill_inputs)
    link(tex, 'RGB', fill, 'C')
    link(vc, 'R', fill, 'G')

    base, glow = atmosphere.apply(m, tex, fill, x=120, y=0)
    assert MEL.connect_material_property(base, '', unreal.MaterialProperty.MP_BASE_COLOR)
    assert MEL.connect_material_property(glow, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    rough = node(unreal.MaterialExpressionConstant, 120, 420, r=0.92)
    spec = node(unreal.MaterialExpressionConstant, 120, 520, r=0.04)
    MEL.connect_material_property(rough, '', unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(spec, '', unreal.MaterialProperty.MP_SPECULAR)

    wind = node(
        unreal.MaterialExpressionCustom,
        120,
        680,
        code='float phase=T*2.1+P.x*.003+P.y*.004; return float3(sin(phase)*2.4,cos(phase*.85)*1.6,sin(phase*1.4)*.5)*W*W;',
        output_type=unreal.CustomMaterialOutputType.CMOT_FLOAT3,
    )
    args = []
    for key in ('T', 'P', 'W'):
        a = unreal.CustomInput()
        a.set_editor_property('input_name', key)
        args.append(a)
    wind.set_editor_property('inputs', args)
    time_node = node(unreal.MaterialExpressionTime, -360, 680)
    pos_node = node(unreal.MaterialExpressionWorldPosition, -360, 780)
    link(time_node, '', wind, 'T')
    link(pos_node, '', wind, 'P')
    link(vc, 'A', wind, 'W')
    MEL.connect_material_property(wind, '', unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)

    m.set_editor_property('two_sided', True)
    m.set_editor_property('used_with_static_lighting', False)
    MEL.recompile_material(m)
    EAL.save_loaded_asset(m)
    return m


def main():
    unreal.SystemLibrary.execute_console_command(None, 'Interchange.FeatureFlags.Import.FBX 0')
    manifest = json.loads((OUT / 'manifest.json').read_text())
    atlas = import_atlas()
    mat = build_material(atlas)
    report = {}
    for name in sorted(manifest):
        fbx = FBX_DIR / f'{name}.fbx'
        mesh = import_fbx(fbx, DEST_MESH, name, seed=SEED)
        mesh.set_material(0, mat)
        body = mesh.get_editor_property('body_setup')
        if body:
            flag = (
                unreal.CollisionTraceFlag.CTF_USE_SIMPLE_AND_COMPLEX
                if name in SOLID_PROPS
                else unreal.CollisionTraceFlag.CTF_USE_DEFAULT
            )
            body.set_editor_property('collision_trace_flag', flag)
        EAL.save_loaded_asset(mesh)
        report[name] = mesh.get_path_name()
        unreal.log(f'SWORDCAMP imported {name}')
    (OUT / 'import-report.json').write_text(json.dumps(report, indent=2) + '\n')
    unreal.log(f'SWORDCAMP IMPORT COMPLETE ({len(report)} meshes)')


if __name__ == '__main__':
    main()
