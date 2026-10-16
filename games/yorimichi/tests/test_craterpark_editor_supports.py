"""Editor-park supports: stone viaducts under every ramp, flush with its underside, clear of the pieces below."""
from pathlib import Path
import sys
import types

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
from craterpark.v2 import dsl, editor_supports as es  # noqa: E402


def sheet(pid, y, length=60., width=18., x0=0., z0=0., line='L1'):
    """A flat run along +x at height y, as the bridge would hand it over (a triangulated sheet plus stations)."""
    xs, zs = np.meshgrid(np.arange(0, length + .1, 2.), np.arange(-width / 2, width / 2 + .1, 3.))
    V = np.stack([x0 + xs.ravel(), np.full(xs.size, y), z0 + zs.ravel()], 1)
    nz, nx = xs.shape
    i = (np.arange(nz - 1)[:, None] * nx + np.arange(nx - 1)[None]).ravel()
    F = np.concatenate([np.stack([i, i + nx, i + 1], 1), np.stack([i + 1, i + nx, i + nx + 1], 1)])
    stations = [dict(d=float(d), x=x0 + d, y=y, z=z0, h=0., a=0., w=width - 2, wl={'h': 0., 'R': 1.}, wr={'h': 0., 'R': 1.},
                     deck=0.) for d in np.arange(0, length + .1, 1.)]
    return types.SimpleNamespace(mesh=types.SimpleNamespace(V=V, F=F), metadata=dict(id=pid, type='run', line=line, stations=stations))


GRID = dict(x0=-60., z0=-60., G=2., nx=150, nz=150)
FLAT = np.zeros(150 * 150, 'f4')


def vertices(parts):
    return np.concatenate([p.V for p in parts]) if parts else np.zeros((0, 3))


def test_high_piece_rides_on_an_arcade_flush_under_it():
    parts, summary = es.build([sheet('p1', 30., length=120.)], FLAT, GRID)
    assert summary['pieces'] == {'p1': 'viaduct'} and summary['piers'] >= 3 and summary['arches'] >= 2
    stone = {dsl.MATERIAL[es.STONE], dsl.MATERIAL[es.ROCK]}
    assert all(set(p.material.tolist()) <= stone and p.role[0] == dsl.ROLE[dsl.SIDE] for p in parts)
    V = vertices(parts)
    assert abs(V[:, 1].max() - (30. + es.EMBED)) < 1e-6, 'the stone meets the ramp in one line'
    assert V[:, 1].min() >= -es.SINK - 5.
    assert np.isfinite(V).all() and np.isfinite(np.concatenate([p.N for p in parts])).all()


def test_few_thick_piers_with_relief_not_a_forest():
    parts, summary = es.build([sheet('p1', 30., length=120.)], FLAT, GRID)
    assert 2 <= summary['piers'] <= 120. / es.SPAN_MIN
    assert summary['boulders'] >= summary['piers'] * 2, 'boulders round every pier foot'
    assert sum(len(p.F) for p in parts) < 25000
    V = vertices(parts)
    assert np.abs(V[:, 2]).max() > 8. + es.INSET + es.PROUD - .1, 'piers stand proud of the faces'



def test_low_run_rests_on_a_solid_wall():
    parts, summary = es.build([sheet('p1', 3.)], FLAT, GRID)
    assert summary['arches'] == 0 and summary['piers'] == 0 and summary['metres'] > 50.
    assert vertices(parts)[:, 1].max() <= 3. + es.EMBED + 1e-6


def test_the_arcade_lifts_clear_of_a_piece_below():
    high, low = sheet('high', 40., length=120.), sheet('low', 10., length=20., x0=50.)
    parts, _ = es.build([high, low], FLAT, GRID)
    V = vertices([p for p in parts if p.features[0] == 'high_supports'])
    over = (V[:, 0] > 50.5) & (V[:, 0] < 69.5) & (np.abs(V[:, 2]) < 8.5)
    assert over.any() and (V[over, 1] >= 10. + es.OVER - 1e-6).all(), 'stone stands on or runs through the lower piece'


def test_supports_are_deterministic():
    a, _ = es.build([sheet('p1', 30.)], FLAT, GRID)
    b, _ = es.build([sheet('p1', 30.)], FLAT, GRID)
    assert np.array_equal(vertices(a), vertices(b))


def box_deck(pid, top, a=8., w=11., bottom=-5.):
    """A solid deck as the bridge meshes it: a box from below the ground up to its top, here square to the axes."""
    V = np.array([(x, y, z) for y in (bottom, top) for x, z in ((-a, -w), (a, -w), (a, w), (-a, w))], 'f8')
    F = np.array([(4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4),
                  (3, 4, 7)])
    return types.SimpleNamespace(mesh=types.SimpleNamespace(V=V, F=F),
                                 metadata=dict(id=pid, type='deck', stations=[], params={'solid': True}))


def test_a_high_solid_deck_stands_on_a_timber_frame_with_a_torii_over_the_drop_in():
    ramp = sheet('ramp', 60., length=60., z0=0., x0=0.)
    ramp.metadata['type'] = 'rollin'                         # the drop-in: the torii stands over a roll-in only
    for st in ramp.metadata['stations']:                     # leaves the deck's +x side (x = 8) at its top
        st['x'] += 8.
    ramp.mesh.V[:, 0] += 8.
    parts, summary = es.build([box_deck('t', 60.), ramp], FLAT, GRID)
    assert summary['towers'] == ['t'] and summary['pieces']['t'] == 'tower'
    tower = [p for p in parts if p.features[0] == 't_tower']
    V = vertices(tower)
    assert V[:, 1].min() < 0. and V[:, 1].max() > 60. + es.TORII - .5, 'from below the ground to the torii and roofs'
    assert sum(len(p.F) for p in tower) < 20000
    by = {dsl.MATERIALS[p.material[0]]: p for p in tower}
    assert {es.ROCK, es.KEYAKI, es.IRON, es.VERMILION, es.TILE, es.TIMBER} <= set(by)
    torii = by[es.VERMILION].V[by[es.VERMILION].V[:, 1] > 60. + es.TORII - 3.]
    assert len(torii) and torii[:, 0].min() > 5., 'the torii stands over the drop-in (+x), not elsewhere'
    rail = by[es.VERMILION].V[(by[es.VERMILION].V[:, 1] > 60.) & (by[es.VERMILION].V[:, 1] < 61.5)]
    assert rail[:, 0].max() < 8.5 + es.RIM, 'no railing across the drop-in'
    frame = vertices([by[es.KEYAKI], by[es.ROCK]])
    reach = es.TOWER_POST * (es.PLINTH_WIDE * (1 + es.PLINTH_STEP * (es.PLINTH_COURSES - 1)) + es.STAGE_TENON + 1.)
    assert np.abs(frame[:, 0]).max() < 8. + reach and np.abs(frame[:, 2]).max() < 11. + reach, 'no flare past the deck'
    assert len(frame) and frame[:, 1].min() < 0. and frame[:, 1].max() > 55., 'posts from the ground up to the deck'


def test_a_low_solid_deck_stays_a_deck():
    parts, summary = es.build([box_deck('t', 3.)], FLAT, GRID)
    assert summary['towers'] == [] and not parts


def test_a_piece_whose_every_pier_would_stand_on_another_is_left_open():
    # rev 110's mega air landing: every pier position under the high run lies on the piece below it
    high, low = sheet('high', 40., length=120.), sheet('low', 10., length=120.)
    parts, summary = es.build([high, low], FLAT, GRID)
    V = vertices([p for p in parts if p.features[0] == 'high_supports'])
    assert not len(V) or (V[:, 1] >= 10. + es.OVER - 1e-6).all(), 'no stone through the piece below'
    assert np.isfinite(vertices(parts)).all()


def test_the_vert_drop_stands_on_a_timber_stage_on_stone_plinths():
    parts, summary = es.build([sheet('p1', 30., length=80., line='L2')], FLAT, GRID)
    assert summary['pieces'] == {'p1': 'stage'} and summary['piers'] == 0 and summary['posts'] >= 6
    assert {dsl.MATERIALS[p.material[0]] for p in parts} == {es.KEYAKI, es.ROCK, es.IRON}
    V = vertices(parts)
    assert V[:, 1].max() <= 30. + es.EMBED + 1e-6, 'the cap beams meet the ramp in one line'
    assert V[:, 1].min() >= -es.SINK - 1e-6 and np.isfinite(V).all()
    assert sum(len(p.F) for p in parts) < 20000
    a, _ = es.build([sheet('p1', 30., length=80., line='L2')], FLAT, GRID)
    assert np.array_equal(vertices(a), V), 'deterministic'


def test_no_timber_spans_the_gap_between_two_pieces():
    # the vert kicker and the reverse catch: each stands on its own frame, the air between them stays open
    kicker = sheet('kicker', 30., length=40., line='L2')
    catch = sheet('catch', 20., length=40., x0=70., line='L2')
    parts, summary = es.build([kicker, catch], FLAT, GRID)
    assert summary['pieces'] == {'kicker': 'stage', 'catch': 'stage'}
    V = vertices(parts)
    assert not ((V[:, 0] > 41.) & (V[:, 0] < 69.)).any(), 'nothing between the two pieces'


def test_a_stage_over_another_piece_is_carried_on_a_truss_from_outriggers():
    # rev 110's vert drop runs 100 m above its own reverse catch and U-turn: no post may stand on them
    high, low = sheet('high', 60., length=60., line='L2'), sheet('low', 10., length=60., width=30., line='L2')
    parts, summary = es.build([high, low], FLAT, GRID)
    assert summary['pieces']['high'] == 'stage'
    V = vertices([p for p in parts if p.features[0] == 'high_supports'])
    over = (V[:, 0] > -1.) & (V[:, 0] < 61.) & (np.abs(V[:, 2]) < 14.)
    assert over.any() and (V[over, 1] >= 60. - es.STAGE_TRUSS[1] - 3.).all(), 'nothing hangs down onto the piece below'
    assert (V[:, 1] < 0.).any() and (np.abs(V[V[:, 1] < 0., 2]) > 14.).all(), 'the outriggers stand clear beside it'


def test_other_lines_keep_their_stone_viaducts():
    _, summary = es.build([sheet('p1', 30., length=120.), sheet('p2', 30., length=120., z0=60., line='L2')], FLAT, GRID)
    assert summary['pieces'] == {'p1': 'viaduct', 'p2': 'stage'}


def test_no_stage_post_stands_beside_another_piece():
    # a U-turn bowl running past the frame: every post (and its plinth) keeps STAGE_CLEAR from it
    stage = sheet('stage', 40., length=80., line='L2')
    beside = sheet('bowl', 6., length=80., width=10., z0=16., line='L2')
    parts, _ = es.build([stage, beside], FLAT, GRID)
    rock = vertices([p for p in parts if p.features[0] == 'stage_supports' and dsl.MATERIALS[p.material[0]] == es.ROCK])
    assert len(rock) and (rock[:, 2] < 11. - es.STAGE_CLEAR + 1e-6).all(), 'plinths keep clear of the piece beside'


def test_a_roll_in_stands_on_timber_like_the_tower():
    roll = sheet('roll', 40., length=80.)
    roll.metadata['type'] = 'rollin'
    _, summary = es.build([roll], FLAT, GRID)
    assert summary['pieces'] == {'roll': 'stage'}
