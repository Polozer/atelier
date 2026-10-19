"""Register painted land from one signed atlas frame into another.

Deterministic, unpaid authoring for a new landmass that an older painting does
not show yet. The donor's painted land is resampled through the two frames'
exact world rectangles and composited only where both signed masks say land,
inside one declared world rectangle. A short feather hides the coast seam.
Every pixel outside the rectangle stays byte-identical, and the correction is
recorded as a hash-bound addition beside the original generation receipt.
"""
import argparse
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

import atlas


def sha(data):
    return hashlib.sha256(data).hexdigest()


def publish(path, data):
    """Publish complete bytes atomically without replacing an existing artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def pixel_box(rect, bounds, size):
    """Frame pixels covering one world rectangle, expanded to whole pixels."""
    x0, y0, x1, y1 = rect
    w, h = size
    px0 = int(np.floor((x0 - bounds[0]) / (bounds[2] - bounds[0]) * w))
    px1 = int(np.ceil((x1 - bounds[0]) / (bounds[2] - bounds[0]) * w))
    py0 = int(np.floor((bounds[3] - y1) / (bounds[3] - bounds[1]) * h))
    py1 = int(np.ceil((bounds[3] - y0) / (bounds[3] - bounds[1]) * h))
    if not (0 <= px0 < px1 <= w and 0 <= py0 < py1 <= h):
        raise ValueError('World rectangle must lie inside both frames')
    return px0, py0, px1, py1


def world_grid(box, bounds, size):
    """World coordinates of the target pixel centres in a pixel box."""
    px0, py0, px1, py1 = box
    w, h = size
    xs = bounds[0] + (np.arange(px0, px1) + .5) / w * (bounds[2] - bounds[0])
    ys = bounds[3] - (np.arange(py0, py1) + .5) / h * (bounds[3] - bounds[1])
    return np.meshgrid(xs, ys)


def donor_pixels(xs, ys, bounds, size):
    """Float donor pixel coordinates of world points, in pixel-centre space."""
    w, h = size
    dx = (xs - bounds[0]) / (bounds[2] - bounds[0]) * w - .5
    dy = (bounds[3] - ys) / (bounds[3] - bounds[1]) * h - .5
    return dx, dy


def sample(array, xs, ys):
    """Bilinear sample of an HxWxC array at float pixel coordinates."""
    h, w = array.shape[:2]
    x0 = np.floor(xs).astype(int)
    y0 = np.floor(ys).astype(int)
    fx = (xs - x0)[..., None]
    fy = (ys - y0)[..., None]
    x0 = np.clip(x0, 0, w - 1)
    y0 = np.clip(y0, 0, h - 1)
    x1 = np.clip(x0 + 1, 0, w - 1)
    y1 = np.clip(y0 + 1, 0, h - 1)
    return (array[y0, x0] * (1 - fx) * (1 - fy) + array[y0, x1] * fx * (1 - fy)
            + array[y1, x0] * (1 - fx) * fy + array[y1, x1] * fx * fy)


def near_land(array, xs, ys):
    h, w = array.shape[:2]
    return array[np.clip(np.rint(ys).astype(int), 0, h - 1), np.clip(np.rint(xs).astype(int), 0, w - 1)] > 127


def register(target, target_mask, donor, donor_mask, target_bounds, donor_bounds, rect, feather, fill_missing=False):
    target_rgb = np.asarray(target.convert('RGB'))
    donor_rgb = np.asarray(donor.convert('RGB'))
    target_land_all = np.asarray(target_mask.convert('L'))
    donor_land_all = np.asarray(donor_mask.convert('L'))
    box = pixel_box(rect, target_bounds, target.size)
    xs, ys = world_grid(box, target_bounds, target.size)
    dx, dy = donor_pixels(xs, ys, donor_bounds, donor.size)
    px0, py0, px1, py1 = box
    donor_rgb_sample = sample(donor_rgb.astype(np.float32), dx, dy)
    land = (target_land_all[py0:py1, px0:px1] > 127) & near_land(donor_land_all, dx, dy)
    if fill_missing:
        target_water = atlas.water_pixels(target)[py0:py1, px0:px1]
        land &= target_water
    if not land.any():
        raise ValueError('The rectangle contains no land shared by both signed masks')
    seed = Image.fromarray((land * 255).astype('uint8'))
    alpha = np.asarray(seed.filter(ImageFilter.GaussianBlur(feather / 2))).astype(np.float32) / 255
    alpha = np.clip(alpha * 2 - 1, 0, 1)
    alpha[~land] = 0
    target_sub = target_rgb[py0:py1, px0:px1].astype(np.float32)
    blended = target_sub * (1 - alpha[..., None]) + donor_rgb_sample * alpha[..., None]
    output = target_rgb.copy()
    output[py0:py1, px0:px1] = np.clip(blended, 0, 255).astype(np.uint8)
    changed = (output != target_rgb).any(axis=2)
    if changed[py0:py1, px0:px1].sum() != changed.sum():
        raise ValueError('Registration changed pixels outside its rectangle')
    if not changed.any():
        raise ValueError('Registration changed nothing; check the donor and rectangle')
    return Image.fromarray(output), box, int(changed.sum()), int((alpha > 0).sum())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('target', 'target-record', 'target-mask', 'donor', 'donor-record', 'donor-mask', 'out', 'out-record'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--key', required=True, help='target region key in atlas.REGIONS')
    parser.add_argument('--donor-key', required=True, help='donor frame key in the coast manifest')
    parser.add_argument('--rect', type=float, nargs=4, required=True, metavar=('X0', 'Y0', 'X1', 'Y1'),
                        help='world rectangle in metres containing every changed pixel')
    parser.add_argument('--feather', type=int, default=2, help='coast seam feather in pixels')
    parser.add_argument('--fill-missing', action='store_true',
                        help='composite only where the target mask is land but its painting is water')
    args = parser.parse_args()
    if args.out.exists() or args.out_record.exists():
        raise FileExistsError('Preserve existing paintings and receipts before a new revision')
    if args.feather < 0 or args.feather > 8:
        raise ValueError('Feather must stay between 0 and 8 pixels')
    paths = (args.target, args.target_record, args.target_mask, args.donor, args.donor_record,
             args.donor_mask, atlas.ASSETS / 'coasts' / 'source.json', Path(__file__))
    snapshots = {path: path.read_bytes() for path in paths}
    geography = atlas.geography_signature()
    manifest = json.loads(snapshots[atlas.ASSETS / 'coasts' / 'source.json'])
    if manifest.get('geography') != geography:
        raise ValueError('Coast reference is stale for the current geography')
    target_record = json.loads(snapshots[args.target_record])
    donor_record = json.loads(snapshots[args.donor_record])
    target_sha = sha(snapshots[args.target])
    donor_sha = sha(snapshots[args.donor])
    for record, name, data_sha in ((target_record, 'target', target_sha), (donor_record, 'donor', donor_sha)):
        if record.get('output_sha256') != data_sha:
            raise ValueError(f'{name} painting bytes differ from their receipt')
        if record.get('labels_baked', True):
            raise ValueError(f'{name} painting contains baked labels')
    target_frame = (manifest.get('frames') or {}).get(args.key) or {}
    donor_frame = (manifest.get('frames') or {}).get(args.donor_key) or {}
    if target_record.get('bounds') != target_frame.get('bounds') or sha(snapshots[args.target_mask]) != target_frame.get('sha256'):
        raise ValueError('Target record or mask differs from the signed frame')
    if donor_record.get('bounds') != donor_frame.get('bounds') or sha(snapshots[args.donor_mask]) != donor_frame.get('sha256'):
        raise ValueError('Donor record or mask differs from the signed frame')
    with Image.open(args.target) as target, Image.open(args.target_mask) as target_mask, \
            Image.open(args.donor) as donor, Image.open(args.donor_mask) as donor_mask:
        atlas.verify_coast(donor, donor_mask, args.donor_key)
        result, box, changed, alpha_pixels = register(
            target, target_mask, donor, donor_mask, target_frame['bounds'], donor_frame['bounds'],
            args.rect, args.feather, args.fill_missing)
    with Image.open(args.target_mask) as target_mask:
        after = atlas.verify_coast(result, target_mask, args.key)
    buffer = io.BytesIO()
    result.save(buffer, format='PNG', optimize=True)
    blob = buffer.getvalue()
    record = dict(target_record)
    record['output_sha256'] = sha(blob)
    record.pop('verified_geography', None)
    record['correction'] = dict(
        kind='signed-donor-land-registration', donor=args.donor_key, donor_sha256=donor_sha,
        donor_record_sha256=sha(snapshots[args.donor_record]), donor_mask_sha256=sha(snapshots[args.donor_mask]),
        target_mask_sha256=sha(snapshots[args.target_mask]), rect=[float(v) for v in args.rect],
        feather=args.feather, box=list(box), changed_pixels=changed, alpha_pixels=alpha_pixels,
        fill_missing=bool(args.fill_missing), coast_error=after, helper_sha256=sha(snapshots[Path(__file__)]))
    if atlas.geography_signature() != geography or any(path.read_bytes() != data for path, data in snapshots.items()):
        raise ValueError('Input/source/geography drifted during registration; nothing published')
    publish(args.out, blob)
    publish(args.out_record, (json.dumps(record, indent=2) + '\n').encode())
    print(json.dumps(dict(changed=changed, alpha_pixels=alpha_pixels, box=box, coast_error=after)), flush=True)


if __name__ == '__main__':
    main()
