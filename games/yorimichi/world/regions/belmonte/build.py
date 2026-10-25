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
from atelier.model_files import source_records, retain_files
from belmonte import (layout as L, source, planting, terrain, appearance, model_pieces, ground_pieces, runtime_layout,
                      collision, furniture, props, skate)

OUT = yori.OUT / 'belmonte'

# Display text only: the committed scene library keeps its source strings, while the
# runtime signs are written in English. Keys are source labels, not identifiers.
SIGN_TRANSLATIONS = runtime_layout.SIGN_TRANSLATIONS


def clear_railway(plants):
    return runtime_layout.clear_railway(plants)


def finish_surfaces(data):
    from belmonte.material_preparation import finish
    return finish(data,OUT,yori.ASSETS,source.LIBRARY)


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
        entries.append({'name': name, 'path': path.relative_to(OUT).as_posix(), 'sha256': source.sha(path),
                        'bounds_m': [info['min'], info['max']], 'triangles': info['triangles'], 'slots': ['Ground']})
    return entries, seam


def osteria_landing():
    return runtime_layout.osteria_landing(source.manifest())


# Local building-space TV placements (mesh_name, local_pivot_cm, local_yaw_deg, local_watch_cm, local_watch_yaw_deg, scale).
TV_BUILDING_SPOTS = runtime_layout.TV_BUILDING_SPOTS


def tv_spots(data=None):
    return runtime_layout.tv_spots(data or source.manifest())


def map_zones(town_z):
    return runtime_layout.map_zones(town_z,source.manifest())


def outward_hulls(hulls, bars=(), over=()):
    """A committed hull file written to glb/ with its faces turned out of their solids (the library's wind inward), as
    the drawn meshes and the generated shells face: the skate surface keeps a face's side. The mesh's reachable
    bars (belmonte/skate.py) collide too, so the board meets the line it grinds, and what is drawn over a too low
    hull (`over`, skate.over_hull: a well's posts and roof)."""
    path = OUT / 'glb' / hulls.name
    collision.write_glb(path, np.concatenate([collision.mirror(source.triangles(hulls))] + [b.faces() for b in bars]
                                             + [np.asarray(over, float).reshape(-1, 3, 3)]))
    return {'path': path.relative_to(OUT).as_posix(), 'sha256': source.sha(path),
            'source': hulls.relative_to(source.LIBRARY).as_posix()}


def building_collision(data, bars):
    """Buildings collide with shells generated from what is drawn (belmonte/collision.py): the committed hulls plus
    the drawn storeys, roofs and stand tiers they miss, and plugs in the openings to unfurnished interiors. Writes each
    <mesh>_Collision.glb and fails if a walker could still get inside: ({mesh name: collision record}, report). A
    record replaces the mesh's committed hull before model_pieces bounds it, so the piece owning the hull owns it.
    A mesh's reachable bars ({mesh name: [skate.Bar]}) join its collision, so the board meets the line it grinds."""
    records, report = {}, {}
    for name, (transform, entries) in collision.buildings(data).items():
        building = collision.load(name, transform, entries)
        shell = collision.generate(building)
        result = collision.audit(building, shell.faces, stats=False)
        if result.intrusion_m3 or result.uncovered_wall > collision.MAX_UNCOVERED or result.uncovered_roof > collision.MAX_UNCOVERED:
            raise ValueError(f'{name}: generated collision leaves the building open: {result.row()}')
        triangles = {}
        for entry in entries:
            if 'collision' not in entry:
                continue
            path = OUT / 'glb' / (entry['name'] + '_Collision.glb')
            faces = np.concatenate([shell.faces[entry['name']]] + [b.faces() for b in bars.get(entry['name'], ())])
            collision.write_glb(path, faces)
            triangles[entry['name']] = len(faces)
            records[entry['name']] = {'path': path.relative_to(OUT).as_posix(), 'sha256': source.sha(path),
                                      'triangles': triangles[entry['name']], 'generated': True}
        report[name] = {'triangles': triangles, 'kept_drawn_triangles': shell.skin_triangles, 'plugs': shell.plugs,
                        'reachable_m3': result.intrusion_m3, 'uncovered_wall': round(result.uncovered_wall, 4),
                        'uncovered_roof': round(result.uncovered_roof, 4)}
        print(f'BELMONTE COLLISION {name}: {sum(triangles.values())} triangles, {shell.plugs} plugs', flush=True)
    print(f'BELMONTE COLLISION: {sum(sum(r["triangles"].values()) for r in report.values())} triangles '
          f'for {len(report)} buildings', flush=True)
    return records, report


def furniture_collision(entry, drawn, data):
    """Skate furniture (benches, planters, walls, basins) collides with columns generated from its drawn tops
    (belmonte/furniture.py); fails if the collision leaves any of the drawing outside. Its grind lines come with the
    town's (belmonte/skate.py), from this collision."""
    path = OUT / 'glb' / (entry['name'] + '_Collision.glb')
    item = furniture.generate(entry, drawn, run=furniture.run_axis(data, entry, drawn))
    worst = float(furniture.outside_m(item, np.unique(np.round(item.drawn.reshape(-1, 3), 5), axis=0)).max())
    if worst > furniture.TOP_TOL_M + 1e-3:
        raise ValueError(f'{entry["name"]}: drawn geometry {worst:.3f} m outside its generated collision')
    collision.write_glb(path, item.faces)
    entry['collision'] = {'path': path.relative_to(OUT).as_posix(), 'sha256': source.sha(path),
                          'triangles': len(item.faces), 'generated': True}
    print(f'BELMONTE FURNITURE {entry["name"]}: {len(item.faces)} triangles', flush=True)
    return {'triangles': len(item.faces), 'columns': len(item.columns), 'drawn_outside_m': round(worst, 3)}


def prop_collision(entry, drawn):
    """A prop made for the game (belmonte/props.py) collides with boxes over its seat, backrest and legs; fails if the
    boxes leave any of the drawing outside. Its grind lines come with the town's, from this collision."""
    path = OUT / 'glb' / (entry['name'] + '_Collision.glb')
    faces, worst, seat = props.boxes(source.triangles(drawn))
    if worst > furniture.TOP_TOL_M + 1e-3:
        raise ValueError(f'{entry["name"]}: drawn geometry {worst:.3f} m outside its collision')
    collision.write_glb(path, faces)
    entry['collision'] = {'path': path.relative_to(OUT).as_posix(), 'sha256': source.sha(path),
                          'triangles': len(faces), 'generated': True}
    print(f'BELMONTE PROP {entry["name"]} ({entry["prop"]}): {len(faces)} triangles, seat at {seat:.3f} m', flush=True)
    return {'prop': entry['prop'], 'triangles': len(faces), 'seat_m': round(seat, 3), 'drawn_outside_m': round(worst, 3)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'glb').mkdir(exist_ok=True)
    (OUT / 'textures').mkdir(exist_ok=True)
    data = source.manifest()
    ground_pieces.placements(data)
    data = props.apply(data, OUT / 'props')
    materials = finish_surfaces(data)
    by_asset, meshes, surfaces = {}, [], []
    furniture_report, collisions = {}, {}
    above = skate.street_query(data)
    bars, bar_lines = skate.bars(data, above)
    shell_records, shells = building_collision(data, bars)
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
        if entry.get('prop'):
            furniture_report[entry['name']] = prop_collision(entry, destination)
            collisions[entry['name']] = OUT / entry['collision']['path']
        elif 'collision' in entry:
            hulls = source.LIBRARY / entry['collision']['path']
            assert source.sha(hulls) == entry['collision']['sha256'], hulls
            if skate.as_drawn(entry['name']):
                entry = {k: v for k, v in entry.items() if k != 'collision'}     # its drawn counter and shelf collide
            elif furniture.is_furniture(entry['name']):
                furniture_report[entry['name']] = furniture_collision(entry, path, data)
            else:
                entry['collision'] = (shell_records[entry['name']] if collision.is_building(entry['name'])
                                      else outward_hulls(hulls, bars.get(entry['name'], ()), skate.over_hull(entry, hulls)))
            if 'collision' in entry:
                collisions[entry['name']] = OUT / entry['collision']['path']
        if ground_pieces.is_ground(entry['name']):
            surface, prepared = ground_pieces.prepare(entry, destination, OUT)
            surfaces.append(surface)
        else:
            prepared = model_pieces.prepare(entry, destination)
        meshes.extend(row[0] for row in prepared)
        by_asset[entry['source_asset']] = prepared
    extra, seam = surroundings()
    pieces = []
    for entry in extra:
        surface, prepared = ground_pieces.prepare(entry, OUT / entry['path'], OUT)
        surfaces.append(surface)
        pieces.extend(row[0] for row in prepared)
    extra = pieces
    meshes.extend(extra)
    grouped = {}
    for placement in data['placements']:
        for entry, slots, collides in by_asset[placement['asset']]:
            # Retained glTF names pin the original material slots for every piece.
            names = [materials[placement['materials'][slot]]['name'] for slot in slots]
            bindings = tuple(f'/Game/Belmonte/Materials/{name}.{name}' for name in names)
            # A child may omit a material that distinguished two original instance
            # groups. Keep their parent grouping, including its max-scale cull policy.
            parent_slots = entry.get('parent_material_slots', slots)
            parent_bindings = tuple(materials[placement['materials'][slot]]['name'] for slot in parent_slots)
            key = (entry['name'], bindings, collides, parent_bindings)
            grouped.setdefault(key, []).append(placement['transform'])
    groups = []
    for (name, bindings, collides, _parent_bindings), transforms in grouped.items():
        water = any(word in name for word in ('Water', 'Foam'))
        entry = next(entry for entry in meshes if entry['name'] == name)
        policy_bounds = entry.get('parent_bounds_m', entry['bounds_m'])
        span = max(np.subtract(policy_bounds[1], policy_bounds[0]))
        span *= max(max(abs(value) for value in transform['scale']) for transform in transforms)
        groups.append({'asset': f'/Game/Belmonte/Meshes/{name}.{name}', 'materials': list(bindings),
                       'plant': False, 'collision': collides and not water, 'shadow': not water,
                       'parent_collision': not water,
                       'cull_cm': 50000 if span < 8. else 0, 'transforms': transforms})
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
    woods = planting.woodland(source.Surface(source.triangles(OUT / 'ground/glb/SM_BM_NorthApron.glb')))
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
    signs = [dict(sign, text=SIGN_TRANSLATIONS.get(sign['text'], sign['text'])) for sign in data['signs']]
    rails, grind_report = skate.rails(data, collisions, bar_lines, above)
    print(f'BELMONTE GRIND LINES: {grind_report}', flush=True)
    town_z = float(source.terrain().height(0., -18.)) + L.ORIGIN[2] + 1.
    runtime = {'version': 1, 'origin_cm': L.native_origin(), 'bounds_m': L.BOUNDS,
               'clearance_m': list(terrain.OUTER), 'groups': groups, 'signs': signs, 'railway_corridor': L.RAILWAY,
               'zones': map_zones(town_z), 'tv_spots': tv_spots(data), 'rails': rails}
    # Current meshes/hulls are complete now. Retire only this producer's generated
    # model members, so a normal removal/rename cannot strand an invalid inventory.
    expected = [Path(name).relative_to('glb').as_posix()
                for _, name in source_records(meshes, collision_directory='glb')]
    ground_pieces.publish(OUT, surfaces, L.native_origin())
    retired = retain_files(OUT / 'glb', expected)
    if retired:
        print(f'BELMONTE retired {len(retired)} superseded generated model files', flush=True)
    (OUT / 'runtime.json').write_text(json.dumps(runtime, separators=(',', ':')) + '\n')
    (OUT / 'build-report.json').write_text(json.dumps({'meshes': meshes, 'materials': materials,
                                                     'planting': plant_report, 'seam': seam,
                                                     'building_collision': shells,
                                                     'furniture_collision': furniture_report,
                                                     'grind_lines': grind_report}, indent=1) + '\n')
    print(f'BELMONTE BUILD COMPLETE: {len(meshes)} meshes, {len(groups)} groups, {sum(len(v) for v in plants.values())} plants', flush=True)


if __name__ == '__main__':
    main()
