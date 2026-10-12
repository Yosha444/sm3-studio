# SPDX-License-Identifier: GPL-3.0-or-later
"""uv_footprint.py - rasterise, per material slot, the UV area that is really used.

(Renamed on 2026-10-12 from empreinte_uv.py, French for "UV footprint"; nothing referenced the
old name. Its log lines still start with [empreinte].)

Status: NOT CALLED by SM3 Studio. It was the first attempt at pairing images with materials;
the window's "Guess texture assignments" button now uses tools/apparier_textures.py, which
measures colour continuity on the 3D surface instead. Kept as a manual diagnostic.

The problem: pairing textures with materials when NOTHING links them, neither a reference in
the file nor a meaningful name. Gojo's Free Fire model is the example: 4 slots, 4 files named
`Tex_0217_1out.png`, no link. A texture painted for a slot has its detail INSIDE that slot's UV
islands and empty space around them, and that can be measured against these masks.

    blender -b --python uv_footprint.py -- --src <model> --out <folder> [--taille 256]

Runs inside Blender (it imports the model with Blender's importers). Writes one boolean
numpy mask per material, <out>/uv_<material>.npy, of --taille x --taille texels, and prints the
share of the UV square each one covers. UVs are wrapped into [0, 1) first (tiling repeats).
"""
import argparse
import os
import sys

import numpy as np

import bpy

_a = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--src', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--taille', type=int, default=256)        # "taille" = mask size in texels
A = ap.parse_args(_a)

bpy.ops.wm.read_homefile(use_empty=True)
ext = os.path.splitext(A.src)[1].lower()
if ext in ('.glb', '.gltf'):
    bpy.ops.import_scene.gltf(filepath=A.src)
elif ext == '.fbx':
    bpy.ops.import_scene.fbx(filepath=A.src)
elif ext == '.obj':
    bpy.ops.wm.obj_import(filepath=A.src)
else:
    bpy.ops.wm.obj_import(filepath=A.src)

N = A.taille
os.makedirs(A.out, exist_ok=True)
masques = {}                     # material name -> N x N boolean mask
for o in [x for x in bpy.data.objects if x.type == 'MESH']:
    me = o.data
    me.calc_loop_triangles()
    uv = me.uv_layers.active
    if uv is None:
        continue
    for t in me.loop_triangles:
        # '(sans materiau)' = "(no material)". Same label as analyser_modele.py and
        # apparier_textures.py, where it ends up as a key; it is also part of the file name here.
        nom = (me.materials[t.material_index].name
               if t.material_index < len(me.materials) and me.materials[t.material_index]
               else '(sans materiau)')
        m = masques.setdefault(nom, np.zeros((N, N), bool))
        p = [uv.data[li].uv for li in t.loops]
        # fill the triangle with barycentric coordinates, over its bounding box
        xy = np.array([[c[0] % 1.0, c[1] % 1.0] for c in p]) * (N - 1)
        x0, y0 = np.floor(xy.min(0)).astype(int)
        x1, y1 = np.ceil(xy.max(0)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, N - 1), min(y1, N - 1)
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        d = ((xy[1, 1] - xy[2, 1]) * (xy[0, 0] - xy[2, 0])
             + (xy[2, 0] - xy[1, 0]) * (xy[0, 1] - xy[2, 1]))
        if abs(d) < 1e-12:               # degenerate triangle: mark its whole box
            m[gy, gx] = True
            continue
        a = ((xy[1, 1] - xy[2, 1]) * (gx - xy[2, 0])
             + (xy[2, 0] - xy[1, 0]) * (gy - xy[2, 1])) / d
        b = ((xy[2, 1] - xy[0, 1]) * (gx - xy[2, 0])
             + (xy[0, 0] - xy[2, 0]) * (gy - xy[2, 1])) / d
        c = 1 - a - b
        # small negative tolerance so texels on a shared edge belong to both triangles
        ok = (a >= -0.002) & (b >= -0.002) & (c >= -0.002)
        m[gy[ok], gx[ok]] = True

for nom, m in masques.items():
    sur = ''.join(ch if ch.isalnum() else '_' for ch in nom)     # file-name-safe material name
    np.save(os.path.join(A.out, 'uv_%s.npy' % sur), m)
    print('[empreinte] %-28s coverage %5.1f %%' % (nom, 100.0 * m.mean()))
print('[empreinte] WROTE %d mask(s) in %s' % (len(masques), A.out))
