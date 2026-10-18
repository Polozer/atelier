"""Bounded shipped sheet inputs before extracting the next regional owner."""
from unittest.mock import patch

import numpy as np

import yori  # noqa: F401
from train import earthworks


def inputs():
    return dict(
        vertices=np.array([[40., -8., 106.], [52., -8., 108.],
                           [52., 8., 110.], [40., 8., 107.]]),
        faces=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32),
        colours=np.array([[.16, .24, .08, .25], [.22, .31, .12, .5],
                          [.34, .38, .19, .75], [.28, .32, .14, 1.]]),
        normals=np.array([[0., .6, .8], [.6, 0., .8],
                          [0., -.6, .8], [-.6, 0., .8]]),
        source_name='bounded-r8-sheet')


def evaluate(carved):
    data = inputs()
    before = {key: value.copy() for key, value in data.items() if isinstance(value, np.ndarray)}
    line = earthworks.Line({'samples': [
        dict(s=float(s), x=float(s), y=0., rail_z=100., ground_z=104., **{'class': 'cutting'})
        for s in range(0, 410, 10)]})
    with patch.object(earthworks, 'line', return_value=None):
        result = earthworks.sheet(data, step=6., ln=line if carved else None)
    unchanged = all(np.array_equal(data[key], value) for key, value in before.items())
    return result, dict(input_arrays_unchanged=unchanged, returns_original=result is data)
