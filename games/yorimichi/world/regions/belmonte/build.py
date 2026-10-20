"""Build Belmonte from the committed environmental library, without Haras code."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import yori  # noqa: E402
import hashlib
import json
import shutil

import numpy as np
from PIL import Image
from atelier.gltf import glb_pack, glb_parts
from belmonte import layout as L, source, planting, terrain, appearance

OUT = yori.OUT / 'belmonte'


def clear_railway(plants):
    """Clear the Belmonte railway's corridor (train/corridor.py settle): trees off it, shrubs and grass down to the
    line's soft edge, set on the carved ground; {name: removed}."""
    from train import corridor
    line = corridor.load()
    removed = {}
    if line is None:
        return removed
    for name, transforms in plants.items():
        if not transforms:
            continue
        t = np.asarray([tr['translation_cm'] for tr in transforms], float)
        x, y = t[:, 0] / 100 + L.ORIGIN[0], -t[:, 1] / 100 + L.ORIGIN[1]
        keep, z = corridor.settle(name, x, y, t[:, 2] / 100 + L.ORIGIN[2], line)
        moved = np.abs(z - (t[:, 2] / 100 + L.ORIGIN[2])) > .005
        for tr, zz, m in zip(transforms, z, moved):
            if m:
                tr['translation_cm'] = [tr['translation_cm'][0], tr['translation_cm'][1], round((zz - L.ORIGIN[2]) * 100, 1)]
        if (~keep).any():
            removed[name] = int((~keep).sum())
            plants[name] = [tr for tr, k in zip(transforms, keep) if k]
    return removed


def finish_surfaces(data):
    """Current scenery and a Tuscan ground palette with neutral texture grain."""
    materials, images = {}, {}
    for path, entry in data['materials'].items():
        if path.endswith('MI_B_foliage'):
            continue
        scalars, vectors = entry['scalars'], entry['vectors']
        atlas = 'SalonPosters' in path or '/Atelier/' in path
        texture = entry['textures'].get('BaseColor') or entry['textures'].get('DryColor')
        name = 'MI_BM_' + hashlib.sha256(path.encode()).hexdigest()[:12]
        terrain = 'terrain_' in path
        colour = vectors.get('Target', vectors.get('Color', [1., 1., 1., 1.]))
        tint = np.array(vectors.get('Tint', [1., 1., 1., 1.])) * vectors.get('StableColor', [1., 1., 1., 1.])
        layers = {}
        if terrain:
            layers={layer:list(colour) for layer,colour in source.TERRAIN_LAYERS.items()}
        materials[path] = {'name': name, 'colour': colour, 'tint': tint.tolist(), 'terrain': terrain,
                           'layers': layers, 'tile_m': 9. if terrain else 1. if atlas else 1. / max(scalars.get('Scale', .25), .001),
                           'white_vertex': 'Target' in vectors or 'Color' in vectors,
                           'brightness': scalars.get('Brightness', 1.), 'atlas': atlas,
                           'water': 'water' in path.lower(), 'texture': None}
        if not texture:
            continue
        key = ('tuscan-ground' if terrain else texture) + (':atlas' if atlas else ':detail')
        if key not in images:
            if terrain:
                image_path=yori.ASSETS/'environment/textures/tuscan-ground.jpg'
                provenance=json.loads(image_path.with_suffix('.provenance.json').read_text())
                assert source.sha(image_path)==provenance['source_sha256'],image_path
            else:
                image_info = data['textures'][texture]
                image_path = source.LIBRARY / image_info['file']
                assert source.sha(image_path) == image_info['sha256'], image_path
            image = Image.open(image_path).convert('RGB')
            image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            if not atlas:
                from surface_textures import neutral_detail
                image = neutral_detail(image)
            file = 'T_BM_' + hashlib.sha256(key.encode()).hexdigest()[:12] + '.png'
            image.save(OUT / 'textures' / file)
            images[key] = file
        materials[path]['texture'] = images[key]
    return materials


def surroundings():
    from hidamari import mountains
    from train import earthworks
    collar, seam = terrain.collar()
    entries = []
    (OUT / 'natural').mkdir(exist_ok=True)
    parts = [('SM_BM_NorthApron', collar, 2.5), ('SM_BM_NorthCountry', terrain.country(), 4.)]
    joins = [(0, terrain.OUTER[0]), (0, terrain.OUTER[2]), (1, terrain.OUTER[3])]
    # The coastal profile is nonlinear between the original coarse grid knots.
    # Both natural and carved products must share every boundary knot, even
    # where the railway does not reach.
    earthworks.stitch([p[1] for p in parts], L.ORIGIN, joins, whole_seam=True)
    for name, mesh, step in parts:
        # The natural ground stays beside the built one: the route study samples it, never the railway's own cuttings.
        mesh.save(OUT / 'natural' / (name + '.glb'), 'BM_000_Ground')
        # The valley's committed terrain is not carved: the apron's carving eases out towards their seam (the bank
        # mesh, train/track.py, covers the line there) so the rim stays closed.
        earthworks.quads(mesh, L.ORIGIN, step, hidden=lambda x, y: (x > mountains.BOUNDS[0]) & (x < mountains.BOUNDS[2]) & (y > mountains.BOUNDS[1]) & (y < L.SOUTH_JOIN),
                         weight=lambda x, y: earthworks.seam_weight(x, y, L.BOUNDS))
    # Apron and country are refined at different steps: their outer seam shares every vertex where the line crosses.
    earthworks.stitch([collar, parts[1][1]], L.ORIGIN, joins, whole_seam=True)
    for name, mesh, _ in parts:
        path = OUT / 'glb' / (name + '.glb')
        info = mesh.save(path, 'BM_000_Ground')
        appearance.paint_join(path, mesh)
        # The whole painted surface stays the product the map, route and tests read; the game draws its tiles.
        cut = split_tiles(path, SURROUNDING_TILE_M)
        assert info['triangles'] == sum(tile['triangles'] for tile in cut), name
        entries.extend(cut)
    return entries, seam


# A single mesh kilometres wide is never frustum- or cascade-culled and has one LOD for all of it. Tiles of this size
# (plan metres, aligned to the region origin) are culled and take their LODs one by one (import_belmonte.py).
SURROUNDING_TILE_M = 500.


def split_tiles(path, size):
    """@cc [owner:fontanierh,label:correctness] belmonte-surrounding-tiles
    The painted surroundings MUST be cut along whole triangles only, each triangle in exactly one tile (by its
    plan centroid), every tile keeping its vertices' positions, normals, UVs and colours bit for bit, so tile edges
    meet exactly as the whole surface did. Tiles are named <whole>_NN in row-major order of the non-empty cells.
    """
    doc, binary = glb_parts(path.read_bytes())
    primitive = doc['meshes'][0]['primitives'][0]
    assert len(doc['meshes']) == 1 and len(doc['meshes'][0]['primitives']) == 1, path

    def read(index):
        accessor = doc['accessors'][index]
        view = doc['bufferViews'][accessor['bufferView']]
        dtype = {5126: '<f4', 5125: '<u4'}[accessor['componentType']]
        width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[accessor['type']]
        start = view['byteOffset'] + accessor.get('byteOffset', 0)
        return np.frombuffer(binary, dtype, accessor['count'] * width, start).reshape(-1, width)

    for stale in path.parent.glob(path.stem + '_[0-9][0-9].glb'):
        stale.unlink()
    attributes = {key: read(index) for key, index in primitive['attributes'].items()}
    faces = read(primitive['indices']).reshape(-1, 3)
    position = attributes['POSITION']                    # glTF frame: x east, y up, z south
    centre = position[faces].mean(axis=1)
    cell = np.floor(np.c_[centre[:, 0], -centre[:, 2]] / size).astype(np.int64)
    keys, which = np.unique(cell[:, ::-1], axis=0, return_inverse=True)
    which = which.reshape(-1)
    entries = []
    for number in range(len(keys)):
        tri = faces[which == number]
        used, local = np.unique(tri, return_inverse=True)
        tile_doc = {key: doc[key] for key in ('asset', 'scene', 'materials')}
        name = f'{path.stem}_{number:02d}'
        tile_doc.update(scenes=[{'nodes': [0]}], nodes=[{'name': name, 'mesh': 0}], accessors=[], bufferViews=[])
        blob = b''
        layout = {}
        for key, values in [*((k, attributes[k][used]) for k in attributes), ('indices', local.astype('<u4').reshape(-1, 1))]:
            data = np.ascontiguousarray(values).tobytes()
            tile_doc['bufferViews'].append({'buffer': 0, 'byteOffset': len(blob), 'byteLength': len(data),
                                            'target': 34963 if key == 'indices' else 34962})
            accessor = {'bufferView': len(tile_doc['bufferViews']) - 1, 'componentType': 5125 if key == 'indices' else 5126,
                        'count': int(values.size if key == 'indices' else len(values)),
                        'type': 'SCALAR' if key == 'indices' else ['', 'SCALAR', 'VEC2', 'VEC3', 'VEC4'][values.shape[1]]}
            if key == 'POSITION':
                accessor.update(min=values.min(axis=0).tolist(), max=values.max(axis=0).tolist())
            tile_doc['accessors'].append(accessor)
            layout[key] = len(tile_doc['accessors']) - 1
            blob += data + b'\0' * (-len(data) % 4)
        tile_doc['meshes'] = [{'name': name, 'primitives': [{'attributes': {k: layout[k] for k in attributes},
                                                             'indices': layout['indices'], 'material': primitive.get('material', 0)}]}]
        tile_doc['buffers'] = [{'byteLength': len(blob)}]
        out = path.with_name(name + '.glb')
        out.write_bytes(glb_pack(tile_doc, blob))
        points = position[used].astype(np.float64)
        low = [float(points[:, 0].min()), float(-points[:, 2].max()), float(points[:, 1].min())]
        high = [float(points[:, 0].max()), float(-points[:, 2].min()), float(points[:, 1].max())]
        entries.append({'name': name, 'path': out.relative_to(OUT).as_posix(), 'sha256': source.sha(out),
                        'bounds_m': [low, high], 'triangles': int(len(tri)), 'slots': ['Ground']})
    return entries


def osteria_landing():
    """Place the authored local landing inside the committed taproom's actual transform."""
    data = source.manifest()
    assets = {m['source_asset'] for m in data['meshes'] if m['name'] == 'SM_BM_BH_Osteria_Taproom'}
    placements = [p['transform'] for p in data['placements'] if p['asset'] in assets]
    if len(assets) != 1 or len(placements) != 1:
        raise ValueError('Osteria map landing requires exactly one committed taproom placement')
    transform = placements[0]
    # Local plan metres: clear the stool by one metre, at floor level. Placement
    # translation/rotation/scale belong to the source scene, never to this map stop.
    local = np.array([.4, 2.1, 0.]) * [100., -100., 100.] * transform['scale']
    native = planting.rotate(transform['rotation_xyzw'], local) + transform['translation_cm']
    position = native / [100., -100., 100.] + L.ORIGIN
    # Face the front wall relative to the taproom. The map uses plan-space yaw;
    # JapanMap converts its Y axis and negates yaw when loading native runtime data.
    angle = np.radians(-86.)
    forward = planting.rotate(transform['rotation_xyzw'], np.array([np.cos(angle), np.sin(angle), 0.]))
    return position, float(np.degrees(np.arctan2(-forward[1], forward[0])))


# Local building-space TV placements (mesh_name, local_pivot_cm, local_yaw_deg, local_watch_cm, local_watch_yaw_deg, scale).
TV_BUILDING_SPOTS = (
    ('osteria_front', 'SM_BM_BH_Osteria_Taproom', [10., -750., 230.], 90., [40., -310., 0.], -94., 1.4),
    ('osteria_back', 'SM_BM_BH_Osteria_Taproom', [685., 700., 230.], -90., [360., 350., 0.], 46.2, 1.4),
    ('salon_paris', 'SM_BM_BHip_SalonHall', [-500., -480., 255.], 90., [-500., -50., 15.], -90., 1.4),
    ('salon_bar', 'SM_BM_BHip_SalonHall', [1250., 1437.6, 305.], -90., [1250., 960., 15.], 90., 1.3),
)


def tv_spots(data=None):
    """Derive the four Belmonte racing TV spots from the committed Osteria and Salon placements."""
    data = data or source.manifest()
    by_name = {}
    for mesh_name in {'SM_BM_BH_Osteria_Taproom', 'SM_BM_BHip_SalonHall'}:
        assets = {m['source_asset'] for m in data['meshes'] if m['name'] == mesh_name}
        placements = [p['transform'] for p in data['placements'] if p['asset'] in assets]
        if len(assets) != 1 or len(placements) != 1:
            raise ValueError(f'TV placement requires exactly one committed {mesh_name} placement')
        by_name[mesh_name] = placements[0]
    out = []
    for spot_id, mesh_name, local_pivot, dyaw, local_watch, dwyaw, scale in TV_BUILDING_SPOTS:
        tr = by_name[mesh_name]
        q = tr['rotation_xyzw']
        t = np.asarray(tr['translation_cm'], float)
        s = np.asarray(tr['scale'], float)
        fwd = planting.rotate(q, np.array([1., 0., 0.]))
        base_yaw = float(np.degrees(np.arctan2(fwd[1], fwd[0])))
        pivot = (planting.rotate(q, np.asarray(local_pivot, float) * s) + t).round(2).tolist()
        watch = (planting.rotate(q, np.asarray(local_watch, float) * s) + t).round(2).tolist()
        yaw = round(((base_yaw + dyaw + 180.) % 360.) - 180., 2)
        if abs(yaw + 180.) < 1e-6:
            yaw = 180.
        watch_yaw = round(((base_yaw + dwyaw + 180.) % 360.) - 180., 2)
        out.append({'id': spot_id, 'pivot_cm': pivot, 'yaw': yaw, 'watch_cm': watch, 'watch_yaw': watch_yaw,
                    'scale': float(scale * max(abs(v) for v in s[:2]))})
    return out


def map_zones(town_z):
    """@cc [owner:fontanierh,label:correctness] belmonte-indoor-map-stop
    Indoor stops MUST follow Belmonte's origin and land on their committed floors below
    the roofs, with a clear standing footprint. The salon faces the counters and the
    osteria follows its taproom transform and faces the front wall. Outdoor stops MUST
    retain their default landing trace.
    """
    osteria, osteria_yaw = osteria_landing()
    return [
        {'key': 'belmonte', 'name': 'Belmonte · town square', 'x': L.ORIGIN[0],
         'y': L.ORIGIN[1] - 18., 'z': town_z, 'yaw': 90.,
         'hint': 'Town, estates and countryside racecourses north of the volcano'},
        {'key': 'belmonte_course', 'name': 'Belmonte · racecourse',
         'x': 385., 'y': 4255. + L.NORTH_SHIFT, 'z': float(L.ORIGIN[2] + 30.2), 'yaw': 90.,
         'hint': 'Explore the turf and sand course and its grandstands'},
        {'key': 'belmonte_training', 'name': 'Belmonte · training grounds',
         'x': 230., 'y': 4560. + L.NORTH_SHIFT, 'z': float(L.ORIGIN[2] + 30.2), 'yaw': 0.,
         'hint': 'Countryside arenas and practice grounds'},
        # Haras Valley's salon.inside, moved one metre west off the hall fixture; face the counters.
        {'key': 'belmonte_salon', 'name': 'Belmonte · Salon des Paris',
         'x': L.ORIGIN[0] + 67.8, 'y': L.ORIGIN[1] + 306.8, 'z': float(L.ORIGIN[2] + 30.2),
         'yaw': 0., 'above_m': 1.5,
         'hint': 'The betting hall by the racecourse: betting counters'},
        {'key': 'belmonte_osteria', 'name': 'Belmonte · Osteria',
         'x': float(osteria[0]), 'y': float(osteria[1]), 'z': float(osteria[2]),
         'yaw': osteria_yaw, 'above_m': 1.5,
         'hint': 'The tavern on the piazza'},
    ]


# Small props (under 8 m across) end at a distance that grows with their size: 100 m per metre, 80 to 500 m. A pot or
# a saucer stays drawn to 80 to 105 m, a chair to 86 m, a lantern post to 360 m and the course rail to 400 m; past
# that each is a few pixels at 1080p. Larger pieces are never culled.
def prop_cull_cm(span):
    return int(round(min(500., max(80., 100. * span)) * 100.)) if span < 8. else 0


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'glb').mkdir(exist_ok=True)
    (OUT / 'textures').mkdir(exist_ok=True)
    data = source.manifest()
    materials = finish_surfaces(data)
    by_asset, meshes, retained_slots = {}, [], {}
    for entry in data['meshes']:
        path = source.LIBRARY / entry['path']
        assert source.sha(path) == entry['sha256'], path
        destination = OUT / 'glb' / path.name
        if entry['name'] in terrain.VALLEY_CARVED_TILES:
            tris, bounds_m, _ = terrain.write_carved_valley_tile(path, destination)
            entry = dict(entry, path=destination.relative_to(OUT).as_posix(), sha256=source.sha(destination),
                         triangles=tris, bounds_m=bounds_m)
        else:
            shutil.copy2(path, destination)
            entry = dict(entry, path=destination.relative_to(OUT).as_posix())
        meshes.append(entry)
        by_asset[entry['source_asset']] = entry
        doc, _ = glb_parts(path.read_bytes())
        retained_slots[entry['source_asset']] = [int(material['name'].split('_')[1]) for material in doc['materials']]
        if 'collision' in entry:
            collision = source.LIBRARY / entry['collision']['path']
            assert source.sha(collision) == entry['collision']['sha256'], collision
            shutil.copy2(collision, OUT / 'glb' / collision.name)
    extra, seam = surroundings()
    meshes.extend(extra)
    grouped = {}
    for placement in data['placements']:
        entry = by_asset[placement['asset']]
        # glTF omits unused slots. The retained names pin their original index.
        slots = retained_slots[placement['asset']]
        names = [materials[placement['materials'][slot]]['name'] for slot in slots]
        bindings = tuple(f'/Game/Belmonte/Materials/{name}.{name}' for name in names)
        key = (entry['name'], bindings)
        grouped.setdefault(key, []).append(placement['transform'])
    groups = []
    for (name, bindings), transforms in grouped.items():
        water = any(word in name for word in ('Water', 'Foam'))
        entry = next(entry for entry in meshes if entry['name'] == name)
        span = max(np.subtract(entry['bounds_m'][1], entry['bounds_m'][0]))
        span *= max(max(abs(value) for value in transform['scale']) for transform in transforms)
        groups.append({'asset': f'/Game/Belmonte/Meshes/{name}.{name}', 'materials': list(bindings),
                       'plant': False, 'collision': not water, 'shadow': not water,
                       'cull_cm': prop_cull_cm(span), 'transforms': transforms})
    material_name = 'MI_BM_Ground'
    materials['Ground'] = {'name': material_name, 'colour': [.24, .30, .12, 1.], 'tint': [1., 1., 1., 1.],
                           'terrain': False, 'layers': {}, 'tile_m': 4., 'white_vertex': True,
                           'brightness': 1., 'atlas': False, 'water': False, 'texture': None, 'join': True}
    for entry in extra:
        name = entry['name']
        groups.append({'asset': f'/Game/Belmonte/Meshes/{name}.{name}',
                       'materials': [f'/Game/Belmonte/Materials/{material_name}.{material_name}'], 'plant': False,
                       'collision': True, 'shadow': True, 'cull_cm': 0,
                       'transforms': [{'translation_cm': [0., 0., 0.], 'rotation_xyzw': [0., 0., 0., 1.], 'scale': [1., 1., 1.]}]})
    plants, plant_report = planting.replacements(data, source.terrain().height)
    woods = planting.woodland(source.Surface(source.triangles(OUT / 'glb/SM_BM_NorthApron.glb')))
    for name, transforms in woods.items():
        plants.setdefault(name, []).extend(transforms)
    plant_report['connecting_woodland'] = sum(len(v) for v in woods.values())
    plant_report['tree_detail'] = 'Original detailed leaf geometry; no backdrop or _lo assets'
    plant_report['railway_corridor_removed'] = clear_railway(plants)
    for name, transforms in plants.items():
        tree = name.startswith(('Tree_', 'HD_'))
        grass = name.startswith('Grass_')
        groups.append({'asset': f'/Game/Japan/Assets/{name}.{name}', 'materials': [], 'plant': True,
                       'collision': tree, 'shadow': not grass, 'cull_cm': 8000 if grass else 36000 if not tree else 400000,
                       'transforms': transforms})
    signs = data['signs']
    for sign in signs:
        if sign['text'] == 'Votre écurie':
            sign['text'] = 'Haras de Belmonte'
    town_z = float(source.terrain().height(0., -18.)) + L.ORIGIN[2] + 1.
    runtime = {'version': 1, 'origin_cm': L.native_origin(), 'bounds_m': L.BOUNDS,
               'clearance_m': list(terrain.OUTER), 'groups': groups, 'signs': signs, 'railway_corridor': L.RAILWAY,
               'zones': map_zones(town_z), 'tv_spots': tv_spots(data)}
    (OUT / 'runtime.json').write_text(json.dumps(runtime, separators=(',', ':')) + '\n')
    (OUT / 'build-report.json').write_text(json.dumps({'meshes': meshes, 'materials': materials,
                                                     'planting': plant_report, 'seam': seam}, indent=1) + '\n')
    print(f'BELMONTE BUILD COMPLETE: {len(meshes)} meshes, {len(groups)} groups, {sum(len(v) for v in plants.values())} plants', flush=True)


if __name__ == '__main__':
    main()
