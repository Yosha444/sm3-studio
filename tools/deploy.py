# SPDX-License-Identifier: GPL-3.0-or-later
"""deploy.py - assemble an xeSM3 mod (one copy under each PACK/APKF scope) and copy it into the game.

Status: NOT CALLED by SM3 Studio. It predates the converter's `assembler` stage (sm3_convertir.py
already lays the files out under every scope) and the "Install and launch game" button
(tools/boucle_test.ps1). Kept as a manual helper for hand-made mods.

Why every scope: xeSM3 (TSGAMING264's mod loader) matches a replacement on the exact identity
PACK + APKF + TYPE + HASH, with no global fallback. A resource used by several packs must
therefore be present under EACH scope, otherwise it stays vanilla in the missions served by the
other pack. The scopes are read from the loader's catalogue `<game>\\Mods\\filelist.apkf.paths.txt`
(one `PACK/APKF/.../file` path per line).

    python deploy.py --mod Sukuna [--src <folder>] [--game <game folder>] [--all-scopes] [--install]

Without --install: completes `<src>/<mod>` and prints the copy command (the game folder is
usually under Program Files, hence protected: the copy needs administrator rights).
With --install: copies the mod folder into <game>/Mods. In both cases the mod still has to be
enabled in <game>/Mods/mods.config.ini (the line to add is printed).
"""
import argparse
import os
import shutil
import sys

# Default game folder: the location the game's installer proposes. Use --game for any other.
GAME = r"C:/Program Files (x86)/Activision/Spider-Man 3"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(HERE, '..', 'mods')


def scopes_for(catalog, filename):
    """[(PACK, APKF)] where this resource exists in the vanilla game, according to the catalogue."""
    out = []
    with open(catalog, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip().replace('\\', '/')
            if line.endswith('/' + filename):
                parts = line.split('/')
                if len(parts) >= 3:
                    out.append((parts[0], parts[1]))
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mod', required=True)
    ap.add_argument('--src', default=DEFAULT_SRC)
    ap.add_argument('--game', default=GAME)
    ap.add_argument('--all-scopes', action='store_true', help='duplicate under every pack of the catalogue')
    ap.add_argument('--install', action='store_true', help='copy into the game (administrator rights required)')
    a = ap.parse_args()

    root = os.path.join(a.src, a.mod)
    if not os.path.isdir(root):
        sys.exit(f'mod folder not found: {root}')
    catalog = os.path.join(a.game, 'Mods', 'filelist.apkf.paths.txt')

    files = []
    for r, _d, fs in os.walk(root):
        for f in fs:
            files.append(os.path.join(r, f))
    print(f'mod {a.mod}: {len(files)} file(s)')

    if a.all_scopes and os.path.exists(catalog):
        added = 0
        for p in list(files):
            name = os.path.basename(p)
            for pack, apkf in scopes_for(catalog, name):
                dst = os.path.join(root, pack, apkf, name)
                if os.path.normcase(dst) == os.path.normcase(p) or os.path.exists(dst):
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(p, dst)
                print(f'  + {pack}/{apkf}/{name}')
                added += 1
        print(f'{added} scope duplicate(s)')

    print('\nfinal tree:')
    for r, _d, fs in sorted(os.walk(root)):
        for f in sorted(fs):
            p = os.path.join(r, f)
            print(f'  {os.path.relpath(p, a.src)}  ({os.path.getsize(p)} bytes)')

    ini = os.path.join(a.game, 'Mods', 'mods.config.ini')
    print(f'\n{ini} must contain, under [EnabledMods]:\n  {a.mod}=100')
    if a.install:
        dst = os.path.join(a.game, 'Mods', a.mod)
        shutil.copytree(root, dst, dirs_exist_ok=True)
        print(f'installed -> {dst}')
    else:
        print(f'\nCopy (administrator PowerShell):\n'
              f'  Copy-Item -Recurse -Force "{os.path.abspath(root)}" "{os.path.join(a.game, "Mods")}"')


if __name__ == '__main__':
    main()
