"""Crater Park's tunnels kept open (pure numpy, native frame: metres, y up).

The foundation blocks under the riding pieces were made solid up to the top of the pieces over them, so the one
round tunnel was filled: its bore held the block's solid, and the rider met its flat end. carve cuts the faces
reaching into a bore (of the pieces tunnels finds) out of the render and the collision.
"""
import math

import numpy as np

from craterpark import grind

TUBE = 2.               # metres from a tunnel's floor to its roof at least
TUBE_REACH = 12.        # metres to a tunnel's wall at most, every way
TUBE_SIDES = 2          # horizontal lines through a point in a tunnel meeting its wall both ways (its ends are open)
TUBE_RAYS = 5           # of eight horizontal directions from a point near a tunnel's open end, meeting its wall
PROBE = 2.              # metres between the points that find which pieces close round a bore (tunnels)
SPLIT = .5              # metres across: a face reaching into a bore is split down to parts this small (carve)
PAIRS = 2_000_000       # ray-face pairs per batch at most


def ray_distances(origins, direction, triangles, reach):
    """The distance from each of the `origins` (k, 3) along `direction` (3,) to the nearest of the `triangles` (m, 3, 3),
    inf where none lies within `reach`."""
    out = np.full(len(origins), np.inf)
    if not len(triangles):
        return out
    e1 = triangles[:, 1] - triangles[:, 0]; e2 = triangles[:, 2] - triangles[:, 0]
    p = np.cross(direction, e2); det = (e1 * p).sum(1)
    ok = np.abs(det) > 1e-12; inv = 1 / np.where(ok, det, 1.)
    step = max(1, PAIRS // max(len(triangles), 1))
    for i in range(0, len(origins), step):
        s = origins[i:i + step, None] - triangles[None, :, 0]
        u = (s * p).sum(-1) * inv; q = np.cross(s, e1); v = (q * direction).sum(-1) * inv; t = (e2 * q).sum(-1) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-3) & (t < reach)
        out[i:i + step] = np.where(hit, t, np.inf).min(1)
    return out


def in_bore(points, pieces):
    """Mask of the `points` (k, 3) in the space a riding piece closes round, a tunnel's bore: one of the `pieces`
    [(m, 3, 3)] lies over and under the point (TUBE apart) and round it, within TUBE_REACH: along TUBE_SIDES of four
    horizontal lines through it on both sides, or, near an open end, along TUBE_RAYS of eight horizontal directions;
    and open along at least one of them (the inside of a closed block is no bore)."""
    mask = np.zeros(len(points), bool)
    up, down = np.array([0., 1., 0.]), np.array([0., -1., 0.])
    flat = [np.array([math.cos(a), 0., math.sin(a)]) for a in np.radians(np.arange(0, 360, 45))]
    for piece in pieces:
        t = piece.astype('f8'); lo, hi = t.min((0, 1)), t.max((0, 1))
        near = np.flatnonzero(((points > lo) & (points < hi)).all(1) & ~mask)
        if not len(near):
            continue
        y = points[near, 1]; between = grind.heights(t)               # cheap first: a face over and under at all
        near = near[between(points[near], y + 1e-3, y + TUBE_REACH) & between(points[near], y - TUBE_REACH, y - 1e-3)]
        if not len(near):
            continue
        c = points[near]
        over = ray_distances(c, up, t, TUBE_REACH); under = ray_distances(c, down, t, TUBE_REACH)
        maybe = np.isfinite(over) & np.isfinite(under) & (over + under > TUBE)
        if not maybe.any():
            continue
        c = c[maybe]
        hits = np.stack([np.isfinite(ray_distances(c, d, t, TUBE_REACH)) for d in flat], 1)
        # Open along some way (a tunnel's ends), not the inside of a closed block.
        closed = (((hits[:, :4] & hits[:, 4:]).sum(1) >= TUBE_SIDES) | (hits.sum(1) >= TUBE_RAYS)) & ~hits.all(1)
        mask[near[np.flatnonzero(maybe)[closed]]] = True
    return mask


def tunnels(pieces, step=PROBE):
    """The `pieces` [(m, 3, 3)] that close round a bore somewhere, each with the points of a `step`-metre grid over it
    that lie in its bore (in_bore): [(piece, points)]."""
    found = []
    for piece in pieces:
        lo, hi = piece.min((0, 1)), piece.max((0, 1))
        axes = [np.arange(lo[k] + step / 2, hi[k], step) for k in range(3)]
        grid = np.stack(np.meshgrid(*axes, indexing='ij'), -1).reshape(-1, 3)
        inside = grid[in_bore(grid, [piece])] if len(grid) else grid
        if len(inside):
            found.append((piece, inside))
    return found


def carve(triangles, bores, split=SPLIT):
    """The `triangles` (n, 3, 3) cut out of the tunnels' bores (in_bore), `bores` as tunnels gives them. A face reaching
    into a bore is split in four, again and again near the bore, down to `split` metres; the parts whose centre lies in
    the bore are left out and the rest kept, so a block's wall keeps its solid round the portal and a long face crossing
    the bore keeps its ends. Returns (cut, parent, corners): the mask of the faces cut, and for each kept part its face's
    index and its corners' barycentric coordinates on that face (m, 3, 3)."""
    cut = np.zeros(len(triangles), bool); parents, corners = [], []
    halves = np.array([[[1, 0, 0], [.5, .5, 0], [.5, 0, .5]], [[.5, .5, 0], [0, 1, 0], [0, .5, .5]],
                       [[.5, 0, .5], [0, .5, .5], [0, 0, 1]], [[.5, .5, 0], [0, .5, .5], [.5, 0, .5]]])
    for piece, inside in bores:
        reach = inside.min(0) - PROBE, inside.max(0) + PROBE
        near = np.flatnonzero(((triangles.max(1) > reach[0]) & (triangles.min(1) < reach[1])).all(1) & ~cut)
        if not len(near):
            continue
        lo, hi = reach[0] - TUBE_REACH, reach[1] + TUBE_REACH
        piece = piece[((piece.max(1) > lo) & (piece.min(1) < hi)).all(1)]
        parent, bary = near, np.repeat(np.eye(3)[None], len(near), 0)
        kept, dropped = [], np.zeros(len(triangles), bool)
        while len(parent):
            c = np.einsum('kij,kjd->kid', bary, triangles[parent].astype('f8'))
            a, b = c.min(1), c.max(1)
            touch = np.zeros(len(c), bool)
            for i in range(0, len(c), 4096):        # a part whose box, PROBE wider, holds a bore point is near the bore
                touch[i:i + 4096] = ((inside[None] > a[i:i + 4096, None] - PROBE)
                                     & (inside[None] < b[i:i + 4096, None] + PROBE)).all(-1).any(1)
            small = np.linalg.norm(b - a, axis=1) <= split
            test = np.flatnonzero(touch & small)
            gone = np.zeros(len(c), bool); gone[test] = in_bore(c[test].mean(1), [piece])
            dropped[parent[gone]] = True
            keep = ~touch | (small & ~gone)
            kept.append((parent[keep], bary[keep]))
            more = touch & ~small
            parent = np.repeat(parent[more], 4)
            bary = np.einsum('hij,kjl->khil', halves, bary[more]).reshape(-1, 3, 3)
        cut |= dropped
        for p, b in kept:
            mine = dropped[p]
            parents.append(p[mine]); corners.append(b[mine])
    if not parents:
        return cut, np.zeros(0, 'i8'), np.zeros((0, 3, 3))
    return cut, np.concatenate(parents), np.concatenate(corners)
