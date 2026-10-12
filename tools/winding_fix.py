# SPDX-License-Identifier: GPL-3.0-or-later
"""winding_fix.py - check and fix the FACE ORIENTATION and the NORMAL DIRECTION of a delivered .mesh.

Last check run on every delivered player mesh: sm3_convertir.py calls it on the red suit's 000
then 001 (in-process, through lance()), blacksuit_finalize.py on the black suit's 000 then 001,
rvb_finalize.py on the Web of Shadows meshes. It rewrites the .mesh in place.

Two independent defects, both produced by a mirror on X (needed when a model has its left on the
wrong side), and both invisible in Blender:

1. THE WINDING. Test: signed volume of the closed mesh, sum( v0 . (v1 x v2) ) / 6.
   It is NEGATIVE on everything that works in game (vanilla -0.116, Sukuna -0.181) and came out
   at +0.135 after a mirror. The game then culls the outside: you see the inside of the
   character. Fix: swap indices 1 and 2 of every triangle.

2. THE NORMALS. Absolute test, no reference needed: a normal must point away from the mesh's
   centre. Mean of normal . (vertex - centre): vanilla +0.229, Sukuna +0.107, and -0.150 after a
   mirror. The engine lights with the STORED normals (they do not follow the winding, even on the
   vanilla model), so inward normals render the character black.
   Fix: negate normal and binormal (the tangent stays; the basis handedness follows the normal).

3. THE HANDS (2026-10-06). This script is the LAST step read from disk that both chains run on
   every delivered mesh: `sm3_convertir` (red suit, bundled in the .exe) calls it on the 000 then
   the 001, `blacksuit_finalize` on the black 000 then 001. So this is where
   `mains_poings.apres_winding()` gives the fingers back their 30 phalanges (fists clenched at
   rest), without rebuilding the .exe. It only touches the 4 player meshes produced by the Studio
   chain (an `etape_poids.mesh` next to them), never a Web of Shadows (RvB) export. A failure does
   not stop the conversion: it is printed with `!!` and the mesh stays as the chain produced it.
   See tools/mains_poings.py ("hands, fists").

4. THE SECTIONS (2026-10-08). The game only reads 16-bit indices: a section with more than
   65,535 vertices (written with 32-bit indices by our writers) comes out torn, without any
   error. Last step, after the hands (which may write such a section on a dense model):
   `decoupe_sections` splits it into sections of at most 65,535 vertices (red suit, material by
   reference), or REFUSES the mesh (black suit and others, material by index). Unlike the hands,
   this one BLOCKS: exit code 1, the conversion stops, nothing is assembled. A mesh that already
   complies is not rewritten. See tools/decoupe_sections.py ("section splitting").

    python winding_fix.py <file.mesh> [--dry] [--sans-mains]
    --sans-mains ("without hands") or SM3_MAINS_POINGS=0 skips step 3. Step 4 cannot be skipped.

Assumes the player-mesh vertex layout: position SHORT4 at +0 (/512), normal / tangent /
binormal SHORT4N at +16 / +24 / +32 (see OFF_NOR below).
"""
import argparse
import importlib.util
import os
import sys

import numpy as np

# TSGAMING264's SM3 Blender Toolkit, where Blender 5.2 installs extensions for the current user.
# Only its pure-Python parser sm3_format.py is loaded (this script runs outside Blender).
EXT = os.path.join(os.environ.get('APPDATA', ''), 'Blender Foundation', 'Blender', '5.2',
                   'extensions', 'user_default', 'sm3_blender_toolkit')
_s = importlib.util.spec_from_file_location('sm3_format', os.path.join(EXT, 'sm3_format.py'))
fmt = importlib.util.module_from_spec(_s)
sys.modules['sm3_format'] = fmt
_s.loader.exec_module(fmt)

ap = argparse.ArgumentParser()
ap.add_argument('mesh')
ap.add_argument('--dry', action='store_true', help='measure without writing anything')
ap.add_argument('--sans-mains', action='store_true',
                help='do not give the fingers back their phalanges (tools/mains_poings.py)')
A = None                      # set by main(): see below

# byte offsets of NORMAL, TANGENT, BINORMAL in the 52-byte player vertex (SHORT4N each)
OFF_NOR, OFF_TAN, OFF_BIN = 16, 24, 32


def mesures(data):
    """("measurements") (signed volume, mean of normal . radial direction)."""
    m = fmt.parse_mesh(A.mesh)
    vol = 0.0
    P, N = [], []
    for s in m.sections:
        vo, vc, st = s.vertex_buffer_offset, s.vertex_count, s.vertex_stride
        if not vc:
            continue
        raw = np.frombuffer(data[vo:vo + vc * st], np.uint8).reshape(vc, st)
        pos = raw[:, 0:8].copy().view(np.int16).astype(np.float64)[:, :3] / 512.0
        nor = raw[:, OFF_NOR:OFF_NOR + 8].copy().view(np.int16).astype(np.float64)[:, :3] / 32767.0
        P.append(pos)
        N.append(nor)
        if s.index_count % 3 == 0:
            # WARNING: the SECTION's index size, not 2 by default: a section with more than
            # 65,535 vertices arrives here with 32-bit indices (it is only split at step 4). Read
            # as 16 bits, each 32-bit index gave two false indices (low word, high word).
            # Measured on raimi_nodecim (156,115 vertices): volume read +0.962 "FACES INVERTED"
            # instead of -2.113, and the "fix" swapped half-indices: 288,692 indices changed out
            # of 577,383, 192,458 of them outside the vertices. The model was destroyed before
            # it even reached the game.
            t = '<u2' if s.index_size == 2 else '<u4'
            ind = np.frombuffer(data[s.index_buffer_offset:
                                     s.index_buffer_offset + s.index_count * s.index_size],
                                t).astype(np.int64).reshape(-1, 3)
            Q = pos[ind]
            vol += float(np.einsum('ij,ij->i', Q[:, 0], np.cross(Q[:, 1], Q[:, 2])).sum() / 6.0)
    P = np.vstack(P)
    N = np.vstack(N)
    r = P - P.mean(0)
    r /= np.linalg.norm(r, axis=1, keepdims=True) + 1e-9
    N = N / (np.linalg.norm(N, axis=1, keepdims=True) + 1e-9)
    return vol, float(np.einsum('ij,ij->i', r, N).mean())


def mains(chemin):
    """Step 3: the 30 finger bones (tools/mains_poings.py), AFTER the face orientation.

    WARNING: loaded from DISK, next to this file, and never fatal: the conversion has already
    produced a valid mesh, and an open hand is better than a mod that is not delivered. The
    failure is printed with `!!` so it does not go unnoticed."""
    if A.sans_mains or os.environ.get('SM3_MAINS_POINGS', '1') == '0':
        return None
    try:
        chemin_mp = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mains_poings.py')
        mp = sys.modules.get('mains_poings')
        if mp is None or os.path.abspath(getattr(mp, '__file__', '')) != chemin_mp:
            s = importlib.util.spec_from_file_location('mains_poings', chemin_mp)
            mp = importlib.util.module_from_spec(s)
            sys.modules['mains_poings'] = mp
            s.loader.exec_module(mp)
        return mp.apres_winding(chemin, log=lambda *x: print('  [mains]', *x, flush=True))
    except Exception as e:                      # noqa: BLE001 -- never fatal, see above
        print('  !! hands: %s: %s -- mesh left as it is (fingers without phalanges)'
              % (type(e).__name__, e), flush=True)
        return None


def _controle_brut(chemin):
    """The blocking check without decoupe_sections.py ("raw check"): re-reads the sections with
    the toolkit's reader only. Used when that tool is missing or crashes. Returns the problems."""
    m = fmt.parse_mesh(chemin)
    return ['section %d: %d vertices, %d-byte indices' % (s.index, s.vertex_count, s.index_size)
            for s in m.sections if s.vertex_count > 0xFFFF or s.index_size != 2]


def decoupe(chemin):
    """Step 4: no section with more than 65,535 vertices, never 32-bit indices
    (tools/decoupe_sections.py). AFTER the hands: mains_poings may itself write a section that is
    too large on a dense model.

    WARNING: BLOCKING, unlike the hands: the game silently truncates 32-bit indices, and the
    model would come out torn. A refusal exits with code 1 (SystemExit): the conversion stops
    before assembly. A crash of the tool itself stops nothing if the file already complies
    (re-read by _controle_brut), and stops everything otherwise."""
    if A.dry:
        p = _controle_brut(chemin)
        print('  sections: %s' % ('compliant (at most 65,535 vertices, 16-bit indices)' if not p
                                  else 'TO SPLIT -- ' + '; '.join(p)), flush=True)
        return None
    log = lambda *x: print('  [sections]', *x, flush=True)      # noqa: E731
    try:
        chemin_ds = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'decoupe_sections.py')
        ds = sys.modules.get('decoupe_sections')
        if ds is None or os.path.abspath(getattr(ds, '__file__', '')) != chemin_ds:
            s = importlib.util.spec_from_file_location('decoupe_sections', chemin_ds)
            ds = importlib.util.module_from_spec(s)
            sys.modules['decoupe_sections'] = ds
            s.loader.exec_module(ds)
    except Exception as e:                      # noqa: BLE001 -- fall back on the raw check
        ds = None
        print('  !! sections: tool unavailable (%s: %s)' % (type(e).__name__, e), flush=True)
    if ds is not None:
        try:
            return ds.apres_mains(chemin, log=log)
        except ds.RefusDecoupe as e:
            print('  !! sections: %s' % e, flush=True)
            raise SystemExit('%s REFUSED: %s' % (os.path.basename(chemin), e))
        except Exception as e:                  # noqa: BLE001 -- decided by the raw check
            print('  !! sections: %s: %s' % (type(e).__name__, e), flush=True)
    p = _controle_brut(chemin)
    if p:
        raise SystemExit('%s REFUSED: %s -- the game would truncate the indices and tear the model'
                         % (os.path.basename(chemin), '; '.join(p)))
    print('  sections: compliant despite the error above (at most 65,535 vertices, 16-bit indices)'
          ' -> mesh left as it is', flush=True)
    return None


def main():
    """The actual work.

    WARNING: the parser does NOT run at import time. `sm3_convertir.lance()` imports this file
    and then sets `sys.argv`: parsing at import time read the converter's own command line, whose
    mod name ended up in `mesh`.
    """
    global A
    A = ap.parse_args()
    d = bytearray(open(A.mesh, 'rb').read())
    vol, sortant = mesures(bytes(d))
    print('%s' % os.path.basename(A.mesh))
    print('  signed volume       %+.4f  (%s; vanilla -0.116)'
          % (vol, 'OK' if vol < 0 else 'FACES INVERTED'))
    print('  outward normals     %+.4f  (%s; vanilla +0.229)'
          % (sortant, 'OK' if sortant > 0 else 'INWARD NORMALS'))
    if A.dry or (vol < 0 and sortant > 0):
        if not A.dry:
            mains(A.mesh)
        decoupe(A.mesh)
        sys.exit(0)

    m = fmt.parse_mesh(A.mesh)
    if vol >= 0:
        n = 0
        for s in m.sections:
            if s.index_count % 3:
                print('  section %d is a strip: winding not fixed' % s.index)
                continue
            off, isz = s.index_buffer_offset, s.index_size
            t = '<u2' if isz == 2 else '<u4'        # same trap as in mesures()
            ind = np.frombuffer(bytes(d[off:off + s.index_count * isz]), t).copy().reshape(-1, 3)
            ind[:, [1, 2]] = ind[:, [2, 1]]
            d[off:off + s.index_count * isz] = ind.astype(t).tobytes()
            n += len(ind)
        print('  -> %d triangle(s) flipped' % n)
    if sortant <= 0:
        n = 0
        for s in m.sections:
            vo, vc, st = s.vertex_buffer_offset, s.vertex_count, s.vertex_stride
            if not vc:
                continue
            blk = np.frombuffer(bytes(d[vo:vo + vc * st]), np.uint8).copy().reshape(vc, st)
            for off in (OFF_NOR, OFF_BIN):
                q = blk[:, off:off + 8].copy().view(np.int16)
                q[:, :3] = np.clip(-q[:, :3].astype(np.int32), -32767, 32767).astype(np.int16)
                blk[:, off:off + 8] = q.view(np.uint8)
            d[vo:vo + vc * st] = blk.tobytes()
            n += vc
        print('  -> normal and binormal negated on %d vertex(es)' % n)

    open(A.mesh, 'wb').write(bytes(d))
    vol, sortant = mesures(bytes(open(A.mesh, 'rb').read()))
    print('  after the fix: volume %+.4f (%s), normals %+.4f (%s)'
          % (vol, 'OK' if vol < 0 else 'FAILED', sortant, 'OK' if sortant > 0 else 'FAILED'))
    mains(A.mesh)
    decoupe(A.mesh)


if __name__ == '__main__':
    main()
