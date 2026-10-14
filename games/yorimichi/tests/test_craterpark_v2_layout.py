"""Crater Park v2 layout (craterpark/v2/layout.py): the lines' geometry rules and that each line compiles."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
import itertools

from craterpark import placement
from craterpark.v2 import dsl
from craterpark.v2 import layout as L


def heading_at(line, s):
    return math.degrees(math.atan2(*L.Turtle.at(line.path, s)[1][::-1]))


@pytest.mark.parametrize('line', L.LINES, ids=lambda line: line.id)
def test_profile_matches_features(line):
    k = np.asarray(L.knots(line, .5))
    assert np.isfinite(k).all()
    assert k[0, 1] == pytest.approx(L.TOWER['y'])                  # every line starts on the tower deck
    for f in line.features:
        assert f.s1 > f.s0 and f.width > 0
        if f.kind not in ('gap', 'bowl_entry'):
            assert (np.abs(k[:, 0] - f.s0) < .6).any(), f.id       # the profile has ground where the feature starts
    for f in line.features:
        if f.kind == 'gap':
            assert not ((k[:, 0] > f.s0 + .6) & (k[:, 0] < f.s1 - .6)).any(), f'{f.id}: surface inside an open gap'


@pytest.mark.parametrize('line', L.LINES, ids=lambda line: line.id)
def test_jumps_are_straight(line):
    """A kicker has at least 20 m of straight run-in and its landing lies on the same straight (coordinator rule 5)."""
    for take, land in line.airs:
        _, k = L.feature(take); _, g = L.feature(land)
        h = [heading_at(line, s) for s in np.arange(k.s0 - 20., g.s1, 1.)]
        assert np.ptp(np.unwrap(np.radians(h))) < math.radians(.1), take


@pytest.mark.parametrize('line', L.LINES, ids=lambda line: line.id)
def test_lips_launch_forward(line):
    """Gap lips are launch ramps, never vert (owner): 30 degrees at most."""
    for take, _ in line.airs:
        _, f = L.feature(take)
        assert f.tag == 'takeoff' and f.params['lip_deg'] <= 30


@pytest.mark.parametrize('line', L.LINES, ids=lambda line: line.id)
def test_line_on_the_block(line):
    pts, _ = line.path.points(2.)
    isl = placement.native_to_island(np.c_[pts[:, 0], np.zeros(len(pts)), pts[:, 1]])
    assert placement.contains(isl[:, 0], isl[:, 1]).all()


def test_bowls_on_the_block_and_apart():
    for b in L.BOWLS:
        c = placement.native_to_island(np.array([b.centre[0], 0., b.centre[1]]))
        assert placement.contains(c[0], c[1]), b.id
        assert b.rim_y > b.floor_y and b.max_entry > 0
    for i, a in enumerate(L.BOWLS):
        for b in L.BOWLS[i + 1:]:
            gap = np.hypot(*np.subtract(a.centre, b.centre)) - (a.size[1] + b.size[1]) / 2
            assert gap > 5., (a.id, b.id)


def test_every_line_leads_somewhere():
    bowls = {b.id for b in L.BOWLS}
    for line in L.LINES:
        assert line.exit in bowls
    for link in L.LINKS:
        assert link.a in bowls and link.b in bowls


def test_crater_line_compiles_with_tags():
    built = L.build_line(L.L1, ground=-20.)
    tags = set(np.asarray(dsl.TAGS)[np.unique(built.mesh.tag)])
    assert {'takeoff', 'landing'} <= tags
    air = [c for c in built.checks if c.get('kind') == 'air']
    assert len(air) == 1 and air[0]['gap'] == pytest.approx(22.) and air[0]['lip_degrees'] == pytest.approx(30.)


def test_palette_is_pale():
    """Owner: no dark concrete. Bowls are pale concrete, blue only on the Blue Pool."""
    for b in L.BOWLS:
        assert b.material not in L.FORBIDDEN_MATERIALS, b.id
        assert b.material == (L.PALETTE['pool'] if b.id == 'blue_pool' else L.PALETTE['concrete']), b.id
    assert L.TOWER['material'] == L.PALETTE['deck']
    used = {dsl.MATERIALS[i] for i in np.unique(L.build_line(L.L1, ground=-20.).mesh.material)}
    assert not used & set(L.FORBIDDEN_MATERIALS)


@pytest.mark.parametrize('line', L.LINES, ids=lambda line: line.id)
def test_profile_is_smooth(line):
    """No kinks (('angle', ...) parts) and no sliver parts: a surface splits only at its gaps (C's review)."""
    for part in line.profile:
        assert part[0] != 'angle'
        if part[0] == 'line':
            assert part[1] >= .25, part


@pytest.mark.parametrize('line', L.LINES, ids=lambda line: line.id)
def test_line_starts_outside_the_tower(line):
    """B's tower owns its footprint and the roll-ins: a line starts at its roll-in's exit section, off the tower."""
    s, _, _, (x, z), _ = L.exit_station(line)
    (cx, cz), (sx, sz) = L.TOWER['centre'], L.TOWER['size']
    assert abs(x - cx) > sx / 2 or abs(z - cz) > sz / 2
    assert s == pytest.approx(next(f.s1 for f in line.features if f.kind == 'roll_in'), abs=.05)


def test_crater_gap_lip_speed():
    """J1 (park-assist #13452): the lip must see 18.25 m/s or more from a standing start. Ridden on the validator lane
    (plan/l3final): 18.61-18.62 m/s for 1, 4 and 8 m/s starts; the model here must agree within its margin."""
    lip = L.feature('L3_K1')[1]
    k = np.asarray(L.knots(L.L3, .25)); k = k[k[:, 0] <= lip.s1 + 1e-6]
    v = 1.
    for (s0, y0, _), (s1, y1, _) in itertools.pairwise(k):
        dl = math.hypot(s1 - s0, y1 - y0)
        drag = float(np.interp(v, L.MEASURED_DRAG[0], L.MEASURED_DRAG[1]))
        v = math.sqrt(max(v * v - 2 * 9.81 * (y1 - y0) - 2 * drag * dl, 0.))
    assert 18.25 <= v <= 19.35, v
