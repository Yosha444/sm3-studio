# SPDX-License-Identifier: GPL-3.0-or-later
"""uv_1000.py - fix the UV divisor of an already written .mesh: from 1024 to 1000.

Status: manual repair tool, NOT CALLED by SM3 Studio. The converter now writes UVs for the
right divisor directly (see sm3_sans_blender.py: "position /512 and UV *1000"); this script
repairs a .mesh exported earlier with the toolkit's * 1024.

Where 1000 comes from. The suit's vertex shader (dumped from Game.exe as 006a19b0_vs30_169i.bin)
does

    def c235, 0.001, -0.5, 6.999, 0
    def c236, 3, 0.00195312, 0, 1
    mad r0, v0.xyzx, c236.yyyz, c236.zzzw     ; POSITION x 0.00195312 = 1/512
    mul o2.xy, c235.x, v1                     ; TEXCOORD0 x 0.001 = 1/1000

and its input declarations give v0 = POSITION0, v1 = TEXCOORD0. The position divisor 1/512 is
one we already knew for certain, which anchors the reading. It is also the only large skinned
character vertex shader of the binary that contains 0.001 and not 1/1024.

The toolkit's exporter encodes uv * 1024. Consequences:
  - the whole atlas is enlarged by 2.4 % around the origin;
  - whatever goes past 1.0 wraps onto the opposite edge (ADDRESSU/V = WRAP everywhere);
  - above all, a section deliberately placed in the SECOND V tile (the lower body of
    TSGAMING264's model has half its UVs above 1024) sees its tile boundary land in the wrong
    place, so that whole group shifts.

Fixing it afterwards means multiplying the stored integers by 1000/1024 = 0.9765625: a value
authored for 1024 lands exactly on the same UV once divided by 1000.

    python uv_1000.py <file.mesh> [--facteur 0.9765625] [--dry]

Rewrites the .mesh in place (every TEXCOORD of every section, stored as int16 pairs); --dry only
prints the ranges before/after.
"""
import argparse
import importlib.util
import os
import sys

import numpy as np

# TSGAMING264's SM3 Blender Toolkit, where Blender 5.2 installs extensions for the current user.
# Only its pure-Python parser sm3_format.py is loaded (no Blender needed).
EXT = os.path.join(os.environ.get('APPDATA', ''), 'Blender Foundation', 'Blender', '5.2',
                   'extensions', 'user_default', 'sm3_blender_toolkit')
_s = importlib.util.spec_from_file_location('sm3_format', os.path.join(EXT, 'sm3_format.py'))
fmt = importlib.util.module_from_spec(_s)
sys.modules['sm3_format'] = fmt
_s.loader.exec_module(fmt)

ap = argparse.ArgumentParser()
ap.add_argument('mesh')
ap.add_argument('--facteur', type=float, default=1000.0 / 1024.0)     # "facteur" = factor
ap.add_argument('--dry', action='store_true', help='measure without writing')
A = None                      # set by main(): see below

def main():
    """The actual work.

    WARNING: the parser does NOT run at import time. `sm3_convertir.lance()` imports this file
    and then sets `sys.argv`: parsing at import time read the converter's own command line, whose
    mod name ended up in `mesh`.
    """
    global A
    A = ap.parse_args()
    d = bytearray(open(A.mesh, 'rb').read())
    m = fmt.parse_mesh(A.mesh)
    print('%s: %d section(s), factor %.7f' % (os.path.basename(A.mesh), m.section_count, A.facteur))

    total = 0
    for s in m.sections:
        vo, vc, st = s.vertex_buffer_offset, s.vertex_count, s.vertex_stride
        if not vc:
            continue
        offs = [dc.offset for dc in s.decl if dc.usage == 5]      # every TEXCOORD (D3DDECLUSAGE 5)
        if not offs:
            continue
        blk = np.frombuffer(bytes(d[vo:vo + vc * st]), np.uint8).copy().reshape(vc, st)
        avant = []            # (min, max) before
        apres = []            # (min, max) after
        for off in offs:
            q = blk[:, off:off + 4].copy().view(np.int16)          # u, v as two int16
            avant.append((int(q.min()), int(q.max())))
            # WARNING: round to nearest, in float64 so nothing overflows before the clamp
            r = np.rint(q.astype(np.float64) * A.facteur)
            q[:] = np.clip(r, -32768, 32767).astype(np.int16)
            blk[:, off:off + 4] = q.view(np.uint8)
            apres.append((int(q.min()), int(q.max())))
        if not A.dry:
            d[vo:vo + vc * st] = blk.tobytes()
        total += vc * len(offs)
        print('   sec %d: %d UV set(s) on %6d vertices | %s -> %s'
              % (s.index, len(offs), vc,
                 ' '.join('[%d..%d]' % t for t in avant), ' '.join('[%d..%d]' % t for t in apres)))

    if A.dry:
        print('  (--dry: nothing written)')
    else:
        open(A.mesh, 'wb').write(bytes(d))
        print('  %d coordinate(s) rescaled, file rewritten' % total)


if __name__ == '__main__':
    main()
