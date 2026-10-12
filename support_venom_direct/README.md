# Venom draw adapter (experimental, not used by SM3 Studio)

This folder is a **research module**, kept because it is our work and documents an approach.
SM3 Studio does not use it: no button calls it, and the Venom conversion works without it.

**Status (measured, 2026-10-12):** it was built and installed once, in September 2026, for a single
test mod ("Venom Blue"). The last log it wrote in the game folder contains only
`CREATE9_HOOK_ACTIVE`: the DLL was loaded and hooked Direct3D, but it never logged a recognised
texture (`ATLAS_MATCH`) or shader (`SHADER ... DIRECT_READY`). It was then disabled. So it has
**never been seen working in game**. Treat it as a starting point, not as a feature.

## What it tries to do

In the game, Venom is drawn with a 256-colour palette: his main texture holds a palette *index*
per pixel and a second texture holds the palette. SM3 Studio's Venom conversion has to reduce your
model's colours to 256 for that reason (`tools/venom_native_textures.py`).

The adapter keeps everything of the game (pack, mesh, vertex shaders) and changes only what
happens at draw time:

1. `winmm.dll` is a proxy: the game imports `winmm.dll`, Windows finds ours in the game folder
   first, and every real multimedia call is forwarded to `winmm_real.dll`, a copy of Windows' own
   32-bit `winmm.dll` (`forwards.h` lists the exports).
2. When loaded, it replaces the game's import of `Direct3DCreate9`, then hooks
   `IDirect3D9::CreateDevice` and the device's `DrawIndexedPrimitive` (v-table slot 82).
3. At each draw it looks at the texture on sampler 6. If it is the mod's index texture (32 known
   texels, `atlas_signature.h`) and the current pixel shader is one of the 4 Venom shaders
   (recognised by an FNV-1a hash of its tokens), it swaps in:
   - a modified copy of that shader, where the palette lookup (about 35 instructions) is replaced
     by `texld r0, v1, s6` (read the colour directly) and `mov r1, cN.w`;
   - a full-colour 4096 x 4096 atlas (`venom_direct_atlas.tex`) on sampler 6, linear filtering;
   then draws and restores the game's shader, texture and sampler states.

## What is ours, what comes from the game

| File | Origin | Published |
| --- | --- | --- |
| `direct_runtime.cpp` | ours (the adapter) | yes |
| `forwards.h` | ours (generated list of `winmm.dll` export names, from our earlier redirector project) | yes |
| `install.py`, `remove_module.cmd`, `build.cmd` | ours | yes |
| `make_shaders_h.py`, `venom_direct_shaders.json` | ours: the recipe holds instruction ranges and our 2 instructions per shader, no game bytes | yes |
| `make_atlas.py` | ours | yes |
| `shaders.h` | **game bytecode** (4 original shaders + modified copies) | no: rebuilt from your `Game.exe` by `make_shaders_h.py` |
| `winmm_real.dll` | **Microsoft** (Windows' `winmm.dll`) | no: `install.py` copies the one of your Windows (`SysWOW64`) |
| `venom_direct_atlas.tex`, `atlas_signature.h`, `atlas_signature.json` | made from *your* converted mod | no: `make_atlas.py` |
| `winmm.dll`, `validate_direct.exe`, `.obj`, `.lib`, `.exp` | build outputs (they embed `shaders.h`) | no: `build.cmd` |

The earlier release also had `shader_N.asm` / `shader_N.bin` (disassembly and bytecode of the
modified game shaders): they are game-derived and not needed to build, so they are gone.

## Rebuilding it

You need Python 3 with numpy and Pillow, SM3 Studio's repository (for `dilater_atlas.py`,
`tools/png2tex.py`), and Visual Studio Build Tools with C++ (32-bit).

1. **Shaders, from your game.** With an unmodified `Game.exe` (or an intact copy of it):

       python make_shaders_h.py "C:\Games\Spider-man 3\Game.exe"

   It checks the 4 original shaders (file offsets `0x6CB770`, `0x6DD6E0`, `0x6DF100`,
   `0x6E05F0`) by sha256 and refuses a modified exe. Other Game.exe patches that rewrite these
   shaders make the adapter useless anyway: it recognises the *original* shaders at run time.
2. **Atlas, from your mod.** Convert a model with SM3 Studio (target Venom), install it, then:

       python make_atlas.py "<SM3 Studio>\build\<mod name>"

3. **Build**, from an "x86 Native Tools Command Prompt for VS": `build.cmd`. Run
   `validate_direct.exe`: it must end with `D3D9_SHADER_MATCH_ATLAS_LOAD_DRAW_SWAP_AND_RESTORE_OK`.
4. **Install**, game closed: `python install.py --mod "<mod name>" --game "C:\Games\Spider-man 3"`.
   Remove with `remove_module.cmd` (or `python install.py --remove --game ...`).
   Note: RaimiHook also uses a proxy DLL (`d3d9.dll`); this one is `winmm.dll`, they do not
   replace each other, but they were never tested together.

## Measured reproduction (2026-10-12)

- `make_shaders_h.py` on an intact `Game.exe` writes a `shaders.h` identical byte for byte to the
  one of the first build (sha256 `b4986d48e63c5743...`). On the author's installed `Game.exe`,
  which carries other graphics patches, it refuses (shader 0 is no longer original).
- `make_atlas.py` on the test mod's build folder writes an `atlas_signature.h` identical byte for
  byte to the first build. `venom_direct_atlas.tex`: header and full-size level identical; the
  smaller mip levels differ by at most 5/255, because SM3 Studio's texture writer
  (`tools/png2tex.py`) computes mip levels differently since 2026-10-06.
- `install.py` against the first version (which was hard-wired to one folder and one mod), on
  copies: same outcome and same game folder for a normal install and removal, and for the three
  refusals tested (file already present, modified pack, other mod texture).
