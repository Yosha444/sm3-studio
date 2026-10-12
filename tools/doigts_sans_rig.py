# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""doigts_sans_rig.py - pose the fingers of a model WITHOUT A RIG on the phalanges of the game's skeleton.

("doigts sans rig" = "fingers without a rig".)

THE DEFECT, MEASURED (2026-10-07, "some models still have broken fingers even after the patch")
---------------------------------------------------------------------------------------------
The five mods installed without a rig (Gojo, 2099, Miles, TASM, Brand) kept 0 to 20 finger bones
out of 30: `mains_poings` requires five separate finger pieces, posed like the vanilla, and left
the hand with proximity weights taken from several of the game's fingers -> broken fingers in a
fist. Labelling the fingers is not enough: those of an arbitrary model do not go through the
game's joints (offset, longer, spread differently). The fist then makes them pivot around axes
placed off target and they stretch into bars (seen on Brand and Miles).

THE FIX
-------
What the rig does for a rigged model (tools/conformer_squelette.py), we do here with the SHAPE
of the hand:
  1. the fingers are found as the BRANCHES of the hand (geodesic distance from the wrist,
     persistence segmentation: `mains_poings.branches_main`), whether they touch or not;
  2. each branch is matched to one of the game's fingers by its base and its tip;
  3. we measure the branch's joints (rings of vertices at the same fractions as the vanilla
     phalanges) and POSE each phalanx on the game's phalanx: rotation, stretch along the bone,
     blending at the joints and at the base of the finger (the palm does not move);
  4. a branch already FOLDED in the model (sculpted fist) is not touched: it will be attached to
     the hand, otherwise the game's fist would fold it a second time;
  5. we write `doigts_modele.npz` (finger of each vertex): `mains_poings` takes these fingers
     instead of guessing them, exactly as for a rigged model.
The weights are not touched here, nor any vertex outside the fingers.
For each hand, a simulated fist decides between "fingers posed" and "hand left as it is"
(arbitration, see traiter()).

Place in the chain: called by sm3_convertir.py after `poids`, before `lod` (so the 001 gets the
same posed fingers), only for a model without a rig. Skipped if the chain already conformed the
model through its own rig (conforme.json next to it).

    python tools/doigts_sans_rig.py --mesh <etape_poids.mesh> --out <etape_doigts.mesh>
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import struct
import sys

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))


def _mp():
    """mains_poings.py (next to this file), loaded once."""
    m = sys.modules.get('mains_poings')
    if m is None:
        s = importlib.util.spec_from_file_location('mains_poings', os.path.join(ICI, 'mains_poings.py'))
        m = importlib.util.module_from_spec(s)
        sys.modules['mains_poings'] = m
        s.loader.exec_module(m)
    return m


def log(*x):
    print('[doigts]', *x, flush=True)


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


DEPLACEMENT_MAX = 0.10      # beyond this, the branch is badly recognised: it is not posed (rigid)
COLLE = 0.008               # an unconnected piece within 8 mm of a finger follows that finger


def pose_poing(sq, angle=75.0):
    """4x4 matrices (rest -> fist) of every bone: each phalanx bent by `angle` degrees towards
    the palm (thumb at 60 %), like the game's resting fist. Used as a REFEREE, not as animation."""
    rot = {}
    for c in 'lr':
        h = sq.joint(sq.idx['bip01 %s hand' % c])
        nrm = np.cross(sq.joint(sq.idx['bip01 %s finger1' % c]) - h, sq.joint(sq.idx['bip01 %s finger4' % c]) - h)
        nrm /= max(np.linalg.norm(nrm), 1e-9)
        for D in range(5):
            ch = sq.chaine(c, D)
            for k in (1, 2, 3):
                a0 = sq.joint(ch[k])
                b0 = sq.joint(ch[k + 1]) if k < 3 else a0 + (a0 - sq.joint(ch[k - 1]))
                ax = np.cross(b0 - a0, nrm)
                ax /= max(np.linalg.norm(ax), 1e-9)
                ang = np.radians(angle * (0.6 if D == 0 else 1.0))
                K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
                R = np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * K @ K
                rot[ch[k]] = R
    T = [None] * sq.n

    def t(b):
        if T[b] is not None:
            return T[b]
        par = sq.parents.get(b, -1)
        M = np.eye(4) if par is None or par < 0 else t(par).copy()
        if b in rot:
            J = sq.joint(b)
            A = np.eye(4)
            A[:3, :3] = rot[b]
            A[:3, 3] = J - rot[b] @ J
            M = M @ A
        T[b] = M
        return M
    for b in range(sq.n):
        t(b)
    return np.array(T)


def dechirure(P, F, cumul, T, centre, rayon=0.18):
    """("tearing") 99th percentile of the stretch of the hand's edges in the fist
    (fist length / rest length)."""
    sel = np.linalg.norm(P - centre, axis=1) < rayon
    fs = F[sel[F].all(1)]
    if len(fs) < 10:
        return None
    ids = np.unique(fs)
    X = P.copy()
    for i in ids:
        acc = cumul[i]
        tot = sum(acc.values()) or 1.0
        Mx = sum((w / tot) * T[b] for b, w in acc.items()) if acc else np.eye(4)
        X[i] = (Mx @ np.r_[P[i], 1.0])[:3]
    E = np.concatenate([fs[:, [0, 1]], fs[:, [1, 2]], fs[:, [2, 0]]])
    l0 = np.linalg.norm(P[E[:, 0]] - P[E[:, 1]], axis=1)
    l1 = np.linalg.norm(X[E[:, 0]] - X[E[:, 1]], axis=1)
    ok = l0 > 1e-4
    return float(np.percentile(l1[ok] / l0[ok], 99))


def poser_branche(c, br, r, sq, bouts):
    """("pose a branch") One 4x4 matrix per node of the branch, or None if the branch is
    unusable. Returns (matrices, largest node displacement)."""
    D = br['doigt']
    nds = br['noeuds']
    u = r['u'][nds]
    Pn = r['Pn']
    _h, b0, b1, b2 = sq.chaine(c, D)
    pts = np.array([sq.joint(b0), sq.joint(b1), sq.joint(b2), bouts[(c, D)]])

    def V(x):
        """Point at parameter x along the vanilla finger (0 base .. 3 tip)."""
        k = int(np.clip(np.floor(x), 0, 2))
        return pts[k] + (x - k) * (pts[k + 1] - pts[k])
    u0 = float(u.min())
    us = [u0] + [x for x in (1.0, 2.0) if x > u0 + 0.15] + [3.0]
    # the model's joints on the branch: GAUSSIAN mean along the finger. A fixed window fell
    # between two rings of vertices on low-poly fingers (Brand: rings at u = 0.2 / 0.7 / 1.5 /
    # 2.6) -> "measurement impossible".
    M = []
    for uj in us:
        if uj >= 3.0:
            M.append(Pn[br['bout']])
            continue
        if uj == us[0]:
            M.append(np.asarray(br['base'], float))
            continue
        w = np.exp(-((u - uj) / 0.3) ** 2)
        if w.sum() < 0.5:
            return None
        M.append((Pn[nds] * w[:, None]).sum(0) / w.sum())
    T = []
    Rp = np.eye(3)
    for j in range(len(us) - 1):
        dm, dv = M[j + 1] - M[j], V(us[j + 1]) - V(us[j])
        if np.linalg.norm(dm) < 1e-5 or np.linalg.norm(dv) < 1e-5:
            return None
        R = rot_min(Rp @ dm, dv) @ Rp
        k = float(np.clip(np.linalg.norm(dv) / np.linalg.norm(dm), 0.6, 1.6))    # stretch, bounded
        d = dm / np.linalg.norm(dm)
        A = R @ (np.eye(3) + (k - 1.0) * np.outer(d, d))
        X = np.eye(4)
        X[:3, :3] = A
        X[:3, 3] = V(us[j]) - A @ M[j]
        T.append(X)
        Rp = R
    out = np.zeros((len(nds), 4, 4))
    for i, x in enumerate(u):
        j = int(np.searchsorted(us, x, side='right') - 1)
        j = int(np.clip(j, 0, len(T) - 1))
        Mx = T[j]
        if j > 0 and x < us[j] + 0.15:                 # blend at the segment's joint
            w = lisse((x - (us[j] - 0.15)) / 0.30)
            Mx = (1 - w) * T[j - 1] + w * T[j]
        elif j < len(T) - 1 and x > us[j + 1] - 0.15:
            w = lisse((x - (us[j + 1] - 0.15)) / 0.30)
            Mx = (1 - w) * T[j] + w * T[j + 1]
        wb = lisse((x - u0) / 0.35)                     # the finger's base stays attached to the palm
        out[i] = (1 - wb) * np.eye(4) + wb * Mx
    dep = np.linalg.norm(np.einsum('nij,nj->ni', out, np.c_[Pn[nds], np.ones(len(nds))])[:, :3] - Pn[nds], axis=1)
    return out, float(dep.max())


def traiter(entree, sortie):
    """("process") The whole job. Returns 'rig', 'inconnu' (unknown layout), 'rien' (nothing
    found) or 'ecrit' (written)."""
    mp = _mp()
    fmt = mp.fmt
    dossier = os.path.dirname(os.path.abspath(sortie))
    npz = os.path.join(dossier, 'doigts_modele.npz')
    if os.path.isfile(os.path.join(dossier, 'conforme.json')):
        log('model already conformed through its rig (conforme.json): fingers already posed -> nothing to do')
        if os.path.abspath(entree) != os.path.abspath(sortie):
            shutil.copy2(entree, sortie)
        return 'rig'
    if os.path.isfile(npz):
        os.remove(npz)                   # old sidecar from a previous conversion
    m = fmt.parse_mesh(entree)
    vraies = [s for s in m.sections if not mp.est_fantome(m, s)]
    princ = max(vraies, key=lambda s: s.vertex_count)
    corps = [s for s in vraies if s.material_ref_serialized == princ.material_ref_serialized
             and s.vertex_stride == princ.vertex_stride and mp.disposition_ok(s)]
    if not corps:
        log('!! unknown vertex layout: nothing to do')
        shutil.copy2(entree, sortie)
        return 'inconnu'
    Ls = [mp.lignes(m, s) for s in corps]
    L = np.concatenate(Ls)
    F, base = [], 0
    for s in corps:
        F.append(mp.faces_section(m, s) + base)
        base += s.vertex_count
    F = np.concatenate(F)
    G0, Q0 = map(np.concatenate, zip(*[mp.influences(m, s, l) for s, l in zip(corps, Ls)]))
    p = np.concatenate([mp.positions(s, l) for s, l in zip(corps, Ls)])
    n = len(p)
    vm, sk = mp.chemins_vanilla()
    sq = mp.Squelette(sk)
    Pv, Wv = mp.lire_vanilla(vm, sq.n)
    bouts = mp.bouts_vanilla(sq, Pv, Wv)
    grp, vois, debut = mp.graphe(p, F)
    ng = len(debut) - 1
    cumul = []
    for i in range(n):
        acc = {}
        for b, w in zip(G0[i], Q0[i]):
            if w > 0:
                acc[int(b)] = acc.get(int(b), 0.0) + w / 32767.0
        cumul.append(acc)
    # pieces of the mesh (connected components), so that only SEPARATE pieces get attached to a finger
    piece = np.full(ng, -1, np.int64)
    k = 0
    for s0 in range(ng):
        if piece[s0] >= 0:
            continue
        pile = [s0]
        piece[s0] = k
        while pile:
            x = pile.pop()
            for y in vois[debut[x]:debut[x + 1]]:
                if piece[y] < 0:
                    piece[y] = k
                    pile.append(int(y))
        k += 1
    delta_n = np.tile(np.eye(4), (ng, 1, 1))      # per node: pose matrix
    bouge_n = np.zeros(ng, bool)                  # per node: moved
    cote_n = np.full(ng, -1, np.int8)             # per node: side (0 left, 1 right)
    doigt_n = np.full(ng, -1, np.int8)            # per node: finger (-2 = attached to the hand)
    resume = []
    for c in 'lr':
        main = sq.idx['bip01 %s hand' % c]
        chaines = [sq.chaine(c, D) for D in range(5)]
        doigt_de_os = {b for ch in chaines for b in ch[1:]}
        zone = np.array([sum(w for b, w in acc.items() if b == main or b in doigt_de_os)
                         for acc in cumul]) > 0.5
        r = mp.branches_main(c, p, ng, grp, vois, debut, zone, sq, bouts, log)
        if r is None:
            continue
        for br in r['branches']:
            nds, D = br['noeuds'], br['doigt']
            cote_n[nds] = 0 if c == 'l' else 1
            if br.get('replie', br['droit'] < mp.REPLIE):
                doigt_n[nds] = -2
                resume.append('%s %s folded: attached to the hand' % (c.upper(), mp.NOMS_DOIGTS[D]))
                continue
            res = poser_branche(c, br, r, sq, bouts)
            if res is None or res[1] > DEPLACEMENT_MAX:
                doigt_n[nds] = -2
                resume.append('%s %s cannot be posed (%s): attached to the hand'
                              % (c.upper(), mp.NOMS_DOIGTS[D],
                                 'measurement impossible' if res is None else '%.0f mm' % (res[1] * 1000)))
                continue
            delta_n[nds] = res[0]
            bouge_n[nds] = True
            doigt_n[nds] = D
            resume.append('%s %s posed (tip moved by %.0f mm)' % (c.upper(), mp.NOMS_DOIGTS[D], res[1] * 1000))
        # WARNING: pieces NOT CONNECTED to the finger (web overlay, nail, glove modelled apart):
        # they belong to no branch, stayed with the hand while their finger bent, and floated
        # (loops and spikes seen on Brand). They take the label, the pose and the u of the nearest
        # finger node, within COLLE.
        lab_n = np.where(cote_n == (0 if c == 'l' else 1), doigt_n, -1)
        ref = np.where(lab_n != -1)[0]
        if len(ref):
            avec_doigt = np.isin(piece, np.unique(piece[ref]))
            pres = np.where((doigt_n == -1) & ~avec_doigt
                            & (np.linalg.norm(r['Pn'] - sq.joint(main), axis=1) < 0.3))[0]
            A = r['Pn'][ref]
            colles = 0
            for a0 in range(0, len(pres), 256):
                bloc = pres[a0:a0 + 256]
                d2 = ((r['Pn'][bloc][:, None, :] - A[None, :, :]) ** 2).sum(2)
                j = d2.argmin(1)
                ok = d2[np.arange(len(bloc)), j] < COLLE ** 2
                for x, y in zip(bloc[ok], ref[j[ok]]):
                    doigt_n[x], cote_n[x] = doigt_n[y], cote_n[y]
                    delta_n[x], bouge_n[x] = delta_n[y], bouge_n[y]
                    colles += 1
            if colles:
                resume.append('%s: %d nodes of unconnected pieces attached to their finger'
                              % (c.upper(), colles))
    for x in resume:
        log('  ' + x)
    if not (doigt_n != -1).any():
        log('no finger found: mesh left as it is, mains_poings will try the topology')
        shutil.copy2(entree, sortie)
        return 'rien'
    # ---- ARBITRATION: for each hand, the game's fist simulated on both variants -- fingers
    # posed (new mains_poings weights) or hand left alone (proximity weights) -- and the least
    # torn one is kept. Measured 2026-10-07: posing helped Miles on the left and degraded Gojo
    # (thumb pulled by 56 mm, neighbours folded): no fixed rule wins everywhere, the measurement
    # does.
    try:
        tables = mp.tables_vanilla(sq, Pv, Wv, bouts)
        Tp = pose_poing(sq)
        Dv0 = delta_n[grp]
        bv0 = bouge_n[grp]
        p_pose = p.copy()
        p_pose[bv0] = np.einsum('nij,nj->ni', Dv0[bv0], np.c_[p[bv0], np.ones(int(bv0.sum()))])[:, :3]
        co_v0, dg_v0 = cote_n[grp].astype(np.int64), doigt_n[grp].astype(np.int64)
        cumul_a = [dict(acc) for acc in cumul]
        cumul_a, _t, _r = mp.poids_doigts(p_pose, F, cumul_a, sq, bouts, tables, lambda *x: None,
                                          etiq_modele=(co_v0, dg_v0, 'doigts_sans_rig'))
        for c in 'lr':
            ci = 0 if c == 'l' else 1
            if not ((cote_n == ci) & (doigt_n != -1)).any():
                continue
            h = sq.joint(sq.idx['bip01 %s hand' % c])
            da = dechirure(p_pose, F, cumul_a, Tp, h)
            db = dechirure(p, F, cumul, Tp, h)
            if da is None or db is None:
                continue
            if da > db * 1.05:
                nds = np.where(cote_n == ci)[0]
                bouge_n[nds] = False
                delta_n[nds] = np.eye(4)
                doigt_n[nds] = -1
                log('  hand %s: simulated fist, fingers posed %.2f against hand left alone %.2f -> '
                    'hand LEFT ALONE (less torn)' % (c.upper(), da, db))
            else:
                log('  hand %s: simulated fist, fingers posed %.2f against hand left alone %.2f -> '
                    'fingers posed' % (c.upper(), da, db))
    except Exception as ex:
        log('!! fist arbitration impossible (%s): posed fingers kept' % ex)
    if not (doigt_n != -1).any():
        log('no hand kept: mesh left as it is, mains_poings will try the topology')
        shutil.copy2(entree, sortie)
        return 'rien'
    # ---- application: positions and vectors of the vertices of the posed fingers
    Dv = delta_n[grp]
    bv = bouge_n[grp]
    p2 = p.copy()
    p2[bv] = np.einsum('nij,nj->ni', Dv[bv], np.c_[p[bv], np.ones(int(bv.sum()))])[:, :3]
    s0 = corps[0]
    po = mp._decl(s0, 0).offset
    L1 = L.copy()
    qi = np.clip(np.rint(p2[bv] * 512.0), -32768, 32767).astype(np.int16)
    idx = np.where(bv)[0]
    L1[idx, po:po + 6] = qi.view(np.uint8).reshape(-1, 6)
    for usage in (3, 6, 7):          # NORMAL, TANGENT, BINORMAL: rotated, renormalised
        o = mp._decl(s0, usage).offset
        v = mp.vecteurs(s0, L[idx], usage)
        w = np.einsum('nij,nj->ni', Dv[bv][:, :3, :3], v)
        w /= np.maximum(np.linalg.norm(w, axis=1, keepdims=True), 1e-12)
        L1[idx, o:o + 6] = mp._snorm(w).view(np.uint8).reshape(-1, 6)
    raw = bytearray(m.raw)
    a0 = 0
    P_fin = mp.positions(s0, L1)
    for s, l in zip(corps, Ls):
        blk = L1[a0:a0 + len(l)]
        raw[s.vertex_buffer_offset:s.vertex_buffer_offset + blk.size] = blk.tobytes()
        # the section's bounds, enlarged if a finger sticks out of them
        b = struct.unpack_from('<8f', raw, s.info_offset)
        Ps = P_fin[a0:a0 + len(l)]
        nb = mp.bornes_union(tuple(b[:7]), Ps)
        if len(nb) == 7:
            nb = tuple(nb) + (b[7],)
        struct.pack_into('<8f', raw, s.info_offset, *nb)
        a0 += len(l)
    bm = struct.unpack_from('<8f', raw, 0x20)      # model bounds in the header
    nbm = mp.bornes_union(tuple(bm[:7]), P_fin)
    if len(nbm) == 7:
        nbm = tuple(nbm) + (bm[7],)
    struct.pack_into('<8f', raw, 0x20, *nbm)
    with open(sortie, 'wb') as f:
        f.write(bytes(raw))
    relu = fmt.parse_mesh(sortie)
    Pr = np.concatenate([mp.positions(s, mp.lignes(relu, s)) for s in relu.sections
                         if s.index in {x.index for x in corps}])
    co_v = cote_n[grp]
    dg_v = doigt_n[grp]
    # same keys as the chain's doigts_modele.npz (read by mains_poings.etiquettes_modele)
    np.savez(npz, P=Pr.astype(np.float32), cote=co_v, doigt=dg_v,
             part=np.where(dg_v != -1, 1.0, 0.0).astype(np.float32),
             zone=np.where(dg_v != -1, 1.0, 0.0).astype(np.float32), version=np.array(1),
             source=np.array('doigts_sans_rig'))
    dep = np.linalg.norm(Pr - p, axis=1)
    log('WROTE %s: %d vertices of posed fingers (median displacement %.1f mm, max %.1f mm); '
        'doigts_modele.npz for mains_poings' % (os.path.basename(sortie), int(bv.sum()),
                                                float(np.median(dep[bv])) * 1000 if bv.any() else 0,
                                                float(dep.max()) * 1000))
    return 'ecrit'


def main():
    ap = argparse.ArgumentParser(description='Pose the fingers of a rig-less model on the game\'s.')
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--out', required=True)
    A = ap.parse_args()
    traiter(A.mesh, A.out)


if __name__ == '__main__':
    main()
