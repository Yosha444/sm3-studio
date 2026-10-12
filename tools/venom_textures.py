# SPDX-License-Identifier: GPL-3.0-or-later
"""Venom full-colour atlas using the working Spider-Man texture encoder.

Belongs to the SUSPENDED "direct" Venom renderer (renderer 'spider_direct_v1'): it writes the
colour atlas into the AO texture slot, which only the modified Venom pack would read as albedo.
That pack change crashed the game (see support_venom_atlas/README.md), so nothing calls this
module any more; current conversions use venom_native_textures.py. Kept for reference.
"""
import json
from pathlib import Path
import numpy as np
from PIL import Image
import png2tex
AO='0xBF12903E.ch_venom_ao.tex'
NOR='0xA164CFBD.ch_venom_nor.tex'

def build(atlas,out,profile,config):
    out=Path(out); profile=Path(profile)
    format=config.get('format','ARGB8')
    # Pack patch rebinds the AO resource identity to the direct diffuse slot.
    png2tex.write_tex(str(atlas),str(out/AO),0xBF12903E,str(profile/AO),format,'full',None)
    with Image.open(atlas) as im:
        source=im.convert('RGBA'); w,h=source.size
    raw=(out/AO).read_bytes()
    from sm3.texfind import decode_level
    decoded=decode_level(raw[68:],{'ARGB8':'a8r8g8b8','DXT1':'dxt1','DXT5':'dxt5'}[format],w,h)
    Image.fromarray(decoded).save(out/'Venom_couleurs.png')
    error=float(np.abs(np.asarray(source).astype(np.int16)-decoded.astype(np.int16)).mean())
    if format=='ARGB8' and error!=0: raise RuntimeError('ARGB8 atlas differs from the source.')
    normal=out/'venom_normal_neutre.png'
    Image.new('RGBA',(4,4),(128,128,128,128)).save(normal)
    png2tex.write_tex(str(normal),str(out/NOR),0xA164CFBD,str(profile/NOR),'ARGB8','full',None)
    normal.unlink()
    report={'renderer':'spider_direct_v1','width':w,'height':h,'albedo_format':format,
            'palette_quantization':False,'mean_absolute_rgba_error':error,
            'requires_pack_patch':True,'cel_shading':config.get('cel_shading',{}),
            'normal_map':'neutral; source normal detail is not baked'}
    (out/'venom_textures.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    return report
