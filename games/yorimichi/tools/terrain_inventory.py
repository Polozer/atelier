"""Read-only, order-sensitive inventories for terrain consolidation proofs.

This module does not build, weld, triangulate, carve or choose ground owners.
Callers supply explicit triangles in world metres. Nothing here participates in
the game build until a later reviewed extraction wires it into a recipe.
"""
import hashlib

import numpy as np


def _digest(array, dtype):
    data = np.ascontiguousarray(array, dtype=dtype)
    digest = hashlib.sha256()
    digest.update(str(data.shape).encode('ascii'))
    digest.update(b'\0')
    digest.update(data.tobytes())
    return digest.hexdigest()


def inventory(vertices, triangles, *, owner, stage):
    """@cc [owner:fontanierh,label:correctness] terrain-inventory-preserves-order
    Inventory explicit world-metre triangles without changing input arrays,
    vertex/face order, duplicates, winding or ownership. Digests MUST include
    ordered positions and indices; index-edge counts MUST NOT be presented as
    geometric seam continuity across duplicated render vertices or owners.
    """
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError('Terrain inventory requires an explicit owner')
    if stage not in ('natural', 'final'):
        raise ValueError('Terrain stage must be natural or final')
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(triangles)
    if v.ndim != 2 or v.shape[1] != 3 or not np.isfinite(v).all():
        raise ValueError('Terrain positions must be finite N by 3 world metres')
    if f.ndim != 2 or f.shape[1] != 3 or f.dtype.kind not in 'iu':
        raise ValueError('Terrain faces must be an integer M by 3 triangle array')
    if f.size and (f.min() < 0 or f.max() >= len(v)):
        raise ValueError('Terrain triangle index outside vertex array')
    f = f.astype(np.int64, copy=False)
    tri = v[f]
    cross = np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0])
    if not np.isfinite(cross).all():
        raise ValueError('Terrain triangle area is not finite')
    edges = np.sort(np.concatenate((f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]])), axis=1)
    _, incidence = np.unique(edges, axis=0, return_counts=True)
    return {
        'schema': 1,
        'owner': owner,
        'stage': stage,
        'units': 'metres, x east, y north, z up',
        'vertices': len(v),
        'triangles': len(f),
        'bounds': [v.min(0).tolist(), v.max(0).tolist()] if len(v) else None,
        'ordered_positions_sha256': _digest(v, '<f8'),
        'ordered_indices_sha256': _digest(f, '<i8'),
        'zero_area_triangles': int(np.count_nonzero(np.all(cross == 0., axis=1))),
        'upward_triangles': int(np.count_nonzero(cross[:, 2] > 0.)),
        'downward_triangles': int(np.count_nonzero(cross[:, 2] < 0.)),
        'vertical_triangles': int(np.count_nonzero((cross[:, 2] == 0.) & np.any(cross != 0., axis=1))),
        'index_edges': {
            'boundary': int(np.count_nonzero(incidence == 1)),
            'paired': int(np.count_nonzero(incidence == 2)),
            'nonmanifold': int(np.count_nonzero(incidence > 2)),
        },
    }
