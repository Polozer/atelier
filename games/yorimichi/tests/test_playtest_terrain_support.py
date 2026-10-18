"""Regressions for the reported west-rim opening and hovering air apron."""
import ast
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'world'))
import yori  # noqa: E402,F401
import shorelines as coast  # noqa: E402
import coastal_dressing  # noqa: E402
import farhills_grid  # noqa: E402
from hidamari import layout  # noqa: E402
from terrain_product import Mesh  # noqa: E402
from terrain_query import Surface  # noqa: E402
from train import earthworks  # noqa: E402
from city_terrain_fixture import RecordingMesh  # noqa: E402


def test_exposed_west_backdrop_does_not_protect_the_old_sea_floor():
    y=np.array([-130.,-125.,-110.,-90.,-60.])
    x=np.full_like(y,-350.)
    # Previously all these inland points retained the old -30m sea floor.
    assert np.all(coast.height(x,y,-30.,exposed_west=True)>0.)
    assert np.all(coast.height(x,y,-30.)[1:]==-30.)
    x,y=np.meshgrid([-300.,0.,550.,1231.,1420.],[-124.,0.,301.])
    z=np.full_like(x,32.)
    np.testing.assert_array_equal(coast.height(x,y,z,exposed_west=True),coast.height(x,y,z))


def test_full_west_rim_uses_the_fine_profiles_exact_knots(monkeypatch):
    axis=np.linspace(-300.,300.,301)
    h=25.+.04*axis+np.sin(axis/3.)
    monkeypatch.setattr(layout,'H',np.broadcast_to(h[:,None],(301,301)).copy())
    xs=np.array([-380.,-300.]);ys=np.array([-160.,80.]);z=np.full((2,2),-30.)
    vertices,faces=coast.grid_mesh(xs,ys,z,parents=(xs,ys,z),
        shape=layout.coastal_backdrop_height,edge_knots={(0,-300.):axis})
    p=np.asarray(vertices);edge=p[np.isclose(p[:,0],-300.)]
    wanted=axis[(axis>=ys[0])&(axis<=ys[-1])]
    assert all(np.any(abs(edge[:,1]-v)<1e-10) for v in wanted)
    np.testing.assert_allclose(edge[:,2],np.interp(edge[:,1],axis,h),rtol=0,atol=1e-12)
    surface=Surface(Mesh.from_polygons(vertices,faces),owner='FarHills',stage='natural')
    y=np.array([-150.7,-125.,-99.1,-10.2,75.3])
    hit=surface.upper(np.full_like(y,-300.),y)
    np.testing.assert_allclose(hit.height,np.interp(y,axis,h),rtol=0,atol=1e-10)
    # Both sides of the original parent diagonal remain upward, and the new
    # nodes belong to faces rather than being unattached boundary witnesses.
    assert np.all(surface.normals[:,2]>0.)
    used={i for face in faces for i in face}
    assert all(any(i in used and abs(p[i,1]-v)<1e-10 for i in np.flatnonzero(p[:,0]==-300.)) for v in wanted)


def test_city_export_restores_air_apron_after_carving_but_not_the_rail_bed(monkeypatch):
    path=Path(__file__).resolve().parents[1]/'world/regions/hidamari/build.py'
    node=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='surface')
    scope=dict(np=np,math=math,M=RecordingMesh,height=lambda x,y:np.full_like(x,35.5),
        pond=lambda x,y:False,canal=lambda x,y:False,grass_patch=lambda x,y:True,
        land_use=lambda x,y:'park',ROAD_Y=[1000.],layout=SimpleNamespace(ISLAND_FADE=24.))
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),scope)
    monkeypatch.setattr(earthworks,'carve',lambda x,y,z:z-1.8)
    for xs,ys,wanted in [([1263.,1283.],[312.2,318.2],35.5),
                         ([1263.,1283.],[301.8,306.],33.7),
                         ([1239.,1240.],[328.,329.],33.7)]:
        mesh=scope['surface']('HD_Terrain',xs,ys,'park')
        np.testing.assert_allclose(np.asarray(mesh.vertices)[:,2],wanted,rtol=0,atol=1e-12)


def test_forest_repair_follows_changed_parent_support_beyond_the_analytical_fade(monkeypatch):
    # Actual failing row: the point is north of the 80m analytical fade, but
    # its original parent triangle reaches down into the changed rim.
    xs=np.array([-700.,-400.,-300.,-200.]);ys=np.array([300.,500.])
    grid=(xs,ys,np.full((len(ys),len(xs)),40.))
    monkeypatch.setattr(farhills_grid,'mesh_grid',lambda n:grid)
    monkeypatch.setattr(farhills_grid,'source_grid',lambda:grid)
    monkeypatch.setattr(earthworks,'carve',lambda x,y,z:z)
    monkeypatch.setattr(layout,'H',None)
    owned={'Tree_Maple_A':[[-300.77,436.59,103.97,307.,2.026],[-700.,500.,2.,20.,3.]]}
    world={'instances':{'Tree_Maple_A':[r.copy() for r in owned['Tree_Maple_A']],
                        'Tree_Cedar_B':[[-300.77,436.59,9.,30.,1.]]}}
    before=[r.copy() for r in world['instances']['Tree_Maple_A']]
    coastal_dressing.repair_west_forest(world,np.full((3,3),10.),owned)
    p=np.array(before[0][:2]);h=coast.sample_grid_mesh(*grid,p[0],p[1],
        shape=layout.coastal_backdrop_height,parents=grid,
        edge_knots={(0,-300.):np.linspace(-300.,300.,3)})
    assert world['instances']['Tree_Maple_A'][0]==[*before[0][:2],round(float(h-.3),2),*before[0][3:]]
    assert world['instances']['Tree_Maple_A'][0][2]!=before[0][2]
    assert world['instances']['Tree_Maple_A'][1]==before[1]
    assert world['instances']['Tree_Cedar_B']==[[-300.77,436.59,9.,30.,1.]]


def test_forest_repair_accepts_changed_scalar_points_inserted_on_the_fine_edge(monkeypatch):
    xs=np.array([-400.,-300.,-200.]);ys=np.array([-160.,80.])
    grid=(xs,ys,np.full((2,3),40.))
    monkeypatch.setattr(farhills_grid,'mesh_grid',lambda n:grid)
    monkeypatch.setattr(farhills_grid,'source_grid',lambda:grid)
    monkeypatch.setattr(earthworks,'carve',lambda x,y,z:z)
    monkeypatch.setattr(layout,'H',None)
    owned={'Tree_Maple_A':[[-310.,-100.,39.7,10.,2.]]}
    world={'instances':{'Tree_Maple_A':[r.copy() for r in owned['Tree_Maple_A']]}}
    coastal_dressing.repair_west_forest(world,np.full((3,3),10.),owned)
    vertices,faces=coast.grid_mesh(*grid,shape=layout.coastal_backdrop_height,parents=grid,
        edge_knots={(0,-300.):np.array([-300.,0.,300.])})
    assert any(x==-300. and y==0. for x,y,z in vertices)
    actual=Surface(Mesh.from_polygons(vertices,faces),owner='FarHills',stage='natural').upper(-310.,-100.)
    assert world['instances']['Tree_Maple_A'][0]==[-310.,-100.,round(float(actual.height-.3),2),10.,2.]
    assert world['instances']['Tree_Maple_A'][0][2]!=39.7
