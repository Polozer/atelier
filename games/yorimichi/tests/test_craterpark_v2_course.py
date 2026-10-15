"""Geometric controls for the nested, elevated primary returns."""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
from craterpark.v2 import course  # noqa: E402
from craterpark.v2.curves import EasedTurn  # noqa: E402


@pytest.mark.parametrize('degrees', [180., -180., 90., -120.])
def test_eased_turn_has_true_minimum_radius_and_smooth_ports(degrees):
    p = EasedTurn((20., 30.), 310., 60., degrees)
    t = np.linspace(0., p.length, 10001)
    assert np.max(np.abs(p.curvature(t))) == pytest.approx(1 / 60.)
    assert np.allclose(p.curvature([0., p.length]), 0.)
    assert np.linalg.norm(np.diff(p.point(t), axis=0), axis=1).sum() == pytest.approx(p.length, abs=1e-5)
    v = np.gradient(p.point(t), t, axis=0)
    assert np.max(np.linalg.norm(v[1:-1] - p.tangent(t)[1:-1], axis=1)) < 1e-5
    for cut in p.breaks()[1:-1]:
        assert np.linalg.norm(p.point([cut + 1e-6])[0] - p.point([cut - 1e-6])[0]) == pytest.approx(2e-6, abs=1e-8)
    want = np.radians(310. + degrees)
    assert np.allclose(p.tangent([p.length])[0], [math.cos(want), math.sin(want)])


def test_primary_paths_project_real_outer_wall_rows_without_station_jumps():
    specs = course.primary_specs()
    assert {q.id for q in specs} == {'L1', 'L2', 'L3', 'L4'}
    for spec in specs:
        p = spec.path
        t = np.linspace(1., p.length - 1., 301)
        for offset in (-15., 15.):
            s, lateral = p.project(p.point(t) + offset * p.normal(t))
            assert np.max(np.abs(s - t)) < 1e-6
            assert np.max(np.abs(lateral - offset)) < 1e-6


def test_longitudinal_shared_cut_is_on_the_exact_profile_not_a_sampled_inverse():
    from craterpark.v2 import dsl, primitives as P
    from craterpark.v2.curves import Line
    from craterpark.v2.sweep import sweep
    prof=P.from_additions(100.,0.,[('arc',80.,-35.),('line',30.),('arc',60.,0.)])
    cut=37.123456789
    m=sweep(Line((0.,0.),(200.,0.)),prof,mode='longitudinal',across=18.,t=[cut],tess=dsl.Tess(.002,1.,2.8))
    row=m.V[np.abs(m.V[:,0]-cut)<1e-10]
    assert len(row)>=2
    # This cut lies on the first exact circle, so no sampled inversion is used
    # in the expected height. The old table interpolation misplaced it.
    want=100.-80.+math.sqrt(80.**2-cut**2)
    assert np.max(np.abs(row[:,1]-want))<1e-9
