# SPDX-License-Identifier: GPL-3.0-or-later
"""Save a textured rest-pose preview; this is not the game's lighting shader.

Runs inside Blender (started by venom_runner.py): renders build/<mod>/apercu_venom.png
("apercu" = preview), shown by SM3 Studio's Preview button, from Venom_couleurs.png
("couleurs" = colours), the colours actually exported to the game.
"""
import argparse
import sys
from pathlib import Path
import bpy
from mathutils import Vector, Matrix
ap=argparse.ArgumentParser(); ap.add_argument('--folder',required=True)
a=ap.parse_args(sys.argv[sys.argv.index('--')+1:]); folder=Path(a.folder).resolve()
bpy.ops.wm.open_mainfile(filepath=str(folder/'Venom_custom.blend'))
sc=bpy.context.scene
texture=bpy.data.images.load(str(folder/'Venom_couleurs.png'),check_existing=True); texture.pack()
objects=[o for o in sc.objects if o.type=='MESH']
for obj in objects:
    material=bpy.data.materials.new('Venom exported colours'); material.use_nodes=True
    nodes=material.node_tree.nodes; nodes.clear()
    image=nodes.new('ShaderNodeTexImage'); image.image=texture
    emission=nodes.new('ShaderNodeEmission'); output=nodes.new('ShaderNodeOutputMaterial')
    material.node_tree.links.new(image.outputs['Color'],emission.inputs['Color'])
    material.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])
    obj.data.materials.clear(); obj.data.materials.append(material)
    for p in obj.data.polygons: p.material_index=0
points=[obj.matrix_world @ v.co for obj in objects for v in obj.data.vertices]
low=Vector([min(p[i] for p in points) for i in range(3)]); high=Vector([max(p[i] for p in points) for i in range(3)]); center=(low+high)/2
old=bpy.data.objects.get('Venom preview camera')
if old: bpy.data.objects.remove(old,do_unlink=True)
data=bpy.data.cameras.new('Venom preview camera'); cam=bpy.data.objects.new(data.name,data); sc.collection.objects.link(cam); sc.camera=cam
cam.location=center+Vector((0,0,10)); cam.rotation_euler=(0,0,0)
data.type='ORTHO'; data.ortho_scale=max(high.y-low.y,high.x-low.x)*1.15
sc.render.engine='BLENDER_EEVEE'; sc.render.resolution_x=900; sc.render.resolution_y=900; sc.render.resolution_percentage=100
if sc.world is None: sc.world=bpy.data.worlds.new('Venom preview world')
sc.world.color=(.10,.10,.10); sc.view_settings.view_transform='Standard'
sc.render.filepath=str(folder/'apercu_venom.png'); bpy.ops.render.render(write_still=True)
sc['sm3_preview_note']='Exported colours, rest pose, without the game lighting.'
bpy.ops.wm.save_as_mainfile(filepath=str(folder/'Venom_custom.blend'))
