"""Cleanup r01 of the boy: his face and hair brought back to the reference sheets.

/Applications/Blender.app/Contents/MacOS/Blender -b --python games/haras_valley/assets/characters/tools/cleanup_face_hair.py -- \
    --input model-r03/raw/output_model_url.fbx --references references --output cleanup-r01

Tripo's texture made the face older and tanner than the drawings (darker skin, no blush, small murky eyes, heavy
brows) and its hair shorter and greyer, and its eyes and mouth droop at the outer ends, which reads as sad. Seven fixes, textures and vertices only, no retopology:

1. Face projection. The front portrait (`--face`, painted by tools/face_portrait.py; without it the face sheet's
   top-left cell) is projected onto the face with the affine map that puts its irises and mouth line (found in the
   image) on the model's own (MODEL_EYE_* and MODEL_MOUTH_Z, read off model-r03's front render). Face texels facing
   forward take the drawing's colour, faded out as the surface turns away and above the chin's drawn outline; the
   normal map goes flat under it. The hair cap, the eyeballs and the shirt are excluded.
2. Skin match. The rest of the skin (neck, ears, arms, hands) is scaled per channel so its median meets the projected
   cheek's.
3. Hair colour. The hair cap's texels are scaled per channel to the sheet's hair median: the warm dark brown
   instead of grey. The cap, the face and the eyeballs are separate pieces of Tripo's mesh (eyes.head_parts).
4. Hair length. Hair vertices move away from the skull centre by HAIR_STRETCH of their height above the skull, and
   the fringe's also drop by FRINGE_DROOP of it, so the spikes grow and the fringe comes down toward the brows as
   drawn; the scalp does not move.
5. Eye shape. Tripo's eyes slope down toward the outside and sit low between their corners, which reads as sad.
   Each eye region turns by EYE_TILT_DEGREES, outer corner up (eyes.tilt), then the middle of each eye (lower lid,
   eyeball, upper lid and brow) rises by EYE_LIFT of its width with the corners pinned (eyes.lift), so the upper lid
   arches 0.32 eye widths above the corners as in the drawing; eyes.py draws the lower lid 0.23 below them, so the
   corners sit 42% of the way up the opening. Both fade out before the nose, temple, cheek and forehead.
6. Eyes and brows. The projected drawing's eyes do not fit Tripo's sculpted sockets, so eyes.py paints clean cel
   eyes onto the eyeballs inside each reshaped socket's rim, colours the brow strips, clears Tripo's eye paint, gloss
   and normal detail around them, and the cornea discs are removed (see eyes.py).
7. Mouth corners. The face around the mouth corners rises by up to MOUTH_RISE, nothing at the middle, fading into the
   cheeks, so the lower lip and the painted line no longer droop at the ends (mouth.py).

The output is a .blend with the four texture maps packed, a GLB beside it and cleanup.json with the measurements.
"""
import argparse
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))   # Blender's --python does not add the script's folder
import eyes  # noqa: E402
import mouth  # noqa: E402

SHEET_CELL = (0, 0, 512, 512)          # the front view in the face sheet
HEAD_Z = 0.27                          # above this: head and neck
FACE_Z, FACE_HALF_WIDTH = 0.30, 0.08   # the projection stays above the collar and within the head
MODEL_EYE_MID_Y, MODEL_EYE_Z, MODEL_EYE_SPACING, MODEL_MOUTH_Z = -0.0058, 0.378, 0.0524, 0.341
FACE_FADE = (0.35, 0.75)               # normal x over which the projection fades in (the sides keep Tripo's paint)
CHIN_FADE = (0.324, 0.338)             # z over which it fades out above the chin's drawn outline
HAIR_STRETCH = 0.40
FRINGE_DROOP = 0.35
EYE_TILT_DEGREES = 8.0                 # outer corners up: from Tripo's 12 degree droop to the drawing's 4
MOUTH_Z, MOUTH_HALF_WIDTH = 0.338, 0.016    # the mouth's middle and half width (front render of model-r03)
MOUTH_RISE = 0.0025                    # the corners up by 2.5 mm: from a 1.6 mm droop to slightly up
EYE_LIFT = 0.20                        # the eye's middle up by this much of its width: the drawing's upper-lid arch                    # strands in front of the skull also drop by this much of their height
HAIR_LUMINANCE = 0.42                  # below this a warm texel is hair (or brow, or pupil)


def iris_centres(image, box):
    """The two irises of a face image, by their hazel colour; (left, right) in image pixels, y down."""
    x0, y0, x1, y1 = box
    sub = image[y0:y1, x0:x1, :3]
    r, g, b = sub[..., 0], sub[..., 1], sub[..., 2]
    mask = (r > 0.5) & (g > 0.38) & (b < 0.32) & (r - b > 0.3) & (g - b > 0.15)
    ys, xs = np.nonzero(mask)
    if len(xs) < 20:
        raise RuntimeError(f'only {len(xs)} iris pixels found in {box}')
    xs, ys = xs + x0, ys + y0
    left = xs < np.median(xs)
    return (xs[left].mean(), ys[left].mean()), (xs[~left].mean(), ys[~left].mean()), int(mask.sum())


def mouth_row(image, left, right):
    """The mouth line: the darkest row between the irises' columns, 0.55 to 1.1 eye spacings below them."""
    spacing = math.dist(left, right)
    x0, x1 = int(min(left[0], right[0]) + spacing * .15), int(max(left[0], right[0]) - spacing * .15)
    y0, y1 = int(left[1] + spacing * .55), int(left[1] + spacing * 1.1)     # below the nose, above the chin line
    strip = image[y0:y1, x0:x1, :3] @ np.array([.299, .587, .114], np.float32)
    return y0 + int(np.argmin(strip.mean(axis=1)))


def load_image(path):
    """An image file as a float array indexed [row from top, column, channel]."""
    image = bpy.data.images.load(str(path))
    width, height = image.size
    data = np.array(image.pixels[:], dtype=np.float32).reshape(height, width, 4)[::-1]
    bpy.data.images.remove(image)
    return data


def sample(image, cols, rows):
    """Bilinear samples; (value, inside) with inside false where the lookup leaves the image."""
    height, width = image.shape[:2]
    inside = (cols >= 0) & (cols <= width - 1) & (rows >= 0) & (rows <= height - 1)
    cols, rows = np.clip(cols, 0, width - 1.001), np.clip(rows, 0, height - 1.001)
    c0, r0 = np.floor(cols).astype(int), np.floor(rows).astype(int)
    fc, fr = (cols - c0)[:, None], (rows - r0)[:, None]
    value = (image[r0, c0] * (1 - fc) * (1 - fr) + image[r0, c0 + 1] * fc * (1 - fr)
             + image[r0 + 1, c0] * (1 - fc) * fr + image[r0 + 1, c0 + 1] * fc * fr)
    return value, inside


def image_for(material, socket):
    """The image feeding a socket: 'Base Color' on the shader, 'Color' on the Normal Map node."""
    for link in material.node_tree.links:
        if link.to_socket.name == socket and link.from_node.type == 'TEX_IMAGE':
            return link.from_node.image
    raise RuntimeError('no image feeds ' + socket)


def texel_coverage(polygon, uv, width, height, grow=1.5):
    """Texels of a polygon's UV triangles with their barycentric weights: (rows, cols, corner indices, weights)."""
    loops = list(polygon.loop_indices)
    corners = [uv[index].uv for index in loops]
    out_rows, out_cols, out_corners, out_weights = [], [], [], []
    for i in range(1, len(corners) - 1):
        tri = (0, i, i + 1)
        points = np.array([[corners[t].x * width, corners[t].y * height] for t in tri])
        x0, y0 = np.floor(points.min(axis=0)).astype(int) - 2
        x1, y1 = np.ceil(points.max(axis=0)).astype(int) + 2
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, width - 1), min(y1, height - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
        (ax, ay), (bx, by), (cx, cy) = points
        d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(d) < 1e-9:
            continue
        l1 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / d
        l2 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / d
        l3 = 1 - l1 - l2
        tolerance = grow / max(abs(d) ** .5, 1)
        inside = (l1 >= -tolerance) & (l2 >= -tolerance) & (l3 >= -tolerance)
        if not inside.any():
            continue
        weights = np.stack([l1[inside], l2[inside], l3[inside]], axis=1)
        weights = np.clip(weights, 0, None)
        weights /= weights.sum(axis=1, keepdims=True)
        out_rows.append(ys[inside].astype(int))
        out_cols.append(xs[inside].astype(int))
        out_corners.append(np.array([tri] * int(inside.sum())))
        out_weights.append(weights)
    if not out_rows:
        return None
    return (np.concatenate(out_rows), np.concatenate(out_cols), np.concatenate(out_corners), np.concatenate(out_weights))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--references', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--face', type=Path, default=None,
                        help='a large clean front portrait to project instead of the sheet\'s front cell (tools/face_portrait.py)')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(args.input.resolve()))
    obj = [o for o in bpy.context.scene.objects if o.type == 'MESH'][0]
    mesh, uv = obj.data, obj.data.uv_layers.active.data
    material = obj.material_slots[0].material
    world = obj.matrix_world
    rotation = world.to_3x3()

    if args.face:
        sheet = load_image(args.face)
        cell = (0, 0, sheet.shape[1], sheet.shape[0])
    else:
        sheet = load_image(args.references / 'face-six-views.png')
        cell = SHEET_CELL
    sheet_left, sheet_right, sheet_pixels = iris_centres(sheet, cell)
    sheet_mid = ((sheet_left[0] + sheet_right[0]) / 2, (sheet_left[1] + sheet_right[1]) / 2)
    sheet_spacing = math.dist(sheet_left, sheet_right)
    sheet_mouth_row = mouth_row(sheet, sheet_left, sheet_right)

    base = image_for(material, 'Base Color')
    width, height = base.size
    colour = np.array(base.pixels[:], dtype=np.float32).reshape(height, width, 4)
    original = colour.copy()
    luminance = original[..., :3] @ np.array([.299, .587, .114], np.float32)
    warm = (original[..., 0] > original[..., 1]) & (original[..., 1] > original[..., 2])
    hair_texels = warm & (luminance < HAIR_LUMINANCE)
    skin_texels = warm & (luminance > 0.45) & (original[..., 0] - original[..., 2] > 0.28) & (original[..., 1] - original[..., 2] > 0.08)

    positions = np.array([list(world @ v.co) for v in mesh.vertices], np.float32)
    vertex_normals = np.array([list((rotation @ v.normal).normalized()) for v in mesh.vertices], np.float32)
    head = positions[:, 2] > HEAD_Z
    # Hair polygons: dark texels standing off the skull. The skull is the sphere through the bright head vertices.
    polygon_texel = {}
    for polygon in mesh.polygons:
        if positions[polygon.vertices[0], 2] < HEAD_Z - 0.05:
            continue
        corners = [uv[index].uv for index in polygon.loop_indices]
        u, v = sum(c.x for c in corners) / len(corners), sum(c.y for c in corners) / len(corners)
        polygon_texel[polygon.index] = (int(v * height) % height, int(u * width) % width)
    skin_points = [list(world @ polygon.center) for polygon in mesh.polygons
                   if polygon.index in polygon_texel and skin_texels[polygon_texel[polygon.index]]
                   and (world @ polygon.center).z > 0.30]
    skin_points = np.array(skin_points)
    design = np.hstack([2 * skin_points, np.ones((len(skin_points), 1))])
    solution = np.linalg.lstsq(design, (skin_points ** 2).sum(axis=1), rcond=None)[0]
    skull_centre = Vector(solution[:3])
    skull_radius = math.sqrt(solution[3] + float(skull_centre.dot(skull_centre)))
    # Tripo builds the head from separate pieces: the hair cap, the face, and one eyeball behind each eye hole.
    parts = eyes.head_parts(mesh, world)
    hair_polygons = [mesh.polygons[index] for index in sorted(parts['hair'])]
    hair_vertices = sorted({index for polygon in hair_polygons for index in polygon.vertices})
    hair_polygon_set = {polygon.index for polygon in hair_polygons}

    # The mapping: the sheet's irises and mouth onto the model's (model anchors read off the orthographic front
    # render of model-r03: irises 41 px apart at row 154, mouth at row 183, 782.6 px per metre, centre at 450).
    px_per_m_y = sheet_spacing / MODEL_EYE_SPACING
    px_per_m_z = (sheet_mouth_row - sheet_mid[1]) / (MODEL_EYE_Z - MODEL_MOUTH_Z)

    def sheet_coords(points):
        """World points (n, 3) to face-sheet pixels (cols, rows): his left (+Y) is on the viewer's right."""
        return (sheet_mid[0] + (points[:, 1] - MODEL_EYE_MID_Y) * px_per_m_y,
                sheet_mid[1] - (points[:, 2] - MODEL_EYE_Z) * px_per_m_z)

    # 1. Face projection.
    projected = np.zeros((height, width), bool)
    weight_map = np.zeros((height, width), np.float32)
    cheek_samples = []
    for polygon in mesh.polygons:
        if polygon.index in hair_polygon_set or polygon.index in parts['eyeballs'] or polygon.index not in polygon_texel:
            continue
        centre = world @ polygon.center
        if centre.z < FACE_Z or abs(centre.y) > FACE_HALF_WIDTH:
            continue
        texel = original[polygon_texel[polygon.index]]
        if texel[1] > texel[0] + 0.02:            # the shirt
            continue
        coverage = texel_coverage(polygon, uv, width, height)
        if coverage is None:
            continue
        rows, cols, corners, weights = coverage
        loop_vertices = np.array([mesh.loops[li].vertex_index for li in polygon.loop_indices])
        verts = loop_vertices[corners]                      # (n, 3) vertex indices per texel
        points = (positions[verts] * weights[:, :, None]).sum(axis=1)
        normals = (vertex_normals[verts] * weights[:, :, None]).sum(axis=1)
        facing = np.clip((normals[:, 0] - FACE_FADE[0]) / (FACE_FADE[1] - FACE_FADE[0]), 0, 1)
        facing *= np.clip((points[:, 2] - CHIN_FADE[0]) / (CHIN_FADE[1] - CHIN_FADE[0]), 0, 1)   # not the chin's ink line
        if facing.max() <= 0:
            continue
        sheet_cols, sheet_rows = sheet_coords(points)
        value, inside = sample(sheet, sheet_cols, sheet_rows)
        inside &= (sheet_cols >= cell[0]) & (sheet_cols < cell[2]) & (sheet_rows >= cell[1]) & (sheet_rows < cell[3])
        alpha = (facing * inside)[:, None]
        colour[rows, cols, :3] = colour[rows, cols, :3] * (1 - alpha) + value[:, :3] * alpha
        strong = alpha[:, 0] > 0.9
        projected[rows[strong], cols[strong]] = True
        weight_map[rows, cols] = np.maximum(weight_map[rows, cols], alpha[:, 0])
        if strong.any() and skin_texels[rows[strong], cols[strong]].any():
            keep = strong & skin_texels[rows, cols]
            cheek_samples.append(np.stack([original[rows[keep], cols[keep], :3], value[keep, :3]], axis=1))
    cheek = np.concatenate(cheek_samples)
    skin_before, skin_after = np.median(cheek[:, 0], axis=0), np.median(cheek[:, 1], axis=0)

    # 2. Skin match on everything skin-coloured that the projection did not reach.
    skin_gain = np.clip(skin_after / np.maximum(skin_before, 1e-3), 0.6, 1.6).astype(np.float32)
    rest = skin_texels & (weight_map < 0.05)
    colour[rest, :3] = np.clip(original[rest, :3] * skin_gain, 0, 1)
    # Within the fade, blend the gain so the cheeks meet the ears without a step.
    fade = skin_texels & (weight_map >= 0.05) & (weight_map < 0.9)
    gained = np.clip(original[fade, :3] * skin_gain, 0, 1)
    w = weight_map[fade][:, None]
    colour[fade, :3] = colour[fade, :3] * w + gained * (1 - w)

    # 3. Hair colour toward the sheet's.
    face_pixels = sheet[cell[1]:cell[3], cell[0]:cell[2], :3]
    face_luminance = face_pixels @ np.array([.299, .587, .114], np.float32)
    sheet_hair = face_pixels[(face_luminance < 0.4) & (face_pixels[..., 0] > face_pixels[..., 2]) & (face_pixels[..., 0] > 0.12)]
    hair_target = np.median(sheet_hair, axis=0)
    hair_mask = np.zeros((height, width), bool)
    for polygon in hair_polygons:
        coverage = texel_coverage(polygon, uv, width, height)
        if coverage is not None:
            hair_mask[coverage[0], coverage[1]] = True
    # The cap is all hair: every texel becomes the sheet's brown, keeping only Tripo's light and shade (pale specks
    # and skin-coloured patches included, so none survive).
    hair_luminance = luminance[hair_mask]
    hair_before = np.median(original[hair_mask, :3], axis=0)
    shade = np.clip(hair_luminance / max(float(np.median(hair_luminance)), 1e-3), .6, 1.35)[:, None]
    colour[hair_mask, :3] = np.clip(hair_target[None] * shade, 0, 1)

    # The normal map under the projected face goes flat, so Tripo's own smaller eyes and brows stop showing through.
    normal_image = image_for(material, 'Color')
    normal_data = np.array(normal_image.pixels[:], dtype=np.float32).reshape(height, width, 4)
    flat = weight_map[..., None]
    normal_data[..., :3] = normal_data[..., :3] * (1 - flat) + np.array([.5, .5, 1], np.float32) * flat

    def replace(image, name, data):
        fresh = bpy.data.images.new(name, width, height, alpha=False)
        fresh.colorspace_settings.name = image.colorspace_settings.name
        fresh.pixels.foreach_set(data.ravel())
        fresh.filepath_raw = str(output / (name + '.png'))
        fresh.file_format = 'PNG'
        fresh.save()
        for node in material.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image == image:
                node.image = fresh
        fresh.pack()

    # 5. Eye shape, before the eyes are painted on it: the outer corners up to the drawing's slant, then the middle of
    # each eye lifted so the corners sit where the drawing's do (Tripo's droop and low lids read as sad).
    tilt_record = eyes.tilt(mesh, world, parts, EYE_TILT_DEGREES)
    lift_record = eyes.lift(mesh, world, parts, EYE_LIFT)

    # 6. Eyes and brows: clean cel eyes fitted to the reshaped sockets (eyes.py).
    roughness_image, metallic_image = image_for(material, 'Roughness'), image_for(material, 'Metallic')
    roughness_data = np.array(roughness_image.pixels[:], dtype=np.float32).reshape(height, width, 4)
    metallic_data = np.array(metallic_image.pixels[:], dtype=np.float32).reshape(height, width, 4)
    eye_record = eyes.paint(mesh, world, uv, colour, roughness_data, metallic_data, normal_data, texel_coverage, parts)

    replace(base, 'BaseColor', colour)
    replace(normal_image, 'Normal', normal_data)
    replace(roughness_image, 'Roughness', roughness_data)
    replace(metallic_image, 'Metallic', metallic_data)

    # 4. Hair length: strands grow away from the skull centre by HAIR_STRETCH of their height above it.
    inverse = world.inverted()
    largest = 0.0
    for index in hair_vertices:
        point = world @ mesh.vertices[index].co
        offset = point - skull_centre
        above = offset.length - skull_radius
        if above <= 0:
            continue
        move = offset.normalized() * above * HAIR_STRETCH
        if offset.x > 0.3 * offset.length:          # the fringe: toward the brows, as drawn
            move += Vector((0, 0, -above * FRINGE_DROOP))
        largest = max(largest, move.length)
        mesh.vertices[index].co = inverse @ (point + move)
    mesh.update()

    # 7. Mouth corners up: Tripo's lower lip and the projected line both droop at the ends (mouth.py).
    mouth_record = mouth.corners(mesh, world, parts['face'], MODEL_EYE_MID_Y, MOUTH_Z, MOUTH_HALF_WIDTH, MOUTH_RISE)

    # Tripo's cornea discs (tiny pieces floating on each eyeball) shade differently from the painted eye: removed.
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    discs = [bm.faces[index] for index in sorted(parts['discs'])]
    bmesh.ops.delete(bm, geom=discs, context='FACES')
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()

    bpy.ops.file.pack_all()
    blend = output / 'boy-cleanup-r01.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(output / 'boy-cleanup-r01.glb'), export_format='GLB', use_selection=True,
                              export_animations=False)
    record = {
        'source': args.input.name, 'face': args.face.name if args.face else 'face-six-views.png (front cell)', 'script': Path(__file__).name, 'blender_version': bpy.app.version_string,
        'mapping': {'sheet_irises_px': [list(sheet_left), list(sheet_right), sheet_pixels], 'sheet_mouth_row': sheet_mouth_row,
                    'model_eyes': [MODEL_EYE_MID_Y, MODEL_EYE_Z, MODEL_EYE_SPACING], 'model_mouth_z': MODEL_MOUTH_Z,
                    'sheet_px_per_m': [round(px_per_m_y, 1), round(px_per_m_z, 1)]},
        'skull_sphere': {'centre': [round(c, 4) for c in skull_centre], 'radius': round(skull_radius, 4)},
        'face_texels_projected': int(projected.sum()),
        'skin_median_before': [round(float(c), 3) for c in skin_before], 'skin_median_after': [round(float(c), 3) for c in skin_after],
        'skin_gain': [round(float(c), 3) for c in skin_gain], 'skin_texels_matched': int(rest.sum()),
        'hair_median_before': [round(float(c), 3) for c in hair_before], 'hair_target': [round(float(c), 3) for c in hair_target],
        'hair_texels_recoloured': int(hair_mask.sum()), 'hair_polygons': len(hair_polygons),
        'eyes': eye_record, 'eye_tilt': tilt_record, 'eye_lift': lift_record, 'mouth_corners': mouth_record, 'cornea_disc_polygons_removed': len(parts['discs']), 'hair_vertices_moved': len(hair_vertices), 'largest_hair_move': round(largest, 4), 'hair_stretch': HAIR_STRETCH, 'fringe_droop': FRINGE_DROOP,
    }
    (output / 'cleanup.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=1), flush=True)


if __name__ == '__main__':
    main()
