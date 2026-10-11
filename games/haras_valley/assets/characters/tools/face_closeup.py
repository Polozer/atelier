"""Render a character's face at 1200 px, front and three-quarter, from a review blend (review_model.py).

/Applications/Blender.app/Contents/MacOS/Blender -b --python games/haras_valley/assets/characters/tools/face_closeup.py -- review.blend face-closeup.png
Writes face-closeup-front.png and face-closeup-three-quarter.png beside the given name. The camera looks at z = 0.37
(the eyes of a 1 m Tripo model) through a 22 cm frame.
"""
import bpy, sys, math
from mathutils import Vector
path, out = sys.argv[sys.argv.index('--')+1:][:2]
bpy.ops.wm.open_mainfile(filepath=path)   # the review blend: lights and camera exist
scene=bpy.context.scene; cam=scene.camera; cam.data.ortho_scale=0.22
scene.render.resolution_x=scene.render.resolution_y=1200
centre=Vector((0,0,0.37))
for i,(name,direction) in enumerate([('front',(1,0,0)),('three-quarter',(1,.65,.12))]):
    cam.location=centre+Vector(direction).normalized()*3; cam.rotation_euler=(centre-cam.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=out.replace('.png',f'-{name}.png'); bpy.ops.render.render(write_still=True)
