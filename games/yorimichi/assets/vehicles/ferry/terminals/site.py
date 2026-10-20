"""Ferry berths and manoeuvres at Hidamari and Brinecove, checked by sweeping ship C's hull along each manoeuvre
against the harbours' exported geometry.

uv run python games/yorimichi/assets/vehicles/ferry/terminals/site.py
Reads build/yorimichi/ferry/terminals/world_<harbour>.npz (world_probe.py: the ground and solid triangles of the
exported world around each berth, with the sha256 of every file they came from) and writes site.json and site_*.png
there. site.json records the sha256 of both probes and of this file; build.py refuses a site.json whose inputs changed.

Two envelopes, both from build.py's hull lines:
- the full plan outline above water (the widest half-width over every waterline, plus 0.4 m for the rubbing
  strake, davits and fittings), swept against every exported solid: quays, piers, the breakwater, moored boats,
  ships, rocks and props. While moving it must keep STRUCTURE_CLEARANCE from all of them. Alongside (within 3 m of
  onto or off the berth (the 'berth' crab that ends or starts each manoeuvre) only the berth's own structure, inside
  its berth zone, may come closer, and the outline still must not touch it;
- the underwater footprint (the half-width at the waterline, z 0, from stern_x(0) to stem_x(0)), swept against the
  exported seabed: it must stay at least KEEL_CLEARANCE (plus DESIGN_MARGIN) below the 2.6 m keel.
Each manoeuvre is a list of moves: ahead/astern along the heading, crab (sideways on thrusters) and pivot (turn on
the spot). Every pose along it is checked every half metre / degree. Hidamari is in world metres; Brinecove is in its
region-local export frame (world = local + (-1500, -120)).
"""
import hashlib
import importlib.util
import json
import math
import sys
import types
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
OUT = REPO / 'build/yorimichi/ferry/terminals'


def _ship():
    """The ship's build.py, whose hull lines are plain functions; outside Blender bpy and mathutils are stubbed."""
    if 'ferry_build' in sys.modules:
        return sys.modules['ferry_build']
    if 'bpy' not in sys.modules:
        sys.modules['bpy'] = types.ModuleType('bpy')
        mu = sys.modules.setdefault('mathutils', types.ModuleType('mathutils')); mu.Matrix = mu.Vector = object
    spec = importlib.util.spec_from_file_location('ferry_build', HERE.parent / 'build.py')
    mod = importlib.util.module_from_spec(spec); sys.modules['ferry_build'] = mod; spec.loader.exec_module(mod)
    return mod


ship = _ship()

DRAFT = -ship.Z_BOTTOM
KEEL_CLEARANCE = 0.5
DESIGN_MARGIN = 0.2                             # for between-sample extrema of the exported seabed
SEABED_MAX = -(DRAFT + KEEL_CLEARANCE + DESIGN_MARGIN)   # the seabed limit under the underwater footprint
STRUCTURE_CLEARANCE = 4.0                       # metres the full outline keeps from every solid while manoeuvring
FENDER = 0.6                                    # hull side to berth face, alongside
SHIP_TOP = 30.0                                 # above the masthead: solids up to here can meet the ship
GATE_X, GATE_W = ship.GATES[0]
SILL_Z = ship.deck_z(GATE_X)
CELL = 0.25
BOUNDS = {'hidamari': (700.0, -330.0, 1000.0, -110.0), 'brinecove': (-460.0, -260.0, -100.0, 70.0)}


def outline(full):
    """Ship-local plan outline (x forward, y port) as a closed polygon."""
    if full:
        x0, x1 = ship.STERN, ship.STEM
        zs = np.linspace(ship.Z_BOTTOM, ship.deck_z(ship.STEM), 60)
        hw = lambda x: max(ship.half_width(x, z) for z in zs) + 0.4
    else:
        x0, x1 = ship.stern_x(0.0), ship.stem_x(0.0)
        hw = lambda x: ship.half_width(x, 0.0)
    xs = np.linspace(x0, x1, 161)
    side = [(x, hw(x)) for x in xs]
    return np.array(side + [(x, -y) for x, y in reversed(side)])


FULL, WET = outline(True), outline(False)
ENV = {id(FULL): (FULL[:161, 0], FULL[:161, 1]), id(WET): (WET[:161, 0], WET[:161, 1])}


def place(poly, x, y, heading):
    c, s = math.cos(heading), math.sin(heading)
    return np.c_[x + poly[:, 0] * c - poly[:, 1] * s, y + poly[:, 0] * s + poly[:, 1] * c]


def poses(start, moves):
    """start (x, y, heading deg; heading 0 = east, 90 = north). Moves: ('ahead', m) (negative = astern),
    ('crab', m) (positive = to port), ('berth', m) (a crab onto or off the berth), ('pivot', deg) (positive = to port), ('arc', radius, deg) (ahead, port +),
    ('move', dx, dy) (a world-frame glide on engines and thrusters, heading held)."""
    x, y, h = start[0], start[1], math.radians(start[2])
    out = [(x, y, h, 'start')]
    for mv in moves:
        kind = mv[0]
        if kind in ('ahead', 'crab', 'berth'):
            d = mv[1]; n = max(1, int(abs(d) / 0.5))
            ux, uy = (math.cos(h), math.sin(h)) if kind == 'ahead' else (-math.sin(h), math.cos(h))
            for k in range(1, n + 1):
                out.append((x + ux * d * k / n, y + uy * d * k / n, h, kind))
            x, y = out[-1][:2]
        elif kind == 'move':
            n = max(1, int(math.hypot(mv[1], mv[2]) / 0.5))
            for k in range(1, n + 1):
                out.append((x + mv[1] * k / n, y + mv[2] * k / n, h, kind))
            x, y = out[-1][:2]
        elif kind == 'pivot':
            n = max(1, int(abs(mv[1]))); h0 = h
            for k in range(1, n + 1):
                out.append((x, y, h0 + math.radians(mv[1]) * k / n, kind))
            h = out[-1][2]
        elif kind == 'arc':
            R, deg = mv[1], mv[2]; sgn = 1 if deg > 0 else -1
            cx, cy = x - sgn * R * math.sin(h), y + sgn * R * math.cos(h)
            n = max(1, int(abs(R * math.radians(deg)) / 0.5)); h0 = h
            for k in range(1, n + 1):
                hk = h0 + math.radians(deg) * k / n
                out.append((cx + sgn * R * math.sin(hk), cy - sgn * R * math.cos(hk), hk, kind))
            x, y, h = out[-1][:3]
        else:
            raise ValueError(kind)
    return out


class Grid:
    def __init__(self, x0, y0, x1, y1):
        self.x0, self.y0 = x0, y0
        self.nx, self.ny = int(round((x1 - x0) / CELL)), int(round((y1 - y0) / CELL))
        self.X = x0 + (np.arange(self.nx) + 0.5) * CELL
        self.Y = y0 + (np.arange(self.ny) + 0.5) * CELL

    def mask(self):
        return np.zeros((self.ny, self.nx), bool)

    def fill_poly(self, m, poly):
        """Cells whose centre lies inside the polygon."""
        poly = np.asarray(poly, float)
        i0 = max(0, int((poly[:, 0].min() - self.x0) / CELL)); i1 = min(self.nx, int((poly[:, 0].max() - self.x0) / CELL) + 2)
        j0 = max(0, int((poly[:, 1].min() - self.y0) / CELL)); j1 = min(self.ny, int((poly[:, 1].max() - self.y0) / CELL) + 2)
        if i0 >= i1 or j0 >= j1:
            return
        px, py = np.meshgrid(self.X[i0:i1], self.Y[j0:j1])
        inside = np.zeros(px.shape, bool)
        xa, ya = poly[:, 0], poly[:, 1]; xb, yb = np.roll(xa, -1), np.roll(ya, -1)
        for a, b, c, d in zip(xa, ya, xb, yb):
            if b == d:
                continue
            cross = ((b > py) != (d > py)) & (px < a + (py - b) * (c - a) / (d - b))
            inside ^= cross
        m[j0:j1, i0:i1] |= inside

    def ship(self, m, poly, x, y, h):
        """Fill a ship outline at a pose: cells whose ship-local |y| is within the half-width at their local x."""
        xs, hw = ENV[id(poly)]
        R = math.hypot(max(abs(xs[0]), abs(xs[-1])), hw.max())
        i0 = max(0, int((x - R - self.x0) / CELL)); i1 = min(self.nx, int((x + R - self.x0) / CELL) + 2)
        j0 = max(0, int((y - R - self.y0) / CELL)); j1 = min(self.ny, int((y + R - self.y0) / CELL) + 2)
        if i0 >= i1 or j0 >= j1:
            return
        px, py = np.meshgrid(self.X[i0:i1] - x, self.Y[j0:j1] - y)
        c, s = math.cos(h), math.sin(h)
        lx, ly = px * c + py * s, -px * s + py * c
        inside = (lx >= xs[0]) & (lx <= xs[-1]) & (np.abs(ly) <= np.interp(lx, xs, hw))
        m[j0:j1, i0:i1] |= inside

    # ---- rasterising exported triangles
    def _centres_in(self, tris, fn):
        """For every triangle and every cell centre inside it in plan, call fn(triangle indices, j, i, u, v, w)."""
        if not len(tris):
            return
        lo, hi = tris[:, :, :2].min(1), tris[:, :, :2].max(1)
        i0 = np.clip(np.ceil((lo[:, 0] - self.x0) / CELL - 0.5).astype(int), 0, self.nx)
        i1 = np.clip(np.floor((hi[:, 0] - self.x0) / CELL - 0.5).astype(int) + 1, 0, self.nx)
        j0 = np.clip(np.ceil((lo[:, 1] - self.y0) / CELL - 0.5).astype(int), 0, self.ny)
        j1 = np.clip(np.floor((hi[:, 1] - self.y0) / CELL - 0.5).astype(int) + 1, 0, self.ny)
        ni, nj = i1 - i0, j1 - j0
        live = (ni > 0) & (nj > 0)
        K = 8                                     # small triangles in one vectorised pass, large ones one at a time
        small = live & (ni <= K) & (nj <= K)
        for idx in (np.nonzero(small)[0], ):
            if not len(idx):
                continue
            di, dj = np.meshgrid(np.arange(K), np.arange(K))
            I = i0[idx, None] + di.ravel()[None]; J = j0[idx, None] + dj.ravel()[None]
            ok = (I < i1[idx, None]) & (J < j1[idx, None])
            T = np.repeat(idx, K * K).reshape(len(idx), K * K)[ok]; I, J = I[ok], J[ok]
            self._bary(tris, T, J, I, fn)
        for t in np.nonzero(live & ~small)[0]:
            J, I = np.meshgrid(np.arange(j0[t], j1[t]), np.arange(i0[t], i1[t]), indexing='ij')
            self._bary(tris, np.full(J.size, t), J.ravel(), I.ravel(), fn)

    def _bary(self, tris, T, J, I, fn):
        a, b, c = tris[T, 0], tris[T, 1], tris[T, 2]
        px, py = self.X[I], self.Y[J]
        d = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
        good = np.abs(d) > 1e-12
        d = np.where(good, d, 1.0)
        u = ((b[:, 1] - c[:, 1]) * (px - c[:, 0]) + (c[:, 0] - b[:, 0]) * (py - c[:, 1])) / d
        v = ((c[:, 1] - a[:, 1]) * (px - c[:, 0]) + (a[:, 0] - c[:, 0]) * (py - c[:, 1])) / d
        w = 1 - u - v
        e = -1e-9
        inside = good & (u >= e) & (v >= e) & (w >= e)
        fn(T[inside], J[inside], I[inside], u[inside], v[inside], w[inside])

    def surface_max(self, tris, zmax=np.inf):
        """Per cell, the highest surface (interpolated at the cell centre) no higher than zmax; NaN where none."""
        z = np.full((self.ny, self.nx), -np.inf)

        def put(T, J, I, u, v, w):
            zz = u * tris[T, 0, 2] + v * tris[T, 1, 2] + w * tris[T, 2, 2]
            keep = zz <= zmax
            np.maximum.at(z, (J[keep], I[keep]), zz[keep])
        self._centres_in(tris, put)
        return np.where(np.isfinite(z), z, np.nan)

    def cover(self, tris, labels=None, nlabels=1):
        """Every cell a triangle meets in plan: cells holding a point of one of its edges (sampled at a quarter cell)
        or whose centre lies inside it. Returns one mask per label."""
        out = np.zeros((nlabels, self.ny, self.nx), bool)
        if not len(tris):
            return out
        labels = np.zeros(len(tris), int) if labels is None else np.asarray(labels, int)
        for k in range(3):
            a, b = tris[:, k, :2], tris[:, (k + 1) % 3, :2]
            n = np.maximum(1, np.ceil(np.hypot(*(b - a).T) / (CELL / 4)).astype(int))
            T = np.repeat(np.arange(len(tris)), n + 1)
            t = np.concatenate([np.linspace(0, 1, m + 1) for m in n])
            p = a[T] + (b[T] - a[T]) * t[:, None]
            I = np.floor((p[:, 0] - self.x0) / CELL).astype(int); J = np.floor((p[:, 1] - self.y0) / CELL).astype(int)
            ok = (I >= 0) & (I < self.nx) & (J >= 0) & (J < self.ny)
            out[labels[T[ok]], J[ok], I[ok]] = True

        def put(T, J, I, u, v, w):
            out[labels[T], J, I] = True
        self._centres_in(tris, put)
        return out


def distance(m, limit):
    """Approximate distance (metres) from every cell to the nearest True cell, up to limit (8-neighbour chamfer).
    Cells inside a True cell are 0, so an outline cell on a solid cell reports overlap."""
    INF = 1e9
    d = np.where(m, 0.0, INF)
    steps = int(limit / CELL) + 1
    for _ in range(steps):
        p = np.pad(d, 1, constant_values=INF)
        nb = [p[1:-1, :-2], p[1:-1, 2:], p[:-2, 1:-1], p[2:, 1:-1]]
        dg = [p[:-2, :-2], p[:-2, 2:], p[2:, :-2], p[2:, 2:]]
        d = np.minimum.reduce([d] + [a + CELL for a in nb] + [a + CELL * 1.4142 for a in dg])
    return np.minimum(d, limit)


class Harbour:
    """One harbour's rasters: exported seabed, exported solids (by label), plus the berth's own structure, which
    is the authored terminal deck (not in the world yet) and every exported solid inside the berth zone."""

    def __init__(self, name, world, berth, berth_zone, terminal):
        self.name, self.berth, self.terminal = name, berth, terminal
        self.g = Grid(*world['bounds'])
        self.z = self.g.surface_max(world['ground'])
        self.misses = int(np.isnan(self.z).sum())
        self.z = np.where(np.isnan(self.z), np.inf, self.z)           # no exported ground: never safe water, so a
        #                                                               swept cell there fails as grounding
        masks = self.g.cover(world['solid'], world['solid_label'], len(world['labels']))
        zone = self.g.cover(np.array([[(*berth_zone[0], 0.0), (*a, 0.0), (*b, 0.0)]          # conservative, as the solids
                                      for a, b in zip(berth_zone[1:], berth_zone[2:])]))[0]
        own = self.g.mask()
        for poly in terminal:
            self.g.fill_poly(own, poly)
        self.labels = [(lab, m & ~zone) for lab, m in zip(world['labels'], masks)] + [('ferry terminal', own)]
        solid = masks.any(0)
        self.berth_solid = (solid & zone) | own
        self.other = solid & ~zone
        self.land = self.z > 0.0
        self.shallow = self.z > SEABED_MAX
        self.d_other = distance(self.other | self.land, 12.0)
        self.d_berth = distance(self.berth_solid, 12.0)

    def check(self, label, start, moves):
        """Sweep both envelopes. The outline keeps STRUCTURE_CLEARANCE from every solid and from land; on the berthing
        crab (and alongside at its end) it keeps it from all but the berth's own structure, and must not touch that."""
        ps = poses(start, moves)
        swept, wet = self.g.mask(), self.g.mask()
        worst, worst_alongside, berth_gap, grounded, hits = 99.0, 99.0, 99.0, [], []
        berthing = [k == 'berth' or (k == 'start' and i + 1 < len(ps) and ps[i + 1][3] == 'berth') or
                    (i > 0 and ps[i - 1][3] == 'berth' and k == 'berth') for i, (_, _, _, k) in enumerate(ps)]
        for (x, y, h, kind), alongside in zip(ps, berthing):
            m = self.g.mask(); self.g.ship(m, FULL, x, y, h)
            w = self.g.mask(); self.g.ship(w, WET, x, y, h)
            swept |= m; wet |= w
            other = float(self.d_other[m].min()) if m.any() else 99.0
            berth = float(self.d_berth[m].min()) if m.any() else 99.0
            pose = (round(x, 1), round(y, 1), round(math.degrees(h), 1), kind)
            if alongside:
                worst_alongside = min(worst_alongside, other); berth_gap = min(berth_gap, berth)
                if other < STRUCTURE_CLEARANCE or berth <= 0.0:
                    hits.append(pose + (round(other, 2), round(berth, 2)))
            else:
                clear = min(other, berth); worst = min(worst, clear)
                if clear < STRUCTURE_CLEARANCE:
                    hits.append(pose + (round(other, 2), round(berth, 2)))
            if (w & self.shallow).any():
                grounded.append(pose + (round(float(self.z[w].max()), 2),))
        ds = distance(swept, 30.0)
        near = {}
        for lab, m in self.labels:
            if m.any():
                near[lab] = min(near.get(lab, 99.0), round(float(ds[m].min()), 2))
        result = {'manoeuvre': label, 'poses': len(ps), 'min_structure_clearance_m': round(worst, 2),
                  'alongside_min_clearance_m': round(worst_alongside, 2), 'alongside_berth_gap_m': round(berth_gap, 2),
                  'structure_conflicts': hits[:20], 'conflict_count': len(hits), 'grounding_poses': grounded[:20],
                  'grounding_count': len(grounded), 'deepest_seabed_under_keel_m': round(float(self.z[wet].max()), 2),
                  'swept_cells_without_ground': int(np.isinf(self.z[wet]).sum()),
                  'nearest_by_obstacle_m': dict(sorted(near.items(), key=lambda kv: kv[1])[:8]),
                  'path': [[round(x, 2), round(y, 2), round(math.degrees(h), 1)] for x, y, h, _ in ps[::8]] +
                  [[round(ps[-1][0], 2), round(ps[-1][1], 2), round(math.degrees(ps[-1][2]), 1)]]}
        result['pass'] = not hits and not grounded
        return result, swept, ps, wet

    def draw(self, path, results, title):
        from PIL import Image, ImageDraw, ImageFont
        S = 2  # px per cell -> 8 px/m
        g = self.g
        img = np.zeros((g.ny, g.nx, 3), np.uint8)
        depth = np.clip(-np.where(np.isfinite(self.z), self.z, 0.0) / 20.0, 0, 1)
        img[...] = (np.stack([70 - 40 * depth, 150 - 60 * depth, 200 - 40 * depth], -1)).astype(np.uint8)
        img[self.shallow & ~self.land] = (150, 200, 210)
        img[self.land] = (214, 205, 180)
        img[self.other] = (150, 110, 80)
        img[self.berth_solid] = (200, 70, 60)
        colours = [(255, 210, 60), (255, 120, 90), (120, 255, 140), (220, 120, 255)]
        for k, (_, swept, ps) in enumerate(results):
            c = np.array(colours[k % len(colours)])
            img[swept] = (0.55 * img[swept] + 0.45 * c).astype(np.uint8)
        im = Image.fromarray(img[::-1]).resize((g.nx * S // 2, g.ny * S // 2), Image.NEAREST)
        d = ImageDraw.Draw(im)
        P = lambda x, y: ((x - g.x0) / CELL * S / 2, (g.ny - (y - g.y0) / CELL) * S / 2)
        for k, (res, swept, ps) in enumerate(results):
            c = colours[k % len(colours)]
            d.line([P(x, y) for x, y, _, _ in ps], fill=c, width=2)
            for x, y, h, _ in ps[::60] + [ps[-1]]:
                d.polygon([P(*p) for p in place(FULL, x, y, h)], outline=c)
        bx, by, bh = self.berth
        d.polygon([P(*p) for p in place(FULL, bx, by, math.radians(bh))], outline=(20, 40, 120), width=3)
        try:
            f = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 14)
        except OSError:
            f = ImageFont.load_default()
        head = 8 + 18 * (len(results) + 1)
        full = Image.new('RGB', (im.width, im.height + head), (255, 255, 255)); full.paste(im, (0, head)); im = full
        d = ImageDraw.Draw(im)
        y = 6
        d.text((8, y), title, fill=(0, 0, 0), font=f)
        for k, (res, _, _) in enumerate(results):
            y += 18
            d.text((8, y), '%s: %s, min clearance %.2f m (rule %.1f), alongside %.2f m, seabed under keel max %.2f m (limit %.1f)' % (
                res['manoeuvre'], 'PASS' if res['pass'] else 'FAIL', res['min_structure_clearance_m'], STRUCTURE_CLEARANCE,
                res['alongside_min_clearance_m'], res['deepest_seabed_under_keel_m'], SEABED_MAX),
                fill=colours[k % len(colours)] if res['pass'] else (200, 0, 0), font=f)
            d.rectangle((im.width - 30, y + 2, im.width - 16, y + 14), fill=colours[k % len(colours)])
        im.save(path)


def gate_point(pose, side):
    """World position of the boarding opening on the given side (+1 port, -1 starboard) at a ship pose."""
    x, y, h = pose; h = math.radians(h)
    lx, ly = GATE_X, side * ship.deck_half(GATE_X)
    return (x + lx * math.cos(h) - ly * math.sin(h), y + lx * math.sin(h) + ly * math.cos(h))


def berth_offshore(g, z, x, heading, y_from, step=-0.1):
    """The first berth y (moving offshore from y_from) whose underwater footprint clears the exported seabed."""
    y = y_from
    while y > g.y0:
        w = g.mask(); g.ship(w, WET, x, y, math.radians(heading))
        if z[w].max() <= SEABED_MAX:
            return round(y, 1)
        y += step
    raise ValueError('no berth clears the seabed')


def levels(world, pts, zmax):
    """Exported walking surfaces (ground or solid) under plan points: the highest surface no higher than zmax."""
    tris = np.concatenate([world['ground'], world['solid']])
    xs, ys = np.asarray(pts, float).T
    g = Grid(xs.min() - CELL, ys.min() - CELL, xs.max() + CELL, ys.max() + CELL)
    z = g.surface_max(tris, zmax)
    i = np.clip(((xs - g.x0) / CELL).astype(int), 0, g.nx - 1); j = np.clip(((ys - g.y0) / CELL).astype(int), 0, g.ny - 1)
    return z[j, i]


def world_cut(what, x, y, z_from):
    """A piece of the exported world that the ferry's world change (B3) removes, as data both the terminal walk audit
    and the world change read from site.json: every triangle whose plan lies within the band y, meets the span x and
    starts no lower than z_from. Whole posts standing in the coping go with the rail; the coping and the wall, wider
    than the band or reaching lower, stay."""
    return {'what': what, 'x': [round(x[0], 3), round(x[1], 3)], 'y': [round(y[0], 3), round(y[1], 3)], 'z_from': round(z_from, 3)}


def cut_mask(tris, cut):
    """Triangles (n, 3, 3) that a world_cut removes."""
    lo, hi = tris.min(1), tris.max(1)
    return ((hi[:, 0] >= cut['x'][0]) & (lo[:, 0] <= cut['x'][1]) & (lo[:, 1] >= cut['y'][0]) & (hi[:, 1] <= cut['y'][1])
            & (lo[:, 2] >= cut['z_from']))


def rect_points(x0, y0, x1, y1, step=0.5):
    X, Y = np.meshgrid(np.arange(x0 + step / 2, x1, step), np.arange(y0 + step / 2, y1, step))
    return np.c_[X.ravel(), Y.ravel()]


# ---------------------------------------------------------------- Hidamari (world metres)
HIDAMARI_X = 855.0                    # berth centre x: the jetty clears the canal mouth (x 840-856 stays open at the quay)
HIDAMARI_QUAY_FACE = -127.7           # quay coping outer face (hidamari/build.py harbor(): 3.4 m coping on y -126)
HIDAMARI_PIVOT = (872.0, -190.0)      # deep water inside the mouth, clear of the workboats and the headland shelf
HIDAMARI_STANDOFF = -156.0            # the glide line off the berth
HIDAMARI_TIMETABLE_DX = -6.5         # the timetable board, west of the jetty axis on the quay
QUAY_RAIL = 2.9                       # quay surfaces sit below the timber rail (posts 2.45-3.55)


def hidamari_layout(world):
    """Berth, gate, jetty and the walk levels it stands on, from the exported seabed and quay."""
    g = Grid(*world['bounds']); z = g.surface_max(world['ground'])
    z = np.where(np.isnan(z), np.inf, z)
    cy = berth_offshore(g, z, HIDAMARI_X, 180.0, HIDAMARI_QUAY_FACE - FENDER - ship.BEAM)
    face_y = cy + ship.BEAM + FENDER     # jetty fender face; the hull side is FENDER outside it
    berth = (HIDAMARI_X, cy, 180.0)      # bow west; starboard side to the jetty
    gx, gy = gate_point(berth, -1)
    jetty = [(gx - 8.0, HIDAMARI_QUAY_FACE), (gx + 8.0, HIDAMARI_QUAY_FACE), (gx + 8.0, face_y), (gx - 8.0, face_y)]
    quay = levels(world, rect_points(gx - 8, HIDAMARI_QUAY_FACE + 0.1, gx + 8, HIDAMARI_QUAY_FACE + 3.3), QUAY_RAIL)
    house = levels(world, rect_points(gx - 21.3, -122.3, gx - 8.7, -114.2, 0.25), QUAY_RAIL + 0.5)   # the plinth
    q = float(np.nanmedian(quay))
    # The waiting house's door (south wall, 1.2-2.2 m from its west end) steps down to the quay; the timetable board
    # stands on the quay west of the jetty root (x 840-856 east of it is the canal mouth, water at the quay).
    door = levels(world, rect_points(gx - 21.0 + 1.0, -123.0, gx - 21.0 + 2.4, -122.3, 0.2), QUAY_RAIL + 0.5)
    tx, ty = gx + HIDAMARI_TIMETABLE_DX, -122.5
    board = levels(world, rect_points(tx - 1.5, ty - 0.3, tx + 1.5, ty + 0.3, 0.2), QUAY_RAIL + 0.5)
    for what, zs in (('waiting house door step', door), ('timetable board', board)):
        if np.isnan(zs).any():
            raise ValueError(f'Hidamari {what}: no exported surface under part of its footprint')
    # The jetty root crosses the quay's timber rail (posts 2.45-3.55, top beam 3.5): B3 cuts it over the jetty's width.
    cuts = [world_cut("the quay's timber rail and posts across the jetty root", (gx - 8.0, gx + 8.0), (-126.3, -125.7),
                      q - 0.1)]
    walk = {'world_cuts': cuts, 'quay_top_z': round(q, 3), 'quay_top_range': [round(float(np.nanmin(quay)), 3), round(float(np.nanmax(quay)), 3)],
            'promenade_z': round(float(np.nanmax(house)), 3), 'promenade_range': [round(float(np.nanmin(house)), 3), round(float(np.nanmax(house)), 3)],
            'waiting_house': [gx - 21.0, -122.0, gx - 9.0, -114.5], 'door_ground_z': round(float(np.nanmin(door)), 3),
            'timetable': [round(tx, 3), ty, round(float(np.nanmax(board)), 3)],
            'timetable_ground_range': [round(float(np.nanmin(board)), 3), round(float(np.nanmax(board)), 3)]}
    zone = jetty
    return berth, (gx, gy), jetty, face_y, zone, walk


def hidamari_moves(berth):
    bx, by, _ = berth
    px, py = HIDAMARI_PIVOT
    # Arrival: in through the harbour mouth heading north, stop in deep water, pivot to port onto west, glide
    # north-west to the stand-off line, then crab onto the fenders. Departure is the same in reverse.
    arrive = (px, -290.0, 90.0)
    arrival = [('ahead', py + 290.0), ('pivot', 90.0), ('move', bx - px, HIDAMARI_STANDOFF - py), ('berth', -(by - HIDAMARI_STANDOFF))]
    departure = [('berth', by - HIDAMARI_STANDOFF), ('move', px - bx, py - HIDAMARI_STANDOFF), ('pivot', 90.0), ('ahead', py + 290.0)]
    return (arrive, arrival), (berth, departure)


# ---------------------------------------------------------------- Brinecove (region-local metres)
BRINECOVE_PIER = (-238.0, 13.0)       # west pier centre x and width (brinecove/layout.py PIERS)
BRINECOVE_BERTH_Y = 10.0
BRINECOVE_LANE = 4.0                  # the arrival's first leg runs this far west of the berth line, east of the rowboat
                                      # moored at (-270, -145)
BRINECOVE_JOG_Y = -95.0               # once the stern has passed that rowboat, the ship glides west...
BRINECOVE_STANDOFF = 13.0             # ...to this line west of the berth, clear of the rowboat moored at (-250, -40)
BRINECOVE_CRAB = 40.0                 # west of the berth, a 180-degree pivot clears the west pier by its full radius


def brinecove_layout(world):
    px, pw = BRINECOVE_PIER
    face_x = px - pw / 2 - 0.5            # fender piles on the pier's west face
    cx = face_x - FENDER - ship.BEAM
    berth = (cx, BRINECOVE_BERTH_Y, 90.0)  # bow north; starboard (east) side to the pier
    gx, gy = gate_point(berth, -1)
    landing = [(face_x, gy - 3.6), (face_x + 3.4, gy - 3.6), (face_x + 3.4, gy + 3.6), (face_x, gy + 3.6)]
    # The berth is the pier's west face along the hull: fender piles, pier deck edge and its piles.
    half = (ship.STEM - ship.STERN) / 2 + 4.0
    zone = [(face_x - 0.05, BRINECOVE_BERTH_Y - half), (px + pw / 2, BRINECOVE_BERTH_Y - half),
            (px + pw / 2, BRINECOVE_BERTH_Y + half), (face_x - 0.05, BRINECOVE_BERTH_Y + half)]
    deck = levels(world, rect_points(face_x + 0.6, gy - 12.0, face_x + 12.5, gy + 18.0), 5.6)
    walk = {'world_cuts': [], 'pier_deck_z': round(float(np.nanmedian(deck)), 3), 'pier_deck_range': [round(float(np.nanmin(deck)), 3), round(float(np.nanmax(deck)), 3)]}
    return berth, (gx, gy), landing, face_x, zone, walk


def brinecove_moves(berth):
    bx, by, _ = berth
    # Arrival: up the channel west of the west pier, bow north, between the two moored rowboats: east of the one at
    # (-270, -145), then a glide west to pass west of the one at (-250, -40), then crab east onto the fenders.
    arrival_start = (bx - BRINECOVE_LANE, -250.0, 90.0)
    arrival = [('ahead', BRINECOVE_JOG_Y + 250.0), ('move', BRINECOVE_LANE - BRINECOVE_STANDOFF, 0.0),
               ('ahead', by - BRINECOVE_JOG_Y), ('berth', -BRINECOVE_STANDOFF)]
    # Departure: crab off to port (west) into the open basin until a pivot clears the pier, turn on the spot to south,
    # then ahead out of the bay.
    departure = [('berth', BRINECOVE_STANDOFF), ('crab', BRINECOVE_CRAB - BRINECOVE_STANDOFF), ('pivot', 180.0), ('ahead', 260.0)]
    return (arrival_start, arrival), (berth, departure)


# ---------------------------------------------------------------- inputs
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_world(name, out=OUT):
    """world_<name>.npz from world_probe.py."""
    path = out / f'world_{name}.npz'
    with np.load(path) as f:
        meta = json.loads(str(f['meta']))
        return {'ground': f['ground'].astype(float), 'solid': f['solid'].astype(float), 'solid_label': f['solid_label'],
                'labels': meta['labels'], 'bounds': tuple(meta['bounds']), 'meta': meta, 'path': path}


def inputs(worlds):
    """What site.json was computed from: both probes (which carry their own export hashes) and the code."""
    return {'world_probes': {n: sha(w['path']) for n, w in worlds.items()},
            'exports': {n: w['meta']['sources'] for n, w in worlds.items()},
            'code': {p.name: sha(p) for p in (HERE / 'site.py', HERE.parent / 'build.py')}}


def stale_inputs(report, out=OUT):
    """Inputs recorded in site.json that no longer match the files on disk (empty when site.json is current)."""
    rec = report.get('inputs') or {}
    bad = [f'world_{n}.npz' for n, h in (rec.get('world_probes') or {}).items()
           if not (out / f'world_{n}.npz').exists() or sha(out / f'world_{n}.npz') != h]
    bad += [name for name, h in (rec.get('code') or {}).items()
            if sha(HERE / name if name == 'site.py' else HERE.parent / name) != h]
    return bad if rec else ['no inputs recorded']


def main(argv=None):
    worlds = {n: load_world(n) for n in ('hidamari', 'brinecove')}
    report = {'ship': {'length': round(FULL[:, 0].max() - FULL[:, 0].min(), 2), 'outline_half_beam': round(FULL[:, 1].max(), 2),
                       'draft': DRAFT, 'keel_clearance': KEEL_CLEARANCE, 'design_margin': DESIGN_MARGIN,
                       'seabed_limit': round(SEABED_MAX, 3), 'sill_z': round(SILL_Z, 3), 'gate_x': GATE_X,
                       'gate_width': GATE_W, 'structure_clearance': STRUCTURE_CLEARANCE,
                       'fender_gap': FENDER},
              'inputs': inputs(worlds)}
    ok = True
    for name, layout, moves in (('hidamari', hidamari_layout, hidamari_moves), ('brinecove', brinecove_layout, brinecove_moves)):
        world = worlds[name]
        berth, gate, deck, face, zone, walk = layout(world)
        hb = Harbour(name.title(), world, berth, zone, [deck])
        (a0, am), (d0, dm) = moves(berth)
        ra = hb.check('arrival', a0, am)
        rd = hb.check('departure', d0, dm)
        ok &= ra[0]['pass'] and rd[0]['pass']        # a swept cell with no exported ground counts as grounding
        report[name] = {'berth': {'centre': [round(berth[0], 2), round(berth[1], 2)], 'heading_deg': berth[2],
                                  'gate': [round(gate[0], 2), round(gate[1], 2), round(SILL_Z, 3)], 'face': round(face, 2),
                                  'terminal_deck': [[round(a, 2), round(b, 2)] for a, b in deck],
                                  'berth_zone': [[round(a, 2), round(b, 2)] for a, b in zone], **walk},
                        'frame': world['meta']['frame'], 'seabed_cells_without_ground': hb.misses,
                        'arrival': ra[0], 'departure': rd[0]}
        OUT.mkdir(parents=True, exist_ok=True)
        hb.draw(OUT / f'site_{name}.png', [ra[:3], rd[:3]], f'{hb.name}: ship C arrival / departure swept path (4 px/m)')
        print(name, 'berth', report[name]['berth'])
        for r in (ra[0], rd[0]):
            print(' ', r['manoeuvre'], 'PASS' if r['pass'] else 'FAIL', 'clearance', r['min_structure_clearance_m'],
                  'alongside', r['alongside_min_clearance_m'], 'berth gap', r['alongside_berth_gap_m'],
                  'conflicts', r['conflict_count'], r['structure_conflicts'][:3], 'grounding', r['grounding_count'],
                  r['grounding_poses'][:3], 'nearest', r['nearest_by_obstacle_m'])
    report['pass'] = bool(ok)
    (OUT / 'site.json').write_text(json.dumps(report, indent=1) + '\n')
    print('SITE', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
