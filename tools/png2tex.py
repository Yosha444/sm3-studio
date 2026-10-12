# SPDX-License-Identifier: GPL-3.0-or-later
"""png2tex.py - convert an image (PNG/JPG/DDS readable by Pillow) into a loose TEX resource for xeSM3.

Used by sm3_convertir.py (atlas and normal map of the red suit, loaded in-process with write_tex),
blacksuit_package.py, rvb_finalize.py, the Venom tools and support_venom_direct/make_atlas.py;
usable on its own. It encodes the PNG that dilater_atlas.py (project root) prepares.

Loose TEX format (measured on the CH_BLACKSUIT extractions and the vanilla headers of
CH_SPIDERMAN.PCPACK):
  68-byte header: dw[0..1]=0, dw[2]=serialised name pointer (copied from the vanilla), dw[3]=djb2
  hash, dw[4..5]=0, dw[6]=width, dw[7]=height, dw[8]=1, dw[9]=mip count, dw[10]=fourcc
  ('DXT1'/'DXT5', or 21 = D3DFMT_A8R8G8B8), dw[11..16]=0; then the complete chain (mip 0 down to
  1x1, 8 bytes minimum per DXT1 level, 16 in DXT5; ARGB8 stored B,G,R,A).

Usage:
  python png2tex.py <image> <output.tex> --hash 0x8E661B33 [--like vanilla.hdr68.bin] [--dxt5]
                    [--format DXT1|DXT5|ARGB8] [--mips N|full] [--size 1024]
                    [--genre couleur|normale] [--reglages texture_qualite.json]
  --like   : vanilla .tex or .hdr68.bin whose first 24 bytes (name pointer) are copied
  --mips   : 'full' (default) = down to 1x1; 1 = no mips; N = N levels
  --genre  : forces the kind ("genre"): couleur (colour) or normale (normal map); otherwise
             'normale' for hash 0x61DCA273 or a file name containing 'normale' / 'normswizzle',
             'couleur' for everything else
Dependencies: numpy, Pillow, and tools/sm3/dxtenc.py. NOTHING else: this file is loaded from disk
by the FROZEN interpreter of SM3 Studio.exe, which has neither scipy, nor cv2, nor numba.

Texture chain (2026-10-06) -- settings in <root>/texture_qualite.json (French keys, kept):

  COLOUR (default)
    1. edge-preserving smoothing of mip 0: CIELAB bilateral filter (radius 4, spatial sigma 3,
       colour sigma 5 dE), averaged in linear light, applied ONLY outside the background. It
       erases the bake noise that DXT turned into dirty blocks, without touching the web lines
       (high dE). Never in ARGB8 (lossless: mip 0 must stay the exact PNG).
       BLACK GUARD: below L* 0.5 the texel stays raw, above L* 3 it is fully smoothed, in between
       it is blended. All the black fits within a few dE: without this guard, the almost-black
       gaps between the symbiote's scales were washed out to grey (contrast 88 % -> 35 %). With
       it: 88.6 %, and the approved red suit changes on only 0.36 % of its texels.
    2. mips: 2x2 average in sRGB (default, as before) or in linear light (option), in FLOATING
       POINT from one level to the next (no more 8-bit round trips).
    3. background: mask computed ONCE at mip 0 (RGB exactly 0,0,0, or alpha 0 if the image has a
       real alpha), propagated by a 2x2 logical AND; only those texels are filled (2 rings per
       level) before each reduction. Atlas already dilated (background < fond_min_pct): nothing
       to do.
    4. high-quality DXT encoder (sm3/dxtenc.py).
  NORMAL MAP (SM3 swizzle: X in the ALPHA, Y in the GREEN, R = B = 0, always DXT5)
    mips in floating point: 2x2 average of x and y, then LINEAR fade of the relief per level
    (f*x, f*y; f = 1, 1, 0.75, 0.5, 0.3, 0.15, 0 then 0) -- exactly the chain of the red-suit
    normal map validated in game (rouge_propre_fondu). Never a Pillow reduction of an RGBA,
    which PREMULTIPLIES by the alpha (= x) and corrupted y at each level. (Option
    normale_renormaliser: average of (x,y,z) renormalised -- more relief than the approved one.)
  PER TEXTURE (par_texture, key = hash): settings that apply to one slot only.

  BLACK SUIT (2026-10-06, validated in game: "it works") -- default for 0x0133FD92:
    - NO bilateral (the whole symbiote sits below L* 3: the CIELAB filter is blind there) but
      lissage_tissu ("fabric smoothing"): the BASE of the fabric (everything except the web
      lines, logos and eyes, found by their lightness) is blurred in linear light (sigma 16
      texels, detail 0). The pattern of scales / dots kept on an almost-black background had
      ~50 % relative contrast: it was the grain seen in game (14.6 % rendered noise against
      5.4 % on the validated red suit).
    - format_force ARGB8 + taille_max 2048: DXT 565 cannot render near-blacks (steps of 8 levels
      in R/B) and stained them purple / green, and fringed the web. ARGB8 2048 = same file size
      as DXT5 4096, zero compression error at the mips seen in game.
    - black suit normal map (blacksuit_package): noir_normale_plaquer [9, 14] -- the fabric's
      relief (smoothed slope < 9 deg) is flattened, the web keeps its own (like the red suit).

The text report returned by write_tex() is partly French on purpose: sm3/dxtenc_selftest.py
looks for the fragments 'chaine reprise', 'sautee', 'lissage non' and 'par_texture 0x...' in it.
"""
import sys, os, struct, argparse, json, time
ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
sys.path.insert(0, os.path.join(ICI, '..', '..', 'tools'))
sys.path.insert(0, ICI)
import numpy as np
from PIL import Image
from sm3.dxtenc import dxt1_encode, dxt5_encode
try:
    from sm3.dxtenc import ENCODEURS
except ImportError:          # old dxtenc.py without a switch: only one encoder available
    ENCODEURS = {'hq': {'DXT1': dxt1_encode, 'DXT5': dxt5_encode},
                 'rapide': {'DXT1': dxt1_encode, 'DXT5': dxt5_encode}}

HASH_NORMALE = 0x61DCA273          # the suit's normal map slot (_normswizzle)
HASH_ATLAS_NOIR = 0x0133FD92       # the black suit's colour texture
FICHIER_REGLAGES = os.path.join(RACINE, 'texture_qualite.json')
# Default settings; texture_qualite.json overrides them key by key (French keys, kept).
DEFAUTS = {
    'encodeur': 'hq',
    'lissage': {'actif': True, 'rayon': 4, 'sigma_spatial': 3.0, 'sigma_couleur': 5.0,
                'garde_noir': [0.5, 3.0]},
    'mips_couleur': 'srgb',
    'normale_fondu': [1.0, 1.0, 0.75, 0.5, 0.3, 0.15, 0.0],
    'normale_renormaliser': False,
    'dilatation': {'actif': True, 'anneaux': 2, 'fond_min_pct': 5.0},
    # Smoothing of the BASE of the fabric (lines / logos / eyes = texels of sRGB lightness >=
    # seuil_fil, dilated by fil_dilate texels, kept as they are). Off by default; on for the
    # black atlas.
    'lissage_tissu': {'actif': False, 'sigma': 16.0, 'detail': 0.0, 'seuil_fil': 48.0, 'fil_dilate': 3},
    'format_force': '',          # '' = the format the caller asks for; otherwise ARGB8 / DXT5 / DXT1
    'taille_max': 0,             # 0 = no limit; otherwise 2x2 sRGB reduction down to this size
    'normale_plaquer': [0.0, 0.0],        # [low, high] degrees; [0, 0] = fabric relief kept
    'noir_normale_plaquer': [9.0, 14.0],  # what blacksuit_package applies to the BLACK suit's normal map
    # WARNING: BLACK suit atlas: NO bilateral (the whole symbiote sits below L* 3, the filter is
    # blind there and its guard leaves it raw) BUT lissage_tissu + ARGB8 2048 -- the version
    # validated in game on 2026-10-06 (grain -69 %, DXT colour stains -61 % measured on the render).
    'par_texture': {'0x%08X' % HASH_ATLAS_NOIR: {'lissage': {'actif': False},
                                                 'lissage_tissu': {'actif': True},
                                                 'format_force': 'ARGB8', 'taille_max': 2048}},
}


def _log(*x):
    print('[png2tex]', *x, flush=True)


# =====================================================================================
# Settings
# =====================================================================================

def _copie(d):
    """Deep copy of a JSON-like dict."""
    return json.loads(json.dumps(d))


def _nombre(v, lo, hi):
    """True if v is a number (not a bool) within [lo, hi]."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi


# validation rules of the nested blocks: key -> 'bool', 'plage' (range [a, b]) or (min, max, type)
_REGLES_BLOCS = (('lissage', {'actif': 'bool', 'rayon': (0, 16, int),
                              'sigma_spatial': (0.1, 50.0, float),
                              'sigma_couleur': (0.1, 100.0, float),
                              'garde_noir': 'plage'}),
                 ('dilatation', {'actif': 'bool', 'anneaux': (0, 64, int),
                                 'fond_min_pct': (0.0, 100.0, float)}),
                 ('lissage_tissu', {'actif': 'bool', 'sigma': (0.0, 64.0, float),
                                    'detail': (0.0, 1.0, float), 'seuil_fil': (0.0, 255.0, float),
                                    'fil_dilate': (0, 32, int)}))


def _appliquer(R, lu, origine=''):
    """("apply") Copy into R the VALID keys of the dict `lu` (read from a JSON). An invalid value
    is reported and ignored: R keeps what it had (default, or global setting for par_texture)."""
    def refuse(cle, v):
        d = R
        for k in cle.split('.'):
            d = d.get(k) if isinstance(d, dict) else None
        _log('setting %s%s = %r invalid: %r kept' % (origine, cle, v, d))

    if 'encodeur' in lu:
        v = str(lu['encodeur']).lower()
        if v in ENCODEURS:
            R['encodeur'] = v
        else:
            refuse('encodeur', lu['encodeur'])
    if 'mips_couleur' in lu:
        v = str(lu['mips_couleur']).lower()
        if v in ('srgb', 'lineaire'):
            R['mips_couleur'] = v
        else:
            refuse('mips_couleur', lu['mips_couleur'])
    if 'normale_fondu' in lu:
        v = lu['normale_fondu']
        if isinstance(v, list) and v and all(_nombre(x, 0.0, 1.0) for x in v):
            R['normale_fondu'] = [float(x) for x in v]
        else:
            refuse('normale_fondu', v)
    if 'normale_renormaliser' in lu:
        v = lu['normale_renormaliser']
        if isinstance(v, bool):
            R['normale_renormaliser'] = v
        else:
            refuse('normale_renormaliser', v)
    if 'format_force' in lu:
        v = str(lu['format_force'] or '').upper()
        if v in ('', 'ARGB8', 'DXT5', 'DXT1'):
            R['format_force'] = v
        else:
            refuse('format_force', lu['format_force'])
    if 'taille_max' in lu:
        v = lu['taille_max']
        if _nombre(v, 0, 16384) and float(v).is_integer() and (int(v) == 0 or int(v) & (int(v) - 1) == 0):
            R['taille_max'] = int(v)
        else:
            refuse('taille_max', v)
    for cle in ('normale_plaquer', 'noir_normale_plaquer'):
        if cle in lu:
            v = lu[cle]
            if (isinstance(v, list) and len(v) == 2 and all(_nombre(x, 0.0, 90.0) for x in v)
                    and v[0] <= v[1]):
                R[cle] = [float(v[0]), float(v[1])]
            else:
                refuse(cle, v)
    for bloc, regles in _REGLES_BLOCS:
        sous = lu.get(bloc)
        if sous is None:
            continue
        if not isinstance(sous, dict):
            refuse(bloc, sous)
            continue
        for cle, regle in regles.items():
            if cle not in sous:
                continue
            v = sous[cle]
            if regle == 'bool':
                if isinstance(v, bool):
                    R[bloc][cle] = v
                else:
                    refuse(bloc + '.' + cle, v)
            elif regle == 'plage':
                # [L* without smoothing, L* fully smoothed]; [0, 0] = no guard
                if (isinstance(v, list) and len(v) == 2 and all(_nombre(x, 0.0, 100.0) for x in v)
                        and v[0] <= v[1]):
                    R[bloc][cle] = [float(v[0]), float(v[1])]
                else:
                    refuse(bloc + '.' + cle, v)
            else:
                lo, hi, typ = regle
                if _nombre(v, lo, hi) and (typ is float or float(v).is_integer()):
                    R[bloc][cle] = typ(v)
                else:
                    refuse(bloc + '.' + cle, v)


def _cle_hash(k):
    """'0x0133fd92', '0133FD92', 19135890 -> '0x0133FD92'; None if it is not a hash."""
    try:
        h = k if isinstance(k, int) and not isinstance(k, bool) else int(str(k).strip(), 16)
    except ValueError:
        return None
    return '0x%08X' % h if 0 <= h <= 0xFFFFFFFF else None


def _table_textures(v):
    """Validate the par_texture table read from the JSON. Returns the normalised dict, or None."""
    if not isinstance(v, dict):
        return None
    table = {}
    for k, sous in v.items():
        if str(k).startswith('_'):          # "_aide", "_exemple" ...: comments
            continue
        cle = _cle_hash(k)
        if cle is None or not isinstance(sous, dict):
            _log('par_texture: entry %r ignored (key = hash 0x........, value = object)' % (k,))
            continue
        table[cle] = sous
    return table


def charger_reglages(chemin=None):
    """("load the settings") Read texture_qualite.json. Missing or unreadable file, missing key
    or invalid value: default value (and a warning for what is invalid). A par_texture table
    present in the file REPLACES the default one (write {} to keep none)."""
    R = _copie(DEFAUTS)
    chemin = chemin or FICHIER_REGLAGES
    try:
        with open(chemin, encoding='utf-8') as f:
            lu = json.load(f)
    except FileNotFoundError:
        return R
    except Exception as e:
        _log('%s unreadable (%s): default settings' % (os.path.basename(chemin), e))
        return R
    if not isinstance(lu, dict):
        _log('%s: JSON object expected, default settings' % os.path.basename(chemin))
        return R
    _appliquer(R, lu)
    if 'par_texture' in lu:
        table = _table_textures(lu['par_texture'])
        if table is None:
            _log('setting par_texture = %r invalid: default %r kept' % (lu['par_texture'], R['par_texture']))
        else:
            R['par_texture'] = table
    return R


def _reglages(reglages):
    """Settings from a dict (completed with the defaults for missing keys), the path of a JSON,
    or None (texture_qualite.json at the root)."""
    if isinstance(reglages, dict):
        R = _copie(DEFAUTS)
        for k, v in reglages.items():
            if isinstance(v, dict) and isinstance(R.get(k), dict) and k != 'par_texture':
                R[k].update(v)
            else:
                R[k] = v
        return R
    return charger_reglages(reglages)


def _reglages_effectifs(reglages, hash_):
    """(settings for THIS texture, par_texture key applied or None)."""
    R = _reglages(reglages)
    cle = None if hash_ is None else _cle_hash(int(hash_) & 0xFFFFFFFF)
    sous = (R.get('par_texture') or {}).get(cle) if cle else None
    if not sous:
        return R, None
    E = _copie(R)
    _appliquer(E, sous, 'par_texture.%s.' % cle)
    return E, cle


def reglages_texture(reglages=None, hash_=None):
    """The settings that apply to texture `hash_`: global ones, then its par_texture entry."""
    return _reglages_effectifs(reglages, hash_)[0]


def genre_texture(image_path=None, out_path=None, hash_=None, genre=None):
    """("kind of texture") 'normale' for the suit's swizzled map (hash 0x61DCA273, or a file name
    containing 'normale' or 'normswizzle'), 'couleur' otherwise. An explicit `genre` wins."""
    if genre:
        g = str(genre).lower()
        if g in ('normale', 'normal'):
            return 'normale'
        if g == 'couleur':
            return 'couleur'
        raise ValueError('unknown texture kind: %r (couleur | normale)' % genre)
    if hash_ is not None and (int(hash_) & 0xFFFFFFFF) == HASH_NORMALE:
        return 'normale'
    for p in (image_path, out_path):
        if p:
            nom = os.path.basename(str(p)).lower()
            if 'normale' in nom or 'normswizzle' in nom:
                return 'normale'
    return 'couleur'


def encodeur(fmt, reglages=None, hash_=None):
    """The DXT encoding function write_tex uses for this format, these settings and this hash."""
    R = reglages_texture(reglages, hash_)
    return ENCODEURS[R['encodeur']][fmt]


# =====================================================================================
# Colour: sRGB, CIELAB, bilateral smoothing (pure numpy)
# =====================================================================================

def _srgb_vers_lin(x):
    """x in 0..1 -> linear light 0..1."""
    x = np.asarray(x, np.float32)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def _lin_vers_srgb255(y):
    """linear light 0..1 -> sRGB 0..255 (floating point)."""
    y = np.clip(np.asarray(y, np.float32), 0.0, 1.0)
    return (np.where(y <= 0.0031308, 12.92 * y, 1.055 * np.power(y, 1 / 2.4) - 0.055)
            * 255.0).astype(np.float32)


_LUT_LIN = _srgb_vers_lin(np.arange(256, dtype=np.float32) / 255.0)       # uint8 -> linear
_M_XYZ = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722],
                   [0.0193, 0.1192, 0.9505]], np.float32)                 # linear sRGB -> XYZ
_BLANC = np.array([0.95047, 1.0, 1.08883], np.float32)                    # D65 white point


def _lab_depuis_lin(lin):
    """lin (3, ...) linear light 0..1 -> (3, ...) L*, a*, b* (D65)."""
    f = []
    for i in range(3):
        t = (_M_XYZ[i, 0] * lin[0] + _M_XYZ[i, 1] * lin[1] + _M_XYZ[i, 2] * lin[2]) / _BLANC[i]
        f.append(np.where(t > 216 / 24389, np.cbrt(t), (24389 / 27 * t + 16) / 116))
    return np.stack([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])]).astype(np.float32)


def _rampe(L, garde):
    """Smoothing strength from the texel's RAW lightness: 0 below garde[0], 1 above garde[1],
    smooth transition (smoothstep) in between. garde None or [0, 0]: 1 everywhere."""
    lo, hi = float(garde[0]), float(garde[1])
    if hi <= 0.0:
        return np.ones(L.shape, np.float32)
    if hi <= lo:
        return (L >= hi).astype(np.float32)
    t = np.clip((L - lo) / (hi - lo), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


def lisser_bilateral(rgb, masque=None, rayon=4, sigma_spatial=3.0, sigma_couleur=5.0, bande=64,
                     garde_noir=None):
    """("bilateral smoothing") Edge-preserving bilateral filter: weight = spatial Gaussian x
    exp(-dE^2/2 sr^2), dE in CIELAB, averaged in LINEAR light. Texels outside `masque` are never
    used as neighbours and do not change. Pure-numpy port of denoise.bilateral_lab
    (C_albedo_B_lisse, validated in game on the red suit on 2026-10-06).

    garde_noir = [L0, L1] (L*): the result is pulled back towards the RAW texel according to its
    lightness -- raw below L0, fully smoothed above L1, blended in between (in linear light).
    WARNING: why: from deep black to the symbiote's scales there are only 3 to 8 dE, the filter
    sees noise there and washes out the almost-black gaps (RGB sum 3.8 -> 24.8). The dark
    neighbours stay in the average of the other texels: excluding them would raise the scales
    (measured bias: +1.2 on the darkest band, relief x1.4). Without a guard (None or [0, 0]): the
    original filter, byte for byte.

    rgb: (h, w, 3+) uint8. Returns (h, w, 3) uint8. Processed in bands of `bande` rows (bounded
    memory) and by PAIRS of symmetric neighbours (the weight from p to q is the one from q to p:
    each exponential serves twice)."""
    rgb = np.asarray(rgb)[..., :3]
    H, W = rgb.shape[:2]
    r = int(rayon)
    if r <= 0:
        return rgb.copy()
    if garde_noir is not None and float(garde_noir[1]) <= 0.0:
        garde_noir = None
    m_tout = np.ones((H, W), bool) if masque is None else np.asarray(masque, bool)
    inv = np.float32(1.0 / (2.0 * float(sigma_couleur) ** 2))
    paires = []
    for dy in range(0, r + 1):
        for dx in range(-r, r + 1):
            if dy == 0 and dx <= 0:
                continue
            ws = float(np.exp(-(dy * dy + dx * dx) / (2.0 * float(sigma_spatial) ** 2)))
            if ws >= 0.01:
                paires.append((dy, dx, np.float32(ws)))
    sortie = rgb.copy()
    for y0 in range(0, H, bande):
        y1 = min(H, y0 + bande)
        a0 = max(0, y0 - r); a1 = min(H, y1 + r); hw = a1 - a0
        m = m_tout[a0:a1].astype(np.float32)
        if not m[y0 - a0:y1 - a0].any():
            continue
        lin = np.ascontiguousarray(_LUT_LIN[rgb[a0:a1]].transpose(2, 0, 1))     # (3, hw, W)
        lab = _lab_depuis_lin(lin)
        acc = lin * m                                                            # centre: weight 1
        wsum = m.copy()
        tw = np.empty((hw, W), np.float32); tt = np.empty((hw, W), np.float32)
        tx = np.empty((hw, W), np.float32)
        for dy, dx, ws in paires:
            nr = hw - dy
            pr = slice(0, nr); qr = slice(dy, hw)
            nc = W - abs(dx)
            if nr <= 0 or nc <= 0:          # image smaller than the neighbourhood
                continue
            if dx >= 0:
                pc = slice(0, nc); qc = slice(dx, W)
            else:
                pc = slice(-dx, W); qc = slice(0, nc)
            w = tw[:nr, :nc]; t = tt[:nr, :nc]; x = tx[:nr, :nc]        # reused buffers
            np.subtract(lab[0, pr, pc], lab[0, qr, qc], out=w); np.multiply(w, w, out=w)
            np.subtract(lab[1, pr, pc], lab[1, qr, qc], out=t); np.multiply(t, t, out=t); w += t
            np.subtract(lab[2, pr, pc], lab[2, qr, qc], out=t); np.multiply(t, t, out=t); w += t
            w *= -inv
            np.exp(w, out=w)
            np.multiply(m[pr, pc], m[qr, qc], out=t); t *= ws; w *= t
            for c in range(3):
                np.multiply(w, lin[c, qr, qc], out=x); acc[c, pr, pc] += x
                np.multiply(w, lin[c, pr, pc], out=x); acc[c, qr, qc] += x
            wsum[pr, pc] += w
            wsum[qr, qc] += w
        cr = slice(y0 - a0, y1 - a0)
        res = acc[:, cr] / np.maximum(wsum[cr], 1e-12)
        if garde_noir is not None:
            g = _rampe(lab[0, cr], garde_noir)
            partiel = g < 1.0
            if partiel.any():
                # elsewhere (g == 1) the result stays the original filter's, byte for byte
                brut = lin[:, cr]
                res = np.where(partiel, brut + g * (res - brut), res)
        res = np.clip(np.rint(_lin_vers_srgb255(res)), 0, 255).astype(np.uint8).transpose(1, 2, 0)
        garde = m_tout[y0:y1]
        sortie[y0:y1][garde] = res[garde]
    return sortie


# =====================================================================================
# Background, 2x2 reductions
# =====================================================================================

def masque_fond(rgba):
    """("background mask") True = BACKGROUND texel: alpha 0 if the image has a real alpha,
    otherwise RGB exactly (0,0,0).

    WARNING: never again a colour threshold (the old R+G+B <= 6): on the black suit, LEGITIMATE
    dark texels of the body passed it and were overwritten by their neighbours at each mip."""
    a = rgba[..., 3]
    if (a != 255).any():
        fond = a == 0
    else:
        fond = ~rgba[..., :3].any(-1)
    if fond.all():               # entirely "empty" image: nothing to protect or fill
        fond[:] = False
    return fond


def _reduire(cur):
    """2x2 average in floating point; an axis already at 1 is not reduced."""
    if cur.shape[0] > 1:
        cur = (cur[0::2] + cur[1::2]) * np.float32(0.5)
    if cur.shape[1] > 1:
        cur = (cur[:, 0::2] + cur[:, 1::2]) * np.float32(0.5)
    return cur


def _reduire_masque(m):
    """2x2 logical AND: a reduced texel is background only if its four children are."""
    if m.shape[0] > 1:
        m = m[0::2] & m[1::2]
    if m.shape[1] > 1:
        m = m[:, 0::2] & m[:, 1::2]
    return m


# =====================================================================================
# Black suit: fabric smoothing, relief flattening (numpy only, no scipy in the .exe)
# =====================================================================================

def _flou_boite(x, r):
    """("box blur") Sliding mean of width 2r+1, separable, edges replicated. Cumulative sums in
    float64: on an almost-black background (linear ~0.001) float32 lost the precision."""
    if r <= 0:
        return x
    for ax in (0, 1):
        n = x.shape[ax]
        pad = [(0, 0)] * x.ndim
        pad[ax] = (r + 1, r)
        c = np.cumsum(np.pad(x, pad, mode='edge'), axis=ax, dtype=np.float64)
        haut = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=ax)
        bas = np.take(c, np.arange(0, n), axis=ax)
        x = ((haut - bas) / (2 * r + 1)).astype(np.float32)
        del c, haut, bas
    return x


def _flou_gauss(x, sigma, passes=3):
    """Gaussian approximated by 3 boxes (variance n(w^2-1)/12 = sigma^2)."""
    if sigma <= 0:
        return x
    w = np.sqrt(12.0 * sigma * sigma / passes + 1.0)
    r = max(1, int(round((w - 1.0) / 2.0)))
    for _ in range(passes):
        x = _flou_boite(x, r)
    return x


def _max_glissant(m, r):
    """Maximum over a (2r+1) x (2r+1) window, separable, edges replicated."""
    if r <= 0:
        return m
    for ax in (0, 1):
        n = m.shape[ax]
        pad = [(0, 0)] * m.ndim
        pad[ax] = (r, r)
        p = np.pad(m, pad, mode='edge')
        out = np.take(p, np.arange(0, n), axis=ax)
        for k in range(1, 2 * r + 1):
            np.maximum(out, np.take(p, np.arange(k, k + n), axis=ax), out=out)
        m = out
    return m


def lisser_tissu(base, hors, L, info):
    """("smooth the fabric") Smooth the BASE of the fabric of a dark atlas (black suit) without
    touching the web lines, the logos or the eyes. Returns the new RGB uint8 (h, w, 3).

    Lines = texels of sRGB lightness >= seuil_fil, dilated by fil_dilate texels, with a
    one-texel ramp: weight w = 1 -> identical bytes. Base (w = 0, outside the background):
    Gaussian blur of sigma normalised over the base texels only, in LINEAR light, channel by
    channel; base' = blur + detail x (original - blur). The tone seen from afar is kept. No new
    (0,0,0) is created (exact black is the BACKGROUND for the rest of the chain)."""
    t = time.time()
    rgb = base[..., :3]
    luma = (rgb[..., 0] * np.float32(0.2126) + rgb[..., 1] * np.float32(0.7152)
            + rgb[..., 2] * np.float32(0.0722))
    fil = luma >= np.float32(L['seuil_fil'])
    del luma
    w = _max_glissant(fil.astype(np.float32), int(L['fil_dilate']))
    w = np.clip(_flou_boite(w, 1) * np.float32(1.5), 0.0, 1.0)
    w[fil] = 1.0
    if hors is None:
        hors = np.zeros(fil.shape, bool)
    bp = ((w <= 0.0) & ~hors).astype(np.float32)
    sigma = float(L['sigma'])
    detail = np.float32(L['detail'])
    den = np.maximum(_flou_gauss(bp, sigma), np.float32(1e-6))
    out = np.empty(rgb.shape, np.float32)
    for c in range(3):
        lin = _LUT_LIN[rgb[..., c]]
        lisse = _flou_gauss(lin * bp, sigma) / den
        out[..., c] = w * lin + (1.0 - w) * (lisse + detail * (lin - lisse))
        del lin, lisse
    s = np.clip(np.rint(_lin_vers_srgb255(out)), 0, 255).astype(np.uint8)
    del out
    garde = hors | (w >= 1.0)
    s[garde] = rgb[garde]
    nouveaux = ~s.any(-1) & ~hors
    s[nouveaux] = 1
    info['lissage_tissu'] = 'sigma %g detail %g, lines >= %g (%.2f %%), %.1f s' % (
        sigma, float(detail), float(L['seuil_fil']), 100.0 * float(fil.mean()), time.time() - t)
    return s


def plaquer_relief(x, y, bas, haut):
    """("flatten the relief") Flatten the WEAK relief of a normal map (smoothed slope < bas
    degrees), keep the strong one (> haut: the ridges of the web), smoothstep transition then a
    5x5 maximum to keep the sides of the ridges. Same recipe as the validated red normal map
    (--plaquer) and as B1."""
    z = np.sqrt(np.clip(1.0 - x * x - y * y, 0.0, None)).astype(np.float32)
    bx, by, bz = (_flou_gauss(c, 1.5) for c in (x, y, z))
    pente = np.degrees(np.arctan2(np.hypot(bx, by), bz))
    del bx, by, bz, z
    w = np.clip((pente - bas) / max(haut - bas, 1e-6), 0.0, 1.0).astype(np.float32)
    w = w * w * (3.0 - 2.0 * w)
    w = _max_glissant(w, 2)
    return x * w, y * w, float((w == 0).mean())


def _flottant(base, lineaire):
    """uint8 (h, w, 4) -> float32; RGB in linear light 0..1 if asked, alpha 0..255."""
    f = base.astype(np.float32)
    if lineaire:
        f[..., :3] = _LUT_LIN[base[..., :3]]
    return f


def _reduire_u8(base, lineaire):
    """First reduction straight from the uint8 mip 0 (no full floating-point copy)."""
    h, w = base.shape[:2]
    pas_y = (0, 1) if h > 1 else (0,)
    pas_x = (0, 1) if w > 1 else (0,)
    acc = None
    for dy in pas_y:
        for dx in pas_x:
            v = base[dy::len(pas_y), dx::len(pas_x)]
            f = _flottant(v, lineaire)
            if acc is None:
                acc = f
            else:
                acc += f
    acc *= np.float32(1.0 / (len(pas_y) * len(pas_x)))
    return acc


def _remplir_fond(img, fond, anneaux):
    """("fill the background") Fill the `fond` texels (RGB only) with the mean of their full
    neighbours, one ring at a time (4-neighbourhood, no wrapping at the edges). Modifies `img`
    (floating point)."""
    plein = ~fond
    if plein.all() or not plein.any():
        return img
    rgb = img[..., :3]
    for _ in range(anneaux):
        pf = plein.astype(np.float32)
        somme = np.zeros(rgb.shape, np.float32)
        compte = np.zeros(plein.shape, np.float32)
        somme[1:] += rgb[:-1] * pf[:-1, :, None]; compte[1:] += pf[:-1]
        somme[:-1] += rgb[1:] * pf[1:, :, None]; compte[:-1] += pf[1:]
        somme[:, 1:] += rgb[:, :-1] * pf[:, :-1, None]; compte[:, 1:] += pf[:, :-1]
        somme[:, :-1] += rgb[:, 1:] * pf[:, 1:, None]; compte[:, :-1] += pf[:, 1:]
        cible = (~plein) & (compte > 0)
        if not cible.any():
            break
        rgb[cible] = somme[cible] / compte[cible][:, None]
        plein = plein | cible
    return img


def dilater_niveau(a, passes=2, seuil=6):
    """OBSOLETE (kept for compatibility): the old dilation by COLOUR THRESHOLD.

    It treated as background every texel with R+G+B <= 6, at each level: on the black suit,
    legitimate dark texels of the body were overwritten by their neighbours. The chain now uses
    masque_fond() (computed once at mip 0) + _remplir_fond()."""
    a = a.astype(np.int16)
    for _ in range(passes):
        fond = a[:, :, :3].sum(2) <= seuil
        if not fond.any():
            break
        somme = np.zeros(a.shape[:2] + (3,), np.int32)
        compte = np.zeros(a.shape[:2], np.int32)
        plein = (~fond).astype(np.int32)
        rgb = a[:, :, :3].astype(np.int32) * plein[:, :, None]
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            somme += np.roll(np.roll(rgb, dy, 0), dx, 1)
            compte += np.roll(np.roll(plein, dy, 0), dx, 1)
        remplir = fond & (compte > 0)
        if not remplir.any():
            break
        a[:, :, :3][remplir] = (somme[remplir] // compte[remplir][:, None]).astype(np.int16)
    return a.astype(np.uint8)


# =====================================================================================
# Level chains
# =====================================================================================

def _niveaux_couleur(base, fond, nb, R, info):
    """Yields the `nb` levels: mip 0 as it is (uint8), then sRGB 0..255 floats."""
    yield base
    if nb <= 1:
        return
    lineaire = R['mips_couleur'] == 'lineaire'
    anneaux = int(R['dilatation']['anneaux']) if fond is not None else 0
    if anneaux > 0:
        cur = _remplir_fond(_flottant(base, lineaire), fond, anneaux)
    else:
        fond = None
        cur = None
    for _ in range(1, nb):
        cur = _reduire_u8(base, lineaire) if cur is None else _reduire(cur)
        if fond is not None:
            fond = _reduire_masque(fond)
            if fond.any():
                cur = _remplir_fond(cur, fond, anneaux)
            else:
                fond = None
        if lineaire:
            out = cur.copy()
            out[..., :3] = _lin_vers_srgb255(cur[..., :3])
            yield out
        else:
            yield cur


def _fondu(R, niveau):
    """Relief fade factor of a mip level (the last value repeats)."""
    f = R['normale_fondu']
    return float(f[min(niveau, len(f) - 1)])


def _niveaux_normale(base, nb, R, info):
    """Swizzled map: x = 2*ALPHA/255 - 1, y = 2*GREEN/255 - 1 (exact reading of the shader,
    `mad r3.xy, c47.x, r2.wyzw, c47.y`). Yields floating-point levels (h, w, 4): A = x, G = y,
    R = B = 0.

    Default (normale_renormaliser false) = the chain of the red normal map VALIDATED IN GAME
    (A_normale/outils/build_candidate.py, rouge_propre_fondu): mip L = 2x2 average of x and y in
    floating point, WITHOUT z nor renormalisation, then LINEAR fade (f*x, f*y).
    WARNING: do not "fix" it by renormalising: the average of (x,y,z) renormalised then
    normalise(f*x, f*y, z) keeps 18 to 24 % more slope at mips 2-5 (effective relief factor
    0.81/0.53/0.30/0.15 against the approved 0.69/0.44/0.25/0.13): the fade figures would no
    longer mean what was validated. That variant stays available as an option."""
    A = base[..., 3].astype(np.float32); G = base[..., 1].astype(np.float32)
    if (A == 255).all() and base[..., 0].any():
        # classic RGB map (X in the RED, full alpha): read it as such rather than turn it into a
        # pure tangent (x = +1 everywhere)
        info['normale_source'] = 'classic RGB (X read from the RED)'
        A = base[..., 0].astype(np.float32)
    x = A / np.float32(127.5) - 1; y = G / np.float32(127.5) - 1
    del A, G
    r2 = x * x + y * y
    trop = r2 > 1.0
    if trop.any():                          # impossible texels: brought back onto the unit circle
        info['texels_impossibles_corriges'] = int(trop.sum())
        k = np.where(trop, 1.0 / np.sqrt(np.maximum(r2, 1e-12)), 1.0).astype(np.float32)
        x *= k; y *= k
        del k
    del r2, trop
    plaq = R.get('normale_plaquer') or [0.0, 0.0]
    if float(plaq[1]) > 0.0:
        x, y, plat = plaquer_relief(x, y, float(plaq[0]), float(plaq[1]))
        info['normale_plaquer'] = 'slope < %g deg flattened, > %g kept (%.1f %% flat)' % (
            float(plaq[0]), float(plaq[1]), 100.0 * plat)
    renorm = bool(R.get('normale_renormaliser', False))
    info['normale_mips'] = ('mean (x,y,z) renormalised, fade normalise(f*x, f*y, z)' if renorm
                            else 'mean (x,y), linear fade (f*x, f*y)')
    z = np.sqrt(np.maximum(0.0, 1.0 - x * x - y * y)).astype(np.float32) if renorm else None
    for L in range(nb):
        if L > 0:
            # the mean of points of the unit disc stays in the disc: nothing to rescale
            x = _reduire(x); y = _reduire(y)
            if renorm:
                z = _reduire(z)
                n = np.sqrt(x * x + y * y + z * z)
                nul = n < 1e-8
                n = np.where(nul, 1.0, n).astype(np.float32)
                x = np.where(nul, 0.0, x / n).astype(np.float32)
                y = np.where(nul, 0.0, y / n).astype(np.float32)
                z = np.where(nul, 1.0, z / n).astype(np.float32)
        f = _fondu(R, L)
        if f == 1.0:
            xs, ys = x, y
        elif renorm:
            fx = f * x; fy = f * y
            nn = np.sqrt(fx * fx + fy * fy + z * z)
            nn = np.where(nn < 1e-8, 1.0, nn)
            xs = fx / nn; ys = fy / nn
        else:
            xs = x * np.float32(f); ys = y * np.float32(f)
        out = np.zeros(x.shape + (4,), np.float32)
        out[..., 1] = (ys + 1) * np.float32(127.5)
        out[..., 3] = (xs + 1) * np.float32(127.5)
        yield out


def _u8(niveau):
    """A level as uint8 (rounded and clamped if it is floating point)."""
    if niveau.dtype == np.uint8:
        return niveau
    return np.clip(np.rint(niveau), 0, 255).astype(np.uint8)


# =====================================================================================
# Preparation of mip 0 (shared by write_tex and by the checks)
# =====================================================================================

# Small in-memory caches (2 entries each: the atlas AND the normal map of a same build). They
# help when the same image is written twice (sm3_convertir delivers the atlas under 0x8E661B33
# THEN under the _grey hash, after the normal map) and when a check asks again for the prepared
# mip 0. Byte budget: the most recent entry is always kept, older ones go beyond it (a prepared
# 8192 atlas alone weighs 335 MB; the .exe keeps the module loaded between two builds).
_CACHE = {'prep': [], 'chaine': []}
_CACHE_TAILLE = 2
_CACHE_BUDGET = {'prep': 320 << 20, 'chaine': 160 << 20}


def _octets(valeur):
    """Approximate memory size of a cached value (arrays and byte strings)."""
    return sum(getattr(v, 'nbytes', None) or (len(v) if isinstance(v, (bytes, bytearray)) else 0)
               for v in valeur)


def _cache_lire(nom, cle):
    for c, v in _CACHE[nom]:
        if c == cle:
            return v
    return None


def _cache_ecrire(nom, cle, valeur):
    liste = [e for e in _CACHE[nom] if e[0] != cle]
    liste.append((cle, valeur))
    liste = liste[-_CACHE_TAILLE:]
    while len(liste) > 1 and sum(_octets(v) for _, v in liste) > _CACHE_BUDGET[nom]:
        liste.pop(0)
    _CACHE[nom] = liste


def _cle_fichier(image_path):
    """Cache key of a file: absolute path, modification time, size."""
    st = os.stat(image_path)
    return (os.path.abspath(image_path), st.st_mtime_ns, st.st_size)


def _preparer(image_path, genre, fmt, size, R, info):
    """("prepare") Returns (base uint8 (h,w,4), fond (h,w) bool or None). DXT colour: smoothing
    applied."""
    lisse = (genre == 'couleur' and fmt in ('DXT1', 'DXT5') and R['lissage']['actif']
             and int(R['lissage']['rayon']) > 0)
    tissu = (genre == 'couleur' and R['lissage_tissu']['actif']
             and float(R['lissage_tissu']['sigma']) > 0)
    tmax = int(R.get('taille_max') or 0) if genre == 'couleur' else 0
    cle = (_cle_fichier(image_path), size, genre,
           json.dumps(R['lissage'], sort_keys=True) if lisse else None,
           json.dumps(R['lissage_tissu'], sort_keys=True) if tissu else None, tmax,
           json.dumps(R.get('normale_plaquer')) if genre == 'normale' else None)
    deja = _cache_lire('prep', cle)
    if deja is not None:
        info.update(deja[2])
        info['mip0'] = 'already prepared (cache)'
        return deja[0], deja[1]
    img = Image.open(image_path).convert('RGBA')
    if size and genre == 'normale':
        # WARNING: never resize an RGBA for a normal map: Pillow PREMULTIPLIES by the alpha, which
        # carries x -- y would be wrong. Each channel is reduced on its own, in floating point.
        canaux = [np.asarray(Image.fromarray(np.asarray(img)[..., c].astype(np.float32), 'F')
                             .resize((size, size), Image.LANCZOS)) for c in range(4)]
        base = np.clip(np.rint(np.stack(canaux, -1)), 0, 255).astype(np.uint8)
        del canaux
    else:
        if size:
            img = img.resize((size, size), Image.LANCZOS)
        base = np.array(img, dtype=np.uint8)
    del img
    fond = None
    pinfo = {}
    if genre == 'couleur':
        fond = masque_fond(base)
        if tissu:
            # exact black is BACKGROUND only on an atlas with real gutters; on an already dilated
            # atlas those are black dots of the fabric, which the smoothing must precisely fill
            reel = 100.0 * float(fond.mean()) >= float(R['dilatation']['fond_min_pct'])
            base[..., :3] = lisser_tissu(base, fond if reel else None, R['lissage_tissu'], pinfo)
            fond = masque_fond(base)
        if tmax and max(base.shape[:2]) > tmax:
            # 2x2 sRGB reduction (like the mips) down to taille_max: mip 0 becomes EXACTLY level
            # 1 (2, ...) of the full-size chain
            h0, w0 = base.shape[:2]
            while max(base.shape[:2]) > tmax:
                base = _u8(_reduire_u8(base, False))
            fond = masque_fond(base)
            pinfo['taille'] = '%dx%d -> %dx%d (taille_max %d)' % (w0, h0, base.shape[1],
                                                                   base.shape[0], tmax)
        pinfo['fond_pct'] = round(100.0 * float(fond.mean()), 3)
        if lisse:
            t = time.time()
            L = R['lissage']
            garde = L.get('garde_noir')
            base[..., :3] = lisser_bilateral(base, ~fond, L['rayon'], L['sigma_spatial'],
                                             L['sigma_couleur'], garde_noir=garde)
            pinfo['lissage'] = 'bilateral r%d ss%g sr%g, black guard %s (%.1f s)' % (
                L['rayon'], L['sigma_spatial'], L['sigma_couleur'],
                'L* %g..%g' % tuple(garde) if garde and float(garde[1]) > 0 else 'off',
                time.time() - t)
        else:
            # kept in French: dxtenc_selftest.py looks for 'lissage non' in write_tex's report
            pinfo['lissage'] = 'non'
    base.setflags(write=False)
    _cache_ecrire('prep', cle, (base, fond, pinfo))
    info.update(pinfo)
    return base, fond


def preparer_image(image_path, genre=None, fmt='DXT5', size=None, reglages=None, hash_=None):
    """The EXACT pixels of the mip 0 that write_tex encodes for this image (uint8 (h, w, 4)).

    DXT colour: the smoothed image (if smoothing is on FOR THIS HASH). ARGB8: the image as it
    is. Normal map: A = x, G = y (faded if normale_fondu[0] != 1), R = B = 0.
    This is the reference to give to the tolerance checks (blacksuit_package.controle_texture).
    WARNING: pass the SAME hash_ as write_tex: par_texture may change a slot's settings (the
    black atlas 0x0133FD92 is not smoothed) -- without a hash, the global settings apply."""
    R = reglages_texture(reglages, hash_)
    g = genre_texture(image_path, None, hash_, genre)
    fmt = format_effectif(fmt, g, R)
    info = {}
    base, _ = _preparer(image_path, g, fmt, size, R, info)
    if g == 'normale':
        return _u8(next(_niveaux_normale(base, 1, R, info)))
    return np.array(base)


def format_effectif(fmt, genre, R):
    """The format really written: format_force from the settings (colour atlas only), otherwise
    the one requested. A normal map always stays DXT5 (X is in the alpha)."""
    force = str(R.get('format_force') or '').upper()
    if genre == 'couleur' and force in ('ARGB8', 'DXT5', 'DXT1'):
        return force
    return fmt


def _nombre_niveaux(w, h, mips, fmt):
    """Number of mip levels: 'full' = down to 1x1, otherwise min(N, full)."""
    plein = max(w, h).bit_length()
    if mips == 'full':
        return plein
    n = int(mips)
    if n < 1:
        if fmt == 'ARGB8':
            raise ValueError('At least one mipmap level is required')
        n = 1
    return min(n, plein)


def _chaine(image_path, genre, fmt, mips, size, R, info):
    """Builds (w, h, levels, iterator over the levels)."""
    base, fond = _preparer(image_path, genre, fmt, size, R, info)
    h, w = base.shape[:2]
    assert w & (w - 1) == 0 and h & (h - 1) == 0, "power-of-two dimensions are required"
    nb = _nombre_niveaux(w, h, mips, fmt)
    if genre == 'normale':
        info['fondu'] = [round(_fondu(R, L), 3) for L in range(nb)]
        return w, h, nb, _niveaux_normale(base, nb, R, info)
    D = R['dilatation']
    pct = 100.0 * float(fond.mean()) if fond is not None else 0.0
    if not (D['actif'] and int(D['anneaux']) > 0):
        info['dilatation'] = 'disabled'
        fond = None
    elif pct == 0.0:
        # kept in French (as the next one): dxtenc_selftest.py looks for 'sautee' ("skipped")
        info['dilatation'] = 'sautee : aucun fond'
        fond = None
    elif pct < float(D['fond_min_pct']):
        # a few exactly black texels do not make a gutter: on an already dilated atlas (JFA,
        # dilater_atlas rings, bake margin), they are LEGITIMATE blacks of the body -- measured:
        # 0.66 % of the red atlas, 1.47 % of the black one, two thirds of them INSIDE the islands
        info['dilatation'] = 'sautee : fond %.2f %% < %.1f %% (atlas deja dilate)' % (
            pct, float(D['fond_min_pct']))
        fond = None
    else:
        info['dilatation'] = '%d rings per level on the background (%.2f %%)' % (int(D['anneaux']), pct)
    info['mips'] = R['mips_couleur']
    return w, h, nb, _niveaux_couleur(base, fond, nb, R, info)


def mip_chain(img, fmt, mips, dilater=2):
    """Compatibility: whole chain in memory -> (bytes, levels), new method (floating-point mips,
    background by mask, encoder chosen in texture_qualite.json), without smoothing."""
    R = charger_reglages()
    R['dilatation']['anneaux'] = int(dilater or 0)
    base = np.array(img.convert('RGBA'), dtype=np.uint8)
    h, w = base.shape[:2]
    nb = _nombre_niveaux(w, h, mips, fmt)
    fond = masque_fond(base)
    if not (dilater and fond.any() and 100.0 * fond.mean() >= R['dilatation']['fond_min_pct']):
        fond = None
    out = bytearray()
    for niveau in _niveaux_couleur(base, fond, nb, R, {}):
        hh, ww = niveau.shape[:2]
        if fmt == 'ARGB8':
            out += _u8(niveau)[:, :, [2, 1, 0, 3]].tobytes()
        elif fmt in ('DXT1', 'DXT5'):
            enc = ENCODEURS[R['encodeur']][fmt]
            out += enc(_u8(niveau) if R['encodeur'] == 'rapide' else niveau, ww, hh)
        else:
            raise ValueError('Unknown TEX format: ' + fmt)
    return bytes(out), nb


# =====================================================================================
# Writing the .tex
# =====================================================================================

def _supprimer(chemin):
    """Delete a file, ignoring errors ("supprimer" = delete)."""
    try:
        os.remove(chemin)
    except OSError:
        pass


def write_tex(image_path, out_path, hash_, like=None, fmt='DXT1', mips='full', size=None,
              genre=None, reglages=None):
    """Write the .tex. Original signature kept; `genre` ('couleur' | 'normale', otherwise
    deduced) and `reglages` (dict, or path of a texture_qualite.json) are optional.
    Returns a text summary (logged by sm3_convertir; see the module docstring about its French
    fragments). The file is written to <out>.ecriture first, then renamed: a locked target never
    leaves a half-written .tex."""
    t0 = time.time()
    if fmt not in ('DXT1', 'DXT5', 'ARGB8'):
        raise ValueError('Unknown TEX format: ' + fmt)
    R, cle_texture = _reglages_effectifs(reglages, hash_)
    g = genre_texture(image_path, out_path, hash_, genre)
    force = format_effectif(fmt, g, R)
    if force != fmt:
        _log('format %s imposed by the settings (instead of %s)' % (force, fmt))
        fmt = force
    if g == 'normale' and fmt == 'DXT1':
        # X is in the ALPHA: in DXT1 alpha is 255, nx = +1, the normal becomes the tangent
        _log('normal map requested in DXT1: impossible (X is in the alpha), written in DXT5')
        fmt = 'DXT5'
    info = {'genre': g}
    if cle_texture:
        info['reglages'] = 'par_texture %s' % cle_texture
    if fmt != 'ARGB8':
        info['encodeur'] = R['encodeur']
    cle = None
    if fmt != 'ARGB8':
        cle = (_cle_fichier(image_path), g, fmt, str(mips), size,
               json.dumps(R, sort_keys=True))
    hdr = bytearray(68)
    if like:
        with open(like, 'rb') as f:
            hdr[:24] = f.read(24).ljust(24, b'\0')
    struct.pack_into('<I', hdr, 12, hash_ & 0xFFFFFFFF)
    format_code = 21 if fmt == 'ARGB8' else struct.unpack('<I', fmt.encode())[0]
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = out_path + '.ecriture'
    deja = _cache_lire('chaine', cle) if cle is not None else None
    if deja is not None:
        # same image, same settings (e.g. the atlas also delivered under the _grey hash): the
        # already encoded chain is reused as it is, only the header changes
        w, h, nb, corps, info_c = deja
        info.update((k, v) for k, v in info_c.items() if k != 'reglages')
        # kept in French: dxtenc_selftest.py looks for 'chaine reprise' ("chain reused")
        info['cache'] = 'chaine reprise'
        struct.pack_into('<IIIII', hdr, 24, w, h, 1, nb, format_code)
        try:
            with open(tmp, 'wb') as stream:
                stream.write(hdr); stream.write(corps)
        except BaseException:
            _supprimer(tmp)
            raise
    else:
        w, h, nb, niveaux = _chaine(image_path, g, fmt, mips, size, R, info)
        struct.pack_into('<IIIII', hdr, 24, w, h, 1, nb, format_code)
        hdr[44:68] = b'\0' * 24
        corps = [] if cle is not None else None
        enc = None if fmt == 'ARGB8' else ENCODEURS[R['encodeur']][fmt]
        t1 = time.time()
        try:
            with open(tmp, 'wb') as stream:
                stream.write(hdr)
                for niveau in niveaux:
                    hh, ww = niveau.shape[:2]
                    if fmt == 'ARGB8':
                        # levels written as they come: no 358 MB chain in memory at 8K
                        stream.write(_u8(niveau)[:, :, [2, 1, 0, 3]].tobytes())
                    else:
                        octets = enc(_u8(niveau) if R['encodeur'] == 'rapide' else niveau, ww, hh)
                        stream.write(octets)
                        corps.append(octets)
        except BaseException:
            _supprimer(tmp)
            raise
        info['encodage_s'] = round(time.time() - t1, 1)
        if cle is not None:
            _cache_ecrire('chaine', cle, (w, h, nb, b''.join(corps), dict(info)))
    try:
        os.replace(tmp, out_path)
    except BaseException:
        _supprimer(tmp)          # locked target (game open...): no orphan .ecriture file
        raise
    taille = os.path.getsize(out_path)
    details = ', '.join('%s %s' % (k, v) for k, v in info.items())
    print(f"wrote {out_path}: {w}x{h} {fmt} {nb} mips, {taille} bytes ({details}, {time.time() - t0:.1f} s)",
          flush=True)
    return '%dx%d %s %d mips, %s' % (w, h, fmt, nb, details)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('image'); ap.add_argument('out'); ap.add_argument('--hash', required=True)
    ap.add_argument('--like'); ap.add_argument('--dxt5', action='store_true'); ap.add_argument('--format', choices=['DXT1','DXT5','ARGB8']); ap.add_argument('--mips', default='full'); ap.add_argument('--size', type=int)
    ap.add_argument('--genre', choices=['couleur', 'normale']); ap.add_argument('--reglages')
    a = ap.parse_args()
    write_tex(a.image, a.out, int(a.hash, 0), a.like, a.format or ('DXT5' if a.dxt5 else 'DXT1'), a.mips, a.size,
              genre=a.genre, reglages=a.reglages)
