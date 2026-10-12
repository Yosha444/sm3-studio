# SPDX-License-Identifier: GPL-3.0-or-later
"""Import a custom character into the native Venom target (runs inside Blender only).

Called by venom_blender.py for a GLB/glTF/FBX/OBJ source: the model is aligned on Venom's
template, given Venom's 70-bone skeleton (by mapping a recognised source rig, otherwise by
transferring the weights of the nearest template surface), then baked into one atlas
(venom_atlas.py).
"""
import json
import math
import re
from pathlib import Path
from types import SimpleNamespace
import bpy
import numpy as np
from mathutils import Matrix, Vector
import qualite_hq as hq


def semantic(name):
    # Unreal-style exported joints carry an extra numeric node suffix.
    ue=re.sub(r'_0\d+$','',name.lower())
    if ue!=name.lower():
        m=re.fullmatch(r'(clavicle|upperarm|lowerarm|hand|thigh|calf|foot|ball)_(l|r)',ue)
        if m:
            return m[2]+{'lowerarm':'forearm','ball':'toe0'}.get(m[1],m[1])
        m=re.fullmatch(r'(thumb|index|middle|ring|pinky)_0([1-3])_(l|r)',ue)
        if m:
            digit=int(m[2])-1
            return m[3]+'finger'+str(('thumb','index','middle','ring','pinky').index(m[1]))+(str(digit) if digit else '')
        if ue in ('pelvis','head'): return ue
        if re.fullmatch(r'neck_0[1-2]',ue): return 'neck'
        if re.fullmatch(r'spine_0[1-5]',ue):
            return {'spine_01':'spine','spine_02':'spine1','spine_03':'spine2','spine_04':'spine2','spine_05':'spine3'}[ue]
    n = name.lower().split('_amazing')[0].replace('mixamorig:', '')
    n = re.sub(r'[^a-z0-9]', '', n)
    for prefix in ('bip01', 'bip', 'hlp'):
        if n.startswith(prefix):
            n = n[len(prefix):]
            break
    side = ''
    if n.startswith(('left', 'right')):
        side = n[0]; n = n[4:] if side == 'l' else n[5:]
    elif n[:1] in ('l', 'r') and n[1:].startswith(('upperarm','forearm','hand','finger','thigh','calf','foot','toe','clavicle')):
        side, n = n[0], n[1:]
    elif n[-1:] in ('l', 'r') and any(s in n for s in ('arm','hand','hip','knee','foot','toe','collar','thumb','index','middle','ring','pinky','wrist','elbow','calf','thigh','bicep','deltoid','tricep','leg')):
        side, n = n[-1], n[:-1]
    n = {'hips':'pelvis','hip':'thigh','upleg':'thigh','upperleg':'thigh','knee':'calf','leg':'calf',
         'lowerarm':'forearm','arm':'upperarm','collar':'clavicle','shoulder':'clavicle',
         'toe':'toe0','toebase':'toe0','spine0':'spine','wrist':'forearm',
         'elbow':'forearm','bicep':'upperarm','deltoid':'upperarm','tricep':'upperarm'}.get(n,n)
    for i, finger in enumerate(('thumb','index','middle','ring','pinky')):
        m = re.fullmatch(r'(?:hand)?'+finger+r'([0-3])', n)
        if m:
            digit=int(m[1])
            # Source-engine bip fingers are 0-based; Mixamo are 1-based.
            if 'mixamorig' in name.lower(): digit -= 1
            n='finger'+str(i)+(str(digit) if digit else '')
    return side+n


def active(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True); bpy.context.view_layer.objects.active = obj


def build(source, collection, donors, arm, out, textures='', drop='', materiaux=''):
    config=hq.settings(); out=Path(out); out.mkdir(parents=True,exist_ok=True)
    before=set(bpy.data.objects)
    suffix=source.suffix.lower()
    if suffix in ('.glb','.gltf'): bpy.ops.import_scene.gltf(filepath=str(source))
    elif suffix=='.fbx': bpy.ops.import_scene.fbx(filepath=str(source))
    elif suffix=='.obj': bpy.ops.wm.obj_import(filepath=str(source))
    else: raise ValueError('Custom source: GLB, glTF, FBX or OBJ.')
    imported=[o for o in bpy.data.objects if o not in before]
    meshes=[o for o in imported if o.type=='MESH' and len(o.data.vertices)]
    rigs=[o for o in imported if o.type=='ARMATURE']
    # Source export helpers are not character geometry. Retain every textured part.
    ignored=[o.name for o in meshes if o.name.lower().startswith('icosphere') and not o.vertex_groups and not o.data.materials]
    meshes=[o for o in meshes if o.name not in ignored]
    if not meshes: raise ValueError('No source mesh.')
    bpy.context.view_layer.update()
    source_rig=max(rigs,key=lambda o:len(o.data.bones)) if rigs else None
    bones={}
    if source_rig:
        bones={b.name:(semantic(b.name), source_rig.matrix_world @ b.head, b.parent.name if b.parent else None)
               for b in source_rig.pose.bones}
    for obj in meshes:
        # glTF can carry compensating pose matrices for its inverse bind matrices.
        # Freeze the evaluated imported shape before removing its source armature.
        if any(mod.type=='ARMATURE' for mod in obj.modifiers):
            evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            obj.data=bpy.data.meshes.new_from_object(evaluated,preserve_all_data_layers=True,
                depsgraph=bpy.context.evaluated_depsgraph_get())
        matrix=obj.matrix_world.copy(); obj.parent=None; obj.matrix_world=Matrix.Identity(4)
        obj.data.transform(matrix)
        for mod in list(obj.modifiers):
            if mod.type=='ARMATURE': obj.modifiers.remove(mod)
        if obj.data.shape_keys: obj.shape_key_clear()
        if obj.data.uv_layers:
            chosen=next((u for u in obj.data.uv_layers if u.active_render),obj.data.uv_layers.active)
            old=chosen.name
            for layer in list(obj.data.uv_layers):
                if layer!=chosen: obj.data.uv_layers.remove(layer)
            chosen.name='UVMap'
            for mat in obj.data.materials:
                if mat and mat.use_nodes:
                    for node in mat.node_tree.nodes:
                        if node.type=='UVMAP' and node.uv_map==old: node.uv_map='UVMap'
    meshes.sort(key=lambda o:-len(o.data.vertices)); active(meshes[0])
    for obj in meshes: obj.select_set(True)
    if len(meshes)>1: bpy.ops.object.join()
    src=bpy.context.object; src.name='VENOM_CUSTOM'
    dropped={s.strip().lower() for s in drop.split(',') if s.strip()}
    if dropped:
        active(src)
        for p in src.data.polygons:
            mat=src.data.materials[p.material_index] if p.material_index<len(src.data.materials) else None
            p.select=bool(mat and mat.name.lower() in dropped)
        bpy.context.tool_settings.mesh_select_mode=(False,False,True)
        bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.delete(type='FACE'); bpy.ops.object.mode_set(mode='OBJECT')
        if not src.data.vertices: raise ValueError('Every source material was excluded.')
    for image in bpy.data.images:
        if min(image.size)>0: continue
        candidates=[Path(textures or source.parent)/Path(bpy.path.abspath(image.filepath)).name]
        candidates += [Path(textures or source.parent)/(image.name+ext) for ext in ('.png','.tga','.jpg','.dds')]
        for path in candidates:
            if path.is_file(): image.filepath=str(path); image.reload(); break
    for mod in list(src.modifiers):
        active(src); bpy.ops.object.modifier_apply(modifier=mod.name)
    # Align the source's vertical direction, including upside-down imported rigs.
    coords=np.array([v.co[:] for v in src.data.vertices])
    if bones:
        centers=np.array([p[:] for _,p,_ in bones.values()])
        diagonal=float(np.linalg.norm(np.ptp(coords,axis=0)))
        distance=float(np.median(np.linalg.norm(centers-(coords.min(0)+coords.max(0))/2,axis=1)))
        if distance>10*max(diagonal,1e-6):
            print('[venom] Source rig outside the mesh frame: native transfer, without deforming the geometry.',flush=True)
            bones={}
    target=np.array([(o.matrix_world @ v.co)[:] for o in donors for v in o.data.vertices])
    by_sem={v[0]:v[1] for v in bones.values()}
    rotation=Matrix.Identity(4)
    if 'head' in by_sem and 'pelvis' in by_sem:
        up=by_sem['head']-by_sem['pelvis']
        rotation=up.rotation_difference(Vector((0,1,0))).to_matrix().to_4x4()
    elif np.argmax(np.ptp(coords,axis=0))==2:
        rotation=Matrix.Rotation(-math.pi/2,4,'X')
    target_bones={semantic(b.name):b for b in arm.data.bones if b.name.startswith('bip01')}
    feet=('lfoot','ltoe0','rfoot','rtoe0')
    if all(k in by_sem and k in target_bones for k in feet):
        forward=rotation.to_3x3() @ (by_sem['ltoe0']-by_sem['lfoot']+by_sem['rtoe0']-by_sem['rfoot'])
        target_forward=arm.matrix_world.to_3x3() @ (target_bones['ltoe0'].head_local-target_bones['lfoot'].head_local+target_bones['rtoe0'].head_local-target_bones['rfoot'].head_local)
        yaw=math.atan2(forward.z,forward.x)-math.atan2(target_forward.z,target_forward.x)
        rotation=Matrix.Rotation(yaw,4,'Y') @ rotation
    if all(k in by_sem and k in target_bones for k in ('lupperarm','rupperarm')):
        lateral=rotation.to_3x3() @ (by_sem['lupperarm']-by_sem['rupperarm'])
        target_lateral=arm.matrix_world.to_3x3() @ (target_bones['lupperarm'].head_local-target_bones['rupperarm'].head_local)
        if lateral.dot(target_lateral)<0:
            # Some exports label left/right in the opposite convention. Match spatial sides
            # without turning the torso backwards or crossing the limbs.
            bones={n:((('r' if key[0]=='l' else 'l')+key[1:] if key[:1] in ('l','r') else key),p,parent)
                   for n,(key,p,parent) in bones.items()}
    src.data.transform(rotation)
    coords=np.array([v.co[:] for v in src.data.vertices])
    lo,hi=coords.min(0),coords.max(0); tlo,thi=target.min(0),target.max(0)
    scale=(thi[1]-tlo[1])/(hi[1]-lo[1])
    offset=(tlo+thi)/2-(lo+hi)*scale/2
    align=Matrix.Translation(Vector(offset)) @ Matrix.Scale(scale,4) @ rotation
    src.data.transform(Matrix.Translation(Vector(offset)) @ Matrix.Scale(scale,4))
    direct={name:target_bones[key] for name,(key,_,_) in bones.items() if key in target_bones}
    mapped=dict(direct)
    for name in bones:
        parent=bones[name][2]
        while name not in mapped and parent:
            if parent in direct: mapped[name]=direct[parent]; break
            parent=bones[parent][2]
    old_names={g.index:g.name for g in src.vertex_groups}
    weights=[]
    for v in src.data.vertices:
        entries=[(old_names[g.group],g.weight) for g in v.groups if g.weight>1e-5]
        weights.append(entries)
    covered=sum(bool(w) and sum(x for n,x in w if n in mapped)>.9 for w in weights)/len(weights)
    report={'source':str(source),'helpers_ignored':ignored,'mapped_bones':len(direct),'rig_coverage':covered}
    if len(direct)>=10 and covered>.95:
        # Use corresponding joint positions, not Blender's arbitrary imported bone tails.
        by_target={b.name:n for n,b in direct.items() if not n.lower().startswith('hlp')}
        transforms={}
        for target_name,name in by_target.items():
            tb=mapped[name]; sh=align @ bones[name][1]; th=arm.matrix_world @ tb.head_local
            pairs=[]
            # A branching pelvis/hand must not rotate toward an arbitrary first child.
            # Use the anatomical continuation only; the pelvis keeps global alignment.
            key=semantic(tb.name)
            next_key={'spine':'spine1','spine1':'spine2','spine2':'neck','neck':'head'}
            for side in ('l','r'):
                for a,b in (('clavicle','upperarm'),('upperarm','forearm'),('forearm','hand'),('thigh','calf'),('calf','foot'),('foot','toe0'),('hand','finger2')):
                    next_key[side+a]=side+b
                for digit in range(5):
                    next_key[side+'finger'+str(digit)]=side+'finger'+str(digit)+'1'
                    next_key[side+'finger'+str(digit)+'1']=side+'finger'+str(digit)+'2'
            continuation=target_bones.get(next_key.get(key,''))
            for child in ([continuation] if continuation else []):
                other=by_target.get(child.name)
                if other:
                    sv=align @ bones[other][1]-sh; tv=arm.matrix_world @ child.head_local-th
                    if min(sv.length,tv.length)>1e-4: pairs.append((sv,tv))
            if not pairs and key!='pelvis' and tb.parent and tb.parent.name in by_target:
                pn=by_target[tb.parent.name]
                pairs=[(sh-align @ bones[pn][1],th-arm.matrix_world @ tb.parent.head_local)]
            rot=Matrix.Identity(3)
            if pairs and min(pairs[0][0].length,pairs[0][1].length)>1e-4:
                sv,tv=pairs[0]; rot=sv.rotation_difference(tv).to_matrix()
                if continuation:
                    unit=np.array(sv.normalized())
                    stretch=Matrix(np.eye(3)+(tv.length/sv.length-1)*np.outer(unit,unit))
                    rot=rot @ stretch
            transforms[target_name]=(sh,th,rot)
        # Helpers share the corresponding main-bone transform; fingers retain their own weights.
        positions=[]; vertex_rotations=[]; new_weights=[]
        for v,entries in zip(src.data.vertices,weights):
            total=sum(w for n,w in entries if n in mapped and mapped[n].name in transforms)
            if total<=0: raise ValueError('Vertex without a matching bone in the rig.')
            position=Vector(); blended=np.zeros((3,3)); merged={}
            for name,w in entries:
                if name not in mapped or mapped[name].name not in transforms: continue
                key=mapped[name].name; sh,th,rot=transforms[key]; weight=w/total
                position+=(th+rot @ (v.co-sh))*weight
                blended+=np.array(rot.inverted_safe().transposed())*weight; merged[key]=merged.get(key,0)+weight
            positions.append(position); vertex_rotations.append(Matrix(blended)); new_weights.append(merged)
        normals=[(vertex_rotations[loop.vertex_index] @ normal.vector).normalized()[:]
                 for loop,normal in zip(src.data.loops,src.data.corner_normals)]
        for v,p in zip(src.data.vertices,positions): v.co=p
        src.data.update(); src.data.normals_split_custom_set(normals)
        for g in list(src.vertex_groups): src.vertex_groups.remove(g)
        groups={b.name:src.vertex_groups.new(name=b.name) for b in arm.data.bones}
        for i,entries in enumerate(new_weights):
            top=sorted(entries.items(),key=lambda p:-p[1])[:4]; total=sum(w for _,w in top)
            for n,w in top: groups[n].add([i],w/total,'REPLACE')
        report['skinning']='source rig mapped to Venom; joint rest adaptation'
    else:
        # Unrigged/unknown rigs: interpolate the native donor surface after alignment.
        copies=[]
        for obj in donors:
            copy=obj.copy(); copy.data=obj.data.copy(); bpy.context.scene.collection.objects.link(copy); copies.append(copy)
        active(copies[0])
        for obj in copies: obj.select_set(True)
        if len(copies)>1: bpy.ops.object.join()
        donor=bpy.context.object
        for g in list(src.vertex_groups): src.vertex_groups.remove(g)
        active(donor); src.select_set(True)
        bpy.ops.object.data_transfer(use_object_transform=True,data_type='VGROUP_WEIGHTS',use_create=True,
            vert_mapping='POLYINTERP_NEAREST',layers_select_src='ALL',layers_select_dst='NAME',mix_mode='REPLACE')
        bpy.data.objects.remove(donor,do_unlink=True)
        report['skinning']='native nearest-surface transfer; source must match target rest pose'
        print('[venom] Unknown rig: spatial transfer, check the pose and the fingers in Blender.',flush=True)
    # A valid exported vertex always has normalized weights and at most four influences.
    for v in src.data.vertices:
        top=sorted([(g.group,g.weight) for g in v.groups if g.weight>1e-5],key=lambda p:-p[1])[:4]
        if not top: raise ValueError(f'Vertex {v.index} has no weight: export cancelled.')
        total=sum(w for _,w in top)
        for g in list(v.groups): src.vertex_groups[g.group].remove([v.index])
        for gi,w in top: src.vertex_groups[gi].add([v.index],w/total,'REPLACE')
    active(src); hq.geometry(src,config)
    # Conservation mode still needs triangles for the native writer.
    if any(len(p.vertices)!=3 for p in src.data.polygons):
        mod=src.modifiers.new('Export triangulation','TRIANGULATE'); mod.keep_custom_normals=True
        bpy.ops.object.modifier_apply(modifier=mod.name)
    from venom_atlas import bake
    bake(src,out,textures or str(source.parent),materiaux,config)
    for c in list(src.users_collection): c.objects.unlink(src)
    collection.objects.link(src)
    src['sm3_material_ref_serialized']=0x28C
    mod=src.modifiers.new('Venom skeleton','ARMATURE'); mod.object=arm
    arm.data.pose_position='REST'
    for obj in list(donors): bpy.data.objects.remove(obj,do_unlink=True)
    for obj in list(bpy.data.objects):
        if obj not in (src,arm) and obj.type in ('MESH','ARMATURE'): bpy.data.objects.remove(obj,do_unlink=True)
    report['vertices']=len(src.data.vertices); report['triangles']=len(src.data.polygons)
    report['bones_used']=len({g.group for v in src.data.vertices for g in v.groups if g.weight>0})
    collection['sm3_hq_custom']=True
    collection['sm3_hq_atlas']=str(out/'SM3_Spider_Baked_Atlas_atlas_final.png')
    (out/'venom_custom.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print('[venom] Custom adaptation:',report,flush=True)
    return [src]
