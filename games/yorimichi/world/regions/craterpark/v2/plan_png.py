"""Top-down plan of the generated park for the owner's page (numpy + pillow; native metres, x right, z down).

Height-shaded (the top surface's height, hill-shaded from the north-west), feature outlines (where the top face's
feature changes), riding lines, air arcs (lip to touchdown, bowed by the air's height so they read as flights) and the
validators' failure locations (red rings, numbered as in geometry-report.json).
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

LINE_COLOURS = [(233, 94, 47), (40, 120, 220), (30, 160, 90), (170, 70, 200), (220, 170, 20), (20, 170, 180)]
MAX_PX = 2400        # the longer side of the image at most, in pixels


def top_raster(T, feature, box, px, budget=4_000_000):
    """The highest face over each pixel centre: (height (h,w) NaN where empty, feature id (h,w) -1 where empty)."""
    x0, z0, x1, z1 = box
    w = int(math.ceil((x1 - x0) / px)); h = int(math.ceil((z1 - z0) / px))
    H = np.full(h * w, -np.inf); Fid = np.full(h * w, -1, 'i8')
    P = T[:, :, [0, 2]]
    e1 = P[:, 1] - P[:, 0]; e2 = P[:, 2] - P[:, 0]
    det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    keep = np.abs(det) > 1e-12                                   # vertical faces have no plan area
    c0 = np.clip(np.floor((P[:, :, 0].min(1) - x0) / px - .5).astype('i8'), 0, w - 1)
    c1 = np.clip(np.ceil((P[:, :, 0].max(1) - x0) / px - .5).astype('i8'), 0, w - 1)
    r0 = np.clip(np.floor((P[:, :, 1].min(1) - z0) / px - .5).astype('i8'), 0, h - 1)
    r1 = np.clip(np.ceil((P[:, :, 1].max(1) - z0) / px - .5).astype('i8'), 0, h - 1)
    inside = keep & (P[:, :, 0].max(1) >= x0) & (P[:, :, 0].min(1) <= x1) & (P[:, :, 1].max(1) >= z0) & (P[:, :, 1].min(1) <= z1)
    f = np.flatnonzero(inside)
    nc = (c1 - c0 + 1)[f]; nr = (r1 - r0 + 1)[f]; cnt = nc * nr
    cum = np.cumsum(cnt)
    if not len(cum):
        return H.reshape(h, w) * np.nan, Fid.reshape(h, w)
    cuts = np.unique(np.r_[0, np.searchsorted(cum, np.arange(budget, cum[-1], budget)), len(f)])
    for a, b in zip(cuts[:-1], cuts[1:]):
        k = cnt[a:b]
        if not k.sum():
            continue
        fi = np.repeat(f[a:b], k)
        loc = np.arange(k.sum()) - np.repeat(np.cumsum(k) - k, k)
        cc = c0[fi] + loc % np.repeat(nc[a:b], k); rr = r0[fi] + loc // np.repeat(nc[a:b], k)
        qx = x0 + (cc + .5) * px - P[fi, 0, 0]; qz = z0 + (rr + .5) * px - P[fi, 0, 1]
        u = (qx * e2[fi, 1] - qz * e2[fi, 0]) / det[fi]; v = (e1[fi, 0] * qz - e1[fi, 1] * qx) / det[fi]
        ok = (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
        y = T[fi, 0, 1] + u * (T[fi, 1, 1] - T[fi, 0, 1]) + v * (T[fi, 2, 1] - T[fi, 0, 1])
        idx = (rr * w + cc)[ok]; y = y[ok]; fi = fi[ok]
        o = np.lexsort((y, idx))                                  # per pixel, the highest last
        idx, y, fi = idx[o], y[o], fi[o]
        last = np.r_[idx[1:] != idx[:-1], True]
        idx, y, fi = idx[last], y[last], fi[last]
        better = y > H[idx]
        H[idx[better]] = y[better]; Fid[idx[better]] = feature[fi[better]]
    H[~np.isfinite(H)] = np.nan
    return H.reshape(h, w), Fid.reshape(h, w)


def _palette(t):
    """Height colours: low teal-grey through warm sand to pale concrete (t in [0, 1])."""
    stops = np.array([[0., 70, 96, 110], [.35, 120, 150, 140], [.65, 214, 190, 150], [1., 246, 238, 224]])
    out = np.empty(t.shape + (3,))
    for c in range(3):
        out[..., c] = np.interp(t, stops[:, 0], stops[:, c + 1])
    return out


def shade(H, px):
    """RGB (h,w,3) uint8: height colours times a north-west hill shade; empty pixels light grey."""
    empty = np.isnan(H)
    lo, hi = (np.nanmin(H), np.nanmax(H)) if (~empty).any() else (0., 1.)
    Hf = np.where(empty, lo, H)
    gz, gx = np.gradient(Hf, px)
    n = np.stack([-gx, np.ones_like(gx), -gz], -1); n /= np.linalg.norm(n, axis=-1, keepdims=True)
    light = np.array([-.5, .75, -.45]); light /= np.linalg.norm(light)
    lam = np.clip(n @ light, 0, 1)
    rgb = _palette((Hf - lo) / max(hi - lo, 1e-9)) * (.45 + .55 * lam)[..., None]
    rgb[empty] = (232, 232, 228)
    return np.clip(rgb, 0, 255).astype('u1'), (float(lo), float(hi))


def render_plan(meshes, out, lanes=(), airs=(), report=None, box=None, px=None, title='Crater Park v2 plan',
                pad=4., line_of=None):
    """Write the plan PNG. meshes: validate.Mesh (render ones are drawn). lanes: validate.Lane. airs: dicts with
    'lip' (x, y, z), 'land' (x, y, z), optional 'apex' (height of the flight's top, native y) and 'label'.
    report: geometry-report.json's dict, whose failure locations are ringed. line_of: {feature id: line index} colours
    the outlines by line. Returns (path, metres per pixel, box)."""
    from .validate import as_mesh
    meshes = [as_mesh(m) for m in meshes]
    ren = [m for m in meshes if m.domain == 'render'] or meshes
    T = np.concatenate([m.T for m in ren]) if ren else np.zeros((0, 3, 3))
    feat = np.concatenate([m.feature for m in ren]) if ren else np.zeros(0, 'i8')
    if box is None:
        lo = T.reshape(-1, 3).min(0); hi = T.reshape(-1, 3).max(0)
        box = (lo[0] - pad, lo[2] - pad, hi[0] + pad, hi[2] + pad)
    x0, z0, x1, z1 = box
    if px is None:
        px = max((x1 - x0), (z1 - z0)) / MAX_PX
        px = max(px, .05)
    H, Fid = top_raster(T, feat, box, px)
    rgb, (ylo, yhi) = shade(H, px)
    # feature outlines: a pixel whose right or lower neighbour has another top feature
    edge = np.zeros(Fid.shape, bool)
    edge[:, :-1] |= Fid[:, :-1] != Fid[:, 1:]; edge[:-1] |= Fid[:-1] != Fid[1:]
    edge &= ~np.isnan(H)
    col = np.full(Fid.shape + (3,), 40, 'u1')
    if line_of:
        for fid, li in line_of.items():
            col[Fid == fid] = LINE_COLOURS[li % len(LINE_COLOURS)]
    rgb[edge] = (.35 * rgb[edge] + .65 * col[edge]).astype('u1')
    margin = 60
    img = Image.new('RGB', (rgb.shape[1], rgb.shape[0] + margin), (250, 250, 247))
    img.paste(Image.fromarray(rgb), (0, margin))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:                                             # pillow < 10.1
        font = ImageFont.load_default()
    to = lambda x, z: ((x - x0) / px, (z - z0) / px + margin)
    for k, lane in enumerate(lanes):
        c = LINE_COLOURS[k % len(LINE_COLOURS)]
        pts = [to(x, z) for x, z in np.asarray(lane.path)]
        if len(pts) > 1:
            d.line(pts, fill=c, width=max(2, int(.6 / px)))
            # an arrow head at the end, along the last segment
            (ax, az), (bx, bz) = pts[-2], pts[-1]
            ang = math.atan2(bz - az, bx - ax); s = max(8, 2. / px)
            d.polygon([(bx, bz), (bx - s * math.cos(ang - .4), bz - s * math.sin(ang - .4)),
                       (bx - s * math.cos(ang + .4), bz - s * math.sin(ang + .4))], fill=c)
            d.text((pts[0][0] + 6, pts[0][1] + 6), lane.name, fill=c, font=font)
    for a in airs:
        lip, land = np.asarray(a['lip'], 'f8'), np.asarray(a['land'], 'f8')
        p0, p1 = np.array(to(lip[0], lip[2])), np.array(to(land[0], land[2]))
        v = p1 - p0; L = np.linalg.norm(v)
        if L < 1:
            continue
        nrm = np.array([-v[1], v[0]]) / L
        rise = float(a.get('apex', max(lip[1], land[1])) - max(lip[1], land[1]))
        bow = min(.25 * L, (abs(rise) + 1.) / px)
        pts = [tuple(p0 + v * t + nrm * bow * 4 * t * (1 - t)) for t in np.linspace(0, 1, 33)]
        for i in range(0, 32, 2):                                 # dashed
            d.line([pts[i], pts[i + 1]], fill=(20, 20, 20), width=3)
        d.ellipse([p0[0] - 4, p0[1] - 4, p0[0] + 4, p0[1] + 4], fill=(20, 20, 20))
        d.ellipse([p1[0] - 5, p1[1] - 5, p1[0] + 5, p1[1] + 5], outline=(20, 20, 20), width=2)
        gap = float(np.linalg.norm((land - lip)[[0, 2]]))
        label = a.get('label') or f'{gap:.0f} m air'
        mid = pts[16]
        d.text((mid[0] + 6, mid[1] - 8), f'{label}  (drop {lip[1] - land[1]:+.1f} m)', fill=(20, 20, 20), font=font)
    n = 0
    if report:
        for name, chk in report.get('checks', {}).items():
            for f in chk.get('failures', []) or []:
                w = f.get('where')
                if not w or w[0] is None or len(w) < 3:
                    continue
                n += 1
                x, z = to(w[0], w[2])
                r = 9
                d.ellipse([x - r, z - r, x + r, z + r], outline=(220, 20, 20), width=3)
                if n <= 99:
                    d.text((x + r + 2, z - r), f'{n} {name}', fill=(200, 10, 10), font=font)
    # header: title, height scale, metre bar, axes
    d.text((10, 8), title, fill=(20, 20, 20), font=font)
    sw = min(240, img.width // 4)
    bar = _palette(np.linspace(0, 1, sw))
    for i in range(sw):
        d.line([(10 + i, 32), (10 + i, 46)], fill=tuple(int(c) for c in bar[i]))
    d.text((14 + sw, 31), f'{ylo:.1f} m to {yhi:.1f} m', fill=(20, 20, 20), font=font)
    ten = 10. / px
    bx = img.width - ten - 20
    d.line([(bx, 40), (bx + ten, 40)], fill=(20, 20, 20), width=3)
    d.text((bx, 18), '10 m', fill=(20, 20, 20), font=font)
    d.text((bx - 140, 18), 'x right, z down', fill=(90, 90, 90), font=font)
    if n:
        d.text((10 + sw + 200, 31), f'{n} failure locations ringed', fill=(200, 10, 10), font=font)
    img.save(out)
    return out, px, box
