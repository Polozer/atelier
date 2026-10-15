"""A tight crest nose still needs all samples required by the angle tolerance."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
from craterpark.v2 import dsl, primitives as P  # noqa: E402


def test_narrow_rounded_crest_keeps_its_arcs_and_breaks():
    path = P.Rounded([(0., -.15), (30., -.15), (30., .15), (0., .15)], .15, closed=True)
    tess = dsl.Tess(.002, 1.2, 2.8)
    t = path.samples(tess, offsets=[0., -7.8])
    for b in path.breaks():
        assert np.min(np.abs(t - b)) < 1e-9
    p = path.point(t)
    assert p[:, 0].max() > 29.99
    for i, curve in enumerate(path.curves):
        if curve.curvature([curve.length / 2])[0] == 0:
            continue
        local = t[(t >= path.s[i] - 1e-9) & (t <= path.s[i + 1] + 1e-9)] - path.s[i]
        tangents = curve.tangent(local)
        angles = np.unwrap(np.arctan2(tangents[:, 1], tangents[:, 0]))
        assert len(local) > 70
        assert np.max(np.abs(np.diff(angles))) <= np.deg2rad(tess.angle) + 1e-9
