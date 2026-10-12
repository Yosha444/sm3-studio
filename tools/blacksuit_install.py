# SPDX-License-Identifier: GPL-3.0-or-later
"""blacksuit_install.py - first transactional installer of the "Symbiote_BlackSuit" prototype mod.

Status: NOT CALLED by SM3 Studio (dead since blacksuit_deploy.py replaced it; only the equally
unused blacksuit_update.py and cj_update.py import it). Kept for history.

    python blacksuit_install.py

What it did: copy the files of mods/Symbiote_BlackSuit (listed with their sha256 in
build/symbiote_blacksuit/package.json) as loose files into <game>/Mods, check that the black
suit skeletons it was built against are byte-for-byte inside the installed CH_BLACKSUIT pack,
back up mods.config.ini into <game>/SM3_Studio_Backups, disable the other mods that replace the
same files, enable this one, check the copies and that the pack was not touched, and undo
everything on error. It never overwrites an existing mod folder. Writes a receipt to
build/symbiote_blacksuit/installation.json. The original game packs stay untouched.

Paths (configured on 2026-10-12; they used to point into the author's Downloads folder):
  * game folder: the SM3_GAME environment variable, else the search SM3 Studio uses everywhere
    (sm3_studio.json "jeu", the registry, usual places: see tools/extraire_donnees_jeu.py);
  * black suit skeletons: <SM3 Studio>/profiles/blacksuit/SKEL, extracted from the player's
    own pack by tools/extraire_donnees_jeu.py.
"""
from pathlib import Path
import configparser,datetime,hashlib,json,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
def _game_folder():
    """Game folder: SM3_GAME, else the same search as tools/extraire_donnees_jeu.py."""
    import os,sys
    if os.environ.get('SM3_GAME'):return Path(os.environ['SM3_GAME'])
    sys.path.insert(0,str(ROOT/'tools'))
    from extraire_donnees_jeu import find_game_folder
    folder,_,tried=find_game_folder(ROOT)
    if folder is None:raise SystemExit('Spider-Man 3 was not found (tried: %s). Set the SM3_GAME environment variable to the game folder.'%'; '.join(tried))
    return folder
GAME=_game_folder()
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def install():
 tasks=subprocess.run(['tasklist','/FI','IMAGENAME eq Game.exe','/FO','CSV','/NH'],capture_output=True,text=True,check=True)
 if any(s.lower().startswith('"game.exe",') for s in tasks.stdout.splitlines()):raise RuntimeError('Close the game before installing.')
 out=ROOT/'build/symbiote_blacksuit';state=json.loads((out/'package.json').read_text())
 scope=Path(state['scope']);source=ROOT/'mods/Symbiote_BlackSuit'/scope;dest=GAME/'Mods/Symbiote_BlackSuit'/scope
 if not dest.resolve().is_relative_to(GAME.resolve()):raise ValueError('Invalid destination')
 if dest.exists():raise RuntimeError('Mod already present: nothing is overwritten.')
 pack=GAME/'packs/CH_BLACKSUIT.PCPACK';packhash=digest(pack)
 # The black suit skeletons (MESH/ and SKEL/ of the CH_BLACKSUIT archive), extracted from the
 # player's pack by tools/extraire_donnees_jeu.py.
 extracted=ROOT/'profiles/blacksuit'
 if not any((extracted/'SKEL').glob('*.skel')):raise RuntimeError('No black suit skeleton in %s: run tools/extraire_donnees_jeu.py first.'%(extracted/'SKEL'))
 data=pack.read_bytes()
 for p in (extracted/'SKEL').glob('*.skel'):
  if p.read_bytes() not in data:raise RuntimeError('Skeleton missing from the installed pack: '+p.name)
 for name,h in state['files'].items():
  if digest(source/name)!=h:raise RuntimeError('Unvalidated source: '+name)
 configpath=GAME/'Mods/mods.config.ini';original=configpath.read_bytes()
 config=configparser.ConfigParser(interpolation=None,strict=False);config.optionxform=str;config.read_string(original.decode('utf-8-sig'))
 backup=GAME/'SM3_Studio_Backups'/datetime.datetime.now().strftime('BlackSuit_%Y%m%d_%H%M%S');backup.mkdir(parents=True)
 (backup/'mods.config.ini').write_bytes(original)
 disabled=[]
 for name,value in config['EnabledMods'].items():
  folder=GAME/'Mods'/name/scope
  if value.strip()=='100' and folder.is_dir() and any((folder/f).exists() for f in state['files']):
   config['EnabledMods'][name]='0';disabled.append(name)
 config['EnabledMods']['Symbiote_BlackSuit']='100'
 try:
  dest.mkdir(parents=True)
  for name,h in state['files'].items():
   shutil.copy2(source/name,dest/name)
   if digest(dest/name)!=h:raise RuntimeError('Invalid copy')
  with configpath.open('w',encoding='utf8') as f:config.write(f)
  if digest(pack)!=packhash:raise RuntimeError('Pack modified')
 except Exception:
  configpath.write_bytes(original)
  for name in state['files']:
   p=dest/name
   if p.exists():p.unlink()
  raise
 receipt={'destination':str(dest),'backup':str(backup),'files':state['files'],'disabled':disabled,'pack_sha256_unchanged':packhash,'in_game_verified':False}
 (out/'installation.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt,indent=2))
if __name__=='__main__':install()
