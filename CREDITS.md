# Credits

## SM3 Studio

SM3 Studio — the converter, its window, the checks, the texture encoder, the game-data extractor,
the Matte suit patch, the measurements and the documentation in this repository — was made by
**Yosha444**, with AI coding assistants, between August and October 2026.

## TSGAMING264

None of this would load in the game without **TSGAMING264**'s work. SM3 Studio depends on it and
does not include it: install it from his pages.

| Project | What SM3 Studio uses it for | Licence |
|---|---|---|
| **xeSM3** — <https://github.com/TSGAMING264/xeSM3> | the mod loader: the game loads SM3 Studio's mods through it; SM3 Studio writes mods in its folder layout and enables them in its `mods.config.ini` | see its repository |
| **SM3 Blender Toolkit** (Blender add-on) — <https://github.com/TSGAMING264/SM3-Blender-Tools> | importing the game's suit as a target, the dedicated suit exporters, and its `sm3_format.py` / `sm3_mesh_writer.py`, which SM3 Studio loads to read and write `.mesh` and `.skel` files everywhere | GPL-3.0-or-later |
| **SM3 Material Combiner** (Blender add-on), same repository | wiring the model's textures and baking the texture atlas | GPL-3.0-or-later |

Files in this repository derived from his code, redistributed under the same licence, with our
changes listed in each file's header:

- `correctifs_blender/blacksuit_mesh_writer.py` — a modified copy of the toolkit's
  `sm3_mesh_writer.py` (import path, black vertex colour by default, UV divisor 1000, palette
  reservation). SM3 Studio's scripts import it from that folder; it is not meant to be copied into
  Blender.
- `correctifs_blender/apply_fixes.py` — applies our fixes to your installed copy of his two add-ons;
  it quotes the few lines of his code that it replaces.
- `correctifs_blender/sm3_baked_atlas.py` — the Material Combiner's `sm3_baked_atlas.py` (version
  1.4.8) with two fixes (same pixels in the `.tex` as in the atlas PNG; islands rotated by quarter
  turns only). Details in [correctifs_blender/README.md](correctifs_blender/README.md).

These two files are the only code of his in this repository, and both live in `correctifs_blender/`
(checked on 2026-10-12 by comparing every line of the repository with his add-ons and xeSM3). One
look-alike is ours: about twenty lines of the "fast" DXT1 encoder in `tools/sm3/dxtenc.py` are
also found in the Material Combiner's sm3_dxt.py. Our file already existed on 2026-08-05; the
Combiner added sm3_dxt.py in its version 1.3.0, whose release notes describe it as "based on the
supplied working xeSM3 Spider-Man conversion scripts".

SM3 Studio was also calibrated on the `CH_SPIDERMAN` sample files shipped with the toolkit, and
`transplanter_lod.py` and `reparer_uv_ts.py` were first written to understand and repair
TSGAMING264's own converted suit. His remark that a suit mod needs **both** `ch_spiderman000` and
`ch_spiderman001` set the course of the `lod` stage.

## Other projects mentioned

- **RaimiHook** by **AkyrosXD** — <https://github.com/AkyrosXD/RaimiHook> (GPL-3.0): a debug menu
  for Spider-Man 3 PC (a `d3d9.dll` proxy). Not used and not included; its list of `Game.exe` hook
  addresses was consulted during our research, and the Matte suit was checked not to conflict with
  it (it does not modify `Game.exe` on disk).
- **Blender** (Blender Foundation), **Python**, **NumPy**, **Pillow**, **PyInstaller**, **7-Zip**:
  the tools SM3 Studio runs on. Not included.

## The game

*Spider-Man 3* (PC, 2007) was developed by Treyarch and published by Activision; Spider-Man is a
Marvel character. *Spider-Man: Web of Shadows* (2008) is mentioned for the optional mode that
recognises two exports of its models. SM3 Studio is an unofficial fan project, not affiliated with
or endorsed by any of them, and it ships none of their files (see the README, "What this repository
does not contain").

The 3D models people convert with SM3 Studio belong to their authors; none is included here.
