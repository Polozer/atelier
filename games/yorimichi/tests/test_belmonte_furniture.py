"""Belmonte's street furniture is good to grind: collision follows the drawn tops and the grind lines qualify.

Paul's to-do: the bench's hull stopped at the seat (0.44 m) under a 0.86 m backrest, the planters' at 0.50 m, the
field walls' hull was a box 19 cm proud of the battered stone at its top, and no Belmonte edge was registered as a
grind line at all. world.belmonte now generates the furniture's collision from its drawn tops (belmonte/furniture.py)
and writes its grind lines to runtime.json. These checks hold the mechanism to the general rule on every prop it
covers: the drawing inside the collision, planar tops within tolerance, closed outward columns, and every grind line
on the collision and accepted by the skate plugin's own grind-surface probes.
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

# What a skater should find on each prop: (kind, least length m, height m) for every line it must offer.
EXPECTED = {
    'SM_BM_BP_Bench': [('ThinRail', 1.8, .83)],          # the seat's edges run under the armrests (below)
    'SM_BM_BP_StoneBench': [('Ledge', 1.9, .49)] * 2,
    'SM_BM_BP_StonePlanter_A': [('Ledge', 1.85, .50)] * 2,
    'SM_BM_BP_StonePlanter_B': [('Ledge', 1.85, .50)] * 2,
    'SM_BM_BVV_StoneWall': [('Ledge', 10., .92)] * 2,
    'SM_BM_BE_Trough': [('ThinRail', 2., .62)] * 2,
    'SM_BM_BE_MountingBlock': [('Ledge', 1.1, .75)] * 2 + [('Ledge', 1.1, .50), ('Ledge', 1.1, .25)],
    'SM_BM_BHip_HayBale': [('Ledge', 1., .42)] * 2,
    'SM_BM_BH_Fontanella': [('Ledge', 8., .80), ('Ledge', 10., .16)],
    'SM_BM_BH_FountainPiazza': [('Ledge', 27., 1.10), ('Ledge', 34., .32), ('Ledge', 37., .16)],
}


@lru_cache(maxsize=None)
def generated(name):
    item = furniture.generate(ENTRIES[name], run=furniture.run_axis(MANIFEST, ENTRIES[name]))
    return item, furniture.rails(item)


def test_every_furniture_kind_is_in_the_scene():
    assert set(NAMES) == set(EXPECTED)
    assert all('collision' in ENTRIES[name] for name in NAMES)     # each replaces a committed hull


@pytest.mark.parametrize('name', NAMES)
def test_collision_covers_what_is_drawn(name):
    item, _ = generated(name)
    points = np.unique(np.round(item.drawn.reshape(-1, 3), 5), axis=0)
    assert furniture.outside_m(item, points).max() <= furniture.TOP_TOL_M + 1e-3, name
    # Tops are planes within tolerance of the drawn tops they replace, never a guessed height.
    for plate, _ in item.columns:
        if plate is not None:
            drawn = plate.faces.reshape(-1, 3)
            assert np.abs(plate.z(drawn[:, :2]) - drawn[:, 2]).max() <= furniture.TOP_TOL_M + 1e-3, name


def test_reported_hulls_now_reach_the_drawn_tops():
    bench, _ = generated('SM_BM_BP_Bench')
    tops = sorted(float(p.z(p.poly).max()) for p, _ in bench.columns if p is not None)
    assert tops[0] == pytest.approx(.477, abs=.01)          # the seat, not the 0.44 m hull under it
    assert tops[-1] >= .82                                  # the backrest has collision up to its top rail
    wall, _ = generated('SM_BM_BVV_StoneWall')
    top = [p for p, _ in wall.columns if p is not None]
    assert len(top) == 1 and furniture.width(top[0].poly)[0] == pytest.approx(.24, abs=.01)   # the battered top


@pytest.mark.parametrize('name', NAMES)
def test_columns_are_closed_convex_and_wound_outward(name):
    item, _ = generated(name)
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
    item, _ = generated(name)
    solids = [solid for plate, solid in item.columns if plate is not None]
    faces = item.faces
    covering = sum(furniture.inside(solid, faces.reshape(-1, 3), furniture.SEAM_M).reshape(-1, 3).all(1) for solid in solids)
    assert covering.max() <= 1, name
    if name in ('SM_BM_BVV_StoneWall', 'SM_BM_BP_Bench', 'SM_BM_BP_StonePlanter_A'):
        assert all(plate is not None for plate, _ in item.columns), name     # nothing left to collide as drawn


def test_generated_collision_round_trips_outward(tmp_path):
    item, _ = generated('SM_BM_BP_Bench')
    path = tmp_path / 'SM_BM_BP_Bench_Collision.glb'
    collision.write_glb(path, item.faces)
    back = source.triangles(path)
    assert np.allclose(back, item.faces, atol=1e-5)
    volume = np.einsum('ij,ij->i', back[:, 0], np.cross(back[:, 1], back[:, 2])).sum() / 6
    assert volume > 0                                       # outward: a positive enclosed volume


@pytest.mark.parametrize('name', NAMES)
def test_grind_lines_qualify_under_the_plugin_rules(name):
    item, lines = generated(name)
    faces = np.concatenate([item.faces, furniture.GROUND])
    for rail in lines:
        pts = rail['points']
        assert furniture._length(pts) >= furniture.RAIL_MIN_M
        seg = np.diff(pts, axis=0)
        for a, b in zip(seg[:-1], seg[1:]):
            assert furniture.turn(a, b) <= furniture.RAIL_TURN_DEG, (name, 'kinked line')
        # Every 10 cm along it: on the collision, not blocked, the kind the plugin will find.
        for p, q in zip(pts[:-1], pts[1:]):
            n = max(1, int(np.ceil(np.linalg.norm(q - p) / furniture.RAIL_STEP_M)))
            samples = p + (q - p) * (np.arange(n + 1) / n)[:, None]
            kinds, on = furniture.classify(faces, samples, q - p)
            assert on.all(), (name, 'line off its collision')
            assert (kinds != furniture.IMPOSSIBLE).all(), (name, 'blocked line', kinds)
            assert furniture.clear(faces, samples, q - p).all(), (name, 'the deck would stop on something')
    found = sorted((r['kind'], furniture._length(r['points']), float(r['points'][:, 2].mean())) for r in lines)
    for kind, length, height in EXPECTED[name]:
        match = [f for f in found if f[0] == kind and f[1] >= length - .02 and abs(f[2] - height) < .02]
        assert match, (name, kind, length, height, found)
        found.remove(match[0])


def test_a_bench_seat_edge_is_no_line_where_the_armrests_stop_the_deck():
    """In game the board stalled 0.7 m into the bench's seat edge: its nose (45.6 cm ahead of the deck's centre) hit
    the armrest, which spans the seat's whole depth. Both seat edges fail the deck clearance near the armrests, so
    neither is offered as a line; the backrest's rail is the bench's grind, clear every 10 cm of its length."""
    item, lines = generated('SM_BM_BP_Bench')
    faces = np.concatenate([item.faces, furniture.GROUND])
    seat = [p for p in item.plates if abs(p.z(p.poly).max() - .477) < .01][0]
    for y in (seat.poly[:, 1].min(), seat.poly[:, 1].max()):
        x = np.arange(-.7, .71, furniture.RAIL_STEP_M)
        edge = np.c_[x, np.full(len(x), y), seat.z(np.c_[x, np.full(len(x), y)])]
        ok = furniture.clear(faces, edge, np.array([1., 0., 0.]))
        assert ok[np.abs(x) < .15].all() and not ok[np.abs(x) > .3].any()
    assert all(r['points'][:, 2].min() > .8 for r in lines)
    rail = lines[0]['points']
    x = np.arange(rail[:, 0].min(), rail[:, 0].max() + 1e-6, furniture.RAIL_STEP_M)
    samples = np.c_[x, np.full(len(x), rail[0, 1]), np.full(len(x), rail[0, 2])]
    kinds, on = furniture.classify(faces, samples, np.array([1., 0., 0.]))
    assert on.all() and (kinds != furniture.IMPOSSIBLE).all() and furniture.clear(faces, samples, np.array([1., 0., 0.])).all()


def test_placed_lines_join_wall_sections_and_follow_their_placements():
    data = source.manifest()
    lines = {name: generated(name)[1] for name in ('SM_BM_BVV_StoneWall', 'SM_BM_BP_Bench')}
    placed = furniture.placed_rails(data, lines)
    walls = [r for r in placed if r['id'].startswith('BVV_StoneWall')]
    sections = sum(1 for p in data['placements'] if p['asset'] == ENTRIES['SM_BM_BVV_StoneWall']['source_asset'])
    assert len(walls) < sections                            # sections meeting end to end are one line
    for rail in walls:
        seg = np.diff(np.asarray(rail['points']), axis=0)
        assert np.linalg.norm(seg, axis=1).max() <= 1000. + furniture.JOIN_CM, rail['id']
        for a, b in zip(seg[:-1], seg[1:]):                 # one continuous edge through every join
            assert furniture.turn(a, b) <= furniture.RAIL_TURN_DEG, rail['id']
    # A bench's line sits where collision.to_world puts the bench's own local point.
    index = next(i for i, p in enumerate(data['placements']) if p['asset'] == ENTRIES['SM_BM_BP_Bench']['source_asset'])
    rail = next(r for r in placed if r['id'] == f'BP_Bench_{index}_0')
    local = lines['SM_BM_BP_Bench'][0]['points']
    world = collision.to_world(data['placements'][index]['transform'], local)
    assert np.allclose(np.asarray(rail['points']) / [100., -100., 100.], world, atol=.002)


def test_wall_runs_have_a_level_unbroken_top_through_every_join():
    """In game the board slowed crossing a field wall join. Sections meet with up to JOIN_CM of gap or overlap; their
    collision reaches RUN_OVERLAP_M past each drawn end, so through every join the top has no hole and no step over
    5 mm, every centimetre across the top both sections share, and the run's line is one line through it."""
    name = 'SM_BM_BVV_StoneWall'
    item, lines = generated(name)
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
            t = furniture.segment_hits(faces, at + [0, 0, 30], at - [0, 0, 30])
            assert not np.isnan(t).any(), (i, j, 'hole in the top at the join')
            rise = np.diff(at[:, 2] + 30 - 60 * t)            # cm per cm along the run, on a slope
            assert np.abs(rise - np.median(rise)).max() <= .5, (i, j, 'step at the join', (rise - np.median(rise)).round(2).tolist())
    placed = furniture.placed_rails(MANIFEST, {name: lines})
    walls = [np.asarray(r['points']) for r in placed if r['id'].startswith('BVV_StoneWall')]
    for i, j in joins:                                       # the join is a point inside one line, not two ends
        for edge in (-.12, .12):
            p = furniture.to_region_cm(transforms[i], [[hi, edge, top]])[0]
            near = [w for w in walls if np.linalg.norm(w - p, axis=1).min() <= furniture.JOIN_CM]
            assert any(0 < np.linalg.norm(w - p, axis=1).argmin() < len(w) - 1 for w in near), (i, j, edge)


def test_build_writes_furniture_collision_and_rails(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'OUT', tmp_path)
    (tmp_path / 'glb').mkdir()
    entry = dict(ENTRIES['SM_BM_BP_StoneBench'])
    lines, report = build.furniture_collision(entry, source.LIBRARY / entry['path'], MANIFEST)
    assert entry['collision']['generated'] and (tmp_path / entry['collision']['path']).exists()
    assert report['drawn_outside_m'] == 0 and len(lines) == 2
