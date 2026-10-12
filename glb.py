# SPDX-License-Identifier: GPL-3.0-or-later
"""glb.py - glTF / GLB reader in pure Python (numpy only, no Blender).

Where it sits: used by sm3_sans_blender.py (the experimental Blender-free GLB -> .mesh path) and
by tools/apercu_modele.py (model preview). The normal conversion imports models through Blender
instead (tools/chaine_officielle.py), so this reader is not on its path.

Only what SM3 needs is read: positions, normals, UV0, colours, joints and weights, indices, the
node hierarchy (for world matrices) and the skeleton (`skins`). Both .glb (binary container) and
.gltf (JSON with external or data: URI buffers) are accepted.

Coordinate frame (the pitfall this file exists for): glTF is Y-up, and SM3 Studio works with what
Blender exports, i.e. Blender's Z-up frame. Blender's glTF importer applies
    (x, y, z)_blender = (x, -z, y)_gltf
and en_repere_sm3() applies exactly the same change; without it the model arrives lying down.
"""
from __future__ import annotations

import base64
import json
import os
import struct

import numpy as np

# glTF componentType -> (numpy dtype, size in bytes)
CT = {5120: ('<i1', 1), 5121: ('<u1', 1), 5122: ('<i2', 2),
      5123: ('<u2', 2), 5125: ('<u4', 4), 5126: ('<f4', 4)}
# glTF accessor type -> number of components
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}


class GLB:
    """A loaded glTF/GLB file: `g` is the JSON document, `bins` the list of its buffers."""

    def __init__(self, chemin):
        self.chemin = chemin
        brut = open(chemin, 'rb').read()
        if brut[:4] == b'glTF':
            # GLB: 12-byte header, then chunks (length, type): 0x4E4F534A 'JSON', 0x004E4942 'BIN'.
            off, morceaux = 12, {}
            while off < len(brut):
                ln, ty = struct.unpack_from('<II', brut, off)
                off += 8
                morceaux[ty] = brut[off:off + ln]
                off += ln
            self.g = json.loads(morceaux[0x4E4F534A])
            self.bins = [morceaux.get(0x004E4942, b'')]
        else:
            self.g = json.loads(brut)
            self.bins = [b'']
        # buffers: the GLB's own BIN chunk (no uri), external files, or data: URIs
        base = os.path.dirname(os.path.abspath(chemin))
        tampons = []
        for i, buf in enumerate(self.g.get('buffers', [])):
            uri = buf.get('uri')
            if uri is None:
                tampons.append(self.bins[0])
            elif uri.startswith('data:'):
                tampons.append(base64.b64decode(uri.split(',', 1)[1]))
            else:
                from urllib.parse import unquote
                tampons.append(open(os.path.join(base, unquote(uri)), 'rb').read())
        self.bins = tampons or self.bins

    # ------------------------------------------------------------------ raw access
    def vue(self, i):
        """Bytes of bufferView `i`, and its byteStride (None when tightly packed)."""
        bv = self.g['bufferViews'][i]
        d = self.bins[bv.get('buffer', 0)]
        o = bv.get('byteOffset', 0)
        return d[o:o + bv['byteLength']], bv.get('byteStride')

    def acces(self, i):
        """Accessor `i` as an (n, components) array, interleaving included.

        Floats come back as float64, integers as int64; normalised integer accessors are scaled
        to [0, 1] / [-1, 1] as the glTF specification says."""
        a = self.g['accessors'][i]
        n = a['count']
        nc = NC[a['type']]
        dt, taille = CT[a['componentType']]
        if 'bufferView' not in a:
            return np.zeros((n, nc), np.dtype(dt).type)
        d, pas = self.vue(a['bufferView'])
        d = d[a.get('byteOffset', 0):]
        if pas in (None, nc * taille):
            out = np.frombuffer(d[:n * nc * taille], dt).reshape(n, nc)
        else:
            # Interleaved attributes: cut row by row, otherwise the neighbouring attribute is read.
            m = np.frombuffer(d[:n * pas], np.uint8).reshape(n, pas)[:, :nc * taille]
            out = np.ascontiguousarray(m).view(dt).reshape(n, nc)
        out = out.astype(np.float64) if a['componentType'] == 5126 else out.astype(np.int64)
        if a.get('normalized') and a['componentType'] != 5126:
            out = out / {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}[a['componentType']]
        return out

    # ------------------------------------------------------------------ hierarchy
    def matrices_monde(self):
        """4x4 world matrix of every node, in the glTF frame (column-vector convention)."""
        n = len(self.g.get('nodes', []))
        parent = [-1] * n
        for i, nd in enumerate(self.g.get('nodes', [])):
            for c in nd.get('children', []):
                parent[c] = i

        def locale(nd):
            # local matrix: either 'matrix' (column-major) or T * R * S
            if 'matrix' in nd:
                return np.array(nd['matrix'], np.float64).reshape(4, 4).T
            m = np.eye(4)
            if 'scale' in nd:
                m[:3, :3] = np.diag(nd['scale'])
            if 'rotation' in nd:
                x, y, z, w = nd['rotation']
                r = np.array([
                    [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
                m[:3, :3] = r @ m[:3, :3]
            if 'translation' in nd:
                m[:3, 3] = nd['translation']
            return m

        out = [None] * n
        def calc(i):
            if out[i] is None:
                m = locale(self.g['nodes'][i])
                out[i] = m if parent[i] < 0 else calc(parent[i]) @ m
            return out[i]
        for i in range(n):
            calc(i)
        return out

    def noeud_du_mesh(self, imesh):
        """Index of the first node that instantiates mesh `imesh`, or None."""
        for i, nd in enumerate(self.g.get('nodes', [])):
            if nd.get('mesh') == imesh:
                return i
        return None

    def image_png(self, iimg):
        """Encoded bytes (PNG/JPEG...) of image `iimg`: embedded, data: URI or external file."""
        im = self.g['images'][iimg]
        if 'bufferView' in im:
            return self.vue(im['bufferView'])[0]
        uri = im.get('uri', '')
        if uri.startswith('data:'):
            return base64.b64decode(uri.split(',', 1)[1])
        base = os.path.dirname(os.path.abspath(self.chemin))
        from urllib.parse import unquote
        return open(os.path.join(base, unquote(uri)), 'rb').read()

    def image_de_materiau(self, imat):
        """Index of the base-colour image of material `imat`, or None."""
        try:
            m = self.g['materials'][imat]
            it = m['pbrMetallicRoughness']['baseColorTexture']['index']
            return self.g['textures'][it]['source']
        except Exception:
            return None


# ---------------------------------------------------------------------- frame conversion
GLTF_VERS_BLENDER = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], np.float64)


def en_repere_sm3(v):
    """(x, y, z)_gltf -> (x, -z, y): the same change as Blender's glTF importer."""
    return v @ GLTF_VERS_BLENDER.T
