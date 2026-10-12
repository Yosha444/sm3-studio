# SPDX-License-Identifier: GPL-3.0-or-later
"""cj_package.py - CJ prototype: encode the atlas and copy the mod files (see cj_build.py).

Status: NOT CALLED by SM3 Studio; replaced by blacksuit_package.py. Kept for history.

    python cj_package.py

Reads build/cj_blacksuit (validation.json from cj_build.py, atlas_dilate.png); writes the
black suit texture 0x0133FD92.ch_blacksuit_spider.tex in ARGB8 4096 x 4096 (13 mips), checks
that it decodes back to the PNG exactly, copies the meshes and the texture into
mods/Symbiote_BlackSuit/CH_BLACKSUIT/<archive>/ and records their sha256 in package.json.
Texture header fields read here: +12 hash, +24/+28 width/height, +36 mip count, +40 format
(21 = A8R8G8B8); pixels from +68, in B,G,R,A order.
"""

from pathlib import Path
import sys,json,hashlib,shutil,struct
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from png2tex import write_tex
OUT=ROOT/'build/cj_blacksuit';SCOPE=Path('CH_BLACKSUIT/_O0108.0xF8ACB40C.T36.apkf')
def package():
 state=json.loads((OUT/'validation.json').read_text())
 assert all(all(v['checks'].values()) for v in state['variants'].values())
 texture='0x0133FD92.ch_blacksuit_spider.tex'
 write_tex(str(OUT/'atlas_dilate.png'),str(OUT/texture),0x0133FD92,None,'ARGB8','full',None)
 raw=(OUT/texture).read_bytes();width,height=struct.unpack_from('<II',raw,24)
 assert (width,height)==(4096,4096) and struct.unpack_from('<I',raw,36)[0]==13
 assert struct.unpack_from('<I',raw,40)[0]==21 and struct.unpack_from('<I',raw,12)[0]==0x0133FD92
 pixels=np.frombuffer(raw,dtype=np.uint8,offset=68,count=width*height*4).reshape(height,width,4)[:,:,[2,1,0,3]]
 assert np.array_equal(pixels,np.array(Image.open(OUT/'atlas_dilate.png').convert('RGBA'))),'ARGB8 roundtrip mismatch'
 state['texture_roundtrip_exact']=True
 files=[x['file'] for x in state['variants'].values()]+[texture]
 dest=ROOT/'mods/Symbiote_BlackSuit'/SCOPE;dest.mkdir(parents=True,exist_ok=True)
 for name in files: shutil.copy2(OUT/name,dest/name)
 state['files']={name:hashlib.sha256((dest/name).read_bytes()).hexdigest() for name in files}
 state['scope']=str(SCOPE);state['in_game_verified']=False
 (OUT/'package.json').write_text(json.dumps(state,indent=2));print('PACKAGE',dest,flush=True)
if __name__=='__main__':package()

