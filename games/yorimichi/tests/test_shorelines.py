"""Regressions for the continuous coast, occupied ground and exported waterline."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'world'))
import shorelines as S  # noqa: E402


def test_inland_town_and_railway_terrain_is_unchanged():
    x = np.array([-475., 550., 1574., 2450., 2490., 1231., -700.])
    y = np.array([3900., 4500., 5692., 1550., 2220., 301., 2400.])
    base = np.array([210., 250., 230., 180., 240., 32., 120.])
    np.testing.assert_array_equal(S.height(x, y, base), base)


def test_existing_road_and_quay_top_are_protected():
    x, y = np.meshgrid(np.linspace(-300., 1420., 79), [-125., -100., -90., 0.])
    base = 2.4+.04*(y+125.)
    # The quay's new submerged ground begins below its coping; its top is retained.
    mask = ~((x >= 420.) & (x <= 900.) & (y == -125.))
    np.testing.assert_array_equal(S.height(x, y, base)[mask], base[mask])
    np.testing.assert_array_equal(S.height(x, np.maximum(y, -124.), base), base)


def test_old_zero_height_country_aprons_are_submerged():
    y = np.linspace(3700., 7100., 90)
    for x in [-3200., -3100., 3100., 3200.]:
        h = S.height(np.full_like(y, x), y, np.zeros_like(y))
        assert np.max(h) < -.5
    x = np.linspace(-3200., 3200., 130)
    assert np.max(S.height(x, np.full_like(x, 7100.), 0.)) < -5.


def test_profile_has_dry_land_and_a_continuous_underwater_toe():
    for y in [800., 2400., 4600., 6000.]:
        x = np.linspace(2500., 3200., 1401)
        z = S.height(x, np.full_like(x, y), 180.)
        assert z.min() <= -15.
        assert z.max() > 30.
        assert np.count_nonzero((z > .2) & (z < 3.)) > 2
        assert np.max(np.abs(np.diff(z))) < 4.


def test_country_export_has_no_sea_level_quads_and_faces_up():
    xs = np.array([2800., 3000., 3200.]); ys = np.array([4500., 4550.])
    vertices, faces = S.grid_mesh(xs, ys, np.zeros((2, 3)))
    p = np.asarray(vertices); f = np.asarray(faces)
    assert len(f) > 100
    assert not np.any(np.all(np.abs(p[f, 2]) < .001, axis=1))
    normals = np.cross(p[f[:, 1]]-p[f[:, 0]], p[f[:, 3]]-p[f[:, 0]])
    assert np.all(normals[:, 2] > 0.)
    assert np.max(np.abs(p[:, 2])) > 1.


def test_harbor_piers_and_canal_approach_remain_over_water():
    x, y = np.meshgrid(np.arange(480., 841., 60.), [-136., -160., -200.])
    assert np.max(S.height(x, y, 3.)) < -.2
    assert S.height(848., -145., 3.) < -1.


def test_shore_vegetation_clearance_and_palette_are_finite():
    x, y = np.meshgrid(np.linspace(-3200., 3200., 151), np.linspace(-300., 7100., 101))
    z = S.height(x, y, 200.)
    colour = S.colours(x, y, z, np.ones_like(z), [.055, .11, .035])
    assert colour.shape == (*x.shape, 3)
    assert np.isfinite(colour).all() and np.all((colour >= 0.) & (colour <= 1.))
    d, _ = S.field(x, y)
    assert not S.vegetation(x[d < 0.], y[d < 0.]).any()


def test_harbor_and_open_sea_partition_the_surface_without_an_overlap():
    vertices,faces=S.sea_mesh()
    p=np.asarray(vertices);f=np.asarray(faces)
    assert np.all(p[:,2]==0.)
    rectangles=[(*p[ids[0],:2],*p[ids[2],:2]) for ids in f]+[S.HARBOR_RECT]
    area=sum((x1-x0)*(y1-y0) for x0,y0,x1,y1 in rectangles)
    assert area==(48000.)**2
    for i,(x0,y0,x1,y1) in enumerate(rectangles):
        for a0,b0,a1,b1 in rectangles[i+1:]:
            assert max(0.,min(x1,a1)-max(x0,a0))*max(0.,min(y1,b1)-max(y0,b0))==0.


def test_beach_clearance_preserves_town_planting_and_the_separate_islet():
    rows=[[0.,-170.,2.,0.,1.],[600.,-112.,3.,0.,1.],[-150.,-530.,82.,0.,1.]]
    instances={'Tree_Maple_A':rows.copy(),'SW_Stand':rows.copy()}
    assert S.clear_vegetation(instances)==1
    assert instances['Tree_Maple_A']==rows[1:]
    assert instances['SW_Stand']==rows
