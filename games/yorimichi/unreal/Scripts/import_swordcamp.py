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


def build_ronin_body_material(atlas_tex):
    """Skeletal-mesh material allowing per-role tunic color variation (Scout indigo, Guard jade, Captain crimson)."""
    path = f'{DEST_MAT}/M_RoninBody'
    m = EAL.load_asset(path) if EAL.does_asset_exist(path) else None
    if not m:
        m = AT.create_asset('M_RoninBody', DEST_MAT, unreal.Material, unreal.MaterialFactoryNew())
    MEL.delete_all_material_expressions(m)
    m.set_editor_property('blend_mode', unreal.BlendMode.BLEND_OPAQUE)
    m.set_editor_property('two_sided', False)
    m.set_editor_property('used_with_skeletal_mesh', True)
    m.set_editor_property('used_with_static_lighting', False)

    tex = MEL.create_material_expression(m, unreal.MaterialExpressionTextureSampleParameter2D, -640, 0)
    tex.set_editor_property('parameter_name', 'BaseTex')
    char_tex_path = '/Game/SwordTrainer/Textures/T_tripo_mat_ee5a1a4b'
    default_tex = EAL.load_asset(char_tex_path) if EAL.does_asset_exist(char_tex_path) else None
    if not default_tex:
        unreal.log_warning(f'M_RoninBody: {char_tex_path} not yet imported; using atlas_tex placeholder until runtime override')
        default_tex = atlas_tex
    tex.set_editor_property('texture', default_tex)

    tint = MEL.create_material_expression(m, unreal.MaterialExpressionVectorParameter, -640, 260)
    tint.set_editor_property('parameter_name', 'CoatTint')
    tint.set_editor_property('default_value', unreal.LinearColor(0.16, 0.30, 0.62, 1.0))

    recol = MEL.create_material_expression(m, unreal.MaterialExpressionCustom, -240, 80)
    recol.set_editor_property(
        'code',
        'float coat=saturate((C.r-C.g*2.15-0.02)*18.0)*saturate((0.18-C.g)*16.0); '
        'float luma=dot(C,float3(0.299,0.587,0.114)); '
        'float3 dyed=saturate((luma/0.11)*pow(saturate(T),1.35)); '
        'return lerp(C,dyed,coat);',
    )
    recol.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    inputs = []
    for key in ('C', 'T'):
        arg = unreal.CustomInput()
        arg.set_editor_property('input_name', key)
        inputs.append(arg)
    recol.set_editor_property('inputs', inputs)
    assert MEL.connect_material_expressions(tex, 'RGB', recol, 'C')
    assert MEL.connect_material_expressions(tint, '', recol, 'T')
    assert MEL.connect_material_property(recol, '', unreal.MaterialProperty.MP_BASE_COLOR)

    fill = MEL.create_material_expression(m, unreal.MaterialExpressionMultiply, 80, 120)
    fill.set_editor_property('const_b', 0.30)
    assert MEL.connect_material_expressions(recol, '', fill, 'A')
    assert MEL.connect_material_property(fill, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)

    for val, prop, y in [
        (0.7, unreal.MaterialProperty.MP_ROUGHNESS, 320),
        (0.0, unreal.MaterialProperty.MP_METALLIC, 400),
        (0.3, unreal.MaterialProperty.MP_SPECULAR, 480),
    ]:
        c = MEL.create_material_expression(m, unreal.MaterialExpressionConstant, 80, y)
        c.set_editor_property('r', val)
        assert MEL.connect_material_property(c, '', prop)

    MEL.recompile_material(m)
    EAL.save_loaded_asset(m)
    return m


def main():
    unreal.SystemLibrary.execute_console_command(None, 'Interchange.FeatureFlags.Import.FBX 0')
    manifest = json.loads((OUT / 'manifest.json').read_text())
    atlas = import_atlas()
    mat = build_material(atlas)
    body_mat = build_ronin_body_material(atlas)
    report = {'M_RoninBody': body_mat.get_path_name()}
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
    unreal.log(f'SWORDCAMP IMPORT COMPLETE ({len(report)} assets)')


if __name__ == '__main__':
    main()
