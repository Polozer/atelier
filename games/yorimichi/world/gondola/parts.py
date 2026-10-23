"""Explicit physical ownership for the two rope families and oversized access walk."""
import re

LIMIT = 32768


def component_count(line):
    if line not in ('L1','L2','L3'):raise ValueError('Unknown Gondola rope line')
    return 1 if line=='L3' else 2


def names(line,lod):
    if type(lod) is not int or lod not in (0,1,2):raise ValueError('Unknown Gondola rope LOD')
    parent=f'GD_{line}_Rope_LOD{lod}'
    return [parent] if component_count(line)==1 else [parent+f'_Piece{index:02d}' for index in range(2)]


def face_groups(key,faces,count):
    """@cc [owner:fontanierh,label:correctness;performance] coordinated-gondola-rope-face-ownership
    L1/L2 MUST retain two declared members at every original LOD, even below a
    size threshold. L3 MUST retain its original whole identity. Every original
    face MUST have exactly one owner, in original order within each member, and
    each member MUST fit the actual triangle budget. No geometry is joined,
    reconstructed or discarded to satisfy these ownership declarations.
    """
    match=re.fullmatch(r'GD_(L[123])_Rope_LOD([012])',key)
    if not match or type(count) is not int or count!=component_count(match[1]) or not faces:
        raise ValueError('Invalid authored Gondola rope family')
    return partition(names(match[1],int(match[2])),faces)


def access_groups(key,faces):
    if key!='GD_floor_rim_Access':raise ValueError('Unknown split Gondola static owner')
    return partition([key+f'_Piece{index:02d}' for index in range(2)],faces)


def partition(keys,faces):
    if not faces:raise ValueError('Missing original Gondola source faces')
    count=len(keys);weights=[len(face)-2 for face in faces]
    if any(weight<1 for weight in weights):raise ValueError('Invalid original rope face')
    total=sum(weights);groups=[[] for _ in range(count)];accumulated=0
    for index,weight in enumerate(weights):
        owner=min(count-1,accumulated*count//total)
        groups[owner].append(index);accumulated+=weight
    if any(not group or sum(weights[index] for index in group)>LIMIT for group in groups):
        raise ValueError('Gondola rope LOD cannot fit its coordinated bounded roster')
    return list(zip(keys,map(tuple,groups)))
