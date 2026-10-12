# SPDX-License-Identifier: GPL-3.0-or-later
"""blacksuit_update.py - update an installed "Symbiote_BlackSuit" prototype mod, with backup and rollback.

Status: NOT CALLED by SM3 Studio (prototype tooling, replaced by blacksuit_deploy.py). Kept for
history. Game folder and project root come from blacksuit_install.py (SM3_GAME or the usual
search).

    python blacksuit_update.py

Checks everything first (the shader-palette audit of build/symbiote_blacksuit, the installed
files and the pack against the previous receipt installation.json, the mod still enabled at
100), then copies only the changed files, after backing them up into
<game>/SM3_Studio_Backups/BlackSuit_32bones_<date>; restores them on any error. The new receipt
records shader_palette_limit 32: going by that and the backup name, it dates from a 32-bone
palette, before the 48-bone limit was established (see blacksuit_build.py).
"""
from pathlib import Path
import json, datetime, shutil, subprocess, configparser
from blacksuit_install import ROOT, GAME, digest

def update():
    tasks=subprocess.check_output(['tasklist','/FI','IMAGENAME eq Game.exe','/FO','CSV','/NH'],text=True)
    if any(line.lower().startswith('"game.exe",') for line in tasks.splitlines()):
        raise RuntimeError('Close the game before installing.')
    out=ROOT/'build/symbiote_blacksuit'
    state=json.loads((out/'package.json').read_text())
    old=json.loads((out/'installation.json').read_text())
    audit=json.loads((out/'shader_palette_audit.json').read_text())
    assert all(v['after']['vertices_reading_non_bone_shader_constants']==0 for v in audit.values())
    source=ROOT/'mods/Symbiote_BlackSuit'/state['scope']
    dest=GAME/'Mods/Symbiote_BlackSuit'/state['scope']
    assert dest.resolve().is_relative_to((GAME/'Mods/Symbiote_BlackSuit').resolve())
    config=GAME/'Mods/mods.config.ini'
    config_bytes=config.read_bytes()
    cfg=configparser.ConfigParser();cfg.read_string(config_bytes.decode('utf-8-sig'))
    assert cfg['EnabledMods']['Symbiote_BlackSuit']=='100'
    pack=GAME/'packs/CH_BLACKSUIT.PCPACK'
    assert digest(pack)==old['pack_sha256_unchanged']
    for name,h in state['files'].items():
        assert digest(source/name)==h
        assert digest(dest/name)==old['files'][name], 'Installed file changed: '+name
    changed=[name for name,h in state['files'].items() if h!=old['files'][name]]
    backup=GAME/'SM3_Studio_Backups'/datetime.datetime.now().strftime('BlackSuit_32bones_%Y%m%d_%H%M%S')
    backup.mkdir(parents=True)
    (backup/'installation.json').write_text(json.dumps(old,indent=2))
    for name in changed: shutil.copy2(dest/name,backup/name)
    try:
        for name in changed:
            shutil.copy2(source/name,dest/name)
            assert digest(dest/name)==state['files'][name]
        assert digest(pack)==old['pack_sha256_unchanged']
        assert config.read_bytes()==config_bytes
    except Exception:
        for name in changed: shutil.copy2(backup/name,dest/name)
        raise
    receipt={**old,'backup':str(backup),'files':state['files'],'updated_files':changed,'shader_palette_limit':32,'in_game_verified':False}
    (out/'installation.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt,indent=2))

if __name__=='__main__': update()
