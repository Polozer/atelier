"""Ferry berths and manoeuvres at Hidamari and Brinecove, checked by sweeping ship C's hull along each manoeuvre.

uv run python games/yorimichi/assets/vehicles/ferry/terminals/site.py [--world-build PATH]

The seabed comes from the regions' own height functions, which read the built world (heightmap.npy); --world-build
points them at another checkout's build/yorimichi. Writes build/yorimichi/ferry/terminals/site.json and site_*.png.

Two envelopes, both from build.py's hull lines:
- the full plan outline above water (the widest half-width over every waterline, plus 0.4 m for the rubbing
  strake, davits and fittings), swept against land, quays, piers, the breakwater and moored boats;
- the underwater footprint (the half-width at the waterline, z 0, from stern_x(0) to stem_x(0)), swept against the
  seabed: it must stay at least KEEL_CLEARANCE below the 2.6 m keel.
Each manoeuvre is a list of moves: ahead/astern along the heading, crab (sideways on thrusters) and pivot (turn on
the spot). Every pose along it is checked every half metre / degree. Hidamari is in world metres; Brinecove is in its
region-local frame (world = local + (-1500, -120)).
"""
import argparse
import json
import math
import sys
import types
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
sys.modules.setdefault('bpy', types.ModuleType('bpy'))          # build.py's hull lines are plain functions
_mu = sys.modules.setdefault('mathutils', types.ModuleType('mathutils')); _mu.Matrix = _mu.Vector = object
sys.path.insert(0, str(HERE.parent))
import build as ship  # noqa: E402

DRAFT = -ship.Z_BOTTOM
KEEL_CLEARANCE = 0.5
DESIGN_MARGIN = 0.2                             # for the exported terrain's triangulation and between-sample extrema
SEABED_MAX = -(DRAFT + KEEL_CLEARANCE + DESIGN_MARGIN)   # the seabed limit under the underwater footprint
STRUCTURE_CLEARANCE = 2.0                       # metres the full outline keeps from anything solid while moving
FENDER = 0.6                                    # hull side to berth face, alongside
GATE_X, GATE_W = ship.GATES[0]
SILL_Z = ship.deck_z(GATE_X)
CELL = 0.25


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
    ('crab', m) (positive = to port), ('pivot', deg) (positive = to port), ('arc', radius, deg) (ahead, port +),
    ('move', dx, dy) (a world-frame glide on engines and thrusters, heading held)."""
    x, y, h = start[0], start[1], math.radians(start[2])
    out = [(x, y, h, 'start')]
    for mv in moves:
        kind = mv[0]
        if kind in ('ahead', 'crab'):
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
        self.nx, self.ny = int((x1 - x0) / CELL), int((y1 - y0) / CELL)
        self.X = x0 + (np.arange(self.nx) + 0.5) * CELL
        self.Y = y0 + (np.arange(self.ny) + 0.5) * CELL

    def mask(self):
        return np.zeros((self.ny, self.nx), bool)

    def fill_poly(self, m, poly):
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

    def rect(self, m, cx, cy, L, W, yaw_deg=0.0):
        c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
        pts = [(cx + a * c - b * s, cy + a * s + b * c) for a, b in ((-L / 2, -W / 2), (L / 2, -W / 2), (L / 2, W / 2), (-L / 2, W / 2))]
        self.fill_poly(m, pts)

    def segment(self, m, a, b, half):
        d = np.subtract(b, a); n = np.array([-d[1], d[0]]) / np.hypot(*d) * half
        self.fill_poly(m, [np.add(a, n), np.add(b, n), np.subtract(b, n), np.subtract(a, n)])

    def disc(self, m, cx, cy, r):
        self.fill_poly(m, [(cx + r * math.cos(t), cy + r * math.sin(t)) for t in np.linspace(0, 2 * math.pi, 24, endpoint=False)])

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

    def sample(self, fn):
        px, py = np.meshgrid(self.X, self.Y)
        return np.asarray(fn(px.ravel(), py.ravel()), float).reshape(px.shape)


def distance(m, limit):
    """Approximate distance (metres) from every cell to the nearest True cell, up to limit (8-neighbour chamfer)."""
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
    def __init__(self, name, bounds, seabed, solids, berth, terminal):
        self.name, self.berth, self.terminal = name, berth, terminal
        self.g = Grid(*bounds)
        self.z = self.g.sample(seabed)
        self.solid = self.g.mask()
        self.labels = []
        for label, kind, *args in solids:
            m = self.g.mask(); getattr(self.g, kind)(m, *args); self.solid |= m; self.labels.append((label, m))
        self.land = self.z > 0.0
        self.shallow = self.z > SEABED_MAX
        self.d_solid = distance(self.solid | self.land, 12.0)

    def check(self, label, start, moves, *, berth_pose=None):
        """Sweep both envelopes; poses within 3 m of the berth (alongside) may come within FENDER of the berth face."""
        ps = poses(start, moves)
        swept, wet = self.g.mask(), self.g.mask()
        worst, grounded, hits = 99.0, [], []
        for x, y, h, kind in ps:
            m = self.g.mask(); self.g.ship(m, FULL, x, y, h)
            w = self.g.mask(); self.g.ship(w, WET, x, y, h)
            swept |= m; wet |= w
            alongside = berth_pose is not None and math.hypot(x - berth_pose[0], y - berth_pose[1]) < 3.0 + 1e-6
            clear = float(self.d_solid[m].min()) if m.any() else 99.0
            if not alongside:
                worst = min(worst, clear)
                if clear < STRUCTURE_CLEARANCE:
                    hits.append((round(x, 1), round(y, 1), round(math.degrees(h), 1), kind, round(clear, 2)))
            if (w & self.shallow).any():
                grounded.append((round(x, 1), round(y, 1), round(math.degrees(h), 1), kind,
                                 round(float(self.z[w].max()), 2)))
        ds = distance(swept, 30.0)
        near = {}
        for lab, m in self.labels:
            if m.any():
                near[lab] = min(near.get(lab, 99.0), round(float(ds[m].min()), 2))
        result = {'manoeuvre': label, 'poses': len(ps), 'min_structure_clearance_m': round(worst, 2),
                  'structure_conflicts': hits[:20], 'conflict_count': len(hits), 'grounding_poses': grounded[:20],
                  'grounding_count': len(grounded), 'deepest_seabed_under_keel_m': round(float(self.z[wet].max()), 2),
                  'nearest_by_obstacle_m': near, 'path': [[round(x, 2), round(y, 2), round(math.degrees(h), 1)] for x, y, h, _ in ps[::8]] +
                  [[round(ps[-1][0], 2), round(ps[-1][1], 2), round(math.degrees(ps[-1][2]), 1)]]}
        result['pass'] = not hits and not grounded
        return result, swept, ps, wet

    def draw(self, path, results, title):
        S = 2  # px per cell -> 8 px/m
        g = self.g
        img = np.zeros((g.ny, g.nx, 3), np.uint8)
        depth = np.clip(-self.z / 20.0, 0, 1)
        img[...] = (np.stack([70 - 40 * depth, 150 - 60 * depth, 200 - 40 * depth], -1)).astype(np.uint8)
        img[self.shallow & ~self.land] = (150, 200, 210)
        img[self.land] = (214, 205, 180)
        img[self.solid] = (150, 110, 80)
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
        for p in self.terminal:
            d.polygon([P(*q) for q in p], fill=(200, 70, 60), outline=(90, 20, 20))
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
            d.text((8, y), '%s: %s, min clearance %.1f m, seabed under keel max %.2f m (limit %.1f)' % (
                res['manoeuvre'], 'PASS' if res['pass'] else 'FAIL', res['min_structure_clearance_m'],
                res['deepest_seabed_under_keel_m'], SEABED_MAX), fill=colours[k % len(colours)] if res['pass'] else (200, 0, 0), font=f)
            d.rectangle((im.width - 30, y + 2, im.width - 16, y + 14), fill=colours[k % len(colours)])
        im.save(path)


def gate_point(pose, side):
    """World position of the boarding opening on the given side (+1 port, -1 starboard) at a ship pose."""
    x, y, h = pose; h = math.radians(h)
    lx, ly = GATE_X, side * ship.deck_half(GATE_X)
    return (x + lx * math.cos(h) - ly * math.sin(h), y + lx * math.sin(h) + ly * math.cos(h))


# ---------------------------------------------------------------- Hidamari (world metres)
def berth_offshore(seabed, x, heading, y_from, step=-0.1):
    """The first berth y (moving offshore from y_from) whose underwater footprint clears the seabed."""
    g = Grid(x - 45, y_from - 60, x + 45, y_from + 10)
    z = g.sample(seabed)
    y = y_from
    while True:
        w = g.mask(); g.ship(w, WET, x, y, math.radians(heading))
        if z[w].max() <= SEABED_MAX:
            return round(y, 1)
        y += step


def hidamari(H):
    # The seabed shelves up to the quay wall (y -126): the hull lies off the quay on a timber jetty, as in concept v2.
    seabed = lambda x, y: H.height(x, y)
    cx = 855.0
    cy = berth_offshore(seabed, cx, 180.0, -126.0 - FENDER - 5.6)
    face_y = cy + 5.6 + FENDER          # jetty fender face; the hull side is FENDER outside it
    berth = (cx, cy, 180.0)            # bow west; starboard side to the jetty
    gx, gy = gate_point(berth, -1)
    jetty = [(gx - 8.0, HIDAMARI_QUAY_FACE), (gx + 8.0, HIDAMARI_QUAY_FACE), (gx + 8.0, face_y), (gx - 8.0, face_y)]
    solids = [('quay wall', 'segment', (420, -126), (900, -126), 0.6),
              ('breakwater', 'segment', (420, -126), (420, -225), 3.4),
              ('breakwater', 'segment', (420, -225), (760, -225), 3.4),
              ('lighthouse', 'disc', 440, -225, 4.0)]
    solids += [('workboat piers', 'rect', x, -148.0, 2.7, 44.0) for x in range(480, 781, 60)]
    solids += [('workboats', 'rect', 460 + i * 32, -150 - (i % 2) * 19, 9.0, 3.2) for i in range(12)]
    # The jetty is the berth itself; it is solid for every pose but the final alongside approach.
    solids += [('ferry jetty', 'fill_poly', jetty)]
    h = Harbour('Hidamari', (700, -330, 1000, -110), seabed, solids, berth, [jetty])
    return h, berth, (gx, gy), jetty, face_y


HIDAMARI_QUAY_TOP = 2.475            # quay coping top, outer face y -127.7 (hidamari/build.py harbor())
HIDAMARI_QUAY_FACE = -127.7
HIDAMARI_PIVOT = (872.0, -190.0)     # deep water inside the mouth, clear of the workboats and the headland shelf
HIDAMARI_STANDOFF = -156.0           # off the berth: the hull clears the workboat at (812, -169) while it glides


def hidamari_moves(berth):
    bx, by, _ = berth
    px, py = HIDAMARI_PIVOT
    # Arrival: in through the harbour mouth heading north, stop in deep water, pivot to port onto west, glide
    # north-west to the stand-off line, then crab onto the fenders. Departure is the same in reverse.
    arrive = (px, -290.0, 90.0)
    arrival = [('ahead', py + 290.0), ('pivot', 90.0), ('move', bx - px, HIDAMARI_STANDOFF - py), ('crab', -(by - HIDAMARI_STANDOFF))]
    departure = [('crab', by - HIDAMARI_STANDOFF), ('move', px - bx, py - HIDAMARI_STANDOFF), ('pivot', 90.0), ('ahead', py + 290.0)]
    return (arrive, arrival), (berth, departure)


# ---------------------------------------------------------------- Brinecove (region-local metres)
def brinecove(L):
    pier_x, _, pier_y1, pier_w = next((p[1], p[2], p[3], p[4]) for p in L.PIERS if p[0] == 'west')
    face_x = pier_x - pier_w / 2 - 0.5            # fender piles on the pier's west face
    cx = face_x - FENDER - 5.6
    berth = (cx, 10.0, 90.0)                      # bow north; starboard (east) side to the pier
    gx, gy = gate_point(berth, -1)
    landing = [(face_x, gy - 3.6), (face_x + 3.4, gy - 3.6), (face_x + 3.4, gy + 3.6), (face_x, gy + 3.6)]
    solids = [('quay', 'rect', 0.0, 61.0, 1200.0, 2.0)]
    for name, px, y0, y1, w in L.PIERS:
        solids.append(('%s pier' % name, 'rect', px, (y0 + y1) / 2, y0 - y1, w, 90.0))
    solids += [('central pier T-head', 'rect', 0.0, -184.0 + 5.0, 40.0, 10.0), ('east pier T-head', 'rect', 238.0, -136.0, 26.0, 14.0)]
    for name, x, y, yaw, scale, _ in L.SHIPS:
        solids.append((name, 'disc', x, y, 19.0 * scale))       # hull, bowsprit and yards at any yaw
    kept = [(-150, -90, -14), (-380, -40, -22), (-155, -205, 20), (-270, -145, 65)]
    for x, y, yaw in kept:
        solids.append(('rowboats', 'rect', x, y, 9.6, 2.9, yaw + 90.0))
    solids += [('buoys', 'disc', x, y, 0.8) for x, y in [(-200, -160), (-90, -210)]]
    seabed = np.vectorize(lambda x, y: float(L.height(x, y)))
    h = Harbour('Brinecove', (-460, -260, -100, 70), seabed, solids, berth, [landing])
    return h, berth, (gx, gy), landing, face_x


PIER_DECK_Z = 5.25                    # Brinecove pier deck (modules.py seats pier crates and barrels on it)
BRINECOVE_STANDOFF = 4.0                # the approach runs between the west pier and the rowboat at (-270, -145)
BRINECOVE_CRAB = 40.0               # west of the berth, a 180-degree pivot clears the west pier by its full radius


def brinecove_moves(berth):
    bx, by, _ = berth
    # Arrival: straight up the channel west of the west pier, bow north and BRINECOVE_STANDOFF off the fenders, then
    # crab onto them.
    arrival_start = (bx - BRINECOVE_STANDOFF, -250.0, 90.0)
    arrival = [('ahead', by + 250.0), ('crab', -BRINECOVE_STANDOFF)]
    # Departure: crab off to port (west) into the open basin until a pivot clears the pier, turn on the spot to south,
    # then ahead out of the bay west of the moored rowboat at (-270, -145).
    departure = [('crab', BRINECOVE_CRAB), ('pivot', 180.0), ('ahead', 260.0)]
    return (arrival_start, arrival), (berth, departure)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--world-build', type=Path, help="another checkout's build/yorimichi with heightmap.npy")
    args = ap.parse_args(argv)
    import yori
    if args.world_build:
        yori.OUT = args.world_build
    from hidamari import layout as H
    from brinecove import layout as L
    out = REPO / 'build/yorimichi/ferry/terminals'; out.mkdir(parents=True, exist_ok=True)
    report = {'ship': {'length': round(FULL[:, 0].max() - FULL[:, 0].min(), 2), 'outline_half_beam': round(FULL[:, 1].max(), 2),
                       'draft': DRAFT, 'keel_clearance': KEEL_CLEARANCE, 'design_margin': DESIGN_MARGIN,
                       'seabed_limit': round(SEABED_MAX, 3), 'sill_z': round(SILL_Z, 3), 'gate_x': GATE_X,
                       'gate_width': GATE_W, 'structure_clearance': STRUCTURE_CLEARANCE, 'fender_gap': FENDER}}
    ok = True
    for name, make, moves in (('hidamari', lambda: hidamari(H), hidamari_moves), ('brinecove', lambda: brinecove(L), brinecove_moves)):
        hb, berth, gate, deck, face = make()
        (a0, am), (d0, dm) = moves(berth)
        ra = hb.check('arrival', a0, am, berth_pose=berth)
        rd = hb.check('departure', d0, dm, berth_pose=berth)
        ok &= ra[0]['pass'] and rd[0]['pass']
        ground = HIDAMARI_QUAY_TOP if name == 'hidamari' else PIER_DECK_Z
        report[name] = {'berth': {'centre': [round(berth[0], 2), round(berth[1], 2)], 'heading_deg': berth[2],
                                  'walk_level_z': round(ground, 3),
                                  'gate': [round(gate[0], 2), round(gate[1], 2), round(SILL_Z, 3)], 'face': round(face, 2),
                                  'terminal_deck': [[round(a, 2), round(b, 2)] for a, b in deck]},
                        'arrival': ra[0], 'departure': rd[0]}
        hb.draw(out / f'site_{name}.png', [ra[:3], rd[:3]], f'{hb.name}: ship C arrival / departure swept path (4 px/m)')
        wet = ra[3] | rd[3]; jj, ii = np.nonzero(wet)
        np.savez_compressed(out / f'wet_{name}.npz', x=hb.g.X[ii], y=hb.g.Y[jj], seabed=hb.z[jj, ii])
        print(name, 'berth', report[name]['berth'])
        for r in (ra[0], rd[0]):
            print(' ', r['manoeuvre'], 'PASS' if r['pass'] else 'FAIL', 'clearance', r['min_structure_clearance_m'],
                  'conflicts', r['conflict_count'], r['structure_conflicts'][:3], 'grounding', r['grounding_count'],
                  r['grounding_poses'][:3], 'nearest', r['nearest_by_obstacle_m'])
    (out / 'site.json').write_text(json.dumps(report, indent=1) + '\n')
    print('SITE', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
