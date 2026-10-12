# SPDX-License-Identifier: GPL-3.0-or-later
"""Transactional installation of a converted Venom mod, and restoration of the game's own Venom.

Called by SM3 Studio (buttons "Install" and "Restore original Venom"): install(root, game, mod).

What an installation does, in this order, with everything rolled back on any error:
  1. checks that the game is closed, the folders are the right ones and the conversion passed
     its checks (build/<mod>/venom_validation.json, same mesh as the one that was checked);
  2. makes sure packs/STORY_MOVIE_4_PHASE3.PCPACK is the ORIGINAL pack (see below);
  3. backs up the pack and Mods/mods.config.ini into <game>/SM3_Studio_Backups/Venom_<date>/;
  4. copies the mod's resources into Mods/<mod>/STORY_MOVIE_4_PHASE3/<pack scope>/ (xeSM3 loads
     them from there), enables the mod and disables every other enabled mod that also replaces
     Venom's mesh;
  5. reads everything back and compares it with what was meant to be written.

Why the pack is checked at all. An earlier experiment ("direct" Venom renderer, Sept. 2026)
rewrote Venom's material inside STORY_MOVIE_4_PHASE3.PCPACK so that Venom would use Spider-Man's
shader. That crashed the game, so it is suspended (see install() and support_venom_atlas/README.md).
Mods built today ("native" format) need the ORIGINAL pack. If the pack still holds that old
patch, it is put back to its original bytes here.

No game data is shipped for that. venom_shader_patch.json (next to this file) only holds
fingerprints (sha256) and offsets. The original bytes are taken from the player's own files:
  - the 184-byte material record: from the player's ORIGINAL Venom material, i.e.
    profiles/venom/0x8910FC42.ch_venom01_-_default.mat (extracted from the player's game), or
    from a pack backup in <game>/SM3_Studio_Backups/ (every installation makes one);
  - the 5 relocation entries: recomputed. Each one is the dword index of a field of that
    material inside the pack section, 0x28C + field_offset / 4; the patch had moved 5 of them
    to other fields.
Every piece is checked against its fingerprint, and the whole pack against the original pack's
fingerprint, before anything is written.
"""
import configparser
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

SCOPE = Path('STORY_MOVIE_4_PHASE3') / '_O0114.0x2AF92556.T36.apkf'   # xeSM3 folder of Venom's pack
MESH = '0xBF11C1BF.ch_venom000.mesh'
# Resources of the original Venom material that the suspended "direct" renderer did not use.
OBSOLETE = ('0x8910FC42.ch_venom01_-_default.mat', '0xA164D857.ch_venom_ppi.tex', '0xA164D85E.ch_venom_ppp.tex')
ORIGINAL_MATERIAL = OBSOLETE[0]                  # in profiles/venom: the player's original material
MANIFEST = 'venom_shader_patch.json'             # in tools/: fingerprints of the old pack patch


def digest(data):
    return hashlib.sha256(data).hexdigest()


def game_running():
    """True if a process named Game.exe is running (also used by blacksuit_deploy.py)."""
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Game.exe', '/FO', 'CSV', '/NH'],
                            capture_output=True, text=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), check=True)
    return any(line.lower().startswith('"game.exe",') for line in result.stdout.splitlines())


def original_material_sources(root, game):
    """Places that may hold the original bytes of Venom's material, most direct first."""
    sources = []
    if root is not None:
        sources.append(('material', Path(root) / 'profiles' / 'venom' / ORIGINAL_MATERIAL))
    if game is not None:
        backups = Path(game) / 'SM3_Studio_Backups'
        if backups.is_dir():
            for folder in sorted(backups.iterdir(), reverse=True):     # newest backup first
                sources.append(('pack', folder / 'STORY_MOVIE_4_PHASE3.PCPACK'))
    return sources


def original_bytes(item, manifest, root, game):
    """The original bytes of one patched range, from the player's own files (checked by sha256)."""
    if item['kind'] == 'relocation':
        value = item['material_dword'] + item['field_original'] // 4
        data = value.to_bytes(4, 'little')
        if digest(data) != item['sha256_original']:
            raise ValueError('Pack check failed (relocation at offset %d).' % item['offset'])
        return data
    for kind, path in original_material_sources(root, game):
        try:
            if kind == 'material':
                data = path.read_bytes()
            elif path.is_file() and path.stat().st_size == manifest['size']:
                with path.open('rb') as stream:
                    stream.seek(item['offset'])
                    data = stream.read(item['length'])
            else:
                continue
        except OSError:
            continue
        if len(data) == item['length'] and digest(data) == item['sha256_original']:
            return data
    raise ValueError('The Venom pack still contains the old suspended "direct" patch, and the original '
                     'Venom material was not found to undo it (looked in profiles/venom/%s and in the '
                     'pack backups of SM3_Studio_Backups). Extract the game data (profiles/venom) again '
                     'from an intact game, or put back an original STORY_MOVIE_4_PHASE3.PCPACK. '
                     'Nothing was replaced.' % ORIGINAL_MATERIAL)


def transform_pack(data, manifest, direct, root=None, game=None):
    """Return the pack bytes in the wanted state: original (direct=False) or old patch (direct=True).

    Only original -> original and old patch -> original are possible: the old patch itself is not
    shipped (it made the game crash, and its material record is derived from game data)."""
    before = manifest['original_sha256']; after = manifest['patched_sha256']; current = digest(data)
    desired = after if direct else before
    if current == desired:
        return data
    expected = before if direct else after
    if current != expected:
        raise ValueError('Unknown or already modified pack version: no game file will be replaced.')
    if direct:
        raise ValueError('The "direct" Venom pack patch is not available in this version (it crashed '
                         'the game). Nothing was replaced.')
    result = bytearray(data)
    for item in manifest['patches']:
        offset, length = item['offset'], item['length']
        if digest(result[offset:offset + length]) != item['sha256_patched']:
            raise ValueError('Pack byte check failed.')
        result[offset:offset + length] = original_bytes(item, manifest, root, game)
    if len(result) != manifest['size'] or digest(result) != desired:
        raise ValueError('Final pack check failed.')
    return bytes(result)


def install(root, game, mod_name, restore=False, *, process_check=game_running):
    """Install mods/<mod_name> (built by venom_runner.py) into the game, or restore=True: only put
    the game's own Venom back (original pack, every Venom replacement disabled). Returns a report."""
    root = Path(root).resolve(); game = Path(game).resolve()
    if process_check(): raise ValueError('Close Spider-Man 3 before installing or restoring the pack.')
    if not (game / 'Game.exe').is_file(): raise ValueError('Wrong game folder: Game.exe is missing.')
    if not mod_name or Path(mod_name).name != mod_name or any(x in mod_name for x in ('/', '\\', ':')) or mod_name in ('.', '..'):
        raise ValueError('Invalid mod name.')
    support = json.loads((root / 'tools' / MANIFEST).read_text(encoding='utf8'))
    pack = game / 'packs' / support['pack']; config_path = game / 'Mods/mods.config.ini'
    destination = game / 'Mods' / mod_name / SCOPE

    # Resolve every mutable target inside the explicitly selected game directory.
    def contained(path):
        if not path.resolve().is_relative_to(game): raise ValueError('Destination outside the game folder.')
    for path in (pack, config_path, destination, game / 'SM3_Studio_Backups'): contained(path)
    original_pack = pack.read_bytes(); source = root / 'mods' / mod_name / SCOPE
    assets = []; direct = False
    if not restore:
        build = root / 'build' / mod_name.lower()
        state = json.loads((build / 'venom_build.json').read_text(encoding='utf8'))
        direct = state.get('renderer') == 'spider_direct_v1'
        if direct:
            raise ValueError('Venom installation suspended: this mod was built for the "direct" renderer, '
                             'whose shader change crashed the game. The original pack must be kept. '
                             'Use "Restore original Venom" if needed, and convert the model again '
                             '(current conversions use the native Venom format).')
        if state.get('custom') and state.get('renderer') != 'venom_native_argb_indices_v1': raise ValueError('Convert this old mod again before installing it.')
        checks = json.loads((build / 'venom_validation.json').read_text(encoding='utf8'))
        if not checks or not all(checks.values()): raise ValueError('Conversion not validated.')
        required = [MESH, '0x26EC9D72.ch_venomskeleton_ch_venom000.skel',
                    '0xBF12903E.ch_venom_ao.tex', '0xA164CFBD.ch_venom_nor.tex']
        if not direct: required.extend(OBSOLETE)
        assets = [source / name for name in required]
        for asset in assets:
            if not asset.is_file(): raise ValueError('Missing resource: ' + str(asset))
        # Validate the delivered geometry against the file whose checks were recorded.
        if digest((source / MESH).read_bytes()) != digest((build / MESH).read_bytes()):
            raise ValueError('The assembled mod differs from the checked conversion.')
    patched = transform_pack(original_pack, support, direct, root, game)
    original_config = config_path.read_bytes() if config_path.exists() else None
    config = configparser.ConfigParser(interpolation=None, strict=False); config.optionxform = str
    if original_config: config.read_string(original_config.decode('utf-8-sig'))
    section = next((s for s in config.sections() if s.lower() == 'enabledmods'), 'EnabledMods')
    if not config.has_section(section): config.add_section(section)
    disabled = []
    for name, value in list(config[section].items()):
        if value.strip() == '100' and (game / 'Mods' / name / SCOPE / MESH).is_file():
            config[section][name] = '0'; disabled.append(name)
    if not restore: config[section][mod_name] = '100'
    backup = game / 'SM3_Studio_Backups' / datetime.datetime.now().strftime('Venom_%Y%m%d_%H%M%S_%f')
    contained(backup); backup.mkdir(parents=True)
    (backup / pack.name).write_bytes(original_pack)
    if original_config is not None: (backup / 'mods.config.ini').write_bytes(original_config)
    modified = {}
    if not restore:
        for name in {a.name for a in assets} | (set(OBSOLETE) if direct else set()):
            target = destination / name; contained(target)
            modified[target] = target.read_bytes() if target.is_file() else None
            if modified[target] is not None:
                (backup / 'mod_files').mkdir(exist_ok=True); (backup / 'mod_files' / name).write_bytes(modified[target])
    temporary = pack.with_suffix('.PCPACK.sm3studio.tmp'); contained(temporary)
    if temporary.exists(): raise ValueError('Temporary file already exists: ' + str(temporary))
    try:
        if patched != original_pack:
            temporary.write_bytes(patched); os.replace(temporary, pack)
        if not restore:
            destination.mkdir(parents=True, exist_ok=True)
            for asset in assets: shutil.copy2(asset, destination / asset.name)
            if direct:
                for name in OBSOLETE:
                    old = destination / name
                    if old.is_file(): old.unlink()
            # Check the deployed bytes, not just the conversion directory.
            for asset in assets:
                if digest((destination / asset.name).read_bytes()) != digest(asset.read_bytes()):
                    raise ValueError('Installed resource differs: ' + asset.name)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open('w', encoding='utf8') as stream: config.write(stream)
        if digest(pack.read_bytes()) != digest(patched): raise ValueError('Check of the installed pack failed.')
        installed_config = configparser.ConfigParser(interpolation=None, strict=False)
        installed_config.optionxform = str
        installed_config.read(config_path, encoding='utf-8-sig')
        if not restore and installed_config[section].get(mod_name) != '100':
            raise ValueError('The installed mod is not enabled.')
        if any(installed_config[section].get(name) != '0' for name in disabled if restore or name != mod_name):
            raise ValueError('Another Venom replacement is still enabled.')
    except Exception:
        pack.write_bytes(original_pack)
        for target, data in modified.items():
            if data is not None: target.write_bytes(data)
            elif target.is_file(): target.unlink()
        if original_config is not None: config_path.write_bytes(original_config)
        elif config_path.is_file(): config_path.unlink()
        if temporary.is_file(): temporary.unlink()
        raise
    report = {'mode': 'restore' if restore else ('spider_direct_v1' if direct else 'native'),
              'mod': mod_name, 'backup': str(backup), 'disabled_venom_mods': disabled, 'pack_sha256': digest(patched),
              'installed_assets_sha256': {a.name: digest((destination / a.name).read_bytes()) for a in assets},
              'deployment_verified': True, 'in_game_validation': False}
    (backup / 'installation.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    return report
