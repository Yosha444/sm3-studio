# SPDX-License-Identifier: GPL-3.0-or-later
"""uv_depuis_lod.py - recover the missing UVs of a 000 mesh from its 001 ("UVs from the LOD").

Where it sits: NOT part of the conversion. It is a diagnostic/repair tool written for one
third-party mod (TSGAMING264's red suit), kept with reparer_uv_ts.py, which imports its lire()
and `fmt`. The converter never calls either of them. (000 = ch_spiderman000.mesh, the main
player model; 001 = ch_spiderman001.mesh, the second model of the suit, stored in its own frame.)

What was measured on that mod: **44 % of its 000** (3252 faces out of 7370 - arms, legs, hips,
feet) had UVs in V tile 1 (`V[1031..2035]` raw), which do not match its baked atlas. Its exporter
had serialised, for those faces, the SOURCE UV layer instead of the PACKED one. In game those
parts sample arbitrary regions of the atlas: exactly the flat, web-less areas of the screenshots.

But its **001** holds all four sections in `V[2..1021]` - a complete layout, entirely inside
[0,1] - and its geometry is the same as the 000's (re-exported against the other template).

So the packed UVs do exist in the files: they are in the 001. This script transfers them onto
the vertices of the 000 by nearest neighbour in POSITION, and reports how well that worked.

Reads:  --mesh000, --mesh001 (two .mesh files of the same model)
Writes: nothing, unless --sortie (French: "output") is given: a .npz with positions, recovered
        UVs, distances and the faulty-vertex mask.

    python uv_depuis_lod.py --mesh000 <...> --mesh001 <...> [--seuil 0.002]

The toolkit's sm3_format.py is loaded from $SM3_TOOLKIT_DIR, or from Blender 5.2's extension
folder (same rule as sm3_sans_blender.py).
"""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
import sys

import numpy as np


def _toolkit_dir():
    """Folder of the SM3 Blender Toolkit add-on: $SM3_TOOLKIT_DIR, else Blender 5.2's default."""
    explicit = os.environ.get('SM3_TOOLKIT_DIR', '').strip().strip('"')
    if explicit:
        return explicit
    return os.path.join(os.environ.get('APPDATA', ''), 'Blender Foundation', 'Blender', '5.2',
                        'extensions', 'user_default', 'sm3_blender_toolkit')


EXT = _toolkit_dir()
if not os.path.isfile(os.path.join(EXT, 'sm3_format.py')):
    raise SystemExit('SM3 Blender Toolkit (TSGAMING264) not found: %s does not contain '
                     'sm3_format.py.\nInstall the add-on in Blender 5.2 '
                     '(https://github.com/TSGAMING264/SM3-Blender-Tools), or set the '
                     'SM3_TOOLKIT_DIR environment variable to its folder.' % EXT)
# Fake package so that the toolkit's relative imports work without its bpy-importing __init__
# (see sm3_sans_blender.py).
_PKG = 'sm3_blender_toolkit'
if _PKG not in sys.modules:
    _f = importlib.util.module_from_spec(
        importlib.machinery.ModuleSpec(_PKG, None, is_package=True))
    _f.__path__ = [EXT]
    sys.modules[_PKG] = _f


def _charge(nom):
    """Load <toolkit>/<nom>.py as sm3_blender_toolkit.<nom> (French: "load")."""
    s = importlib.util.spec_from_file_location(_PKG + '.' + nom, os.path.join(EXT, nom + '.py'))
    m = importlib.util.module_from_spec(s)
    sys.modules[s.name] = m
    s.loader.exec_module(m)
    return m


fmt = _charge('sm3_format')


def log(*x):
    print('[uv-lod]', *x)


def lire(chemin, uv_divisor=1024.0):
    """Positions, UV0 of all sections (concatenated) and the parsed mesh (French: "read")."""
    m = fmt.parse_mesh(chemin)
    P, U = [], []
    for s in m.sections:
        if not s.vertex_count:
            continue
        d = fmt.decode_section_vertices(m, s, uv_divisor=uv_divisor)
        P.append(np.array(d['positions'], np.float64))
        tc = d['texcoords']
        cle = sorted(tc)[0]
        U.append(np.array(tc[cle], np.float64))
    return np.concatenate(P), np.concatenate(U), m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh000', required=True)
    ap.add_argument('--mesh001', required=True)
    ap.add_argument('--uv-divisor', type=float, default=1024.0)
    ap.add_argument('--seuil', type=float, default=0.002,
                    help='threshold: largest distance accepted for a match (model units)')
    ap.add_argument('--sortie', default='', help='output .npz file: positions + recovered UVs')
    A = ap.parse_args()

    P0, U0, m0 = lire(A.mesh000, A.uv_divisor)
    P1, U1, m1 = lire(A.mesh001, A.uv_divisor)
    log('000: %d vertices, UV v %.3f..%.3f' % (len(P0), U0[:, 1].min(), U0[:, 1].max()))
    log('001: %d vertices, UV v %.3f..%.3f' % (len(P1), U1[:, 1].min(), U1[:, 1].max()))

    # The two templates do NOT share a frame: measured on TSGAMING264's mod,
    # (x, y, z)_000 = (-z, y - 1.20, x)_001. Rather than hard-coding that case, the 48 signed axis
    # permutations are tried and the best-matching one is kept.
    import itertools
    ech = np.random.default_rng(0).choice(len(P0), size=min(400, len(P0)), replace=False)
    meilleur = None
    for perm in itertools.permutations(range(3)):
        for sg in itertools.product((1, -1), repeat=3):
            Q = P1[:, perm] * np.array(sg, np.float64)
            d = (P0.min(0) + P0.max(0)) / 2 - (Q.min(0) + Q.max(0)) / 2
            Qr = Q + d
            dd = np.linalg.norm(P0[ech, None, :] - Qr[None, :, :], axis=2).min(1)
            score = float(np.median(dd))
            if meilleur is None or score < meilleur[0]:
                meilleur = (score, perm, sg, d)
    score, perm, sg, dec = meilleur
    log('frame of the 001 found: axes %s signs %s offset %s (median distance %.5f)'
        % (perm, sg, np.round(dec, 4), score))
    P1r = P1[:, perm] * np.array(sg, np.float64) + dec

    try:
        from scipy.spatial import cKDTree as KD
        arbre = KD(P1r)
        dist, idx = arbre.query(P0, k=1)
    except Exception:
        log('scipy not available: matching by numpy blocks (slower)')
        dist = np.empty(len(P0))
        idx = np.empty(len(P0), np.int64)
        pas = 512
        for a in range(0, len(P0), pas):
            d = np.linalg.norm(P0[a:a + pas, None, :] - P1r[None, :, :], axis=2)
            idx[a:a + pas] = d.argmin(1)
            dist[a:a + pas] = d.min(1)

    bon = dist <= A.seuil
    log('matching: %d / %d under %.4f  (%.1f %%) | median distance %.5f, max %.4f'
        % (bon.sum(), len(P0), A.seuil, 100 * bon.mean(), np.median(dist), dist.max()))
    if bon.mean() < 0.95:
        log('!! fewer than 95 %% matched: the two meshes are not the same geometry')

    Unew = U1[idx]
    hors = (Unew < -1e-6) | (Unew > 1 + 1e-6)
    log('recovered UVs: u %.4f..%.4f  v %.4f..%.4f  | %d outside [0,1]'
        % (Unew[:, 0].min(), Unew[:, 0].max(), Unew[:, 1].min(), Unew[:, 1].max(), hors.any(1).sum()))

    # How many of the FAULTY vertices of the 000 (V tile 1) get a different UV?
    faux = np.floor(U0[:, 1] + 1e-6) != 0
    if faux.any():
        ecart = np.linalg.norm(Unew[faux] - (U0[faux] - np.floor(U0[faux] + 1e-6)), axis=1)
        log('faulty vertices (V tile 1): %d | median distance to the old wrapped UV %.4f'
            % (faux.sum(), np.median(ecart)))

    if A.sortie:
        np.savez(A.sortie, positions=P0, uv=Unew, distance=dist, fautifs=faux)
        log('WROTE %s' % A.sortie)


if __name__ == '__main__':
    main()
