"""Hidamari's ground meets its neighbours at the city's north-west corner, and the forest there stands on it.

North of the main terrain the city ground's west edge (x 300, y 300-500) borders the far hills and the foothills'
apron, and its north edge (y 500) the foothills. They once stood up to 18 m over the city there, opening a slit west
of the hippodrome, and Mega Park trees stood on the hidden far hills up to 8 m over the city ground (Op410).
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'world'))
import yori  # noqa: E402,F401
from hidamari import layout as L, mountains as M  # noqa: E402
from hidamari.forest_backdrop import ground  # noqa: E402

# The samplers read world.layout's generated outputs.
BUILT = all((yori.OUT / name).is_file() for name in
            ('farhills.npy', 'heightmap.npy', 'world.json', 'megapark/trail.json'))


@unittest.skipUnless(BUILT, 'needs world.layout')
class CityWestSeam(unittest.TestCase):
    def test_far_hills_meet_the_city_west_edge(self):
        ys = np.linspace(300., 500., 201)
        city = L.height(np.full_like(ys, 300.), ys)
        self.assertLess(float(np.abs(L.far_height(np.full_like(ys, 300.), ys) - city).max()), 1e-6)

    def test_apron_meets_the_city_west_edge(self):
        ys = np.linspace(M.BOUNDS[1] - 62., M.BOUNDS[1], 40)
        ys = ys[M.in_apron(np.full_like(ys, 299.9), ys)]
        self.assertTrue(len(ys))
        apron = M.skirt_height(np.full_like(ys, 300.), ys, L.north_base_height)
        self.assertLess(float(np.abs(apron - L.height(np.full_like(ys, 300.), ys)).max()), 1e-6)

    def test_foothills_south_edge_is_the_city_north_edge(self):
        xs = np.arange(300., 1421., 5.)
        ys = np.full_like(xs, M.BOUNDS[1])
        foothills = M.height(xs, ys, L.north_base_height, carved=False)
        self.assertLess(float(np.abs(foothills - L.height(xs, ys)).max()), 1e-6)

    def test_forest_stands_on_the_city_ground_on_its_footprint(self):
        x, y = np.meshgrid(np.arange(302., 420., 3.), np.arange(380., 500., 3.))
        x, y = x.ravel(), y.ravel()
        z = ground(x, y, L.height, L.backdrop_grid, L.terrain_axes, L.north_height)
        # The placement surface is HD_Terrain's triangles; height() is the smooth surface they sample.
        self.assertLess(float(np.abs(z - L.height(x, y)).max()), .25)

    def test_foothills_mesh_shares_the_city_north_edge_vertices(self):
        """Built mesh, whole edge: the foothills' emitted south edge carries HD_Terrain's own edge vertices
        (city_north_edge), so the two edge polylines are one. With 5 m knots alone it sagged up to 0.11 m between
        them where the city's profile bends (x 300-370)."""
        sheet = M.sheets(L.north_base_height)[0]
        v = np.asarray(sheet['vertices'], float)
        edge = v[(np.abs(v[:, 1] - M.BOUNDS[1]) < 1e-6) & (v[:, 0] >= 300.) & (v[:, 0] <= 1420.)]
        edge = edge[np.argsort(edge[:, 0])]
        kx, kz = L.city_north_edge()
        self.assertTrue(set(np.round(kx, 6)) <= set(np.round(edge[:, 0], 6)))
        x = np.linspace(300., 1420., 22401)
        self.assertLess(float(np.abs(np.interp(x, edge[:, 0], edge[:, 2]) - np.interp(x, kx, kz)).max()), 1e-6)
        # Every edge vertex belongs to a face (no dangling knots) and the faces stay counter-clockwise from above.
        f = np.asarray(sheet['faces'])
        p = v[f]
        area = (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1])
        self.assertGreater(float(area.min()), 0.)


if __name__ == '__main__':
    unittest.main()
