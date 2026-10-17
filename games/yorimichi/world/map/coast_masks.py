"""Record geometry masks from exact, semantic, north-up atlas reference plans.

Regenerate the plans with build_map.py --atlas-reference for the current world
first. This tool makes deterministic reference data; it never edits a painting
or calls an image model. Blue is reserved for water in those plans.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

import atlas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--references', type=Path, required=True)
    parser.add_argument('--verify-paintings', action='store_true',
                        help='check all paintings and record current-terrain revalidation without changing their generation provenance')
    args = parser.parse_args()
    out = atlas.ASSETS / 'coasts'
    out.mkdir(exist_ok=True)
    manifest = dict(kind='semantic-terrain-water-masks', geography=atlas.geography_signature(), frames={})
    for key, bounds in [('world', atlas.WORLD_BOUNDS), *((r['key'], r['bounds']) for r in atlas.REGIONS)]:
        reference = args.references / key / 'rough.png'
        info = json.loads((reference.parent / 'map.json').read_text())
        if info['bounds'] != bounds:
            raise ValueError('Reference frame differs: '+key)
        with Image.open(reference) as image:
            mask = Image.fromarray(np.where(atlas.water_pixels(image), 0, 255).astype('uint8'))
            mask.save(out / (key + '.png'), optimize=True)
        manifest['frames'][key] = dict(bounds=bounds, sha256=hashlib.sha256((out / (key + '.png')).read_bytes()).hexdigest(),
                                       reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest())
        print('COAST MASK '+key, flush=True)
    (out / 'source.json').write_text(json.dumps(manifest, indent=2)+'\n')
    if args.verify_paintings:
        records, failures = [], []
        for key, coast in manifest['frames'].items():
            path = atlas.ASSETS / f'{key}.png'
            record = json.loads(path.with_suffix('.json').read_text())
            painting_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if record['bounds'] != coast['bounds'] or record.get('labels_baked', True) or record['output_sha256'] != painting_sha:
                raise ValueError('Painting provenance differs: '+key)
            try:
                with Image.open(path) as painting, Image.open(out / f'{key}.png') as mask:
                    error = atlas.verify_coast(painting, mask, key)
                print(f'COAST VERIFIED {key}: {error:.3%}', flush=True)
            except ValueError as error:
                failures.append(str(error))
                print(str(error), flush=True)
                continue
            record['verified_geography'] = dict(kind='terrain-reference-revalidation', geography=manifest['geography'],
                                                painting_sha256=painting_sha, coast_sha256=coast['sha256'],
                                                reference_sha256=coast['reference_sha256'])
            records.append((path.with_suffix('.json'), record))
        if failures:
            raise ValueError('Correct the failed paintings before recording revalidation: '+'; '.join(failures))
        for path, record in records:
            path.write_text(json.dumps(record, indent=2)+'\n')


if __name__ == '__main__':
    main()
