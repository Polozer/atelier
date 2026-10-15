"""The finite orange continuation at the shared-room choice point.

A single quarter pipe and integral apron turn the rider ninety degrees. The
separate forward transfer leaves through the other portal.
"""
import math
from dataclasses import dataclass

import numpy as np

from . import junctions as J, shared14
from .layout import LineSpec, Turtle, elbow_spec

WIDTH = 32.
RADIUS = 14.
VERT = 1.
DRIFT = 55.
ACROSS = np.unique(np.r_[-16., -15., np.arange(-14., 15., 2.), 15., 16.])


@dataclass
class Choice:
    line: LineSpec
    spec: dict
    inlet: np.ndarray
    outlet: np.ndarray

    def row(self, point, heading):
        n = J.direction(heading + 90.)
        q = point + ACROSS[:, None] * n
        return np.c_[q[:, 0], np.full(len(q), shared14.OUTLET_Y), q[:, 1]]


def definition():
    """Actual room port, finite R14 quarter pipe, and a broad return mouth.

    The 32 m clear mouth MUST remain wide enough for the measured along-wall
    speed-dependent drift; it MUST NOT be funnelled to an 18 m lane at the wall.
    """
    room = shared14.definition()
    inlet = room.body.point([room.body.length])[0] + shared14.ORANGE_OFFSET * room.body.normal([room.body.length])[0]
    tangent = room.body.tangent([room.body.length])[0]
    heading = math.degrees(math.atan2(tangent[1],tangent[0])) % 360.
    run = 6. * math.sqrt(2.) + WIDTH / 2.
    params = dict(r=RADIUS, vert=VERT, deck=3., apron=6., width=WIDTH,
                  drift=DRIFT, lip_min=40.)
    path = Turtle(tuple(inlet), heading, (('straight', run), ('elbow', -90., params), ('straight', run)))
    line = LineSpec('V14', 'Orange vert continuation', path, shared14.OUTLET_Y,
                    (('line', path.length),), (), 'shared choice', 'orange straight', rollin=0)
    spec = elbow_spec(line, 0)
    if abs(spec['s_in']) > 1e-7 or abs(spec['s_out'] - path.length) > 1e-7:
        raise ValueError('choice vert: actual apron port differs from the room portal')
    outlet = np.asarray(path.at(path.length)[0])
    return Choice(line, spec, inlet, outlet)


def build(choice=None):
    choice = definition() if choice is None else choice
    return J.elbow(choice.spec, ground=shared14.OUTLET_Y - 1.5, on_ground=False,
                   rows=[choice.row(choice.inlet, choice.spec['heading_in']),
                         choice.row(choice.outlet, choice.spec['heading_out'])])
