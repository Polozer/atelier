"""Render a review blend from the face sheet's six angles (front, both three-quarters, both profiles, back).

/Applications/Blender.app/Contents/MacOS/Blender -b --python games/haras_valley/assets/characters/tools/sheet_views.py -- review.blend sv.png
"""
import bpy, sys, math
from mathutils import Vector
path, out = sys.argv[sys.argv.index('--')+1:][:2]
bpy.ops.wm.open_mainfile(filepath=path)
scene=bpy.context.scene; cam=scene.camera; cam.data.ortho_scale=0.30
scene.render.resolution_x=scene.render.resolution_y=800
c=Vector((-0.008,-0.003,0.355))
views={'front':(1,0,0),'tq-a':(1,-0.75,0),'tq-b':(1,0.75,0),'profile-a':(0,-1,0),'profile-b':(0,1,0),'back':(-1,0,0)}
for name,d in views.items():
    cam.location=c+Vector(d).normalized()*3; cam.rotation_euler=(c-cam.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=out.replace('.png',f'-{name}.png'); bpy.ops.render.render(write_still=True)
