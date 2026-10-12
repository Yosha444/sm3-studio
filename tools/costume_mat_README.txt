SM3 - MATTE SUIT (costume_mat.py)
Spider-Man 3 PC (2007) - patch of the suit shaders inside Game.exe
==============================================================================

(This file replaces the French costume_mat_LISEZMOI.txt of earlier releases.
"Costume mat" is French for "matte suit"; the file names were kept so that
SM3 Studio keeps finding them.)

WHAT IT DOES
------------
In the game, Spider-Man's suit looks "oily". That shine is computed by the game
itself (material + "cowbell" animation + per-view factors): no texture in a mod
can change it.

This patch edits the 3 pixel shaders of the suit (class sm_phatspiderman: red
suit, black suit, Peter, cut-scene variants). They are stored inside Game.exe.
Right after the game's own computation, one added instruction imposes:

    final shine      = sat(game shine      x Ks + As)
    final reflection = sat(game reflection x Ke + Ae)

Ks = 0: the game is ignored and As becomes the shine of the suit.
Ks = 1 and As = 0: nothing changes.
Transparency (when the game fades the character out) is not touched.

Presets (Ks As Ke Ae) - the names are SM3 Studio's internal keys, in French:
    satine     0     0.06  0     0     satin: slight constant sheen, no reflection
                                       (recommended, tested in game)
    mat        0     0     0     0     matte: no shine, no reflection
    attenue    0.35  0     0.25  0     softened: keeps the game's nuances, much gentler
    identite   1     0     1     0     identity: no visible change (test)
or 4 free values, for example:  python costume_mat.py install 0 0.1 0 0
(a comma is accepted as decimal separator too: 0,1)

Game.exe keeps its exact size: to make room for the 2 added instructions, the
"Microsoft (R) HLSL Shader Compiler ..." string inside each shader's constant
table, never read by the game, is shortened by as much (44 bytes).

FILES
-----
    costume_mat.py              the script (Python 3, nothing to install)
    costume_mat_shaders.json    the RECIPE (keep it next to the script)
    costume_mat_make_recipe.py  maintainer tool: how the recipe was derived
    costume_mat_README.txt      this file

No game data is shipped. The recipe does not contain the patched shaders: it
says "copy bytes a..b of the original shader, insert these 36 bytes of ours,
put the 4 preset values here". The script follows it on YOUR Game.exe, only
after checking (sha256) that each shader there is the original one, and it
checks the result against the fingerprint of the expected patched shader
before writing anything.

REQUIREMENTS
------------
- Spider-Man 3 PC with its original Game.exe (10 846 998 bytes). Before
  writing, the script checks the size, the entry point (0x9CEBE8) and the
  fingerprint of each of the 3 shaders. If a shader is neither original nor
  patched by this script, it refuses and writes nothing.
- Python 3: https://www.python.org/downloads/ (tick "Add Python to PATH"
  during installation).
- THE GAME MUST BE CLOSED. The script refuses to work while Game.exe runs.
- If the game is installed under C:\Program Files (x86)\..., open the
  command prompt AS ADMINISTRATOR: Start menu, type "cmd", right click on
  "Command Prompt" > "Run as administrator".

USAGE
-----
Open a command prompt in this folder (in Explorer: type "cmd" in the address
bar, then Enter), then:

    python costume_mat.py status                show the state (changes nothing)
    python costume_mat.py install satine        install a preset
    python costume_mat.py install 0 0.06 0 0    install 4 free values
    python costume_mat.py remove                put the original shaders back

The French command words used by SM3 Studio work the same way:
etat = status, installer = install, retirer = remove, --jeu = --game,
--origine = --original.

You can change preset as often as you like, and run a command again safely
(if everything is already in place, the script answers "Nothing to do").

Game folder: C:\Games\Spider-man 3 by default. Otherwise add --game:

    python costume_mat.py install satine --game "D:\Games\Spider-Man 3"

(do not put a \ right before the closing quote)

In SM3 Studio: Target character tab > "Matte suit (reapplied on each
install)". Studio calls this same script, with the same checks.

BACKUPS (IMPORTANT)
-------------------
- Before the very first write, the 3 original shaders (15 KB) are saved next
  to the game in Game.exe.costume_mat_origine.bin. That file is what makes
  "remove" possible. DO NOT DELETE IT.
- A full copy of Game.exe is also made once, before the first modification:
  Game.exe.sauvegarde_patchs_sm3 (never overwritten, shared with the camera
  patch).
- If your Game.exe had already been patched BEFORE this script (for example
  by an older version of the patch), the original shaders are no longer in
  the exe: "status" says so and "remove" refuses and explains why. Then give
  it an intact copy of Game.exe (CD, backup):

    python costume_mat.py remove --original "C:\path\to\Game.exe.original"

  Only the 3 shaders are read from that copy, checked by sha256 fingerprint.
  The script also looks by itself in the "Game.exe.*" copies present in the
  game folder. Last resort: reinstall the original Game.exe, then reapply
  the other patches you want.

COMPATIBILITY
-------------
- Camera patch (other bytes of Game.exe) and swing patch (packs): compatible,
  in any order; each one is removed independently.
- Suit mods loaded by xeSM3 (Mods folder) and RaimiHook: compatible, they do
  not modify Game.exe on disk. The patch applies to every suit of this
  class, including the ones from mods.
- Measured on copies of the original Game.exe (2026-10-12): for every preset
  and for free values, this recipe-based version writes a Game.exe identical
  byte for byte to the one written by the earlier version that shipped the
  full patched shaders (and "remove" gives back the original exe exactly).
