# SPDX-License-Identifier: GPL-3.0-or-later
"""atlas.py - texture atlas assembly WITHOUT Blender and without baking.

Where it sits: helper of sm3_sans_blender.py (options --atlas and --canvas), the experimental
Blender-free GLB -> .mesh path. The normal conversion (sm3_convertir.py) does NOT use it: its
atlas is baked in Blender by the `chaine` stage. sm3_sans_blender.py imports this module at load
time, so it is loaded whenever the converter runs, but only that experimental path calls it.

Why it exists: the Material Combiner add-on BAKES the atlas, i.e. renders every material into one
image through Blender's render engine. All our early atlas problems came from there: the double
sRGB encoding (in the combiner's sm3_baked_atlas.py, around its lines 453 and 520 in the version
studied at the time; see correctifs_blender/), the island repacking that scatters islands when the
vertices are not welded, and five minutes of computation.

Here nothing is baked: texels are COPIED. A group = (material, UDIM tile). Each group gets one
cell of a grid, its source texture is resized into that cell, and the UVs are rewritten into the
cell. It is exact to the texel, instantaneous, and no colour space conversion is involved.

Pitfall: the gutter around each cell is filled by EXTENDING the texture with wrap-around, not with
black. Mip levels mix neighbouring cells, and a black border shows in game as a dark line along
every seam.

Reads/writes nothing itself: arrays in, arrays out (the caller loads the images and saves the PNG).
"""
from __future__ import annotations

import numpy as np


def echantillonne(src, larg, haut, marge=0.0):
    """Resample `src` (H, W, 4) to (haut, larg, 4) (French: height, width), over-extended by
    `marge` (a fraction of the tile on each side) using WRAP-around, the same WRAP addressing the
    engine applies."""
    H, W = src.shape[:2]
    u = (np.arange(larg) + 0.5) / larg * (1 + 2 * marge) - marge
    v = (np.arange(haut) + 0.5) / haut * (1 + 2 * marge) - marge
    x = np.mod((u * W).astype(np.int64), W)
    y = np.mod((v * H).astype(np.int64), H)
    return src[np.ix_(y, x)]


def groupes_uv(UV, tris, materiau_par_tri):
    """Group triangles by (material, UDIM tile): {(material, tu, tv): [triangle indices]}.

    The tile is taken from the MEAN of the triangle's UVs: a single vertex lying on a tile
    border must not move the whole face to the next tile."""
    c = UV[tris].mean(1)
    tu = np.floor(c[:, 0] + 1e-6).astype(np.int64)
    tv = np.floor(c[:, 1] + 1e-6).astype(np.int64)
    cles = {}
    for i in range(len(tris)):
        cles.setdefault((int(materiau_par_tri[i]), int(tu[i]), int(tv[i])), []).append(i)
    return cles


def compose(UV, tris, materiau_par_tri, images, taille=2048, marge_px=8, poids=None):
    """Build the atlas; return (RGBA uint8 atlas, rewritten UVs, (columns, rows), report).

    `images`: list indexed by material, each entry an (H, W, 4) uint8 array or None (a light grey
              placeholder is used).
    `taille`: atlas size in pixels; `marge_px`: gutter kept on each side of every cell.
    `poids`:  accepted but unused (meant as the relative area wanted per group).
    `report`: one (group key, faces, vertices, source width, source height) tuple per group.
    """
    cles = groupes_uv(UV, tris, materiau_par_tri)
    n = len(cles)
    # A SQUARE grid wastes atlas space as soon as n is not a perfect square (2 groups in a 2x2
    # grid leave half of the texture black), so the grid is tightened to columns x rows.
    cols = int(np.ceil(np.sqrt(n)))
    lignes = int(np.ceil(n / cols))
    cw, ch = taille // cols, taille // lignes
    marge = marge_px / max(1, min(cw, ch) - 2 * marge_px)

    atlas = np.zeros((taille, taille, 4), np.uint8)
    atlas[:, :, 3] = 255
    UV2 = UV.copy()
    rapport = []
    for k, (cle, faces) in enumerate(sorted(cles.items())):
        imat, tu, tv = cle
        col, lig = k % cols, k // cols
        x0, y0 = col * cw, lig * ch
        src = images[imat] if imat < len(images) and images[imat] is not None else None
        if src is None:
            src = np.full((4, 4, 4), 200, np.uint8)
            src[:, :, 3] = 255
        atlas[y0:y0 + ch, x0:x0 + cw] = echantillonne(src, cw, ch, marge)

        # UV -> cell. The gutter is reserved on BOTH sides; the content fills the middle.
        fu = (cw - 2 * marge_px) / taille
        fv = (ch - 2 * marge_px) / taille
        o = marge_px / taille
        sommets = np.unique(tris[faces])
        u = UV[sommets, 0] - tu
        v = UV[sommets, 1] - tv
        UV2[sommets, 0] = (x0 / taille) + o + np.clip(u, 0, 1) * fu
        UV2[sommets, 1] = (y0 / taille) + o + np.clip(v, 0, 1) * fv
        rapport.append((cle, len(faces), len(sommets), src.shape[1], src.shape[0]))
    return atlas, UV2, (cols, lignes), rapport
