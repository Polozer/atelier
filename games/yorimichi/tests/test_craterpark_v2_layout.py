"""Crater Park v2 layout (craterpark/v2/layout.py): the lines' geometry rules and that each line compiles."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
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
