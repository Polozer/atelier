"""Raise the corners of a Tripo face's mouth.

Used by cleanup_face_hair.py (step 7). Tripo sculpted the boy's lower lip as an arc whose ends drop about 1.6 mm below
its middle, and the mouth line projected from the drawing ends in small downward hooks: together they read as a pout.
The drawing's mouth is a short level line. corners() lifts the face's surface around the mouth corners: nothing at
the middle of the mouth, growing with the square of the distance from it to RISE at the corners, fading out past the
corners into the cheeks and above and below the lips. Only the face piece moves, only on the front of the head, and
only vertically, so the painted mouth line bends up with the surface.
"""
import math

import numpy as np


def smoothstep(edge0, edge1, x):
    t = min(max((x - edge0) / (edge1 - edge0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def corners(mesh, world, face_polygons, centre_y, centre_z, half_width, rise):
    """Lift the mouth corners by `rise` metres; returns a record of what moved."""
    from mathutils import Vector
    inverse = world.inverted()
    vertices = {v for i in face_polygons for v in mesh.polygons[i].vertices}
    moved, largest = 0, 0.0
    for index in vertices:
        point = world @ mesh.vertices[index].co
        if point.x < 0:
            continue
        u = abs(point.y - centre_y) / half_width
        across = min(u, 1.0) ** 2 * smoothstep(1.9, 1.15, u)       # 0 at the middle, 1 at the corners, 0 in the cheek
        down = smoothstep(.013, .005, abs(point.z - centre_z))     # the lips and just around them
        front = smoothstep(0.0, .02, point.x)
        dz = rise * across * down * front
        if dz > 1e-6:
            mesh.vertices[index].co = inverse @ Vector((point.x, point.y, point.z + dz))
            moved += 1
            largest = max(largest, dz)
    mesh.update()
    return {'centre': [round(centre_y, 4), round(centre_z, 4)], 'half_width_mm': round(half_width * 1000, 1),
            'rise_mm': round(rise * 1000, 2), 'vertices_moved': moved, 'largest_move_mm': round(largest * 1000, 2)}
