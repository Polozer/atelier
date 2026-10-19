"""Register an authored Momiji beach strip to its signed terrain coastline.

This explicit authoring tool makes no paid calls. It preserves generated RGB
outside the narrow strip, including expanded road/settlement and pier anchors.
Production builds validate and stage the committed painting normally.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageDraw

import atlas

SIZE = (1536, 1024)
PIER = (645, 735, 935, 980)


def register(image, mask):
    """@cc [owner:fontanierh,label:correctness] coast-strip-preserves-anchors
    Registration MUST preserve every pixel outside its bounded coast strip,
    every pier pixel and the road/settlement anchor. It MUST reject an invalid
    frame, missing ocean profile, excessive change or failing signed coast check.
    """
    if image.size != SIZE or mask.size != SIZE:
        raise ValueError('Momiji strip registration requires its exact 1536x1024 frame')
    original = np.asarray(image.convert('RGB'))
    water = Image.fromarray(atlas.water_pixels(image).astype('uint8')).copy()
    if not water.getpixel((0, SIZE[1]-1)):
        raise ValueError('Source must have connected ocean at the bottom-left edge')
    ImageDraw.floodfill(water, (0, SIZE[1]-1), 2)
    ocean = np.asarray(water) == 2
    reference = np.asarray(mask.convert('L')) < 128
    profiles = []
    for raster in (ocean, reference):
        profile = []
        for x in range(SIZE[0]):
            rows = np.flatnonzero(raster[400:, x])
            if not len(rows):
                raise ValueError('Source/reference has no complete ocean profile')
            profile.append(rows[0]+400)
        profile = np.asarray(profile, dtype=float)
        # Interpolate the ordinary shore behind the separately protected pier.
        profile[645:935] = np.interp(np.arange(645, 935), [644, 935], [profile[644], profile[935]])
        profiles.append(profile)
    candidate = original.copy()
    allowed = np.zeros((SIZE[1], SIZE[0]), dtype=bool)
    for x, (source, target) in enumerate(zip(*profiles)):
        if abs(source-target) < 1:
            continue
        upper = max(400, int(min(source, target)-24))
        lower = min(SIZE[1]-1, int(max(source, target)+24))
        if not upper < min(source, target)-8 < max(source, target)+8 < lower:
            raise ValueError('Coast profile leaves insufficient registration margin')
        ys = np.arange(upper, lower+1)
        mapped = np.interp(ys, [upper, target-8, target+8, lower], [upper, source-8, source+8, lower])
        dry = ys < target-8
        mapped[dry] = ys[dry]-(target-source)
        if mapped.min() < 0 or mapped.max() >= SIZE[1]:
            raise ValueError('Registration would sample outside the source frame')
        lo = np.floor(mapped).astype(int)
        hi = np.minimum(lo+1, SIZE[1]-1)
        weight = (mapped-lo)[:, None]
        shifted = original[lo, x]*(1-weight)+original[hi, x]*weight
        blend = np.ones(len(ys))
        blend[dry] = .5-.5*np.cos(np.pi*np.clip((ys[dry]-upper)/24, 0, 1))
        candidate[ys, x] = np.rint(original[ys, x]*(1-blend[:, None])+shifted*blend[:, None]).astype('uint8')
        allowed[ys, x] = True
    left, top, right, bottom = PIER
    candidate[top:bottom, left:right] = original[top:bottom, left:right]
    allowed[top:bottom, left:right] = False
    candidate[:700, 500:] = original[:700, 500:]
    allowed[:700, 500:] = False
    changed = np.any(candidate != original, axis=2)
    if changed[~allowed].any() or changed[:400].any() or changed[:700, 500:].any():
        raise ValueError('Registration changed protected terrain/route pixels')
    if not np.array_equal(candidate[top:bottom, left:right], original[top:bottom, left:right]):
        raise ValueError('Registration changed the protected pier')
    if changed.mean() >= .08:
        raise ValueError('Coastal correction exceeds its eight-percent bound')
    image = Image.fromarray(candidate)
    error = atlas.verify_coast(image, mask, 'momiji_coast')
    return image, dict(kind='bounded-coast-strip-registration', changed_pixels=int(changed.sum()),
                      changed_fraction=float(changed.mean()), protected_pier=list(PIER),
                      input_size=list(SIZE), output_size=list(SIZE),
                      source_rgb_sha256=hashlib.sha256(original.tobytes()).hexdigest(),
                      output_rgb_sha256=hashlib.sha256(candidate.tobytes()).hexdigest(),
                      allowed_mask_shape=list(allowed.shape),
                      allowed_mask_sha256=hashlib.sha256(np.packbits(allowed).tobytes()).hexdigest(),
                      all_outside_strip_unchanged=True, all_pier_pixels_unchanged=True,
                      all_road_hamlet_pixels_unchanged=True, coast_error=error)


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'record', 'mask', 'out', 'out-record'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists() or args.out_record.exists():
        raise FileExistsError('Preserve existing paintings and receipts')
    manifest_path = atlas.ASSETS / 'coasts/source.json'
    paths = (args.source, args.record, args.mask, manifest_path, Path(__file__))
    snapshots = {path: path.read_bytes() for path in paths}
    geography = atlas.geography_signature()
    original = json.loads(snapshots[args.record])
    source_sha = hashlib.sha256(snapshots[args.source]).hexdigest()
    bounds = next(r['bounds'] for r in atlas.REGIONS if r['key'] == 'momiji_coast')
    if original.get('bounds') != bounds or original.get('labels_baked', True):
        raise ValueError('Source has the wrong frame or baked labels')
    if original.get('output_sha256') != source_sha or original.get('geography') != geography:
        raise ValueError('Source bytes/geography differ from their receipt')
    if args.mask.resolve() != (atlas.ASSETS / 'coasts/momiji_coast.png').resolve():
        raise ValueError('Use the authoritative signed Momiji coast mask')
    manifest = json.loads(snapshots[manifest_path])
    frame = manifest['frames']['momiji_coast']
    mask_sha = hashlib.sha256(snapshots[args.mask]).hexdigest()
    if manifest['geography'] != geography or frame['bounds'] != bounds or frame['sha256'] != mask_sha:
        raise ValueError('Coast reference geography/frame/bytes differ')
    reference_sha = frame.get('reference_sha256', '')
    if len(reference_sha) != 64 or any(c not in '0123456789abcdef' for c in reference_sha):
        raise ValueError('Signed coast has no valid reference-image witness')
    bindings = {}
    for item in original.get('inputs', []):
        role = item.get('role') if isinstance(item, dict) else None
        if role in ('exact geography', 'exact coast mask'):
            if role in bindings:
                raise ValueError('Generation receipt has duplicate exact input bindings')
            bindings[role] = item.get('sha256')
    if bindings != {'exact geography': reference_sha, 'exact coast mask': mask_sha}:
        raise ValueError('Generation input plan/mask bindings differ from the signed reference')
    with Image.open(io.BytesIO(snapshots[args.source])) as image, Image.open(io.BytesIO(snapshots[args.mask])) as mask:
        output, correction = register(image, mask)
    buffer = io.BytesIO()
    output.save(buffer, format='PNG', optimize=True)
    blob = buffer.getvalue()
    correction.update(source_sha256=source_sha, mask_sha256=mask_sha, reference_sha256=reference_sha,
                      helper_sha256=hashlib.sha256(snapshots[Path(__file__)]).hexdigest())
    record = dict(bounds=bounds, labels_baked=False, geography=geography, generation=original,
                  output_sha256=hashlib.sha256(blob).hexdigest(), correction=correction)
    if atlas.geography_signature() != geography or any(path.read_bytes() != data for path, data in snapshots.items()):
        raise ValueError('Input/source/geography drifted during registration; nothing published')
    # The receipt publishes last and certifies a complete hash-bound PNG. An
    # interrupted PNG-only publication remains unaccepted and cannot overwrite.
    publish(args.out, blob)
    publish(args.out_record, (json.dumps(record, indent=2)+'\n').encode())
    print(json.dumps(correction), flush=True)


if __name__ == '__main__':
    main()
