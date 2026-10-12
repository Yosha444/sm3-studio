# SM3 Studio

**Turn a 3D character model into a playable suit for *Spider-Man 3* on PC (2007).**

SM3 Studio takes a model (GLB, glTF, FBX, OBJ and the other formats Blender opens, or a ZIP/RAR/7z
archive that contains one) and produces a ready-to-load mod for **xeSM3**, the Spider-Man 3 mod
loader. It does everything the game needs and that is hard to get right by hand: putting the model
in the game's pose and on the game's skeleton, giving it the game's own skin weights, baking all its
textures into one atlas, writing the game's mesh and texture formats, and checking the delivered
bytes against the original suit before calling the mod finished.

It is an unofficial fan tool. It contains **no file of the game**: the first time you use it, it
rebuilds what it needs from **your own copy** of Spider-Man 3.

> Everything in this README marked *measured* was measured on files or in the game; anything we
> could not measure is said to be *not measured* or *assumed*.

---

## Contents

1. [What it does](#what-it-does)
2. [Status at a glance](#status-at-a-glance)
3. [What you need](#what-you-need)
4. [Installation, step by step](#installation-step-by-step)
5. [First launch: rebuilding the game data from your copy](#first-launch-rebuilding-the-game-data-from-your-copy)
6. [Your first conversion, step by step](#your-first-conversion-step-by-step)
7. [Where the files go](#where-the-files-go)
8. [Going back: undoing what SM3 Studio did](#going-back-undoing-what-sm3-studio-did)
9. [Other targets: Black Suit and Venom](#other-targets-black-suit-and-venom)
10. [The Matte suit box](#the-matte-suit-box)
11. [Known limitations](#known-limitations)
12. [FAQ: what went wrong in game, and what the tool does about it](#faq-what-went-wrong-in-game-and-what-the-tool-does-about-it)
13. [What this repository does not contain, and why](#what-this-repository-does-not-contain-and-why)
14. [For developers](#for-developers)
15. [Licence and credits](#licence-and-credits)

---

## What it does

- **Red suit (default target).** Replaces Spider-Man's suit, i.e. the game's two suit models
  (`ch_spiderman000.mesh`, the main one, and `ch_spiderman001.mesh`, a second model of the same suit
  that the game uses in other situations), the suit's colour atlas and its normal map.
- **Black Suit target.** Replaces the black (symbiote) suit's two models and atlas.
- **Venom target.** Replaces Venom, keeping Venom's own shader and material (experimental, see the
  status table).
- **Automatic preparation of the model**, each step measured against the game's own suit:
  standing it up and facing it forward, scaling and centring it on the game's body, putting the
  arms into the game's bind pose (an "A" pose, arms 36.6° down), placing every joint on the game's
  skeleton (from the model's own rig if it has one, from its shape otherwise), transferring the
  game's **own** skin weights, giving the fingers their 30 bones so fists clench, splitting parts
  the game cannot index.
- **Textures:** every material of the model is baked into one atlas (2048, 4096 or 8192 pixels),
  a normal map is baked too (or deduced from the colours when the model has none), and both are
  encoded with a high-quality DXT encoder (or uncompressed ARGB8).
- **A final check on the delivered bytes:** internal names, materials, UV range, vertex colour,
  face orientation, bone palette, skin weights compared with the game's at the same place, and
  more (19 checks). A mod that fails is not assembled.
- **Install and launch** the converted suit in one click (optional), and the **Matte suit** patch
  that removes the game's oily shine from every Spider-Man suit.

## Status at a glance

| Feature | Status |
|---|---|
| Red suit conversion | **Works.** Suits converted with SM3 Studio have been played; the texture clean-up and the clenched fists of the 2026-10-06 version were confirmed in game. The proportion fix (2026-10-07) and the detail fixes (2026-10-08) were measured on the files; our notes do not record an in-game confirmation yet. |
| Black Suit | **Works** with the model it was built on (CJ, confirmed in game 2026-09-08; noise fix confirmed 2026-10-06). Other models should be checked in motion in game. Its install button has a known bug (see [Known limitations](#known-limitations)): install it by hand. |
| Venom (native profile) | **Experimental.** The mod is built and passes its checks; the in-game look still has to be confirmed (the tool says so in its log). |
| Matte suit (Game.exe patch) | **Works.** The recommended "Satin" preset was confirmed in game (2026-10-06). |
| Game-data extraction from your copy | **Works.** Measured: 261 of 261 extracted files byte-identical to those SM3 Studio was developed with. |
| Web of Shadows mode | **Off** unless you have the files of an older SM3 Studio (they come from another game, see [Known limitations](#known-limitations)). |
| Venom "direct" renderer | **Disabled**: it crashed the game. |
| `support_venom_direct/` | Research code, never seen working in game, not used by SM3 Studio. |

---

## What you need

| | What | Why |
|---|---|---|
| 1 | **Windows** (tested on Windows 11) | the tool uses PowerShell, the registry and Windows paths |
| 2 | **Spider-Man 3, PC version (2007)**, with its original `packs\` | SM3 Studio measures every model against the game's own suit and rebuilds its reference files from your copy. The Matte suit additionally needs the original `Game.exe` (10,846,998 bytes). |
| 3 | **xeSM3** by TSGAMING264 — <https://github.com/TSGAMING264/xeSM3> | the mod loader: the game loads SM3 Studio's mods through it. SM3 Studio was last tested with xeSM3 0.1.4. |
| 4 | **Blender 5.2** | used, in the background, to import the model and bake the texture atlas (the only slow step), and for the preview |
| 5 | **SM3 Blender Toolkit** and **SM3 Material Combiner**, Blender add-ons by TSGAMING264 — <https://github.com/TSGAMING264/SM3-Blender-Tools> | SM3 Studio runs their import, bake and export operators and reads the toolkit's format code. Tested with toolkit 1.3.7 and combiner 1.4.8 **plus our small fixes** ([`correctifs_blender/README.md`](correctifs_blender/README.md)). |
| 6 | **Python 3** with **numpy** and **Pillow** (python.org installer, which includes tkinter) | to run SM3 Studio from source, to build `SM3 Studio.exe`, and for the last step of the Black Suit target. Tested with Python 3.14.7, numpy 2.5.2, Pillow 12.3.0. **PyInstaller** (6.22.2 tested) only to build the .exe. |
| 7 | *optional:* **7-Zip** | only to accept `.rar` / `.7z` archives as a source (ZIP works without it) |

SM3 Studio does not install, download or bundle any of these.

---

## Installation, step by step

**1. The game and xeSM3.** Install Spider-Man 3 and xeSM3 (follow xeSM3's own instructions). Check
that xeSM3 works before going further: its example mod should show in game.

**2. Blender 5.2 and the two add-ons.** Install Blender 5.2. In Blender, *Edit > Preferences >
Add-ons*, install the *SM3 Blender Toolkit* and the *SM3 Material Combiner* from TSGAMING264's
release. Keep the default install location: SM3 Studio expects the toolkit in

```
%APPDATA%\Blender Foundation\Blender\5.2\extensions\user_default\sm3_blender_toolkit
```

(It reads the toolkit's format modules from there even for the steps that do not start Blender.
`SM3_TOOLKIT_DIR` can point elsewhere, but some scripts in `tools\` only look in that default
folder; see [Known limitations](#known-limitations).)

**3. Our fixes to the add-ons.** Close Blender, then run, from the SM3 Studio folder:

```bat
python correctifs_blender\apply_fixes.py
```

It patches the two add-ons in place (only if they are exactly toolkit 1.3.7 and combiner 1.4.8,
keeping each original as `<file>.before_sm3studio`; `--check` shows what it would do, `--undo`
puts the originals back). What each fix does and why: [`correctifs_blender/README.md`](correctifs_blender/README.md).
Without them the conversion still runs, but it is not what we tested.

**4. Python.** Install Python 3 (64-bit, python.org, tick "Add Python to PATH"), then in a command
prompt:

```bat
python -m pip install numpy pillow
python -m pip install pyinstaller        (only to build SM3 Studio.exe)
```

**5. Get SM3 Studio.** The easiest way: on the [Releases](https://github.com/Yosha444/sm3-studio/releases) page, download
`SM3-Studio-<version>-windows.zip`. It is this repository with `SM3 Studio.exe` already built
from it; extract it into a folder you can write to, for example `C:\SM3Studio`, and you can skip
the build below. Otherwise clone this repository, or download it as a ZIP, into such a folder.
Avoid `C:\Program Files`: SM3 Studio writes its build folders, mods and settings next to itself.
Python (step 4) is still needed for step 3 and for the last step of the Black Suit target.

**6. Choose how to start it.**

- **Recommended: `SM3 Studio.exe`.** It is already in the release ZIP. To build it yourself from a
  clone (about half a minute):

  ```bat
  cd C:\SM3Studio\construire
  python -m PyInstaller --noconfirm --distpath dist --workpath work SM3Studio.spec
  copy "dist\SM3 Studio.exe" ..
  ```

  Then double-click `C:\SM3Studio\SM3 Studio.exe` (or `Ouvrir SM3 HQ.cmd`, French for "open SM3
  HQ", which does the same). The .exe uses **its own folder** as the project folder, so it must sit
  next to `tools\`. Details: [`construire/README.md`](construire/README.md) ("construire" = build).
- **From source:** `python C:\SM3Studio\sm3_studio_hq.py`. One thing to know: when run from source,
  the default project folder is the source folder itself (because `tools\` sits next to it), so
  nothing needs setting. The **Paths** tab's **Dossier du projet** ("project folder"; this label
  stays French in the English window) can point elsewhere if you keep your projects apart.

**7. The Paths tab.** In the window, check the three paths once (they are saved in
`sm3_studio.json`):

| Field | Set it to |
|---|---|
| blender.exe | `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` (the default) |
| Dossier du projet (project folder; not translated in the English window) | the folder that holds `tools\` (the .exe's folder) |
| Game folder | the folder that contains `Game.exe` and `packs\`, e.g. `C:\Games\Spider-man 3` |

The default Game folder is `C:\Program Files (x86)\Activision\Spider-Man 3`. If it is wrong, SM3
Studio also looks at the install path Windows keeps in the registry and at the usual folders, but
setting it yourself is the reliable way.

---

## First launch: rebuilding the game data from your copy

At the very first start, a small window asks for the language (English or French); the answer is
kept in `language.txt`.

SM3 Studio measures every model against Spider-Man 3's own files: the red suit's two models and
skeletons, the black suit's resources, Venom. Those files belong to Activision and Treyarch, so the
repository does not contain them. **The first time you convert something**, the log says:

```
SM3 Studio needs N file(s) from your copy of Spider-Man 3 (first use: they are not distributed
with the tool). Extracting them now...
```

(N is about 260 the first time.)

and SM3 Studio reads them from three packs of your game (`CH_SPIDERMAN`, `CH_BLACKSUIT`,
`STORY_MOVIE_4_PHASE3`). It takes a few seconds and it **never writes into the game folder**. The
files land in `vanilla\` and `profiles\` of the project folder.

Every file is checked against [`tools/game_data_fingerprints.json`](tools/game_data_fingerprints.json):
the size and SHA-256 of the files SM3 Studio was developed and tested with (a fingerprint contains
no game data). If one differs, it is still written and the tool runs, but you get a warning: your
pack is probably modded (an old mod copied into the pack itself). Restore the original pack for
exact results.

You can also run the extraction yourself, or check an installation:

```bat
python tools\extraire_donnees_jeu.py                                (finds the game by itself)
python tools\extraire_donnees_jeu.py --game "C:\Games\Spider-man 3"
python tools\extraire_donnees_jeu.py --check                        (only compares what is there)
```

Options: `--force` (rewrite everything), `--no-blender`, `--blender <blender.exe>`,
`--root <SM3 Studio folder>`. Exit code 0 = everything present and identical, 2 = written but some
files differ from the reference, 1 = game not found or unreadable. ("extraire les données du jeu" =
"extract the game data".)

<details>
<summary>Two special cases, and what is not rebuilt</summary>

- `ch_spiderman001.mesh` is copied from the `samples` folder of the SM3 Blender Toolkit, because
  SM3 Studio was calibrated on that copy (*measured:* its vertex buffers are not the pack's; SM3
  Studio only reads its header). Without the toolkit it is taken from the pack instead, and the
  conversions come out the same (*measured*).
- `Venom_editable.blend` (the "Load Venom project" button) is made by Blender. Without Blender only
  that button does nothing.
- **Not rebuilt:** `profiles\rvb` (models from *Spider-Man: Web of Shadows*, another game). Without
  them, the Web of Shadows mode is off and such a model is converted like any other.

</details>

**If the game is not found**, the conversion stops with the list of folders it tried. Set **Game
folder** in the Paths tab and convert again.

---

## Your first conversion, step by step

This is the normal path for the red suit. Everything not mentioned can stay at its default.

**1. Target character tab** (the first tab): leave **Spider-Man**.

**2. The Model box** (top of the window):
- **Source model**: your `.glb`, `.fbx`, `.obj`... or an archive that contains it (the biggest
  model file inside is used).
- **Texture folder**: leave empty. SM3 Studio looks for a `textures`, `tex`, `maps`... folder next
  to the model or one level up, then next to the model, then below it.
- **Mod name**: the folder name of your mod, for example `MySuit` (letters and digits are safest).

**3. Only if your model references no texture** (many ripped models): **Textures** tab, click
**Analyze model**, then **Guess texture assignments**. SM3 Studio measures which image goes on which
material (a texture read through the right UV unwrap varies smoothly over the 3D surface; a wrong
one jumps). Check the proposals; you can change any of them by hand.

**4. General / Quality tab** (defaults are fine):

| Setting | Default | What it does |
|---|---|---|
| Atlas resolution | 4096 | size of the baked atlas: 2048, 4096 or 8192 (8192 is accepted by the engine but has not been checked in game) |
| Compression | DXT5 | DXT1 (half the size, no alpha), DXT5, or ARGB8 (uncompressed, 4 times DXT5) |
| Geometry | Retriangulate quads and ngons | or keep the mesh as it is, or subdivide ×4 without smoothing |
| Dilation (pixels) | 12 | colour pushed into the empty space around each UV island, so seams do not show a line |
| Vertex color — gray | **0** | keep 0 (black): it is what the game's own suit carries on the part our suit replaces; other values change the shading (see the [FAQ](#faq-what-went-wrong-in-game-and-what-the-tool-does-about-it)) |
| Materials to exclude | empty | comma-separated material names to drop: capes you do not want, decals, placeholder parts |

**5. Pose and Skinning tabs**: leave them alone. They hold manual corrections (scale, rotation,
offset, weight method) for the rare model the automatic alignment misses.

**6. Click Convert.** The log shows each stage. Only the first one, `chaine` (the Blender bake), is
slow. A finished conversion ends with:

```
[convertir] CONTROLE (final check): everything conforms
[convertir] mod assembled: ...\mods\MySuit - 10 files, ...
```

Lines starting with `OK` (green) are passed checks; lines starting with `!!` (red) are problems.
If the final check fails, the mod is **not** assembled and the failed line says what is wrong.

**7. Preview tab** (optional): **Render preview** renders the delivered model with Blender (front,
back, three-quarter, and the atlas). It decodes the file that goes into the game, not a Blender
object.

**8. Put it in the game.** Two ways:

- **Install and launch game** (button): asks for administrator rights (UAC), finds the game,
  closes it if it is running, copies `mods\MySuit` to `<game>\Mods\MySuit`, **enables it and
  disables every other mod** in `Mods\mods.config.ini` (two suit mods would fight over the same
  files), then starts the game. It never touches another mod's `winmm.dll` (see
  [Going back](#going-back-undoing-what-sm3-studio-did)).
- **By hand:** copy `mods\MySuit` into `<game>\Mods\`, open `<game>\Mods\mods.config.ini` and add
  `MySuit=100` under `[EnabledMods]` (xeSM3: 100 = enabled, 0 = disabled). Set any other suit mod
  to 0.

<details>
<summary>Re-running part of a conversion, and the other buttons</summary>

Every stage keeps its result in `build\<mod name>\`, so a later stage can be re-run alone with
**Resume from stage**. The stages, in order:

| Stage | French | What it does |
|---|---|---|
| `chaine` | "chain" | Blender: import, alignment, weights, atlas and normal-map bake, export (slow) |
| `ajuster` | "adjust" | manual scale/rotation/offset from the Pose tab (skipped if none is set) |
| `bras` | "arms" | arms put into the game's A-pose (skipped for a rigged model already fitted on the skeleton) |
| `poids` | "weights" | the game's own skin weights, then limbs and fingers posed for models without a rig |
| `lod` | — | writes the second model (`001`) from the finished first one |
| `atlas` | — | dilates the atlas, encodes the `.tex` files |
| `verifier` | "check" | the final check on the delivered bytes |
| `assembler` | "assemble" | copies the files into `mods\<mod name>\`, in xeSM3's layout |

Changing a quality setting (resolution, geometry, colour, format) makes the next conversion start
again from `chaine` automatically. **Validate only** re-runs `verifier` and `assembler`. **Open mod
folder** opens `mods\<mod name>\`.

</details>

<details>
<summary>Converting from the command line</summary>

`SM3 Studio.exe` with arguments converts without a window (its log is in English):

```bat
"SM3 Studio.exe" --nom MySuit --src "C:\models\suit.glb"
"SM3 Studio.exe" --nom MySuit --depuis atlas                 (resume from a stage)
"SM3 Studio.exe" --help                                      (every option)
```

`--nom` = name, `--depuis` = from (stage), `--target spiderman|blacksuit|venom`,
`--format DXT1|DXT5|ARGB8`, `--slot spider|sideweb|topweb` (body material: the game's, matte, or
glossy; command line only), and the manual corrections of the Pose and Skinning tabs (`--echelle`
scale, `--rot-x/y/z`, `--decalage` offset, `--poser-au-sol` put on the ground, `--methode-poids`,
`--sans-retouche` skip the arm and weight stages). Command-line conversions use the folder of the
.exe as the project folder. Blender comes from `SM3_BLENDER`, else the `blender` key of
`sm3_studio.json`, else the default Blender 5.2 path.

</details>

---

## Where the files go

| Where | What | Notes |
|---|---|---|
| `build\<mod name>\` | every intermediate file of a conversion: stage outputs (`etape_*.mesh`, "etape" = stage), baked atlas and normal map PNGs, the Blender scene `chaine.blend`, reports, previews | safe to delete; needed only to resume a conversion |
| `mods\<mod name>\` | **the deliverable mod**, in xeSM3's layout (below) | this is what goes into the game |
| `<game>\Mods\<mod name>\` | the installed copy | written by the install buttons, or by you |
| `<game>\Mods\mods.config.ini` | xeSM3's list of enabled mods | the Install button keeps the previous one as `mods.config.ini.bak` |
| `<game>\SM3_Studio_Backups\` | backups made by the Black Suit and Venom installers | one dated folder per installation |
| `vanilla\`, `profiles\` | the game files rebuilt from your copy | never commit them |
| `sm3_studio.json`, `language.txt` | your settings (paths, last model, every field) and the language | personal |
| `qualite.json`, `texture_qualite.json` | quality settings ("qualité" = quality); the window writes the first, the second is edited by hand | see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#11-settings) |
| `install.log`, `boucle.log` | what the Install and launch button did ("boucle" = loop) | shown in the window's log |

A red-suit mod is 10 files (13 with the matte or glossy body slot), under three of the game's packs
because Spider-Man appears in all three and xeSM3 matches files by pack *and* archive:

```
mods\MySuit\
  CH_SPIDERMAN\_O0069.0xCFB154CD.T36.apkf\
      0xAC92103D.ch_spiderman000.mesh      main suit model
      0xAC92103E.ch_spiderman001.mesh      second model of the suit
      0x8E661B33.ch_spiderman_spider.tex   colour atlas
      0x61DCA273.normswizzle.tex           normal map
  MARYJANE_SCARERIDE\_O0082.0x4F920A48.T36.apkf\    the same 4 files
  STORY_MOVIE_3\_O0121.0x03294B12.T36.apkf\         the 2 textures
```

File names are `0x<hash>.<name>.<type>`, folder names `_O<archive index>.0x<archive hash>.T<type>.apkf`:
the names xeSM3 uses. [docs/FORMATS.md](docs/FORMATS.md) explains them.

---

## Going back: undoing what SM3 Studio did

SM3 Studio never writes into the game's `packs\` for the red suit or the black suit: xeSM3 loads the
mod's loose files instead of the pack's. Everything below is reversible.

| To undo | Do this |
|---|---|
| a suit mod | set it to `0` in `<game>\Mods\mods.config.ini` (or delete `<game>\Mods\<mod name>\`). The Install and launch button kept the previous file as `mods.config.ini.bak` (the state before its **last** run only): rename it back to restore every mod's previous state. |
| what the Install and launch button renamed | only leftovers of an earlier experiment of this project, which you will not have: a `winmm.dll` recognised by its SHA-256 (renamed `winmm.dll.off`, never deleted) and a `<game>\sm3\mods\` folder (renamed `sm3.off`). Any other `winmm.dll` is left untouched. |
| a Black Suit install | its backup is in `<game>\SM3_Studio_Backups\BlackSuit_tool_<date>\` (`mods.config.ini` and every overwritten file): copy them back |
| a Venom install | click **Restore original Venom** (Target character tab), or copy back the backup from `<game>\SM3_Studio_Backups\Venom_<date>\` |
| the Matte suit | click **Remove matte suit**, or `python tools\costume_mat.py remove`. A full copy of the original exe was also kept: `Game.exe.sauvegarde_patchs_sm3` ("sauvegarde" = backup) |
| SM3 Studio's own state | delete `build\<mod name>\`; delete `sm3_studio.json` and `language.txt` to get the defaults back; `python tools\extraire_donnees_jeu.py --force` rebuilds the game data |

---

## Other targets: Black Suit and Venom

**Black Suit.** Target character tab > **Black Suit**. Choosing it sets black vertex colour and 12
pixels of dilation (the settings validated in game). The conversion produces the black suit's two
models and atlas (`CH_BLACKSUIT` pack). The black suit has only **one** usable section (xeSM3 gives
it its material by section *position*), so a model above 65,535 vertices is refused rather than
delivered torn, and 26 of the 30 finger bones fit (the tips of the ring and little fingers follow
their middle phalanx). The last step runs in a separate Python, which must have numpy and Pillow:
the one named by the `SM3_PYTHON` environment variable if it is set, else the Python running SM3
Studio (from source), else `python` or `py` found on PATH (from the .exe). Install the result **by
hand** (see [Known limitations](#known-limitations)).

**Venom.** Target character tab > **Venom**. Venom is drawn by his own shader with a 256-colour
palette: SM3 Studio keeps that shader and Venom's material, reduces your model's colours to a
256-colour palette (ARGB8 index texture, 2048 × 1024) and installs with the original pack. With
this target, the **Install and launch game** button installs without launching: it checks that the
pack is the original one, backs up, installs, reads everything back, and rolls back on any error.
**Load Venom project** opens the game's Venom prepared for editing in Blender. This profile is
**experimental**: the in-game look is still to be confirmed.

---

## The Matte suit box

The "oily" shine of Spider-Man's suit is not in any texture of a mod: the game computes it in
`Game.exe` itself, in the three pixel shaders shared by the red suit, the black suit and every suit
mod. The **Matte suit** box (Target character tab) patches those three shaders in place, without
changing the size of `Game.exe`. After the game's own computation one added instruction imposes:

```
final shine      = saturate(game shine      × Ks + As)
final reflection = saturate(game reflection × Ke + Ae)
```

| Preset (French key) | Ks | As | Ke | Ae | Look |
|---|---|---|---|---|---|
| **Satin** (`satine`, recommended) | 0 | 0.06 | 0 | 0 | slight constant sheen, no reflection — confirmed in game |
| Matte (`mat`) | 0 | 0 | 0 | 0 | no shine, no reflection |
| Softened (`attenue`) | 0.35 | 0 | 0.25 | 0 | the game's nuances, much gentler |
| Identity (`identite`, test) | 1 | 0 | 1 | 0 | patch in place, no visible change |

How to use it: close the game, set **Game folder** in the Paths tab, tick the box, pick a preset,
**Apply to game**, restart the game. If the game is installed under `C:\Program Files (x86)`,
Windows refuses the write: start SM3 Studio as administrator (right-click > Run as administrator). While the box is ticked, the preset is re-applied before each
suit installation. **Unticking removes nothing**: only **Remove matte suit** puts the original
shaders back.

Safety (all *measured* on copies of `Game.exe`): the script refuses anything but the original
10,846,998-byte `Game.exe`, checks the fingerprint of each original shader before writing and of each
patched shader after, refuses to run while the game runs, and writes nothing else (other patches
elsewhere in `Game.exe`, such as camera patches, are kept). Before the first write it saves the 3 original
shaders to `Game.exe.costume_mat_origine.bin` (**keep it**: "remove" needs it) and a full copy to
`Game.exe.sauvegarde_patchs_sm3`. No game bytes are shipped: `tools/costume_mat_shaders.json` is a
*recipe* ("copy these byte ranges of your shader, insert these 36 bytes of ours, put the 4 values
here") applied to your own `Game.exe`. A `Game.exe` changed by another tool in the same shaders is
refused, with nothing written.

Command line: `python tools\costume_mat.py status | install <preset or Ks As Ke Ae> | remove
[--game "folder"] [--original "intact Game.exe"]`. Details: [`tools/costume_mat_README.txt`](tools/costume_mat_README.txt).

---

## Known limitations

**Disabled or incomplete, and why**

- **Black Suit installation from the window: broken on freshly converted mods** (*measured*, in the
  current code and in the version before it). With the Black Suit target, the Install and launch game
  button calls `tools/blacksuit_deploy.py`. It expects a `package.json` listing 3 files inside the mod's
  archive folder; today's packaging writes it elsewhere and ships 4 files (with the normal map), so
  the button stops with "file not found". Install the black suit by hand: copy `mods\<name>` into
  `<game>\Mods\`, set `<name>=100` in `mods.config.ini`, and set to 0 the other mods that replace the
  black suit.
- **Venom "direct" renderer: disabled.** In September 2026 it rewrote 82 bytes of Venom's pack so that
  Venom would use the Spider-Man shader; it crashed the game (installed at 20:34, original pack put
  back at 20:38). SM3 Studio refuses those mods. See
  [`support_venom_atlas/README.md`](support_venom_atlas/README.md).
- **`support_venom_direct/`**: a draw-time adapter (a `winmm.dll` proxy) meant to give Venom full
  colours. Research code, not wired to any button, never seen working in game. See its README.
- **Web of Shadows mode: off.** SM3 Studio recognises two exports of *Spider-Man: Web of Shadows*
  models and converts them with their original weights, but the profile files are that game's data
  and are not rebuilt. Without them such a model is converted like any other. Copying
  `profiles\rvb` from an older SM3 Studio installation turns the mode back on.
- **Venom export is not exactly reproducible** (*measured*): the add-on's export varies by 1 to 4
  bytes of tangent data from one run to the next, on the reference installation too.

**Things to know**

- **Tested on one machine and one copy of the game** (retail PC release). Other releases or language
  versions are *assumed* to have the same packs; if not, the fingerprints will say so.
- **The add-ons must be in Blender 5.2's default folder.** `SM3_TOOLKIT_DIR` is honoured by two
  modules only; `tools\winding_fix.py`, `mains_poings.py`, `render_mesh.py` and `uv_1000.py` still
  look only in `%APPDATA%\Blender Foundation\Blender\5.2\extensions\user_default\`.
- **Without our add-on fixes** the results were not measured: run `correctifs_blender\apply_fixes.py`
  (see [`correctifs_blender/README.md`](correctifs_blender/README.md)). It only patches the exact
  add-on versions we tested; with other versions, apply the changes by hand from that page.
- **The game data is extracted at the first conversion, not at start-up.** Until then, **Load Venom
  project** answers "Venom project not found": convert anything once, or run
  `python tools\extraire_donnees_jeu.py`, first.
- **Language:** the window follows the language chosen at start-up, but about a dozen labels and
  messages stay French in the English window, as in every build so far (for example the Paths
  tab's "Dossier du projet" field and two of its help texts). The converter's log and the logs of
  the Install and launch button (`tools\boucle_test.ps1`, `install_admin.ps1`) are English.
  One message shows a stray control character (`tools<BEL>pparier_textures.py`); it is harmless.
- **Very dense models:** each section is limited to 65,535 vertices; the red suit is split
  automatically into several sections, the black suit and Venom are refused above that.
- **Hands of models without a rig** remain the weakest point: measured on the simulated fist, the
  99th percentile of hand-edge stretch is 1.55 for the game's own suit, 1.6 to 3.0 for rigged
  models, but 2.8 to 6.1 for some rig-less ones.
- **The `--slot topweb` glossy body** (command line) was never judged in game; `sideweb` (matte) was
  checked on one model.
- **Experimental Blender-free converter** (`sm3_sans_blender.py`): not used by the normal
  conversion; its `--canvas` option fails on a glTF with more than one primitive.
- **Nothing here was tested in game after 2026-10-12's publication work**: the code changes of that
  day (English messages, configuration paths, recipes instead of game bytes) were proven equivalent
  on copies — same files out, byte for byte — not replayed in game.

---

## FAQ: what went wrong in game, and what the tool does about it

Every row is something we saw, then measured. "Vanilla" means the game's own, unmodified suit.

| What you see in game | Cause (measured) | What SM3 Studio does |
|---|---|---|
| The suit looks washed out, "as if light went through it" | the add-on wrote a **white** vertex colour; the vanilla suit has black (`0,0,0,255`) on every vertex of 8 of its 10 sections, including the one our suit replaces. Our reading of the suit's vertex shader: a non-zero colour switches on a branch that uses a normal made from the colour instead of the stored one | writes the colour of `qualite.json` (black by default) on every vertex of both models, and checks it |
| The texture is slightly too big and wraps at the edges | UVs encoded ×1024, while the suit's vertex shader multiplies them by 0.001: everything 2.4 % too large | UVs encoded ×1000; the final check requires every UV in 0..1000 |
| Wavy lines across the texture | the atlas was painted with floating-point UVs, but the game samples the rounded ones: mean offset 1.56 texels at 4096 | snaps the UVs to the game's 1/1000 grid, then re-bakes the atlas on it |
| The suit is inside-out, dark and mottled, or black | a mirrored model: inverted triangle winding (signed volume must be negative, vanilla −0.116) and inward normals (the engine lights with the stored normals) | measures and fixes both on every delivered model |
| The mod does not work, or the suit's second model is wrong | the game needs **both** models; a copy of the first one has the wrong internal name and materials, and the second model lives in another frame: `(x, y, z)₀₀₁ = (z, y + 1.199, −x)₀₀₀` | writes the real second model from the finished first one, and checks its frame to 0.01 |
| Hands stay open, fingers rigid, no fist | a section holds at most 48 bones (xeSM3's cap, and the most the game's own suit uses in one section); body + 30 finger bones need about 55. Nearest-vertex weights also gave 29 to 38 % of a finger's vertices to the **neighbouring** finger | re-weights each finger along its own bone chain; red suit: the hand goes into its own section, **30 of 30** finger bones (*confirmed in game:* "the fists are clenched"); black suit: 26 of 30 |
| Arms or forearms do not follow their bones | the 48-bone palette used to be capped at 32 in our code, and the weights of discarded twist bones landed on the wrong bone (`foretwist` is a child of the upper arm in this skeleton: the elbow stopped bending) | 48 everywhere; a discarded twist bone gives its vertices to the main bone of its segment |
| "Broken back", the body bends at the wrong places, head pushed forward | the game turns each part around **its** skeleton's joints; scaling and centring the model left its elbows, knees and neck elsewhere (TASM2: elbow 7 cm off, knees 7 cm low), and centring on the median of all vertices put bodies **10 to 19 cm behind** the skeleton | places every joint on the game's skeleton (from the rig, or from the shape of each limb), centres depth on the trunk, keeps the feet flat |
| Hands like blades, stretched arms | the model was in T-pose; the game's bind pose is an A-pose (arms 36.6° down); with a T-pose 23 % of the hands' weight went to the upper arm | puts the arms into the A-pose before transferring weights (and checks the arm span: below 85 % of vanilla, no transfer can work) |
| The model is torn | a section above 65,535 vertices was written with 32-bit indices; the game keeps only the low 16 bits of each index, silently | splits the red suit into sections of at most 65,535 vertices (same material, seams copied byte for byte); refuses for the black suit and Venom |
| Dirty 4×4 blocks and grey streaks along the web lines | **our own** old DXT encoder (endpoints taken from the darkest and brightest texels, truncated colours) | new encoder: several candidate endpoints refined by least squares, the best *decoded* block kept, never worse than the old one: +4.0 dB at full size, web lines 26.1 → 31.6 dB |
| Grain, purple/green stains on the black suit | the scale pattern on an almost-black base (50 % relative contrast), and DXT's 5/6-bit colours cannot render near-blacks | black suit atlas in ARGB8 2048 (same file size as DXT5 4096) with the fabric base smoothed and the web kept (*confirmed in game*) |
| Web lines cut, colours smeared over neighbouring parts | atlas dilation read the islands with V upside down and painted over real texels (3 % to 52 % of them depending on the model) | the orientation is detected automatically and logged; tested on 36 builds, no island texel touched |
| No relief at all on the suit | the game's normal map for the suit is a **flat 32×32 placeholder** (every texel identical) | bakes a real normal map (from the model's own, or deduced from the colours with a gain calibrated on the median slope of real Spider-Man normal maps, those of *Web of Shadows*: 1.3° to 5.7°) |
| Green patches, lighting that breaks at every texture seam | in Blender, setting the colour space of a *generated* image **erases it to black**; the deduced normal map arrived black: median slope 81° instead of 3°, 6.7 % impossible texels | sets the colour space before writing pixels; checks slope and impossible texels |
| Strange shading with a DXT1 normal map | the suit's shader reads X from the **alpha** channel: in DXT1 alpha is 255, the normal becomes the tangent (88° off) | the normal map is always DXT5, whatever you choose for the atlas |
| The suit looks oily | the shine is computed by `Game.exe` (material and its animated parameters), no texture changes it | the Matte suit patch |
| Skin turns orange | saturating colours at bake time adds to the engine's own colour grading | no saturation at bake by default |
| The character is plain white | the model references no texture; the bake had no image | Analyze model + Guess texture assignments |
| Small parts (buckles, pouches) tear apart | a detached part touches the body by no edge, each half took a different bone | small detached parts follow one group of bones; capes and cloth still deform |
| The model is a cone or a blob | positions are 16-bit integers ÷ 512 whatever the model's size: a tiny model collapses (one of ours kept 5 % of its points distinct, vanilla 89.6 %) | measured and reported before skinning (also "lying down" and "arms out of pose") |
| The model faces backwards | toes pointing back | turned by 180° automatically |
| The game crashes now and then, `Game.exe` itself at offset 0x3C90F4 / 0x3C9105 | *measured on our machine (21 crashes in the Windows event log):* the faulting module is `Game.exe`, not xeSM3 nor a proxy DLL, and the code is the parser of the **save data** (a loop that checks a pointer for null but never against the end of the buffer); the first crashes predate the suit mods they were blamed on | not caused by SM3 Studio; if it happens, keep a copy of your save files (`Documents\Activision\Spider-Man 3\`) before anything else |
| Two suits mixed, or the "wrong" mod shows | two enabled mods replace the same files | the install buttons disable the conflicting mods (the red suit's button disables every other mod) |

---

## What this repository does not contain, and why

| Not here | Why | How the tool gets it |
|---|---|---|
| Any file of Spider-Man 3: packs, meshes, skeletons, textures, materials (`vanilla\`, most of `profiles\`) | they belong to Activision / Treyarch / Marvel | rebuilt from **your** game by `tools\extraire_donnees_jeu.py`, checked against fingerprints |
| Any byte of `Game.exe` (original or patched shaders) | same | the Matte suit and `support_venom_direct` ship **recipes** (byte ranges + our own instructions) applied to your own `Game.exe` after a fingerprint check |
| The modified Venom pack of the suspended "direct" renderer | game data, and it crashed the game | not rebuilt |
| *Spider-Man: Web of Shadows* models (`profiles\rvb`) | another game's data | only our list of recognised fingerprints is shipped |
| TSGAMING264's add-ons and xeSM3 | they are his work; install them from his pages | — (two files derived from his GPL code are here, see [CREDITS.md](CREDITS.md)) |
| Windows' `winmm.dll` | Microsoft's | `support_venom_direct\install.py` copies yours |
| 3D models and their textures | their authors' work | you bring your own |
| `SM3 Studio.exe` | built from this code | [`construire/README.md`](construire/README.md) |

What **is** here: our code, our notes, and our own measurements (numbers and SHA-256
fingerprints, which cannot be turned back into the files). [`.gitignore`](.gitignore) blocks every
game file type and the generated folders; please keep it that way in pull requests.

---

## For developers

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): the conversion stage by stage, every file and its
  role, the other targets, settings, environment variables, log conventions, self-tests.
- [docs/FORMATS.md](docs/FORMATS.md): what we measured about the game's formats (packs, meshes,
  skeletons, textures, materials, shaders, xeSM3's layout).
- [construire/README.md](construire/README.md): building the .exe, what is inside it and what is
  read from disk (this decides whether a fix needs a rebuild), and how the window's source was
  recovered from bytecode and checked.
- [profiles/README.md](profiles/README.md), [correctifs_blender/README.md](correctifs_blender/README.md),
  [support_venom_atlas/README.md](support_venom_atlas/README.md),
  [support_venom_direct/README.md](support_venom_direct/README.md),
  [tools/costume_mat_README.txt](tools/costume_mat_README.txt).
- [docs/historique/](docs/historique/README.md): the release notes written in French while the tool was
  developed ("historique" = history), kept as they were.

**Why so many French names.** SM3 Studio was written in French. File names, function names, JSON
keys, stage names and log tags stay French because other code, saved settings or the window read
them exactly; every file starts with a docstring in English that explains its names. A few you
will meet everywhere: `convertir` = convert, `chaine` = chain, `poids` = weights, `bras` = arms,
`vanilla` = the game's original, `racine` = project folder, `jeu` = game, `costume` = suit,
`mat` = matte, `qualite` = quality, `apercu` = preview, `construire` = build.

```
SM3 Studio
├── sm3_studio_hq.py       entry point (window, or command line with arguments)
├── sm3_interface.py       the main window          sm3_gui_hq.py   its HQ additions
├── studio_language.py     English for the window
├── sm3_convertir.py       the converter, stage by stage
├── *.py                   converter stages that run inside the .exe (see ARCHITECTURE)
├── qualite.json           atlas quality settings     texture_qualite.json   texture encoding settings
├── tools/                 Blender scripts, texture encoder, checks, installers, extraction, matte suit
├── construire/            recipe of SM3 Studio.exe
├── correctifs_blender/    our fixes to TSGAMING264's add-ons (apply_fixes.py) and the files derived from them
├── profiles/              our measurement files (game data lands here too, ignored)
├── support_venom_*/       Venom research
└── docs/                  ARCHITECTURE, FORMATS, history
```

---

## Licence and credits

SM3 Studio is free software under the **GNU General Public License, version 3 or later**
([LICENSE](LICENSE)). It drives TSGAMING264's GPL-3.0-or-later Blender add-ons and contains two
files derived from them (`correctifs_blender/blacksuit_mesh_writer.py`,
`correctifs_blender/sm3_baked_atlas.py`), hence the same licence. Every source file carries the
line `SPDX-License-Identifier: GPL-3.0-or-later`.

Full credits: [CREDITS.md](CREDITS.md). In short: **TSGAMING264** for the SM3 Blender Toolkit, the
SM3 Material Combiner and xeSM3, without which none of this would load in the game.

*Spider-Man 3* is a game by Treyarch, published by Activision; Spider-Man is a Marvel character.
This project is not affiliated with, endorsed by or connected to any of them. Use it with a copy of
the game you own.
