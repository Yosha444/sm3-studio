# SPDX-License-Identifier: GPL-3.0-or-later
"""Venom target of SM3 Studio: conversion steps after Blender, checks, and assembly of the mod.

Called by sm3_convertir.py for "--target venom". The mod uses Venom's OWN shader and resources
("native" profile): no Spider-Man constant ends up in the delivered resources. The reference
files (template mesh, skeleton, textures) come from profiles/venom, extracted from the player's
game. The --depuis values are SM3 Studio's step names: chaine (whole chain), verifier (checks
only), assembler (assemble the mod folder).
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import math
import struct

MESH = '0xBF11C1BF.ch_venom000.mesh'
SKEL = '0x26EC9D72.ch_venomskeleton_ch_venom000.skel'
SCOPE = 'STORY_MOVIE_4_PHASE3'
PACK = '_O0114.0x2AF92556.T36.apkf'


def verify(path, profile, fmt, direct=False):
    model = fmt.parse_mesh(str(path))
    # WARNING: the game only reads 16-bit indices (Game.exe 0x8CF1E0, see tools/decoupe_sections.py).
    # The toolkit's exporter writes a section of more than 65,535 vertices with 32-bit indices, and
    # the game silently truncates it -> Venom comes out torn. This mesh does not go through
    # winding_fix (so it is not split into sections): it is refused here, with what to do.
    trop = ['section %d: %d vertices, %d-byte indices' % (s.index, s.vertex_count, s.index_size)
            for s in model.sections if s.vertex_count > 0xFFFF or s.index_size != 2]
    if trop:
        raise RuntimeError('Venom: ' + '; '.join(trop) + '. The game only addresses 65,535 vertices '
                           'per section (16-bit indices): the model would come out torn. Mod NOT '
                           'delivered: bring each section under 65,535 vertices (Decimate in '
                           'Blender).')
    original = fmt.parse_mesh(str(profile / MESH))
    skeleton = fmt.parse_skeleton(str(profile / SKEL))
    # The check names are French (they are stored in venom_validation.json): reference_squelette =
    # same skeleton reference, sections_non_vides = non-empty sections, squelette_70_os = 70-bone
    # skeleton, poids = weights. venom_install.py only requires every value to be True.
    checks = dict(hash=model.filename_hash == original.filename_hash,
                  reference_squelette=model.skeleton_ref_serialized == original.skeleton_ref_serialized,
                  sections_non_vides=bool(model.sections), squelette_70_os=skeleton.bone_count == 70)
    for section in model.sections:
        checks[f'section_{section.index}'] = (
            section.vertex_count > 0 and section.index_count > 0
            and section.material_ref_serialized == 0x28C
            and section.vertex_stride == (52 if direct else 48)
            and all(0 <= b < skeleton.bone_count for b in section.bone_palette or [])
            and len(section.bone_palette or []) <= 48
            and any(d.usage == 10 for d in section.decl)==direct)
        indices = fmt.read_indices(model, section)
        # Strip restart markers may be present; indices_to_faces handles them.
        faces = fmt.indices_to_faces(indices, section.primitive_type, section.vertex_count)
        checks[f'indices_{section.index}'] = bool(faces) and all(
            0 <= i < section.vertex_count for face in faces for i in face)
        decoded=fmt.decode_section_vertices(model,section,position_divisor=512 if direct else 1000,
                                            uv_divisor=1000 if direct else 1024)
        if direct:
            checks[f'uv_atlas_{section.index}']=all(
                math.isfinite(float(x)) and 0 <= x <= 1
                for uv in decoded['texcoords'][0] for x in uv)
        checks[f'poids_{section.index}']=all(
            all(math.isfinite(float(w)) and w>=0 for w in weights)
            and abs(sum(weights)-1)<.002
            and all(0<=int(i)<len(section.bone_palette) for i,w in zip(indices,weights) if w>0)
            for indices,weights in zip(decoded['blend_indices'],decoded['blend_weights']))
        checks[f'positions_{section.index}']=all(math.isfinite(float(x)) for p in decoded['positions'] for x in p)
    if not all(checks.values()):
        raise RuntimeError('Venom check failed: ' + str(checks))
    return checks


def run(args, root, blender, fmt):
    root = Path(root).resolve()
    profile = root / 'profiles/venom'
    out = Path(args.out).resolve() if args.out else root / 'build' / args.nom.lower()
    out.mkdir(parents=True, exist_ok=True)
    if args.depuis not in ('chaine', 'verifier', 'assembler'):
        raise SystemExit('Native Venom: resume from "chaine", "verifier" or "assembler".')
    if args.depuis == 'chaine':
        source = Path(args.src).resolve() if args.src else profile / MESH
        if source.suffix.lower() not in ('.mesh', '.blend', '.glb', '.gltf', '.fbx', '.obj'):
            raise SystemExit('Venom: choose a GLB, glTF, FBX, OBJ, native mesh or prepared Blender project.')
        if not source.is_file(): raise SystemExit('Venom source not found: '+str(source))
        command = [blender, '-b', '--python-exit-code', '1', '--python',
                   str(root / 'tools/venom_blender.py'), '--', '--src', str(source),
                   '--out', str(out / MESH), '--textures', args.textures or str(source.parent),
                   '--drop', args.drop or '', '--materiaux', args.materiaux or '']
        subprocess.run(command, check=True)
        config=json.loads((root/'qualite.json').read_text(encoding='utf-8-sig'))
        config['dilation_pixels']=int(args.dilate)
        custom=json.loads((out/'venom_build.json').read_text(encoding='utf8'))['custom']
        if custom:
            sys.path.insert(0,str(root/'tools'))
            from venom_native_textures import build
            report=build(out/'SM3_Spider_Baked_Atlas_atlas_final.png',out,profile,config)
            print('[venom] Custom textures:',report,flush=True)
            subprocess.run([blender,'-b','--python-exit-code','1','--python',str(root/'tools/venom_preview.py'),
                            '--','--folder',str(out)],check=True)
    manifest=json.loads((out/'venom_build.json').read_text(encoding='utf8'))
    direct=manifest.get('renderer')=='spider_direct_v1'
    if manifest['custom'] and manifest.get('renderer')!='venom_native_argb_indices_v1':
        raise SystemExit('Old, incompatible export: convert again with the native Venom format.')
    checks = verify(out / MESH, profile, fmt,direct=direct)
    print('[venom] Native checks OK:', checks, flush=True)
    (out / 'venom_validation.json').write_text(json.dumps(checks, indent=2), encoding='utf8')
    manifest=json.loads((out/'venom_build.json').read_text(encoding='utf8'))
    assets=[]
    for asset in profile.iterdir():
        if asset.suffix.lower() in ('.tex','.mat','.skel'):
            if direct and (asset.suffix.lower()=='.mat' or '_ppi.' in asset.name or '_ppp.' in asset.name): continue
            replacement=out/asset.name if manifest['custom'] and asset.suffix.lower()=='.tex' else asset
            if not replacement.is_file(): raise RuntimeError('Missing Venom resource: '+str(replacement))
            if replacement.suffix.lower()=='.tex':
                data=replacement.read_bytes(); native=asset.read_bytes()
                if data[12:16]!=native[12:16]: raise RuntimeError('Wrong Venom texture identity (hash).')
                w,h,depth,mips,code=struct.unpack_from('<5I',data,24)
                if not (w>0 and h>0 and depth==1 and 1<=mips<=max(w,h).bit_length()):
                    raise RuntimeError('Invalid texture dimensions.')
                if code in (21,50):
                    expected=68+sum(max(1,w>>i)*max(1,h>>i)*(4 if code==21 else 1) for i in range(mips))
                    if len(data)<expected or (manifest['custom'] and len(data)!=expected):
                        raise RuntimeError('Wrong Venom texture size: '+asset.name)
            assets.append(replacement)
    mods = Path(args.mods).resolve() if args.mods else root / 'mods'
    destination = mods / args.nom / SCOPE / PACK
    destination.mkdir(parents=True, exist_ok=True)
    if direct:
        for name in ('0x8910FC42.ch_venom01_-_default.mat','0xA164D857.ch_venom_ppi.tex','0xA164D85E.ch_venom_ppp.tex'):
            obsolete=destination/name
            if obsolete.is_file(): obsolete.unlink()
    shutil.copy2(out / MESH, destination / MESH)
    for asset in assets:
        shutil.copy2(asset, destination / asset.name)
    print('[venom] Mod assembled:', destination, flush=True)
    if direct:
        (mods / args.nom / 'INSTALLATION_VENOM.txt').write_text(
            'THIS MOD CANNOT BE INSTALLED\n\n'
            'This mesh was built for the "direct" Venom renderer, which uses the Spider-Man shader and\n'
            'needs a modified Venom pack. That pack change crashed the game, so the "direct" renderer is\n'
            'suspended: SM3 Studio refuses to install this mod, and copying this folder into Mods alone\n'
            'gives deformations and wrong colours. Convert the model again (current conversions use the\n'
            'native Venom format, which works with the original pack).\n',encoding='utf8')
        print('[venom] IMPORTANT: this mod uses the suspended "direct" renderer; Studio will refuse to install it. Convert the model again.',flush=True)
    print('[venom] Experimental native profile: a visual check in game is still needed.', flush=True)
