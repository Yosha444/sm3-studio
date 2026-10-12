# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""mains_poings.py - FISTS that clench: the 30 finger bones, phalanx by phalanx.

("mains, poings" = "hands, fists".) Called by winding_fix.py on every delivered player mesh
(red and black suits, 000 and 001), after the face-orientation check; usable by hand too.
Its reader/rewriter functions are also used by decoupe_sections.py, conformer_sans_rig.py and
doigts_sans_rig.py.

THE DEFECT, MEASURED (2026-10-06)
---------------------------------
At rest, Spider-Man clenches his fists. The converted suits (red AND black) kept their hands
OPEN. Neither the painting nor the animation: the fingers no longer had phalanges.

    installed mods        10 finger bones out of 30: finger0..4 of each hand (the BASES). All
                          the `finger<D>1` / `finger<D>2` phalanges were gone -> stiff fingers,
                          bending only at the knuckle, no fist possible.
    current chain, 48     17 out of 30. ONE section cannot hold a body + 30 fingers (~52 to 66
                          bones): a section's palette is capped at 48 (12 skinned vertex shaders,
                          `world` on c0..c191).
    nearest-neighbour     29 to 38 % of a finger's vertices pulled by the NEIGHBOURING finger:
    transfer              the model's fingers are offset 7 to 14 mm towards the little finger,
                          and thinner.
    vanilla               30 / 30, spread over 8 to 10 sections.

THE FIX
-------
1. FINGER BY FINGER, THROUGH THE TOPOLOGY. Beyond the 1st phalanx, each finger of the model is
   a SEPARATE piece of surface. We recognise the five pieces of each hand, project their vertices
   onto the vanilla bone chain of THAT finger (hand -> base -> middle -> tip), and give them the
   weight profile the vanilla carries along the finger: rigid phalanges, a blending ring at each
   joint. Continuous blend towards the existing weights in the palm.
   WARNING: every vertex outside the fingers keeps ITS weight BYTES: the body does not move by
   a single bit.
   Offline fist test (15 joints bent): distance to rigid phalanx tracking 38.7 mm (installed)
   -> 3.4 mm; no vertex pulled by two fingers (kNN: 29 to 38 %).

2. SEVERAL SECTIONS when the palette overflows. How xeSM3.dll (function 0x10011650) picks the
   material of a loose section decides everything:
   - ch_spiderman000/001 (0xAC92103D/E): by material REFERENCE, hard-coded table. Several
     sections with the same reference get the same material; the vanilla does it itself
     (sections 7 and 8 of the 000, both 0x640). So we detach one hand (then the other if needed)
     into its own section, SAME reference as the body. Seam vertices duplicated identically:
     same bytes, same bones, same weights -> no crack possible.
   - any other mesh, including ch_blacksuit (0xABE79B1C/D): by section INDEX. Only section 3
     carries the fabric (hence the three one-vertex ghost sections before it). Only one real
     section, so 48 bones at most: we fold the bones least visible in a closed fist, in this
     order: toes, ring and little fingertips, index and middle fingertips, upper-arm twist
     helpers, thumb tip (see REPLIS). Installed black suit: 22 body bones + 26 finger bones = 48
     (the ring and little fingertips follow their middle phalanx). A folded bone is never
     re-posed (rest shape kept).

3. RE-POSING THE BLACK SUIT. Its skeleton does not have the red suit's thumb (finger01 +15 deg,
   finger02 +44 deg relative to the hand), and its vertices were POSED with the old weights
   (blacksuit_build: p_black = sum w_b . bind_black(b) . bind_red(b)^-1 . p_red). Changing the
   weights without re-posing would leave the thumb tip 3 cm from its bone. For the vertices whose
   FINGER weights change, and only those: p' = A_new . A_old^-1 . p (normal, tangent, binormal:
   the 3x3 part, renormalised). The red 000 (source skeleton) and the red 001 (001 frame =
   translation + rigid rotation, differences < 0.1 deg) are never re-posed: their bytes 0..39
   stay as they are.

WHERE THE FINGERS COME FROM (2026-10-07: "some models still have broken fingers")
  1. `doigts_modele.npz` ("model fingers") next to the .mesh, if present: the finger of each
     vertex, written
     - by the chain when the model has a RIG (tools/conformer_squelette.py: its phalanges were
       put on the game's, and its own weights say which vertex belongs to which finger);
     - by tools/doigts_sans_rig.py for a model WITHOUT a rig (fingers found as branches of the
       hand, then POSED on the game's phalanges; a finger already folded = label -2, attached to
       the hand). Vertices are matched by their quantised position (1/512).
  2. otherwise the TOPOLOGY (the original method): five separate finger pieces, posed like the
     vanilla. photoreal: yes; most downloaded models: no -> hand left as it is.
  WARNING: never labels "by branches" WITHOUT posing: fingers that do not go through the game's
  joints pivot off target and stretch into bars in a fist (seen on Brand and Miles).

WHAT IS NEVER TOUCHED: positions, normals, UVs, colours of the existing vertices (except the
black re-pose above), the file header, the ghost sections, the material references. The file is
rewritten in the same layout as the toolkit's writer; before any work, the tool checks that it
can REWRITE the input byte for byte, otherwise it refuses.

USAGE
    python tools/mains_poings.py <input.mesh> <output.mesh>
            [--vanilla-mesh <vanilla ch_spiderman000.mesh>] [--skel <ch_spiderman000.skel>]
            [--skel-cible <skeleton of the mesh>] [--poids-de <.npz trace of the 000>]
            [--trace <output .npz>] [--max-os 48] [--forcer]
    The vanilla paths and the target skeleton are deduced from the mesh's hash when SM3 Studio's
    `vanilla/` folder is there. For a 001 (red or black), pass the 000's trace with
    `--poids-de` ("weights from"): the LOD gets exactly the same weights and split as the 000.
    (skel-cible = target skeleton, max-os = max bones, forcer = force.)

AUTOMATIC CALL: `winding_fix.py` (end of the red AND black chains) calls `apres_winding()` on
every delivered mesh. Can be disabled: `winding_fix.py --sans-mains` or SM3_MAINS_POINGS=0.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import struct
import sys
from collections import Counter, deque

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
# TSGAMING264's SM3 Blender Toolkit, where Blender 5.2 installs extensions for the current user.
EXT = os.path.join(os.environ.get('APPDATA', ''), 'Blender Foundation', 'Blender', '5.2',
                   'extensions', 'user_default', 'sm3_blender_toolkit')


def _charger_fmt():
    """The toolkit's reader (sm3_format.py), without Blender. Reuses one already loaded."""
    for nom in ('sm3_format', 'sm3_blender_toolkit.sm3_format'):
        m = sys.modules.get(nom)
        if m is not None and hasattr(m, 'parse_mesh') and hasattr(m, 'parse_skeleton'):
            return m
    s = importlib.util.spec_from_file_location('sm3_format', os.path.join(EXT, 'sm3_format.py'))
    m = importlib.util.module_from_spec(s)
    sys.modules['sm3_format'] = m
    s.loader.exec_module(m)
    return m


fmt = _charger_fmt()

# ------------------------------------------------------------------------------- constants
HASH_ROUGE_000, HASH_ROUGE_001 = 0xAC92103D, 0xAC92103E      # red suit ("rouge")
HASH_NOIR_000, HASH_NOIR_001 = 0xABE79B1C, 0xABE79B1D        # black suit ("noir")
# xeSM3.dll 0x10011650: these two hashes go through the "LEGACY-MAP" table (material chosen by
# REFERENCE); all the others by section INDEX (0x100117FB: mov edx,[ebp+0xC]).
PAR_REFERENCE = (HASH_ROUGE_000, HASH_ROUGE_001)
DOSSIER_ROUGE = os.path.join('vanilla', 'CH_SPIDERMAN', '_O0069.0xCFB154CD.T36.apkf')
DOSSIER_NOIR = os.path.join('vanilla', 'CH_BLACKSUIT', '_O0108.0xF8ACB40C.T36.apkf')
MESH_VANILLA = '0xAC92103D.ch_spiderman000.mesh'
SKEL_SOURCE = '0x461356AE.ch_spidermanskeleton_ch_spiderman000.skel'
SQUELETTE_CIBLE = {          # target skeleton of each mesh hash
    HASH_ROUGE_000: (DOSSIER_ROUGE, '0x461356AE.ch_spidermanskeleton_ch_spiderman000.skel'),
    HASH_ROUGE_001: (DOSSIER_ROUGE, '0x461356AF.ch_spidermanskeleton_ch_spiderman001.skel'),
    HASH_NOIR_000: (DOSSIER_NOIR, '0x302DADCC.ch_blacksuitskeleton_ch_blacksuit000.skel'),
    HASH_NOIR_001: (DOSSIER_NOIR, '0x302DADCD.ch_blacksuitskeleton_ch_blacksuit001.skel'),
}
# the 000 whose weights a 001 takes over (trace written next to the 000)
FRERE_000 = {HASH_ROUGE_001: '0xAC92103D.ch_spiderman000.mesh',
             HASH_NOIR_001: '0xABE79B1C.ch_blacksuit000.mesh'}

MAX_OS = 48                 # 12 skinned vertex shaders: `world` on c0..c191 = 48 matrices
SENTINELLE = b'\xFF\x00\x00\x00\x11\x00\x00\x00'      # end marker of a vertex declaration

# Profile parameters, tuned on photoreal and validated by the offline fist test.
# u: -1 wrist, 0 knuckle (MCP), 1 and 2 joints (PIP, DIP), 3 fingertip. Key = finger (0 = thumb).
U_MIN = {0: 0.6, 1: -0.2, 2: -0.2, 3: -0.2, 4: -0.2}     # below: existing weights untouched
U_PLEIN = {0: 1.25, 1: 0.3, 2: 0.3, 3: 0.3, 4: 0.3}    # beyond: 100 % finger profile
R_MAX = 0.035               # maximum radius around the chain to propagate a finger
U_GRAINE, D_GRAINE = 0.6, 0.04      # seeds: past u 0.6 and within 0.04 of a chain

# What is folded when ONE section has to hold everything (black suit), in this order. Each step
# folds its bones (both sides at once) onto their parent, then we count again.
# WARNING: a folded bone is NEVER re-posed: its vertex keeps its rest shape and follows the parent.
# Measured on a 48-bone black chain: re-posing the folded `split` bones moved the upper arm by
# 15.7 mm at rest. The thumb comes AFTER the twist helpers: its IP shows in a closed fist, a twist
# helper (split2/3; split1 stays) much less.
REPLIS = (
    ('toes (they fall back on the foot, their parent)', r'toe\d'),
    ('ring and little fingertips (DIP hidden in the fist)', r'finger[34]2$'),
    ('index and middle fingertips', r'finger[12]2$'),
    ('upper-arm twist helpers (split2/3)', r'upperarm split[23]$'),
    ('thumb tip', r'finger02$'),
    ('neck', r'bip01 neck$'),
    ('ring and little middle phalanges', r'finger[34]1$'),
)


def log_defaut(*x):
    print('[mains]', *x, flush=True)


def align(v, a):
    return (v + a - 1) & ~(a - 1)


# ------------------------------------------------------------------------------- skeleton
def _bind(b):
    """Rest matrix (columns, translation in the last column) - same convention as
    blacksuit_build.bind."""
    m = np.array(b.inverse_values, np.float64).reshape(4, 4).copy()
    m[:3, 3] = 0.0
    m[3, 3] = 1.0
    return np.linalg.inv(m).T


class Squelette:
    """A skeleton: names, parents, name hashes and rest matrices by bone index."""

    def __init__(self, chemin):
        sk = fmt.parse_skeleton(chemin)
        self.chemin = chemin
        self.n = sk.bone_count
        self.noms = {b.index: b.name for b in sk.bones}
        self.parents = {b.index: b.parent_index for b in sk.bones}
        self.hashes = [b.name_hash for b in sk.bones]
        self.bind = np.array([_bind(b) for b in sk.bones])
        self.idx = {v: k for k, v in self.noms.items()}

    def joint(self, b):
        return self.bind[b][:3, 3]

    def chaine(self, c, D):
        """(hand, base, middle, tip) of finger D, side 'l' or 'r'."""
        return (self.idx['bip01 %s hand' % c], self.idx['bip01 %s finger%d' % (c, D)],
                self.idx['bip01 %s finger%d1' % (c, D)], self.idx['bip01 %s finger%d2' % (c, D)])


def cote(nom):
    """Side of a bone from its name: 'l', 'r' or ''."""
    n = ' %s ' % nom
    return 'l' if ' l ' in n else ('r' if ' r ' in n else '')


def sauts(parents, a, b):
    """Number of edges between two bones in the hierarchy (like poids_par_segments._sauts)."""
    if a == b:
        return 0

    def ch(x):
        c = []
        while x is not None and x >= 0 and x not in c:
            c.append(x)
            x = parents.get(x, -1)
        return c
    ca, cb = ch(a), ch(b)
    for i, x in enumerate(ca):
        if x in cb:
            return i + cb.index(x)
    return 99


def os_doigts(sq):
    return [b for b in range(sq.n) if 'finger' in sq.noms[b]]


def phalanges_du_milieu(sq):
    return [sq.idx['bip01 %s finger%d1' % (c, D)] for c in 'lr' for D in range(5)]


# ------------------------------------------------------------------------------- reading
def _decl(s, usage):
    d = [x for x in s.decl if x.usage == usage and x.usage_index == 0]
    return d[0] if d else None


def lignes(m, s):
    """("rows") The raw vertex bytes of a section, one row per vertex."""
    return np.frombuffer(m.raw, np.uint8, s.vertex_count * s.vertex_stride,
                         s.vertex_buffer_offset).reshape(s.vertex_count, s.vertex_stride).copy()


def faces_section(m, s):
    if not s.index_count:
        return np.zeros((0, 3), np.int64)
    if s.primitive_type == 4 and s.index_count % 3 == 0:
        t = '<u2' if s.index_size == 2 else '<u4'
        return np.frombuffer(m.raw, t, s.index_count, s.index_buffer_offset).astype(np.int64).reshape(-1, 3)
    return np.array(fmt.indices_to_faces(fmt.read_indices(m, s), s.primitive_type,
                                         s.vertex_count), np.int64).reshape(-1, 3)


def est_fantome(m, s):
    """("is a ghost") Section of one vertex and degenerate triangles: an index placeholder
    (black suit)."""
    if s.vertex_count <= 2:
        return True
    f = faces_section(m, s)
    return len(f) == 0 or bool(np.all((f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2]) | (f[:, 0] == f[:, 2])))


def disposition_ok(s):
    """The 52-byte layout we know how to read AND rewrite without losing anything:
    usage -> D3DDECLTYPE (POSITION SHORT4, NORMAL/TANGENT/BINORMAL SHORT4N, BLENDINDICES UBYTE4,
    BLENDWEIGHT SHORT4N)."""
    attendu = {0: 7, 3: 10, 6: 10, 7: 10, 2: 5, 1: 10}
    for usage, dtype in attendu.items():
        d = _decl(s, usage)
        if d is None or d.dtype != dtype:
            return False
    return True


def influences(m, s, L):
    """(global bones n x 4, int16 weights n x 4) of a section, read from the bytes."""
    oi, ow = _decl(s, 2).offset, _decl(s, 1).offset
    loc = L[:, oi:oi + 4].astype(np.int64)
    q = L[:, ow:ow + 8].copy().view('<i2').astype(np.int64)
    pal = np.array(s.bone_palette or [0], np.int64)
    g = np.where(loc < len(pal), pal[np.minimum(loc, len(pal) - 1)], 0)
    g = np.where(q > 0, g, -1)          # empty slot: bone irrelevant
    return g, q


def positions(s, L):
    o = _decl(s, 0).offset
    return L[:, o:o + 8].copy().view('<i2')[:, :3].astype(np.float64) / 512.0


def vecteurs(s, L, usage):
    o = _decl(s, usage).offset
    return L[:, o:o + 8].copy().view('<i2')[:, :3].astype(np.float64) / 32767.0


def lire_vanilla(chemin, nb_os):
    """DENSE positions and weights (n x nb_os) of every section of the vanilla 000."""
    m = fmt.parse_mesh(chemin)
    P, W = [], []
    for s in m.sections:
        if not s.vertex_count:
            continue
        d = fmt.decode_section_vertices(m, s, uv_divisor=1000.0)
        pal = list(s.bone_palette or [0])
        j = np.array(d['blend_indices'], np.int64)
        g = np.array([[pal[k] if k < len(pal) else 0 for k in ligne] for ligne in j], np.int64)
        w = np.array(d['blend_weights'], np.float64)
        w = w / np.maximum(w.sum(1, keepdims=True), 1e-9)
        Wd = np.zeros((len(g), nb_os))
        for c in range(g.shape[1]):
            np.add.at(Wd, (np.arange(len(g)), g[:, c]), w[:, c])
        P.append(np.array(d['positions'], np.float64))
        W.append(Wd)
    return np.concatenate(P), np.concatenate(W)


# ------------------------------------------------------------------------------- geometry
def proj_polyligne(X, pts):
    """Projection of X (n,3) onto the polyline pts (k,3): (u, distance), u = segment + fraction."""
    best_d = np.full(len(X), np.inf)
    best_u = np.zeros(len(X))
    for i in range(len(pts) - 1):
        A, B = pts[i], pts[i + 1]
        AB = B - A
        L2 = max(float(AB @ AB), 1e-12)
        t = np.clip(((X - A) @ AB) / L2, 0.0, 1.0)
        d = np.linalg.norm(X - (A + t[:, None] * AB), axis=1)
        m = d < best_d
        best_d[m] = d[m]
        best_u[m] = i + t[m]
    return best_u, best_d


def graphe(P, faces):
    """Neighbourhood on the MESH, co-located vertices merged (same key as
    poids_depuis_vanilla._graphe). Returns (group of each vertex, CSR neighbours, start)."""
    cle = np.round(np.asarray(P, np.float64) * 4096.0).astype(np.int64)
    _, groupe = np.unique(cle, axis=0, return_inverse=True)
    groupe = np.asarray(groupe).ravel()
    n = int(groupe.max()) + 1
    f = np.asarray(faces, np.int64)
    a = groupe[np.concatenate([f[:, 0], f[:, 1], f[:, 2]])]
    b = groupe[np.concatenate([f[:, 1], f[:, 2], f[:, 0]])]
    k = a != b
    a, b = np.concatenate([a[k], b[k]]), np.concatenate([b[k], a[k]])
    o = np.lexsort((b, a))
    a, b = a[o], b[o]
    u = np.ones(len(a), bool)
    u[1:] = (a[1:] != a[:-1]) | (b[1:] != b[:-1])
    a, b = a[u], b[u]
    return groupe, b, np.searchsorted(a, np.arange(n + 1))


# ------------------------------------------------------------------------------- vanilla
def bouts_vanilla(sq, Pv, Wv):
    """("vanilla tips") End point of each finger: J2 + d . max((x - J2) . d) over the vanilla
    vertices the tip dominates, d = axis of the last phalanx."""
    dom = Wv.argmax(1)
    T = {}
    for c in 'lr':
        for D in range(5):
            _h, _b0, b1, b2 = sq.chaine(c, D)
            J1, J2 = sq.joint(b1), sq.joint(b2)
            d = (J2 - J1) / max(np.linalg.norm(J2 - J1), 1e-9)
            X = Pv[dom == b2]
            T[(c, D)] = J2 + d * (float(((X - J2) @ d).max()) if len(X) else np.linalg.norm(J2 - J1))
    return T


def tables_vanilla(sq, Pv, Wv, bouts):
    """The vanilla's profile along each finger: for u from -1 to 3 in steps of 0.05, the mean
    share (base, middle, tip) of the vanilla vertices that carry this finger."""
    T = {}
    grille = np.arange(-1.0, 3.0001, 0.05)
    for c in 'lr':
        for D in range(5):
            h, b0, b1, b2 = sq.chaine(c, D)
            pts = np.array([sq.joint(h), sq.joint(b0), sq.joint(b1), sq.joint(b2), bouts[(c, D)]])
            sel = Wv[:, [b0, b1, b2]].sum(1) > 0.01
            u, _d = proj_polyligne(Pv[sel], pts)
            u = u - 1.0
            w = Wv[sel][:, [b0, b1, b2]]
            prof = np.zeros((len(grille), 3))
            ok = np.zeros(len(grille), bool)
            for k, g in enumerate(grille):
                m = np.abs(u - g) < 0.075                 # sliding window of 0.15
                if m.sum() >= 3:
                    prof[k] = w[m].mean(0)
                    ok[k] = True
            for j in range(3):
                if ok.any():
                    prof[:, j] = np.interp(grille, grille[ok], prof[ok, j])
            T[(c, D)] = (grille, prof)
    return T


# ------------------------------------------------------------------------------- the core
def poids_doigts(P, faces, cumul, sq, bouts, tables, log=log_defaut, etiq_modele=None):
    """("finger weights") Replace the FINGER weights: each finger recognised by its topological
    component, each vertex placed on ITS chain by projection, vanilla profile along the finger,
    continuous blend towards the existing weights in the palm. `cumul`: list of dict
    {global bone: weight}.
    `etiq_modele`: (side, finger) per vertex, given by the model's RIG (conformed chain,
    doigts_modele.npz): when they cover the hand, they REPLACE the recognition by topology, which
    requires five separate finger pieces.
    Returns (modified cumul, mask of the touched vertices, report)."""
    n = len(P)
    grp, vois, debut = graphe(P, faces)
    ng = len(debut) - 1
    touche = np.zeros(n, bool)
    rapport = {}
    for c in 'lr':
        main = sq.idx['bip01 %s hand' % c]
        chaines = [sq.chaine(c, D) for D in range(5)]
        doigt_de_os = {b: D for D, ch in enumerate(chaines) for b in ch[1:]}
        zone = np.array([sum(w for b, w in acc.items() if b == main or b in doigt_de_os)
                         for acc in cumul]) > 0.5
        U = np.zeros((n, 5))
        Dd = np.zeros((n, 5))
        for D, (h, b0, b1, b2) in enumerate(chaines):
            pts = np.array([sq.joint(h), sq.joint(b0), sq.joint(b1), sq.joint(b2), bouts[(c, D)]])
            u, d = proj_polyligne(P, pts)
            U[:, D] = u - 1.0
            Dd[:, D] = d
        lab = Dd.argmin(1)
        ul = U[np.arange(n), lab]
        etiq_v = None
        rigides = np.zeros(n, bool)
        source_m = None
        if etiq_modele is not None:
            co_m, dg_m = etiq_modele[0], etiq_modele[1]
            source_m = etiq_modele[2] if len(etiq_modele) > 2 else 'rig'
            rigides = (co_m == (0 if c == 'l' else 1)) & (dg_m == -2)
            sel_m = (co_m == (0 if c == 'l' else 1)) & (dg_m >= 0)
            lab_m = np.where(sel_m, dg_m, -1).astype(np.int64)
            # a vertex far from ITS chain (accessory labelled as hand) is not a finger
            proche = Dd[np.arange(n), np.maximum(lab_m, 0)] < 2 * R_MAX
            lab_m = np.where(proche & (lab_m >= 0), lab_m, -1)
            comptes = [int((lab_m == D).sum()) for D in range(5)]
            if sum(1 for x in comptes if x >= 8) >= 3:
                etiq_v = lab_m
                log('%s hand: fingers given by the model\'s RIG (doigts_modele.npz), vertices per '
                    'finger %s' % ('LEFT' if c == 'l' else 'RIGHT', comptes))
            else:
                log('%s hand: model rig without usable fingers (%s) -> topology'
                    % ('LEFT' if c == 'l' else 'RIGHT', comptes))
        U_b = None
        # WARNING: no "by branches" fallback HERE: labelling fingers that do not go through the
        # game's joints makes them pivot off target and stretch into bars in a fist (measured on
        # Brand and Miles). Rig-less models go through tools/doigts_sans_rig.py, which POSES their
        # fingers on the game's chains before writing doigts_modele.npz.
        if etiq_v is None:
            etiq_v = _etiquettes_topologie(c, n, ng, grp, vois, debut, zone, U, Dd, lab, ul, log)
        # SCULPTED folded fingers (fist already modelled) or unposable ones: attached to the hand,
        # otherwise the game's fist would fold them a second time into the palm -- even if the
        # rest of the hand gave nothing
        for i in np.where(rigides | ((etiq_v == -2) if etiq_v is not None else False))[0]:
            cumul[i] = {main: 1.0}
            touche[i] = True
        # WARNING: hand posed by its SHAPE (rig-less model): only the vertices recognised as
        # fingers keep finger bones. The palm inherited the vanilla's phalanx weights by
        # proximity: in a fist it went off with fingers that were not its own (spikes measured on
        # Gojo, Brand, TASM1). It now follows only the hand.
        if source_m == 'doigts_sans_rig' and (sel_m.any() or rigides.any()):
            lab_paume = etiq_v if etiq_v is not None else np.full(n, -1)
            nettoyes = 0
            for i in np.where(zone & (lab_paume == -1) & ~rigides)[0]:
                acc = cumul[i]
                dw = sum(w for b, w in acc.items() if b in doigt_de_os)
                if dw > 0:
                    neuf = {b: w for b, w in acc.items() if b not in doigt_de_os}
                    neuf[main] = neuf.get(main, 0.0) + dw
                    cumul[i] = neuf
                    touche[i] = True
                    nettoyes += 1
            if nettoyes:
                log('%s hand: %d palm vertices without a finger bone (hand posed without a rig)'
                    % ('LEFT' if c == 'l' else 'RIGHT', nettoyes))
        if rigides.any() and etiq_v is None:
            log('%s hand: %d vertices of folded or unposable fingers attached to the hand'
                % ('LEFT' if c == 'l' else 'RIGHT', int(rigides.sum())))
        if etiq_v is None:
            rapport[c] = None
            continue
        # 3. weights: vanilla profile along the finger, blended with the existing ones from U_MIN
        #    to U_PLEIN (smoothstep)
        par_doigt = Counter()
        for i in range(n):
            D = int(etiq_v[i])
            if D < 0:
                continue
            u = U_b[i] if U_b is not None else U[i, D]
            t = float(np.clip((u - U_MIN[D]) / (U_PLEIN[D] - U_MIN[D]), 0.0, 1.0))
            a = t * t * (3.0 - 2.0 * t)
            if a <= 0.0:
                continue
            _h, b0, b1, b2 = chaines[D]
            grille, prof = tables[(c, D)]
            p = np.array([np.interp(u, grille, prof[:, j]) for j in range(3)])
            acc = cumul[i]
            reste = {b: w for b, w in acc.items() if b not in doigt_de_os}
            s = 1.0 if u >= U_PLEIN[D] else min(1.0, float(p.sum()))
            p = p / p.sum() if p.sum() > 1e-6 else np.array([1.0, 0.0, 0.0])
            prof_w = {}
            tr = sum(reste.values())
            if s < 1.0:
                for b, w in (reste.items() if tr > 0 else [(main, 1.0)]):
                    prof_w[b] = (1.0 - s) * w / (tr if tr > 0 else 1.0)
            for b, x in zip((b0, b1, b2), p):
                if x * s > 1e-4:
                    prof_w[b] = prof_w.get(b, 0.0) + float(x * s)
            neuf = {b: (1.0 - a) * w for b, w in acc.items()}
            for b, w in prof_w.items():
                neuf[b] = neuf.get(b, 0.0) + a * w
            cumul[i] = {b: w for b, w in neuf.items() if w > 1e-4}
            touche[i] = True
            par_doigt[D] += 1
        rapport[c] = {D: int(par_doigt[D]) for D in range(5)}
        log('%s hand: %d vertices re-weighted, per finger (thumb..little) %s'
            % ('LEFT' if c == 'l' else 'RIGHT', sum(par_doigt.values()),
               [rapport[c][D] for D in range(5)]))
    return cumul, touche, rapport


def _etiquettes_topologie(c, n, ng, grp, vois, debut, zone, U, Dd, lab, ul, log=log_defaut):
    """Finger recognition by TOPOLOGY (the original method): returns the finger of each vertex
    (-1 outside the fingers), or None if the hand does not show five distinct finger pieces."""
    # 1. seeds: beyond the middle of the 1st phalanx, close to a chain
    graine = zone & (ul > U_GRAINE) & (Dd.min(1) < D_GRAINE)
    noeud_graine = np.zeros(ng, bool)
    noeud_graine[grp[graine]] = True
    comp = np.full(ng, -1, np.int64)
    comps = []
    for s0 in np.where(noeud_graine)[0]:
        if comp[s0] >= 0:
            continue
        k = len(comps)
        comp[s0] = k
        pile, membres = [int(s0)], [int(s0)]
        while pile:
            x = pile.pop()
            for y in vois[debut[x]:debut[x + 1]]:
                if noeud_graine[y] and comp[y] < 0:
                    comp[y] = k
                    pile.append(int(y))
                    membres.append(int(y))
        comps.append(membres)
    ordre = sorted(range(len(comps)), key=lambda k: -len(comps[k]))[:5]
    doigt_de_comp = {}
    for k in ordre:
        vs = np.where(graine & (comp[grp] == k))[0]
        doigt_de_comp[k] = Counter(lab[vs].tolist()).most_common(1)[0][0]
    if len(ordre) < 5 or sorted(doigt_de_comp.values()) != [0, 1, 2, 3, 4]:
        log('!! hand %s: the finger pieces do not designate 5 distinct fingers (%s) -> '
            'hand left as it is (merged fingers, mitten, non-vanilla pose?)'
            % (c.upper(), {len(comps[k]): D for k, D in doigt_de_comp.items()}))
        return None
    # 2. propagation towards the palm, bounded along the finger AND in radius
    etiq = np.full(ng, -1, np.int64)
    q = deque()
    for k, D in doigt_de_comp.items():
        for x in comps[k]:
            etiq[x] = D
            q.append(x)
    zone_n = np.zeros(ng, bool)
    zone_n[grp[zone]] = True
    u_n = np.full((ng, 5), -9.0)
    u_n[grp] = U
    d_n = np.full((ng, 5), 9.0)
    d_n[grp] = Dd
    while q:
        x = q.popleft()
        D = etiq[x]
        for y in vois[debut[x]:debut[x + 1]]:
            if etiq[y] < 0 and zone_n[y] and u_n[y, D] > U_MIN[D] and d_n[y, D] < R_MAX:
                etiq[y] = D
                q.append(int(y))
    return etiq[grp]


# Fingers as BRANCHES of the hand (rig-less models whose fingers are not five separate pieces
# posed like the vanilla). Measured 2026-10-07 on the installed mods: Gojo, 2099, Miles, TASM,
# Brand stayed at 0..20 finger bones out of 30 -- the topology refused, the hand kept proximity
# weights taken from several of the game's fingers, hence broken fingers in a fist.
PROMINENCE = 0.012          # a branch shorter than this is not a finger (bump, nail)
REPLIE = 0.55               # tip-base / length below this ratio: finger already folded in the model
NOMS_DOIGTS = ('thumb', 'index', 'middle', 'ring', 'little')      # finger names, for the log


def _etiquettes_branches(c, P, n, ng, grp, vois, debut, zone, sq, bouts, log=log_defaut):
    """(label, u) per vertex from `branches_main`, or None."""
    r = branches_main(c, P, ng, grp, vois, debut, zone, sq, bouts, log)
    if r is None:
        return None
    return r['etiq'][grp], r['u'][grp]


def branches_main(c, P, ng, grp, vois, debut, zone, sq, bouts, log=log_defaut):
    """("branches of the hand") Finger of each vertex from the SHAPE of the hand, without
    requiring five separate pieces.

    Geodesic distance from the wrist; the fingers are the branches that emerge from it
    (persistence segmentation: a branch splits off when it joins the rest through a saddle, if
    it rises above that saddle by PROMINENCE). Each branch is matched to one of the game's
    fingers by its base and its tip (optimal assignment), and parameterised along ITS length,
    in proportion to the phalanges of the vanilla finger. A mitten (fused fingers) bends as one
    block with the finger it is given; a branch already folded in the model (sculpted fist) is
    attached to the hand (label -2).
    Returns a dict: 'etiq' and 'u' per NODE, 'g' (distance to the wrist), 'Pn' (node positions),
    'branches' (nodes, tip, saddle, finger, tip-base/length ratio), or None. The keys are read by
    doigts_sans_rig.py."""
    import heapq
    from itertools import permutations
    cnt = np.bincount(grp, minlength=ng).astype(np.float64)
    Pn = np.zeros((ng, 3))
    for k in range(3):
        Pn[:, k] = np.bincount(grp, weights=P[:, k], minlength=ng) / np.maximum(cnt, 1)
    zn = np.zeros(ng, bool)
    zn[grp[zone]] = True
    main_j = sq.joint(sq.idx['bip01 %s hand' % c])
    zn &= np.linalg.norm(Pn - main_j, axis=1) < 0.30
    if zn.sum() < 30:
        log('!! hand %s: too few vertices in the hand (%d) -> left as it is'
            % (c.upper(), int(zn.sum())))
        return None
    # wrist: hand nodes next to a node outside the hand. A hand modelled APART from its sleeve
    # (Gojo) has no such border: each borderless piece then starts from its nodes closest to the
    # elbow, along the forearm -> hand axis.
    bord = set(x for x in np.where(zn)[0] if any(not zn[y] for y in vois[debut[x]:debut[x + 1]]))
    axe = main_j - sq.joint(sq.idx['bip01 %s forearm' % c])
    axe = axe / max(np.linalg.norm(axe), 1e-9)
    t = (Pn - main_j) @ axe
    vu = np.zeros(ng, bool)
    for s0 in np.where(zn)[0]:
        if vu[s0]:
            continue
        comp, pile = [], [int(s0)]
        vu[s0] = True
        while pile:
            x = pile.pop()
            comp.append(x)
            for y in vois[debut[x]:debut[x + 1]]:
                if zn[y] and not vu[y]:
                    vu[y] = True
                    pile.append(int(y))
        if len(comp) >= 30 and not any(x in bord for x in comp):
            comp = np.array(comp)
            bord.update(int(x) for x in comp[t[comp] <= t[comp].min() + 0.006])
    bord = sorted(bord)
    if not bord:
        return None
    # Dijkstra from the wrist border over the hand's nodes
    g = np.full(ng, np.inf)
    tas = [(0.0, int(x)) for x in bord]
    for x in bord:
        g[x] = 0.0
    heapq.heapify(tas)
    while tas:
        d, x = heapq.heappop(tas)
        if d > g[x]:
            continue
        for y in vois[debut[x]:debut[x + 1]]:
            if not zn[y]:
                continue
            nd = d + float(np.linalg.norm(Pn[x] - Pn[y]))
            if nd < g[y]:
                g[y] = nd
                heapq.heappush(tas, (nd, int(y)))
    ok = np.isfinite(g) & zn
    # ---- persistence segmentation, from the farthest to the nearest to the wrist (union-find)
    racine = np.full(ng, -1, np.int64)
    comps = {}

    def trouve(x):
        while racine[x] != x:
            racine[x] = racine[racine[x]]
            x = racine[x]
        return x
    for x in sorted(np.where(ok)[0], key=lambda v: -g[v]):
        act = {trouve(y) for y in vois[debut[x]:debut[x + 1]] if ok[y] and racine[y] >= 0}
        act = {r for r in act if not comps[r]['fini']}
        racine[x] = x
        if not act:
            comps[x] = {'noeuds': [x], 'pic': g[x], 'bout': x, 'fini': False, 'fusion': None, 'col': None}
            continue
        ordre = sorted(act, key=lambda r: -comps[r]['pic'])
        m0 = ordre[0]
        for r in ordre[1:]:
            if comps[r]['pic'] - g[x] >= PROMINENCE:
                comps[r]['fini'] = True
                comps[r]['col'] = g[x]
                if comps[m0]['fusion'] is None:
                    comps[m0]['fusion'] = g[x]
            else:
                comps[m0]['noeuds'] += comps[r]['noeuds']
                racine[r] = m0
                del comps[r]
        racine[x] = m0
        comps[m0]['noeuds'].append(x)
    branches = []
    for r, cp in comps.items():
        if cp['fini']:
            branches.append((np.array(cp['noeuds']), cp['bout'], cp['col']))
        elif cp['fusion'] is not None and cp['pic'] - cp['fusion'] >= PROMINENCE:
            nds = np.array([v for v in cp['noeuds'] if g[v] >= cp['fusion']])
            branches.append((nds, cp['bout'], cp['fusion']))
    branches = [b for b in branches if len(b[0]) >= 4 and g[b[1]] - b[2] >= PROMINENCE]
    if not branches:
        log('!! hand %s: no finger branch (hand in one block) -> left as it is' % c.upper())
        return None
    branches.sort(key=lambda b: -(g[b[1]] - b[2]))
    branches = branches[:5]
    # ---- matching with the game's fingers: base and tip of the branch against the vanilla's
    # WARNING: a branch's base = its nodes closest to the WRIST along the hand axis, not its
    # nodes with the smallest geodesic distance: fingers that TOUCH (Gojo: index and ring glued
    # to the middle finger) get their geodesic through the contact point, and their "base" landed
    # near the tip -> false folded finger, then a thumb bent against a rigid neighbour.
    bases, bouts_m = [], []
    for nds, tip, col in branches:
        tt = (Pn[nds] - main_j) @ axe
        pres = nds[tt <= np.percentile(tt, 20)]
        bases.append(Pn[pres].mean(0) if len(pres) else Pn[nds].mean(0))
        bouts_m.append(Pn[tip])
    cout = np.zeros((len(branches), 5))
    for k in range(len(branches)):
        for D in range(5):
            _h, b0, b1, b2 = sq.chaine(c, D)
            cout[k, D] = (np.linalg.norm(bases[k] - sq.joint(b1))
                          + 0.5 * np.linalg.norm(bouts_m[k] - bouts[(c, D)]))
    meilleur, choix = np.inf, None
    for perm in permutations(range(5), len(branches)):
        cc = sum(cout[k, perm[k]] for k in range(len(branches)))
        if cc < meilleur:
            meilleur, choix = cc, perm
    etiq_n = np.full(ng, -1, np.int64)
    u_n = np.zeros(ng)
    resume_b = []
    infos = []
    for k, (nds, tip, col) in enumerate(branches):
        D = choix[k]
        v = bouts_m[k] - bases[k]
        L = float(np.linalg.norm(v))
        # folded = the finger comes back towards the palm: its base -> tip axis turns its back on
        # the hand axis (the thumb, naturally slanted, gets a wider margin)
        cosang = float(v @ axe) / max(L, 1e-9)
        replie = cosang < (-0.2 if D == 0 else 0.3) or L < PROMINENCE
        infos.append({'noeuds': nds, 'bout': tip, 'col': col, 'doigt': D, 'droit': cosang,
                      'replie': replie, 'longueur': L, 'base': bases[k]})
        if replie:
            etiq_n[nds] = -2
            resume_b.append('%s folded (axis at %.0f deg from the hand)'
                            % (NOMS_DOIGTS[D], np.degrees(np.arccos(np.clip(cosang, -1, 1)))))
            continue
        # u along the branch, in proportion to the phalanges of the vanilla finger
        _h, b0, b1, b2 = sq.chaine(c, D)
        pts = [sq.joint(b0), sq.joint(b1), sq.joint(b2), bouts[(c, D)]]
        cum = np.cumsum([0.0] + [float(np.linalg.norm(pts[i + 1] - pts[i])) for i in range(3)])
        u0 = 1.0 if D == 0 else 0.2                           # the thumb's saddle is at its MCP
        s0 = np.interp(u0, [0, 1, 2, 3], cum)
        f = np.clip(((Pn[nds] - bases[k]) @ v) / max(L * L, 1e-12), 0.0, 1.0)
        u_n[nds] = np.interp(s0 + f * (cum[-1] - s0), cum, [0, 1, 2, 3])
        etiq_n[nds] = D
        resume_b.append('%s %d nodes, %.0f mm' % (NOMS_DOIGTS[D], len(nds), L * 1000))
    log('%s hand: fingers found as BRANCHES of the hand (%d): %s'
        % ('LEFT' if c == 'l' else 'RIGHT', len(branches), '; '.join(resume_b)))
    return {'etiq': etiq_n, 'u': u_n, 'g': g, 'Pn': Pn, 'branches': infos}


def finaliser(acc, sq, sauts_max=4, arcs_max=5, k=4):
    """("finalise") Same safeguards as poids_depuis_vanilla: one side only, distance to the
    dominant bone <= 4 edges, distance between two influences <= 5 edges (the lightest is
    dropped), 4 influences, sum 1."""
    paires = sorted(((w, b) for b, w in acc.items() if w > 0), reverse=True)
    pg = sum(w for w, b in paires if cote(sq.noms[b]) == 'l')
    pd = sum(w for w, b in paires if cote(sq.noms[b]) == 'r')
    if pg > 0 and pd > 0:
        perdant = 'r' if pg >= pd else 'l'
        paires = [(w, b) for w, b in paires if cote(sq.noms[b]) != perdant]
    if paires:
        bd = paires[0][1]
        paires = [(w, b) for w, b in paires if sauts(sq.parents, bd, b) <= sauts_max]
        while len(paires) > 1 and max(sauts(sq.parents, x, y)
                                      for _, x in paires for _, y in paires) > arcs_max:
            paires = paires[:-1]
    paires = paires[:k]
    t = sum(w for w, _ in paires)
    return [(b, w / t) for w, b in paires]


def quantifier(paires):
    """("quantise") Like the toolkit's writer: round(w * 32767), the gap to 32767 on the
    heaviest."""
    g = np.full(4, -1, np.int64)
    q = np.zeros(4, np.int64)
    for i, (b, w) in enumerate(paires[:4]):
        g[i] = b
        q[i] = max(0, min(32767, int(round(w * 32767.0))))
    actifs = [i for i in range(4) if q[i] > 0]
    if actifs:
        best = max(actifs, key=lambda i: q[i])
        q[best] = max(0, min(32767, q[best] + 32767 - int(q.sum())))
    g[q == 0] = -1
    return g, q


def meme_influence(g1, q1, g2, q2):
    a = sorted((int(b), int(w)) for b, w in zip(g1, q1) if w > 0)
    b = sorted((int(b), int(w)) for b, w in zip(g2, q2) if w > 0)
    return a == b


# ------------------------------------------------------------------------------- palette
def palette_de(G, Q, sommets=None):
    if sommets is not None:
        G, Q = G[sommets], Q[sommets]
    return set(np.unique(G[Q > 0]).tolist())


def replier(G, Q, sq, max_os, log=log_defaut):
    """("fold") ONE section, palette > max_os: bones are folded onto their parent, in steps
    (REPLIS), until it fits. Folded weights are added AS INTEGERS: the sum stays exactly 32767.
    Returns (G, Q, mask of the modified vertices, list of the folded bones)."""
    G, Q = G.copy(), Q.copy()
    modifies = np.zeros(len(G), bool)
    replies = []
    for quoi, motif in REPLIS:
        utilises = palette_de(G, Q)
        if len(utilises) <= max_os:
            break
        lot = sorted(b for b in utilises if re.search(motif, sq.noms[b]))
        if not lot:
            continue
        repli = set(replies) | set(lot)

        def cible(b):
            while b in repli:
                b = sq.parents[b]
            return b
        for b in lot:
            lignes_b = np.where((G == b).any(1))[0]
            for i in lignes_b:
                acc = {}
                for bb, w in zip(G[i], Q[i]):
                    if w > 0:
                        cc = cible(int(bb))
                        acc[cc] = acc.get(cc, 0) + int(w)
                paires = sorted(acc.items(), key=lambda x: -x[1])
                G[i] = -1
                Q[i] = 0
                for k, (bb, w) in enumerate(paires[:4]):
                    G[i, k] = bb
                    Q[i, k] = w
                modifies[i] = True
        replies += lot
        log('   single palette: %s folded -> %d bones' % (quoi, len(palette_de(G, Q))))
    if len(palette_de(G, Q)) > max_os:
        raise RuntimeError('single palette cannot be brought down to %d bones (%d)'
                           % (max_os, len(palette_de(G, Q))))
    return G, Q, modifies, replies


def niveaux_bras(sq, c):
    """Bones detached with the hand, from the shortest to the longest set (we go up the arm
    if needed)."""
    def nom(motif):
        return {b for b in range(sq.n) if cote(sq.noms[b]) == c and re.search(motif, sq.noms[b])}
    n0 = nom(r'hand|finger')
    n1 = n0 | nom(r'forearm|foretwist')
    n2 = n1 | nom(r'upperarm|bone01')
    n3 = n2 | nom(r'clavicle')
    return [n0, n1, n2, n3]


def decouper(faces, G, Q, sq, max_os, log=log_defaut):
    """("split") Split into sections of <= max_os bones. First the RIGHT hand alone in its
    section, then both hands, going up the arm only if the palette still overflows. Returns a
    list of triangle masks (body first) and their names (for the log)."""
    tout = np.ones(len(faces), bool)

    def pal(masque):
        return palette_de(G, Q, np.unique(faces[masque]))
    if len(pal(tout)) <= max_os:
        return [tout], ['whole body']
    porte = {}
    for c in 'rl':
        for niv, lot in enumerate(niveaux_bras(sq, c)):
            v = np.isin(G, list(lot)) & (Q > 0)
            porte[(c, niv)] = v.any(1)[faces].any(1)
    for cotes in (('r',), ('r', 'l')):
        for niv in range(4):
            reste = tout.copy()
            masques, noms = [], []
            for c in cotes:
                m = porte[(c, niv)] & reste
                masques.append(m)
                noms.append('%s (%s)' % ('hand' if niv == 0 else 'arm', 'right' if c == 'r' else 'left'))
                reste &= ~m
            secs = [reste] + masques
            if all(m.any() for m in secs) and all(len(pal(m)) <= max_os for m in secs):
                return secs, ['body'] + noms
    raise RuntimeError('no split fits in %d bones per section' % max_os)


# ------------------------------------------------------------------------------- writing
def reecrire(m, sorties, chemin=None, bornes_modele=None):
    """("rewrite") Write a loose .mesh in the layout of the toolkit's writer (local offsets):
    0x50 header, section table, sections aligned on 16, PHYS = VB, align 4, IB, align 4.
    `sorties`: list of dict(ref, palette, lignes, faces, bornes, decl, stride, prim, inc,
    index_size). The header (name pointer, skeleton, external meshes, 0x40 block) comes from `m`.
    Per-section record written at `info`: 8 floats of bounds (centre, radius, half-box, 0), then
    12 dwords from +0x20: material ref, palette offset, palette count, 0, inc[0], vertex count,
    inc[1], VB offset (+0x2C, patched below), inc[2], index count, index size, schema offset;
    the IB offset is patched at +0x3C."""
    n = len(sorties)
    img = bytearray(m.raw[0:0x50])
    struct.pack_into('<I', img, 0x0C, n)            # section count
    struct.pack_into('<I', img, 0x10, 0x50)         # section table right after the header
    if bornes_modele is not None:
        struct.pack_into('<8f', img, 0x20, *bornes_modele)
    img += bytes(n * 8)
    while len(img) % 16:
        img.append(0)
    infos = []
    for i, s in enumerate(sorties):
        if i and len(img) % 16:
            img += bytes(align(len(img), 16) - len(img))
        info = len(img)
        infos.append(info)
        struct.pack_into('<II', img, 0x50 + i * 8, 0, info)
        img += bytes(0x50)
        img += struct.pack('<II', *s['prim'])
        pal_off = len(img)
        for b in s['palette']:
            img += struct.pack('<H', int(b))
        if len(img) % 4:
            img += bytes(align(len(img), 4) - len(img))
        sch = len(img)
        img += struct.pack('<III', s['stride'], sch + 12, s['inc'][3])
        for d in s['decl']:
            img += struct.pack('<HHBBBB', d.stream, d.offset, d.dtype, d.method, d.usage, d.usage_index)
        img += SENTINELLE
        struct.pack_into('<8f', img, info, *s['bornes'])
        struct.pack_into('<12I', img, info + 0x20, s['ref'], pal_off if len(s['palette']) else 0,
                         len(s['palette']), 0, s['inc'][0], len(s['lignes']), s['inc'][1], 0,
                         s['inc'][2], len(s['faces']), s['index_size'], sch)
    out = bytearray(img)
    for i, s in enumerate(sorties):
        struct.pack_into('<I', out, infos[i] + 0x2C, len(out))
        out += np.ascontiguousarray(s['lignes'], np.uint8).tobytes()
        if len(out) % 4:
            out += bytes(align(len(out), 4) - len(out))
        struct.pack_into('<I', out, infos[i] + 0x3C, len(out))
        out += np.asarray(s['faces'], '<u2' if s['index_size'] == 2 else '<u4').tobytes()
        if i != n - 1 and len(out) % 4:
            out += bytes(align(len(out), 4) - len(out))
    if chemin:
        with open(chemin, 'wb') as f:
            f.write(bytes(out))
    return bytes(out)


def copie_section(m, s):
    """A section as a reecrire() entry, unchanged."""
    return dict(ref=s.material_ref_serialized, palette=list(s.bone_palette), lignes=lignes(m, s),
                faces=np.frombuffer(m.raw, '<u2' if s.index_size == 2 else '<u4', s.index_count,
                                    s.index_buffer_offset).astype(np.int64),
                bornes=tuple(s.mesh_offset) + (s.sphere_radius,) + tuple(s.mesh_bbox),
                decl=s.decl, stride=s.vertex_stride, prim=(s.primitive_type, s.primitive_unknown),
                inc=(s.unknown_30, s.unknown_38, s.unknown_40, s.schema_unknown),
                index_size=s.index_size)


def sait_reecrire(m):
    """("can rewrite") The test that allows everything else: rewriting the input as it is gives
    back its bytes."""
    sorties = [copie_section(m, s) for s in m.sections]
    for s in sorties:
        s['faces'] = s['faces'].reshape(-1)       # already flat, the exact file order
    return reecrire(m, sorties) == m.raw


def _snorm(v):
    return np.clip(np.rint(np.clip(v, -1.0, 1.0) * 32767.0), -32767, 32767).astype(np.int16)


def bornes_union(b, P):
    """Box (centre, radius, half-extent, 0) enlarged to contain the points P."""
    c, h = np.array(b[0:3]), np.array(b[4:7])
    lo, hi = np.minimum(c - h, P.min(0)), np.maximum(c + h, P.max(0))
    if np.all(lo >= c - h - 1e-7) and np.all(hi <= c + h + 1e-7):
        return tuple(b)
    c2, h2 = (lo + hi) / 2, (hi - lo) / 2
    return tuple(float(x) for x in c2) + (float(np.linalg.norm(h2)),) + tuple(float(x) for x in h2) + (0.0,)


# ------------------------------------------------------------------------------- processing
def cle_topologie(faces, uv):
    h = hashlib.sha256()
    h.update(np.asarray(faces, '<i4').tobytes())
    h.update(np.asarray(uv, '<i2').tobytes())
    return h.hexdigest()


def etiquettes_modele(dossier, p, log=log_defaut):
    """("model labels") Finger of each vertex according to the model's RIG: `doigts_modele.npz`,
    written by the chain when it conformed the model to the game's skeleton
    (tools/conformer_squelette.py), or by doigts_sans_rig.py. The .mesh vertices are matched by
    their quantised position (1/512, the exporter's). Returns (side, finger, source) aligned on
    `p`, or None."""
    chemin = os.path.join(dossier, 'doigts_modele.npz')
    if not os.path.isfile(chemin):
        return None
    z = np.load(chemin)
    Q = np.rint(np.asarray(z['P'], np.float64) * 512.0).astype(np.int64)
    co, dg, part = z['cote'], z['doigt'], z['part']
    cle = lambda X: (X[:, 0] + 40000) * 6400000000 + (X[:, 1] + 40000) * 80000 + (X[:, 2] + 40000)
    k_mod = cle(Q)
    o = np.argsort(-part, kind='stable')          # at an equal position, the surest label
    table = {}
    for i in o[::-1]:
        table[int(k_mod[i])] = i
    Qp = np.rint(np.asarray(p, np.float64) * 512.0).astype(np.int64)
    k_p = cle(Qp)
    idx = np.array([table.get(int(k), -1) for k in k_p], np.int64)
    manque = np.where(idx < 0)[0]
    if len(manque):
        # a few vertices duplicated or rounded differently: the nearest within 3/512
        P = np.asarray(z['P'], np.float64)
        for a0 in range(0, len(manque), 512):
            m = manque[a0:a0 + 512]
            d = np.linalg.norm(p[m][:, None, :] - P[None, :, :], axis=2)
            j = d.argmin(1)
            ok = d[np.arange(len(m)), j] <= 3.0 / 512.0
            idx[m[ok]] = j[ok]
    taux = float((idx >= 0).mean())
    if taux < 0.9:
        log('!! doigts_modele.npz ignored: only %.0f %% of the vertices found (mesh modified '
            'after the chain?)' % (100 * taux))
        return None
    cote_v = np.where(idx >= 0, co[np.maximum(idx, 0)], -1).astype(np.int64)
    doigt_v = np.where(idx >= 0, dg[np.maximum(idx, 0)], -1).astype(np.int64)
    source = str(z['source']) if 'source' in z.files else 'rig'
    log('fingers %s: %.1f %% of the vertices found in doigts_modele.npz'
        % ('posed by shape (no rig)' if source == 'doigts_sans_rig' else 'from the model\'s rig',
           100 * taux))
    return cote_v, doigt_v, source


def chemins_vanilla(racine=RACINE):
    return (os.path.join(racine, DOSSIER_ROUGE, MESH_VANILLA),
            os.path.join(racine, DOSSIER_ROUGE, SKEL_SOURCE))


def skel_cible_auto(hash_, racine=RACINE):
    if hash_ not in SQUELETTE_CIBLE:
        return None
    dossier, nom = SQUELETTE_CIBLE[hash_]
    p = os.path.join(racine, dossier, nom)
    return p if os.path.isfile(p) else None


def traiter(entree, sortie, vanilla_mesh=None, skel=None, skel_cible=None, poids_de=None,
            trace=None, max_os=MAX_OS, forcer=False, mode='auto', reposer='auto', log=log_defaut):
    """("process") The whole job. Returns a report (dict) whose 'etat' ("state") is 'ecrit'
    (written), 'deja' (already done) or 'inchange' (unchanged); main() tests those values.
    Writes `sortie` only after ALL the checks."""
    rap = {'entree': entree, 'sortie': sortie}
    vm, sk0 = chemins_vanilla()
    vanilla_mesh = vanilla_mesh or vm
    skel = skel or sk0
    m = fmt.parse_mesh(entree)
    rap['hash'] = '0x%08X' % m.filename_hash
    if not sait_reecrire(m):
        raise RuntimeError('unknown .mesh layout: identical rewriting fails, '
                           'nothing is touched')
    if mode == 'auto':
        mode = 'reference' if m.filename_hash in PAR_REFERENCE else 'index'
    rap['mode'] = mode
    skel_cible = skel_cible or skel_cible_auto(m.filename_hash) or skel
    src = Squelette(skel)
    cib = Squelette(skel_cible)
    if cib.n != src.n or cib.hashes != src.hashes:
        raise RuntimeError('incompatible skeletons (%s / %s)' % (skel, skel_cible))

    # ---- sections: ghosts, real ones, body
    vraies = [s for s in m.sections if not est_fantome(m, s)]
    if not vraies:
        raise RuntimeError('no real section')
    princ = max(vraies, key=lambda s: s.vertex_count)
    corps = [s for s in vraies if s.material_ref_serialized == princ.material_ref_serialized
             and s.vertex_stride == princ.vertex_stride]
    i_vraies = {s.index for s in vraies}
    i_corps = {s.index for s in corps}
    if mode == 'index' and len(corps) != 1:
        raise RuntimeError('material by index: exactly one real body section expected (%d)'
                           % len(corps))
    for s in corps:
        if not disposition_ok(s):
            raise RuntimeError('section %d: vertex layout not supported' % s.index)
    L = np.concatenate([lignes(m, s) for s in corps])
    F, base = [], 0
    for s in corps:
        F.append(faces_section(m, s) + base)
        base += s.vertex_count
    F = np.concatenate(F)
    G0, Q0 = map(np.concatenate, zip(*[influences(m, s, lignes(m, s)) for s in corps]))
    p = np.concatenate([positions(s, lignes(m, s)) for s in corps])
    n = len(L)
    uv_off = _decl(corps[0], 5).offset
    uv = L[:, uv_off:uv_off + 4].copy().view('<i2')
    cle = cle_topologie(F, uv)
    rap['sections_entree'] = [(s.index, s.vertex_count, len(set(s.bone_palette)),
                               '0x%X' % s.material_ref_serialized,
                               'fantome' if s.index not in i_vraies else
                               ('corps' if s.index in i_corps else 'autre'))
                              for s in m.sections]
    log('%s: %s, %d vertices, %d triangles, material 0x%X by %s'
        % (os.path.basename(entree), rap['hash'], n, len(F), princ.material_ref_serialized,
           'REFERENCE (several sections allowed)' if mode == 'reference'
           else 'INDEX (one real section only, index %d)' % princ.index))

    doigts = os_doigts(src)
    milieu = phalanges_du_milieu(src)
    porte0 = palette_de(G0, Q0)
    rap['os_doigts_avant'] = sorted(src.noms[b] for b in doigts if b in porte0)
    if all(b in porte0 for b in milieu) and not forcer:
        log('already processed: the 10 middle phalanges already carry weights -> nothing to do')
        rap['etat'] = 'deja'
        return rap

    # ---- into the frame of the SOURCE skeleton (the red 000, the vanilla's)
    T = np.array([cib.bind[b] @ np.linalg.inv(src.bind[b]) for b in range(src.n)])
    identite = bool(np.allclose(T, np.eye(4)[None], atol=1e-6))

    def mixe(G, Q):
        """Per-vertex blend of the bone transforms T, weighted by the int16 weights."""
        W = np.where(Q > 0, Q, 0).astype(np.float64)
        W /= np.maximum(W.sum(1, keepdims=True), 1e-12)
        A = np.zeros((len(G), 4, 4))
        for k in range(4):
            A += W[:, k, None, None] * T[np.maximum(G[:, k], 0)]
        return A
    A0 = None if identite else mixe(G0, Q0)
    if identite:
        Pr = p
    else:
        Pr = np.linalg.solve(A0[:, :3, :3], (p - A0[:, :3, 3])[:, :, None])[:, :, 0]

    # ---- the finger weights
    G1, Q1 = G0.copy(), Q0.copy()
    source_poids = None
    if poids_de and os.path.isfile(poids_de):
        # WARNING: the .npz arrays are read ONCE. `z['G0']` on an NpzFile decompresses the whole
        # array again on EVERY access: in the per-vertex loop that was n decompressions of n
        # rows. Measured on bnd (463,012 vertices): 38 ms per vertex, about 5 h for the 001,
        # which looked frozen; 7.5 s for the whole winding_fix once read in one go. Same
        # comparisons as before: same result, byte for byte.
        with np.load(poids_de) as z:            # closed right away: Windows locks the .npz
            meme = str(z['cle']) == cle and z['G0'].shape == G0.shape
            if meme:
                zG0, zQ0, zG1, zQ1, ch = (np.array(z[k]) for k in ('G0', 'Q0', 'G1', 'Q1', 'change'))
        if meme:
            ok = True
            for i in range(n):
                if not (sorted(set(zG0[i][zQ0[i] > 0].tolist())) == sorted(set(G0[i][Q0[i] > 0].tolist()))):
                    ok = False
                    break
            if ok and np.abs(np.sort(zQ0, 1) - np.sort(Q0, 1)).max() <= 4:
                G1[ch], Q1[ch] = zG1[ch], zQ1[ch]
                source_poids = poids_de
                log('finger weights taken from %s (%d vertices): same topology, same base '
                    'weights -> LOD identical to the 000' % (os.path.basename(poids_de), int(ch.sum())))
        if source_poids is None:
            log('!! trace %s ignored (different topology or base weights): full computation'
                % os.path.basename(poids_de))
    if source_poids is None:
        Pv, Wv = lire_vanilla(vanilla_mesh, src.n)
        bouts = bouts_vanilla(src, Pv, Wv)
        tables = tables_vanilla(src, Pv, Wv, bouts)
        cumul = []
        for i in range(n):
            acc = {}
            for b, w in zip(G0[i], Q0[i]):
                if w > 0:
                    acc[int(b)] = acc.get(int(b), 0.0) + w / 32767.0
            cumul.append(acc)
        etiq = etiquettes_modele(os.path.dirname(os.path.abspath(entree)), p, log) if identite else None
        rap['doigts_du_rig'] = etiq is not None
        cumul, touche, rap['mains'] = poids_doigts(Pr, F, cumul, src, bouts, tables, log,
                                                   etiq_modele=etiq)
        for i in np.where(touche)[0]:
            g, q = quantifier(finaliser(cumul[i], src))
            if not meme_influence(g, q, G0[i], Q0[i]):
                G1[i], Q1[i] = g, q
    change = np.array([not meme_influence(G1[i], Q1[i], G0[i], Q0[i]) for i in range(n)])
    # an unchanged vertex keeps its original slots, in the same order (indices AND weights)
    G1[~change], Q1[~change] = G0[~change], Q0[~change]
    change_mains = change.copy()          # only these vertices may be re-posed
    # the trace keeps the result of the FINGERS step (before folding): a 001 redoes the same
    # deterministic folding, and does not take a folded bone for a finger to re-pose
    Gm, Qm = G1.copy(), Q1.copy()
    rap['sommets_doigts_modifies'] = int(change.sum())
    if not change.any():
        # nothing recognised (both hands refused): we do not rewrite an equivalent, we copy
        log('no finger weight changed -> file left as it is')
        if os.path.abspath(sortie) != os.path.abspath(entree):
            with open(sortie, 'wb') as f:
                f.write(m.raw)
        rap['etat'] = 'inchange'
        return rap

    # ---- palette: several sections (by reference) or folding (by index)
    replies = []
    if mode == 'index':
        G1, Q1, modif, replies = replier(G1, Q1, src, max_os, log)
        rap['os_replies'] = [src.noms[b] for b in replies]
        change = np.array([not meme_influence(G1[i], Q1[i], G0[i], Q0[i]) for i in range(n)])
        G1[~change], Q1[~change] = G0[~change], Q0[~change]
        masques, noms_sec = [np.ones(len(F), bool)], ['whole body']
    else:
        masques, noms_sec = decouper(F, G1, Q1, src, max_os, log)
    porte1 = palette_de(G1, Q1)
    rap['os_doigts_apres'] = sorted(src.noms[b] for b in doigts if b in porte1)
    hors_doigts = ~change
    rap['corps_inchange'] = bool(np.all(G1[hors_doigts] == G0[hors_doigts]) and
                                 np.all(Q1[hors_doigts] == Q0[hors_doigts]))

    # ---- re-pose (black suit) of only the vertices whose FINGER weights change
    L1 = L.copy()
    rap['reposes'] = 0
    arepose = change & change_mains
    if not identite and arepose.any():
        A1 = mixe(G1[arepose], Q1[arepose])
        A0c = A0[arepose]
        if reposer == 'auto':
            # difference between the bones involved: rotation of T_b . T_ref^-1 (red 001: < 0.1 deg)
            jeu = sorted({int(b) for b in np.concatenate([G0[arepose][Q0[arepose] > 0],
                                                         G1[arepose][Q1[arepose] > 0]])})
            ang = 0.0
            for b in jeu:
                ref = src.idx['bip01 %s hand' % (cote(src.noms[b]) or 'l')]
                R = (T[b] @ np.linalg.inv(T[ref]))[:3, :3]
                ang = max(ang, float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1)))))
            reposer = ang > 1.0
            log('re-pose: max difference between the bones involved %.2f deg -> %s'
                % (ang, 'YES (target skeleton differs from the red one)' if reposer
                   else 'no (target skeleton = the red one up to a frame)'))
        if reposer:
            D = A1 @ np.linalg.inv(A0c)
            po = _decl(corps[0], 0).offset
            pc = p[arepose]
            pn = np.einsum('nij,nj->ni', D[:, :3, :3], pc) + D[:, :3, 3]
            # WARNING: a near-identity Delta (weight sliding between two bones that move together,
            # hand and finger base of the black suit: same transform) must not make the bytes
            # shake by one LSB. Below 0.02 deg and 1/4 of a position step: bytes kept.
            ang = np.degrees(np.arccos(np.clip((np.trace(D[:, :3, :3], axis1=1, axis2=2) - 1) / 2,
                                               -1.0, 1.0)))
            reel = (ang >= 0.02) | (np.linalg.norm(pn - pc, axis=1) >= 0.25 / 512.0)
            idx = np.where(arepose)[0][reel]
            D, pc, pn = D[reel], pc[reel], pn[reel]
            qi = np.clip(np.rint(pn * 512.0), -32768, 32767).astype(np.int16)
            vieux = L1[idx, po:po + 6].copy().view('<i2').reshape(-1, 3)
            bouge = np.any(qi != vieux, axis=1)
            for usage in (3, 6, 7):
                o = _decl(corps[0], usage).offset
                v = vecteurs(corps[0], L1[idx], usage)
                w = np.einsum('nij,nj->ni', D[:, :3, :3], v)
                w /= np.maximum(np.linalg.norm(w, axis=1, keepdims=True), 1e-12)
                qv = _snorm(w)
                bouge |= np.any(qv != L1[idx, o:o + 6].copy().view('<i2').reshape(-1, 3), axis=1)
                L1[idx[bouge], o:o + 6] = qv[bouge].view(np.uint8).reshape(-1, 6)
            L1[idx[bouge], po:po + 6] = qi[bouge].view(np.uint8).reshape(-1, 6)
            rap['reposes'] = int(bouge.sum())
            dep = np.linalg.norm(pn - pc, axis=1) if len(pn) else np.zeros(1)
            rap['repose_max_mm'] = float(dep.max() * 1000.0)
            rap['repose_positions'] = int(np.any(qi != vieux, axis=1).sum())
            log('re-pose: %d vertices re-posed (%d moved, max %.1f mm; the others: normal '
                'only), everything else keeps its bytes'
                % (int(bouge.sum()), rap['repose_positions'], rap['repose_max_mm']))

    # ---- output sections
    oi, ow = _decl(corps[0], 2).offset, _decl(corps[0], 1).offset
    b0 = tuple(princ.mesh_offset) + (princ.sphere_radius,) + tuple(princ.mesh_bbox)
    if rap['reposes']:
        b0 = bornes_union(b0, positions(corps[0], L1))
    nouvelles = []
    sources = []
    for masque, nom in zip(masques, noms_sec):
        Fs = F[masque]
        ids = np.unique(Fs)
        remap = np.full(n, -1, np.int64)
        remap[ids] = np.arange(len(ids))
        pal = sorted(palette_de(G1, Q1, ids))
        if len(pal) > max_os:
            raise RuntimeError('section %s: %d bones > %d' % (nom, len(pal), max_os))
        pal_ecrite = pal + [pal[-1]] * max(0, 32 - len(pal))   # like the writer: at least 32 slots
        loc = {b: k for k, b in reversed(list(enumerate(pal_ecrite)))}
        R = L1[ids].copy()
        g, q = G1[ids], Q1[ids]
        li = np.zeros((len(ids), 4), np.uint8)
        for k in range(4):
            li[:, k] = [loc[int(b)] if w > 0 else 0 for b, w in zip(g[:, k], q[:, k])]
        R[:, oi:oi + 4] = li
        # unchanged vertex: its 4 original int16 weights, in the same order; otherwise the new ones
        R[:, ow:ow + 8] = np.where(change[ids, None], q, Q0[ids]).astype('<i2').view(np.uint8).reshape(-1, 8)
        nouvelles.append(dict(ref=princ.material_ref_serialized, palette=pal_ecrite, lignes=R,
                              faces=remap[Fs].reshape(-1), bornes=b0, decl=princ.decl,
                              stride=princ.vertex_stride,
                              prim=(4, 1) if princ.primitive_type == 5 else (princ.primitive_type, princ.primitive_unknown),
                              inc=(princ.unknown_30, princ.unknown_38, princ.unknown_40, princ.schema_unknown),
                              index_size=2 if len(ids) <= 0xFFFF else 4, nom=nom, os=len(pal)))
        sources.append(ids)
    # WARNING: a section with more than 65,535 vertices (dense model) comes out here with 32-bit
    # indices, which the game truncates. It is never delivered like that: winding_fix calls
    # decoupe_sections.py right after, which splits it (red) or refuses the mesh (black). Nothing
    # to do here.
    sorties = []
    places = False
    for s in m.sections:
        if s.index in i_corps:
            if not places:
                sorties += nouvelles
                places = True
        else:
            sorties.append(copie_section(m, s))
    for s in sorties:
        s['faces'] = np.asarray(s['faces']).reshape(-1)
    bornes_modele = None
    if rap['reposes']:
        bm = tuple(m.model_offset) + (m.sphere_radius,) + tuple(m.model_bbox)
        bornes_modele = bornes_union(bm, positions(corps[0], L1))
    octets = reecrire(m, sorties, None, bornes_modele)

    # ---- checks BEFORE writing anything
    tmp = sortie + '.tmp_mains'
    with open(tmp, 'wb') as f:
        f.write(octets)
    try:
        ctl = controler(tmp, m, i_corps, nouvelles, sources, F, L, L1, G1, Q1, change, src,
                        max_os, mode, princ, log)
    except Exception:
        os.remove(tmp)
        raise
    rap['controles'] = ctl
    if not all(v for k, v in ctl.items() if isinstance(v, bool)):
        os.remove(tmp)
        raise RuntimeError('check failed: %s' % {k: v for k, v in ctl.items() if v is False})
    os.replace(tmp, sortie)
    rap['sections_sortie'] = [(x['nom'], len(x['lignes']), x['os'], '0x%X' % x['ref']) for x in nouvelles]
    rap['taille'] = os.path.getsize(sortie)
    rap['etat'] = 'ecrit'
    if trace:
        np.savez_compressed(trace, cle=np.array(cle), G0=G0, Q0=Q0, G1=Gm, Q1=Qm,
                            change=change_mains)
        rap['trace'] = trace
    log('WROTE %s: %d section(s) %s, finger bones %d/30, %d bytes'
        % (os.path.basename(sortie), len(sorties),
           ' + '.join('%s %d vert./%d bones' % (x['nom'], len(x['lignes']), x['os']) for x in nouvelles),
           len(rap['os_doigts_apres']), rap['taille']))
    return rap


def canon(G, Q):
    """A vertex's influences in canonical (bone, weight) sorted form: for comparisons."""
    k = np.where(Q > 0, np.asarray(G, np.int64) * 65536 + Q, np.int64(1) << 40)
    return np.sort(k, axis=1)


def _cles_tri(T):
    """Key of a triangle up to rotation (the winding is kept)."""
    T = np.asarray(T, np.int64)
    r = np.argmin(T, axis=1)
    R = np.stack([T[np.arange(len(T)), (r + k) % 3] for k in range(3)], 1)
    return R[:, 0] * (1 << 42) + R[:, 1] * (1 << 21) + R[:, 2]


def controler(chemin, m_av, i_corps, nouvelles, sources, F, L0, L1, G1, Q1, change, sq, max_os,
              mode, princ, log=log_defaut):
    """("check") Re-read of the WRITTEN bytes, with the toolkit's reader. Any false boolean =
    refusal. The keys are French and kept (they appear in the log and in the report)."""
    m = fmt.parse_mesh(chemin)
    n = len(L0)
    c = {}
    c['relecture'] = (m.filename_hash == m_av.filename_hash and
                      m.skeleton_ref_serialized == m_av.skeleton_ref_serialized and
                      m.external_mesh_count == m_av.external_mesh_count and
                      m.raw[0x40:0x50] == m_av.raw[0x40:0x50])
    k0 = min(i_corps)
    neuves = m.sections[k0:k0 + len(nouvelles)]
    autres_av = [s for s in m_av.sections if s.index not in i_corps]
    autres = [s for i, s in enumerate(m.sections) if not k0 <= i < k0 + len(nouvelles)]
    c['autres_sections_a_l_octet'] = len(autres) == len(autres_av) and all(
        bytes(lignes(m, a)) == bytes(lignes(m_av, b)) and
        a.material_ref_serialized == b.material_ref_serialized and
        a.bone_palette == b.bone_palette and
        np.array_equal(faces_section(m, a), faces_section(m_av, b)) for a, b in zip(autres, autres_av))
    if mode == 'index':
        c['index_du_corps_garde'] = (k0 == princ.index and len(nouvelles) == 1 and
                                     len(m.sections) == len(m_av.sections))
    c['references_du_corps'] = all(s.material_ref_serialized == princ.material_ref_serialized
                                   for s in neuves)
    c['palettes_48'] = all(len(s.bone_palette) <= max_os for s in m.sections)
    vu = np.zeros(n, bool)
    lu = np.zeros((n, 4), np.int64)
    coherent = idx_ok = somme_ok = octets_ok = True
    tris = []
    for s, ids in zip(neuves, sources):
        R = lignes(m, s)
        f = faces_section(m, s)
        g, q = influences(m, s, R)
        oi = _decl(s, 2).offset
        idx_ok &= bool(np.all(R[:, oi:oi + 4].astype(np.int64) < len(s.bone_palette)))
        # WARNING: EXACT sum (32767) on the rewritten vertices. The kept vertices keep their
        # bytes: poids_depuis_vanilla rounds without fixing the sum (32766..32768 on 1,328
        # vertices of the installed red 000); we do not "repair" them on the quiet.
        sm = q.sum(1)
        somme_ok &= bool(np.all(q >= 0) and np.all(sm[change[ids]] == 32767) and
                         np.all(np.abs(sm - 32767) <= 2))
        octets_ok &= bool(np.array_equal(R[:, :40], L1[ids][:, :40]))
        tris.append(ids[f])
        k = canon(g, q)
        deja = vu[ids]
        coherent &= bool(np.array_equal(lu[ids][deja], k[deja]))
        lu[ids[~deja]] = k[~deja]
        vu[ids] = True
    tris = np.concatenate(tris)
    c['tous_les_sommets'] = bool(vu.all())
    c['triangles'] = len(tris) == len(F)
    c['triangles_identiques'] = bool(np.array_equal(np.sort(_cles_tri(tris)), np.sort(_cles_tri(F))))
    c['indices_dans_palette'] = idx_ok
    c['poids_somme_32767'] = somme_ok
    c['coutures_memes_poids'] = coherent
    c['octets_0_39_relus'] = octets_ok
    c['octets_0_39_hors_repose'] = bool(np.array_equal(L0[~change][:, :40], L1[~change][:, :40]))
    c['uv_couleurs_partout'] = bool(np.array_equal(L0[:, 8:16], L1[:, 8:16]))
    c['poids_relus'] = bool(np.array_equal(lu, canon(G1, Q1)))
    porte = set(np.unique(G1[Q1 > 0]).tolist())
    c['os_de_doigts'] = sum(1 for b in os_doigts(sq) if b in porte)
    c['sommets_ecrits'] = int(sum(s.vertex_count for s in neuves))
    c['couture_dupliquee'] = c['sommets_ecrits'] - n
    c['sections'] = [(s.vertex_count, len(set(s.bone_palette)), '0x%X' % s.material_ref_serialized)
                     for s in m.sections]
    log('checks: %s' % ', '.join('%s=%s' % (k, v) for k, v in c.items()))
    return c


# ------------------------------------------------------------------------------- hook
def apres_winding(chemin, log=log_defaut):
    """("after the winding") Called by winding_fix.py on every mesh delivered by the red and
    black chains.

    Acts only on the 4 player meshes (red / black, 000 / 001) PRODUCED BY THE STUDIO CHAIN (an
    `etape_poids.mesh` or `etape_chaine.mesh` next to it, or in `source/`): their weights come
    from the vanilla neighbourhood, and that is where the phalanges get lost. A Web of Shadows
    (RvB) export (original weights, `corrected/` folder) is never touched. Writes in place,
    after the checks."""
    m = fmt.parse_mesh(chemin)
    if m.filename_hash not in SQUELETTE_CIBLE:
        return None
    dossier = os.path.dirname(os.path.abspath(chemin))
    chaine = any(os.path.isfile(os.path.join(d, f))
                 for d in (dossier, os.path.join(dossier, 'source'))
                 for f in ('etape_poids.mesh', 'etape_chaine.mesh'))
    if not chaine:
        log('%s: not from the Studio chain (no etape_poids next to it) -> not touched'
            % os.path.basename(chemin))
        return None
    vm, sk = chemins_vanilla()
    if not (os.path.isfile(vm) and os.path.isfile(sk)):
        log('!! vanilla not found (%s): hands left as they are' % vm)
        return None
    poids_de = None
    if m.filename_hash in FRERE_000:
        t = os.path.join(dossier, FRERE_000[m.filename_hash] + '.mains.npz')
        poids_de = t if os.path.isfile(t) else None
    return traiter(chemin, chemin, vm, sk, None, poids_de, trace=chemin + '.mains.npz', log=log)


def main():
    ap = argparse.ArgumentParser(description='Fists that clench: the 30 finger bones.')
    ap.add_argument('entree')
    ap.add_argument('sortie')
    vm, sk = chemins_vanilla()
    ap.add_argument('--vanilla-mesh', default=vm)
    ap.add_argument('--skel', default=sk, help='SOURCE skeleton: the vanilla red 000\'s')
    ap.add_argument('--skel-cible', default='',
                    help='skeleton of the processed mesh. Empty = deduced from the hash (Studio\'s vanilla/)')
    ap.add_argument('--poids-de', default='',
                    help='.npz trace of the 000: a 001 takes EXACTLY its weights and its split')
    ap.add_argument('--trace', default='',
                    help='where to write the .npz trace (NEVER inside a mod\'s .apkf folder)')
    ap.add_argument('--max-os', type=int, default=MAX_OS)
    ap.add_argument('--forcer', action='store_true', help='process even if already processed')
    ap.add_argument('--mode', default='auto', choices=['auto', 'reference', 'index'])
    A = ap.parse_args()
    if not 1 <= A.max_os <= 48:
        ap.error('the engine accepts 1 to 48 bones per section')
    rap = traiter(A.entree, A.sortie, A.vanilla_mesh, A.skel, A.skel_cible or None,
                  A.poids_de or None, A.trace or None, A.max_os, A.forcer, A.mode)
    return 0 if rap.get('etat') in ('ecrit', 'deja', 'inchange') else 1


if __name__ == '__main__':
    sys.exit(main())
