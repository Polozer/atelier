"""Compares the host's and the guest's racing receipts (RacingNetworkQA, review_network_session.py --racing).

Both processes run on one machine, so they share the wall clock: a sample's world second minus its wall time is that
machine's view of the shared clock, and the two must agree. Runner positions are compared at whole world seconds both
computed (the race data itself) and at the moments the guest sampled (what it shows), the host's interpolated there.
"""
import bisect
import math
import statistics


def _own_checks(receipt, prefix):
    checks = {}
    for check in receipt.get('checks', []):
        name = prefix + check.get('name', '?')
        checks[name] = checks.get(name, True) and bool(check.get('pass'))
    return checks


def _offsets(samples, field):
    return [s[field] - s['wall'] for s in samples if field in s and 'wall' in s]


def _interpolate(times, values, t):
    """Linear interpolation of values (lists of numbers) at t; None outside the sampled span."""
    if not times or t < times[0] or t > times[-1]:
        return None
    i = bisect.bisect_left(times, t)
    if times[i] == t:
        return values[i]
    a, b = i - 1, i
    w = (t - times[a]) / (times[b] - times[a]) if times[b] > times[a] else 0.
    return [x + (y - x) * w for x, y in zip(values[a], values[b])]


def race_review(host, guest):
    """The race both sampled: clock agreement, identical runner data, and live position differences (metres)."""
    out = {}
    hs, gs = host.get('race', []), guest.get('race', [])
    keys = {s['race'] for s in hs} & {s['race'] for s in gs}
    out['races'] = sorted(keys)
    if not keys:
        return out
    key = max(keys, key=lambda k: sum(1 for s in gs if s['race'] == k))
    hs = [s for s in hs if s['race'] == key]
    gs = [s for s in gs if s['race'] == key]
    out['race'], out['host_samples'], out['guest_samples'] = key, len(hs), len(gs)
    ho, go = _offsets(hs, 'world'), _offsets(gs, 'world')
    out['clock_difference_s'] = abs(statistics.mean(ho) - statistics.mean(go))
    # The same world second: identical race data on both machines.
    grid = {}
    for s in hs:
        for i, g in enumerate(s.get('grid', [])):
            grid[(i, round(g[0], 3))] = g[1:]
    worst = 0.
    compared = 0
    for s in gs:
        for i, g in enumerate(s.get('grid', [])):
            other = grid.get((i, round(g[0], 3)))
            if other is not None:
                compared += 1
                worst = max(worst, math.dist(g[1:], other) / 100.)
    out['grid_points'], out['grid_max_m'] = compared, worst
    # What each showed at the same instant: the host's runners interpolated at the guest's wall times.
    times = [s['wall'] for s in hs]
    errors = []
    for s in gs:
        for i, at in enumerate(s.get('runners', [])):
            series = [h['runners'][i] if i < len(h.get('runners', [])) else at for h in hs]
            there = _interpolate(times, series, s['wall'])
            if there is not None:
                errors.append(math.dist(at, there) / 100.)
    if errors:
        out['live_points'] = len(errors)
        out['live_median_m'] = statistics.median(errors)
        out['live_max_m'] = max(errors)
    return out


def train_review(host, guest):
    """The train line on both: service clock agreement and the countdowns a station board shows."""
    out = {}
    hs, gs = host.get('train', []), guest.get('train', [])
    if not hs or not gs:
        return out
    out['host_samples'], out['guest_samples'] = len(hs), len(gs)
    out['clock_difference_s'] = abs(statistics.mean(_offsets(hs, 'time')) - statistics.mean(_offsets(gs, 'time')))
    times = [s['wall'] for s in hs]
    worst = 0.
    compared = 0
    for s in gs:
        h = _interpolate(times, [[x['crossing_in'], x['passing_in']] for x in hs], s['wall'])
        if h is None:
            continue
        # A countdown jumps when its train passes: compare only where both count down to the same event.
        for mine, theirs in zip([s['crossing_in'], s['passing_in']], h):
            if mine >= 0 and theirs >= 0 and abs(mine - theirs) < 30:
                compared += 1
                worst = max(worst, abs(mine - theirs))
    out['countdown_points'], out['countdown_max_s'] = compared, worst
    return out


def fps_review(receipt):
    values = [f['fps'] for f in receipt.get('fps', [])]
    if not values:
        return {}
    values.sort()
    return dict(seconds=len(values), mean=statistics.mean(values), median=statistics.median(values),
                low_5_percent=values[max(0, int(len(values) * .05) - 1)], minimum=values[0])


def racing_checks(host, guest):
    checks = {}
    checks.update(_own_checks(host, 'racing_host: '))
    checks.update(_own_checks(guest, 'racing_guest: '))
    checks['racing_host_done'] = bool(host.get('done'))
    checks['racing_guest_done'] = bool(guest.get('done'))
    race = race_review(host, guest)
    train = train_review(host, guest)
    checks['racing_same_race_sampled'] = bool(race.get('race'))
    checks['racing_clock_agrees'] = race.get('clock_difference_s', 1e9) < .25
    checks['racing_same_runner_data'] = race.get('grid_points', 0) > 0 and race.get('grid_max_m', 1e9) < .01
    checks['racing_same_positions_shown'] = race.get('live_points', 0) > 0 and race.get('live_max_m', 1e9) < 5.
    checks['train_clock_agrees'] = train.get('clock_difference_s', 1e9) < .25
    checks['train_same_countdowns'] = train.get('countdown_points', 0) > 0 and train.get('countdown_max_s', 1e9) < 1.
    return dict(checks=checks, race=race, train=train, fps=dict(host=fps_review(host), guest=fps_review(guest)),
                identity=dict(host=host.get('host'), guest=host.get('guest'), guest_left=host.get('guest_left'),
                              guest_back=host.get('guest_back'), guest_install=guest.get('install')))
