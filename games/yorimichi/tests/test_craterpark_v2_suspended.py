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


def test_end_openings_expose_only_the_actual_joined_port_intervals():
    side=P.Side('bowl',fade=(10.,10.))
    floor=np.unique(np.r_[np.arange(-50.,51.,2.),np.arange(-19.,20.,2.)])
    ramp=P.ramp(Line((0.,0.),(20.,0.)),P.from_additions(17.5,0.,[('line',20.)]),100.,
                left=side,right=side,thickness=1.5,across=floor,bottom_u=np.linspace(0.,1.,103),
                end_openings=([(-20.,20.)],[(-46.,-14.),(20.,40.)]))
    assert solids.check_closed(ramp.mesh)>0
    T=ramp.mesh.triangles()
    for x,openings in ((0.,[(-20.,20.)]),(20.,[(-46.,-14.),(20.,40.)])):
        end=(np.abs(T[:,:,0]-x)<1e-8).all(1)
        visible=end&(ramp.mesh.role==dsl.ROLE[dsl.SIDE])
        for lo,hi in openings:
            w=T[visible,:,2]
            assert not ((w.max(1)>lo+1e-7)&(w.min(1)<hi-1e-7)).any()
        hidden=end&(ramp.mesh.role==dsl.ROLE[dsl.BASE])
        assert ramp.mesh.areas()[hidden].sum()==pytest.approx(sum(hi-lo for lo,hi in openings)*1.5)
        assert ramp.mesh.areas()[visible].sum()==pytest.approx((102.-sum(hi-lo for lo,hi in openings))*1.5)


def test_end_openings_reject_unsampled_or_overlapping_cuts():
    path=Line((0.,0.),(20.,0.));prof=P.from_additions(10.,0.,[('line',20.)])
    with pytest.raises(ValueError,match='matching upper and underside'):
        P.ramp(path,prof,18.,thickness=1.,end_openings=([(-3.141,3.141)],None))
    with pytest.raises(ValueError,match='overlap'):
        P.ramp(path,prof,18.,thickness=1.,across=np.arange(-9.,10.,1.),bottom_u=np.linspace(0.,1.,19),
               end_openings=([(-3.,3.),(1.,5.)],None))


def test_adjoining_suspended_walls_share_vertical_rows_despite_different_peak_heights():
    def growing(E):
        t=np.clip(E[:,0]/30.,0.,1.);w=np.sin(np.pi*t)**2
        return 3.+4.*w,3.5+2.5*w
    def ordinary(E):return np.full(len(E),3.),np.full(len(E),3.5)
    built=[]
    for start,end,shape in ((0.,30.,growing),(30.,50.,ordinary)):
        side=P.Side('bowl',height=7.,radius=6.,shape=shape)
        built.append(P.ramp(Line((start,0.),(end,0.)),P.from_additions(10.,0.,[('line',end-start)]),18.,
                            left=side,right=side,thickness=1.5,bottom_u=np.linspace(0.,1.,21)).mesh)
    m=dsl.Mesh.concat(built);m=m.subset(m.role!=dsl.ROLE[dsl.BASE])
    assert len(solids.check_open(m))==2
