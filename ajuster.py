# SPDX-License-Identifier: GPL-3.0-or-later
"""ajuster.py - MANUAL correction of an already written .mesh: scale, rotation, offset.

Where it sits: stage `ajuster` ("adjust") of sm3_convertir.py, right after `chaine` (the Blender
stage). It only runs when one of the manual pose settings is used (Pose tab of the window, or
--echelle / --rot-x / --rot-y / --rot-z / --decalage / --poser-au-sol on the command line);
otherwise the converter skips it.

Why it exists: the automatic alignment on the vanilla template (tools/chaine_officielle.py, in
Blender) sometimes misses: model too big or too small, lying on its back, turned by 90 degrees,
or not standing on the ground. This script works directly on the bytes of the delivered .mesh,
without going back through Blender, so it is instantaneous and can be repeated at will.

Reads:  --mesh     a .mesh written by the `chaine` stage (build/<mod>/etape_chaine.mesh)
        --vanilla  the vanilla ch_spiderman000.mesh (only needed by --poser-au-sol)
Writes: --out      the same file with its positions, normals, tangents and binormals rewritten;
                   everything else (UVs, weights, sections, palettes) is copied unchanged.

    python ajuster.py --mesh <in.mesh> --out <out.mesh> [--echelle 1.05] [--rot-y 90]
                      [--decalage 0,0.05,0] [--poser-au-sol] [--vanilla <000.mesh>]

French option names: echelle = scale, decalage = offset (dx,dy,dz), poser au sol = put on the
ground (scale and lift the model so that its height span matches the vanilla model's).

Pitfalls handled here:
  * Rotations are applied to normals, tangents and binormals too (without the offset). A rotation
    about an axis is a proper rotation, so the triangle winding is kept. A NEGATIVE scale would
    be a mirror and would turn the faces inside out, so it is refused.
  * After a pose change the skinning weights are wrong (they were computed for the old position).
    The converter's `poids` stage, which runs after this one, computes them again.
  * Positions are stored as signed 16-bit integers divided by --pos-divisor (512, the value the
    game uses), so anything beyond +-64 units is clipped.
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
    print('[ajuster]', *x)


def rotation(ax, ay, az):
    """XYZ rotation matrix from angles in degrees, in the SM3 frame (axis 1 = height)."""
    a, b, c = np.radians([ax, ay, az])
    Rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    Ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    Rz = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--echelle', type=float, default=1.0)
    ap.add_argument('--rot-x', type=float, default=0.0)
    ap.add_argument('--rot-y', type=float, default=0.0)
    ap.add_argument('--rot-z', type=float, default=0.0)
    ap.add_argument('--decalage', default='0,0,0', help='offset dx,dy,dz in model units')
    ap.add_argument('--poser-au-sol', action='store_true',
                    help='scale and move the model so that its lowest and highest points match '
                         'those of the vanilla model')
    ap.add_argument('--vanilla', default='', help='vanilla ch_spiderman000.mesh, required by --poser-au-sol')
    ap.add_argument('--pos-divisor', type=float, default=512.0)
    A = ap.parse_args()

    if A.echelle <= 0:
        raise SystemExit("a zero or negative scale is refused (a negative scale is a mirror: "
                         "it would turn the faces inside out)")
    dec = np.array([float(x) for x in A.decalage.split(',')], np.float64)
    R = rotation(A.rot_x, A.rot_y, A.rot_z)
    log('scale %.4f | rotation (%.1f, %.1f, %.1f) | offset %s'
        % (A.echelle, A.rot_x, A.rot_y, A.rot_z, dec.tolist()))

    m = fmt.parse_mesh(A.mesh)
    d = bytearray(m.raw)

    # Pass 1: current bounds, needed by --poser-au-sol.
    P_tot = []
    for s in m.sections:
        if s.vertex_count:
            P_tot.append(np.array(fmt.decode_section_vertices(m, s, uv_divisor=1000.0)['positions'],
                                  np.float64))
    P_tot = np.concatenate(P_tot)
    ech, dec2 = A.echelle, dec.copy()
    if A.poser_au_sol:
        if not A.vanilla:
            raise SystemExit('--poser-au-sol needs --vanilla')
        mv = fmt.parse_mesh(A.vanilla)
        Pv = np.concatenate([np.array(fmt.decode_section_vertices(mv, s, uv_divisor=1000.0)['positions'],
                                      np.float64) for s in mv.sections if s.vertex_count])
        Q = (P_tot * A.echelle) @ R.T
        h_src = Q[:, 1].max() - Q[:, 1].min()
        h_van = Pv[:, 1].max() - Pv[:, 1].min()
        ech = A.echelle * (h_van / max(h_src, 1e-9))
        Q = (P_tot * ech) @ R.T
        dec2 = dec + np.array([0.0, Pv[:, 1].min() - Q[:, 1].min(), 0.0])
        log('poser-au-sol: height %.3f -> %.3f, final scale %.4f, Y offset %+.4f'
            % (h_src, h_van, ech, dec2[1]))

    # Pass 2: rewrite the vertex bytes, section by section.
    for s in m.sections:
        if not s.vertex_count:
            continue
        dv = fmt.decode_section_vertices(m, s, uv_divisor=1000.0)
        P = np.array(dv['positions'], np.float64)
        P2 = (P * ech) @ R.T + dec2
        bloc = np.frombuffer(bytes(d[s.vertex_buffer_offset:
                                     s.vertex_buffer_offset + s.vertex_count * s.vertex_stride]),
                             np.uint8).copy().reshape(s.vertex_count, s.vertex_stride)
        # D3DDECLUSAGE 0 = POSITION, stored as 4 int16 (x, y, z, w): only x, y, z are replaced.
        op = [dc.offset for dc in s.decl if dc.usage == 0][0]
        q = np.clip(np.rint(P2 * A.pos_divisor), -32768, 32767).astype(np.int16)
        anc = bloc[:, op:op + 8].copy().view(np.int16)
        anc[:, :3] = q
        bloc[:, op:op + 8] = anc.view(np.uint8)
        # Normals, tangents, binormals (D3DDECLUSAGE 3, 6, 7; 4 int16 normalised to 32767): the
        # rotation ONLY, neither scale nor offset.
        for usage, cle in ((3, 'normals'), (6, 'tangents'), (7, 'binormals')):
            o = [dc.offset for dc in s.decl if dc.usage == usage]
            if not o:
                continue
            V = np.array(dv[cle], np.float64) @ R.T
            V = V / np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-9)
            qq = np.clip(np.rint(V * 32767.0), -32768, 32767).astype(np.int16)
            a2 = bloc[:, o[0]:o[0] + 8].copy().view(np.int16)
            a2[:, :3] = qq
            bloc[:, o[0]:o[0] + 8] = a2.view(np.uint8)
        d[s.vertex_buffer_offset:s.vertex_buffer_offset + s.vertex_count * s.vertex_stride] = \
            bloc.tobytes()

    os.makedirs(os.path.dirname(os.path.abspath(A.out)) or '.', exist_ok=True)
    open(A.out, 'wb').write(bytes(d))
    mm = fmt.parse_mesh(A.out)
    P3 = np.concatenate([np.array(fmt.decode_section_vertices(mm, s, uv_divisor=1000.0)['positions'],
                                  np.float64) for s in mm.sections if s.vertex_count])
    log('WROTE %s' % A.out)
    log('  bounds %s .. %s  (before: %s .. %s)'
        % (np.round(P3.min(0), 3), np.round(P3.max(0), 3),
           np.round(P_tot.min(0), 3), np.round(P_tot.max(0), 3)))
    log("  NOTE: the skinning must be computed again after this (the converter's `poids` stage does it)")


if __name__ == '__main__':
    main()
