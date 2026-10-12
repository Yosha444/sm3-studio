# SPDX-License-Identifier: GPL-3.0-or-later
"""reparer_uv_ts.py - repair TSGAMING264's 000 by giving it back the UVs of its own 001.

Where it sits: NOT part of the conversion; a one-off repair tool for one third-party mod (the
converter never calls it). transplanter_lod.py replaced this approach for the reason explained in
its docstring (UV seams). Kept for the record. (000 = ch_spiderman000.mesh, 001 =
ch_spiderman001.mesh; see uv_depuis_lod.py.)

The diagnosis, measured:
  - 44 % of his 000 (3252 faces / 7370: arms, legs, hips, feet) have their UVs in V tile 1
    (`V[1031..2035]` raw). Those UVs do not match his baked atlas: his exporter serialised the
    SOURCE UV layer instead of the PACKED one.
  - his 001 holds all four sections in `V[2..1021]`, a complete layout inside [0,1];
  - both meshes are the SAME geometry: 4757 vertices matched out of 4757, median distance
    0.00000, once the frame of the 001 is brought back onto the 000's
    (`(x,y,z)_000 = (-z, y - 1.1934, x)_001`, found automatically).

So the right UVs are in the files he sent, just in the other one. They are copied over.

ONLY the UV bytes are rewritten, plus the material reference. Positions, normals, tangents,
weights, sections, palettes: nothing else is touched.

Reads:  --mesh000, --mesh001
Writes: --out, the repaired 000

    python reparer_uv_ts.py --mesh000 <...> --mesh001 <...> --out <...>
                            [--material-ref 0x614] [--uv-divisor 1000]
"""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
import struct
import sys

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
from uv_depuis_lod import fmt, lire  # noqa: E402


def log(*x):
    print('[reparer]', *x)


def repere_du_001(P0, P1):
    """Find the signed axis permutation + offset that bring the 001 onto the 000.

    Returns (median distance, permutation, signs, offset)."""
    import itertools
    ech = np.random.default_rng(0).choice(len(P0), size=min(400, len(P0)), replace=False)
    meilleur = None
    for perm in itertools.permutations(range(3)):
        for sg in itertools.product((1, -1), repeat=3):
            Q = P1[:, perm] * np.array(sg, np.float64)
            d = (P0.min(0) + P0.max(0)) / 2 - (Q.min(0) + Q.max(0)) / 2
            dd = np.linalg.norm(P0[ech, None, :] - (Q + d)[None, :, :], axis=2).min(1)
            s = float(np.median(dd))
            if meilleur is None or s < meilleur[0]:
                meilleur = (s, perm, sg, d)
    return meilleur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh000', required=True)
    ap.add_argument('--mesh001', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--material-ref', default='0x614',
                    help='0x614 = spider, the non-tiled material confirmed in game '
                         "to display a custom texture correctly")
    ap.add_argument('--uv-divisor', type=float, default=1000.0,
                    help="what the vertex shader applies (`mul o2.xy, c235.x, v1`, c235.x=0.001)")
    ap.add_argument('--lu-en', type=float, default=1024.0,
                    help='divisor BOTH files were WRITTEN with (French: "read as")')
    A = ap.parse_args()

    P0, U0, m0 = lire(A.mesh000, A.lu_en)
    P1, U1, m1 = lire(A.mesh001, A.lu_en)
    score, perm, sg, dec = repere_du_001(P0, P1)
    log('frame of the 001: axes %s signs %s offset %s (median distance %.5f)'
        % (perm, sg, np.round(dec, 4), score))
    P1r = P1[:, perm] * np.array(sg, np.float64) + dec

    dist = np.empty(len(P0))
    idx = np.empty(len(P0), np.int64)
    for a in range(0, len(P0), 512):
        d = np.linalg.norm(P0[a:a + 512, None, :] - P1r[None, :, :], axis=2)
        idx[a:a + 512] = d.argmin(1)
        dist[a:a + 512] = d.min(1)
    log('matching: %d / %d under 0.01 | median %.5f | max %.4f'
        % (int((dist <= 0.01).sum()), len(P0), np.median(dist), dist.max()))
    if (dist <= 0.01).mean() < 0.95:
        raise SystemExit('the two meshes are not the same geometry, stopping')
    Unew = U1[idx]
    fautifs = int((np.floor(U0[:, 1] + 1e-6) != 0).sum())
    log('recovered UVs: u %.4f..%.4f v %.4f..%.4f | %d vertices were outside tile 0'
        % (Unew[:, 0].min(), Unew[:, 0].max(), Unew[:, 1].min(), Unew[:, 1].max(), fautifs))

    # ---------------------------------------------------------------- rewriting the bytes
    d = bytearray(m0.raw)
    ref = int(str(A.material_ref), 16) if str(A.material_ref).lower().startswith('0x') \
        else int(A.material_ref)
    curseur = 0
    for s in m0.sections:
        if not s.vertex_count:
            continue
        offs = [dc.offset for dc in s.decl if dc.usage == 5]        # every TEXCOORD
        bloc = np.frombuffer(bytes(d[s.vertex_buffer_offset:
                                     s.vertex_buffer_offset + s.vertex_count * s.vertex_stride]),
                             np.uint8).copy().reshape(s.vertex_count, s.vertex_stride)
        u = Unew[curseur:curseur + s.vertex_count]
        q = np.clip(np.rint(u * A.uv_divisor), -32768, 32767).astype(np.int16)
        # His stride-56 layout carries TWO identical UV sets: rewrite both, otherwise a read of
        # the second set would bring back the old, broken layout.
        for off in offs:
            bloc[:, off:off + 4] = q.view(np.uint8).reshape(s.vertex_count, 4)
        d[s.vertex_buffer_offset:s.vertex_buffer_offset + s.vertex_count * s.vertex_stride] = \
            bloc.tobytes()
        # material_ref_serialized is at +0x20 of the section's MeshInfo record
        struct.pack_into('<I', d, s.info_offset + 0x20, ref)
        log('   sec %d: %5d vertices, %d UV set(s) rewritten, material 0x%X -> 0x%X'
            % (s.index, s.vertex_count, len(offs), s.material_ref_serialized, ref))
        curseur += s.vertex_count

    os.makedirs(os.path.dirname(os.path.abspath(A.out)) or '.', exist_ok=True)
    open(A.out, 'wb').write(bytes(d))
    v = fmt.parse_mesh(A.out)
    log('WROTE %s (%d bytes, %d sections, hash 0x%08X)'
        % (A.out, len(d), v.section_count, v.filename_hash))
    for s in v.sections:
        offs = [dc.offset for dc in s.decl if dc.usage == 5]
        b = np.frombuffer(v.raw[s.vertex_buffer_offset:
                                s.vertex_buffer_offset + s.vertex_count * s.vertex_stride],
                          np.uint8).reshape(s.vertex_count, s.vertex_stride)
        z = b[:, offs[0]:offs[0] + 4].copy().view(np.int16)
        log('   check sec %d: mat 0x%-4X U[%d..%d] V[%d..%d]'
            % (s.index, s.material_ref_serialized,
               z[:, 0].min(), z[:, 0].max(), z[:, 1].min(), z[:, 1].max()))


if __name__ == '__main__':
    main()
