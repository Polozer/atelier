"""Hidden speed must never leak across an exposed portal or a gap between tunnels."""
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from train import route as R  # noqa: E402


@pytest.fixture
def line():
    samples = np.arange(0., 3001., 10.)
    return SimpleNamespace(s=samples, curvature=np.full(samples.shape, 1. / 300.), length=3000.)


@pytest.mark.parametrize('direction', [1, -1])
def test_separate_tunnels_never_hide_an_exposed_middle(line, direction):
    tunnel = ((line.s >= 300.) & (line.s <= 1400.)) | ((line.s >= 1450.) & (line.s <= 2600.))
    # Both ends are underground, but the middle crosses the open gap.
    head = 1500. if direction == 1 else 1500. - R.TRAIN_LENGTH
    rear = head - direction * R.TRAIN_LENGTH
    assert np.interp(head, line.s, tunnel) > .5 and np.interp(rear, line.s, tunnel) > .5
    assert not R.tunnel_covered(line, tunnel, [head], direction)[0]


@pytest.mark.parametrize('direction', [1, -1])
def test_portal_containment_includes_the_rear_and_preserves_braking(line, direction):
    tunnel = (line.s >= 300.) & (line.s <= 2600.)
    c, t, v = R.run(line, direction=direction, tunnel=tunnel)
    # Independent oracle: every part of the physical interval must fit this tunnel.
    rear = c - direction * R.TRAIN_LENGTH
    inside = (np.minimum(c, rear) >= 300.) & (np.maximum(c, rear) <= 2600.)
    curve_limit = R.curve_limit(300.)
    assert np.all(v[~inside] <= curve_limit + 1e-6)
    assert v.max() <= R.TUNNEL_SPEED + 1e-6
    assert v.max() > R.MAX_SPEED
    assert v[0] == v[-1] == 0.
    assert np.all(np.diff(t) > 0.)
    ds = np.abs(np.diff(c))
    acceleration = np.diff(v ** 2) / (2. * ds)
    assert acceleration.max() <= R.TUNNEL_ACCELERATION + 1e-6
    assert acceleration.min() >= -R.BRAKING - 1e-6
    assert t[-1] < R.run(line, direction=direction)[1][-1]


@pytest.mark.parametrize('direction', [1, -1])
def test_short_tunnel_cannot_boost_a_partly_exposed_train(line, direction):
    tunnel = (line.s >= 1400.) & (line.s <= 1450.)
    baseline = R.run(line, direction=direction)
    actual = R.run(line, direction=direction, tunnel=tunnel)
    for a, b in zip(actual, baseline):
        np.testing.assert_array_equal(a, b)


def test_wrong_tunnel_mask_is_rejected(line):
    with pytest.raises(ValueError, match='one value per line sample'):
        R.run(line, tunnel=[True])


def test_loop_waiting_profiles_keep_the_tunnel_schedule(line):
    tunnel = (line.s >= 300.) & (line.s <= 2600.)
    rail = np.zeros_like(line.s)
    loop = (1400., 1850.)
    fast = R.service(line, rail, loop, tunnel=tunnel)
    ordinary = R.service(line, rail, loop)
    assert fast['cycle_s'] < ordinary['cycle_s']
    assert fast['dwell_s'] == R.DWELL
    a, b = fast['schedule']
    up, down = a['legs'][0], b['legs'][0]
    assert max(up['loop_arrive_s'], down['loop_arrive_s']) < min(up['loop_leave_s'], down['loop_leave_s'])
    for train in (a, b):
        first, second = train['legs']
        assert abs(second['depart_s'] - first['arrive_s'] - R.DWELL) < .2
        for leg in train['legs']:
            assert leg['depart_s'] <= leg['loop_arrive_s'] <= leg['loop_leave_s'] <= leg['arrive_s']
