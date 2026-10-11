"""Clean cel eyes and brows for a Tripo head, painted into its textures and fitted to its sculpted eye sockets.

Used by cleanup_face_hair.py (step 5). Projecting a drawing's eyes onto a Tripo head does not work: the drawn eye is a
different size and shape from the sculpted socket, so skin shows inside the socket, the sculpted lid ridge cuts the
iris, and Tripo's own eye paint, gloss and normal detail show through at the socket walls. Instead:

1. Tripo builds the head from separate pieces: the hair cap, the face (with a hole at each eye), one eyeball behind
   each hole, a brow strip above each eye and a cornea disc on each eyeball (head_parts). The upper lid and the
   corners of each eye are the rim of its hole seen from the front, fitted with smooth quartic curves (outline).
   The lower lid is drawn LOWER_LID eye widths below the corners, the drawing's proportion, but never below where
   the eyeball is still visible from the front (visible_outline): the eyeball bulges past the mesh's lower lid.
2. On the eyeball and the rim, an eye is drawn in the face sheet's style, analytically in front-view coordinates (so edges
   are as sharp as the texture allows): white with a shadow under the lid, an olive-to-yellow iris with a dark rim,
   a pupil, two highlights, a thick upper lash line ending in an outer wing, a crease above it, a short lower line.
3. Around the eyes and over the brow band, anything that is not skin (Tripo's eye paint, the projected drawing's
   larger eyes and brows) becomes skin. The brows are their own strips standing off the forehead; they take the
   drawing's brow colour.
4. In that whole zone the normal map goes flat, roughness takes the skin's value and metallic goes to zero, so no
   sculpted-eye detail or gloss shows through the paint.

Colours are the face sheet's, as sampled from `face-six-views.png` (sRGB values, as Blender stores them).
"""
import numpy as np

# The face sheet's palette.
LASH = np.array([.07, .05, .04], np.float32)
BROW = np.array([.24, .16, .11], np.float32)
CREASE = np.array([.74, .47, .37], np.float32)
LOWER_LINE = np.array([.72, .46, .36], np.float32)
SCLERA = np.array([.95, .94, .94], np.float32)
SCLERA_SHADOW = np.array([.78, .74, .77], np.float32)
IRIS_TOP = np.array([.34, .28, .06], np.float32)
IRIS_BOTTOM = np.array([.88, .74, .13], np.float32)
IRIS_RIM = np.array([.22, .17, .04], np.float32)
PUPIL = np.array([.08, .05, .03], np.float32)
HIGHLIGHT = np.array([1., 1., 1.], np.float32)

CELL = 0.0004            # front-view grid for reading the openings (0.4 mm)
LOWER_LID = 0.23         # the drawn lower lid's depth below the corners, in eye widths (the drawing's)
EDGE = 0.0004            # antialiasing width: one texel, measured by paint() from the texture's density


def smoothstep(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0, 1)
    return t * t * (3 - 2 * t)


def inside(distance):
    """Coverage of a shape from a signed distance (positive inside), antialiased over EDGE."""
    return smoothstep(-EDGE, EDGE, distance)


def over(colour, paint, alpha):
    a = alpha[:, None]
    return colour * (1 - a) + paint * a


def skinness(rgb):
    """1 for skin-coloured texels, 0 for lash, brow, eye white, iris and grey."""
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    luminance = .299 * r + .587 * g + .114 * b
    return np.clip((r - b - .16) / .1, 0, 1) * np.clip((luminance - .38) / .1, 0, 1) * np.clip((r - g - .08) / .08, 0, 1)


def head_parts(mesh, world):
    """Polygon indices of the hair cap, the face and the two eyeballs, from the mesh's connected pieces."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    piece = [-1] * len(bm.faces)
    count = 0
    for face in bm.faces:
        if piece[face.index] >= 0:
            continue
        piece[face.index] = count
        stack = [face]
        while stack:
            current = stack.pop()
            for edge in current.edges:
                for other in edge.link_faces:
                    if piece[other.index] < 0:
                        piece[other.index] = count
                        stack.append(other)
        count += 1
    bm.free()
    piece = np.array(piece)
    centres = np.array([list(world @ p.center) for p in mesh.polygons], np.float32)
    sizes = np.bincount(piece)
    # The hair: the piece holding the topmost polygon. The face: the piece holding the frontmost head polygon.
    hair = piece[np.argmax(centres[:, 2])]
    head = centres[:, 2] > .3
    face = piece[np.argmax(np.where(head & (piece != hair), centres[:, 0], -1e9))]
    eyeballs, small = [], []
    for index in range(count):
        if index in (hair, face):
            continue
        c = centres[piece == index]
        if c[:, 0].min() < 0 or not (.34 < c[:, 2].mean() < .43) or np.abs(c[:, 1]).max() > .08:
            continue
        (eyeballs if sizes[index] >= 40 else small).append(index)
    if len(eyeballs) != 2:
        raise RuntimeError(f'expected two eyeball pieces, found {len(eyeballs)}')
    eyeballs.sort(key=lambda i: centres[piece == i][:, 1].mean())          # his right (-Y) first
    eyeball_sets = [set(np.nonzero(piece == e)[0].tolist()) for e in eyeballs]
    brows, discs = [], []
    for index in small:
        c = centres[piece == index]
        for k, e in enumerate(eyeballs):
            ec = centres[piece == e]
            if ec[:, 1].min() - .004 < c[:, 1].mean() < ec[:, 1].max() + .004:
                if c[:, 2].min() > ec[:, 2].max():            # above the eyeball: the brow strip
                    brows.append(index)
                else:                                        # on the eyeball: Tripo's cornea highlight disc
                    discs.append(index)
    return {'hair': set(np.nonzero(piece == hair)[0].tolist()), 'face': set(np.nonzero(piece == face)[0].tolist()),
            'eyeball': eyeball_sets, 'eyeballs': set().union(*eyeball_sets),
            'brows': set(np.nonzero(np.isin(piece, brows))[0].tolist()),
            'discs': set(np.nonzero(np.isin(piece, discs))[0].tolist())}


def hole_rim(mesh, world, face_polygons, eyeball_polygons, with_depth=False):
    """The face's boundary edges around one eyeball, as front-view points (y, z), densely sampled."""
    centres = np.array([list(world @ mesh.polygons[i].center) for i in eyeball_polygons], np.float32)
    y0, y1 = centres[:, 1].min() - .006, centres[:, 1].max() + .006
    z0, z1 = centres[:, 2].min() - .006, centres[:, 2].max() + .006
    edge_faces = {}
    for index in face_polygons:
        for key in mesh.polygons[index].edge_keys:
            edge_faces[key] = edge_faces.get(key, 0) + 1
    points = []
    for (a, b), n in edge_faces.items():
        if n != 1:
            continue
        pa, pb = world @ mesh.vertices[a].co, world @ mesh.vertices[b].co
        mid = (pa + pb) / 2
        if y0 < mid.y < y1 and z0 < mid.z < z1 and mid.x > 0:
            for t in np.linspace(0, 1, 6):
                p = pa.lerp(pb, t)
                points.append((p.y, p.z, p.x) if with_depth else (p.y, p.z))
    return np.array(points)


def outline(rim):
    """Top and bottom edges of the rim per CELL column, then smooth quartic curves through them: the opening."""
    y = rim[:, 0]
    columns = np.arange(y.min(), y.max() + CELL, CELL)
    ys, tops, bottoms = [], [], []
    for c in columns:
        near = np.abs(y - c) < CELL
        if near.sum() < 2:
            continue
        ys.append(c)
        tops.append(rim[near, 1].max())
        bottoms.append(rim[near, 1].min())
    ys, tops, bottoms = np.array(ys), np.array(tops), np.array(bottoms)
    # Quartic fits in the normalised coordinate, weighted toward the middle where the rim is well sampled.
    u = (ys - ys[0]) / (ys[-1] - ys[0]) * 2 - 1
    weight = 1.2 - u ** 2
    top_fit = np.polyval(np.polyfit(u, tops, 4, w=weight), u)
    bottom_fit = np.polyval(np.polyfit(u, bottoms, 4, w=weight), u)
    # The corners close: the curves meet at both ends.
    mid = (top_fit + bottom_fit) / 2
    gap = np.maximum(top_fit - bottom_fit, 0) * np.clip((1 - np.abs(u)) / .08, 0, 1) ** .5
    tops, bottoms = mid + gap / 2, mid - gap / 2
    return {'y': ys, 'top': tops, 'bottom': bottoms, 'cells': int(len(ys)),
            'width': float(ys[-1] - ys[0]), 'height': float((tops - bottoms).max())}


class Eye:
    """One eye in front-view coordinates. s runs from the inner corner (0) to the outer corner (1)."""

    def __init__(self, shape, midline_y):
        self.shape = shape
        ys = shape['y']
        inner_first = abs(ys[0] - midline_y) < abs(ys[-1] - midline_y)
        self.y_inner, self.y_outer = (ys[0], ys[-1]) if inner_first else (ys[-1], ys[0])
        self.height = shape['height']

    def s(self, y):
        return (y - self.y_inner) / (self.y_outer - self.y_inner)

    def edges(self, y):
        top = np.interp(y, self.shape['y'], self.shape['top'], left=np.nan, right=np.nan)
        bottom = np.interp(y, self.shape['y'], self.shape['bottom'], left=np.nan, right=np.nan)
        return top, bottom

    def paint(self, colour, y, z, on_eyeball, x=None):
        """Draw the eye over colour (n, 3) at front-view points (y, z); on_eyeball marks the eyeball's texels, which
        take eye paint everywhere (above the opening they sit under the lid in shadow)."""
        H = self.height
        s = self.s(y)
        top, bottom = self.edges(y)
        top_c = np.where(np.isnan(top), np.nanmax(self.shape['top']), top)
        bottom_c = np.where(np.isnan(bottom), np.nanmin(self.shape['bottom']), bottom)
        lower_lid = inside(z - bottom_c) * inside(np.minimum(s, 1 - s) * abs(self.y_outer - self.y_inner))
        in_opening = on_eyeball * lower_lid                  # the eye paint: on the eyeball, above the drawn lower lid
        colour = over(colour, self.skin[None], on_eyeball * (1 - lower_lid) * (z < top_c))   # the drawn lower lid
        # White, darker under the lid.
        shade = smoothstep(.0, .32 * H, top_c - z)
        white = SCLERA_SHADOW[None] * (1 - shade[:, None]) + SCLERA[None] * shade[:, None]
        colour = over(colour, white, in_opening)
        # Iris: a slightly tall ellipse resting just above the lower lid, a little toward the nose.
        sc = 0.44
        yc = self.y_inner + sc * (self.y_outer - self.y_inner)
        top_mid, bottom_mid = self.edges(np.array([yc]))
        Rz = .54 * float(top_mid[0] - bottom_mid[0])
        Ry = .86 * Rz
        zc = float(bottom_mid[0]) + .96 * Rz
        r = np.hypot((y - yc) / Ry, (z - zc) / Rz)
        iris_cover = inside((1 - r) * Rz) * in_opening
        t = np.clip((zc + Rz - z) / (2 * Rz), 0, 1)          # 0 at the iris top, 1 at its bottom
        gradient = smoothstep(.45, .66, t)[:, None]
        iris = IRIS_TOP[None] * (1 - gradient) + IRIS_BOTTOM[None] * gradient
        under_lash = smoothstep(.12, 0, (top_c - z) / H)[:, None] * .6
        iris = iris * (1 - under_lash) + IRIS_RIM[None] * under_lash
        rim = inside((r - .86) * Rz)[:, None]
        iris = iris * (1 - rim) + IRIS_RIM[None] * rim
        colour = over(colour, iris, iris_cover)
        pupil = inside((.40 - np.hypot((y - yc) / (.80 * Ry), (z - zc - .04 * Rz) / Rz)) * Rz) * in_opening
        colour = over(colour, PUPIL[None], pupil)
        # Highlights: one large at the upper right of the pupil (as drawn), one small at the lower left.
        for dy, dz, radius in ((.34, .36, .20), (-.34, -.30, .09)):
            spot = inside((radius - np.hypot((y - yc - dy * Ry) / Ry, (z - zc - dz * Rz) / Rz)) * Rz) * in_opening
            colour = over(colour, HIGHLIGHT[None], spot)
        # Upper lash line: down from the top edge, thicker toward the outer corner, with an outer wing.
        thickness = H * (.11 + .09 * np.clip(s, 0, 1))
        upper = np.where(on_eyeball, 1.0, inside((top_c + .05 * H) - z))
        band = np.where(np.isnan(top) & ~on_eyeball, 0.0,
                        np.minimum(inside(z - (top_c - thickness)), upper)
                        * np.where(on_eyeball, 1.0, smoothstep(-.02, .06, s) * smoothstep(1.03, .98, s)))
        colour = over(colour, LASH[None], band)
        top_outer = float(self.edges(np.array([self.y_outer - .03 * (self.y_outer - self.y_inner)]))[0][0])
        wing_s = np.clip((s - .95) / .17, 0, 1)
        wing_centre = top_outer - .06 * H + wing_s * .18 * H
        wing_half = .09 * H * (1 - wing_s)
        wing = inside(np.minimum(wing_half - np.abs(z - wing_centre), .001)) * (s > .95) * (s < 1.12)
        if x is not None:                                    # not on the side of the head behind the corner
            wing = wing * smoothstep(self.corner_x - .006, self.corner_x - .003, x)
        colour = over(colour, LASH[None], wing)
        # Crease above the lid and a short soft line under the outer half.
        crease_z = top_c + .26 * H
        crease = np.where(np.isnan(top), 0.0, inside(.022 * H - np.abs(z - crease_z))) * smoothstep(.1, .3, s) * smoothstep(1.0, .85, s)
        colour = over(colour, CREASE[None], .45 * crease * (1 - on_eyeball))
        lower = inside(.03 * H - np.abs(z - bottom_c)) * smoothstep(.3, .55, s) * smoothstep(1.0, .88, s)
        colour = over(colour, LOWER_LINE[None], .6 * lower)
        return colour, np.maximum.reduce([in_opening, band, wing])

    def brow(self, colour, y, z):
        """A tapered brow above the eye, from just past the inner corner to beyond the outer one."""
        H = self.height
        s = self.s(y)
        top_inner = float(self.edges(np.array([self.y_inner + .05 * (self.y_outer - self.y_inner)]))[0][0])
        top_outer = float(self.edges(np.array([self.y_outer - .05 * (self.y_outer - self.y_inner)]))[0][0])
        base = top_inner + (top_outer - top_inner) * np.clip(s, 0, 1)
        arch = .14 * H * np.sin(np.pi * np.clip((s + .1) / 1.25, 0, 1))
        droop = .30 * H * np.clip((s - .85) / .3, 0, 1) ** 2
        centre = base + .70 * H + arch - droop
        half = .20 * H * (1 - .75 * np.clip((s + .08) / 1.26, 0, 1))
        cover = inside(np.minimum(half - np.abs(z - centre), .001)) * smoothstep(-.12, -.06, s) * smoothstep(1.2, 1.12, s)
        return over(colour, BROW[None], cover), cover

    def zone(self, y, z, margin):
        """1 within margin of the eye and its brow, fading to 0 over another margin."""
        H = self.height
        lo_y, hi_y = sorted((self.y_inner, self.y_outer))
        extend = .25 * abs(self.y_outer - self.y_inner)
        lo_y, hi_y = lo_y - extend, hi_y + extend
        bottom = float(np.nanmin(self.shape['bottom'])) - margin
        top = float(np.nanmax(self.shape['top'])) + 1.15 * H
        dy = np.maximum(lo_y - y, y - hi_y)
        dz = np.maximum(bottom - z, z - top)
        outside = np.maximum(dy, dz)
        return smoothstep(margin, 0, outside)


def paint(mesh, world, uv, colour, roughness, metallic, normal, texel_coverage, parts):
    """Paint both eyes and brows into the texture arrays in place, from the head's pieces (head_parts)."""
    global EDGE
    height, width = colour.shape[:2]
    positions = np.array([list(world @ v.co) for v in mesh.vertices], np.float32)
    shapes = [outline(hole_rim(mesh, world, parts['face'], eyeball)) for eyeball in parts['eyeball']]
    midline = (np.mean(shapes[0]['y']) + np.mean(shapes[1]['y'])) / 2
    eyes = [Eye(shape, midline) for shape in shapes]
    lo_y = min(e.shape['y'].min() for e in eyes) - .02
    hi_y = max(e.shape['y'].max() for e in eyes) + .02
    lo_z = min(e.shape['bottom'].min() for e in eyes) - .01
    hi_z = max(e.shape['top'].max() for e in eyes) + 1.5 * max(e.height for e in eyes)
    texels, densities = [], []
    for index in sorted(parts['face'] | parts['eyeballs'] | parts['brows']):
        polygon = mesh.polygons[index]
        centre = world @ polygon.center
        if not (lo_y < centre.y < hi_y and lo_z < centre.z < hi_z) or centre.x < 0:
            continue
        coverage = texel_coverage(polygon, uv, width, height)
        if coverage is None:
            continue
        rows, cols, corners, weights = coverage
        loop_vertices = np.array([mesh.loops[li].vertex_index for li in polygon.loop_indices])
        points = (positions[loop_vertices[corners]] * weights[:, :, None]).sum(axis=1)
        which = -2 if index in parts['brows'] else next((k for k, eyeball in enumerate(parts['eyeball']) if index in eyeball), -1)
        texels.append((rows, cols, points, np.full(len(rows), which)))
        densities.append((polygon.area * world.to_scale()[0] ** 2, len(rows), index in parts['eyeballs']))
    rows = np.concatenate([t[0] for t in texels])
    cols = np.concatenate([t[1] for t in texels])
    points = np.concatenate([t[2] for t in texels])
    eyeball_of = np.concatenate([t[3] for t in texels])
    on_eyeball = eyeball_of >= 0
    on_brow = eyeball_of == -2
    densities = np.array(densities, np.float64)
    sizes = [np.sqrt(densities[m, 0].sum() / densities[m, 1].sum()) for m in (densities[:, 2] == 0, densities[:, 2] == 1)]
    EDGE = float(max(sizes))                             # world size of one texel: the coarser of face and eyeball

    # The lower lid is drawn, not taken from the mesh: Tripo's eyeball bulges past the lower lid, so its white would
    # show far below the drawing's lower lid. The lid line runs LOWER_LID of the eye's width below the line through
    # the corners (the drawing's proportion), never below the eyeball's visible edge; under it the eyeball is skin.
    for k, eye in enumerate(eyes):
        visible = visible_outline(points, eyeball_of, k, eye.shape)
        ys = eye.shape['y']
        s_ = eye.s(ys)
        width = abs(eye.y_outer - eye.y_inner)
        corner_inner = float(eye.edges(np.array([eye.y_inner]))[0][0])
        corner_outer = float(eye.edges(np.array([eye.y_outer]))[0][0])
        line = corner_inner + (corner_outer - corner_inner) * np.clip(s_, 0, 1)
        designed = line - LOWER_LID * width * np.sin(np.pi * np.clip(s_, 0, 1)) ** .9
        floor = np.interp(ys, visible['y'], visible['bottom'], left=-1, right=-1)
        eye.shape = dict(eye.shape, bottom=np.maximum(designed, floor))
        eye.height = float((eye.shape['top'] - eye.shape['bottom']).max())

    y, z = points[:, 1], points[:, 2]
    current = colour[rows, cols, :3].copy()
    skin_near = current[(skinness(current) > .9) & ~on_eyeball]
    skin = np.median(skin_near, axis=0)
    margin = .003
    zone = np.maximum.reduce([eye.zone(y, z, margin) for eye in eyes])
    zone = np.maximum(zone, (on_eyeball | on_brow).astype(np.float32))
    clean = zone * ~(on_eyeball | on_brow)          # all of it: Tripo's eye paint and the drawing's line art go
    current = over(current, skin[None], clean)
    for eye in eyes:
        eye.skin = skin
    current[on_brow] = BROW                       # Tripo's brow strips, in the drawing's brow colour
    for k, eye in enumerate(eyes):
        rim = hole_rim(mesh, world, parts['face'], parts['eyeball'][k], with_depth=True)
        outer = np.argmax(np.abs(rim[:, 0] - midline))
        eye.corner_x = float(rim[outer, 2])
        current, _ = eye.paint(current, y, z, eyeball_of == k, points[:, 0])
    colour[rows, cols, :3] = current
    flat = zone[:, None]
    normal[rows, cols, :3] = normal[rows, cols, :3] * (1 - flat) + np.array([.5, .5, 1], np.float32) * flat
    skin_roughness = float(np.median(roughness[rows, cols, 0][~(on_eyeball | on_brow)]))
    roughness[rows, cols, :3] = roughness[rows, cols, :3] * (1 - flat) + skin_roughness * flat
    metallic[rows, cols, :3] = metallic[rows, cols, :3] * (1 - flat)
    return {'eyes': [{'inner_y': round(float(e.y_inner), 4), 'outer_y': round(float(e.y_outer), 4),
                      'width': round(e.shape['width'], 4), 'height': round(e.height, 4), 'rim_columns': e.shape['cells']}
                     for e in eyes],
            'texel_size_mm': {'face': round(sizes[0] * 1000, 3), 'eyeball': round(sizes[1] * 1000, 3)}, 'texels_in_zone': int((zone > 0).sum()),
            'skin_colour': [round(float(c), 3) for c in skin], 'skin_roughness': round(skin_roughness, 3)}


def visible_outline(points, eyeball_of, k, base_shape):
    """The opening as seen from the front: cells of a 0.3 mm front-view grid where eyeball k is the frontmost
    surface, then its top and bottom per column fitted like outline(). The eyeball bulges in front of the lower lid,
    so this reaches lower than the face's hole rim."""
    cell = .0003
    y0, y1 = base_shape['y'].min() - .004, base_shape['y'].max() + .004
    z0, z1 = base_shape['bottom'].min() - .008, base_shape['top'].max() + .004
    columns, rows = int((y1 - y0) / cell), int((z1 - z0) / cell)
    col = ((points[:, 1] - y0) / cell).astype(int)
    row = ((z1 - points[:, 2]) / cell).astype(int)
    keep = (col >= 0) & (col < columns) & (row >= 0) & (row < rows)
    flat = row[keep] * columns + col[keep]
    depth = points[keep, 0]
    order = np.lexsort((-depth, flat))
    first = np.r_[True, flat[order][1:] != flat[order][:-1]]
    owner = np.full(rows * columns, -9)
    owner[flat[order][first]] = eyeball_of[keep][order][first]
    mask = (owner == k).reshape(rows, columns)
    known = (owner != -9).reshape(rows, columns)
    # Fill empty cells from their neighbours (the texel grid is sparser than the cells in places).
    padded = np.pad(mask, 1)
    mask = mask | (~known & (padded[:-2, 1:-1] & padded[2:, 1:-1] | padded[1:-1, :-2] & padded[1:-1, 2:]))
    ys, tops, bottoms = [], [], []
    for c in range(columns):
        r = np.nonzero(mask[:, c])[0]
        if len(r) < 3:
            continue
        ys.append(y0 + (c + .5) * cell)
        tops.append(z1 - r.min() * cell)
        bottoms.append(z1 - (r.max() + 1) * cell)
    rim = np.array([[y, t] for y, t in zip(ys, tops)] + [[y, b] for y, b in zip(ys, bottoms)])
    return outline(rim)


def tilt(mesh, world, parts, degrees, inner_radius=.019, outer_radius=.026):
    """Raise each eye's outer corner: rotate the eye region about the front-view axis through the eye's centre.

    Tripo's sockets slope down toward the outside (outer corner 0.22 eye widths below the inner one, against 0.07 in
    the drawing), which reads as sad. Each eyeball turns rigidly by `degrees`; the face and the brow strip turn with it
    up to inner_radius from the eye's centre (front view), fading to nothing at outer_radius, only on the front of the
    head. Vertices keep their depth (x). Run after painting: the paint turns with the surface."""
    import math
    from mathutils import Vector
    inverse = world.inverted()
    shapes = [outline(hole_rim(mesh, world, parts['face'], eyeball)) for eyeball in parts['eyeball']]
    midline = (np.mean(shapes[0]['y']) + np.mean(shapes[1]['y'])) / 2
    face_vertices = {v for i in parts['face'] for v in mesh.polygons[i].vertices}
    brow_vertices = {v for i in parts['brows'] for v in mesh.polygons[i].vertices}
    record = []
    moved = {}
    for shape, eyeball in zip(shapes, parts['eyeball']):
        eye = Eye(shape, midline)
        top, bottom = eye.edges(np.array([eye.y_inner, eye.y_outer]))
        pivot_y = (eye.y_inner + eye.y_outer) / 2
        pivot_z = float(np.mean([top, bottom]))
        outward = np.sign(eye.y_outer - eye.y_inner)            # -1 for his right eye, +1 for his left
        angle = math.radians(degrees) * outward                 # outer corner up
        c, s = math.cos(angle), math.sin(angle)
        eyeball_vertices = {v for i in eyeball for v in mesh.polygons[i].vertices}
        for index in eyeball_vertices | face_vertices | brow_vertices:
            point = world @ mesh.vertices[index].co
            dy, dz = point.y - pivot_y, point.z - pivot_z
            r = math.hypot(dy, dz)
            if index in eyeball_vertices:
                weight = 1.0
            else:
                if r > outer_radius or point.x < -.01:
                    continue
                weight = float(smoothstep(outer_radius, inner_radius, r)) * float(smoothstep(-.01, .01, point.x))
            if weight <= 0:
                continue
            a = angle * weight
            ca, sa = math.cos(a), math.sin(a)
            target = Vector((point.x, pivot_y + dy * ca - dz * sa, pivot_z + dy * sa + dz * ca))
            moved[index] = inverse @ target
        corner = Vector((0, eye.y_outer - pivot_y, float(top[1]) - pivot_z))
        record.append({'pivot': [round(pivot_y, 4), round(pivot_z, 4)], 'degrees': round(math.degrees(angle), 2),
                       'outer_corner_rise_mm': round((corner.y * s + corner.z * c - corner.z) * 1000, 2)})
    for index, co in moved.items():
        mesh.vertices[index].co = co
    mesh.update()
    return {'eyes': record, 'vertices_moved': len(moved)}


def lift(mesh, world, parts, fraction):
    """Open each eye like the drawing's: lift its middle by `fraction` of its width, corners pinned.

    In the drawing the corners sit 42% of the opening's height above the lower lid; on Tripo's sockets 63%, so the
    upper lid hangs low and the lower lid sags, which reads as tired and sad. Raising the middle of the eye (lower
    lid, eyeball, upper lid and brow together) by about 0.11 of its width puts the corners back at 42%. The lift is
    sin(pi s) across the eye (zero at both corners and beyond them), full from just under the lower lid through the
    brow, fading out into the cheek below and the forehead above, and only on the front of the head."""
    import math
    from mathutils import Vector
    inverse = world.inverted()
    shapes = [outline(hole_rim(mesh, world, parts['face'], eyeball)) for eyeball in parts['eyeball']]
    midline = (np.mean(shapes[0]['y']) + np.mean(shapes[1]['y'])) / 2
    vertices = {v for i in parts['face'] | parts['eyeballs'] | parts['brows'] for v in mesh.polygons[i].vertices}
    offsets = {}
    record = []
    for shape in shapes:
        eye = Eye(shape, midline)
        width = abs(eye.y_outer - eye.y_inner)
        amount = fraction * width
        bottom, top = float(np.min(shape['bottom'])), float(np.max(shape['top']))
        for index in vertices:
            point = world @ mesh.vertices[index].co
            if point.x < -.005:
                continue
            s = float(eye.s(point.y))
            if not 0 < s < 1:
                continue
            across = math.sin(math.pi * s) ** .8
            down = float(smoothstep(bottom - .010, bottom - .002, point.z) * smoothstep(top + .024, top + .014, point.z))
            front = float(smoothstep(-.005, .01, point.x))
            dz = amount * across * down * front
            if dz > 1e-6:
                offsets[index] = offsets.get(index, 0.0) + dz
        record.append({'lift_mm': round(amount * 1000, 2), 'width_mm': round(width * 1000, 1)})
    for index, dz in offsets.items():
        point = world @ mesh.vertices[index].co
        mesh.vertices[index].co = inverse @ Vector((point.x, point.y, point.z + dz))
    mesh.update()
    return {'eyes': record, 'vertices_moved': len(offsets)}
