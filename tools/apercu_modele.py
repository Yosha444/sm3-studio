# SPDX-License-Identifier: GPL-3.0-or-later
"""apercu_modele.py - LOOK at a shaded model, .mesh or .glb, without starting Blender.

("aperçu du modèle" = "model preview".) Diagnostic tool, run by hand; SM3 Studio does not call
it. `silhouette.py` shows the overall shape; this one shows the RELIEF, because a point cloud says
nothing about a fold or a hollow. Software rendering: depth buffer + N.L lighting, pure numpy,
PNG written by hand.

Why it is worth having, twice over:
  - `peter` produced a perfect skinning report (distance to the game's weights 0.000) and it was
    a CONE.
  - a Batman Beyond had "its chin glued to its neck". Rendering the head of the SOURCE .glb next
    to that of the DELIVERED .mesh showed two heads that matched: the defect was in the model,
    not in the conversion. Without this image we would have had to believe or guess.

WARNING, the axes. The vanilla SM3 model is Y-UP. A glTF exported from a Z-up program arrives
lying down; `--redresser` ("stand up") rotates it upright, as `chaine_officielle.py` does. If the
preview comes out lying down, the model is, and no weight transfer will recover from that.

    python tools/apercu_modele.py --modele <f.mesh|f.glb> [--zone 0.84,1.02] [--redresser]
                                  [--angle 0.45] [--out image.png]

Reads a SM3 .mesh (toolkit parser, via sm3_sans_blender.fmt) or a .glb/.gltf (glb.py at the
project root); writes a grey PNG, default <model>.apercu.png.
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
    """8-bit greyscale PNG written without PIL (same writer as silhouette.py)."""
    h, w = img.shape
    brut = b''.join(b'\x00' + img[y].tobytes() for y in range(h))   # filter byte 0 on each row

    def morceau(t, d):          # one PNG chunk: length, then type + data, then CRC32 of both
        c = t + d
        return struct.pack('>I', len(d)) + c + struct.pack('>I', zlib.crc32(c))

    with open(chemin, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n'
                + morceau(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0))
                + morceau(b'IDAT', zlib.compress(brut)) + morceau(b'IEND', b''))


def lire(chemin, redresser=False):
    """(positions, normals, triangles) from a SM3 .mesh or a .glb / .gltf, in SM3 axes (Y up)."""
    if chemin.lower().endswith(('.glb', '.gltf')):
        from glb import GLB, en_repere_sm3
        g = GLB(chemin)
        M = g.matrices_monde()            # world matrix of every node
        P, N, T, base = [], [], [], 0
        for im, me in enumerate(g.g['meshes']):
            nd = g.noeud_du_mesh(im)      # node that instantiates this mesh
            mat = M[nd] if nd is not None else np.eye(4)
            for pr in me['primitives']:
                a = pr['attributes']
                p0 = g.acces(a['POSITION'])
                n0 = g.acces(a['NORMAL']) if 'NORMAL' in a else np.zeros_like(p0)
                p0 = (np.c_[p0, np.ones(len(p0))] @ mat.T)[:, :3]
                n0 = n0 @ mat[:3, :3].T
                idx = g.acces(pr['indices'])[:, 0] if 'indices' in pr else np.arange(len(p0))
                T.append(idx.reshape(-1, 3) + base)
                P.append(p0)
                N.append(n0)
                base += len(p0)
        P, N = en_repere_sm3(np.concatenate(P)), en_repere_sm3(np.concatenate(N))
        T = np.concatenate(T)
    else:
        m = fmt.parse_mesh(chemin)
        P, N, T, base = [], [], [], 0
        for s in m.sections:
            if not s.vertex_count:
                continue
            d = fmt.decode_section_vertices(m, s, uv_divisor=1000.0)
            P.append(np.array(d['positions'], np.float64))
            N.append(np.array(d['normals'], np.float64))
            T.append(np.array(fmt.indices_to_faces(fmt.read_indices(m, s), s.primitive_type,
                                                   s.vertex_count), np.int64) + base)
            base += s.vertex_count
        P, N, T = np.concatenate(P), np.concatenate(N), np.concatenate(T)
    if redresser:
        # Z-up -> Y-up: (x, y, z) -> (x, z, -y)
        R = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float)
        P, N = P @ R.T, N @ R.T
    return P, N, T


def rendre(P, N, T, sortie, zone=(-0.05, 1.05), cote=460, angle=0.45, lumiere=(0.3, 0.45, 0.85)):
    """Render the triangles whose 3 vertices lie in the height band `zone` (fractions of the
    model's height), seen from `angle` radians around the vertical, into a `cote` x `cote` PNG."""
    N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
    lo, hi = P.min(0), P.max(0)
    h = (P[:, 1] - lo[1]) / max(hi[1] - lo[1], 1e-9)
    dedans = np.where((h >= zone[0]) & (h <= zone[1]))[0]
    T = T[np.all(np.isin(T, dedans), axis=1)]
    if not len(T):
        raise SystemExit('no triangle in the requested band')
    ca, sa = np.cos(angle), np.sin(angle)
    R = np.array([[ca, 0, sa], [0, 1, 0], [-sa, 0, ca]])
    Q, NN = P @ R.T, N @ R.T
    iv = np.unique(T)
    l2, h2 = Q[iv].min(0), Q[iv].max(0)
    ech = max(h2[0] - l2[0], h2[1] - l2[1]) or 1.0
    u = (Q[:, 0] - (l2[0] + h2[0]) / 2) / ech * cote * 0.82 + cote / 2
    v = cote / 2 - (Q[:, 1] - (l2[1] + h2[1]) / 2) / ech * cote * 0.82
    z = Q[:, 2]
    L = np.array(lumiere, float)
    L /= np.linalg.norm(L)
    inten = np.clip(NN @ L, 0, 1) * 0.85 + 0.15        # Lambert + 15 % ambient
    img = np.zeros((cote, cote))
    prof = np.full((cote, cote), -1e9)                 # depth buffer (larger z = nearer)
    for t in T:
        xs, ys = u[t], v[t]
        x0, x1 = int(max(0, np.floor(xs.min()))), int(min(cote - 1, np.ceil(xs.max())))
        y0, y1 = int(max(0, np.floor(ys.min()))), int(min(cote - 1, np.ceil(ys.max())))
        if x1 < x0 or y1 < y0:
            continue
        yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        det = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(det) < 1e-12:
            continue
        w0 = ((ys[1] - ys[2]) * (xx - xs[2]) + (xs[2] - xs[1]) * (yy - ys[2])) / det
        w1 = ((ys[2] - ys[0]) * (xx - xs[2]) + (xs[0] - xs[2]) * (yy - ys[2])) / det
        w2 = 1 - w0 - w1
        m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not m.any():
            continue
        zz = w0 * z[t[0]] + w1 * z[t[1]] + w2 * z[t[2]]
        ii = w0 * inten[t[0]] + w1 * inten[t[1]] + w2 * inten[t[2]]
        ligne, col = yy[m], xx[m]
        devant = zz[m] > prof[ligne, col]
        prof[ligne[devant], col[devant]] = zz[m][devant]
        img[ligne[devant], col[devant]] = ii[m][devant]
    _png(sortie, (np.clip(img, 0, 1) * 255).astype(np.uint8))
    print('[apercu] %d triangle(s) rendered | extent %s | WROTE %s'
          % (len(T), np.round(hi - lo, 3), sortie))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--modele', required=True, help='SM3 .mesh, or .glb / .gltf')
    ap.add_argument('--out', default='')
    ap.add_argument('--zone', default='-0.05,1.05',
                    help='HEIGHT band to render, as fractions. "0.84,1.02" for the head')
    ap.add_argument('--angle', type=float, default=0.45, help='rotation around the vertical')
    ap.add_argument('--redresser', action='store_true',
                    help='the glTF comes from a Z-up program: stand it up')
    ap.add_argument('--cote', type=int, default=460)      # image side in pixels
    A = ap.parse_args()
    z = tuple(float(x) for x in A.zone.split(',')[:2])
    P, N, T = lire(A.modele, A.redresser)
    rendre(P, N, T, A.out or os.path.splitext(A.modele)[0] + '.apercu.png', z, A.cote, A.angle)


if __name__ == '__main__':
    main()
