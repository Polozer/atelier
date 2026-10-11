"""Render a review blend from the front with flat, unlit texture colours (Workbench), framed like overlay_render.py.

/Applications/Blender.app/Contents/MacOS/Blender -b --python games/haras_valley/assets/characters/tools/flat_render.py -- review.blend flat.png
The painted eyes, brows and nose read as painted, with no shading, for comparison with the drawing.
"""
import bpy, sys
from mathutils import Vector
path, out = sys.argv[sys.argv.index('--')+1:][:2]
bpy.ops.wm.open_mainfile(filepath=path)
scene=bpy.context.scene
scene.render.engine='BLENDER_WORKBENCH'
scene.display.shading.light='FLAT'; scene.display.shading.color_type='TEXTURE'
scene.view_settings.view_transform='Standard'
cam=scene.camera; cam.data.ortho_scale=0.2; scene.render.resolution_x=scene.render.resolution_y=1200
cy,cz=-0.0031,0.352
cam.location=Vector((3,cy,cz)); cam.rotation_euler=(Vector((0,cy,cz))-cam.location).to_track_quat('-Z','Y').to_euler()
scene.render.filepath=out; bpy.ops.render.render(write_still=True)
