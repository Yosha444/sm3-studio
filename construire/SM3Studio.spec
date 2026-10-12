# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""PyInstaller recipe of SM3 Studio.exe (one file, console window kept for the command-line mode).

Build (Windows, Python 3.14 with PyInstaller, numpy and Pillow installed), from this folder:

    python -m PyInstaller --noconfirm --distpath dist --workpath work SM3Studio.spec

then copy dist\\SM3 Studio.exe into the project folder (the one holding tools\\, vanilla\\,
mods\\ ...). See construire/README.md.

What goes INSIDE the .exe and what stays on disk matters:
  * Bundled (data files at the root of sys._MEIPASS): the entry point's two interface sources and
    the root modules of the converter. sm3_studio_hq.py compiles / imports them from
    sys._MEIPASS, so a fix made on disk to one of these files is invisible until the .exe is
    rebuilt. They are bundled as .py source on purpose: the interface has to be compiled at run
    time so that studio_language.localize() can translate it.
  * NOT bundled: qualite.json, texture_qualite.json, sm3_studio.json, tools\\, vanilla\\,
    profiles\\. They are read under the project folder at run time, so they stay editable and a
    fix in tools\\ applies without rebuilding.
"""
import os

# SPECPATH (set by PyInstaller) is the folder of this .spec file; the repository is its parent.
REPO = os.path.dirname(os.path.abspath(SPECPATH))

ROOT_MODULES = [
    # converter (loaded by sm3_interface: sm3_convertir.py, which imports the others)
    "ajuster.py", "atlas.py", "dilater_atlas.py", "glb.py", "poids_depuis_vanilla.py",
    "poids_par_segments.py", "redresser_bras.py", "reparer_uv_ts.py", "sm3_convertir.py",
    "sm3_sans_blender.py", "transplanter_lod.py", "uv_depuis_lod.py",
    # interface (compiled by sm3_studio_hq.py) and its translation table
    "sm3_interface.py", "sm3_gui_hq.py", "studio_language.py",
]
datas = [(os.path.join(REPO, name), ".") for name in ROOT_MODULES]
# transplanter_lod.py imports blacksuit_mesh_writer from "<its own folder>\correctifs_blender"
# (the folder of the files derived from TSGAMING264's GPL code), which does not exist inside the
# .exe; bundled at the root, next to it, the module is found on sys.path anyway.
datas.append((os.path.join(REPO, "correctifs_blender", "blacksuit_mesh_writer.py"), "."))

a = Analysis(
    [os.path.join(REPO, "sm3_studio_hq.py")],
    pathex=[REPO],
    binaries=[],
    datas=datas,
    # Modules that only the files read at run time import (bundled sources executed with
    # compile/exec, and tools\*.py read from disk): PyInstaller's analysis cannot see them.
    #  - configparser: tools\venom_install.py and tools\blacksuit_deploy.py. Missing from the
    #    builds until 2026-10-06, the Black Suit and Venom install buttons failed inside the .exe
    #    with "No module named 'configparser'".
    #  - argparse, hashlib, shutil, subprocess: tools\costume_mat.py (already bundled anyway,
    #    listed as a reminder).
    #  - heapq, itertools, importlib.util: tools\conformer_sans_rig.py, doigts_sans_rig.py and
    #    mains_poings.py (2026-10-07).
    #  - marshal: imported by the entry point of the builds up to 2026-10-08 (built in, harmless).
    hiddenimports=["numpy", "PIL", "PIL.Image", "PIL.ImageTk", "tkinter", "tkinter.ttk",
                   "tkinter.filedialog", "tkinter.messagebox", "struct", "json", "marshal",
                   "configparser", "argparse", "hashlib", "shutil", "subprocess",
                   "heapq", "itertools", "importlib.util"],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="SM3 Studio",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    # console=True: the same .exe is also the command-line converter ("SM3 Studio.exe" --nom ...).
    console=True, disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
