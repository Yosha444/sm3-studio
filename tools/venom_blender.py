# SPDX-License-Identifier: GPL-3.0-or-later
"""Native Venom editing in Blender: import of the template, export of its SM3 collection.

Started by venom_runner.py as  blender -b --python venom_blender.py -- --src ... --out ...
It uses TSGAMING264's "SM3 Blender Toolkit" add-on (blender_io, sm3_export, sm3_mesh_writer)
to read and write the game's .mesh format. --prepare saves an editable .blend instead of
exporting. A custom model (GLB, glTF, FBX, OBJ) is adapted by venom_custom.py first.
"""
import argparse
import os
import sys
import json
import shutil
from pathlib import Path
import bpy
import bl_ext.user_default.sm3_blender_toolkit.blender_io as io
import bl_ext.user_default.sm3_blender_toolkit.sm3_export as export

ap = argparse.ArgumentParser()
ap.add_argument('--src', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--prepare', action='store_true')
ap.add_argument('--textures', default='')
ap.add_argument('--materiaux', default='')
ap.add_argument('--drop', default='')
A = ap.parse_args(sys.argv[sys.argv.index('--') + 1:])
source = Path(A.src).resolve()
sys.path.insert(0,str(Path(__file__).resolve().parent))
custom = source.suffix.lower() in ('.glb','.gltf','.fbx','.obj')
if source.suffix.lower() == '.blend':
    bpy.ops.wm.open_mainfile(filepath=str(source))
    collections = [c for c in bpy.data.collections if c.get('sm3_hq_target') == 'venom']
    if len(collections) != 1:
        raise RuntimeError('Use the Venom project prepared by Studio: target collection missing or ambiguous.')
    collection = collections[0]
    objects = [o for o in collection.all_objects if o.type == 'MESH']
else:
    if source.suffix.lower() != '.mesh' and not custom:
        raise RuntimeError('The Venom profile accepts the native mesh or its prepared .blend project.')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    template = Path(__file__).resolve().parent.parent / 'profiles/venom/0xBF11C1BF.ch_venom000.mesh' if custom else source
    collection, objects, arm, mesh = io.import_mesh(str(template), uv_divisor=1024.0,
        auto_find_skeleton=True, import_skeleton_if_found=True,
        reverse_winding=True, flip_uv_v=True)
    if mesh.filename_hash != 0xBF11C1BF:
        raise RuntimeError('This mesh is not the ch_venom000 template.')
    if arm is None:
        raise RuntimeError('Venom skeleton missing: use the template in profiles/venom.')
    collection['sm3_hq_target'] = 'venom'
    io.rename_vertex_groups_from_armature(collection)
    for obj in objects:
        stored = obj.data.attributes.get('sm3_normal')
        if stored is not None:
            obj.data.shade_smooth()
            obj.data.normals_split_custom_set_from_vertices([tuple(v.vector) for v in stored.data])
    arm.data.pose_position = 'REST'
    if custom:
        from venom_custom import build
        objects=build(source,collection,objects,arm,Path(A.out).parent,A.textures,A.drop,A.materiaux)

Path(A.out).parent.mkdir(parents=True, exist_ok=True)
if A.prepare:
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(A.out).resolve()))
    print('[venom] Blender project prepared:', A.out, flush=True)
else:
    import bl_ext.user_default.sm3_blender_toolkit.sm3_mesh_writer as writer
    is_custom=bool(collection.get('sm3_hq_custom',False))
    writer.encode_player_vertex.__defaults__ = (1024.0,)
    if is_custom:
        original_write=export.write_raw_mesh
        def write_native(output_path,template,sections,**kwargs):
            for section in sections:
                section.position_divisor=1000.0
            return original_write(output_path,template,sections,**kwargs)
        export.write_raw_mesh=write_native
        collection['sm3_hq_renderer']='venom_native_argb_indices_v1'
    def triangulated_preserving_normals(obj, *, tangent_uv_layer_name=None, preflip_tangent_uv_v=False):
        # The generic toolkit's BMesh pass discards custom normals. Avoid it for
        # already triangulated meshes, including the native Venom sections.
        mesh = obj.data.copy()
        if any(len(poly.vertices) != 3 for poly in mesh.polygons):
            bpy.data.meshes.remove(mesh)
            raise RuntimeError('Venom: triangulate the mesh in Blender before export, keeping the normals.')
        if mesh.uv_layers:
            mesh.calc_tangents(uvmap=tangent_uv_layer_name or mesh.uv_layers.active.name)
        return mesh
    export._triangulated_mesh = triangulated_preserving_normals
    result = export.export_objects_to_target_mesh(objects, collection, str(Path(A.out).resolve()),
        max_bones=48, reverse_winding=True, flip_uv_v=True, write_report=True)
    if is_custom:
        report_path=Path(str(Path(A.out).resolve())+'.export.json')
        report=json.loads(report_path.read_text(encoding='utf8'))
        report['uv_encoding']='SHORT2 uv * 1024 (native Venom roundtrip)'
        report['renderer']='venom_native_argb_indices_v1'
        for decision in report.get('section_decisions',[]): decision['vertex_stride']=48
        report_path.write_text(json.dumps(report,indent=2),encoding='utf8')
    print('[venom] Native export finished:', A.out, flush=True)
    is_custom=bool(collection.get('sm3_hq_custom',False))
    if is_custom:
        atlas=Path(collection['sm3_hq_atlas'])
        destination=Path(A.out).resolve().parent/'SM3_Spider_Baked_Atlas_atlas_final.png'
        if atlas.resolve()!=destination:
            shutil.copy2(atlas,destination)
            collection['sm3_hq_atlas']=str(destination)
    (Path(A.out).parent/'venom_build.json').write_text(json.dumps({'custom':is_custom,'source':str(source),
        'renderer':'venom_native_argb_indices_v1' if is_custom else 'native','requires_pack_patch':False},indent=2),encoding='utf8')
    if is_custom:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(A.out).parent/'Venom_custom.blend'))
