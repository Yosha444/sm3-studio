# SPDX-License-Identifier: GPL-3.0-or-later
"""transplanter_lod.py - write one .mesh file from the COMPLETE geometry of another ("transplant").

Where it sits: stage `lod` of sm3_convertir.py. The suit has two models: ch_spiderman000.mesh (the
"000", the player model the converter builds) and ch_spiderman001.mesh (the "001", a second model
of the same suit, used by the game in other situations, with its own vertex layout and its own
frame). The converter calls this script to write the REAL 001 from the finished 000:

    --source <build>/0xAC92103D.ch_spiderman000.mesh   --gabarit <vanilla>/...001.mesh
    --skel-source <vanilla>/...000.skel   --skel-cible <vanilla>/...001.skel
    --repere vers001 --material-ref 0x560 --cible 001 --schema 3 --lu-en 1000

Every vertex, seam, UV and weight of the source is re-encoded with the toolkit-based writer
correctifs_blender/blacksuit_mesh_writer.py into the file layout of the template (--gabarit). Bone indices are
mapped from one skeleton to the other by bone-name hash, and positions/normals are moved into the
target frame.

Why the whole geometry rather than a UV transfer (the reason this script was first written, to
repair TSGAMING264's suit, whose 000 was rebuilt from his 001): on a UV seam a vertex is
DUPLICATED - same position, two UVs. His 001 had 4845 vertices against 4757 for his 000, so the
seams were not cut at the same places. Measured:

    positions of the 001 carrying several different UVs: 697 (1466 vertices, 30 % of the model)
    vertices of the 000 landing on one of those positions: 456 / 4757 (9.6 %)

For those 456, a nearest-neighbour match picks a UV AT RANDOM between the two sides of the seam,
which draws a stray line along every seam, on the render as in game. Taking the source mesh whole
(its vertices, seams, UVs and weights) removes the ambiguity: UVs and duplicates come from the
same mesh.

Reads:  --source, --gabarit (template .mesh whose layout and filename hash are reused),
        --skel-source / --skel-cible, optionally --reference (a mesh to align onto).
Writes: --out, then prints a per-section check of the written bytes.

Frames: (x, y, z)_001 = (z, y + 1.199, -x)_000, measured on TWO independent models (--repere
vers001; vers000 is the inverse). The converter's final check (sm3_convertir.verifier) tests the
same relation on the delivered files.

Pitfalls handled here:
  * The frame change is a pure axis permutation with signs; its determinant is printed. A
    negative determinant would be a mirror (winding inverted).
  * Normals, tangents and binormals get the rotation, never the offset.
  * After writing, the signed volume and the outward-normal score are compared with the vanilla
    signs (-0.116 / +0.229); an inverted model is flipped back (triangles and normals).
  * The toolkit writes UVs * 1024 while the suit's vertex shader divides by 1000: the writer's
    default divisor is patched to --uv-divisor.
  * Vertex colour: --couleur noir (black, 0,0,0,255) is what the vanilla model carries on 29,674
    of its 55,180 vertices (every vertex of 8 of its 10 sections, including the one a suit replaces); TSGAMING264's mod shipped WHITE, which adds light to the whole body
    (it "lets light through"). In the converter the colour is overwritten afterwards anyway with
    the value of qualite.json (sm3_convertir.appliquer_couleur_hq).

French names: gabarit = template, cible = target, repere = frame, couleur = colour,
lu en = read with (UV divisor used to READ the source).

    python transplanter_lod.py --source <...001.mesh> --gabarit <vanilla 000.mesh>
            --skel-source <...001.skel> --skel-cible <...000.skel> --out <...>
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
from sm3_sans_blender import fmt, normales_sortantes, volume_signe  # noqa: E402
# correctifs_blender/blacksuit_mesh_writer.py (a modified copy of TSGAMING264's GPL writer: the
# folder correctifs_blender/ holds every file derived from his code) imports
# `sm3_blender_toolkit.sm3_format`: that only works after sm3_sans_blender (imported above) has
# mounted the fake `sm3_blender_toolkit` package. Inside SM3 Studio.exe the writer is bundled next
# to this file instead (see construire/SM3Studio.spec).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'correctifs_blender'))
import blacksuit_mesh_writer as mw


def log(*x):
    print('[transplant]', *x)


def repere(Psrc, Pcible):
    """Signed axis permutation + offset that bring the source onto the target.

    Returns (median distance, permutation, signs, offset)."""
    import itertools
    ech = np.random.default_rng(0).choice(len(Pcible), size=min(400, len(Pcible)), replace=False)
    meilleur = None
    for perm in itertools.permutations(range(3)):
        for sg in itertools.product((1, -1), repeat=3):
            Q = Psrc[:, perm] * np.array(sg, np.float64)
            d = (Pcible.min(0) + Pcible.max(0)) / 2 - (Q.min(0) + Q.max(0)) / 2
            dd = np.linalg.norm(Pcible[ech, None, :] - (Q + d)[None, :, :], axis=2).min(1)
            s = float(np.median(dd))
            if meilleur is None or s < meilleur[0]:
                meilleur = (s, perm, sg, d)
    return meilleur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True, help='the .mesh whose geometry is taken')
    ap.add_argument('--gabarit', required=True, help='template: the vanilla .mesh whose file layout is written')
    ap.add_argument('--reference', default='', help='a .mesh to align the source onto')
    ap.add_argument('--repere', default='auto', choices=['auto', 'vers001', 'vers000'],
                    help="frame change applied when there is no --reference. Measured on TWO "
                         "independent models: (x, y, z)_001 = (z, y + 1.199, -x)_000.")
    ap.add_argument('--skel-source', required=True)
    ap.add_argument('--skel-cible', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--material-ref', default='0x614')
    ap.add_argument('--couleur', default='noir', choices=['noir', 'source'],
                    help="vertex colour: noir = black. VANILLA = BLACK (0,0,0,255) on 29,674 of "
                         "its 55,180 vertices (8 of its 10 sections); TSGAMING264's mod ships WHITE. White adds light to "
                         "the whole body -- the suit seemed to \"let light through\".")
    ap.add_argument('--cible', default='000', choices=['000', '001'])
    ap.add_argument('--schema', type=int, default=-1)
    ap.add_argument('--lu-en', type=float, default=1024.0, help='UV divisor used to READ the source')
    ap.add_argument('--uv-divisor', type=float, default=1000.0, help='UV divisor used to WRITE')
    A = ap.parse_args()

    src = fmt.parse_mesh(A.source)
    gab = fmt.parse_mesh(A.gabarit)
    ks = fmt.parse_skeleton(A.skel_source)
    kc = fmt.parse_skeleton(A.skel_cible)
    # source bone index -> target bone index, by bone-name hash (unknown bones go to bone 0)
    vers_cible = {}
    par_hash = {b.name_hash: b.index for b in kc.bones}
    manquants = []
    for b in ks.bones:
        if b.name_hash in par_hash:
            vers_cible[b.index] = par_hash[b.name_hash]
        else:
            vers_cible[b.index] = 0
            manquants.append(b.index)
    log('skeletons: source %d bones, target %d bones, %d bones without a match'
        % (ks.bone_count, kc.bone_count, len(manquants)))

    # ---------------------------------------------------------------- reading the sections
    lots = []
    for s in src.sections:
        if not s.vertex_count or not s.index_count:
            continue
        d = fmt.decode_section_vertices(src, s, uv_divisor=A.lu_en)
        idx = fmt.read_indices(src, s)
        tris = np.array(fmt.indices_to_faces(idx, s.primitive_type, s.vertex_count), np.int64)
        tc = d['texcoords']
        lots.append(dict(
            P=np.array(d['positions'], np.float64),
            N=np.array(d['normals'], np.float64),
            T=np.array(d['tangents'], np.float64),
            B=np.array(d['binormals'], np.float64),
            UV=np.array(tc[sorted(tc)[0]], np.float64),
            C=np.array(d['colors'][sorted(d['colors'])[0]], np.float64)
            if d['colors'] else np.ones((s.vertex_count, 4)),
            J=np.array(d['blend_indices'], np.int64),
            W=np.array(d['blend_weights'], np.float64),
            pal=list(s.bone_palette or [0]),
            tris=tris))
        log('   section %d: %5d vertices, %5d triangles, palette %2d'
            % (s.index, s.vertex_count, len(tris), len(s.bone_palette or [])))

    P = np.concatenate([L['P'] for L in lots])

    # ---------------------------------------------------------------- frame alignment
    if A.reference:
        Pref = np.concatenate([
            np.array(fmt.decode_section_vertices(fmt.parse_mesh(A.reference), s,
                                                 uv_divisor=A.lu_en)['positions'], np.float64)
            for s in fmt.parse_mesh(A.reference).sections if s.vertex_count])
        score, perm, sg, dec = repere(P, Pref)
        log('frame: axes %s signs %s offset %s (median distance %.5f)'
            % (perm, sg, np.round(dec, 4), score))
    elif A.repere == 'vers001':
        # (x, y, z)_001 = (z, y + 1.199, -x)_000  -> axes (2,1,0), signs (1,1,-1), +1.199 on Y
        perm, sg, dec = (2, 1, 0), (1, 1, -1), np.array([0.0, 1.199, 0.0])
        log('frame 000 -> 001 applied: (z, y + 1.199, -x)')
    elif A.repere == 'vers000':
        perm, sg, dec = (2, 1, 0), (-1, 1, 1), np.array([0.0, -1.199, 0.0])
        log('frame 001 -> 000 applied: (-z, y - 1.199, x)')
    else:
        perm, sg, dec = (0, 1, 2), (1, 1, 1), np.zeros(3)
        log('no reference: frame left as it is')
    S = np.array(sg, np.float64)
    # The rotation also applies to normals/tangents/binormals, WITHOUT the offset.
    det = np.linalg.det(np.eye(3)[list(perm)] * S[:, None])
    log('determinant of the transformation: %+.0f (%s)'
        % (det, 'proper rotation, winding kept' if det > 0 else 'MIRROR, winding inverted'))

    log('vertex colour: %s' % ('BLACK (like the vanilla model)' if A.couleur == 'noir'
                               else 'the source\'s'))
    ref = int(str(A.material_ref), 16) if str(A.material_ref).lower().startswith('0x') \
        else int(A.material_ref)
    sections = []
    for L in lots:
        p = L['P'][:, perm] * S + dec
        n = L['N'][:, perm] * S
        t = L['T'][:, perm] * S
        b = L['B'][:, perm] * S
        # palette of the source section, converted to GLOBAL bone indices of the target skeleton
        pal_g = [vers_cible.get(int(x), 0) for x in L['pal']]
        sommets = []
        for i in range(len(p)):
            inf = [(pal_g[int(L['J'][i, c])] if int(L['J'][i, c]) < len(pal_g) else 0,
                    float(L['W'][i, c])) for c in range(L['J'].shape[1]) if L['W'][i, c] > 1e-8]
            if not inf:
                inf = [(pal_g[0], 1.0)]
            sommets.append(mw.ExportVertex(
                position=tuple(p[i]), uv=(float(L['UV'][i, 0]), float(L['UV'][i, 1])),
                color=(0.0, 0.0, 0.0, 1.0) if A.couleur == 'noir'
                else tuple(float(x) for x in L['C'][i]),
                normal=tuple(n[i]), tangent=tuple(t[i]), binormal=tuple(b[i]),
                influences=tuple(inf)))
        pal = sorted({g for vertex in sommets for g,w in vertex.influences if w>0})
        sections.append(mw.ExportSection(
            source_object=os.path.basename(A.source), source_material_index=0,
            material_ref_serialized=ref, vertices=sommets,
            triangles=[tuple(int(x) for x in tr) for tr in L['tris'].tolist()],
            bone_palette=pal, position_divisor=512.0,
            schema_template_section=(A.schema if A.schema >= 0 else None)))

    # ---------------------------------------------------------------- absolute checks
    Ptot = np.concatenate([np.array([v.position for v in s.vertices]) for s in sections])
    Ntot = np.concatenate([np.array([v.normal for v in s.vertices]) for s in sections])
    base = 0
    tris_tot = []
    for s in sections:
        tris_tot.append(np.array(s.triangles) + base)
        base += len(s.vertices)
    TT = np.concatenate(tris_tot)
    v, o = volume_signe(Ptot, TT), normales_sortantes(Ptot, Ntot)
    log('signed volume %+.4f | normals %+.4f   (vanilla: -0.116 and +0.229)' % (v, o))
    if v > 0 or o < 0:
        log('!! orientation inverted -> fixed')
        for s in sections:
            s.triangles = [(a, c, bb) for a, bb, c in s.triangles]
            for x in s.vertices:
                x.normal = tuple(-np.array(x.normal))
                x.binormal = tuple(-np.array(x.binormal))

    # The writer encodes UVs * 1024 by default; the suit's vertex shader divides by 1000.
    f = mw.encode_player_vertex
    if f.__defaults__ and abs(f.__defaults__[0] - 1024.0) < 1e-6:
        f.__defaults__ = (A.uv_divisor,) + f.__defaults__[1:]
        log('UV divisor forced to %g' % A.uv_divisor)

    r = mw.write_raw_mesh(A.out, gab, sections, filename_hash=gab.filename_hash,
                          player_target=A.cible)
    log('WROTE %s: %d sections, %d vertices, %d triangles, %d bytes, hash 0x%08X, read back %s'
        % (r.output_path, r.section_count, r.vertex_count, r.triangle_count, r.file_size,
           r.filename_hash, r.report.get('roundtrip_parse')))
    m = fmt.parse_mesh(A.out)
    for s in m.sections:
        off = [dc.offset for dc in s.decl if dc.usage == 5][0]
        q = np.frombuffer(m.raw[s.vertex_buffer_offset:
                                s.vertex_buffer_offset + s.vertex_count * s.vertex_stride],
                          np.uint8).reshape(s.vertex_count, s.vertex_stride)[:, off:off + 4] \
            .copy().view(np.int16)
        log('   sec %d: %5d v, stride %d, mat 0x%-4X, U[%d..%d] V[%d..%d]'
            % (s.index, s.vertex_count, s.vertex_stride, s.material_ref_serialized,
               q[:, 0].min(), q[:, 0].max(), q[:, 1].min(), q[:, 1].max()))


if __name__ == '__main__':
    main()
