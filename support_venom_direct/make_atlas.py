#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Make the two per-mod files of the Venom draw adapter from a converted Venom mod.

    python make_atlas.py "<SM3 Studio>\\build\\<mod name>"

Reads, in that build folder (written by SM3 Studio's Venom conversion):
    SM3_Spider_Baked_Atlas_atlas_final.png   the full-colour atlas baked from your model (4096 x 4096)
    0xBF11C1BF.ch_venom000.mesh              the converted mesh (for its UV islands)
    0xA164D857.ch_venom_ppi.tex              the palette-index texture the game will load
Writes, next to this script:
    venom_direct_atlas.tex   the colour atlas in the game's .tex container (ARGB8, 13 mip levels).
                             The adapter loads it from the game folder and binds it to sampler 6.
    atlas_signature.h        32 texels of the index texture: how the adapter recognises, at draw
                             time, that the texture bound to sampler 6 is THIS mod's Venom texture
                             (compiled into winmm.dll).
    atlas_signature.json     sha256 of the mesh, index texture and atlas, checked by install.py so
                             that the DLL is only installed next to the mod it was built for.

Why. The game draws Venom with a 256-colour palette: index texture + palette. The adapter swaps
the palette lookup for a direct read of a full-colour atlas (see make_shaders_h.py), so detail
lost to the 256-colour reduction comes back. Nothing here comes from the game: the atlas is your
model's bake, the probes are texels of the texture SM3 Studio made from it.

The atlas islands are first dilated by 12 pixels (same code as the Spider-Man conversion,
dilater_atlas.py), so that mip levels do not bleed the background into the seams.
The probe positions are a fixed spread of 32 points, x = (113 + 811 k) mod width,
y = (277 + 463 k) mod height, k = 0..31 (the values of the first build, kept so that a rebuild
gives the same header).
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path[:0] = [REPO, os.path.join(REPO, 'tools')]

ATLAS_PNG = 'SM3_Spider_Baked_Atlas_atlas_final.png'
MESH = '0xBF11C1BF.ch_venom000.mesh'
INDEX_TEX = '0xA164D857.ch_venom_ppi.tex'
ATLAS_HASH = 0x8E661B33          # texture hash written in the .tex header (Spider-Man's suit texture id)
DILATION = 12
PROBES = 32


def probe_positions(width, height):
    return [((113 + 811 * k) % width, (277 + 463 * k) % height) for k in range(PROBES)]


def signature_header(index_tex):
    """atlas_signature.h text from the level-0 texels of the index texture (BGRA as one DWORD)."""
    w, h, depth, levels, code = struct.unpack_from('<5I', index_tex, 24)
    if code != 21 or depth != 1:
        raise SystemExit('%s is not an ARGB8 texture (format code %d).' % (INDEX_TEX, code))
    probes = [(x, y, struct.unpack_from('<I', index_tex, 68 + (y * w + x) * 4)[0]) for x, y in probe_positions(w, h)]
    return ('static const UINT atlasWidth=%d,atlasHeight=%d;\r\n' % (w, h)
            + 'struct Probe { UINT x,y; DWORD bgra; };\r\n'
            + 'static const Probe atlasProbes[]={' + ','.join('{%d,%d,%d}' % p for p in probes) + '};\r\n')


def make_atlas(build, out_tex):
    import numpy as np
    from PIL import Image
    from dilater_atlas import couverture, dilate, fmt
    from png2tex import write_tex
    from sm3.texfind import decode_level
    with Image.open(os.path.join(build, ATLAS_PNG)) as image:
        rgba = np.array(image.convert('RGBA'))
    h, w = rgba.shape[:2]
    if (w, h) != (4096, 4096):
        raise SystemExit('the atlas is %dx%d; the adapter only loads a 4096 x 4096 atlas.' % (w, h))
    mask = np.zeros((h, w), bool)
    mesh = fmt.parse_mesh(os.path.join(build, MESH))
    for section in mesh.sections:
        data = fmt.decode_section_vertices(mesh, section, uv_divisor=1024)
        uv = np.array(data['texcoords'][0])
        uv[:, 1] = 1 - uv[:, 1]
        faces = np.array(fmt.indices_to_faces(fmt.read_indices(mesh, section), section.primitive_type, section.vertex_count))
        mask |= couverture(uv, faces, (w, h))
    pixels, _ = dilate(rgba, mask, DILATION)
    if not np.array_equal(pixels[mask], rgba[mask]):
        raise SystemExit('dilation changed pixels inside the UV islands.')
    png = out_tex + '.dilated.png'
    Image.fromarray(pixels).save(png)
    try:
        write_tex(png, out_tex, ATLAS_HASH, fmt='ARGB8', mips='full')
    finally:
        os.remove(png)
    with open(out_tex, 'rb') as f:
        decoded = decode_level(f.read()[68:], 'a8r8g8b8', w, h)
    if not np.array_equal(decoded, pixels):
        raise SystemExit('the written atlas does not decode back to the dilated image.')


def main(argv=None):
    ap = argparse.ArgumentParser(description='Make venom_direct_atlas.tex and atlas_signature.h from a converted Venom mod.')
    ap.add_argument('build', help='SM3 Studio build folder of the Venom mod (build\\<mod name>)')
    ap.add_argument('--out', default=HERE, help='output folder (default: next to this script)')
    a = ap.parse_args(argv)
    for name in (ATLAS_PNG, MESH, INDEX_TEX):
        if not os.path.isfile(os.path.join(a.build, name)):
            raise SystemExit('missing in the build folder: ' + name)
    with open(os.path.join(a.build, INDEX_TEX), 'rb') as f:
        index_tex = f.read()
    header = signature_header(index_tex)
    with open(os.path.join(a.out, 'atlas_signature.h'), 'wb') as f:
        f.write(header.encode('ascii'))
    out_tex = os.path.join(a.out, 'venom_direct_atlas.tex')
    make_atlas(a.build, out_tex)
    sha = lambda p: hashlib.sha256(open(p, 'rb').read()).hexdigest()
    record = {'mesh_sha256': sha(os.path.join(a.build, MESH)), 'index_texture_sha256': hashlib.sha256(index_tex).hexdigest(),
              'atlas_sha256': sha(out_tex), 'atlas_signature_h_sha256': hashlib.sha256(header.encode('ascii')).hexdigest()}
    with open(os.path.join(a.out, 'atlas_signature.json'), 'w', encoding='utf-8') as f:
        json.dump(record, f, indent=2)
    print(json.dumps(record, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
