"""Small r8 production-function inputs, independent of generated world caches."""
from unittest.mock import patch

import numpy as np

import yori  # noqa: F401
import shorelines
from belmonte.source import Surface
from train import earthworks


def _grid(xs, ys, z, *, parents=None, refinement=None, curved=False):
    def shape(x, y, base):
        return base+.2*x*x-.07*y*y if curved else base
    with patch.object(shorelines, 'field', lambda x, y: (np.zeros_like(x), np.zeros_like(x))), \
         patch.object(shorelines, 'reach', lambda x, y: np.full_like(x, 1000.)):
        vertices, polygons = shorelines.grid_mesh(xs, ys, z, step=4., shape=shape,
                                                  parents=parents, parent_refinement=refinement)
    faces = [(p[0], p[k], p[k+1]) for p in polygons for k in range(1, len(p)-1)]
    return np.asarray(vertices), np.asarray(faces), {}


def _parent_grid(xs, ys, parents, **kwargs):
    from belmonte.terrain import grid_height
    x, y = np.meshgrid(xs, ys)
    return _grid(xs, ys, grid_height(*parents, x, y), parents=parents, **kwargs)


def _neighbor():
    class LowerTriangle:
        def project(self, x, y):
            y = np.asarray(y)
            return np.where(y < 0., 0., np.nan), np.zeros_like(y), np.zeros_like(y)
    span = 2.694580078125
    vertices = np.array([[0., 0., 0.], [span, 0., 0.], [0., span, 0.], [0., -span, 0.]])
    faces = np.array([[0, 1, 2], [1, 0, 3]])
    def carve(x, y, z, ln=None):
        return np.where(np.asarray(x) < 1.e-10, 152.651, 10.822347640991211+
                        (span-np.asarray(x))*(10.97188949584961-10.822347640991211)/(span/3.))
    with patch.object(earthworks, 'touched', lambda p, ln: np.ones(len(p), bool)), \
         patch.object(earthworks, 'carve', carve):
        v, f, attributes, report = earthworks.refine(vertices, faces, span/2.,
            {'colour': vertices[:, :1]+1.}, LowerTriangle(), holes=False, conform_neighbors=True)
    return v, f, {'attributes': {k: a.tolist() for k, a in attributes.items()}, 'report': report}


def _portal():
    line = earthworks.Line({'samples': [
        {'s': float(s), 'x': float(s), 'y': 0., 'rail_z': 100., 'ground_z': 100.,
         'class': 'cutting' if s < 150 else 'tunnel' if s < 250 else 'embankment'}
        for s in range(0, 410, 10)]})
    x, y = np.meshgrid([140., 150., 160.], [-12., 0., 12.])
    v = np.stack((x, y, np.full_like(x, 115.)), -1).reshape(-1, 3)
    f = [(a, a+1, a+4) for a in [0, 1, 3, 4]]+[(a, a+4, a+3) for a in [0, 1, 3, 4]]
    v, f, _, report = earthworks.refine(v, f, 5., ln=line, conform_neighbors=True)
    return v, f, {'report': report}


def cases():
    parents = (np.array([0., 12.]), np.array([0., 7.]), np.array([[1., 3.], [4., 11.]]))
    transition = (np.array([0., 12., 24.]), parents[1], np.array([[1., 3., 7.], [4., 11., 13.]]))
    return {
        'inserted_parent_saddle': (*_parent_grid([0., 2., 12.], [0., 3., 7.], parents),
                                    [[1., 2.], [5., 3.], [11., 6.]]),
        'asymmetric_curved_sampling': (*_grid([0., 10.], [0., 14.], [[1., 2.], [3., 8.]], curved=True),
                                         [[2.5, 3.5], [7., 4.], [3., 12.], [9., 13.]]),
        'rail_lattice_transition': (*_parent_grid([0., 4., 12., 24.], [0., 3., 7.], transition,
                                                  refinement={(0, 0): 5}),
                                      [[1., 2.], [11., 6.], [13., 5.], [23., 1.]]),
        'selected_retained_shared_edge': (*_neighbor(), [[.1, 0.], [1., 0.], [2., 0.], [.5, .5]]),
        'portal_opening': (*_portal(), [[140., 0.], [146., 0.], [155., 0.], [150., 10.]]),
    }


def sampled_heights(vertices, faces, queries):
    xy = np.asarray(queries)
    heights = Surface(vertices[faces]).height(xy[:, 0], xy[:, 1])
    return [float(z) if np.isfinite(z) else None for z in heights]
