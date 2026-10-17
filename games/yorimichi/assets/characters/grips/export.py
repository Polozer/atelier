"""A playable character's body as glTF for the grip poser: its built FBX (the skeleton the game plays) and its textures.

    blender -b --python games/yorimichi/assets/characters/grips/export.py -- --character modori

Reads build/yorimichi/<character>/fbx/<Name>.fbx and export.json (written by characters/pipeline/export.py) and
writes build/yorimichi/grips/<character>/body.glb: the skinned meshes in their rest pose with their base-colour textures,
and the armature, bones named as in the game. glTF's frame is Y up, metres; the game's is Z up, centimetres, so a point
(x, y, z) in the game is (x, z, y) / 100 here (moments.py and the poser convert the same way).
"""
from pathlib import Path
import argparse
import json
import sys
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'world')); import yori  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline')); import definition  # noqa: E402


def main(args):
    character = definition.load(args.character)
    source = yori.OUT / character.output
    record = json.loads((source / 'export.json').read_text())
    name = character.name
    out = yori.OUT / 'grips' / args.character
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # The axes pipeline/export.py wrote with (forward -Y, up Z), so the skeleton keeps its frames.
    bpy.ops.import_scene.fbx(filepath=str(source / 'fbx' / f'{name}.fbx'), axis_forward='-Y', axis_up='Z', use_anim=False,
                             automatic_bone_orientation=False, ignore_leaf_bones=False)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    for obj in meshes:
        obj.data.name = obj.name   # the poser finds the body and the coat by these names
        for slot in obj.material_slots:
            # The FBX keeps export.json's material names; its own image links point at its build's paths
            material = slot.material
            entry = record['materials'].get(material.name) if material else None
            if not entry or not entry.get('texture'):
                continue
            material.use_nodes = True
            nodes, links = material.node_tree.nodes, material.node_tree.links
            shader = next(n for n in nodes if n.type == 'BSDF_PRINCIPLED')
            for reference in list(shader.inputs['Base Color'].links):
                links.remove(reference)
            image = nodes.new('ShaderNodeTexImage')
            image.image = bpy.data.images.load(str(source / entry['texture']))
            links.new(image.outputs['Color'], shader.inputs['Base Color'])
            material.use_backface_culling = not entry.get('two_sided')
    bpy.ops.object.select_all(action='DESELECT')
    for obj in [arm, *meshes]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = arm
    arm.data.pose_position = 'REST'
    bpy.ops.export_scene.gltf(filepath=str(out / 'body.glb'), export_format='GLB', use_selection=True, export_yup=True,
                              export_skins=True, export_animations=False, export_apply=False, export_image_format='JPEG',
                              export_def_bones=False)
    report = {'character': args.character, 'source': str((source / 'fbx' / f'{name}.fbx').relative_to(yori.OUT)),
              'meshes': {o.name: len(o.data.vertices) for o in meshes}, 'bones': len(arm.data.bones)}
    (out / 'body.json').write_text(json.dumps(report, indent=2) + '\n')
    print('GRIP BODY EXPORT COMPLETE', json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--character', required=True)
    main(parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []))
