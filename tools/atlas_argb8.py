# SPDX-License-Identifier: GPL-3.0-or-later
"""atlas_argb8.py - re-encode the Material Combiner's final atlas as an UNCOMPRESSED .tex.

Status: NOT USED by SM3 Studio, and broken as it stands: it imports `build_tex`, a module that is
no longer part of the project (its job is now done by tools/png2tex.py, which also writes ARGB8
with `--format ARGB8`). Kept for history only.

What it was for: the Material Combiner add-on writes its .tex in DXT1. The game also accepts
A8R8G8B8 (D3DFORMAT 21): checked in `CalculateMipDataSize` at 0x008DA790 in Game.exe, where case
21 is w*h*4. In our measurements DXT1 cost a mean error of 11.6 on thin lines, with peaks at 83.
The combiner's atlas background is already fully filled (JFA dilation), so a plain box
reduction is enough for the mip levels: no level has black voids to pull onto island borders.

    python atlas_argb8.py --png <..._atlas_final.png> --out <folder> [--hash 0x8E661B33]

Reads the PNG; writes <out>/0x<hash>.<nom>.tex.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_tex import argb8_encode, write_tex   # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--png', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--hash', default='0x8E661B33')
ap.add_argument('--nom', default='ch_spiderman_spider')     # "nom" = resource name
ap.add_argument('--gain', type=float, default=1.0,
                help='< 1 darkens the albedo: the engine ADDS ambient + environment, then applies '
                     'an exponential tone map, so a light albedo saturates to white in game')
ap.add_argument('--contraste', type=float, default=1.0, help='contrast, around mid grey')
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)

im = Image.open(a.png).convert('RGBA')
w, h = im.size
px = np.asarray(im)
noir = float((px[:, :, :3].max(2) <= 12).mean() * 100.0)      # share of near-black texels
print('atlas %dx%d, mean luminance %.1f, %.1f %% near-black texels'
      % (w, h, px[:, :, :3].mean(), noir))

if abs(a.gain - 1.0) > 1e-3 or abs(a.contraste - 1.0) > 1e-3:
    f = px[:, :, :3].astype(np.float32) / 255.0
    f = np.clip(((f - 0.5) * a.contraste + 0.5) * a.gain, 0.0, 1.0)
    px = px.copy()
    px[:, :, :3] = np.clip(f * 255.0 + 0.5, 0, 255).astype(np.uint8)
    im = Image.fromarray(px)
    print('  gain %.2f, contrast %.2f -> luminance %.1f' % (a.gain, a.contraste, px[:, :, :3].mean()))

# Full mip chain down to 1x1, each level a box reduction of the previous one.
cur = im
niveaux = []
while True:
    niveaux.append(argb8_encode(np.asarray(cur, np.uint8), cur.size[0], cur.size[1]))
    if cur.size == (1, 1):
        break
    cur = cur.resize((max(1, cur.size[0] // 2), max(1, cur.size[1] // 2)), Image.BOX)

write_tex(os.path.join(a.out, '0x%08X.%s.tex' % (int(a.hash, 16), a.nom)),
          niveaux, w, h, 'ARGB8', int(a.hash, 16))
