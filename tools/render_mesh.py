# SPDX-License-Identifier: GPL-3.0-or-later
"""render_mesh.py - decode an ALREADY WRITTEN loose .mesh and render it with its atlas, front and back.

Called by the window's "Render preview" button (sm3_interface.Studio.rendre_apercu) on the built
mod (build/<mod>/0xAC92103D.ch_spiderman000.mesh + atlas_dilate.png). It renders the DELIVERED
BYTES, never the intermediate Blender object: it is the only check that cannot lie about what the
game will receive. With --culling, back faces are culled; Blender culls the opposite winding to
the engine, so "solid here" = solid in game when compared with a vanilla piece in the same render.

    blender -b --python render_mesh.py -- \
        --mesh <file.mesh> --atlas <atlas.png> --out <folder> [--culling] [--zoom 1] [--hauteur h]

`blender` is the Blender 5.2 executable (the one set in the window's Paths tab). Runs inside
Blender. Writes <out>/render_face.png, render_dos.png ("back") and render_trois_quarts.png
("three quarters"); the window shows them by those names, so they are kept. --out is a FOLDER
(the window passes ...\\apercu.png, which becomes a folder of that name).
"""
import argparse
import importlib.util
import os
import struct
import sys

import bpy
import numpy as np
from mathutils import Vector

# TSGAMING264's SM3 Blender Toolkit, where Blender 5.2 installs extensions for the current user.
# Only its pure-Python parser sm3_format.py is loaded.
EXT = os.path.join(os.environ.get('APPDATA', ''), 'Blender Foundation', 'Blender', '5.2',
                   'extensions', 'user_default', 'sm3_blender_toolkit')

_a = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--mesh', required=True)
ap.add_argument('--atlas')
ap.add_argument('--out', required=True)
ap.add_argument('--culling', action='store_true')
ap.add_argument('--zoom', type=float, default=1.0, help='1 = whole body, 4 = close-up')
ap.add_argument('--hauteur', type=float, default=None, help='height to aim at (default: centre of the model)')
A = ap.parse_args(_a)
os.makedirs(A.out, exist_ok=True)

spec = importlib.util.spec_from_file_location('sm3_format', os.path.join(EXT, 'sm3_format.py'))
fmt = importlib.util.module_from_spec(spec)
sys.modules['sm3_format'] = fmt
spec.loader.exec_module(fmt)

m = fmt.parse_mesh(A.mesh)
# The position divisor is NOT stored in the file: it is deduced from the section bounds
# (ch_spiderman000 = 512, the 001 LOD does not use the same value). Assuming it gives a model
# 8x too large or too small.
DIV = fmt.choose_position_divisors(m)
print(f'{os.path.basename(A.mesh)}: {m.section_count} section(s), IMG {m.img_size}, PHYS {m.phys_size}, '
      f'divisors {DIV}')

bpy.ops.wm.read_homefile(use_empty=True)
sc = bpy.context.scene
allv = []
for s in m.sections:
    d = {e.usage: e for e in s.decl}
    pos, uv, nrm = d.get(0), d.get(5), d.get(3)        # D3DDECLUSAGE POSITION, TEXCOORD, NORMAL
    P, UV, N = [], [], []
    # Two conventions coexist (measured on the vanilla files): ch_spiderman000 encodes
    # pos = raw/512, ch_spiderman001 encodes pos = offset + raw/32767 x half-bbox (raw saturates).
    _raw = [struct.unpack_from('<4h', m.raw, s.vertex_buffer_offset + i * s.vertex_stride + pos.offset)
            for i in range(s.vertex_count)]
    _sature = max(max(abs(v) for v in r[:3]) for r in _raw) > 30000 if _raw else False
    dv = DIV[s.index] if s.index < len(DIV) else 512.0
    print(f'  section {s.index}: convention ' + ('NORMALISED (bbox)' if _sature else f'raw/{dv:g}'))
    for i in range(s.vertex_count):
        x, y, z, _w = _raw[i]
        if _sature:
            x = s.mesh_offset[0] + x / 32767.0 * s.mesh_bbox[0]
            y = s.mesh_offset[1] + y / 32767.0 * s.mesh_bbox[1]
            z = s.mesh_offset[2] + z / 32767.0 * s.mesh_bbox[2]
        else:
            x, y, z = x / dv, y / dv, z / dv
        P.append((x, z, y))                                   # game (x, y=up, z) -> Blender Z-up
        o = s.vertex_buffer_offset + i * s.vertex_stride
        if uv is not None:
            u, v = struct.unpack_from('<2h', m.raw, o + uv.offset)
            # WARNING: /1000, not /1024: the suit's vertex shader does "mul o2.xy, c235.x, v1"
            # with "def c235, 0.001". The checking tool must decode like the engine.
            UV.append((u / 1000.0, 1.0 - v / 1000.0))
        if nrm is not None:
            a, b, c, _ = struct.unpack_from('<4h', m.raw, o + nrm.offset)
            N.append(Vector((a / 32767.0, c / 32767.0, b / 32767.0)).normalized())
    idx = fmt.read_indices(m, s)
    tris = fmt.indices_to_faces(idx, s.primitive_type, s.vertex_count)
    me = bpy.data.meshes.new(f'sec{s.index}')
    me.from_pydata(P, [], [t for t in tris if len(set(t)) == 3])     # skip degenerate triangles
    me.update()
    if UV:
        lay = me.uv_layers.new(name='UVMap')
        for lp in me.loops:
            lay.data[lp.index].uv = UV[lp.vertex_index]
    ob = bpy.data.objects.new(f'sec{s.index}', me)
    sc.collection.objects.link(ob)
    if N:
        me.shade_smooth()
        try:
            me.normals_split_custom_set_from_vertices(N)
        except Exception as e:
            print('  (custom normals not possible:', e, ')')
    allv += P
    print(f'  section {s.index}: {s.vertex_count} v, {len(tris)} tris, mat 0x{s.material_ref_serialized:X}, '
          f'palette {len(s.bone_palette)}, prim {s.primitive_type}')

    mat = bpy.data.materials.new(f'm{s.index}')
    mat.use_nodes = True
    mat.use_backface_culling = bool(A.culling)
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is not None:
        bsdf.inputs['Roughness'].default_value = 0.85
        for sock in ('Specular IOR Level', 'Specular'):       # Blender 4+ name, then older name
            if sock in bsdf.inputs:
                bsdf.inputs[sock].default_value = 0.2
    if A.atlas and os.path.exists(A.atlas):
        tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
        tex.image = bpy.data.images.load(os.path.abspath(A.atlas))
        if bsdf is not None:
            mat.node_tree.links.new(bsdf.inputs['Base Color'], tex.outputs['Color'])
        print(f'    atlas linked: {tex.image.name} {tuple(tex.image.size)}')
    me.materials.append(mat)

allv = np.array(allv)
print(f'bounds X[{allv[:,0].min():.3f},{allv[:,0].max():.3f}] '
      f'Z(height)[{allv[:,2].min():.3f},{allv[:,2].max():.3f}] '
      f'Y(depth)[{allv[:,1].min():.3f},{allv[:,1].max():.3f}]')

cx = float((allv[:, 0].min() + allv[:, 0].max()) / 2)
cz = float((allv[:, 2].min() + allv[:, 2].max()) / 2)
rad = float(max(np.ptp(allv[:, 0]), np.ptp(allv[:, 2]))) * 1.15 / max(A.zoom, 0.01)
if A.hauteur is not None:
    cz = float(A.hauteur)

sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
sun.data.energy = 4.0
sc.collection.objects.link(sun)
cam_data = bpy.data.cameras.new('cam')
cam_data.type = 'ORTHO'
cam_data.ortho_scale = rad
cam = bpy.data.objects.new('cam', cam_data)
sc.collection.objects.link(cam)
sc.camera = cam
# First available engine: EEVEE (5.x name, then the older name), Cycles, Workbench as last resort.
_engines = {i.identifier for i in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items}
sc.render.engine = next((e for e in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE', 'CYCLES') if e in _engines), 'BLENDER_WORKBENCH')
print('render engine:', sc.render.engine)
if sc.render.engine == 'BLENDER_WORKBENCH':
    sc.display.shading.light = 'STUDIO'
    sc.display.shading.color_type = 'TEXTURE'
sc.render.resolution_x = sc.render.resolution_y = 900
sc.render.film_transparent = False
sc.world = bpy.data.worlds.new('w')
sc.world.use_nodes = True
sc.world.node_tree.nodes['Background'].inputs[0].default_value = (0.05, 0.05, 0.06, 1)

# View names are part of the output file names the window reads (face = front, dos = back,
# trois_quarts = three quarters).
for name, dy, rot in (('face', -3.0, (np.pi / 2, 0, 0)), ('dos', 3.0, (np.pi / 2, 0, np.pi)),
                      ('trois_quarts', -2.6, (np.pi / 2, 0, -0.7))):
    cam.location = (cx + (2.6 * np.sin(rot[2])), dy, cz)
    cam.rotation_euler = rot
    sun.rotation_euler = (rot[0] - 0.5, 0, rot[2] + 0.4)
    sc.render.filepath = os.path.join(A.out, f'render_{name}.png')
    bpy.ops.render.render(write_still=True)
    print('  render ->', sc.render.filepath)
