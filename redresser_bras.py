# SPDX-License-Identifier: GPL-3.0-or-later
"""redresser_bras.py - put the arms of a model WITHOUT A SKELETON back into the vanilla bind pose.

("redresser les bras" = straighten the arms.) Where it sits: stage `bras` of sm3_convertir.py,
after `chaine` (and the optional `ajuster`), before the skinning stage `poids`. The converter
SKIPS it when the model was rigged and has already been conformed joint by joint to the game's
skeleton during `chaine` (tools/conformer_squelette.py poses the joints, then
tools/chaine_officielle.py writes the marker build/<mod>/conforme.json): its arms are then
already exactly in pose, and this script would only undo that.

The problem: the vanilla `ch_spiderman000` is in an A-pose, arms at about -36.6 degrees. An
imported model rarely has the same angle. Measured on the Free Fire Gojo, at equal x:

    x band         vanilla median y   Gojo median y
    0.30..0.45          +0.426            +0.205
    0.45..0.60          +0.295            -0.004
    0.60..0.75          +0.189            -0.105

Its arms hang 0.3 units lower. No proximity method can fix that: any weight transfer then binds
the forearm to finger bones. Nor can the bones be tilted to follow the model - the engine
computes `sum w * (current_bone * bind_bone^-1) * v`, so the GEOMETRY has to be in the bind pose,
or the model deforms from the first frame.

A rigged model is posed exactly by its own joints (see above; an earlier script, pose_liaison.py,
not distributed, did it with an armature). Here there is no armature: the vertices themselves
are rotated about the shoulder, with a blend so the shoulder does not break.

Reads:  --mesh (the model, .mesh), --vanilla (vanilla ch_spiderman000.mesh; its .skel must sit
        next to it, as in vanilla/CH_SPIDERMAN/..., to find the shoulders)
Writes: --out, the same file with positions, normals, tangents and binormals rewritten.

    python redresser_bras.py --mesh <in.mesh> --vanilla <vanilla 000.mesh> --out <out.mesh>

How the angle is found: the arm direction (shoulder -> farthest vertex) is compared with the
vanilla arm's; that first guess comes from ONE extreme vertex, so it is then refined by trying a
window of angles (--affiner, every 0.5 degree) and keeping the one whose arm surface sits closest
to the vanilla arm. Rotations larger than --max-angle are refused (probably a bad measurement).
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
from poids_par_segments import lire_skin, segments_depuis_vanilla  # noqa: E402
from sm3_sans_blender import fmt  # noqa: E402


def log(*x):
    print('[bras]', *x)


def axe_du_bras(P, signe, x_epaule):
    """Mean direction of the arm in the (x, height) plane, from the shoulder to the hand.

    `signe` is the side (-1 / +1 along x), `x_epaule` the |x| of the shoulder. Returns
    (direction vector or None if fewer than 20 vertices, selection mask of the arm vertices)."""
    sel = (P[:, 0] * signe) > x_epaule
    if sel.sum() < 20:
        return None, sel
    Q = P[sel]
    # The shoulder -> tip axis is used rather than a PCA: the PCA of a thick arm sometimes
    # follows its thickness when the arm is short.
    bout = Q[np.argmax(Q[:, 0] * signe)]
    orig = np.array([signe * x_epaule, np.median(Q[(Q[:, 0] * signe) < x_epaule + 0.06, 1])
                     if ((Q[:, 0] * signe) < x_epaule + 0.06).any() else Q[:, 1].max(), 0.0])
    v = bout - orig
    return v, sel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--vanilla', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--fondu', type=float, default=0.10,
                    help="width of the blend around the shoulder, in model units")
    ap.add_argument('--max-angle', type=float, default=45.0,
                    help='safeguard: above this angle, refuse to rotate (probably badly measured)')
    ap.add_argument('--affiner', type=float, default=25.0,
                    help='half-width, in degrees, of the refinement by distance to the vanilla arm. 0 = none')
    A = ap.parse_args()

    mv, Pv, Gv, Wv = lire_skin(A.vanilla)
    segs = segments_depuis_vanilla(Pv, Gv, Wv)
    sk = None
    # the shoulder = the start of the `upperarm` segment, side by side
    noms = {}
    for chemin in (A.vanilla.replace('0xAC92103D.ch_spiderman000.mesh',
                                     '0x461356AE.ch_spidermanskeleton_ch_spiderman000.skel'),):
        if os.path.exists(chemin):
            sk = fmt.parse_skeleton(chemin)
            noms = {b.index: b.name for b in sk.bones}
    x_ep = {}
    for b, (a, z) in segs.items():
        n = noms.get(b, '')
        if 'upperarm' in n:
            cote = -1 if ' l ' in n else 1
            x_ep[cote] = min(abs(a[0]), abs(z[0]))
    if not x_ep:
        raise SystemExit('shoulders not found: the vanilla .skel must be next to the vanilla .mesh')
    log('shoulders at |x| = %s' % {k: round(v, 3) for k, v in x_ep.items()})

    m = fmt.parse_mesh(A.mesh)
    d = bytearray(m.raw)
    for s in m.sections:
        if not s.vertex_count:
            continue
        dec = fmt.decode_section_vertices(m, s, uv_divisor=1000.0)
        P = np.array(dec['positions'], np.float64)
        N = np.array(dec['normals'], np.float64)
        T = np.array(dec['tangents'], np.float64)
        B = np.array(dec['binormals'], np.float64)
        P2, N2, T2, B2 = P.copy(), N.copy(), T.copy(), B.copy()

        for signe in (-1, 1):
            xe = x_ep.get(signe, x_ep[list(x_ep)[0]])
            vm, sel = axe_du_bras(P, signe, xe)
            vv, _ = axe_du_bras(Pv, signe, xe)
            if vm is None or vv is None:
                log('side %+d: not enough vertices, skipped' % signe)
                continue
            am = np.arctan2(vm[1], vm[0] * signe)
            av = np.arctan2(vv[1], vv[0] * signe)
            ang = av - am
            log('side %+d: %5d vertices | model %+.1f deg, vanilla %+.1f deg -> rotation %+.1f deg'
                % (signe, sel.sum(), np.degrees(am), np.degrees(av), np.degrees(ang)))
            if abs(np.degrees(ang)) > A.max_angle:
                log('   !! above %.0f deg, refused' % A.max_angle)
                continue

            pivot = np.array([signe * xe, np.median(P[sel & ((P[:, 0] * signe) < xe + 0.06), 1])
                              if (sel & ((P[:, 0] * signe) < xe + 0.06)).any()
                              else P[sel, 1].max(), 0.0])

            # ---- refinement: the rough angle comes from ONE extreme vertex (`axe_du_bras`), and a
            # protruding finger makes it lie. Measured on the Gojo: 2 degrees of error, but it
            # adds up along the arm -- clavicle 0.037 away from the vanilla, arm 0.105, hand
            # 0.143, i.e. more than the width of a hand. The hands then took the forearm's
            # weights. So no more guessing: a window of angles is tried and the one that sticks
            # best to the vanilla surface is kept.
            if A.affiner > 0:
                brasv = Pv[(Pv[:, 0] * signe) > xe]
                ech = P[sel]
                if len(ech) > 400:
                    ech = ech[np.random.default_rng(0).choice(len(ech), 400, replace=False)]
                tt = np.clip(((ech[:, 0] * signe) - xe) / max(A.fondu, 1e-6), 0.0, 1.0)
                tt = tt * tt * (3 - 2 * tt)

                def colle(essai):
                    # median distance from the rotated sample to the vanilla arm (lower = better)
                    cc, ss = np.cos(essai * tt), np.sin(essai * tt)
                    ex = ech[:, 0] - pivot[0]
                    ey = ech[:, 1] - pivot[1]
                    Q = np.column_stack([pivot[0] + ex * cc - ey * ss * signe,
                                         pivot[1] + ex * ss * signe + ey * cc,
                                         ech[:, 2]])
                    best = np.full(len(Q), np.inf)
                    for k in range(0, len(brasv), 4096):
                        bloc_v = brasv[k:k + 4096]
                        dd = np.linalg.norm(Q[:, None, :] - bloc_v[None, :, :], axis=2).min(1)
                        best = np.minimum(best, dd)
                    return float(np.median(best))

                grille = np.radians(np.arange(-A.affiner, A.affiner + 1e-9, 0.5))
                scores = [(colle(ang + g), g) for g in grille]
                sc0 = colle(ang)
                meilleur, g = min(scores)
                if abs(abs(np.degrees(g)) - A.affiner) < 0.26:
                    log('   !! the optimum is at the EDGE of the window (%+.1f deg): widen --affiner'
                        % np.degrees(g))
                if meilleur < sc0:
                    log('   refinement: %+.2f deg more | median distance to the vanilla %.4f -> %.4f'
                        % (np.degrees(g), sc0, meilleur))
                    ang = ang + g
                else:
                    log('   refinement: nothing better (median distance %.4f)' % sc0)
            # Blend: full rotation away from the shoulder and none before it, otherwise the
            # shoulder folds sharply and an edge shows.
            t = np.clip(((P[:, 0] * signe) - xe) / max(A.fondu, 1e-6), 0.0, 1.0)
            t = t * t * (3 - 2 * t)                     # cubic smoothstep
            t = np.where((P[:, 0] * signe) > xe, t, 0.0)
            c, sn = np.cos(ang * t), np.sin(ang * t)
            dx = P[:, 0] - pivot[0]
            dy = P[:, 1] - pivot[1]
            # rotation in the (x, height) plane, with opposite signs on the two sides
            rx = dx * c - dy * sn * signe
            ry = dx * sn * signe + dy * c
            bouge = t > 0
            P2[bouge, 0] = (pivot[0] + rx)[bouge]
            P2[bouge, 1] = (pivot[1] + ry)[bouge]
            for src, dst in ((N, N2), (T, T2), (B, B2)):
                ax = src[:, 0] * c - src[:, 1] * sn * signe
                ay = src[:, 0] * sn * signe + src[:, 1] * c
                dst[bouge, 0] = ax[bouge]
                dst[bouge, 1] = ay[bouge]

        # ---- re-encoding: positions as int16 x 512 (D3DDECLUSAGE 0), normal / tangent /
        # binormal (3, 6, 7) as int16 normalised to 32767
        bloc = np.frombuffer(bytes(d[s.vertex_buffer_offset:
                                     s.vertex_buffer_offset + s.vertex_count * s.vertex_stride]),
                             np.uint8).copy().reshape(s.vertex_count, s.vertex_stride)
        op = [dc.offset for dc in s.decl if dc.usage == 0][0]
        div = 512.0
        q = np.clip(np.rint(P2 * div), -32768, 32767).astype(np.int16)
        anc = bloc[:, op:op + 8].copy().view(np.int16)
        anc[:, :3] = q
        bloc[:, op:op + 8] = anc.view(np.uint8)
        for usage, V in ((3, N2), (6, T2), (7, B2)):
            o = [dc.offset for dc in s.decl if dc.usage == usage][0]
            n = V / np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-9)
            qq = np.clip(np.rint(n * 32767.0), -32768, 32767).astype(np.int16)
            a2 = bloc[:, o:o + 8].copy().view(np.int16)
            a2[:, :3] = qq
            bloc[:, o:o + 8] = a2.view(np.uint8)
        d[s.vertex_buffer_offset:s.vertex_buffer_offset + s.vertex_count * s.vertex_stride] = \
            bloc.tobytes()
        log('section %d: %d vertices re-encoded, bounds %s .. %s'
            % (s.index, s.vertex_count, np.round(P2.min(0), 3), np.round(P2.max(0), 3)))

    os.makedirs(os.path.dirname(os.path.abspath(A.out)) or '.', exist_ok=True)
    open(A.out, 'wb').write(bytes(d))
    log('WROTE %s' % A.out)

    # check: median height per x band, against the vanilla model
    mm = fmt.parse_mesh(A.out)
    P3 = np.concatenate([np.array(fmt.decode_section_vertices(mm, s, uv_divisor=1000.0)['positions'],
                                  np.float64) for s in mm.sections if s.vertex_count])
    log('median height per x band  (after | vanilla):')
    for lo, hi in ((0.30, 0.45), (0.45, 0.60), (0.60, 0.75)):
        a = P3[(P3[:, 0] > lo) & (P3[:, 0] <= hi)]
        b = Pv[(Pv[:, 0] > lo) & (Pv[:, 0] <= hi)]
        if len(a) and len(b):
            log('   x %.2f..%.2f: %+.3f | %+.3f' % (lo, hi, np.median(a[:, 1]), np.median(b[:, 1])))


if __name__ == '__main__':
    main()
