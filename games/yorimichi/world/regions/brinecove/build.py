"""Export Brinecove for the game: ground tiles, town and nature meshes, hero models, foliage instances,
runtime.json and build-report.json in build/yorimichi/brinecove.

    blender -b --factory-startup --python games/yorimichi/world/regions/brinecove/build.py

The ground closes onto the FarHills final product's hole (ground.py), so this step reads that product. Every mesh
is exported in local metres around region.ORIGIN; the Unreal importer (import_brinecove.py) binds each material
slot to a region material, and ABelmonteRegion (tag brinecove) places the groups. The review scene
(review_build.py) builds the same modules for Eevee renders and is never read here.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import yori  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import random  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402

import bpy  # noqa: E402
import numpy as np  # noqa: E402

from atelier.gltf import glb_parts  # noqa: E402
from terrain_product import load  # noqa: E402
from brinecove import flora, ground, hero_assets, modules, region as R  # noqa: E402
from brinecove import layout as L  # noqa: E402
from brinecove.geom import Builder  # noqa: E402
from brinecove.paths import BUILD as OUT, TEXTURES  # noqa: E402

ROOT = '/Game/Brinecove'
TILE = 256.0
IDENTITY = {'translation_cm': [0., 0., 0.], 'rotation_xyzw': [0., 0., 0., 1.], 'scale': [1., 1., 1.]}
# Surfaces a player walks through: no collision, and the translucent ones cast no shadow.
SOFT = ('leaf_', 'palm_', 'waterfall', 'mist', 'spray', 'foam', 'water', 'vine', 'flower', 'grass', 'fern')
MASKED = ('leaf_', 'palm_', 'waterfall', 'spray')
TRANSLUCENT = ('mist',)
EMISSIVE = ('lantern', 'glass_warm')
PAN_CM_S = {'waterfall': -0.9}  # UV v per second: the curtain's streaks run down
MODULES = [('Rocks', lambda: modules.terrain_dressing(Builder('rocks'), hills=False)),
           ('Harbor', modules.harbor), ('TownLower', modules.lower_town), ('Market', modules.market),
           ('TownUpper', modules.upper_town), ('Landmarks', modules.landmarks), ('Ships', modules.ships),
           ('Props', modules.props), ('Understory', modules.vegetation)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def srgb_to_linear(value):
    value = value / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def soft(mat):
    return mat.startswith(SOFT)


def kind(mat):
    if mat.startswith(TRANSLUCENT):
        return 'translucent'
    if mat.startswith(MASKED):
        return 'masked'
    if mat.startswith(EMISSIVE):
        return 'emissive'
    return 'opaque'


def rim():
    """FarHills' hole boundary from its final product (world.farhills)."""
    mesh = load(yori.OUT / 'terrain/FarHills/final.npz', owner='FarHills', stage='final', city=True)
    vertices, triangles = np.asarray(mesh.vertices), np.asarray(mesh.triangles())
    x0, y0, x1, y1 = R.OUTER_WORLD
    near = ((np.abs(vertices[:, 0] - x0) < .05) | (np.abs(vertices[:, 0] - x1) < .05)
            | (np.abs(vertices[:, 1] - y0) < .05) | (np.abs(vertices[:, 1] - y1) < .05))
    near &= (vertices[:, 0] > x0 - .05) & (vertices[:, 0] < x1 + .05) & (vertices[:, 1] > y0 - .05) & (vertices[:, 1] < y1 + .05)
    keep = near[triangles].sum(1) >= 2
    used = np.unique(triangles[keep])
    remap = {int(v): i for i, v in enumerate(used)}
    local = [[remap[int(v)] for v in t] for t in triangles[keep]]
    return R.rim_from_mesh(vertices[used].tolist(), local)


def split(builder, prefix):
    """Tiles of TILE metres, and per tile a solid part and a soft part (foliage cards, water, spray)."""
    parts, outside = {}, 0
    ox0, oy0, ox1, oy1 = R.OUTER
    for f, mat in zip(builder.faces, builder.mats):
        pts = [builder.verts[i] for i in f]
        cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        if not (ox0 <= cx <= ox1 and oy0 <= cy <= oy1):
            outside += 1
            continue
        key = (int((cx - ox0) // TILE), int((cy - oy0) // TILE), soft(mat))
        part = parts.get(key)
        if part is None:
            part = parts[key] = Builder(f'SM_BC_{prefix}_{key[0]}_{key[1]}' + ('_Soft' if key[2] else ''))
        normals = [builder.normals[i] for i in f] if builder.normals is not None else None
        part.face(pts, mat, [builder.uvs[i] for i in f], normals)
    return parts, outside


def blender_materials():
    result = {}
    for name in L.COLORS:
        material = bpy.data.materials.new('BC_' + name)
        material.use_nodes = True
        result[name] = material
    return result


def mesh_object(builder, materials):
    used = sorted(set(builder.mats))
    index = {name: i for i, name in enumerate(used)}
    mesh = bpy.data.meshes.new(builder.name)
    mesh.from_pydata(builder.verts, [], builder.faces)
    uv_layer = mesh.uv_layers.new(name='UVMap')
    for loop in mesh.loops:
        uv_layer.data[loop.index].uv = builder.uvs[loop.vertex_index]
    for name in used:
        mesh.materials.append(materials[name])
    custom = builder.normals is not None
    for poly, mat in zip(mesh.polygons, builder.mats):
        poly.material_index = index[mat]
        poly.use_smooth = custom
    mesh.validate(verbose=False)
    mesh.update()
    if custom:
        normals = list(builder.normals)
        for poly in mesh.polygons:
            for v in poly.vertices:
                if normals[v] is None:
                    normals[v] = tuple(poly.normal)
        mesh.normals_split_custom_set_from_vertices(normals)
    obj = bpy.data.objects.new(builder.name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def export(obj, path):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB', use_selection=True, export_apply=True,
                              export_yup=True, export_animations=False, export_skins=False, export_cameras=False,
                              export_lights=False, export_extras=False, export_normals=True,
                              export_image_format='NONE', export_materials='EXPORT')


def glb_info(path):
    """Triangle count, material slot names and bounds (local metres, z up) of an exported GLB."""
    doc, _ = glb_parts(path.read_bytes())
    triangles, low, high = 0, [math.inf] * 3, [-math.inf] * 3
    for mesh in doc['meshes']:
        for primitive in mesh['primitives']:
            triangles += doc['accessors'][primitive['indices']]['count'] // 3
            accessor = doc['accessors'][primitive['attributes']['POSITION']]
            # glTF is y up: (x, z, -y) in Blender's frame.
            (ax, ay, az), (bx, by, bz) = accessor['min'], accessor['max']
            for k, (lo, hi) in enumerate(((ax, bx), (-bz, -az), (ay, by))):
                low[k], high[k] = min(low[k], lo), max(high[k], hi)
    return triangles, [m['name'] for m in doc.get('materials', [])], [low, high]


def material_report(names):
    (OUT / 'textures').mkdir(parents=True, exist_ok=True)
    report = {}
    for name in sorted(names):
        hex_colour = L.COLORS.get(name, '#808080')
        colour = [srgb_to_linear(int(hex_colour[i:i + 2], 16)) for i in (1, 3, 5)]
        texture = next((TEXTURES / f'{name}{ext}' for ext in ('.png', '.jpg') if (TEXTURES / f'{name}{ext}').exists()), None)
        file = None
        if texture:
            file = f'T_BC_{name}{texture.suffix}'
            shutil.copy2(texture, OUT / 'textures' / file)
        report[name] = {'name': 'MI_BC_' + name, 'colour': colour, 'texture': file, 'kind': kind(name),
                        'pan': PAN_CM_S.get(name, 0.), 'roughness': .3 if name.startswith('water') else .88,
                        'metal': name in ('metal', 'gold')}
    return report


def hero_models(materials_out):
    """Each processed TRELLIS/Tripo model once, with its placements; its own textures become region textures."""
    entries, groups = [], []
    for slug, placements in hero_assets.placements(modules.HULL).items():
        obj = hero_assets.import_model(slug)
        if obj is None:
            continue
        name = 'SM_BC_Hero_' + ''.join(part.title() for part in slug.split('-'))
        obj.name = name
        slots = []
        for k, material in enumerate(obj.data.materials):
            key = f'hero_{slug}_{k}'
            image = next((node.image for node in material.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image), None)
            file = None
            if image is not None:
                file = f'T_BC_{key}.png'
                image.file_format = 'PNG'
                image.save(filepath=str(OUT / 'textures' / file))  # the glTF importer packs its images
            materials_out[key] = {'name': 'MI_BC_' + key, 'colour': [1., 1., 1.], 'texture': file, 'kind': 'opaque',
                                  'pan': 0., 'roughness': .8, 'metal': False}
            material.name = 'BC_' + key
            slots.append(key)
        path = OUT / 'glb' / f'{name}.glb'
        export(obj, path)
        triangles, names, bounds = glb_info(path)
        entries.append({'name': name, 'path': path.relative_to(OUT).as_posix(), 'sha256': sha(path), 'triangles': triangles,
                        'bounds_m': bounds, 'slots': [n[3:] for n in names], 'collision': True})
        transforms = [transform(x, y, z, yaw, scale, pitch) for x, y, z, yaw, scale, pitch in placements]
        groups.append(group(name, [n[3:] for n in names], transforms, collision=True, shadow=True, cull_cm=60000))
    return entries, groups


def transform(x, y, z, yaw=0.0, scale=1.0, pitch=0.0):
    """Unreal transform relative to the region origin from local metres and Blender degrees.

    Unreal's y is Blender's -y, so a turn about z by yaw becomes -yaw; pitch turns about local x first."""
    hy, hp = math.radians(-yaw) / 2, math.radians(-pitch) / 2
    qz = (0., 0., math.sin(hy), math.cos(hy))
    qx = (math.sin(hp), 0., 0., math.cos(hp))
    x1, y1, z1, w1 = qz
    x2, y2, z2, w2 = qx
    q = (w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2, w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
         w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2, w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2)
    return {'translation_cm': [round(x * 100, 1), round(-y * 100, 1), round(z * 100, 1)],
            'rotation_xyzw': [round(c, 6) for c in q], 'scale': [scale, scale, scale]}


def group(name, slots, transforms, *, collision, shadow, cull_cm):
    return {'asset': f'{ROOT}/Meshes/{name}.{name}', 'materials': [f'{ROOT}/Materials/MI_BC_{s}.MI_BC_{s}' for s in slots],
            'plant': False, 'collision': collision, 'shadow': shadow, 'cull_cm': cull_cm, 'transforms': transforms}


def main():
    started = time.time()
    (OUT / 'glb').mkdir(parents=True, exist_ok=True)
    for stale in (OUT / 'glb').glob('*.glb'):
        stale.unlink()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    materials = blender_materials()
    meshes, groups, used = [], [], set()
    rim_shape, rim_world = rim()
    terrain, seam = ground.build(rim_shape, rim_world)
    print(f'ground: {seam}; {time.time() - started:.0f}s', flush=True)
    sources = [('Ground', terrain)] + [(name, fn()) for name, fn in MODULES]
    report_outside = {}
    for prefix, builder in sources:
        parts, outside = split(builder, prefix)
        report_outside[prefix] = outside
        for (_, _, is_soft), part in sorted(parts.items()):
            obj = mesh_object(part, materials)
            path = OUT / 'glb' / f'{part.name}.glb'
            export(obj, path)
            bpy.data.objects.remove(obj, do_unlink=True)
            triangles, names, bounds = glb_info(path)
            slots = [n[3:] for n in names]
            used.update(slots)
            water = all(s.startswith(('water', 'mist', 'spray', 'foam', 'waterfall')) for s in slots)
            meshes.append({'name': part.name, 'path': path.relative_to(OUT).as_posix(), 'sha256': sha(path),
                           'triangles': triangles, 'bounds_m': bounds, 'slots': slots, 'collision': not is_soft})
            groups.append(group(part.name, slots, [IDENTITY], collision=not is_soft, shadow=not water,
                                cull_cm=0 if prefix in ('Ground', 'Rocks') else 120000))
        print(f'{prefix}: {len(parts)} parts, {sum(len(f) - 2 for f in builder.faces)} triangles; '
              f'{time.time() - started:.0f}s', flush=True)
    material_entries = material_report(used)
    hero_meshes, hero_groups = hero_models(material_entries)
    meshes += hero_meshes
    groups += hero_groups
    # Foliage: each species prototype once, its placements as instances.
    protos = flora.prototypes()
    placements = {}
    for proto, x, y, z, yaw, scale in flora.scatter() + flora.bloom_spots(random.Random(5)):
        placements.setdefault(proto, []).append(transform(x, y, z, yaw, scale))
    for proto, builder in protos.items():
        if proto not in placements:
            continue
        builder.name = 'SM_BC_Plant_' + ''.join(part.title() for part in proto.split('_'))
        obj = mesh_object(builder, materials)
        path = OUT / 'glb' / f'{builder.name}.glb'
        export(obj, path)
        bpy.data.objects.remove(obj, do_unlink=True)
        triangles, names, bounds = glb_info(path)
        slots = [n[3:] for n in names]
        for s in slots:
            if s not in material_entries:
                material_entries.update(material_report({s}))
        height = bounds[1][2] - bounds[0][2]
        meshes.append({'name': builder.name, 'path': path.relative_to(OUT).as_posix(), 'sha256': sha(path),
                       'triangles': triangles, 'bounds_m': bounds, 'slots': slots, 'collision': False, 'lods': True})
        groups.append(group(builder.name, slots, placements[proto], collision=False, shadow=True,
                            cull_cm=24000 if height < 4 else 60000))
    quay_z = float(L.ground(R.QUAY_STOP[0] - R.ORIGIN[0], R.QUAY_STOP[1] - R.ORIGIN[1])) + 1.0
    runtime = {'version': 1,
               'origin_cm': [R.ORIGIN[0] * 100., -R.ORIGIN[1] * 100., R.ORIGIN[2] * 100.],
               'bounds_m': list(R.OUTER_WORLD), 'clearance_m': list(R.OUTER_WORLD),
               # Coastal dressing's boulders line the old shore, which now runs through the cove.
               'clear_prefixes': ['SW_Boulder'], 'groups': groups, 'signs': [],
               'zones': [{'key': 'brinecove_quay', 'name': 'Brinecove · quay', 'x': R.QUAY_STOP[0],
                          'y': R.QUAY_STOP[1], 'z': quay_z, 'yaw': -90.,
                          'hint': 'The pirate port in the western reach: market, galleons and the waterfall'}]}
    (OUT / 'runtime.json').write_text(json.dumps(runtime, separators=(',', ':')) + '\n')
    report = {'meshes': meshes, 'materials': material_entries, 'seam': seam, 'outside_faces': report_outside,
              'triangles': sum(m['triangles'] for m in meshes),
              'instances': sum(len(g['transforms']) for g in groups)}
    (OUT / 'build-report.json').write_text(json.dumps(report, indent=1) + '\n')
    print(f'BRINECOVE GAME BUILD COMPLETE: {len(meshes)} meshes, {len(groups)} groups, {report["triangles"]} unique '
          f'triangles, {report["instances"]} instances; {time.time() - started:.0f}s', flush=True)


if __name__ == '__main__':
    main()
