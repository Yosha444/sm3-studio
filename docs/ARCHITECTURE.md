# SM3 Studio — architecture

How SM3 Studio turns a model into a suit mod: the processes involved, the conversion stage by
stage, every file and its role, the settings, and how to rebuild and check the tool. For the game's
file formats see [FORMATS.md](FORMATS.md); for the user's side see the [README](../README.md).

Conventions used here: *measured* = measured on files, on `Game.exe` or in the game, and written
down at the time; *assumed* = believed, not measured. "Vanilla" = the game's own, unmodified files.
Names in `code font` that look French are identifiers kept on purpose (a glossary is at the end).

---

## 1. The big picture

```
 you
  │
  ├── the window: sm3_interface.py + sm3_gui_hq.py          (python sm3_studio_hq.py, or SM3 Studio.exe)
  └── the command line: "SM3 Studio.exe" --nom MyMod --src model.glb
           │
           │  both set sys.argv = ['sm3_convertir', options...] and call, in the same process,
           ▼
     sm3_convertir.main()
           │ 1. tools/extraire_donnees_jeu.ensure_game_data()   first use: rebuild vanilla/, profiles/
           │ 2. which target?
           │      a recognised Web of Shadows export ─► tools/rvb_runner.py
           │      --target blacksuit ────────────────► tools/blacksuit_runner.py
           │      --target venom ────────────────────► tools/venom_runner.py
           │      otherwise, the red suit:
           │ 3. chaine ► ajuster ► bras ► poids ► lod ► atlas ► verifier ► assembler
           ▼
     build/<mod>/   (every intermediate file)  ──►  mods/<mod>/   (the deliverable, xeSM3 layout)
                                                         │
                                Install button, or by hand
                                                         ▼
                                 <game>/Mods/<mod>/ + <game>/Mods/mods.config.ini  ──► xeSM3 ──► game
```

The converter never touches the game folder. Only the install buttons and the Matte suit write
there, each with its own backups.

## 2. Where the code runs

| Process | What runs there | Why |
|---|---|---|
| **SM3 Studio** (`SM3 Studio.exe`, a frozen Python 3.14, or `python sm3_studio_hq.py`) | the window, the converter and every stage that does not need Blender: `ajuster`, `bras`, `poids`, `lod`, `atlas`, `verifier`, `assembler`, `winding_fix`, the extraction, the Matte suit | Our stage scripts are loaded **in-process** (`sm3_convertir.lance()` imports the script and calls its `main()` with a temporary `sys.argv`). Inside the .exe, `sys.executable` is the .exe itself: starting it again would open a second window instead of running a script. |
| **Blender 5.2**, in the background (`blender -b --python ...`) | `tools/chaine_officielle.py` (stage `chaine`), `analyser_modele.py`, `apparier_textures.py`, `render_mesh.py`, the Blender parts of the Black Suit and Venom targets | TSGAMING264's add-ons and the bake need Blender. Only lines starting with `[chaine]` are relayed to the window's log (and the end of Blender's output on failure). |
| **An external Python** with numpy and Pillow | `tools/blacksuit_finalize.py`, `tools/rvb_finalize.py` | They were written as separate scripts; `tools/external_python.py` chooses the interpreter (`SM3_PYTHON`, else the running Python from source, else `python` / `py` on PATH from the .exe). |
| **Elevated PowerShell** (UAC) | `tools/boucle_test.ps1` → `tools/install_admin.ps1` | "Install and launch game" writes into the game folder, often under Program Files. |

During a conversion, the window replaces `sys.stdout` with a queue (`Tuyau`, "pipe"); the Tk main
loop empties it every 60 ms into the log. That is why the Matte suit, which can run at the same
time, prints through its own injected `print` instead of `sys.stdout`.

## 3. Inside the .exe, and on disk

This decides whether a fix needs a rebuild of `SM3 Studio.exe`:

- **inside the .exe** (read from `sys._MEIPASS`): `sm3_studio_hq.py`, `sm3_interface.py`,
  `sm3_gui_hq.py`, `studio_language.py`, and the converter modules of the root (`sm3_convertir.py`,
  `ajuster.py`, `atlas.py`, `dilater_atlas.py`, `glb.py`, `poids_depuis_vanilla.py`,
  `poids_par_segments.py`, `redresser_bras.py`, `reparer_uv_ts.py`, `sm3_sans_blender.py`,
  `transplanter_lod.py`, `uv_depuis_lod.py`), plus `correctifs_blender/blacksuit_mesh_writer.py`;
- **on disk, next to the .exe**, read at run time: `tools/` (everything), `qualite.json`,
  `texture_qualite.json`, `sm3_studio.json`, `language.txt`, `vanilla/`, `profiles/`.

A fix in `tools/` applies at the next conversion (restart the window if it was open: it keeps the
modules it already loaded). A fix in a root module needs a rebuild. Details and the build recipe:
[construire/README.md](../construire/README.md).

The toolkit's format code is read from **Blender's add-on folder**, not from the .exe:
`sm3_sans_blender.py` mounts `sm3_format.py` (mesh and skeleton parser) and `sm3_mesh_writer.py`
of the installed SM3 Blender Toolkit as a package without Blender (only the add-on's `__init__.py`
imports `bpy`). Almost every script does `from sm3_sans_blender import fmt`.

## 4. Start-up

1. `sm3_studio_hq.py`: without arguments, a small window asks for the language
   (`studio_language.choose`, answer kept in `language.txt`). With arguments: no window, French
   interface strings (irrelevant without a window), conversion straight away.
2. It **compiles** `sm3_interface.py` and `sm3_gui_hq.py` from source and, for English, passes the
   code objects through `studio_language.localize()`, which replaces every string constant found in
   the `EN` table. That is why the interface files are executed instead of imported, and why they
   are bundled as source.
3. `sm3_gui_hq.integrate()` patches the `Studio` class: replaces the "General" tab with the
   "General / Quality" panel, adds the "Target character" tab (Spider-Man / Venom / Black Suit,
   Matte suit), and wraps load, save, convert, arguments, preview, model chooser and install.
4. The window opens (`Studio()`), or `_sans_fenetre(args)` converts without one.

Project folder (`RACINE`, "root"): the .exe's folder when frozen; from source, the source folder
itself when `tools\` sits next to it (the repository layout), else its parent (the original
development tree); or the "Dossier du projet" (project folder) field of the Paths tab.
Command-line conversions use the default.

---

## 5. The red-suit conversion, stage by stage

The stage names are command-line values (`--depuis`, "from") and values of the window's "Resume
from stage" list: never translate them. Each stage starts from the **frozen output of the previous
one** (`etape_chaine.mesh`, `etape_ajuste.mesh`, `etape_bras.mesh`, `etape_poids.mesh`; "étape" =
stage), never from its own previous output: re-running `--depuis bras` used to rotate the arms a
second time. Resuming from a stage now gives the same files as the first run.

The two models: `0xAC92103D.ch_spiderman000.mesh` ("the 000", the main suit model) and
`0xAC92103E.ch_spiderman001.mesh` ("the 001", a second model of the same suit, in its own frame).
The reference files are in `vanilla/CH_SPIDERMAN/_O0069.0xCFB154CD.T36.apkf/`.

### `chaine` ("chain") — Blender, `tools/chaine_officielle.py`

The only stage that needs Blender, and the slow one. It runs TSGAMING264's add-on operators in the
order of their README, with our measured additions in between:

1. `sm3.import_vanilla_spider_target`: the vanilla 000 as the target (10 sections, the "canvas"
   section 4, material reference `0x614`).
2. Import of the source model, joined into one object. `tools/qualite_hq.py` applies the geometry
   mode of `qualite.json` (keep / retriangulate / subdivide ×4 without smoothing) and drops
   materials without an image (decal and effect layers of ripped models) by their **share of
   surface**: below 0.2 % (under the smallest textured section the game ships, 0.197 %) they are
   dropped; up to 1 % they are dropped with a warning; above, the model is refused, with what to do. Metallic factors are reset (a diffuse bake of metal is black).
3. Alignment on the vanilla template: stood up, turned forward (a model whose toes point back is
   turned by 180°), scaled to the vanilla height, depth centred on the vanilla **trunk** (centring
   on the median of all vertices put bodies 10 to 19 cm behind the skeleton, *measured*). The
   armature is put in rest position before joining (parts attached to bones landed under the feet).
4. Model with its own rig: `tools/conformer_squelette.py` recognises its bones (Mixamo, with
   Sketchfab's `_012` suffixes; Unreal/Fortnite; Auto-Rig Pro; Biped; Free Fire; free names such as
   "left arm" or "upperarm_l") and **places each bone on the game's bone**: position, direction,
   length; the mesh follows with its own weights, feet kept flat. It writes `conforme.json` (the
   `bras` stage is then skipped) and `doigts_modele.npz` (the rig's fingers, for `mains_poings`).
   `SM3_CONFORMER=non` (or `0`) falls back to scale + centre only.
5. Weights transferred from the vanilla mesh (refined later by `poids`).
6. `sm3mat.auto_setup_source_textures` wires the images (or the manual assignment of the Textures
   tab, `--materiaux`). Skipped when the materials are already wired (the glTF importer inserts a
   Mix node: the graph is walked back to find the image).
7. `sm3mat.create_friend_baked_atlas`: UV repack (quarter turns only with our fixed add-on, see
   [correctifs_blender/README.md](../correctifs_blender/README.md)), bake, dilation. Island density
   is equalised only when needed (`--egaliser-densite auto`: tiled UVs crushed everything into a
   corner, 1 % atlas coverage *measured*, 47 % after; on a clean model it would steal resolution
   from the head).
8. `tools/atlas_recuit.py` ("re-baked atlas"): snaps the UVs to the game's 1/1000 grid and
   **re-bakes** the colours on the snapped UVs (the game samples the rounded UVs: mean offset 1.56
   texels at 4096, *measured*, hence wavy web lines). UVs outside [0, 1] are first brought back by
   an integer offset.
9. `tools/normale_bake.py`: bakes the model's normal map into the atlas unwrap, or deduces one from
   the colours when there is none (gain calibrated on the median slope of real maps, `auto`). The
   colour space of the generated image is set **before** its pixels are written (setting it after
   erases a generated image to black in Blender, *measured*). Output: `normale_swizzle.png`.
10. `sm3.prepare_spider_atlas_section` then the dedicated exporters
    `export_scene.sm3_prepared_spider_atlas` (000) and `..._001` (001). The UV divisor of the
    toolkit's writer is set to 1000 in memory first if it is still 1024.

Outputs in `build/<mod>/`: both meshes, `SM3_Spider_Baked_Atlas_atlas_final.png` and the add-on's
other files, `normale_swizzle.png`, `qualite_hq_rapport.json`, `conforme.json` and
`doigts_modele.npz` when conformed, and `chaine.blend` (the scene, reopened by the Black Suit
pipeline). The 000 is then frozen as `etape_chaine.mesh`.

### `ajuster` ("adjust") — `ajuster.py`

Only when a manual value of the Pose tab is set (scale, rotation, offset, "put on the ground").
Rewrites positions (int16 ÷ 512), normals, tangents and binormals. Otherwise skipped, and an old
`etape_ajuste.mesh` is deleted so it cannot become an input by accident.

### `bras` ("arms") — `redresser_bras.py`

Puts the arms of a model **without** a fitted skeleton into the vanilla bind pose, an A-pose with
the arms 36.6° down (a T-pose model with vanilla weights gives blade-like hands: 23 % of the hands'
weight went to the upper arm, *measured*). Rotates each arm around the shoulder, refines ±25°
against the vanilla surface, blends over the shoulder (`--fondu-bras`, 0.10). **Skipped** when
`conforme.json` exists: the rig fit is already exact, and the refinement against a vanilla surface
of another thickness would undo it. `--sans-retouche` skips `bras` and `poids` entirely.

### `poids` ("weights") — `poids_depuis_vanilla.py` (default) or `poids_par_segments.py`

The default takes **Treyarch's real weights**: each vertex blends the weights of its 6 nearest
vanilla vertices (`--voisins`), 4 influences kept. Measured safeguards:

- **topological repair**: a vertex whose bone is more than `--sauts-max` (4) hierarchy steps from
  its neighbours', or on the other side of the body, takes its neighbours' average, repeatedly;
  a wrong patch "melts from its edge". Co-located vertices are merged first (two vertices at the
  same place with different weights split open as soon as the body moves);
- at most 5 hierarchy steps between two influences of a vertex (`--arcs-max`, the vanilla never
  exceeds 5);
- small detached parts (under 2 % of the mesh) follow one group of bones;
- a **48-bone palette** per section, ranked by domination; finger bones go last when the palette
  overflows (`mains_poings` rebuilds them afterwards); a discarded twist bone (`foretwist`,
  `upperarm split`) gives its vertices to the main bone of its segment;
- `etat_du_maillage` ("state of the mesh") reports three defects no weights can fix: lying down
  (largest extent not the height), arms out of pose (span under 85 % of vanilla), crushed by
  quantisation (share of vertices still distinct after ÷512).

`--methode-poids segments` builds weights from distances to bone segments instead (a fallback when
the two bodies do not overlap at all).

Then, **for models without a rig** only:

- `tools/conformer_sans_rig.py` places arms and legs on the game's joints: each limb is isolated
  by the weights just computed, its centre line measured, and elbow, wrist, knee and ankle put at
  the same fractions as on the vanilla limb (same algorithm on both). A limb whose length is outside
  70-135 % or whose cut is more than 12 cm off is refused and left as it is. Weights are then
  computed again on the posed limbs.
- `tools/doigts_sans_rig.py` finds the fingers as **branches** of the hand (geodesic distance from
  the wrist), poses each one on the game's phalanges, and writes `doigts_modele.npz`. For each hand
  it simulates the game's fist on two variants (fingers posed, hand left as it was) and keeps the
  less torn one; no fixed rule won everywhere.

### `lod` — `transplanter_lod.py`

Writes the **real 001** from the finished 000: every vertex, seam, UV and weight of the 000,
re-encoded (with `correctifs_blender/blacksuit_mesh_writer.py`) into the vanilla 001's layout, bones mapped
between the two skeletons by name hash, positions moved into the 001 frame
`(x, y, z)₀₀₁ = (z, y + 1.199, −x)₀₀₀` (normals, tangents and binormals rotated without the
offset), material `0x560`. A nearest-vertex UV transfer was rejected: on a seam a vertex is
duplicated with two UVs, and 9.6 % of the vertices picked the wrong side (*measured*). The signed
volume and outward-normal score are compared with the vanilla signs after writing.

### After the geometry stages

When any of `chaine`, `ajuster`, `bras`, `poids`, `lod` ran:

1. **vertex colour**: `appliquer_couleur_hq` writes `qualite.json`'s `vertex_color` (black by
   default) on every vertex of both meshes;
2. (the `atlas` stage, below);
3. **`tools/winding_fix.py`** on the 000 then the 001: (1) triangle winding (signed volume must be
   negative), (2) normal direction (normals must point outwards), (3) `tools/mains_poings.py`, the
   30 finger bones (each finger re-weighted along its own bone chain; red suit: the hand is
   detached into its own section with the same material reference, seam vertices duplicated byte
   for byte, so 30 of 30 finger bones fit; a failure is logged with `!!` and never stops the
   conversion; `SM3_MAINS_POINGS=0` skips it), (4) `tools/decoupe_sections.py`, at most 65,535
   vertices and 16-bit indices per section (red suit: split in place; anything else: refused;
   **blocking**).

### `atlas`

1. `dilater_atlas.py` grows each UV island into the empty gutters (`--dilate`, 12 from the window),
   reading the islands from the delivered mesh. It detects the vertical orientation by itself (a
   V-flip bug painted over 3 % to 52 % of real texels before 2026-10-08, *measured*) and logs the
   choice under `[dilat]`. Output: `atlas_dilate.png`.
2. `tools/png2tex.py` (`write_tex`, in-process) encodes `0x8E661B33.ch_spiderman_spider.tex` in the
   chosen format, settings from `texture_qualite.json`.
3. The normal map `0x61DCA273.normswizzle.tex` is **always DXT5** (the shader reads X from the
   alpha channel; DXT1 has none). Without a baked normal map the suit keeps the game's flat look.

### Optional body slot (`--slot`, command line)

`spider` (default, the game's: shine 0.20, ambient and rim light off), `sideweb` (matte) or
`topweb` (glossy). The toolkit's exporter only writes `0x614`, so the switch is made **afterwards**
in the delivered bytes (the material reference of each section, at the section record + 0x20), read
back and checked; the atlas is also delivered as `0x06F18556._grey.tex`, the diffuse those two
materials read. The 001 is not touched (its only alternatives are tiled ×100).

### `verifier` ("check") — `sm3_convertir.verifier()`

Run on the written bytes against the vanilla files. One `OK` / `!!` line per check; if one fails
and `assembler` was asked for, the conversion stops ("final check failed, mod not assembled").

| # | Check | Expected |
|---|---|---|
| 1-2 | internal name hash of the 000 / 001 | `0xAC92103D` / `0xAC92103E` (not the 000's) |
| 3 | materials of the 000 | among the non-tiled `0x614 0x37C 0x640 0xA0` |
| 4 | material of the 001 | `0x560` |
| 5-6 | sections of the 000 / 001 | at most 65,535 vertices, 16-bit indices |
| 7 | vertex colour of the 001 | the `qualite.json` colour on every vertex |
| 8-9 | UVs of the 000 / 001 | within 0..1000 (otherwise they wrap in game) |
| 10 | vertex colour of the 000 | the `qualite.json` colour on every vertex |
| 11 | frame of the 001 | `(z, y + 1.199, −x)` of the 000, max gap < 0.01 |
| 12 | signed volume of the 000 | negative (vanilla −0.116) |
| 13 | bone palette | at most 48 |
| 14-15 | active bone indices of the 000 / 001 | 0 to 47 |
| 16 | atlas | at least 8 mip levels (a short chain shimmers) |
| 17 | weights close to the vanilla | median gap < 0.35 at the same place (0 = the game's weights, 1 = no bone in common), on 1,200 sampled vertices |
| 18 | sides not mixed | vertices pulled by a left **and** a right bone: at most 4 × the vanilla share (at least 1 %); a broken build had 32.6 % against the vanilla's 0.23 % |
| 19 | hierarchy consistency | largest step between two influences ≤ max(5, vanilla's) |

(Checks 10, 11, 16, 18 and 19 are skipped when they cannot apply: no colour attribute, different
vertex counts, no atlas file, no vanilla skeleton.)

### `assembler` ("assemble")

Copies the files under every pack and archive folder where the suit lives, because xeSM3 matches a
loose file by pack **and** archive, with no global fallback:

| File | `CH_SPIDERMAN\_O0069.0xCFB154CD.T36.apkf` | `MARYJANE_SCARERIDE\_O0082.0x4F920A48.T36.apkf` | `STORY_MOVIE_3\_O0121.0x03294B12.T36.apkf` |
|---|---|---|---|
| `0xAC92103D.ch_spiderman000.mesh` | yes | yes | |
| `0xAC92103E.ch_spiderman001.mesh` | yes | yes | |
| `0x8E661B33.ch_spiderman_spider.tex` | yes | yes | yes |
| `0x61DCA273.normswizzle.tex` | yes | yes | yes |
| `0x06F18556._grey.tex` (sideweb / topweb only) | yes | yes | yes |

The mod goes to `<--mods>/<name>` if given (the window gives `<project>/mods`); otherwise, when the
build folder is `<somewhere>/build/<name>`, to `<somewhere>/mods/<name>`, else to
`<project>/mods/<name>`. An existing mod folder of the same name is replaced.

---

## 6. The other targets

### Black Suit (`--target blacksuit`, `tools/blacksuit_runner.py`)

1. `blacksuit_resources.resolve()`: the game's `CH_BLACKSUIT` resources must be in
   `vanilla/CH_BLACKSUIT/_O0108.0xF8ACB40C.T36.apkf/` (186 files, listed with their SHA-256 in
   `resources.json`).
2. `build/<mod>/blacksuit_job.json` holds every setting for the next steps.
3. Blender runs `tools/blacksuit_pipeline.py`: the red-suit chain into `build/<mod>/source`
   (normal map included), `redresser_bras.py`, weights redone from the vanilla with a 48-bone limit
   (`tools/blacksuit_weights.py`, a faster nearest-neighbour version of `poids_depuis_vanilla.py`),
   then `tools/blacksuit_build.py` moves the result onto the black suit's skeletons and **native
   sections** and writes `ch_blacksuit000/001.mesh` + `validation.json`. xeSM3 gives a black suit
   section its material by section *index* (only index 3 carries the texture), so the mesh has
   three one-vertex stub sections and one real section.
4. `sections_ou_refus()` ("sections or refusal") refuses a section above 65,535 vertices, in the
   window's own process so the message reaches the log.
5. The external Python runs `tools/blacksuit_finalize.py`: `dilater_atlas.py`, `winding_fix.py`
   (with `mains_poings`: 26 of 30 finger bones in one section), then `tools/blacksuit_package.py`
   (texture encoding with the per-texture settings of `texture_qualite.json`: ARGB8 2048 with the
   fabric base smoothed; checks against the exact image `png2tex` encodes; mod layout under
   `mods/<mod>/CH_BLACKSUIT/...`).

Installation: `tools/blacksuit_deploy.py` (see §8; known issue).

### Venom (`--target venom`, `tools/venom_runner.py`)

The "native" profile: Venom keeps his own shader (palette lookup) and material.

1. Blender runs `tools/venom_blender.py`: imports the source (`.glb`, `.fbx`, `.obj`, a native
   `.mesh` or a prepared `.blend`), `tools/venom_custom.py` fits a custom character on Venom's
   template (rig recognised: source weights adapted to the rest pose; otherwise spatial transfer),
   `tools/venom_atlas.py` bakes the atlas with the same quality settings, and the mesh is exported
   (`0xBF11C1BF.ch_venom000.mesh`, stride 48, material reference `0x28C`).
2. `tools/venom_native_textures.py`: the atlas becomes a 256-colour palette plus an index texture
   (ARGB8 indices, Venom's native 2048 × 1024), losslessly stored.
3. Blender renders `apercu_venom.png` ("Venom preview", rest pose, not the game's lighting) with
   `tools/venom_preview.py`.
4. Checks (`verify()`): same hash and skeleton reference as Venom's, 70-bone skeleton, every
   section non-empty, material `0x28C`, palette bones in range, at most 65,535 vertices and 16-bit
   indices per section (Venom's mesh does not go through `winding_fix`, so it is refused rather
   than split). Results in `venom_validation.json` (French keys, kept).
5. Assembly under `mods/<mod>/STORY_MOVIE_4_PHASE3/_O0114.0x2AF92556.T36.apkf/`: the mesh, the new
   textures (identity and size checked against Venom's), and Venom's material and skeleton.

Installation: `tools/venom_install.py` (see §8). The suspended "direct" renderer
(`renderer: spider_direct_v1`) is refused at assembly and at installation.

### Web of Shadows mode (`tools/rvb_runner.py`)

Checked before any other target when the source is a `.glb`: if its SHA-256 is listed in
`profiles/rvb/sources.json` **and** that model's profile (`profiles/rvb/<model>.json`,
`.skeleton.json`, from *Spider-Man: Web of Shadows*) is installed, Blender runs the chain for the
atlas only, then `tools/rvb_finalize.py` → `tools/rvb_native.py` rebuilds the meshes from the
profile with the model's **original** weights, using the chain's mesh only to find each vertex's
UVs. Recognition is by content, never by name. The profile is not distributed: the mode is off
unless copied from an older installation.

---

## 7. Game data: `tools/extraire_donnees_jeu.py` and `tools/pcpack.py`

`ensure_game_data()` runs at the start of every conversion: when every file is present it only
checks that they exist; otherwise it finds the game (`--game`, the `jeu` key of `sm3_studio.json`,
the registry's install path, then `C:\Games\Spider-man 3`,
`C:\Program Files (x86)\Activision\Spider-Man 3` and `C:\Program Files\Activision\Spider-Man 3`;
the folder must hold the three packs), reads `CH_SPIDERMAN.PCPACK`,
`CH_BLACKSUIT.PCPACK` and `STORY_MOVIE_4_PHASE3.PCPACK` with the read-only reader `pcpack.py`, and
writes:

| Folder | Content |
|---|---|
| `vanilla/CH_SPIDERMAN/_O0069.0xCFB154CD.T36.apkf/` | red suit: 2 meshes, 2 skeletons |
| `vanilla/CH_BLACKSUIT/_O0108.0xF8ACB40C.T36.apkf/` + `resources.json` | black suit: 186 resources |
| `vanilla/tex_headers/` | 68-byte headers of 12 red-suit textures |
| `profiles/blacksuit/MESH/`, `SKEL/` | the black suit's meshes and skeletons again (read there by the Black Suit tools) |
| `profiles/venom/` | Venom: mesh, skeleton, material, textures, `Venom_editable.blend` (Blender) |

Each file is compared with `tools/game_data_fingerprints.json` (size + SHA-256, sections
"extracted", "distributed", "optional"). *Measured* on 2026-10-12: 261 of 261 extracted files
identical to the reference installation's; the four measurement files of `profiles/` are
distributed with the repository. How each file is cut out of the pack, and the two special
`ch_spiderman000/001.mesh` cases, are explained in the docstrings of both scripts and in
[FORMATS.md](FORMATS.md#2-pcpack-archives).

---

## 8. Installing into the game

**Install and launch game** (red suit target): `Studio.installer` starts, elevated,
`powershell -File tools\boucle_test.ps1 -Mod <name>` and waits, then shows `install.log` and
`boucle.log` ("boucle" = loop: it was a test loop). `boucle_test.ps1`:

1. finds the game: `-Jeu`, the `jeu` key of `sm3_studio.json`, the registry
   (`HKLM\SOFTWARE\WOW6432Node\Activision\Spider-Man 3\InstallPath`), the usual folders; only a
   folder containing `Game.exe` is accepted;
2. glues back a mod name containing spaces (`Start-Process -ArgumentList` does not quote: "sm3
   remake" arrives in two pieces);
3. closes the game if it runs, then calls `install_admin.ps1`, which refuses a folder without
   `Game.exe`, disables leftovers of an earlier experiment of this project (a `winmm.dll` recognised
   by its SHA-256 → `winmm.dll.off`, and a `sm3\mods\` folder → `sm3.off`; any other `winmm.dll`
   is left untouched), copies `mods\<name>` to `<game>\Mods\<name>`, keeps `mods.config.ini.bak`,
   and sets `<name>=100` and **every other** mod of `[EnabledMods]` to 0;
4. starts `Game.exe`. `-Simuler` ("simulate") shows what would be done; `-Captures N` takes
   screenshots through the NVIDIA overlay (a test tool, off by default).

If the Matte suit box is ticked, `sm3_gui_hq` applies the preset first (nothing is written if it is
already in place).

**Black Suit** target: `tools/blacksuit_deploy.py install()` refuses a running game, checks the files
against a `package.json` manifest, backs up `mods.config.ini` and every overwritten file into
`<game>\SM3_Studio_Backups\BlackSuit_tool_<date>\`, removes red-suit files a previous mod of the same
name left, disables other mods that ship the same black suit files, enables this one, and rolls
everything back on any error. *Known issue (measured):* today's packaging writes `package.json`
elsewhere and ships 4 files instead of 3, so it fails on fresh mods.

**Venom** target: `tools/venom_install.py install()` checks the game is closed and the conversion
passed its checks, makes sure `STORY_MOVIE_4_PHASE3.PCPACK` is the **original** pack (if it still
holds the old "direct" patch, it puts the original bytes back, taken from the player's own files and
checked against fingerprints), backs up into `<game>\SM3_Studio_Backups\Venom_<date>\`, copies the
mod, enables it and disables other Venom replacements, reads everything back, and rolls back on any
error. "Restore original Venom" runs the same function with `restore=True`.

## 9. The Matte suit: `tools/costume_mat.py`

The window reads the state with `costume_mat.etat_dossier()` ("folder state", read only) and writes
**only** through `costume_mat.main([...])`, in a thread, exactly like the command line; it looks
for the texts listed in `costume_mat.MARKERS` in the output to show the right message.

- `tools/costume_mat_shaders.json` is a **recipe** per shader: byte ranges to copy from the
  player's original shader, 36 bytes of ours to insert (`def c100`, one `mad_sat` instruction, the
  shortened constant-table comment and the new creator-string offset), and where the 4 preset
  values go. The 44 bytes are made by shortening the "Microsoft (R) HLSL Shader Compiler" string,
  which the game never reads, so `Game.exe` keeps its size.
- Before writing: size and entry point of `Game.exe`, game not running, SHA-256 of each original
  shader; after building: SHA-256 of each patched shader (values masked); after writing: read back,
  and nothing changed outside the 3 shaders. An already patched exe is recognised by the masked
  fingerprint, so changing preset needs no original.
- `tools/costume_mat_make_recipe.py` (maintainers) derives the recipe from an intact `Game.exe` with
  the shader rules (find the constant table, the last `def`, the instruction that reads
  `special_effects_matrix[3]`); `--check` regenerates exactly the shipped JSON.

---

## 10. File reference

### Root (bundled in the .exe)

| File | French meaning | Role |
|---|---|---|
| `sm3_studio_hq.py` | | entry point: language, compile + translate the interface, window or command line |
| `sm3_interface.py` | | the main window: model box, tabs, buttons, log, preview; `_sans_fenetre` = command line |
| `sm3_gui_hq.py` | | HQ additions: quality panel, Target character tab, Venom / Black Suit / Matte suit |
| `studio_language.py` | | the English table and `localize()` |
| `sm3_convertir.py` | convert | the converter: target dispatch, stages, checks, assembly |
| `ajuster.py` | adjust | stage `ajuster` |
| `redresser_bras.py` | straighten the arms | stage `bras` |
| `poids_depuis_vanilla.py` | weights from the vanilla | stage `poids` (default) |
| `poids_par_segments.py` | weights by segments | stage `poids`, segment method; also `lire_skin` used by the checks |
| `transplanter_lod.py` | transplant the LOD | stage `lod` |
| `dilater_atlas.py` | dilate the atlas | stage `atlas` (and the Black Suit's finishing step) |
| `sm3_sans_blender.py` | SM3 without Blender | loads the toolkit's format modules outside Blender (`fmt`, `mw`); also an experimental Blender-free GLB → .mesh converter |
| `glb.py`, `atlas.py` | | glTF reader and copy-based atlas for that experimental path |
| `uv_depuis_lod.py`, `reparer_uv_ts.py` | UVs from the LOD, repair TS's UVs | one-off repairs of one third-party mod; not called by the converter |

### `tools/` (read from disk)

| Group | Files |
|---|---|
| **Red suit chain** | `chaine_officielle.py` (Blender, stage `chaine`), `qualite_hq.py` (quality options inside Blender), `conformer_squelette.py` (rigged models), `atlas_recuit.py` (UVs on the 1/1000 grid + re-bake), `normale_bake.py` (normal map), `conformer_sans_rig.py` and `doigts_sans_rig.py` (models without a rig, stage `poids`), `png2tex.py` (`.tex` encoder), `winding_fix.py` → `mains_poings.py` and `decoupe_sections.py` |
| **Window buttons** | `analyser_modele.py` (Analyze model, Blender), `apparier_textures.py` (Guess texture assignments, Blender), `render_mesh.py` (Render preview, Blender), `boucle_test.ps1` + `install_admin.ps1` (Install and launch game), `costume_mat.py` (Matte suit) |
| **Black Suit** | `blacksuit_runner.py`, `blacksuit_pipeline.py` (Blender), `blacksuit_weights.py`, `blacksuit_build.py`, `blacksuit_finalize.py`, `blacksuit_package.py`, `blacksuit_deploy.py` (install), `blacksuit_resources.py`, `external_python.py`; the mesh writer is `correctifs_blender/blacksuit_mesh_writer.py` (a modified copy of TSGAMING264's writer, see [CREDITS.md](../CREDITS.md)) |
| **Venom** | `venom_runner.py`, `venom_blender.py`, `venom_custom.py`, `venom_atlas.py`, `venom_native_textures.py`, `venom_preview.py`, `venom_install.py`, `venom_shader_patch.json` (offsets + fingerprints of the old pack patch) |
| **Web of Shadows** | `rvb_runner.py`, `rvb_finalize.py`, `rvb_native.py` |
| **Game data** | `extraire_donnees_jeu.py`, `pcpack.py`, `game_data_fingerprints.json` |
| **Matte suit** | `costume_mat.py`, `costume_mat_shaders.json` (recipe), `costume_mat_make_recipe.py` (maintainers), `costume_mat_README.txt` |
| **Manual diagnostics** (not called by SM3 Studio) | `silhouette.py` (front/side point cloud of a `.mesh`), `apercu_modele.py` (shaded render of a `.mesh` or `.glb` without Blender), `uv_footprint.py` (UV area really used per material), `uv_1000.py` (repairs old meshes written with UV ×1024), `deploy.py` (manual mod assembly and copy) |
| **History** (prototypes of the black suit, kept, not called) | `cj_build.py`, `cj_package.py`, `cj_update.py`, `blacksuit_install.py`, `blacksuit_update.py` |
| **Not working / suspended** | `atlas_argb8.py` (imports a module that no longer exists; use `png2tex.py --format ARGB8`), `venom_textures.py` (suspended "direct" Venom renderer) |

### `tools/sm3/`

`dxtenc.py` (DXT1/DXT5 encoders, numpy only: the high-quality one and the old "rapide" one),
`texfind.py` (independent texture decoder used to check our encoders, plus DDS parsing and the early
format-identification tools), `dxtenc_selftest.py` and `texfind_selftest.py` (self-tests, run by
hand), `skel.py` (stand-alone skeleton parser from the early research, not used).

### Other folders

| Folder | Content |
|---|---|
| `construire/` | `SM3Studio.spec` (PyInstaller recipe), `verify_interface.py`, README |
| `correctifs_blender/` | `apply_fixes.py` (applies all our add-on fixes to the user's installed add-ons, safely and reversibly), and every file derived from TSGAMING264's code: our fixed `sm3_baked_atlas.py` for the Material Combiner (to copy into Blender), `blacksuit_mesh_writer.py` (his `sm3_mesh_writer.py` with our changes, imported by `transplanter_lod.py`, `blacksuit_build.py`, `rvb_native.py`; not for Blender), and the description of all our add-on fixes |
| `profiles/` | our measurement files; the extracted game data lands here too (ignored by git) |
| `support_venom_atlas/` | README of the suspended "direct" Venom pack patch (contents not published) |
| `support_venom_direct/` | experimental Venom draw adapter (C++ `winmm.dll` proxy + recipes), never seen working |
| `docs/historique/` | French release notes written during development |

---

## 11. Settings

### `qualite.json` ("quality") — written by the General / Quality panel

| Key | Values | Meaning |
|---|---|---|
| `resolution` | 2048, 4096, 8192 | atlas size (wins over `--bake`) |
| `geometrie` | `conserver`, `retrianguler`, `subdiviser` | keep the mesh, retriangulate quads and n-gons, or subdivide ×4 without smoothing (falls back to retriangulate above the triangle limit) |
| `marge_pixels` | 2..32 | bake margin |
| `limite_triangles` | 1..10,000,000 | above it no geometry is added, and a heavier source is refused (nothing is decimated automatically) |
| `autoriser_couleurs_unies` | true / false | "allow flat colours": bake image-less materials as flat colours even when no material has an image |
| `vertex_color` | `[g, g, g, 255]` | written on every vertex (keep `[0, 0, 0, 255]`) |
| `format` | `DXT1`, `DXT5`, `ARGB8` | the panel's compression choice |
| `dilation_pixels` | integer | used by the Venom texture step (the window passes its dilation value) |

Changing `resolution`, `geometrie`, `vertex_color` or `format` in the window makes the next
conversion restart from `chaine`. The file is replaced atomically (`.tmp` then rename).

### `texture_qualite.json` ("texture quality") — edited by hand

Read by `tools/png2tex.py` at **every** texture write; missing file, key or invalid value → default
(and a `[png2tex]` warning). Keys starting with `_` are comments; the `_aide` ("help") block of the
file explains every key in English.

| Key | Default | Meaning |
|---|---|---|
| `encodeur` | `"hq"` | `"hq"` = high-quality DXT encoder; `"rapide"` = the old fast one |
| `lissage` | active, radius 4, spatial σ 3, colour σ 5 ΔE, `garde_noir` [0.5, 3] | edge-preserving CIELAB bilateral smoothing of mip 0 (colour textures, DXT only), with a guard that leaves near-blacks raw |
| `mips_couleur` | `"srgb"` | mip averaging in sRGB, or `"lineaire"` (linear light) |
| `normale_fondu` | [1, 1, 0.75, 0.5, 0.3, 0.15, 0] | relief kept per mip level of the normal map (the chain validated in game) |
| `normale_renormaliser` | false | renormalised mips (about 20 % more relief at mips 2-5) |
| `dilatation` | active, 2 rings, `fond_min_pct` 5 | background filling before each reduction |
| `lissage_tissu` | off | fabric-base smoothing for dark atlases (web lines, logos, eyes kept) |
| `format_force`, `taille_max` | `""`, 0 | force a format, cap the size |
| `normale_plaquer` | [0, 0] | flatten weak relief of the normal map (degrees) |
| `noir_normale_plaquer` | [9, 14] | the same for the black suit's normal map (validated in game) |
| `par_texture` | `0x0133FD92`: no bilateral, `lissage_tissu` on, ARGB8, 2048 | per-texture overrides by hash; this table **replaces** the default one |

### `sm3_studio.json` — the window's fields

Written when a conversion starts and when the window closes, next to the .exe (or the sources).
Keys: `src`, `textures`, `nom`, `depuis`, `target`, `bake`, `format`, `dilate`, `drop`,
`hq_geometry`, `hq_gray`, `echelle`, `rot_x`, `rot_y`, `rot_z`, `decalage`, `poser`,
`sans_retouche`, `fondu_bras`, `methode_poids`, `voisins`, `puissance`, `part_mini`, `blender`,
`racine`, `jeu`, `vue`, `zoom`, `costume_mat`, `costume_mat_preset`. The command-line converter
also reads `blender`; the extractor and `boucle_test.ps1` read `jeu`. Personal: never commit it.

### `language.txt`

`en` or `fr`, written by the language window.

### Environment variables

| Variable | Read by | Effect |
|---|---|---|
| `SM3_BLENDER` | `sm3_convertir.py` (command line) | blender.exe; else the `blender` key of `sm3_studio.json`, else the default Blender 5.2 path. The window always uses its own field. |
| `SM3_TOOLKIT_DIR` | `sm3_sans_blender.py`, `uv_depuis_lod.py` | folder of the SM3 Blender Toolkit add-on (other scripts only use Blender 5.2's default folder) |
| `SM3_PYTHON` | `tools/external_python.py` | python.exe with numpy + Pillow for the Black Suit / Web of Shadows finishing step |
| `SM3_CONFORMER` | `tools/chaine_officielle.py` | `non` / `0`: no rig conformation, scale + centre only |
| `SM3_MAINS_POINGS` | `tools/winding_fix.py` | `0`: skip the finger step |
| `SM3_GAME` | `tools/blacksuit_install.py` (prototype), `tools/sm3/texfind_selftest.py` | game folder |
| `SM3_WORK` | `tools/sm3/texfind_selftest.py` | where decoded PNGs go (default: temp folder) |
| `SM3_SELFTEST_RAPIDE` | `tools/sm3/dxtenc_selftest.py` | `1`: skip the 4096 case ("rapide" = fast) |
| `SM3_ATLAS_ROUGE` | `tools/sm3/dxtenc_selftest.py` | a red-suit atlas PNG for the atlas tests ("rouge" = red) |
| `SM3_UI_LANGUAGE` | `sm3_gui_hq.py` | set by the entry point, not by you |

---

## 12. Log conventions

Every tool prefixes its lines: `[convertir]`, `[chaine]`, `[bras]`, `[poids-van]`, `[poids]`,
`[transplant]`, `[dilat]`, `[ajuster]`, `[mains]`, `[doigts]`, `[membres]`, `[sections]`,
`[costume noir]`, `[venom]`, `[png2tex]`, `[installer]`... The window colours:

- `OK ...` green (passed check), `!!...` red (failure or warning);
- `[convertir] ---` and `[convertir] CONTROLE` blue (section titles and the final verdict:
  "CONTROLE" is French for "check" and the window looks for that word);
- indented `    [...]` grey (details relayed from a tool).

Keep these prefixes when editing: the window and `sm3_convertir.lance()` filter on them. Since
2026-10-12 the converter's messages are in English whatever the interface language; the window's
own texts follow the language chosen at start-up.

## 13. Interface internals, for editors

- Visible strings of `sm3_interface.py` and `sm3_gui_hq.py` are **French by design**: English is
  produced at run time by `studio_language.localize()`, which replaces string constants listed in
  `EN`. Keep each message **one** string constant (Python 3.14 compiles `'%s ... %s' % (a, b)` into
  fragments that no longer match; use `.format()`), and never add to `EN` a string that is also an
  internal value (stage names, JSON keys, presets such as `satine`): it would be translated too and
  the logic would break.
- `self.v` maps every setting name to its Tk variable: it is what `_args()` turns into converter
  options and what `_sauver()` ("save") writes to `sm3_studio.json`.
- Until 2026-10-12 the window existed only as bytecode (`sm3_studio_original.marshal`); how the
  source was recovered and proven equal is in [construire/README.md](../construire/README.md).

## 14. Building `SM3 Studio.exe`

```bat
cd construire
python -m PyInstaller --noconfirm --distpath dist --workpath work SM3Studio.spec
```

Python 3.14 with PyInstaller (6.22.2 used), numpy, Pillow. Copy `construire\dist\SM3 Studio.exe` next
to `tools\`. The spec bundles the interface and converter modules as **source** data files (the
interface must be compiled at run time to be translated), lists hidden imports that only the
disk-read tools need (`configparser`, `heapq`, `itertools`, `importlib.util`...: without
`configparser` the Black Suit and Venom install buttons failed inside the .exe), and keeps the
console for the command-line mode. Everything else: [construire/README.md](../construire/README.md).

## 15. Checking a change

There is no unit-test suite; changes were checked the way the game would see them, **on the
delivered bytes**:

- **Self-tests**, run by hand after touching texture code: `python tools\sm3\dxtenc_selftest.py`
  (encoder and `png2tex` chain, decoded by the independent decoder; about 1 minute, or set
  `SM3_SELFTEST_RAPIDE=1`), `python tools\sm3\texfind_selftest.py` (decoder, on two DDS files of the
  game's `pcinterface\` folder, read only).
- **Conversions compared byte for byte**: run the same conversion with the old and the new code on
  identical copies of a project and compare every file of `build\<mod>\` and `mods\<mod>\` (logs
  compared with durations masked). This is how the 2026-10-12 publication work was proven not to
  change any output.
- **Code-structure comparison**: for comment, docstring and message changes, compare the normalised
  syntax tree (strings blanked) before and after.
- `python construire\verify_interface.py "<old SM3 Studio.exe>"` re-checks that the window's source
  compiles to the bytecode shipped in the builds of 2026-09-09 to 2026-10-08.
- The quick visual checks: Render preview in the window, or `tools\apercu_modele.py` and
  `tools\silhouette.py` without Blender (they showed a "perfectly skinned" model that was in fact a
  cone).

## 16. Glossary of French names

| French | English | | French | English |
|---|---|---|---|---|
| ajuster | adjust | | jeu | game |
| aperçu / apercu | preview | | journal | log |
| apparier | match (textures to materials) | | mains, poings | hands, fists |
| bras | arms | | mat, satiné, atténué | matte, satin, softened |
| chaîne / chaine | chain | | membres | limbs |
| cible | target | | modèle / modele | model |
| construire | build | | noir | black |
| conformer | conform (to the skeleton) | | normale | normal map |
| contrôle / controle | check | | onglet | tab |
| costume | suit | | poids | weights |
| cuisson | bake | | racine | root, project folder |
| découper / decoupe | split | | recuit | re-baked |
| depuis | from (stage) | | redresser | straighten |
| dilater | dilate | | réglages / reglages | settings |
| doigts | fingers | | sans | without |
| échelle / echelle | scale | | sauvegarde | backup |
| étape / etape | stage | | squelette | skeleton |
| extraire les données | extract the data | | tissu | fabric |
| fondu | blend, fade | | toile | web |
| gabarit | template | | vanilla | the game's original |
| historique | history | | voisins | neighbours |
