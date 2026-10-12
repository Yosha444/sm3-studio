# SPDX-License-Identifier: GPL-3.0-or-later
"""dxtenc.py -- vectorised DXT1/DXT5 (BC1/BC3) encoders (numpy only, neither scipy nor numba).

Where it sits: tools/png2tex.py encodes every .tex texture of a mod with it (the suit atlas, the
normal map, the Black Suit and Venom textures); tools/blacksuit_package.py also imports it. The
texture_qualite.json setting "encodeur" ("encoder": "hq" or "rapide" = fast) picks the family
through the ENCODEURS table at the end of this file. Self-test: dxtenc_selftest.py.

Two families, same signatures `(rgba, w, h) -> bytes`, same block order (row-major blocks):

* `dxt1_encode` / `dxt5_encode`: HIGH QUALITY encoder (the default since 2026-10-06).
  For each 4x4 block several endpoint pairs are tried, and the one whose DECODED block (integer
  rounding of texfind / D3D: (2a+b+1)//3, (k*a0+(7-k)*a1+3)//7) has the smallest squared error
  is kept:
    1. main axis (PCA by power iteration), endpoints at the min/max projections;
    2. the same, pulled in by 1/16 of the extent on each side;
    3. corners of the bounding box, oriented by the sign of the axis;
    4. the EXACT choice of the old encoder (min/max luminance texels, TRUNCATED 565): the new
       encoder can therefore never do worse than the old one, block by block;
    5. optimal single colour (stb_dxt-style tables) for the block mean: the dark flat areas of
       the black suit no longer turn green through the 5/6/5-bit rounding.
  Candidates 1 to 4 are refined three times by least squares on the indices found, with 565
  quantisation ROUNDED to nearest (the old encoder truncated: -4 levels on average on red and
  blue, hence dark, desaturated blocks along the web lines).
  DXT5 alpha: 8-value mode guaranteed (a0 > a1), local search +-1 around min/max, then two
  least-squares refinements; a constant block is restored exactly.
  Measured on 2026-10-06 (texfind decoder): red 4096 atlas +4.0 dB at mip 0 and +4.2 to +4.8 dB
  at mips 1-6; web-line crop at mip 2: 26.1 -> 31.6 dB; flat areas: max error 7 -> 1. Complete
  4096 DXT5 chain (13 levels): ~10 s, against ~60 s for dxtbetter.py (an earlier encoder, not
  distributed).

* `dxt1_encode_rapide` / `dxt5_encode_rapide`: the old encoder, unchanged (min/max luminance,
  truncated 565, partial blocks padded with BLACK). Kept for comparison and for the setting
  `"encodeur": "rapide"` of texture_qualite.json.

Input: array (h, w, 3 or 4), uint8 OR float 0..255 (float mip chains thus avoid an 8-bit round
trip). Any size: 1x1, 2x2, and dimensions that are not multiples of 4 (padding by REPEATING THE
EDGE, never with black, which would pull the endpoints).
Blocks are processed in batches (`bloc` blocks at a time): memory stays bounded even for a 4096
level (1,048,576 blocks).

French names kept in the API: rapide = fast, ancien = old, bloc(s) = block(s), raffinages =
refinement passes, couleur = colour, ENCODEURS = encoders.
"""
import numpy as np


# =====================================================================================
# Old encoder ("rapide" = fast) -- kept exactly as it was
# =====================================================================================

def _rgb_to_565(rgb):
    """rgb float array (..., 3) 0..255 -> uint16 565."""
    r = (rgb[..., 0].astype(np.uint16) >> 3) & 0x1F
    g = (rgb[..., 1].astype(np.uint16) >> 2) & 0x3F
    b = (rgb[..., 2].astype(np.uint16) >> 3) & 0x1F
    return (r << 11) | (g << 5) | b


def _565_to_rgb(c):
    r = ((c >> 11) & 0x1F).astype(np.float32) * (255.0 / 31.0)
    g = ((c >> 5) & 0x3F).astype(np.float32) * (255.0 / 63.0)
    b = (c & 0x1F).astype(np.float32) * (255.0 / 31.0)
    return np.stack([r, g, b], axis=-1)


def dxt1_encode_rapide(rgba, w, h):
    """rgba uint8 (h, w, 4) -> DXT1 bytes (no alpha: opaque 4-colour mode). OLD encoder."""
    bw, bh = (w + 3) // 4, (h + 3) // 4
    # pad to multiple of 4
    pad = np.zeros((bh * 4, bw * 4, 4), dtype=np.uint8)
    pad[:h, :w] = rgba[:h, :w]
    px = pad.reshape(bh, 4, bw, 4, 4).transpose(0, 2, 1, 3, 4)  # (bh,bw,4,4,4)
    blocks = px.reshape(bh * bw, 16, 4)[:, :, :3].astype(np.float32)  # (N,16,3)

    # choose endpoints: min/max along luminance
    lum = blocks @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    lo_i = lum.argmin(axis=1)
    hi_i = lum.argmax(axis=1)
    n = np.arange(len(blocks))
    c_lo = blocks[n, lo_i]           # (N,3)
    c_hi = blocks[n, hi_i]

    e0 = _rgb_to_565(c_hi)           # colour0 (must be > colour1 for 4-colour mode)
    e1 = _rgb_to_565(c_lo)
    swap = e0 < e1
    e0s = np.where(swap, e1, e0)
    e1s = np.where(swap, e0, e1)
    eq = e0s == e1s

    # palette: c0, c1, (2c0+c1)/3, (c0+2c1)/3
    p0 = _565_to_rgb(e0s)
    p1 = _565_to_rgb(e1s)
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], axis=1)  # (N,4,3)

    dist = ((blocks[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)  # (N,16,4)
    idx = dist.argmin(-1).astype(np.uint32)                             # (N,16)
    idx[eq] = 0

    code = np.zeros(len(blocks), dtype=np.uint32)
    for k in range(16):
        code |= idx[:, k] << (2 * k)

    out = np.zeros((len(blocks), 8), dtype=np.uint8)
    out[:, 0] = e0s & 0xFF
    out[:, 1] = e0s >> 8
    out[:, 2] = e1s & 0xFF
    out[:, 3] = e1s >> 8
    out[:, 4] = code & 0xFF
    out[:, 5] = (code >> 8) & 0xFF
    out[:, 6] = (code >> 16) & 0xFF
    out[:, 7] = (code >> 24) & 0xFF
    return out.tobytes()


def dxt5_encode_rapide(rgba, w, h):
    """rgba uint8 (h, w, 4) -> DXT5 bytes. OLD encoder."""
    bw, bh = (w + 3) // 4, (h + 3) // 4
    pad = np.zeros((bh * 4, bw * 4, 4), dtype=np.uint8)
    pad[:h, :w] = rgba[:h, :w]
    px = pad.reshape(bh, 4, bw, 4, 4).transpose(0, 2, 1, 3, 4)
    blocks = px.reshape(bh * bw, 16, 4).astype(np.float32)
    N = len(blocks)

    # ---- alpha block (BC3 8-value interpolated mode)
    a = blocks[:, :, 3]
    a_hi = a.max(1)
    a_lo = a.min(1)
    same = a_hi == a_lo
    a_hi2 = np.where(same, np.minimum(a_hi + 1, 255), a_hi)
    apal = np.stack([a_hi2, a_lo] +
                    [((6 - k) * a_hi2 + (k + 1) * a_lo) / 7 for k in range(6)], axis=1)
    adist = np.abs(a[:, :, None] - apal[:, None, :])
    aidx = adist.argmin(-1).astype(np.uint64)
    acode = np.zeros(N, dtype=np.uint64)
    for k in range(16):
        acode |= aidx[:, k] << np.uint64(3 * k)

    # ---- colour block (same as DXT1 4-colour mode)
    rgb = blocks[:, :, :3]
    lum = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    n = np.arange(N)
    c_lo = rgb[n, lum.argmin(1)]
    c_hi = rgb[n, lum.argmax(1)]
    e0 = _rgb_to_565(c_hi); e1 = _rgb_to_565(c_lo)
    swap = e0 < e1
    e0s = np.where(swap, e1, e0); e1s = np.where(swap, e0, e1)
    eq = e0s == e1s
    p0 = _565_to_rgb(e0s); p1 = _565_to_rgb(e1s)
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], axis=1)
    dist = ((rgb[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)
    cidx = dist.argmin(-1).astype(np.uint32)
    cidx[eq] = 0
    ccode = np.zeros(N, dtype=np.uint32)
    for k in range(16):
        ccode |= cidx[:, k] << (2 * k)

    out = np.zeros((N, 16), dtype=np.uint8)
    out[:, 0] = a_hi2.astype(np.uint8)
    out[:, 1] = a_lo.astype(np.uint8)
    for b in range(6):
        out[:, 2 + b] = ((acode >> np.uint64(8 * b)) & np.uint64(0xFF)).astype(np.uint8)
    out[:, 8] = e0s & 0xFF; out[:, 9] = e0s >> 8
    out[:, 10] = e1s & 0xFF; out[:, 11] = e1s >> 8
    out[:, 12] = ccode & 0xFF; out[:, 13] = (ccode >> 8) & 0xFF
    out[:, 14] = (ccode >> 16) & 0xFF; out[:, 15] = (ccode >> 24) & 0xFF
    return out.tobytes()


# =====================================================================================
# High quality encoder
# =====================================================================================

# Internal layout: (channel, texel, block) = (3, 16, N). Per-block quantities are (N,) vectors
# broadcast along the CONTIGUOUS axis: 4 to 20 times faster in numpy than the (N, 16, 3) layout,
# where every operation loops over rows of 16 texels.

_LUM = np.array([0.299, 0.587, 0.114], np.float32)
# weight of endpoint 0 for palette indices 0..3 (c0, c1, 2/3 c0 + 1/3 c1, 1/3 c0 + 2/3 c1)
_W4 = np.array([1.0, 0.0, 2.0 / 3.0, 1.0 / 3.0], np.float32)
# 8-value alpha: weight of a0 for indices 0..7
_W8 = np.array([1.0, 0.0, 6 / 7, 5 / 7, 4 / 7, 3 / 7, 2 / 7, 1 / 7], np.float32)
_DEC5 = np.array([(v << 3) | (v >> 2) for v in range(32)], np.float32)
_DEC6 = np.array([(v << 2) | (v >> 4) for v in range(64)], np.float32)
_DECALAGES2 = (2 * np.arange(16)).astype(np.uint32)
_DECALAGES3 = (3 * np.arange(16)).astype(np.uint64)


def _table_couleur_unique(dec):
    """For each value 0..255: the pair (q0, q1) whose palette entry 2, (2*d0 + d1 + 1)//3, lands
    nearest; on a tie, the smallest d0-d1 gap (less sensitive to the rounding of graphics
    cards). Same idea as the OMatch tables of stb_dxt. `dec` = decoded values of the 5- or
    6-bit codes ("single colour table")."""
    n = len(dec)
    d0 = dec[:, None]; d1 = dec[None, :]
    p2 = np.floor((2 * d0 + d1 + 1) / 3)                      # (n, n)
    cible = np.arange(256, dtype=np.float32)[:, None, None]
    cout = np.abs(p2[None] - cible) * 1000.0 + np.abs(d0 - d1)[None]
    meilleur = cout.reshape(256, -1).argmin(1)
    return (meilleur // n).astype(np.int32), (meilleur % n).astype(np.int32)


_U5_0, _U5_1 = _table_couleur_unique(_DEC5)
_U6_0, _U6_1 = _table_couleur_unique(_DEC6)


def _q565(c):
    """float (3, N) 0..255 -> (r, g, b) integers ROUNDED to nearest."""
    r = np.clip(np.rint(c[0] * (31.0 / 255.0)), 0, 31).astype(np.int32)
    g = np.clip(np.rint(c[1] * (63.0 / 255.0)), 0, 63).astype(np.int32)
    b = np.clip(np.rint(c[2] * (31.0 / 255.0)), 0, 31).astype(np.int32)
    return r, g, b


def _q565_tronque(c):
    """Quantisation of the OLD encoder (truncation), for the 'ancien' (old) candidate."""
    r = np.clip(c[0], 0, 255).astype(np.int32) >> 3
    g = np.clip(c[1], 0, 255).astype(np.int32) >> 2
    b = np.clip(c[2], 0, 255).astype(np.int32) >> 3
    return r, g, b


def _code565(r, g, b):
    return (r << 11) | (g << 5) | b


def _evaluer(xc, moy, x2, q0, q1):
    """Error of the DECODED block for the quantised endpoints q0=(r,g,b), q1=(r,g,b) ("evaluate").

    Palette exactly as the decoder builds it (texfind / D3D): 565 expansion by bit replication,
    then (2a+b+1)//3 and (a+2b+1)//3. Distance through the expansion |x-p|^2 = |x|^2 - 2x.p
    + |p|^2 on texels CENTRED on the block mean (keeps float32 precision).
    xc (3,16,N), moy (mean, 3,N), x2 (N,). Returns (code0, code1, idx (16,N) uint8, sse (N,))."""
    d0 = np.stack([_DEC5[q0[0]], _DEC6[q0[1]], _DEC5[q0[2]]])          # (3, N)
    d1 = np.stack([_DEC5[q1[0]], _DEC6[q1[1]], _DEC5[q1[2]]])
    pal = (d0, d1, np.floor((2 * d0 + d1 + 1) * (1.0 / 3.0) + 1e-4),
           np.floor((d0 + 2 * d1 + 1) * (1.0 / 3.0) + 1e-4))
    sc = []
    for p in pal:
        pc = p - moy
        f = -2.0 * pc
        s = xc[0] * f[0]
        s += xc[1] * f[1]
        s += xc[2] * f[2]
        s += (pc * pc).sum(0)
        sc.append(s)
    m01 = sc[1] < sc[0]; b01 = np.minimum(sc[0], sc[1])
    m23 = sc[3] < sc[2]; b23 = np.minimum(sc[2], sc[3])
    m = b23 < b01
    meilleur = np.minimum(b01, b23, out=b01)
    i01 = m01.view(np.uint8)
    i23 = m23.view(np.uint8) + np.uint8(2)
    idx = i01 + m.view(np.uint8) * (i23 - i01)
    sse = np.maximum(meilleur.sum(0) + x2, 0.0)
    return _code565(*q0), _code565(*q1), idx, sse


def _moindres_carres(xc, moy, idx, e0, e1):
    """Endpoints (float, (3,N)) that minimise the error for the given indices ("least squares").

    Centred texels: the sum of x is 0, so sum(b*x) = -sum(a*x) and everything follows from
    sum(a), sum(a^2) and sum(a*x) per channel."""
    a = _W4[idx]                                                         # (16, N) weight of e0
    sa = a.sum(0); saa = (a * a).sum(0)
    aa = saa; bb = 16.0 - 2.0 * sa + saa; ab = sa - saa
    det = aa * bb - ab * ab
    ok = np.abs(det) > 1e-6
    inv = 1.0 / np.where(ok, det, 1.0)
    ax = (xc * a).sum(1)                                                 # (3, N)
    n0 = np.where(ok, moy + ax * ((bb + ab) * inv), e0)
    n1 = np.where(ok, moy - ax * ((aa + ab) * inv), e1)
    return np.clip(n0, 0, 255), np.clip(n1, 0, 255)


def _encoder_couleur(pc, raffinages=3):
    """pc (3, 16, N) float 0..255 -> (c0, c1, idx (16, N)) with c0 >= c1 (4-colour mode).

    c0 == c1 only for a block whose best palette is a single colour; its indices are then all 0
    (safe in DXT1, where c0 == c1 switches to the 3-colour mode). ("encode colour")"""
    pc = np.asarray(pc, np.float32)
    N = pc.shape[2]
    moy = pc.mean(1)                                                     # (3, N)
    xc = pc - moy[:, None, :]
    x2 = (xc * xc).sum((0, 1))
    # --- main axis: power iteration on the 3x3 covariance (6 terms)
    cxx = (xc[0] * xc[0]).sum(0); cyy = (xc[1] * xc[1]).sum(0); czz = (xc[2] * xc[2]).sum(0)
    cxy = (xc[0] * xc[1]).sum(0); cxz = (xc[0] * xc[2]).sum(0); cyz = (xc[1] * xc[2]).sum(0)
    lo = pc.min(1); hi = pc.max(1)                                       # (3, N)
    v = (hi - lo) + 1e-3
    for _ in range(8):
        v = np.stack([cxx * v[0] + cxy * v[1] + cxz * v[2],
                      cxy * v[0] + cyy * v[1] + cyz * v[2],
                      cxz * v[0] + cyz * v[1] + czz * v[2]])
        v /= np.maximum(np.sqrt((v * v).sum(0)), 1e-12)
    t = xc[0] * v[0] + xc[1] * v[1] + xc[2] * v[2]                       # (16, N)
    tmin = t.min(0); tmax = t.max(0)
    rentre = (tmax - tmin) / 16.0

    candidats = [
        (moy + tmax * v, moy + tmin * v, False),
        (moy + (tmax - rentre) * v, moy + (tmin + rentre) * v, False),
        (np.where(v >= 0, hi, lo), np.where(v >= 0, lo, hi), False),
    ]
    # the old encoder's choice, computed as it did (same product, same ties)
    lum = np.ascontiguousarray(pc.transpose(2, 1, 0)) @ _LUM              # (N, 16)
    n = np.arange(N)
    candidats.append((pc[:, lum.argmax(1), n], pc[:, lum.argmin(1), n], True))

    m_c0 = m_c1 = m_idx = m_sse = None
    for e0, e1, ancien in candidats:
        e0 = np.clip(e0, 0, 255).astype(np.float32); e1 = np.clip(e1, 0, 255).astype(np.float32)
        for it in range(raffinages + 1):
            if it == 0 and ancien:
                q0, q1 = _q565_tronque(e0), _q565_tronque(e1)
            else:
                q0, q1 = _q565(e0), _q565(e1)
            c0, c1, idx, sse = _evaluer(xc, moy, x2, q0, q1)
            if m_sse is None:
                m_c0, m_c1, m_idx, m_sse = c0, c1, idx, sse
            else:
                mieux = sse < m_sse
                m_c0 = np.where(mieux, c0, m_c0); m_c1 = np.where(mieux, c1, m_c1)
                m_idx = np.where(mieux, idx, m_idx); m_sse = np.minimum(sse, m_sse)
            if it < raffinages:
                e0, e1 = _moindres_carres(xc, moy, idx, e0, e1)

    # --- optimal single colour (flat areas, very soft gradients)
    mi = np.clip(np.rint(moy), 0, 255).astype(np.int32)
    q0 = (_U5_0[mi[0]], _U6_0[mi[1]], _U5_0[mi[2]])
    q1 = (_U5_1[mi[0]], _U6_1[mi[1]], _U5_1[mi[2]])
    c0, c1, idx, sse = _evaluer(xc, moy, x2, q0, q1)
    mieux = sse < m_sse
    m_c0 = np.where(mieux, c0, m_c0); m_c1 = np.where(mieux, c1, m_c1)
    m_idx = np.where(mieux, idx, m_idx)

    # --- 4-colour mode: c0 > c1; otherwise swap (indices 0<->1 and 2<->3: idx ^ 1)
    ech = m_c0 < m_c1
    c0 = np.where(ech, m_c1, m_c0); c1 = np.where(ech, m_c0, m_c1)
    idx = m_idx ^ ech.view(np.uint8)
    idx *= (c0 != c1).view(np.uint8)
    return c0.astype(np.uint32), c1.astype(np.uint32), idx


def encoder_couleur_blocs(px, raffinages=3):
    """px (N, 16, 3) float 0..255 -> (c0, c1, idx (N, 16)). Block-wise interface."""
    pc = np.ascontiguousarray(np.asarray(px, np.float32).transpose(2, 1, 0))
    c0, c1, idx = _encoder_couleur(pc, raffinages)
    return c0, c1, np.ascontiguousarray(idx.T)


def _palette_alpha(a0, a1):
    """a0 > a1 (8-value mode), integers -> (8, N) decoded values (texfind rounding)."""
    a0 = a0.astype(np.int32); a1 = a1.astype(np.int32)
    cols = [a0, a1] + [((8 - i) * a0 + (i - 1) * a1 + 3) // 7 for i in range(2, 8)]
    return np.stack(cols).astype(np.float32)


def _encoder_alpha(at):
    """at (16, N) float 0..255 -> (a0, a1, idx (16, N)) in 8-value mode (a0 > a1)."""
    at = np.asarray(at, np.float32)
    N = at.shape[1]
    a0 = np.empty(N, np.int32); a1 = np.empty(N, np.int32); idx = np.zeros((16, N), np.uint8)
    hi = np.rint(at.max(0)).astype(np.int32); lo = np.rint(at.min(0)).astype(np.int32)
    const = hi == lo
    if const.any():
        # constant block: a0 = exact value (index 0); for 0: a0 = 1, a1 = 0, index 1
        v = hi[const]
        a0[const] = np.maximum(v, 1); a1[const] = np.maximum(v - 1, 0)
        idx[:, const] = (v == 0).view(np.uint8)
    var = ~const
    if not var.any():
        return a0, a1, idx
    tout = bool(var.all())
    av = at if tout else at[:, var]
    hv = hi if tout else hi[var]
    lv = lo if tout else lo[var]
    m = {}

    def essai(h, l):
        h = np.clip(h, 1, 255); l = np.clip(l, 0, 254)
        h = np.maximum(h, l + 1)
        pal = _palette_alpha(h, l)
        meilleur = None; ix = None
        for k in range(8):
            e = av - pal[k]
            e *= e
            if meilleur is None:
                meilleur = e; ix = np.zeros(e.shape, np.uint8)
            else:
                mieux = e < meilleur
                ix += mieux.view(np.uint8) * (np.uint8(k) - ix)     # modulo-256 arithmetic
                np.minimum(meilleur, e, out=meilleur)
        sse = meilleur.sum(0)
        if not m:
            m.update(a0=h, a1=l, idx=ix, sse=sse)
        else:
            b = sse < m['sse']
            m['a0'] = np.where(b, h, m['a0']); m['a1'] = np.where(b, l, m['a1'])
            m['idx'] = np.where(b, ix, m['idx']); m['sse'] = np.minimum(sse, m['sse'])

    for dh in (0, -1, 1):
        for dl in (0, -1, 1):
            essai(hv + dh, lv + dl)
    for _ in range(2):           # least squares on the kept indices
        w = _W8[m['idx']]; u = 1.0 - w
        ww = (w * w).sum(0); uu = (u * u).sum(0); wu = (w * u).sum(0)
        wx = (w * av).sum(0); ux = (u * av).sum(0)
        det = ww * uu - wu * wu
        ok = np.abs(det) > 1e-6; det = np.where(ok, det, 1.0)
        f0 = np.where(ok, (uu * wx - wu * ux) / det, hv)
        f1 = np.where(ok, (ww * ux - wu * wx) / det, lv)
        b0 = np.floor(f0).astype(np.int32); b1 = np.floor(f1).astype(np.int32)
        for d0 in (0, 1):
            for d1 in (0, 1):
                essai(b0 + d0, b1 + d1)
    if tout:
        return m['a0'].astype(np.int32), m['a1'].astype(np.int32), m['idx']
    a0[var] = m['a0']; a1[var] = m['a1']; idx[:, var] = m['idx']
    return a0, a1, idx


def encoder_alpha_blocs(a):
    """a (N, 16) float 0..255 -> (a0, a1, idx (N, 16)). Block-wise interface."""
    a0, a1, idx = _encoder_alpha(np.ascontiguousarray(np.asarray(a, np.float32).T))
    return a0, a1, np.ascontiguousarray(idx.T)


def _image_blocs(rgba, w, h):
    """Image (h, w, C) -> (working array (bh*4, bw*4, 4), bw, bh), edge repeated if needed."""
    img = np.asarray(rgba)
    if img.ndim != 3:
        raise ValueError('expected an image (h, w, channels)')
    img = img[:h, :w]
    if img.shape[2] == 3:
        alpha = np.full(img.shape[:2] + (1,), 255, img.dtype)
        img = np.concatenate([img, alpha], 2)
    elif img.shape[2] > 4:
        img = img[:, :, :4]
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    if (bh * 4, bw * 4) != img.shape[:2]:
        img = np.pad(img, ((0, bh * 4 - img.shape[0]), (0, bw * 4 - img.shape[1]), (0, 0)),
                     mode='edge')
    return img, bw, bh


def _iter_paquets(img, bw, bh, bloc):
    """Yield (start, blocks (4, 16, n) float32) by batches of block rows."""
    rangs = max(1, bloc // bw)
    debut = 0
    for by in range(0, bh, rangs):
        by1 = min(bh, by + rangs)
        tranche = np.ascontiguousarray(img[by * 4:by1 * 4])
        blocs = tranche.reshape(by1 - by, 4, bw, 4, 4).transpose(4, 1, 3, 0, 2)
        blocs = blocs.reshape(4, 16, -1).astype(np.float32)
        yield debut, blocs
        debut += blocs.shape[2]


def _ecrire_couleur(sortie, c0, c1, idx):
    """8-byte colour block: c0, c1 (u16 LE), 32 bits of indices (texel k at bits 2k)."""
    code = (idx.astype(np.uint32) << _DECALAGES2[:, None]).sum(0, dtype=np.uint32)
    mots = np.empty((len(c0), 4), '<u2')
    mots[:, 0] = c0; mots[:, 1] = c1
    mots[:, 2] = code & 0xFFFF; mots[:, 3] = code >> 16
    sortie[:] = mots.view(np.uint8)


def _ecrire_alpha(sortie, a0, a1, idx):
    """8-byte alpha block: a0, a1, then 48 bits of indices (texel k at bits 3k)."""
    code = (idx.astype(np.uint64) << _DECALAGES3[:, None]).sum(0, dtype=np.uint64)
    mot = (a0.astype(np.uint64) | (a1.astype(np.uint64) << np.uint64(8))
           | (code << np.uint64(16)))
    sortie[:] = mot.astype('<u8').view(np.uint8).reshape(-1, 8)


def dxt1_encode(rgba, w, h, bloc=4096):
    """rgba (h, w, 3|4) uint8 or float -> opaque DXT1 bytes (4-colour mode). HQ."""
    img, bw, bh = _image_blocs(rgba, w, h)
    out = np.empty((bw * bh, 8), np.uint8)
    for s, b in _iter_paquets(img, bw, bh, bloc):
        n = b.shape[2]
        c0, c1, idx = _encoder_couleur(b[:3])
        _ecrire_couleur(out[s:s + n], c0, c1, idx)
    return out.tobytes()


def dxt5_encode(rgba, w, h, bloc=4096):
    """rgba (h, w, 4) uint8 or float -> DXT5 bytes (interpolated alpha + colour). HQ."""
    img, bw, bh = _image_blocs(rgba, w, h)
    out = np.empty((bw * bh, 16), np.uint8)
    for s, b in _iter_paquets(img, bw, bh, bloc):
        n = b.shape[2]
        a0, a1, aidx = _encoder_alpha(b[3])
        _ecrire_alpha(out[s:s + n, 0:8], a0, a1, aidx)
        c0, c1, idx = _encoder_couleur(b[:3])
        _ecrire_couleur(out[s:s + n, 8:16], c0, c1, idx)
    return out.tobytes()


# Encoder selection by setting name (texture_qualite.json: "encodeur": "hq" | "rapide").
# The keys are setting values read by tools/png2tex.py: never translate them.
ENCODEURS = {
    'hq': {'DXT1': dxt1_encode, 'DXT5': dxt5_encode},
    'rapide': {'DXT1': dxt1_encode_rapide, 'DXT5': dxt5_encode_rapide},
}
