"""Belmonte's street furniture is good to grind: collision follows the drawn tops.

Paul's to-do: the bench's hull stopped at the seat (0.44 m) under a 0.86 m backrest, the planters' at 0.50 m, the
field walls' hull was a box 19 cm proud of the battered stone at its top, and no Belmonte edge was registered as a
grind line at all. world.belmonte now generates the furniture's collision from its drawn tops (belmonte/furniture.py)
and its grind lines come from that collision (belmonte/skate.py, test_belmonte_skate.py). These checks hold the
mechanism to the general rule on every prop it covers: the drawing inside the collision, planar tops within
tolerance, closed outward columns, and wall runs whose top has no gap or step at a join.
"""
from functools import lru_cache
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from belmonte import build, collision, furniture, source  # noqa: E402

MANIFEST = source.manifest()
ENTRIES = {m['name']: m for m in MANIFEST['meshes'] if furniture.is_furniture(m['name'])}
NAMES = sorted(ENTRIES)

@lru_cache(maxsize=None)
def generated(name):
    return furniture.generate(ENTRIES[name], run=furniture.run_axis(MANIFEST, ENTRIES[name]))


def segment_hits(faces, start, end, eps=1e-3):
    """Where each segment start -> end first meets the faces, as a fraction of its length (nan where it does not)."""
    start, end = np.atleast_2d(start), np.atleast_2d(end)
    d = end - start
    a, b, c = faces[:, 0], faces[:, 1], faces[:, 2]
    e1, e2 = b - a, c - a
    p = np.cross(d[:, None], e2[None])
    det = (p * e1[None]).sum(-1)
    det = np.where(np.abs(det) < 1e-12, np.nan, det)
    s = start[:, None] - a[None]
    u = (s * p).sum(-1) / det
    q = np.cross(s, e1[None])
    v = (q * d[:, None]).sum(-1) / det
    t = (q * e2[None]).sum(-1) / det
    hit = (u >= -eps) & (v >= -eps) & (u + v <= 1 + eps) & (t >= 0) & (t <= 1)
    t = np.where(hit, t, np.inf).min(1)
    return np.where(np.isfinite(t), t, np.nan)


def test_every_furniture_kind_is_in_the_scene():
    assert set(NAMES) == {'SM_BM_BP_Bench', 'SM_BM_BP_StoneBench', 'SM_BM_BP_StonePlanter_A', 'SM_BM_BP_StonePlanter_B',
                          'SM_BM_BVV_StoneWall', 'SM_BM_BE_Trough', 'SM_BM_BE_MountingBlock', 'SM_BM_BHip_HayBale',
                          'SM_BM_BH_Fontanella', 'SM_BM_BH_FountainPiazza'}
    assert all('collision' in ENTRIES[name] for name in NAMES)     # each replaces a committed hull


@pytest.mark.parametrize('name', NAMES)
def test_collision_covers_what_is_drawn(name):
    item = generated(name)
    points = np.unique(np.round(item.drawn.reshape(-1, 3), 5), axis=0)
    assert furniture.outside_m(item, points).max() <= furniture.TOP_TOL_M + 1e-3, name
    # Tops are planes within tolerance of the drawn tops they replace, never a guessed height.
    for plate, _ in item.columns:
        if plate is not None:
            drawn = plate.faces.reshape(-1, 3)
            assert np.abs(plate.z(drawn[:, :2]) - drawn[:, 2]).max() <= furniture.TOP_TOL_M + 1e-3, name


def test_reported_hulls_now_reach_the_drawn_tops():
    bench = generated('SM_BM_BP_Bench')
    tops = sorted(float(p.z(p.poly).max()) for p, _ in bench.columns if p is not None)
    assert max(z for z in tops if z < .6) == pytest.approx(.477, abs=.01)   # the seat, not the 0.44 m hull under it
    assert tops[-1] >= .82                                  # the backrest has collision up to its top rail
    wall = generated('SM_BM_BVV_StoneWall')
    top = [p for p, _ in wall.columns if p is not None]
    poly = top[0].poly
    edge = np.roll(poly, -1, 0) - poly
    normal = np.stack([edge[:, 1], -edge[:, 0]], 1) / np.linalg.norm(edge, axis=1)[:, None]
    assert len(top) == 1 and min(np.ptp(poly @ n) for n in normal) == pytest.approx(.24, abs=.01)   # the battered top


@pytest.mark.parametrize('name', NAMES)
def test_columns_are_closed_convex_and_wound_outward(name):
    item = generated(name)
    for plate, solid in item.columns:
        if plate is None:
            continue
        keys, index = np.unique(np.round(solid.reshape(-1, 3), 4), axis=0, return_inverse=True)
        tri = index.reshape(-1, 3)
        edges = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
        directed = {tuple(e) for e in edges}
        assert all((b, a) in directed for a, b in directed), (name, 'open column')
        normal, offset = furniture.planes(solid)
        assert (keys @ normal.T - offset).max() < 1e-3, (name, 'not convex')
        assert ((solid.mean(1) - keys.mean(0)) * normal).sum(1).min() > 0, (name, 'faces wound inward')


@pytest.mark.parametrize('name', NAMES)
def test_no_seams_inside_the_collision(name):
    """In game the board stalled crossing the fountain rim's piece seams: the faces between two columns must go."""
    item = generated(name)
    solids = [solid for plate, solid in item.columns if plate is not None]
    faces = item.faces
    covering = sum(furniture.inside(solid, faces.reshape(-1, 3), furniture.SEAM_M).reshape(-1, 3).all(1) for solid in solids)
    assert covering.max() <= 1, name
    if name in ('SM_BM_BVV_StoneWall', 'SM_BM_BP_Bench', 'SM_BM_BP_StonePlanter_A'):
        assert all(plate is not None for plate, _ in item.columns), name     # nothing left to collide as drawn


def test_generated_collision_round_trips_outward(tmp_path):
    item = generated('SM_BM_BP_Bench')
    path = tmp_path / 'SM_BM_BP_Bench_Collision.glb'
    collision.write_glb(path, item.faces)
    back = source.triangles(path)
    assert np.allclose(back, item.faces, atol=1e-5)
    volume = np.einsum('ij,ij->i', back[:, 0], np.cross(back[:, 1], back[:, 2])).sum() / 6
    assert volume > 0                                       # outward: a positive enclosed volume


def test_wall_runs_have_a_level_unbroken_top_through_every_join():
    """In game the board slowed crossing a field wall join. Sections meet with up to JOIN_CM of gap or overlap; their
    collision reaches RUN_OVERLAP_M past each drawn end, so through every join the top has no hole and no step over
    5 mm, every centimetre across the top both sections share (its grind line joins: test_belmonte_skate.py)."""
    name = 'SM_BM_BVV_StoneWall'
    item = generated(name)
    axis, lo, hi, _ = item.run
    assert axis == 0
    top = max(p.z(p.poly).max() for p in item.plates)
    transforms = [p['transform'] for p in MANIFEST['placements'] if p['asset'] == ENTRIES[name]['source_asset']]
    starts = np.array([furniture.to_region_cm(t, [[lo, 0, top]])[0] for t in transforms])
    ends = np.array([furniture.to_region_cm(t, [[hi, 0, top]])[0] for t in transforms])
    gap = np.linalg.norm(ends[:, None] - starts[None], axis=-1)
    joins = np.argwhere(gap <= furniture.JOIN_CM)
    assert len(joins) > 100
    s = np.arange(-.2, .201, .01)
    for i, j in joins:
        faces = np.concatenate([furniture.to_region_cm(transforms[k], item.faces.reshape(-1, 3)).reshape(-1, 3, 3)
                                for k in (i, j)])
        # Across the top both sections share: one placement sits up to a few cm aside of the other.
        u = (ends[i] - starts[i])[:2] / np.linalg.norm((ends[i] - starts[i])[:2])
        aside = abs(u[0] * (starts[j] - ends[i])[1] - u[1] * (starts[j] - ends[i])[0]) / 100
        shared = .12 - aside - .01
        for lateral in (-shared, 0., shared):
            local = np.c_[hi + s, np.full(len(s), lateral), np.full(len(s), top)]
            at = furniture.to_region_cm(transforms[i], local)
            t = segment_hits(faces, at + [0, 0, 30], at - [0, 0, 30])
            assert not np.isnan(t).any(), (i, j, 'hole in the top at the join')
            rise = np.diff(at[:, 2] + 30 - 60 * t)            # cm per cm along the run, on a slope
            assert np.abs(rise - np.median(rise)).max() <= .5, (i, j, 'step at the join', (rise - np.median(rise)).round(2).tolist())


def test_build_writes_furniture_collision(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'OUT', tmp_path)
    (tmp_path / 'glb').mkdir()
    entry = dict(ENTRIES['SM_BM_BP_StoneBench'])
    report = build.furniture_collision(entry, source.LIBRARY / entry['path'], MANIFEST)
    assert entry['collision']['generated'] and (tmp_path / entry['collision']['path']).exists()
    assert report['drawn_outside_m'] == 0 and report['triangles'] == len(source.triangles(tmp_path / entry['collision']['path']))
