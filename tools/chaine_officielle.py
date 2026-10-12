# SPDX-License-Identifier: GPL-3.0-or-later
"""chaine_officielle.py - runs the REAL workflow of TSGAMING264's add-ons, start to finish.

("chaîne officielle" = "official chain".) The `chaine` stage of the converter: sm3_convertir.py
starts it in Blender (red suit); blacksuit_pipeline.py and rvb_runner.py reuse it. It is the
only stage that needs Blender, and the slow one (the bake).

Nothing is reimplemented any more: it calls the add-ons' operators, in the order of their README.
  1. sm3.import_vanilla_spider_target        (VANILLA target, 10 sections, canvas section 4, ref 0x0614)
  2. import of the source model, joined into one object, aligned on the vanilla template,
     conformed to the game's skeleton when it has its own rig, weights transferred from the
     vanilla mesh
  3. sm3mat.auto_setup_source_textures       (wires the images of the source folder)
  4. sm3mat.create_friend_baked_atlas        (UV repack + bake + dilation + mips + .tex), then our
     re-bake on the game's UV grid (atlas_recuit.py) and the normal-map bake (normale_bake.py)
  5. sm3.prepare_spider_atlas_section        (joins OUR mesh into the canvas section)
  6. export_scene.sm3_prepared_spider_atlas  (DEDICATED exporter: 1 section, 0x0614, /512, 32 bones)
     and export_scene.sm3_prepared_spider_atlas_001 for the 001 LOD

WARNING: do NOT use the generic exporter `export_scene.sm3_mesh_exporter`: its README explicitly
forbids it for this path, and that is what I was doing.

    blender -b --python chaine_officielle.py -- --src <model> --textures <folder>
            --vanilla <apkf folder> --out <folder> [--drop ...] [--materiaux ...]

Writes into --out: 0xAC92103D.ch_spiderman000.mesh, 0xAC92103E.ch_spiderman001.mesh, the atlas
(SM3_Spider_Baked_Atlas_atlas_final.png and the add-on's other outputs), normale_swizzle.png,
conforme.json and doigts_modele.npz when the model was conformed, qualite_hq_rapport.json, and
chaine.blend (the scene, reopened by blacksuit_pipeline.py).
Only lines starting with '[chaine]' (the log() below) reach the window's log: sm3_convertir.lance()
relays nothing else from Blender's output, except the tail of it on failure.
Names kept in French because other code reads them: Blender objects NOTRE_MODELE ("our model")
and DONNEUR_VANILLA ("vanilla donor"), conforme.json keys, the --egaliser-densite values oui/non.
"""
import argparse
import os
import sys

import bpy
import numpy as np

_a = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument('--src', required=True)
ap.add_argument('--textures', required=True)
ap.add_argument('--vanilla', required=True)
ap.add_argument('--out', required=True)
# --tris (old decimation budget) is no longer used: the HQ options never decimate. --bake is
# overridden by qualite.json below. Both are still accepted so older command lines keep working.
ap.add_argument('--tris', type=int, default=44000)
ap.add_argument('--bake', type=int, default=2048)
ap.add_argument('--drop', default='', help='materials to delete, comma-separated')
ap.add_argument('--materiaux', default='',
                help="MANUAL texture assignment: 'mat0=file.png,mat1=other.png'. "
                     "Indispensable when the model references no texture -- a Free Fire FBX, "
                     "for example: its images sit next to it, named unrelated to the "
                     "materials, and the bake produced a uniform atlas "
                     "(`source_image_count = 0`), an all-white character in game.")
ap.add_argument('--pre-pose', action='store_true',
                help='the model comes out of pose_liaison.py (an experimental tool, not shipped): do not re-align it')
ap.add_argument('--conformer', default=os.environ.get('SM3_CONFORMER', 'auto'),
                choices=['auto', 'non', '0', '1'],
                help="auto = if the model has its own rig, put each of its joints on the game "
                     "skeleton's (tools/conformer_squelette.py); non = old fit "
                     "(scale + centring) only")
# WARNING: the engine ALREADY applies a global `colorMatrix` (present in the CTAB of every shader
# in Game.exe, applied with add_sat on the albedo). Saturating at bake time adds on top of it and
# turns skin orange. Adjustable; 1.0 = let the engine do the grading.
ap.add_argument('--sat', type=float, default=1.0)
ap.add_argument('--egaliser-densite', default='auto', choices=['auto', 'oui', 'non'],
                help='equalise UV island density: auto = only if the model needs it (tiled UVs). oui = always (old behaviour). non = never. Equalising saves tiled models but STEALS resolution from the head on a clean model.')
ap.add_argument('--uv-grille', type=int, default=1,
                help='1 = snap the UVs to the game grid (1/1000), then RE-BAKE the diffuse on it. Without this the atlas is painted with the floating-point UVs and the game samples it with the rounded UVs: measured mean offset of 1.56 texels at 4096, hence wavy lines.')
ap.add_argument('--normale-force', default='auto',
                help="relief DEDUCED from the diffuse when the model provides no normal map. 'auto' (default) calibrates the gain to aim at the median slope of the game's real maps, 1.3 to 5.7 deg; 'auto:5' aims at 5 deg; a number forces the gain as before; 0 deduces nothing; a negative number inverts the direction, for textures whose shading is painted (highlights) rather than geometric. A FIXED gain saturated on textures with hard flat areas: median slope of 81 deg measured on the `verse` model, against 1.3 to 5.7 for a real map.")
ap.add_argument('--normale', type=int, default=1,
                help='1 = also bake the normal map in the atlas unwrap')
ap.add_argument('--contraste-bake', type=float, default=1.0)
A = ap.parse_args(_a)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qualite_hq as hq
HQ = hq.settings()
A.bake = HQ['resolution']          # qualite.json decides the bake size, not --bake
os.makedirs(A.out, exist_ok=True)
MESH_VAN = os.path.join(A.vanilla, '0xAC92103D.ch_spiderman000.mesh')


def log(*x):
    print('[chaine]', *x)


bpy.ops.wm.read_homefile(use_empty=True)
sc = bpy.context.scene

# ---------------------------------------------------------------- 1. vanilla target
r = bpy.ops.sm3.import_vanilla_spider_target(filepath=MESH_VAN)
log('vanilla target import:', r)
van = [o for o in bpy.data.objects if o.type == 'MESH']
_noms_van = [o.name for o in van]
log('  %d object(s) after the vanilla import' % len(van))
# WARNING: without the SKELETON in the same collection, the vanilla vertex groups stay named
# "bone_0, bone_1..." and `rename_vertex_groups` refuses. Renaming by proximity then gives
# useless names and the exported palette drops to 1 or 5 bones.
SKEL_VAN = os.path.join(A.vanilla, '0x461356AE.ch_spidermanskeleton_ch_spiderman000.skel')
try:
    # this importer expects `directory` + `files`, not `filepath`
    r = bpy.ops.import_scene.sm3_skeleton_importer(
        directory=os.path.dirname(SKEL_VAN) + os.sep,
        files=[{"name": os.path.basename(SKEL_VAN)}])
    log('vanilla skeleton import:', r)
except Exception as e:
    log('skeleton import failed:', e)
_arm_van = [o for o in bpy.data.objects if o.type == 'ARMATURE']
log('  %d armature(s) in the scene' % len(_arm_van))

# ---------------------------------------------------------------- 2. our model
avant = set(bpy.data.objects)          # objects before the import ("avant" = before)
if A.src.lower().endswith(('.glb', '.gltf')):
    bpy.ops.import_scene.gltf(filepath=A.src)
elif A.src.lower().endswith('.fbx'):
    bpy.ops.import_scene.fbx(filepath=A.src)
else:
    bpy.ops.wm.obj_import(filepath=A.src)
# The model's RIG, captured right away (the join and unparenting that follow do not touch it,
# but we want its joints in the same world frame as the vertices at rest).
_RIG = None
_arms_mod = [o for o in bpy.data.objects if o not in avant and o.type == 'ARMATURE'
             and len(o.data.bones)]
if _arms_mod:
    _am = max(_arms_mod, key=lambda o: len(o.data.bones))
    _bn = list(_am.data.bones)
    # noms = bone names, parents = parent indices, tetes = bone heads (world), objet = armature name
    _RIG = {'noms': [b.name for b in _bn],
            'parents': [(_bn.index(b.parent) if b.parent is not None else -1) for b in _bn],
            'tetes': np.array([tuple(_am.matrix_world @ b.head_local) for b in _bn], np.float64),
            'objet': _am.name}
    log('  model rig: "%s", %d bones' % (_am.name, len(_bn)))
# WARNING: armatures in REST position before the join. Skinned meshes are read from their DATA
# (bind pose); an unskinned piece ATTACHED TO A BONE (claws, cape wings of the Auto-Rig Pro 2099)
# is placed by the armature's POSE. The two did not match: the pieces landed below the feet, the
# bounding box grew and the whole model shrank (2099 mod installed on 2026-10-06: body at two
# thirds of the height, debris on the ground).
for _a in _arms_mod:
    if _a.data.pose_position != 'REST':
        _a.data.pose_position = 'REST'
        log('  armature "%s" set to rest position (pieces attached to bones)' % _a.name)
bpy.context.view_layer.update()
# WARNING: an FBX references its textures by external path: if they are missing, Blender loads
# 0x0 images and the add-on refuses to bake ("used material slot(s) have no diffuse image").
# We point them at the source folder, matching by name.
manquantes = 0                          # images still missing
for im in bpy.data.images:
    if im.name == 'Render Result' or (im.size[0] and im.size[1]):
        continue
    for ext in ('.png', '.tga', '.jpg', '.dds'):
        cand = os.path.join(A.textures, im.name + ext)
        if os.path.exists(cand):
            im.filepath = cand
            im.source = 'FILE'
            im.reload()
            log('  image "%s" repointed -> %s (%dx%d)'
                % (im.name, os.path.basename(cand), im.size[0], im.size[1]))
            break
    else:
        manquantes += 1
        log('  image "%s" NOT FOUND in %s' % (im.name, A.textures))
if manquantes:
    log('  %d missing image(s): the bake will refuse' % manquantes)
neufs = [o for o in bpy.data.objects if o not in avant]
src_meshes = [o for o in neufs if o.type == 'MESH' and len(o.data.vertices)]
# WARNING: a NORMAL join, no manual evaluation: going through `new_from_object` loses the image
# links of the materials AND the vertex group weights (the add-on then reported "9 slots without
# a diffuse image" and a one-bone palette).
# WARNING: the ACTIVE object is the target of the join: taking the first one that comes may land
# on a 42-vertex icosphere and everything else is lost. We join into the LARGEST mesh.
src_meshes.sort(key=lambda o: -len(o.data.vertices))
log('  imported meshes: ' + ', '.join('%s(%d v)' % (o.name, len(o.data.vertices))
                                       for o in src_meshes[:6]))
# WARNING: Blender merges UV layers BY NAME when joining. A model whose every part has its own
# layer ("AvatarBody", "AvatarHead", "outfit_top"...) therefore gives an object with 12 layers,
# each holding the UVs of one part only, and the add-on fails on a missing active layer
# ("_copy_uv_layer: NoneType"). We make them uniform BEFORE joining.
for o in src_meshes:
    me = o.data
    if not me.uv_layers:
        me.uv_layers.new(name='UVMap')
    chosen = next((layer for layer in me.uv_layers if layer.active_render), me.uv_layers.active)
    old_name = chosen.name
    for layer in list(me.uv_layers):
        if layer.name != old_name:
            me.uv_layers.remove(layer)
    me.uv_layers[0].name = 'UVMap'
    me.uv_layers.active_index = 0
    me.uv_layers[0].active_render = True
    for material in me.materials:
        if material and material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type == 'UVMAP' and node.uv_map == old_name:
                    node.uv_map = 'UVMap'
log('  UV layers made uniform as "UVMap" on %d mesh(es)' % len(src_meshes))
bpy.ops.object.select_all(action='DESELECT')
for o in src_meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = src_meshes[0]
if len(src_meshes) > 1:
    bpy.ops.object.join()
src = bpy.context.view_layer.objects.active
# WARNING: `join()` DELETES the absorbed objects: any reference kept in a list becomes dead
# ("StructRNA of type Object has been removed"). We rebuild from bpy.data.objects.
neufs = [o for o in bpy.data.objects if o.name not in set(_noms_van)]
src.name = 'NOTRE_MODELE'
# WARNING: a Mixamo FBX is Z-up, the vanilla template is Y-up: without a rotation the character
# comes out lying down (height 0.31, depth 1.80 instead of the reverse). We rotate the DATA.
import numpy as _np
# apply the object transform first: the FBX importer puts a rotation on the OBJECT, so world
# space looks already upright while the DATA, which is what the exporter reads, stays Z-up.
bpy.ops.object.select_all(action='DESELECT')
src.select_set(True); bpy.context.view_layer.objects.active = src
# WARNING: the imported mesh is PARENTED to the armature: as long as that link exists, neither
# `src.location` nor `src.data.transform` moves anything in world space, and the alignment on the
# template silently does nothing (measured: the model stayed 4 units away, all weights collapsed
# onto 4 leg bones). We cut the link keeping the position, then apply.
if src.parent is not None:
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    log('  parenting to the armature removed (position kept)')
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
_P = _np.array([tuple(v.co) for v in src.data.vertices], _np.float64)
_e = _P.max(0) - _P.min(0)
log('  extents of the DATA before standing it up: %s' % _np.round(_e, 3))
# We work in the template's frame (Y up) to align and map; the counter-rotation for the exporter
# is applied at the very end.
if int(_np.argmax(_e)) == 2 or (_e[2] > 1.5 * _e[1] and _e[1] < _e[0]):
    from mathutils import Matrix as _Mx1
    import math as _mt1
    src.data.transform(_Mx1.Rotation(_mt1.radians(-90), 4, 'X'))
    src.data.update()
    _P = _np.array([tuple(v.co) for v in src.data.vertices], _np.float64)
    log('  stood up to Y-up: %s' % _np.round(_P.max(0) - _P.min(0), 3))
    if _RIG is not None:
        _Rx = _np.array(_Mx1.Rotation(_mt1.radians(-90), 3, 'X'))
        _RIG['tetes'] = _RIG['tetes'] @ _Rx.T
log('source model: %d vertices, %d faces, %d slots'
    % (len(src.data.vertices), len(src.data.polygons), len(src.material_slots)))

# materials to drop (stray objects, untextured shells)
drop = [x.strip().lower() for x in A.drop.split(',') if x.strip()]
if drop:
    import bmesh
    idx = {i for i, sl in enumerate(src.material_slots)
           if sl.material and sl.material.name.lower() in drop}
    if idx:
        bm = bmesh.new(); bm.from_mesh(src.data)
        f = [x for x in bm.faces if x.material_index in idx]
        bmesh.ops.delete(bm, geom=f, context='FACES')
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
        bm.to_mesh(src.data); bm.free(); src.data.update()
        log('materials dropped %s: %d faces -> %d' % (sorted(drop), len(f), len(src.data.polygons)))

# WARNING: an avatar carries shape keys (facial expressions) and Blender then refuses to apply a
# modifier: "Modifier cannot be applied to a mesh with shape keys". We remove them; they mean
# nothing once exported to SM3.
if src.data.shape_keys:
    _nsk = len(src.data.shape_keys.key_blocks)
    bpy.ops.object.select_all(action='DESELECT')
    src.select_set(True); bpy.context.view_layer.objects.active = src
    src.shape_key_clear()
    log('  %d shape key(s) removed' % _nsk)

# HQ: no automatic reduction of the surface.
hq.geometry(src, HQ)

# ---------------------------------------------------------------- 2 bis. renaming the weights
# The model's vertex groups carry Mixamo names; the exporter looks for SM3 bones and finds only
# one (palette of 1). The toolkit's operator renames the groups of the TARGET by proximity to
# the group centroids of a SOURCE mesh that already has SM3 names (a vanilla piece).
# ---------------------------------------------------------------- 2 ter. ALIGNMENT on the template
# WARNING: to do BEFORE the weight transfer, which is spatial: if the scales differ, the transfer
# brings back anything. And we put the FEET on the feet rather than matching bounding boxes,
# which shift as soon as the poses differ by a hair.
_objs_van = [o for o in bpy.data.objects if o.name in set(_noms_van) and o.type == 'MESH'
             and len(o.data.vertices)]
_VP = _np.array([tuple(o.matrix_world @ v.co) for o in _objs_van for v in o.data.vertices],
                _np.float64)
_vmin, _vmax = _VP.min(0), _VP.max(0)
_SP = _np.array([tuple(src.matrix_world @ v.co) for v in src.data.vertices], _np.float64)
from mathutils import Matrix as _MxA, Vector as _VecA
# WARNING: `math` is imported above (`_mt1`) only INSIDE the Z-up straightening, which does not
# always run: the orientation fallback below needs its own.
import math as _mtO
_axe_h = int(_np.argmax(_vmax - _vmin))    # height axis of the template


def _points_src():
    return _np.array([tuple(src.matrix_world @ v.co) for v in src.data.vertices], _np.float64)


_CALAGE = {'echelle': 1.0, 'decalage': _np.zeros(3)}     # accumulated fit: scale, offset


def _centre_tronc(P, k):
    """Centre (min+max)/2 of the TRUNK on axis k: median over slices of 1 % of the height between
    the pelvis and the chest (53..75 % of the height), arms excluded. Does not depend on vertex
    density, unlike the median of the whole model. None if the trunk cannot be found."""
    _h = P[:, _axe_h]
    _lo, _hi = _h.min(), _h.max()
    _lar = 3 - _axe_h - k                      # the width axis
    _cl = float(_np.median(P[:, _lar]))
    _bras = _np.abs(P[:, _lar] - _cl) < 0.09 * (_hi - _lo)     # near the middle = not the arms
    _c = []
    for _f in _np.arange(0.53, 0.75, 0.01):
        _m = _bras & (_h >= _lo + _f * (_hi - _lo)) & (_h < _lo + (_f + 0.01) * (_hi - _lo))
        if _m.sum() >= 4:
            _c.append((P[_m, k].min() + P[_m, k].max()) / 2.0)
    return float(_np.median(_c)) if len(_c) >= 8 else None


def _caler_sur_gabarit():
    """("fit on the template") Isotropic scale + translation on the template's box. Returns
    (scale, points)."""
    _P = _points_src()
    _ec = float((_vmax - _vmin).max() / (_P.max(0) - _P.min(0)).max())
    src.data.transform(_MxA.Scale(_ec, 4))
    src.data.update()
    _P = _points_src()
    _d = _np.zeros(3)
    _ext = _vmax - _vmin
    _prof = min((k for k in range(3) if k != _axe_h), key=lambda k: _ext[k])    # depth axis
    for _k in range(3):
        if _k == _axe_h:
            _d[_k] = _vmin[_k] - _P.min(0)[_k]          # feet on feet
        else:
            _d[_k] = float(_np.median(_VP[:, _k])) - float(_np.median(_P[:, _k]))
    # WARNING: DEPTH: the median of all vertices puts the body BEHIND the skeleton as soon as the
    # density differs from the vanilla (dense head, head held forward): 10 to 19 cm measured on
    # two TASM models; the spine then rotated around an axis sitting in the belly ("broken
    # back"). We put the model's TRUNK CENTRE on the vanilla's.
    _cv, _cm = _centre_tronc(_VP, _prof), _centre_tronc(_P, _prof)
    if _cv is not None and _cm is not None:
        _dt = _cv - _cm
        log('  depth: trunk centre on the vanilla\'s (%+.3f; the median gave %+.3f)'
            % (_dt, _d[_prof]))
        _d[_prof] = _dt
    src.data.transform(_MxA.Translation(_VecA((float(_d[0]), float(_d[1]), float(_d[2])))))
    src.data.update()
    _CALAGE['echelle'] = _CALAGE['echelle'] * _ec
    _CALAGE['decalage'] = _CALAGE['decalage'] * _ec + _d
    if _RIG is not None:
        _RIG['tetes'] = _RIG['tetes'] * _ec + _d
    return _ec, _points_src()


def _caler_points(P):
    """The same fit as `_caler_sur_gabarit`, but on an array: to TRY without modifying anything."""
    _ec = float((_vmax - _vmin).max() / (P.max(0) - P.min(0)).max())
    _Q = P * _ec
    _d = _np.zeros(3)
    for _k in range(3):
        _d[_k] = ((_vmin[_k] - _Q.min(0)[_k]) if _k == _axe_h
                  else (float(_np.median(_VP[:, _k])) - float(_np.median(_Q[:, _k]))))
    return _Q + _d


def _ecart_au_gabarit(P):
    """Mean distance from a model vertex to the nearest VANILLA vertex, after the fit.

    WARNING: no home-made descriptor: we compare with the template ITSELF, which is the referee.
    That is what decides which side the head is on, since both quarter turns give the same
    extents. Measured on the "lying on its side" case (5,491 vertices against 55,180 in the
    template):
        head up 0.0673   head down 0.0922   -> 27 % margin, the right choice wins.
    A first attempt by SILHOUETTE (mean horizontal radius per height slice) gave 1.4409 against
    1.3693: it pointed at the WRONG orientation. It was thrown away, not kept as a fallback.
    """
    return float(_np.mean([_kd_van.find(_VecA(tuple(_p)))[2] for _p in _caler_points(P)]))


if A.pre_pose:
    # The model already comes out of `pose_liaison.py`: its 52 joints are on the vanilla's to
    # within 0.000. Re-fitting here on bounding boxes would only shift them again.
    log('alignment skipped (--pre-pose): the model is already in the vanilla bind pose')
else:
    _ech, _SP = _caler_sur_gabarit()
    log('aligned on the template: scale %.4f, height axis %d' % (_ech, _axe_h))
log('   model     %s .. %s' % (_np.round(_SP.min(0), 3), _np.round(_SP.max(0), 3)))
# ---------------------------------------------------------------- orientation: FALL BACK, do not refuse
# WARNING: before, we raised "Orientation source incoherente" and the conversion stopped there.
# Yet there is an obvious, measurable fallback: TAKE THE MODEL'S LONGEST AXIS AS ITS HEIGHT. A rip
# lying on its side is not a model to fix by hand, it is a quarter turn to make.
# What remains is which side the head is on: both quarter turns give the same extents. We decide
# by trying both and keeping the one whose vertices fall closest to those of the VANILLA
# TEMPLATE (see `_ecart_au_gabarit`): the referee decides, not an invented rule.
if not A.pre_pose and (_SP.max(0) - _SP.min(0))[_axe_h] < .65 * (_vmax - _vmin)[_axe_h]:
    _e_src = _SP.max(0) - _SP.min(0)
    _axe_l = int(_np.argmax(_e_src))
    log('!! orientation undetermined: %.3f high on axis %d, the template expects %.3f '
        '(model extents %s).'
        % (_e_src[_axe_h], _axe_h, (_vmax - _vmin)[_axe_h], _np.round(_e_src, 3)))
    if _axe_l == _axe_h:
        log('!! the longest axis already is the height axis: the model is just squat. '
            'Going on as it is; check the silhouette of the render.')
    else:
        _axe_c = 3 - _axe_l - _axe_h            # the 3rd axis: the one we rotate around
        from mathutils.kdtree import KDTree as _KDT
        _kd_van = _KDT(len(_VP))
        for _i, _p in enumerate(_VP):
            _kd_van.insert(_VecA(tuple(_p)), _i)
        _kd_van.balance()
        _choix = []
        for _ang in (90.0, -90.0):
            _R = _MxA.Rotation(_mtO.radians(_ang), 4, 'XYZ'[_axe_c])
            _Q = _np.array([tuple(_R @ (src.matrix_world @ v.co)) for v in src.data.vertices],
                           _np.float64)
            _choix.append((_ecart_au_gabarit(_Q), _ang, _R))
        _choix.sort()
        _ecart, _ang, _R = _choix[0]
        # WARNING: ACT ONLY IF THE TEMPLATE REALLY DECIDES. The trigger -- height below 65 % of
        # the template's -- does not tell "model lying down" from "STANDING model whose bounding
        # box is widened by a horizontal axis": `_caler_sur_gabarit` scales on the LARGEST
        # extent, so a spread cape, an accessory or a single stray vertex is enough to lower the
        # relative height. Rotating in that second case LAYS DOWN a character that was upright,
        # and the output validator does not catch orientation.
        # The only figure that separates the two cases is the margin between the two quarter
        # turns: 27 % on a model really lying down, 0.05 % on a standing one that is too wide.
        # Below 10 % the template has not decided -- we refuse, instead of flipping a coin on a mod.
        if _ecart > 0.9 * _choix[1][0]:
            raise RuntimeError(
                'Inconsistent source orientation: %.3f high for %.3f expected, and the template '
                'cannot decide between the two directions (%.4f against %.4f, less than 10 %% '
                'apart). The model is probably STANDING but its bounding box is widened by a '
                'stray piece -- cape, accessory, lost vertex: remove it. If it really is lying '
                'down, stand it up in Blender before converting.'
                % (_e_src[_axe_h], (_vmax - _vmin)[_axe_h], _ecart, _choix[1][0]))
        log('!! fallback: the longest axis is %s (%.3f), it is put on the height axis %s by '
            'a rotation of %+.0f deg around %s. Mean distance to the template: %.4f for '
            '%+.0f deg against %.4f for %+.0f deg -- that decides which side the head is on.'
            % ('XYZ'[_axe_l], _e_src[_axe_l], 'XYZ'[_axe_h], _ang, 'XYZ'[_axe_c],
               _choix[0][0], _choix[0][1], _choix[1][0], _choix[1][1]))
        src.data.transform(_R)
        src.data.update()
        _RIG = None          # the rig did not follow this quarter turn: no conformation
        _ech, _SP = _caler_sur_gabarit()
        log('!! re-aligned: scale %.4f, model %s .. %s'
            % (_ech, _np.round(_SP.min(0), 3), _np.round(_SP.max(0), 3)))
        _reste = (_SP.max(0) - _SP.min(0))[_axe_h]
        if _reste < .65 * (_vmax - _vmin)[_axe_h]:
            log('!! WARNING: even after the fallback the height is only %.3f for %.3f '
                'expected. The mod will be produced, but its proportions will be wrong: '
                're-orient the source model, or pass --rot-x/--rot-y/--rot-z.'
                % (_reste, (_vmax - _vmin)[_axe_h]))
log('   template  %s .. %s' % (_np.round(_vmin, 3), _np.round(_vmax, 3)))
log('   offset: bottom %+.3f, top %+.3f' % (_SP.min(0)[_axe_h] - _vmin[_axe_h],
                                           _SP.max(0)[_axe_h] - _vmax[_axe_h]))

# ---------------------------------------------------------------- 2 ter bis. FACING (front / back)
# WARNING: the straightening only looks at the height: a model facing BACKWARDS went through as
# it was. Measured 2026-10-07 on tasm_1_spider-man.glb: toes towards -z, back to the camera (the
# mod installed on 06/10 had been turned by hand). Toes stick out of the leg towards the FRONT: we
# compare the median depth of the bottom of the feet with that of the calves, on the model and on
# the vanilla.
def _sens_pieds(P):
    """("direction of the feet") (median toe depth - median calf depth, depth axis)."""
    _h = P[:, _axe_h]
    _lo, _H = _h.min(), _h.max() - _h.min()
    _ext = _vmax - _vmin
    _pr = min((k for k in range(3) if k != _axe_h), key=lambda k: _ext[k])
    _pied = P[_h < _lo + 0.03 * _H]                               # bottom 3 %: feet
    _mol = P[(_h > _lo + 0.16 * _H) & (_h < _lo + 0.21 * _H)]     # 16-21 %: calves
    if len(_pied) < 10 or len(_mol) < 10:
        return None, _pr
    return float(_np.median(_pied[:, _pr]) - _np.median(_mol[:, _pr])), _pr


if not A.pre_pose:
    _sv, _pr = _sens_pieds(_VP)
    _sm, _ = _sens_pieds(_SP)
    if _sv is not None and _sm is not None and _sm * _sv < 0 and abs(_sm) > 0.01 * (_vmax - _vmin)[_axe_h]:
        from mathutils import Matrix as _MxS
        import math as _mtS
        _Rs = _MxS.Rotation(_mtS.radians(180.0), 4, 'XYZ'[_axe_h])
        src.data.transform(_Rs)
        src.data.update()
        if _RIG is not None:
            _RIG['tetes'] = _RIG['tetes'] @ _np.array(_Rs)[:3, :3].T
        _ech, _SP = _caler_sur_gabarit()
        log('!! model facing BACKWARDS (toes towards the back: %+.3f against %+.3f on the vanilla) -> '
            'turned 180 deg; re-fitted %s .. %s' % (_sm, _sv, _np.round(_SP.min(0), 3), _np.round(_SP.max(0), 3)))
    elif _sm is not None:
        log('  facing: front (toes %+.3f, vanilla %+.3f)' % (_sm, _sv))

# ---------------------------------------------------------------- 2 quater. CONFORMATION to the skeleton
# The engine rotates every piece around the joints of the VANILLA skeleton. A model that is only
# scaled keeps ITS joints: elbow, knee, shoulder, neck land off target and the body bends in the
# wrong place (TASM2: 4 to 19 cm off, torso leaning, head forward).
# When the model has its own rig, we put each of its joints on the game's (see
# tools/conformer_squelette.py); its fingers are kept for `mains_poings` (doigts_modele.npz).
_CONFORME = None
_marque = os.path.join(A.out, 'conforme.json')          # marker: the model was conformed
if os.path.isfile(_marque):
    os.remove(_marque)                  # an old marker would wrongly skip the `bras` stage
_doigts_npz = os.path.join(A.out, 'doigts_modele.npz')
if os.path.isfile(_doigts_npz):
    os.remove(_doigts_npz)
if A.pre_pose or A.conformer in ('non', '0'):
    log('conformation to the skeleton: not requested')
elif _RIG is None:
    log('conformation to the skeleton: no rig in the model -> fit only')
else:
    try:
        import importlib.util as _ilu_c
        _sp_c = _ilu_c.spec_from_file_location(
            'conformer_squelette', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                'conformer_squelette.py'))
        _cs = _ilu_c.module_from_spec(_sp_c)
        _sp_c.loader.exec_module(_cs)
        _tetes = _RIG['tetes']
        _carte = _cs.cartographier(_RIG['noms'], _RIG['parents'], _tetes, log=log)
        _cou = set(_carte.values())
        _ess = ['bip01 pelvis', 'bip01 head', 'bip01 l upperarm', 'bip01 r upperarm',
                'bip01 l forearm', 'bip01 r forearm', 'bip01 l hand', 'bip01 r hand',
                'bip01 l thigh', 'bip01 r thigh', 'bip01 l calf', 'bip01 r calf']
        _manque = [b for b in _ess if b not in _cou]
        if _manque:
            raise RuntimeError('essential bones not recognised: %s (rig bones: %s)'
                               % (', '.join(_manque), ', '.join(_RIG['noms'][:12])))
        # weights of the model's RIG (the vertex groups carry the bone names)
        _ix_os = {n: i for i, n in enumerate(_RIG['noms'])}
        _vg = {g.index: _ix_os.get(g.name, -1) for g in src.vertex_groups}
        _nv = len(src.data.vertices)
        _K = 8
        _I = _np.full((_nv, _K), -1, _np.int64)
        _Wt = _np.zeros((_nv, _K))
        for _v in src.data.vertices:
            _gs = sorted(((_vg.get(g.group, -1), g.weight) for g in _v.groups
                          if g.weight > 1e-5 and _vg.get(g.group, -1) >= 0), key=lambda t: -t[1])[:_K]
            for _k2, (_b, _w) in enumerate(_gs):
                _I[_v.index, _k2] = _b
                _Wt[_v.index, _k2] = _w
        _sans = int((_I[:, 0] < 0).sum())       # vertices without any rig weight
        if _sans > 0.5 * _nv:
            raise RuntimeError('%d vertices out of %d have no rig weight: rig and mesh do not '
                               'belong together' % (_sans, _nv))
        if _sans:
            _I, _Wt, _nc = _cs.completer_poids(_points_src(), _I, _Wt)
        _P0 = _points_src()
        # the rig must FIT the mesh: each recognised bone dominates vertices close to it
        _dom = _I[:, 0]
        _ecarts = []
        for _b in _carte:
            _sel = _dom == _b
            if _sel.sum() >= 5:
                _ecarts.append(float(_np.median(_np.linalg.norm(_P0[_sel] - _tetes[_b], axis=1))))
        _haut = float((_vmax - _vmin)[_axe_h])
        if not _ecarts or _np.median(_ecarts) > 0.15 * _haut:
            raise RuntimeError('the rig does not fit the mesh (median bone-vertex distance %.3f '
                               'for a height of %.3f)' % (float(_np.median(_ecarts or [9])), _haut))
        _skel_van = os.path.join(A.vanilla, '0x461356AE.ch_spidermanskeleton_ch_spiderman000.skel')
        import importlib as _il_c
        _fmt_c = _il_c.import_module('bl_ext.user_default.sm3_blender_toolkit.sm3_format')
        _cib = _cs.cibles_depuis_skel(_skel_van, _fmt_c)
        _P2, _Mos, _rap = _cs.conformer(_P0, _I, _Wt, _RIG['noms'], _RIG['parents'], _tetes,
                                        _carte, _cib, log=log, sol=float(_vmin[_axe_h]),
                                        haut=_axe_h)
        _cs.resume(_rap, _carte, log=log)
        if not _np.all(_np.isfinite(_P2)):
            raise RuntimeError('non-finite positions after conformation')
        _co, _dg, _val, _zone = _cs.etiquettes_doigts(_I, _Wt, _carte, _RIG['parents'])
        _co_avant = _np.empty(_nv * 3, _np.float32)
        src.data.vertices.foreach_get('co', _co_avant)
        _inv_mw = _np.array(src.matrix_world.inverted())
        _loc = (_np.c_[_P2, _np.ones(len(_P2))] @ _inv_mw.T)[:, :3]
        src.data.vertices.foreach_set('co', _loc.astype(_np.float32).ravel())
        src.data.update()
        _SP = _points_src()
        log('   conformed model %s .. %s' % (_np.round(_SP.min(0), 3), _np.round(_SP.max(0), 3)))
        # finger labels for mains_poings: side (cote), finger (doigt), share (part), zone
        _np.savez(_doigts_npz, P=_SP.astype(_np.float32), cote=_co, doigt=_dg, part=_val,
                  zone=_zone, version=_np.array(1))
        log('   rig fingers kept for mains_poings: %s'
            % ' '.join('%s%d:%d' % ('lr'[c], D, int(((_co == c) & (_dg == D)).sum()))
                       for c in (0, 1) for D in range(5)))
        import json as _js_c
        with open(_marque, 'w', encoding='utf-8') as _f:
            _js_c.dump({'os_reconnus': len(_carte),
                        'doigts': sum(1 for n in _carte.values() if 'finger' in n),
                        'rig': _RIG['objet'], 'sommets': _nv,
                        'articulations': {n: v for n, v in _rap['os'].items()}}, _f, indent=1)
        _CONFORME = _rap
    except Exception as _ec_c:
        import traceback as _tb_c
        if '_co_avant' in globals() and len(_co_avant) == len(src.data.vertices) * 3:
            src.data.vertices.foreach_set('co', _co_avant)       # give back the plain fit, intact
            src.data.update()
            _SP = _points_src()
        for _f_c in (_marque, _doigts_npz):
            if os.path.isfile(_f_c):
                os.remove(_f_c)
        log('!! conformation to the skeleton abandoned: %s -> fit only' % _ec_c)
        log(_tb_c.format_exc()[-600:])

# ---------------------------------------------------------------- 2 bis. weights by TRANSFER
# Rule of the toolkit's README: "Rename Vertex Groups" gives the VANILLA PIECES their real bone
# names, and a custom model REPLACES those pieces in the collection. The weights must therefore
# come from the game's mesh, transferred SPATIALLY -- no name table, no nearest neighbour by
# centroid. It is Blender's standard operation (Data Transfer), and it works for any source rig
# since the source of the weights is the vanilla itself.
donneur = None                          # "donor": the vanilla pieces joined into one object
_van = [o for o in bpy.data.objects if o.name in set(_noms_van)
        and o.type == 'MESH' and len(o.data.vertices) and len(o.vertex_groups)]
if _van:
    for o in _van:
        bpy.ops.object.select_all(action='DESELECT')
        o.select_set(True); bpy.context.view_layer.objects.active = o
        try:
            bpy.ops.sm3.rename_vertex_groups()
        except Exception as e:
            log('  rename_vertex_groups on %s: %s' % (o.name, e))
    cop = []
    for o in _van:
        n2 = bpy.data.objects.new(o.name + '_DON', o.data.copy())
        sc.collection.objects.link(n2)
        n2.matrix_world = o.matrix_world.copy()
        for g in o.vertex_groups:
            n2.vertex_groups.new(name=g.name)
        cop.append(n2)
    bpy.ops.object.select_all(action='DESELECT')
    for o in cop:
        o.select_set(True)
    bpy.context.view_layer.objects.active = cop[0]
    if len(cop) > 1:
        bpy.ops.object.join()
    donneur = bpy.context.view_layer.objects.active
    donneur.name = 'DONNEUR_VANILLA'
    log('vanilla donor: %d vertices, %d groups, e.g. %s'
        % (len(donneur.data.vertices), len(donneur.vertex_groups),
           [g.name for g in donneur.vertex_groups][:3]))

if donneur is not None:
    for g in list(src.vertex_groups):
        src.vertex_groups.remove(g)
    # WARNING: in `object.data_transfer`, the ACTIVE object is the SOURCE and the selected objects
    # are the destinations. Active = the vanilla donor, selected = our model.
    bpy.ops.object.select_all(action='DESELECT')
    src.select_set(True)
    donneur.select_set(True)
    bpy.context.view_layer.objects.active = donneur
    try:
        r = bpy.ops.object.data_transfer(
            use_object_transform=True, data_type='VGROUP_WEIGHTS', use_create=True,
            vert_mapping='POLYINTERP_NEAREST', layers_select_src='ALL',
            layers_select_dst='NAME', mix_mode='REPLACE')
        log('weight transfer (Data Transfer): %s, %d groups created on the model'
            % (r, len(src.vertex_groups)))
    except Exception as e:
        log('data_transfer failed: %s' % e)
    # normalise: at most 4 bones per vertex, summing to 1
    for v in src.data.vertices:
        top = sorted(((g.group, g.weight) for g in v.groups if g.weight > 1e-4),
                     key=lambda t: -t[1])[:4]
        tot = sum(w for _i, w in top) or 1.0
        for g in v.groups:
            g.weight = 0.0
        for gi, w in top:
            src.vertex_groups[gi].add([v.index], w / tot, 'REPLACE')
    _ut = sorted({g.group for v in src.data.vertices for g in v.groups if g.weight > 1e-4})
    log('  %d bones really used after normalisation' % len(_ut))
    bpy.data.objects.remove(donneur, do_unlink=True)

# ---------------------------------------------------------------- 3-4. atlas by the Material Combiner
sc.sm3mat_source_texture_folder = A.textures
sc.sm3mat_friend_bake_size = A.bake
sc.sm3mat_friend_uv_margin = HQ['marge_pixels'] / A.bake
sc.sm3mat_friend_source_dilate = 24
sc.sm3mat_friend_saturation = A.sat
sc.sm3mat_friend_contrast = A.contraste_bake
sc.sm3mat_friend_auto_setup_sources = True
log('combiner settings: bake %d, margin %.3f, dilate %d, sat %.2f, contrast %.2f'
    % (sc.sm3mat_friend_bake_size, sc.sm3mat_friend_uv_margin, sc.sm3mat_friend_source_dilate,
       sc.sm3mat_friend_saturation, sc.sm3mat_friend_contrast))

# WARNING: a DIFFUSE bake of METAL renders BLACK: a metal has no diffuse lobe, and many materials
# arrive with metallic=1.0. The add-on does not correct it; the atlas came out 91 % black.
_met = 0
for _mat in bpy.data.materials:
    if not _mat.use_nodes:
        continue
    for _nd in _mat.node_tree.nodes:
        if _nd.type == 'BSDF_PRINCIPLED':
            for _cle in ('Metallic', 'Specular IOR Level', 'Specular'):
                _e2 = _nd.inputs.get(_cle)
                if _e2 is not None and not _e2.is_linked and _e2.default_value:
                    _e2.default_value = 0.0
                    _met += 1
if _met:
    log('metallic/specular set to zero on %d input(s)' % _met)

# ---------------------------------------------------------------- 3bis. texel density
# WARNING: on a model assembled from several materials, the UVs are TILED (Messi: u -2.9..20.7,
# v -26.1..4.1). `pack_islands` keeps the RELATIVE sizes of the islands: a single tiled island
# crushes all the others and the atlas fill drops to 1 % (48 % on a healthy model) -> the whole
# character ends up in a 200 px corner and the textures come out smeared.
# We equalise the density BEFORE the bake, on the export layer ONLY: `SM3_SRC_MASTER` is frozen
# here on the AUTHENTIC UVs, otherwise the add-on would copy it from the renormalised UVs and
# read the source textures in the wrong place.
_me = src.data
if not _me.uv_layers:
    log('!! no UV layer: normalisation impossible')
else:
    _me.uv_layers[0].name = 'UVMap'
    _buf = np.empty(len(_me.loops) * 2, np.float32)
    _me.uv_layers['UVMap'].uv.foreach_get('vector', _buf)
    _av = _buf.reshape(-1, 2)
    log('source UVs: u[%.2f..%.2f] v[%.2f..%.2f]'
        % (_av[:, 0].min(), _av[:, 0].max(), _av[:, 1].min(), _av[:, 1].max()))
    _old = _me.uv_layers.get('SM3_SRC_MASTER')
    if _old is not None:
        _me.uv_layers.remove(_old)
    _me.uv_layers.new(name='SM3_SRC_MASTER', do_init=False)
    _me.uv_layers['SM3_SRC_MASTER'].uv.foreach_set('vector', _buf)
    src['sm3_source_uv_master_captured'] = True
    src['sm3_source_uv_master_layer'] = 'SM3_SRC_MASTER'
    _me.uv_layers.active = _me.uv_layers['UVMap']
    for _l in _me.uv_layers:
        _l.active_render = (_l.name == 'UVMap')
    bpy.ops.object.select_all(action='DESELECT')
    src.select_set(True); bpy.context.view_layer.objects.active = src
    # WARNING: EQUALISE ONLY WHEN NEEDED. `average_islands_scale` gives every island the SAME
    # texel density. That is what saves a model with tiled UVs, where one giant island crushes
    # the others. But on a model whose UVs already fit in [0,1], the variable density is WANTED:
    # an artist always gives more texels to the head than to the legs. Measured on this very
    # model: equalising loses 36 % of linear resolution -- 59 % of the texels -- on 4,200
    # triangles between 0.89 and 0.98 of the character's height, that is THE HEAD, while the
    # rest of the body gains 1.17x. We were flattening the face to enlarge the thighs.
    _u0, _u1 = float(_av[:, 0].min()), float(_av[:, 0].max())
    _v0, _v1 = float(_av[:, 1].min()), float(_av[:, 1].max())
    _tuile = not (-0.05 <= _u0 and _u1 <= 1.05 and -0.05 <= _v0 and _v1 <= 1.05)   # tiled UVs?
    if A.egaliser_densite == 'oui':
        _egaliser, _pourquoi = True, 'explicitly requested'
    elif A.egaliser_densite == 'non':
        _egaliser, _pourquoi = False, 'explicitly disabled'
    else:
        _egaliser = _tuile
        _pourquoi = ('tiled UVs (u %.2f..%.2f, v %.2f..%.2f): without equalisation one island '
                     'would crush the others' % (_u0, _u1, _v0, _v1)) if _tuile else (
                     'UVs already in [0,1]: the density chosen by the author is kept, '
                     'the head keeps its resolution')
    if not _egaliser:
        log('island density NOT equalised -- %s' % _pourquoi)
    try:
        if not _egaliser:
            raise StopIteration
        log('island density equalised -- %s' % _pourquoi)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.select_all(action='SELECT')
        _r = bpy.ops.uv.average_islands_scale()
        bpy.ops.object.mode_set(mode='OBJECT')
        _me.uv_layers['UVMap'].uv.foreach_get('vector', _buf)
        _ap = _buf.reshape(-1, 2)
        log('density equalised %s: u[%.2f..%.2f] v[%.2f..%.2f]'
            % (_r, _ap[:, 0].min(), _ap[:, 0].max(), _ap[:, 1].min(), _ap[:, 1].max()))
    except StopIteration:
        pass
    except Exception as _e3:
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass
        log('average_islands_scale failed: %s' % _e3)


bpy.ops.object.select_all(action='DESELECT')
src.select_set(True); bpy.context.view_layer.objects.active = src

# ---------------------------------------------------------------- MANUAL assignment
if A.materiaux:
    demande = {}                        # material name -> image file ("demande" = requested)
    for _p in A.materiaux.split(','):
        if '=' in _p:
            _k, _v = _p.split('=', 1)
            demande[_k.strip()] = _v.strip()
    log('manual assignment requested for %d material(s)' % len(demande))
    _pose = 0
    for _sl in src.material_slots:
        _m = _sl.material
        if _m is None:
            continue
        _f = demande.get(_m.name) or demande.get(_m.name.split('.')[0])
        if not _f:
            continue
        _chemin = _f if os.path.isabs(_f) else os.path.join(A.textures, _f)
        if not os.path.exists(_chemin):
            log('  !! %s: "%s" not found' % (_m.name, _chemin))
            continue
        _m.use_nodes = True
        _nt = _m.node_tree
        _b = next((n for n in _nt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if _b is None:
            _b = _nt.nodes.new('ShaderNodeBsdfPrincipled')
        # WARNING: DISCONNECT first: an imported model often has a flat colour or a Mix node on
        # Base Color, and a second link does not replace the first.
        for _l in list(_b.inputs['Base Color'].links):
            _nt.links.remove(_l)
        _tx = _nt.nodes.new('ShaderNodeTexImage')
        _tx.image = bpy.data.images.load(_chemin, check_existing=True)
        _nt.links.new(_tx.outputs['Color'], _b.inputs['Base Color'])
        for _cle, _val in (('Metallic', 0.0), ('Specular IOR Level', 0.0)):
            if _cle in _b.inputs and not _b.inputs[_cle].is_linked:
                _b.inputs[_cle].default_value = _val
        _pose += 1
        log('  %s <- %s' % (_m.name, os.path.basename(_chemin)))
    log('%d image(s) wired by hand' % _pose)

# WARNING: `auto_setup_source_textures` resolves the diffuse images BY FILE NAME. On a model that
# is already wired -- a UDIM unwrap prepared by `prep_udim.py` (an experimental tool, not
# shipped), for example -- it recognises nothing and the `require_all_sources` safeguard makes
# the whole bake fail ("N used material slot(s) have no diffuse image"). So we first check
# whether every USED slot already carries an image on Base Color.
def _image_en_amont(entree, vus=None):
    """("image upstream") Walk the node graph up from an input: the glTF importer often puts a
    Mix node between the Image Texture and Base Color, so a test on the direct link misses it."""
    vus = vus if vus is not None else set()
    for _l in entree.links:
        nd = _l.from_node
        if nd.as_pointer() in vus:
            continue
        vus.add(nd.as_pointer())
        if getattr(nd, 'image', None) is not None:
            return nd.image
        for e in nd.inputs:
            im = _image_en_amont(e, vus)
            if im is not None:
                return im
    return None


_slots_utilises = sorted({p.material_index for p in src.data.polygons})
_sans_image = []
for _i in _slots_utilises:
    _m = src.material_slots[_i].material if _i < len(src.material_slots) else None
    _im = None
    if _m is not None and _m.use_nodes and _m.node_tree:
        for _n in _m.node_tree.nodes:
            if _n.type == 'BSDF_PRINCIPLED':
                _im = _image_en_amont(_n.inputs['Base Color'])
    if _im is None:
        _sans_image.append((_i, _m.name if _m else 'empty'))
    else:
        log('  slot %d "%s" -> diffuse "%s" (%dx%d)'
            % (_i, _m.name[:22], _im.name[:30], _im.size[0], _im.size[1]))
log('%d slot(s) used, %d without an image on Base Color %s'
    % (len(_slots_utilises), len(_sans_image), _sans_image if _sans_image else ''))
if not _sans_image:
    sc.sm3mat_friend_auto_setup_sources = False
    log('every diffuse image is already wired: auto_setup_source_textures skipped')
else:
    try:
        r = bpy.ops.sm3mat.auto_setup_source_textures()
        log('auto_setup_source_textures:', r)
    except Exception as e:
        log('auto_setup_source_textures failed:', e)
# WARNING: AFTER `auto_setup_source_textures` and the manual assignment, not before: a material
# we would have dropped could still receive its image here. What is still image-less at this
# point will never have one; decals are then dropped by themselves and the bake goes on.
hq.jeter_decalques(src, HQ, log)
hq.validate_materials(src, HQ, log)
# WARNING: AFTER validation, BEFORE the bake: the toolkit's add-on requires one image per used
# slot. Flat-colour pieces get a flat image of their own Base Color here.
hq.peindre_couleurs_unies(src, log)
# WARNING: re-assert the active object before EVERY operator: `auto_setup_source_textures` and
# the deletion of the donor leave the context without an active object, and the add-on then
# crashes on "'NoneType' object has no attribute 'data'".
bpy.ops.object.select_all(action='DESELECT')
src.select_set(True); bpy.context.view_layer.objects.active = src
# WARNING: `create_friend_baked_atlas` EMPTIES the material slots and puts every face back on
# index 0 (apply_preview_material). The materials survive in bpy.data, but the per-face
# ASSIGNMENT is lost: without this snapshot nothing else could be baked afterwards.
_mats_src = [sl.material for sl in src.material_slots]
_idx_src = _np.empty(len(src.data.polygons), _np.int32)
src.data.polygons.foreach_get('material_index', _idx_src)
r = bpy.ops.sm3mat.create_friend_baked_atlas(directory=A.out)
if 'FINISHED' not in r:
    raise RuntimeError('HQ: bake cancelled, conversion stopped.')
hq.validate_atlas(src, A.out, HQ)
log('create_friend_baked_atlas:', r)

# ------------------------------------------------ 4 ter. UVs on the game grid, then re-bake
# WARNING: the operator above unwrapped AND baked in one go, with floating-point UVs. The
# export, however, rounds the UVs to the thousandth (the vertex shader does o2.xy = 0.001 * v1).
# The content would thus be painted in one place and sampled in another: 1.56 texels of offset
# on average at 4096, for triangles of 37 texels -- enough to twist the web lines at every border.
# We keep its LAYOUT, snap the UVs to the grid, and re-bake the diffuse on it: the distortion
# becomes the same on both sides and cancels out.
if A.uv_grille:
    _mat_apercu = [sl.material for sl in src.material_slots]
    _idx_apercu = _np.empty(len(src.data.polygons), _np.int32)
    src.data.polygons.foreach_get('material_index', _idx_apercu)
    try:
        import importlib.util as _ilu2
        _sp2 = _ilu2.spec_from_file_location(
            'atlas_recuit', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         'atlas_recuit.py'))
        _ar = _ilu2.module_from_spec(_sp2); _sp2.loader.exec_module(_ar)
        _ar.arrondir_uv(src, 'UVMap', 1000.0, lambda *x: log(*x))
        _png = _ar.recuire(src, _mats_src, _idx_src, A.bake, A.out, lambda *x: log(*x))
        # replace the atlas where the rest of the chain will look for it
        import shutil as _sh
        for _nom in ('SM3_Spider_Baked_Atlas_atlas_final.png', 'atlas_final.png', 'atlas.png'):
            _c = os.path.join(A.out, _nom)
            if os.path.isfile(_c):
                _sh.copy2(_png, _c)
                log('   atlas replaced by the re-baked version: %s' % _nom)
        # the black suit reads the IMAGE back, not the file: update it too
        _fin = bpy.data.images.get('SM3_Spider_Baked_Atlas_FINAL')
        _neuf = bpy.data.images.get('SM3_ATLAS_RECUIT')
        if _fin is not None and _neuf is not None and tuple(_fin.size) == tuple(_neuf.size):
            _tmp = _np.empty(_neuf.size[0] * _neuf.size[1] * 4, dtype=_np.float32)
            _neuf.pixels.foreach_get(_tmp)
            _fin.pixels.foreach_set(_tmp)
            _fin.update()
            log('   image SM3_Spider_Baked_Atlas_FINAL updated (black suit path)')
    except Exception as _e6:
        import traceback as _tb2
        log('!! re-bake on the grid failed, original atlas kept: %s' % _e6)
        log(_tb2.format_exc()[-700:])
    finally:
        # give the scene back exactly in the state the rest of the chain expects
        src.data.materials.clear()
        for _m in _mat_apercu:
            src.data.materials.append(_m)
        src.data.polygons.foreach_set('material_index', _idx_apercu.tolist())
        src.data.update()

# ---------------------------------------------------------------- 4 bis. normal map
# The suit's specular is HARD-CODED in the material (strength 0.20, exponent 12.8) and the
# environment is multiplied by zero: the normal map is the only texture that still acts on the
# shading. Baking it for real is the only way to break the uniform varnish.
if A.normale and not os.path.isfile(os.path.join(os.path.dirname(__file__), 'normale_bake.py')):
    log('Normal map not generated: optional module missing; mesh normals kept.')
if A.normale and os.path.isfile(os.path.join(os.path.dirname(__file__), 'normale_bake.py')):
    _mat_atlas = [sl.material for sl in src.material_slots]
    try:
        import importlib.util as _ilu
        _sp = _ilu.spec_from_file_location(
            'normale_bake', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'normale_bake.py'))
        _nb = _ilu.module_from_spec(_sp); _sp.loader.exec_module(_nb)
        _tan, _obj = _nb.cuire(src, _mats_src, _idx_src, A.bake, A.out, lambda *x: log(*x),
                               force_deduite=A.normale_force)
        log('normal map baked: %s' % os.path.basename(_tan))
    except Exception as _e5:
        import traceback as _tb
        log('normal map bake failed: %s' % _e5)
        log(_tb.format_exc()[-800:])
    # put the atlas and the flat assignment back for the rest of the chain
    src.data.materials.clear()
    for _m in _mat_atlas:
        src.data.materials.append(_m)
    src.data.polygons.foreach_set('material_index', _np.zeros(len(src.data.polygons), _np.int32))
    src.data.update()

# ---------------------------------------------------------------- 5. preparation
bpy.ops.object.select_all(action='DESELECT')
src.select_set(True); bpy.context.view_layer.objects.active = src
bpy.ops.object.select_all(action='DESELECT')
src.select_set(True); bpy.context.view_layer.objects.active = src
try:
    r = bpy.ops.sm3.prepare_spider_atlas_section()
    log('prepare_spider_atlas_section:', r)
except Exception as e:
    log('prepare_spider_atlas_section failed:', e)

# ---------------------------------------------------------------- 6. DEDICATED export
# WARNING: the exporter applies ITS OWN axis conversion: Y-up geometry comes out lying down.
# Counter-rotation of -90 deg around X, at the very last moment (at +90 the character comes out
# upside down).
from mathutils import Matrix as _Mx2
import math as _mt2
for _o in [o for o in bpy.data.objects if o.type == 'MESH' and o.name.startswith('NOTRE')]:
    _o.data.transform(_Mx2.Rotation(_mt2.radians(-90), 4, 'X'))
    _o.data.update()
log('final counter-rotation applied for the exporter')

# WARNING: UV DIVISOR: the toolkit's exporter encodes uv*1024, but the suit's vertex shader
# (006a19b0_vs30_169i.bin) does "mul o2.xy, c235.x, v1" with "def c235, 0.001" -- that is /1000.
# The same shader does "mad r0, v0.xyzx, c236.yyyz" with 0.00195312 = 1/512 for the POSITION,
# which matches our known encoding and validates the reading. At /1024 the whole atlas came out
# 2.4 % too large and the 1.9 % beyond 1.0 wrapped onto the opposite edge (ADDRESSU/V = WRAP).
# Corroboration on the vanilla: its sections 0 and 1 go from 12 to 990, i.e. 0.012..0.990 at
# /1000 -- a clean unwrap; at /1024 3.3 % would stay unused at the top.
# (An installed toolkit already patched to 1000 logs the "unexpected defaults" line instead.)
try:
    import bl_ext.user_default.sm3_blender_toolkit.sm3_mesh_writer as _mw
    _f = _mw.encode_player_vertex
    if _f.__defaults__ and _f.__defaults__[0] == 1024.0:
        _f.__defaults__ = (1000.0,) + _f.__defaults__[1:]
        log('UV divisor forced to 1000 (the toolkit wrote 1024)')
    else:
        log('!! unexpected defaults on encode_player_vertex: %s' % (_f.__defaults__,))
except Exception as _e4:
    log('!! cannot force the UV divisor: %s' % _e4)

outp = os.path.join(A.out, '0xAC92103D.ch_spiderman000.mesh')
try:
    r = bpy.ops.export_scene.sm3_prepared_spider_atlas(filepath=outp)
    if 'FINISHED' not in r:
        raise RuntimeError('Export of the 000 cancelled')
    log('dedicated export:', r)
except Exception as e:
    raise RuntimeError('HQ: export of the 000 mesh failed') from e
# ---------------------------------------------------------------- 6 bis. the 001 LOD, a REAL one
# WARNING: we used to deliver `0xAC92103E.ch_spiderman001.mesh` as a BYTE-FOR-BYTE COPY of the
# 000. That is wrong on three counts: the internal hash stayed 0xAC92103D, the `skeleton_ref`
# stayed 0x1730 instead of 0x21C0, and material 0x614 does not exist in the LOD 1 table (it holds
# 0x3cc, 0xcc, 0x560, 0x28, 0x4b8). The toolkit has a DEDICATED exporter for it, going through
# section 3 and material 0x00000560 -- and its own comment says: "The proven working CH_SPIDERMAN
# mod replaces BOTH ch_spiderman000 and ch_spiderman001."
# First-hand reference, TSGAMING264's mod: its 001 does carry hash 0xAC92103E, skeleton_ref
# 0x21C0 and a material from the 001's table.
# (The converter's `lod` stage then rewrites the 001 with transplanter_lod.py.)
outp001 = os.path.join(A.out, '0xAC92103E.ch_spiderman001.mesh')
try:
    bpy.ops.object.select_all(action='DESELECT')
    for _o in [o for o in bpy.data.objects if o.type == 'MESH'
               and o.get('sm3_spider_atlas_prepared', False)]:
        _o.select_set(True)
        bpy.context.view_layer.objects.active = _o
    r = bpy.ops.export_scene.sm3_prepared_spider_atlas_001(filepath=outp001)
    if 'FINISHED' not in r:
        raise RuntimeError('Export of the 001 cancelled')
    log('export of the 001 LOD:', r)
    if os.path.exists(outp001):
        _m = fmt001 = None
        log('  LOD 001: %d bytes' % os.path.getsize(outp001))
except Exception as e:
    raise RuntimeError('HQ: export of the 001 mesh failed') from e

if os.path.exists(outp):
    log('EXPORT %s (%d bytes)' % (outp, os.path.getsize(outp)))
    j = outp + '.export.json'           # the exporter's own report
    if os.path.exists(j):
        import json
        rep = json.load(open(j))
        log('  sections %s, vertices %s, mode %s'
            % (rep.get('output_section_count'), rep.get('vertex_count'), rep.get('layout_mode')))
        for d in rep.get('section_decisions', []):
            log('   section %s: mat %s, %s v, %s tris, palette %s'
                % (d.get('output_section'), d.get('material_ref_serialized'), d.get('vertex_count'),
                   d.get('triangle_count'), d.get('bone_palette_count')))
else:
    log('NO FILE WRITTEN')
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(A.out, 'chaine.blend'))
log('finished.')
