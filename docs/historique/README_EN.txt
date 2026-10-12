[Historical note: the readme of the 2026-10-06 ZIP release, kept as it was written. Several statements are out of date: see docs/historique/README.md and the repository's README.md.]

SM3 Studio HQ — Français / English

Extract the entire ZIP before opening SM3 Studio.exe.
Choose English or Français in the startup language dialog. Your choice is remembered.
The interface, main dialogs and quality options are translated. Technical output from Blender and conversion scripts can still be in French.

Black Suit workflow:
1. Select Target character > Black Suit.
2. Select a GLB, glTF, FBX or OBJ and enter a mod name.
3. Click Convert. Both 000 and 001 are generated.
4. Close the game and use the installation button.

The Black Suit preset uses black vertex colors, ARGB8 textures and 12-pixel dilation, without cel shading. The CJ workflow was tested successfully in game. Other source models still need in-game animation testing.

Requirements: the existing Blender 5.2 installation with the SM3 Blender toolkit, and Python with NumPy/Pillow for Black Suit texture processing. These dependencies are not bundled in this ZIP. On the original computer the tool uses the installed Codex Python runtime. Check the Paths tab after moving the tool.

Generated mods, personal paths, source models and temporary build files are not included. Native target profiles and conversion scripts are included.

CH_BLACKSUIT original meshes, skeletons, materials and textures are bundled in vanilla/CH_BLACKSUIT/_O0108.0xF8ACB40C.T36.apkf. The converter resolves this folder relative to Studio; no original Downloads folder is needed.

Update 2026-10-06: see MISE_A_JOUR_2026-10-06.md (high-quality DXT encoder, texture settings in texture_qualite.json, clenched fists with the finger joints restored, --slot topweb). Close and restart SM3 Studio.exe after replacing the tools folder.
Mise a jour du 2026-10-06 : voir MISE_A_JOUR_2026-10-06.md (encodeur DXT haute qualite, reglages texture_qualite.json, poings serres, --slot topweb). Relancer SM3 Studio.exe apres avoir remplace le dossier tools.

Matte suit (2026-10-06, section 9 of MISE_A_JOUR_2026-10-06.md): Target character tab > "Matte suit (reapplied on each install)". Pick a preset (Satin is the default, tested in game), click "Apply to game" with the game closed; "Remove matte suit" restores the original shaders. It patches the suit shaders inside Game.exe, so it works for every Spider-Man suit, red, black and converted mods. Set the Game folder in the Paths tab (the folder that contains Game.exe). Other Game.exe patches (camera) are not touched. When the box is checked, the preset is reapplied before each suit installation. This update replaces SM3 Studio.exe and adds tools\costume_mat.py, tools\costume_mat_shaders.json and tools\costume_mat_LISEZMOI.txt. It also fixes the Black Suit and Venom install buttons in the exe ("No module named 'configparser'").
