"""Render the mouth at 1400x900, front, three-quarter and clay, from a review blend (review_model.py).

/Applications/Blender.app/Contents/MacOS/Blender -b --python games/haras_valley/assets/characters/tools/mouth_closeup.py -- review.blend mouth.png
Writes mouth-front.png, mouth-three-quarter.png, mouth-clay.png and mouth-clay-low.png beside the given name.
"""
import bpy, sys
from mathutils import Vector
path, out = sys.argv[sys.argv.index('--')+1:][:2]
bpy.ops.wm.open_mainfile(filepath=path)
scene=bpy.context.scene; cam=scene.camera; cam.data.ortho_scale=0.09
scene.render.resolution_x=1400; scene.render.resolution_y=900
clay=bpy.data.materials.new('mouth clay'); clay.use_nodes=True
clay.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.6,.62,.66,1)
centre=Vector((0,-0.004,0.335))
for name,direction,mat in [('front',(1,0,0),None),('three-quarter',(1,.65,.12),None),('clay',(1,0,0),clay),('clay-low',(1,0,-.35),clay)]:
    cam.location=centre+Vector(direction).normalized()*3; cam.rotation_euler=(centre-cam.location).to_track_quat('-Z','Y').to_euler()
    bpy.context.view_layer.material_override=mat
    scene.render.filepath=out.replace('.png',f'-{name}.png'); bpy.ops.render.render(write_still=True)
