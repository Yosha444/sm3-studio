# SPDX-License-Identifier: GPL-3.0-or-later
"""cj_build.py - CJ prototype: move a converted model onto the black suit's native "canvas" section.

Status: NOT CALLED by SM3 Studio. This is the prototype, validated in game with the CJ model,
that became the Black Suit target: blacksuit_build.py is the same code made reusable (folders as
arguments). Kept for history.

    python cj_build.py

Reads build/cj_black_source/etape_poids.mesh (a red-suit 000 mesh skinned on the red suit's
skeleton) and the black suit's own 000/001 meshes and skeletons; writes
build/cj_blacksuit/<black suit mesh names> and validation.json. Every vertex is moved by the
blend of (black suit bind pose x inverse red suit bind pose) of its bones, so the model keeps
its shape on the black suit skeleton, then written into section 3 of the black suit template.

Black suit files: <SM3 Studio>/profiles/blacksuit/MESH and SKEL, extracted from the player's
pack by tools/extraire_donnees_jeu.py (configured on 2026-10-12; it used to be an extraction in
the author's Downloads folder, with the same MESH/ and SKEL/ layout).
"""
from pathlib import Path
import sys,json,hashlib,copy,struct
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'correctifs_blender')]
from sm3_sans_blender import fmt
import blacksuit_mesh_writer as mw  # correctifs_blender/: modified copy of TSGAMING264's writer
SOURCE=ROOT/'build/cj_black_source'
TARGET=ROOT/'profiles/blacksuit'      # MESH/ and SKEL/ of CH_BLACKSUIT (tools/extraire_donnees_jeu.py)
OUT=ROOT/'build/cj_blacksuit'
def bind(b):
 # bone -> model matrix, from the stored inverse bind matrix (junk column 3 cleared first)
 m=np.array(b.inverse_values).reshape(4,4).copy();m[:3,3]=0;m[3,3]=1
 return np.linalg.inv(m).T
def build():
 if not any((TARGET/'SKEL').glob('*.skel')):raise SystemExit('No black suit skeleton in %s: run tools/extraire_donnees_jeu.py first.'%(TARGET/'SKEL'))
 OUT.mkdir(exist_ok=True)
 src=fmt.parse_mesh(str(SOURCE/'etape_poids.mesh'))
 assert len(src.sections)==1
 a=fmt.parse_skeleton(str(next((ROOT/'vanilla/CH_SPIDERMAN/_O0069.0xCFB154CD.T36.apkf').glob('*000.skel'))))
 section=src.sections[0];data=fmt.decode_section_vertices(src,section,position_divisor=512,uv_divisor=1000)
 faces=fmt.indices_to_faces(fmt.read_indices(src,section),section.primitive_type,section.vertex_count)
 weights=np.array(data['blend_weights']); indices=np.array(data['blend_indices'],int)
 joints=np.array(section.bone_palette)[indices];P=np.array(data['positions']);uv=np.array(data['texcoords'][0])
 report={'source':str(SOURCE),'source_triangles':len(faces),'cel_shading':False,'variants':{}}
 mw.encode_player_vertex.__defaults__=(1000.0,)
 # Generic loader resolves materials by SECTION INDEX. Keep three invisible
 # placeholders so the entire custom model uses native section 3 (canvas).
 for variant,ref in [('000',0x94),('001',0x95c)]:
  meshpath=next((TARGET/'MESH').glob('*ch_blacksuit'+variant+'.mesh'))
  skelpath=next((TARGET/'SKEL').glob('*'+variant+'.skel'))
  gab=fmt.parse_mesh(str(meshpath));b=fmt.parse_skeleton(str(skelpath))
  target_by_hash={x.name_hash:x.index for x in b.bones}
  mapping={x.index:target_by_hash[x.name_hash] for x in a.bones}
  transforms=np.array([bind(b.bones[mapping[x.index]])@np.linalg.inv(bind(x)) for x in a.bones])
  assert gab.sections[3].material_ref_serialized==ref and gab.sections[3].vertex_stride==52
  blended=(transforms[joints]*weights[:,:,None,None]).sum(axis=1)
  positions=np.einsum('nij,nj->ni',blended[:,:3,:3],P)+blended[:,:3,3]
  normals=[]
  for key in ('normals','tangents','binormals'):
   n=np.einsum('nij,nj->ni',blended[:,:3,:3],np.array(data[key]));n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-12);normals.append(n)
  verts=[]
  for i,p in enumerate(positions):
   inf=tuple((mapping[int(j)],float(w)) for j,w in zip(joints[i],weights[i]) if w>1e-8)
   verts.append(mw.ExportVertex(position=tuple(p),uv=tuple(uv[i]),color=(0.,0.,0.,1.),normal=tuple(normals[0][i]),tangent=tuple(normals[1][i]),binormal=tuple(normals[2][i]),influences=inf))
  # 48, not 32: see blacksuit_build.py -- `world` holds 48 matrices in every skinned shader.
  palette=sorted({j for v in verts for j,w in v.influences});assert len(palette)<=48,'Canvas shader limit exceeded'
  sections=[]
  for i in range(3):
   v=copy.deepcopy(verts[0]);v.position=(0.,0.,0.);v.influences=((palette[0],1.),)
   sections.append(mw.ExportSection(source_object='Invisible native slot',source_material_index=0,material_ref_serialized=gab.sections[i].material_ref_serialized,vertices=[v],triangles=[(0,0,0)],bone_palette=[palette[0]],position_divisor=512.,schema_template_section=i))
  sections.append(mw.ExportSection(source_object='Symbiote',source_material_index=0,material_ref_serialized=ref,vertices=verts,triangles=faces,bone_palette=palette,position_divisor=512.,schema_template_section=3))
  path=OUT/meshpath.name
  mw.write_raw_mesh(str(path),gab,sections,filename_hash=gab.filename_hash,player_target='AUTO')
  result=fmt.parse_mesh(str(path));s=result.sections[3]
  decoded=fmt.decode_section_vertices(result,s,position_divisor=512,uv_divisor=1000)
  checks={'hash':result.filename_hash==gab.filename_hash,'skeleton':result.skeleton_ref_serialized==gab.skeleton_ref_serialized,'canvas_slot':len(result.sections)==4 and s.material_ref_serialized==ref,'vertices':s.vertex_count==len(verts),'faces':len(fmt.indices_to_faces(fmt.read_indices(result,s),s.primitive_type,s.vertex_count))==len(faces),'position_error':float(np.max(np.abs(np.array(decoded['positions'])-positions)))<.0021,'uv_error':float(np.max(np.abs(np.array(decoded['texcoords'][0])-uv)))<.0011,'valid_palette':all(0<=j<b.bone_count for j in s.bone_palette),'finite':bool(np.isfinite(positions).all()),'invisible_slots':all(all(len(set(t))<3 for t in fmt.indices_to_faces(fmt.read_indices(result,x),x.primitive_type,x.vertex_count)) for x in result.sections[:3])}
  w=np.array(decoded['blend_weights']);j=np.array(decoded['blend_indices'],int)
  checks['normalized_weights']=bool(np.isfinite(w).all() and (w>=0).all() and np.max(np.abs(w.sum(1)-1))<.002)
  checks['local_bone_indices']=bool(((j>=0)&(j<len(s.bone_palette))).all())
  checks['canvas_shader_48_bones']=len(s.bone_palette)<=48 and bool((j[w>0]<48).all())
  checks['normals_finite']=bool(np.isfinite(np.array(decoded['normals'])).all())
  assert all(checks.values()),checks
  report['variants'][variant]={'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'checks':checks,'vertices':s.vertex_count,'triangles':len(faces),'bones':len(palette)}
  print('VERIFIED',variant,report['variants'][variant],flush=True)
 (OUT/'validation.json').write_text(json.dumps(report,indent=2))
if __name__=='__main__':build()

