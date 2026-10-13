"""The coach fittings hung on the layout's mounts, modelled in code (plain Python; build.py turns them into meshes).

Second class only for now, in its worn style:
- rack: a luggage net over each bench pair, dull brass rods on two cast wall brackets and a sagging cord net;
- ceiling-lamp: a bare bulb under a small enamel shade (grimy outside, sooted inside, chipped rim), on a twisted
  cord from a ceiling rose (cord and rose LOD0 only);
- curtain-rail: a thin rod over the window and two softly pleated curtains drawn to its sides, mapped in metres;
- menu-board: the canteen's framed menu board, its face a texture slot (T_BT_MenuBoard);
- ladle: the iron wall hook the canteen lady's big ladle hangs from (the ladle itself is a separate asset).
The other mount kinds there are anchors for gameplay (ANCHORS) and carry no geometry.

Each fitting kind gives one Part (one object for every mount of that kind, few draw calls): its faces as
(points, material, uv or None) in the coach frame, whether the mesh is closed, its LODs and its light sockets.
"""
import math
from dataclasses import dataclass, field

from train import layout as L

COACHES = {'second-class'}
ANCHORS = {'npc-spot', 'serve-point', 'queue'}      # where the canteen lady stands, the tray lands, passengers queue

RACK_DEPTH, RACK_SAG, ROD_R = .30, .05, .008
NET_CORD = .008                                       # width of a cord ribbon
SHADE_R, SHADE_H, CORD_LEN = .13, .10, .20          # the bulb clears a 1.75 m adult by 15 cm in the aisle
CURTAIN_W, CURTAIN_PITCH, CURTAIN_AMP, CURTAIN_GAP = .26, .065, .02, .065   # gathered width, pleat, depth, off the wall
CURTAIN_TILE = .50                                    # metres of cloth per repeat of the fabric swatch (T_BT_CurtainFabric)
BOARD_H, BOARD_FRAME = .36, .04


@dataclass
class Part:
    name: str
    faces: list = field(default_factory=list)
    closed: bool = True
    lods: tuple = (0, 1)
    sockets: list = field(default_factory=list)       # (name, (x, y, z)): where a runtime light goes
    smooth: float = 35.                               # edges sharper than this stay hard (degrees)

    def quad(self, a, b, c_, d, mat, uv=None):
        self.faces.append(([a, b, c_, d], mat, uv))


def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _add(a, b, s=1.): return (a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s)
def _cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = math.sqrt(sum(v * v for v in a)) or 1.
    return (a[0] / n, a[1] / n, a[2] / n)


def tube(p, pts, r, mat, sides=6, caps=True):
    """A round bar of radius r along a polyline."""
    rings = []
    for i, c in enumerate(pts):
        d = _unit(_sub(pts[min(i + 1, len(pts) - 1)], pts[max(i - 1, 0)]))
        ref = (0, 0, 1) if abs(d[2]) < .9 else (1, 0, 0)
        u = _unit(_cross(d, ref)); v = _cross(d, u)
        rings.append([_add(_add(c, u, r * math.cos(2 * math.pi * k / sides)), v, r * math.sin(2 * math.pi * k / sides)) for k in range(sides)])
    for a, b in zip(rings, rings[1:]):
        for k in range(sides):
            p.quad(a[k], a[(k + 1) % sides], b[(k + 1) % sides], b[k], mat)
    if caps:
        p.faces.append((rings[0][::-1], mat, None)); p.faces.append((rings[-1], mat, None))


def ribbon(p, pts, w, mat, across=(0, 0, 1)):
    """A flat strip of width w along a polyline, lying across `across` (a cord seen from above and below)."""
    for a, b in zip(pts, pts[1:]):
        d = _unit(_sub(b, a)); s = _unit(_cross(d, across))
        p.quad(_add(a, s, -w / 2), _add(b, s, -w / 2), _add(b, s, w / 2), _add(a, s, w / 2), mat)


def _noise(*v):
    """A repeatable pseudo-random number in [0, 1) from a few numbers (no global random state)."""
    return math.modf(math.sin(sum(a * b for a, b in zip(v, (12.9898, 78.233, 37.719, 4.581)))) * 43758.5453)[0] % 1.


def lathe(p, cx, cy, profile, mat, seg=14):
    """A surface of revolution about the vertical through (cx, cy) from (radius, z) points, top to bottom. mat is a
    material name, or a function (band, segment) -> material name for bands and patches of their own."""
    ring = lambda r, z: [(cx + r * math.cos(2 * math.pi * k / seg), cy + r * math.sin(2 * math.pi * k / seg), z) for k in range(seg)]
    loops = [ring(r, z) for r, z in profile]
    for i, (a, b) in enumerate(zip(loops, loops[1:])):
        for k in range(seg):
            m = mat(i, k) if callable(mat) else mat
            if profile[i][0] < 1e-6:
                p.faces.append(([a[k], b[(k + 1) % seg], b[k]], m, None))
            elif profile[i + 1][0] < 1e-6:
                p.faces.append(([a[k], a[(k + 1) % seg], b[k]], m, None))
            else:
                p.quad(a[k], a[(k + 1) % seg], b[(k + 1) % seg], b[k], m)


def box(p, x0, x1, y0, y1, z0, z1, mat):
    x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1)); z0, z1 = sorted((z0, z1))
    P = lambda i, j, k: ((x0, x1)[i], (y0, y1)[j], (z0, z1)[k])
    for q in ([P(0, 1, 0), P(0, 0, 0), P(0, 0, 1), P(0, 1, 1)], [P(1, 0, 0), P(1, 1, 0), P(1, 1, 1), P(1, 0, 1)],
              [P(0, 0, 0), P(1, 0, 0), P(1, 0, 1), P(0, 0, 1)], [P(1, 1, 0), P(0, 1, 0), P(0, 1, 1), P(1, 1, 1)],
              [P(0, 1, 0), P(1, 1, 0), P(1, 0, 0), P(0, 0, 0)], [P(0, 0, 1), P(1, 0, 1), P(1, 1, 1), P(0, 1, 1)]):
        p.faces.append((q, mat, None))


def into_room(c, mt):
    """The unit vector from the wall a mount hangs on into its room (the nearest edge of the room's rectangle)."""
    r = c.room(mt.room)
    edges = [(mt.x - r.x0, (1, 0)), (r.x1 - mt.x, (-1, 0)), (mt.y - r.y0, (0, 1)), (r.y1 - mt.y, (0, -1))]
    return min(edges)[1]


def _frame(c, mt):
    """Wall-mount frame: (u along the wall, v out from the wall face into the room, height z) -> coach coordinates."""
    nx, ny = into_room(c, mt)
    tx, ty = -ny, nx
    r = c.room(mt.room)
    wx = mt.x if not nx else (r.x0 if nx > 0 else r.x1)
    wy = mt.y if not ny else (r.y0 if ny > 0 else r.y1)
    return lambda u, v, z: (wx + tx * u + nx * v, wy + ty * u + ny * v, z)


def racks(c, part, net):
    for mt in c.mounts:
        if mt.kind != 'rack':
            continue
        P, h, z = _frame(c, mt), mt.length / 2, mt.z
        for v in (.05, RACK_DEPTH):                                       # back and front rods
            tube(part, [P(-h, v, z), P(h, v, z)], ROD_R, 'brass-dull', 8)
        for u in (-h + .06, h - .06):                                     # cast brackets: wall plate, arm, strut above
            a, b = P(u - .025, 0, z - .03), P(u + .025, .012, z + .10)
            box(part, a[0], b[0], a[1], b[1], a[2], b[2], 'brass-dull')
            tube(part, [P(u, .01, z), P(u, RACK_DEPTH + .015, z)], .007, 'brass-dull', 6)
            tube(part, [P(u, .01, z + .08), P(u, .22, z)], .006, 'brass-dull', 6)
        sag = lambda u, v: z - RACK_SAG * math.sin(math.pi * (v - .05) / (RACK_DEPTH - .05)) * (.7 + .3 * math.cos(math.pi * u / h))
        n_u = 16
        for k in range(1, 5):                                             # cords along the rack
            v = .05 + k * (RACK_DEPTH - .05) / 5
            ribbon(net, [P(-h + .01 + i * (2 * h - .02) / n_u, v, sag(-h + .01 + i * (2 * h - .02) / n_u, v)) for i in range(n_u + 1)], NET_CORD, 'cord')
        n = int((2 * h - .02) / .10)
        for i in range(n + 1):                                            # cords across, every 10 cm
            u = -h + .01 + i * (2 * h - .02) / n
            ribbon(net, [P(u, v, sag(u, v)) for v in [.05 + j * (RACK_DEPTH - .05) / 5 for j in range(6)]], NET_CORD, 'cord',
                   across=(0, 0, 1))


def lamps(c, part, cords):
    for n, mt in enumerate(m for m in c.mounts if m.kind == 'ceiling-lamp'):
        x, y, z = mt.x, mt.y, mt.z
        lathe(cords, x, y, [(0, z + .02), (.045, z + .02), (.045, z), (.03, z - .02), (0, z - .02)], 'enamel-grimy', 8)   # ceiling rose
        z0, z1 = z - .02, z - .02 - CORD_LEN
        for s in (0, math.pi):                                            # two twisted strands
            tube(cords, [(x + .003 * math.cos(s + 9 * t), y + .003 * math.sin(s + 9 * t), z0 + (z1 - z0) * t / 6) for t in range(7)],
                 .0025, 'end-dark', 3)
        lathe(part, x, y, [(0, z1), (.018, z1), (.018, z1 - .055), (0, z1 - .055)], 'end-dark', 8)                   # bakelite holder
        # the shade: an enamel cone, grimy outside, sooted inside above the bulb, its rim chipped to the dark iron
        def shade(band, k, n=n):
            if band in (2, 3):
                return 'iron-black' if _noise(n, k, band) < .55 else 'enamel-grimy'
            if band >= 4:
                return 'enamel-soot' if band == 5 or _noise(n, k, 9) < .6 else 'enamel-grimy'
            return 'enamel-grimy' if band == 0 or _noise(n, k, 3) < .7 else 'enamel-white'
        zs = z1 - .03
        lathe(part, x, y, [(.02, zs), (.06, zs - .03), (SHADE_R, zs - SHADE_H), (SHADE_R + .004, zs - SHADE_H - .004),
                           (SHADE_R - .004, zs - SHADE_H), (.057, zs - .033), (.017, zs - .003)], shade, 12)
        zb = z1 - .055
        lathe(part, x, y, [(.008, zb), (.014, zb - .02), (.03, zb - .05), (.031, zb - .07), (.02, zb - .095), (0, zb - .10)], 'lamp-white', 10)
        part.sockets.append((f'SOCKET_Light_{"".join(w.title() for w in mt.id.split("-"))}', (x, y, zb - .06)))


def _top(pl):
    """The highest point of a placement: its pivot is at its base, or at its top for things hung from a hook."""
    pivot = next(a['pivot'] for a in L.contract()['assets'] if a['id'] == pl.asset)
    return pl.z if pivot == 'hook_top' else pl.z + L.asset_dims(pl.asset)[2]


def curtains(c, rails, cloth):
    windows = {f'curtain-{w.name}': w for w in c.windows}
    for mt in c.mounts:
        if mt.kind != 'curtain-rail':
            continue
        w = windows[mt.id]
        P, h, z = _frame(c, mt), mt.length / 2, mt.z
        tube(rails, [P(-h, CURTAIN_GAP, z), P(h, CURTAIN_GAP, z)], ROD_R, 'brass-dull', 8)
        for u in (-h, h):
            tube(rails, [P(u, 0, z), P(u, CURTAIN_GAP, z)], .006, 'brass-dull', 6)                  # wall brackets
            tube(rails, [P(u, CURTAIN_GAP, z), P(u + (-.03 if u < 0 else .03), CURTAIN_GAP, z)], .013, 'brass-dull', 8)     # finials
        top = z - .015
        steps = int(CURTAIN_W / CURTAIN_PITCH) * 10
        for side in (-1, 1):                                              # drawn to both ends
            seed = _noise(mt.x, mt.y, side)
            u0 = side * (h - .02)
            a, b = P(u0, 0, 0), P(u0 - side * CURTAIN_W, CURTAIN_GAP + 2 * CURTAIN_AMP, 0)
            bottom = w.sill - .06                                         # just below the sill, or clear of a bench back
            for pl in c.placements:
                x0, x1, y0, y1 = L.footprint(pl)
                if x0 < max(a[0], b[0]) and min(a[0], b[0]) < x1 and y0 < max(a[1], b[1]) and min(a[1], b[1]) < y1:
                    bottom = max(bottom, _top(pl) + .03)
            # soft folds: the phase runs at a pitch wandering +-15 %, each fold its own depth, gathered tight at the rail
            # and fuller at the hem, which dips at the leading edge and curls up towards the wall end
            cols, phase, run = [], 0., 0.
            for i in range(steps + 1):
                t = i / steps
                u = u0 - side * CURTAIN_W * t
                if i:
                    phase += 2 * math.pi * (CURTAIN_W / steps) / (CURTAIN_PITCH * (1 + .3 * (_noise(seed, int(phase / math.pi)) - .5)))
                depth = CURTAIN_AMP * (.75 + .5 * _noise(seed, int(phase / (2 * math.pi)), 7))
                f = math.sin(phase)
                hem = bottom - .025 * math.sin(math.pi * t) ** 2 + .015 * t
                cols.append((P(u, CURTAIN_GAP + depth * .6 * f, top), P(u, CURTAIN_GAP + depth * f, hem)))
            for (a0, a1), (b0, b1) in zip(cols, cols[1:]):                 # UVs in metres of cloth, for the swatch
                da, db = _sub(b0, a0), _sub(b1, a1)
                s0, s1 = run, run + math.sqrt(sum(v * v for v in da))
                cloth.quad(a1, b1, b0, a0, 'curtain-fabric', [(s0 / CURTAIN_TILE, a1[2] / CURTAIN_TILE), (s1 / CURTAIN_TILE, b1[2] / CURTAIN_TILE),
                                                              (s1 / CURTAIN_TILE, b0[2] / CURTAIN_TILE), (s0 / CURTAIN_TILE, a0[2] / CURTAIN_TILE)])
                run = s1


def menu_board(c, part):
    for mt in c.mounts:
        if mt.kind != 'menu-board':
            continue
        P, h, z = _frame(c, mt), mt.length / 2, mt.z
        hb, f = BOARD_H / 2, BOARD_FRAME
        a, b = P(-h, 0, z - hb), P(h, .015, z + hb)
        box(part, a[0], b[0], a[1], b[1], a[2], b[2], 'end-dark')                                        # the board's body
        part.faces.append(([P(-h + f, .016, z - hb + f), P(h - f, .016, z - hb + f), P(h - f, .016, z + hb - f), P(-h + f, .016, z + hb - f)],
                           'menu-board', [(0, 0), (1, 0), (1, 1), (0, 1)]))                              # its face, mapped whole
        for u0, u1, z0, z1 in ((-h, h, z - hb, z - hb + f), (-h, h, z + hb - f, z + hb), (-h, -h + f, z - hb, z + hb), (h - f, h, z - hb, z + hb)):
            a, b = P(u0, 0, z0), P(u1, .03, z1)
            box(part, a[0], b[0], a[1], b[1], a[2], b[2], 'enamel-cream')


def ladle_hooks(c, part):
    for mt in c.mounts:
        if mt.kind != 'ladle':
            continue
        P, z = _frame(c, mt), mt.z
        a, b = P(-.03, 0, z - .07), P(.03, .012, z + .03)
        box(part, a[0], b[0], a[1], b[1], a[2], b[2], 'iron-black')                                     # screwed plate
        tube(part, [P(0, .01, z), P(0, .07, z - .005), P(0, .085, z + .02), P(0, .08, z + .045)], .006, 'iron-black', 6)   # J hook


def fittings(c):
    """Every fitting Part of a coach (empty for coaches not yet fitted)."""
    if c.name not in COACHES:
        return []
    parts = {k: Part(n, closed=cl, lods=lo) for k, n, cl, lo in (
        ('rack', 'Fittings_Racks', False, (0, 1)), ('net', 'Fittings_RackNets', False, (0,)),
        ('ceiling-lamp', 'Fittings_Lamps', False, (0, 1)), ('cord', 'Fittings_LampCords', False, (0,)),
        ('curtain-rail', 'Fittings_CurtainRails', False, (0, 1)), ('curtain', 'Fittings_Curtains', False, (0, 1)),
        ('menu-board', 'Fittings_MenuBoard', True, (0, 1)), ('ladle', 'Fittings_LadleHook', False, (0, 1)))}
    racks(c, parts['rack'], parts['net'])
    lamps(c, parts['ceiling-lamp'], parts['cord'])
    parts['curtain'].smooth = 180.                    # soft folds, no hard creases
    curtains(c, parts['curtain-rail'], parts['curtain'])
    menu_board(c, parts['menu-board'])
    ladle_hooks(c, parts['ladle'])
    return [p for p in parts.values() if p.faces]


KINDS = {'rack': ('Fittings_Racks', 'Fittings_RackNets'), 'ceiling-lamp': ('Fittings_Lamps', 'Fittings_LampCords'),
         'curtain-rail': ('Fittings_CurtainRails', 'Fittings_Curtains'), 'menu-board': ('Fittings_MenuBoard',),
         'ladle': ('Fittings_LadleHook',)}
