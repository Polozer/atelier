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


# The drawing's mouth line: warm brown in the middle, darker at the ends (face-six-views.png, front view).
LINE_MIDDLE = np.array([.62, .38, .29], np.float32)
LINE_ENDS = np.array([.50, .30, .23], np.float32)
LINE_THICKNESS = .0012          # about two pixels of the drawing's line, in metres on the model
CLOSE = .0016                   # the slit's lip edges within this of the seam close onto it
CLOSE_CORNERS = .0024           # and this much further at the corners, where Tripo cut small pits
CORNER_PASSES = 25              # 3D smoothing passes that unfold the corners


def seam(mesh, world, face_polygons, centre_y, half_width):
    """The lips' seam: the face's vertices sunk at least 2 mm behind the lips around them, fitted with a quadratic
    z(y) across the mouth. Returns (coefficients, y_min, y_max)."""
    vertices = sorted({v for i in face_polygons for v in mesh.polygons[i].vertices})
    points = np.array([list(world @ mesh.vertices[v].co) for v in vertices])
    near = (points[:, 0] > 0) & (np.abs(points[:, 1] - centre_y) < 1.5 * half_width) & (points[:, 2] > .326) & (points[:, 2] < .346)
    points = points[near]
    sunk = []
    for p in points:
        around = points[(np.abs(points[:, 1] - p[1]) < .0015) & (np.abs(points[:, 2] - p[2]) < .006)]
        if around[:, 0].max() - p[0] > .002:
            sunk.append(p)
    sunk = np.array(sunk)
    if len(sunk) < 6:
        raise RuntimeError(f'only {len(sunk)} seam vertices found')
    coefficients = np.polyfit(sunk[:, 1], sunk[:, 2], 2)
    return coefficients, float(sunk[:, 1].min()), float(sunk[:, 1].max())


def paint(mesh, world, uv, colour, roughness, normal, texel_coverage, face_polygons, centre_y, half_width, skin, lips):
    """One mouth: clear the drawn and Tripo-painted mouths to skin, draw a single line where the seam was
    (lips = seam(), measured before flatten())."""
    coefficients, y_min, y_max = lips
    height, width = colour.shape[:2]
    positions = np.array([list(world @ v.co) for v in mesh.vertices], np.float32)
    rows, cols, points = [], [], []
    for index in face_polygons:
        polygon = mesh.polygons[index]
        centre = world @ polygon.center
        if centre.x < 0 or abs(centre.y - centre_y) > 1.6 * half_width or not (.322 < centre.z < .352):
            continue
        coverage = texel_coverage(polygon, uv, width, height)
        if coverage is None:
            continue
        r, c, corners, weights = coverage
        loop_vertices = np.array([mesh.loops[li].vertex_index for li in polygon.loop_indices])
        rows.append(r)
        cols.append(c)
        points.append((positions[loop_vertices[corners]] * weights[:, :, None]).sum(axis=1))
    rows, cols, points = np.concatenate(rows), np.concatenate(cols), np.concatenate(points)
    y, z = points[:, 1], points[:, 2]
    seam_z = np.polyval(coefficients, np.clip(y, y_min, y_max))
    middle = (y_min + y_max) / 2
    half = (y_max - y_min) / 2
    u = (y - middle) / half                                   # -1 and 1 at the corners

    def ramp(a, b, x):
        t = np.clip((x - a) / (b - a), 0, 1)
        return t * t * (3 - 2 * t)

    # Clear: the whole mouth area becomes skin, fading out gently over 8 mm so no edge shows.
    zone = ramp(1.6, 1.15, np.abs(u)) * ramp(.014, .006, np.abs(z - seam_z))
    current = colour[rows, cols, :3]
    current = current * (1 - zone[:, None]) + skin[None] * zone[:, None]
    # The line: along the seam, tapering over the last tenth, darker toward the ends.
    taper = ramp(1.0, .9, np.abs(u))
    half_thickness = LINE_THICKNESS / 2 * (.35 + .65 * taper)
    edge = .00025
    line = ramp(-edge, edge, half_thickness - np.abs(z - seam_z)) * ramp(1.03, .97, np.abs(u))
    tone = ramp(.7, 1.0, np.abs(u))[:, None]
    ink = LINE_MIDDLE[None] * (1 - tone) + LINE_ENDS[None] * tone
    current = current * (1 - line[:, None]) + ink * line[:, None]
    colour[rows, cols, :3] = current
    flat = zone[:, None]
    normal[rows, cols, :3] = normal[rows, cols, :3] * (1 - flat) + np.array([.5, .5, 1], np.float32) * flat
    skin_roughness = float(np.median(roughness[rows, cols, 0]))
    roughness[rows, cols, :3] = roughness[rows, cols, :3] * (1 - flat) + skin_roughness * flat
    return {'seam_quadratic': [round(float(c), 4) for c in coefficients],
            'seam_y_mm': [round(y_min * 1000, 1), round(y_max * 1000, 1)],
            'seam_middle_z_mm': round(float(np.polyval(coefficients, middle)) * 1000, 1),
            'texels_cleared': int((zone > 0).sum()), 'texels_inked': int((line > .5).sum())}


def flatten(mesh, world, face_polygons, lips, iterations=60):
    """Smooth the lips' relief away so the painted line is the only mouth.

    Tripo sculpted lips with a slit about 2 mm tall and 5 mm deep; lit, its two edges and its inside read as a
    second, parted mouth. Only depth (x) changes: the slit's sunk vertices first come forward to the lips around
    them, then Laplacian passes on x even out the lips, fully inside the mouth area and fading to nothing at its
    edge, which stays fixed. Last, the slit's lip edges (within CLOSE of the seam) close onto the seam line, so its
    walls vanish; around each corner a few 3D Laplacian passes unfold what Tripo's corner pits leave. The line is
    painted from the seam measured before all this, so it stays where the seam was."""
    from mathutils import Vector
    coefficients, y_min, y_max = lips
    middle, half = (y_min + y_max) / 2, (y_max - y_min) / 2
    inverse = world.inverted()
    vertices = sorted({v for i in face_polygons for v in mesh.polygons[i].vertices})
    points = {v: world @ mesh.vertices[v].co for v in vertices}

    def weight(p):
        u = abs(p.y - middle) / half
        dz = abs(p.z - float(np.polyval(coefficients, min(max(p.y, y_min), y_max))))
        return (smoothstep(1.35, 1.1, u) * smoothstep(.0075, .0045, dz)) if p.x > 0 else 0.0

    weights = {v: weight(p) for v, p in points.items()}
    active = [v for v, w in weights.items() if w > 0]
    neighbours = {v: [] for v in active}
    for edge in mesh.edges:
        a, b = edge.vertices
        if a in neighbours and b in points:
            neighbours[a].append(b)
        if b in neighbours and a in points:
            neighbours[b].append(a)
    x = {v: points[v].x for v in points}
    before = dict(x)
    # The slit comes forward: each sunk vertex to the front-most lip within 6 mm above or below, 1.5 mm across.
    for v in active:
        p = points[v]
        around = [x[o] for o, q in points.items() if abs(q.y - p.y) < .0015 and abs(q.z - p.z) < .006]
        front = max(around)
        if front - x[v] > .0015:
            x[v] = x[v] + (front - .0003 - x[v]) * weights[v]
    for _ in range(iterations):
        nxt = dict(x)
        for v in active:
            if neighbours[v]:
                mean = sum(x[o] for o in neighbours[v]) / len(neighbours[v])
                nxt[v] = x[v] + (mean - x[v]) * .5 * weights[v]
        x = nxt
    # The slit closes: its lips' edges (within CLOSE of the seam) meet on the seam line, so its walls vanish.
    closed = 0
    for v in active:
        p = points[v]
        seam_z = float(np.polyval(coefficients, min(max(p.y, y_min), y_max)))
        z = p.z
        u = abs(p.y - middle) / half
        reach = CLOSE + CLOSE_CORNERS * smoothstep(.7, 1.0, u)    # the corners' pits are taller than the middle
        if abs(p.z - seam_z) < reach:
            z = p.z + (seam_z - p.z) * weights[v]
            closed += 1
        mesh.vertices[v].co = inverse @ Vector((x[v], p.y, z))
    mesh.update()
    # The corners: Tripo's pits leave folded triangles between the lips and the closed seam. A few 3D Laplacian
    # passes around each corner (and only there) unfold them.
    corner = {}
    for v in active:
        p = world @ mesh.vertices[v].co
        u = abs(p.y - middle) / half
        dz = abs(p.z - float(np.polyval(coefficients, min(max(p.y, y_min), y_max))))
        w = smoothstep(.55, .75, u) * smoothstep(1.35, 1.15, u) * smoothstep(.006, .003, dz)
        if w > 0:
            corner[v] = w
    for _ in range(CORNER_PASSES):
        current = {v: world @ mesh.vertices[v].co for v in points}
        for v, w in corner.items():
            if neighbours[v]:
                mean = sum((current[o] for o in neighbours[v]), current[v] * 0) / len(neighbours[v])
                target = current[v].lerp(mean, .5 * w)
                mesh.vertices[v].co = inverse @ target
    mesh.update()
    moves = [abs(x[v] - before[v]) for v in active]
    return {'vertices_flattened': len(active), 'vertices_closed_onto_seam': closed,
            'largest_depth_change_mm': round(max(moves) * 1000, 2)}


def refresh_normals(mesh, before):
    """Re-derive shading normals where the geometry moved.

    Tripo's FBX carries custom split normals: the sculpt's shading, frozen. After the eyes and mouth are reshaped,
    those normals still shade the old lips and lids (flaps at the mouth corners, a lip where the surface is flat).
    Every vertex that moved (compared with `before`, a list of coordinates), and its neighbours, takes the normal of
    the new surface; the rest of the mesh keeps Tripo's."""
    moved = {i for i, co in enumerate(before) if (mesh.vertices[i].co - co).length > 1e-7}
    ring = set(moved)
    for edge in mesh.edges:
        a, b = edge.vertices
        if a in moved or b in moved:
            ring.update((a, b))
    mesh.update()
    normals = [loop.normal.copy() for loop in mesh.loops]
    for loop in mesh.loops:
        if loop.vertex_index in ring:
            normals[loop.index] = mesh.vertices[loop.vertex_index].normal.copy()
    mesh.normals_split_custom_set(normals)
    mesh.update()
    return {'vertices_moved': len(moved), 'vertices_reshaded': len(ring)}
