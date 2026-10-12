# SPDX-License-Identifier: GPL-3.0-or-later
"""poids_par_segments.py - redo the skinning of a .mesh by distance to bone SEGMENTS.

("poids par segments" = weights by segments.) Where it sits: stage `poids` of sm3_convertir.py
when --methode-poids segments is chosen (the "segments" method of the Skinning tab, kept for
comparison). The default method is poids_depuis_vanilla.py, which copies the game's own weights;
it imports lire_skin(), _cote() and _sauts() from this file, and so do redresser_bras.py and the
converter's final check.

Why it was written: the spatial transfer of the conversion chain (Blender's Data Transfer,
nearest surface) assumes the model and the vanilla body overlap. As soon as an arm span
differs, it slips. Measured on the converted Gojo: the vertices at |x| > 0.45 went 44 % to
`finger01` and 28 % to `finger4`, where the vanilla model has 34 % on `foretwist1` and 18 % on
`foretwist`. In game, the arms collapse.

The fix: weight by the distance to a bone SEGMENT, not to a surface. A shorter arm then still
falls on shoulder -> forearm -> hand along its own length.

The segments are NOT read from the .skel - its inverse bind matrix convention would have to be
guessed. They are derived from the **vanilla skinning itself**: for each bone, the vanilla
vertices it dominates, then their main axis clamped to their extent. No convention to assume,
and it checks itself: a bone without vertices has no segment and is not used.

Reads:  --mesh (model to re-skin), --vanilla (vanilla ch_spiderman000.mesh), --skel (vanilla
        skeleton: bone names for the exclusions, hierarchy for the safeguards)
Writes: --out, the same file with BLENDINDICES / BLENDWEIGHT bytes and bone palettes rewritten.

    python poids_par_segments.py --mesh <to_reskin.mesh> --vanilla <vanilla 000.mesh>
            --out <output.mesh> [--max-os 48] [--k 4] [--puissance 2.0]

Vertex format reminders (D3DDECLUSAGE): 1 = BLENDWEIGHT, 4 x int16 normalised to 32767 (SHORT4N);
2 = BLENDINDICES, 4 x uint8 indices INTO THE SECTION PALETTE; the palette itself is an array of
uint16 global bone indices at `bone_palette_pointer_serialized`.

French names: os = bone(s), poids = weights, puissance = power (exponent p of 1/d^p), part mini =
minimum share, sauts = hops (edges between two bones in the skeleton tree), cote = side
('l' / 'r', from the bone name), exclure = exclude.
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
    print('[poids]', *x)


def lire_skin(chemin):
    """Positions, GLOBAL bone indices and weights of all sections, concatenated (French: "read
    the skin"). Returns (parsed mesh, P (n,3), G (n,4) global bone indices, W (n,4) weights)."""
    m = fmt.parse_mesh(chemin)
    P, G, W = [], [], []
    for s in m.sections:
        if not s.vertex_count:
            continue
        d = fmt.decode_section_vertices(m, s, uv_divisor=1000.0)
        pal = list(s.bone_palette or [0])
        j = np.array(d['blend_indices'], np.int64)
        g = np.array([[pal[k] if k < len(pal) else 0 for k in ligne] for ligne in j], np.int64)
        P.append(np.array(d['positions'], np.float64))
        G.append(g)
        W.append(np.array(d['blend_weights'], np.float64))
    return m, np.concatenate(P), np.concatenate(G), np.concatenate(W)


def segments_depuis_vanilla(P, G, W, seuil=0.3, part_mini=0.001):
    """One segment per bone: main axis of the vertices it dominates, clamped to their extent.

    Only the bones the vanilla model REALLY uses are kept. `bip01 neck` dominates only 0.022 %
    of its vertices (12 out of 55,180): its segment, fitted on almost nothing, went up into the
    head and took 13 % of the skull. In game, the head stretches between `head` and `neck`.
    But the threshold must not be too high either: at 0.5 % `bip01 thigh` (0.373 %) was dropped
    too and the THIGHS fell on `calf`, whose segment covers the whole leg - legs offset in game.
    The gap between `neck` (0.022 %) and the next bone (0.123 %) is wide: **0.1 % falls inside**
    and keeps the 61 useful bones.

    Returns {bone index: (segment start, segment end)}."""
    dom = G[np.arange(len(P)), W.argmax(1)]
    u, c = np.unique(dom, return_counts=True)
    part = dict(zip(u.tolist(), (c / len(P)).tolist()))
    segs = {}
    for b in np.unique(G):
        if part.get(int(b), 0.0) < part_mini:
            continue
        m = np.zeros(len(P), bool)
        for c2 in range(G.shape[1]):
            m |= (G[:, c2] == b) & (W[:, c2] >= seuil)
        if m.sum() < 12:
            continue
        Q = P[m]
        c0 = Q.mean(0)
        # main axis
        u, s, vt = np.linalg.svd(Q - c0, full_matrices=False)
        axe = vt[0]
        t = (Q - c0) @ axe
        segs[int(b)] = (c0 + axe * t.min(), c0 + axe * t.max())
    return segs


def _cote(n):
    """Side of a bone from its name: "bip01 l calf" -> 'l'. Empty for central bones (pelvis,
    spine, head). The returned values 'l' / 'r' / '' are compared elsewhere: keep them."""
    return 'l' if ' l ' in n else ('r' if ' r ' in n else '')


def _sauts(parents, a, b):
    """Number of edges between two bones in the skeleton hierarchy (99 if unrelated)."""
    if a == b:
        return 0

    def chaine(x):
        c = []
        while x is not None and x >= 0 and x not in c:
            c.append(x)
            x = parents.get(x, -1)
        return c

    ca, cb = chaine(a), chaine(b)
    for i, x in enumerate(ca):
        if x in cb:
            return i + cb.index(x)
    return 99


def distance_segments(P, A, B):
    """Distance from each point to each segment [A_i, B_i]. Shape (n, m)."""
    AB = B - A                                    # (m, 3)
    L2 = np.einsum('ij,ij->i', AB, AB)
    L2 = np.where(L2 < 1e-12, 1.0, L2)
    AP = P[:, None, :] - A[None, :, :]            # (n, m, 3)
    t = np.clip(np.einsum('nmj,mj->nm', AP, AB) / L2, 0.0, 1.0)
    proj = A[None, :, :] + t[:, :, None] * AB[None, :, :]
    return np.linalg.norm(P[:, None, :] - proj, axis=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--vanilla', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-os', type=int, default=48)
    ap.add_argument('--k', type=int, default=4, help='influences per vertex (the format holds 4)')
    ap.add_argument('--puissance', default='auto',
                    help="'auto' (default) calibrates p so that the median dominant weight equals "
                         "the vanilla one. Skinning that is TOO SHARP (p too large) makes "
                         "joints bend sharply and volumes swell: the \"slightly deformed "
                         "everywhere\" look. A number forces p.")
    ap.add_argument('--puissance-fixe', type=float, default=0.0,
                    help="weights in 1/d^p. Calibrated on the vanilla model: p=3 reproduces its "
                         "median dominant weight (0.66), p=6 its number of influences (2.76). 4 is "
                         "the compromise. (Unused: --puissance decides.)")
    ap.add_argument('--part-mini', type=float, default=0.001,
                    help='minimum share of the vanilla vertices a bone must dominate to be used')
    ap.add_argument('--skel', default='', help='bone names: report AND exclusions')
    ap.add_argument('--sauts-max', type=int, default=4,
                    help="largest hierarchy gap between the dominant bone of a vertex and its "
                         "other influences, in skeleton edges. Measured on the "
                         "vanilla model: median 2, MAX 5. Beyond that, two distant bones pull the same "
                         "vertex and the limb stretches as soon as the animation separates them.")
    ap.add_argument('--melange-cotes', action='store_true',
                    help="allow a vertex to be influenced by a LEFT and a RIGHT bone. "
                         "The vanilla model does it on only 0.23 %% of its vertices; without this safeguard "
                         "we had 32.6 %%, and the limbs became rubbery in game.")
    ap.add_argument('--lisser', type=int, default=24,
                    help='rounds of topological repair (see poids_depuis_vanilla.reparer). '
                         '0 = none. Only touches the vertices that contradict their neighbours.')
    ap.add_argument('--exclure', default='finger,sync,pivot,nub',
                    help="bone name patterns NOT to use. The fingers are the trap: they are "
                         "many and close together, they take over the palette and push out `foretwist`, "
                         "on which the whole vanilla forearm rests.")
    A = ap.parse_args()

    mv, Pv, Gv, Wv = lire_skin(A.vanilla)
    segs = segments_depuis_vanilla(Pv, Gv, Wv, part_mini=A.part_mini)
    noms, parents = {}, {}
    if A.skel and os.path.exists(A.skel):
        _sk = fmt.parse_skeleton(A.skel)
        noms = {b.index: b.name for b in _sk.bones}
        parents = {b.index: b.parent_index for b in _sk.bones}
    else:
        log('!! without --skel, neither the name exclusions nor the safeguards apply')
    log('%d bones with a usable segment (out of %d in the vanilla model)'
        % (len(segs), len(np.unique(Gv))))

    motifs = [x.strip().lower() for x in A.exclure.split(',') if x.strip()]
    if motifs and noms:
        avant = len(segs)
        segs = {b: v for b, v in segs.items()
                if not any(mo in noms.get(b, '').lower() for mo in motifs)}
        log('exclusions %s: %d bones dropped, %d left' % (motifs, avant - len(segs), len(segs)))

    os_ids = sorted(segs)
    SA = np.array([segs[b][0] for b in os_ids])
    SB = np.array([segs[b][1] for b in os_ids])
    lg = np.linalg.norm(SB - SA, axis=1)
    log('segment length: median %.3f, max %.3f' % (np.median(lg), lg.max()))

    m = fmt.parse_mesh(A.mesh)
    d = bytearray(m.raw)
    total = 0
    for s in m.sections:
        if not s.vertex_count:
            continue
        dec = fmt.decode_section_vertices(m, s, uv_divisor=1000.0)
        P = np.array(dec['positions'], np.float64)
        D = distance_segments(P, SA, SB)
        ordre = np.argsort(D, axis=1)[:, :A.k]
        dist = np.take_along_axis(D, ordre, 1)

        def poids(p):
            x = 1.0 / np.power(np.maximum(dist, 1e-4), p)
            return x / x.sum(1, keepdims=True)

        if str(A.puissance).lower() == 'auto':
            # Aim at the MEDIAN dominant weight of the vanilla model. Too sharp = joints that
            # bend sharply and swollen volumes; too soft = limbs that melt. Binary search: the
            # sharpness grows with p, so the function is monotonic.
            Wv2 = Wv / np.maximum(Wv.sum(1, keepdims=True), 1e-9)
            cible = float(np.median(Wv2.max(1)))
            lo, hi = 0.5, 12.0
            for _ in range(24):
                mid = (lo + hi) / 2
                if float(np.median(poids(mid).max(1))) < cible:
                    lo = mid
                else:
                    hi = mid
            pw = (lo + hi) / 2
            log('calibrated power: %.2f  (median dominant %.3f, vanilla %.3f)'
                % (pw, float(np.median(poids(pw).max(1))), cible))
        else:
            pw = float(A.puissance)
        w = poids(pw)

        # Same repair as in `poids_depuis_vanilla`: the distance to segments goes wrong at the
        # same places as the distance to vertices - where two limbs touch. The model's TOPOLOGY
        # never links a thigh to a finger. So it is corrected here, BEFORE the safeguards, so
        # that they work on weights that are already consistent.
        # Local import: `poids_depuis_vanilla` already imports this module, an import at the top
        # of the file would be circular.
        if noms and A.lisser:
            try:
                faces = fmt.indices_to_faces(fmt.read_indices(m, s), s.primitive_type,
                                             s.vertex_count)
            except Exception as e:
                faces = []
                log('no readable index buffer (%s): topological repair skipped' % e)
            if faces:
                from poids_depuis_vanilla import reparer as _reparer
                _po = {b: j for j, b in enumerate(os_ids)}
                _gl = np.array(os_ids)[ordre]
                cumul = [{int(b): float(x) for b, x in zip(_gl[i], w[i]) if x > 1e-6}
                         for i in range(len(P))]
                cumul, _a, _b = _reparer(P, faces, cumul, noms, parents, A.sauts_max,
                                         A.lisser, log)
                for i, acc in enumerate(cumul):
                    top = sorted(((v, b) for b, v in acc.items() if b in _po),
                                 reverse=True)[:w.shape[1]]
                    if not top:
                        continue
                    tt = sum(v for v, _ in top) or 1.0
                    w[i] = 0.0
                    for c, (v, b) in enumerate(top):
                        ordre[i, c] = _po[b]
                        w[i, c] = v / tt

        # ------------------------------------------------------------ safeguards
        # Weighting by distance alone ignores the SKELETON. Two distant bones can pull the same
        # vertex, and the limb stretches as soon as the animation separates them: the "rubbery
        # arms and legs when he moves, clean at rest".
        # Measured before the safeguards: 32.57 % of the vertices mixed left and right
        # (vanilla 0.23 %) and 27.8 % linked bones more than 3 edges apart (vanilla 13.9 %).
        if noms:
            glob0 = np.array(os_ids)[ordre]
            dominant = glob0[np.arange(len(P)), w.argmax(1)]
            garde = np.ones(w.shape, bool)
            cotes = np.array([_cote(noms.get(int(b), '')) for b in glob0.ravel()]).reshape(
                glob0.shape)
            for i in range(len(P)):
                bd = int(dominant[i])
                # SIDE rule, absolute: a vertex cannot carry both a left and a right bone.
                # Comparing only with the dominant bone was not enough - when that one is
                # central (`pelvis`, `spine`) the filter did not apply and 27 % of the vertices
                # stayed mixed. The heavier side is kept.
                if not A.melange_cotes:
                    pg = float(w[i][cotes[i] == 'l'].sum())
                    pd = float(w[i][cotes[i] == 'r'].sum())
                    if pg > 0 and pd > 0:
                        perdant = 'r' if pg >= pd else 'l'
                        garde[i][cotes[i] == perdant] = False
                for c in range(w.shape[1]):
                    b2_ = int(glob0[i, c])
                    if b2_ != bd and _sauts(parents, bd, b2_) > A.sauts_max:
                        garde[i, c] = False
            w = np.where(garde, w, 0.0)
            s_ = w.sum(1, keepdims=True)
            # a vertex must not end up with zero weight: give it back its dominant bone
            vide = (s_[:, 0] <= 1e-12)
            if vide.any():
                w[vide] = 0.0
                w[vide, np.argmax(np.where(garde[vide], 1, 0), axis=1)] = 1.0
                s_ = w.sum(1, keepdims=True)
            w = w / np.maximum(s_, 1e-12)
            log('safeguards: %d influence(s) dropped out of %d (%.1f %%)'
                % (int((~garde).sum()), garde.size, 100 * (~garde).mean()))

        # EXACTLY the number of slots already present is kept: the palette is an array at a
        # fixed offset in the file, growing it would shift everything after it.
        nslots = len(s.bone_palette or [])
        maxos = min(A.max_os, nslots) if nslots else A.max_os
        # palette: keep at most maxos bones, the most used ones
        glob = np.array(os_ids)[ordre]
        poids_par_os = {}
        for b, ww in zip(glob.ravel(), w.ravel()):
            poids_par_os[int(b)] = poids_par_os.get(int(b), 0.0) + float(ww)
        pal = sorted(sorted(poids_par_os, key=poids_par_os.get, reverse=True)[:maxos])
        gard = {b: i for i, b in enumerate(pal)}
        log('section %d: %d vertices, %d bones kept out of %d proposed (%d slots available)'
            % (s.index, s.vertex_count, len(pal), len(poids_par_os), nslots))

        # Influences that fell outside the palette are SHARED OUT again, not thrown away:
        # otherwise a vertex can end up with zero weight and fly to the origin.
        loc = np.zeros_like(ordre)
        wf = np.zeros_like(w)
        for i in range(len(P)):
            paires = [(gard[int(b)], float(x)) for b, x in zip(glob[i], w[i]) if int(b) in gard]
            if not paires:
                j = int(np.argmin([np.linalg.norm(P[i] - (SA[os_ids.index(b)] + SB[os_ids.index(b)]) / 2)
                                   for b in pal]))
                paires = [(j, 1.0)]
            t = sum(x for _, x in paires)
            for c, (bi, x) in enumerate(paires[:A.k]):
                loc[i, c] = bi
                wf[i, c] = x / t

        bloc = np.frombuffer(bytes(d[s.vertex_buffer_offset:
                                     s.vertex_buffer_offset + s.vertex_count * s.vertex_stride]),
                             np.uint8).copy().reshape(s.vertex_count, s.vertex_stride)
        # D3DDECLUSAGE: 1 = BLENDWEIGHT, 2 = BLENDINDICES. (They were once swapped here.)
        ow = [dc.offset for dc in s.decl if dc.usage == 1][0]     # BLENDWEIGHT  (SHORT4N, 8 bytes)
        oi = [dc.offset for dc in s.decl if dc.usage == 2][0]     # BLENDINDICES (UBYTE4,  4 bytes)
        bloc[:, oi:oi + 4] = np.clip(loc, 0, 255).astype(np.uint8)
        q = np.clip(np.rint(wf * 32767.0), 0, 32767).astype(np.int16)
        bloc[:, ow:ow + 8] = q.view(np.uint8).reshape(s.vertex_count, 8)
        d[s.vertex_buffer_offset:s.vertex_buffer_offset + s.vertex_count * s.vertex_stride] = \
            bloc.tobytes()

        # The palette is an array of **u16** (checked: the bytes at 0xB8 read as u32 give
        # 65536, 196610... i.e. the pairs 0,1 / 2,3 / 4,5 of the parsed palette), at the LOCAL
        # offset `bone_palette_pointer_serialized`.
        import struct
        for i in range(nslots):
            struct.pack_into('<H', d, s.bone_palette_pointer_serialized + i * 2,
                             pal[i] if i < len(pal) else pal[-1])
        total += s.vertex_count

    os.makedirs(os.path.dirname(os.path.abspath(A.out)) or '.', exist_ok=True)
    open(A.out, 'wb').write(bytes(d))
    log('WROTE %s (%d vertices re-skinned)' % (A.out, total))

    # ---- report: dominant bone per zone, compared with the vanilla model
    mm, P2, G2, W2 = lire_skin(A.out)
    dom = G2[np.arange(len(P2)), W2.argmax(1)]
    domv = Gv[np.arange(len(Pv)), Wv.argmax(1)]
    for lab, f in (('left arm  x<-0.45', lambda p: p[:, 0] < -0.45),
                   ('right arm x>+0.45', lambda p: p[:, 0] > 0.45),
                   ('legs      y<-0.5', lambda p: p[:, 1] < -0.5)):
        for nom2, PP, DD in (('  ours   ', P2, dom), ('  vanilla', Pv, domv)):
            sel = f(PP)
            if not sel.any():
                continue
            u, c = np.unique(DD[sel], return_counts=True)
            top = sorted(zip(c.tolist(), u.tolist()), reverse=True)[:3]
            log('%s %-20s %s' % (nom2, lab,
                ' | '.join('%s %d%%' % (noms.get(b, b), 100 * n // sel.sum()) for n, b in top)))


if __name__ == '__main__':
    main()
