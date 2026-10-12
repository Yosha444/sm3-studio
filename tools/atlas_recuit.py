# SPDX-License-Identifier: GPL-3.0-or-later
"""atlas_recuit.py - snap the UVs to the game's grid, then RE-BAKE the diffuse on them.

("atlas recuit" = "re-baked atlas".) Imported inside Blender by chaine_officielle.py (step
"4 ter", --uv-grille 1), right after the add-on's atlas bake; its plan_de_lecture() is also used
by normale_bake.py. Writes <build>/atlas_recuit.png and the scene image SM3_ATLAS_RECUIT; the
chain then copies them over the add-on's atlas files and its SM3_Spider_Baked_Atlas_FINAL image.

THE PROBLEM, MEASURED
---------------------
The suit's vertex shader does `mul o2.xy, c235.x, v1` with `c235.x = 0.001`: the UVs are stored
in the `.mesh` as **integers divided by 1000**. A mesh can therefore only address ~1000
positions per axis, whatever the atlas size.

Yet the chain bakes the atlas with **floating-point** UVs, and the export **rounds** them
afterwards. The content is thus painted where the floating UVs said, and the game fetches it
where the rounded UVs say. Measured on the delivered mesh (11,016 vertices, 4096 atlas):

    mean offset 1.56 texels, p95 2.43, max 2.87   for a median triangle side of 37 texels

Inside a triangle the interpolation is exact, but two neighbouring triangles shift in different
directions: **every border breaks the line**. That is what makes the web lines wavy --
"spaghettified" -- and what eats the fine grain of the fabric, a regular pattern being precisely
what suffers most from placement noise.

WARNING: SHRINKING THE ATLAS CHANGES NOTHING. The error is 0.5 x (size / 1000) texels, and the
width of the details follows the same scale: at 2048 we measure 0.78 texel of error for
triangles of 18.5 texels, exactly the same ratio. We would lose detail without gaining any
sharpness.

THE FIX
-------
Snap the UVs to the thousandth grid BEFORE baking. The distortion then becomes the SAME on both
sides and cancels out: the game samples exactly where the content was painted. The lines become
straight again, at any atlas resolution.

The toolkit's operator re-unwraps and bakes in one go, so we cannot step in between. We let it
give the LAYOUT, then snap, then re-bake the diffuse ourselves from the source images -- exactly
as `normale_bake.py` already does for normal maps.

The bake uses `type='EMIT'`: pure emission carries the colour without mixing any lighting into
it, which makes it a plain texture transfer from one unwrap to the other.

SOURCE UVS OUTSIDE [0,1]
------------------------
See `plan_de_lecture`: the source UVs are brought back face by face into the [0,1] tile before
reading. `normale_bake.py` uses it too.
"""
import os

import numpy as np

# A face with a corner past the [0,1] tile by more than a thousandth (the step of the game's
# grid) "straddles" a tile border.
TOLERANCE_TUILE = 1e-3
# TEMPORARY UV layer: the source UVs brought back into [0,1]. Removed after each bake.
COUCHE_TUILE = 'SM3_SRC_TUILE'
# Check of the re-bake: a point is correct if no channel differs from the source by more than
# SEUIL_POINT (in 0..1, i.e. ~25/255); the re-bake has failed if fewer than SEUIL_CONFORMES of
# the points are correct. Measured:
#     TASM2, old reading (raw UVs, EXTEND)          1.3 % correct, median difference 0.357 -> refused
#     TASM2, UVs brought back into [0,1]            99.9 %, median difference 0.007 (chain, 4096)
#     Miles (UVs already in [0,1])                  100.0 %, median difference 0.000 (chain, 4096)
#     Miles with images reduced to 0..1 byte        100.0 % (94 % black points); the old test
#                                                   refused it: "almost empty (3.95 %)" (bench 1024)
SEUIL_POINT = 0.10
SEUIL_CONFORMES = 0.50
# WARNING: THE SHARE OF CORRECT POINTS IS NOT ENOUGH. On a suit dominated by one colour, a failed
# reading often lands on the same hue as the source. Measured in the chain on spider-man_2099.glb
# (UVs in v within [-3,-2]) with the old reading (raw UVs, EXTEND): an atlas of blue stripes,
# without the red emblem, gave 75.2 % correct points (median difference 0.067) -- accepted. What
# gives it away is the TAIL of the differences: p90 0.467. So we also refuse above SEUIL_P90.
#     correct bakes (chain, 4096)   p90 0.004 to 0.026 (TASM2, Miles, 2099, TASM1); 0.020 (synthetic
#                                   bench); worst single texture, bilinear against cubic at
#                                   arbitrary positions: 0.098
#     failed readings               p90 0.467 (2099, chain), 0.577 (TASM2, bench 1024)
SEUIL_P90 = 0.25


def arrondir_uv(obj, couche='UVMap', pas=1000.0, log=print):
    """("round the UVs") Put the UVs of `couche` exactly on the grid the `.mesh` can store.

    Returns (mean displacement, max displacement) in UV units.
    """
    me = obj.data
    if couche not in me.uv_layers:
        raise RuntimeError('UV layer "%s" missing' % couche)
    n = len(me.loops)
    buf = np.empty(n * 2, dtype=np.float32)
    me.uv_layers[couche].uv.foreach_get('vector', buf)
    uv = buf.reshape(n, 2).astype(np.float64)
    grille = np.rint(uv * pas) / pas
    ecart = np.linalg.norm(uv - grille, axis=1)
    me.uv_layers[couche].uv.foreach_set('vector', grille.astype(np.float32).ravel())
    me.update()
    log('   UVs put on the game\'s grid (1/%d): mean displacement %.5f, max %.5f'
        % (int(pas), ecart.mean(), ecart.max()))
    return float(ecart.mean()), float(ecart.max())


def _uv(me, couche):
    """UVs of a layer, one row per loop (corner)."""
    n = len(me.loops)
    buf = np.empty(n * 2, dtype=np.float32)
    me.uv_layers[couche].uv.foreach_get('vector', buf)
    return buf.reshape(n, 2).astype(np.float64)


def plan_de_lecture(me, couche, index_par_face, nb_materiaux, extensions, log=print):
    """("reading plan") Say, face by face, with which UVs and which edge mode the SOURCE images
    are read.

    WARNING: THE PROBLEM, MEASURED. The source images were read in `EXTEND` on the raw UVs.
    Outside [0,1], EXTEND copies the image's edge to infinity. The TASM2 has ALL its UVs in v
    within [-1,0] (u 0.007..0.999, v -0.999..-0.004): every face read the same edge row, black.
    Measured in Blender, same bake: 1.18 % of texels carried in EXTEND, 63.4 % in REPEAT. In the
    chain: "re-baked atlas almost empty (2.62 %)", and the normal map baked flat (0.9 % of the
    atlas in relief, against a very real normal map at the source).

    THE FIX. The model was made for an engine that REPEATS its textures (it is the default glTF
    sampler, which Blender's importer translates into `REPEAT`; a new image node is REPEAT too).
    In REPEAT, u and u + 1 address the same texel: shifting a face by an INTEGER changes nothing
    in what it shows. So each face is brought back into the [0,1] tile by the integer offset of
    its centre, and EXTEND reads it correctly.

    Why not REPEAT everywhere: on a model already in [0,1], the cubic filter of the edge texels
    would fetch the OPPOSITE edge of the image. Faces that fit in the tile therefore keep EXTEND
    -- a model already in [0,1] follows EXACTLY the old path, without a temporary layer. Only
    two exceptions:
      - a face that still STRADDLES a tile border (a tiled island, which no integer offset fits
        into [0,1]) is read in REPEAT if its source repeats itself; it goes into a separate bake
        batch, so as not to change the mode of its neighbours;
      - a MIRROR source is read as it is, without offset: an odd offset would flip it.

    `extensions[i]`: edge mode of the source image node of material i (None without an image).
    Returns a dict:
      `lots`        one entry (source material, layer, extension) per bake material;
      `index`       the bake material of each face;
      `temporaire`  the name of the created layer (to remove with `retirer_couche`), or None;
      `source`      the source UV layer.
    """
    nf = len(me.polygons)
    idx = np.clip(np.asarray(index_par_face, dtype=np.int64), 0, max(0, nb_materiaux - 1))
    if idx.shape[0] != nf:
        raise RuntimeError('material assignment: %d faces expected, %d received'
                           % (nf, idx.shape[0]))
    plan = {'lots': [(i, couche, 'EXTEND') for i in range(nb_materiaux)],
            'index': idx.astype(np.int32), 'temporaire': None, 'source': couche}
    if nf == 0 or nb_materiaux == 0:
        return plan

    uv = _uv(me, couche)
    debut = np.empty(nf, np.int64)
    me.polygons.foreach_get('loop_start', debut)
    total = np.empty(nf, np.int64)
    me.polygons.foreach_get('loop_total', total)
    if np.any(np.diff(debut) < 0) or np.any(total < 1):
        raise RuntimeError('unexpected corner order: reading the UVs per face is impossible')
    face_du_coin = np.repeat(np.arange(nf), total)

    centre = np.add.reduceat(uv, debut, axis=0) / total[:, None]
    dec = np.floor(centre)
    dec[(centre >= 0.0) & (centre <= 1.0)] = 0.0          # already in the tile: left alone
    uvt = uv - dec[face_du_coin]
    bas = np.minimum.reduceat(uvt, debut, axis=0)
    haut = np.maximum.reduceat(uvt, debut, axis=0)
    cheval = ((bas < -TOLERANCE_TUILE) | (haut > 1.0 + TOLERANCE_TUILE)).any(axis=1)   # straddling
    miroir = np.array([extensions.get(i) == 'MIRROR' for i in range(nb_materiaux)])
    repete = np.array([extensions.get(i) == 'REPEAT' for i in range(nb_materiaux)])
    bouge = (dec != 0.0).any(axis=1) & ~miroir[idx]
    if not bouge.any() and not (cheval & ~miroir[idx]).any():
        for i in np.flatnonzero(miroir):
            plan['lots'][i] = (int(i), couche, 'MIRROR')
        return plan

    lecture = couche
    if bouge.any():
        vieille = me.uv_layers.get(COUCHE_TUILE)
        if vieille is not None:
            me.uv_layers.remove(vieille)
        neuve = me.uv_layers.new(name=COUCHE_TUILE, do_init=False)
        if neuve is None:
            # WARNING: Blender caps UV layers at 8 and returns None beyond. Without a shifted
            # layer, the best left is to read in REPEAT every material whose source repeats.
            log('   !! already 8 UV layers: source UVs not brought back into [0,1], read in REPEAT')
            for i in range(nb_materiaux):
                touche = (bouge | cheval)[idx == i].any()
                ext = 'MIRROR' if miroir[i] else ('REPEAT' if (repete[i] and touche) else 'EXTEND')
                plan['lots'][i] = (i, couche, ext)
            return plan
        uvt[miroir[idx][face_du_coin]] = uv[miroir[idx][face_du_coin]]
        neuve.uv.foreach_set('vector', uvt.astype(np.float32).ravel())
        lecture = plan['temporaire'] = COUCHE_TUILE

    lots = []
    for i in range(nb_materiaux):
        lots.append((i, couche, 'MIRROR') if miroir[i] else (i, lecture, 'EXTEND'))
    nouvel_index = idx.copy()
    a_part = 0
    for i in np.flatnonzero(repete & ~miroir):
        sel = cheval & (idx == i)
        if sel.any():
            nouvel_index[sel] = len(lots)
            lots.append((int(i), lecture, 'REPEAT'))
            a_part += int(sel.sum())
    plan['lots'], plan['index'] = lots, nouvel_index.astype(np.int32)

    sans_repeat = int((cheval & ~miroir[idx] & ~repete[idx]).sum())
    log('   source UVs outside [0,1]: %d face(s) out of %d brought back into the tile (integer offset, '
        'u %.2f..%.2f v %.2f..%.2f -> u %.2f..%.2f v %.2f..%.2f)'
        % (int(bouge.sum()), nf, uv[:, 0].min(), uv[:, 0].max(), uv[:, 1].min(), uv[:, 1].max(),
           uvt[:, 0].min(), uvt[:, 0].max(), uvt[:, 1].min(), uvt[:, 1].max()))
    if a_part:
        log('   %d face(s) straddling a tile border: read in REPEAT, like their source'
            % a_part)
    if sans_repeat:
        log('   !! %d straddling face(s) whose source does not repeat: read in EXTEND (stretched edge)'
            % sans_repeat)
    return plan


def retirer_couche(me, plan):
    """("remove the layer") Remove `plan_de_lecture`'s temporary layer. Harmless if it does not
    exist.

    WARNING: TO DO before the export: the toolkit's exporter takes the first "active_render"
    layer not named SM3_SRC*, and a forgotten layer could one day pass for the atlas.
    """
    nom = plan.get('temporaire') if plan else None
    if nom and nom in me.uv_layers:
        me.uv_layers.remove(me.uv_layers[nom])
    if 'UVMap' in me.uv_layers:
        me.uv_layers.active = me.uv_layers['UVMap']


def _srgb(lin):
    """Linear -> sRGB transfer function."""
    lin = np.clip(lin, 0.0, 1.0)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1.0 / 2.4) - 0.055)


def _echantillonner(px, uv, mode):
    """("sample") Bilinear read of `px` (h, w, c; row 0 AT THE BOTTOM, like Blender's buffer)."""
    h, w = px.shape[:2]
    x = uv[:, 0] * w - 0.5
    y = uv[:, 1] * h - 0.5
    x0 = np.floor(x)
    y0 = np.floor(y)
    fx = (x - x0)[:, None]
    fy = (y - y0)[:, None]
    x0 = x0.astype(np.int64)
    y0 = y0.astype(np.int64)

    def borne(i, n):
        """Texel index i folded into [0, n) according to the edge mode."""
        if mode == 'REPEAT':
            return np.mod(i, n)
        if mode == 'MIRROR':
            m = np.mod(i, 2 * n)
            return np.where(m < n, m, 2 * n - 1 - m)
        return np.clip(i, 0, n - 1)

    xa, xb = borne(x0, w), borne(x0 + 1, w)
    ya, yb = borne(y0, h), borne(y0 + 1, h)
    return ((px[ya, xa] * (1 - fx) + px[ya, xb] * fx) * (1 - fy)
            + (px[yb, xa] * (1 - fx) + px[yb, xb] * fx) * fy)


def _points_couverts(tri, taille, pas):
    """("covered points") Points of a grid (one texel out of `pas`) covered by the triangles
    `tri` (T, 3, 2) in UV.

    Returns (triangle, ix, iy, l0, l1, l2): the barycentric coordinates of each covered point.
    The texel centre (ix*pas, iy*pas) is the one the bake computed.
    """
    n = (taille + pas - 1) // pas
    p = tri * float(taille)                                   # in pixels
    gx0 = np.ceil((p[:, :, 0].min(1) - 0.5) / pas).astype(np.int64).clip(0, n - 1)
    gx1 = np.floor((p[:, :, 0].max(1) - 0.5) / pas).astype(np.int64).clip(-1, n - 1)
    gy0 = np.ceil((p[:, :, 1].min(1) - 0.5) / pas).astype(np.int64).clip(0, n - 1)
    gy1 = np.floor((p[:, :, 1].max(1) - 0.5) / pas).astype(np.int64).clip(-1, n - 1)
    bw, bh = gx1 - gx0 + 1, gy1 - gy0 + 1
    ax, bx, cx = p[:, 0, 0], p[:, 1, 0], p[:, 2, 0]
    ay, by, cy = p[:, 0, 1], p[:, 1, 1], p[:, 2, 1]
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    utiles = np.flatnonzero((bw > 0) & (bh > 0) & (np.abs(den) > 1e-12))
    utiles = utiles[np.argsort(bw[utiles] * bh[utiles], kind='stable')]
    sortie = [[] for _ in range(6)]
    k = 0
    while k < len(utiles):
        # batches of triangles of similar size: at most ~2 M points evaluated at once
        cw = np.maximum.accumulate(bw[utiles[k:]])
        ch = np.maximum.accumulate(bh[utiles[k:]])
        cout = np.arange(1, cw.size + 1) * cw * ch
        fin = k + max(1, int(np.searchsorted(cout, 2_000_000, side='right')))
        t = utiles[k:fin]
        mw, mh = int(bw[t].max()), int(bh[t].max())
        X = gx0[t][:, None, None] + np.arange(mw)[None, None, :]
        Y = gy0[t][:, None, None] + np.arange(mh)[None, :, None]
        px = X * pas + 0.5
        py = Y * pas + 0.5
        d = den[t][:, None, None]
        l0 = ((by[t] - cy[t])[:, None, None] * (px - cx[t][:, None, None])
              + (cx[t] - bx[t])[:, None, None] * (py - cy[t][:, None, None])) / d
        l1 = ((cy[t] - ay[t])[:, None, None] * (px - cx[t][:, None, None])
              + (ax[t] - cx[t])[:, None, None] * (py - cy[t][:, None, None])) / d
        l2 = 1.0 - l0 - l1
        dedans = ((l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
                  & (X <= gx1[t][:, None, None]) & (Y <= gy1[t][:, None, None]))
        q, j, i = np.nonzero(dedans)
        sortie[0].append(t[q])
        sortie[1].append(X[q, 0, i])
        sortie[2].append(Y[q, j, 0])
        sortie[3].append(l0[q, j, i])
        sortie[4].append(l1[q, j, i])
        sortie[5].append(l2[q, j, i])
        k = fin
    if not sortie[0]:
        return tuple(np.empty(0) for _ in range(6))
    return tuple(np.concatenate(s) for s in sortie)


def controler(me, plan, images, cible_px, taille, couche_atlas='UVMap'):
    """("check") Measure the re-bake on the atlas's COVERAGE MASK, not on its colour.

    WARNING: the old test ("RGB sum > 0.004 on more than 5 % of the texels") mixed up two things:
    a BLACK texel and an UNBAKED texel. It would have refused a very dark suit baked perfectly,
    and it counted the 16-texel margin as content.

    Here the atlas's triangles are rasterised: the coverage says WHERE the bake had to write. At
    each covered point (one texel out of `pas`), the source image is read again at the matching
    place -- same barycentric coordinates in the source UVs -- and compared with what the bake
    wrote. An atlas that is black because the source is black is correct; an atlas that is black
    because the reading missed is not.

    WARNING: the reference is read on the RAW source UVs, in REPEAT (MIRROR if the source
    mirrors), never with the bake's plan. Reading again with the plan means comparing the bake
    with itself: measured on the TASM2 with the old reading (raw UVs, EXTEND), such a check gave
    100 % correct points on a half-black atlas.

    Returns a dict (French keys): couverture (fraction of the atlas covered), conformes
    (fraction of the checked points that are correct), ecart_median (median difference),
    ecart_p90, points, noirs (fraction of the covered points that are almost black).
    """
    try:
        me.calc_loop_triangles()
    except AttributeError:
        pass
    nt = len(me.loop_triangles)
    tl = np.empty(nt * 3, np.int64)
    me.loop_triangles.foreach_get('loops', tl)
    tl = tl.reshape(nt, 3)
    tp = np.empty(nt, np.int64)
    me.loop_triangles.foreach_get('polygon_index', tp)
    lot_du_tri = np.asarray(plan['index'], np.int64)[tp]

    pas = max(1, taille // 1024)
    n = (taille + pas - 1) // pas
    uva = _uv(me, couche_atlas)
    t, ix, iy, l0, l1, l2 = _points_couverts(uva[tl], taille, pas)
    if t.size == 0:
        return {'couverture': 0.0, 'conformes': 0.0, 'ecart_median': 1.0, 'ecart_p90': 1.0,
                'points': 0, 'noirs': 0.0}
    t = t.astype(np.int64)
    ix = ix.astype(np.int64)
    iy = iy.astype(np.int64)
    couverture = np.unique(iy * n + ix).size / float(n * n)
    cuit = cible_px[iy * pas, ix * pas, :3]
    noirs = float((cuit.sum(1) <= 0.004).mean())

    ecart = np.full(t.size, np.nan)
    uvs = _uv(me, plan['source'])
    pixels = {}
    for lot, (i, couche, ext) in enumerate(plan['lots']):
        img = images.get(i)
        sel = np.flatnonzero(lot_du_tri[t] == lot)
        if img is None or sel.size == 0 or min(img.size) == 0:
            continue
        tri = tl[t[sel]]
        pos = (uvs[tri[:, 0]] * l0[sel, None] + uvs[tri[:, 1]] * l1[sel, None]
               + uvs[tri[:, 2]] * l2[sel, None])
        cle = img.name
        if cle not in pixels:
            w, h = img.size
            buf = np.empty(w * h * 4, np.float32)
            img.pixels.foreach_get(buf)
            px4 = buf.reshape(h, w, 4)
            rgb = px4[..., :3]
            # WARNING: ALPHA. The bake only wires the colour of the image node: on a STRAIGHT image
            # (the default of an FBX or an OBJ), Cycles then gives the colour PREMULTIPLIED by the
            # alpha, whereas `pixels` gives it straight. Measured (Blender 5.2, RGBA PNG
            # 135/150/120 at alpha 22/255): baked 11/12/10, and 0 % correct points without this
            # product -- a correct reading looked failed. No product in CHANNEL_PACKED (what the
            # glTF importer sets) / NONE, nor on a data image (Non-Color): there the bake gives
            # the colour as it is (measured too).
            cs = img.colorspace_settings
            donnees = bool(getattr(cs, 'is_data', False)) or cs.name in ('Non-Color', 'Raw')
            if (img.alpha_mode in ('STRAIGHT', 'PREMUL') and not donnees
                    and float(px4[..., 3].min()) < 1.0):
                rgb = rgb * px4[..., 3:4]
            pixels[cle] = rgb
            del px4, buf
        src = _echantillonner(pixels[cle], pos, 'MIRROR' if ext == 'MIRROR' else 'REPEAT')
        # WARNING: `pixels` gives the file's BYTES for an 8-bit image (hence sRGB), but LINEAR
        # values for a float image or one declared non-sRGB; the target is sRGB.
        if img.is_float or 'srgb' not in img.colorspace_settings.name.lower():
            src = _srgb(src)
        ecart[sel] = np.abs(src - cuit[sel]).max(1)
    ok = ~np.isnan(ecart)
    if not ok.any():
        return {'couverture': couverture, 'conformes': None, 'ecart_median': None,
                'ecart_p90': None, 'points': 0, 'noirs': noirs}
    e = ecart[ok]
    return {'couverture': couverture, 'conformes': float((e <= SEUIL_POINT).mean()),
            'ecart_median': float(np.median(e)), 'ecart_p90': float(np.percentile(e, 90)),
            'points': int(ok.sum()), 'noirs': noirs}


def recuire(src, materiaux, index_par_face, taille, sortie, log, couche_src=None):
    """("re-bake") Re-bake the DIFFUSE of the source materials into the (now rounded) atlas
    unwrap.

    Same structure as `normale_bake.cuire`, but in pure emission: the colour is carried, no
    lighting is computed. Returns the path of the PNG produced.
    """
    import bpy

    me = src.data
    couche_src = couche_src or src.get('sm3_source_uv_master_layer') or 'SM3_SRC_MASTER'
    if couche_src not in me.uv_layers:
        raise RuntimeError('source UV layer "%s" missing' % couche_src)
    if 'UVMap' not in me.uv_layers:
        raise RuntimeError('atlas UV layer "UVMap" missing')

    # --- the source images, one per material
    def noeud_image_de(mat):
        """The image node of a material: the one wired to Base Color, else the first one."""
        if not (mat and mat.use_nodes and mat.node_tree):
            return None
        nt = mat.node_tree
        for n in nt.nodes:                       # first the one wired to the Base Color
            e = n.inputs.get('Base Color') if hasattr(n, 'inputs') else None
            if e is not None:
                for l in e.links:
                    if getattr(l.from_node, 'image', None) is not None:
                        return l.from_node
        for n in nt.nodes:                       # otherwise the material's first image
            if n.type == 'TEX_IMAGE' and n.image is not None:
                return n
        return None

    noeuds = {i: noeud_image_de(m) for i, m in enumerate(materiaux)}
    images = {i: (n.image if n is not None else None) for i, n in noeuds.items()}
    if not any(v is not None for v in images.values()):
        raise RuntimeError('no source image: nothing to re-bake')
    extensions = {i: (getattr(n, 'extension', None) if n is not None else None)
                  for i, n in noeuds.items()}

    cible = bpy.data.images.get('SM3_ATLAS_RECUIT')
    if cible is not None:
        bpy.data.images.remove(cible)
    cible = bpy.data.images.new('SM3_ATLAS_RECUIT', width=taille, height=taille,
                                alpha=False, float_buffer=False)
    cible.pixels.foreach_set(np.zeros(taille * taille * 4, dtype=np.float32))

    plan = plan_de_lecture(me, couche_src, index_par_face, len(materiaux), extensions, log)
    try:
        # WARNING: put the SOURCE materials and the per-face assignment back:
        # `create_friend_baked_atlas` erased them in favour of a single preview material. Without
        # this snapshot, every face would fall back on slot 0 and the same texture would be
        # re-baked everywhere.
        me.materials.clear()
        for lot, (i, couche, extension) in enumerate(plan['lots']):
            img = images.get(i)
            m = bpy.data.materials.new('SM3_RECUIT_%d' % lot)
            m.use_nodes = True
            nt = m.node_tree
            nt.nodes.clear()
            out = nt.nodes.new('ShaderNodeOutputMaterial')
            emi = nt.nodes.new('ShaderNodeEmission')
            nt.links.new(emi.outputs['Emission'], out.inputs['Surface'])
            if img is not None:
                tex = nt.nodes.new('ShaderNodeTexImage')
                tex.image = img
                tex.interpolation = 'Cubic'
                tex.extension = extension
                uvn = nt.nodes.new('ShaderNodeUVMap')
                uvn.uv_map = couche
                nt.links.new(uvn.outputs['UV'], tex.inputs['Vector'])
                nt.links.new(tex.outputs['Color'], emi.inputs['Color'])
            # the ACTIVE node of each material designates the bake target
            bake = nt.nodes.new('ShaderNodeTexImage')
            bake.image = cible
            for n in nt.nodes:
                n.select = False
            bake.select = True
            nt.nodes.active = bake
            me.materials.append(m)
        me.polygons.foreach_set('material_index', plan['index'].tolist())
        me.update()

        # the bake WRITES into the unwrap of the active_render layer: it must be the ATLAS
        for l in me.uv_layers:
            l.active_render = (l.name == 'UVMap')
        me.uv_layers.active = me.uv_layers['UVMap']

        sc = bpy.context.scene
        moteur = sc.render.engine
        sc.render.engine = 'CYCLES'
        ech = None
        try:
            ech = sc.cycles.samples
            sc.cycles.samples = 1
            sc.cycles.device = 'CPU'
        except Exception:
            pass
        sc.render.bake.use_selected_to_active = False
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
        log('   DIFFUSE re-bake %dx%d on the rounded UVs (pure emission)' % (taille, taille))
        try:
            bpy.ops.object.bake(type='EMIT')
        finally:
            sc.render.engine = moteur
            if ech is not None:
                try:
                    sc.cycles.samples = ech
                except Exception:
                    pass

        chemin = os.path.join(sortie, 'atlas_recuit.png')
        cible.filepath_raw = chemin
        cible.file_format = 'PNG'
        cible.save()
        buf = np.empty(taille * taille * 4, dtype=np.float32)
        cible.pixels.foreach_get(buf)
        px = buf.reshape(taille, taille, 4)
        del buf
        try:
            c = controler(me, plan, images, px, taille)
        except Exception as err:
            # a check that crashes must not throw away a successful bake: fall back on the old test
            log('   !! re-bake check impossible (%s): falling back on the sum test' % err)
            couvert = float((px[..., :3].sum(2) > 0.004).mean())
            c = {'couverture': couvert, 'conformes': None}
            if couvert < 0.05:
                raise RuntimeError('re-baked atlas almost empty (%.2f %%): re-bake failed'
                                   % (100 * couvert))
    finally:
        retirer_couche(me, plan)
    if c['conformes'] is None:
        log('   re-baked atlas: %.1f %% of texels carried, mean %.3f (no point could be checked)'
            % (100 * c['couverture'], float(px[..., :3].mean())))
        return chemin
    log('   re-baked atlas: %.1f %% of texels carried, mean %.3f; %.1f %% of the points match '
        'the source (median difference %.3f, p90 %.3f, %d points, %.1f %% black)'
        % (100 * c['couverture'], float(px[..., :3].mean()), 100 * c['conformes'],
           c['ecart_median'], c['ecart_p90'], c['points'], 100 * c['noirs']))
    if c['conformes'] < SEUIL_CONFORMES or c['ecart_p90'] > SEUIL_P90:
        raise RuntimeError('re-baked atlas unfaithful to the source (%.1f %% of the points match, '
                           'p90 %.3f): re-bake failed' % (100 * c['conformes'], c['ecart_p90']))
    return chemin
