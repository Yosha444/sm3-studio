# SPDX-License-Identifier: GPL-3.0-or-later
"""blacksuit_deploy.py - install a converted Black Suit mod into the game, with backup and rollback.

Called by the window's install button when the target is "Costume noir" (Black Suit):
sm3_gui_hq imports install() from here and shows the returned backup folder.

What install(root, game, name) does:
  * refuses an invalid mod name, or a running game (Game.exe would keep old files loaded);
  * reads <root>/mods/<name>/CH_BLACKSUIT/<archive>/package.json, which must list exactly 3
    files with their sha256, and checks every file against it;
  * backs up <game>/Mods/mods.config.ini, the files it will overwrite, and any red-suit files
    a previous mod of the same name left under CH_SPIDERMAN / MARYJANE_SCARERIDE /
    STORY_MOVIE_3, into <game>/SM3_Studio_Backups/BlackSuit_tool_<date>;
  * copies the files and checks their sha256 after the copy, removes those stale red-suit
    files, sets to 0 every other mod of mods.config.ini that ships the same black suit files,
    and sets this one to 100 ([EnabledMods], read by xeSM3);
  * on ANY error, puts mods.config.ini and every touched file back as they were.
The game's packs are never written.
Returns {'backup': folder, 'destination': folder}.

Known mismatch, kept as it is (behaviour unchanged on purpose, noted 2026-10-12, not tested in
the window): blacksuit_package.py now writes package.json into the BUILD folder and
blacksuit_package.json at the mod's root, not into the archive folder read here, and a mod with
a baked normal map has 4 files, not 3. Only mods packaged by rvb_finalize.py (Web of Shadows
models) still have package.json in the archive folder.
"""
from pathlib import Path
import json,hashlib,shutil,configparser,datetime
from venom_install import game_running

def install(root,game,name):
    root=Path(root);game=Path(game)
    if not name or Path(name).name!=name or name in ('.','..'):raise ValueError('Invalid mod name')
    if game_running():raise RuntimeError('Close the game before installing.')
    # The CH_BLACKSUIT archive folder, named as xeSM3 names it: _O<index>.<hash>.T<type>.apkf
    scope=Path('CH_BLACKSUIT/_O0108.0xF8ACB40C.T36.apkf')
    source=root/'mods'/name/scope; dest=game/'Mods'/name/scope
    manifest=json.loads((source/'package.json').read_text())
    files=manifest['files']
    if len(files)!=3 or any(Path(n).name!=n for n in files):raise ValueError('Invalid manifest')
    for n,h in files.items():
        if hashlib.sha256((source/n).read_bytes()).hexdigest()!=h:raise ValueError('Unverified file: '+n)
    config=game/'Mods/mods.config.ini';original=config.read_bytes()
    # optionxform=str keeps the case of mod names (configparser lower-cases keys by default)
    cfg=configparser.ConfigParser(interpolation=None);cfg.optionxform=str;cfg.read_string(original.decode('utf-8-sig'))
    backup=game/'SM3_Studio_Backups'/datetime.datetime.now().strftime('BlackSuit_tool_%Y%m%d_%H%M%S_%f');backup.mkdir(parents=True)
    (backup/'mods.config.ini').write_bytes(original)
    existing={n:(dest/n).exists() for n in files}
    for n,exists in existing.items():
        if exists:shutil.copy2(dest/n,backup/n)
    # A reused mod name must not retain exports for the previous target.
    stale=[]
    modroot=game/'Mods'/name
    for scope_name in ('CH_SPIDERMAN','MARYJANE_SCARERIDE','STORY_MOVIE_3'):
        for filename in ('0xAC92103D.ch_spiderman000.mesh','0xAC92103E.ch_spiderman001.mesh','0x8E661B33.ch_spiderman_spider.tex'):
            for path in (modroot/scope_name).glob('*/'+filename):
                saved=backup/'previous_target'/path.relative_to(modroot)
                saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,saved)
                stale.append((path,saved))
    try:
        dest.mkdir(parents=True,exist_ok=True)
        for n,h in files.items():
            shutil.copy2(source/n,dest/n)
            assert hashlib.sha256((dest/n).read_bytes()).hexdigest()==h
        for path,saved in stale:path.unlink()
        # Only one mod may replace the black suit: disable the others that ship these files.
        for other,value in list(cfg['EnabledMods'].items()):
            if other!=name and any((game/'Mods'/other/scope/n).is_file() for n in files):cfg['EnabledMods'][other]='0'
        cfg['EnabledMods'][name]='100'
        with config.open('w',encoding='utf8') as f:cfg.write(f)
    except Exception:
        # roll back: configuration, removed red-suit files, overwritten or new black suit files
        config.write_bytes(original)
        for path,saved in stale:shutil.copy2(saved,path)
        for n,exists in existing.items():
            if exists:shutil.copy2(backup/n,dest/n)
            elif (dest/n).exists():(dest/n).unlink()
        raise
    return {'backup':str(backup),'destination':str(dest)}
