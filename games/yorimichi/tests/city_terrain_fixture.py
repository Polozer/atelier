"""Bounded city surface emissions, before Blender packing and triangulation.

Only the production surface function is compiled; its explicit callbacks and
recording Mesh avoid importing the Blender asset builder in ordinary Python CI.
This captures evaluation order, not the native Mesh adapter's float conversion.
"""
import ast
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import yori  # noqa: F401
from train import earthworks


SOURCE = Path(__file__).resolve().parents[1]/'world/regions/hidamari/build.py'
CASES = {
    'coarse_holes': ([400., 404., 410., 416.], [0., 4., 10.]),
    'coast': ([300., 307., 318.], [-140., -130., -124.]),
    'island_fade': ([300., 312., 324., 330.], [0., 4.]),
    'park_refinement': ([981., 982.2], [225., 226.1]),
    'terrace_refinement': ([651., 652.2], [256., 257.1]),
    'paving': ([380., 386.], [-119., -113.]),
    'other_surface': ([400., 404.], [0., 4.]),
}
PALETTE = {'park': (.24, .30, .12), 'paving': (.22, .18, .125),
           'hd_grass': (.125, .18, .048), 'hd_yard': (.15, .115, .07),
           'hd_flag': (.20, .172, .128), 'hd_flag2': (.18, .155, .115)}


class RecordingMesh:
    """Record nondegenerate emitted quads without DCC rounding or transforms."""
    def __init__(self, name):
        self.name = name
        self.vertices, self.faces, self.colors, self.keys = [], [], [], []

    def poly(self, points, key):
        points = [tuple(map(float, point)) for point in points]
        assert len(points) == 4 and len(set(points)) == 4
        assert np.linalg.norm(np.cross(np.subtract(points[1], points[0]),
                                       np.subtract(points[3], points[0]))) > 1.e-10
        start = len(self.vertices)
        self.vertices.extend(points)
        self.faces.append(tuple(range(start, start+4)))
        self.colors.extend([(*PALETTE[key], 0.)]*4)
        self.keys.append(key)


def evaluate(case, *, source=None, capture_natural=False):
    """Run the current emitter with explicit nonlinear height and carved grid."""
    path = SOURCE if source is None else Path(source)
    tree = ast.parse(path.read_text(), filename=str(path))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'surface']
    assert len(functions) == 1
    xs, ys = (np.asarray(axis) for axis in CASES[case])
    before = xs.copy(), ys.copy()
    calls = {'height': [], 'carve': [], 'colours': []}

    def height(x, y):
        x, y = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
        calls['height'].append([list(x.shape), float(x.min()), float(x.max()), float(y.min()), float(y.max())])
        return 12.+.017*x+.031*y+.0007*x*y+.03*np.sin(x*.11+y*.07)

    def carve(x, y, z):
        calls['carve'].append({'shape': list(z.shape), 'before': z.tolist()})
        return z-1.25+.0003*np.asarray(x)

    def grass(x, y):
        return not (case == 'paving' and 382. < x < 398. and -119. < y < -106.)

    def land_use(x, y):
        return 'hd_grass' if case == 'island_fade' or (case == 'coarse_holes' and x > 410.) else 'hd_yard'

    def colours(x, y, z, nz, base):
        calls['colours'].append({'x': x.tolist(), 'y': y.tolist(), 'z': z.tolist(), 'nz': nz.tolist()})
        return np.asarray(base)[None, :]*(1.+.002*z[:, None]+.01*nz[:, None])

    def fade(x):
        t = np.clip((np.asarray(x)-300.)/24., 0., 1.)
        return t*t*(3.-2.*t)

    # Paving uses the same height except one deliberately ineligible strip.
    def street_height(x, y):
        return height(x, y)+np.where(np.asarray(x) > 390., .02, 0.)

    scope = dict(np=np, math=math, M=RecordingMesh, height=height, grass_patch=grass,
                 pond=lambda x, y: case == 'coarse_holes' and x == 402. and y == 2.,
                 canal=lambda x, y: case == 'coarse_holes' and x == 413. and y == 7.,
                 land_use=land_use, street_height=street_height, ROAD_Y=[1000.],
                 layout=SimpleNamespace(ISLAND_FADE=24., ISLAND_LAWN=(.19, .23, .08), island_fade=fade),
                 shorelines=SimpleNamespace(colours=colours), v=SimpleNamespace(PALETTE=PALETTE))
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), scope)
    natural = RecordingMesh('HD_Terrain') if capture_natural else None
    with patch.object(earthworks, 'carve', carve):
        mesh = scope['surface']('Other' if case == 'other_surface' else 'HD_Terrain', xs, ys, 'paving',
                                **({'_natural': natural} if capture_natural else {}))
    result = dict(vertices=mesh.vertices, faces=mesh.faces, colours=mesh.colors, keys=mesh.keys,
                  calls=calls, axes_unchanged=np.array_equal(xs, before[0]) and np.array_equal(ys, before[1]))
    if capture_natural:
        result['natural'] = dict(vertices=natural.vertices, faces=natural.faces)
    return result
