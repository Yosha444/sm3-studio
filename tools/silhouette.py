# SPDX-License-Identifier: GPL-3.0-or-later
"""silhouette.py - LOOK at a .mesh, front and side, without starting Blender.

Diagnostic tool, run by hand; SM3 Studio does not call it.

Why it exists: every skinning statistic can stay flattering on a model that is already ruined.
Measured on 2026-09-14: the `peter` model reported a perfect "distance to the game's weights:
0.000", and its silhouette showed a CONE. `adv_large` was lying on its side with its head
detached. Two seconds of rendering would have saved hours of hunting a weight bug that did not
exist.

How: orthographic point cloud of every vertex (all sections), pure numpy, PNG written by hand.
No dependency beyond numpy, so it runs wherever the rest of the tools run (Blender's Python has
no Pillow, and neither does every build of the .exe).

    python tools/silhouette.py --mesh <file.mesh> [--out <image.png>]

Reads the .mesh with the toolkit's parser (through sm3_sans_blender.fmt); writes one grey PNG
with two views side by side (front x/y, side z/y). Default output: <mesh>.silhouette.png.
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import zlib

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(ICI))
from sm3_sans_blender import fmt  # noqa: E402


def _png(chemin, img):
    """8-bit greyscale PNG written without PIL (Blender has no PIL, the .exe not always)."""
    h, w = img.shape
    brut = b''.join(b'\x00' + img[y].tobytes() for y in range(h))   # filter byte 0 on each row

    def morceau(t, d):          # one PNG chunk: length, then type + data, then CRC32 of both
        c = t + d
        return struct.pack('>I', len(d)) + c + struct.pack('>I', zlib.crc32(c))

    with open(chemin, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n'
                + morceau(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0))
                + morceau(b'IDAT', zlib.compress(brut)) + morceau(b'IEND', b''))


def silhouette(chemin, sortie, largeur=330, hauteur=420):
    m = fmt.parse_mesh(chemin)
    P = np.concatenate([np.array(fmt.decode_section_vertices(m, s, uv_divisor=1000.0)['positions'],
                                 np.float64)
                        for s in m.sections if s.vertex_count])
    lo, hi = P.min(0), P.max(0)
    ech = max((hi - lo)[0], (hi - lo)[1]) or 1.0          # same scale for both views
    img = np.zeros((hauteur, 2 * largeur), np.uint16)
    for axe, decalage in ((0, 0), (2, largeur)):      # front (x, y), then side (z, y)
        u = (P[:, axe] - (lo[axe] + hi[axe]) / 2) / ech * largeur * 0.85 + largeur / 2
        v = hauteur - 15 - (P[:, 1] - lo[1]) / ech * largeur * 0.85
        ok = (u >= 0) & (u < largeur) & (v >= 0) & (v < hauteur)
        # each vertex adds 40 to its pixel: dense areas saturate to white, sparse ones stay grey
        np.add.at(img, (v[ok].astype(int), u[ok].astype(int) + decalage), 40)
    _png(sortie, np.clip(img, 0, 255).astype(np.uint8))
    print('[silhouette] %d vertices | extent %s | WROTE %s'
          % (len(P), np.round(hi - lo, 3), sortie))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mesh', required=True)
    ap.add_argument('--out', default='')
    A = ap.parse_args()
    silhouette(A.mesh, A.out or os.path.splitext(A.mesh)[0] + '.silhouette.png')


if __name__ == '__main__':
    main()
