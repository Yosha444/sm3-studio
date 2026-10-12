# SPDX-License-Identifier: GPL-3.0-or-later
"""Custom Venom atlas, baked with the same HQ settings as the Spider-Man conversion.

Runs inside Blender (called by venom_custom.py). The bake itself is done by TSGAMING264's
"SM3 Material Combiner" add-on (operator sm3mat.create_friend_baked_atlas); this function
prepares the scene so that the add-on gets a usable model, then checks its output (qualite_hq).
"""
import bpy
import numpy as np
import numpy as _np
import os
from types import SimpleNamespace
import qualite_hq as hq

def bake(src, out, textures, materiaux, HQ):
    import addon_utils
    if not hasattr(bpy.context.scene,'sm3mat_source_texture_folder'):
        addon_utils.enable('bl_ext.user_default.sm3_material_combiner',default_set=False)
    A=SimpleNamespace(out=str(out),textures=textures,materiaux=materiaux,bake=HQ['resolution'],sat=1.0,contraste_bake=1.0)
    sc=bpy.context.scene
    def log(*args): print('[venom atlas]',*args,flush=True)
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

    # WARNING: a DIFFUSE bake of a METAL gives BLACK: a metal has no diffuse lobe, and many
    # materials arrive with metallic=1.0. The add-on does not correct it; the atlas came out 91 % black.
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
        log('metallic/specular reset to zero on %d input(s)' % _met)

    # ---------------------------------------------------------------- 3bis. texel density
    # WARNING: on a model assembled from several materials, the UVs are TILED (Messi: u -2.9..20.7,
    # v -26.1..4.1). `pack_islands` keeps the RELATIVE sizes of the islands: one tiled island
    # crushes all the others and the atlas fill drops to 1 % (48 % on a healthy model) ->
    # the whole character ends up in a 200 px corner and the textures come out blurry.
    # The density is equalised BEFORE the bake, on the export layer ONLY: `SM3_SRC_MASTER` is
    # frozen here on the AUTHENTIC UVs, otherwise the add-on would copy it from the renormalised
    # UVs and read the source textures in the wrong place.
    _me = src.data
    if not _me.uv_layers:
        log('!! no UV layer: normalisation impossible')
    else:
        _me.uv_layers[0].name = 'UVMap'
        _buf = np.empty(len(_me.loops) * 2, np.float32)
        _me.uv_layers['UVMap'].uv.foreach_get('vector', _buf)
        _av = _buf.reshape(-1, 2)
        log('source UV: u[%.2f..%.2f] v[%.2f..%.2f]'
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
        try:
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.select_all(action='SELECT')
            _r = bpy.ops.uv.average_islands_scale()
            bpy.ops.object.mode_set(mode='OBJECT')
            _me.uv_layers['UVMap'].uv.foreach_get('vector', _buf)
            _ap = _buf.reshape(-1, 2)
            log('density equalised %s: u[%.2f..%.2f] v[%.2f..%.2f]'
                % (_r, _ap[:, 0].min(), _ap[:, 0].max(), _ap[:, 1].min(), _ap[:, 1].max()))
        except Exception as _e3:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass
            log('average_islands_scale failed: %s' % _e3)


    bpy.ops.object.select_all(action='DESELECT')
    src.select_set(True); bpy.context.view_layer.objects.active = src

    # ---------------------------------------------------------------- MANUAL assignment
    # materiaux = "material=image,material=image" typed in Studio (French name kept: it is the
    # --materiaux option of the converter).
    if A.materiaux:
        demande = {}
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
            # WARNING: UNPLUG first: an imported model often has a flat colour or a Mix node on
            # Base Color, and a second link does not replace the first one.
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
        log('%d image(s) linked by hand' % _pose)

    # WARNING: `auto_setup_source_textures` finds the diffuse images BY FILE NAME. On a model that
    # is already wired (a UDIM unwrap prepared by `prep_udim.py`, for example) it recognises nothing
    # and the `require_all_sources` safeguard makes the whole bake fail ("N used material slot(s)
    # have no diffuse image"). So first look whether every USED slot already has an image on Base Color.
    def _image_en_amont(entree, vus=None):
        """Walk the node graph up from an input: the glTF importer often puts a Mix node between
        the Image Texture and Base Color, so a test on the direct link would miss it."""
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
    log('%d used slot(s), %d without an image on Base Color %s'
        % (len(_slots_utilises), len(_sans_image), _sans_image if _sans_image else ''))
    if not _sans_image:
        sc.sm3mat_friend_auto_setup_sources = False
        log('every diffuse is already wired: auto_setup_source_textures skipped')
    else:
        try:
            r = bpy.ops.sm3mat.auto_setup_source_textures()
            log('auto_setup_source_textures:', r)
        except Exception as e:
            log('auto_setup_source_textures failed:', e)
    hq.validate_materials(src, HQ)
    # WARNING: set the active object again before EACH operator: `auto_setup_source_textures` and
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

