# SPDX-License-Identifier: GPL-3.0-or-later
"""apparier_textures.py - find WHICH texture goes on WHICH material, by measurement.

("apparier les textures" = "pair the textures".) Called by the window's "Guess texture
assignments" button (sm3_interface.Studio.deviner), after "Analyze model".

The case that made it necessary: a mobile-game rip (Gojo, Free Fire) ships 4 slots `mat0,
mat0.001, ...` and 4 files `Tex_0217_1out.png`. No link at all: no reference in the FBX, no
meaningful name, no alpha.

What does NOT work, tested and measured on that model (2 out of 4 at best):
  - gradient energy inside / outside the UV mask
  - local variance inside / outside
  - detecting a flat background outside the islands
  - correlation between variance and mask
All of them assume the texture has EMPTY space outside the islands. A mobile rip covers 100 % of
the image. Pairing "by eye" from mean colour and height on the body was wrong too.

What works: **continuity on the 3D surface**. A texture painted for an unwrap, read through THAT
unwrap, gives a colour that changes smoothly from one triangle to its neighbour. A foreign
texture sends two neighbouring triangles to unrelated areas of the image: the colour jumps.
So for each (material, texture) pair we measure the mean colour difference between triangles
that are ADJACENT in 3D, and keep the assignment that minimises the total. No assumption about
the image content.

    blender -b --python apparier_textures.py -- --src <model> --textures <folder> [--json <f>]

Runs inside Blender (importers, image loading). Writes --json (the window uses
build/apparier.json) with French keys the window reads as they are:
    affectation   {material: image file}        the retained assignment
    matrice       score[material][texture]      normalised jump, lower is better (1.0 = chance)
    materiaux     material names, in matrix order
    textures      image files, in matrix order
It also prints a ready-made --materiaux argument for sm3_convertir.py.
"""
import argparse
import itertools
import json
import os
import sys

import numpy as np

import bpy

_a = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--src', required=True)
ap.add_argument('--textures', required=True)
ap.add_argument('--json', default='')
A = ap.parse_args(_a)

IMAGES = ('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.tif', '.tiff', '.webp')


def log(*x):
    print('[apparier]', *x)


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
else:
    bpy.ops.wm.obj_import(filepath=A.src)

# ---- candidate textures, as numpy arrays (RGB, floats 0..1, Blender's bottom-up row order)
tex = {}
for f in sorted(os.listdir(A.textures)):
    if os.path.splitext(f)[1].lower() not in IMAGES:
        continue
    im = bpy.data.images.load(os.path.join(A.textures, f))
    w, h = im.size
    if w == 0 or h == 0:
        continue
    a = np.array(im.pixels[:], np.float32).reshape(h, w, im.channels)[:, :, :3]
    tex[f] = a
    log('texture %-24s %dx%d' % (f, w, h))
if not tex:
    raise SystemExit('no image in %s' % A.textures)

# ---- per material: triangles (UV of their centre) + 3D adjacency through shared edges
mats = {}
for o in [x for x in bpy.data.objects if x.type == 'MESH']:
    me = o.data
    me.calc_loop_triangles()
    uvl = me.uv_layers.active
    if uvl is None:
        continue
    for t in me.loop_triangles:
        # '(sans materiau)' = "(no material)": same label as analyser_modele.py (a key there)
        nom = (me.materials[t.material_index].name
               if t.material_index < len(me.materials) and me.materials[t.material_index]
               else '(sans materiau)')
        # uv: one UV per triangle; aretes (edges): (object, v1, v2) -> triangles using it; aire: area
        e = mats.setdefault(nom, {'uv': [], 'aretes': {}, 'aire': 0.0})
        uv = np.mean([np.array(uvl.data[li].uv) for li in t.loops], axis=0)
        i = len(e['uv'])
        e['uv'].append(uv)
        e['aire'] += t.area
        vs = sorted(t.vertices)
        for cle in ((vs[0], vs[1]), (vs[0], vs[2]), (vs[1], vs[2])):
            e['aretes'].setdefault((o.name,) + cle, []).append(i)

noms = sorted(mats)           # material names
fichiers = sorted(tex)        # image files


def echantillonne(img, uv):
    """Nearest texel of img at each UV (tiling wrapped into [0, 1))."""
    h, w = img.shape[:2]
    # Blender puts the UV origin at the bottom left, like its pixel rows: no flip here
    x = np.clip((uv[:, 0] % 1.0) * (w - 1), 0, w - 1).astype(int)
    y = np.clip((uv[:, 1] % 1.0) * (h - 1), 0, h - 1).astype(int)
    return img[y, x]


M = np.zeros((len(noms), len(fichiers)))
for i, nm in enumerate(noms):
    e = mats[nm]
    uv = np.array(e['uv'])
    # pairs of triangles sharing an edge (an edge used by exactly two triangles)
    paires = [(v[0], v[1]) for v in e['aretes'].values() if len(v) == 2]
    if len(paires) < 20:
        log('%s: too few shared edges, ignored' % nm)
        M[i, :] = 0.0
        continue
    pa = np.array(paires)
    # WARNING: NORMALISE BY CHANCE. The raw jump mostly measures the texture's CONTRAST: a soft
    # image gives a small jump with any material, a contrasted one a large jump. In the first
    # version of this measurement `Tex_0217` won for all FOUR materials. So we divide by the
    # jump obtained between triangles PICKED AT RANDOM in the same unwrap. Close to 1 = no better
    # than chance; clearly below 1 = this unwrap reads this image well.
    tirage = np.random.default_rng(0)        # fixed seed: same scores on every run
    ra = tirage.integers(0, len(uv), len(pa))
    rb = tirage.integers(0, len(uv), len(pa))
    for j, fn in enumerate(fichiers):
        c = echantillonne(tex[fn], uv)
        voisin = np.abs(c[pa[:, 0]] - c[pa[:, 1]]).mean()       # jump between neighbours
        hasard = np.abs(c[ra] - c[rb]).mean()                    # jump between random triangles
        M[i, j] = voisin / max(hasard, 1e-9)
    log('%-14s %5d tris, %5d edges | jump/chance: %s'
        % (nm, len(uv), len(pa),
           '  '.join('%s %.3f' % (f[:12], M[i, j]) for j, f in enumerate(fichiers))))

# Exhaustive search over one-to-one assignments (a handful of materials in practice).
# NOTE: with more materials than images no assignment is tried, `arg` stays None and the
# report below fails; choose the images by hand in that case.
best, arg = 1e18, None
for p in itertools.permutations(range(len(fichiers))):
    if len(noms) > len(fichiers):
        break
    s = sum(M[i, p[i]] for i in range(len(noms)))
    if s < best:
        best, arg = s, p

log('')
log('Retained ASSIGNMENT (total score %.3f; 1.0 = chance):' % best)
sortie = {}
for i, nm in enumerate(noms):
    j = arg[i]
    autres = sorted(M[i, k] for k in range(len(fichiers)) if k != j)
    marge = (autres[0] / M[i, j]) if M[i, j] > 1e-9 else 1.0     # how much better than the runner-up
    sortie[nm] = fichiers[j]
    log('   %-14s -> %-24s score %.3f, %.1fx better than the next one'
        % (nm, fichiers[j], M[i, j], marge))
log('')
log('--materiaux "%s"' % ','.join('%s=%s' % (n, os.path.join(A.textures, sortie[n]))
                                  for n in noms))
if A.json:
    json.dump({'affectation': sortie, 'matrice': M.tolist(),
               'materiaux': noms, 'textures': fichiers},
              open(A.json, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    log('WROTE %s' % A.json)
