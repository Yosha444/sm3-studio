# profiles/

Per-character data SM3 Studio reads when the target is not the red suit.

Most of this folder is **not in the repository**: it is game data, rebuilt on your machine from
your own copy of Spider-Man 3 by `tools/extraire_donnees_jeu.py` (SM3 Studio runs it by itself
before the first conversion). What the repository does contain are our own measurements:

| File | What it is |
|---|---|
| `blacksuit/comparison.json` | section-by-section comparison of the black and red suit meshes (vertex counts, bone palettes, vertex layouts) |
| `blacksuit/frames.json` | the 4x4 transform measured between the black suit and red suit frames, for the 000 and 001 meshes (identity for 000; for 001 a 90-degree turn plus a height offset of 1.198) |
| `venom/roundtrip_validation.json` | import/export round trip of the Venom mesh through Blender: same triangles, no new vertex, weights within 4e-5 |
| `rvb/sources.json` | SHA-256 of the two Spider-Man: Web of Shadows exports SM3 Studio recognises |

Rebuilt from the game: `blacksuit/MESH/`, `blacksuit/SKEL/` (black suit meshes and skeletons),
`venom/*.mesh *.skel *.mat *.tex` (Venom), `venom/venom_shader_patch.json` and
`venom/venom_direct_material.bin` (a suspended Venom experiment, rebuilt from two materials of the
game), `venom/Venom_editable.blend` (made by Blender).

Never rebuilt: `rvb/*.json`, `rvb/*.glb` (models from Spider-Man: Web of Shadows, another game).
Without them, the Web of Shadows mode is simply off.
