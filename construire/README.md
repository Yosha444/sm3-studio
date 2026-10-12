# construire/ — building SM3 Studio.exe

*"construire" is French for "to build". Like the other French names in this repository, the folder
keeps its original name so that nothing referring to it breaks.*

| File | What it is |
|---|---|
| `SM3Studio.spec` | The PyInstaller recipe of `SM3 Studio.exe` (one file, console kept for the command-line mode). |
| `verify_interface.py` | Checks that `sm3_interface.py` compiles to the same program as the bytecode shipped in the builds of 2026-09-09 to 2026-10-08. |

## Building the executable

Requirements: Windows, Python 3.14 with PyInstaller (6.22.2 used for the last build), numpy and
Pillow.

```bat
cd construire
python -m PyInstaller --noconfirm --distpath dist --workpath work SM3Studio.spec
```

The result is `construire\dist\SM3 Studio.exe` (`dist\` and `work\` are build output, not part of
the repository). Copy the .exe into the project folder, the one that holds `tools\`, `vanilla\`,
`profiles\` and `mods\`: the .exe uses its own folder as the project folder.

## What is inside the .exe, and what stays on disk

This decides whether a fix needs a rebuild.

| Inside the .exe (read from `sys._MEIPASS`) | On disk, next to the .exe (read at run time) |
|---|---|
| `sm3_studio_hq.py` (entry point), `sm3_interface.py`, `sm3_gui_hq.py`, `studio_language.py` | `tools\` (every helper script, the Blender scripts, the matte-suit patcher) |
| the converter: `sm3_convertir.py`, `ajuster.py`, `atlas.py`, `dilater_atlas.py`, `glb.py`, `poids_depuis_vanilla.py`, `poids_par_segments.py`, `redresser_bras.py`, `reparer_uv_ts.py`, `sm3_sans_blender.py`, `transplanter_lod.py`, `uv_depuis_lod.py` | `qualite.json`, `texture_qualite.json`, `sm3_studio.json` (window settings), `language.txt` |
| `correctifs_blender\blacksuit_mesh_writer.py` (imported by `transplanter_lod.py`) | `vanilla\`, `profiles\` (game data rebuilt from the player's own copy of the game) |

A change to a file of the left column has no effect until the .exe is rebuilt; a change in the
right column applies at the next start (or the next conversion).

The interface files are bundled as **source**, not as compiled modules, on purpose: the window is
compiled at start-up so that `studio_language.localize()` can translate its strings when the user
picks English.

## Start-up sequence

1. `sm3_studio_hq.py` asks for the language (small window; the answer is kept in `language.txt`).
   With command-line arguments there is no window at all and the language is French.
2. It compiles `sm3_interface.py` (the main window) and `sm3_gui_hq.py` (the HQ additions), passes
   them through `studio_language.localize()` for English, and executes them.
3. `sm3_gui_hq.integrate()` patches the `Studio` class: "General / Quality" panel, "Target
   character" tab (Spider-Man, Venom, Black Suit, matte suit), and wrappers around load, save,
   convert, install and preview.
4. Without arguments, the window opens. With arguments, the converter runs without a window,
   e.g. `"SM3 Studio.exe" --nom MyMod --src model.glb` (options of `sm3_convertir.py`).

## Where `sm3_interface.py` comes from

Until 2026-10-12 the main window existed in the distributed tool only as
`sm3_studio_original.marshal`: a marshalled Python 3.14 code object, bundled in the .exe and
executed by the entry point. Nobody could read or review it. It has been replaced by
`sm3_interface.py`, a commented source file, and removed from the repository.

How the source was recovered (measured, not assumed):

* The developers' working tree still had the last source of that window, `sm3_studio.py`, dated
  2026-09-08 09:27 (the .marshal is dated 2026-09-08 18:57). Compiled with Python 3.14 and
  compared with the .marshal, it differed in two functions only: an "auto-orient" option
  (`Remettre d'aplomb`: 9 lines in `Studio._onglet_pose`, and `--orienter` in `Studio._args`) that
  was removed in between. The line numbers stored in the bytecode show the gap: its
  `_onglet_skinning` starts exactly 9 lines earlier.
* Without those lines, the source compiles to code objects that CPython itself considers equal
  to the shipped ones (`code == code`, which also compares the line tables), for all 46 code
  objects. Only the serialised bytes differ (62,991 vs 62,999 bytes): the marshal format's
  internal reference flags depend on how the object was created; `marshal.dumps(marshal.loads(x))`
  does not give back `x` either.
* The comments and docstrings were then translated into English and explanations were added;
  the code itself was not touched. One string was rewritten as adjacent literals because two of
  its "empty" lines contain 8 spaces that an editor could silently strip (same constant).

`verify_interface.py` repeats the check on any build of 2026-09-09 to 2026-10-08 (or on a .marshal
file), for the French interface and, with an .exe, for the English one. It needs Python 3.14.

```bat
python construire\verify_interface.py "C:\path\to\an old\SM3 Studio.exe"
```

Results measured on 2026-10-12:

| Check | Result |
|---|---|
| `verify_interface.py`, build of 2026-10-08 | French: 46 code objects, 0 differences. English: 46, 0 differences |
| Same, on the builds of 2026-09-09, 09-13, 09-14, 10-05, 10-06, 10-07 | French: 0 differences. English: 0 for the builds of 10-06 and 10-07; the older ones did not yet translate 3 strings (`Dossier du jeu`, `celui qui contient Game.exe`, `Tous les fichiers`) |
| `sm3_gui_hq.py` and `studio_language.py` after translating their comments | same bytecode as before, docstrings aside (the 4 translation keys that only matched the old French docstrings were removed) |
| Window built through the old entry point + .marshal vs the new entry point + source, without showing it | identical dump of all 131 widgets (options, layout, tab names), the 30 settings, `_args()` and the quality config, in French and in English |
| Same window from a frozen test build of the new recipe | identical to the source run (project folder path aside) |
| Rebuilt .exe vs the 2026-10-08 .exe | same 486 bundled modules and 92 DLL/PYD; archive differences: `sm3_interface.py` added, `sm3_studio_original.marshal` removed, entry script `sm3_studio` renamed `sm3_studio_hq` |
| Command line `--help`, both .exe | identical output |
| Same conversion with both .exe (`--depuis poids` on identical copies of a project) | 24 of 24 build files and 10 of 10 mod files byte-identical; logs identical except timings |
| Later the same day: comments, docstrings and messages of the converter modules translated to English (AST identical apart from the Blender / toolkit path settings) | 4 conversions, code before vs after: every build and mod file byte-identical, logs with the same lines and the same numbers. The command-line help and the log are now in English, so they no longer match an older .exe word for word: rebuild the .exe |
| `sm3_gui_hq.py`, same change | 8 string constants changed: the texts it looks for in the output of `tools/costume_mat.py`, now English (`REFUSED: `, `ERROR: `, `Nothing to do`, `Write access denied`, `is running`, `original version is not available`). Matte-suit box, old window + French patcher vs new window + English patcher, on copies of Game.exe: 110 comparisons, 0 differences (26 without this change). The window itself is unchanged (same dump in French and English) |
| Final audit: .exe rebuilt from this repository + game data rebuilt by `tools/extraire_donnees_jeu.py`, against the 2026-10-08 installation (its .exe and data); full command-line conversions, Blender stage included (a rig-less model) | every build and mod file identical except the paths written into reports and `chaine.blend`, 1 or 2 bytes of tangent / binormal in the two meshes (one step of the last bit) and 1 to 3 texels (delta 1) of the normal map. Those differences are noise of the Blender stage: the 2026-10-08 installation itself, copied unchanged into another folder, flips another tangent byte, and its own repeated runs in one folder differ in the normal map by up to 8 texels over all mip levels (delta at most 2). Black Suit target: the 4 game files identical byte for byte |

## Behaviour kept exactly as it was (known quirks)

These are deliberate: the goal of the move to source was to change nothing.

* In `Studio.deviner`, one message contains `tools\apparier_textures.py` in a normal string, so
  `\a` is the BEL control character and the message shows `tools<BEL>pparier_textures.py`.
* In the English interface, about a dozen messages stay French, as in every build so far, because
  they are not in `studio_language.EN` or are compiled into fragments. Among them: the
  "blender.exe ou tools\... introuvable." warnings, "Le mod n a pas encore ete construit :",
  "blender.exe est introuvable..." (Convert without Blender), the install log lines
  (`[installer] elevation demandee (UAC)...`), the "a jeter dans l onglet General ?" hint, the
  file-dialog filter names, the Venom file dialog and preview titles, and the "Réglages HQ" title
  of the error shown when closing with an invalid quality setting.
* When run from source (`python sm3_studio_hq.py`), the default project folder is the source
  folder itself when `tools\` sits next to it (the repository layout), else its parent (the
  layout of the original development tree). The .exe uses its own folder. Either way, the "Dossier du projet" field of the Paths tab (saved in `sm3_studio.json`)
  overrides it.
* Tracebacks in the log now name `sm3_interface.py` with real line numbers and source lines;
  before, they showed `sm3_studio.py` without source. Nothing else depends on the file name.
