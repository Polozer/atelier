"""The existing FarHills natural -> railway-final geometry, before appearance."""
import json
from pathlib import Path
import sys
import numpy as np

# Blender's --python runner does not add the script folder to sys.path.
if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import yori  # noqa: E402,F401

from terrain_product import Mesh, load, save


def owns_fine_ground(x, y, *, city):
    return (-300. < x < 300. and -300. < y < 300.) or (city and 300. < x < 1420. and -300. < y < 500.)


def generate(fine_count, *, city, progress=None):
    """@cc [owner:fontanierh,label:correctness] farhills-discrete-extraction
    Preserve the r8 grid/parent/rail lattice, hidden footprints and nonlinear
    shape evaluation order. The existing original polygons MUST reach the one
    conforming earthworks call before any product triangulation. Appearance,
    scenery and Blender object creation do not own or change these arrays.
    """
    import shorelines
    from hidamari.layout import coastal_backdrop_height
    from farhills_grid import mesh_grid, source_grid, rail_refinement
    from hidamari.mountains import contains as under_foothills
    from train import earthworks

    phase = progress or (lambda message: print(message, flush=True))
    phase('FarHills: original grid and conforming coastal refinement')
    xs, ys, z = mesh_grid(fine_count, city=city)
    vertices, faces = shorelines.grid_mesh(xs, ys, z,
        hidden=lambda x, y: owns_fine_ground(x, y, city=city), shape=coastal_backdrop_height,
        parents=source_grid(city=city), parent_refinement=rail_refinement(city=city),
        edge_knots={(0,-300.): np.linspace(-300.,300.,fine_count)})
    print('coastal far hills: %d vertices, %d quads' % (len(vertices), len(faces)), flush=True)
    natural = Mesh.from_polygons(vertices, faces)
    phase('FarHills: single railway carve over %d natural vertices' % len(vertices))
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


def export_mesh(fine_count, directory, *, city):
    """@cc [owner:fontanierh,label:correctness] farhills-export-product-read
    Normal city export MUST consume the final product supplied by its verified
    recipe read. Missing/malformed/wrong-mode products MUST fail, never trigger
    silent regeneration. The explicit no-city direct-script fallback retains
    its existing geometry construction and ownership, separately from that
    normal production path. This loader alone does not certify source freshness.
    """
    if city:
        return load(Path(directory)/'final.npz', owner='FarHills', stage='final', city=True)
    natural, final, report = generate(fine_count, city=False)
    publish(directory, natural, final, report, city=False)
    return final


def main(argv=None):
    import argparse
    import threading
    import time
    import yori
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-city', action='store_true', help='explicit isolated fallback geometry')
    if argv is None:
        argv = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
    args = parser.parse_args(argv)
    count = json.loads((yori.OUT/'world.json').read_text())['n']
    started = time.monotonic()
    current = ['starting']
    stopped = threading.Event()

    def progress(message):
        current[0] = message
        print('%s; elapsed %.1fs' % (message, time.monotonic()-started), flush=True)

    def heartbeat():
        while not stopped.wait(25):
            print('FarHills status heartbeat %.0fs: %s; no new stage completed' %
                  (time.monotonic()-started, current[0]), flush=True)

    observer = threading.Thread(target=heartbeat, daemon=True)
    observer.start()
    try:
        natural, final, report = generate(count, city=not args.no_city, progress=progress)
        progress('FarHills: publishing ordered natural/final products')
        publish(yori.OUT/'terrain/FarHills', natural, final, report, city=not args.no_city)
        progress('FarHills: complete, %d final vertices' % len(final.vertices))
    finally:
        stopped.set()
        observer.join(timeout=1.)


if __name__ == '__main__':
    main()
