# SPDX-License-Identifier: GPL-3.0-or-later
"""blacksuit_package.py - encode the Black Suit textures, check them, and lay out the mod folder.

Called by blacksuit_finalize.py: package(<build>, <mod archive folder>, format). Also used by
rvb_finalize.py (controle_texture) and checked by sm3/dxtenc_selftest.py.

package() writes, from <build>/atlas_dilate.png:
  * 0x0133FD92.ch_blacksuit_spider.tex, the black suit's colour texture (png2tex.write_tex, in
    the user's format unless texture_qualite.json imposes one for this hash);
  * 0x61DCA273.normswizzle.tex, the normal map, ALWAYS DXT5, if the chain baked
    normale_swizzle.png (looked for in <build> and <build>/source);
then checks the texture (controle_texture), copies the meshes listed in validation.json and the
textures into the mod's archive folder, records their sha256 in <build>/package.json and in
<mod root>/blacksuit_package.json (not in the archive folder: see the end of package()).
The JSON keys are French and kept (fichier = file, octets = bytes, largeur/hauteur = width/height,
ecart_moyen_par_canal = mean difference per channel...).
"""
from pathlib import Path
import sys,json,hashlib,shutil,struct
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from png2tex import write_tex,preparer_image,encodeur as encodeur_png2tex,charger_reglages
from sm3.texfind import decode_level
from sm3.dxtenc import dxt1_encode,dxt5_encode
# Defaults of the first prototype; blacksuit_finalize.py always passes the real folders.
OUT=ROOT/'build/symbiote_blacksuit';SCOPE=Path('CH_BLACKSUIT/_O0108.0xF8ACB40C.T36.apkf')
# Slot 0x0133FD92 is DXT1 128x128 in the vanilla game, and the 71 textures of the vanilla
# CH_BLACKSUIT pack are all DXT1/DXT3/DXT5: none is ARGB8. The format therefore comes from the
# user's choice (--format, default DXT5), no longer from a constant.
#
# A lossy encoding rules out pixel-for-pixel equality: the check becomes a two-stage tolerance
# check, both stages calibrated on measurements, not on estimates.
#  1. ABSOLUTE CEILING: mean difference per channel, and PSNR. Measured for our encoder on the
#     five 4096 atlases already built (photoreal_noir, photoreal_rouge, freefire_gojo, smmovie,
#     smmoviehuman): mean difference per channel between 1.17 and 3.32 out of 255, RGB PSNR
#     between 35.5 and 39.6 dB, alpha restored exactly (the atlases are opaque). Ceiling at 6.0
#     and 30 dB: ~1.8x margin over the worst measured case, enough to catch a broken encoder.
#  2. DRIFT RELATIVE TO THE CONTENT: the PNG atlas is re-encoded right here, and the difference
#     read from the .tex must not exceed by more than 0.5/255 per channel the unavoidable
#     difference of the encoder on this content. This check calibrates itself and does not
#     depend on the texture: swapped channels, wrong file, shifted mip chain or offset make it
#     fail even when the absolute ceiling would still hold (measured on the black atlas: 5.58
#     against 1.70).
#  WARNING: since 2026-10-06 png2tex SMOOTHS mip 0 of DXT colour atlases (CIELAB bilateral
#  filter, texture_qualite.json) before encoding. The reference is therefore no longer the raw
#  PNG but the EXACT mip 0 that png2tex encodes (png2tex.preparer_image), and the "expected"
#  difference comes from the SAME encoder as write_tex (png2tex.encodeur: "hq" or "rapide"
#  according to the settings). Otherwise the check would count the (wanted) smoothing as a loss,
#  or compare two different encoders.
#  WARNING: the settings depend on the HASH (par_texture: the black atlas 0x0133FD92 is NOT
#  smoothed): the reference is prepared with the hash READ from the header of the checked .tex
#  (+0x0C), never with the global settings -- otherwise a raw .tex would be compared with a
#  smoothed reference.
TOLERANCE={'moyen':6.0,'psnr':30.0,'derive':0.5}       # moyen = mean, derive = drift
FOURCC={'DXT1':0x31545844,'DXT5':0x35545844,'ARGB8':21}  # header +0x28 (D3DFORMAT 21 = A8R8G8B8)
FORMAT_LU={v:k for k,v in FOURCC.items()}                # format name from the header value
BLOC={'DXT1':8,'DXT5':16};ENCODEUR={'DXT1':dxt1_encode,'DXT5':dxt5_encode}   # bytes per 4x4 block
# WARNING 2026-10-06: texture_qualite.json can IMPOSE a slot's format (par_texture 0x0133FD92:
# ARGB8 2048, smoothed fabric -- the version validated in game; DXT stained the near-blacks).
# The checked format is therefore the one READ in the .tex header, not --format.

def _ecarts(pixels,reference):
 """Mean absolute difference per channel (R, G, B, A), and the full difference image."""
 ecart=np.abs(pixels.astype(np.int16)-reference.astype(np.int16))
 return {canal:round(float(ecart[:,:,i].mean()),4) for i,canal in enumerate('RGBA')},ecart

def controle_texture(raw,source,fmt):
 """Compare mip 0 of the written .tex with the PNG atlas: exact in ARGB8, within tolerance in DXT.
 The reference is the mip 0 png2tex really encodes (smoothed atlas if smoothing is on; in
 ARGB8, the PNG as it is). Raises AssertionError with the reason; returns the measurements."""
 width,height=struct.unpack_from('<II',raw,24)
 hash_=struct.unpack_from('<I',raw,12)[0]
 fmt=FORMAT_LU.get(struct.unpack_from('<I',raw,40)[0],fmt)
 reference=preparer_image(str(source),'couleur',fmt,hash_=hash_)
 assert reference.shape[:2]==(height,width),'atlas %s != tex %dx%d'%(reference.shape[:2],width,height)
 if fmt=='ARGB8':
  # pixels start after the 68-byte header, stored B,G,R,A
  pixels=np.frombuffer(raw,dtype=np.uint8,offset=68,count=width*height*4).reshape(height,width,4)[:,:,[2,1,0,3]]
  assert np.array_equal(pixels,reference),'ARGB8 roundtrip mismatch'
  return {'exact':True}
 taille=max(1,width//4)*max(1,height//4)*BLOC[fmt]          # size of mip 0 in bytes
 pixels=decode_level(raw[68:68+taille],fmt.lower(),width,height)[:,:,:4]
 moyen,ecart=_ecarts(pixels,reference)
 attendu,_=_ecarts(decode_level(encodeur_png2tex(fmt,hash_=hash_)(reference,width,height),fmt.lower(),width,height)[:,:,:4],reference)
 carre=float((ecart[:,:,:3].astype(np.float64)**2).mean())
 psnr=round(float(10*np.log10(255.0**2/carre)),2) if carre else 999.0
 trop_gros=[c for c in 'RGBA' if moyen[c]>TOLERANCE['moyen']]
 assert not trop_gros,'%s: loss too strong on %s, mean difference %s (ceiling %.1f/255)'%(fmt,','.join(trop_gros),{c:moyen[c] for c in trop_gros},TOLERANCE['moyen'])
 assert psnr>=TOLERANCE['psnr'],'%s: RGB PSNR %.2f dB below the floor of %.1f dB'%(fmt,psnr,TOLERANCE['psnr'])
 derive=[c for c in 'RGBA' if moyen[c]>attendu[c]+TOLERANCE['derive']]
 assert not derive,'%s: the .tex does not contain this atlas -- difference %s where the encoder gives %s'%(fmt,{c:moyen[c] for c in derive},{c:attendu[c] for c in derive})
 return {'exact':False,'tolerance':TOLERANCE,'ecart_moyen_par_canal':moyen,
         'ecart_encodeur_sur_ce_contenu':attendu,'ecart_max_par_canal':{c:int(ecart[:,:,i].max()) for i,c in enumerate('RGBA')},
         'psnr_rgb_db':psnr}

def package(out=OUT,destination=None,fmt='DXT5'):
 OUT=Path(out)
 fmt=(fmt or 'DXT5').upper()
 if fmt not in FOURCC:raise ValueError('Unknown TEX format: '+fmt)
 state=json.loads((OUT/'validation.json').read_text())
 assert all(all(v['checks'].values()) for v in state['variants'].values())
 texture='0x0133FD92.ch_blacksuit_spider.tex'
 write_tex(str(OUT/'atlas_dilate.png'),str(OUT/texture),0x0133FD92,None,fmt,'full',None)
 # header: +12 hash, +24/+28 width/height, +36 mip count (full chain), +40 format
 raw=(OUT/texture).read_bytes();width,height=struct.unpack_from('<II',raw,24);mips=struct.unpack_from('<I',raw,36)[0]
 assert width==height and width in (1024,2048,4096,8192) and mips==width.bit_length()
 lu=struct.unpack_from('<I',raw,40)[0]
 assert lu in FORMAT_LU and struct.unpack_from('<I',raw,12)[0]==0x0133FD92
 assert width in (2048,4096,8192) or FORMAT_LU[lu]=='ARGB8','atlas %dx%d too small'%(width,height)
 if FORMAT_LU[lu]!=fmt:
  print('FORMAT %s imposed by texture_qualite.json (requested: %s)'%(FORMAT_LU[lu],fmt),flush=True)
  fmt=FORMAT_LU[lu]
 controle=controle_texture(raw,OUT/'atlas_dilate.png',fmt)
 state['texture']=dict(fichier=texture,format=fmt,octets=len(raw),largeur=width,hauteur=height,mips=mips,**controle)
 state['texture_roundtrip_exact']=controle['exact']
 files=[x['file'] for x in state['variants'].values()]+[texture]
 # WARNING: ALWAYS DXT5, even if --format asks for something else: the shader reads X in the
 # ALPHA (mad r3.xy, c47.x, r2.wyzw, c47.y). In DXT1 alpha is 255 everywhere, nx = +1, and the
 # normal becomes the pure tangent. Slot 0x61DCA273 (_normswizzle) is shared by every material
 # of the suit; the game puts a flat 32x32 placeholder in it, hence the missing relief.
 # WARNING: the chain writes into OUT/source (that is the --out blacksuit_pipeline gives it),
 # not into OUT. Look in BOTH places, otherwise the normal map is baked and then forgotten.
 _nor_png=next((c for c in (OUT/'normale_swizzle.png',OUT/'source'/'normale_swizzle.png')
                if c.is_file()),None)
 if _nor_png is not None:
  normale='0x61DCA273.normswizzle.tex'
  # The BLACK suit's fabric is flattened (noir_normale_plaquer, default [9, 14]): the relief of
  # the scales flickered under the sheen; the web keeps its own. Slot 0x61DCA273 is shared with
  # the red suit, hence a setting passed HERE and not through par_texture.
  _R=charger_reglages();_R['normale_plaquer']=list(_R.get('noir_normale_plaquer') or [0.0,0.0])
  write_tex(str(_nor_png),str(OUT/normale),0x61DCA273,None,'DXT5','full',None,reglages=_R)
  brut=(OUT/normale).read_bytes()
  assert struct.unpack_from('<I',brut,40)[0]==FOURCC['DXT5'],'the normal map must be DXT5'
  assert struct.unpack_from('<I',brut,12)[0]==0x61DCA273
  state['normale']=dict(fichier=normale,format='DXT5',octets=len(brut))
  files=files+[normale]
  print('NORMAL MAP',normale,len(brut),'bytes',flush=True)
 else:
  print('NORMAL MAP missing: the suit keeps the game\'s flat look.',flush=True)
 dest=Path(destination) if destination else ROOT/'mods/Symbiote_BlackSuit'/SCOPE
 dest.mkdir(parents=True,exist_ok=True)
 for name in files: shutil.copy2(OUT/name,dest/name)
 state['files']={name:hashlib.sha256((dest/name).read_bytes()).hexdigest() for name in files}
 state['scope']=str(SCOPE);state['in_game_verified']=False
 (OUT/'package.json').write_text(json.dumps(state,indent=2));print('PACKAGE',dest,flush=True)
 # WARNING: NOT in the .apkf folder: xeSM3 scans RESOURCES there and only expects
 # "0xHASH.name.ext" files. A package.json dropped there is an intruder in the scan.
 # Every working mod (CJ, _RvB_ActiveCostumes) puts its manifest at the mod's ROOT.
 # dest = mods/<name>/<PACK>/<APKF>, so the root is two levels up.
 (dest.parent.parent/'blacksuit_package.json').write_text(json.dumps(state,indent=2))
if __name__=='__main__':package(fmt=sys.argv[1] if len(sys.argv)>1 else 'DXT5')
