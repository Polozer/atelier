"""Belmonte's grind lines come from the town's own geometry: Crater Park's lip finder over the collision the board
rides, and the tops of the bars a skater can reach (belmonte/skate.py).

Paul's decisions (2026-10-21): the wooden bench loses its armrests so its seat grinds, and every bar that looks like a
grind or slide bar grinds (shop-window ledges, stall shelves, terrace rails). These checks hold the lines to the
general rules on real Belmonte props, placed on a level street.
"""
from functools import lru_cache
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from belmonte import build, collision, furniture, skate, source  # noqa: E402

MANIFEST = source.manifest()
ENTRIES = {m['name']: m for m in MANIFEST['meshes']}
BOX = (-30., -30., 30., 30.)
STREET = np.array([[[-40., -40., 0.], [40., -40., 0.], [40., 40., 0.]], [[-40., -40., 0.], [40., 40., 0.], [-40., 40., 0.]]])


@lru_cache(maxsize=None)
def columns(name):
    return furniture.generate(ENTRIES[name], run=furniture.run_axis(MANIFEST, ENTRIES[name])).faces


def over_street(line):
    return float(np.median(np.asarray(line)[:, 2]))


def lines_of(name):
    """The lips of one prop's collision standing on a level street at the origin."""
    return skate.lips(np.concatenate([columns(name), STREET]), [BOX], over_street)


def length(line):
    return float(np.linalg.norm(np.diff(line, axis=0), axis=1).sum())


def test_the_bench_has_no_armrests():
    faces = source.triangles(source.LIBRARY / ENTRIES['SM_BM_BP_Bench']['path'])
    assert len(faces) == ENTRIES['SM_BM_BP_Bench']['triangles'] == 136
    points = faces.reshape(-1, 3)
    # Nothing stands on the seat at its ends any more, in front of the backrest.
    over_seat = (np.abs(points[:, 0]) > .7) & (points[:, 1] > -.18) & (points[:, 2] > .5)
    assert not over_seat.any()


def test_the_bench_seat_is_a_lip_and_its_backrest_top_a_bar():
    seat = [l for l in lines_of('SM_BM_BP_Bench') if abs(l[:, 2].mean() - .477) < .02]
    assert seat and max(length(l) for l in seat) >= 1.4                  # the front edge, end to end
    bars = skate.mesh_bars(ENTRIES['SM_BM_BP_Bench'])
    top = max(bars, key=lambda b: b.top[0, 2])
    assert top.top[0, 2] >= .82 and np.linalg.norm(top.top[1] - top.top[0]) >= 1.7


def test_the_stone_bench_offers_both_edges():
    found = [l for l in lines_of('SM_BM_BP_StoneBench') if length(l) >= 1.7]
    assert len(found) == 2 and all(abs(l[:, 2].mean() - .49) < .02 for l in found)


def test_lines_stop_at_a_skaters_reach():
    tall = collision._BOX.copy()
    corners = collision._CORNERS * [4., .3, skate.REACH_M + .5] - [2., .15, 0.]
    high = skate.lips(np.concatenate([corners[tall], STREET]), [BOX], over_street)
    low = skate.lips(np.concatenate([(corners * [1, 1, .2])[tall], STREET]), [BOX], over_street)
    assert not high and len(low) == 2


def test_a_bar_collides_where_it_grinds(tmp_path, monkeypatch):
    """A bar's line lies on its box's top, and the box joins its mesh's collision, wound outward like the rest."""
    name = 'SM_BM_BT_blk_18'
    bars = skate.mesh_bars(ENTRIES[name])
    assert bars
    for bar in bars:
        lo, hi = bar.corners.min(0), bar.corners.max(0)
        assert np.all(bar.top >= lo - 1e-6) and np.all(bar.top <= hi + 1e-6) and np.allclose(bar.top[:, 2], hi[2])
        f = bar.faces()
        assert np.einsum('ij,ij->i', f[:, 0], np.cross(f[:, 1], f[:, 2])).sum() > 0
    monkeypatch.setattr(build, 'OUT', tmp_path)
    (tmp_path / 'glb').mkdir()
    hulls = source.LIBRARY / ENTRIES[name]['collision']['path']
    record = build.outward_hulls(hulls, bars)        # a building's generated shell takes them the same way
    assert len(source.triangles(tmp_path / record['path'])) == len(source.triangles(hulls)) + 12 * len(bars)


def test_a_market_stall_collides_as_drawn():
    """The stall's committed hull was one 2.2 m block over its counter and shelf: it collides as drawn instead, so
    the counter's edge is a lip and a skater rides between its posts."""
    assert skate.as_drawn('SM_BM_BP_Stall_A') and not skate.as_drawn('SM_BM_BP_Bench')
    faces, names = skate.slotted(ENTRIES['SM_BM_BP_Stall_A'])
    found = skate.lips(np.concatenate([faces[skate.hard(names)], STREET]), [BOX], over_street)
    assert any(abs(l[:, 2].mean() - .9) < .03 and length(l) >= 2.5 for l in found)


def test_wall_sections_join_into_one_line():
    """Field walls are 10 m sections laid end to end: their lips meet at every join and become one line."""
    name = 'SM_BM_BVV_StoneWall'
    placed = [p['transform'] for p in MANIFEST['placements'] if p['asset'] == ENTRIES[name]['source_asset']]
    item = furniture.generate(ENTRIES[name], run=furniture.run_axis(MANIFEST, ENTRIES[name]))
    axis, lo, hi, _ = item.run
    starts = np.array([collision.to_world(t, [[lo, 0, 0]])[0] for t in placed])
    ends = np.array([collision.to_world(t, [[hi, 0, 0]])[0] for t in placed])
    # Three sections in a row.
    gap = np.linalg.norm(ends[:, None] - starts[None], axis=-1)
    for a in range(len(placed)):
        b = int(gap[a].argmin())
        c = int(gap[b].argmin())
        if gap[a, b] < .07 and gap[b, c] < .07 and len({a, b, c}) == 3:
            break
    run = [placed[i] for i in (a, b, c)]
    faces = np.concatenate([skate.to_world(t, item.faces) for t in run])
    lo3, hi3 = faces.reshape(-1, 3).min(0), faces.reshape(-1, 3).max(0)
    box = (lo3[0] - 5, lo3[1] - 5, hi3[0] + 5, hi3[1] + 5)
    ground = STREET * [10, 10, 1] + [lo3[0], lo3[1], lo3[2] - .2]
    found = skate.lips(np.concatenate([faces, ground]), [box], lambda line: 1.)
    rails = furniture.join([{'id': str(k), 'kind': furniture.LEDGE, 'points': l * [100., -100., 100.]}
                            for k, l in enumerate(found)], skate.LINE_JOIN_CM)
    assert max(length(np.asarray(r['points']) / 100.) for r in rails) >= 29.
