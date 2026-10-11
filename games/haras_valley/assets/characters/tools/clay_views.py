import bpy, sys
from mathutils import Vector
path, out = sys.argv[sys.argv.index('--')+1:][:2]
bpy.ops.wm.open_mainfile(filepath=path)
scene=bpy.context.scene; cam=scene.camera; cam.data.ortho_scale=0.2
scene.render.resolution_x=scene.render.resolution_y=700
clay=bpy.data.materials.new('c'); clay.use_nodes=True
clay.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.6,.62,.66,1)
bpy.context.view_layer.material_override=clay
c=Vector((0.0,-0.003,0.355))
for name,d in (('front',(1,0,0)),('tq',(1,.8,.05)),('side',(0,-1,0)),('low',(1,0.3,-.5))):
    cam.location=c+Vector(d).normalized()*3; cam.rotation_euler=(c-cam.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=out.replace('.png',f'-{name}.png'); bpy.ops.render.render(write_still=True)
