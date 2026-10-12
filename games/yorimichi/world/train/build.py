"""Belmonte train coach shells (Blender, headless): `atelier build yorimichi world.belmonte_train`.

Builds both coaches from train/layout.py: the shared envelope (side walls with real window and door openings, end
walls, floor deck, roof, ceiling, underframe, two bogies, buffers, couplers, gangways, steps), each coach's own
partitions, sliding and hinged doors, lining panels, window frames and glazing, plus furniture reservations, seat
markers, mounts and simple walkable collision. The coaches are empty: furniture, lamps, curtains and racks are
separate Tripo Studio assets placed from placements.json.

Outputs in build/yorimichi/belmonte-train/: per coach a clean .blend, SM_BT_<Coach>_LOD0/1/2.glb (glTF, metres,
Blender's standard Y-up export), SM_BT_<Coach>_Collision.glb, <coach>-blockout.glb (reservations and markers) and
<coach>-placements.json; textures/; manifest.json with sizes, checksums, triangle counts and the checks.
Object origins: the coach at its centre on the top of the rail; bogies at their pivot; wheelsets at their axle;
doors at their hinge (hinged) or at the bottom centre of the closed leaf (sliding).
"""
import sys as _sys; from pathlib import Path as _Path; _sys.path.insert(0, str(_Path(__file__).resolve().parents[1])); import yori  # noqa: E402,F401
import hashlib
import json
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from train import layout as L
from train import textures as T

OUT = yori.OUT / 'belmonte-train'
TEX = OUT / 'textures'

# name: (base colour, metallic, roughness, texture, uv metres per tile, alpha)
MATERIALS = {
    'livery-blue': ((.012, .022, .060), 0., .32, None, 1., 1.),
    'livery-ivory': ((.74, .64, .46), 0., .38, None, 1., 1.),
    'roof': ((.030, .033, .036), 0., .55, None, 1., 1.),
    'end-dark': ((.018, .019, .022), 0., .5, None, 1., 1.),
    'brass': ((.80, .56, .24), 1., .28, None, 1., 1.),
    'walnut': ((1, 1, 1), 0., .42, 'T_BT_Walnut', .9, 1.),
    'panel-tall': ((1, 1, 1), 0., .35, 'T_BT_PanelTall', 0., 1.),
    'panel-wide': ((1, 1, 1), 0., .35, 'T_BT_PanelWide', 0., 1.),
    'carpet-burgundy': ((1, 1, 1), 0., .9, 'T_BT_CarpetBurgundy', 1.2, 1.),
    'carpet-emerald': ((1, 1, 1), 0., .9, 'T_BT_CarpetEmerald', 1.2, 1.),
    'tile': ((1, 1, 1), 0., .35, 'T_BT_Tiles', 1.2, 1.),
    'parquet': ((1, 1, 1), 0., .45, 'T_BT_Walnut', .45, 1.),
    'ceiling': ((.80, .71, .54), 0., .6, None, 1., 1.),
    'service': ((.62, .62, .60), .2, .4, None, 1., 1.),
    'undercarriage': ((.025, .025, .027), .3, .6, None, 1., 1.),
    'steel': ((.30, .30, .31), 1., .45, None, 1., 1.),
    'rubber': ((.012, .012, .013), 0., .8, None, 1., 1.),
    'glass': ((.92, .95, .96), 0., .04, None, 1., .12),
    'glass-frosted': ((.88, .90, .90), 0., .5, None, 1., .80),
    'glass-dark': ((.05, .07, .09), 0., .1, None, 1., 1.),
    'lamp-red': ((.85, .04, .02), 0., .2, None, 1., 1.),
    'crest': ((1, 1, 1), .8, .3, 'T_BT_Crest', 0., 1.),
    'reservation': ((.85, .28, .04), 0., .8, None, 1., .60),
    'reservation-service': ((.08, .25, .75), 0., .8, None, 1., .50),
    'gauge': ((.9, .1, .3), 0., .8, None, 1., 1.),
}
MAT = {}


def make_textures():
    TEX.mkdir(parents=True, exist_ok=True)
    images = {}
    for name, fn in T.ALL.items():
        px = fn()
        h, w, _ = px.shape
        img = bpy.data.images.new(name, w, h, alpha=True)
        img.pixels.foreach_set(px.astype(np.float32).ravel())
        img.filepath_raw = str(TEX / f'{name}.png'); img.file_format = 'PNG'; img.save()
        images[name] = img
    return images


def make_materials(images):
    for name, (color, metal, rough, tex, _, alpha) in MATERIALS.items():
        m = bpy.data.materials.new(f'M_BT_{"".join(p.title() for p in name.split("-"))}')
        nodes = m.node_tree.nodes
        bsdf = nodes['Principled BSDF']
        bsdf.inputs['Base Color'].default_value = (*color, 1)
        bsdf.inputs['Metallic'].default_value = metal
        bsdf.inputs['Roughness'].default_value = rough
        if name.startswith('livery'):
            bsdf.inputs['Coat Weight'].default_value = .6
        if tex:
            node = nodes.new('ShaderNodeTexImage'); node.image = images[tex]
            m.node_tree.links.new(node.outputs['Color'], bsdf.inputs['Base Color'])
            if name == 'crest':
                m.node_tree.links.new(node.outputs['Alpha'], bsdf.inputs['Alpha'])
                m.surface_render_method = 'DITHERED'
        if alpha < 1:
            bsdf.inputs['Alpha'].default_value = alpha
            m.surface_render_method = 'BLENDED'
            m.use_backface_culling = False
        m.diffuse_color = (*color, alpha) if not tex else (.3, .15, .07, 1)
        MAT[name] = m


# --- mesh building ------------------------------------------------------------------------------------------------
class M:
    """Polygons with a material and optional UVs; every polygon has its own vertices until weld()."""

    def __init__(self):
        self.faces = []        # (points, material, uv or None)

    def poly(self, pts, mat, uv=None, normal=None):
        pts = [tuple(map(float, p)) for p in pts]
        if normal is not None:
            n = _newell(pts)
            if n.dot(Vector(normal)) < 0:
                pts = pts[::-1]
                uv = uv[::-1] if uv else None
        self.faces.append((pts, mat, uv))

    def box(self, x0, x1, y0, y1, z0, z1, mat, front=None, front_mat=None):
        """A closed box. front = (axis, sign): that face gets UVs 0..1 (as seen from outside) and front_mat."""
        x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1)); z0, z1 = sorted((z0, z1))
        P = lambda i, j, k: ((x0, x1)[i], (y0, y1)[j], (z0, z1)[k])
        quads = {('x', -1): [P(0, 1, 0), P(0, 0, 0), P(0, 0, 1), P(0, 1, 1)], ('x', 1): [P(1, 0, 0), P(1, 1, 0), P(1, 1, 1), P(1, 0, 1)],
                 ('y', -1): [P(0, 0, 0), P(1, 0, 0), P(1, 0, 1), P(0, 0, 1)], ('y', 1): [P(1, 1, 0), P(0, 1, 0), P(0, 1, 1), P(1, 1, 1)],
                 ('z', -1): [P(0, 1, 0), P(1, 1, 0), P(1, 0, 0), P(0, 0, 0)], ('z', 1): [P(0, 0, 1), P(1, 0, 1), P(1, 1, 1), P(0, 1, 1)]}
        for key, q in quads.items():
            if front == key:
                self.faces.append((q, front_mat or mat, [(0, 0), (1, 0), (1, 1), (0, 1)]))
            else:
                self.faces.append((q, mat, None if front is None else [(0, 0), (.01, 0), (.01, .01), (0, .01)]))

    def prism(self, pts2, axis, a0, a1, mat, cap_mat=None):
        """Extrude a convex polygon given in the plane of the two other axes ((y, z) for axis x, (x, z) for y)."""
        def P(u, v, a):
            return (a, u, v) if axis == 'x' else (u, a, v) if axis == 'y' else (u, v, a)
        n = len(pts2)
        self.faces.append(([P(u, v, a0) for u, v in pts2], cap_mat or mat, None))
        self.faces.append(([P(u, v, a1) for u, v in pts2[::-1]], cap_mat or mat, None))
        for i in range(n):
            (u0, v0), (u1, v1) = pts2[i], pts2[(i + 1) % n]
            self.faces.append(([P(u0, v0, a0), P(u1, v1, a0), P(u1, v1, a1), P(u0, v0, a1)], mat, None))

    def ring(self, outer, inner, plane, d0, d1, mat):
        """A closed frame between two loops of the same length in a plane at y (plane='y') from d0 to d1."""
        def P(u, v, d):
            return (u, d, v) if plane == 'y' else (d, u, v)
        n = len(outer)
        for i in range(n):
            j = (i + 1) % n
            for d in (d0, d1):
                self.faces.append(([P(*outer[i], d), P(*outer[j], d), P(*inner[j], d), P(*inner[i], d)], mat, None))
            self.faces.append(([P(*outer[i], d0), P(*outer[j], d0), P(*outer[j], d1), P(*outer[i], d1)], mat, None))
            self.faces.append(([P(*inner[i], d0), P(*inner[j], d0), P(*inner[j], d1), P(*inner[i], d1)], mat, None))

    def cylinder(self, c, axis, r, a0, a1, mat, seg=16):
        pts = [(c[0] + r * math.cos(2 * math.pi * k / seg), c[1] + r * math.sin(2 * math.pi * k / seg)) for k in range(seg)]
        self.prism(pts, axis, a0, a1, mat)

    def obj(self, name, coll, origin=(0, 0, 0), parent=None, closed=True, lods=(0, 1), smooth_angle=35):
        me = bpy.data.meshes.new(name)
        mats = []
        for _, m, _ in self.faces:
            if m not in mats:
                mats.append(m)
        for m in mats:
            me.materials.append(MAT[m])
        ox, oy, oz = origin
        bm = bmesh.new()
        uvl = bm.loops.layers.uv.new('UVMap')
        for pts, m, uv in self.faces:
            vs = [bm.verts.new((x - ox, y - oy, z - oz)) for x, y, z in pts]
            try:
                f = bm.faces.new(vs)
            except ValueError:
                continue
            f.material_index = mats.index(m)
            if uv is None:
                n = _newell(pts)
                ax = max(range(3), key=lambda i: abs(n[i]))
                scale = MATERIALS[m][4] or 1.
                for loop, p in zip(f.loops, pts):
                    u, v = [p[i] for i in range(3) if i != ax]
                    loop[uvl].uv = (u / scale, v / scale)
            else:
                for loop, q in zip(f.loops, uv):
                    loop[uvl].uv = q
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        if closed:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me); bm.free()
        finish_mesh(me, smooth_angle)
        o = bpy.data.objects.new(name, me)
        o.location = origin
        coll.objects.link(o)
        if parent:
            o.parent = parent
        o['lods'] = list(lods)
        return o


def _newell(pts):
    n = Vector((0, 0, 0))
    for a, b in zip(pts, pts[1:] + pts[:1]):
        n += Vector(((a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])))
    return n.normalized() if n.length else Vector((0, 0, 1))


def finish_mesh(me, angle=35):
    for p in me.polygons:
        p.use_smooth = True
    me.set_sharp_from_angle(angle=math.radians(angle))
    me.validate()


def rrect(cx, cz, w, h, r, seg=4):
    """A rounded rectangle, counter-clockwise in (u, v)."""
    r = min(r, w / 2, h / 2)
    out = []
    for (qx, qz, a0) in ((cx + w / 2 - r, cz - h / 2 + r, -90), (cx + w / 2 - r, cz + h / 2 - r, 0),
                         (cx - w / 2 + r, cz + h / 2 - r, 90), (cx - w / 2 + r, cz - h / 2 + r, 180)):
        for k in range(seg + 1):
            a = math.radians(a0 + 90 * k / seg)
            out.append((qx + r * math.cos(a), qz + r * math.sin(a)))
    return out


def ellipse(cx, cz, w, h, seg=24):
    return [(cx + w / 2 * math.cos(2 * math.pi * k / seg), cz + h / 2 * math.sin(2 * math.pi * k / seg)) for k in range(seg)]


def boolean(obj, cutters):
    """Subtract the cutter meshes from obj (exact solver) and apply it."""
    coll = bpy.data.collections.new(f'cut_{obj.name}')
    bpy.context.scene.collection.children.link(coll)
    objs = []
    for i, m in enumerate(cutters):
        objs.append(m.obj(f'cut_{obj.name}_{i}', coll, lods=()))
    mod = obj.modifiers.new('cut', 'BOOLEAN')
    mod.operation = 'DIFFERENCE'; mod.operand_type = 'COLLECTION'; mod.collection = coll; mod.solver = 'EXACT'
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(obj.evaluated_get(dg))
    old = obj.data
    obj.modifiers.clear(); obj.data = me; me.name = old.name
    bpy.data.meshes.remove(old)
    for o in objs:
        bpy.data.meshes.remove(o.data)
    bpy.data.collections.remove(coll)
    return obj


def reproject(obj, classify):
    """Reassign every face's material with classify(normal, centre) -> name and redo box-projected UVs."""
    me = obj.data
    names = [m.name for m in me.materials]
    bm = bmesh.new(); bm.from_mesh(me)
    uvl = bm.loops.layers.uv.verify()
    wm = obj.matrix_world
    for f in bm.faces:
        n = (wm.to_3x3() @ f.normal).normalized(); c = wm @ f.calc_center_median()
        name = classify(n, c)
        mname = MAT[name].name
        if mname not in names:
            me.materials.append(MAT[name]); names.append(mname)
        f.material_index = names.index(mname)
        ax = max(range(3), key=lambda i: abs(n[i]))
        scale = MATERIALS[name][4] or 1.
        for loop in f.loops:
            p = wm @ loop.vert.co
            u, v = [p[i] for i in range(3) if i != ax]
            loop[uvl].uv = (u / scale, v / scale)
    bm.to_mesh(me); bm.free()
    finish_mesh(me)


def group(name, coll, parent=None):
    e = bpy.data.objects.new(name, None)
    e.empty_display_size = .3
    coll.objects.link(e)
    if parent:
        e.parent = parent
    e['lods'] = [0, 1, 2]
    return e


# --- the shared envelope ------------------------------------------------------------------------------------------
def side_walls(c, coll, parent):
    out = []
    for side, sy in (('l', 1), ('r', -1)):
        m = M()
        y0, y1 = sorted((sy * L.IN, sy * L.HALF))
        m.box(B.x_a, B.x_b, y0, y1, L.SKIRT_Z, L.BELT_Z, 'livery-blue')
        m.box(B.x_a, B.x_b, y0, y1, L.BELT_Z, L.CANT_Z, 'livery-ivory')
        o = m.obj(f'Shell_Side_{side.upper()}', coll, parent=parent)
        cutters = []
        for w in c.windows:
            if w.side != sy:
                continue
            cut = M(); cut.prism(rrect(w.x, (w.sill + w.head) / 2, w.width, w.head - w.sill, L.WIN_RADIUS), 'y', y0 - .05, y1 + .05, 'glass')
            cutters.append(cut)
        for name, s, x0, x1, z0, z1 in L.exterior_openings(c):
            if s == sy:
                cut = M(); cut.box(x0, x1, y0 - .05, y1 + .05, z0, z1, 'glass'); cutters.append(cut)
        boolean(o, cutters)

        def classify(n, ctr, sy=sy):
            if n.y * sy > .7 and abs(ctr.y) > L.HALF - 1e-3:
                return 'livery-blue' if ctr.z < L.BELT_Z else 'livery-ivory'
            if n.y * sy < -.7:
                return 'walnut'
            return 'walnut' if abs(ctr.y) < L.HALF - .01 or ctr.z > L.SILL - .01 else ('livery-blue' if ctr.z < L.BELT_Z else 'livery-ivory')
        reproject(o, classify)
        out.append(o)
    return out


def end_walls(c, coll, parent):
    """Each end wall rises to the roof; it carries the gangway opening, or the door onto the balcony."""
    for end, sx in (('A', -1), ('B', 1)):
        pts = [(-L.IN, L.SKIRT_Z), (L.IN, L.SKIRT_Z)]
        for k in range(17):
            y = L.IN - 2 * L.IN * k / 16
            pts.append((y, L.roof_z(y, L.ROOF_SKIN) + .002))
        m = M(); a0, a1 = sorted((B.inner(sx), B.face(sx)))
        m.prism(pts, 'x', a0, a1, 'walnut')
        o = m.obj(f'Shell_End_{end}', coll, parent=parent)
        w = c.wall(f'end-{end.lower()}')
        cutters = []
        for op in w.openings:
            cut = M(); cut.box(a0 - .05, a1 + .05, op.a0, op.a1, op.z0, op.z1, 'glass'); cutters.append(cut)
        boolean(o, cutters)
        outside = 'end-dark' if B.end(sx) == 'gangway' else 'livery-ivory'
        reproject(o, lambda n, ctr, sx=sx, outside=outside: (outside if ctr.z > L.BELT_Z or outside == 'end-dark' else 'livery-blue') if n.x * sx > .7 else 'walnut')
    # corner posts close the ends of the side walls up to the roof
    m = M()
    for sx in (-1, 1):
        for sy in (-1, 1):
            x0, x1 = sorted((B.face(sx) - sx * .07, B.face(sx) + sx * .012))
            y0, y1 = sorted((sy * (L.IN - .002), sy * (L.HALF + .012)))
            m.box(x0, x1, y0, y1, L.SKIRT_Z - .02, L.CANT_Z + .14, 'end-dark')
    m.obj('Shell_CornerPosts', coll, parent=parent)


def roof(coll, parent, lod=0):
    seg = 32 if lod == 0 else 12
    outer = [(-L.HALF + 2 * L.HALF * k / seg) for k in range(seg + 1)]
    # the roof overhangs each end wall a little, and runs on over a balcony as its canopy
    xa = (B.x_a - .05) if B.end_a == 'gangway' else B.headstock(-1) - .04
    xb = (B.x_b + .05) if B.end_b == 'gangway' else B.headstock(1) + .04
    m = M()
    ys_o = [(y, L.roof_z(y)) for y in outer]
    ys_i = [(y * (L.HALF - L.ROOF_SKIN) / L.HALF, L.roof_z(y * (L.HALF - L.ROOF_SKIN) / L.HALF, L.ROOF_SKIN)) for y in outer]
    for k in range(seg):
        (ya, za), (yb, zb) = ys_o[k], ys_o[k + 1]
        m.poly([(xa, ya, za), (xa, yb, zb), (xb, yb, zb), (xb, ya, za)], 'roof')
        (ya, za), (yb, zb) = ys_i[k], ys_i[k + 1]
        m.poly([(xb, ya, za), (xb, yb, zb), (xa, yb, zb), (xa, ya, za)], 'roof')
        for x in (xa, xb):
            m.poly([(x, *ys_o[k]), (x, *ys_o[k + 1]), (x, *ys_i[k + 1]), (x, *ys_i[k])], 'roof')
    for k in (0, seg):
        m.poly([(xa, *ys_o[k]), (xb, *ys_o[k]), (xb, *ys_i[k]), (xa, *ys_i[k])], 'roof')
    skin = m.obj('Roof_Skin' if lod == 0 else 'LOD2_Roof', coll, parent=parent, lods=(0, 1) if lod == 0 else (2,))
    if lod:
        return skin
    m = M()
    for sy in (-1, 1):            # cornice and the brass line under it
        y0, y1 = sorted((sy * (L.HALF - .01), sy * (L.HALF + .028)))
        m.box(xa + .03, xb - .03, y0, y1, L.CANT_Z - .07, L.CANT_Z + .01, 'roof')
        y0, y1 = sorted((sy * (L.HALF - .01), sy * (L.HALF + .016)))
        m.box(B.x_a, B.x_b, y0, y1, L.CANT_Z - .105, L.CANT_Z - .085, 'brass')
    span = B.x_b - B.x_a
    vents = max(2, round(span / 2.6))
    cup = B.cupola or (1e9, 1e9)
    for k in range(vents):        # torpedo ventilators on the centre line, none on a lookout
        x = B.x_a + 1.2 + (span - 2.4) * k / (vents - 1)
        if cup[0] - .3 < x < cup[1] + .3:
            continue
        m.cylinder((x, 0), 'z', .085, L.roof_z(0) - .02, L.VENT_TOP - .07, 'roof', 12)
        m.cylinder((x, 0), 'z', .13, L.VENT_TOP - .07, L.VENT_TOP - .02, 'brass', 12)
        m.cylinder((x, 0), 'z', .07, L.VENT_TOP - .02, L.VENT_TOP, 'brass', 12)
    battens = max(2, round((xb - xa) / 1.85))
    for k in range(battens + 1):  # roof seams: raised battens following the roof curve
        x = xa + .3 + (xb - xa - .6) * k / battens
        for j in range(seg):
            (ya, za), (yb, zb) = ys_o[j], ys_o[j + 1]
            if abs(ya) > L.HALF - .05 or abs(yb) > L.HALF - .05:
                continue
            m.poly([(x - .012, ya, za + .010), (x + .012, ya, za + .010), (x + .012, yb, zb + .010), (x - .012, yb, zb + .010)], 'roof', normal=(0, 0, 1))
            for e, sgn in ((x - .012, -1), (x + .012, 1)):
                m.poly([(e, ya, za - .002), (e, yb, zb - .002), (e, yb, zb + .010), (e, ya, za + .010)], 'roof', normal=(sgn, 0, 0))
    m.obj('Roof_Details', coll, parent=parent, lods=(0,), closed=False)
    if B.cupola:
        cupola(coll, parent)
    return skin


def cupola(coll, parent):
    """The guard's lookout: a raised glazed cab on the roof with its own curved top, part of the removable roof."""
    x0, x1 = B.cupola
    hw, z0, z1 = 1.25, L.roof_z(1.25) - .05, L.ROOF_TOP + .62
    m = M()
    m.box(x0, x1, -hw, hw, z0, z1, 'livery-ivory')
    o = m.obj('Roof_Cupola', coll, parent=parent)
    cutters = []
    for sy in (-1, 1):
        for k in range(3):
            xc = x0 + (x1 - x0) * (k + .5) / 3
            cut = M(); cut.prism(rrect(xc, z1 - .30, (x1 - x0) / 3 - .20, .34, .05), 'y', -hw - .05, hw + .05, 'glass'); cutters.append(cut)
    for xe in (x0, x1):
        cut = M(); cut.prism(rrect(0, z1 - .30, 1.30, .34, .05), 'x', xe - .05, xe + .05, 'glass'); cutters.append(cut)
    boolean(o, cutters)
    reproject(o, lambda n, ctr: 'walnut' if abs(ctr.y) < hw - .03 and abs(n.z) < .5 and (x0 + .03 < ctr.x < x1 - .03) else 'livery-ivory')
    m = M()
    seg = 16
    for k in range(seg):          # a small curved top, echoing the main roof
        ya, yb = -hw - .06 + (2 * hw + .12) * k / seg, -hw - .06 + (2 * hw + .12) * (k + 1) / seg
        za = z1 + .16 * (1 - (ya / (hw + .06)) ** 2) ** .5
        zb = z1 + .16 * (1 - (yb / (hw + .06)) ** 2) ** .5
        m.poly([(x0 - .06, ya, za), (x0 - .06, yb, zb), (x1 + .06, yb, zb), (x1 + .06, ya, za)], 'roof', normal=(0, 0, 1))
        m.poly([(x0 - .06, ya, za - .03), (x1 + .06, ya, za - .03), (x1 + .06, yb, zb - .03), (x0 - .06, yb, zb - .03)], 'roof', normal=(0, 0, -1))
    m.obj('Roof_CupolaTop', coll, parent=parent, closed=False)
    m = M(); g = M()
    for sy in (-1, 1):
        for k in range(3):
            xc = x0 + (x1 - x0) * (k + .5) / 3
            pts = rrect(xc, z1 - .30, (x1 - x0) / 3 - .20, .34, .05)
            g.poly([(u, sy * (hw - .02), v) for u, v in pts], 'glass', normal=(0, sy, 0))
            m.ring(rrect(xc, z1 - .30, (x1 - x0) / 3 - .12, .42, .09), rrect(xc, z1 - .30, (x1 - x0) / 3 - .22, .32, .04), 'y', sy * hw, sy * (hw + .012), 'brass')
    for xe, sx in ((x0, -1), (x1, 1)):
        pts = rrect(0, z1 - .30, 1.30, .34, .05)
        g.poly([(xe - sx * .02, u, v) for u, v in pts], 'glass', normal=(sx, 0, 0))
    m.box(x0 - .02, x1 + .02, -hw - .02, hw + .02, z1 - .02, z1 + .01, 'brass')
    m.obj('Roof_CupolaTrim', coll, parent=parent, lods=(0,))
    g.obj('Glazing_Cupola', coll, parent=parent, closed=False)


def ceiling(c, coll, parent):
    seg = 24
    ys = [-L.IN + 2 * L.IN * k / seg for k in range(seg + 1)]
    m = M()
    xa, xb = B.in_a, B.in_b
    for k in range(seg):
        ya, yb = ys[k], ys[k + 1]
        za, zb = L.ceiling_z(ya), L.ceiling_z(yb)
        m.poly([(xa, ya, za), (xb, ya, za), (xb, yb, zb), (xa, yb, zb)], 'ceiling', normal=(0, 0, -1))
        m.poly([(xa, ya, za + .03), (xa, yb, zb + .03), (xb, yb, zb + .03), (xb, ya, za + .03)], 'ceiling', normal=(0, 0, 1))
    m.obj('Ceiling', coll, parent=parent, closed=False)
    # brass ribs at the window piers (and partitions in first class)
    side = sorted((w for w in c.windows if w.side > 0), key=lambda w: w.x)
    xs = sorted({round((a.x + b.x) / 2, 3) for a, b in zip(side, side[1:])})
    m = M()
    for x in xs:                  # a smooth brass band following the ceiling: underside and two edges
        for k in range(seg):
            ya, yb = ys[k], ys[k + 1]
            za, zb = L.ceiling_z(ya) - .016, L.ceiling_z(yb) - .016
            m.poly([(x - .025, ya, za), (x + .025, ya, za), (x + .025, yb, zb), (x - .025, yb, zb)], 'brass', normal=(0, 0, -1))
            for e, sgn in ((x - .025, -1), (x + .025, 1)):
                m.poly([(e, ya, za), (e, yb, zb), (e, yb, zb + .017), (e, ya, za + .017)], 'brass', normal=(sgn, 0, 0))
    # cove line at the springing
    for sy in (-1, 1):
        y0, y1 = sorted((sy * (L.IN - .035), sy * L.IN))
        m.box(B.in_a, B.in_b, y0, y1, L.CEIL_SPRING - .05, L.CEIL_SPRING + .005, 'brass')
    m.obj('Ceiling_Ribs', coll, parent=parent, lods=(0,), closed=False)


def deck_and_underframe(c, coll, parent):
    m = M()
    ha, hb = B.headstock(-1), B.headstock(1)
    m.box(B.in_a, B.in_b, -L.IN, L.IN, L.FLOOR_Z - L.DECK, L.FLOOR_Z - .006, 'undercarriage')
    m.box(ha, hb, -L.IN, L.IN, L.SKIRT_Z - .02, L.FLOOR_Z - L.DECK, 'undercarriage')
    for sy in (-1, 1):            # solebars
        y0, y1 = sorted((sy * (L.HALF - .45), sy * (L.HALF - .28)))
        m.box(ha + .1, hb - .1, y0, y1, .80, L.SKIRT_Z - .02, 'undercarriage')
    for sx in (-1, 1):            # headstocks
        x0, x1 = sorted((B.headstock(sx) - sx * .05, B.headstock(sx) + sx * .07))
        m.box(x0, x1, -L.HALF + .15, L.HALF - .15, .86, 1.24, 'end-dark')
    # equipment between the bogies: battery boxes, water tanks, brake cylinders, truss rods
    lo, hi = B.bogies[0] + B.wheelbase / 2 + .75, B.bogies[1] - B.wheelbase / 2 - .75
    f = lambda t: lo + (hi - lo) * t
    for t0, t1, y0, y1, z0, z1 in ((.0, .15, .25, 1.15, .45, .80), (.85, 1., -1.15, -.25, .45, .80), (.32, .68, -1.10, -.35, .40, .80),
                                   (.36, .45, .45, 1.15, .52, .80), (.56, .66, .45, 1.15, .55, .80)):
        m.box(f(t0), f(t1), y0, y1, z0, z1, 'undercarriage')
    if hi - lo > 6:
        for t in (.33, .67):
            m.cylinder((.65, .62), 'x', .22, f(t) - 1.0, f(t) + 1.0, 'undercarriage', 16)
    for sy in (-1, 1):
        for t0, t1 in ((0., .42), (.58, 1.)):
            m.box(f(t0), f(t1), sy * .55 - .02, sy * .55 + .02, .42, .46, 'steel')
    m.obj('Shell_Underframe', coll, parent=parent)
    # brass lining on the livery
    m = M()
    doors_x = sorted((x0 - .55, x1 + .55) for _, s, x0, x1, *_ in L.exterior_openings(c) if s > 0)
    for sy in (-1, 1):
        o = lambda d: sorted((sy * (L.HALF - .002), sy * (L.HALF + d)))
        y0, y1 = o(.006)
        for z in (L.BELT_Z, L.SKIRT_Z + .06):
            m.box(B.x_a + .08, B.x_b - .08, y0, y1, z - .009, z + .009, 'brass')
        # lined panels on the blue lower body, broken by the exterior doors
        for xa, xb in _free(B.x_a + .45, B.x_b - .45, doors_x, .8):
            for z in (L.SKIRT_Z + .16, L.BELT_Z - .10):
                m.box(xa, xb, y0, y1, z - .005, z + .005, 'brass')
            for x in (xa, xb):
                m.box(x - .005, x + .005, y0, y1, L.SKIRT_Z + .16, L.BELT_Z - .10, 'brass')
        for z in (L.CANT_Z - .16,):
            m.box(B.x_a + .08, B.x_b - .08, y0, y1, z - .006, z + .006, 'brass')
    m.obj('Shell_Lining', coll, parent=parent, lods=(0,))
    # the crest, a decal on each side of the blue band
    m = M()
    zc = (L.SKIRT_Z + .16 + L.BELT_Z - .10) / 2
    for sy in (-1, 1):
        y = sy * (L.HALF + .004)
        w = h = .56
        xs = (B.crest_x - w / 2, B.crest_x + w / 2)
        pts = [(xs[0], y, zc - h / 2), (xs[1], y, zc - h / 2), (xs[1], y, zc + h / 2), (xs[0], y, zc + h / 2)]
        uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
        if sy < 0:
            pts = [(xs[1] + xs[0] - p[0], p[1], p[2]) for p in pts]
        m.poly(pts, 'crest', uv=uv, normal=(0, sy, 0))
    m.obj('Shell_Crest', coll, parent=parent, closed=False)


def ends_hardware(c, coll, parent):
    m = M()
    for sx in (-1, 1):
        hs, bf = B.headstock(sx), B.buffer(sx)
        for sy in (-1, 1):            # buffers
            x0, x1 = sorted((hs + sx * .06, bf - sx * .06))
            m.cylinder((sy * L.BUFFER_Y, L.BUFFER_Z), 'x', .10, x0, x1, 'undercarriage', 16)
            x0, x1 = sorted((bf - sx * .06, bf))
            m.cylinder((sy * L.BUFFER_Y, L.BUFFER_Z), 'x', .20, x0, x1, 'steel', 20)
        x0, x1 = sorted((hs + sx * .06, bf - sx * .02))     # draw hook and screw link
        m.box(x0, x1, -.06, .06, L.BUFFER_Z - .07, L.BUFFER_Z + .05, 'undercarriage')
        m.box(bf - sx * .04 - .03, bf - sx * .04 + .03, -.12, .12, L.BUFFER_Z - .20, L.BUFFER_Z - .05, 'steel')
        for sy in (-1, 1):            # brake hoses
            m.box(hs + sx * .10 - .02, hs + sx * .10 + .02, sy * .35 - .02, sy * .35 + .02, .80, 1.15, 'rubber')
    m.obj('Shell_Buffers', coll, parent=parent)
    # gangways: a bellows frame around the end door, its face at the buffer line, and a footplate
    m = M()
    w_out, h_out = L.GANGWAY_W + .36, L.GANGWAY_H + .26
    z0 = L.FLOOR_Z - .06
    for sx in (-1, 1):
        if B.end(sx) != 'gangway':
            continue
        fx, bf = B.face(sx), B.buffer(sx)
        pitch = (abs(bf - fx) - .01) / 5
        for k in range(5):
            a0, a1 = sorted((fx + sx * (.002 + k * pitch), fx + sx * (.002 + (k + 1) * pitch - (.012 if k < 4 else 0))))
            g = .02 if k % 2 else 0
            yo, yi = w_out / 2 - g, L.GANGWAY_W / 2 + .04
            m.box(a0, a1, -yo, -yi, z0 + g, z0 + h_out - g, 'rubber')
            m.box(a0, a1, yi, yo, z0 + g, z0 + h_out - g, 'rubber')
            m.box(a0, a1, -yi, yi, z0 + L.GANGWAY_H + .08, z0 + h_out - g, 'rubber')
        a0, a1 = sorted((fx, bf - sx * .005))
        m.box(a0, a1, -L.GANGWAY_W / 2 - .02, L.GANGWAY_W / 2 + .02, L.FLOOR_Z - .03, L.FLOOR_Z - .005, 'steel')
    if m.faces:
        m.obj('Shell_Gangways', coll, parent=parent)
    # exterior door steps and brass grab handles
    m = M()
    for name, sy, x0, x1, *_ in L.exterior_openings(c):
        steps(m, sy, x0, x1)
        y = sy * L.HALF
        for x in (x0 - .07, x1 + .07):
            m.cylinder((x, sy * (L.HALF + .065)), 'z', .016, L.FLOOR_Z + .15, L.FLOOR_Z + 1.75, 'brass', 8)
            for z in (L.FLOOR_Z + .15, L.FLOOR_Z + 1.75):
                m.box(x - .012, x + .012, min(sy * L.HALF, sy * (L.HALF + .07)), max(sy * L.HALF, sy * (L.HALF + .07)), z - .012, z + .012, 'brass')
    m.obj('Shell_Steps', coll, parent=parent, lods=(0,))


def steps(m, sy, x0, x1, inset=0.):
    """Two hanging steps under a door or a balcony gate on side sy, from x0 to x1."""
    y = sy * (L.HALF - inset)
    for z, depth in ((.96, .18), (.66, .30)):
        ya, yb = sorted((y - sy * .22, y + sy * (depth - .22)))
        m.box(x0 + .02, x1 - .02, ya, yb, z - .03, z, 'steel')
        m.box(x0 + .02, x1 - .02, ya, yb, z - .004, z + .002, 'brass')
    for x in (x0 + .01, x1 - .01):
        m.box(x - .015, x + .015, min(y, y + sy * .08), max(y, y + sy * .08), .63, L.SKIRT_Z, 'undercarriage')


def balcony(c, coll, parent):
    """An open platform beyond the end wall: plank floor, brass railing with a gate gap and steps on each side,
    canopy posts holding the roof, and the red tail lamp."""
    for s in (-1, 1):
        if B.end(s) != 'balcony':
            continue
        edge, face = B.headstock(s), B.face(s)
        m = M(); trim = M()
        x0, x1 = sorted((edge, face))
        m.box(x0, x1, -L.HALF + .12, L.HALF - .12, L.FLOOR_Z - L.DECK, L.FLOOR_Z, 'parquet')
        for x0b, x1b, y0, y1 in L.railings(B):
            for z in (L.FLOOR_Z + .48, L.FLOOR_Z + 1.02):
                trim.box(x0b, x1b, y0, y1, z - .018, z + .018, 'brass')
            for x in (x0b, x1b) if x1b - x0b > .1 else ((x0b + x1b) / 2,):
                for y in ((y0 + y1) / 2,) if y1 - y0 < .1 else (y0 + .03, (y0 + y1) / 2, y1 - .03):
                    trim.cylinder((x, y), 'z', .022, L.FLOOR_Z, L.FLOOR_Z + 1.04, 'brass', 8)
        # balusters along the outer edge
        for k in range(15):
            y = -L.IN + .1 + (2 * L.IN - .2) * k / 14
            trim.cylinder((edge - s * .025, y), 'z', .012, L.FLOOR_Z, L.FLOOR_Z + 1.02, 'brass', 6)
        for sy in (-1, 1):            # canopy posts at the outer corners, up to the roof
            trim.cylinder((edge - s * .03, sy * (L.HALF - .10)), 'z', .035, L.FLOOR_Z, L.roof_z(L.HALF - .10, L.ROOF_SKIN), 'brass', 10)
            gx0, gx1 = sorted((face + s * .15, face + s * .85))
            steps(m, sy, gx0, gx1)
        lamp = next((mt for mt in c.mounts if mt.kind == 'tail-lamp'), None)
        if lamp:
            trim.box(lamp.x - .09, lamp.x + .09, lamp.y - .09, lamp.y + .09, lamp.z - .12, lamp.z + .12, 'end-dark')
            red = M(); red.cylinder((lamp.y, lamp.z), 'x', .07, lamp.x + s * .09, lamp.x + s * .11, 'lamp-red', 16)
            red.obj('Shell_TailLamp', coll, parent=parent)
        m.obj('Shell_Balcony', coll, parent=parent)
        trim.obj('Shell_BalconyRailing', coll, parent=parent)


def bogies(coll, parent, lod=0):
    """Identical two-axle bogies sharing one frame mesh and one wheelset mesh (linked data)."""
    if lod == 2:
        m = M()
        for bx in B.bogies:
            m.box(bx - B.wheelbase / 2 - .30, bx + B.wheelbase / 2 + .30, -1.08, 1.08, .20, .85, 'undercarriage')
        return [m.obj('LOD2_Bogies', coll, parent=parent, lods=(2,))]
    m = M()
    hl = B.wheelbase / 2 + .30
    for sy in (-1, 1):
        y0, y1 = sorted((sy * .96, sy * 1.06))
        m.box(-hl, hl, y0, y1, .36, .62, 'undercarriage')            # side frame
        m.box(-.55, .55, y0, y1, .62, .80, 'undercarriage')
        for x in (-B.wheelbase / 2, B.wheelbase / 2):
            m.box(x - .16, x + .16, y0 - .02, y1 + .02, .30, .64, 'undercarriage')   # axlebox guides
            m.cylinder((x, L.WHEEL_R), 'y', .085, *sorted((sy * 1.06, sy * 1.10)), 'brass', 12)   # brass axle caps
        for x in (-.75, -.45, .45, .75):                                   # bolster springs
            m.cylinder((x, sy * 1.01), 'z', .07, .62, .82, 'steel', 10)
    m.box(-.30, .30, -1.0, 1.0, .58, .80, 'undercarriage')                 # bolster
    for x in (-B.wheelbase / 2 - .25, B.wheelbase / 2 + .25):             # brake beams
        m.box(x - .04, x + .04, -.95, .95, .42, .50, 'undercarriage')
    out = []
    w = M()
    for sy in (-1, 1):
        y0, y1 = sorted((sy * (L.GAUGE / 2 - .02), sy * (L.GAUGE / 2 + .11)))
        w.cylinder((0, 0), 'y', L.WHEEL_R, y0, y1, 'steel', 24)
        f0, f1 = sorted((sy * (L.GAUGE / 2 - .02), sy * (L.GAUGE / 2 + .005)))
        w.cylinder((0, 0), 'y', L.WHEEL_R + .03, f0, f1, 'steel', 24)
        w.cylinder((0, 0), 'y', .15, *sorted((sy * (L.GAUGE / 2 + .11), sy * .98)), 'undercarriage', 12)
    w.cylinder((0, 0), 'y', .075, -.98, .98, 'undercarriage', 12)
    frame_me = wheel_me = None
    for end, bx in zip('ABCD', B.bogies):
        if frame_me is None:
            b = m.obj(f'Bogie_{end}', coll, parent=parent); frame_me = b.data
        else:
            b = _linked(f'Bogie_{end}', frame_me, coll, (0, 0, 0), parent)
        b.location = (bx, 0, 0)
        out.append(b)
        for k, ax in enumerate((-B.wheelbase / 2, B.wheelbase / 2)):
            name = f'Bogie_{end}_Wheelset_{k + 1}'
            if wheel_me is None:
                ws = w.obj(name, coll); wheel_me = ws.data
            else:
                ws = _linked(name, wheel_me, coll, (0, 0, 0), None)
            ws.parent = b
            ws.location = (ax, 0, L.WHEEL_R)
    return out


def _linked(name, me, coll, loc, parent):
    o = bpy.data.objects.new(name, me)
    o.location = loc
    coll.objects.link(o)
    if parent:
        o.parent = parent
    o['lods'] = [0, 1]
    return o


# --- each coach's interior ----------------------------------------------------------------------------------------
def floors(c, coll, parent):
    m = M()
    for r in c.rooms:
        m.poly([(r.x0, r.y0, L.FLOOR_Z), (r.x1, r.y0, L.FLOOR_Z), (r.x1, r.y1, L.FLOOR_Z), (r.x0, r.y1, L.FLOOR_Z)], r.floor, normal=(0, 0, 1))
    m.obj('Interior_Floor', coll, parent=parent, closed=False)


def partitions(c, coll, parent):
    objs = []
    m = M()
    for w in c.walls:
        if w.name.startswith('end-'):
            continue
        if w.axis == 'x':
            top = L.ceiling_z(min(abs(w.c0), abs(w.c1))) + .02
            m.box(w.a0, w.a1, w.c0, w.c1, L.FLOOR_Z - .006, top, 'walnut')
        else:
            pts = [(w.a0, L.FLOOR_Z - .006), (w.a1, L.FLOOR_Z - .006)]
            for k in range(13):
                y = w.a1 - (w.a1 - w.a0) * k / 12
                pts.append((y, L.ceiling_z(y) + .02))
            m.prism(pts, 'x', w.c0, w.c1, 'walnut')
    o = m.obj('Interior_Partitions', coll, parent=parent)
    cutters = []
    for w in c.walls:
        if w.name.startswith('end-'):
            continue
        for op in w.openings:
            cut = M()
            if w.axis == 'x':
                cut.box(op.a0, op.a1, w.c0 - .05, w.c1 + .05, op.z0 - .05, op.z1, 'glass')
            else:
                cut.box(w.c0 - .05, w.c1 + .05, op.a0, op.a1, op.z0 - .05, op.z1, 'glass')
            cutters.append(cut)
    boolean(o, cutters)
    reproject(o, lambda n, ctr: 'walnut')
    objs.append(o)
    return objs


PANELLED = {'cabin', 'corridor', 'salon', 'lobby', 'bar'}


def _free(a0, a1, blocked, min_len=.12):
    out, a = [], a0
    for b0, b1 in sorted(blocked):
        if b1 <= a or b0 >= a1:
            continue
        if b0 - a >= min_len:
            out.append((a, b0))
        a = max(a, b1)
    if a1 - a >= min_len:
        out.append((a, a1))
    return out


def _panels(m, axis, face, sign, intervals, z0, z1, target, kind):
    """Raised marquetry panels on a wall face. axis: the face runs along x ('x') or y ('y'); face: its coordinate
    across; sign: the side the panel stands proud on."""
    gap = .035
    for a, b in intervals:
        n = max(1, round((b - a) / target))
        w = (b - a - gap * (n + 1)) / n
        for k in range(n):
            p0 = a + gap + k * (w + gap); p1 = p0 + w
            if w < .08:
                continue
            tall = (z1 - z0) / w >= 1.0
            mat = kind if kind != 'auto' else ('panel-tall' if tall else 'panel-wide')
            c0, c1 = sorted((face, face + sign * .014))
            if axis == 'x':
                m.box(p0, p1, c0, c1, z0, z1, 'walnut', front=('y', sign), front_mat=mat)
            else:
                m.box(c0, c1, p0, p1, z0, z1, 'walnut', front=('x', sign), front_mat=mat)


def lining(c, coll, parent):
    """Marquetry panels, dado rail and skirting on the walls of the passenger rooms; brass window frames."""
    m = M(); trim = M()
    rooms = [r for r in c.rooms if r.kind in PANELLED]
    ext = L.exterior_openings(c)
    for sy in (-1, 1):
        face = sy * L.IN
        blocked_doors = [(x0 - .03, x1 + .03) for _, s, x0, x1, *_ in ext if s == sy]
        blocked_walls = [(w.c0 - .005, w.c1 + .005) for w in c.walls if w.axis == 'y' and (w.a1 >= L.IN - 1e-6 if sy > 0 else w.a0 <= -L.IN + 1e-6)]
        for r in rooms:
            if not (r.y1 >= L.IN - 1e-6 if sy > 0 else r.y0 <= -L.IN + 1e-6):
                continue
            base = blocked_doors + blocked_walls
            here = [w for w in c.windows if w.side == sy and r.x0 < w.x < r.x1 and w.kind == 'clear']
            sill = min((w.sill for w in here), default=L.SILL); head = max((w.head for w in here), default=L.HEAD)
            wins = [(w.x - w.width / 2 - .075, w.x + w.width / 2 + .075) for w in c.windows if w.side == sy]
            dado = _free(r.x0, r.x1, base)
            _panels(m, 'x', face, -sy, dado, L.FLOOR_Z + .12, sill - .07, .80, 'panel-wide')
            _panels(m, 'x', face, -sy, _free(r.x0, r.x1, base + wins), sill - .01, head + .01, .85, 'auto')
            if L.CEIL_SPRING - .07 - (head + .08) > .08:
                _panels(m, 'x', face, -sy, _free(r.x0, r.x1, base), head + .08, L.CEIL_SPRING - .07, 1.2, 'walnut')
            for a, b in dado:
                c0, c1 = sorted((face, face - sy * .03))
                trim.box(a, b, c0, c1, sill - .055, sill - .025, 'brass')
                c0, c1 = sorted((face, face - sy * .02))
                trim.box(a, b, c0, c1, L.FLOOR_Z, L.FLOOR_Z + .10, 'walnut')
    # partitions: both faces where they face a panelled room
    for w in c.walls:
        if w.name.startswith('end-'):
            continue
        for side in (-1, 1):
            face = w.c1 if side > 0 else w.c0
            probe = face + side * .1
            pt = (w.a0 + w.a1) / 2
            room = None
            for r in rooms:
                x, y = (pt, probe) if w.axis == 'x' else (probe, pt)
                for frac in (.1, .5, .9):
                    a = w.a0 + (w.a1 - w.a0) * frac
                    x, y = (a, probe) if w.axis == 'x' else (probe, a)
                    if r.x0 <= x <= r.x1 and r.y0 <= y <= r.y1:
                        room = r
            if room is None:
                continue
            lo, hi = (max(w.a0, room.x0), min(w.a1, room.x1)) if w.axis == 'x' else (max(w.a0, room.y0), min(w.a1, room.y1))
            blocked = [(o.a0 - .07, o.a1 + .07) for o in w.openings]
            for o2 in c.walls:            # walls meeting this face
                if o2.axis != w.axis and o2.a0 - 1e-3 <= face <= o2.a1 + 1e-3 or o2.axis != w.axis and abs(face - (o2.a0 if side > 0 else o2.a1)) < 1e-3:
                    blocked.append((o2.c0 - .005, o2.c1 + .005))
            top = min(L.ceiling_z(face) if w.axis == 'x' else L.CEIL_SPRING, L.CEIL_SPRING) - .07
            free = _free(lo, hi, blocked)
            _panels(m, w.axis, face, side, free, L.FLOOR_Z + .12, L.FLOOR_Z + .78, .80, 'panel-wide')
            _panels(m, w.axis, face, side, free, L.FLOOR_Z + .86, L.FLOOR_Z + 1.95, .80, 'auto')
            if top - (L.FLOOR_Z + 2.03) > .08:
                _panels(m, w.axis, face, side, free, L.FLOOR_Z + 2.03, top, 1.2, 'walnut')
            for a, b in free:
                c0, c1 = sorted((face, face + side * .03))
                if w.axis == 'x':
                    trim.box(a, b, c0, c1, L.FLOOR_Z + .80, L.FLOOR_Z + .83, 'brass')
                else:
                    trim.box(c0, c1, a, b, L.FLOOR_Z + .80, L.FLOOR_Z + .83, 'brass')
    m.obj('Interior_Lining', coll, parent=parent, lods=(0,))
    # architraves and thresholds round every interior doorway
    for w in c.walls:
        if w.name.startswith('end-'):
            continue
        for o in w.openings:
            glazed = any(d.opening == o.name and d.glazed for d in c.doors)
            mat = 'brass' if glazed else 'walnut'
            for side in (-1, 1):
                face = w.c1 if side > 0 else w.c0
                c0, c1 = sorted((face, face + side * .018))
                for a0, a1, z0, z1 in ((o.a0 - .06, o.a0, o.z0, o.z1 + .06), (o.a1, o.a1 + .06, o.z0, o.z1 + .06), (o.a0 - .06, o.a1 + .06, o.z1, o.z1 + .06)):
                    if w.axis == 'x':
                        trim.box(a0, a1, c0, c1, z0, z1, mat)
                    else:
                        trim.box(c0, c1, a0, a1, z0, z1, mat)
            if w.axis == 'x':
                trim.box(o.a0, o.a1, w.c0 - .02, w.c1 + .02, L.FLOOR_Z - .006, L.FLOOR_Z + .004, 'brass')
            else:
                trim.box(w.c0 - .02, w.c1 + .02, o.a0, o.a1, L.FLOOR_Z - .006, L.FLOOR_Z + .004, 'brass')
    trim.obj('Interior_Trim', coll, parent=parent, lods=(0,))


def window_frames(c, coll, parent, glass_coll, glass_parent):
    ext = M(); inner = M(); glass = M()
    for w in c.windows:
        zc, h = (w.sill + w.head) / 2, w.head - w.sill
        opening = rrect(w.x, zc, w.width, h, L.WIN_RADIUS)
        out = rrect(w.x, zc, w.width + .11, h + .11, L.WIN_RADIUS + .055)
        lip = rrect(w.x, zc, w.width - .03, h - .03, L.WIN_RADIUS - .015)
        sy = w.side
        ext.ring(out, lip, 'y', sy * (L.HALF - .002), sy * (L.HALF + .014), 'brass')
        inner.ring(rrect(w.x, zc, w.width + .13, h + .13, L.WIN_RADIUS + .065), lip, 'y', sy * (L.IN + .002), sy * (L.IN - .03), 'brass')
        y = sy * (L.IN + L.WALL * .55)
        glass.poly([(u, y, v) for u, v in opening], 'glass' if w.kind == 'clear' else 'glass-frosted', normal=(0, sy, 0))
    ext.obj('Shell_WindowFrames', coll, parent=parent)
    inner.obj('Interior_WindowFrames', coll, parent=parent, lods=(0,))
    o = glass.obj('Glazing_Windows', glass_coll, parent=glass_parent, closed=False, lods=(0, 1))
    return o


# --- doors --------------------------------------------------------------------------------------------------------
DOOR_RECORDS = []


def _door_leaf(name, width, height, thick, glazed, coll, parent, glass_coll, glass_parent, origin, axis, panel_mat='walnut'):
    """A leaf built about its own origin (bottom centre), long side along `axis` ('x' or 'y')."""
    m = M(); g = M()
    def B(a0, a1, t0, t1, z0, z1, mat, front=None, front_mat=None):
        if axis == 'x':
            m.box(a0, a1, t0, t1, z0, z1, mat, front, front_mat)
        else:
            m.box(t0, t1, a0, a1, z0, z1, mat, front, front_mat)
    hw, ht = width / 2, thick / 2
    if glazed:
        stile, rail, mid = .085, .09, .92
        B(-hw, -hw + stile, -ht, ht, 0, height, 'walnut'); B(hw - stile, hw, -ht, ht, 0, height, 'walnut')
        B(-hw + stile, hw - stile, -ht, ht, height - rail, height, 'walnut')
        for s in (-1, 1):
            t0, t1 = sorted((s * ht, s * (ht - .004)))
            B(-hw + stile, hw - stile, -ht, ht, 0, mid, 'walnut', front=('y' if axis == 'x' else 'x', s), front_mat='panel-tall')
        B(-hw + stile, hw - stile, -ht, ht, mid, mid + .05, 'brass')
        for s in (-1, 1):                 # brass glazing beads
            t0, t1 = sorted((s * ht, s * (ht + .008)))
            for a0, a1, z0, z1 in ((-hw + stile, -hw + stile + .02, mid, height - rail), (hw - stile - .02, hw - stile, mid, height - rail),
                                   (-hw + stile, hw - stile, height - rail - .02, height - rail), (-hw + stile, hw - stile, mid + .05, mid + .07)):
                B(a0, a1, t0, t1, z0, z1, 'brass')
        pts = [(-hw + stile, mid + .05), (hw - stile, mid + .05), (hw - stile, height - rail), (-hw + stile, height - rail)]
        if axis == 'x':
            g.poly([(u, 0, v) for u, v in pts], 'glass', normal=(0, 1, 0))
        else:
            g.poly([(0, u, v) for u, v in pts], 'glass', normal=(1, 0, 0))
    else:
        B(-hw, hw, -ht, ht, 0, height, 'walnut', front=('y' if axis == 'x' else 'x', 1), front_mat=panel_mat)
    for s in (-1, 1):                     # handles
        t0, t1 = sorted((s * ht, s * (ht + .03)))
        a = hw - .09
        B(a - .012, a + .012, t0, t1, 1.0, 1.22, 'brass')
    leaf = m.obj(f'Door_{name}', coll, origin=(0, 0, 0), parent=parent)
    leaf.location = origin
    leaf.parent = parent
    if g.faces:
        go = g.obj(f'Glazing_Door_{name}', glass_coll, closed=False)
        go.parent = leaf
    return leaf


def doors(c, coll, parent, glass_coll, glass_parent):
    DOOR_RECORDS.clear()
    walls = {w.name: w for w in c.walls}
    for d in c.doors:
        if d.kind == 'hinged' and d.name.startswith('exterior'):
            _exterior_door(c, d, coll, parent, glass_coll)
            continue
        w = walls[d.wall]
        o = next(o for o in w.openings if o.name == d.opening)
        thick = .035
        height = o.z1 - o.z0 + .03
        face = w.c1 if d.face > 0 else w.c0
        t = face + d.face * (.006 + thick / 2)
        if d.kind == 'sliding':
            a = (o.a0 + o.a1) / 2
            origin = (a, t, o.z0) if w.axis == 'x' else (t, a, o.z0)
            leaf = _door_leaf(d.name, d.width, height, thick, d.glazed, coll, parent, glass_coll, None, origin, w.axis)
            dirv = [d.slide * (o.a1 - o.a0), 0, 0] if w.axis == 'x' else [0, d.slide * (o.a1 - o.a0), 0]
            DOOR_RECORDS.append(dict(name=leaf.name, door=d.name, kind='sliding', pivot=list(origin), open_offset_m=dirv, opening=[o.a0, o.a1, o.z0, o.z1], wall=w.name))
        else:                               # hinged: two leaves (double) or one, hinged at the `slide` end
            leaves = ((o.a0, 1, -90), (o.a1, -1, 90)) if d.kind == 'double' else (((o.a0, 1, -90),) if d.slide < 0 else ((o.a1, -1, 90),))
            for k, (hinge, direction, swing) in enumerate(leaves):
                lw = (o.a1 - o.a0) / len(leaves)
                a = hinge + direction * lw / 2
                t = w.c1 if d.face > 0 else w.c0
                origin = (t + d.face * thick / 2, a, o.z0)
                leaf = _door_leaf(f'{d.name}_{k + 1}' if len(leaves) > 1 else d.name, lw - .005, o.z1 - o.z0, thick, d.glazed, coll, parent, glass_coll, None, origin, 'y')
                # move the origin to the hinge, keeping the leaf where it is
                shift = Vector((0, hinge - a, 0))
                leaf.data.transform(__import__('mathutils').Matrix.Translation(-shift))
                for ch in leaf.children:
                    ch.location -= shift
                leaf.location = Vector(origin) + shift
                DOOR_RECORDS.append(dict(name=leaf.name, door=d.name, kind='hinged', pivot=list(leaf.location), swing_deg=swing * d.face, opening=[o.a0, o.a1, o.z0, o.z1], wall=w.name))


def _exterior_door(c, d, coll, parent, glass_coll):
    name, sy, x0, x1, z0, z1 = next(e for e in L.exterior_openings(c) if e[0] == d.name.replace('exterior-door', 'exterior'))
    sx = -1 if x0 < 0 else 1
    hinge_x = x0 if sx < 0 else x1          # hinged on the end-wall side, opening inward
    yc = sy * (L.IN + L.WALL / 2)
    w = x1 - x0 + .01
    te, ti = sy * .026, -sy * .026          # exterior and interior faces of the leaf
    m = M(); g = M()
    # built relative to the hinge: the leaf runs from the hinge towards the coach centre (-sx)
    a0, a1 = sorted((0, -sx * w))
    m.box(a0, a1, -.026, .026, 0, L.BELT_Z - z0, 'livery-blue')
    m.box(a0, a1, -.026, .026, L.BELT_Z - z0, z1 - z0 + .01, 'livery-ivory')
    leaf = m.obj(f'Door_{d.name}', coll, parent=parent)
    oval_c = (-sx * w / 2, 1.42)
    cut = M(); cut.prism(ellipse(*oval_c, .30, .56, 24), 'y', -.08, .08, 'glass')
    boolean(leaf, [cut])
    belt = L.BELT_Z - z0
    reproject(leaf, lambda n, ctr: ('livery-blue' if ctr.z < belt else 'livery-ivory') if n.y * sy > .7
              else 'walnut' if n.y * sy < -.7 else ('livery-blue' if ctr.z < belt else 'livery-ivory'))
    trim = M()
    trim.ring(ellipse(*oval_c, .38, .64, 24), ellipse(*oval_c, .285, .545, 24), 'y', te - sy * .002, te + sy * .012, 'brass')
    trim.ring(ellipse(*oval_c, .36, .62, 24), ellipse(*oval_c, .285, .545, 24), 'y', ti + sy * .002, ti - sy * .012, 'brass')
    for t in (te, ti):                      # handles on both faces
        ta, tb = sorted((t, t + (t / abs(t)) * .03))
        trim.box(-sx * (w - .10) - .014, -sx * (w - .10) + .014, ta, tb, .95, 1.15, 'brass')
    ta, tb = sorted((te, te + sy * .004))
    for z in (.30, belt - .10):             # lining on the blue lower panel
        trim.box(min(0, -sx * w) + .05, max(0, -sx * w) - .05, ta, tb, z, z + .008, 'brass')
    tr = trim.obj(f'Door_{d.name}_Trim', coll)
    tr.parent = leaf
    g.poly([(u, 0, v) for u, v in ellipse(*oval_c, .30, .56, 24)], 'glass', normal=(0, sy, 0))
    go = g.obj(f'Glazing_Door_{d.name}', glass_coll, closed=False)
    go.parent = leaf
    leaf.location = (hinge_x, yc, z0)
    swing = 90 * sy * sx
    DOOR_RECORDS.append(dict(name=leaf.name, door=d.name, kind='hinged', pivot=[hinge_x, yc, z0], swing_deg=swing, opening=[x0, x1, z0, z1],
                             wall=f'side-{"l" if sy > 0 else "r"}'))


# --- reservations, markers, collision -----------------------------------------------------------------------------
def reservations(c, coll, parent):
    spec = {a['id']: a for a in L.contract()['assets']}
    for p in c.placements:
        a = spec[p.asset]; d = a['dimensions_m']
        w, dep, h = d['width'], d['depth'], d['height']
        m = M()
        if a['pivot'] == 'wall_mount_center':
            m.box(-w / 2, w / 2, -dep, 0, -h / 2, h / 2, 'reservation')
        else:
            m.box(-w / 2, w / 2, -dep / 2, dep / 2, 0, h, 'reservation')
        m.box(-.02, .02, -dep / 2 - .06 if a['pivot'] != 'wall_mount_center' else -dep - .06, -dep / 2 if a['pivot'] != 'wall_mount_center' else -dep, 0 if a['pivot'] != 'wall_mount_center' else -.02, .04, 'gauge')
        o = m.obj(f'FURN_{p.id}', coll, lods=())
        o.location = (p.x, p.y, p.z); o.rotation_euler = (0, 0, math.radians(p.yaw)); o.parent = parent
        o['asset'] = p.asset; o['room'] = p.room; o['yaw_deg'] = p.yaw
    for b in c.reservations:
        m = M(); m.box(b.x0, b.x1, b.y0, b.y1, b.z0, b.z1, 'reservation-service')
        o = m.obj(f'RES_{b.name}', coll, parent=parent, lods=())
        o['kind'] = b.kind; o['note'] = b.note
    for s in c.seats:
        e = bpy.data.objects.new(f'SEAT_{s.id}', None); e.empty_display_type = 'SINGLE_ARROW'; e.empty_display_size = .25
        e.location = (s.x, s.y, s.z); e.rotation_euler = (math.radians(90), 0, math.radians(s.yaw + 180))
        e['furniture'] = s.furniture; e['yaw_deg'] = s.yaw; e['lods'] = []
        coll.objects.link(e); e.parent = parent
    for mt in c.mounts:
        e = bpy.data.objects.new(f'MOUNT_{mt.id}', None); e.empty_display_type = 'PLAIN_AXES'; e.empty_display_size = .12
        e.location = (mt.x, mt.y, mt.z); e.rotation_euler = (0, 0, math.radians(mt.yaw))
        e['kind'] = mt.kind; e['length_m'] = mt.length; e['lods'] = []
        coll.objects.link(e); e.parent = parent


def collision_boxes(c):
    """Simple convex boxes for walking: floor, walls broken at every doorway, partitions, ceiling and fixed fittings."""
    boxes = []
    add = lambda n, *b: boxes.append((n, b))
    add('floor', B.in_a, B.in_b, -L.IN, L.IN, L.FLOOR_Z - .20, L.FLOOR_Z)
    add('ceiling', B.in_a, B.in_b, -L.IN, L.IN, L.CEIL_SPRING, L.CEIL_SPRING + .15)
    for s in (-1, 1):
        if B.end(s) == 'balcony':
            x0, x1 = sorted((B.headstock(s), B.face(s)))
            add('balcony-floor', x0, x1, -L.IN, L.IN, L.FLOOR_Z - .20, L.FLOOR_Z)
    for i, (x0, x1, y0, y1) in enumerate(L.railings(B)):
        add(f'railing-{i}', x0, x1, y0, y1, L.FLOOR_Z, L.FLOOR_Z + 1.05)
    for sy in (-1, 1):
        y0, y1 = sorted((sy * L.IN, sy * L.HALF))
        doors_x = sorted((x0, x1) for _, s, x0, x1, *_ in L.exterior_openings(c) if s == sy)
        for a, b in _free(B.x_a, B.x_b, doors_x, 0.):
            add(f'side-{sy}', a, b, y0, y1, L.FLOOR_Z, L.CANT_Z)
        for x0, x1 in doors_x:
            add(f'side-{sy}-over-door', x0, x1, y0, y1, L.FLOOR_Z + L.DOOR_H, L.CANT_Z)
    for w in c.walls:
        spans = _free(w.a0, w.a1, [(o.a0, o.a1) for o in w.openings], 0.)
        top = L.CEIL_SPRING if not w.name.startswith('end-') else L.CANT_Z
        for a, b in spans:
            add(w.name, *((a, b, w.c0, w.c1) if w.axis == 'x' else (w.c0, w.c1, a, b)), L.FLOOR_Z, top)
        for o in w.openings:
            add(f'{w.name}-head', *((o.a0, o.a1, w.c0, w.c1) if w.axis == 'x' else (w.c0, w.c1, o.a0, o.a1)), o.z1, top)
    for b in c.reservations:
        if b.z0 - L.FLOOR_Z < 1.0 and b.kind in ('bar-counter', 'back-bar', 'galley-counter', 'pantry-counter', 'luggage-shelves', 'wc-toilet', 'drinks-ledge'):
            add(b.name, b.x0, b.x1, b.y0, b.y1, L.FLOOR_Z, b.z1)
    return [(n, b) for n, b in boxes if b[1] - b[0] > 1e-4 and b[3] - b[2] > 1e-4 and b[5] - b[4] > 1e-4]


def collision(c, coll, parent, mesh_name):
    out = []
    for i, (n, b) in enumerate(collision_boxes(c)):
        m = M(); m.box(*b, 'reservation-service')
        o = m.obj(f'UCX_{mesh_name}_{i:02d}', coll, parent=parent, lods=())
        o['part'] = n; o.display_type = 'WIRE'
        out.append(o)
    return out


def lod2_hull(c, coll, parent):
    m = M()
    m.box(B.x_a, B.x_b, -L.HALF, L.HALF, L.SKIRT_Z, L.BELT_Z, 'livery-blue')
    m.box(B.x_a, B.x_b, -L.HALF, L.HALF, L.BELT_Z, L.CANT_Z, 'livery-ivory')
    for w in c.windows:
        y = w.side * (L.HALF + .003)
        m.poly([(w.x - w.width / 2, y, w.sill), (w.x + w.width / 2, y, w.sill), (w.x + w.width / 2, y, w.head), (w.x - w.width / 2, y, w.head)], 'glass-dark', normal=(0, w.side, 0))
    for name, sy, x0, x1, z0, z1 in L.exterior_openings(c):
        y = sy * (L.HALF + .002)
        m.poly([(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)], 'livery-blue', normal=(0, sy, 0))
    for sx in (-1, 1):
        x0, x1 = sorted((B.headstock(sx), B.buffer(sx)))
        m.box(x0, x1, -L.GANGWAY_W / 2 - .18, L.GANGWAY_W / 2 + .18, L.FLOOR_Z - .06, L.FLOOR_Z + L.GANGWAY_H + .2, 'rubber')
        for sy in (-1, 1):
            m.box(x0, x1, sy * L.BUFFER_Y - .15, sy * L.BUFFER_Y + .15, L.BUFFER_Z - .15, L.BUFFER_Z + .15, 'undercarriage')
    m.box(-7, 7, -1.2, 1.2, .45, L.SKIRT_Z, 'undercarriage')
    m.obj('LOD2_Hull', coll, parent=parent, lods=(2,), closed=False)


# --- export -------------------------------------------------------------------------------------------------------
def tris(objs):
    n = 0
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        if o.type == 'MESH':
            n += sum(len(p.vertices) - 2 for p in o.data.polygons)
    return n


def export_glb(path, objs):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.hide_set(False); o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB', use_selection=True, export_yup=True, export_apply=True,
                              export_extras=True, export_materials='EXPORT', export_image_format='AUTO', export_cameras=False,
                              export_lights=False, export_animations=False)
    bpy.ops.object.select_all(action='DESELECT')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mesh_checks(objs):
    """Closed meshes (manifold, outward) and no degenerate faces in the architectural parts."""
    report = {}
    for o in objs:
        if o.type != 'MESH' or o.name.startswith(('Glazing', 'Interior_Floor', 'Ceiling', 'Shell_Crest', 'LOD2_Hull', 'Roof_Details', 'Roof_CupolaTop')):
            continue
        bm = bmesh.new(); bm.from_mesh(o.data)
        boundary = sum(1 for e in bm.edges if e.is_boundary)
        nonman = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
        degenerate = sum(1 for f in bm.faces if f.calc_area() < 1e-9)
        vol = bm.calc_volume(signed=True)
        bm.free()
        report[o.name] = dict(boundary_edges=boundary, non_manifold_edges=nonman, degenerate_faces=degenerate, signed_volume_m3=round(vol, 4))
    return report


B = L.Body()      # the body of the vehicle being built (build() sets it)


def build(coach, images):
    global B
    B = coach.body
    bpy.ops.wm.read_factory_settings(use_empty=True)
    MAT.clear()
    for name, img in images.items():
        if name not in bpy.data.images:
            images[name] = bpy.data.images.load(str(TEX / f'{name}.png'))
            images[name].name = name
    make_materials(images)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'; scene.unit_settings.scale_length = 1.
    title = ''.join(p.title() for p in coach.name.split('-'))
    mesh_name = f'SM_BT_{title}'
    cols = {}
    for n in ('Shell', 'Roof', 'Glazing', 'Doors', 'Interior', 'LOD2', 'Reservations', 'Collision'):
        cols[n] = bpy.data.collections.new(f'{title}_{n}'); scene.collection.children.link(cols[n])
    root = group(f'BT_{title}', cols['Shell'])
    root['coach'] = coach.name; root['frame'] = L.as_dict(coach)['frame']
    g = {n: group(f'BT_{title}_{n}', cols[n], root) for n in ('Shell', 'Roof', 'Glazing', 'Doors', 'Interior')}
    side_walls(coach, cols['Shell'], g['Shell'])
    end_walls(coach, cols['Shell'], g['Shell'])
    deck_and_underframe(coach, cols['Shell'], g['Shell'])
    ends_hardware(coach, cols['Shell'], g['Shell'])
    balcony(coach, cols['Shell'], g['Shell'])
    bogies(cols['Shell'], g['Shell'])
    roof(cols['Roof'], g['Roof'])
    ceiling(coach, cols['Roof'], g['Roof'])
    floors(coach, cols['Interior'], g['Interior'])
    partitions(coach, cols['Interior'], g['Interior'])
    lining(coach, cols['Interior'], g['Interior'])
    window_frames(coach, cols['Shell'], g['Shell'], cols['Glazing'], g['Glazing'])
    doors(coach, cols['Doors'], g['Doors'], cols['Glazing'], g['Glazing'])
    for end, e in L.coupling(B)['ends'].items():   # attachment sockets, exported in every LOD
        for name, loc in [('Coupler', e['draw_hook'])] + ([('Gangway', e['gangway_face_centre'])] if 'gangway_face_centre' in e else []):
            so = bpy.data.objects.new(f'SOCKET_{name}_{end.upper()}', None); so.empty_display_type = 'ARROWS'; so.empty_display_size = .4
            so.location = loc; so.rotation_euler = (0, 0, 0 if end == 'b' else math.pi)
            so['lods'] = [0, 1, 2]; so['length_m'] = B.length
            cols['Shell'].objects.link(so); so.parent = root
    lod2 = group(f'BT_{title}_LOD2', cols['LOD2']); lod2['lods'] = [2]
    lod2_hull(coach, cols['LOD2'], lod2)
    roof(cols['LOD2'], lod2, lod=2)
    bogies(cols['LOD2'], lod2, lod=2)
    res_root = group(f'BT_{title}_Reservations', cols['Reservations']); res_root['lods'] = []
    reservations(coach, cols['Reservations'], res_root)
    col_root = group(f'BT_{title}_Collision', cols['Collision']); col_root['lods'] = []
    ucx = collision(coach, cols['Collision'], col_root, mesh_name)
    cols['LOD2'].hide_render = True; cols['Collision'].hide_render = True
    for o in cols['LOD2'].objects:
        o.hide_set(True)
    out = OUT / coach.name; out.mkdir(parents=True, exist_ok=True)
    every = list(scene.objects)
    lod_sets = {k: [o for o in every if k in list(o.get('lods', []))] for k in (0, 1, 2)}
    lod_sets[0] = [o for o in lod_sets[0] if o.name != lod2.name]
    lod_sets[1] = [o for o in lod_sets[1] if o.name != lod2.name]
    files = {}
    for k in (0, 1, 2):
        p = out / f'{mesh_name}_LOD{k}.glb'; export_glb(p, lod_sets[k]); files[p.name] = p
    p = out / f'{mesh_name}_Collision.glb'; export_glb(p, [col_root] + ucx); files[p.name] = p
    blockout = [res_root] + [o for o in every if o.parent == res_root]
    p = out / f'{coach.name}-blockout.glb'; export_glb(p, blockout); files[p.name] = p
    placements = L.as_dict(coach)
    placements['doors_runtime'] = DOOR_RECORDS
    placements['envelope'] = L.envelope()
    placements['coupling'] = L.coupling(B)
    placements['collision_boxes'] = [dict(name=f'UCX_{mesh_name}_{i:02d}', part=n, box=[round(v, 4) for v in b]) for i, (n, b) in enumerate(collision_boxes(coach))]
    p = out / f'{coach.name}-placements.json'; p.write_text(json.dumps(placements, indent=1)); files[p.name] = p
    for o in cols['Reservations'].objects:
        o.hide_render = False
    for o in cols['LOD2'].objects:
        o.hide_set(True)
    p = out / f'{coach.name}.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(p), compress=True, relative_remap=True)
    files[p.name] = p
    info = dict(
        title=coach.title, mesh=mesh_name,
        triangles={f'LOD{k}': tris(lod_sets[k]) for k in (0, 1, 2)},
        objects={f'LOD{k}': sum(1 for o in lod_sets[k] if o.type == 'MESH') for k in (0, 1, 2)},
        materials=sorted({s.material.name for o in lod_sets[0] if o.type == 'MESH' for s in o.material_slots if s.material}),
        collision_boxes=len(ucx), placements=len(coach.placements), seats=len(coach.seats), mounts=len(coach.mounts),
        reservations=len(coach.reservations), doors=len(DOOR_RECORDS),
        mesh_checks=mesh_checks(lod_sets[0]),
        layout_checks=L.check(coach),
        files={n: dict(bytes=f.stat().st_size, sha256=sha(f)) for n, f in files.items()},
    )
    return info


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    images = make_textures()
    paths = {n: TEX / f'{n}.png' for n in images}
    manifest = dict(
        version=1, about='Belmonte train coach shells, generated by games/yorimichi/world/train/build.py from train/layout.py',
        units='metres in the .blend and placements; GLBs are standard glTF (Y-up) exported by Blender',
        frame=L.as_dict(L.restaurant())['frame'], envelope=L.envelope(), coupling=L.coupling(),
        human_gauges=dict(cairo=L.CAIRO, adult=L.HUMAN),
        budgets=dict(LOD0_triangles=60000, LOD1_triangles=20000, LOD2_triangles=1500, textures='7 maps, 512-1024 px, shared by both coaches'),
        textures={n: dict(bytes=p.stat().st_size, sha256=sha(p)) for n, p in paths.items()},
        coaches={},
    )
    for coach in L.coaches():
        manifest['coaches'][coach.name] = build(coach, dict(images))
        print(f'BELMONTE TRAIN {coach.name}: {manifest["coaches"][coach.name]["triangles"]}', flush=True)
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=1))
    bad = [(n, c['layout_checks']) for n, c in manifest['coaches'].items() if c['layout_checks']]
    if bad:
        raise SystemExit(f'layout checks failed: {bad}')
    print('BELMONTE TRAIN BUILD COMPLETE', flush=True)


if __name__ == '__main__':
    main()
