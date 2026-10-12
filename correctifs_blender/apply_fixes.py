# SPDX-License-Identifier: GPL-3.0-or-later
"""apply_fixes.py - apply SM3 Studio's fixes to TSGAMING264's Blender add-ons.

SM3 Studio drives two Blender add-ons written by TSGAMING264 (GPL-3.0-or-later,
https://github.com/TSGAMING264/SM3-Blender-Tools):

    SM3 Blender Toolkit 1.3.7     (folder sm3_blender_toolkit)
    SM3 Material Combiner 1.4.8   (folder sm3_material_combiner)

It was developed and tested with a few small fixes applied to them. Those fixes live in Blender's
extension folder, not in SM3 Studio's folder, so a fresh install of the add-ons does not have
them. This script re-applies them, so that your conversions match ours.

What it changes (details and measurements in README.md, "The fixes"):

    toolkit   sm3_mesh_writer.py   FIX 1   default vertex colour black instead of white
                                   FIX 2   UV divisor 1000 instead of 1024
                                   Palette reserve all 48 bone slots of a section
    toolkit   sm3_export.py        FIX 3   write the 001 mesh in its own frame
    combiner  sm3_baked_atlas.py   FIX 4   the .tex gets the same pixels as atlas_final.png
                                   Quarter turns: UV islands rotated by multiples of 90 degrees
    combiner  sm3_texture.py       FIX 5   no "PHYS" literal after the 68-byte .tex header

How it stays safe:

  * Each file is patched only if it is EXACTLY the version we tested (checked by SHA-256), or if
    it already carries our fixes (then it is left alone). Any other version is refused with a
    message: apply the changes by hand from README.md instead.
  * Every change is an exact text replacement that must match exactly once.
  * The untouched file is kept next to it as <name>.before_sm3studio, and --undo puts it back.
  * Nothing is written with --check.

Usage (close Blender first):

    python apply_fixes.py                 # default folder: Blender 5.2 extensions of this user
    python apply_fixes.py --check         # only report what would happen
    python apply_fixes.py --undo          # restore the files saved before patching
    python apply_fixes.py --extensions "D:/Blender/5.2/extensions/user_default"

The default folder can also be set with the environment variable SM3_BLENDER_EXTENSIONS.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

# Written into every patched file, so a second run recognises it and does nothing.
MARKER = '# Patched by SM3 Studio (correctifs_blender/apply_fixes.py)'
BACKUP_SUFFIX = '.before_sm3studio'


# ---------------------------------------------------------------------------------------------
# The fixes. Each file lists the SHA-256 of the version we tested, and a list of
# (old text, new text) replacements. Text uses "\n" line ends; the file's own line ends (CRLF
# for these add-ons) are restored when writing.
# ---------------------------------------------------------------------------------------------

MESH_WRITER = (
    'sm3_blender_toolkit/sm3_mesh_writer.py',
    'eba89b4d4015d063aa40fa72b1db6d7ebe73f3e2a9185632b4114ebd260c2599',   # toolkit 1.3.7
    [
        (   # FIX 1
            "    color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)\n",
            "    # FIX 1/5 (SM3 Studio) - vertex colour must default to BLACK.\n"
            "    # Measured on the game's own ch_spiderman000: [0, 0, 0, 255] on every vertex of 8 of\n"
            "    # its 10 sections (29,674 of 55,180 vertices). D3DCOLOR at offset 12 of the 52-byte\n"
            "    # stride, byte order B,G,R,A. White made the suit look as if light went through it.\n"
            "    color: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)\n",
        ),
        (   # FIX 2
            "    uv_divisor: float = 1024.0,\n",
            "    # FIX 2/5 (SM3 Studio) - the suit's vertex shader multiplies TEXCOORD0 by 0.001\n"
            "    # (def c235, 0.001 ... mul o2.xy, c235.x, v1), so UVs are stored x1000, not x1024.\n"
            "    # At 1024 the whole atlas is 2.4 % too large and whatever passes 1.0 wraps around.\n"
            "    uv_divisor: float = 1000.0,\n",
        ),
        (   # Palette reservation
            '            raise ValueError(f"section {sec_i} palette has {len(sec.bone_palette)} bones; '
            'SM3 safe skin-palette limit is 48")\n',
            '            raise ValueError(f"section {sec_i} palette has {len(sec.bone_palette)} bones; '
            'SM3 safe skin-palette limit is 48")\n'
            "        # Palette reservation (SM3 Studio) - reserve all 48 slots. The palette is frozen in\n"
            "        # the written file, and a later re-skinning step can only fill slots that exist.\n"
            "        # With only the bones present at export (often about 30), a whole body (about 52)\n"
            "        # did not fit and the lightest bones lost: upperarm, its three splits, half the\n"
            "        # fingers. The extra slots repeat the last bone: no vertex points at them until\n"
            "        # they are filled, and palette_lookup returns the same global index for a repeat.\n"
            "        if sec.bone_palette and len(sec.bone_palette) < 48:\n"
            "            sec.bone_palette = (list(sec.bone_palette)\n"
            "                                + [sec.bone_palette[-1]] * (48 - len(sec.bone_palette)))\n",
        ),
    ],
)

EXPORT = (
    'sm3_blender_toolkit/sm3_export.py',
    '7dc5f4e618c4c7df8e1e8ef7ac5ce3a43a779737a9875bf17fdda70978563240',   # toolkit 1.3.7
    [
        (   # FIX 3
            "        raise ValueError('Prepared Spider mesh became empty during Spider 001 one-section build')\n"
            "\n"
            "    section = ExportSection(\n",
            "        raise ValueError('Prepared Spider mesh became empty during Spider 001 one-section build')\n"
            "\n"
            "    # FIX 3/5 (SM3 Studio) - the 001 is NOT in the same frame as the 000.\n"
            "    # Measured on three independent models: (x, y, z)_001 = (z, y + 1.199, -x)_000.\n"
            "    # Without this the far model is turned a quarter turn and sits 1.2 units too low.\n"
            "    # The map has determinant +1, so the triangle winding is kept; normals, tangents and\n"
            "    # binormals get the same rotation, WITHOUT the offset.\n"
            "    def _to_001(p):\n"
            "        return (p[2], p[1] + 1.199, -p[0])\n"
            "\n"
            "    def _rot_001(v):\n"
            "        return (v[2], v[1], -v[0])\n"
            "\n"
            "    for _v in vertices:\n"
            "        _v.position = _to_001(_v.position)\n"
            "        _v.normal = _rot_001(_v.normal)\n"
            "        _v.tangent = _rot_001(_v.tangent)\n"
            "        _v.binormal = _rot_001(_v.binormal)\n"
            "\n"
            "    section = ExportSection(\n",
        ),
    ],
)

BAKED_ATLAS = (
    'sm3_material_combiner/sm3_baked_atlas.py',
    '9c51a958c52569d569bf092a168593c0a392c2cd9e99f99dd3891ec66724e4a6',   # combiner 1.4.8
    [
        (   # Quarter turns
            "    try:\n"
            "        bpy.ops.uv.pack_islands(margin=uv_margin, rotate=True)\n"
            "    except TypeError:\n"
            "        bpy.ops.uv.pack_islands(margin=uv_margin)\n",
            "    # Quarter turns (SM3 Studio) - rotate UV islands by multiples of 90 degrees only.\n"
            "    # With Blender's default rotate_method='ANY', on a 20,544-triangle suit 17.0 % of the\n"
            "    # surface ended up more than 10 degrees off a right angle, so fine regular patterns\n"
            "    # (fabric grain, web lines) were resampled at a slant and turned into stairs and moire.\n"
            "    # 'CARDINAL' keeps the packing benefit of rotation without slanted resampling.\n"
            "    for _kw in ({'rotate': True, 'rotate_method': 'CARDINAL'}, {'rotate': True}, {}):\n"
            "        try:\n"
            "            bpy.ops.uv.pack_islands(margin=uv_margin, **_kw)\n"
            "            break\n"
            "        except TypeError:\n"
            "            continue\n",
        ),
        (   # FIX 4
            "        tex_pixels_top_down = np.ascontiguousarray(final[::-1, :, :])\n",
            "        # FIX 4/5 (SM3 Studio) - the .tex must carry the SAME pixels as atlas_final.png.\n"
            "        # `final` is read from a BYTE bake image whose pixels already hold sRGB values, and\n"
            "        # _linear_to_srgb is applied a second time. atlas_final.png undoes it (the PNG is\n"
            "        # saved through _srgb_to_linear); the .tex did not, and shipped about twice as\n"
            "        # bright (measured: .tex luminance 156.6 against 108.3 for the PNG, and\n"
            "        # srgb(108.3) = 156.5). Same transform as _save_srgb_png, so .tex == PNG.\n"
            "        _tex_f = final.astype(np.float32) / 255.0\n"
            "        _tex_f[:, :, :3] = _srgb_to_linear(_tex_f[:, :, :3])\n"
            "        _tex_u8 = np.clip(_tex_f * 255.0 + 0.5, 0, 255).astype(np.uint8)\n"
            "        tex_pixels_top_down = np.ascontiguousarray(_tex_u8[::-1, :, :])\n",
        ),
    ],
)

TEXTURE = (
    'sm3_material_combiner/sm3_texture.py',
    '2079ffbde7a4e6ac040c772d8f14126fe68a21eeda8b0c19e028b8e701d19d27',   # combiner 1.4.8
    [
        (   # FIX 5: offset constant
            "SM3_TEX_DATA_OFFSET = 0x48  # 0x44-byte IMG + literal PHYS\n",
            "# FIX 5/5 (SM3 Studio) - the game's loader expects the 68-byte IMG header followed\n"
            "# IMMEDIATELY by the DXT chain. 0x48 assumed a 4-byte \"PHYS\" literal that does not\n"
            "# belong there.\n"
            "SM3_TEX_DATA_OFFSET = 0x44\n"
            "SM3_TEX_DATA_OFFSET_LEGACY_PHYS = 0x48\n",
        ),
        (   # FIX 5: writer
            '    out = bytes(img) + b"PHYS" + dds.data\n',
            "    # FIX 5/5 (SM3 Studio) - no \"PHYS\" literal: the four extra bytes shifted every block.\n"
            "    # The example texture shipped with xeSM3, 0xDEF62318.i_loading_screen_bkg.tex\n"
            "    # (1024x1024 DXT1), is exactly 0x44 + 1024*1024/2 bytes.\n"
            "    out = bytes(img) + dds.data\n",
        ),
        (   # FIX 5b: reader accepts both forms
            "    if len(raw) < SM3_TEX_DATA_OFFSET:\n"
            '        raise ValueError("File is too small to be an SM3 raw TEX")\n'
            '    if raw[0x44:0x48] != b"PHYS":\n'
            '        raise ValueError("Not an SM3 raw TEX: expected PHYS at offset 0x44")\n',
            "    if len(raw) < 0x44:\n"
            '        raise ValueError("File is too small to be an SM3 raw TEX")\n'
            "    # FIX 5b/5 (SM3 Studio) - accept a .tex WITHOUT the PHYS literal (the correct shape,\n"
            "    # see FIX 5), and still accept the legacy PHYS form written by earlier versions.\n"
            '    _legacy_phys = raw[0x44:0x48] == b"PHYS"\n'
            "    data_offset = 0x48 if _legacy_phys else 0x44\n",
        ),
        (   # FIX 5b: read from the detected offset
            "        data=raw[SM3_TEX_DATA_OFFSET:],\n",
            "        data=raw[data_offset:],\n",
        ),
    ],
)

FIXES = [MESH_WRITER, EXPORT, BAKED_ATLAS, TEXTURE]


# ---------------------------------------------------------------------------------------------

def default_extensions_folder() -> Path:
    """Blender 5.2's user extension folder, unless SM3_BLENDER_EXTENSIONS says otherwise."""
    env = os.environ.get('SM3_BLENDER_EXTENSIONS')
    if env:
        return Path(env)
    appdata = os.environ.get('APPDATA', '')
    return Path(appdata) / 'Blender Foundation' / 'Blender' / '5.2' / 'extensions' / 'user_default'


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patched_text(original: str, replacements) -> str:
    """Apply the replacements to text with "\\n" line ends. Each old text must occur exactly once,
    otherwise the file is not the version we know and we stop rather than guess."""
    text = original
    for i, (old, new) in enumerate(replacements, 1):
        count = text.count(old)
        if count != 1:
            raise ValueError('change %d: expected text found %d times (expected once)' % (i, count))
        text = text.replace(old, new)
    return text


def apply_one(folder: Path, rel: str, expected_sha: str, replacements, check: bool) -> str:
    path = folder / rel
    if not path.is_file():
        return 'MISSING   %s (is the add-on installed in %s?)' % (rel, folder)
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    if MARKER in text:
        return 'ALREADY   %s (our fixes are already there)' % rel
    if sha256(raw) != expected_sha:
        return ('REFUSED   %s: not the version we tested (SHA-256 differs). Apply the changes by '
                'hand from README.md, "The fixes".' % rel)
    crlf = '\r\n' in text
    body = text.replace('\r\n', '\n')
    try:
        new_body = patched_text(body, replacements)
    except ValueError as e:
        return 'REFUSED   %s: %s' % (rel, e)
    new_body = MARKER + '\n' + new_body
    if crlf:
        new_body = new_body.replace('\n', '\r\n')
    if check:
        return 'WOULD FIX %s (%d change(s))' % (rel, len(replacements))
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    if not backup.exists():
        backup.write_bytes(raw)
    path.write_bytes(new_body.encode('utf-8'))
    return 'FIXED     %s (%d change(s); original kept as %s)' % (rel, len(replacements), backup.name)


def undo_one(folder: Path, rel: str, check: bool) -> str:
    path = folder / rel
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    if not backup.is_file():
        return 'NOTHING   %s (no %s backup)' % (rel, BACKUP_SUFFIX)
    if check:
        return 'WOULD RESTORE %s' % rel
    path.write_bytes(backup.read_bytes())
    backup.unlink()
    return 'RESTORED  %s' % rel


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Apply SM3 Studio's fixes to TSGAMING264's add-ons.")
    ap.add_argument('--extensions', type=Path, default=None,
                    help="Blender's user extension folder (default: Blender 5.2 for this user)")
    ap.add_argument('--check', action='store_true', help='only report what would happen')
    ap.add_argument('--undo', action='store_true', help='restore the files saved before patching')
    a = ap.parse_args(argv)
    folder = a.extensions or default_extensions_folder()
    print('Blender extensions folder: %s' % folder)
    if not folder.is_dir():
        print('!! folder not found: pass --extensions or set SM3_BLENDER_EXTENSIONS')
        return 1
    problems = 0
    for rel, expected_sha, replacements in FIXES:
        line = undo_one(folder, rel, a.check) if a.undo else apply_one(folder, rel, expected_sha,
                                                                      replacements, a.check)
        print(line)
        problems += line.startswith(('REFUSED', 'MISSING'))
    if not a.check and not a.undo and not problems:
        print('Done. Restart Blender (or reload the add-ons) for the fixes to take effect.')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
