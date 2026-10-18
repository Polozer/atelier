"""Register a small painted shore overshoot using its own Sunburst sea texture.

Like repaint_island.py's registration/composition step, this is deterministic
geographic registration after a ledgered paint call, never another paid call.
Only reference WATER pixels may change: every real land/landmark pixel is kept.
A missing-land or oversized correction must be repainted, not hidden here.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import atlas


def register(source, record, mask_path, water_box, target):
    original = json.loads(record.read_text())
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    if original['output_sha256'] != source_sha or original.get('labels_baked', True):
        raise ValueError('Source painting provenance differs')
    if original['geography'] != atlas.geography_signature():
        raise ValueError('Source painting geography differs')
    with Image.open(source) as image, Image.open(mask_path) as mask:
        image = image.convert('RGB')
        if image.size != mask.size:
            raise ValueError('Source and terrain mask dimensions differ')
        a = np.array(image)
        ocean = np.asarray(mask.convert('L')) < 128
        # Leave authored inland pools alone. Register only reference water
        # connected to the frame edge, including its real harbours/canals.
        connected = Image.fromarray(ocean.astype('uint8')).copy()
        pixels = connected.load()
        for x, y in ([(x, y) for x in range(image.width) for y in (0, image.height-1)] +
                     [(x, y) for y in range(image.height) for x in (0, image.width-1)]):
            if pixels[x, y] == 1:
                ImageDraw.floodfill(connected, (x, y), 2)
        ocean = np.asarray(connected) == 2
        painted_water = atlas.water_pixels(image)
        bad = ocean & ~painted_water
        core = (np.asarray(Image.fromarray((bad*255).astype('uint8')).filter(ImageFilter.MaxFilter(7))) > 127) & ocean
        alpha = core.astype(float)
        grown = core
        # Start the feather at full opacity; forcing a blurred binary core to
        # one would create a half-opacity jump on the first surrounding row.
        for distance in range(1, 9):
            expanded = (np.asarray(Image.fromarray((grown*255).astype('uint8')).filter(ImageFilter.MaxFilter(3))) > 127) & ocean
            alpha[expanded & ~grown] = .5+.5*np.cos(np.pi*distance/9.)
            grown = expanded
        alpha[~ocean] = 0.
        edit = alpha > 0.
        if edit.mean() > .03:
            raise ValueError('More than 3% needs shore registration; repaint the source')
        patch = image.crop(water_box)
        if patch.width < 32 or patch.height < 32 or not atlas.water_pixels(patch).all():
            raise ValueError('Registration requires a verified open-water texture patch')
        # Match colour locally, rather than tinting a whole rectangular strip
        # with one mean. Exclude bright shore foam from the colour extension.
        samples = ocean & painted_water & (a[:, :, 0] < 20)
        weights = np.asarray(Image.fromarray((samples*255).astype('uint8')).filter(ImageFilter.GaussianBlur(24)), dtype=float)/255.
        colours = np.asarray(Image.fromarray(a*samples[:, :, None]).filter(ImageFilter.GaussianBlur(24)), dtype=float)
        if (weights[edit] <= 0.).any():
            raise ValueError('No nearby open-water colour for the correction')
        field = colours/np.maximum(weights[:, :, None], 1./255.)
        sea = np.asarray(patch, dtype=float)-np.asarray(patch.filter(ImageFilter.GaussianBlur(6)), dtype=float)
        y, x = np.nonzero(edit)
        if len(y):
            # Preserve world-x texture continuity; tile only the small sea strip.
            texture = np.clip(field[y, x]+.4*sea[(y-y.min()) % patch.height, (x-water_box[0]) % patch.width], 0, 255)
            a[y, x] = np.rint(a[y, x]*(1-alpha[y, x, None])+texture*alpha[y, x, None]).astype('uint8')
        result = Image.fromarray(a)
        atlas.verify_coast(result, mask, source.stem)
        original_pixels = np.asarray(image)
        changed = (a != original_pixels).any(-1)
        if changed[~edit].any() or changed[~ocean].any():
            raise ValueError('Registration moved pixels outside reference water')
        if target.exists() or target.with_suffix('.json').exists():
            raise FileExistsError('Preserve an existing registration rather than overwriting it')
        target.parent.mkdir(parents=True, exist_ok=True)
        result.save(target, optimize=True)
    output = dict(kind='registered-sunburst-painting', bounds=original['bounds'], labels_baked=False,
                  geography=atlas.geography_signature(), requested_model=original['requested_model'], quality=original['quality'],
                  prompt=original['prompt'], output_sha256=hashlib.sha256(target.read_bytes()).hexdigest(), generation=original,
                  registration=dict(method='water-only-local-sea-colour-v4', source_sha256=source_sha,
                                    mask_sha256=hashlib.sha256(mask_path.read_bytes()).hexdigest(), water_texture_box=list(water_box),
                                    local_colour_radius=24, texture_detail_weight=.4, feather_pixels=8,
                                    changed_pixels=int(changed.sum()), changed_fraction=float(changed.mean()),
                                    outside_edit_identical=True, all_reference_land_identical=True))
    target.with_suffix('.json').write_text(json.dumps(output, indent=2)+'\n')
    print(f'Registered {source.stem}: {changed.sum()} water pixels; every real land/landmark pixel unchanged', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--mask', type=Path, required=True)
    parser.add_argument('--water-box', type=int, nargs=4, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    register(args.source, args.source.with_suffix('.json'), args.mask, tuple(args.water_box), args.out)


if __name__ == '__main__':
    main()
