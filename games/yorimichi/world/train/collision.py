"""The vehicles' collision, in plain Python (no Blender): the convex boxes build.py exports as UCX_ meshes and
placements.json lists, and check_collision(), which tests them against the plan the way a player capsule meets them.

collision_boxes(c) returns [(part, (x0, x1, y0, y1, z0, z1))] in the coach frame."""
import numpy as np

from train import access as A
from train import layout as L


# reservation kinds that have geometry today (fittings.py, build.lookout, the locomotive's body); the others (WC pans,
# bar, back bar, range, stoves) wait for their models and must not get collision before them
MODELLED = {'galley-counter', 'pantry-counter', 'attendant-seat', 'handbrake', 'bench', 'desk', 'luggage-shelves',
            'drinks-ledge', 'steps', 'wall', 'control-stand', 'pipework', 'seat'}


def _free(a0, a1, blocked, min_len=.12):
    out, a = [], a0
    for b0, b1 in sorted(blocked):
        if b1 <= a or b0 >= a1:
            continue
        if b0 - a >= min_len:
            out.append((a, b0))
        a = max(a, b1)
    if a1 - a >= min_len:
        out.append((a, a1))
    return out


def collision_boxes(c):
    """Simple convex boxes for walking: floor, walls broken at every doorway, partitions, ceiling and fixed fittings."""
    b = c.body
    if b.kind == 'tender':
        return tender_collision_boxes(c)
    if b.kind == 'locomotive':
        return loco_collision_boxes(c)
    boxes = []
    add = lambda n, *q: boxes.append((n, q))
    add('floor', b.in_a, b.in_b, -L.IN, L.IN, L.FLOOR_Z - .20, L.FLOOR_Z)
    add('ceiling', b.in_a, b.in_b, -L.IN, L.IN, L.CEIL_SPRING, L.CEIL_SPRING + .15)
    for s in (-1, 1):
        if b.end(s) == 'balcony':
            x0, x1 = sorted((b.headstock(s), b.face(s)))
            add('balcony-floor', x0, x1, -L.IN, L.IN, L.FLOOR_Z - .20, L.FLOOR_Z)
    for i, (x0, x1, y0, y1) in enumerate(L.railings(b)):
        add(f'railing-{i}', x0, x1, y0, y1, L.FLOOR_Z, L.FLOOR_Z + 1.05)
    for sy in (-1, 1):
        y0, y1 = sorted((sy * L.IN, sy * L.HALF))
        doors_x = sorted((x0, x1) for _, s, x0, x1, *_ in L.exterior_openings(c) if s == sy)
        for a0, a1 in _free(b.x_a, b.x_b, doors_x, 0.):
            add(f'side-{sy}', a0, a1, y0, y1, L.FLOOR_Z, L.CANT_Z)
        for x0, x1 in doors_x:
            add(f'side-{sy}-over-door', x0, x1, y0, y1, L.FLOOR_Z + L.DOOR_H, L.CANT_Z)
    for w in c.walls:
        spans = _free(w.a0, w.a1, [(o.a0, o.a1) for o in w.openings], 0.)
        top = L.CEIL_SPRING if not w.name.startswith('end-') else L.CANT_Z
        for a0, a1 in spans:
            add(w.name, *((a0, a1, w.c0, w.c1) if w.axis == 'x' else (w.c0, w.c1, a0, a1)), L.FLOOR_Z, top)
        for o in w.openings:
            add(f'{w.name}-head', *((o.a0, o.a1, w.c0, w.c1) if w.axis == 'x' else (w.c0, w.c1, o.a0, o.a1)), o.z1, top)
            if o.z0 - L.FLOOR_Z > .05:         # below a hatch
                add(f'{w.name}-sill', *((o.a0, o.a1, w.c0, w.c1) if w.axis == 'x' else (w.c0, w.c1, o.a0, o.a1)), L.FLOOR_Z, o.z0)
    boxes += furniture_boxes(c)
    for r in c.reservations:                        # the furniture modelled in code (an unmodelled box stays soft)
        if r.z0 - L.FLOOR_Z < 1.0 and r.kind in MODELLED:
            add(r.name, r.x0, r.x1, r.y0, r.y1, L.FLOOR_Z, r.z1)
    return [(n, q) for n, q in boxes if q[1] - q[0] > 1e-4 and q[3] - q[2] > 1e-4 and q[5] - q[4] > 1e-4]


SOFT = {'wall-sconce', 'table-lamp', 'canteen-mug', 'canteen-ladle', 'canteen-pot'}   # small, or standing on another
BACK = .15                                          # a seat's back slab, along the side away from where it faces


def furniture_boxes(c):
    """One box per floor-standing placement, from its footprint and the contract's height; seating is a block up to
    its seat height (where the seated marker rests) and a back slab up to its full height."""
    spec = {a['id']: a for a in L.contract()['assets']}
    out = []
    for p in c.placements:
        if p.z - L.FLOOR_Z >= .05 or p.asset in SOFT:
            continue
        x0, x1, y0, y1 = L.footprint(p)
        h = L.asset_dims(p.asset)[2]
        seat = spec[p.asset].get('seat_height_m')
        if not seat:
            out.append((p.id, (x0, x1, y0, y1, L.FLOOR_Z, L.FLOOR_Z + h)))
            continue
        out.append((p.id, (x0, x1, y0, y1, L.FLOOR_Z, L.FLOOR_Z + seat)))
        fx, fy = round(np.sin(np.radians(p.yaw))), round(-np.cos(np.radians(p.yaw)))   # the way it faces (0 = -Y)
        back = {(1, 0): (x0, x0 + BACK, y0, y1), (-1, 0): (x1 - BACK, x1, y0, y1),
                (0, 1): (x0, x1, y0, y0 + BACK), (0, -1): (x0, x1, y1 - BACK, y1)}[(fx, fy)]
        out.append((f'{p.id}-back', (*back, L.FLOOR_Z + seat, L.FLOOR_Z + h)))
    return out


def tender_collision_boxes(c):
    hw, (ta, tb), (z0, z1) = L.TENDER_HALF, L.TENDER_TANK, L.TENDER_TANK_Z
    lx0, lx1, ly, lz = L.TENDER_LOCKER
    boxes = [('floor', (tb, L.TENDER_FALL_PLATE, -hw + .10, hw - .10, L.FLOOR_Z - .20, L.FLOOR_Z)),
             ('tank', (ta, tb, -hw, hw, z0, L.TENDER_COPING_Z)),
             ('frames', (-L.TENDER_HEADSTOCK, L.TENDER_HEADSTOCK, -1.45, 1.45, .30, z0))]
    for side, sy in (('l', 1), ('r', -1)):
        y0, y1 = sorted((sy * ly, sy * hw))
        boxes.append((f'locker-{side}', (lx0, lx1, y0, y1, L.FLOOR_Z, lz)))
        y0, y1 = sorted((sy * (hw - .10), sy * hw))
        boxes.append((f'handrail-{side}', (lx1, L.TENDER_HEADSTOCK, y0, y1, L.FLOOR_Z, L.FLOOR_Z + 1.20)))
    return boxes


def loco_collision_boxes(c):
    F = L.FLOOR_Z
    hw, cin = L.LOCO_HALF, L.CAB_IN
    (ca, cb), ce = L.CAB, L.CAB_ENTRY
    bx = L.BACKHEAD_X
    (b0, b1, br, bz), (s0, s1, sr) = L.BOILER, L.SMOKEBOX
    boxes = [('floor', (ca, cb, -cin, cin, F - .20, F)),
             ('backhead', (bx, cb, -L.FIREBOX_HW, L.FIREBOX_HW, F, L.FIREBOX_TOP)),
             ('cab-roof', (ca - .25, cb, -hw, hw, L.CAB_TOP, L.CAB_ROOF)),
             ('boiler', (b0, s1, -br - .1, br + .1, L.RUNNING_BOARD_Z - .05, bz + br + .3)),
             ('running-gear', (-5.0, L.LOCO_BEAM + .14, -hw, hw, .20, L.RUNNING_BOARD_Z))]
    for side, sy in (('l', 1), ('r', -1)):
        y0, y1 = sorted((sy * cin, sy * hw))
        boxes.append((f'cab-side-{side}', (ce, cb, y0, y1, F, L.CAB_TOP)))
        boxes.append((f'cab-front-{side}', (cb - .06, cb, *sorted((sy * L.FIREBOX_HW, sy * hw)), F, L.CAB_TOP)))
    for r in c.reservations:
        boxes.append((r.name, (r.x0, r.x1, r.y0, r.y1, r.z0, r.z1)))
    return boxes


# --- checks: the collision against the plan, as a player capsule meets it ----------------------------------------
F = L.FLOOR_Z
STEP_UP = .45          # UE MaxStepHeight: anything lower than this does not stop a capsule
PERCH = .08            # a capsule stays up while its centre is this close to a floor edge
SHELL = ('floor', 'ceiling', 'side-', 'end-', 'balcony-floor', 'railing', 'gangway-')
SOFT_ASSETS = SOFT


def _cover(rect, boxes, z):
    """Share of a plan rectangle covered by boxes that span height z above the floor (5 cm raster)."""
    x0, x1, y0, y1 = rect
    xs = np.arange(x0 + .025, x1, .05); ys = np.arange(y0 + .025, y1, .05)
    if not len(xs) or not len(ys):
        return 1.
    X, Y = np.meshgrid(xs, ys, indexing='ij'); hit = np.zeros(X.shape, bool)
    for _, b in boxes:
        if b[4] <= F + z <= b[5]:
            hit |= (X >= b[0]) & (X <= b[1]) & (Y >= b[2]) & (Y <= b[3])
    return hit.mean()


def _visual_rects(c):
    """Plan rectangles of everything visible that a box may stand for: placements, reservations with a fitting."""
    out = [L.footprint(p) for p in c.placements if p.z - F < .05]
    out += [(b.x0, b.x1, b.y0, b.y1) for b in c.reservations if b.kind in MODELLED]
    return out


def _grid(c, boxes, radius, step=.025):
    b = c.body
    x0, x1 = b.buffer_a, b.buffer_b
    xs = np.arange(x0 + step / 2, x1, step); ys = np.arange(-L.HALF - .3, L.HALF + .3, step)
    X, Y = np.meshgrid(xs, ys, indexing='ij')
    floor = np.zeros(X.shape, bool); free = np.ones(X.shape, bool)
    for _, q in boxes:
        if abs(q[5] - F) < .03 and q[4] < F:
            floor |= (X >= q[0] - PERCH) & (X <= q[1] + PERCH) & (Y >= q[2] - PERCH) & (Y <= q[3] + PERCH)
        if q[5] > F + STEP_UP and q[4] < F + A.tallest():
            dx = np.maximum(np.maximum(q[0] - X, 0.), X - q[1]); dy = np.maximum(np.maximum(q[2] - Y, 0.), Y - q[3])
            free &= dx * dx + dy * dy >= radius * radius
    return xs, ys, floor, free


def _flood(mask, seed):
    seen = np.zeros(mask.shape, bool); stack = [seed] if mask[seed] else []
    for s in stack:
        seen[s] = True
    while stack:
        i, j = stack.pop()
        for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if 0 <= a < mask.shape[0] and 0 <= b < mask.shape[1] and mask[a, b] and not seen[a, b]:
                seen[a, b] = True; stack.append((a, b))
    return seen


def check_collision(c, boxes):
    bad = []
    # 1. every solid thing a player can walk into has collision over >= 85 % of its plan, at knee height
    for p in c.placements:
        if p.z - F < .05 and p.asset not in SOFT_ASSETS:
            share = _cover(L.footprint(p), boxes, .30)
            if share < .85:
                bad.append(f'{p.id} ({p.asset}) has collision over {share:.0%} of its footprint')
    for b in c.reservations:
        if b.kind in MODELLED and b.z0 - F < 1.0:
            share = _cover((b.x0, b.x1, b.y0, b.y1), boxes, (b.z0 + b.z1) / 2 - F)
            if share < .85:
                bad.append(f'{b.name} ({b.kind}) has collision over {share:.0%} of its box')
    # 2. no invisible blocks: a non-shell box must stand over something visible
    rects = _visual_rects(c)
    fixed = {b.name for b in c.reservations} | {p.id for p in c.placements}
    for part, q in boxes:
        if part not in fixed:                                   # shell, walls, the engine's body: not checked here
            continue
        area = (q[1] - q[0]) * (q[3] - q[2])
        seen = sum(max(0., min(q[1], r[1]) - max(q[0], r[0])) * max(0., min(q[3], r[3]) - max(q[2], r[2])) for r in rects)
        if seen < .6 * area:
            bad.append(f'collision {part} has nothing visible under {1 - seen / area:.0%} of it')
    # 3. on the collision alone, the widest player reaches every goal and never walks off a floor edge
    radius = max(p[2] for p in A.players())
    xs, ys, floor, free = _grid(c, boxes, radius)
    cell = lambda x, y: (int(np.searchsorted(xs, x)), int(np.searchsorted(ys, y)))
    seen = _flood(floor & free, cell(*L.start(c)))
    for g, (x, y) in L.goals(c).items():
        if not seen[cell(x, y)]:
            bad.append(f'{g} unreachable on collision')
    edge = np.zeros_like(seen); hole = free & ~floor
    edge[1:] |= seen[:-1] & hole[1:]; edge[:-1] |= seen[1:] & hole[:-1]
    edge[:, 1:] |= seen[:, :-1] & hole[:, 1:]; edge[:, :-1] |= seen[:, 1:] & hole[:, :-1]
    if edge.any():
        i, j = np.nonzero(edge)
        bad.append(f'{len(i)} floor-edge cells with no wall, e.g. at ({xs[i[0]]:.2f}, {ys[j[0]]:.2f})')
    # 4. gangways: floor to the buffer line and closed sides and top, so two coaches' boxes meet at the buffers
    for s in (-1, 1):
        if c.body.end(s) != 'gangway':
            continue
        bf, fx = c.body.buffer(s), c.body.face(s)
        mid = (fx + bf) / 2
        hw = L.GANGWAY_W / 2 + .04
        need = {'floor': (mid, 0., F - .05), 'side+': (mid, hw + .03, F + 1.), 'side-': (mid, -hw - .03, F + 1.),
                'roof': (mid, 0., F + L.GANGWAY_H + .10)}
        for what, (x, y, z) in need.items():
            if not any(q[0] <= x <= q[1] and q[2] <= y <= q[3] and q[4] <= z <= q[5] for _, q in boxes):
                bad.append(f'gangway {"ab"[s > 0]}: no {what} collision between the end wall and the buffers')
    # 5. locked gangways are shut by collision (a box named gangway-lock-a/b over the end-wall opening)
    for v, door in A.locked_gangways():
        if v == c.name and not any(p == f'gangway-lock-{door[-1]}' for p, _ in boxes):
            bad.append(f'{door} is locked for passengers but its opening is free in collision')
    # 6. every seat sits on (or up to 2 cm above) a collision top, 0.40-0.50 m above the floor
    for st in c.seats:
        tops = [q[5] for _, q in boxes if q[0] <= st.x <= q[1] and q[2] <= st.y <= q[3] and q[5] <= st.z + .02]
        if not tops or st.z - max(tops) > .06:
            bad.append(f'seat {st.id}: no collision top under it')
        elif c.name not in ('locomotive',) and not .40 <= st.z - F <= .50:
            bad.append(f'seat {st.id}: sitting height {st.z - F:.2f} m')
    # 7. a roof lookout's well is open in the ceiling collision
    if c.body.cupola:
        x0, x1 = c.body.cupola
        if any(p == 'ceiling' and q[0] < x1 - .1 and q[1] > x0 + .1 and q[2] < 0 < q[3] for p, q in boxes):
            bad.append('the ceiling collision closes the lookout well')
    return bad
