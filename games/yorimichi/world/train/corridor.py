"""The railway's vegetation corridor (plain Python): where no tree or bush may stand because the train passes.

From the route study's route.json (route v3), whose samples every 10 m carry the rail and ground heights and the
class of each stretch, plus the passing loop's second track. The corridor runs along the line outside the tunnels
(the forest over a tunnel stays), and over the Belmonte station's ground when the line ends there (station_site.py).
Its half width is the train's clearance with a tree's crown (HALF_WIDTH), widened
where the line runs in a cutting or on an embankment to the earthworks' footprint (route.FORMATION and route.SLOPE),
capped at MAX_HALF_WIDTH.

`load()` returns None when route.json has not been built: callers keep their former behaviour then.

The region steps read line.json, not route.json: the line's geometry alone (samples' s, x, y, heights and class, the
passing loop's second track), which the route step writes beside route.json. route.json also holds what the line
sees (views and empty spaces, counted over the planted trees), which changes whenever the regions clear the corridor;
line.json does not, so clearing the trees never makes the route and the regions stale in turn.
"""
import functools
import json

import numpy as np

import yori
from train import station_site as SS

ROUTE = yori.OUT / 'belmonte-train' / 'route' / 'route.json'
LINE = yori.ASSETS / 'vehicles' / 'belmonte-train' / 'line.json'
HALF_WIDTH = 10.        # metres either side of the centreline: half the train (1.8) plus a tree's crown and a margin
MAX_HALF_WIDTH = 40.
FORMATION, SLOPE = 8., 1.5      # route.py's: formation width and earthwork slope (horizontal per vertical)
OPEN = ('cutting', 'deep cutting', 'embankment', 'viaduct')


def half_width(sample):
    """The corridor's half width at a route sample (None inside a tunnel)."""
    if sample['class'] not in OPEN:
        return None
    w = HALF_WIDTH
    if sample['class'] != 'viaduct':
        w = max(w, FORMATION / 2 + SLOPE * abs(sample['rail_z'] - sample['ground_z']) + 2.)
    return min(w, MAX_HALF_WIDTH)


class Corridor:
    """Segments (a, b, half width) of the open line and the passing loop's second track."""

    def __init__(self, route):
        rows = route['samples']
        segs = []
        for p, q in zip(rows, rows[1:]):
            wp, wq = half_width(p), half_width(q)
            if wp is None and wq is None:
                continue                            # wholly in a tunnel
            segs.append(((p['x'], p['y']), (q['x'], q['y']), max(w for w in (wp, wq) if w is not None)))
        loop = (route.get('passing_loop') or {}).get('second_track') or []
        by_s = {round(r['s']): r for r in rows}
        for p, q in zip(loop, loop[1:]):
            near = by_s.get(int(round(p[0] / 10.) * 10))
            w = half_width(near) if near else HALF_WIDTH
            segs.append(((p[1], p[2]), (q[1], q[2]), w or HALF_WIDTH))
        self.site = SS.for_line([(r['x'], r['y']) for r in rows[-2:]], [r.get('rail_z', np.nan) for r in rows[-2:]])
        self.a = np.array([s[0] for s in segs], float).reshape(-1, 2)
        self.b = np.array([s[1] for s in segs], float).reshape(-1, 2)
        self.w = np.array([s[2] for s in segs], float)

    def margin(self, x, y):
        """Distance beyond the corridor's edge (negative inside it) for points x, y."""
        # The Belmonte station's footprint, forecourt and access road keep ROAD_CLEAR of plants too.
        return np.minimum(self._distance(x, y, self.w, self.w), self.station_margin(x, y))

    def distance(self, x, y, reach=MAX_HALF_WIDTH):
        """Distance from the open line's track (and the passing loop's second one) for points x, y; inf beyond
        `reach`."""
        return self._distance(x, y, np.zeros_like(self.w), np.full_like(self.w, float(np.max(reach, initial=0.))))

    def _distance(self, x, y, widths, pad):
        x, y = np.asarray(x, float).ravel(), np.asarray(y, float).ravel()
        out = np.full(len(x), np.inf)
        if not len(x):
            return out
        lo = np.minimum(self.a, self.b) - pad[:, None]
        hi = np.maximum(self.a, self.b) + pad[:, None]
        for (ax, ay), (bx, by), w, (x0, y0), (x1, y1) in zip(self.a, self.b, widths, lo, hi):
            near = (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
            if not near.any():
                continue
            px, py = x[near], y[near]
            dx, dy = bx - ax, by - ay
            t = np.clip(((px - ax) * dx + (py - ay) * dy) / max(dx * dx + dy * dy, 1e-9), 0., 1.)
            d = np.hypot(px - ax - t * dx, py - ay - t * dy) - w
            out[near] = np.minimum(out[near], d)
        return out

    def station_margin(self, x, y):
        """Distance beyond the station's ground plus its clearance (negative on it)."""
        if self.site is None:
            return np.full(np.shape(x), np.inf)
        return SS.excess(self.site, x, y) - SS.ROAD_CLEAR

    def blocked(self, x, y, reach=0.):
        """True where a plant at x, y stands in the corridor, or (with `reach`, a crown's radius plus the train's
        envelope; see crown_clearance) where its crown would reach the train."""
        out = self.margin(x, y) < 0.
        if np.any(np.asarray(reach) > 0.):
            out |= self.distance(x, y, reach) < reach
        return out


def line_data(route):
    """line.json's content: the route's geometry, nothing that depends on the planting."""
    keys = ('s', 'x', 'y', 'rail_z', 'ground_z', 'class')
    loop = route.get('passing_loop') or {}
    return dict(version=1, frame=route.get('frame'),
                samples=[{k: r[k] for k in keys} for r in route['samples']],
                passing_loop=dict(start=loop.get('start'), end=loop.get('end'),
                                  second_track=loop.get('second_track') or []),
                about='The Belmonte line\'s geometry from route.json (train/corridor.py): what the regions\' '
                      'railway clearance and the terrain\'s earthworks read.')


def load(path=None):
    """The corridor of the committed Belmonte railway line (or path when given)."""
    for p in ([path] if path else [LINE]):
        try:
            return Corridor(json.loads(p.read_text()))
        except (OSError, ValueError, KeyError):
            continue
    return None


def keep(x, y):
    """A mask of the plants at x, y that may stay: all of them when the route is not built."""
    c = load()
    n = np.asarray(x, float).size
    return np.ones(n, bool) if c is None else ~c.blocked(x, y)


PLANTS = ('Tree', 'Bush', 'Shrub', 'Fern', 'Reed')     # what the corridor cleared before the earthworks' soft edge
# The soft edge (with the earthworks, train/earthworks.py): trees keep clear of the whole corridor; shrubs, rocks and
# litter come down the slopes to SHRUB_HALF of the line, off the rock faces; grass and flowers to the ballast's edge.
# Whatever stays near the line is set on the carved ground (the regions place it on the natural one).
SHRUBS = ('Bush', 'Shrub', 'Fern', 'Reed', 'Rock', 'Litter')
GRASSES = ('Grass', 'Flower')
SHRUB_HALF = 4.5            # the train's half width (1.8) and the step boards, plus a shrub's spread
GRASS_HALF = 3.2            # the ballast's skirt (track.SKIRT 2.6) and its shoulder
MOVED = .5                  # a tree on ground the earthworks moved more than this goes (it would float or sink)
# The train's swept envelope (vehicles/belmonte-train service.json's exteriors, 1.7 m either side of the track) with
# 0.3 m margin and 0.1 m for the coaches' overhang on the tightest curve. A tree whose crown (CROWN radius times its
# instance scale) would reach it from beyond the corridor's edge goes too.
ENVELOPE_HALF = 2.1
# Crown radii (m) at scale 1, measured on the built meshes where the forest's generated crowns outgrow their spec.
MEASURED_CROWN = {'Tree_Forest_Maple': 8.2, 'Tree_Forest_Ginkgo': 7.1, 'Tree_Forest_Pine': 5.1}
CROWN_SPREAD = 1.2          # otherwise the generated crown spreads this much past the spec's width / 2


@functools.lru_cache(None)
def crowns():
    """{asset: crown radius at scale 1} for the generated trees (regions/forest/specs.py), measured where known."""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('_forest_specs', Path(__file__).resolve().parents[1] / 'regions' /
                                                  'forest' / 'specs.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = {n: v[3] / 2 * CROWN_SPREAD for n, v in {**mod.TUSCAN, **mod.FOREST}.items()}
    out.update(MEASURED_CROWN)
    return out


def crown_clearance(name, scale=1.):
    """How far from the track a tree named `name` at instance scale `scale` must stand for its crown to keep out of the
    train's envelope (0 for trees without a known crown, which HALF_WIDTH clears)."""
    r = crowns().get(name)
    scale = np.asarray(scale, float)
    return np.zeros(scale.shape) if r is None else r * scale + ENVELOPE_HALF


def kind(name):
    """'tree', 'shrub', 'grass' or None for an instance or asset name."""
    name = name.replace('Tree_Tuscan', 'Tree').replace('Tree_Forest', 'Tree')
    return 'tree' if name.startswith('Tree') else 'shrub' if name.startswith(SHRUBS) else \
        'grass' if name.startswith(GRASSES) else None


def settle(name, x, y, z, corridor=None, scale=1.):
    """(keep, z): which of the plants named `name` at x, y, z (natural ground, instance scale `scale`) stay, and their
    height on the carved ground. A tree also keeps its crown out of the train's envelope (crown_clearance). Without the
    earthworks (RAILWAY_EARTHWORKS=0 or no line) shrubs keep clear of the whole corridor as trees do, and nothing
    moves."""
    from train import earthworks as E
    x, y, z = (np.asarray(v, float).ravel() for v in (x, y, z))
    keep, out = np.ones(len(x), bool), z.copy()
    k = kind(name)
    c = corridor or load()
    if k is None or c is None or not len(x):
        return keep, out
    ln = E.line()
    reach = np.broadcast_to(crown_clearance(name, scale), x.shape) if k == 'tree' else 0.
    if ln is None:
        if k != 'grass':
            keep = ~c.blocked(x, y, reach)
        return keep, out
    s, u, _ = ln.project(x, y)
    near = np.isfinite(s)
    if k == 'tree':
        keep = ~c.blocked(x, y, reach)
    keep &= c.station_margin(x, y) >= 0.                    # nothing grows on the station's ground
    if not near.any():
        return keep, out
    i = np.flatnonzero(near)
    tunnel, _ = ln.inside(s[i], ln.tunnels)
    viaduct, _ = ln.inside(s[i], ln.viaducts)
    open_ = (tunnel <= 0) & (viaduct <= 0)
    # Over a tunnel the ground is left as it is (its hood only thickens thin cover); a plant's own height there may
    # belong to another surface (the far hills under the foothills).
    carved = np.where(open_, E.carve(x[i], y[i], z[i], ln), z[i])
    moved = np.abs(carved - z[i]) > MOVED
    if k == 'tree':
        bad = moved                                         # no tree on the new slopes
    else:
        bad = open_ & (np.abs(u[i]) < (SHRUB_HALF if k == 'shrub' else GRASS_HALF))
        bad |= E.in_hole(x[i], y[i], carved, ln)
        if k == 'shrub':
            rock, _, _ = E.weights(x[i], y[i], carved, z[i], ln)
            bad |= rock > .5
    # Nothing grows inside a tunnel: a plant over one whose foot is under the lining's crown (on ground under the
    # foothills, or below the hood) would stand in the bore, in the passengers' way.
    rail = np.interp(s[i], ln.s, ln.rail)
    bad |= (tunnel > 0) & (np.abs(u[i]) < E.HOOD_HALF) & (z[i] < rail + PORTAL_HEIGHT[1])
    keep[i] &= ~bad
    out[i] = carved
    return keep, out


def clear_instances(instances, corridor=None):
    """Clear the railway's corridor in {name: [[x, y, z, ...], ...]} in place (see settle); {name: removed}."""
    c = corridor or load()
    removed = {}
    if c is None:
        return removed
    for name, rows in instances.items():
        if not rows or kind(name) is None:
            continue
        a = np.asarray(rows, float)
        if a.ndim != 2 or a.shape[1] < 3:
            continue
        keep, z = settle(name, a[:, 0], a[:, 1], a[:, 2], c, a[:, 4] if a.shape[1] > 4 else 1.)
        if (~keep).any() or not np.array_equal(z, a[:, 2]):
            a[:, 2] = np.round(z, 3)
            removed[name] = int((~keep).sum())
            instances[name] = a[keep].tolist()
    return {k: v for k, v in removed.items() if v}


# --- the terrain's cut and fill, for the terrain builders --------------------------------------------------------
CUT, FILL = ('cutting', 'deep cutting'), ('embankment',)
FORMATION_DEPTH = .70       # the formation (ballast toe) under the rail top (track.BALLAST_TOE)
PORTAL_APPROACH = (30., 10.)   # a portal's box reaches this far out of the tunnel and this far in
PORTAL_HALF_WIDTH = 4.6     # track.TUNNEL_HALF plus 2 m
PORTAL_HEIGHT = (-1., 7.8)  # from under the rail top to over the lining's crown (track.TUNNEL_WALL + TUNNEL_HALF + 2)


def _bearing(rows, i):
    a, b = rows[max(i - 1, 0)], rows[min(i + 1, len(rows) - 1)]
    dx, dy = b['x'] - a['x'], b['y'] - a['y']
    n = np.hypot(dx, dy) or 1.
    return dx / n, dy / n


def terrain_mask(route):
    """Where the ground must give way to the line, as plain data: the cut and fill footprints (runs of samples, each
    with its edges where the earthworks' 1:1.5 slopes meet the ground, and the footprint as a polygon) and the box at
    each tunnel portal inside which the terrain is carved or hidden. Frame: route.json's (metres, x east, y north)."""
    rows = route['samples']
    runs, cur = [], None
    for i, r in enumerate(rows):
        kind = 'cut' if r['class'] in CUT else 'fill' if r['class'] in FILL else None
        if kind != (cur and cur['kind']):
            cur = dict(kind=kind, samples=[]) if kind else None
            if cur:
                runs.append(cur)
        if cur:
            tx, ty = _bearing(rows, i)
            hw = FORMATION / 2 + SLOPE * abs(r['rail_z'] - r['ground_z'])
            left = [r['x'] - ty * hw, r['y'] + tx * hw]
            right = [r['x'] + ty * hw, r['y'] - tx * hw]
            cur['samples'].append(dict(s=r['s'], x=r['x'], y=r['y'], rail_z=r['rail_z'], ground_z=r['ground_z'],
                                       formation_z=round(r['rail_z'] - FORMATION_DEPTH, 3), half_width=round(hw, 3),
                                       left=[round(v, 3) for v in left], right=[round(v, 3) for v in right]))
    for run in runs:
        ss = run['samples']
        run['s0'], run['s1'] = ss[0]['s'], ss[-1]['s']
        run['polygon'] = [q['left'] for q in ss] + [q['right'] for q in ss[::-1]]
    portals = []
    tunnel = [i for i, r in enumerate(rows) if r['class'] == 'tunnel']
    starts = [i for i in tunnel if i == 0 or rows[i - 1]['class'] != 'tunnel']
    ends = [i for i in tunnel if i == len(rows) - 1 or rows[i + 1]['class'] != 'tunnel']
    out_len, in_len = PORTAL_APPROACH
    for i, outward in [(i, -1.) for i in starts] + [(i, 1.) for i in ends]:
        r = rows[i]
        tx, ty = _bearing(rows, i)
        ox, oy = tx * outward, ty * outward                # out of the tunnel
        mid = (out_len - in_len) / 2
        z0, z1 = r['rail_z'] + PORTAL_HEIGHT[0], r['rail_z'] + PORTAL_HEIGHT[1]
        portals.append(dict(s=r['s'], centre=[round(r['x'] + ox * mid, 3), round(r['y'] + oy * mid, 3), round((z0 + z1) / 2, 3)],
                            yaw_deg=round(float(np.degrees(np.arctan2(oy, ox))), 3),
                            half_extents=[(out_len + in_len) / 2, PORTAL_HALF_WIDTH, (z1 - z0) / 2],
                            note='x along the line, out of the tunnel; y across; z up'))
    return dict(version=1, frame=route.get('frame'), formation_m=FORMATION, slope=SLOPE,
                runs=runs, portals=portals,
                about='cut: the ground lowered to formation_z between the edges; fill: raised to it; portals: terrain '
                      'carved or hidden inside the box. From train/corridor.py over route.json.')


def _write(path, data):
    """Write only on a change, so an unchanged product keeps its time and content."""
    text = json.dumps(data, indent=1)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def write_terrain_mask(route=None, path=None):
    """terrain_mask.json and line.json beside route.json (the route step calls this after writing it)."""
    route = route or json.loads(ROUTE.read_text())
    path = path or ROUTE.with_name('terrain_mask.json')
    _write(path, terrain_mask(route))
    _write(path.with_name('line.json'), line_data(route))
    return path


if __name__ == '__main__':
    print(write_terrain_mask())
