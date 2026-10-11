import bpy, sys, json
from mathutils import Vector
path, out, cy, cz, scale = sys.argv[sys.argv.index('--')+1:][:5]
cy, cz, scale = float(cy), float(cz), float(scale)
bpy.ops.wm.open_mainfile(filepath=path)
scene=bpy.context.scene; cam=scene.camera; cam.data.ortho_scale=scale
scene.render.resolution_x=scene.render.resolution_y=1200
cam.location=Vector((3,cy,cz)); cam.rotation_euler=(Vector((0,cy,cz))-cam.location).to_track_quat('-Z','Y').to_euler()
scene.render.filepath=out; bpy.ops.render.render(write_still=True)
