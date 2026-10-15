"""A receiver/cup union must preserve labels and real UV/normal seams."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
from craterpark.v2 import dsl, solid_union, solids  # noqa: E402


def cube(x, material, feature):
    return solids.prism(np.array([[x, 0.], [x + 2., 0.], [x + 2., 2.], [x, 2.]]), 0., 2.,
                         feature=feature, material=material)


def test_union_is_closed_and_keeps_exact_face_ownership_and_metric_uvs():
    m = solid_union.union([cube(0., dsl.CONCRETE, 'cup'), cube(1., 'material_016', 'receiver')])
    assert solids.check_closed(m) == pytest.approx(12., abs=1e-8)
    assert set(m.features) == {'cup', 'receiver'}
    for name, material in [('cup', dsl.CONCRETE), ('receiver', 'material_016')]:
        mask = m.feature == m.features.index(name)
        assert mask.any()
        assert (m.material[mask] == dsl.MATERIAL[material]).all()
    assert np.allclose(np.linalg.norm(m.N, axis=1), 1.)
    top = m.subset(m.role == dsl.ROLE[dsl.RIDING])
    assert np.allclose(top.UV * dsl.UV_METRES, top.V[:, [0, 2]])


def test_open_input_cannot_be_treated_as_a_solid():
    m = cube(0., dsl.CONCRETE, 'cup')
    m = m.subset(np.arange(len(m.F)) != 0)
    with pytest.raises(ValueError, match='not watertight'):
        solid_union.union([m])


@pytest.mark.parametrize('offset', [0., 4.9e-8])
def test_numerical_seam_canonicalization_preserves_chart_vertices(offset):
    m = cube(offset, dsl.CONCRETE, 'cup')
    # Two charts may represent the same geometric corner a few nm apart.
    original = m.V.copy()
    m.V[0] += 4e-9
    repaired = solid_union.canonicalize(m)
    assert solids.check_closed(repaired) == pytest.approx(8., abs=1e-7)
    assert len(repaired.V) > len(np.unique(np.round(repaired.V, 7), axis=0))
    assert np.max(np.linalg.norm(repaired.V - original, axis=1)) < 1e-7
