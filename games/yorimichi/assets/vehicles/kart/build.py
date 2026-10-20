"""The go-kart: an open frame with a cream seat and a wheel the driver holds.

Metres; +X is the nose, the ground is z = 0, +Y the car's left. Three meshes, each with its own pivot:
SM_Kart_Body (the kart at rest, origin on the ground under its middle), SM_Kart_Wheel (one wheel, origin at
its axle, axis +Y) and SM_Kart_SteeringWheel (origin at the hub, axis +X, the plane the driver faces).
"""
import sys as _sys; from pathlib import Path as _Path; _sys.path.insert(0, str(_Path(__file__).resolve().parents[3] / 'world')); import yori  # noqa: E402,F401
import json
import math

import bpy
from mathutils import Matrix, Vector
from village import build as v

OUT = yori.OUT / 'kart'; v.OUT = OUT

RED = (.60, .09, .035); CREAM = (.64, .58, .46); DARK = (.028, .028, .033)
METAL = (.34, .34, .32); CHROME = (.58, .58, .55); TYRE = (.015, .015, .018)
HUB = (.62, .50, .30); AMBER = (.72, .26, .02); LAMP = (.82, .78, .66)

WHEEL_RADIUS, WHEEL_WIDTH = .14, .11
TRACK_FRONT, TRACK_REAR = 1.10, 1.24
WHEELBASE, FRONT_AXLE = 1.50, .75
STEER_RADIUS = .15
STEER_AT = (0.06, 0.0, .55)


def disc(m, z, r, color, n=20):
    pts = [(r * math.cos(i * 2 * math.pi / n), r * math.sin(i * 2 * math.pi / n), z) for i in range(n)]
    for k in range(n):
        tri = [(0, 0, z), pts[k], pts[(k + 1) % n]]
        m.poly(tri if z >= 0 else tri[::-1], color)


def ring(m, z, outer, inner, color, n=20):
    a = [(outer * math.cos(i * 2 * math.pi / n), outer * math.sin(i * 2 * math.pi / n), z) for i in range(n)]
    b = [(inner * math.cos(i * 2 * math.pi / n), inner * math.sin(i * 2 * math.pi / n), z) for i in range(n)]
    for k in range(n):
        quad = [a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]]
        m.poly(quad if z >= 0 else quad[::-1], color)


def tube(m, z0, z1, r, color, n=20, inward=False):
    a = [(r * math.cos(i * 2 * math.pi / n), r * math.sin(i * 2 * math.pi / n), z0) for i in range(n)]
    b = [(r * math.cos(i * 2 * math.pi / n), r * math.sin(i * 2 * math.pi / n), z1) for i in range(n)]
    for k in range(n):
        quad = [a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]]
        m.poly(quad[::-1] if inward else quad, color)


def signed_volume(m):
    """Positive when a closed part's faces wind outward (the one-sided material culls the rest)."""
    total = 0.0
    for face in m.faces:
        p0 = Vector(m.vertices[face[0]])
        for k in range(1, len(face) - 1):
            total += p0.dot(Vector(m.vertices[face[k]]).cross(Vector(m.vertices[face[k + 1]]))) / 6.0
    return total


def check_normals(m, axis, inner_radius=None, outer_radii=()):
    """Per-face winding check: end faces face out of the part, walls face their own side.

    Fails the reversed end faces 16b11f12 shipped (their flat normals pointed through the part) and the
    outward-wound inner rim wall.
    """
    unit = {'X': Vector((1, 0, 0)), 'Y': Vector((0, 1, 0)), 'Z': Vector((0, 0, 1))}[axis]
    for face in m.faces:
        pts = [Vector(m.vertices[i]) for i in face]
        normal = Vector((0, 0, 0))
        for k in range(1, len(pts) - 1):
            normal += (pts[k] - pts[0]).cross(pts[k + 1] - pts[0])
        if normal.length < 1e-12:
            continue
        centre = sum(pts, Vector((0, 0, 0))) / len(pts)
        axial = normal.dot(unit)
        offset = centre.dot(unit)
        flat = abs(axial) > .7 * normal.length
        if flat and abs(offset) > 1e-4:
            assert (axial > 0) == (offset > 0), (m.name, 'end face winds through the part', centre, normal)
        elif not flat:
            radial = centre - unit * offset
            if radial.length < 1e-6:
                continue
            alignment = normal.dot(radial) / (normal.length * radial.length)
            if abs(alignment) < .5:
                continue   # a sliver or a face that is not radial; the end-face rule covers its plane
            if inner_radius is not None and abs(radial.length - inner_radius) < .004:
                assert alignment < 0, (m.name, 'inner wall winds outward', centre, normal)
            elif any(abs(radial.length - r) < .004 for r in outer_radii):
                assert alignment > 0, (m.name, 'outer wall winds inward', centre, normal)


def winding_selftest():
    """A negative end face wound toward +Z, as 16b11f12 shipped, must fail check_normals."""
    m = v.Mesh('selftest')
    pts = [(math.cos(i * 2 * math.pi / 8), math.sin(i * 2 * math.pi / 8), -1.0) for i in range(8)]
    for k in range(8):
        m.poly([(0, 0, -1.0), pts[k], pts[(k + 1) % 8]], (.5, .5, .5))
    try:
        check_normals(m, 'Z')
    except AssertionError:
        return
    raise AssertionError('winding check missed a reversed negative end face')


def wheel():
    m = v.Mesh('SM_Kart_Wheel')
    m.transform = Matrix.Rotation(math.radians(-90), 4, 'X')   # the axle becomes +Y
    half = WHEEL_WIDTH / 2
    m.lathe((0, 0, 0), [(-half, .108), (-half, WHEEL_RADIUS), (-half * .7, WHEEL_RADIUS + .006),
                        (half * .7, WHEEL_RADIUS + .006), (half, WHEEL_RADIUS), (half, .108)], TYRE, n=20)
    for z in (-half, half):
        ring(m, z, .108, .062, TYRE, n=20)
        disc(m, z * .92, .064, HUB, n=20)
    m.lathe((0, 0, 0), [(-.045, .028), (.045, .028)], CHROME, n=10)   # the hub's cap
    return m


def steering_wheel():
    m = v.Mesh('SM_Kart_SteeringWheel')
    m.transform = Matrix.Rotation(math.radians(90), 4, 'Y')   # the plane faces +X
    for z in (-.011, .011):
        ring(m, z, STEER_RADIUS, STEER_RADIUS - .026, DARK, n=20)
    m.lathe((0, 0, 0), [(-.011, STEER_RADIUS), (.011, STEER_RADIUS)], DARK, n=20)
    tube(m, -.011, .011, STEER_RADIUS - .026, DARK, n=20, inward=True)
    for angle in (90, 210, 330):
        a = math.radians(angle)
        m.beam((0, 0, 0), ((STEER_RADIUS - .02) * math.cos(a), (STEER_RADIUS - .02) * math.sin(a), 0), .018, .012, CHROME)
    m.lathe((0, 0, 0), [(-.022, .028), (.022, .028)], CHROME, n=10)
    return m


def kart():
    m = v.Mesh('SM_Kart_Body')
    # The frame: two rails and four cross members under the floor.
    for s in (1, -1):
        m.beam((-.78, s * .40, .17), (.70, s * .40, .17), .045, .045, DARK)
    for x in (-.76, -.28, .30, .66):
        m.beam((x, -.42, .15), (x, .42, .15), .04, .04, DARK)
    m.box((-.04, 0, .125), (1.38, .76, .035), (.10, .10, .105), bevel=.01)          # floor pan
    # Nose fairing, bumper and the front hubs' uprights.
    m.box((.83, 0, .17), (.30, .62, .10), RED, bevel=.03)
    m.box((.95, 0, .14), (.09, 1.02, .06), RED, bevel=.02)
    for s in (1, -1):
        m.beam((.62, s * .30, .19), (.72, s * (TRACK_FRONT / 2), .20), .04, .04, METAL)
        m.box((.10, s * .51, .19), (.46, .12, .10), RED, bevel=.02)                 # side pod
    m.box((-.90, 0, .21), (.10, 1.14, .10), RED, bevel=.02)                        # rear bumper
    # The engine behind the seat, and the exhaust.
    m.box((-.70, .24, .30), (.30, .26, .20), METAL, bevel=.02)
    for dy in (-.06, 0, .06):
        m.box((-.70, .24 + dy, .40), (.24, .02, .03), (.16, .16, .16))
    m.lathe((-.84, .24, .29), [(0, .055), (.05, .05)], CHROME, n=10)
    # Steering column and dashboard.
    m.beam((-.02, 0, .40), STEER_AT, .035, .035, CHROME)
    m.box((.36, 0, .115), (.16, .70, .03), METAL)                                    # pedal plate
    for s in (1, -1):
        m.box((.32, s * .15, .15), (.05, .10, .07), CHROME)                          # pedal
    # A low hoop behind the seat and the number plate on the nose.
    for s in (1, -1):
        m.beam((-.66, s * .38, .20), (-.78, s * .30, .42), .03, .03, DARK)
    m.beam((-.78, -.30, .42), (-.78, .30, .42), .03, .03, DARK)
    m.box((.86, 0, .27), (.06, .22, .10), LAMP, bevel=.01)
    for s in (1, -1):
        m.box((.96, s * .20, .20), (.05, .07, .05), AMBER)
    m.collider((0, 0, .28), (2.0, 1.25, .56))
    return m


def seat():
    """The pan and its reclined backrest, on their own pivot so the seat can slide along the frame."""
    m = v.Mesh('SM_Kart_Seat')
    m.box((0, 0, 0), (.44, .44, .05), CREAM, bevel=.02)
    back = Matrix.Translation(Vector((-.14, 0, .155))) @ Matrix.Rotation(math.radians(-20), 4, 'Y')
    m.transform = back
    m.box((0, 0, 0), (.06, .44, .42), CREAM, bevel=.02)
    m.transform = Matrix.Identity(4)
    return m


def main():
    winding_selftest()
    OUT.mkdir(parents=True, exist_ok=True); (OUT / 'assets').mkdir(exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    mat = bpy.data.materials.new('KartPalette'); mat.use_nodes = True
    vc = mat.node_tree.nodes.new('ShaderNodeVertexColor'); vc.layer_name = 'Color'
    mat.node_tree.links.new(vc.outputs['Color'], mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
    manifest = {}
    for make in (kart, seat, wheel, steering_wheel):
        m = make(); ob, report = v.export(m, mat); manifest[m.name] = report
        if m.name in ('SM_Kart_Seat', 'SM_Kart_Wheel', 'SM_Kart_SteeringWheel'):
            volume = signed_volume(m)
            assert volume > 0.0, (m.name, 'faces wind inward', volume)
            if m.name == 'SM_Kart_SteeringWheel':
                check_normals(m, 'X', STEER_RADIUS - .026, (STEER_RADIUS, .028))
            elif m.name == 'SM_Kart_Wheel':
                check_normals(m, 'Y', None, (.028, .062, .108, WHEEL_RADIUS, WHEEL_RADIUS + .006))
            else:
                check_normals(m, 'Z')   # flat end faces only
            print('WINDING', m.name, round(volume, 6))
        bpy.data.objects.remove(ob, do_unlink=True)
    layout = {'wheel_radius': WHEEL_RADIUS, 'wheel_width': WHEEL_WIDTH, 'track_front': TRACK_FRONT,
              'track_rear': TRACK_REAR, 'wheelbase': WHEELBASE, 'front_axle': FRONT_AXLE,
              'steering_radius': STEER_RADIUS, 'steering_at': list(STEER_AT)}
    manifest['layout'] = layout
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('KART BUILD COMPLETE', sum(a['triangles'] for k, a in manifest.items() if k != 'layout'), 'triangles')


if __name__ == '__main__':
    main()
