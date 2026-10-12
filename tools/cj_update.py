# SPDX-License-Identifier: GPL-3.0-or-later
"""cj_update.py - update the installed CJ black suit prototype, with backup and rollback.

Status: NOT CALLED by SM3 Studio. Part of the CJ prototype (cj_build.py, cj_package.py), whose
method became the Black Suit target (blacksuit_runner.py). Kept for history. Game folder and
project root come from blacksuit_install.py (SM3_GAME or the usual search).

    python cj_update.py

Same procedure as blacksuit_update.py, for build/cj_blacksuit: everything is checked first
(validation.json: 2,406 source triangles, all checks true, at most 48 bones per variant; the
installed files and the pack against installation.json; the mod enabled at 100), then only the
changed files are copied after a backup, and restored on any error.
"""
from pathlib import Path
import json, datetime, shutil, subprocess, configparser
from blacksuit_install import ROOT, GAME, digest

def update():
    tasks=subprocess.check_output(['tasklist','/FI','IMAGENAME eq Game.exe','/FO','CSV','/NH'],text=True)
    if any(line.lower().startswith('"game.exe",') for line in tasks.splitlines()):
        raise RuntimeError('Close the game before installing.')
    out=ROOT/'build/cj_blacksuit'
    state=json.loads((out/'package.json').read_text())
    old=json.loads((out/'installation.json').read_text())
    validation=json.loads((out/'validation.json').read_text())
    assert validation['source_triangles']==2406
    assert all(all(v['checks'].values()) and v['bones']<=48 for v in validation['variants'].values())
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

