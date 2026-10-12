# SPDX-License-Identifier: GPL-3.0-or-later
"""Native Venom palette, with lossless ARGB8 index storage and native dimensions.

Venom's own shader does not read a colour texture: it reads a palette-INDEX texture (ch_venom_ppi,
the index is in the red channel) and a 2 x 256 palette (ch_venom_ppp). So the baked atlas is
reduced to 256 colours, the palette is written in place of Venom's, and every pixel stores its
palette index. Dimensions and mip count are the ones of the player's original textures
(profiles/venom).

Loader acceptance of this PHTP texture replacement still needs an in-game test.
Never average numeric palette indices when building mipmaps.
"""
import json
import struct
from pathlib import Path
import numpy as np
from PIL import Image
from sm3.texfind import decode_level
import png2tex

PPI='0xA164D857.ch_venom_ppi.tex'
PPP='0xA164D85E.ch_venom_ppp.tex'
NOR='0xA164CFBD.ch_venom_nor.tex'
AO='0xBF12903E.ch_venom_ao.tex'

def build(atlas,out,profile,config):
    out=Path(out); profile=Path(profile); out.mkdir(parents=True,exist_ok=True)
    stock=(profile/PPI).read_bytes()
    w,h,depth,levels,_=struct.unpack_from('<5I',stock,24)
    with Image.open(atlas) as image:
        source=image.convert('RGB').resize((w,h),Image.Resampling.LANCZOS)
    pixels=int(config.get('dilation_pixels',12))
    if not 0 <= pixels <= 256: raise ValueError('Invalid dilation')
    from dilater_atlas import couverture,dilate,fmt
    mesh=fmt.parse_mesh(str(out/'0xBF11C1BF.ch_venom000.mesh'))
    coverage=np.zeros((h,w),dtype=bool)
    for section in mesh.sections:
        decoded=fmt.decode_section_vertices(mesh,section,uv_divisor=1024)
        uv=np.array(decoded['texcoords'][0],dtype=float)
        uv[:,1]=1-uv[:,1]
        faces=np.array(fmt.indices_to_faces(fmt.read_indices(mesh,section),section.primitive_type,section.vertex_count))
        coverage |= couverture(uv,faces,(w,h))
    before=np.asarray(source)
    expanded,expanded_mask=dilate(before,coverage,pixels)
    assert np.array_equal(expanded[coverage],before[coverage]),'Dilation modified the UV islands'
    source=Image.fromarray(expanded)
    source.save(out/'atlas_venom_dilate.png')
    indexed=source.quantize(colors=256,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)
    colors=np.array(indexed.getpalette(),dtype=np.uint8).reshape(-1,3)
    colors=np.pad(colors,((0,256-len(colors)),(0,0)),mode='edge')
    reference=(profile/PPP).read_bytes()
    pw,ph=struct.unpack_from('<2I',reference,24)
    if (pw,ph)!=(2,256): raise ValueError('Unexpected native Venom palette')
    native=decode_level(reference[68:],'a8r8g8b8',pw,ph)
    palette=native.copy()
    palette[:,0,:3]=colors
    # Diffuse alpha also feeds final shader opacity; stock Venom is opaque.
    # It must never be zeroed as a substitute for removing gloss.
    if not np.all(native[:,0,3]==255):
        raise ValueError('Native palette with transparency: profile to be examined')
    palette[:,0,3]=255
    palette[:,1]=0
    # Keep the original 2 x 256 palette header and single level.
    (out/PPP).write_bytes(reference[:68]+palette[:,:,[2,1,0,3]].tobytes())
    written=decode_level((out/PPP).read_bytes()[68:],'a8r8g8b8',pw,ph)
    if not np.all(written[:,0,3]==255):
        raise RuntimeError('Alpha of the exported palette is not opaque')
    header=bytearray(stock[:68]); struct.pack_into('<I',header,40,21)
    header[44:68]=bytes(24)
    current=source; sizes=[]; errors=[]
    with (out/PPI).open('wb') as stream:
        stream.write(header)
        for level in range(levels):
            quant=current.quantize(palette=indexed,dither=Image.Dither.NONE)
            indices=np.asarray(quant,dtype=np.uint8)
            rgba=np.repeat(indices[:,:,None],4,axis=2); rgba[:,:,3]=255
            stream.write(rgba.tobytes()) # RGB identical: byte order immaterial.
            reconstructed=colors[indices]
            errors.append(float(np.abs(reconstructed.astype(np.int16)-np.asarray(current).astype(np.int16)).mean()))
            sizes.append(current.size)
            if level==0: Image.fromarray(reconstructed).save(out/'Venom_couleurs.png')
            current=current.resize((max(1,current.width//2),max(1,current.height//2)),Image.Resampling.BOX)
    assert (out/PPI).stat().st_size==68+sum(x*y*4 for x,y in sizes)
    # Other resources retain native dimensions too; avoid stale parent descriptors.
    for name,color in ((NOR,(128,128,128,128)),(AO,(255,255,255,255))):
        raw=(profile/name).read_bytes(); tw,th,_,tm,_=struct.unpack_from('<5I',raw,24)
        temp=out/(name+'.png'); Image.new('RGBA',(tw,th),color).save(temp)
        png2tex.write_tex(str(temp),str(out/name),struct.unpack_from('<I',raw,12)[0],str(profile/name),'ARGB8',tm)
        temp.unlink()
    report={'renderer':'venom_native_argb_indices_v1','requires_pack_patch':False,
            'index_format':'ARGB8 grayscale; red channel contains palette index',
            'dimensions':[w,h],'mip_count':levels,'palette_dimensions':[pw,ph],
            'dilation_pixels':pixels,'coverage_before':float(coverage.mean()),
            'coverage_after':float(expanded_mask.mean()),'island_pixels_preserved':True,
            'vertex_color':'not present in native 48-byte layout',
            'mip_errors_rgb':errors,'mips_quantized_from_colors':True,
            'material_controls':'opaque diffuse alpha 255; auxiliary lighting controls zero',
            'palette_opacity_verified':True,
            'cel_shading_applied':False,
            'in_game_validation':False,
            'limitation':'256 colors, neutral normal map; loader acceptance remains unverified'}
    (out/'venom_textures.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    return report
