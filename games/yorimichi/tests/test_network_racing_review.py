"""The racing receipts' comparison (tools/network_racing_review.py) passes a matching pair and catches a drift."""
import copy
import importlib.util
import math
from pathlib import Path

spec = importlib.util.spec_from_file_location('network_racing_review',
                                              Path(__file__).resolve().parents[1] / 'tools' / 'network_racing_review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def receipt(offset_s=0., shift_cm=0., wall0=1000.):
    race, train = [], []
    for k in range(20):
        wall = wall0 + k * .5
        world = 5000. + (wall - 1000.) + offset_s
        x = (world - 5000.) * 1700. + shift_cm
        race.append(dict(wall=wall, world=world, race='d1r1', start=5000., runners=[[x, 0., 0.]],
                         grid=[[5000. + math.floor(world - 5000.), math.floor(world - 5000.) * 1700. + shift_cm, 0., 0.]]))
        train.append(dict(wall=wall, time=200. + (wall - 1000.) + offset_s, chainage=[1., 2.],
                          crossing_in=100. - (wall - 1000.) - offset_s, passing_in=50. - (wall - 1000.) - offset_s))
    return dict(done=True, checks=[{'name': 'ok', 'pass': True}], race=race, train=train,
                fps=[dict(wall=wall0 + k, fps=55. + k) for k in range(5)])



def test_matching_pair_passes():
    host, guest = receipt(wall0=1000.), receipt(wall0=1000.25)
    result = review.racing_checks(host, guest)
    assert all(result['checks'].values()), result['checks']
    assert result['race']['clock_difference_s'] < 1e-9
    assert result['race']['grid_max_m'] == 0.
    assert result['fps']['host']['minimum'] == 55.


def test_clock_drift_and_other_data_fail():
    host = receipt()
    late = receipt(offset_s=.5, wall0=1000.25)
    checks = review.racing_checks(host, late)['checks']
    assert not checks['racing_clock_agrees']
    assert not checks['racing_same_positions_shown']
    assert not checks['train_clock_agrees']
    moved = receipt(shift_cm=50., wall0=1000.25)
    assert not review.racing_checks(host, moved)['checks']['racing_same_runner_data']


def test_failed_or_missing_steps_fail():
    host, guest = receipt(), copy.deepcopy(receipt())
    guest['checks'].append({'name': 'rejoin: the same wallet', 'pass': False})
    guest['done'] = False
    checks = review.racing_checks(host, guest)['checks']
    assert not checks['racing_guest: rejoin: the same wallet']
    assert not checks['racing_guest_done']
    assert not review.racing_checks({}, {})['checks']['racing_same_race_sampled']
