"""Authoritative anatomical mirroring and wheel-local grip serialization."""
import math

import numpy as np


def unpack(values):
    return np.array(values, dtype=float).reshape((4, 4), order='F')


def pack(matrix):
    return matrix.flatten(order='F').tolist()


def bone_names(side):
    return [f'hand_{side}', *(f'{part}_{side}' for digit in range(4)
                             for part in (f'finger_{digit}', f'finger_tip_{digit}', f'finger_end_{digit}')),
            f'thumb_{side}', f'thumb_tip_{side}', f'thumb_end_{side}']


def wheel_frame(meta):
    layout = meta['layout']
    angle = math.radians(layout['steering_tilt_degrees'] + meta.get('wheel_tilt_offset_degrees', 0))
    c, s = math.cos(angle), math.sin(angle)
    matrix = np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]], dtype=float)
    matrix[:3, :3] *= meta['scale']
    hub = list(layout['steering'])
    hub[2] += meta.get('wheel_height_offset', 0)
    if 'steering_column_base' in layout:
        base = layout['steering_column_base']
        hub[0] = base[0] - (hub[2]-base[2]) / math.tan(angle)
    matrix[:3, 3] = np.array(hub) * meta['scale']
    return matrix


def mirror_left(left, meta):
    """Mirror motion through each rig's bind frames, preserving the right fingers' own lengths.

    Reflections act on rotation deltas, not raw bone axes: imported hands have different bind rolls.
    The right hand has no independently editable values.
    """
    wheel = wheel_frame(meta)
    inverse_wheel = np.linalg.inv(wheel)
    reflect = np.diag([1., -1., 1.])
    bind = {name: unpack(frame) for name, frame in meta['bind_world'].items()}
    right, world = {}, {}
    for name in bone_names('L'):
        frame = left[name]
        target = name.removesuffix('_L') + '_R'
        posed = wheel @ unpack(frame)
        result = np.eye(4)
        result[:3, :3] = reflect @ posed[:3, :3] @ bind[name][:3, :3].T @ reflect @ bind[target][:3, :3]
        if name == 'hand_L':
            result[:3, 3] = reflect @ posed[:3, 3]
        else:
            parent = meta['parents'][target]
            local = np.linalg.inv(bind[parent]) @ bind[target]
            result[:3, 3] = (world[parent] @ np.append(local[:3, 3], 1))[:3]
        world[target] = result
        right[target] = pack(inverse_wheel @ result)
    return right
