# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""decoupe_sections.py - never more than 65,535 vertices per section, never 32-bit indices.

("découper les sections" = "split the sections".) Last step of winding_fix.py, hence run on
every delivered player mesh, AFTER mains_poings.py. Also usable by hand (see USAGE).

THE DEFECT, MEASURED (2026-10-08, investigation in sauvegardes/2026-10-08_detail/limites_moteur)
-------------------------------------------------------------------------------------------
The upload of meshes to the GPU (Game.exe 0x8CF1E0) creates ONE INDEX16 index buffer per mesh. A
section marked index_size=4 is copied into it keeping only the low word of each index (loop at
0x8CF373): every index >= 65,536 wraps modulo 65,536, triangles join the wrong vertices, and
nothing reports it. Yet our writers switch to 32 bits as soon as a section exceeds 65,535
vertices: the toolkit's sm3_mesh_writer (Blender export of the 000 and the 001),
correctifs_blender/blacksuit_mesh_writer.py (the 001 of transplanter_lod, the black suit, RvB) and
tools/mains_poings.py (body and hand sections). Real case: raimi_nodecim, 156,115 vertices in one
section, comes out torn.

The engine itself accepts as many sections as we like (xeSM3: 1 to 256), and a single VB / IB
per mesh, with no vertex ceiling. So it is enough to SPLIT.

THE FIX
-------
1. ch_spiderman000/001 (0xAC92103D/E): xeSM3 gives the material by REFERENCE (LEGACY-MAP table,
   xeSM3.dll 0x10011650); the vanilla model already has two sections with the same reference.
   Every section with more than 65,535 vertices is split into pieces of at most 65,535 vertices,
   SAME reference, 16-bit indices, in its place in the section order.
   - The pieces follow a breadth-first walk over the surface. It depends only on the TOPOLOGY:
     the 001, written in another frame, is split exactly like the 000.
   - A seam vertex is written into every piece that uses it, with ITS OWN BYTES: every piece
     keeps the bone palette of the original section (48 bones at most), so even the local bone
     indices are identical. Same positions, same weights: no crack is possible.
   - Every piece keeps the bounding box and sphere of the original section: larger than the
     piece, so never culled by mistake (the mesh is animated; a box tight at rest would be wrong
     as soon as the arm moves).
2. Any other hash (black suit 0xABE79B1C/D, Venom...): material by section INDEX (0x100117FB),
   only one real section possible. Above 65,535 vertices we REFUSE, with a message that says
   what to do, rather than deliver a torn mesh.
3. A section of at most 65,535 vertices but written with 32-bit indices is rewritten in 16 bits:
   its indices fit, and the game was already truncating them without loss.
4. BLOCKING CHECK on the written bytes: a section above 65,535 vertices, 32-bit indices, more
   than 256 sections or more than 64 MiB (xeSM3's limits) -> RefusDecoupe.

A mesh that already complies is NOT rewritten: a light model comes out byte for byte as before.

The 001 receives the 000's split: trace file `<000>.mesh.decoupe.npz` (never inside a .apkf
folder), reused when the triangles of the sections to split are the same (sha256 key).

USAGE
    python tools/decoupe_sections.py <input.mesh> [--sortie <output.mesh>] [--trace <npz>]
            [--trace-de <npz of the 000>]
    python tools/decoupe_sections.py --controle <file.mesh> [...]
            re-read only: exit code 1 if a section exceeds 65,535 vertices or uses 32 bits
AUTOMATIC CALL: winding_fix.py, after mains_poings, on every mesh it processes.
(sortie = output, trace-de = "trace of", controle = check.)
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))


def _charger_mp():
    """mains_poings, next to this file: toolkit reader and identical rewriting of a .mesh.
    Reuses the one winding_fix already loaded (same path)."""
    chemin = os.path.join(ICI, 'mains_poings.py')
    mp = sys.modules.get('mains_poings')
    if mp is None or os.path.abspath(getattr(mp, '__file__', '')) != chemin:
        s = importlib.util.spec_from_file_location('mains_poings', chemin)
        mp = importlib.util.module_from_spec(s)
        sys.modules['mains_poings'] = mp
        s.loader.exec_module(mp)
    return mp


mp = _charger_mp()
fmt = mp.fmt

# ------------------------------------------------------------------------------- constants
# WARNING: 65,535, not 65,536: indices 0..65,535 fit in 16 bits, but all our writers switch to
# 32 bits from 65,536 vertices on. We stay below their threshold.
MAX_SOMMETS = 0xFFFF            # max vertices per section
MAX_OS = 48                     # xeSM3.dll 0x10011D14 refuses a palette of more than 48 bones
MAX_SECTIONS = 256              # xeSM3.dll 0x10011B2C
MAX_OCTETS = 64 * 1024 * 1024   # xeSM3.dll 0x10011A93: a loose .mesh of 64 MiB at most
PAR_REFERENCE = tuple(mp.PAR_REFERENCE)    # hashes whose material is given by reference
NOMS = {0xAC92103D: 'ch_spiderman000', 0xAC92103E: 'ch_spiderman001',
        0xABE79B1C: 'ch_blacksuit000', 0xABE79B1D: 'ch_blacksuit001',
        0xBF11C1BF: 'ch_venom000'}
# the 001 reuses the 000's split (trace written next to the 000)
FRERE_000 = {0xAC92103E: '0xAC92103D.ch_spiderman000.mesh'}
ECRIT_TRACE = (0xAC92103D,)     # meshes that write a trace


class RefusDecoupe(RuntimeError):
    """A mesh we do not deliver: it would come out torn in game, or xeSM3 would refuse it."""


def log_defaut(*x):
    print('[sections]', *x, flush=True)


def nom(h):
    """'0x<hash> (<name>)' for messages."""
    return '0x%08X (%s)' % (h, NOMS.get(h, 'mesh'))


# ------------------------------------------------------------------------------- check
def problemes(m, taille=None):
    """("problems") What would break in game or make xeSM3 refuse the file. Empty = deliverable."""
    p = []
    for s in m.sections:
        if s.vertex_count > MAX_SOMMETS:
            p.append('section %d: %d vertices (the game only addresses %d per section)'
                     % (s.index, s.vertex_count, MAX_SOMMETS))
        if s.index_size != 2:
            p.append('section %d: %d-byte indices (the game keeps only the low 16 bits)'
                     % (s.index, s.index_size))
    if len(m.sections) > MAX_SECTIONS:
        p.append('%d sections (xeSM3 accepts %d)' % (len(m.sections), MAX_SECTIONS))
    taille = len(m.raw) if taille is None else taille
    if taille > MAX_OCTETS:
        p.append('%d bytes (xeSM3 refuses a loose .mesh larger than 64 MiB)' % taille)
    return p


def controle(chemin):
    """The blocking check alone, on a file: returns the list of problems."""
    return problemes(fmt.parse_mesh(chemin), os.path.getsize(chemin))


def message_index(m, grosses):
    """The refusal message for a mesh whose material is chosen by section index (also shown by
    blacksuit_runner.py)."""
    s = max(grosses, key=lambda x: x.vertex_count)
    return ('%s: xeSM3 chooses this mesh\'s material by section INDEX, so it can only have one '
            'real section, and that section has %d vertices. The game only addresses %d per '
            'section (16-bit indices: above that it truncates silently and the model comes out '
            'torn). Mod NOT delivered. What to do: reduce the model below %d vertices (Decimate '
            'modifier in Blender), or convert it as the red suit (ch_spiderman000/001 accept '
            'several sections).' % (nom(m.filename_hash), s.vertex_count, MAX_SOMMETS, MAX_SOMMETS))


# ------------------------------------------------------------------------------- splitting
def ordre_parcours(faces, nv):
    """("walk order") The triangles in the order of a breadth-first walk over the surface
    (shared vertices).

    Depends ONLY on the topology, never on positions: the 001 (another frame) gives the same
    order as the 000. Connected components are taken in the order of their first triangle, each
    one from that triangle to its end: a piece cuts only one component at a time, hence few seam
    vertices. Layers are walked entirely, triangles of a layer in file order: deterministic."""
    nt = len(faces)
    plat = faces.reshape(-1)
    nb = np.bincount(plat, minlength=nv).astype(np.int64)      # triangles per vertex
    debut = np.zeros(nv + 1, np.int64)                         # CSR start of each vertex
    np.cumsum(nb, out=debut[1:])
    tri_de = np.argsort(plat, kind='stable') // 3          # triangles sorted by vertex
    vu_t = np.zeros(nt, bool)                               # triangles already reached
    vu_s = np.zeros(nv, bool)                               # vertices already expanded
    ordre = []
    for g in range(nt):
        if vu_t[g]:
            continue
        vu_t[g] = True
        front = np.array([g], np.int64)
        while len(front):
            ordre.append(front)
            s = np.unique(faces[front].reshape(-1))
            s = s[~vu_s[s]]
            vu_s[s] = True
            n = nb[s]
            total = int(n.sum())
            if not total:
                break
            idx = np.repeat(debut[s] - (np.cumsum(n) - n), n) + np.arange(total)
            cand = tri_de[idx]
            cand = np.unique(cand[~vu_t[cand]])
            vu_t[cand] = True
            front = cand
    return np.concatenate(ordre) if ordre else np.zeros(0, np.int64)


def remplir(ordre, faces, nv, max_sommets=MAX_SOMMETS):
    """("fill") Piece number of each triangle: fill in walk order up to `max_sommets` DISTINCT
    vertices per piece, seam included (a vertex already taken by an earlier piece counts again:
    it will be duplicated there)."""
    F = faces.tolist()
    morceau = np.zeros(len(F), np.int64)
    marque = [-1] * nv              # last piece each vertex was counted in
    k, n = 0, 0
    for t in ordre.tolist():
        a, b, c = F[t]
        neufs = (marque[a] != k) + (b != a and marque[b] != k) + (c != a and c != b and marque[c] != k)
        if n + neufs > max_sommets:
            k += 1
            n = 0
            neufs = len({a, b, c})
        marque[a] = marque[b] = marque[c] = k
        n += neufs
        morceau[t] = k
    return morceau


def cle_sections(m, grosses):
    """Fingerprint of what decides the split: place, vertex count and triangles of each section
    to split. The 001 recomputes it and reuses the trace only if it matches."""
    h = hashlib.sha256()
    for s in grosses:
        h.update(np.array([s.index, s.vertex_count], '<i8').tobytes())
        h.update(np.asarray(mp.faces_section(m, s), '<i4').tobytes())
    return h.hexdigest()


def _bornes(s):
    """Bounds of a section: centre (3), sphere radius, half-box (3)."""
    return tuple(s.mesh_offset) + (s.sphere_radius,) + tuple(s.mesh_bbox)


def _copie_16(m, s):
    """The section as it is; its indices rewritten in 16 bits if they were 32 (they fit)."""
    d = mp.copie_section(m, s)
    d['faces'] = np.asarray(d['faces']).reshape(-1)
    if d['index_size'] != 2:
        if s.vertex_count > MAX_SOMMETS or (len(d['faces']) and int(d['faces'].max()) > 0xFFFF):
            raise RefusDecoupe('section %d: 32-bit indices that do not fit in 16' % s.index)
        d['index_size'] = 2
    return d


def decouper(entree, sortie=None, trace=None, trace_de=None, log=log_defaut):
    """("split") The whole job. Returns a report (dict). Raises RefusDecoupe if the mesh cannot
    be delivered. Writes `sortie` only after ALL the checks, and only if something must change."""
    sortie = sortie or entree
    m = fmt.parse_mesh(entree)
    rap = {'entree': entree, 'sortie': sortie, 'hash': '0x%08X' % m.filename_hash,
           'sections_entree': [(s.index, s.vertex_count, s.index_size) for s in m.sections]}
    grosses = [s for s in m.sections if s.vertex_count > MAX_SOMMETS]                 # too many vertices
    larges = [s for s in m.sections if s.index_size != 2 and s.vertex_count <= MAX_SOMMETS]  # 32-bit only

    if not grosses and not larges:
        p = problemes(m)
        if p:
            raise RefusDecoupe('%s: %s' % (nom(m.filename_hash), '; '.join(p)))
        if trace and os.path.isfile(trace):
            os.remove(trace)                    # old trace from a previous build
        if os.path.abspath(sortie) != os.path.abspath(entree):
            with open(sortie, 'wb') as f:
                f.write(m.raw)
        rap['etat'] = 'conforme'
        log('%s: %d section(s), at most %d vertices, 16-bit indices -> nothing to split'
            % (os.path.basename(entree), len(m.sections), max(s.vertex_count for s in m.sections)))
        return rap

    if grosses and m.filename_hash not in PAR_REFERENCE:
        raise RefusDecoupe(message_index(m, grosses))
    for s in grosses:
        if len(s.bone_palette) > MAX_OS:
            raise RefusDecoupe('section %d: palette of %d bones (xeSM3 accepts %d): to be fixed '
                               'upstream, not here' % (s.index, len(s.bone_palette), MAX_OS))
    if not mp.sait_reecrire(m):
        raise RefusDecoupe('%s: unknown .mesh layout, identical rewriting fails: '
                           'it cannot be split safely' % nom(m.filename_hash))

    # ---- the split: reused from the 000 (same topology) or computed
    cle = cle_sections(m, grosses)
    repris = None
    if trace_de and os.path.isfile(trace_de):
        with np.load(trace_de) as z:            # closed right away: Windows locks the .npz
            if str(z['cle']) == cle:
                repris = {int(i): np.array(z['morceau_%d' % int(i)]) for i in z['sections']}
        if repris is not None:
            log('split reused from %s: same sections to split, same triangles -> cut like '
                'the 000' % os.path.basename(trace_de))
        else:
            log('!! trace %s ignored (different sections or triangles): split computed'
                % os.path.basename(trace_de))
    rap['decoupage_repris'] = repris is not None

    plan = {}                       # section index -> (L, F, morceau, [(tk, ids)])
    for s in grosses:
        L = mp.lignes(m, s)         # raw vertex rows ("lignes") of the section
        F = mp.faces_section(m, s)
        if len(F) and (F.min() < 0 or F.max() >= s.vertex_count):
            raise RefusDecoupe('section %d: index outside the vertices' % s.index)
        if repris is not None:
            morceau = np.asarray(repris[s.index], np.int64)
        else:
            morceau = remplir(ordre_parcours(F, s.vertex_count), F, s.vertex_count, MAX_SOMMETS)
        lots = []
        for k in range(int(morceau.max()) + 1 if len(morceau) else 0):
            tk = np.where(morceau == k)[0]          # file order kept within the piece
            if len(tk):
                lots.append((tk, np.unique(F[tk])))
        plan[s.index] = (L, F, morceau, lots)

    # ---- output sections, in the original order
    sorties, origine = [], []
    for s in m.sections:
        if s.index not in plan:
            sorties.append(_copie_16(m, s))
            origine.append((s, None))
            continue
        L, F, morceau, lots = plan[s.index]
        for tk, ids in lots:
            remap = np.full(s.vertex_count, -1, np.int64)
            remap[ids] = np.arange(len(ids))
            sorties.append(dict(
                ref=s.material_ref_serialized, palette=list(s.bone_palette), lignes=L[ids],
                faces=remap[F[tk]].reshape(-1), bornes=_bornes(s), decl=s.decl,
                stride=s.vertex_stride,
                # a strip (type 5) is written back as a triangle list (type 4)
                prim=(4, 1) if s.primitive_type == 5 else (s.primitive_type, s.primitive_unknown),
                inc=(s.unknown_30, s.unknown_38, s.unknown_40, s.schema_unknown), index_size=2))
            origine.append((s, (tk, ids)))
    octets = mp.reecrire(m, sorties)

    # ---- checks BEFORE writing anything
    tmp = sortie + '.tmp_decoupe'
    with open(tmp, 'wb') as f:
        f.write(octets)
    try:
        ctl = controler(tmp, m, origine, plan, log)
    except Exception:
        os.remove(tmp)
        raise
    rap['controles'] = ctl
    if not all(v for v in ctl.values() if isinstance(v, bool)):
        os.remove(tmp)
        # WARNING: the problems IN PLAIN WORDS: a model still above 64 MiB once split (about
        # 1 M vertices) otherwise only said "bloquant_65535_16bits: False", which misled.
        raise RefusDecoupe('split check failed: %s%s'
                           % ({k: v for k, v in ctl.items() if v is False},
                              ' -- ' + '; '.join(ctl['problemes']) if ctl.get('problemes') else ''))
    os.replace(tmp, sortie)

    if trace and plan:
        np.savez_compressed(trace, cle=np.array(cle), sections=np.array(sorted(plan), np.int64),
                            **{'morceau_%d' % i: plan[i][2] for i in plan})
        rap['trace'] = trace
    elif trace and os.path.isfile(trace):
        os.remove(trace)                        # nothing split: no stale trace
    rap['etat'] = 'ecrit'
    rap['sections_sortie'] = ctl['sections']
    rap['taille'] = os.path.getsize(sortie)
    for i, (L, F, morceau, lots) in plan.items():
        log('section %d (%d vertices, %d triangles) split into %d: %s vertices; %d copied '
            'seam vertex(es), byte for byte'
            % (i, m.sections[i].vertex_count, len(F), len(lots),
               ' + '.join(str(len(ids)) for tk, ids in lots),
               sum(len(ids) for tk, ids in lots) - len(np.unique(F))))
    if larges:
        log('32-bit indices rewritten as 16-bit: section(s) %s (fewer than 65,536 vertices)'
            % ', '.join(str(s.index) for s in larges))
    log('WROTE %s: %d sections (at most %d vertices), 16-bit indices, %d bytes'
        % (os.path.basename(sortie), len(ctl['sections']), max(x[0] for x in ctl['sections']),
           rap['taille']))
    return rap


def controler(chemin, m_av, origine, plan, log=log_defaut):
    """("check") Re-read of the WRITTEN bytes, with the toolkit's reader. Any false boolean =
    refusal. The keys are French and kept (they appear in the log and in the report)."""
    m = fmt.parse_mesh(chemin)
    c = {}
    # header identity: everything but the section-table pointer area must be unchanged
    c['relecture'] = (len(m.sections) == len(origine) and
                      m.raw[0x00:0x0C] == m_av.raw[0x00:0x0C] and
                      m.raw[0x14:0x50] == m_av.raw[0x14:0x50])
    c['reecriture_a_l_identique'] = bool(mp.sait_reecrire(m))
    inchangees = touchees = True
    morceaux_ok = True
    couverture = {i: [] for i in plan}
    for s, (s0, lot) in zip(m.sections, origine):
        meme = (s.material_ref_serialized == s0.material_ref_serialized and
                s.bone_palette == s0.bone_palette and s.vertex_stride == s0.vertex_stride and
                s.decl == s0.decl and _bornes(s) == _bornes(s0) and s.index_size == 2)
        if lot is None:
            inchangees &= bool(meme and bytes(mp.lignes(m, s)) == bytes(mp.lignes(m_av, s0)) and
                               np.array_equal(mp.faces_section(m, s), mp.faces_section(m_av, s0)))
            continue
        tk, ids = lot
        L, F = plan[s0.index][0], plan[s0.index][1]
        f = mp.faces_section(m, s)
        # WARNING: same BYTES for every vertex, seam included (palette kept: even the local bone
        # indices), and every triangle identical, winding included.
        touchees &= bool(meme and s.vertex_count == len(ids) and
                         bytes(mp.lignes(m, s)) == bytes(L[ids]) and
                         len(f) == len(tk) and np.array_equal(ids[f], F[tk]))
        morceaux_ok &= bool(s.vertex_count <= MAX_SOMMETS)
        couverture[s0.index].append(lot)
    c['sections_inchangees_a_l_octet'] = bool(inchangees)
    c['morceaux_octets_et_triangles'] = bool(touchees)
    c['morceaux_65535'] = bool(morceaux_ok)
    tous_tri = tous_som = True
    for i, lots in couverture.items():
        F = plan[i][1]
        t = np.sort(np.concatenate([tk for tk, ids in lots])) if lots else np.zeros(0, np.int64)
        tous_tri &= bool(np.array_equal(t, np.arange(len(F))))
        v = np.unique(np.concatenate([ids for tk, ids in lots])) if lots else np.zeros(0, np.int64)
        tous_som &= bool(np.array_equal(v, np.unique(F)))
    c['chaque_triangle_une_fois'] = bool(tous_tri)
    c['tous_les_sommets'] = bool(tous_som)
    c['palettes_48'] = all(len(s.bone_palette) <= MAX_OS for s in m.sections)
    p = problemes(m, os.path.getsize(chemin))
    c['bloquant_65535_16bits'] = not p
    if p:
        c['problemes'] = p
    c['sections'] = [(s.vertex_count, len(set(s.bone_palette)), '0x%X' % s.material_ref_serialized)
                     for s in m.sections]
    log('checks: %s' % ', '.join('%s=%s' % (k, v) for k, v in c.items()))
    return c


# ------------------------------------------------------------------------------- hook
def apres_mains(chemin, log=log_defaut):
    """("after the hands") Called by winding_fix.py, as its last step, on every mesh it
    processes. Writes in place, after the checks. Raises RefusDecoupe if the mesh cannot be
    delivered."""
    m = fmt.parse_mesh(chemin)
    dossier = os.path.dirname(os.path.abspath(chemin))
    # WARNING: never a trace inside a mod folder (.apkf): xeSM3 reads everything it finds there.
    dans_mod = dossier.lower().endswith('.apkf')
    trace_de = trace = None
    if m.filename_hash in FRERE_000:
        t = os.path.join(dossier, FRERE_000[m.filename_hash] + '.decoupe.npz')
        trace_de = t if os.path.isfile(t) else None
    if m.filename_hash in ECRIT_TRACE and not dans_mod:
        trace = chemin + '.decoupe.npz'
    return decouper(chemin, chemin, trace=trace, trace_de=trace_de, log=log)


def main():
    ap = argparse.ArgumentParser(
        description='No section with more than 65,535 vertices, never 32-bit indices.')
    ap.add_argument('entree', nargs='+')
    ap.add_argument('--sortie', default='', help='default: in place')
    ap.add_argument('--trace', default='', help='where to write the split (for the 001)')
    ap.add_argument('--trace-de', default='', help='split of the 000 to reuse')
    ap.add_argument('--controle', action='store_true',
                    help='re-read only: exit code 1 if a file is not deliverable')
    A = ap.parse_args()
    if A.controle:
        code = 0
        for chemin in A.entree:
            p = controle(chemin)
            print('%s: %s' % (os.path.basename(chemin), 'OK' if not p else 'REFUSED -- ' + '; '.join(p)))
            code |= bool(p)
        return code
    if len(A.entree) != 1:
        ap.error('only one file to split at a time')
    try:
        decouper(A.entree[0], A.sortie or None, A.trace or None, A.trace_de or None)
    except RefusDecoupe as e:
        print('!! REFUSED: %s' % e, flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
