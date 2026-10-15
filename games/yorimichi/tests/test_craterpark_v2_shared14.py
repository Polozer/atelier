"""Actual tower-route interfaces into the one shared orange/purple room."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'world'/'regions'))
from craterpark.v2 import primitives as P, shared14  # noqa: E402


@pytest.mark.parametrize('dy',[-4.7,-1.,0.,2.9])
def test_level_change_has_exact_height_and_plan_length_with_level_ends(dy):
    p=P.from_additions(17.,0.,shared14.level_change(17.,17.+dy,40.3))
    assert p.end[0]==pytest.approx(40.3,abs=1e-9)
    assert p.end[1]==pytest.approx(17.+dy,abs=1e-9)
    assert p.end_degrees==pytest.approx(0.)


def test_real_primary_outlets_feed_same_room_without_lateral_teleports():
    spec=shared14.definition()
    for key,sign in [('L1',-1),('L4',1)]:
        primary=spec.primary[key];arm=spec.arms[key]
        assert np.linalg.norm(arm.point([0.])[0]-primary.path.point([primary.path.length])[0])<1e-7
        assert np.linalg.norm(arm.tangent([0.])[0]-primary.path.tangent([primary.path.length])[0])<1e-8
        body_entry=spec.body.point([0.])[0]+sign*10.*spec.body.normal([0.])[0]
        assert np.linalg.norm(body_entry-arm.point([arm.length])[0])<1e-7
        prof=P.from_additions(shared14.end_height(primary),0.,spec.arm_profiles[key])
        assert prof.end[0]==pytest.approx(arm.length,abs=1e-8)
        assert prof.end[1]==pytest.approx(shared14.FLOOR_Y,abs=1e-8)
        assert spec.reference(key)[-1,1]==pytest.approx(shared14.OUTLET_Y,abs=1e-7)
    assert np.allclose(spec.reference('L1')[-1],spec.reference('L4')[-1],atol=1e-8)
