"""Elevated channels permit real flyovers without foundations occupying lower lanes."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
from craterpark.v2 import dsl, primitives as P, solids  # noqa: E402
from craterpark.v2.curves import Line  # noqa: E402


def test_suspended_steep_channel_is_closed_and_follows_the_floor():
    prof = P.from_additions(70., 0., [('arc', 80., -35.), ('line', 30.), ('arc', 60., 0.)])
    ramp = P.ramp(Line((0., 0.), (200., 0.)), prof, 18., left=P.Side('bowl'), right=P.Side('bowl'),
                  ground=-30., thickness=1.5, ends=('wall', 'wall'))
    assert solids.check_closed(ramp.mesh) > 0
    assert not ramp.foot
    bottom = ramp.mesh.triangles()[ramp.mesh.face_normals()[:, 1] < -.5]
    assert len(bottom)
    # Underside is a continuous, visible part of the channel, rather than a
    # hidden global base at terrain height. All its points follow local height.
    assert bottom[:, :, 1].min() > prof.end[1] - 1.51
    role = ramp.mesh.role[ramp.mesh.face_normals()[:, 1] < -.5]
    assert (role == dsl.ROLE[dsl.SIDE]).all()
    assert ramp.mesh.V[:, 1].min() == pytest.approx(prof.end[1] - 1.5)
    tri = bottom
    edges = np.concatenate([tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 1], tri[:, 0] - tri[:, 2]])
    assert np.linalg.norm(edges, axis=1).max() <= 4.


def test_suspended_requires_solid_sides_and_positive_thickness():
    path, prof = Line((0., 0.), (20., 0.)), P.from_additions(10., 0., [('line', 20.)])
    for kwargs in ({'thickness': .1}, {'thickness': 1., 'on_ground': True},
                   {'thickness': 1., 'left': P.Side('bowl', outer='ground')}):
        with pytest.raises(ValueError):
            P.ramp(path, prof, 18., **kwargs)
