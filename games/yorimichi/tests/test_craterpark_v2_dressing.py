"""Crater Park v2 and the caldera's dressing: the park stays on the r4 block, its riding a cell inside it, so 10 m
clear of every dressing instance; its own bushes stand on its ground, clear of every riding face."""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
sys.path.insert(0, str(GAME / 'world'))

import yori  # noqa: E402
from craterpark import placement  # noqa: E402
from craterpark.v2 import dressing, dsl, layout_m0  # noqa: E402

DROP = np.array(layout_m0.DROP)


def slab(centre, size, y, role, tilt=0.):
    """A square (native) about `centre` at height y, rising `tilt` degrees toward +x."""
    x0, _, z0 = centre
    rise = size * math.tan(math.radians(tilt))
    V = np.array([[x0 - size, y - rise, z0 - size], [x0 + size, y + rise, z0 - size],
                  [x0 + size, y + rise, z0 + size], [x0 - size, y - rise, z0 + size]], 'f8')
    return dsl.Mesh.part(V, np.array([[0, 2, 1], [0, 3, 2]]), role=role, feature='f')


def test_the_m0_park_lies_on_the_block():
    report = dressing.check(layout_m0.park().mesh, placement)
    assert report['ok'] and report['samples'] > 100 and report['outside'] == 0


def test_a_face_off_the_block_is_refused_but_a_buried_base_is_not():
    off = DROP + np.array([0., 0., 400.])        # 400 m along native z: far off the 385 m block
    assert not placement.contains(*placement.native_to_island(off)[:2])
    with pytest.raises(dressing.DressingError, match='off the r4 block'):
        dressing.check(slab(off, 3., off[1], dsl.RIDING), placement)
    dressing.check(dsl.Mesh.concat([slab(DROP, 3., DROP[1], dsl.RIDING), slab(off, 3., off[1], dsl.BASE)]), placement)


def test_bushes_stand_on_the_ground_clear_of_the_riding():
    ground = slab(DROP, 40., DROP[1], dsl.GROUND, tilt=20.)
    ramp = slab(DROP, 8., DROP[1] + 1., dsl.RIDING)
    trees = dressing.plant(dsl.Mesh.concat([ground, ramp]), density=1.)
    assert set(trees) <= {b[0] for b in dressing.BUSHES} and sum(map(len, trees.values())) > 50
    reach = {b[0]: b[3] for b in dressing.BUSHES}
    rise = math.tan(math.radians(20.))
    for name, items in trees.items():
        for x, z, y, yaw, scale in items:
            x, y, z = x / 100, y / 100, z / 100
            assert y == pytest.approx(DROP[1] + (x - DROP[0]) * rise - .15, abs=.02)   # on the ground, 15 cm in
            gap = max(abs(x - DROP[0]) - 8., abs(z - DROP[2]) - 8., 0.)                 # plan gap to the ramp
            assert gap >= dressing.CLEAR + reach[name] * scale - 1.5 * dressing.CELL
            assert 0 <= yaw <= 360


def test_flat_and_steep_ground_and_other_roles_get_no_bushes():
    assert dressing.plant(slab(DROP, 30., DROP[1], dsl.GROUND), density=1.) == {}             # flat: up > .97
    assert dressing.plant(slab(DROP, 30., DROP[1], dsl.GROUND, tilt=60.), density=1.) == {}   # steep: up < .55
    assert dressing.plant(slab(DROP, 30., DROP[1], dsl.SIDE, tilt=20.), density=1.) == {}


def test_planting_is_deterministic():
    mesh = slab(DROP, 40., DROP[1], dsl.GROUND, tilt=20.)
    assert json.dumps(dressing.plant(mesh)) == json.dumps(dressing.plant(mesh))


def to_native(xy):
    """Island (x, y) -> native (x, z) at y 0 (placement.native_to_island is affine in plan)."""
    a = placement.native_to_island(np.array([0., 0., 0.]))[:2]
    ex = placement.native_to_island(np.array([1., 0., 0.]))[:2] - a
    ez = placement.native_to_island(np.array([0., 0., 1.]))[:2] - a
    return np.linalg.solve(np.stack([ex, ez], 1), np.asarray(xy, 'f8') - a)


def test_riding_at_the_block_edge_is_refused_but_ground_is_not():
    x0, y0, cell, _, mask = placement.footprint()
    j, i = np.nonzero(mask)
    k = int(np.argmax(i))                                   # the mask's easternmost cell: its outer edge is open
    nx, nz = to_native([x0 + (i[k] + .9) * cell, y0 + (j[k] + .5) * cell])
    with pytest.raises(dressing.DressingError, match='caldera may be dressed'):
        dressing.check(slab((nx, 0., nz), .3, 30., dsl.RIDING), placement)
    dressing.check(slab((nx, 0., nz), .3, 30., dsl.GROUND), placement)


def test_the_built_island_dressing_keeps_a_cell_off_the_block():
    """city.json as world.hidamari built it in this checkout (skipped without one): no instance on the block's mask
    grown by FREE_MARGIN, so every one is at least RING m from any v2 riding face."""
    city = yori.OUT / 'hidamari' / 'city.json'
    if not city.exists():
        pytest.skip('no world.hidamari output in this checkout')
    near = dressing.clearance(json.loads(city.read_text())['instances'], placement)
    assert near and min(near.values()) > 0.
    for name, items in json.loads(city.read_text())['instances'].items():
        a = np.asarray(items, 'f8').reshape(-1, 5)
        assert not placement.contains(a[:, 0], a[:, 1], margin=dressing.FREE_MARGIN).any(), name
