"""The two physical portals at the shared orange/purple choice point."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'world'/'regions'))
from craterpark.v2 import bowl_entry, choice_vert, dsl, junctions as J, shared14, solids  # noqa: E402
from craterpark.v2.layout import knots, pieces  # noqa: E402


def test_choice_paths_use_the_actual_two_room_portals():
    room=shared14.definition();direct=bowl_entry.definition();vert=choice_vert.definition()
    for key in ('L1','L4'):
        assert np.allclose(room.reference(key,exit_offset=shared14.DIRECT_OFFSET)[-1],
                           [direct.path.start[0],shared14.OUTLET_Y,direct.path.start[1]])
        assert np.allclose(room.reference(key,exit_offset=shared14.ORANGE_OFFSET)[-1],
                           [vert.inlet[0],shared14.OUTLET_Y,vert.inlet[1]])
    assert np.linalg.norm(direct.path.point([0.])[0]-vert.inlet)==pytest.approx(shared14.DIRECT_OFFSET-shared14.ORANGE_OFFSET)
    assert np.allclose(direct.path.tangent([0.])[0],room.body.tangent([room.body.length])[0])
    assert np.allclose(vert.line.path.at(vert.line.path.length)[1],J.direction(vert.spec['heading_in']-90.))


def test_direct_transfer_has_straight_alignment_and_a_real_open_gap():
    entry=bowl_entry.definition();line=entry.line();spans=pieces(line)
    assert line.profile[0][0]=='line' and line.profile[0][1]>=20.
    assert len(spans)==2
    start,y,a,parts=spans[1]
    assert start-spans[0][0]>entry.gap
    k=knots(line)
    assert k[-1][0]==pytest.approx(entry.path.length)
    # The bowl is excavated below the caldera floor; its eventual rim and
    # surrounding ground must be built around this actual receiving height.
    assert -60.<k[-1][1]<0.
    assert k[-1][2]==pytest.approx(0.)
    assert parts[-1][0]=='line' and parts[-1][1]>=10.


def test_finite_choice_wall_keeps_apron_end_walls_outside_the_real_ports():
    mesh=choice_vert.build().mesh
    exposed=mesh.subset(mesh.role!=dsl.ROLE[dsl.BASE])
    loops=solids.check_open(exposed)
    assert len(loops)==2
