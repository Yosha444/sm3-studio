# SPDX-License-Identifier: GPL-3.0-or-later
"""normale_bake.py - bake the NORMAL MAP of the source materials into the atlas unwrap.

("normale" = normal map, "bake" = cuisson.) Imported inside Blender by chaine_officielle.py
(step "4 bis", --normale 1), right after the atlas bake; writes <build>/normale_swizzle.png,
which sm3_convertir.py (red suit) or blacksuit_package.py (black suit) then encodes as
0x61DCA273.normswizzle.tex, always in DXT5.

WHY THIS MODULE EXISTS
----------------------
On the player's suit, every other part of the shading is dead:

  - the specular is multiplied by the material's `+0x50` field, which is **0.000** on
    `ch_spidermanspider` as on `ch_blacksuitspider_black`: `sat(spe.GREEN * 0 + 0.200)` gives
    0.200 for every texel. A specular map would be multiplied by zero there;
  - the cube reflection goes through `+0x60`/`+0x64`, also at zero.

Only the normal map is left. And the texture the game puts there, `_normswizzle` (`0x61DCA273`,
shared by ALL the materials of the suit), is a **flat placeholder**: 32x32, and all its texels
are (R=0, G=132, B=0, A=127), standard deviation exactly 0 on all four channels. The game's suit
therefore never had any relief at all. That is what gives it its smooth, depthless look.

WHAT THE SHADER EXPECTS (pixel shader 006a2918, read from its instructions)
--------------------------------------------------------------------------
    texld r2, v1, s6                    ; the normal map is read with RAW v1 = the model's UVs,
                                        ; without the c30 scale/offset applied to other samplers
    mad r3.xy, c47.x, r2.wyzw, c47.y    ; nx = 2*ALPHA - 1   and   ny = 2*GREEN - 1
    dp2add / rsq / rcp                  ; nz = sqrt(1 - nx^2 - ny^2)
    mul r2.xyz, r3.y, v4                ; ny * binormal
    mad r2.xyz, r3.x, v3, r2            ; + nx * tangent
    mad r2.xyz, r0.w, v2, r2            ; + nz * normal
    nrm r17.xyz, r2                     ; r17 feeds the 4 lights, the ambient, the sun AND the
                                        ; reflection vector of the cube map

Three consequences, all checked on the bytes:

  1. **X is in the ALPHA, Y in the GREEN** -- the DXT5nm swizzle, hence the texture's name.
     DXT1 is therefore IMPOSSIBLE, not merely degraded: without alpha it is 255 everywhere, so
     nx = +1 and the normal becomes the pure tangent (measured angular error: 88.35 degrees).
  2. The material must have an identity tiling for the map to line up. It does:
     `+0x88`/`+0x8C` = 1.00/1.00 and `+0x90`/`+0x94` = 0/0 on the suit's materials.
  3. Red and blue are useless: they are set to zero, which leaves the whole DXT5 budget to the
     green (6 bits) and to the alpha (interpolated separately).

THE GREEN-DIRECTION TRAP
------------------------
The same relief is encoded in two opposite ways depending on the convention:

  - **DirectX**: green goes down when the surface goes up;
  - **OpenGL**:  the reverse.

Getting it wrong breaks nothing visible on a flat area: the webs simply look DUG IN instead of
raised. Two measured facts settle the question:

  - the maps shipped by games (SM3's as well as Web of Shadows') are **DirectX**; Blender expects
    **OpenGL**. So the green is flipped on input.
  - the tangent frame Blender computes on `UVMap` is **identical** to the one the exporter writes
    into the `.mesh`: the exporter stores B = -dP/dv_game (measured -0.960 on the delivered mesh,
    against +0.811 for the vanilla), and since v_game = 1 - v_blender, Blender's bitangent is
    also -dP/dv_game. The bake therefore comes out directly usable.

The convention of EACH image is detected, not assumed: see `convention()`.
"""
import os

import numpy as np

# Image extensions Blender can open and that are accepted as a normal-map source.
EXT_IMAGE = ('.png', '.tga', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.dds')

# How to go from a diffuse's file name to its normal map's. Order matters: the first one that
# names an existing file wins. Covers the usual conventions of rips and exports.
SUFFIXES = (
    ('_dif', '_nor'), ('_dif', '_nrm'), ('_dif', '_n'),
    ('_diff', '_norm'), ('_diffuse', '_normal'), ('_albedo', '_normal'),
    ('_basecolor', '_normal'), ('_base_color', '_normal'),
    ('_col', '_nrm'), ('_c', '_n'), ('_d', '_n'),
)


def convention(pix):
    """'directx' or 'opengl' ('plate' = flat), measured on the image bytes -- never assumed.

    WARNING: `pix` must be oriented LIKE AN IMAGE: row 0 AT THE TOP. Blender's pixel buffer has
    its row 0 AT THE BOTTOM -- it must be flipped BEFORE calling this. Otherwise the vertical
    derivative changes sign, so does the correlation, and the function returns the exact
    opposite of the right answer. A silent error: the relief comes out DUG IN instead of raised.

    A normal map is the gradient of a height. A gradient field is *integrable*: d(gy)/dx must
    equal d(gx)/dy. If those two derivatives are correlated and the correlation is POSITIVE,
    both channels describe the same relief in the same direction -- the DirectX convention. If
    the green was flipped (OpenGL), the correlation becomes negative.

    Calibrated on a synthetic DirectX reference: +1.000, and -1.000 with the green flipped.
    Measured on real maps: SM3 `ch_spiderman_tex1_nor` +0.483, `ch_spidermanlod_tex2_nor`
    +0.809; Web of Shadows redsuit/blacksuit +0.575 to +0.585. All DirectX.
    """
    gx = pix[..., 0].astype(np.float32) - 127.5
    gy = pix[..., 1].astype(np.float32) - 127.5
    # subsample: the correlation is a global statistic, 512x512 is plenty
    pas = max(1, min(gx.shape[0], gx.shape[1]) // 512)
    gx, gy = gx[::pas, ::pas], gy[::pas, ::pas]
    dgy_dx = np.diff(gy, axis=1)[:-1, :]
    dgx_dy = np.diff(gx, axis=0)[:, :-1]
    a, b = dgy_dx.ravel(), dgx_dy.ravel()
    if a.std() < 1e-6 or b.std() < 1e-6:
        return 'plate'                      # uniform image: no relief to orient
    r = float(np.corrcoef(a, b)[0, 1])
    return 'directx' if r > 0 else 'opengl'


def _srgb(lin):
    """Blender gives `image.pixels` in LINEAR; the calibration below was done on sRGB PNGs.
    So we re-encode before measuring the luminance, otherwise the strength would not mean the
    same thing depending on how light the texture is."""
    lin = np.clip(lin, 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1.0 / 2.4) - 0.055)


CIBLE_PENTE = 3.0      # target median slope, degrees ("cible" = target, "pente" = slope)
# WARNING: why 3 degrees, and why a TARGET rather than a fixed gain. The real normal maps of
# Web of Shadows, measured (slope = angle to the vertical):
#     redsuit_tex1 1.31 deg   redsuit_tex2 1.31   blacksuit1_tex2 2.31   blacksuit1_tex1 5.74
# A fixed GAIN cannot suit both families of textures. `force = 10` had been calibrated on WoS's
# photographic diffuse maps, where it lands right: 2.10 deg on redsuit_tex1 (real map 1.31), 6.77
# on blacksuit1_tex1 (real 5.74). On a texture with hard flat areas -- a cel-shaded model, a PS2
# rip -- an edge's gradient is ~1.0 per pixel instead of ~0.004, and the same gain SATURATES:
# measured on the two delivered models `verse` and `suku`, MEDIAN slope 81 deg and 80.6 deg,
# |n_xy| = 0.975 (normals lying flat in the tangent plane), and 6.7 % to 11.7 % of mathematically
# impossible texels (nx^2 + ny^2 > 1). In game: green patches and lighting that breaks at every
# texture edge.
# So we aim at the same MEDIAN slope as the real maps, and derive the gain from it. It is exact,
# not iterative: the slope is atan(scale x |grad|), atan is monotonic, hence
#     median(slope) = atan(scale x median(|grad|))   ->   scale = tan(target) / median(|grad|)


def normale_depuis_diffuse(rgb, force=10.0, rayon=1, cible_deg=None):
    """("normal from the diffuse") Make a normal map from the RELIEF SUGGESTED BY THE DIFFUSE,
    for lack of anything better.

    `rgb`: (h, w, 3) array in 0..1 sRGB, row 0 AT THE TOP. Returns an (h, w, 3) array of unit
    normals, in the DirectX convention -- the same as the games' maps, so the rest of the chain
    flips it like any other source.

    WARNING: WHAT THIS FUNCTION IS WORTH, MEASURED against the real Web of Shadows maps (same
    UVs, same resolution, hence a direct comparison):

    | texture          | real relief | found by the generated map | direction in those areas |
    |------------------|-------------|----------------------------|--------------------------|
    | redsuit_tex1     |   9.7 %     |           83.3 %           |        cos +0.738        |
    | redsuit_tex2     |   8.0 %     |           77.3 %           |        cos +0.777        |
    | blacksuit1_tex1  |  28.4 %     |           72.4 %           |        cos -0.357        |
    | blacksuit1_tex2  |  18.2 %     |           70.2 %           |        cos -0.234        |

    In other words: the diffuse says very well WHERE the detail is, and not always IN WHICH
    DIRECTION. When its shading comes from the geometry (red suit), the direction is right. When
    it comes from highlights PAINTED into the texture (black symbiote suit), it is inverted --
    and an inverted normal digs in what should stand out. Hence a negative `force` to flip it.

    The default sign (light = RAISED) is measured too, not assumed: correlation between the real
    normal and the luminance gradient, -0.45 / -0.54 / -0.22 / -0.32 on the four pairs, both
    axes agreeing. `force = 10` is the value that minimises the angular error to the real map on
    redsuit_tex1 (6.69 deg against 7.99 for a flat map).
    """
    L = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    # light smoothing: without it the diffuse's compression noise gets amplified
    k = 2 * rayon + 1
    pad = np.pad(L, rayon, mode='edge')
    acc = np.zeros_like(L, dtype=np.float64)
    for i in range(k):
        for j in range(k):
            acc += pad[i:i + L.shape[0], j:j + L.shape[1]]
    L = acc / (k * k)
    gx = np.zeros_like(L)
    gy = np.zeros_like(L)
    gx[:, 1:-1] = (L[:, 2:] - L[:, :-2]) * 0.5
    gy[1:-1, :] = (L[2:, :] - L[:-2, :]) * 0.5
    # WARNING: the gradient's scale is PER PIXEL: at twice the resolution, the same detail gives
    # half the slope. We normalise on the 2048 of the calibration.
    if cible_deg:
        # AUTO gain: aim at the median slope of a real map, whatever the texture.
        # Only the SIGN of `force` is kept -- it says whether light stands out or digs in.
        med = float(np.median(np.hypot(gx, gy)))
        echelle = (np.tan(np.radians(cible_deg)) / med) if med > 1e-9 else 0.0
        echelle *= 1.0 if force >= 0 else -1.0
    else:
        echelle = force * (max(L.shape) / 2048.0)
    n = np.stack([-echelle * gx, -echelle * gy, np.ones_like(L)], -1)
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return n


def _image_du_noeud(mat, types):
    """First image found behind a node of the requested type."""
    if not (mat and mat.use_nodes and mat.node_tree):
        return None
    for n in mat.node_tree.nodes:
        if n.type in types and getattr(n, 'image', None) is not None:
            return n.image
    return None


def _normale_du_materiau(mat, log):
    """Find a material's normal map: wired, or deduced from its diffuse's file name.
    Returns (image, where it came from) or (None, None)."""
    # 1. already wired behind a Normal Map node
    if mat and mat.use_nodes and mat.node_tree:
        for n in mat.node_tree.nodes:
            if n.type == 'NORMAL_MAP':
                for lien in n.inputs['Color'].links:
                    img = getattr(lien.from_node, 'image', None)
                    if img is not None:
                        return img, 'wired'
    # 2. deduced from the diffuse's file name
    dif = _image_du_noeud(mat, ('TEX_IMAGE',))
    if dif is None or not dif.filepath:
        return None, None
    import bpy
    chemin = bpy.path.abspath(dif.filepath)
    dossier, fichier = os.path.split(chemin)
    base, ext = os.path.splitext(fichier)
    bas = base.lower()
    for avant, apres in SUFFIXES:
        if not bas.endswith(avant):
            continue
        souche = base[:len(base) - len(avant)] + apres
        for e in (ext,) + EXT_IMAGE:
            cand = os.path.join(dossier, souche + e)
            if os.path.isfile(cand):
                try:
                    return bpy.data.images.load(cand, check_existing=True), 'deduced from %s' % fichier
                except Exception as err:
                    log('   unreadable normal map %s: %s' % (os.path.basename(cand), err))
    return None, None


def _extension_source(mat, img):
    """Edge mode (REPEAT, EXTEND, MIRROR...) of the node that carries `img`, else of the diffuse.

    A DEDUCED normal map (generated image) or one found by its file name has no node of its own:
    it is read on the same UVs as the diffuse, so with the same edge mode.
    """
    if not (mat and mat.use_nodes and mat.node_tree):
        return None
    noeuds = [n for n in mat.node_tree.nodes
              if n.type == 'TEX_IMAGE' and getattr(n, 'image', None) is not None]
    for n in noeuds:
        if n.image == img:
            return n.extension
    return noeuds[0].extension if noeuds else None


def _plan_de_lecture(me, couche_src, index_par_face, nb_materiaux, extensions, log):
    """`atlas_recuit.plan_de_lecture` ("reading plan"): source UVs brought back into the [0,1]
    tile face by face.

    Falls back on the old reading (raw UVs, EXTEND) if the module is missing or fails, with a
    warning: a model with UVs outside [0,1] would then bake a flat normal map.
    """
    try:
        import importlib.util as _ilu
        sp = _ilu.spec_from_file_location(
            'atlas_recuit', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         'atlas_recuit.py'))
        ar = _ilu.module_from_spec(sp)
        sp.loader.exec_module(ar)
        return (ar.plan_de_lecture(me, couche_src, index_par_face, nb_materiaux, extensions, log),
                ar.retirer_couche)
    except Exception as err:
        log('   !! source UVs not brought back into [0,1] (%s): read raw, in EXTEND' % err)
        idx = np.clip(np.asarray(index_par_face, dtype=np.int32), 0, max(0, nb_materiaux - 1))

        def retirer(me_, plan_):
            if 'SM3_SRC_TUILE' in me_.uv_layers:     # in case the failure came after its creation
                me_.uv_layers.remove(me_.uv_layers['SM3_SRC_TUILE'])
        return ({'lots': [(i, couche_src, 'EXTEND') for i in range(nb_materiaux)],
                 'index': idx, 'temporaire': None, 'source': couche_src}, retirer)


def _gain(force):
    """Return (numeric force, target degrees). 'auto' -> aim at the slope of the real maps."""
    if isinstance(force, str):
        f = force.strip().lower()
        if f in ('auto', ''):
            return 1.0, CIBLE_PENTE
        if f.startswith('auto'):                    # "auto:5" to aim at 5 degrees
            try:
                return 1.0, float(f.split(':', 1)[1])
            except (IndexError, ValueError):
                return 1.0, CIBLE_PENTE
        force = float(f)
    return float(force), None


def _fabriquer_depuis_diffuse(mat, force, log):
    """Create a normal-map image from the material's diffuse. None if there is no diffuse."""
    import bpy

    dif = _image_du_noeud(mat, ('TEX_IMAGE',))
    if dif is None or min(dif.size) == 0:
        return None
    w, h = dif.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    dif.pixels.foreach_get(buf)
    # Blender buffer: row 0 AT THE BOTTOM and LINEAR values -> put back upright and in sRGB,
    # the orientation and space in which the calibration was done.
    rgb = _srgb(buf.reshape(h, w, 4)[::-1, :, :3].astype(np.float64))
    f, cible = _gain(force)
    n = normale_depuis_diffuse(rgb, force=f, cible_deg=cible)
    enc = ((n + 1.0) * 0.5).clip(0.0, 1.0)
    nom = 'SM3_NOR_DEDUITE_%s' % mat.name
    old = bpy.data.images.get(nom)
    if old is not None:
        bpy.data.images.remove(old)
    img = bpy.data.images.new(nom, width=w, height=h, alpha=False, float_buffer=True)
    img.colorspace_settings.name = 'Non-Color'
    tampon = np.ones((h, w, 4), dtype=np.float32)
    tampon[..., :3] = enc[::-1]              # flipped back for Blender
    img.pixels.foreach_set(tampon.ravel())
    img.update()
    pente = np.degrees(np.arccos(np.clip(n[..., 2], -1.0, 1.0)))
    log('   normal map DEDUCED from the diffuse for "%s": %s, median slope %.2f deg, p95 %.2f'
        % (mat.name, ('auto gain towards %.1f deg' % cible) if cible else ('force %+.1f' % f),
           float(np.median(pente)), float(np.percentile(pente, 95))))
    # a texture with hard flat areas saturated the fixed gain and came out at a median of 81 deg:
    # the relief turned into vertical noise. We refuse to deliver that silently.
    if float(np.median(pente)) > 25.0:
        log('   !! DEDUCED relief too strong (median %.1f deg, real maps 1.3 to 5.7): '
            'the texture has hard flat areas. Use --normale-force auto, or 0 to deduce nothing.'
            % float(np.median(pente)))
    return img


def cuire(src, materiaux, index_par_face, taille, sortie, log, force_deduite='auto'):
    """("bake") Bake the normal maps of the SOURCE materials into the atlas unwrap.

    `src`            the mesh object, after `create_friend_baked_atlas`
    `materiaux`      the list of SOURCE materials, taken BEFORE the atlas emptied the slots
    `index_par_face` the `material_index` snapshot, taken at the same moment
    `taille`         the atlas side
    `sortie`         the build folder

    Returns `(path_of_the_swizzled_png, preview_path)` (the preview is always None now).
    Raises if the bake is requested but no source is usable -- the caller catches it and goes
    on without a normal map.
    """
    import bpy

    me = src.data
    couche_src = src.get('sm3_source_uv_master_layer') or 'SM3_SRC_MASTER'
    if couche_src not in me.uv_layers:
        raise RuntimeError('source UV layer "%s" missing: nothing to bake' % couche_src)
    if 'UVMap' not in me.uv_layers:
        raise RuntimeError('atlas UV layer "UVMap" missing')

    # ---------------------------------------------------------------- 1. the sources
    normales, manquants = {}, []
    for i, mat in enumerate(materiaux):
        img, origine = _normale_du_materiau(mat, log)
        nom = mat.name if mat else '(empty)'
        if img is None and force_deduite:
            # WARNING: no map provided: rather than leaving the piece flat, we DEDUCE the relief
            # from the diffuse. It is not equivalent -- see the table of measurements in
            # `normale_depuis_diffuse` -- but it is better than the game's flat placeholder, and
            # the strength is adjustable (negative = reversed) for textures with painted shading.
            img = _fabriquer_depuis_diffuse(mat, force_deduite, log)
            origine = 'deduced from the diffuse'
        if img is None:
            manquants.append(nom)
            continue
        normales[i] = img
        log('   normal map of "%s": %s (%s, %dx%d)'
            % (nom, os.path.basename(bpy.path.abspath(img.filepath) or img.name), origine,
               img.size[0], img.size[1]))
    if not normales:
        raise RuntimeError('no normal map found (materials: %s)'
                           % ', '.join(manquants[:6]))
    if manquants:
        log('   !! without a normal map, left flat: %s' % ', '.join(manquants[:6]))

    # ---------------------------------------------------------------- 2. orient each source
    # Blender expects OpenGL. A DirectX source must have its green flipped, otherwise the relief
    # comes out DUG IN instead of raised.
    for i, img in list(normales.items()):
        # WARNING: NEVER REASSIGN `colorspace_settings.name` ON A GENERATED IMAGE. Blender clears
        # its buffer to BLACK on assignment -- even when the value it already has is put back.
        # Measured: a generated 64x64 image filled with a 0..1 gradient comes out at 0.000..0.000,
        # standard deviation 0.0000, after a mere `img.colorspace_settings.name = 'Non-Color'`.
        # That was THE defect: the normal map DEDUCED from the diffuse (hence generated, with no
        # file) arrived black at the bake. The Normal Map node read (0,0,0), i.e. a degenerate
        # normal (-1,-1,-1), and the bake re-encoded it in the tangent frame of EACH island --
        # hence normals lying flat, grouped in four diagonal clusters (the four quarter turns of
        # `pack_islands`), 80.3 % of the atlas beyond 45 deg, and the green patches in game. A
        # map loaded from a FILE was reloaded from disk: that is why only models WITHOUT a normal
        # map were affected.
        if img.colorspace_settings.name != 'Non-Color':
            if img.filepath:
                img.colorspace_settings.name = 'Non-Color'
            else:
                log('   %s: generated, colour space "%s" left as it is (reassigning it would clear it)'
                    % (img.name, img.colorspace_settings.name))
        w, h = img.size
        if w * h == 0:
            log('   !! empty image, ignored: %s' % img.name)
            normales.pop(i)
            continue
        buf = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(buf)
        # `[::-1]`: Blender's buffer starts at the BOTTOM, `convention()` wants an image from the TOP.
        pix = (buf.reshape(h, w, 4)[::-1, :, :3] * 255.0).clip(0, 255).astype(np.uint8)
        conv = convention(pix)
        if conv == 'directx':
            buf = buf.reshape(h, w, 4)
            buf[..., 1] = 1.0 - buf[..., 1]
            img.pixels.foreach_set(buf.ravel())
            img.update()
            log('   %s: DirectX -> green flipped for Blender' % img.name)
        elif conv == 'plate':
            # WARNING: it is DISCARDED instead of baked. A uniform source cannot bring anything,
            # and if it is uniform because it is BLACK (and not because it is flat), baking it
            # produces vertical noise over the whole atlas. Without a map, the material bakes a
            # straight normal: useless, but harmless.
            log('   !! %s: UNIFORM image, discarded (a straight normal is better than noise)'
                % img.name)
            normales.pop(i)
            continue
        else:
            log('   %s: already OpenGL, left as it is' % img.name)

    # ---------------------------------------------------------------- 3. the target
    cible = bpy.data.images.get('SM3_NORMALE_ATLAS')
    if cible is not None:
        bpy.data.images.remove(cible)
    cible = bpy.data.images.new('SM3_NORMALE_ATLAS', width=taille, height=taille,
                                alpha=False, float_buffer=False)
    cible.colorspace_settings.name = 'Non-Color'
    # background = straight normal (0,0,1) encoded: (0.5, 0.5, 1.0)
    cible.pixels.foreach_set(np.tile(np.array([0.5, 0.5, 1.0, 1.0], np.float32), taille * taille))

    # ---------------------------------------------------------------- 4. bake materials
    # WARNING: the source UVs do not always fit in [0,1]: the TASM2 is entirely in v within
    # [-1,0], and read in EXTEND it baked the edge row of each image -- 0.9 % of the atlas in
    # relief. `plan_de_lecture` brings each face back into the tile by an integer offset; a model
    # already in [0,1] keeps exactly the old reading.
    # The tangent frame, however, stays computed on the RAW source layer (`nm.uv_map`): an
    # integer offset does not change its derivatives, but the shifted layer may cut an island in
    # two, and MikkTSpace does not average across a seam.
    extensions = {i: _extension_source(mat, normales[i])
                  for i, mat in enumerate(materiaux) if i in normales}
    plan, retirer = _plan_de_lecture(me, couche_src, index_par_face, len(materiaux),
                                     extensions, log)
    try:
        # WARNING: the source materials and the per-face assignment are PUT BACK:
        # `create_friend_baked_atlas` erased them. Without this snapshot, every face would fall
        # back on slot 0 and the same normal map would be baked everywhere.
        me.materials.clear()
        for lot, (i, couche, extension) in enumerate(plan['lots']):
            img = normales.get(i)
            m = bpy.data.materials.new('SM3_NOR_%d' % lot)
            m.use_nodes = True
            nt = m.node_tree
            nt.nodes.clear()
            out = nt.nodes.new('ShaderNodeOutputMaterial')
            bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
            nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
            if img is not None:
                tex = nt.nodes.new('ShaderNodeTexImage')
                tex.image = img
                tex.interpolation = 'Cubic'
                tex.extension = extension
                uvn = nt.nodes.new('ShaderNodeUVMap')
                uvn.uv_map = couche
                nm = nt.nodes.new('ShaderNodeNormalMap')
                nm.space = 'TANGENT'
                nm.uv_map = couche_src
                nt.links.new(uvn.outputs['UV'], tex.inputs['Vector'])
                nt.links.new(tex.outputs['Color'], nm.inputs['Color'])
                nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])
            # the ACTIVE node of each material designates the bake target
            bake = nt.nodes.new('ShaderNodeTexImage')
            bake.image = cible
            for n in nt.nodes:
                n.select = False
            bake.select = True
            nt.nodes.active = bake
            me.materials.append(m)
        me.polygons.foreach_set('material_index', np.asarray(plan['index'], np.int32).tolist())
        me.update()

        # ------------------------------------------------------------ 5. bake
        # The bake WRITES into the unwrap of the active_render layer: it must be the ATLAS.
        for l in me.uv_layers:
            l.active_render = (l.name == 'UVMap')
        me.uv_layers.active = me.uv_layers['UVMap']

        sc = bpy.context.scene
        moteur, echantillons = sc.render.engine, None
        sc.render.engine = 'CYCLES'
        try:
            echantillons = sc.cycles.samples
            sc.cycles.samples = 1
            sc.cycles.device = 'CPU'
        except Exception:
            pass
        sc.render.bake.use_selected_to_active = False
        sc.render.bake.normal_space = 'TANGENT'
        sc.render.bake.normal_r, sc.render.bake.normal_g, sc.render.bake.normal_b = \
            'POS_X', 'POS_Y', 'POS_Z'
        sc.render.bake.margin = 16
        try:
            sc.render.bake.margin_type = 'EXTEND'
        except Exception:
            pass
        sc.render.bake.use_clear = True

        for ob in bpy.context.view_layer.objects:
            ob.select_set(False)
        src.select_set(True)
        bpy.context.view_layer.objects.active = src
        log('   NORMAL bake %dx%d (source "%s" -> atlas "UVMap")'
            % (taille, taille, couche_src))
        try:
            bpy.ops.object.bake(type='NORMAL')
        finally:
            sc.render.engine = moteur
            if echantillons is not None:
                try:
                    sc.cycles.samples = echantillons
                except Exception:
                    pass
    finally:
        retirer(me, plan)

    buf = np.empty(taille * taille * 4, dtype=np.float32)
    cible.pixels.foreach_get(buf)
    # Blender gives row 0 at the BOTTOM; images are read from the top
    a = buf.reshape(taille, taille, 4)[::-1, :, :3]

    # ---------------------------------------------------------------- 6. DXT5nm swizzle
    n = 2.0 * a - 1.0
    n /= np.linalg.norm(n, axis=2, keepdims=True).clip(1e-6)
    pente = np.degrees(np.arccos(np.clip(n[:, :, 2], -1.0, 1.0)))
    X = ((n[:, :, 0] + 1.0) * 127.5).clip(0, 255)
    Y = ((n[:, :, 1] + 1.0) * 127.5).clip(0, 255)
    out = np.zeros((taille, taille, 4), np.uint8)
    out[:, :, 0] = 0              # RED    unused by the shader
    out[:, :, 1] = Y.astype(np.uint8)   # GREEN = Y   (the shader reads r2.y)
    out[:, :, 2] = 0              # BLUE   unused
    out[:, :, 3] = X.astype(np.uint8)   # ALPHA = X   (the shader reads r2.w)

    # WARNING: write the PNG with BLENDER, not with Pillow: Blender's bundled Python has no PIL,
    # and the import made the whole bake fail ("No module named 'PIL'").
    chemin = os.path.join(sortie, 'normale_swizzle.png')
    ancienne = bpy.data.images.get('SM3_NORMALE_SWIZZLE')
    if ancienne is not None:
        bpy.data.images.remove(ancienne)
    img_out = bpy.data.images.new('SM3_NORMALE_SWIZZLE', width=taille, height=taille, alpha=True)
    img_out.colorspace_settings.name = 'Non-Color'
    # CHANNEL_PACKED: forbids Blender to premultiply the colour by the alpha. Here the alpha is
    # not a transparency, it is the X component of the normal -- premultiplying would destroy the
    # green wherever X is low.
    img_out.alpha_mode = 'CHANNEL_PACKED'
    img_out.pixels.foreach_set((out[::-1].astype(np.float32) / 255.0).ravel())
    img_out.filepath_raw = chemin
    img_out.file_format = 'PNG'
    img_out.save()
    apercu = None

    vif = pente > 1.0
    log('   baked relief: mean slope %.2f deg, p95 %.2f, max %.2f | %.1f %% of the atlas in relief'
        % (pente.mean(), np.percentile(pente, 95), pente.max(), 100.0 * vif.mean()))
    log('   (the game\'s _normswizzle: 2.03 deg CONSTANT, standard deviation 0 -- no relief)')
    if float(pente.std()) < 0.05:
        raise RuntimeError('the baked normal map is UNIFORM (standard deviation %.4f deg): '
                           'it would be no better than the game\'s placeholder' % pente.std())
    log('   GREEN %d..%d (sd %.2f) | ALPHA %d..%d (sd %.2f)'
        % (out[:, :, 1].min(), out[:, :, 1].max(), out[:, :, 1].std(),
           out[:, :, 3].min(), out[:, :, 3].max(), out[:, :, 3].std()))
    return chemin, apercu
