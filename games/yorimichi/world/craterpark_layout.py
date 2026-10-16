"""Validated Crater Park data used by the surrounding terrain, planting and map.

Render meshes and the park document still rebuild the park. This cutoff records the
values placement consumers use, so an unchanged landform need not rebuild the island.
"""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / 'regions'))
from craterpark import placement  # noqa: E402
from craterpark.v2 import v4_placement  # noqa: E402


def array_identity(value):
    value = np.ascontiguousarray(value, dtype='<f8')
    return {'shape': list(value.shape), 'sha256': hashlib.sha256(value.tobytes()).hexdigest()}


def snapshot():
    """@cc [owner:fontanierh,label:correctness] validated-crater-layout-cutoff
    The cutoff MUST validate current selected geometry before recording every value
    terrain, exclusion, footprint and spawn consumers read. Missing or stale source,
    invalid geometry and changing inputs MUST fail. Riding-only changes MAY retain
    the same identity; changed ground, site, depth, frame or spawn MUST NOT.
    """
    before = v4_placement.identity()
    ground, _, _ = v4_placement._geometry(*before)
    grid = v4_placement.ground_grid()
    result = {'schema': 1, 'ground': array_identity(ground),
              'site': array_identity(v4_placement.site_polygon()), 'depth': v4_placement.depth(),
              'frame': {'centre': placement.CENTRE, 'heading': placement.HEADING, 'lift': placement.LIFT,
                        'native_centre': placement.frame()},
              'drop_in': [np.asarray(p).tolist() for p in v4_placement.drop_in()],
              'grid': None if grid is None else {'metadata': grid[0], 'heights': array_identity(grid[1]),
                                                'weights': array_identity(grid[2])}}
    if v4_placement.identity() != before:
        raise ValueError('Crater Park layout inputs changed during observation; retry with stable inputs')
    return result


def main():
    import yori
    output = yori.OUT / 'craterpark' / 'layout-identity.json'
    text = json.dumps(snapshot(), sort_keys=True, indent=1, allow_nan=False) + '\n'
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.is_file() or output.read_text() != text:
        output.write_text(text)
    print('Crater Park layout identity validated', flush=True)


if __name__ == '__main__':
    main()
