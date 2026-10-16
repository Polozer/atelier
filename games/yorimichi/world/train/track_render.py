"""Control renders of the Belmonte railway track (Blender, headless, Eevee): `atelier build yorimichi world.belmonte_track_review`.

Builds the track from track.py's layout (LOD0, the instances merged into single meshes) and renders the viaduct,
a portal of the spiral tunnel, the passing loop from above, a turnout, the Belmonte buffer stop and a plan of the
whole line, on a white background without terrain. Output: build/yorimichi/belmonte-track/review/.
"""
import sys as _sys; from pathlib import Path as _Path; _sys.path.insert(0, str(_Path(__file__).resolve().parents[1])); import yori  # noqa: E402,F401
import math

import bpy
import numpy as np
from mathutils import Vector

from train import track as T
from train import track_build as B

REVIEW = T.OUT / 'review'


def merged(mesh, rows, scale_axis=1):
    """One mesh holding `mesh` at every [x, y, z, yaw degrees, scale] row (scale along local `scale_axis`)."""
    out = T.Mesh()
    v = np.asarray(mesh.verts)
    for x, y, z, yaw, scale in rows:
        local = v.copy()
        local[:, scale_axis] *= scale
        c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        world = np.c_[x + c * local[:, 0] - s * local[:, 1], y + s * local[:, 0] + c * local[:, 1], z + local[:, 2]]
        base = len(out.verts)
        out.verts.extend(map(tuple, world))
        out.faces.extend(tuple(base + i for i in f) for f in mesh.faces)
        out.mats.extend(mesh.mats)
    return out


def scene_setup():
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.eevee.taa_render_samples = 16
    scene.view_settings.view_transform = 'Standard'
    scene.render.resolution_x, scene.render.resolution_y = 1600, 900
    world = bpy.data.worlds.new('White')
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = (1, 1, 1, 1)
    bg.inputs['Strength'].default_value = .7
    sun = bpy.data.lights.new('Sun', 'SUN')
    sun.energy = 3.5
    sun.angle = math.radians(3)
    o = bpy.data.objects.new('Sun', sun)
    o.rotation_euler = (math.radians(50), 0, math.radians(35))
    scene.collection.objects.link(o)
    cam = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
    cam.data.clip_end = 20000
    scene.collection.objects.link(cam)
    scene.camera = cam
    return scene, cam


def shoot(scene, cam, name, eye, target, lens=35., ortho=None):
    cam.location = Vector(eye)
    cam.rotation_euler = (Vector(target) - Vector(eye)).to_track_quat('-Z', 'Y').to_euler()
    if ortho:
        cam.data.type, cam.data.ortho_scale = 'ORTHO', ortho
    else:
        cam.data.type, cam.data.lens = 'PERSP', lens
    scene.render.filepath = str(REVIEW / f'{name}.png')
    bpy.ops.render.render(write_still=True)


def main():
    B.clear()
    REVIEW.mkdir(parents=True, exist_ok=True)
    line = T.Line()
    meshes, doc = T.layout(line)
    mats = B.materials()
    for name, lods in meshes.items():
        if name in doc['instances']:
            continue
        row = next((r for group in (doc['chunks'], *[t['lining'] for t in doc['tunnels']],
                                    *[v['pieces'] for v in doc['viaducts']]) for r in group if r['name'] == name), None)
        o = B.to_object(name, lods[0], mats)
        if row:
            o.location = row['origin']
    for name, rows in doc['instances'].items():
        if name in doc['editor_only']:
            continue
        rows = [r for group in rows.values() for r in group] if isinstance(rows, dict) else rows
        mesh = merged(meshes[name][0], rows)
        B.to_object(name + '_all', mesh, mats)
    scene, cam = scene_setup()

    def at(s, u=0., v=0.):
        return tuple(float(c) for c in line.place(s, u, v))

    via = doc['viaducts'][0]
    mid = (via['start'] + via['end']) / 2
    ground = float(line.ground_at(mid))
    eye = at(mid - 60., -110., 0.)
    shoot(scene, cam, 'viaduct', (eye[0], eye[1], ground + 8.), at(mid, 0., -10.), lens=30.)
    spiral = next(t for t in doc['tunnels'] if t['name'] == 'Spiral')
    s = spiral['start']
    shoot(scene, cam, 'portal-spiral-south', at(s - 45., 9., 4.), at(s, 0., 3.), lens=35.)
    a, b = line.loop
    shoot(scene, cam, 'loop', at((a + b) / 2 - 40., -90., 70.), at((a + b) / 2, 0., 0.), lens=35.)
    shoot(scene, cam, 'turnout', at(a - 18., -4., 3.), at(a + 25., 0., 0.), lens=35.)
    end = line.length
    shoot(scene, cam, 'buffer-stop-belmonte', at(end - 22., 3.5, 2.2), at(end - T.BUFFER_OFFSET, 0., 1.), lens=40.)
    xy = np.asarray([line.frame(s)[0] for s in np.linspace(0, end, 50)])
    lo, hi = xy.min(0), xy.max(0)
    centre = (lo + hi) / 2
    shoot(scene, cam, 'plan', (centre[0], centre[1], hi[2] + 2000.), (centre[0], centre[1] + .01, 0.),
          ortho=float(max(hi[0] - lo[0], (hi[1] - lo[1]) * 16 / 9)) * 1.1)
    print('belmonte-track review:', sorted(p.name for p in REVIEW.glob('*.png')))


if __name__ == '__main__':
    main()
