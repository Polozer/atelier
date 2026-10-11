"""Render the eyes at 1400x700, front, three-quarter and clay, from a review blend (review_model.py).

/Applications/Blender.app/Contents/MacOS/Blender -b --python games/haras_valley/assets/characters/tools/eye_closeup.py -- review.blend eyes.png
Writes eyes-front.png, eyes-three-quarter.png and eyes-front-clay.png beside the given name: a 13 cm frame centred
between the eyes of a 1 m Tripo model.
"""
import bpy, sys
from mathutils import Vector
path, out = sys.argv[sys.argv.index('--')+1:][:2]
bpy.ops.wm.open_mainfile(filepath=path)
scene=bpy.context.scene; cam=scene.camera; cam.data.ortho_scale=0.13
scene.render.resolution_x=1400; scene.render.resolution_y=700
centre=Vector((0,-0.005,0.375))
for name,direction,mode in [('front',(1,0,0),None),('three-quarter',(1,.65,.12),None),('front-clay',(1,0,0),'clay')]:
    cam.location=centre+Vector(direction).normalized()*3; cam.rotation_euler=(centre-cam.location).to_track_quat('-Z','Y').to_euler()
    bpy.context.view_layer.material_override = bpy.data.materials.get('Review clay') if mode else None
    scene.render.filepath=out.replace('.png',f'-{name}.png'); bpy.ops.render.render(write_still=True)
