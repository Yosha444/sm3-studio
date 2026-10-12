# SPDX-License-Identifier: GPL-3.0-or-later
"""analyser_modele.py - list what a model contains, as JSON, without converting anything.

("analyser le modele" = "analyse the model".) Called by the window's "Analyze model" button
(sm3_interface.Studio.analyser), before any conversion. The window needs to know which
materials exist, which ones already have an image, and how many triangles each carries, so it
can offer a manual image-to-material assignment (Textures tab -> converter's --materiaux).

The case that made it necessary: a Free Fire FBX contained **no texture reference at all**. The
images sat next to it, named `Tex_0217_1out.png`, unrelated to the materials. The bake then
produced a uniform atlas (`source_image_count = 0`) and an all-white character in game. Nothing
can guess the link from the file: it has to be chosen (or measured, see apparier_textures.py).

    blender -b --python analyser_modele.py -- --src <model> [--json <output.json>]

Runs inside Blender (it uses Blender's importers). Writes the report to --json (the window
uses build/analyse.json) and also prints it after a '---JSON---' line. The report's keys are
French and are read by the window as they are; do not rename them:
    materiaux             materials, most triangles first: {nom (name), triangles,
                          sommets (vertices), image (file already wired in the model, or ''),
                          objets (objects using it)}
    objets                mesh objects: {nom, triangles, sommets, bornes_min / bornes_max
                          (world bounding box), decalque (decal), placeholder}
    armatures             {nom, os (bone count)}
    triangles_total, sommets_total, materiaux_sans_image (materials without an image), source
"triangles" counts Blender polygons, i.e. faces before triangulation.
"""
import json
import os
import sys

import bpy


def log(*x):
    print('[analyse]', *x)


_a = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
import argparse  # noqa: E402
ap = argparse.ArgumentParser()
ap.add_argument('--src', required=True)
ap.add_argument('--json', default='')
A = ap.parse_args(_a)

bpy.ops.wm.read_homefile(use_empty=True)
ext = os.path.splitext(A.src)[1].lower()
if ext in ('.glb', '.gltf'):
    bpy.ops.import_scene.gltf(filepath=A.src)
elif ext == '.fbx':
    bpy.ops.import_scene.fbx(filepath=A.src)
elif ext == '.obj':
    bpy.ops.wm.obj_import(filepath=A.src)
elif ext == '.dae':
    bpy.ops.wm.collada_import(filepath=A.src)
elif ext == '.blend':
    bpy.ops.wm.open_mainfile(filepath=A.src)
else:
    bpy.ops.wm.obj_import(filepath=A.src)

mailles = [o for o in bpy.data.objects if o.type == 'MESH']          # "mailles" = meshes
armatures = [o for o in bpy.data.objects if o.type == 'ARMATURE']


def image_du_materiau(m):
    """File name of the material's Base Color image, following intermediate nodes (mix, hue...)
    up to 6 levels; failing that, the first image node of the material; '' if none."""
    if not m or not m.use_nodes:
        return ''
    vus = set()               # nodes already visited (node graphs can loop through groups)

    def descendre(sortie, prof=0):
        if sortie is None or prof > 6:
            return ''
        n = sortie.node
        if n.type == 'TEX_IMAGE' and n.image:
            return os.path.basename(n.image.filepath) or n.image.name
        if id(n) in vus:
            return ''
        vus.add(id(n))
        for e in n.inputs:
            for li in e.links:
                r = descendre(li.from_socket, prof + 1)
                if r:
                    return r
        return ''

    b = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if b is not None:
        for li in b.inputs['Base Color'].links:
            r = descendre(li.from_socket)
            if r:
                return r
    for n in m.node_tree.nodes:
        if n.type == 'TEX_IMAGE' and n.image:
            return os.path.basename(n.image.filepath) or n.image.name
    return ''


mats = {}
for o in mailles:
    par_slot = {}             # material slot index -> polygon count
    for p in o.data.polygons:
        par_slot[p.material_index] = par_slot.get(p.material_index, 0) + 1
    for i, sl in enumerate(o.material_slots):
        m = sl.material
        # '(sans materiau)' = "(no material)": it becomes a material name in the report (a key)
        nom = m.name if m else '(sans materiau)'
        e = mats.setdefault(nom, {'nom': nom, 'triangles': 0, 'sommets': 0, 'image': '',
                                  'objets': []})
        e['triangles'] += par_slot.get(i, 0)
        e['image'] = e['image'] or image_du_materiau(m)
        if o.name not in e['objets']:
            e['objets'].append(o.name)
            e['sommets'] += len(o.data.vertices)

objets = []
for o in mailles:
    P = [tuple(o.matrix_world @ v.co) for v in o.data.vertices]
    if P:
        mn = [min(p[i] for p in P) for i in range(3)]
        mx = [max(p[i] for p in P) for i in range(3)]
    else:
        mn = mx = [0, 0, 0]
    nt = len(o.data.polygons)
    nv = len(o.data.vertices)
    objets.append({
        'nom': o.name, 'triangles': nt, 'sommets': nv,
        'bornes_min': [round(x, 4) for x in mn], 'bornes_max': [round(x, 4) for x in mx],
        # two cheap warnings, learnt from our conversions; the window offers to drop such objects:
        'decalque': bool(nt and nv > nt),        # more vertices than faces -> a sheet laid on top
        'placeholder': bool(max(abs(a) for a in mn + mx) < 1e-6),   # all bounds at 0
    })

rap = {
    'source': A.src,
    'materiaux': sorted(mats.values(), key=lambda d: -d['triangles']),
    'objets': objets,
    'armatures': [{'nom': a.name, 'os': len(a.data.bones)} for a in armatures],
    'triangles_total': sum(o['triangles'] for o in objets),
    'sommets_total': sum(o['sommets'] for o in objets),
    'materiaux_sans_image': [m['nom'] for m in mats.values() if not m['image']],
}
txt = json.dumps(rap, indent=1, ensure_ascii=False)
if A.json:
    open(A.json, 'w', encoding='utf-8').write(txt)
    log('WROTE %s' % A.json)
log('%d material(s), %d without an image, %d triangles'
    % (len(mats), len(rap['materiaux_sans_image']), rap['triangles_total']))
print('---JSON---')
print(txt)
