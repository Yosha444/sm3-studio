# SPDX-License-Identifier: GPL-3.0-or-later
"""Self-tests of the high-quality DXT encoder (sm3/dxtenc.py) and of the png2tex.py chain.

Not part of the conversion: run it by hand after changing tools/sm3/dxtenc.py or tools/png2tex.py.

Run:  python dxtenc_selftest.py            (from anywhere; ~1 min)
      SM3_SELFTEST_RAPIDE=1 python ...      (skips the full 4096 case; "rapide" = fast)

Optional input: the red-suit atlas of a test build, <project>/build/essai_mains/atlas_dilate.png
(or the file named by the SM3_ATLAS_ROUGE environment variable). Without it the atlas tests are
skipped and a synthetic image replaces it for the size tests.

Everything is decoded by the INDEPENDENT decoder sm3/texfind.py (decode_level), never by the
encoder itself. What is checked:
  1. synthetic blocks: flat colours, exactly representable pairs, random blocks (error of the
     decoded block <= old encoder, BLOCK BY BLOCK), exact constant alpha, DXT1 without any
     transparent texel (4-colour mode, c0 > c1, or c0 == c1 with indices 0);
  2. crops of the red atlas: new PSNR >= old everywhere, and >= +3 dB on the web-line crop (at
     mip 2, where the game showed them);
  3. sizes 1x1 .. 4096 (and non multiples of 4), DXT1 and DXT5: exact size, PSNR >= old; time
     of a complete 4096 DXT5 chain;
  4. normal map (swizzle X=alpha, Y=green): no pre-multiplication -- a constant y with a tiny x
     goes through every mip, a checkerboard of opposite normals gives a flat normal; default
     fade, R = B = 0, DXT5 forced; chain = the one of the red normal map APPROVED in game (mean of
     x and y, linear fade f*(x,y), no renormalisation); renormalise option; size= without
     pre-multiplication;
  5. background / dilation on a very dark atlas: body texels with an RGB sum <= 6 are kept (the
     old threshold overwrote them), the background is filled, an already dilated atlas is not
     touched; black guard of the smoothing (near-black gaps kept, nothing changes above L* 3);
  6. write_tex end to end (header, sizes, chain reuse, exact ARGB8), reading of
     texture_qualite.json (missing / partial / invalid), par_texture (black atlas 0x0133FD92 not
     smoothed) and blacksuit_package.controle_texture with the settings of the hash.

Some strings below are NOT messages: they are compared with png2tex's report ('chaine reprise',
'sautee', 'lissage non', ...), passed to png2tex as kinds ('normale', 'couleur') or used as file
names from which png2tex deduces the kind ('normale_swizzle.png'). They stay in French because
png2tex uses those exact words.
"""
import json
import os
import struct
import sys
import tempfile
import time

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))
OUTILS = os.path.dirname(ICI)
RACINE = os.path.dirname(OUTILS)
sys.path.insert(0, OUTILS)
from sm3 import dxtenc as D               # noqa: E402
from sm3.texfind import decode_level      # noqa: E402
import png2tex                            # noqa: E402
from PIL import Image                     # noqa: E402

Image.MAX_IMAGE_PIXELS = None
ATLAS_ROUGE = os.environ.get('SM3_ATLAS_ROUGE',
                             os.path.join(RACINE, 'build', 'essai_mains', 'atlas_dilate.png'))
RAPIDE = bool(os.environ.get('SM3_SELFTEST_RAPIDE'))
BLOC = {'dxt1': 8, 'dxt5': 16}
NEUF = {'dxt1': D.dxt1_encode, 'dxt5': D.dxt5_encode}
ANCIEN = {'dxt1': D.dxt1_encode_rapide, 'dxt5': D.dxt5_encode_rapide}

_resultats = []


def check(nom, cond, detail=''):
    _resultats.append((nom, bool(cond), detail))
    print('  [%s] %s%s' % ('PASS' if cond else 'FAIL', nom, ('  (%s)' % detail) if detail else ''),
          flush=True)


def psnr(a, b):
    m = ((np.asarray(a, np.float64) - np.asarray(b, np.float64)) ** 2).mean()
    return 99.0 if m == 0 else 10 * np.log10(255.0 ** 2 / m)


def aller_retour(img, fmt, enc=None):
    h, w = img.shape[:2]
    octets = (enc or NEUF[fmt])(img, w, h)
    attendu = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * BLOC[fmt]
    assert len(octets) == attendu, (fmt, w, h, len(octets), attendu)
    return decode_level(octets, fmt, w, h), octets


def blocs_vers_image(blocs):
    """(N, 16, 4) -> image (4, 4N, 4): N blocks side by side."""
    n = len(blocs)
    return np.ascontiguousarray(blocs.reshape(n, 4, 4, 4).transpose(1, 0, 2, 3).reshape(4, 4 * n, 4))


def sse_par_bloc(dec, ref):
    n = ref.shape[1] // 4
    d = (dec.astype(np.int64) - ref.astype(np.int64)) ** 2
    return d.reshape(4, n, 4, -1).sum((0, 2))          # (N, channels)


# ------------------------------------------------------------------------------------------
# 1. synthetic blocks
# ------------------------------------------------------------------------------------------

def test_blocs_synthetiques():
    print('1. synthetic blocks')
    rng = np.random.default_rng(1234)
    # flat colours: the old encoder rounds to 565 (up to 8 levels of red/blue lost), the new one
    # goes through palette entry 2/3 (single-colour tables)
    coul = rng.integers(0, 256, (3000, 1, 3))
    blocs = np.concatenate([np.repeat(coul, 16, 1), np.full((3000, 16, 1), 255)], 2).astype(np.uint8)
    img = blocs_vers_image(blocs)
    for fmt in ('dxt1', 'dxt5'):
        dn, _ = aller_retour(img, fmt); do, _ = aller_retour(img, fmt, ANCIEN[fmt])
        en = np.abs(dn[..., :3].astype(int) - img[..., :3]).max()
        eo = np.abs(do[..., :3].astype(int) - img[..., :3]).max()
        check('%s flat colours: max error %d (old %d)' % (fmt, en, eo), en <= 2 and en <= eo)
        check('%s flat colours: exact alpha' % fmt, fmt == 'dxt1' or np.array_equal(dn[..., 3], img[..., 3]))
    # exactly representable pairs: 565 endpoints and their exact interpolations
    q0 = rng.integers(0, 65536, 2000); q1 = rng.integers(0, 65536, 2000)
    def dec(q):
        r = (q >> 11) & 31; g = (q >> 5) & 63; b = q & 31
        return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1)
    d0, d1 = dec(q0), dec(q1)
    pal = np.stack([d0, d1, (2 * d0 + d1 + 1) // 3, (d0 + 2 * d1 + 1) // 3], 1)      # (N, 4, 3)
    choix = rng.integers(0, 4, (2000, 16))
    rgb = np.take_along_axis(pal, choix[..., None], 1)
    blocs = np.concatenate([rgb, np.full((2000, 16, 1), 255)], 2).astype(np.uint8)
    img = blocs_vers_image(blocs)
    for fmt in ('dxt1', 'dxt5'):
        dn, _ = aller_retour(img, fmt)
        exact = (sse_par_bloc(dn[..., :3], img[..., :3]).sum(1) == 0).mean()
        check('%s exactly representable blocks: %.1f %% restored without error' % (fmt, 100 * exact),
              exact >= 0.97)
    # random blocks (noise, gradients, two colours): never worse than the old encoder, block by block
    n = 6000
    bruit = rng.integers(0, 256, (n // 3, 16, 4))
    t = np.linspace(0, 1, 16)[None, :, None]
    a = rng.integers(0, 256, (n // 3, 1, 4)); b = rng.integers(0, 256, (n // 3, 1, 4))
    degr = np.rint(a + (b - a) * t + rng.normal(0, 4, (n // 3, 16, 4)))
    deux = np.where(rng.random((n // 3, 16, 1)) < 0.5, a, b)
    blocs = np.clip(np.concatenate([bruit, degr, deux]), 0, 255).astype(np.uint8)
    img = blocs_vers_image(blocs)
    for fmt in ('dxt1', 'dxt5'):
        dn, _ = aller_retour(img, fmt); do, _ = aller_retour(img, fmt, ANCIEN[fmt])
        sn = sse_par_bloc(dn[..., :3], img[..., :3]).sum(1); so = sse_par_bloc(do[..., :3], img[..., :3]).sum(1)
        pire = int((sn > so + 1).sum())
        check('%s %d random blocks: error <= old encoder block by block (%d worse), PSNR %.2f -> %.2f dB'
              % (fmt, n, pire, psnr(do[..., :3], img[..., :3]), psnr(dn[..., :3], img[..., :3])), pire == 0)
        if fmt == 'dxt1':
            check('dxt1: no transparent texel (4-colour mode, or c0 == c1 with index 0)',
                  (dn[..., 3] == 255).all())
        else:
            an = sse_par_bloc(dn[..., 3:], img[..., 3:])[:, 0]; ao = sse_par_bloc(do[..., 3:], img[..., 3:])[:, 0]
            check('dxt5 alpha: error <= old encoder block by block, PSNR %.2f -> %.2f dB'
                  % (psnr(do[..., 3], img[..., 3]), psnr(dn[..., 3], img[..., 3])), int((an > ao).sum()) == 0)
    # constant alpha 0..255: exact
    v = np.arange(256)
    blocs = np.zeros((256, 16, 4), np.uint8); blocs[..., :3] = 128; blocs[..., 3] = v[:, None]
    dn, _ = aller_retour(blocs_vers_image(blocs), 'dxt5')
    check('dxt5 constant alpha 0..255 restored exactly', np.array_equal(dn[..., 3], blocs_vers_image(blocs)[..., 3]))
    # float inputs (mip chains): same result as integer input when the values are integers
    img = blocs_vers_image(blocs)
    check('float input == uint8 input for integer values',
          D.dxt5_encode(img.astype(np.float32), img.shape[1], 4) == D.dxt5_encode(img, img.shape[1], 4))


# ------------------------------------------------------------------------------------------
# 2. crops of the red atlas
# ------------------------------------------------------------------------------------------

def _atlas():
    if not os.path.isfile(ATLAS_ROUGE):
        print('  (red atlas missing: %s -- atlas tests SKIPPED)' % ATLAS_ROUGE)
        return None
    return np.asarray(Image.open(ATLAS_ROUGE).convert('RGBA'))


def _mip(c, k):
    """2^k x 2^k float mean, rounded (the content of mip k)."""
    s = 2 ** k; h, w = c.shape[:2]
    return np.clip(np.rint(c.astype(np.float32).reshape(h // s, s, w // s, s, 4).mean((1, 3))), 0, 255).astype(np.uint8)


def test_atlas(atlas):
    print('2. crops of the red atlas')
    if atlas is None:
        return
    # (name, y, x, size, mip level); (768, 2560): red fabric striped with web lines. The first
    # name is also compared below (it alone requires +3 dB): change both together.
    extraits = [('web lines, mip 2', 768, 2560, 256, 2), ('web lines, mip 0', 768, 2560, 64, 0),
                ('web lines 2, mip 2', 1152, 1920, 256, 2), ('red fabric, mip 0', 1000, 1000, 256, 0),
                ('dark blue, mip 0', 2300, 2700, 256, 0), ('island border, mip 3', 3000, 500, 512, 3),
                ('whole atlas, mip 4', 0, 0, 4096, 4)]
    for nom, y, x, s, k in extraits:
        c = _mip(np.ascontiguousarray(atlas[y:y + s, x:x + s]), k)
        for fmt in ('dxt1', 'dxt5'):
            dn, _ = aller_retour(c, fmt); do, _ = aller_retour(c, fmt, ANCIEN[fmt])
            pn, po = psnr(dn[..., :3], c[..., :3]), psnr(do[..., :3], c[..., :3])
            seuil = 3.0 if nom == 'web lines, mip 2' else 0.0
            check('%s %s: %.2f -> %.2f dB (%+.2f)' % (fmt, nom, po, pn, pn - po), pn >= po + seuil,
                  'requires >= +3 dB' if seuil else '')


# ------------------------------------------------------------------------------------------
# 3. every size
# ------------------------------------------------------------------------------------------

def test_tailles(atlas):
    print('3. sizes 1x1 .. 4096, DXT1 and DXT5')
    rng = np.random.default_rng(7)
    if atlas is None:
        yy, xx = np.mgrid[0:1024, 0:1024]
        src = np.stack([(xx // 4) % 256, (yy // 4) % 256, (xx + yy) % 256, np.full_like(xx, 255)], -1)
        src = np.clip(src + rng.normal(0, 6, src.shape), 0, 255).astype(np.uint8)
    else:
        src = atlas
    img_src = Image.fromarray(src, 'RGBA')
    tailles = [(1, 1), (2, 2), (4, 4), (8, 8), (16, 16), (32, 32), (64, 64), (128, 128), (256, 256),
               (512, 512), (1024, 1024), (2048, 2048), (3, 5), (7, 7), (13, 6), (2, 8), (16, 2), (1, 64)]
    if not RAPIDE:
        tailles.append((4096, 4096))
    for w, h in tailles:
        img = np.asarray(img_src.resize((w, h), Image.BOX)) if (w, h) != src.shape[1::-1] else src
        img = np.ascontiguousarray(img)
        for fmt in ('dxt1', 'dxt5'):
            t = time.time(); dn, _ = aller_retour(img, fmt); dt = time.time() - t
            do, _ = aller_retour(img, fmt, ANCIEN[fmt])
            pn, po = psnr(dn[..., :3], img[..., :3]), psnr(do[..., :3], img[..., :3])
            check('%s %dx%d: %.2f -> %.2f dB%s' % (fmt, w, h, po, pn, ' (%.1f s)' % dt if dt > 0.5 else ''),
                  pn >= po)
    if RAPIDE:
        return
    # complete 4096 DXT5 chain (13 levels), float mips
    t = time.time(); total = 0
    cur = src.astype(np.float32); niveau = src
    while True:
        h, w = niveau.shape[:2]
        total += len(D.dxt5_encode(niveau, w, h))
        if (w, h) == (1, 1):
            break
        cur = cur.reshape(h // 2, 2, w // 2, 2, 4).mean((1, 3)); niveau = cur
    dt = time.time() - t
    check('complete DXT5 chain %dx%d: %.1f s, %d bytes' % (src.shape[1], src.shape[0], dt, total),
          dt <= 40.0, 'target ~25 s on the development machine')


# ------------------------------------------------------------------------------------------
# 4. normal map
# ------------------------------------------------------------------------------------------

def _niveaux_tex(chemin):
    raw = open(chemin, 'rb').read()
    w, h = np.frombuffer(raw[24:32], '<u4'); nb = int(np.frombuffer(raw[36:40], '<u4')[0])
    fourcc = raw[40:44]
    off = 68; out = []
    for L in range(nb):
        ww, hh = max(1, int(w) >> L), max(1, int(h) >> L)
        n = max(1, (ww + 3) // 4) * max(1, (hh + 3) // 4) * 16
        out.append(decode_level(raw[off:off + n], 'dxt5', ww, hh)); off += n
    return raw, fourcc, out, off


def _pillow_chaine(img):
    """The OLD chain: Image.resize(BOX) of an RGBA image (Pillow pre-multiplies by alpha)."""
    cur = Image.fromarray(img, 'RGBA'); out = [img]
    while cur.size != (1, 1):
        cur = cur.resize((max(1, cur.size[0] // 2), max(1, cur.size[1] // 2)), Image.BOX)
        out.append(np.asarray(cur))
    return out


def test_normale(tmp):
    print('4. normal map (swizzle: X in alpha, Y in green)')
    rng = np.random.default_rng(99)
    R1 = png2tex.charger_reglages(os.path.join(tmp, 'absent.json')); R1['normale_fondu'] = [1.0]
    # a) constant y, tiny varying x
    img = np.zeros((64, 64, 4), np.uint8)
    img[..., 1] = 200
    img[..., 3] = 128 + rng.integers(-3, 4, (64, 64))
    p = os.path.join(tmp, 'normale_swizzle.png'); Image.fromarray(img, 'RGBA').save(p)
    out = os.path.join(tmp, 'n1.tex')
    png2tex.write_tex(p, out, 0x61DCA273, None, 'DXT5', 'full', None, reglages=R1)
    _, fourcc, niv, _ = _niveaux_tex(out)
    ecarts = [float(np.abs(n[..., 1].astype(float) - 200).max()) for n in niv]
    vieux = _pillow_chaine(img)
    ecarts_vieux = [float(np.abs(n[..., 1].astype(float) - 200).max()) for n in vieux]
    check('constant y (green 200), tiny x: green at %s on the %d levels (max gap %.1f)'
          % ('200 +- 2', len(niv), max(ecarts)), max(ecarts) <= 2.0,
          'old Pillow chain before DXT: max gap %.0f' % max(ecarts_vieux))
    check('R and B zero at every level', all(n[..., 0].max() == 0 and n[..., 2].max() == 0 for n in niv))
    check('fourcc DXT5', fourcc == b'DXT5')
    # b) checkerboard of opposite normals: the mean is FLAT (Pillow gave a y biased by x)
    n1 = (0.6, 0.3); n2 = (-0.6, -0.3)
    img = np.zeros((64, 64, 4), np.uint8)
    yy, xx = np.mgrid[0:64, 0:64]; dam = (yy + xx) % 2 == 0
    for (nx, ny), m in ((n1, dam), (n2, ~dam)):
        img[m, 3] = int(round((nx + 1) * 127.5)); img[m, 1] = int(round((ny + 1) * 127.5))
    p = os.path.join(tmp, 'damier_normale.png'); Image.fromarray(img, 'RGBA').save(p)
    out = os.path.join(tmp, 'n2.tex')
    png2tex.write_tex(p, out, 0x61DCA273, None, 'DXT5', 'full', None, reglages=R1)
    _, _, niv, _ = _niveaux_tex(out)
    g1 = niv[1][..., 1].astype(float); a1 = niv[1][..., 3].astype(float)
    vieux = _pillow_chaine(img)[1]
    check('checkerboard of opposite normals -> flat mip 1: green %.1f..%.1f, alpha %.1f..%.1f (127.5 +- 1.5)'
          % (g1.min(), g1.max(), a1.min(), a1.max()),
          np.abs(g1 - 127.5).max() <= 1.5 and np.abs(a1 - 127.5).max() <= 1.5,
          'Pillow RGBA BOX gave green %.0f' % vieux[..., 1].mean())
    # c) default fade: full relief at mips 0-1, flat from mip 6 on; DXT1 refused
    img = np.zeros((256, 256, 4), np.uint8)
    img[..., 1] = np.clip(127.5 + 60 * np.sin(np.arange(256) / 3.0)[None, :], 0, 255)
    img[..., 3] = np.clip(127.5 + 60 * np.cos(np.arange(256) / 5.0)[:, None], 0, 255)
    p = os.path.join(tmp, 'relief_normale.png'); Image.fromarray(img, 'RGBA').save(p)
    out = os.path.join(tmp, 'n3.tex')
    png2tex.write_tex(p, out, 0x12345678, None, 'DXT1', 'full', None,
                      reglages=png2tex.charger_reglages(os.path.join(tmp, 'absent.json')))
    _, fourcc, niv, _ = _niveaux_tex(out)
    check('normal map asked in DXT1 -> written in DXT5 (kind deduced from the name)', fourcc == b'DXT5')
    plat = all(np.abs(n[..., 1].astype(float) - 127.5).max() <= 1 and np.abs(n[..., 3].astype(float) - 127.5).max() <= 1
               for n in niv[6:])
    check('default fade: levels 6..%d flat (127/128)' % (len(niv) - 1), plat)
    check('default fade: full relief at mip 0 (green std dev %.1f)' % niv[0][..., 1].std(),
          niv[0][..., 1].std() > 30)
    # d) default chain = chain of the red normal map APPROVED in game (A_normale,
    #    rouge_propre_fondu): level L = fade(L) x box mean of (x, y), no renormalisation
    Rd = png2tex.charger_reglages(os.path.join(tmp, 'absent.json'))
    x0 = img[..., 3].astype(np.float64) / 127.5 - 1; y0 = img[..., 1].astype(np.float64) / 127.5 - 1
    ecart = 0.0; cx, cy = x0, y0
    flottants = list(png2tex._niveaux_normale(img, 7, Rd, {}))
    for L, n in enumerate(flottants):
        if L:
            h = cx.shape[0] // 2
            cx = cx.reshape(h, 2, h, 2).mean((1, 3)); cy = cy.reshape(h, 2, h, 2).mean((1, 3))
        f = png2tex._fondu(Rd, L)
        ecart = max(ecart, np.abs(n[..., 3] - (f * cx + 1) * 127.5).max(), np.abs(n[..., 1] - (f * cy + 1) * 127.5).max())
    check('default chain = mean of (x,y) then LINEAR fade f*(x,y), like the approved red normal map '
          '(max gap %.4f on 0..255)' % ecart, ecart < 1e-3)
    Rr = dict(Rd); Rr['normale_renormaliser'] = True
    renorm = list(png2tex._niveaux_normale(img, 4, Rr, {}))
    amp = []; plus_pres = True
    for L in (1, 2, 3):
        d = niv[L][..., [1, 3]].astype(float)
        amp.append((d - 127.5).std() / (flottants[L][..., [1, 3]] - 127.5).std())
        if L >= 2:
            plus_pres &= np.abs(d - flottants[L][..., [1, 3]]).mean() < np.abs(d - renorm[L][..., [1, 3]]).mean()
    check('decoded .tex = this chain: relief amplitude x%.3f / x%.3f / x%.3f at mips 1-3, closer '
          'than the renormalised variant' % tuple(amp), all(abs(a - 1) <= 0.03 for a in amp) and plus_pres)
    def pente(n):
        x = n[..., 3] / 127.5 - 1; y = n[..., 1] / 127.5 - 1
        return float(np.sqrt(x * x + y * y).mean())
    rapports = [pente(renorm[L]) / max(pente(flottants[L]), 1e-9) for L in (2, 3)]
    check('option normale_renormaliser: stronger relief at mips 2-3 (x%.2f, x%.2f), same mip 0'
          % tuple(rapports), all(r > 1.0 for r in rapports) and np.abs(renorm[0] - flottants[0]).max() < 1e-4)
    # e) size=: each channel reduced alone (a Pillow RGBA resize would pre-multiply y by x)
    p = os.path.join(tmp, 'damier_normale.png')
    n32 = png2tex.preparer_image(p, 'normale', 'DXT5', size=32, reglages=R1)
    g = n32[4:-4, 4:-4, 1].astype(float)
    vieux = np.asarray(Image.open(p).convert('RGBA').resize((32, 32), Image.LANCZOS))[4:-4, 4:-4, 1].astype(float)
    check('size= on a normal map: opposite checkerboard reduced to flat (green %.1f..%.1f, Pillow RGBA %.1f)'
          % (g.min(), g.max(), vieux.mean()), np.abs(g - 127.5).max() <= 2.0)
    # f) deduced kind (png2tex.genre_texture; 'normale' / 'couleur' are its return values)
    G = png2tex.genre_texture
    check('kind: hash 0x61DCA273 -> normale', G('x.png', None, 0x61DCA273) == 'normale')
    check('kind: normale_swizzle.png / *.normswizzle.tex -> normale',
          G('C:/a/normale_swizzle.png') == 'normale' and G('a.png', '0x1.normswizzle.tex') == 'normale')
    check('kind: atlas_dilate.png, venom_normal_neutre.png, ch_venom_nor.tex -> couleur',
          G('atlas_dilate.png', 'x.tex', 0x8E661B33) == 'couleur' and G('venom_normal_neutre.png') == 'couleur'
          and G('t.png', '0xA164CFBD.ch_venom_nor.tex', 0xA164CFBD) == 'couleur')


# ------------------------------------------------------------------------------------------
# 5. background and dilation on a very dark atlas
# ------------------------------------------------------------------------------------------

def test_fond_sombre():
    print('5. background and dilation (very dark atlas)')
    rng = np.random.default_rng(5)
    H = W = 256
    yy, xx = np.mgrid[0:H, 0:W]
    corps = (yy - 128) ** 2 + (xx - 128) ** 2 < 100 ** 2                 # disc: ~48 % background
    img = np.zeros((H, W, 4), np.uint8); img[..., 3] = 255
    rgb = rng.integers(0, 4, (H, W, 3))                                   # sums 0..9: the black of the suit
    rgb[rng.random((H, W)) < 0.3] += rng.integers(5, 25, (1, 3))
    nul = ~rgb.any(-1); rgb[nul] = (1, 1, 2)                              # no (0,0,0) inside the body
    img[..., :3] = np.where(corps[..., None], rgb, 0)
    sombres = corps & (img[..., :3].astype(int).sum(-1) <= 6)
    fond = png2tex.masque_fond(img)
    check('mask: background == outside the body exactly (%d dark texels <= 6 inside the body, none taken for background)'
          % sombres.sum(), np.array_equal(fond, ~corps) and sombres.sum() > 1000)
    R = png2tex.charger_reglages(os.path.join(tempfile.gettempdir(), 'absent_%d.json' % os.getpid()))
    niveaux = list(png2tex._niveaux_couleur(img, fond, 9, R, {}))
    ok = True; rempli = None
    ref = img.astype(np.float64)
    for k in range(1, 9):
        s = 2 ** k
        plein = corps.reshape(H // s, s, W // s, s).all((1, 3))
        boite = ref.reshape(H // s, s, W // s, s, 4).mean((1, 3))
        if plein.any():
            ok &= np.abs(niveaux[k][plein] - boite[plein]).max() < 1e-2
        if k == 1:
            f1 = (~corps).reshape(H // 2, 2, W // 2, 2).all((1, 3))      # background at mip 1
            rempli = int((niveaux[1][f1][:, :3].sum(-1) > 0).sum())
    check('mips: texels entirely inside the body = exact mean of mip 0 (nothing overwritten)', ok)
    check('mips: the background next to the body is filled (%d texels at mip 1)' % rempli, rempli > 0)
    vieux = png2tex.dilater_niveau(img, 2)
    ecrases = int((np.any(vieux[..., :3] != img[..., :3], -1) & corps).sum())
    check('reference: the old threshold R+G+B <= 6 would have overwritten %d body texels' % ecrases, ecrases > 0)
    # smoothing: never applied to the background, and dark texels stay dark
    lisse = png2tex.lisser_bilateral(img, ~fond, 4, 3.0, 5.0)
    check('smoothing: background intact', np.array_equal(lisse[~corps], img[..., :3][~corps]))
    check('smoothing: dark body texels still dark (max %d)' % lisse[sombres].astype(int).sum(-1).max(),
          lisse[sombres].astype(int).sum(-1).max() <= 40)
    # black guard: scales (sRGB ~11) separated by near-black gaps (sRGB 1), like the symbiote.
    # Without the guard, 3 to 8 dE apart counts as "noise": the gaps get washed out to grey.
    ec = np.full((H, W, 4), 255, np.uint8)
    ec[..., :3] = np.clip(11 + rng.normal(0, 1.5, (H, W, 1)), 0, 255).astype(np.uint8)
    inter = ((yy % 8) == 0) | ((xx % 8) == 0)
    ec[inter, :3] = 1
    garde = png2tex.DEFAUTS['lissage']['garde_noir']
    sans = png2tex.lisser_bilateral(ec, None, 4, 3.0, 5.0)
    avec = png2tex.lisser_bilateral(ec, None, 4, 3.0, 5.0, garde_noir=garde)
    def contraste(o):
        v = o[..., :3].astype(float).sum(-1)
        return 100 * (1 - v[inter].mean() / v[~inter].mean())
    c0, cs, ca = contraste(ec), contraste(sans), contraste(avec)
    check('black guard %s: near-black gaps kept (contrast %.0f %% -> %.0f %%, without guard %.0f %%)'
          % (garde, c0, ca, cs), np.array_equal(avec[inter], ec[inter, :3]) and ca >= c0 - 5 and cs < c0 - 20)
    clair = rng.integers(40, 200, (H, W, 3)).astype(np.uint8)
    check('black guard: above L* %g, result identical to the original filter (byte for byte)' % garde[1],
          np.array_equal(png2tex.lisser_bilateral(clair, None, 4, 3.0, 5.0, garde_noir=garde),
                         png2tex.lisser_bilateral(clair, None, 4, 3.0, 5.0))
          and np.array_equal(png2tex.lisser_bilateral(ec, None, 4, 3.0, 5.0, garde_noir=[0, 0]), sans))
    # already dilated atlas: a few exact blacks (< 5 %) = content, chain without filling
    img2 = np.zeros((H, W, 4), np.uint8); img2[..., 3] = 255
    img2[..., :3] = rng.integers(10, 40, (H, W, 3))
    trous = rng.random((H, W)) < 0.01; img2[trous, :3] = 0
    tmp = tempfile.mkdtemp()
    p = os.path.join(tmp, 'atlas_deja_dilate.png'); Image.fromarray(img2, 'RGBA').save(p)
    info = {}
    R2 = dict(R); R2['lissage'] = dict(R['lissage'], actif=False)
    w, h, nb, it = png2tex._chaine(p, 'couleur', 'DXT5', 'full', None, R2, info)
    n1 = list(it)[1]
    boite = img2.astype(np.float64).reshape(H // 2, 2, W // 2, 2, 4).mean((1, 3))
    check('already dilated atlas (1 %% blacks): dilation skipped, mip 1 = exact mean (%s)'
          % info.get('dilatation'), 'sautee' in info.get('dilatation', '') and np.abs(n1 - boite).max() < 1e-2)
    os.remove(p); os.rmdir(tmp)


# ------------------------------------------------------------------------------------------
# 6. write_tex end to end, settings
# ------------------------------------------------------------------------------------------

def test_write_tex(tmp):
    print('6. write_tex end to end, texture_qualite.json')
    rng = np.random.default_rng(11)
    yy, xx = np.mgrid[0:128, 0:128]
    img = np.stack([xx * 2, yy * 2, (xx + yy) % 256, np.full_like(xx, 255)], -1)
    img = np.clip(img + rng.normal(0, 5, img.shape) * [1, 1, 1, 0], 0, 255).astype(np.uint8)
    p = os.path.join(tmp, 'atlas_test.png'); Image.fromarray(img, 'RGBA').save(p)
    R = png2tex.charger_reglages(os.path.join(tmp, 'absent.json'))
    o1 = os.path.join(tmp, '0x8E661B33.t.tex'); o2 = os.path.join(tmp, '0x06F18556._grey.tex')
    png2tex.write_tex(p, o1, 0x8E661B33, None, 'DXT5', 'full', None, reglages=R)
    rep = png2tex.write_tex(p, o2, 0x06F18556, None, 'DXT5', 'full', None, reglages=R)
    b1 = open(o1, 'rb').read(); b2 = open(o2, 'rb').read()
    hdr = np.frombuffer(b1[:68], '<u4')
    taille = 68 + sum(max(1, (128 >> k) // 4) ** 2 * 16 for k in range(8))
    check('header: hash, 128x128, 1, 8 mips, DXT5; size %d' % len(b1),
          hdr[3] == 0x8E661B33 and hdr[6] == 128 and hdr[7] == 128 and hdr[8] == 1 and hdr[9] == 8
          and b1[40:44] == b'DXT5' and len(b1) == taille)
    check('same image under another hash: chain reused from the cache, identical bytes apart from the hash',
          'chaine reprise' in rep and b1[68:] == b2[68:] and np.frombuffer(b2[12:16], '<u4')[0] == 0x06F18556)
    ref = png2tex.preparer_image(p, 'couleur', 'DXT5', reglages=R)
    m0 = decode_level(b1[68:68 + 32 * 32 * 16], 'dxt5', 128, 128)
    check('mip 0 of the .tex close to preparer_image (%.1f dB) and smoothing on (%.1f dB from the raw PNG)'
          % (psnr(m0[..., :3], ref[..., :3]), psnr(ref[..., :3], img[..., :3])),
          psnr(m0[..., :3], ref[..., :3]) > 35 and not np.array_equal(ref, img))
    o3 = os.path.join(tmp, 'argb8.tex')
    # NEUTRAL hash: since 2026-10-06, 0x0133FD92 (black atlas) has its own treatment (par_texture)
    png2tex.write_tex(p, o3, 0x12345678, None, 'ARGB8', 'full', None, reglages=R)
    b3 = open(o3, 'rb').read()
    px = np.frombuffer(b3, np.uint8, 128 * 128 * 4, 68).reshape(128, 128, 4)[..., [2, 1, 0, 3]]
    check('ARGB8: mip 0 identical to the PNG (no smoothing), size %d' % len(b3),
          np.array_equal(px, img) and len(b3) == 68 + sum((128 >> k) ** 2 * 4 for k in range(8))
          and np.array_equal(png2tex.preparer_image(p, 'couleur', 'ARGB8', reglages=R), img))
    for w, h in ((1, 1), (2, 2), (4, 2)):
        q = os.path.join(tmp, 'mini_%dx%d.png' % (w, h)); Image.fromarray(img[:h, :w], 'RGBA').save(q)
        o = os.path.join(tmp, 'mini.tex'); png2tex.write_tex(q, o, 1, None, 'DXT1', 'full', None, reglages=R)
        b = open(o, 'rb').read()
        check('write_tex %dx%d DXT1: %d levels, %d bytes' % (w, h, b[36], len(b)),
              b[36] == max(w, h).bit_length() and len(b) == 68 + 8 * b[36])
    # settings (keys and values are png2tex's: 'rapide' is a valid encoder, 'turbo' an invalid one)
    j = os.path.join(tmp, 'reglages.json')
    json.dump({'encodeur': 'rapide', 'lissage': {'rayon': 2}}, open(j, 'w'))
    R = png2tex.charger_reglages(j)
    check('partial settings: encoder rapide, radius 2, the rest by default',
          R['encodeur'] == 'rapide' and R['lissage']['rayon'] == 2 and R['lissage']['actif'] is True
          and R['mips_couleur'] == 'srgb' and R['normale_fondu'] == png2tex.DEFAUTS['normale_fondu'])
    json.dump({'encodeur': 'turbo', 'mips_couleur': 3, 'lissage': {'rayon': -1, 'actif': 'oui', 'garde_noir': [3, 1]},
               'normale_fondu': [2], 'normale_renormaliser': 'oui', 'par_texture': 5}, open(j, 'w'))
    R = png2tex.charger_reglages(j)
    check('invalid settings -> default values', R == png2tex.DEFAUTS)
    # par_texture: the black atlas 0x0133FD92 is not smoothed by default; a table in the file replaces it
    check('default par_texture: black atlas 0x0133FD92 without smoothing, red one smoothed',
          png2tex.reglages_texture(png2tex.DEFAUTS, 0x0133FD92)['lissage']['actif'] is False
          and png2tex.reglages_texture(png2tex.DEFAUTS, 0x8E661B33)['lissage']['actif'] is True)
    json.dump({'par_texture': {'133fd92': {'lissage': {'rayon': 99, 'sigma_couleur': 2}},
                               'pas_un_hash': {}, '_note': 'commentaire'}}, open(j, 'w'))
    R = png2tex.charger_reglages(j)
    E = png2tex.reglages_texture(R, 0x0133FD92)
    check('par_texture read: key normalised, invalid value refused (radius 4 kept), sigma 2 applied, '
          'smoothing on (the table in the file replaces the default one)',
          list(R['par_texture']) == ['0x0133FD92'] and E['lissage']['rayon'] == 4
          and E['lissage']['sigma_couleur'] == 2.0 and E['lissage']['actif'] is True)
    on = os.path.join(tmp, '0x0133FD92.noir.tex')
    ra = png2tex.write_tex(p, on, 0x0133FD92, None, 'DXT5', 'full', None)
    prep = png2tex.preparer_image(p, 'couleur', 'DXT5', hash_=0x0133FD92)
    bn = open(on, 'rb').read()
    pxn = np.frombuffer(bn, np.uint8, 128 * 128 * 4, 68).reshape(128, 128, 4)[..., [2, 1, 0, 3]]
    check('write_tex under 0x0133FD92 (installed texture_qualite.json): ARGB8 forced, no bilateral, '
          'fabric smoothed, mip 0 == preparer_image(hash_)', 'par_texture 0x0133FD92' in ra and 'ARGB8' in ra
          and 'lissage non' in ra and 'lissage_tissu' in ra and bn[40:44] == struct.pack('<I', 21)
          and np.array_equal(pxn, prep) and not np.array_equal(prep, img), ra[:90])
    # taille_max: 2x2 sRGB reduction of mip 0; normale_plaquer: weak relief flattened
    ot = os.path.join(tmp, 'tmax.tex')
    rt = png2tex.write_tex(p, ot, 0x12345678, None, 'ARGB8', 'full', None, reglages={'taille_max': 64})
    bt = open(ot, 'rb').read()
    check('taille_max 64: 128 -> 64, 7 mips, mip 0 = 2x2 sRGB mean', np.frombuffer(bt[24:40], '<u4').tolist() == [64, 64, 1, 7]
          and np.abs(np.frombuffer(bt, np.uint8, 64 * 64 * 4, 68).reshape(64, 64, 4)[..., [2, 1, 0]].astype(float)
                     - img[..., :3].astype(float).reshape(64, 2, 64, 2, 3).mean((1, 3))).max() <= 1.0, rt[:80])
    xx = np.linspace(0, 6 * np.pi, 64)
    nrm = np.zeros((64, 64, 4), np.uint8); nrm[..., 1] = 128
    nrm[..., 3] = np.clip(128 + 8 * np.sin(xx)[None, :], 0, 255).astype(np.uint8)      # weak relief ~3.5 deg
    nrm[:, 30:34, 3] = 230                                                            # one strong edge
    pn = os.path.join(tmp, 'normale_plaquer.png'); Image.fromarray(nrm, 'RGBA').save(pn)
    pl = png2tex.preparer_image(pn, 'normale', reglages={'normale_plaquer': [9.0, 14.0]})
    check('normale_plaquer [9, 14]: weak relief flattened, strong edge kept',
          np.abs(pl[:, 5:20, 3].astype(int) - 128).max() <= 1 and pl[:, 31, 3].min() > 200)
    # blacksuit_package check: reference prepared with the hash READ from the .tex
    sys.path.insert(0, OUTILS)
    from blacksuit_package import controle_texture
    ok = True; detail = []
    for h, nom in ((0x0133FD92, 'black'), (0x8E661B33, 'red')):
        o = os.path.join(tmp, '0x%08X.ctl.tex' % h)
        png2tex.write_tex(p, o, h, None, 'DXT5', 'full', None)
        c = controle_texture(open(o, 'rb').read(), p, 'DXT5')
        if c.get('exact'):           # black atlas: ARGB8 forced by par_texture -> exact equality
            detail.append('%s ARGB8 exact' % nom)
            continue
        ok &= c['ecart_moyen_par_canal'] == c['ecart_encodeur_sur_ce_contenu']
        detail.append('%s %.2f dB' % (nom, c['psnr_rgb_db']))
    check('blacksuit_package.controle_texture: gap == expected gap, black atlas (raw) AND red one (smoothed)', ok,
          ', '.join(detail))
    # like=: only 24 bytes are read, a short file is padded with zeros
    court = os.path.join(tmp, 'court.bin'); open(court, 'wb').write(b'\x07' * 10)
    o = os.path.join(tmp, 'like.tex'); png2tex.write_tex(p, o, 0x8E661B33, court, 'DXT5', 'full', None, reglages=R)
    b = open(o, 'rb').read()
    check('like= shorter than 24 bytes: 68-byte header intact', b[:10] == b'\x07' * 10 and b[10:12] == b'\0\0'
          and np.frombuffer(b[12:16], '<u4')[0] == 0x8E661B33 and len(b) == len(b1))
    open(j, 'w').write('{ pas du json')
    check('unreadable file -> default values', png2tex.charger_reglages(j) == png2tex.DEFAUTS)
    check('missing file -> default values',
          png2tex.charger_reglages(os.path.join(tmp, 'rien.json')) == png2tex.DEFAUTS)
    vrai = os.path.join(RACINE, 'texture_qualite.json')
    if os.path.isfile(vrai):
        check('texture_qualite.json of the installation is readable', isinstance(png2tex.charger_reglages(vrai), dict))


def main():
    t0 = time.time()
    test_blocs_synthetiques()
    atlas = _atlas()
    test_atlas(atlas)
    test_tailles(atlas)
    with tempfile.TemporaryDirectory() as tmp:
        test_normale(tmp)
        test_fond_sombre()
        test_write_tex(tmp)
    rate = [r for r in _resultats if not r[1]]
    print('\n%d checks, %d failure(s), %.0f s' % (len(_resultats), len(rate), time.time() - t0))
    for nom, _, detail in rate:
        print('  FAIL:', nom, detail)
    return 1 if rate else 0


if __name__ == '__main__':
    sys.exit(main())
