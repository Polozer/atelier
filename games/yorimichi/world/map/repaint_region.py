"""Repaint one region rectangle of a larger atlas painting from its plan.

Bounded replacement of a redesigned area: the parent painting outside the
region rectangle stays byte-identical. The region plan is the authoritative
geometry, the signed region mask guides the shoreline, and the previous
painting is style only. One ledgered Sunburst call; registration is
deterministic and unpaid, and records a hash-bound correction beside the
original generation receipt.
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
import paint_atlas
from register_region_land import pixel_box, publish, sha


def prepare(args):
    record = json.loads(args.parent_record.read_text())
    painting_sha = sha(args.parent.read_bytes())
    if record.get('output_sha256') != painting_sha:
        raise ValueError('Parent painting bytes differ from their receipt')
    bounds = next(r['bounds'] for r in atlas.REGIONS if r['key'] == args.key)
    plan = args.references / args.key / 'rough.png'
    info = json.loads((plan.parent / 'map.json').read_text())
    if info['bounds'] != bounds:
        raise ValueError('Reference plan does not use the production region frame')
    with Image.open(plan) as plan_image, Image.open(args.parent) as parent, Image.open(args.mask) as mask:
        if plan_image.size != mask.size:
            raise ValueError('Plan and signed mask dimensions differ')
        crop = pixel_box(bounds, atlas.WORLD_BOUNDS, parent.size)
        parent_crop = parent.convert('RGB').crop(crop).resize(plan_image.size, Image.LANCZOS)
        parent_crop.save(args.work / 'parent.png')
        plan_image.convert('RGB').save(args.work / 'plan.png')
        mask.convert('L').save(args.work / 'mask.png')
    state = dict(key=args.key, bounds=bounds, world_bounds=atlas.WORLD_BOUNDS, crop=list(crop),
                 plan_sha256=sha((args.work / 'plan.png').read_bytes()),
                 parent_sha256=sha((args.work / 'parent.png').read_bytes()),
                 mask_sha256=sha((args.work / 'mask.png').read_bytes()),
                 signed_mask_sha256=sha(args.mask.read_bytes()),
                 parent_painting_sha256=painting_sha)
    (args.work / 'prepare.json').write_text(json.dumps(state, indent=2) + '\n')
    print('PREPARED', json.dumps(state), flush=True)


def paint(args):
    state = json.loads((args.work / 'prepare.json').read_text())
    target = args.work / 'painted.png'
    request = paint_atlas.prompt(state['key'])
    request = request.replace(
        'Image 2, if present, is ONLY a painterly style reference; ignore all its text, layout, symbols and geography.',
        'Image 2 is the authoritative coast mask. Image 3, if present, is ONLY a painterly style reference; ignore all its text, layout, symbols and geography.')
    request += '''\nSHORELINE CORRECTION: Image 2 is an authoritative binary terrain mask: WHITE is solid ground, BLACK is water. Match its silhouette at the exact same pixel positions; do not enlarge, shrink, recenter or rotate the land. Paint terrain only inside the white footprint. Surf is water, not extra dry ground. If image 3 is present, it is STYLE ONLY: its shoreline is older and must not be copied. The binary mask overrides all artistic interpretation of the coast.\n'''
    from atelier.ai.images import paint as call
    from atelier.env import load
    load()
    inputs = [args.work / 'plan.png', args.work / 'mask.png', args.work / 'parent.png']
    print('PAINT one Sunburst high call; no automatic retry', flush=True)
    result = call(target, request, '1536x1024', inputs, record=target.with_suffix('.json'),
                  metadata=dict(bounds=state['bounds'], labels_baked=False, geography=atlas.geography_signature(),
                                prompt=request, inputs=[
                                    dict(role='exact geography' if i == 0 else 'exact coast mask' if i == 1 else 'style only',
                                         sha256=sha(path.read_bytes())) for i, path in enumerate(inputs)]))
    print('DONE', result['output_sha256'], result['elapsed_seconds'], flush=True)


def register(args):
    state = json.loads((args.work / 'prepare.json').read_text())
    if sha((args.work / 'parent.png').read_bytes()) != state['parent_sha256']:
        raise ValueError('Parent crop changed since prepare')
    with Image.open(args.work / 'painted.png') as painted, \
            Image.open(args.parent) as parent, Image.open(args.parent_mask) as world_mask, \
            Image.open(args.work / 'plan.png') as plan:
        if plan.size != painted.size:
            raise ValueError('Painted frame differs from the prepared plan')
        crop = state['crop']
        x0, y0, x1, y1 = crop
        width, height = x1 - x0, y1 - y0
        parent_rgb = np.asarray(parent.convert('RGB'))
        crop_rgb = parent_rgb[y0:y1, x0:x1].astype(np.float32)
        painted_rgb = np.asarray(painted.convert('RGB').resize((width, height), Image.LANCZOS)).astype(np.float32)
        # Match the region sea to the plate sea in the margin ring outside the rectangle.
        pad = 20
        ring = np.zeros(parent_rgb.shape[:2], dtype=bool)
        ring[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad] = True
        ring[y0:y1, x0:x1] = False
        plate_sea = atlas.water_pixels(parent)
        region_sea = atlas.water_pixels(painted.resize((width, height), Image.LANCZOS))
        outside_sea = plate_sea & ring
        if outside_sea.sum() < 100 or region_sea.sum() < 100:
            raise ValueError('Not enough sea to match tones')
        offset = parent_rgb[outside_sea].mean(axis=0) - painted_rgb[region_sea].mean(axis=0)
        painted_rgb[region_sea] += offset
        feather = max(1, args.edge)
        alpha = np.ones((height, width), dtype=np.float32)
        ramp = np.minimum(np.arange(width) + .5, np.arange(width)[::-1] + .5)[None, :]
        ramp_y = np.minimum(np.arange(height) + .5, np.arange(height)[::-1] + .5)[:, None]
        alpha = np.minimum(np.minimum(ramp, ramp_y) / feather, 1.)
        blended = crop_rgb * (1 - alpha[..., None]) + np.clip(painted_rgb, 0, 255) * alpha[..., None]
        output = parent_rgb.copy()
        output[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)
        changed = (output != parent_rgb).any(axis=2)
        result = Image.fromarray(output)
        error = atlas.verify_coast(result, world_mask, 'world')
    if changed[y0:y1, x0:x1].sum() != changed.sum():
        raise ValueError('Registration changed pixels outside its rectangle')
    buffer = io.BytesIO()
    result.save(buffer, format='PNG', optimize=True)
    blob = buffer.getvalue()
    original = json.loads(args.parent_record.read_text())
    record = dict(original)
    record['output_sha256'] = sha(blob)
    record.pop('verified_geography', None)
    record['correction'] = dict(
        kind='bounded-region-repaint', key=state['key'], rect=[float(v) for v in state['bounds']],
        crop=list(crop), edge=args.edge, sea_offset=[round(float(v), 3) for v in offset],
        changed_pixels=int(changed.sum()), coast_error=error,
        painted_sha256=sha((args.work / 'painted.png').read_bytes()),
        painted_record_sha256=sha((args.work / 'painted.json').read_bytes()),
        plan_sha256=state['plan_sha256'], mask_sha256=state['signed_mask_sha256'],
        helper_sha256=sha(Path(__file__).read_bytes()))
    publish(args.out, blob)
    publish(args.out_record, (json.dumps(record, indent=2) + '\n').encode())
    print(json.dumps(dict(changed=int(changed.sum()), coast_error=error, sea_offset=record['correction']['sea_offset'])), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'paint', 'register'])
    parser.add_argument('--key', default='brinecove')
    parser.add_argument('--references', type=Path)
    parser.add_argument('--parent', type=Path)
    parser.add_argument('--parent-record', type=Path)
    parser.add_argument('--parent-mask', type=Path)
    parser.add_argument('--mask', type=Path)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--edge', type=int, default=6)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--out-record', type=Path)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    if args.stage == 'prepare':
        if (args.work / 'prepare.json').exists():
            raise FileExistsError('Prepare work already exists; preserve it')
        prepare(args)
    elif args.stage == 'paint':
        paint(args)
    else:
        if args.out.exists() or args.out_record.exists():
            raise FileExistsError('Preserve existing paintings and receipts')
        register(args)


if __name__ == '__main__':
    main()
