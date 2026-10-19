"""The racing TVs' picture material, /Game/Racing/M_RacingTv (ARacingBroadcast, docs/RACING.md "TVs").

Unlit and opaque: the screen glows with its picture whatever the room's light. The picture is the broadcast's render
target, `Picture`: the scene capture's final (display-encoded) colours and the canvas graphics, both stored encoded in
an sRGB target, so the sample comes back display-encoded once more and is decoded here (2.2) to the linear colour the
renderer expects. `Brightness` scales it (1: the picture as filmed).
"""
import unreal

E = unreal.EditorAssetLibrary
M = unreal.MaterialEditingLibrary
FOLDER, NAME = '/Game/Racing', 'M_RacingTv'
PATH = f'{FOLDER}/{NAME}'

E.make_directory(FOLDER)
mat = E.load_asset(PATH) if E.does_asset_exist(PATH) else unreal.AssetToolsHelpers.get_asset_tools().create_asset(
    NAME, FOLDER, unreal.Material, unreal.MaterialFactoryNew())
M.delete_all_material_expressions(mat)
mat.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_UNLIT)
mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_OPAQUE)
mat.set_editor_property('two_sided', False)


def node(cls, x, y, **properties):
    e = M.create_material_expression(mat, cls, x, y)
    for key, value in properties.items():
        e.set_editor_property(key, value)
    return e


def link(a, out, b, into):
    assert M.connect_material_expressions(a, out, b, into), (a, out, b, into)


picture = node(unreal.MaterialExpressionTextureSampleParameter2D, -700, 0, parameter_name='Picture',
               texture=unreal.load_asset('/Engine/EngineResources/Black'))
brightness = node(unreal.MaterialExpressionScalarParameter, -700, 300, parameter_name='Brightness', default_value=1.)
decode = node(unreal.MaterialExpressionCustom, -350, 0, code='return saturate(pow(max(C, 0.), 2.2) * 1.04 - .004) * B;',
              output_type=unreal.CustomMaterialOutputType.CMOT_FLOAT3)
inputs = []
for name in ('C', 'B'):
    arg = unreal.CustomInput()
    arg.set_editor_property('input_name', name)
    inputs.append(arg)
decode.set_editor_property('inputs', inputs)
link(picture, 'RGB', decode, 'C')
link(brightness, '', decode, 'B')
# The room's exposure undone: the screen shows its picture at the same brightness in a dim taproom as in the bright
# Salon, never washed out by the eye adaptation of a dark room.
exposure = node(unreal.MaterialExpressionEyeAdaptationInverse, -100, 0)
assert any(M.connect_material_expressions(decode, '', exposure, name) for name in ('LightValueInput', 'LightValue', 'Light Value')), \
    'EyeAdaptationInverse input'
assert M.connect_material_property(exposure, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR)

M.recompile_material(mat)
assert E.save_loaded_asset(mat, False), PATH
unreal.log('RACING TV MATERIAL COMPLETE')
