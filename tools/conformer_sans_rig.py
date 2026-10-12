# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""conformer_sans_rig.py - put the arms and legs of a model WITHOUT A RIG on the game's skeleton.

("conformer sans rig" = "conform without a rig".)

THE DEFECT, MEASURED (2026-10-07)
---------------------------------
Without a rig, the chain only did: scale on the height, feet on feet, centring, then
`redresser_bras` (the ANGLE of the arm, not its length). Elbow, wrist, knee, ankle stayed where
the model had put them. Measured on the installed rig-less mods: the hand landed 5 to 10 cm away
from the game's, so that no finger method could work (the fist rotates the phalanges around the
GAME's joints); and the knees bent in the wrong place.

THE FIX
-------
What the rig does for a rigged model (tools/conformer_squelette.py), we do with the SHAPE:
  1. each limb is isolated (arm: beyond the shoulder; leg: below the crotch, on one side) -- the
     connected component that holds its end, among the vertices the chain's weights (transferred
     from the vanilla) assign to that limb's bones;
  2. its CENTRE LINE: geodesic distance from the cut, centroids per slice;
  3. the joints are placed on that line at the SAME FRACTIONS as the vanilla's, measured by the
     SAME algorithm on the vanilla (the method's biases cancel out);
  4. each segment is put on the game's segment (rotation, stretch along the bone), blended at
     the joints and at the cut (the shoulder and the hip do not jump);
  5. the FOOT stays flat: it only turns around the vertical and its sole is put back on the
     vanilla's (like conformer_squelette).
The head, the trunk and the weights are not touched.

Place in the chain: called by sm3_convertir.py in the `poids` stage, for a model without a rig,
after `redresser_bras` and the first weight transfer:
    python tools/conformer_sans_rig.py --mesh <etape_poids.mesh> --out <etape_membres.mesh>
On success it writes the marker conforme_sans_rig.json next to the output, and the converter
computes the weights again on the posed limbs; without the marker the converter keeps the
`redresser_bras` result. Skipped if the chain already conformed the model through its rig
(conforme.json). The marker's keys are French (bras = arm, jambe = leg).
"""
from __future__ import annotations

import argparse
import heapq
import importlib.util
import json
import os
import shutil
import struct
import sys

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))


def _mp():
    """mains_poings.py (next to this file), loaded once: mesh reading and helpers."""
    m = sys.modules.get('mains_poings')
    if m is None:
        s = importlib.util.spec_from_file_location('mains_poings', os.path.join(ICI, 'mains_poings.py'))
        m = importlib.util.module_from_spec(s)
        sys.modules['mains_poings'] = m
        s.loader.exec_module(m)
    return m


def log(*x):
    print('[membres]', *x, flush=True)


def rot_min(a, b):
    """Smallest rotation (3x3) taking direction a onto direction b (Rodrigues)."""
    a = a / max(np.linalg.norm(a), 1e-12)
    b = b / max(np.linalg.norm(b), 1e-12)
    v = np.cross(a, b)
    c = float(np.clip(a @ b, -1.0, 1.0))
    if c > 1 - 1e-12:
        return np.eye(3)
    if c < -1 + 1e-12:
        ax = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(ax) < 1e-6:
            ax = np.cross(a, [0.0, 1.0, 0.0])
        ax /= np.linalg.norm(ax)
        return 2 * np.outer(ax, ax) - np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K * (1.0 / (1.0 + c))


def lisse(t):
    """Smoothstep on [0, 1] ("lisse" = smooth)."""
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ------------------------------------------------------------------------------ geometry
PONT = 0.015                # two pieces closer than 1.5 cm to each other are connected ("bridge")


class Maillage:
    """A mesh as a graph of nodes (co-located vertices merged), with virtual bridges between
    nearby disjoint pieces ("maillage" = mesh)."""

    def __init__(self, P, F, mp):
        self.P = np.asarray(P, np.float64)
        self.grp, self.vois, self.debut = mp.graphe(self.P, F)
        self.ng = len(self.debut) - 1
        cnt = np.bincount(self.grp, minlength=self.ng).astype(np.float64)
        self.Pn = np.zeros((self.ng, 3))
        for k in range(3):
            self.Pn[:, k] = np.bincount(self.grp, weights=self.P[:, k], minlength=self.ng) / np.maximum(cnt, 1)

        self.ponts = self._ponts(PONT)

    def _ponts(self, r):
        """VIRTUAL edges between disjoint pieces of the mesh closer than r to each other: a hand
        modelled apart from its sleeve (Gojo), a shoe separate from the leg. Without them, the
        geodesic stops at the edge of the piece and the limb has no cut."""
        lab = np.full(self.ng, -1, np.int64)
        k = 0
        for s0 in range(self.ng):
            if lab[s0] >= 0:
                continue
            pile = [s0]
            lab[s0] = k
            while pile:
                x = pile.pop()
                for y in self.vois[self.debut[x]:self.debut[x + 1]]:
                    if lab[y] < 0:
                        lab[y] = k
                        pile.append(int(y))
            k += 1
        self.pieces = k
        ponts = {}
        if k <= 1:
            return ponts
        cle = np.floor(self.Pn / r).astype(np.int64)       # grid of cells of size r
        cases = {}
        for i, c in enumerate(map(tuple, cle)):
            cases.setdefault(c, []).append(i)
        for i in range(self.ng):
            cx, cy, cz = cle[i]
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for j in cases.get((cx + dx, cy + dy, cz + dz), ()):
                            if lab[j] != lab[i] and j > i and                                     np.linalg.norm(self.Pn[i] - self.Pn[j]) < r:
                                ponts.setdefault(i, []).append(j)
                                ponts.setdefault(j, []).append(i)
        return ponts

    def voisins(self, x):
        """Neighbours of node x, bridges included."""
        v = self.vois[self.debut[x]:self.debut[x + 1]]
        if x in self.ponts:
            return list(v) + self.ponts[x]
        return v

    def composante(self, masque, graine):
        """Nodes of the mask connected to the seed."""
        vu = np.zeros(self.ng, bool)
        if not masque[graine]:
            return vu
        pile = [int(graine)]
        vu[graine] = True
        while pile:
            x = pile.pop()
            for y in self.voisins(x):
                if masque[y] and not vu[y]:
                    vu[y] = True
                    pile.append(int(y))
        return vu

    def geodesique(self, region, sources):
        """Geodesic distance (Dijkstra on the edges) from the source nodes, inside the region."""
        g = np.full(self.ng, np.inf)
        tas = []
        for x in sources:
            g[x] = 0.0
            tas.append((0.0, int(x)))
        heapq.heapify(tas)
        while tas:
            d, x = heapq.heappop(tas)
            if d > g[x]:
                continue
            for y in self.voisins(x):
                if not region[y]:
                    continue
                nd = d + float(np.linalg.norm(self.Pn[x] - self.Pn[y]))
                if nd < g[y]:
                    g[y] = nd
                    heapq.heappush(tas, (nd, int(y)))
        return g


def membre(M, masque_coupe, extremite_score):
    """("limb") Isolate a limb: component (within `masque_coupe`) of the node that maximises
    `extremite_score`; cut = its nodes next to a node outside the mask. Returns (region, g, G,
    centre line (k,3), gl (k,)) or None. The centre line has 48 slices along the geodesic."""
    cand = np.where(masque_coupe)[0]
    if len(cand) < 30:
        return None
    bout = cand[np.argmax(extremite_score[cand])]
    reg = M.composante(masque_coupe, bout)
    if reg.sum() < 30:
        return None
    coupe = [x for x in np.where(reg)[0] if any(not reg[y] for y in M.voisins(x))]
    if not coupe:
        return None
    g = M.geodesique(reg, coupe)
    ok = reg & np.isfinite(g)
    G = float(g[ok].max())
    if G <= 1e-3:
        return None
    nb = 48
    ligne, gl = [], []
    for k in range(nb):
        a, b = G * k / nb, G * (k + 1) / nb
        sel = ok & (g >= a) & (g < b + (1e-9 if k == nb - 1 else 0))
        if sel.sum():
            ligne.append(M.Pn[sel].mean(0))
            gl.append((a + b) / 2)
    return ok, g, G, np.array(ligne), np.array(gl)


def point_ligne(ligne, gl, gq):
    """Point of the centre line at geodesic distance gq."""
    return np.array([np.interp(gq, gl, ligne[:, k]) for k in range(3)])


def fraction_sur_ligne(ligne, gl, G, J):
    """Fraction (0..1) of the point of the centre line nearest to J."""
    fins = np.linspace(0, G, 400)
    pts = np.stack([np.interp(fins, gl, ligne[:, k]) for k in range(3)], 1)
    return float(fins[np.argmin(np.linalg.norm(pts - J, axis=1))] / G)


def transformations_chaine(Mp, Vp, kmin=0.6, kmax=1.6):
    """Segments M[j]->M[j+1] put on V[j]->V[j+1]: one 4x4 per segment, chained rotations."""
    T = []
    Rp = np.eye(3)
    for j in range(len(Mp) - 1):
        dm, dv = Mp[j + 1] - Mp[j], Vp[j + 1] - Vp[j]
        if np.linalg.norm(dm) < 1e-5 or np.linalg.norm(dv) < 1e-5:
            return None
        R = rot_min(Rp @ dm, dv) @ Rp
        k = float(np.clip(np.linalg.norm(dv) / np.linalg.norm(dm), kmin, kmax))
        d = dm / np.linalg.norm(dm)
        A = R @ (np.eye(3) + (k - 1.0) * np.outer(d, d))
        X = np.eye(4)
        X[:3, :3] = A
        X[:3, 3] = Vp[j] - A @ Mp[j]
        T.append(X)
        Rp = R
    return T


def melange(f, fj, T, fondu=0.04, base=0.10):
    """("blend") Matrix per node from its fraction f along the limb; fj = fractions of the joints
    (len(T)+1 values). Linear blend around each joint, and from the identity at the cut."""
    out = np.zeros((len(f), 4, 4))
    for i, x in enumerate(f):
        j = int(np.clip(np.searchsorted(fj, x, side='right') - 1, 0, len(T) - 1))
        Mx = T[j]
        if j > 0 and x < fj[j] + fondu:
            w = lisse((x - (fj[j] - fondu)) / (2 * fondu))
            Mx = (1 - w) * T[j - 1] + w * T[j]
        elif j < len(T) - 1 and x > fj[j + 1] - fondu:
            w = lisse((x - (fj[j + 1] - fondu)) / (2 * fondu))
            Mx = (1 - w) * T[j] + w * T[j + 1]
        wb = lisse(x / base)
        out[i] = (1 - wb) * np.eye(4) + wb * Mx
    return out


# ------------------------------------------------------------------------------ limbs
BRAS = ('upperarm', 'forearm', 'hand')           # arm
JAMBE = ('thigh', 'calf', 'foot')                # leg
MAX_PIED = 1.12                                  # max height scaling of the foot (see conformer_squelette)


def os_du_membre(sq, c, quoi):
    """Bones of the limb `quoi` ('bras' = arm, otherwise leg) on side c."""
    if quoi == 'bras':
        motifs = ('bip01 %s upperarm' % c, 'bone %s upperarm split' % c, 'bip01 %s bone01' % c,
                  'bip01 %s forearm' % c, 'bip01 %s foretwist' % c, 'bip01 %s hand' % c,
                  'bip01 %s finger' % c, 'bip01 prop %s hand' % c)
    else:
        motifs = ('bip01 %s thigh' % c, 'bip01 %s calf' % c, 'bip01 %s foot' % c,
                  'bip01 %s toe0' % c, 'bip01 %s hip' % c)
    return [b for b in range(sq.n) if any(sq.noms[b].startswith(m) for m in motifs)]


def dominance_noeuds(M, dom):
    """Dominant bone of each node (from the per-vertex dominant bone)."""
    d = np.full(M.ng, -1, np.int64)
    d[M.grp] = dom
    return d


LONGUEUR_MIN, LONGUEUR_MAX = 0.70, 1.35   # limb length / the game's; outside that range we refuse
COUPE_MAX = 0.12                          # distance between the cuts (shoulder, hip) above which we refuse


def conformer_membres(Pm, Fm, Pv, Fv, sq, mp, dom_m, dom_v):
    """("conform the limbs") Returns (4x4 matrix per model VERTEX, mask of the moved vertices,
    report) or None. The limbs are isolated by the DOMINANCE of the weights (those the chain
    transferred from the vanilla): a geometric mask (beyond the shoulder) caught Brand's wide
    torso and Gojo's coat, and the "posed" arms exploded."""
    Mm, Mv = Maillage(Pm, Fm, mp), Maillage(Pv, Fv, mp)
    dnm, dnv = dominance_noeuds(Mm, dom_m), dominance_noeuds(Mv, dom_v)
    delta = np.tile(np.eye(4), (Mm.ng, 1, 1))
    bouge = np.zeros(Mm.ng, bool)
    rapport = {}
    sol = float(Pv[:, 1].min())              # the vanilla's sole height (Y up)
    for c, sg in (('l', -1.0), ('r', 1.0)):
        J = {nom: sq.joint(sq.idx['bip01 %s %s' % (c, nom)]) for nom in BRAS + JAMBE + ('toe0',)}
        # ---------------- arm: beyond the shoulder, on side c; end = the farthest in x

        ob = os_du_membre(sq, c, 'bras')
        rv = membre(Mv, np.isin(dnv, ob), Mv.Pn[:, 0] * sg)
        rm = membre(Mm, np.isin(dnm, ob), Mm.Pn[:, 0] * sg)
        refus = None                          # reason for refusing, for the log
        if rv is None or rm is None:
            refus = 'not found'
        else:
            okv, gv, Gv, lv, glv = rv
            okm, gm, Gm, lm, glm = rm
            ec = float(np.linalg.norm(point_ligne(lm, glm, 0.0) - point_ligne(lv, glv, 0.0)))
            if not LONGUEUR_MIN <= Gm / Gv <= LONGUEUR_MAX:
                refus = 'length %.0f mm for %.0f in the game' % (Gm * 1000, Gv * 1000)
            elif ec > COUPE_MAX:
                refus = 'shoulder %.0f mm from the game\'s' % (ec * 1000)
        if refus:
            log('!! %s arm refused (%s) -> redresser_bras' % (c.upper(), refus))
            rapport['bras_refuse'] = True
        else:
            # the CUT (shoulder) stays fixed: first point = start of the centre line, on both
            # sides; elbow, wrist and end of the hand are posed
            fj = [0.0] + [fraction_sur_ligne(lv, glv, Gv, J[n]) for n in ('forearm', 'hand')] + [1.0]
            fj = np.maximum.accumulate(np.clip(fj, 0.0, 1.0))
            Mp = [point_ligne(lm, glm, f * Gm) for f in fj]
            Vp = ([point_ligne(lv, glv, 0.0)] + [J[n] for n in ('forearm', 'hand')]
                  + [point_ligne(lv, glv, Gv)])
            T = transformations_chaine(Mp, Vp)
            if T is None:
                log('!! %s arm: degenerate segments -> not touched' % c.upper())
            else:
                nds = np.where(okm)[0]
                f = gm[nds] / Gm
                delta[nds] = melange(f, fj, T, base=0.10)
                bouge[nds] = True
                dep = [float(np.linalg.norm(Mp[k] - Vp[k])) * 1000 for k in range(len(Mp))]
                rapport['bras ' + c] = {'longueur_modele_mm': Gm * 1000, 'longueur_jeu_mm': Gv * 1000,
                                        'ecarts_articulations_mm': dep}
                log('%s arm: %d nodes, length %.0f mm (game %.0f); cut, elbow, wrist, end '
                    'moved by %s mm' % (c.upper(), len(nds), Gm * 1000, Gv * 1000,
                                        ', '.join('%.0f' % x for x in dep)))
        # ---------------- leg: below the crotch, on side c; end = the lowest, then the most forward

        oj = os_du_membre(sq, c, 'jambe')
        rv = membre(Mv, np.isin(dnv, oj), -Mv.Pn[:, 1] * 10 + Mv.Pn[:, 2])
        rm = membre(Mm, np.isin(dnm, oj), -Mm.Pn[:, 1] * 10 + Mm.Pn[:, 2])
        if rv is None or rm is None:
            log('!! %s leg not found -> not touched' % c.upper())
            continue
        okv, gv, Gv, lv, glv = rv
        okm, gm, Gm, lm, glm = rm
        ec = float(np.linalg.norm(point_ligne(lm, glm, 0.0) - point_ligne(lv, glv, 0.0)))
        if not LONGUEUR_MIN <= Gm / Gv <= LONGUEUR_MAX or ec > COUPE_MAX:
            log('!! %s leg refused (length %.0f mm for %.0f, hip %.0f mm away) -> not touched'
                % (c.upper(), Gm * 1000, Gv * 1000, ec * 1000))
            continue
        # the CUT (top of the thigh) stays fixed; knee and ankle are posed
        fj = [0.0] + [fraction_sur_ligne(lv, glv, Gv, J[n]) for n in ('calf', 'foot')]
        fj = np.maximum.accumulate(np.clip(fj, 0.0, 1.0))
        Mp = [point_ligne(lm, glm, f * Gm) for f in fj]
        Vp = [point_ligne(lv, glv, 0.0), J['calf'], J['foot']]
        # flat foot: height of the ankle above the sole
        nds = np.where(okm)[0]
        f = gm[nds] / Gm
        pied = nds[f >= fj[2]]
        up = np.array([0.0, 1.0, 0.0])
        sem = float(Mm.Pn[pied, 1].min()) if len(pied) else float(Mm.Pn[nds, 1].min())
        hm = float(Mp[2][1]) - sem
        hv = float(Vp[2][1]) - sol
        sv = float(np.clip(hv / hm, 1.0 / MAX_PIED, MAX_PIED)) if hm > 1e-3 else 1.0
        delta_p = hv - sv * hm
        Vp[2] = Vp[2] - delta_p * up
        T = transformations_chaine(Mp, Vp)
        if T is None:
            log('!! %s leg: degenerate segments -> not touched' % c.upper())
            continue
        # the foot: yaw only, towards the game's toe; height set for the sole
        bout_m = Mm.Pn[pied][np.argmax(Mm.Pn[pied, 2])] if len(pied) else Mp[2]
        fm = bout_m - Mp[2]
        fv = J['toe0'] - J['foot']
        fm[1] = 0.0
        fv[1] = 0.0
        R = rot_min(fm, fv) if np.linalg.norm(fm) > 1e-4 and np.linalg.norm(fv) > 1e-4 else np.eye(3)
        A = R @ (np.eye(3) + (sv - 1.0) * np.outer(up, up))
        Tp = np.eye(4)
        Tp[:3, :3] = A
        Tp[:3, 3] = Vp[2] - A @ Mp[2]
        T = T + [Tp]
        fj2 = list(fj) + [1.0]
        delta[nds] = melange(f, fj2, T, base=0.06)
        bouge[nds] = True
        dep = [float(np.linalg.norm(Mp[k] - Vp[k])) * 1000 for k in range(3)]
        rapport['jambe ' + c] = {'longueur_modele_mm': Gm * 1000, 'longueur_jeu_mm': Gv * 1000,
                                 'ecarts_articulations_mm': dep, 'pied_hauteur': sv,
                                 'pivot_cheville_abaisse_mm': delta_p * 1000}
        log('%s leg: %d nodes, length %.0f mm (game %.0f); cut, knee, ankle moved by '
            '%s mm; foot x%.2f in height, pivot lowered by %.0f mm'
            % (c.upper(), len(nds), Gm * 1000, Gv * 1000, ', '.join('%.0f' % x for x in dep), sv,
               delta_p * 1000))
    if not bouge.any():
        return None
    return delta[Mm.grp], bouge[Mm.grp], rapport


# ------------------------------------------------------------------------------ file
def lire_corps(m, mp):
    """The real body sections of a mesh (same material and layout as the largest one)."""
    vraies = [s for s in m.sections if not mp.est_fantome(m, s)]
    princ = max(vraies, key=lambda s: s.vertex_count)
    corps = [s for s in vraies if s.material_ref_serialized == princ.material_ref_serialized
             and s.vertex_stride == princ.vertex_stride and mp.disposition_ok(s)]
    return corps


def traiter(entree, sortie, vanilla_mesh=None):
    """("process") The whole job. Returns 'rig', 'echec' (failure, no marker) or 'ecrit'
    (written, marker conforme_sans_rig.json)."""
    mp = _mp()
    fmt = mp.fmt
    dossier = os.path.dirname(os.path.abspath(sortie))
    marque = os.path.join(dossier, 'conforme_sans_rig.json')
    if os.path.isfile(marque):
        os.remove(marque)
    if os.path.isfile(os.path.join(dossier, 'conforme.json')):
        log('model already conformed through its rig: nothing to do')
        shutil.copy2(entree, sortie)
        return 'rig'
    m = fmt.parse_mesh(entree)
    corps = lire_corps(m, mp)
    if not corps:
        log('!! unknown layout')
        return 'echec'
    Ls = [mp.lignes(m, s) for s in corps]
    L = np.concatenate(Ls)
    F, base = [], 0
    for s in corps:
        F.append(mp.faces_section(m, s) + base)
        base += s.vertex_count
    F = np.concatenate(F)
    p = np.concatenate([mp.positions(s, l) for s, l in zip(corps, Ls)])
    G0, Q0 = map(np.concatenate, zip(*[mp.influences(m, s, l) for s, l in zip(corps, Ls)]))
    dom_m = G0[np.arange(len(G0)), np.argmax(np.where(G0 >= 0, Q0, -1), axis=1)]
    vm, sk = mp.chemins_vanilla()
    vm = vanilla_mesh or vm
    sq = mp.Squelette(sk)
    mv = fmt.parse_mesh(vm)
    Pv, Fv, Dv0, b2 = [], [], [], 0
    for s in mv.sections:
        if mp.est_fantome(mv, s) or not s.vertex_count:
            continue
        lv = mp.lignes(mv, s)
        Pv.append(mp.positions(s, lv))
        Fv.append(mp.faces_section(mv, s) + b2)
        gv, qv = mp.influences(mv, s, lv)
        Dv0.append(gv[np.arange(len(gv)), np.argmax(np.where(gv >= 0, qv, -1), axis=1)])
        b2 += s.vertex_count
    Pv, Fv, dom_v = np.concatenate(Pv), np.concatenate(Fv), np.concatenate(Dv0)
    res = conformer_membres(p, F, Pv, Fv, sq, mp, dom_m, dom_v)
    if res is None:
        log('!! no limb conformed -> the redresser_bras result is kept')
        return 'echec'
    Dv, bv, rapport = res
    s0 = corps[0]
    po = mp._decl(s0, 0).offset
    idx = np.where(bv)[0]
    p2 = p.copy()
    p2[idx] = np.einsum('nij,nj->ni', Dv[idx], np.c_[p[idx], np.ones(len(idx))])[:, :3]
    L1 = L.copy()
    L1[idx, po:po + 6] = np.clip(np.rint(p2[idx] * 512.0), -32768, 32767).astype(np.int16).view(np.uint8).reshape(-1, 6)
    for usage in (3, 6, 7):          # NORMAL, TANGENT, BINORMAL: rotated, renormalised
        o = mp._decl(s0, usage).offset
        v = mp.vecteurs(s0, L[idx], usage)
        w = np.einsum('nij,nj->ni', Dv[idx][:, :3, :3], v)
        w /= np.maximum(np.linalg.norm(w, axis=1, keepdims=True), 1e-12)
        L1[idx, o:o + 6] = mp._snorm(w).view(np.uint8).reshape(-1, 6)
    raw = bytearray(m.raw)
    P_fin = mp.positions(s0, L1)
    a0 = 0
    for s, l in zip(corps, Ls):
        blk = L1[a0:a0 + len(l)]
        raw[s.vertex_buffer_offset:s.vertex_buffer_offset + blk.size] = blk.tobytes()
        # section bounds recomputed: centre, radius, half-box, last float kept
        Ps = P_fin[a0:a0 + len(l)]
        c = (Ps.min(0) + Ps.max(0)) / 2
        h = (Ps.max(0) - Ps.min(0)) / 2
        b = struct.unpack_from('<8f', raw, s.info_offset)
        struct.pack_into('<8f', raw, s.info_offset, *(tuple(c) + (float(np.linalg.norm(h)),) + tuple(h) + (b[7],)))
        a0 += len(l)
    c = (P_fin.min(0) + P_fin.max(0)) / 2
    h = (P_fin.max(0) - P_fin.min(0)) / 2
    bm = struct.unpack_from('<8f', raw, 0x20)       # model bounds in the header
    struct.pack_into('<8f', raw, 0x20, *(tuple(c) + (float(np.linalg.norm(h)),) + tuple(h) + (bm[7],)))
    with open(sortie, 'wb') as f:
        f.write(bytes(raw))
    fmt.parse_mesh(sortie)                       # read back
    rapport['bras_faits'] = not rapport.get('bras_refuse', False) and         all(('bras ' + c) in rapport for c in 'lr')
    with open(marque, 'w', encoding='utf-8') as f:
        json.dump(rapport, f, indent=1)
    log('WROTE %s: %d limb vertices posed on the game\'s skeleton (max displacement %.0f mm)'
        % (os.path.basename(sortie), len(idx), float(np.linalg.norm(p2 - p, axis=1).max()) * 1000))
    return 'ecrit'


def main():
    ap = argparse.ArgumentParser(description='Pose the arms and legs of a rig-less model on the game\'s skeleton.')
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--vanilla', default='')
    A = ap.parse_args()
    traiter(A.mesh, A.out, A.vanilla or None)      # failure = no marker: the converter keeps the redresser_bras result


if __name__ == '__main__':
    main()
