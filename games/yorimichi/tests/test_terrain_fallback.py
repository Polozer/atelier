"""Execute the exporter's pure ownership rules without starting Blender."""
import ast
from pathlib import Path

import numpy as np
import pytest

from test_shorelines import S


@pytest.fixture
def exporter():
    source=Path(__file__).resolve().parents[1]/'world/build_terrain.py'
    tree=ast.parse(source.read_text(),filename=str(source))
    functions=[node for node in tree.body if isinstance(node,ast.FunctionDef)
               and node.name in {'backdrop_owned','ocean_mesh'}]
    namespace={'shorelines':S}
    exec(compile(ast.Module(body=functions,type_ignores=[]),str(source),'exec'),namespace)
    return namespace


def test_fallback_retains_actual_ground_faces_under_the_missing_city(exporter):
    hidden=exporter['backdrop_owned']
    # These cells include the former hole, the fine terrain and both exterior
    # borders. Query actual generated faces, rather than only mask booleans.
    xs=np.array([-400.,-300.,300.,600.,1420.,1500.])
    ys=np.array([-400.,-300.,0.,300.,500.,600.])
    z=np.zeros((len(ys),len(xs)))
    before=lambda x,y:(-300.<x<300. and -300.<y<300.) or (300.<x<1420. and -300.<y<500.)
    old=S.grid_mesh(xs,ys,z,hidden=before,shape=lambda x,y,z:z)
    current=S.grid_mesh(xs,ys,z,hidden=lambda x,y:hidden(x,y,city=True),shape=lambda x,y,z:z)
    np.testing.assert_array_equal(current[0],old[0])
    assert current[1]==old[1]
    fallback=S.grid_mesh(xs,ys,z,hidden=lambda x,y:hidden(x,y,city=False),shape=lambda x,y,z:z)
    def hits(mesh,x,y):
        vertices,faces=mesh
        return sum(min(vertices[i][0] for i in f)<x<max(vertices[i][0] for i in f)
                   and min(vertices[i][1] for i in f)<y<max(vertices[i][1] for i in f) for f in faces)
    assert hits(current,900.,100.)==0
    assert hits(fallback,900.,100.)==1
    assert hits(fallback,0.,100.)==0  # The fine Terrain still supplies this.


def test_fallback_sea_fills_harbor_once_and_preserves_normal_export_bytes(exporter):
    mesh=exporter['ocean_mesh']
    old=S.sea_mesh()
    current=mesh(city=True)
    assert np.asarray(current[0]).tobytes()==np.asarray(old[0]).tobytes()
    assert np.asarray(current[1]).tobytes()==np.asarray(old[1]).tobytes()
    vertices,faces=mesh(city=False)
    p=np.asarray(vertices)
    rectangles=[(*p[f[0],:2],*p[f[2],:2]) for f in faces]
    assert np.all(p[:,2]==0.)
    assert sum((x1-x0)*(y1-y0) for x0,y0,x1,y1 in rectangles)==48000.**2
    assert sum(x0<600.<x1 and y0<-500.<y1 for x0,y0,x1,y1 in rectangles)==1
    for i,(x0,y0,x1,y1) in enumerate(rectangles):
        for a0,b0,a1,b1 in rectangles[i+1:]:
            assert max(0.,min(x1,a1)-max(x0,a0))*max(0.,min(y1,b1)-max(y0,b0))==0.
