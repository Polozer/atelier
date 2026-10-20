"""Check the ferry's keel clearance against the exported seabed meshes, not only the height functions.

blender --background --factory-startup --threads 3 --python-exit-code 1 -P seabed_probe.py -- WORLD_BUILD
WORLD_BUILD is a checkout's build/yorimichi with the exported Hidamari terrain (hidamari/assets/HD_Terrain.fbx) and
the far hills' product south of it (terrain/FarHills/final.npz), and the Brinecove ground tiles
(brinecove/glb/SM_BC_Ground_*.glb). site.py writes wet_<harbour>.npz: every 0.25 m cell
the ship's underwater footprint sweeps on arrival, alongside and on departure. Each cell is ray-cast down onto the
mesh; the highest hit must stay KEEL_CLEARANCE below the keel. Writes seabed_probe.json beside site.json.
"""
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import build as F  # noqa: E402

OUT = F.OUT / 'terminals'
SITE = json.loads((OUT / 'site.json').read_text())
LIMIT = -(SITE['ship']['draft'] + SITE['ship']['keel_clearance'])


def bvh_of(objs):
    deps = bpy.context.evaluated_depsgraph_get(); verts, polys = [], []
    for o in objs:
        if o.type != 'MESH':
            continue
        me = o.evaluated_get(deps).to_mesh(); base = len(verts)
        verts += [o.matrix_world @ v.co for v in me.vertices]; polys += [[base + i for i in p.vertices] for p in me.polygons]
    lo = [min(v[i] for v in verts) for i in range(3)]; hi = [max(v[i] for v in verts) for i in range(3)]
    return BVHTree.FromPolygons(verts, polys), lo, hi


def probe(bvh, pts, offset=(0.0, 0.0)):
    worst, at, misses = -1e9, None, 0
    for x, y in pts:
        h = bvh.ray_cast(Vector((x + offset[0], y + offset[1], 60.0)), Vector((0, 0, -1)), 200.0)
        if h[0] is None:
            misses += 1; continue
        if h[0].z > worst:
            worst, at = h[0].z, (round(float(x), 2), round(float(y), 2))
    return worst, at, misses


def main():
    build = Path(sys.argv[sys.argv.index('--') + 1])
    report = {'limit': LIMIT}
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(build / 'hidamari/assets/HD_Terrain.fbx'))
    # South of y -300 (outside the city's footprint) the far hills' exported product is the seabed.
    hills = np.load(build / 'terrain/FarHills/final.npz')
    me = bpy.data.meshes.new('FarHills'); me.from_pydata(hills['vertices'].tolist(), [], hills['triangles'].tolist())
    bpy.context.scene.collection.objects.link(bpy.data.objects.new('FarHills', me))
    bvh, lo, hi = bvh_of(list(bpy.context.scene.objects))
    w = np.load(OUT / 'wet_hidamari.npz')
    worst, at, misses = probe(bvh, zip(w['x'], w['y']))
    report['hidamari'] = {'mesh': 'hidamari/assets/HD_Terrain.fbx + terrain/FarHills/final.npz', 'bounds': [lo, hi], 'cells': int(len(w['x'])),
                          'highest_seabed': round(worst, 3), 'at': at, 'misses': misses,
                          'keel_clearance': round(-SITE['ship']['draft'] - worst, 3),
                          'function_highest': round(float(w['seabed'].max()), 3)}
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    for f in sorted((build / 'brinecove/glb').glob('SM_BC_Ground_*.glb')):
        bpy.ops.import_scene.gltf(filepath=str(f))
    bvh, lo, hi = bvh_of(list(bpy.context.scene.objects))
    w = np.load(OUT / 'wet_brinecove.npz')
    # The tiles are exported in the region-local frame when their bounds straddle the bay; otherwise in world metres.
    offset = (0.0, 0.0) if lo[0] > -1300 else (-1500.0, -120.0)
    worst, at, misses = probe(bvh, zip(w['x'], w['y']), offset)
    report['brinecove'] = {'mesh': 'brinecove/glb/SM_BC_Ground_*.glb', 'bounds': [lo, hi], 'offset': offset,
                           'cells': int(len(w['x'])), 'highest_seabed': round(worst, 3), 'at': at, 'misses': misses,
                           'keel_clearance': round(-SITE['ship']['draft'] - worst, 3),
                           'function_highest': round(float(w['seabed'].max()), 3)}
    ok = all(report[k]['highest_seabed'] <= LIMIT and report[k]['misses'] == 0 for k in ('hidamari', 'brinecove'))
    report['pass'] = ok
    (OUT / 'seabed_probe.json').write_text(json.dumps(report, indent=1) + '\n')
    print('SEABED PROBE', json.dumps(report))
    if not ok:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
