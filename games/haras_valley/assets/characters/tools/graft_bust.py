"""Put a Tripo bust (head, hair, neck) on a Tripo body in place of its head.

/Applications/Blender.app/Contents/MacOS/Blender -b --python games/haras_valley/assets/characters/tools/graft_bust.py -- \
    --body model-r03/raw/output_model_url.fbx --bust bust-r01/raw/output_model_url.fbx --output graft-r01

The body came from the full-figure turnaround, where the head is about 150 px tall: its face did not resemble the
drawing however it was reworked. The bust came from the face sheet's front, profiles and back, the head about 300 px
tall, and matches the drawing's proportions (eyes to chin 1.45 pupil spacings, drawn 1.41; the body's head 1.27).

1. The body's head pieces go: face with neck, hair, eyeballs, brow strips, cornea discs (eyes.head_parts).
2. The bust's shirt piece goes, and its neck is cut at NECK_CUT (bust units), so the open end sits well inside the
   body's shirt; once placed, any of its skin under the collar that lies outside the body's shirt is moved back
   inside it.
3. The bust is scaled by SCALE (its eye spacing and its hair-top-to-chin height both measure 0.25 of the body's
   head) and moved so its chin bottom lands on the body's (BODY_CHIN) and its neck's centre on the old neck's.
4. Skin: the texels of the bust's face and the body's arms and hands are brought to the drawing's skin colour (the
   face sheet's cheek), per channel, keeping their shading.
5. One object, two materials (the body's, the bust's) and one UV layer, saved as a .blend with its textures packed
   and a GLB.
"""
import argparse
import json
from pathlib import Path
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))   # Blender's --python does not add the script's folder
import eyes  # noqa: E402

SCALE = 0.248
BUST_CHIN = -0.260            # the bust's chin bottom (z, bust units), from its front profile
BODY_CHIN = 0.3103            # the body's chin bottom
NECK_CUT = -0.44              # the bust's neck is cut here (z, bust units), well inside the body's shirt
COLLAR_TOP = 0.300            # body z: below it, the bust's skin is kept inside the body's shirt
NECK_CENTRE_BODY = (-0.020, -0.0031)   # the old neck's centre (x, y) just under the chin
NECK_PROBE = -0.289           # bust z where its neck centre is measured, just under the chin
SKIN_TARGET = np.array([.99, .66, .50], np.float32)   # the face sheet's cheek (sRGB), as Blender stores it


def pieces(mesh):
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    piece = [-1] * len(bm.faces)
    count = 0
    for face in bm.faces:
        if piece[face.index] >= 0:
            continue
        piece[face.index] = count
        stack = [face]
        while stack:
            current = stack.pop()
            for edge in current.edges:
                for other in edge.link_faces:
                    if piece[other.index] < 0:
                        piece[other.index] = count
                        stack.append(other)
        count += 1
    bm.free()
    return np.array(piece)


def delete_faces(obj, indices):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in sorted(indices)], context='FACES')
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def import_fbx(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=str(path))
    obj = [o for o in bpy.data.objects if o not in before and o.type == 'MESH'][0]
    for other in [o for o in bpy.data.objects if o not in before and o is not obj]:
        bpy.data.objects.remove(other)
    # Bake the import transform into the mesh, so world and local coordinates agree.
    obj.data.transform(obj.matrix_world)
    obj.matrix_world = Matrix.Identity(4)
    return obj


def base_image(obj):
    material = obj.material_slots[0].material
    for link in material.node_tree.links:
        if link.to_socket.name == 'Base Color' and link.from_node.type == 'TEX_IMAGE':
            return material, link.from_node.image
    raise RuntimeError('no base colour image')


def recolour_skin(obj, polygons, label, output):
    """Bring the skin texels of `polygons` to SKIN_TARGET, per channel; returns the gain used."""
    from cleanup_face_hair import texel_coverage
    material, image = base_image(obj)
    width, height = image.size
    data = np.array(image.pixels[:], dtype=np.float32).reshape(height, width, 4)
    mask = np.zeros((height, width), bool)
    uv = obj.data.uv_layers.active.data
    for index in polygons:
        coverage = texel_coverage(obj.data.polygons[index], uv, width, height)
        if coverage is not None:
            mask[coverage[0], coverage[1]] = True
    rgb = data[mask][:, :3]
    weight = eyes.skinness(rgb)
    skin = rgb[weight > .9]
    gain = (SKIN_TARGET / np.maximum(np.median(skin, axis=0), 1e-3)).astype(np.float32)
    adjusted = np.clip(rgb * gain, 0, 1)
    data[mask, :3] = rgb * (1 - weight[:, None]) + adjusted * weight[:, None]
    fresh = bpy.data.images.new(label, width, height, alpha=False)
    fresh.colorspace_settings.name = image.colorspace_settings.name
    fresh.pixels.foreach_set(data.ravel())
    fresh.filepath_raw = str(output / (label + '.png'))
    fresh.file_format = 'PNG'
    fresh.save()
    for node in material.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image == image:
            node.image = fresh
    fresh.pack()
    return [round(float(g), 3) for g in gain]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--body', type=Path, required=True)
    parser.add_argument('--bust', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # 1. The body without its head.
    body = import_fbx(args.body.resolve())
    identity = Matrix.Identity(4)
    parts = eyes.head_parts(body.data, identity)
    head = parts['face'] | parts['hair'] | parts['eyeballs'] | parts['brows'] | parts['discs']
    delete_faces(body, head)

    # 2. The bust without its shirt, its neck cut.
    bust = import_fbx(args.bust.resolve())
    piece = pieces(bust.data)
    centres = np.array([list(p.center) for p in bust.data.polygons])
    sizes = np.bincount(piece)
    lowest = piece[np.argmin(centres[:, 2])]                 # the shirt holds the lowest polygon
    hair = piece[np.argmax(centres[:, 2])]
    face = max((i for i in range(len(sizes)) if i not in (lowest, hair)), key=lambda i: sizes[i])
    drop = set(np.nonzero(piece == lowest)[0].tolist())
    drop |= set(np.nonzero((piece == face) & (centres[:, 2] < NECK_CUT))[0].tolist())
    delete_faces(bust, drop)
    piece = pieces(bust.data)
    centres = np.array([list(p.center) for p in bust.data.polygons])
    sizes = np.bincount(piece)
    hair = piece[np.argmax(centres[:, 2])]
    face = max((i for i in range(len(sizes)) if i != hair), key=lambda i: sizes[i])
    face_polygons = np.nonzero(piece == face)[0]

    # 3. Scale and place: the chin on the body's chin, the neck's centre on the old neck's.
    vertices = np.array([list(v.co) for v in bust.data.vertices])
    face_vertices = vertices[sorted({v for i in face_polygons for v in bust.data.polygons[i].vertices})]
    probe = face_vertices[np.abs(face_vertices[:, 2] - NECK_PROBE) < .01]
    neck_x = (probe[:, 0].min() + probe[:, 0].max()) / 2
    neck_y = (probe[:, 1].min() + probe[:, 1].max()) / 2
    offset = Vector((NECK_CENTRE_BODY[0] - neck_x * SCALE, NECK_CENTRE_BODY[1] - neck_y * SCALE,
                     BODY_CHIN - BUST_CHIN * SCALE))
    bust.data.transform(Matrix.Translation(offset) @ Matrix.Scale(SCALE, 4))
    bust.data.update()

    # The neck's skin under the collar: anything outside the body's shirt goes back inside it, 1.5 mm under the
    # cloth, along a horizontal line from the neck's axis (the shoulders under the bust's own shirt were wider).
    from mathutils.bvhtree import BVHTree
    bm = bmesh.new()
    bm.from_mesh(body.data)
    tree = BVHTree.FromBMesh(bm)
    axis = Vector(NECK_CENTRE_BODY)
    face_vertex_ids = sorted({v for i in face_polygons for v in bust.data.polygons[i].vertices})
    pushed = 0
    for index in face_vertex_ids:
        p = bust.data.vertices[index].co
        if p.z >= COLLAR_TOP:
            continue
        origin = Vector((axis.x, axis.y, p.z))
        out = Vector((p.x - origin.x, p.y - origin.y, 0))
        distance = out.length
        if distance < 1e-6:
            continue
        direction = out / distance
        hit = tree.ray_cast(origin, direction, distance)
        if hit[0] is not None:
            bust.data.vertices[index].co = hit[0] - direction * .0015
            pushed += 1
    bm.free()
    bust.data.update()

    # 4. Skin colour: the bust's face, and the body's skin (arms, hands, the rest of its neck).
    bust_gain = recolour_skin(bust, face_polygons.tolist(), 'BustBaseColor', output)
    body_gain = recolour_skin(body, list(range(len(body.data.polygons))), 'BodyBaseColor', output)

    # 5. One object. The UV layers must share a name, or the join keeps only the body's and the bust loses its UVs.
    for obj in (body, bust):
        obj.data.uv_layers.active.name = 'UVMap'
    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True)
    bust.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    body.name = 'boy'
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(output / 'boy-graft-r01.blend'))
    bpy.ops.export_scene.gltf(filepath=str(output / 'boy-graft-r01.glb'), export_format='GLB', use_selection=True,
                              export_animations=False)
    record = {'body': args.body.name, 'bust': args.bust.name, 'script': Path(__file__).name,
              'blender_version': bpy.app.version_string, 'scale': SCALE, 'offset': [round(c, 4) for c in offset],
              'bust_neck_centre': [round(float(neck_x), 4), round(float(neck_y), 4)], 'neck_cut': NECK_CUT, 'neck_vertices_pushed_inside_shirt': pushed,
              'body_head_polygons_removed': len(head), 'bust_polygons_removed': len(drop),
              'skin_target': SKIN_TARGET.tolist(), 'bust_skin_gain': bust_gain, 'body_skin_gain': body_gain,
              'polygons': len(body.data.polygons)}
    (output / 'graft.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=1), flush=True)


if __name__ == '__main__':
    main()
