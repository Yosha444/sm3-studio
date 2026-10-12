# SPDX-License-Identifier: GPL-3.0-or-later
"""Install, or remove, the EXPERIMENTAL Venom draw adapter in the game folder (hash-guarded rollback).

    python install.py --mod <mod name> [--game "C:\\Games\\Spider-man 3"]     install
    python install.py --remove [--game "C:\\Games\\Spider-man 3"]             remove

Installs three files next to Game.exe, and refuses to overwrite anything already there:
    winmm.dll               the adapter, compiled from direct_runtime.cpp (see build.cmd)
    winmm_real.dll          a copy of YOUR Windows' 32-bit winmm.dll (SysWOW64): winmm.dll
                            forwards every multimedia call of the game to it (forwards.h)
    venom_direct_atlas.tex  the full-colour atlas made by make_atlas.py
Before that it checks that:
    - the game is closed;
    - packs/STORY_MOVIE_4_PHASE3.PCPACK is the original pack (the adapter changes nothing in it);
    - Game.exe imports only Direct3DCreate9 from d3d9.dll (the adapter hooks that import) and
      imports winmm.dll (that is what makes Windows load our winmm.dll from the game folder);
    - the installed mod Mods/<mod>/... is the one the DLL and atlas were built for: same mesh and
      index texture as recorded by make_atlas.py in atlas_signature.json.
installation.json (next to this script) records what was installed; --remove deletes exactly
those files, and only if they were not modified since.

Status: never wired into SM3 Studio, never seen working in game (see README.md).
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
DEFAULT_GAME = r'C:\Games\Spider-man 3'
FILES = ('winmm_real.dll', 'venom_direct_atlas.tex', 'winmm.dll')    # install order (removed in reverse)
PACK = '9d5e63f8c18328e7b9b07786e37b5cc14ad9c58bb91237a2578ea30a4486993f'   # sha256 of the original pack
SCOPE = Path('STORY_MOVIE_4_PHASE3') / '_O0114.0x2AF92556.T36.apkf'
MESH, INDEX_TEX = '0xBF11C1BF.ch_venom000.mesh', '0xA164D857.ch_venom_ppi.tex'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def imports(path):
    """{dll name: [imported names or ordinals]} read from the PE import table of an x86 exe."""
    b = path.read_bytes(); u = lambda o: struct.unpack_from('<I', b, o)[0]
    pe = u(60); require(b[pe:pe + 4] == b'PE\0\0', 'Invalid PE file')
    require(struct.unpack_from('<H', b, pe + 4)[0] == 0x14c, 'x86 executable required')
    n = struct.unpack_from('<H', b, pe + 6)[0]; opt = pe + 24
    sec = opt + struct.unpack_from('<H', b, pe + 20)[0]

    def offset(rva):
        for i in range(n):
            p = sec + i * 40; va = u(p + 12)
            if va <= rva < va + max(u(p + 8), u(p + 16)): return u(p + 20) + rva - va
        raise RuntimeError('Invalid RVA')

    def string(p): return b[p:b.index(b'\0', p)].decode('ascii')
    p = offset(u(opt + 104)); result = {}
    while u(p + 12):
        name = string(offset(u(p + 12))).lower(); t = offset(u(p) or u(p + 16)); names = []
        while u(t):
            v = u(t); names.append(str(v & 65535) if v & 0x80000000 else string(offset(v) + 2)); t += 4
        result[name] = names; p += 20
    return result


def system_winmm():
    """The 32-bit winmm.dll of this Windows (the game is a 32-bit program)."""
    windir = Path(os.environ.get('WINDIR', r'C:\Windows'))
    for candidate in (windir / 'SysWOW64' / 'winmm.dll', windir / 'System32' / 'winmm.dll'):
        if candidate.is_file():
            return candidate
    raise RuntimeError('winmm.dll of Windows not found')


def source_of(name):
    if name == 'winmm_real.dll' and not (ROOT / name).is_file():
        return system_winmm()
    return ROOT / name


def main(argv=None):
    ap = argparse.ArgumentParser(description='Install or remove the experimental Venom draw adapter.')
    ap.add_argument('--game', default=DEFAULT_GAME, help='game folder (default: %s)' % DEFAULT_GAME)
    ap.add_argument('--mod', help='name of the installed Venom mod (folder in Mods) the adapter was built for')
    ap.add_argument('--remove', action='store_true')
    a = ap.parse_args(argv)
    game = Path(a.game)
    task = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Game.exe', '/FO', 'CSV', '/NH'], capture_output=True, text=True, check=True)
    require(not any(s.lower().startswith('"game.exe",') for s in task.stdout.splitlines()), 'Close the game before this operation.')
    receipt = ROOT / 'installation.json'
    if a.remove:
        state = json.loads(receipt.read_text())
        require(Path(state['game']).resolve() == game.resolve(), 'The module was installed in another folder: ' + state['game'])
        for name in FILES:
            target = game / name
            require(not target.exists() or digest(target) == state['files'][name], 'File modified: removal stopped ' + name)
        for name in reversed(FILES):
            target = game / name
            if target.exists(): target.unlink()
        state['installed'] = False; receipt.write_text(json.dumps(state, indent=2))
        print('Module removed; the Venom mod itself is kept.'); return
    require(a.mod, '--mod is required to install (the Venom mod the adapter was built for).')
    require(digest(game / 'packs/STORY_MOVIE_4_PHASE3.PCPACK') == PACK, 'Pack differs from the original version.')
    table = imports(game / 'Game.exe')
    require(table.get('d3d9.dll') == ['Direct3DCreate9'], 'Unexpected layout of the Direct3D imports')
    require('winmm.dll' in table, 'WinMM import missing')
    signature = json.loads((ROOT / 'atlas_signature.json').read_text())
    scope = game / 'Mods' / a.mod / SCOPE
    require(digest(scope / INDEX_TEX) == signature['index_texture_sha256'], 'Venom texture of the mod differs from the one the adapter was built for (run make_atlas.py and build.cmd again).')
    require(digest(scope / MESH) == signature['mesh_sha256'], 'Venom mesh of the mod differs from the one the adapter was built for (run make_atlas.py and build.cmd again).')
    require(digest(ROOT / 'venom_direct_atlas.tex') == signature['atlas_sha256'], 'venom_direct_atlas.tex differs from atlas_signature.json')
    for name in FILES:
        require(source_of(name).is_file(), 'Missing source ' + name)
        require(not (game / name).exists(), 'File already present, nothing overwritten: ' + name)
    hashes = {name: digest(source_of(name)) for name in FILES}
    created = []
    try:
        for name in FILES:
            created.append(game / name); shutil.copy2(source_of(name), game / name)
            require(digest(game / name) == hashes[name], 'Invalid copy ' + name)
        require(digest(game / 'packs/STORY_MOVIE_4_PHASE3.PCPACK') == PACK, 'Pack modified')
        state = {'installed': True, 'game': str(game), 'mod': a.mod, 'files': hashes, 'pack_unchanged': PACK, 'in_game_verified': False}
        receipt.write_text(json.dumps(state, indent=2)); print(json.dumps(state, indent=2))
    except Exception:
        for path in reversed(created):
            if path.exists(): path.unlink()
        raise


if __name__ == '__main__':
    main()
