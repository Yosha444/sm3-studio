# SPDX-License-Identifier: GPL-3.0-or-later
"""rvb_native.py - rebuild a Web of Shadows model as SM3 meshes with its ORIGINAL weights ("RvB" mode).

Called by rvb_finalize.py: build(<build folder>, model, target). Reads
profiles/rvb/<model>.json (per-section positions and bone influences of the Web of Shadows
model) and <model>.skeleton.json (its bones: index, name hash, inverse bind matrix), plus the
official chain's <build>/source/0xAC92103D.ch_spiderman000.mesh, and the target's vanilla
meshes and skeletons. Writes <build>/corrected/<target 000 and 001 mesh names> and
correction.json.

Steps, per LOD (000 then 001):
  * vertex identity: the chain's 000 has the baked atlas UVs but was re-weighted; each of its
    vertices is matched to the nearest original vertex (after a bounding-box fit; max error
    must stay < 0.003), so the original weights can be used with the new UVs;
  * every original bone is mapped by name hash onto the target skeleton, and each vertex moved
    by its weighted blend of (target bone -> model) x (original model -> bone);
  * the bone palette is cut to the 32 bones that dominate the most vertices; an influence on a
    dropped bone goes to its closest retained ANCESTOR, never to a spatial neighbour on another
    finger or limb;
  * triangles are flipped if needed so the winding is the PC's (inward), normals recomputed
    outward, tangents from the UVs;
  * the model goes into the target's "canvas" section (3 for the black suit and for any 001,
    4 for the red suit 000), earlier sections become invisible placeholders, and the written
    file is decoded back and checked (positions, UVs, weights).
"""

from pathlib import Path
import sys,json,copy,struct
import numpy as np
STUDIO=Path(__file__).resolve().parents[1]

sys.path[:0]=[str(STUDIO),str(STUDIO/'tools'),str(STUDIO/'correctifs_blender')]
from sm3_sans_blender import fmt,tbn,norme
import blacksuit_mesh_writer as mw  # correctifs_blender/: modified copy of TSGAMING264's writer

def bind(values):
    m=np.array(values).reshape(4,4).copy();m[:3,3]=0;m[3,3]=1
    return np.linalg.inv(m).T

def build(root, model, target_name, pose_target=None):
    if pose_target not in (None, "spiderman", "blacksuit"):
        raise ValueError("Unsupported pose target")
    ROOT=Path(root)
    source=json.loads((STUDIO/'profiles/rvb'/(model+'.json')).read_text())
    bones=json.loads((STUDIO/'profiles/rvb'/(model+'.skeleton.json')).read_text())
    P=np.array([p for s in source for p in s['positions']]);inf=[w for s in source for w in s['influences']]
    # Atlas identity uses the legacy GLB positions. Native section corrections
    # apply only after matching, so the atlas and all other sections stay intact.
    native_scale=np.array([s.get('native_position_scale',1.0) for s in source for _ in s['positions']])
    native_positions=P*native_scale[:,None]
    atlas=fmt.parse_mesh(str(ROOT/'source/0xAC92103D.ch_spiderman000.mesh'))
    sec=atlas.sections[0];d=fmt.decode_section_vertices(atlas,sec,position_divisor=512,uv_divisor=1000)
    A=np.array(d['positions']);uv=np.array(d['texcoords'][0]);faces=fmt.indices_to_faces(fmt.read_indices(atlas,sec),sec.primitive_type,sec.vertex_count)
    # Recover only vertex identity from the atlas conversion, before arm edits.
    scale=max(np.ptp(A,axis=0))/max(np.ptp(P,axis=0));offset=(A.max(0)+A.min(0))/2-scale*(P.max(0)+P.min(0))/2
    aligned=P*scale+offset
    nearest=[];errors=[]
    for start in range(0,len(A),128):
        ds=((A[start:start+128,None,:]-aligned[None,:,:])**2).sum(2)
        ids=ds.argmin(1);nearest.extend(ids.tolist());errors.extend(np.sqrt(ds[np.arange(len(ids)),ids]).tolist())
    assert max(errors)<.003, max(errors)
    out=ROOT/'corrected';out.mkdir(exist_ok=True)
    reports={}
    black=target_name=='blacksuit'
    target=STUDIO/('vanilla/CH_BLACKSUIT/_O0108.0xF8ACB40C.T36.apkf' if black else 'vanilla/CH_SPIDERMAN/_O0069.0xCFB154CD.T36.apkf')
    pose_black=black if pose_target is None else pose_target=='blacksuit'
    pose_root=STUDIO/('vanilla/CH_BLACKSUIT/_O0108.0xF8ACB40C.T36.apkf' if pose_black else 'vanilla/CH_SPIDERMAN/_O0069.0xCFB154CD.T36.apkf')
    basename='ch_blacksuit' if black else 'ch_spiderman'
    for variant in ('000','001'):
        template=fmt.parse_mesh(str(next(target.glob('*'+basename+variant+'.mesh'))))
        skel=fmt.parse_skeleton(str(next(pose_root.glob('*'+variant+'.skel'))))
        mapping={b['index']:next(x.index for x in skel.bones if x.name_hash==int(b['hash'],16)) for b in bones}
        transforms=[bind(skel.bones[mapping[i]].inverse_values)@np.linalg.inv(bind(b['inverse'])) for i,b in enumerate(bones)]
        positions=[];weights=[]
        for original in nearest:
            w=inf[original];matrix=sum(transforms[j]*v for j,v in w)
            positions.append((matrix@np.r_[native_positions[original],1])[:3]);weights.append([(mapping[j],v) for j,v in w])
        positions=np.array(positions)
        assert np.isfinite(positions).all() and np.max(np.abs(positions))<5
        # The PC canvas supports 32 bones. Select by dominant vertices, then
        # remap omitted influences to the closest retained ancestor, never a
        # spatial neighbour on another finger or limb.
        scores={}
        for w in weights:
            j=max(w,key=lambda item:item[1])[0];scores[j]=scores.get(j,0)+1
        palette=sorted(sorted(scores,key=scores.get,reverse=True)[:32])
        parents={b.index:b.parent_index for b in skel.bones}
        reduced=[];omitted=0
        for w in weights:
            acc={}
            for j,v in w:
                old=j
                while j not in palette and j>=0:j=parents[j]
                if j<0:
                    # A root without a retained ancestor is kept explicitly.
                    raise ValueError('Missing retained ancestor for bone '+str(old))
                omitted+=int(j!=old);acc[j]=acc.get(j,0)+v
            reduced.append(tuple(acc.items()))
        triangles=np.array(faces,int)
        volume=float(np.einsum('ij,ij->i',positions[triangles[:,0]],np.cross(positions[triangles[:,1]],positions[triangles[:,2]])).sum()/6)
        if volume>0:triangles[:,[1,2]]=triangles[:,[2,1]]
        # PC winding is inward; shading normals are outward, independently.
        normals=np.zeros_like(positions)
        cross=-np.cross(positions[triangles[:,1]]-positions[triangles[:,0]],positions[triangles[:,2]]-positions[triangles[:,0]])
        for col in range(3):np.add.at(normals,triangles[:,col],cross)
        normals=norme(normals);t,b=tbn(positions,uv,triangles);t=norme(t);b=norme(b)
        vertices=[mw.ExportVertex(position=tuple(p),uv=tuple(uv[i]),normal=tuple(normals[i]),tangent=tuple(t[i]),binormal=tuple(b[i]),color=(0,0,0,1),influences=reduced[i]) for i,p in enumerate(positions)]
        sections=[]
        canvas=3 if black or variant=="001" else 4
        for i in range(canvas):
            v=copy.deepcopy(vertices[0]);v.position=(0,0,0);v.influences=((palette[0],1),)
            sections.append(mw.ExportSection('placeholder',0,template.sections[i].material_ref_serialized,[v],[(0,0,0)],[palette[0]],schema_template_section=i))
        sections.append(mw.ExportSection('RvB native weights',0,template.sections[canvas].material_ref_serialized,vertices,[tuple(map(int,f)) for f in triangles],palette,position_divisor=512,schema_template_section=canvas))
        mw.encode_player_vertex.__defaults__=(1000.,)
        path=out/Path(template.path).name
        mw.write_raw_mesh(str(path),template,sections,filename_hash=template.filename_hash,player_target='AUTO')
        check=fmt.parse_mesh(str(path));dd=fmt.decode_section_vertices(check,check.sections[canvas],position_divisor=512,uv_divisor=1000)
        assert np.max(np.abs(np.array(dd['positions'])-positions))<.0021
        assert np.max(np.abs(np.array(dd['texcoords'][0])-uv))<.0011
        assert np.max(np.abs(np.array(dd['blend_weights']).sum(1)-1))<.002
        reports[variant]=dict(pose_target=('blacksuit' if pose_black else 'spiderman'),triangles=len(triangles),vertices=len(vertices),atlas_match_max_error=max(errors),original_volume=volume,retained_bones=palette,ancestor_remapped_influences=omitted,position_bounds=[positions.min(0).tolist(),positions.max(0).tolist()],game_verified=False)
    (out/'correction.json').write_text(json.dumps(reports,indent=2));print(json.dumps(reports,indent=2))
if __name__=='__main__':build(*sys.argv[1:])
