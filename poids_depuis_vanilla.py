# SPDX-License-Identifier: GPL-3.0-or-later
"""poids_depuis_vanilla.py - take Treyarch's REAL weights instead of inventing them.

("poids depuis vanilla" = weights from the vanilla model.) Where it sits: stage `poids` of
sm3_convertir.py with the default method (--methode-poids vanilla): it runs after `bras` and
before `lod`, on build/<mod>/etape_bras.mesh (or the output of `chaine`/`ajuster`), and writes
etape_poids.mesh. tools/blacksuit_weights.py runs its main() for the Black Suit (with a k-d tree
nearest-neighbour search swapped in), and poids_par_segments.py reuses its reparer().

`poids_par_segments.py` builds weights from distances to bone segments. That is an
approximation, and it shows as soon as the character moves: rubbery limbs, squashed head.

Here nothing is built. For each vertex of the model, the nearest VANILLA vertices are taken and
their weights are blended by inverse distance. The resulting weights are the game's: right bones,
right proportions, and the left/right and hierarchical consistency comes along for free, because
it is already in the source.

How to READ the final report. A skinning statistic must not be compared with the average of the
WHOLE vanilla body: that describes a complete body, not the area where the converted model lives.
A mask placed on the head comes out at 1.00 dominant weight and looks rigid - while the vanilla
head really is rigid (64.7 % of its vertices on a single bone, against 28.6 % over the whole
body). So the comparison is always made AT THE SAME PLACE, with the nearest vanilla vertex:

    on a converted mask         ours        VANILLA at the same place   (whole vanilla)
    mean influences             1.58              1.75                   2.76
    single bone                65.1 %            64.7 %                 28.6 %

The first two columns look alike: that is the good sign. The third one means nothing here. Only
two measurements compare globally, because they do not depend on the area: left+right mixing and
the hierarchy gap.

The transfer of the Blender chain (`data_transfer`) produces RIGID weights: one bone per vertex,
weight 1.00. The nuance is lost and the joints bend sharply. Blending several neighbours brings
it back.

The correspondence assumes that both bodies OVERLAP. Run `redresser_bras.py` first, otherwise an
arm in another pose takes the torso's weights. `etat_du_maillage()` now SAYS so, instead of
printing a flattering report about a geometry that is already lost.

THREE GENERAL FIXES, measured on delivered models
-------------------------------------------------
1. **48 bones per section, not 32.** The "32 maximum" note was wrong. The 12 skinned vertex
   shaders of Game.exe all declare `world` on c0..c191, i.e. 48 matrices, and the game's
   ch_spiderman000 has three sections with 48 bones. With 32 slots, after the 21 postural bones,
   the forearms, the hands and the ten fingers are the ones that drop out. Measured on the red
   suit:

                              at 32 bones  at 48 bones  vanilla
       segments covered        29 / 31      31 / 31       -
       finger bones, left hand       5            9       -
       gap to the game weights   0.046        0.009        0

2. **Topological repair** (`reparer`): weights that contradict the NEIGHBOURHOOD are erased and
   replaced by it, round after round, until the faulty patch has melted away. Touches nothing
   on a model that is already clean - 24 nodes out of 10,266 for the red suit.

3. **Mesh state** (`etat_du_maillage`): lying down, arms out of pose, or crushed by the
   quantisation. Three defects no set of weights can make up for, which used to go through
   without a word.

Reads:  --mesh (model), --vanilla (vanilla ch_spiderman000.mesh), --skel (vanilla skeleton:
        bone names and hierarchy, for the report AND the safeguards)
Writes: --out, the same file with BLENDINDICES / BLENDWEIGHT bytes and bone palettes rewritten.

    python poids_depuis_vanilla.py --mesh <in.mesh> --vanilla <vanilla 000.mesh>
            --out <out.mesh> [--voisins 6] [--skel <000.skel>] [--max-os 48] [--lisser 24]

Internal segment names are French and are compared in the code, so they stay as they are (they
also appear in the log): avant-bras = forearm, bras = upper arm, clavicule = clavicle, doigt(s) =
finger(s), main = hand, cuisse = thigh, mollet = calf, orteils = toes, pied = foot, tete = head,
cou = neck, haut du torse / torse / bas du torse = upper / middle / lower torso, bassin = pelvis,
autre = other. Sides: 'g' = gauche (left), 'd' = droite (right). Other French names: voisins =
neighbours, os = bone(s), domine = number of vertices a bone dominates, jetes = dropped,
retenus = kept, sauts / arcs = hops in the skeleton tree, lisser = smooth (repair rounds).
"""
from __future__ import annotations

import argparse
import os
import re
import struct
import sys

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
from poids_par_segments import _cote, _sauts, lire_skin  # noqa: E402
from sm3_sans_blender import fmt  # noqa: E402


def log(*x):
    print('[poids-van]', *x)


SEGMENTS = (
    # (patterns in the bone name, segment name) -- order matters: the first match wins
    (('foretwist', 'forearm'), 'avant-bras'),
    (('upperarm',), 'bras'),
    (('clavicle',), 'clavicule'),
    # Safety net only: a NAMED finger bone (`finger<N>...`, `thumb`) is caught before this table,
    # by `DOIGT` below, to get its own segment. This line only catches the rare "finger" bones
    # without a number.
    (('finger', 'thumb'), 'doigts'),
    (('hand',), 'main'),
    (('thigh', 'hip'), 'cuisse'),
    (('calf',), 'mollet'),
    (('toe',), 'orteils'),
    (('foot',), 'pied'),
    (('head',), 'tete'),
    (('neck',), 'cou'),
    (('spine2',), 'haut du torse'),
    (('spine1',), 'torse'),
    (('spine',), 'bas du torse'),
    (('pelvis',), 'bassin'),
)


# FIVE fingers per hand, hence FIVE segments per hand - not a single one.
# The bones are called `bip01 <l|r> finger<D>`, `finger<D>1`, `finger<D>2`: the FIRST digit after
# "finger" names the FINGER, the following ones number the phalanges. `finger01` is therefore
# phalanx 1 of finger 0, not finger 1 - hence the `(\d)` that only captures the first digit.
# Before this fix the 15 finger bones of a hand fell into one single segment: the "one bone per
# segment" reservation kept only ONE of them, and the hand came out as a claw. Measured on
# ch_spiderman: 29 finger bones dropped, only 1 kept on the right and 2 on the left.
DOIGT = re.compile(r'finger(\d)')


def segment(nom):
    """Which anatomical segment a bone belongs to, side included: (side, segment name).

    Used to guarantee that a limb keeps something to BEND with when the palette is too small to
    take everything. Twist bones (`foretwist`, `upperarm split`) are filed with their parent
    segment: they refine it, they do not replace it. The FINGERS do not refine each other: each
    one bends on its own, so each one has its own segment.
    """
    n = ' %s ' % nom.lower().strip()
    cote = 'g' if ' l ' in n else ('d' if ' r ' in n else '')
    d = DOIGT.search(n)                    # a local `d`: there is no byte buffer to overwrite here
    if d:
        return (cote, 'doigt %s' % d.group(1))
    if 'thumb' in n:                       # skeletons that name the thumb instead of numbering it
        return (cote, 'doigt pouce')
    for motifs, quoi in SEGMENTS:
        if any(m in n for m in motifs):
            return (cote, quoi)
    return (cote, 'autre')


def classer_par_segments(candidats, domine, poids, noms, nslots, log):
    """Choose `nslots` bones, guaranteeing ONE bone per anatomical segment first.

    Ranking by the number of dominated vertices alone favours the big postural bones and
    sacrifices the joints. Measured on a 1.2-million-vertex model, palette capped at 32 by the
    Black Suit loader: BOTH forearms (1683 and 1566 dominated vertices) and BOTH clavicles were
    dropped, while the torso kept several slots. An arm without a forearm does not bend.

    So the best bone of each segment is reserved first -- shoulder, upper arm, forearm, hand,
    the FIVE fingers, thigh, calf, foot on each side, plus the torso and the head -- then what is
    left is filled by volume. Measured on ch_spiderman with a 32-bone palette: 31 segments
    dominate at least one vertex, so 31 reserved slots and only 1 left for the volume. It is
    tight, but it holds, and nothing is sacrificed.

    Returns (kept bones, dropped bones).
    """
    if len(candidats) <= nslots:
        return list(candidats), []

    par_segment = {}
    for b in candidats:
        par_segment.setdefault(segment(noms.get(b, '')), []).append(b)

    # Prefer the MAIN bone of the segment to its twist bones. `foretwist` is a CHILD of
    # `forearm`, not its parent: if the twist is kept and the forearm dropped, the 1675 vertices
    # of the forearm go up to their kept ancestor -- the UPPER ARM -- and no longer bend at the
    # elbow. Measured on kim_kardashian: the segment looked covered, and the joint was lost
    # anyway. The reverse works: if `forearm` is kept and `foretwist` dropped, the twist's
    # vertices fall back on the forearm, which is indeed their parent.
    TORSION = ('twist', 'split', 'pivot', 'nub')

    def principal(b):
        return not any(t in noms.get(b, '').lower() for t in TORSION)

    def valeur(b):
        return (domine.get(b, 0), poids.get(b, 0.0))

    def valeur_segment(b):
        # a main bone that dominates something goes before any twist bone
        return (principal(b) and domine.get(b, 0) > 0, domine.get(b, 0), poids.get(b, 0.0))

    charge = {k: sum(domine.get(b, 0) for b in v) for k, v in par_segment.items()}
    dominants = [k for k in par_segment if charge[k] > 0]

    # EXPLICIT TRADE-OFF: 32 slots are not enough for a whole body in ONE section. Treyarch
    # never tries - its ch_spiderman000 splits the body into 10 sections, and its 32-bone
    # section (no. 6) rigs only HALF a body: the complete left arm with its 9 finger bones, its 2
    # `foretwist` and its 3 `upperarm split`, and on the right side only the clavicle.
    # We have only one section. Reserving a bone for EACH of the 31 segments that dominate
    # something leaves only ONE slot for the volume fill - and that fill is what held the TWIST
    # chains (`foretwist`, `upperarm split`). Measured on ch_spiderman, median gap to the
    # vanilla weights per region:
    #                     before (claw fingers)   31 segments reserved   toes sacrificed
    #   fingers                        1.000                 0.496                0.496
    #   upper arm / forearm            0.016                 0.608                0.277
    #   toes                           0.000                 0.000                0.946
    #   whole body                     0.024                 0.052                0.046
    # The arms weigh 277 sampled vertices against 54 for the toes, and a dropped toe falls back
    # on the FOOT, its real parent - it does not show, whereas a lost forearm twist shows at
    # every web throw. So the toes are sacrificed, and ONLY THEM: neither the fingers (very
    # visible) nor the clavicles (less loaded, but a stuck shoulder shows everywhere).
    SACRIFIABLES = ('orteils',)
    # ... but only when room is REALLY missing. The need is counted on the skeleton: a segment
    # that has a twist chain wants one more volume slot to take it back.
    torsions = [k for k, v in par_segment.items()
                if any(domine.get(b, 0) and not principal(b) for b in v)]
    sacrifies = set()
    if len(dominants) > nslots - len(torsions):
        sacrifies = {k for k in dominants if k[1] in SACRIFIABLES}
        if sacrifies:
            log('   tight budget: %d dominant segments for %d slots, and %d '
                'twist chain(s) to take back -> sacrificing %s'
                % (len(dominants), nslots, len(torsions),
                   ', '.join('%s %s' % (c or '-', q) for c, q in sorted(sacrifies))))

    # the segments first, from the most loaded to the least loaded
    ordre = sorted(par_segment, key=lambda k: charge[k], reverse=True)
    retenus, couverts = [], []
    for k in ordre:
        if len(retenus) >= nslots:
            break
        if k in sacrifies:
            continue
        meilleur = max(par_segment[k], key=valeur_segment)
        if domine.get(meilleur, 0) == 0:
            continue          # a segment nobody dominates will be missed by nobody
        retenus.append(meilleur)
        couverts.append(k)

    # then fill up by volume - a sacrificed segment stays sacrificed to the end, otherwise its
    # bone comes back through the window: `toe0` dominates 200 vertices, it would pass before
    # `foretwist` (177).
    # The PHALANGES (`finger<D>1`, `finger<D>2`) come AFTER any body bone that dominates
    # something: `tools/mains_poings.py` redoes them behind us anyway, over several sections.
    # Measured on 2026-10-07 on the conformed TASM2 (five fingers properly in place): the
    # phalanges dominated 44 to 49 vertices and pushed out `foretwist` (47) and `upperarm split3`
    # (30) -- the elbow lost its twist, and mains_poings could not give it back.
    def valeur_remplissage(b):
        phal = bool(re.search(r'finger\d[12]', noms.get(b, '').lower()))
        return (domine.get(b, 0) > 0 and not phal, domine.get(b, 0), poids.get(b, 0.0))
    reste = sorted((b for b in candidats if b not in retenus
                    and segment(noms.get(b, '')) not in sacrifies),
                   key=valeur_remplissage, reverse=True)
    retenus += reste[:max(0, nslots - len(retenus))]

    manquants = [k for k in ordre if k not in couverts
                 and any(domine.get(b, 0) for b in par_segment[k])]
    log('   coverage: %d segment(s) out of %d have at least one bone'
        % (len(couverts), len([k for k in ordre if any(domine.get(b, 0) for b in par_segment[k])])))
    # the hand is the first place where the palette cracks: count it, hand by hand
    doigts = [segment(noms.get(b, '')) for b in retenus]
    for cote, quoi in (('g', 'LEFT'), ('d', 'RIGHT')):
        pris = [q for c, q in doigts if c == cote and q.startswith('doigt')]
        log('   %s hand: %d finger bone(s) kept over %d distinct finger(s)'
            % (quoi, len(pris), len(set(pris))))
    if manquants:
        log('   !! segments WITHOUT a bone: %s'
            % ', '.join('%s %s' % (c or '-', q) for c, q in manquants))
    return retenus, [b for b in candidats if b not in retenus]


def plus_proches(P, Q, k, pas=192):
    """The k nearest points of Q for each point of P, by blocks of `pas` rows, numpy only.

    Returns (indices (n, k), distances (n, k)), nearest first."""
    idx = np.empty((len(P), k), np.int64)
    dst = np.empty((len(P), k), np.float64)
    for a in range(0, len(P), pas):
        d = np.linalg.norm(P[a:a + pas, None, :] - Q[None, :, :], axis=2)
        o = np.argpartition(d, k, axis=1)[:, :k]
        dd = np.take_along_axis(d, o, 1)
        r = np.argsort(dd, axis=1)
        idx[a:a + pas] = np.take_along_axis(o, r, 1)
        dst[a:a + pas] = np.take_along_axis(dd, r, 1)
    return idx, dst


def etat_du_maillage(m, Pv, log=print):
    """Say, BEFORE skinning, whether the mesh is still a human body ("state of the mesh").

    A weight transfer can do nothing for a geometry that is already broken, and until this
    check nothing said so: the skinning ran, the report looked fine, and the character arrived
    twisted in game. Three measurements are enough to decide, all taken on the BYTES of the mesh.

    1. STANDING? The vanilla model is longest along y (2.150 against 1.744 in x and 0.438 in z).
       A model whose largest extent is not y is lying down: it missed its straightening.
    2. WIDTH. The vanilla model is in an A-pose, arms apart: x/y = 0.81. A model with its arms
       along the body falls to about 0.25, and every arm vertex will then pick the hip bones.
    3. CRUSHED BY THE QUANTISATION. Positions are 16-bit integers divided by 512: the step is
       1/512 everywhere, whatever the size of the model. A squashed mesh loses vertices by
       merging. Share of vertices that survive, measured:
           vanilla 89.6 %   photoreal_rouge 91.8 %   suku 78.9 %   |   peter 5.0 %
       At 5 %, the 32,932 vertices of `peter` only point to 1,631 distinct positions: the model
       is now just a cone, and no weights will save it.

    Returns the list of serious problems found (empty if none); they are also logged.
    """
    P, distincts, nsom = [], 0, 0
    for s in m.sections:
        if not s.vertex_count:
            continue
        P.append(np.array(fmt.decode_section_vertices(m, s, uv_divisor=1000.0)['positions'],
                          np.float64))
        # positions declared as dtype 7 (D3DDECLTYPE_SHORT4): count distinct int16 triples
        dp = [d for d in s.decl if d.usage == 0]
        if dp and dp[0].dtype == 7:
            b = np.frombuffer(m.raw, np.uint8, s.vertex_count * s.vertex_stride,
                              s.vertex_buffer_offset).reshape(s.vertex_count, s.vertex_stride)
            sh = b[:, dp[0].offset:dp[0].offset + 8].copy().view(np.int16)[:, :3]
            distincts += len(np.unique(sh, axis=0))
            nsom += s.vertex_count
    P = np.concatenate(P)
    e, ev = P.max(0) - P.min(0), Pv.max(0) - Pv.min(0)
    survie = 100.0 * distincts / max(nsom, 1)
    log('mesh: extent %s against %s for the vanilla model | %.1f %% of the vertices survive the '
        'quantisation' % (np.round(e, 3), np.round(ev, 3), survie))
    grave = []
    if int(np.argmax(e)) != 1:
        grave.append('THE MODEL IS LYING DOWN: its largest extent is %s, not the height.'
                     % 'xyz'[int(np.argmax(e))])
    r = (e[0] / max(e[1], 1e-9)) / max(ev[0] / ev[1], 1e-9)
    if r < 0.85:
        grave.append('ARMS OUT OF POSE: arm span at %.0f %% of the vanilla one. The proximity '
                     'transfer will bind the arms to the pelvis and finger bones.' % (100 * r))
    if survie < 50.0:
        grave.append('CRUSHED MESH: only %.1f %% of the vertices remain distinct after the '
                     '1/512 quantisation. The geometry is lost BEFORE the skinning.' % survie)
    for g in grave:
        log('!! %s' % g)
    if grave:
        log('!! -> fix the geometry upstream (orientation, scale, A-pose): no set of weights')
        log('!!    makes up for these three defects. The topological repair will limit the')
        log('!!    damage, it will not undo it.')
    return grave


# ---------------------------------------------------------------- topological repair


def _graphe(P, faces):
    """Neighbourhood on the MESH, co-located vertices merged.

    Merging first is not a detail: a UV seam duplicates vertices, and two vertices at the same
    place that get different weights split apart as soon as it moves - that is the crack that
    cuts a face in two and folds it onto itself. Here they form one single node, so they
    necessarily carry the same weights.

    Returns (group of each vertex, concatenated neighbours, start per group) in CSR form.
    """
    cle = np.round(np.asarray(P, np.float64) * 4096.0).astype(np.int64)
    _, groupe = np.unique(cle, axis=0, return_inverse=True)
    groupe = np.asarray(groupe).ravel()
    n = int(groupe.max()) + 1
    if not len(faces):
        return groupe, np.zeros(0, np.int64), np.zeros(n + 1, np.int64)
    f = np.asarray(faces, np.int64)
    a = groupe[np.concatenate([f[:, 0], f[:, 1], f[:, 2]])]
    b = groupe[np.concatenate([f[:, 1], f[:, 2], f[:, 0]])]
    garde = a != b
    a, b = a[garde], b[garde]
    a, b = np.concatenate([a, b]), np.concatenate([b, a])       # each edge in both directions
    o = np.lexsort((b, a))
    a, b = a[o], b[o]
    uniq = np.ones(len(a), bool)
    uniq[1:] = (a[1:] != a[:-1]) | (b[1:] != b[:-1])
    a, b = a[uniq], b[uniq]
    return groupe, b, np.searchsorted(a, np.arange(n + 1))


def _moyenne_voisins(W, vois, debut):
    """Mean of the rows of W over each node's neighbourhood. Exact sums by slices."""
    if not len(vois):
        return W.copy()
    C = np.zeros((len(vois) + 1, W.shape[1]), np.float64)
    np.cumsum(W[vois], axis=0, out=C[1:])
    somme = C[debut[1:]] - C[debut[:-1]]
    nb = np.maximum(debut[1:] - debut[:-1], 1)[:, None]
    return (somme / nb).astype(W.dtype)


def _composantes(vois, debut):
    """Label the SEPARATE pieces of the mesh (connected components of the CSR graph)."""
    n = len(debut) - 1
    etiq = np.full(n, -1, np.int64)
    courant = 0
    for depart in range(n):
        if etiq[depart] >= 0:
            continue
        pile = [depart]
        etiq[depart] = courant
        while pile:
            x = pile.pop()
            for k in range(debut[x], debut[x + 1]):
                y = int(vois[k])
                if etiq[y] < 0:
                    etiq[y] = courant
                    pile.append(y)
        courant += 1
    return etiq, courant


def reparer(P, faces, cumul, noms, parents, sauts_max=4, tours=24, log=print):
    """Erase the weights that contradict the NEIGHBOURHOOD, eroding from the border ("repair").

    THE PROBLEM, MEASURED
    ---------------------
    The transfer decides vertex by vertex, without ever looking next door. When the two bodies
    do not overlap - a hand hanging along the thigh, two feet touching - a whole patch of
    vertices catches the bones of its GEOMETRIC NEIGHBOUR instead of its own. Measured on the
    delivered meshes, share of edges whose two ends fall on opposite sides of the body (the
    vanilla model has 0.006 %):

        peter 3.27 %   apres_flanc2 2.14 %   adv_large 0.46 %   photoreal_rouge 0.00 %

    and share of edges whose two bones are more than 3 edges apart (vanilla 0.38 %):

        smmovie 4.28 %   peter 3.07 %   adv_large 1.93 %

    In game: a thigh patch that follows a finger, one arm out of two going askew.

    THE FIX
    -------
    The model's TOPOLOGY is reliable: it does not depend on the pose. A thigh is never linked
    to a finger by the surface. So each vertex is compared with the mean of its neighbours; if
    it points to a bone more than `sauts_max` edges away from theirs, or on the other side of
    the body, it is replaced by that mean. And again: the faulty patch melts from its BORDER,
    round after round, even when it is wide - inside, the neighbours are wrong too, but at the
    border they are right, and the right answer gains ground at every pass.

    Nothing is touched on a vertex that already agrees with its neighbourhood: a clean model
    comes out unchanged. The fix calibrates itself; it has no threshold to tune.

    `cumul` is one {bone: weight} dict per vertex. Returns (new cumul, % of contradicting nodes
    before, % after).
    """
    n = len(cumul)
    os_vus = sorted({b for acc in cumul for b in acc})
    if not os_vus or not len(faces) or tours <= 0:
        return cumul, 0.0, 0.0
    col = {b: i for i, b in enumerate(os_vus)}
    nb = len(os_vus)
    groupe, vois, debut = _graphe(P, faces)
    ng = len(debut) - 1
    W = np.zeros((ng, nb), np.float64)
    for i, acc in enumerate(cumul):
        g = groupe[i]
        for b, w in acc.items():
            W[g, col[b]] += w
    W /= np.maximum(W.sum(1, keepdims=True), 1e-12)

    cote = np.array([{'l': -1, 'r': 1}.get(_cote(noms.get(b, '')), 0) for b in os_vus], np.int8)
    SAUT = np.zeros((nb, nb), np.int16)
    if parents:
        for i, x in enumerate(os_vus):
            for j, y in enumerate(os_vus):
                SAUT[i, j] = _sauts(parents, x, y)
    isole = (debut[1:] - debut[:-1]) == 0

    def incoherents(W):
        M = _moyenne_voisins(W, vois, debut)
        d, dv = W.argmax(1), M.argmax(1)
        mauvais = SAUT[d, dv] > sauts_max
        mauvais |= (cote[d] != 0) & (cote[dv] != 0) & (cote[d] != cote[dv])
        mauvais &= ~isole
        return mauvais, M

    mauvais, M = incoherents(W)
    depart = 100.0 * mauvais.mean()
    touches = np.zeros(ng, bool)
    for _ in range(tours):
        if not mauvais.any():
            break
        W[mauvais] = M[mauvais]
        W /= np.maximum(W.sum(1, keepdims=True), 1e-12)
        touches |= mauvais
        mauvais, M = incoherents(W)
    fin = 100.0 * mauvais.mean()
    log('   topological repair: %.2f %% of nodes contradicting their neighbours '
        '-> %.2f %% (%d node(s) changed out of %d)'
        % (depart, fin, int(touches.sum()), ng))

    # SMALL SEPARATE PIECES escape everything above: a belt pouch, a buckle, a shoulder pad
    # touch the body by no edge, so they have no neighbour to correct them, and each of their
    # halves can fall on a different bone. Measured on the delivered Batman Beyond: 17 pieces,
    # 16 of them accessories of 8 to 63 nodes at height 0.57..0.61 - a pouch half `bip01 pelvis`,
    # half `bip01 l thigh`. In game it stretches in two from the first step. A rigid accessory
    # must follow ONE group of bones: it gets the mean of its own component. The threshold is
    # deliberately low (2 % of the mesh) so that a cape or a flap of cloth, which MUST deform,
    # is never stiffened.
    etiq, nc = _composantes(vois, debut)
    if nc > 1:
        limite = max(24, int(0.02 * ng))
        unifies = 0
        for c in range(nc):
            m = etiq == c
            k = int(m.sum())
            if k < 2 or k > limite:
                continue
            d = W[m].argmax(1)
            u = np.unique(d)
            if len(u) < 2:
                continue
            ecart = SAUT[np.ix_(u, u)].max()
            cotes = {int(x) for x in cote[u] if x}
            if ecart <= sauts_max and len(cotes) < 2:
                continue
            moy = W[m].mean(0)
            W[m] = moy
            unifies += 1
        if unifies:
            W /= np.maximum(W.sum(1, keepdims=True), 1e-12)
        log('   %d separate piece(s); %d small accessory(ies) unified on a single '
            'bone group (threshold %d nodes)' % (nc, unifies, limite))

    neuf = []
    for i in range(n):
        w = W[groupe[i]]
        nz = np.where(w > 1e-5)[0]
        neuf.append({os_vus[j]: float(w[j]) for j in nz} or dict(cumul[i]))
    return neuf, depart, fin


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--vanilla', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--voisins', type=int, default=6,
                    help='vanilla vertices blended per vertex (neighbours). 1 = rigid, too hard; '
                         '6 reproduces the smoothness of the vanilla model')
    ap.add_argument('--k', type=int, default=4, help='influences kept (the format holds 4)')
    ap.add_argument('--sauts-max', type=int, default=4,
                    help='largest hierarchy gap between the dominant bone and the other influences')
    ap.add_argument('--skel', default='', help='bone names and hierarchy: report AND safeguards')
    ap.add_argument('--par-segments', type=int, default=1,
                    help='1 = guarantee one bone per anatomical segment before filling by volume. '
                         'Without it, a 32-bone palette drops BOTH clavicles and both '
                         'forearms: the shoulders no longer move and the elbows no longer bend.')
    ap.add_argument('--max-os', type=int, default=48,
                    help='Bones per section. The engine accepts 48: the 12 skinned vertex shaders '
                         'of Game.exe all declare `world` on c0..c191, i.e. 48 '
                         'matrices, and the game\'s ch_spiderman000 has three sections with 48.')
    ap.add_argument('--arcs-max', type=int, default=5,
                    help='largest hierarchy gap BETWEEN TWO influences of the same vertex. '
                         'Measured on the vanilla model: never more than 5 edges.')
    ap.add_argument('--lisser', type=int, default=24,
                    help='rounds of topological repair. 0 = none. Only touches the '
                         'vertices that contradict their neighbours: a clean model does not move.')
    A = ap.parse_args()
    # The "32 bones maximum" note was WRONG, and it was costly: with 32 slots nothing is left
    # after the 21 postural bones, and the forearms, the hands and the ten fingers are the ones
    # that drop out - measured on the delivered models, segments missing from the palette:
    #     peter      both forearms, both hands, the 10 fingers
    #     adv_large  both upper arms, both clavicles, one foot, 8 fingers
    # Two independent measurements give 48: the constant table of the shaders
    # (`world` = 192 float4 registers = 48 matrices, in the game's 12 skinned shaders) and the
    # vanilla model itself (sections 0, 5 and 7 of ch_spiderman000: palettes of 48 distinct bones).
    if not 1 <= A.max_os <= 48:
        ap.error('The engine accepts 1 to 48 bones per section.')

    mv, Pv, Gv, Wv = lire_skin(A.vanilla)
    Wv = Wv / np.maximum(Wv.sum(1, keepdims=True), 1e-9)
    log('vanilla: %d vertices, %d distinct bones' % (len(Pv), len(np.unique(Gv))))
    noms, parents = {}, {}
    if A.skel and os.path.exists(A.skel):
        _sk = fmt.parse_skeleton(A.skel)
        noms = {b.index: b.name for b in _sk.bones}
        parents = {b.index: b.parent_index for b in _sk.bones}

    m = fmt.parse_mesh(A.mesh)
    d = bytearray(m.raw)
    total = 0

    etat_du_maillage(m, Pv, log)
    for s in m.sections:
        if not s.vertex_count:
            continue
        dec = fmt.decode_section_vertices(m, s, uv_divisor=1000.0)
        P = np.array(dec['positions'], np.float64)
        idx, dst = plus_proches(P, Pv, A.voisins)
        log('section %d: %d vertices | distance to the vanilla model: median %.4f, max %.4f'
            % (s.index, len(P), float(np.median(dst[:, 0])), float(dst[:, 0].max())))

        # blend by inverse distance, then sum the weights per BONE
        pond = 1.0 / np.maximum(dst, 1e-4)
        pond = pond / pond.sum(1, keepdims=True)
        cumul = []
        for i in range(len(P)):
            acc = {}
            for j in range(A.voisins):
                v = idx[i, j]
                for c in range(Gv.shape[1]):
                    w = Wv[v, c] * pond[i, j]
                    if w > 1e-6:
                        acc[int(Gv[v, c])] = acc.get(int(Gv[v, c]), 0.0) + float(w)
            cumul.append(acc)

        # The geometric neighbourhood lies as soon as the two poses differ; the model's
        # TOPOLOGY does not. The weights that contradict the surface are erased here.
        if A.lisser:
            try:
                faces = fmt.indices_to_faces(fmt.read_indices(m, s), s.primitive_type,
                                             s.vertex_count)
            except Exception as e:
                faces = []
                log('   no readable index buffer (%s): topological repair skipped' % e)
            if faces:
                cumul, _av, _ap = reparer(P, faces, cumul, noms, parents, A.sauts_max,
                                          A.lisser, log)

        # ---- palette: rank by DOMINATION, not by the sum of the weights.
        # The sum favours the big postural bones and sacrifices the small terminal ones. On a
        # whole body, `bip01 neck` and `bip01 l/r hip` kept a slot while dominating NO vertex,
        # while `bip01 l/r upperarm` and their three `split` bones were dropped. Result in game:
        # deformed arms and hands, because those vertices fell on the clavicle or the forearm.
        # What matters is the number of vertices for which a bone is the MAIN influence - a
        # bone that dominates nothing will be missed by nobody.
        nslots = min(len(s.bone_palette or []) or 48, A.max_os)
        poids_os, domine = {}, {}
        for acc in cumul:
            for b, w in acc.items():
                poids_os[b] = poids_os.get(b, 0.0) + w
            if acc:
                # do NOT call this `d`: that is the mesh byte buffer, above
                dom = max(acc, key=acc.get)
                domine[dom] = domine.get(dom, 0) + 1
        rang = sorted(poids_os, key=lambda b: (domine.get(b, 0), poids_os[b]), reverse=True)
        if A.par_segments:
            retenus, jetes = classer_par_segments(rang, domine, poids_os, noms, nslots, log)
        else:
            retenus, jetes = rang[:nslots], rang[nslots:]
        pal = sorted(retenus)
        loc = {b: i for i, b in enumerate(pal)}
        log('   %d bones kept out of %d proposed (%d slots)' % (len(pal), len(poids_os), nslots))
        if jetes:
            log('   bones dropped: %s' % ', '.join(
                '%s (dominates %d)' % (noms.get(b, '?%d' % b), domine.get(b, 0)) for b in jetes))
            perdus = sum(domine.get(b, 0) for b in jetes)
            if perdus:
                log('   !! %d vertex(es) lose their main bone - moved to the kept ancestor'
                    % perdus)

        # A dropped TWIST bone does not give its weights back to its parent: in ch_spiderman000,
        # `foretwist` is a child of the UPPER ARM (parent = upperarm), not of the forearm. Its
        # vertices -- the forearm near the elbow -- went up to the upper arm and no longer bent
        # at the elbow. They go to the MAIN bone of their segment, on their side, if it is kept.
        _principal_de = {}
        for _b, _n in noms.items():
            _nl = ' %s ' % _n.lower()
            for _mot, _vers in (('foretwist', 'forearm'), ('upperarm split', 'upperarm'),
                                ('bone01', 'upperarm'), (' hip ', 'thigh')):
                if _mot in _nl:
                    _c = _cote(_n)
                    for _b2, _n2 in noms.items():
                        if _n2.lower() == 'bip01 %s %s' % (_c, _vers):
                            _principal_de[_b] = _b2

        def vers_garde(b):
            """A dropped bone gives its weights to its nearest kept ANCESTOR, never to pal[0];
            a twist bone, to the main bone of its segment."""
            if b in _principal_de and _principal_de[b] in loc:
                return _principal_de[b]
            vu, cur = set(), b
            while cur is not None and cur not in loc and cur not in vu:
                vu.add(cur)
                cur = parents.get(cur)
            return cur if cur in loc else None

        L = np.zeros((len(P), 4), np.int64)
        Wo = np.zeros((len(P), 4), np.float64)
        ecartes = 0
        for i, acc in enumerate(cumul):
            # move the dropped bones onto their kept ancestor BEFORE sorting
            if len(acc) != len([1 for b in acc if b in loc]):
                rep = {}
                for b, w in acc.items():
                    cible = b if b in loc else vers_garde(b)
                    if cible is not None:
                        rep[cible] = rep.get(cible, 0.0) + w
                acc = rep
            paires = sorted(((w, b) for b, w in acc.items() if b in loc), reverse=True)
            # Safeguards, even when the weights come from the vanilla model: a vertex whose
            # neighbours straddle a border picks up bones from BOTH sides, and the limb
            # stretches as soon as the animation separates them. The vanilla model mixes sides
            # on only 0.23 % of its vertices.
            if paires and noms:
                pg = sum(w for w, b in paires if _cote(noms.get(b, '')) == 'l')
                pd = sum(w for w, b in paires if _cote(noms.get(b, '')) == 'r')
                if pg > 0 and pd > 0:
                    perdant = 'r' if pg >= pd else 'l'
                    n0 = len(paires)
                    paires = [(w, b) for w, b in paires if _cote(noms.get(b, '')) != perdant]
                    ecartes += n0 - len(paires)
                if paires and parents:
                    bd = paires[0][1]
                    n0 = len(paires)
                    paires = [(w, b) for w, b in paires
                              if _sauts(parents, bd, b) <= A.sauts_max]
                    ecartes += n0 - len(paires)
                    # Bounding the distance to the DOMINANT bone does not bound the gap between
                    # the others: two influences 4 edges away on either side are 8 apart. The
                    # vanilla model never exceeds 5 edges between two influences of one vertex;
                    # beyond that, two distant bones pull the same vertex and the limb
                    # stretches. `paires` is sorted by decreasing weight: the lightest goes first.
                    while len(paires) > 1:
                        if max(_sauts(parents, x, y)
                               for _, x in paires for _, y in paires) <= A.arcs_max:
                            break
                        paires = paires[:-1]
                        ecartes += 1
            paires = paires[:A.k]
            if not paires:
                paires = [(1.0, pal[0])]
            t = sum(w for w, _ in paires)
            for c, (w, b) in enumerate(paires):
                L[i, c] = loc[b]
                Wo[i, c] = w / t
        if ecartes:
            log('   safeguards: %d influence(s) dropped' % ecartes)

        bloc = np.frombuffer(bytes(d[s.vertex_buffer_offset:
                                     s.vertex_buffer_offset + s.vertex_count * s.vertex_stride]),
                             np.uint8).copy().reshape(s.vertex_count, s.vertex_stride)
        oi = [dc.offset for dc in s.decl if dc.usage == 2][0]     # BLENDINDICES, UBYTE4
        ow = [dc.offset for dc in s.decl if dc.usage == 1][0]     # BLENDWEIGHT, SHORT4N
        bloc[:, oi:oi + 4] = np.clip(L, 0, 255).astype(np.uint8)
        q = np.clip(np.rint(Wo * 32767.0), 0, 32767).astype(np.int16)
        bloc[:, ow:ow + 8] = q.view(np.uint8).reshape(s.vertex_count, 8)
        d[s.vertex_buffer_offset:s.vertex_buffer_offset + s.vertex_count * s.vertex_stride] = \
            bloc.tobytes()
        # palette as u16 at the LOCAL offset, not u32 (see poids_par_segments.py)
        for i in range(nslots):
            struct.pack_into('<H', d, s.bone_palette_pointer_serialized + i * 2,
                             pal[i] if i < len(pal) else pal[-1])
        total += s.vertex_count

    os.makedirs(os.path.dirname(os.path.abspath(A.out)) or '.', exist_ok=True)
    open(A.out, 'wb').write(bytes(d))
    log('WROTE %s (%d vertices)' % (A.out, total))

    # ---- report, compared with the vanilla model
    _, P2, G2, W2 = lire_skin(A.out)
    W2n = W2 / np.maximum(W2.sum(1, keepdims=True), 1e-9)
    Wvn = Wv

    def mesures(G, W):
        # (% of vertices mixing left and right, % with influences > 3 edges apart, max gap)
        mixte = 0
        hs = []
        for i in range(len(G)):
            act = [int(G[i, c]) for c in range(G.shape[1]) if W[i, c] > 0.05]
            if len(act) < 2:
                continue
            cs = {_cote(noms.get(b, '')) for b in act if _cote(noms.get(b, ''))}
            if len(cs) > 1:
                mixte += 1
            hs.append(max(_sauts(parents, a, b) for a in act for b in act))
        hs = np.array(hs) if hs else np.array([0])
        return 100.0 * mixte / len(G), 100.0 * float((hs > 3).mean()), int(hs.max())

    # NEVER compare a skinning statistic with the GLOBAL MEAN of the vanilla model: it describes
    # a whole body, not the area where the converted model lives. A mask on the head will always
    # come out "too rigid" against it, while the vanilla head IS rigid (64.7 % of its vertices on
    # a single bone, against 28.6 % over the whole body). Twice in a row that comparison raised
    # a false alarm. So the comparison is made AT THE SAME PLACE.
    ech = np.random.default_rng(0).choice(len(P2), min(1500, len(P2)), replace=False)
    ivois, _ = plus_proches(P2[ech], Pv, 1)
    ivois = ivois[:, 0]
    nn = (W2n[ech] > 0.01).sum(1)
    nv = (Wvn[ivois] > 0.01).sum(1)
    ecarts = []
    for k, i in enumerate(ech):
        a = {int(G2[i, c]): float(W2n[i, c]) for c in range(G2.shape[1]) if W2n[i, c] > 0.01}
        v = int(ivois[k])
        b = {int(Gv[v, c]): float(Wvn[v, c]) for c in range(Gv.shape[1]) if Wvn[v, c] > 0.01}
        ecarts.append(sum(abs(a.get(o, 0) - b.get(o, 0)) for o in set(a) | set(b)) / 2)

    log('')
    log('                          ours       VANILLA at the same place (whole vanilla)')
    log('   mean influences      %9.2f %23.2f %17.2f'
        % (nn.mean(), nv.mean(), float((Wvn > 0.01).sum(1).mean())))
    log('   median dominant w.   %9.2f %23.2f %17.2f'
        % (float(np.median(W2n[ech].max(1))), float(np.median(Wvn[ivois].max(1))),
           float(np.median(Wvn.max(1)))))
    log('   single bone          %8.1f %% %21.1f %% %15.1f %%'
        % (100 * (nn == 1).mean(), 100 * (nv == 1).mean(),
           100 * ((Wvn > 0.01).sum(1) == 1).mean()))
    log('   -> what matters is that the FIRST TWO columns look alike.')
    log('')
    log('   gap to the game weights, at the same place: median %.3f  (0 = the game weights)'
        % float(np.median(ecarts)))

    if noms:
        a1 = mesures(G2, W2n)
        a2 = mesures(Gv, Wvn)
        log('')
        log('   consistency (these two compare well, they do not depend on the area):')
        log('                          left+right mixing          influences > 3 edges apart')
        log('   ours                %14.2f %%       %20.2f %%' % (a1[0], a1[1]))
        log('   VANILLA             %14.2f %%       %20.2f %%' % (a2[0], a2[1]))
        log('   -> beyond ~2 % of left+right mixing, the limbs stretch as soon as it moves.')


if __name__ == '__main__':
    main()
