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
    assert np.linalg.norm(direct.path.point([0.])[0]-vert.inlet)==pytest.approx(abs(shared14.DIRECT_OFFSET-shared14.ORANGE_OFFSET))
    assert np.allclose(direct.path.tangent([0.])[0],room.body.tangent([room.body.length])[0])
    assert np.allclose(vert.line.path.at(vert.line.path.length)[1],J.direction(vert.spec['heading_in']+90.))
    apron_inlet = vert.line.path.at(vert.spec['s_in'])[0]
    np.testing.assert_allclose(apron_inlet - vert.inlet,
                               choice_vert.APPROACH * J.direction(vert.spec['heading_in']), atol=1e-7)


def test_direct_transfer_has_straight_alignment_and_a_real_open_gap():
    entry=bowl_entry.definition();line=entry.line();spans=pieces(line)
    from craterpark.v2 import primitives as P
    alignment=P.from_additions(line.y0,0.,line.profile[:2])
    assert alignment.end[0]>=20.
    assert alignment.end[1]==pytest.approx(line.y0-3.2)
    assert alignment.end_degrees==pytest.approx(0.)
    assert min(part[1] for part in line.profile[:2])>=60.
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


@pytest.fixture(scope="module")
def choice_meshes():
    return bowl_entry.build(include_runout=False).mesh, choice_vert.build().mesh


def test_finite_choice_wall_keeps_apron_end_walls_outside_the_real_ports(choice_meshes):
    _,mesh=choice_meshes
    exposed=mesh.subset(mesh.role!=dsl.ROLE[dsl.BASE])
    loops=solids.check_open(exposed)
    assert len(loops)==2


def test_facing_choice_approach_shoulders_have_positive_plan_clearance():
    from craterpark.v2 import primitives as P
    side=P.Side('bowl',height=3.,radius=3.5)
    # Both actual approach floors are30m wide. This includes each1m top cap,
    # even at the full-height section, independent of their different y.
    reach=P.bowl_reach(side)
    separation=abs(shared14.ORANGE_OFFSET-shared14.DIRECT_OFFSET)
    assert separation-30.-2.*reach>1., 'facing curved shoulders intersect'


def test_actual_facing_approach_meshes_keep_a_clear_strip(choice_meshes):
    entry,vert=choice_meshes
    direct=bowl_entry.definition()
    tangent=direct.path.tangent([0.])[0]
    normal=np.array([-tangent[1],tangent[0]])
    origin=direct.path.point([0.])[0]-shared14.DIRECT_OFFSET*normal
    spans=[]
    for mesh,feature in ((entry,'B14.0'),(vert,'V14.approach')):
        selected=mesh.subset(mesh.feature==mesh.features.index(feature))
        q=selected.V[np.unique(selected.F)][:,[0,2]]-origin
        along=q@tangent
        lateral=q[(along>=1.-1e-7)&(along<=20.+1e-7)]@normal
        assert len(lateral)>10
        spans.append((lateral.min(),lateral.max()))
    assert spans[1][0]-spans[0][1]>1.


@pytest.mark.parametrize("legacy_overlap", [False, True])
def test_actual_vert_module_preserves_direct_receiver_headroom(choice_meshes, monkeypatch, legacy_overlap):
    from craterpark.v2 import validate as V
    entry,vert=choice_meshes
    if legacy_overlap:
        monkeypatch.setattr(choice_vert,"APPROACH",20.)
        vert=choice_vert.build().mesh
    entry=entry.subset(entry.role==dsl.ROLE[dsl.RIDING])
    vert=vert.subset(np.isin(vert.role,[dsl.ROLE[r] for r in dsl.COLLISION_ROLE]))
    meshes=[V.Mesh('direct',entry.V,entry.F),V.Mesh('vert',vert.V,vert.F)]
    route=bowl_entry.definition().path
    lane=V.Lane('direct',route.point([0.,route.length-25.]),9.,surface=('direct',))
    check=V.protrusions(meshes,[lane])
    assert check['ok'] is (not legacy_overlap),check['failures']
