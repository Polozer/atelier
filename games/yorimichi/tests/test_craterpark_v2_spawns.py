"""Crater Park v2 starts: each line's spawn stands on the tower deck, never floating or buried, facing down its line."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world' / 'regions'))
sys.path.insert(0, str(GAME / 'world'))

from craterpark import placement  # noqa: E402
from craterpark.v2 import dsl, layout_m0, spawns  # noqa: E402

CREST = (1149., spawns.TOWER_DECK_Y, 1137.)


def deck(y=spawns.TOWER_DECK_Y, tilt=0., role=dsl.RIDING, size=6.):
    """A square deck round CREST at height y, tilted `tilt` degrees about native z (rising toward +x)."""
    x0, _, z0 = CREST
    rise = size * math.tan(math.radians(tilt))
    V = np.array([[x0 - size, y - rise, z0 - size], [x0 + size, y + rise, z0 - size],
                  [x0 + size, y + rise, z0 + size], [x0 - size, y - rise, z0 + size]], 'f8')
    return dsl.Mesh.part(V, np.array([[0, 2, 1], [0, 3, 2]]), role=role, feature='tower')


def line(theta=0., y=spawns.TOWER_DECK_Y, name='L1'):
    x, _, z = CREST
    d = spawns.forward(theta)
    return dsl.RideLine(name, ['tower'], path=[(x, y, z), (x + 30 * d[0], y - 10, z + 30 * d[1])],
                        spawn=((x, y, z), theta), finish=(x + 30 * d[0], y - 10, z + 30 * d[1]))


def test_a_spawn_on_the_deck_passes_and_lands_on_the_checked_ground():
    mesh = deck()
    out = spawns.entries(mesh, [line(0.), line(-90., name='L3')], placement, deck_y=spawns.TOWER_DECK_Y,
                         labels={'L1': 'Crater Line'})
    assert [e['key'] for e in out] == ['L1', 'L3'] and out[0]['name'] == 'Crater Line' and out[1]['name'] == 'L3'
    want = placement.to_unreal(np.array(CREST))
    assert np.allclose(out[0]['spawn']['location_cm'], want, atol=.01)
    yaw = placement.unreal_transform()['yaw_deg']
    assert out[0]['spawn']['yaw_deg'] == pytest.approx(((yaw + 180) % 360) - 180)
    assert out[1]['spawn']['yaw_deg'] == pytest.approx(((yaw - 90 + 180) % 360) - 180)
    assert abs(out[0]['ground_error_m']) < 1e-9


def test_the_unreal_yaw_points_down_the_line():
    """Unreal forward (cos yaw, sin yaw) matches the line's first segment taken through placement.to_unreal."""
    for theta in (0., 37., -120., 180.):
        ln = line(theta)
        e = spawns.entries(deck(), [ln], placement)[0]
        a, b = placement.to_unreal(np.asarray(ln.path[:2], 'f8'))
        d = (b - a)[:2] / np.linalg.norm((b - a)[:2])
        yaw = math.radians(e['spawn']['yaw_deg'])
        assert d @ np.array([math.cos(yaw), math.sin(yaw)]) > .999


@pytest.mark.parametrize('dy, word', [(.8, 'floating'), (-.8, 'buried')])
def test_a_floating_or_buried_spawn_is_refused(dy, word):
    with pytest.raises(spawns.SpawnError, match=word):
        spawns.entries(deck(), [line(y=spawns.TOWER_DECK_Y + dy)], placement)


def test_a_face_over_the_spawn_buries_it():
    roof = deck(y=spawns.TOWER_DECK_Y + 1.5, role=dsl.SIDE)
    with pytest.raises(spawns.SpawnError, match='buried'):
        spawns.entries(dsl.Mesh.concat([deck(), roof]), [line()], placement)


def test_render_only_and_buried_base_faces_are_not_ground():
    for role in (dsl.COPING, dsl.BASE):
        with pytest.raises(spawns.SpawnError, match='no ground'):
            spawns.entries(deck(role=role), [line()], placement)


def test_steep_ground_off_deck_and_wrong_yaw_are_refused():
    with pytest.raises(spawns.SpawnError, match='steep'):
        spawns.entries(deck(tilt=20.), [line()], placement)
    with pytest.raises(spawns.SpawnError, match='tower deck'):
        spawns.entries(deck(y=37.6), [line(y=37.6)], placement, deck_y=spawns.TOWER_DECK_Y)
    bad = line(0.); bad.spawn = (bad.spawn[0], 40.)
    with pytest.raises(spawns.SpawnError, match='faces'):
        spawns.entries(deck(), [bad], placement)


def test_the_m0_layout_spawn_passes_off_the_tower():
    park = layout_m0.park()
    out = spawns.entries(park.mesh, park.lines, placement)
    assert len(out) == 1 and abs(out[0]['ground_error_m']) <= spawns.GROUND_TOLERANCE
