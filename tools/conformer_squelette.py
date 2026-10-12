# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""conformer_squelette.py - put the JOINTS of a rigged model on those of the game's skeleton.

("conformer au squelette" = "conform to the skeleton".) Used by chaine_officielle.py (inside
Blender, step "2 quater") when the source model has its own rig; conformer_sans_rig.py and
doigts_sans_rig.py do the same job for models without one. Writes nothing itself: the chain
writes conforme.json and doigts_modele.npz from what it returns.

THE DEFECT, MEASURED (2026-10-07, "the TASM2 has a broken back", "some models still have
broken fingers even after the patch")
---------------------------------------------------------------------------------------------
The chain ignored the model's skeleton: isotropic scale on the height, feet on feet, then
centring on the MEDIAN of all the vertices, and the vanilla's weights by proximity. Yet the
engine rotates each piece around the joints of the VANILLA skeleton. Measurements, after that
fit:

    TASM2 (GLB, mixamo rig)   elbow 7 cm too far along the arm (humerus +26 %), knees 7 cm
                              too low, and the WHOLE body 10 to 19 cm BEHIND the skeleton (head
                              in place): the spine rotates around an axis sitting in the belly.
    TASM (installed)          same offset backwards, 10 to 17 cm.
    photoreal                 <= 3 cm everywhere: that is why it alone looked right.
    hands                     the model's fingers do not follow the vanilla's: the proximity
                              transfer finds only 3 fingers, and `mains_poings` (which requires
                              5 separate finger pieces, posed like the vanilla) leaves the hand.

THE FIX
-------
When the model has its own rig, we use it: every recognised bone (mixamo, Unreal, Biped, free
names "left arm", "upperarm_l") is moved, oriented and stretched so that ITS head lands on the
corresponding vanilla joint and its main child on the next one. The mesh follows by linear
skinning with ITS OWN weights. Unrecognised bones (twists, ends) follow their ancestor.

    - the stretch acts only ALONG the bone: thicknesses, head, hands keep their size;
    - a bone with several children (pelvis, upper torso, hand) is oriented as well as possible
      on ALL of them (Kabsch), then snapped exactly onto the main child;
    - left/right is decided by GEOMETRY (sign of x), never by the name: the chain never mirrored
      the model, we keep its convention (photoreal validated in game that way);
    - the fingers too: each phalanx on the vanilla phalanx. And we keep, vertex by vertex, the
      finger the model's rig attaches it to -> `mains_poings` no longer needs to guess the
      fingers from the topology (file `doigts_modele.npz` next to the .mesh).

No bpy here: the module can be tested outside Blender. `chaine_officielle.py` passes it arrays.
Bone names of the game look like 'bip01 l upperarm', 'bip01 r finger21' (3ds Max Biped names).
"""
from __future__ import annotations

import os
import re

import numpy as np

DOIGTS = ('thumb', 'index', 'middle', 'ring', 'pinky')          # fingers, game order (0..4)
# finger words found in rig bone names (French ones included: pouce, majeur, annulaire,
# auriculaire) -> canonical finger
SYNONYMES_DOIGT = {'thumb': 'thumb', 'pouce': 'thumb', 'index': 'index', 'pointer': 'index',
                   'middle': 'middle', 'mid': 'middle', 'majeur': 'middle', 'ring': 'ring',
                   'annulaire': 'ring', 'pinky': 'pinky', 'little': 'pinky', 'small': 'pinky',
                   'auriculaire': 'pinky'}
KMIN, KMAX = 0.55, 1.80        # bounds of the stretch along a bone


# =============================================================================== names
def _base(nom):
    """Bone name without its 'Armature|' or 'mixamorig:' style prefixes."""
    n = nom.split('|')[-1].split(':')[-1]
    return n.strip()


def normaliser_noms(noms):
    """Name -> comparable form. Sketchfab exports glue a "_012" suffix to every bone; it is
    removed unless that creates duplicates (Unreal: spine_01 / spine_02 must stay distinct)."""
    bruts = [_base(n).lower() for n in noms]
    sans = [re.sub(r'_\d+$', '', b) for b in bruts]
    vus = {}
    for s in sans:
        vus[s] = vus.get(s, 0) + 1
    return [s if vus[s] == 1 else b for s, b in zip(sans, bruts)]


def _cote_nom(n):
    """'l', 'r' or '' from the name (only used to PAIR the two sides; the final vanilla side
    comes from the geometry)."""
    t = re.sub(r'[^a-z0-9]+', ' ', n).strip()
    m = ' %s ' % t
    if re.search(r'(^|[^a-z])left', n) or n.startswith('left') or ' l ' in m or m.startswith(' l ') \
            or re.search(r'[ _.\-]l$', n) or re.search(r'^l[ _.\-]', n) or re.search(r'_l_', n):
        return 'l'
    if re.search(r'(^|[^a-z])right', n) or n.startswith('right') or ' r ' in m or m.startswith(' r ') \
            or re.search(r'[ _.\-]r$', n) or re.search(r'^r[ _.\-]', n) or re.search(r'_r_', n):
        return 'r'
    # Daz camelCase: lShldr, rHand
    if re.match(r'^l(shldr|forearm|hand|thigh|shin|foot|collar|toe|thumb|index|mid|ring|pinky)', n):
        return 'l'
    if re.match(r'^r(shldr|forearm|hand|thigh|shin|foot|collar|toe|thumb|index|mid|ring|pinky)', n):
        return 'r'
    return ''


def _sans_cote(n):
    """The name without its side marks and common rig prefixes ("sans côté" = without side)."""
    n = re.sub(r'left|right', ' ', n)
    n = re.sub(r'(^|[ _.\-])[lr]([ _.\-]|$)', ' ', n)
    n = re.sub(r'_[lr]_', ' ', n)
    n = re.sub(r'^bip0*1 ?|^bip ?|^mixamorig\d*|^def[ _\-]|^bone[ _\-]|^b_|^bn_|^j_|^jnt_|^c_', ' ', n)
    return re.sub(r'[ _.\-]+', ' ', n).strip()


def _est_bout(n):
    """True for an end bone (end, nub, tip...)."""
    return bool(re.search(r'(end|nub|tip|top|_end|null)\b', n) or n.endswith('end') or n.endswith('nub'))


def _partie(n):
    """Body part (without side) or None. `n` is already without side. Finger parts are
    returned as 'doigt:<finger>' ("doigt" = finger)."""
    s = n.replace(' ', '')
    if _est_bout(n) and not re.search(r'toe', s):
        return None
    for d, cle in SYNONYMES_DOIGT.items():
        if d in s:
            # metacarpal (Unreal "metacarpal", Auto-Rig Pro "index1_base"): not a phalanx
            if 'metacarpal' in s or 'meta' in s or s.endswith('base') or 'base' in s:
                return None
            return 'doigt:' + cle
    m = re.search(r'finger(\d)', s)
    if m and not re.search(r'meta', s):
        # Biped ("finger0, finger01, finger02") and Free Fire ("finger01, finger02"): the
        # FIRST digit is the finger, as in the game's skeleton
        return 'doigt:' + DOIGTS[min(int(m.group(1)), 4)]
    if re.search(r'finger', s):
        return 'doigt:?'
    if re.search(r'twist|roll|split|bend2|helper|pivot|prop|weapon|ik|pole|target', s):
        return None
    if re.fullmatch(r'(hips?|pelvis|root ?hips|cog|hip)', s) and 'leg' not in s:
        return 'pelvis'
    if re.search(r'clavicle|collar|shoulder|clav', s):
        return 'clavicle'
    if re.search(r'forearm|lowerarm|elbow|forarm', s):
        return 'forearm'
    if re.search(r'upperarm|uparm|shldr|^arm\d*$|armbend|^arm$|^armstretch|^arm ?stretch', s) or s == 'arm':
        return 'upperarm'
    if re.search(r'hand|wrist|palm|carpal', s):
        return 'hand'
    if re.search(r'upleg|upperleg|legupper|thigh|femur|^hip$', s):
        return 'thigh'
    if re.search(r'lowerleg|calf|shin|knee|^leg\d*$|^legstretch|tibia', s):
        return 'calf'
    if re.search(r'toebase|ball|toe|digit', s):
        return 'toe_fin' if _est_bout(n) else 'toe'
    if re.search(r'foot|ankle', s):
        return 'foot'
    if re.search(r'neck', s):
        return 'neck'
    if re.search(r'head', s):
        return 'head'
    if re.search(r'spine|chest|torso|abdomen|abdom|back|waist|belly|stomach', s):
        return 'spine'
    return None


# =============================================================================== hierarchy
def _profondeur(parents):
    """Depth of each bone in the hierarchy (0 = root)."""
    p = []
    for i in range(len(parents)):
        d, x, vus = 0, parents[i], set()
        while x is not None and x >= 0 and x not in vus:
            vus.add(x)
            d += 1
            x = parents[x]
        p.append(d)
    return p


def _ancetres(parents, i):
    """Ancestors of bone i, nearest first."""
    out, x, vus = [], parents[i], set()
    while x is not None and x >= 0 and x not in vus:
        vus.add(x)
        out.append(x)
        x = parents[x]
    return out


def cartographier(noms, parents, tetes, cote_vanilla_gauche_x=-1.0, log=print):
    """("map") Returns {model bone index: vanilla bone name}. `tetes`: positions of the bone
    heads in the mesh's frame (used to assign the sides and to order vertebrae and phalanges)."""
    nn = normaliser_noms(noms)
    prof = _profondeur(parents)
    info = []
    for i, n in enumerate(nn):
        c = _cote_nom(n)
        p = _partie(_sans_cote(n))
        info.append((c, p))
    # ---- VANILLA side from the geometry: mean x of the bones named 'l' and 'r'
    xs = {'l': [], 'r': []}
    for i, (c, p) in enumerate(info):
        if c in xs and p in ('upperarm', 'forearm', 'hand', 'thigh', 'calf', 'foot', 'clavicle'):
            xs[c].append(tetes[i][0])
    vers = {'l': 'l', 'r': 'r'}
    if xs['l'] and xs['r']:
        gx = float(np.mean(xs['l'])) - float(np.mean(xs['r']))
        if gx * cote_vanilla_gauche_x < 0:
            vers = {'l': 'r', 'r': 'l'}
            log('  sides: the rig\'s "left" is at x %+.3f, the game\'s "l" at x < 0 -> '
                'rig left = game r (no mirror, the chain\'s convention)'
                % float(np.mean(xs['l'])))

    def cote_jeu(i):
        """Game side ('l'/'r') of model bone i."""
        c = info[i][0]
        if c in vers:
            return vers[c]
        x = tetes[i][0]
        return 'l' if x * cote_vanilla_gauche_x > 0 else 'r'

    carte = {}
    par_partie = {}
    for i, (c, p) in enumerate(info):
        if p is None:
            continue
        par_partie.setdefault(p, []).append(i)

    def plus_haut(lst):
        return sorted(lst, key=lambda i: prof[i])

    # ---- trunk
    pel = plus_haut(par_partie.get('pelvis', []))
    cous = plus_haut(par_partie.get('neck', []))
    tetes_os = plus_haut(par_partie.get('head', []))
    if pel:
        carte[pel[0]] = 'bip01 pelvis'
    if cous:
        carte[cous[0]] = 'bip01 neck'
    if tetes_os:
        carte[tetes_os[0]] = 'bip01 head'
    # vertebrae: the pelvis -> neck path in the hierarchy, otherwise the "spine" bones by depth
    vert = []
    if pel and cous:
        ch = _ancetres(parents, cous[0])
        if pel[0] in ch:
            vert = [x for x in reversed(ch[:ch.index(pel[0])])]
    if not vert:
        vert = plus_haut(par_partie.get('spine', []))
    vert = [v for v in vert if v not in carte]
    if vert:
        n = len(vert)
        if n == 1:
            choix = {0: 'bip01 spine'}
        elif n == 2:
            choix = {0: 'bip01 spine', 1: 'bip01 spine2'}
        else:
            choix = {0: 'bip01 spine', int(round((n - 1) / 2.0)): 'bip01 spine1', n - 1: 'bip01 spine2'}
        for k, b in choix.items():
            carte[vert[k]] = b
    # ---- limbs
    simples = {'clavicle': 'clavicle', 'upperarm': 'upperarm', 'forearm': 'forearm',
               'hand': 'hand', 'thigh': 'thigh', 'calf': 'calf', 'foot': 'foot'}
    for p, cible in simples.items():
        for i in plus_haut(par_partie.get(p, [])):
            nom = 'bip01 %s %s' % (cote_jeu(i), cible)
            if nom not in carte.values():
                carte[i] = nom
    # pelvis not found by name (Auto-Rig Pro: "root.x"): the common ancestor of the two thighs,
    # if it really is at hip height (not the scene root, sitting on the ground)
    if 'bip01 pelvis' not in carte.values():
        cuisses = [i for i, v in carte.items() if v.endswith(' thigh')]
        if len(cuisses) == 2:
            a1 = [cuisses[0]] + _ancetres(parents, cuisses[0])
            a2 = set([cuisses[1]] + _ancetres(parents, cuisses[1]))
            ac = next((x for x in a1 if x in a2), None)
            tt = np.asarray(tetes, float)
            haut = float(np.ptp(tt[:, int(np.argmax(np.ptp(tt, axis=0)))])) or 1.0
            if ac is not None and ac not in carte and np.linalg.norm(
                    tt[ac] - (tt[cuisses[0]] + tt[cuisses[1]]) / 2) < 0.2 * haut:
                carte[ac] = 'bip01 pelvis'
                log('  pelvis: "%s" (common ancestor of the thighs)' % noms[ac])
    # toes: the BALL of the foot (toebase) first, the tip only if nothing else
    for c in 'lr':
        cand = [i for i in plus_haut(par_partie.get('toe', [])) if cote_jeu(i) == c]
        cand += [i for i in plus_haut(par_partie.get('toe_fin', [])) if cote_jeu(i) == c]
        if cand:
            carte[cand[0]] = 'bip01 %s toe0' % c
            carte_alt = cand[1:]
            for j in carte_alt:
                info[j] = (info[j][0], 'toe_alt')
    # ---- fingers: per hand, each finger = its bones by depth; the first 3 that are not ends
    inv_main = {v: k for k, v in carte.items()}
    mains = {c: inv_main['bip01 %s hand' % c] for c in 'lr' if 'bip01 %s hand' % c in inv_main}
    for c, h in mains.items():
        desc = [i for i in range(len(noms)) if h in _ancetres(parents, i)]
        for D, dg in enumerate(DOIGTS):
            os_d = [i for i in desc if info[i][1] == 'doigt:' + dg]
            os_d = sorted(os_d, key=lambda i: prof[i])
            for k, i in enumerate(os_d[:3]):
                carte[i] = 'bip01 %s finger%d%s' % (c, D, ('', '1', '2')[k])
    return carte


# =============================================================================== geometry
def rot_min(a, b):
    """Smallest rotation taking direction a onto direction b."""
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


def kabsch(X, Y, w):
    """Weighted best rotation taking the vectors X onto Y (Kabsch, no reflection)."""
    H = (X * w[:, None]).T @ Y
    U, _S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
    return Vt.T @ np.diag([1.0, 1.0, d]) @ U.T


# main child to aim each bone at, by preference
ENFANT_PRINCIPAL = {
    'pelvis': ('spine', 'spine1', 'spine2', 'neck'),
    'spine': ('spine1', 'spine2', 'neck'),
    'spine1': ('spine2', 'neck'),
    'spine2': ('neck', 'head'),
    'neck': ('head',),
    'clavicle': ('upperarm',),
    'upperarm': ('forearm',),
    'forearm': ('hand',),
    'hand': ('finger2', 'finger1', 'finger3', 'finger4'),
    'thigh': ('calf',),
    'calf': ('foot',),
    'foot': ('toe0',),
}


def _court(nom_jeu):
    """'bip01 l upperarm' -> 'upperarm'; 'bip01 l finger21' -> 'finger21'."""
    return nom_jeu.split()[-1]


def completer_poids(P, idx, poids):
    """("complete the weights") Vertices WITHOUT rig weights (accessory parented to a bone but
    not skinned, forgotten piece): they take the weights of the nearest skinned vertex.
    Returns (idx, poids, number completed)."""
    W = np.where(idx >= 0, poids, 0.0)
    sans = W.sum(1) <= 1e-9
    if not sans.any() or sans.all():
        return idx, poids, 0
    A = np.asarray(P, np.float32)[~sans]
    ia = np.where(~sans)[0]
    js = np.where(sans)[0]
    idx, poids = idx.copy(), poids.copy()
    for a0 in range(0, len(js), 64):
        bloc = js[a0:a0 + 64]
        X = np.asarray(P, np.float32)[bloc]
        d2 = (X * X).sum(1)[:, None] - 2.0 * X @ A.T + (A * A).sum(1)[None, :]
        near = ia[d2.argmin(1)]
        idx[bloc], poids[bloc] = idx[near], poids[near]
    return idx, poids, int(sans.sum())


def conformer(P, idx, poids, noms, parents, tetes, carte, cibles, kmin=KMIN, kmax=KMAX, log=print,
              sol=None, haut=1):
    """The retargeting. P (n,3); idx/poids (n,K): model bones and weights (idx < 0: empty);
    tetes (m,3): bone heads at rest in P's frame; carte {model bone: game name};
    cibles {game name: (3,)}; sol: height of the vanilla's sole (axis `haut`) -- enables the
    FLAT FOOT. Returns (P2, M (m,4,4), report)."""
    m = len(noms)
    prof = _profondeur(parents)
    ordre = sorted(range(m), key=lambda i: prof[i])
    cibles = dict(cibles)              # the foot may move its toe's target
    M = [None] * m
    R = [None] * m
    rapport = {'os': {}}
    idx, poids, rapport['sommets_completes'] = completer_poids(P, idx, poids)
    if rapport['sommets_completes']:
        log('  %d vertex(es) without rig weights: weights of the nearest skinned vertex'
            % rapport['sommets_completes'])
    Wd = np.where(idx >= 0, poids, -1.0)
    dom = idx[np.arange(len(idx)), Wd.argmax(1)]      # dominant bone of each vertex
    up = np.zeros(3)
    up[haut] = 1.0
    A_des_pieds = {}

    def sous_arbre(i):
        """Bone i and all its descendants."""
        out, pile = {i}, [i]
        while pile:
            x = pile.pop()
            for j in range(m):
                if parents[j] == x and j not in out:
                    out.add(j)
                    pile.append(j)
        return out

    def ancetre_mappe(i):
        """Nearest recognised ancestor of bone i."""
        for a in _ancetres(parents, i):
            if a in carte:
                return a
        return None

    def descendants_mappes(i):
        """The nearest recognised descendants (unrecognised bones are walked through)."""
        out, pile = [], [j for j in range(m) if parents[j] == i]
        while pile:
            j = pile.pop()
            if j in carte:
                out.append(j)
            else:
                pile += [k for k in range(m) if parents[k] == j]
        return out

    # ---- FEET: height of the ankle above the sole. The game's is high (15.5 cm), a rig's often
    # lower (TASM2 mixamo: 11.7). Making up all of it by stretching the foot enlarged it by 33 %;
    # making up none of it sank it 4 cm into the ground. We share: the foot stretches by 12 % at
    # most, and the rest lowers the ankle PIVOT (the foot's target, hence also the end of the
    # calf) -- a pivot a few cm above the anatomical ankle does not show, a foot in the ground
    # does.
    MAX_PIED = 1.12
    reglage_pied = {}
    if sol is not None:
        for i, nom in carte.items():
            if _court(nom) != 'foot' or nom not in cibles:
                continue
            sel = np.isin(dom, list(sous_arbre(i)))
            if sel.sum() < 3:
                continue
            sem = float(P[sel, haut].min())
            hm = float(np.asarray(tetes[i], float) @ up) - sem
            hv = float(np.asarray(cibles[nom], float) @ up) - sol
            if hm <= 1e-3 or hv <= 1e-3:
                continue
            sv = float(np.clip(hv / hm, 1.0 / MAX_PIED, MAX_PIED))
            delta = hv - sv * hm
            cibles[nom] = np.asarray(cibles[nom], float) - delta * up
            reglage_pied[i] = sv
            rapport.setdefault('pieds', {})[nom] = {'cheville_rig_mm': hm * 1000, 'cheville_jeu_mm': hv * 1000,
                                                   'echelle_hauteur': sv, 'pivot_abaisse_mm': delta * 1000}

    racine_mappee = min((i for i in carte), key=lambda i: prof[i]) if carte else None
    for i in ordre:
        if i not in carte:
            continue
        nom = carte[i]
        if nom not in cibles:
            continue
        a = ancetre_mappe(i)
        Rp = R[a] if a is not None and R[a] is not None else np.eye(3)
        h, H = np.asarray(tetes[i], float), np.asarray(cibles[nom], float)
        enf = [j for j in descendants_mappes(i) if carte[j] in cibles]
        court = _court(nom)
        cle = 'spine' if court == 'spine' else court
        if court.startswith('finger') and len(court) == 7:      # finger0..4 -> the next phalanx
            prefs = (court + '1',)
        elif court.startswith('finger') and len(court) == 8 and court[-1] == '1':
            prefs = (court[:-1] + '2',)
        else:
            prefs = ENFANT_PRINCIPAL.get(cle, ())
        princ = None
        for pr in prefs:
            for j in enf:
                if _court(carte[j]) == pr:
                    princ = j
                    break
            if princ is not None:
                break
        if princ is None and len(enf) == 1:
            princ = enf[0]
        A_pied = None
        if court == 'foot' and sol is not None:
            # WARNING: FLAT FOOT. Aiming at the game's toe makes the foot PIVOT: a rig's "ball"
            # (mixamo toebase, in the middle of the foot's thickness) is not `toe0` (flush with
            # the sole). Measured on the TASM2: tip 1.6 cm BELOW the ground, heel 4 cm above.
            # So the foot only turns around the VERTICAL, stretches horizontally towards the
            # game's toe, and is scaled in height to put its sole on the vanilla's. The toe
            # follows the foot (its target becomes the point where the foot carries it).
            Ri, k, d = np.eye(3), 1.0, None
            S = np.eye(3)
            if princ is not None:
                c = np.asarray(tetes[princ], float)
                C = np.asarray(cibles[carte[princ]], float)
                fm, fv = (c - h) - ((c - h) @ up) * up, (C - H) - ((C - H) @ up) * up
                if np.linalg.norm(fm) > 1e-6 and np.linalg.norm(fv) > 1e-6:
                    Ri = rot_min(fm, fv)
                    kh = float(np.clip(np.linalg.norm(fv) / np.linalg.norm(fm), 0.75, 1.35))
                    f = fm / np.linalg.norm(fm)
                    S = S + (kh - 1.0) * np.outer(f, f)
                    k = kh
            sv = reglage_pied.get(i, 1.0)
            S = S + (sv - 1.0) * np.outer(up, up)
            A_pied = Ri @ S
            if princ is not None:
                cibles[carte[princ]] = H + A_pied @ (np.asarray(tetes[princ], float) - h)
            rapport.setdefault('pieds', {}).setdefault(nom, {})['allongement'] = k
        if A_pied is None and (not enf or princ is None):
            Ri, k, d = Rp, 1.0, None
        elif A_pied is None:
            if len(enf) >= 2:
                X = np.array([Rp @ (np.asarray(tetes[j], float) - h) for j in enf])
                Y = np.array([np.asarray(cibles[carte[j]], float) - H for j in enf])
                w = np.array([3.0 if j == princ else 1.0 for j in enf])
                ok = (np.linalg.norm(X, axis=1) > 1e-6) & (np.linalg.norm(Y, axis=1) > 1e-6)
                R0 = kabsch(X[ok], Y[ok], w[ok]) if ok.sum() >= 2 else np.eye(3)
                Ri = R0 @ Rp
            else:
                Ri = Rp
            c = np.asarray(tetes[princ], float)
            C = np.asarray(cibles[carte[princ]], float)
            Ri = rot_min(Ri @ (c - h), C - H) @ Ri
            L0, L1 = np.linalg.norm(c - h), np.linalg.norm(C - H)
            k = float(np.clip(L1 / max(L0, 1e-9), kmin, kmax)) if L0 > 1e-6 else 1.0
            d = (c - h) / max(L0, 1e-12)
        if A_pied is not None:
            A = A_pied
            A_des_pieds[i] = A_pied
        elif court == 'toe0' and a in A_des_pieds and not enf:
            A = A_des_pieds[a]          # the toe keeps the foot's scale: no step at the joint
        else:
            S = np.eye(3) if d is None else np.eye(3) + (k - 1.0) * np.outer(d, d)
            A = Ri @ S
        T = np.eye(4)
        T[:3, :3] = A
        T[:3, 3] = H - A @ h
        M[i], R[i] = T, Ri
        ang = np.degrees(np.arccos(np.clip((np.trace(Ri @ Rp.T) - 1) / 2, -1, 1)))
        rapport['os'][nom] = {'deplacement_mm': float(np.linalg.norm(H - h) * 1000),
                              'rotation_deg': float(ang), 'allongement': float(k)}
    # unrecognised bones (or bones without a target): they follow their recognised ancestor;
    # root: the pelvis
    base = M[racine_mappee] if racine_mappee is not None and M[racine_mappee] is not None else np.eye(4)
    for i in ordre:
        if M[i] is None:
            a = ancetre_mappe(i)
            M[i] = M[a] if a is not None and M[a] is not None else base
    M = np.array(M)
    # linear skinning of the vertices with the model's own weights
    W = np.where(idx >= 0, poids, 0.0).astype(np.float64)
    s = W.sum(1, keepdims=True)
    sans = (s[:, 0] <= 1e-9)
    W = W / np.maximum(s, 1e-12)
    Ph = np.c_[P, np.ones(len(P))]
    P2 = np.zeros((len(P), 3))
    for kk in range(idx.shape[1]):
        Mk = M[np.maximum(idx[:, kk], 0)]
        P2 += W[:, kk:kk + 1] * np.einsum('nij,nj->ni', Mk, Ph)[:, :3]
    if sans.any():
        P2[sans] = (Ph[sans] @ base.T)[:, :3]
    rapport['sommets_sans_poids'] = int(sans.sum())
    rapport['os_reconnus'] = len(carte)
    return P2, M, rapport


# =============================================================================== fingers
def etiquettes_doigts(idx, poids, carte, parents, seuil=0.25):
    """("finger labels") For each vertex: (side 0 = l / 1 = r / -1, finger 0..4 or -1, share
    of that finger, share of hand + fingers), from the weights of the MODEL'S RIG.
    Unrecognised fingertips count for their finger."""
    m = len(parents)
    doigt_os = {}
    main_os = {}
    for i, nom in carte.items():
        c = _court(nom)
        cote = nom.split()[1] if len(nom.split()) > 2 else ''
        if c.startswith('finger'):
            doigt_os[i] = (cote, int(c[6]))
        elif c == 'hand':
            main_os[i] = cote
    # unrecognised descendants of a phalanx: same finger
    for i in range(m):
        if i in carte:
            continue
        for a in _ancetres(parents, i):
            if a in doigt_os:
                doigt_os[i] = doigt_os[a]
                break
            if a in carte:
                break
    n = len(idx)
    W = np.where(idx >= 0, poids, 0.0).astype(np.float64)
    W = W / np.maximum(W.sum(1, keepdims=True), 1e-12)
    part = np.zeros((n, 2, 5))
    main = np.zeros((n, 2))
    for kk in range(idx.shape[1]):
        for i, (c, D) in doigt_os.items():
            sel = idx[:, kk] == i
            if sel.any():
                part[sel, 0 if c == 'l' else 1, D] += W[sel, kk]
        for i, c in main_os.items():
            sel = idx[:, kk] == i
            if sel.any():
                main[sel, 0 if c == 'l' else 1] += W[sel, kk]
    tot = part.reshape(n, -1)
    best = tot.argmax(1)
    val = tot.max(1)
    cote = np.where(val >= seuil, np.where(best < 5, 0, 1), -1)        # 0 = l, 1 = r
    doigt = np.where(val >= seuil, best % 5, -1)
    zone = part.sum(2).max(1) + main.max(1)
    return cote.astype(np.int8), doigt.astype(np.int8), val.astype(np.float32), zone.astype(np.float32)


# =============================================================================== vanilla
def cibles_depuis_skel(chemin_skel, fmt):
    """("targets from the skeleton") {vanilla bone name: joint} at rest, in the .mesh's frame
    (same convention as mains_poings.Squelette.joint)."""
    sk = fmt.parse_skeleton(chemin_skel)
    out = {}
    for b in sk.bones:
        mm = np.array(b.inverse_values, np.float64).reshape(4, 4).copy()
        mm[:3, 3] = 0.0
        mm[3, 3] = 1.0
        out[b.name] = np.linalg.inv(mm).T[:3, 3]
    return out


def resume(rapport, carte, log=print):
    """Log a summary of the conformation report ("résumé" = summary)."""
    os_ = rapport['os']
    tronc = [n for n in os_ if 'finger' not in n]
    if not tronc:
        return
    dep = [os_[n]['deplacement_mm'] for n in tronc]
    k = [os_[n]['allongement'] for n in tronc]
    log('  conformation: %d bones recognised (%d fingers); joint displacement median %.0f mm, '
        'max %.0f mm; stretches %.2f..%.2f'
        % (len(carte), sum(1 for n in carte.values() if 'finger' in n), float(np.median(dep)),
           float(np.max(dep)), float(np.min(k)), float(np.max(k))))
    for n, pd in sorted(rapport.get('pieds', {}).items()):
        if 'echelle_hauteur' in pd:
            log('     %-18s ankle %3.0f mm above the sole (game %3.0f): foot x%.2f in '
                'height, pivot lowered by %2.0f mm, sole on the ground'
                % (n, pd['cheville_rig_mm'], pd['cheville_jeu_mm'], pd['echelle_hauteur'],
                   pd['pivot_abaisse_mm']))
    for n in ('bip01 pelvis', 'bip01 spine2', 'bip01 neck', 'bip01 head', 'bip01 l upperarm',
              'bip01 l forearm', 'bip01 l hand', 'bip01 l thigh', 'bip01 l calf', 'bip01 l foot'):
        if n in os_:
            o = os_[n]
            log('     %-18s moved %4.0f mm, turned %5.1f deg, stretched x%.2f'
                % (n, o['deplacement_mm'], o['rotation_deg'], o['allongement']))
