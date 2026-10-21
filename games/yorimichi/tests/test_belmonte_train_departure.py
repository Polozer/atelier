"""The train's motion is Paul's (2026-10-20, from his simulator, which ports route.run() + service()): a soft start
(RAMP), 1 km/h/s, 3.1 km/h/s braking, 110 km/h, 118 km/h in covered tunnels, 90 s at each terminus, speed zones and a
curve set by hand.
The built timetable gives his trip times, and the game plays route.py's runs exactly."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME / 'world'))
sys.path.insert(0, str(GAME / 'tools'))
import yori  # noqa: E402
from train import route as R  # noqa: E402
import belmonte_train_service as S  # noqa: E402


def straight(length=4000., radius=None):
    s = np.arange(0., length + 1., 10.)
    return SimpleNamespace(s=s, curvature=np.full(s.shape, 0. if radius is None else 1. / radius), length=length)


def in_time(c, t, dt=.5):
    """Speed every dt seconds (from the run's chainage against time) and its acceleration, at the interval ends."""
    grid = np.arange(0., t[-1], dt)
    d = np.interp(grid, t, np.abs(c - c[0]))
    speed = np.diff(d) / dt
    return grid[2:], speed, np.diff(speed) / dt


def test_paul_values():
    assert R.ACCELERATION * 3.6 == pytest.approx(1.)
    assert R.BRAKING * 3.6 == pytest.approx(3.1)
    assert R.MAX_SPEED * 3.6 == pytest.approx(110.)
    assert R.TUNNEL_SPEED * 3.6 == pytest.approx(118.)
    assert R.TUNNEL_ACCELERATION * 3.6 == pytest.approx(2.)
    assert R.DWELL == 90. and R.RAMP == 12.
    assert R.SPEED_ZONES == [(0., 1010., 70.), (1000., 2430., 110.), (2450., 4630., 140.), (4640., 7000., 110.),
                             (6990., 7940., 70.)]
    assert R.CURVE_LIMITS == {1701.: 91.}


@pytest.mark.parametrize('direction', [1, -1])
def test_departure_is_soft_then_gentle(direction):
    c, t, v = R.run(straight(), direction=direction, zones=[])
    at, speed, a = in_time(c, t)
    top = max(R.ACCELERATION, R.TUNNEL_ACCELERATION)
    # the first metre (the simulator's 1 m/s floor) takes 2 s; then the acceleration follows the ramp ...
    assert t[1] == pytest.approx(2.)
    ramp = (at > 3.) & (at < R.RAMP)
    assert np.all(a[ramp] <= top * at[ramp] / R.RAMP + .03)
    # ... and never exceeds 0.8 km/h/s once moving, holding it on the level until the engine's power runs out
    assert a[(at > 3.) & (at < 60.)].max() <= R.ACCELERATION + .04      # (1 m steps sampled every 0.5 s)
    assert np.median(a[(at > R.RAMP + 2) & (at < 40.)]) == pytest.approx(R.ACCELERATION, abs=.01)
    assert np.diff(v ** 2)[2:].max() / 2 <= R.ACCELERATION + 1e-6
    assert -np.diff(v ** 2).min() / 2 <= R.BRAKING + 1e-6        # and stops at 3 km/h/s at most


def test_speed_zones_replace_the_line_speed_under_the_curve_limits():
    line = straight(radius=900.)                        # posted 90 km/h everywhere
    tunnel = (line.s >= 2000.) & (line.s <= 3800.)
    plain = R.run(line, direction=1, tunnel=tunnel, zones=[])
    zones = [(500., 1500., 40.), (1500., 1900., 130.), (2500., 3200., 70.)]
    c, t, v = R.run(line, direction=1, tunnel=tunnel, zones=zones)
    kmh = v * 3.6
    assert kmh[(c >= 600.) & (c <= 1450.)].max() <= 40. + 1e-6      # slower than the curve: the zone
    assert kmh[(c >= 1500.) & (c <= 1900.)].max() <= 90. + 1e-6     # faster than the curve: the curve still caps
    inside = (c >= 2500.) & (c <= 3200.)
    assert kmh[inside].max() <= 70. + 1e-6                           # in the covered tunnel it replaces 150
    assert kmh[inside].max() < plain[2][inside].max() * 3.6
    c2, _, v2 = R.run(line, direction=-1, tunnel=tunnel, zones=zones)  # both directions, same chainage
    assert (v2 * 3.6)[(c2 >= 600.) & (c2 <= 1450.)].max() <= 40. + 1e-6
    # later zones win where they overlap, as in the simulator
    c3, _, v3 = R.run(line, direction=1, tunnel=tunnel, zones=[(500., 1500., 40.), (1000., 1500., 60.)])
    assert (v3 * 3.6)[(c3 >= 1200.) & (c3 <= 1500.)].max() > 40. + 1e-6


ROUTE = yori.OUT / 'belmonte-train' / 'route' / 'route.json'
SERVICE = yori.OUT / 'belmonte-train' / 'service' / 'service.json'


def built(path):
    if not path.exists() or not ROUTE.exists():
        pytest.skip(f'{path.name} not built')
    if 'speed_profile_stopping' not in json.loads(ROUTE.read_text()):
        pytest.skip('route.json predates the exact runs')
    return json.loads(path.read_text())


def test_timetable_is_pauls():
    service = built(ROUTE)['summary']['service']
    assert service['run_up_s'] == pytest.approx(567.3, abs=2)       # H -> B 9:27, with the crossing wait
    assert service['run_down_s'] == pytest.approx(386.1, abs=2)     # B -> H 6:26
    assert service['headway_s'] == pytest.approx(566.7, abs=2)      # 9:27
    assert service['waiting_direction'] == 'up' and service['loop_wait_s'] == pytest.approx(92.2, abs=2)
    assert service['dwell_s'] == R.DWELL


def test_the_game_plays_the_runs_exactly():
    route, data = built(ROUTE), built(SERVICE)
    h = route['summary']['service']['train_length_m'] / 2
    rows = np.array(route['speed_profile_down'])
    service = data['service']
    checked = 0
    for train in service['trains']:
        for leg in train['legs']:
            if leg['direction'] != 'down' or 'loop_arrive' in leg:
                continue
            for k in range(0, int(leg['arrive'] - leg['depart']), 3):
                at = S.position(train, service['cycle_s'], leg['depart'] + k)
                assert at == pytest.approx(np.interp(k, rows[:, 1], rows[:, 0]) + h, abs=1.5), (train["name"], k)   # 0.1 s schedule rounding
                checked += 1
    assert checked > 100


def test_built_departures_are_gentle():
    service = built(SERVICE)['service']
    found = 0
    for train in service['trains']:
        s, dt = np.asarray(train['s']), train['dt']
        v = np.abs(np.diff(s)) / dt
        for k in range(1, len(v) - int(60 / dt)):
            if v[k - 1] < 1e-3 <= v[k]:
                found += 1
                window = v[k - 1:k + int(60 / dt)]
                gain = window[int(1 / dt):] - window[:-int(1 / dt)]      # m/s gained over each second
                assert gain[int(3 / dt):].max() <= R.ACCELERATION + .03, (train['name'], k * dt)
                assert gain.max() <= .55, (train['name'], k * dt)            # the first metre: the 1 m/s floor
    assert found >= 4
