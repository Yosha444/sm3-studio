# correctifs_blender/ — our fixes to TSGAMING264's Blender add-ons

*"correctifs" is French for "fixes". This page replaces the French `LISEZMOI.md` of earlier
releases.*

SM3 Studio drives two Blender add-ons written by **TSGAMING264**, the *SM3 Blender Toolkit* and the
*SM3 Material Combiner* (GPL-3.0-or-later, <https://github.com/TSGAMING264/SM3-Blender-Tools>). They
are **not** part of this repository: install them from their author's page.

SM3 Studio was developed and tested with **SM3 Blender Toolkit 1.3.7** and **SM3 Material Combiner
1.4.8**, each carrying small fixes made by this project. Those fixes live inside Blender's
extension folder, not inside SM3 Studio's folder, so **on a new machine they must be applied**;
otherwise they are silently missing.

## The easy way: `apply_fixes.py`

Close Blender, then run:

```bat
python correctifs_blender\apply_fixes.py            (or --check first, to see what it would do)
```

It applies every fix of the table below to the add-ons installed in Blender 5.2's user extension
folder (`--extensions <folder>` or the variable `SM3_BLENDER_EXTENSIONS` for another one). It is
careful:

- a file is patched only if it is **exactly** the version we tested (toolkit 1.3.7, combiner 1.4.8,
  checked by SHA-256); a file that already has our fixes is left alone; any other version is
  refused with a message, and then you apply the changes by hand (last section);
- every change is an exact text replacement that must match once, with an English comment
  explaining it;
- the untouched file is kept as `<file>.before_sm3studio`, and `--undo` puts it back.

Checked: on copies of the original add-ons, the patched code is identical to the add-ons SM3
Studio was developed with; a second run changes nothing; `--undo` restores them byte for byte.

This folder holds every file of the repository derived from TSGAMING264's code, and nothing
else (both are GPL-3.0-or-later, like the add-ons; each lists our changes in its header):

- `apply_fixes.py`, which applies all our fixes to your installed add-ons (above).
- `sm3_baked_atlas.py`, the Material Combiner file with our fixes, for those who prefer to copy a
  file by hand (see below). `apply_fixes.py` makes the same change.
- `blacksuit_mesh_writer.py`, the toolkit's `sm3_mesh_writer.py` with our changes. **Do not copy
  it into Blender**: SM3 Studio's own scripts import it from this folder (see the last section).

Every fix is also described below precisely enough to be re-applied by hand; for most of them SM3
Studio already corrects the result itself (last column).

## The fixes

| # | Add-on file | Change | Why (measured) | Does SM3 Studio make up for it? |
|---|---|---|---|---|
| FIX 1 | Toolkit `sm3_mesh_writer.py` | default vertex colour black instead of white | the game's own main suit model has `0,0,0,255` on every vertex of 8 of its 10 sections (29,674 of its 55,180 vertices, including the section our suit replaces); with white the suit looked washed out in game, "as if light went through it" | **Yes.** Red suit: the converter rewrites the colour of every vertex of both meshes from `qualite.json` and checks it. Black suit: our own writer sets it explicitly. |
| FIX 2 | Toolkit `sm3_mesh_writer.py` | UV divisor 1000 instead of 1024 | the suit's vertex shader multiplies UVs by 0.001; at 1024 the whole atlas is 2.4 % too large and what passes 1.0 wraps to the other edge | **Yes.** `tools/chaine_officielle.py` changes this default in memory before exporting, and the final check requires UVs in 0..1000. |
| Palette | Toolkit `sm3_mesh_writer.py` | reserve all 48 bone slots of a section when writing | the palette is frozen in the written file and the later re-skinning can only fill existing slots; with only the bones present at export (often about 30), the arms, forearms and half the fingers lost their bones | **No.** `poids_depuis_vanilla.py` works within the slots the file has. Apply this one. |
| FIX 3 | Toolkit `sm3_export.py` | write the 001 mesh in its own frame, `(x, y, z)_001 = (z, y + 1.199, -x)_000` | measured on three independent models; without it the second model is turned a quarter turn and sits 1.2 units too low | **Yes** for the red suit (stage `lod` rewrites the 001 with `transplanter_lod.py`, then the final check measures the frame) and the black suit (`blacksuit_build.py` writes both meshes). |
| FIX 4 | Combiner `sm3_baked_atlas.py` (**shipped here**) | the `.tex` gets the same pixels as `atlas_final.png` | the bake image held already-encoded sRGB values that were encoded a second time: `.tex` luminance 156.6 against 108.3 for the PNG on one model (and sRGB(108.3) = 156.5, the curve exactly) | **Yes** for delivered textures: SM3 Studio encodes its own `.tex` from the PNG with `tools/png2tex.py`. |
| Quarter turns | Combiner `sm3_baked_atlas.py` (**shipped here**) | UV islands rotated by multiples of 90° only (`rotate_method='CARDINAL'`) | see the table below | **No.** This is why the file is shipped. |
| FIX 5 | Combiner `sm3_texture.py` | no `PHYS` literal between the 68-byte header and the pixels; the reader accepts both forms | the game's loader expects the pixels right at offset 0x44; the example texture shipped with xeSM3 (`0xDEF62318.i_loading_screen_bkg.tex`, 1024×1024 DXT1) is exactly 0x44 + 1024×1024/2 = 524,356 bytes | **Yes** for delivered textures (written by `tools/png2tex.py`). Recommended anyway if you use the add-on on its own. |

(The fixes are numbered "FIX n/5" in the comments of the patched files; the palette and quarter-turn
changes came later and are not numbered.)

## Installing `sm3_baked_atlas.py`

Close Blender, then copy `correctifs_blender\sm3_baked_atlas.py` over the add-on's file:

```
%APPDATA%\Blender Foundation\Blender\5.2\extensions\user_default\sm3_material_combiner\sm3_baked_atlas.py
```

Keep a copy of the original first. The shipped file is the add-on's version 1.4.8 with FIX 4 and the
quarter-turn change; if you have another version of the add-on, compare before replacing (the two
changed places are marked `FIX 4/5` and `SM3 Studio HQ` in the file).

### Why quarter turns

The add-on called `pack_islands(rotate=True)`, which uses Blender's `rotate_method='ANY'`: islands
were turned by **any** angle, and their content resampled at a slant. Rotation of the islands
between the source unwrap and the atlas, measured on a 20,544-triangle suit:

| | ANY (before) | CARDINAL (after) |
|---|---|---|
| median | 1.77° | 1.07° |
| 90th percentile | 12.21° | 3.09° |
| islands turned by more than 10° | **17.0 %** | 0.4 % |
| atlas coverage | 67.2 % | 63.4 % |
| atlas sharpness | 3.948 | **4.119** |

We give up 3.8 points of coverage (about 2.9 % of linear resolution) to remove the slanted
resampling of 17 % of the body, and the measured sharpness still goes up by 4.3 %. `CARDINAL` only
allows 0/90/180/270°, where resampling is exact. The change falls back step by step (`CARDINAL`,
then `rotate=True`, then no rotation), so a Blender version that does not know `rotate_method`
keeps working.

## Re-applying the fixes by hand

Only needed if `apply_fixes.py` refused your add-on version, and above all for **the palette
fix** (the others are made up for, see the table). The snippets below are the lines this project
added; line numbers are those of toolkit 1.3.7.

**Palette (toolkit `sm3_mesh_writer.py`, in the loop that writes each section, right after the
check that raises "SM3 safe skin-palette limit is 48", around line 446):**

```python
        # Reserve the whole palette: it is frozen in the written file, and every later skinning
        # step can only fill existing slots. The extra slots repeat the last bone: no vertex
        # points at them until they are filled.
        if sec.bone_palette and len(sec.bone_palette) < 48:
            sec.bone_palette = (list(sec.bone_palette)
                                + [sec.bone_palette[-1]] * (48 - len(sec.bone_palette)))
```

**FIX 1 (same file, `class ExportVertex`):** the default of the `color` field becomes
`(0.0, 0.0, 0.0, 1.0)` instead of `(1.0, 1.0, 1.0, 1.0)`.

**FIX 2 (same file, `def encode_player_vertex`):** the default of the `uv_divisor` parameter becomes
`1000.0` instead of `1024.0`.

**FIX 3 (toolkit `sm3_export.py`, in the "Spider 001 one-section build", right after the check that
raises "Prepared Spider mesh became empty during Spider 001 one-section build", around line 854):**

```python
    # The 001 is not in the same frame as the 000: (x, y, z)_001 = (z, y + 1.199, -x)_000.
    # The map has determinant +1 (winding preserved); normals, tangents and binormals get the
    # rotation without the offset.
    def _to_001(p):
        return (p[2], p[1] + 1.199, -p[0])

    def _rot_001(v):
        return (v[2], v[1], -v[0])

    for _v in vertices:
        _v.position = _to_001(_v.position)
        _v.normal = _rot_001(_v.normal)
        _v.tangent = _rot_001(_v.tangent)
        _v.binormal = _rot_001(_v.binormal)
```

**FIX 5 (combiner `sm3_texture.py`):** the data offset constant becomes `0x44` instead of `0x48`;
the writer of a `.tex` from a DDS concatenates the 68-byte header and the pixel data without the
4-byte `b"PHYS"` in between; the reader accepts both forms (pixels at 0x48 when the 4 bytes at 0x44
are `PHYS`, at 0x44 otherwise).

## `blacksuit_mesh_writer.py`: the writer SM3 Studio uses outside Blender

Several of SM3 Studio's scripts write `.mesh` files outside Blender: `transplanter_lod.py` (stage
`lod` of every red-suit conversion: it writes the 001), and `tools/blacksuit_build.py`,
`tools/rvb_native.py` and `tools/cj_build.py` (Black Suit target, Web of Shadows mode, old
prototype). They need the toolkit's writer **with** the fixes above (black vertex colour, UV
divisor 1000) whatever toolkit version is installed, so they use this modified copy of
`sm3_mesh_writer.py` (toolkit 1.3.7, 32 lines changed, listed in its header). It still reads the
installed toolkit's `sm3_format.py`, mounted by `sm3_sans_blender.py`. Each of those scripts adds
this folder to `sys.path`; inside `SM3 Studio.exe` the file is bundled
(`construire/SM3Studio.spec`). Until 2026-10-12 it was tools/blacksuit_mesh_writer.py.

## What was measured, what was not

- Measured: every number in the tables above (September 2026, on this project's test models and on
  the game's own files).
- Measured (2026-10-12): the shipped `sm3_baked_atlas.py` differs from the copy installed on the
  development machine only by comments (same Python syntax tree).
- **Not measured:** a complete conversion with the *unpatched* add-ons. The "does SM3 Studio make up
  for it?" column comes from reading SM3 Studio's code, not from a test run.
