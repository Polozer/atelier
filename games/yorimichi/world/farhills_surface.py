"""The existing FarHills natural -> railway-final geometry, before appearance."""
import json
from pathlib import Path

from terrain_product import Mesh, save


def owns_fine_ground(x, y, *, city):
    return (-300. < x < 300. and -300. < y < 300.) or (city and 300. < x < 1420. and -300. < y < 500.)


def generate(fine_count, *, city):
    """@cc [owner:fontanierh,label:correctness] farhills-discrete-extraction
    Preserve the r8 grid/parent/rail lattice, hidden footprints and nonlinear
    shape evaluation order. The existing original polygons MUST reach the one
    conforming earthworks call before any product triangulation. Appearance,
    scenery and Blender object creation do not own or change these arrays.
    """
    import shorelines
    from hidamari.layout import coastal_backdrop_height
    from hidamari.forest_backdrop import mesh_grid, source_grid, rail_refinement
    from hidamari.mountains import contains as under_foothills
    from train import earthworks

    xs, ys, z = mesh_grid(fine_count, city=city)
    vertices, faces = shorelines.grid_mesh(xs, ys, z,
        hidden=lambda x, y: owns_fine_ground(x, y, city=city), shape=coastal_backdrop_height,
        parents=source_grid(city=city), parent_refinement=rail_refinement(city=city))
    print('coastal far hills: %d vertices, %d quads' % (len(vertices), len(faces)), flush=True)
    natural = Mesh.from_polygons(vertices, faces)
    vertices, faces, report = earthworks.polygons(vertices, faces, 4., hidden=under_foothills,
                                                  conform_neighbors=True)
    final = Mesh.from_polygons(vertices, faces)
    return natural, final, report


def publish(directory, natural, final, report, *, city):
    directory = Path(directory)
    save(directory/'natural.npz', natural, owner='FarHills', stage='natural', city=city)
    save(directory/'final.npz', final, owner='FarHills', stage='final', city=city)
    manifest = {'schema': 1, 'owner': 'FarHills', 'city': city,
                'units': 'metres, x east, y north, z up', 'earthworks': report}
    (directory/'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2)+'\n')
