"""Modori's export steps beyond the shared ones (pipeline/export.py): his coat's cloth mask and colliders, and his
trousers tucked in under it.

The coat's `cloth_pin` group (1 where the coat follows the body, 0 where it hangs free) travels as its vertex colour,
for the cloth in Unreal (Scripts/import_character.py builds it from export.json `cloth`).
"""
import math

PIN = 'cloth_pin'


def outer_shell(coat, arm):
    """Which coat vertices are on its outer surface. Tripo's coat is a solid with thickness, an outer and an inner surface
    joined at the hems: a vertex is outer when its normal points away from the bone carrying most of its weight (its
    nearest point on that bone's segment), inner when it points back at the body."""
    bones = {g.index: arm.data.bones.get(g.name) for g in coat.vertex_groups}
    out = {}
    for v in coat.data.vertices:
        g = max((g for g in v.groups if bones.get(g.group) is not None), key=lambda g: g.weight, default=None)
        if g is None:
            out[v.index] = True; continue
        bone = bones[g.group]
        a, b = arm.matrix_world @ bone.head_local, arm.matrix_world @ bone.tail_local
        d = b - a
        t = min(1., max(0., (v.co - a).dot(d) / max(d.length_squared, 1e-12)))
        out[v.index] = v.normal.dot(v.co - (a + d * t)) >= 0.
    return out


# Passes of averaging the pin over each vertex's neighbours. Tripo's cloth_pin falls from 1 to 0 within a ring or two at
# the hips, so the coat leaning with his torso above it creased into a sharp corner against the skirt hanging below as he
# leant into a run (the operator's photo, #6349); averaged, the coat comes free over about a hand's width.
SOFTEN_PASSES = 20


def soften(coat, weight):
    """The pin weights averaged with their neighbours' (along the mesh's edges) SOFTEN_PASSES times; a vertex fully pinned
    and far from the free part stays pinned."""
    near = {i: [] for i in weight}
    for e in coat.data.edges:
        a, b = e.vertices
        near[a].append(b); near[b].append(a)
    for _ in range(SOFTEN_PASSES):
        weight = {i: (w + sum(weight[j] for j in near[i])) / (1 + len(near[i])) for i, w in weight.items()}
    return weight


def pin_colours(coat, arm):
    """The coat's cloth_pin weights as its vertex colour (red), the mask Unreal's cloth paints its max distance from, and
    its outer surface as green (1 outer, 0 inner): Unreal simulates the outer surface and carries the inner one on it."""
    group = coat.vertex_groups[PIN]
    weight = {v.index: next((g.weight for g in v.groups if g.group == group.index), 0.) for v in coat.data.vertices}
    weight = soften(coat, weight)
    outer = outer_shell(coat, arm)
    attribute = coat.data.color_attributes.new(PIN, 'BYTE_COLOR', 'CORNER')
    for loop in coat.data.loops:
        w = weight[loop.vertex_index]
        attribute.data[loop.index].color = (w, float(outer[loop.vertex_index]), w, 1.)
    coat.data.color_attributes.active_color = attribute
    coat.data.color_attributes.render_color_index = coat.data.color_attributes.active_color_index
    values = list(weight.values())
    return {'vertices': len(values), 'pinned': sum(w >= .999 for w in values), 'free': sum(w <= .001 for w in values),
            'outer': sum(outer.values()), 'simulated': [i for i, w in weight.items() if w < .999 and outer[i]]}


# The coat's collision (Unreal cloth collides with capsules): each (bone carrying it, from joint, to joint, the bones
# whose skin sets its radius), measured on the body alone, so the coat hangs on his legs and hips, not on itself. The
# pelvis capsule stands up his middle (pelvis to spine): run across from hip to hip, its rounded ends stood a radius out
# past each hip joint and the skirt hung off them, a bump at the waist (megapark #7325, the operator #7329).
COLLIDERS = [('pelvis', 'pelvis', 'spine', ('pelvis',)), ('spine', 'spine', 'chest', ('spine', 'spine_mid')),
             ('thigh_L', 'thigh_L', 'shin_L', ('thigh_L',)), ('thigh_R', 'thigh_R', 'shin_R', ('thigh_R',)),
             ('shin_L', 'shin_L', 'foot_L', ('shin_L',)), ('shin_R', 'shin_R', 'foot_R', ('shin_R',))]

PERCENTILE = 90
CLEARANCE = .015   # metres between each capsule and the nearest simulated coat vertex at rest


def colliders(arm, body, coat, simulated):
    """Capsules for the cloth, in centimetres: a segment between two joints and the radius that holds PERCENTILE% of
    the skin of the bones around it, but never closer than CLEARANCE to a simulated coat vertex at rest (`simulated`,
    indices into `coat`). At 80% his baggy trousers came through the coat at the thighs; at 99% plus a centimetre the
    thigh and pelvis capsules took in the trousers' outliers and held the skirt out like a hoop (the operator, #7296:
    the coat should fall straight, as the references do). At 90% the spine capsule still started 1.8 cm outside the
    back of the coat at the waist and the thighs pushed its front out a centimetre: a capsule the coat starts inside
    pushes it out."""
    import numpy as np
    head = {b.name: np.array(arm.matrix_world @ b.head_local) for b in arm.data.bones}
    cloth = np.array([list(coat.matrix_world @ coat.data.vertices[i].co) for i in sorted(simulated)])
    names = {g.index: g.name for g in body.vertex_groups}
    points = {}
    for v in body.data.vertices:
        if v.groups:
            strongest = max(v.groups, key=lambda g: g.weight)
            points.setdefault(names[strongest.group], []).append(np.array(body.matrix_world @ v.co))
    out = []
    for bone, start, end, skin in COLLIDERS:
        a, b = head[start], head[end]
        p = np.array([q for name in skin for q in points.get(name, [])])
        assert len(p) > 20, (bone, 'too little skin to size its capsule', len(p))
        t = np.clip((p - a) @ (b - a) / ((b - a) @ (b - a)), 0, 1)
        distance = np.linalg.norm(p - (a + t[:, None] * (b - a)), axis=1)
        t = np.clip((cloth - a) @ (b - a) / ((b - a) @ (b - a)), 0, 1)
        clearance = float(np.linalg.norm(cloth - (a + t[:, None] * (b - a)), axis=1).min())
        skin = float(np.percentile(distance, PERCENTILE))
        radius = math.floor(min(skin, clearance - CLEARANCE) * 1e4) / 100
        assert radius > 5, (bone, 'the coat leaves no room for its capsule', clearance)
        out.append({'bone': bone, 'from': start, 'to': end, 'radius_cm': radius,
                    'skin_cm': round(skin * 100, 2), 'coat_cm': round(clearance * 100, 2)})
    return out


# His baggy trousers under the coat (fattest behind the thigh joint, 11-12 cm out at the back) follow the thighs, while
# the skirt over them follows the hips: in the idle stance the thighs came through the back and sides of the coat at rest,
# with the cloth simulation off as well (the operator, #7451). Where the coat hides them, behind and beside each thigh
# from a hand above its hem up to the hip, they are pulled TUCK in toward the thigh's bone (never more than TUCK_SHARE
# of their distance from it). Their front, in the coat's opening, and their legs below the hem keep their cut.
TUCK = .03
TUCK_SHARE = .35


def tuck_trousers(arm, body, coat):
    """Pull the hidden back and sides of the trousers in toward each thigh bone; returns how many vertices moved and the
    largest move (cm)."""
    import numpy as np
    from mathutils import Vector
    hem = min((coat.matrix_world @ v.co).z for v in coat.data.vertices)
    thighs = {g.index: arm.data.bones[g.name] for g in body.vertex_groups if g.name in ('thigh_L', 'thigh_R')}
    inverse = body.matrix_world.inverted()
    moved, largest = 0, 0.
    for v in body.data.vertices:
        g = max(v.groups, key=lambda g: g.weight, default=None)
        if g is None or g.group not in thighs:
            continue
        bone = thighs[g.group]
        p = np.array(body.matrix_world @ v.co)
        a, b = np.array(arm.matrix_world @ bone.head_local), np.array(arm.matrix_world @ bone.tail_local)
        d = b - a
        t = float(np.clip((p - a) @ d / (d @ d), 0., 1.))
        r = p - (a + t * d)
        out = float(np.linalg.norm(r))
        if out < 1e-4:
            continue
        facing = r[0] / out   # +X is his front: 1 in front, -1 behind
        side = float(np.clip((.3 - facing) / .5, 0., 1.))
        height = float(np.clip((p[2] - hem - .02) / .06, 0., 1.))
        move = min(TUCK, TUCK_SHARE * out) * side * height
        if move <= 0.:
            continue
        v.co = inverse @ Vector(p - r / out * move)
        moved += 1; largest = max(largest, move)
    return moved, round(largest * 100, 2)


def body(prepared, report):
    """Tuck the trousers, paint the coat's cloth mask and size its colliders; recorded as `trousers_tucked` and `cloth`."""
    arm, meshes = prepared.arm, prepared.meshes
    coat = next(o for o in meshes if o.name.endswith('Coat'))
    tucked = tuck_trousers(arm, next(o for o in meshes if o.name.endswith('Body')), coat)
    pins = pin_colours(coat, arm)
    capsules = colliders(arm, next(o for o in meshes if o.name.endswith('Body')), coat, pins.pop('simulated'))
    report['trousers_tucked'] = {'vertices': tucked[0], 'largest_cm': tucked[1]}
    report['cloth'] = {'mesh': coat.name, 'mask': PIN, 'channel': 'vertex colour red (pin), green (outer surface)',
                       'colliders': capsules, **pins}
