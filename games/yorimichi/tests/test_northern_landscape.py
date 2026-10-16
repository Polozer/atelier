"""The northern woodland remains green; the crater has an exposed rock rim."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'world'))
import yori  # noqa: E402,F401
from hidamari import mountains as M, layout as H  # noqa: E402
from belmonte.appearance import far_palette  # noqa: E402
from megapark import gate  # noqa: E402

# The terrain and trail samplers read world.layout's generated outputs.
BUILT=all((yori.OUT/name).is_file() for name in
          ('farhills.npy','heightmap.npy','world.json','megapark/trail.json'))


class NorthernLandscape(unittest.TestCase):
    @unittest.skipUnless(BUILT,'needs world.layout')
    def test_raised_northern_ground_has_no_absolute_height_rock_band(self):
        x=np.array([0.,550.,1200.]);y=np.full_like(x,M.BOUNDS[3]-50.)
        colours=M.colours(x,y,H.north_height(x,y))
        self.assertTrue(np.all(colours[:,1]>colours[:,0]*1.3),colours)
        y[:]=M.BOUNDS[3]
        np.testing.assert_allclose(M.colours(x,y,H.north_height(x,y)),far_palette(x,y),atol=1e-12)

    @unittest.skipUnless(BUILT,'needs world.layout')
    def test_snow_keeps_crater_rim_exposed_and_collects_in_bowl(self):
        x,y,z=M.surface_grid(H.north_base_height)
        _,_,radius,angle=M.polar(x,y)
        snow=M.snow(x,y,H.north_base_height)
        self.assertLess(float(snow[np.abs(radius-M.rim_radius(angle))<15].mean()),.15)
        floor_white=float((snow[radius<M.FLOOR_RADIUS-40]>.5).mean())
        self.assertGreater(floor_white,.6)
        self.assertLess(floor_white,.9)
        # Snow still runs down the flanks in gullies, and none lies beyond them.
        flank=(radius>M.RIM_RADIUS+100)&(radius<M.stretch(520))
        self.assertGreater(float((snow[flank]>.5).mean()),.08)
        self.assertEqual(float(snow[radius>M.BASE_RADIUS].max()),0.)
        self.assertTrue(np.all((snow>=0)&(snow<=1)))

    @unittest.skipUnless(BUILT,'needs world.layout')
    def test_snow_texture_preserves_linear_bytes_and_world_orientation(self):
        import json
        import tempfile
        from PIL import Image
        field=M.snow_grid(H.north_base_height)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            M.export_snow_mask(path,H.north_base_height)
            image=Image.open(path/'north_snow.png')
            self.assertEqual(image.mode,'L')
            self.assertEqual(image.size,(1024,1024))
            np.testing.assert_array_equal(np.asarray(image),field)
            meta=json.loads((path/'north_snow.json').read_text())
            self.assertTrue(meta['linear'])
        # Asymmetric points detect a flipped PNG or swapped world axes.
        for iy,ix in ((310,417),(541,526),(690,488)):
            x=M.SNOW_BOUNDS[0]+ix*M.SNOW_STEP
            y=M.SNOW_BOUNDS[1]+iy*M.SNOW_STEP
            self.assertAlmostEqual(float(M.snow(x,y,H.north_base_height)),int(field[iy,ix])/255.,places=12)
        x,y,z=M.surface_grid(H.north_base_height)
        outside=(x<M.SNOW_BOUNDS[0])|(x>M.SNOW_BOUNDS[2])|(y<M.SNOW_BOUNDS[1])|(y>M.SNOW_BOUNDS[3])
        authored=M.snow_cover(x,y,z)
        self.assertEqual(float(authored[outside].max()),0.,'Snow would be lost beyond the texture footprint')

    def test_crater_mask_covers_the_floor_not_the_crags_and_keeps_its_bytes(self):
        import json
        import tempfile
        from PIL import Image
        field=M.crater_grid()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            M.export_crater_mask(path)
            image=Image.open(path/'north_crater.png')
            self.assertEqual((image.mode,image.size),('L',(1024,1024)))
            np.testing.assert_array_equal(np.asarray(image),field)
            meta=json.loads((path/'north_crater.json').read_text())
            snow={'bounds':list(M.SNOW_BOUNDS),'step_m':M.SNOW_STEP}
            self.assertEqual({k:meta[k] for k in snow},snow,'the material samples it as the snow mask')
            self.assertTrue(meta['linear'])
        # Asymmetric texels detect a flipped PNG or swapped world axes.
        for iy,ix in ((512,512),(530,600),(470,380),(512,700)):
            x=M.SNOW_BOUNDS[0]+ix*M.SNOW_STEP
            y=M.SNOW_BOUNDS[1]+iy*M.SNOW_STEP
            self.assertEqual(int(field[iy,ix]),int(np.rint(float(M.crater_floor(x,y))*255)))
        angle=np.linspace(0,2*np.pi,90,endpoint=False)
        cx,cy=M.VOLCANO
        for r,want in ((M.wall_foot(angle)-10,1.),(M.rim_radius(angle)-12,0.)):
            got=M.crater_floor(cx+r*np.cos(angle),cy+r*np.sin(angle))
            np.testing.assert_allclose(got,want,atol=1e-9)

    def test_species_transition_is_shared_continuous_and_preserves_roots(self):
        from forest.ecotone import tuscan_mask,northern_ecotone
        join=M.BOUNDS[3]
        x=np.linspace(-400,1500,1901)
        south=tuscan_mask(x,np.full_like(x,join-.25))
        north=tuscan_mask(x,np.full_like(x,join+.25))
        self.assertLess(float(np.mean(south!=north)),.015)
        self.assertFalse(tuscan_mask(x,np.full_like(x,join-500.)).any())
        self.assertTrue(tuscan_mask(x,np.full_like(x,join+500.)).all())
        rows=[[float(xx),join,100.,37.,1.] for xx in x[::50]]
        instances={'Tree_Forest_Maple':rows.copy()}
        northern_ecotone(instances)
        actual=[row for group in instances.values() for row in group]
        self.assertEqual(len(actual),len(rows))
        self.assertEqual(sorted(tuple(row[:4]) for row in actual),sorted(tuple(row[:4]) for row in rows))

    @unittest.skipUnless(BUILT,'needs world.layout')
    def test_the_apron_closes_the_slit_under_the_foothills_edges(self):
        from megapark.trail import _far_hills
        xs=np.arange(M.BOUNDS[0],M.BOUNDS[2]+1,M.STEP);ys=np.arange(M.BOUNDS[1],M.BOUNDS[3]+1,M.STEP)
        (sx,sy),_,(ex,ey)=M.apron_grids(xs,ys)
        # It meets the foothills' south edge, where the city does not, and the far hills' first unlowered line.
        edge=M.apron_cell_open(xs,np.full_like(xs,M.BOUNDS[1]-1.))
        np.testing.assert_allclose(M.skirt_height(xs[edge],np.full(edge.sum(),M.BOUNDS[1]),H.north_base_height),
                                   M.height(xs[edge],np.full(edge.sum(),M.BOUNDS[1]),H.north_base_height),atol=1e-3)
        outer=sx[M.apron_cell_open(sx,np.full_like(sx,sy[0]+1.))]
        np.testing.assert_allclose(M.skirt_height(outer,np.full_like(outer,sy[0]),H.north_base_height),
                                   _far_hills(outer,np.full_like(outer,sy[0]),upper=True),atol=1e-3)
        # Nowhere does it sink below the far hills, so no opening is left; trees placed on north_height stand on it.
        x,y=np.meshgrid(sx[::7],sy);open_=M.in_apron(x,y)
        z=M.skirt_height(x[open_],y[open_],H.north_base_height)
        self.assertGreaterEqual(float((z-_far_hills(x[open_],y[open_])).min()),-1e-3)
        np.testing.assert_allclose(H.north_height(x[open_],y[open_]),z,atol=1e-6)
        self.assertTrue(M.in_apron(np.array([2430.]),np.array([1600.]))[0])

    def test_the_south_edge_meets_the_forest_floor_beside_the_city_grass(self):
        # Away from the city the edge takes the far hills' forest floor (M_ForestGround); beside it, the city's grass.
        y=np.array([470.,470.,470.,470.]);x=np.array([-500.,100.,1800.,800.])
        colours=M.colours(x,y,np.full_like(x,100.))
        np.testing.assert_allclose(colours[:3],np.tile([.055,.11,.035],(3,1)),atol=3e-3)   # the Mega Park's litter
        np.testing.assert_allclose(colours[3],[.24,.30,.12],atol=3e-3)

    def test_fine_cells_are_excluded_at_both_patch_edges(self):
        for bounds,inside in [(gate.GATE,gate.cell_inside)]:
            x0,y0,x1,y1=bounds
            self.assertTrue(inside(x1-M.STEP,y1-M.STEP,M.STEP))
            self.assertFalse(inside(x1,y1,M.STEP))

    def test_caldera_floor_holds_a_340_by_390_m_park_under_a_low_rim(self):
        cx,cy=M.VOLCANO
        # A 340 x 390 m footprint at any heading lies on the level floor.
        u,v=np.meshgrid(np.linspace(-170,170,35),np.linspace(-195,195,40))
        for heading in np.radians(np.arange(0,180,15)):
            z=M.natural_height(cx+u*np.cos(heading)-v*np.sin(heading),cy+u*np.sin(heading)+v*np.cos(heading))
            self.assertLess(float(np.ptp(z)),3.)
            self.assertLess(float(np.abs(z-M.caldera_floor()).max()),2.)
        # The crest stands at least 40 m over the floor all the way round: Crater Park stands high in it.
        angles=np.arange(128)*np.pi/64
        radii=np.arange(300.,600.,2.5)
        crest=M.natural_height(cx+np.cos(angles[:,None])*radii,cy+np.sin(angles[:,None])*radii).max(axis=1)
        self.assertGreater(float(crest.min()-M.caldera_floor()),40.)
        self.assertGreater(float(np.ptp(crest)),40.)     # broken, not a drawn circle
        # Crater Park (a 337.95 x 384.51 m block, corner radius 256 m) keeps 60 m to the wall's foot at any heading.
        self.assertGreater(float(M.wall_foot(np.linspace(0,2*np.pi,1440)).min())-256.,60.)
        self.assertLess(float(crest.max()),850.)

    def test_the_former_summit_keeps_the_ground_round_the_mega_park(self):
        import math
        a=np.linspace(0,2*math.pi,72,endpoint=False)
        # Within 450 m of its centre (the park and its terrain stamp) the ground is the former summit's own.
        for reach in (350.,450.):
            x=-150+reach*np.cos(a);y=1300+reach*np.sin(a)
            trail_quiet=M.smooth((M.trail_distance(x,y)-15)/100)
            former=M._foothills(x,y,trail_quiet)+M._former_cone(x,y,trail_quiet)
            former=47+(former-47)*M.smooth(np.maximum(y-500,0)/180)
            np.testing.assert_allclose(M.natural_height(x,y),np.maximum(former,M.natural_height(x,y)),atol=1e-9)
            self.assertLess(float(np.abs(M.natural_height(x,y)-former).max()),7.)


if __name__=='__main__':unittest.main()
