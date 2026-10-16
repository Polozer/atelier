"""Small synthetic v4 geometry checks; no complete park or native process."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'world'/'regions'))
from craterpark.v2 import dsl, solids
from craterpark.v2 import v4_geometry as geometry


def flat_geo(length=5.,width=2.):
    return dict(id='synthetic',kind='straight',s=np.array([0.,length]),x=np.array([0.,length]),
                z=np.array([0.,0.]),h=np.array([0.,0.]),y=np.array([0.,0.]),L=length,W=width,
                start=dict(x=0.,z=0.,h=0.,y=0.,a=0.),end=dict(x=length,z=0.,h=0.,y=0.,a=0.),
                profile_parts=[('line',length)],wl={'type':'none'},wr={'type':'none'})


def test_straight_uses_resolved_coordinates_and_actual_port_rows():
    geo=flat_geo()
    built=geometry.build_module({'support':'earth'},geo,lambda x,z:np.full(np.shape(x),-1.))
    ports=geometry.module_ports(built,geo)
    assert np.allclose(ports['start'][:,0],0)
    assert np.allclose(ports['end'][:,0],5)
    assert np.ptp(ports['start'][:,2])==pytest.approx(2)
    assert solids.check_open(built.mesh)


def test_gap_has_no_riding_triangles_over_open_interval():
    geo=flat_geo(7.)
    geo.update(kind='gap',launch_parts=[('line',2.)],landing_parts=[('line',2.)],
               launch_y=0.,landing_y=-1.,launch_deg=0.,landing_deg=0.,air_intervals=[(2.,5.)])
    built=geometry.build_module({'support':'earth'},geo,lambda x,z:np.full(np.shape(x),-2.))
    tri=built.mesh.triangles()[built.mesh.role==dsl.ROLE[dsl.RIDING]]
    assert not ((tri[:,:,0].max(1)>2.+1e-8)&(tri[:,:,0].min(1)<5.-1e-8)).any()
    check=next(c for c in built.checks if c['kind']=='air')
    assert check['gap']==pytest.approx(3.)
    assert built.mesh.tag.max()>0


def test_mismatched_resolved_profile_is_refused():
    geo=flat_geo();geo['profile_parts']=[('line',4.)]
    with pytest.raises(geometry.GeometryError,match='endpoints disagree'):
        geometry.build_module({},geo,-1.)


def test_unsupported_structural_support_and_elbow_fail_closed():
    with pytest.raises(geometry.GeometryError,match='unsupported support'):
        geometry.build_module({'support':'bridge'},flat_geo(),-1.)
    geo=flat_geo();geo.update(kind='elbow',corner=1.)
    with pytest.raises(geometry.GeometryError,match='wide mouths do not fit'):
        geometry.build_module({'angle':90},geo,-1.)


def test_bowl_plan_parameters_change_real_shape_and_floor():
    spec=dict(centre=[20.,30.],scale=[1.,1.],axis_deg=0.,floor_y=-5.,shallow_y=-4.,
              wall=dict(h=4.,R=3.,deck=3.),lobes=[dict(c=[0.,0.],r=12.)],pockets=[],
              lobe_blend=3.,pocket_blend=3.,spines=[],floor_blend_m=10.)
    plan=geometry.DesignBowlPlan(spec)
    assert plan.shape([[20.,30.]])[0]==pytest.approx(-12.)
    assert plan.floor([[20.,30.],[30.,30.]]).tolist()==pytest.approx([-5.,-4.])
    assert plan.rim==pytest.approx(-1.)


def test_combined_module_seam_is_checked_and_diagnostics_are_serializable():
    from types import SimpleNamespace
    from craterpark.v2.v4_layout import compile_design
    a=flat_geo(3.);a['id']='a'
    b=flat_geo(3.);b['id']='b';b['x']+=3.;b['start']['x']=3.;b['end']['x']=6.
    resolved=SimpleNamespace(document={},ground_at=lambda x,z:np.full(np.shape(x),-1.),
                             order=['a','b'],segments={'a':{},'b':{}},geo={'a':a,'b':b},
                             lines=[dict(id='line',segments=[{'id':'a'},{'id':'b'}])],diagnostics=[],source=None)
    park=compile_design(resolved,include_ground=False)
    assert len(park.lines)==1
    assert np.allclose(park.lines[0].finish,[6.,0.,0.])
    import json
    json.dumps(park.checks)


def test_curved_resolver_interpolant_keeps_endpoints_without_scipy():
    r=30.;a=np.linspace(0.,.1,7);s=r*a
    geo=dict(s=s,x=r*np.sin(a),z=r*(1-np.cos(a)),h=np.degrees(a))
    curve=geometry.ResolvedCurve(geo)
    assert np.allclose(curve.point([0.,s[-1]]),[[0.,0.],[r*np.sin(.1),r*(1-np.cos(.1))]])
    assert np.allclose(curve.curvature(s),1/r,atol=2e-5)


def test_ground_outline_uses_declared_site_and_native_heights():
    from types import SimpleNamespace
    from craterpark.v2.v4_layout import ground_specification
    design=SimpleNamespace(document=dict(ground={},site=dict(buildable=[[0,0],[4,0],[4,4],[0,4],[0,0]])),source=None)
    spec=ground_specification(design,lambda x,z:x+z)
    assert spec['outline']==[[0.,0.,0.],[4.,4.,0.],[4.,8.,4.],[0.,4.,4.]]


def test_rainbow_flag_builds_real_bar_and_grind_line_over_gap():
    geo=flat_geo(7.,4.)
    geo.update(kind='gap',launch_parts=[('line',2.)],landing_parts=[('line',2.)],
               launch_y=0.,landing_y=-1.,launch_deg=0.,landing_deg=0.,air_intervals=[(2.,5.)])
    built=geometry.build_module({'support':'earth','rail':True},geo,lambda x,z:np.full(np.shape(x),-2.))
    assert len(built.rails)==1
    assert (built.mesh.role==dsl.ROLE[dsl.RAIL]).any()
    check=next(c for c in built.checks if c['kind']=='v4_rainbow')
    assert check['parameters']['height_m']==.75
    assert built.rails[0].points[:,1].max()>.75


def test_narrow_elbow_keeps_junction_structural_refusal():
    geo=flat_geo(12.,2.)
    wall=dict(type='bowl',h=1.,R=1.,cap=.4,fade=[0.,0.],outer='ground')
    geo.update(kind='elbow',corner=6.,wl=wall,wr=wall)
    geo['end']=dict(x=6.,z=6.,h=90.,y=0.,a=0.)
    segment=dict(angle=90.,mouth_w=3.,mouth_len=6.,funnel_m=2.,apron=1.,
                 qp=dict(R=1.,h=2.,vert=1.,deck=1.2,lip_min=2.))
    # An exact construction can still be invalid. The adapter must expose the
    # primitive ownership failure rather than add a covering apron or skip it.
    with pytest.raises(ValueError,match='supplied port is not on the floor perimeter'):
        geometry.build_module(segment,geo,lambda x,z:np.full(np.shape(x),-1.))


def test_compatible_tower_has_real_closed_concrete_body_and_owned_crest():
    geo=flat_geo(3.,2.);geo['id']='roll';geo['kind']='rollin';geo['x']+=2.
    geo['start']['x']=2.;geo['end']['x']=5.
    terrain=lambda x,z:np.full(np.shape(x),-1.)
    ramp=geometry.build_module({'support':'tower'},geo,terrain)
    tower=geometry.tower_deck(dict(centre=[0,0],size=[4,4],heading=0,deck_y=0),[(ramp,geo)],terrain)
    side=tower.mesh.triangles()[tower.mesh.role==dsl.ROLE[dsl.SIDE]]
    assert np.ptp(side[:,:,1])==pytest.approx(1.)
    support=next(c for c in tower.checks if c['kind']=='v4_support')
    triangles=np.asarray(support['body_triangles'])
    body=dsl.Mesh.part(triangles.reshape(-1,3),np.arange(triangles.size//3).reshape(-1,3),feature='core')
    assert solids.check_closed(body)>0
    assert {b['target_feature'] for b in support['bearings']}=={'tower','roll'}
    assert solids.check_open(dsl.Mesh.concat([ramp.mesh,tower.mesh]))


def test_large_tower_deck_and_sloping_sidewalls_share_all_boundary_samples():
    geo=flat_geo(3.,18.);geo.update(id='roll',kind='rollin')
    terrain=lambda x,z:-20.+.05*np.asarray(x)+.02*np.asarray(z)
    ramp=geometry.build_module({'support':'tower'},geo,terrain)
    tower=geometry.tower_deck(dict(centre=[-17.5,0],size=[35,36],heading=0,deck_y=0),
                              [(ramp,geo)],terrain)
    loops=solids.check_open(dsl.Mesh.concat([ramp.mesh,tower.mesh]))
    assert len(loops)==1
    # Only the ground-owned foot remains open; no edge of the rear deck leaks.
    assert not any(np.any((np.abs(p[:,0]+35)<1e-7)&(np.abs(p[:,1])<1e-7)) for p in loops)
