"""Freeze the shipped city emitter before moving its geometry authority."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

GAME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GAME/'world'))
from city_terrain_fixture import CASES, evaluate  # noqa: E402

BASELINE = Path(__file__).with_name('fixtures')/'terrain-city-r8.json'


def same_calls(current, expected):
    if isinstance(expected, dict):
        assert current.keys() == expected.keys()
        for key in expected:
            same_calls(current[key], expected[key])
    elif isinstance(expected, list):
        assert len(current) == len(expected)
        for a, b in zip(current, expected):
            same_calls(a, b)
    else:
        assert current == pytest.approx(expected, rel=0., abs=1.e-12)


@pytest.mark.parametrize('case', [case for case in CASES if case != 'city_pad'])
def test_city_emission_order_heights_and_colours(case):
    # city_pad exercises main's post-r8 air-station apron and is covered by the
    # paired/unpaired regression; the frozen baseline is the published r8 source.
    baseline = json.loads(BASELINE.read_text())
    assert baseline['source_revision'] == '4ff62dabbc1a20350a3a849e58f00196db8a3dff'
    assert baseline['source_sha256'] == '93702c4d2efb5496bc3bf665aee68b136ec12fb74e4110f2877504a952e8c1eb'
    expected = baseline['cases'][case]
    current = evaluate(case)
    assert current['axes_unchanged'] is True
    assert current['faces'] == [tuple(face) for face in expected['faces']]
    assert current['keys'] == expected['keys']
    for field in ('vertices', 'colours'):
        np.testing.assert_allclose(current[field], expected[field], atol=1.e-12, rtol=0., err_msg=field)
    same_calls(current['calls'], expected['calls'])
    assert len(current['calls']['carve']) == (0 if case == 'other_surface' else 1)


def test_frozen_cases_distinguish_coarse_carve_from_uncarved_details():
    cases = json.loads(BASELINE.read_text())['cases']
    assert len(cases['coarse_holes']['faces']) == 4  # Two different water omissions.
    assert set(cases['coast']['keys']) == {'coast_sand'}
    assert len(set(map(tuple, cases['island_fade']['colours']))) >= 3
    for name in ('park_refinement', 'terrace_refinement'):
        case = cases[name]
        assert len(case['faces']) == 9 and len(case['calls']['height']) == 2
        # A coarse grid carve occurred, but these existing subpatches use a
        # fresh height evaluation instead of interpolating the carved grid.
        assert case['calls']['height'][1][0] == [4, 4]
    assert {'hd_flag', 'hd_flag2'} & set(cases['paving']['keys'])
    assert cases['paving']['keys'][0] == 'hd_yard'
