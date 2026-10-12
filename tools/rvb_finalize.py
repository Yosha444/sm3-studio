# SPDX-License-Identifier: GPL-3.0-or-later
"""rvb_finalize.py - last step of the Web of Shadows ("RvB") mode, outside Blender.

    <python with numpy + Pillow> rvb_finalize.py <build>/rvb_job.json

Started by rvb_runner.py after the Blender chain. In order:
  1. rvb_native.build(): the meshes rebuilt from the Web of Shadows profile -> <build>/corrected;
  2. winding_fix.py on each of them (face orientation and normals);
  3. dilater_atlas.py: the chain's atlas with its UV gutters filled -> atlas_dilate.png;
  4. the atlas encoded as the target's texture (red suit 0x8E661B33 or black suit 0x0133FD92)
     in the format chosen by the user, checked by blacksuit_package.controle_texture();
  5. files copied under every scope of the target (red suit: CH_SPIDERMAN, MARYJANE_SCARERIDE,
     and STORY_MOVIE_3 for the texture only; black suit: CH_BLACKSUIT), each copy checked by
     sha256; manifest <mod>/rvb_package.json, plus package.json in the black suit archive folder
     (the one blacksuit_deploy.py reads).
"""
from pathlib import Path
import sys,json,subprocess,hashlib,shutil
job=json.loads(Path(sys.argv[1]).read_text());root=Path(job['root']);out=Path(job['out'])
sys.path[:0]=[str(root),str(root/'tools')]
from rvb_native import build
from png2tex import write_tex
build(out,job['model'],job['target'])
for mesh in (out/'corrected').glob('*.mesh'):
    subprocess.run([sys.executable,str(root/'tools/winding_fix.py'),str(mesh)],check=True)
subprocess.run([sys.executable,str(root/'dilater_atlas.py'),'--atlas',str(out/'source/SM3_Spider_Baked_Atlas_atlas_final.png'),'--mesh',str(out/'source/0xAC92103D.ch_spiderman000.mesh'),'--out',str(out/'atlas_dilate.png'),'--pixels',str(job['dilate'])],check=True)
black=job['target']=='blacksuit'
tex='0x0133FD92.ch_blacksuit_spider.tex' if black else '0x8E661B33.ch_spiderman_spider.tex'
# Same fix as tools/blacksuit_package.py: the format comes from the user's choice.
# The 71 textures of the vanilla CH_BLACKSUIT pack are DXT1/DXT3/DXT5, none is ARGB8,
# and a 4096 atlas weighs 89,478,552 bytes in ARGB8 against 22,369,716 bytes in DXT5.
fmt=(job.get('format') or 'DXT5').upper()
write_tex(str(out/'atlas_dilate.png'),str(out/'corrected'/tex),int(tex[2:10],16),None,fmt,'full',None)
from blacksuit_package import controle_texture
controle=controle_texture((out/'corrected'/tex).read_bytes(),out/'atlas_dilate.png',fmt)
scopes=['CH_BLACKSUIT/_O0108.0xF8ACB40C.T36.apkf'] if black else ['CH_SPIDERMAN/_O0069.0xCFB154CD.T36.apkf','MARYJANE_SCARERIDE/_O0082.0x4F920A48.T36.apkf','STORY_MOVIE_3/_O0121.0x03294B12.T36.apkf']
destination=Path(job['destination']);files={}
for scope in scopes:
    dest=destination/scope;dest.mkdir(parents=True,exist_ok=True)
    for file in (out/'corrected').iterdir():
        if file.suffix not in ('.mesh','.tex') or (scope.startswith('STORY_MOVIE_3') and file.suffix=='.mesh'):continue
        shutil.copy2(file,dest/file.name)
        digest=hashlib.sha256(file.read_bytes()).hexdigest()
        assert hashlib.sha256((dest/file.name).read_bytes()).hexdigest()==digest
        files[str(Path(scope)/file.name)]=digest
manifest=dict(files=files,source=job['source'],model=job['model'],target=job['target'],in_game_verified=False,native_rvb=True,texture=dict(fichier=tex,format=fmt,octets=(out/'corrected'/tex).stat().st_size,**controle))
(destination/'rvb_package.json').write_text(json.dumps(manifest,indent=2))
if black:
    flat={Path(name).name:digest for name,digest in files.items()}
    (destination/scopes[0]/'package.json').write_text(json.dumps(dict(files=flat,native_rvb=True,in_game_verified=False),indent=2))
print('RvB PACKAGE VERIFIED',destination,flush=True)
