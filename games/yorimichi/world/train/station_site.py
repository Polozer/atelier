"""The Belmonte station's site (plain Python, numpy only): its footprint, levels and forecourt, in the
frame of the line's Belmonte end. Read by the earthworks (the ground the station stands on) and the corridor (no plants
on it). Nothing here applies to a line that does not end at the site (for_line): the committed riverside terminus keeps
its ground and planting unchanged.

Station frame: origin at the end of the line (route.json's last sample, rail top), `a` metres along the track towards
the buffer stop and beyond (the facade side), `u` metres to the left of a train arriving, z up from the rail top.
The buffer stop stands at a = -track.BUFFER_OFFSET.

The rail reaches Belmonte 8.6 m under the road from the south-east gate (route v4, Paul 2026-10-17), so the station
stands in a shallow cutting: platforms and the concourse at platform level, the headhouse's vestibule and the forecourt
at street level (STREET over the rail), with a grand staircase between them inside the headhouse.
"""
import math

import numpy as np

# Paul, 2026-10-18: the train will grow 15 % (today 131 m long, 3.60 m wide, 4.30 m tall); the station takes it.
TRAIN_SCALE = 1.15
TRAIN_LENGTH = 131. * TRAIN_SCALE           # 150.7 m; the head stops 10 m short of the buffer (route.STOP_CLEARANCE)
SHED_LENGTH = 175.          # the sheds cover the whole train with 14 m to spare
PLATFORM = 1.0              # platform top over the rail (the train service's arrival spot and boarding steps)
EDGE = round(1.80 * TRAIN_SCALE + .05, 2)   # 2.12: platform edges from a track's centre, clear of the scaled body
STREET = 7.2                # the vestibule and the forecourt over the rail (214.8 m)
FORMATION = -.85            # the ground under the track and the buildings (earthworks.FORMATION_DROP)
SIDING = -29.               # the decorative siding's centre (second shed)
# Rectangles (a0, a1, u0, u1) in the station frame.
SHEDS = (-SHED_LENGTH - 3., 0., -45., 15.5)             # the two train sheds, their outer walls and rear pavilions
HEADHOUSE = (0., 26., -55., 26.)            # the street building: wings, vestibule, gallery and stairs
FORECOURT = (26., 46., -57., 28.)           # the square in front of the facade, at street level
AXIS_U = -14.5                              # the building's axis of symmetry (the clock tower)
WALL_SLOPE = .05            # horizontal per vertical: the ground stands against the station's walls
ROAD_CLEAR = 3.             # plants keep this far off the footprint
# The road from the south-east gate to the Dunes Basses estate crosses the cutting 229 m before the buffer stop. It
# keeps its line and level: a stone deck carries it (the overbridge) and retaining walls stand WALL_HALF either side
# of the track along WALL_LENGTH each way, so the cutting does not reach the road. deck_z: the road's ground there.
OVERBRIDGE = dict(xy=(999.0, 4542.0), road_bearing=17.5, wall_half=5.0, wall_length=16., deck_z=216.2)
WALL_FADE = 6.              # metres over which the cutting's walls give way to its ordinary slopes


class Site:
    """The station frame at the end of a line given as samples (x, y, rail z), and its zones in world metres."""

    def __init__(self, xy, rail):
        xy = np.asarray(xy, float)
        self.origin = xy[-1]
        d = xy[-1] - xy[-2]
        self.t = d / np.hypot(*d)                       # along the track, towards the buffer stop
        self.n = np.array([-self.t[1], self.t[0]])      # left of an arriving train
        self.rail = float(rail[-1])
        self.heading = math.atan2(self.t[1], self.t[0])

    def world(self, a, u):
        a, u = np.asarray(a, float), np.asarray(u, float)
        return self.origin + a[..., None] * self.t + u[..., None] * self.n

    def local(self, x, y):
        d = np.stack([np.asarray(x, float) - self.origin[0], np.asarray(y, float) - self.origin[1]], -1)
        return d @ self.t, d @ self.n

    def zones(self):
        """(rectangle, floor height) of the ground the station stands on: the sheds at the formation, the headhouse
        at the formation (its walls retain the street), the forecourt at street level."""
        return [(SHEDS, self.rail + FORMATION), (HEADHOUSE, self.rail + FORMATION), (FORECOURT, self.rail + STREET)]


def for_line(xy, rail):
    """@cc [owner:fontanierh,label:correctness] station-site-gate
    A line that does not end at Belmonte's station site MUST get None, so its
    earthworks, corridor and carved terrain stay exactly as without the station.
    Otherwise the station's Site at the end of the line given by its last samples.
    """
    xy = np.asarray(xy, float)
    rail = np.asarray(rail, float)
    if xy.ndim != 2 or xy.shape[0] < 2 or xy.shape[1] != 2 or rail.size < 1:
        return None
    if not (np.isfinite(xy[-2:]).all() and np.isfinite(rail[-1])):
        return None
    if np.hypot(*(xy[-1] - xy[-2])) < 1e-6:
        return None
    if np.hypot(*(xy[-1] - np.asarray(OVERBRIDGE['xy']))) > 300.:
        return None
    return Site(xy, rail)


def rect_excess(a, u, rect):
    """Metres outside the rectangle (0 inside)."""
    a0, a1, u0, u1 = rect
    da = np.maximum(np.maximum(a0 - a, a - a1), 0.)
    du = np.maximum(np.maximum(u0 - u, u - u1), 0.)
    return np.hypot(da, du)


def inside(site, x, y, margin=0.):
    """True on the footprint and forecourt (plus `margin`)."""
    return excess(site, x, y) <= margin


def excess(site, x, y):
    """Metres beyond the station's ground (0 on it): the sheds, the headhouse and the forecourt."""
    a, u = site.local(x, y)
    return np.min([rect_excess(a, u, rect) for rect, _ in site.zones()], axis=0)
