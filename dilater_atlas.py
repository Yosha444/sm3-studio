# SPDX-License-Identifier: GPL-3.0-or-later
"""dilater_atlas.py - grow the atlas islands into the gutter, to hide the seams ("dilate the atlas").

Where it sits: stage `atlas` of sm3_convertir.py, between the Blender bake (stage `chaine`, which
leaves SM3_Spider_Baked_Atlas_atlas_final.png in build/<mod>/) and the .tex encoding
(tools/png2tex.py). Also used by the Black Suit and Web of Shadows pipelines in tools/ (run as a
script), and by tools/venom_native_textures.py and support_venom_direct/make_atlas.py (which import
couverture(), dilate() and `fmt`).

The problem in one sentence: a UV island stops abruptly at its border, the background right next
to it has another colour, and bilinear filtering - then every mip level, more and more - mixes
the two. That draws a thin line along every cut of the suit (a user's remark: "the cuts in the
suit where the textures attach don't look good").

The standard fix: DILATE. The real coverage of the UV triangles is rasterised, then the colour
of the border texels is pushed outwards, one ring at a time. The mips then mix the border with
the continuation of the island instead of the background.

The dilation has to happen before the encoding, and the mips have to be computed again on top
of it - hence a PNG is written, which `tools/png2tex.py` then encodes.

V ORIENTATION (fixed on 2026-10-08). V used to be flipped ("1 - V") on the belief that the image
origin is at the bottom: wrong. The bake PNG is written with row 0 at the top, the .tex takes it
as is (friend_bake.json: "tex_row_orientation TOP_DOWN_MATCHES_SAVED_PNG") and D3D reads v = 0 at
the top: row = v x R. With the flip, only 40 to 85 % of the computed coverage fell on baked
content (photoreal: 71 %), and the rings smeared real island texels outside the flipped island:
3.3 % on the red photoreal suit, 3.5 % on the black one, 10 to 52 % on miles, tasm1, brand (cut
web lines, streaks). Measured on 36 builds, all in direct V.
Rather than freezing one direction, BOTH are rasterised and the one that matches the atlas
background is kept (see `choisir_orientation`); `--orientation V` or `1-V` forces it.

Reads:  --atlas (the baked PNG), --mesh (the .mesh whose UVs define the islands), optionally the
        raw bake next to the atlas (*atlas_cuit*.png: pure black background) to decide V.
Writes: --out, the dilated RGBA PNG (atlas_dilate.png in the converter).

    python dilater_atlas.py --atlas <in.png> --mesh <file.mesh> --out <out.png> [--pixels 24]
                            [--orientation auto|V|1-V] [--cuit <raw_baked_atlas.png>]

French names: couverture = coverage, anneaux = rings, cuit = baked (the raw bake), indice =
clue (a measurement that votes for one V orientation).
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
from sm3_sans_blender import fmt  # noqa: E402


def log(*x):
    print('[dilat]', *x)


def couverture(UV, tris, R):
    """Mask of the texels really covered by a UV triangle (barycentric rasterisation).

    `R` is the atlas size (square) or a (width, height) pair; UV are image coordinates in [0,1],
    row 0 at the top. A small tolerance (-0.02) includes the texels that touch an edge."""
    W, H = (R, R) if np.isscalar(R) else R
    m = np.zeros((H, W), bool)
    P = UV[tris] * np.array([W, H])
    for a, b, c in P:
        x0 = max(int(min(a[0], b[0], c[0])) - 1, 0)
        x1 = min(int(max(a[0], b[0], c[0])) + 2, W)
        y0 = max(int(min(a[1], b[1], c[1])) - 1, 0)
        y1 = min(int(max(a[1], b[1], c[1])) + 2, H)
        if x1 <= x0 or y1 <= y0:
            continue
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-12:
            continue
        X, Y = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        l1 = ((b[1] - c[1]) * (X - c[0]) + (c[0] - b[0]) * (Y - c[1])) / d
        l2 = ((c[1] - a[1]) * (X - c[0]) + (a[0] - c[0]) * (Y - c[1])) / d
        m[y0:y1, x0:x1] |= (l1 >= -0.02) & (l2 >= -0.02) & (1 - l1 - l2 >= -0.02)
    return m


def dilate(img, masque, anneaux):
    """Push the colour outwards, one 1-pixel ring at a time (4-neighbourhood).

    Each new texel takes the mean of its already-filled neighbours. Returns (image, new mask)."""
    out = img.astype(np.int32).copy()
    m = masque.copy()
    for k in range(anneaux):
        bord = ~m
        somme = np.zeros(out.shape, np.int32)
        n = np.zeros(m.shape, np.int32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            v = np.roll(np.roll(m, dy, 0), dx, 1)
            vi = np.roll(np.roll(out, dy, 0), dx, 1)
            pr = bord & v
            somme[pr] += vi[pr]
            n[pr] += 1
        pr = n > 0
        if not pr.any():
            log('   nothing left to extend after %d ring(s)' % k)
            break
        out[pr] = somme[pr] // n[pr, None]
        m |= pr
    return out.astype(np.uint8), m


# ----------------------------------------------------------------------------- V orientation
ORIENTATIONS = ('V', '1-V')
# Smallest gap (in points) between the two orientations for a clue to decide. Measured on 36
# builds: the decisive clue always separates them by at least 12 points (m2099, black
# background); the weak clues (black background at 5 %, fill signature) go down to 2.4 points.
SEUIL_POINTS = 3.0


def uv_image(UV, orientation):
    """UV -> image coordinates (row 0 at the top) for the orientation being tried."""
    UVi = UV.copy()
    if orientation == '1-V':
        UVi[:, 1] = 1.0 - UVi[:, 1]
    return UVi


def atlas_cuit_voisin(chemin_atlas, forme):
    """The raw baked atlas (pure black background) that the bake leaves next to the final atlas,
    with the same size as the atlas; None if there is none."""
    d = os.path.dirname(os.path.abspath(chemin_atlas))
    try:
        noms = sorted(os.listdir(d))
    except OSError:
        return None
    noms = [n for n in noms if n.lower().endswith('.png') and 'atlas_cuit' in n.lower()]
    noms.sort(key=lambda n: n != 'SM3_Spider_Baked_Atlas_atlas_cuit.png')
    from PIL import Image
    for n in noms:
        c = os.path.join(d, n)
        if os.path.abspath(c) == os.path.abspath(chemin_atlas):
            continue
        try:
            with Image.open(c) as im:
                if (im.size[1], im.size[0]) == tuple(forme):
                    return c
        except OSError:
            continue
    return None


def _doublons(rgb):
    """Texels identical (exact RGB) to one of their 4 neighbours. The bake fills the background
    (JUMP_FLOOD_NEAREST_ISLAND) by copying the nearest island texel: the background is full of
    such duplicates, a real texture much less so."""
    a = rgb.astype(np.int32)
    k = (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]
    d = np.zeros(k.shape, bool)
    d[1:] |= k[1:] == k[:-1]
    d[:-1] |= k[:-1] == k[1:]
    d[:, 1:] |= k[:, 1:] == k[:, :-1]
    d[:, :-1] |= k[:, :-1] == k[:, 1:]
    return d


def indices(im, chemin_cuit):
    """The clues that decide between the orientations: [(name, scoring function)].

    Each one scores a coverage mask in points: the higher, the better it matches the content of
    the atlas. The "black background" clue is only valid for a re-baked atlas: on a very dark
    atlas whose background was filled, pure black is CONTENT and that clue can be wrong (see
    `choisir_orientation`)."""
    rgb = im[..., :3]
    out = []
    noir = ~rgb.any(-1)
    if noir.mean() >= 0.05:
        # re-baked atlas (tools/atlas_recuit.py): pure black background beyond the bake margin
        out.append(('atlas black background (%.1f %% pure black)' % (100 * noir.mean()),
                    lambda m: 100.0 * (m & ~noir).sum() / max(1, m.sum())))
    if chemin_cuit:
        from PIL import Image
        plein = np.asarray(Image.open(chemin_cuit).convert('RGB')).any(-1)
        if plein.shape == noir.shape:
            out.append(('raw baked atlas %s (%.1f %% content)'
                        % (os.path.basename(chemin_cuit), 100 * plein.mean()),
                        lambda m: 100.0 * (m & plein).sum() / max(1, m.sum())))
        else:
            # only a --cuit given by hand can get here (the neighbour is filtered by size)
            log('!! raw baked atlas %s ignored: %dx%d, the atlas is %dx%d'
                % (os.path.basename(chemin_cuit), plein.shape[1], plein.shape[0],
                   noir.shape[1], noir.shape[0]))
    dup = _doublons(rgb)
    out.append(('background fill signature',
                lambda m: 100.0 * (dup[~m].mean() - dup[m].mean()) if m.any() and (~m).any()
                else 0.0))
    return out


def choisir_orientation(UV, tris, R, im, chemin_cuit=None, imposee='auto'):
    """Return (orientation, mask). In `auto`, rasterise V and 1-V and keep the one the decisive
    clues prefer; if they contradict each other or none decides, direct V (the convention of the
    conversion chain). `imposee` (French: "forced") = 'V' or '1-V' skips the measurement."""
    if imposee in ORIENTATIONS:
        log('V orientation forced: %s' % imposee)
        return imposee, couverture(uv_image(UV, imposee), tris, R)
    cov = {o: couverture(uv_image(UV, o), tris, R) for o in ORIENTATIONS}
    choix = source = None
    contredit = False
    for nom, note in indices(im, chemin_cuit):
        s = {o: note(cov[o]) for o in ORIENTATIONS}
        ecart = s['V'] - s['1-V']
        log('   clue %s: V %.2f | 1-V %.2f (gap %+.2f)' % (nom, s['V'], s['1-V'], ecart))
        if abs(ecart) < SEUIL_POINTS:
            continue
        prefere = 'V' if ecart > 0 else '1-V'
        if choix is None:
            choix, source = prefere, nom
        elif prefere != choix:
            contredit = True
            log('!! contradictory clue: %s prefers %s, %s prefers %s'
                % (nom, prefere, source, choix))
    if contredit:
        # Very dark atlas WITHOUT a black background (background filled by the bake, 60 to 70 %
        # pure black inside the islands): the "black background" clue leans 3 to 5 points
        # towards 1-V there, against the raw baked atlas (+6 to +10) and the signature (+6 to
        # +8) -- measured by re-reading the black photoreal suit crushed to black. So 1-V is
        # only kept if ALL the decisive clues agree.
        choix, source = 'V', 'default: contradictory clues, convention of the conversion chain'
    if choix is None:
        choix, source = 'V', 'default: no clue decides (gap < %g points)' % SEUIL_POINTS
    log('V orientation kept: %s (row = %s x R) -- %s'
        % (choix, 'v' if choix == 'V' else '(1 - v)', source))
    if choix != 'V':
        # Never seen on an atlas of the conversion chain (36 builds, all in direct V): if it
        # happens, the atlas probably does not come from SM3 Studio's bake.
        log('!! flipped orientation: unexpected for an atlas baked by SM3 Studio, check it')
    return choix, cov[choix]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--atlas', required=True)
    ap.add_argument('--mesh', required=True, help='gives the real UV coverage')
    ap.add_argument('--out', required=True)
    ap.add_argument('--pixels', type=int, default=24)
    ap.add_argument('--uv-divisor', type=float, default=1000.0)
    ap.add_argument('--orientation', choices=('auto',) + ORIENTATIONS, default='auto',
                    help='direction of V in the image (auto = measured against the atlas background)')
    ap.add_argument('--cuit', default=None,
                    help='raw baked atlas (black background); by default the one next to --atlas')
    A = ap.parse_args()
    if A.cuit and not os.path.isfile(A.cuit):
        raise SystemExit('--cuit not found: %s' % A.cuit)

    from PIL import Image
    im = np.asarray(Image.open(A.atlas).convert('RGBA')).copy()
    R = im.shape[0]
    m = fmt.parse_mesh(A.mesh)
    UV, tris, base = [], [], 0
    for s in m.sections:
        if not s.vertex_count:
            continue
        d = fmt.decode_section_vertices(m, s, uv_divisor=A.uv_divisor)
        tc = d['texcoords']
        UV.append(np.array(tc[sorted(tc)[0]], np.float64))
        idx = fmt.read_indices(m, s)
        tris.append(np.array(fmt.indices_to_faces(idx, s.primitive_type, s.vertex_count),
                             np.int64) + base)
        base += s.vertex_count
    UV = np.concatenate(UV)
    tris = np.concatenate(tris)
    hors = (UV < 0.0) | (UV > 1.0)
    if hors.any():
        log('!! %d vertex(es) with UVs outside [0,1] (u %.3f..%.3f, v %.3f..%.3f): only the part '
            'inside the atlas is counted' % (int(hors.any(1).sum()), UV[:, 0].min(), UV[:, 0].max(),
                                             UV[:, 1].min(), UV[:, 1].max()))

    cuit = A.cuit if A.cuit else atlas_cuit_voisin(A.atlas, im.shape[:2])
    orientation, cov = choisir_orientation(UV, tris, R, im, cuit, A.orientation)
    log('atlas %dx%d | real UV coverage %.1f %% | %d background texels'
        % (R, R, 100 * cov.mean(), int((~cov).sum())))
    out, m2 = dilate(im, cov, A.pixels)
    log('after %d rings: %.1f %% of the atlas carries island colour (+%.1f points)'
        % (A.pixels, 100 * m2.mean(), 100 * (m2.mean() - cov.mean())))
    Image.fromarray(out).save(A.out)
    log('WROTE %s' % A.out)


if __name__ == '__main__':
    main()
