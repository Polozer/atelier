"""Give the world overview an island-shaped feathered alpha edge.

The RGB painting is never changed: its coastline still comes from the signed
terrain mask and atlas.verify_coast still checks it. The alpha channel only
controls where the UI reveals that painting, so the World view becomes the
island silhouette instead of a rectangular ocean tile. The original paid-call
receipt is nested unchanged in the new provenance record.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

import atlas


def island_alpha(mask, dilation, feather, threshold):
    land = np.asarray(mask.convert('L')) > 127
    keep = mask.convert('L').filter(ImageFilter.MaxFilter(dilation * 2 + 1))
    alpha = np.asarray(keep.filter(ImageFilter.GaussianBlur(feather))).copy()
    alpha[land] = 255
    return np.where(alpha < threshold, 0, alpha).astype('uint8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--mask', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--out-record', type=Path, required=True)
    parser.add_argument('--dilation', type=int, default=9)
    parser.add_argument('--feather', type=int, default=24)
    parser.add_argument('--threshold', type=int, default=6)
    args = parser.parse_args()

    original = json.loads(args.record.read_text())
    source_sha = hashlib.sha256(args.source.read_bytes()).hexdigest()
    if original.get('output_sha256') != source_sha:
        raise ValueError('Source painting bytes differ from their receipt')
    if original.get('labels_baked', True):
        raise ValueError('Source painting contains baked labels')
    if original.get('bounds') != atlas.WORLD_BOUNDS:
        raise ValueError('Source painting is not the production World frame')
    if 'geography' in original and original['geography'] != atlas.geography_signature():
        raise ValueError('Source painting geography is stale')
    if args.out.exists() or args.out_record.exists():
        raise FileExistsError('Preserve the existing World alpha and receipt')

    with Image.open(args.source) as raw, Image.open(args.mask) as mask:
        image = raw.convert('RGBA')
        mask = mask.convert('L')
        if image.size != mask.size:
            raise ValueError('Source painting and coast mask dimensions differ')
        alpha = island_alpha(mask, args.dilation, args.feather, args.threshold)
        image.putalpha(Image.fromarray(alpha))
        land = np.asarray(mask) > 127
        far = [(0, 0), (image.width - 1, 0), (0, image.height - 1),
               (image.width - 1, image.height - 1), (image.width - 1, image.height // 2)]
        far = [(x, y) for x, y in far if mask.getpixel((x, y)) < 128]
        if alpha[land].min() < 250 or not far or max(alpha[y, x] for x, y in far) != 0:
            raise ValueError('World alpha does not keep land opaque and far sea clear')
        error = atlas.verify_coast(image, mask, 'world')
        if error > .0035:
            raise ValueError(f'World painting no longer matches its coast mask: {error:.2%}')
        args.out.parent.mkdir(parents=True, exist_ok=True)
        image.save(args.out, optimize=True)
        record = dict(kind='island-alpha-atlas-painting', bounds=original['bounds'], labels_baked=False,
                      geography=atlas.geography_signature(), prompt=original['prompt'],
                      requested_model=original.get('requested_model'), quality=original.get('quality'),
                      output_sha256=hashlib.sha256(args.out.read_bytes()).hexdigest(),
                      generation=original,
                      display=dict(kind='island-alpha-from-signed-coast',
                                   mask_sha256=hashlib.sha256(args.mask.read_bytes()).hexdigest(),
                                   alpha_sha256=hashlib.sha256(alpha.tobytes()).hexdigest(),
                                   dilation_pixels=args.dilation, feather_pixels=args.feather,
                                   alpha_threshold=args.threshold, coast_error=error,
                                   land_alpha_min=int(alpha[land].min()),
                                   far_sea_sample_alpha_max=int(max(alpha[y, x] for x, y in far)),
                                   changed_rgb=False))
        args.out_record.write_text(json.dumps(record, indent=2) + '\n')
        print(f'World alpha: {args.out}; coast error {error:.3%}; land opaque; far sea clear', flush=True)


if __name__ == '__main__':
    main()
