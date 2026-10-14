"""Crater Park v2 starts: one per designed line, on its roll-in crest at the tower, ground-checked, in park.json's
Unreal terms (park.json `lines`). The game reads them for the menu's Crater Park tower buttons, the F8 shortcut and the
map's Crater Park stop (unreal/Source/Yorimichi/CraterParkTower.cpp). Pure numpy.

A spawn passes only when a downward ray from CLEARANCE over it meets collidable ground within GROUND_TOLERANCE of it
(no floating or buried start), the ground there is no steeper than MAX_SLOPE (the rider stands still), its yaw agrees
with the line's first path segment within FACING, and, given `deck_y`, the ground is the tower deck.

Yaw: `RideLine.spawn[1]` is theta degrees from native +x toward native +z, so forward is (cos theta, 0, sin theta). In
Unreal (x, z, y) that is the same angle, so the Unreal yaw is the park actor's yaw plus theta (r4's spawn is theta 0).
"""
import math

import numpy as np

from . import dsl

TOWER_DECK_Y = 40.          # native m: the tower deck at 720 m in the island (layout.md 4; island z = native y + 680)
GROUND_TOLERANCE = .5       # m
CLEARANCE = 2.              # m: the ray starts this far over the spawn; a face in between buries it
MAX_SLOPE = 10.             # degrees
FACING = 15.                # degrees


class SpawnError(ValueError):
    pass


def collidable(mesh):
    """(m, 3, 3) the faces the rider stands on in the game (the collision roles), native metres."""
    return mesh.triangles()[np.isin(mesh.role, [dsl.ROLE[r] for r in dsl.COLLISION_ROLE])]


def ground(triangles, x, z, top):
    """The highest face under the plan point (x, z) at or below `top`: (y, unit normal facing up) or None."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    den = (b[:, 2] - c[:, 2]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 2] - c[:, 2])
    ok = np.abs(den) > 1e-12                  # vertical faces have no plan area: a vertical ray never meets them
    den = np.where(ok, den, 1.)
    u = ((b[:, 2] - c[:, 2]) * (x - c[:, 0]) + (c[:, 0] - b[:, 0]) * (z - c[:, 2])) / den
    v = ((c[:, 2] - a[:, 2]) * (x - c[:, 0]) + (a[:, 0] - c[:, 0]) * (z - c[:, 2])) / den
    eps = 1e-9
    hit = ok & (u >= -eps) & (v >= -eps) & (u + v <= 1 + eps)
    y = u * a[:, 1] + v * b[:, 1] + (1 - u - v) * c[:, 1]
    hit &= y <= top
    if not hit.any():
        return None
    i = int(np.flatnonzero(hit)[np.argmax(y[hit])])
    n = np.cross(b[i] - a[i], c[i] - a[i]); n = n / np.linalg.norm(n)
    return float(y[i]), (n if n[1] >= 0 else -n)


def forward(theta):
    """The native plan direction (dx, dz) of a spawn yaw."""
    t = math.radians(theta)
    return np.array([math.cos(t), math.sin(t)])


def check(triangles, line, deck_y=None):
    """The ground under `line`'s spawn: {'ground_y', 'error_m', 'slope_deg', 'facing_deg'}, or SpawnError."""
    (x, y, z), theta = np.asarray(line.spawn[0], 'f8'), float(line.spawn[1])
    found = ground(triangles, x, z, y + CLEARANCE)
    if found is None:
        raise SpawnError(f'{line.name}: no ground under the spawn ({x:.2f}, {y:.2f}, {z:.2f})')
    hit, normal = found
    error = hit - y
    if abs(error) > GROUND_TOLERANCE:
        how = 'buried' if error > 0 else 'floating'
        raise SpawnError(f'{line.name}: the spawn is {how}: ground at y {hit:.2f}, {abs(error):.2f} m '
                         f'{"over" if error > 0 else "under"} it (tolerance {GROUND_TOLERANCE} m)')
    slope = math.degrees(math.acos(min(1., float(normal[1]))))
    if slope > MAX_SLOPE:
        raise SpawnError(f'{line.name}: the ground at the spawn is {slope:.1f} degrees steep (max {MAX_SLOPE})')
    if deck_y is not None and abs(hit - deck_y) > GROUND_TOLERANCE:
        raise SpawnError(f'{line.name}: the spawn ground is at y {hit:.2f}, not on the tower deck at {deck_y:.2f}')
    path = np.asarray(line.path, 'f8')[:, [0, 2]]
    steps = path[1:] - path[:1]
    far = np.flatnonzero(np.linalg.norm(steps, axis=1) > .5)
    facing = 0.
    if len(far):
        d = steps[far[0]] / np.linalg.norm(steps[far[0]])
        facing = math.degrees(math.acos(float(np.clip(d @ forward(theta), -1., 1.))))
        if facing > FACING:
            raise SpawnError(f'{line.name}: the spawn yaw {theta:.1f} faces {facing:.1f} degrees off the line '
                             f'(yaw is from native +x toward +z)')
    return {'ground_y': hit, 'error_m': error, 'slope_deg': slope, 'facing_deg': facing}


def entries(mesh, lines, placement, deck_y=None, labels=None):
    """park.json `lines`: [{'key', 'name', 'spawn': {'location_cm', 'yaw_deg'}, 'ground_error_m'}], one per line, each
    standing on its checked ground point. `labels` maps a line name to the name shown in the game (default: the name).
    Raises SpawnError for the first spawn that fails."""
    triangles = collidable(mesh)
    yaw = float(placement.unreal_transform()['yaw_deg'])
    result = []
    for line in lines:
        found = check(triangles, line, deck_y)
        x, _, z = np.asarray(line.spawn[0], 'f8')
        location = np.asarray(placement.to_unreal(np.array([x, found['ground_y'], z])), 'f8')
        result.append({'key': line.name, 'name': (labels or {}).get(line.name, line.name),
                       'spawn': {'location_cm': [round(float(v), 2) for v in location],
                                 'yaw_deg': round(((yaw + float(line.spawn[1]) + 180.) % 360.) - 180., 3)},
                       'ground_error_m': round(found['error_m'], 4)})
    return result
