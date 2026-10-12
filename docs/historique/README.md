# docs/historique/ — release notes written during development (French)

*"historique" is French for "history".* These are the notes that shipped with the ZIP releases of
"SM3 Studio HQ" between September and October 2026. **They are kept in French, as they were
written**, because they record when and why each change was made and what was measured at the
time. Each file starts with a one-line English note saying so; nothing else was changed.

The current documentation is the repository's [README](../../README.md),
[ARCHITECTURE.md](../ARCHITECTURE.md) and [FORMATS.md](../FORMATS.md). Where these notes disagree with
it, the current documentation wins. Paths such as `Documents\SM3-modding-projet-complet\sauvegardes\...`
point to the authors' working folders and are not part of this repository.

| File | Date | What it is about (in English) | Out of date since |
|---|---|---|---|
| `RIG_UPDATE.md` | 2026-09-14 | the bone palette is 48, not 32 (three measurements); topological repair of the weights; three mesh defects no weights can fix (lying down, arms out of pose, crushed by quantisation); the generated normal map that arrived black in Blender; auto-calibrated relief; small detached parts; the no-Blender preview tools | still accurate |
| `RVB_UPDATE.md` | 2026-09-09 | Web of Shadows mode (French and English): two recognised exports converted with their original weights; the red suit's lens section measured at /1000 | its "32 bones" limit is wrong (48, see `RIG_UPDATE.md`); the Web of Shadows profile is no longer distributed |
| `COSTUME_NOIR.md` | 2026-09-08, updated 2026-10-06 | the Black Suit target ("costume noir"), validated in game with the CJ model | the black suit's game files are no longer bundled (extracted from your game); the finishing step no longer uses a "Codex" Python runtime (`SM3_PYTHON` or the running Python) |
| `MISE_A_JOUR_2026-10-06.md` | 2026-10-06 | "update": high-quality DXT encoder and new texture chain (`texture_qualite.json`), clenched fists (30 finger bones), `--slot topweb`, the Matte suit box, quieter black suit, Install and launch button repaired | the window is now source (`sm3_interface.py`), not `sm3_studio_original.marshal`; `costume_mat_LISEZMOI.txt` became `costume_mat_README.txt`; `costume_mat_shaders.json` is now a recipe, not shaders; the patcher's output is now English |
| `MISE_A_JOUR_2026-10-07.md` | 2026-10-07 | proportions: every joint placed on the game's skeleton, with a rig (`conformer_squelette.py`) or without (`conformer_sans_rig.py`, `doigts_sans_rig.py`); depth centred on the trunk; backward-facing models turned | still accurate |
| `MISE_A_JOUR_2026-10-08.md` | 2026-10-08 | detail: the engine is already "large" (no exe patch needed); atlas dilation V-flip bug; UVs outside [0, 1]; automatic section splitting above 65,535 vertices; fast finger step on dense models | still accurate (its `photoreal_detail` textures are a separate mod, not part of the tool) |
| `README_EN.txt` | 2026-10-06 | the short English readme of the ZIP release | the black suit's files are no longer bundled; no "Codex" runtime; the converter's output is now English; see the current README |
