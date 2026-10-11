"""Face shape, nose, brows and cheeks of a Tripo head, brought to the face sheet's proportions.

Used by cleanup_face_hair.py. Every measure comes from overlaying the face sheet's front view on a front render of
the model with the pupils made to coincide, in units of the pupil spacing (sp). The drawing's pupils are the dark
centres of its irises, (242.3, 235.9) and (334.9, 235.8) in face-six-views.png: sp = 92.6 px. (A first measure
took the lash line for a pupil and overstated sp by 12%, which made the eyes too small and too far apart.)

- lower face: the nose and mouth already sit where the drawing's do; the jaw does not. Tripo's chin is a V whose tip
  is 3 mm above the drawing's broad U. fit_jaw() drops the jaw outline onto the drawing's (JAW_DROP), on the front
  of the head only; the neck stays attached to the collar.
- nose: Tripo's nostril dimples and frozen shading made a brown smudge. smooth_nose() evens out the dimples;
  paint() clears the nose to skin and draws it as drawn: a soft round shade on the bulb, a light tip, two small dark
  arched nostrils 0.20 sp apart, a faint shade under it.
- brows: the drawing's are thick and almost straight, 0.42 sp above the pupils, from 0.22 sp toward the nose to
  0.40 sp outward, 0.13 sp thick, tapering and dropping at the outer end. Tripo's brow strips are removed by the
  cleanup and paint() draws these instead.
- cheeks: a soft blush 0.37 sp under each pupil and a few freckles across the cheeks and the nose bridge.
"""
import math

import numpy as np

BROW = np.array([.21, .14, .10], np.float32)
NOSTRIL = np.array([.20, .12, .09], np.float32)
NOSE_SHADE = np.array([.88, .55, .41], np.float32)
NOSE_TIP = np.array([1.0, .82, .70], np.float32)
BLUSH = np.array([.96, .55, .47], np.float32)
FRECKLE = np.array([.80, .47, .37], np.float32)


def smoothstep(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0, 1)
    return t * t * (3 - 2 * t)


# The jaw outline seen from the front, as height (m) against distance from the face's centre line (m): the model's
# (Tripo's lower face, a V) and how far each point must drop to lie on the drawing's (a U), from the face sheet's
# outline traced column by column with the pupils overlaid (pupil spacing 57.1 mm, pupils at z 0.3854).
JAW_MODEL = ((0.0, .3103), (.0040, .3110), (.0084, .3140), (.0157, .3170), (.0225, .3200), (.0308, .3260),
             (.0377, .3320), (.0416, .3380))
JAW_DROP = ((0.0, -.0042), (.0051, -.0045), (.0086, -.0055), (.0120, -.0052), (.0148, -.0043), (.0183, -.0039),
            (.0217, -.0031), (.0251, -.0034), (.0286, -.0033), (.0320, -.0032), (.0354, -.0034), (.0388, -.0037),
            (.0420, -.0020), (.0450, 0.0))


def fit_jaw(mesh, world, vertices, centre_y, z_mouth, z_collar):
    """Bring the jaw outline onto the drawing's: Tripo's chin is a V 3 mm too high, the drawing's a broad U.

    At a distance d from the centre line the outline must drop by JAW_DROP(d). Vertices between the mouth line and
    the outline drop by that amount times how far down they are (0 at the mouth, 1 on the outline); under the
    outline (the chin's underside, the front of the neck) the drop fades out toward z_collar so the neck stays on the
    collar. Only the front of the head moves (x > 0), and only vertically."""
    from mathutils import Vector
    inverse = world.inverted()
    model_d, model_z = np.array(JAW_MODEL).T
    drop_d, drop_z = np.array(JAW_DROP).T
    moved, largest = 0, 0.0
    for index in vertices:
        p = world @ mesh.vertices[index].co
        if p.z >= z_mouth or p.x < -.012:
            continue
        d = abs(p.y - centre_y)
        drop = float(np.interp(d, drop_d, drop_z, right=0.0))
        if drop == 0.0:
            continue
        outline_z = float(np.interp(d, model_d, model_z))
        if p.z >= outline_z:
            f = float(smoothstep(0, 1, (z_mouth - p.z) / max(z_mouth - outline_z, 1e-4)))
        else:
            f = float(smoothstep(z_collar, outline_z, p.z))
        dz = drop * f * float(smoothstep(-.012, .012, p.x))
        if dz < -1e-6:
            mesh.vertices[index].co = inverse @ Vector((p.x, p.y, p.z + dz))
            moved += 1
            largest = max(largest, -dz)
    mesh.update()
    return {'vertices_moved': moved, 'largest_drop_mm': round(largest * 1000, 2)}


def widen_lower_face(mesh, world, vertices, centre_y, z_fade_top, z_full_top, z_full_bottom, z_fade_bottom, amount):
    """Widen the cheeks and jaw by `amount` (0.09 = 9%) about the centre line: in full between z_full_bottom and
    z_full_top, fading to nothing at z_fade_top (under the cheekbones and ears) and z_fade_bottom (the chin), and
    only toward the front (x from -0.03 to 0), so the back of the head and the neck do not move. With the pupils
    and the chin matched, the drawing's lower face is 9 to 13% wider than the model's."""
    from mathutils import Vector
    inverse = world.inverted()
    moved = 0
    for index in vertices:
        p = world @ mesh.vertices[index].co
        w = float(smoothstep(z_fade_top, z_full_top, p.z) if p.z > z_full_top else
                  smoothstep(z_fade_bottom, z_full_bottom, p.z) if p.z < z_full_bottom else 1.0)
        w *= float(smoothstep(-.03, 0.0, p.x))
        if w <= 0:
            continue
        mesh.vertices[index].co = inverse @ Vector((p.x, centre_y + (p.y - centre_y) * (1 + amount * w), p.z))
        moved += 1
    mesh.update()
    return {'amount': amount, 'vertices_moved': moved}


def recede_chin(mesh, world, vertices, centre_y, z_mouth, z_chin, z_collar, depth, half_width=.020, fade_width=.034):
    """Move the lower face back, nothing at the mouth line growing to `depth` at the chin, full within half_width of
    the centre line and fading out by fade_width; under the chin it fades out toward the collar.

    In the drawing's profile (left.png) the face recedes in a straight line from the nose tip: the mouth 10 mm
    behind it, the chin 21 mm. The model's chin stayed 11 mm behind, which with the flattened lips read as a muzzle
    and puffy cheeks."""
    from mathutils import Vector
    inverse = world.inverted()
    moved = 0
    for index in vertices:
        p = world @ mesh.vertices[index].co
        if p.z >= z_mouth or p.x < -.01:
            continue
        t = float(smoothstep(z_mouth, z_chin, p.z)) if p.z >= z_chin else float(smoothstep(z_collar, z_chin, p.z))
        w = t * float(smoothstep(fade_width, half_width, abs(p.y - centre_y))) * float(smoothstep(-.01, .015, p.x))
        if w <= 0:
            continue
        mesh.vertices[index].co = inverse @ Vector((p.x - depth * w, p.y, p.z))
        moved += 1
    mesh.update()
    return {'depth_mm': round(depth * 1000, 1), 'vertices_moved': moved}


def smooth_lower_face(mesh, world, face_polygons, centre_y, z_centre, radius_y, radius_z, iterations=150):
    """Smooth the depth (x only) of the area between the nose, the cheeks and the chin into the surface its border
    defines, so no rounded muzzle or ring is left around the painted mouth. Full inside 70% of the ellipse, fading
    to nothing at its edge, front of the face only. The drawing's profile is a straight line from nose to chin."""
    from mathutils import Vector
    inverse = world.inverted()
    vertices = sorted({v for i in face_polygons for v in mesh.polygons[i].vertices})
    points = {v: world @ mesh.vertices[v].co for v in vertices}

    def weight(p):
        if p.x < .02:
            return 0.0
        return float(smoothstep(1.0, .7, math.hypot((p.y - centre_y) / radius_y, (p.z - z_centre) / radius_z)))

    weights = {v: weight(p) for v, p in points.items()}
    active = [v for v, w in weights.items() if w > 0]
    neighbours = {v: [] for v in active}
    for edge in mesh.edges:
        a, b = edge.vertices
        if a in neighbours and b in points:
            neighbours[a].append(b)
        if b in neighbours and a in points:
            neighbours[b].append(a)
    x = {v: p.x for v, p in points.items()}
    for _ in range(iterations):
        nxt = dict(x)
        for v in active:
            if neighbours[v]:
                nxt[v] = x[v] + (sum(x[o] for o in neighbours[v]) / len(neighbours[v]) - x[v]) * .6 * weights[v]
        x = nxt
    largest = 0.0
    for v in active:
        p = points[v]
        largest = max(largest, abs(x[v] - p.x))
        mesh.vertices[v].co = inverse @ Vector((x[v], p.y, p.z))
    mesh.update()
    return {'vertices_smoothed': len(active), 'largest_depth_change_mm': round(largest * 1000, 2)}


def shrink_nose(mesh, world, vertices, centre_y, z_centre, factor, radius_y=.014, radius_z=.016, x_base=.050):
    """Make the nose stand out less: its depth in front of x_base (the face beside it) times `factor`, in full near
    its middle and fading out over the ellipse (radius_y, radius_z). The drawing's nose is small; Tripo's sticks out
    11 mm and throws a dark blurred shadow under it."""
    from mathutils import Vector
    inverse = world.inverted()
    moved = 0
    for index in vertices:
        p = world @ mesh.vertices[index].co
        if p.x <= x_base:
            continue
        r = math.hypot((p.y - centre_y) / radius_y, (p.z - z_centre) / radius_z)
        w = float(smoothstep(1.0, .55, r))
        if w <= 0:
            continue
        mesh.vertices[index].co = inverse @ Vector((x_base + (p.x - x_base) * (1 - (1 - factor) * w), p.y, p.z))
        moved += 1
    mesh.update()
    return {'factor': factor, 'vertices_moved': moved}


def smooth_nose(mesh, world, face_polygons, centre_y, z_nose, half_width=.011, iterations=4):
    """Even out the depth (x only) of the nostril dimples, so they stop shading as a brown smudge. The nose's tip and
    bridge do not move: a first version smoothed them too and the nose all but vanished in profile."""
    from mathutils import Vector
    inverse = world.inverted()
    vertices = sorted({v for i in face_polygons for v in mesh.polygons[i].vertices})
    points = {v: world @ mesh.vertices[v].co for v in vertices}

    def weight(p):
        # Only the nostril dimples: either side of the centre line, at and under the nose line; the tip (above the
        # line, the most forward point) and the bridge keep their shape.
        if p.x < .02 or p.z > z_nose + .001:
            return 0.0
        d = abs(p.y - centre_y)
        return float(smoothstep(.002, .004, d) * smoothstep(half_width, half_width * .7, d) * smoothstep(.006, .003, z_nose - p.z))

    weights = {v: weight(p) for v, p in points.items()}
    active = [v for v, w in weights.items() if w > 0]
    neighbours = {v: [] for v in active}
    for edge in mesh.edges:
        a, b = edge.vertices
        if a in neighbours and b in points:
            neighbours[a].append(b)
        if b in neighbours and a in points:
            neighbours[b].append(a)
    x = {v: p.x for v, p in points.items()}
    for _ in range(iterations):
        nxt = dict(x)
        for v in active:
            if neighbours[v]:
                nxt[v] = x[v] + (sum(x[o] for o in neighbours[v]) / len(neighbours[v]) - x[v]) * .5 * weights[v]
        x = nxt
    for v in active:
        p = points[v]
        mesh.vertices[v].co = inverse @ Vector((x[v], p.y, p.z))
    mesh.update()
    return {'vertices_smoothed': len(active)}


def gather(mesh, world, uv, shape, polygons, texel_coverage, keep):
    """Texels (rows, cols) and their world points for the polygons whose centre passes keep(centre)."""
    height, width = shape
    positions = np.array([list(world @ v.co) for v in mesh.vertices], np.float32)
    rows, cols, points = [], [], []
    for index in polygons:
        polygon = mesh.polygons[index]
        if not keep(world @ polygon.center):
            continue
        coverage = texel_coverage(polygon, uv, width, height)
        if coverage is None:
            continue
        r, c, corners, weights = coverage
        loop_vertices = np.array([mesh.loops[li].vertex_index for li in polygon.loop_indices])
        rows.append(r)
        cols.append(c)
        points.append((positions[loop_vertices[corners]] * weights[:, :, None]).sum(axis=1))
    return np.concatenate(rows), np.concatenate(cols), np.concatenate(points)


def paint(mesh, world, uv, colour, normal, roughness, texel_coverage, face_polygons, pupils, nose_z, skin):
    """Brows, nose and cheeks in the drawing's style, placed from the painted pupils (world y, z)."""
    (y_right, z_right), (y_left, z_left) = pupils          # his right eye has the smaller y
    sp = y_left - y_right
    centre_y = (y_right + y_left) / 2
    eye_z = (z_right + z_left) / 2
    height, width = colour.shape[:2]
    rows, cols, points = gather(mesh, world, uv, (height, width), face_polygons, texel_coverage,
                                lambda c: c.x > 0 and abs(c.y - centre_y) < 1.3 * sp and eye_z - .75 * sp < c.z < eye_z + .62 * sp)
    y, z = points[:, 1], points[:, 2]
    current = colour[rows, cols, :3].copy()
    edge = .00025

    def inside(distance):
        return smoothstep(-edge, edge, distance)

    def over(paint_colour, alpha):
        nonlocal current
        current = current * (1 - alpha[:, None]) + paint_colour[None] * alpha[:, None]

    flat_zone = np.zeros(len(y), np.float32)
    # Brows: clear a band to skin (Tripo's painted brows and the drawing's projected ones), then draw.
    brow_band = np.zeros(len(y), np.float32)
    for pupil_y, pupil_z, outward in ((y_right, z_right, -1.0), (y_left, z_left, 1.0)):
        u = (y - pupil_y) * outward / sp                  # outward from the pupil, in sp
        band = smoothstep(-.4, -.3, u) * smoothstep(.62, .5, u) * smoothstep(.62, .5, np.abs((z - pupil_z) / sp - .36) + .4)
        brow_band = np.maximum(brow_band, band)
    over(skin, brow_band)
    flat_zone = np.maximum(flat_zone, brow_band)
    for pupil_y, pupil_z, outward in ((y_right, z_right, -1.0), (y_left, z_left, 1.0)):
        u = (y - pupil_y) * outward / sp                  # -0.22 at the inner end, +0.40 at the outer end
        s = np.clip((u + .22) / .62, 0, 1)                # 0 inner, 1 outer
        centre = pupil_z + sp * np.interp(s, (0, .2, .4, .6, .8, 1), (.40, .425, .43, .42, .39, .35))
        half = sp * .5 * np.interp(s, (0, .12, .5, .8, 1), (.09, .125, .13, .11, .06))
        cover = inside(half - np.abs(z - centre)) * inside((u + .22) * sp) * inside((.40 - u) * sp)
        over(BROW, cover)
    # Nose, as drawn, placed from the pupils (the drawing's: nostrils 0.49 sp below them and 0.20 sp apart, the
    # light tip 0.37 sp below, the bulb from 0.30 to 0.62 sp below): cleared to skin, a soft rounded bulb shade,
    # a light tip, two small dark arched nostrils, a faint shade under the bulb.
    nostril_z = eye_z - .49 * sp
    nose_zone = smoothstep(1.15, .85, np.hypot((y - centre_y) / (.30 * sp), (z - nostril_z - .03 * sp) / (.22 * sp)))
    over(skin, nose_zone)
    flat_zone = np.maximum(flat_zone, nose_zone)
    v = np.clip((eye_z - .28 * sp - z) / (.34 * sp), 0, 1)        # 0 at the top of the bulb, 1 at its bottom
    half_width = sp * (.07 + .12 * np.sqrt(v))                    # narrow at the top, round and full low down
    bottom = eye_z - .62 * sp + .09 * sp * np.clip(np.abs(y - centre_y) / (.19 * sp), 0, 1.2) ** 2
    soft = .022 * sp
    bulb = (smoothstep(-soft, soft, half_width - np.abs(y - centre_y)) * smoothstep(-soft, soft, z - bottom)
            * smoothstep(0, .3, v))
    over(NOSE_SHADE, .45 * bulb)
    tip = smoothstep(.05, .0, np.hypot((y - centre_y) / sp, (z - (eye_z - .37 * sp)) / (1.25 * sp)))
    over(NOSE_TIP, .6 * tip)
    for side in (-1.0, 1.0):
        nx = centre_y + side * .10 * sp
        u = (y - nx) / (.045 * sp)
        arc = nostril_z + .014 * sp - .024 * sp * u ** 2   # a small arch: ends down, as drawn
        stroke = inside(.0105 * sp - np.abs(z - arc)) * smoothstep(1.0, .7, np.abs(u))
        over(NOSTRIL, .9 * stroke)
    # Cheeks: a soft blush under each eye, and freckles.
    for pupil_y, pupil_z, outward in ((y_right, z_right, -1.0), (y_left, z_left, 1.0)):
        dy = (y - (pupil_y - outward * .02 * sp)) / (.22 * sp)
        dz = (z - (pupil_z - .36 * sp)) / (.10 * sp)
        over(BLUSH, .26 * smoothstep(1.0, .15, np.hypot(dy, dz)))
    rng = np.random.default_rng(7)
    freckles = []
    for pupil_y, pupil_z, outward in ((y_right, z_right, -1.0), (y_left, z_left, 1.0)):
        for _ in range(9):
            fu = rng.uniform(-.35, .08)                   # mostly toward the nose
            freckles.append((pupil_y + outward * fu * sp, pupil_z - rng.uniform(.22, .33) * sp))
    for _ in range(5):
        freckles.append((centre_y + rng.uniform(-.12, .12) * sp, eye_z - rng.uniform(.2, .27) * sp))
    for fy, fz in freckles:
        radius = rng.uniform(.006, .009) * sp
        over(FRECKLE, .55 * inside(radius - np.hypot(y - fy, z - fz)))
    colour[rows, cols, :3] = current
    flat = flat_zone[:, None]
    normal[rows, cols, :3] = normal[rows, cols, :3] * (1 - flat) + np.array([.5, .5, 1], np.float32) * flat
    return {'pupil_spacing_mm': round(sp * 1000, 1), 'texels': int(len(rows)), 'freckles': len(freckles)}
