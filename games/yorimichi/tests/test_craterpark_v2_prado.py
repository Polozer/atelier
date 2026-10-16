"""The integral finish must have two real spines and one manifold bowl surface."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world' / 'regions'))
from craterpark.v2 import dsl, prado, solids  # noqa: E402


def test_pockets_have_deep_and_shallow_floors():
    p = prado.PradoPlan()
    # The bowl has five connected receiving and carving pockets.
    pocket = p.native(np.array([[-43., 18.], [-45., -18.], [-14., -5.], [35., 19.], [35., -19.]]) * prado.PLAN_SCALE)
    assert (p.sdf(pocket) < 0).all()
    assert p.floor(pocket).min() == pytest.approx(prado.DEEP)
    assert p.floor(pocket).max() == pytest.approx(prado.SHALLOW)


def test_spines_are_integral_and_mesh_is_closed():
    b = prado.build()
    assert solids.check_closed(b.mesh) > 0
    assert len(b.rails) >= 1
    assert len(b.mesh.features) == len(set(b.mesh.features))
    assert 'crater_bowl' in b.mesh.features
    assert np.ptp(b.mesh.V[:, 0]) > 140.
    assert not (b.mesh.material == dsl.MATERIAL['material_004']).any()
    spines = [c for c in b.checks if c.get('kind') == 'spine']
    assert len(spines) == 2
    p = prado.PradoPlan()
    for c in spines:
        assert c['gap_m'] == 0.
        faces = b.mesh.F[(b.mesh.feature == b.mesh.features.index(c['feature'])) &
                         (b.mesh.material == dsl.MATERIAL[dsl.CONCRETE])]
        v = b.mesh.V[np.unique(faces)]
        crest = v[np.abs(v[:, 1] - prado.RIM) < 1e-7]
        # Check actual geometry, not just the spine's declared dimensions.
        assert np.ptp(p.local(crest[:, [0, 2]])[:, 1]) <= .300001
