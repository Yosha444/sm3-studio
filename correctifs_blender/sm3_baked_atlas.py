# SPDX-License-Identifier: GPL-3.0-or-later
# Modified copy of sm3_baked_atlas.py from TSGAMING264's "SM3 Material Combiner" Blender add-on
# (version 1.4.8, GPL-3.0-or-later, https://github.com/TSGAMING264/SM3-Blender-Tools).
# Changed by the SM3 Studio project in September 2026, in two places marked "FIX 4/5" (the .tex
# gets the same pixels as atlas_final.png) and "SM3 Studio HQ" (islands rotated by quarter turns
# only). Everything else is TSGAMING264's code, unchanged. Distributed under the same licence.
# Why and how to install it: correctifs_blender/README.md of SM3 Studio.
"""Friend-style Blender baked atlas experiment for Spider-Man 3.

This path mirrors the proven xeSM3 workflow discovered in the supplied source:
  * preserve the original UVs in ``SM3_SRC``;
  * repack the export UV islands into 0..1;
  * dilate source image islands before baking;
  * Cycles diffuse-color bake to a single atlas;
  * fill the ENTIRE unused atlas background from the nearest packed UV island;
  * generate a complete DXT1 mip chain;
  * write a raw 0x44-byte-header SM3 TEX (no inserted PHYS literal).

The operator is intentionally focused on one active mesh at a time.  That is the
same shape the Spider canvas export path ultimately needs, and makes diagnosis
far safer than silently joining arbitrary selected objects during texture bake.
"""
from __future__ import annotations

from pathlib import Path
import json
import math
import re
from typing import Dict, Iterable, List, Sequence, Tuple

import bpy
import numpy as np

from .sm3_dxt import build_dxt1_mips, write_dxt1_dds, write_raw_sm3_dxt1_tex


def _safe_name(text: str, fallback: str = "SM3_Baked_Atlas") -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text or "").strip())
    return text or fallback


def _linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1.0 / 2.4) - 0.055)


def _srgb_to_linear(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, np.power((x + 0.055) / 1.055, 2.4))


def _image_pixels_linear(image: bpy.types.Image) -> np.ndarray:
    w, h = int(image.size[0]), int(image.size[1])
    if w <= 0 or h <= 0:
        raise ValueError(f"Image '{image.name}' has invalid size")
    arr = np.empty(w * h * 4, dtype=np.float32)
    image.pixels.foreach_get(arr)
    return np.clip(arr.reshape(h, w, 4), 0.0, 1.0)


def _image_pixels_srgb_u8(image: bpy.types.Image) -> np.ndarray:
    linear = _image_pixels_linear(image)
    out = np.empty(linear.shape, dtype=np.uint8)
    out[:, :, :3] = np.clip(_linear_to_srgb(linear[:, :, :3]) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out[:, :, 3] = np.clip(linear[:, :, 3] * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return out


def _set_image_from_srgb_u8(image: bpy.types.Image, rgba: np.ndarray) -> None:
    rgba = np.asarray(rgba, dtype=np.uint8)
    f = rgba.astype(np.float32) / 255.0
    linear = np.empty(f.shape, dtype=np.float32)
    linear[:, :, :3] = _srgb_to_linear(f[:, :, :3])
    linear[:, :, 3] = f[:, :, 3]
    image.pixels.foreach_set(linear.reshape(-1))
    image.update()


def _copy_uv_layer(mesh: bpy.types.Mesh, source, name: str):
    existing = mesh.uv_layers.get(name)
    if existing is not None:
        mesh.uv_layers.remove(existing)
    dest = mesh.uv_layers.new(name=name, do_init=False)
    for i in range(min(len(source.data), len(dest.data))):
        dest.data[i].uv = source.data[i].uv
    return dest


def _triangles_for_slots(mesh: bpy.types.Mesh, uv_layer, slots: set[int]) -> List[np.ndarray]:
    """Read triangle UVs without keeping a stale MeshUVLoopLayer reference.

    Blender 4.5 can reallocate mesh CustomData when UV operators run in Edit Mode.
    Any Python MeshUVLoopLayer object captured before that operation may then point
    at freed/replaced data and can hard-crash blender.exe on ``uv_layer.data[i]``.
    Always resolve the layer again by name immediately before reading it.
    """
    tris: List[np.ndarray] = []
    layer_name = uv_layer if isinstance(uv_layer, str) else getattr(uv_layer, "name", None)
    if not layer_name:
        raise ValueError("UV layer reference has no name")
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        raise ValueError(f"UV layer '{layer_name}' no longer exists")
    uv = layer.data
    for poly in mesh.polygons:
        if int(poly.material_index) not in slots or len(poly.loop_indices) != 3:
            continue
        tris.append(np.asarray([[float(uv[li].uv.x), float(uv[li].uv.y)] for li in poly.loop_indices], dtype=np.float32))
    return tris


def _rasterize_uv_triangles(triangles: Iterable[np.ndarray], width: int, height: int) -> np.ndarray:
    """Rasterize UV triangles to a bottom-origin mask matching Blender image pixels."""
    mask = np.zeros((height, width), dtype=bool)
    for tri_uv in triangles:
        tr = np.asarray(tri_uv, dtype=np.float64).copy()
        tr[:, 0] *= max(1, width - 1)
        tr[:, 1] *= max(1, height - 1)
        x0 = max(0, int(math.floor(float(tr[:, 0].min()))))
        x1 = min(width - 1, int(math.ceil(float(tr[:, 0].max()))))
        y0 = max(0, int(math.floor(float(tr[:, 1].min()))))
        y1 = min(height - 1, int(math.ceil(float(tr[:, 1].max()))))
        if x1 < x0 or y1 < y0:
            continue
        (ax, ay), (bx, by), (cx, cy) = tr
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        X, Y = np.meshgrid(np.arange(x0, x1 + 1, dtype=np.float64) + 0.5,
                           np.arange(y0, y1 + 1, dtype=np.float64) + 0.5)
        l1 = ((by - cy) * (X - cx) + (cx - bx) * (Y - cy)) / den
        l2 = ((cy - ay) * (X - cx) + (ax - cx) * (Y - cy)) / den
        inside = (l1 >= -1e-6) & (l2 >= -1e-6) & (l1 + l2 <= 1.0 + 1e-6)
        mask[y0:y1 + 1, x0:x1 + 1] |= inside
    return mask


def _dilate_fixed_passes_rgba(rgba: np.ndarray, mask: np.ndarray, passes: int) -> np.ndarray:
    """Friend-style local dilation used on SOURCE images before the bake."""
    out = np.asarray(rgba, dtype=np.uint8).copy()
    valid = np.asarray(mask, dtype=bool).copy()
    if not valid.any() or passes <= 0:
        return out
    rgb = out[:, :, :3].astype(np.uint16)
    for _ in range(int(passes)):
        empty = ~valid
        if not empty.any():
            break
        sums = np.zeros((*valid.shape, 3), dtype=np.uint32)
        counts = np.zeros(valid.shape, dtype=np.uint16)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            shifted_valid = np.roll(np.roll(valid, dy, axis=0), dx, axis=1)
            shifted_rgb = np.roll(np.roll(rgb, dy, axis=0), dx, axis=1)
            if dy < 0: shifted_valid[dy:, :] = False
            elif dy > 0: shifted_valid[:dy, :] = False
            if dx < 0: shifted_valid[:, dx:] = False
            elif dx > 0: shifted_valid[:, :dx] = False
            sums += shifted_rgb.astype(np.uint32) * shifted_valid[:, :, None]
            counts += shifted_valid.astype(np.uint16)
        grow = empty & (counts > 0)
        if not grow.any():
            break
        rgb[grow] = (sums[grow] // counts[grow, None]).astype(np.uint16)
        valid[grow] = True
    out[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    out[:, :, 3][valid] = 255
    return out


def _shift_seed(seed_y: np.ndarray, seed_x: np.ndarray, dy: int, dx: int):
    h, w = seed_y.shape
    cy = np.full_like(seed_y, -1)
    cx = np.full_like(seed_x, -1)
    sy0 = max(0, -dy); sy1 = min(h, h - dy)
    sx0 = max(0, -dx); sx1 = min(w, w - dx)
    dy0 = sy0 + dy; dy1 = sy1 + dy
    dx0 = sx0 + dx; dx1 = sx1 + dx
    if sy1 > sy0 and sx1 > sx0:
        cy[dy0:dy1, dx0:dx1] = seed_y[sy0:sy1, sx0:sx1]
        cx[dy0:dy1, dx0:dx1] = seed_x[sy0:sy1, sx0:sx1]
    return cy, cx


def _fill_background_nearest(rgba: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Fill all non-island pixels from a near-nearest island pixel using JFA.

    This replaces the thousands of full-image dilation passes in the research
    script with a logarithmic jump-flood pass, while preserving the important
    rule: no black/empty background remains for lower mip levels to sample.
    """
    rgba = np.asarray(rgba, dtype=np.uint8)
    mask = np.asarray(mask, dtype=bool)
    if not mask.any():
        raise ValueError("Packed UV mask is empty; cannot dilate atlas")
    h, w = mask.shape
    yy, xx = np.indices((h, w), dtype=np.int32)
    seed_y = np.where(mask, yy, -1).astype(np.int32)
    seed_x = np.where(mask, xx, -1).astype(np.int32)
    best_dist = np.where(mask, 0, np.iinfo(np.int32).max).astype(np.int32)

    step = 1
    while step < max(h, w):
        step <<= 1
    step >>= 1
    while step >= 1:
        for dy in (-step, 0, step):
            for dx in (-step, 0, step):
                if dy == 0 and dx == 0:
                    continue
                cy, cx = _shift_seed(seed_y, seed_x, dy, dx)
                valid = cy >= 0
                if not valid.any():
                    continue
                dist = (cy - yy) * (cy - yy) + (cx - xx) * (cx - xx)
                better = valid & (dist < best_dist)
                seed_y[better] = cy[better]
                seed_x[better] = cx[better]
                best_dist[better] = dist[better]
        step >>= 1

    missing = seed_y < 0
    if missing.any():
        # JFA should resolve every pixel.  A final cheap local propagation is a
        # defensive fallback for pathological 1px masks.
        resolved = ~missing
        temp = _dilate_fixed_passes_rgba(rgba, resolved, max(h, w))
        out = temp
    else:
        out = rgba.copy()
        bg = ~mask
        out[bg] = rgba[seed_y[bg], seed_x[bg]]
    out[:, :, 3] = 255
    return out


def _boost_srgb(rgba: np.ndarray, saturation: float, contrast: float) -> np.ndarray:
    out = np.asarray(rgba, dtype=np.uint8).copy()
    x = out[:, :, :3].astype(np.float32)
    if abs(float(saturation) - 1.0) > 1e-6:
        lum = (x @ np.array([0.299, 0.587, 0.114], dtype=np.float32))[:, :, None]
        x = lum + (x - lum) * float(saturation)
    if abs(float(contrast) - 1.0) > 1e-6:
        x = (x - 128.0) * float(contrast) + 128.0
    out[:, :, :3] = np.clip(x, 0, 255).astype(np.uint8)
    return out


def _save_srgb_png(path: Path, rgba: np.ndarray, image_name: str) -> bpy.types.Image:
    old = bpy.data.images.get(image_name)
    if old is not None:
        bpy.data.images.remove(old)
    h, w = rgba.shape[:2]
    image = bpy.data.images.new(image_name, width=w, height=h, alpha=True)
    try:
        image.colorspace_settings.name = "sRGB"
    except Exception:
        pass
    _set_image_from_srgb_u8(image, rgba)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    return image


def _atlas_preview_material(image: bpy.types.Image, name: str, uv_layer_name: str | None = None) -> bpy.types.Material:
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    tex.extension = "EXTEND"
    tex.interpolation = "Linear"
    if uv_layer_name:
        uv = nodes.new("ShaderNodeUVMap")
        uv.uv_map = str(uv_layer_name)
        uv.label = f"Atlas UV: {uv_layer_name}"
        links.new(uv.outputs["UV"], tex.inputs["Vector"])
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if "Alpha" in tex.outputs and "Alpha" in bsdf.inputs:
        links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    mat["sm3_friend_baked_atlas"] = True
    return mat


def create_friend_baked_atlas(
    obj: bpy.types.Object,
    output_directory: str | Path,
    *,
    atlas_name: str = "SM3_Spider_Baked_Atlas",
    size: int = 2048,
    uv_margin: float = 0.006,
    source_dilate_passes: int = 24,
    saturation: float = 1.25,
    contrast: float = 1.05,
    texture_hash: int = 0x8E661B33,
    texture_resource_name: str = "ch_spiderman_spider",
    apply_preview_material: bool = True,
) -> Dict[str, object]:
    if obj is None or obj.type != "MESH":
        raise ValueError("Active object must be a MESH")
    mesh = obj.data
    if not mesh.uv_layers:
        raise ValueError(f"{obj.name}: no UV map")
    if len(mesh.polygons) == 0:
        raise ValueError(f"{obj.name}: mesh has no faces")
    size = int(size)
    if size < 128 or size > 8192 or (size & (size - 1)):
        raise ValueError("Bake size must be a power of two from 128 to 8192")
    uv_margin = max(0.0, float(uv_margin))
    source_dilate_passes = max(0, int(source_dilate_passes))

    out_dir = Path(output_directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_name(atlas_name)
    baked_png = out_dir / f"{safe}_atlas_cuit.png"
    final_png = out_dir / f"{safe}_atlas_final.png"
    dds_path = out_dir / f"0x{int(texture_hash)&0xFFFFFFFF:08X}.{texture_resource_name}.dds"
    tex_path = out_dir / f"0x{int(texture_hash)&0xFFFFFFFF:08X}.{texture_resource_name}.tex"
    report_path = out_dir / f"{safe}.friend_bake.json"

    # Resolve the export UV deterministically. Repeated atlas builds must never
    # treat SM3_SRC as the export UV or overwrite SM3_SRC with an already-packed
    # atlas layout. Prefer the UV recorded by a prior successful bake, otherwise
    # use the first non-SM3_SRC layer.
    preferred_export = str(obj.get("sm3_friend_atlas_uv_export") or "").strip()
    export_uv = None
    if preferred_export and preferred_export != "SM3_SRC":
        export_uv = mesh.uv_layers.get(preferred_export)
    if export_uv is None:
        active = mesh.uv_layers.active
        if active is not None and active.name != "SM3_SRC":
            export_uv = active
    if export_uv is None:
        export_uv = next((layer for layer in mesh.uv_layers if layer.name != "SM3_SRC"), None)
    if export_uv is None:
        raise ValueError(f"{obj.name}: no export UV layer other than SM3_SRC")

    export_uv_name = export_uv.name

    # TRUSTED SOURCE UV SNAPSHOT -------------------------------------------------
    # The friend pipeline copies the model's *actual authored UVs* before packing.
    # Polygon-index reconstruction from the source OBJ is not safe after Blender
    # import/join because polygon/corner order may differ even when triangle counts
    # match. Keep a persistent master snapshot from the clean .blend instead.
    master_name = "SM3_SRC_MASTER"
    master_uv = mesh.uv_layers.get(master_name)
    had_prior_atlas = bool(obj.get("sm3_friend_atlas_png") or obj.get("sm3_friend_atlas_uv_export"))
    atlas_material_present = any(
        slot.material is not None and slot.material.name.startswith("SM3_ATLAS_")
        for slot in obj.material_slots
    )

    if master_uv is None:
        if had_prior_atlas or atlas_material_present:
            raise ValueError(
                "No trusted clean source-UV snapshot exists for this already-baked mesh. "
                "Do NOT guess/reconstruct UVs by face index. Reopen the original pre-bake saved .blend "
                "(or its .blend1 backup), select the joined WoS mesh, and run AUTO SETUP + BAKE once with v1.4.8. "
                "v1.4.8 will capture SM3_SRC_MASTER before packing and make future re-bakes non-destructive."
            )
        master_uv = _copy_uv_layer(mesh, export_uv, master_name)
        obj["sm3_source_uv_master_captured"] = True
        obj["sm3_source_uv_master_layer"] = master_name
        master_created = True
    else:
        master_created = False

    # Refresh the working source layer from the immutable master every bake.
    src_uv = _copy_uv_layer(mesh, master_uv, "SM3_SRC")
    src_uv_name = src_uv.name
    source_uv_reused = not master_created

    # Blender bake destination uses the mesh active/render UV. Explicitly lock it
    # to the packed export layer; source image sampling is separately forced through
    # SM3_SRC in the temporary bake materials below.
    mesh.uv_layers.active = mesh.uv_layers.get(export_uv_name)
    for layer in mesh.uv_layers:
        try:
            layer.active_render = (layer.name == export_uv_name)
        except Exception:
            pass

    # Pack the export UV islands in-place.
    prev_mode = obj.mode
    prev_active = bpy.context.view_layer.objects.active
    prev_selected = list(bpy.context.selected_objects)
    bpy.ops.object.mode_set(mode="OBJECT") if obj.mode != "OBJECT" else None
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    # SM3 Studio HQ: island rotation limited to QUARTER TURNS.
    # Measured on a photoreal suit (20,544 triangles) with rotate_method='ANY', the default:
    # 45.9 % of the surface ends up more than 2 deg away from a right angle, 17.0 % more than
    # 10 deg, p95 at 14.74 deg. The source texture is then resampled AT AN ANGLE: a fine regular
    # pattern -- fabric grain, web lines -- turns into stair steps and moire. 'CARDINAL' keeps the
    # benefit of rotation for the packing without ever sampling askew. The fallbacks keep older
    # Blender versions working: without rotate_method, then without rotation at all.
    for _kw in ({'rotate': True, 'rotate_method': 'CARDINAL'}, {'rotate': True}, {}):
        try:
            bpy.ops.uv.pack_islands(margin=uv_margin, **_kw)
            break
        except TypeError:
            continue
    bpy.ops.object.mode_set(mode="OBJECT")
    # IMPORTANT (Blender 4.5): pack_islands/edit-mode switching can reallocate
    # UV CustomData. Never use the MeshUVLoopLayer Python objects we held before
    # the operator; refresh the mesh and resolve layers by NAME below.
    try:
        mesh.update()
        bpy.context.view_layer.update()
    except Exception:
        pass
    export_uv_refreshed = mesh.uv_layers.get(export_uv_name)
    if export_uv_refreshed is None:
        raise ValueError(f"Export UV layer '{export_uv_name}' disappeared after packing")
    mesh.uv_layers.active = export_uv_refreshed
    for layer in mesh.uv_layers:
        try:
            layer.active_render = (layer.name == export_uv_name)
        except Exception:
            pass

    packed_triangles = _triangles_for_slots(mesh, export_uv_name, set(range(len(obj.material_slots))))
    packed_mask = _rasterize_uv_triangles(packed_triangles, size, size)
    if not packed_mask.any():
        raise ValueError("Packed UVs produced an empty coverage mask")

    original_materials = [slot.material for slot in obj.material_slots]
    temp_materials: List[bpy.types.Material] = []
    temp_images: Dict[int, bpy.types.Image] = {}
    image_slots: Dict[int, set[int]] = {}
    image_objects: Dict[int, bpy.types.Image] = {}

    # Discover every image used by each material slot so source dilation matches
    # the supplied research script rather than only touching one global image.
    for slot_index, mat in enumerate(original_materials):
        if mat is None or not mat.use_nodes or mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if node.bl_idname == "ShaderNodeTexImage" and node.image is not None:
                ptr = node.image.as_pointer()
                image_slots.setdefault(ptr, set()).add(slot_index)
                image_objects[ptr] = node.image

    # Build dilated in-memory copies; originals remain untouched.
    for ptr, src_image in image_objects.items():
        clone = src_image.copy()
        clone.name = f"SM3_TMP_DILATED_{src_image.name}"
        if source_dilate_passes:
            slots = image_slots.get(ptr, set())
            tris = _triangles_for_slots(mesh, src_uv_name, slots)
            if tris:
                w, h = int(clone.size[0]), int(clone.size[1])
                mask = _rasterize_uv_triangles(tris, w, h)
                if mask.any():
                    px = _image_pixels_srgb_u8(clone)
                    px = _dilate_fixed_passes_rgba(px, mask, source_dilate_passes)
                    _set_image_from_srgb_u8(clone, px)
        temp_images[ptr] = clone

    bake_image = bpy.data.images.new(f"{safe}_BAKE", width=size, height=size, alpha=False)
    try:
        bake_image.colorspace_settings.name = "sRGB"
    except Exception:
        pass

    # Temporary material copies let us force all image sampling through SM3_SRC
    # and set the bake target without mutating the user's authored materials.
    for slot_index, original in enumerate(original_materials):
        if original is None:
            temp_materials.append(None)
            continue
        mat = original.copy()
        mat.name = f"SM3_TMP_BAKE_{original.name}"
        mat.use_nodes = True
        nt = mat.node_tree
        uv_node = nt.nodes.new("ShaderNodeUVMap")
        uv_node.uv_map = src_uv_name
        for node in nt.nodes:
            if node.bl_idname == "ShaderNodeTexImage" and node.image is not None:
                replacement = temp_images.get(node.image.as_pointer())
                if replacement is not None:
                    node.image = replacement
                vector = node.inputs.get("Vector")
                if vector is not None:
                    for link in list(vector.links):
                        nt.links.remove(link)
                    nt.links.new(uv_node.outputs["UV"], vector)
        target = nt.nodes.new("ShaderNodeTexImage")
        target.name = "SM3_BAKE_TARGET"
        target.image = bake_image
        nt.nodes.active = target
        for node in nt.nodes:
            node.select = (node == target)
        obj.material_slots[slot_index].material = mat
        temp_materials.append(mat)

    scene = bpy.context.scene
    old_engine = scene.render.engine
    old_margin = int(scene.render.bake.margin)
    old_direct = bool(scene.render.bake.use_pass_direct)
    old_indirect = bool(scene.render.bake.use_pass_indirect)
    old_color = bool(scene.render.bake.use_pass_color)
    old_margin_type = getattr(scene.render.bake, "margin_type", None)

    try:
        scene.render.engine = "CYCLES"
        try:
            scene.cycles.samples = 1
            scene.cycles.device = "CPU"
            scene.cycles.use_denoising = False
        except Exception:
            pass
        scene.render.bake.use_pass_direct = False
        scene.render.bake.use_pass_indirect = False
        scene.render.bake.use_pass_color = True
        scene.render.bake.margin = max(4, int(round(uv_margin * size)))
        try:
            scene.render.bake.margin_type = "EXTEND"
        except Exception:
            pass
        bpy.ops.object.bake(type="DIFFUSE")

        bake_image.filepath_raw = str(baked_png)
        bake_image.file_format = "PNG"
        bake_image.save()

        baked = _image_pixels_srgb_u8(bake_image)
        final = _fill_background_nearest(baked, packed_mask)
        final = _boost_srgb(final, saturation, contrast)
        final_image = _save_srgb_png(final_png, final, f"{safe}_FINAL")

        # Blender Image.pixels is bottom-origin, while the proven friend pipeline
        # writes atlas_final.png and then reloads that PNG through Pillow before
        # DXT1 compression (top-origin row order).  Feeding Blender's raw pixel
        # buffer directly to DXT1 therefore vertically flips the .tex relative
        # to both the saved atlas PNG and the UVs exported to SM3.
        #
        # Keep Blender's in-memory orientation for preview/masks, but flip rows
        # exactly once for DDS/TEX serialization so the game sees the same atlas
        # orientation as atlas_final.png.
        # FIX 4/5 - the .tex must carry the SAME pixels as atlas_final.png.
        #
        # `final` comes from _image_pixels_srgb_u8(bake_image), and the bake target is a BYTE
        # image whose `pixels` already hold the sRGB-encoded value - so _linear_to_srgb is
        # applied a second time. `final` is therefore encoded TWICE.
        # atlas_final.png escapes it: _save_srgb_png stores _srgb_to_linear(final), which lands
        # back on the true albedo. The .tex was fed `final` raw, so it shipped about twice as
        # bright and desaturated.
        # Measured on one model: .tex 156.6 luminance against 108.3 for the PNG, and
        # srgb(108.3) = 156.5 - the curve, exactly.
        # Verified against stock: the addon's own PNG matches our corrected .tex on two other
        # models (120.7 vs 120.7, and 56.2 vs 56.2).
        #
        # We take the same transform _save_srgb_png applies, so .tex == PNG by construction.
        _tex_f = final.astype(np.float32) / 255.0
        _tex_f[:, :, :3] = _srgb_to_linear(_tex_f[:, :, :3])
        _tex_u8 = np.clip(_tex_f * 255.0 + 0.5, 0, 255).astype(np.uint8)
        tex_pixels_top_down = np.ascontiguousarray(_tex_u8[::-1, :, :])
        levels = build_dxt1_mips(tex_pixels_top_down)
        dds_report = write_dxt1_dds(dds_path, levels)
        tex_report = write_raw_sm3_dxt1_tex(tex_path, levels, filename_hash=int(texture_hash))

        if apply_preview_material:
            preview_mat = _atlas_preview_material(final_image, f"SM3_ATLAS_{safe}", export_uv_name)
            obj.data.materials.clear()
            obj.data.materials.append(preview_mat)
            for poly in obj.data.polygons:
                poly.material_index = 0
            # Keep Blender's default UV state aligned with the explicit preview node
            # and with the UV layer the SM3 exporter records as TEXCOORD0.
            export_uv_refreshed = mesh.uv_layers.get(export_uv_name)
            if export_uv_refreshed is not None:
                mesh.uv_layers.active = export_uv_refreshed
                for layer in mesh.uv_layers:
                    try:
                        layer.active_render = (layer.name == export_uv_name)
                    except Exception:
                        pass
        else:
            for i, original in enumerate(original_materials):
                if i < len(obj.material_slots):
                    obj.material_slots[i].material = original

        obj["sm3_friend_atlas_png"] = str(final_png)
        obj["sm3_friend_atlas_tex"] = str(tex_path)
        obj["sm3_friend_atlas_hash"] = f"0x{int(texture_hash)&0xFFFFFFFF:08X}"
        obj["sm3_friend_atlas_uv_source"] = src_uv_name
        obj["sm3_friend_atlas_uv_export"] = export_uv_name

        report = {
            "mode": "FRIEND_STYLE_BLENDER_BAKED_ATLAS",
            "object": obj.name,
            "source_material_count": len(original_materials),
            "source_image_count": len(image_objects),
            "size": [size, size],
            "uv_source_layer": src_uv_name,
            "uv_export_layer": export_uv_name,
            "source_uv_reused": bool(source_uv_reused),
            "source_uv_master_layer": master_name,
            "source_uv_master_created_this_run": bool(master_created),
            "source_uv_strategy": "PERSISTENT_CLEAN_BLEND_SNAPSHOT_NOT_FACE_INDEX_RECONSTRUCTION",
            "repeat_bake_safe": True,
            "preview_uv_layer": export_uv_name if apply_preview_material else None,
            "uv_margin": uv_margin,
            "margin_pixels": max(4, int(round(uv_margin * size))),
            "source_dilate_passes": source_dilate_passes,
            "packed_uv_coverage_percent": round(float(packed_mask.mean() * 100.0), 4),
            "full_background_dilation": True,
            "full_background_dilation_algorithm": "JUMP_FLOOD_NEAREST_ISLAND",
            "tex_row_orientation": "TOP_DOWN_MATCHES_SAVED_PNG_AND_PROVEN_FRIEND_TEX",
            "saturation": float(saturation),
            "contrast": float(contrast),
            "atlas_cuit_png": str(baked_png),
            "atlas_final_png": str(final_png),
            "dds": dds_report,
            "tex": tex_report,
            "texture_resource_name": texture_resource_name,
            "apply_preview_material": bool(apply_preview_material),
            "next_step": "Use SM3 Blender Toolkit > Prepare Selected Model -> Spider Atlas Section, then export the original Spider-Man target collection.",
        }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        report["report"] = str(report_path)
        return report
    finally:
        scene.render.engine = old_engine
        scene.render.bake.margin = old_margin
        scene.render.bake.use_pass_direct = old_direct
        scene.render.bake.use_pass_indirect = old_indirect
        scene.render.bake.use_pass_color = old_color
        if old_margin_type is not None:
            try: scene.render.bake.margin_type = old_margin_type
            except Exception: pass

        # If preview replacement did not happen because of an exception, restore.
        if len(obj.material_slots) == len(original_materials):
            for i, original in enumerate(original_materials):
                if obj.material_slots[i].material in temp_materials:
                    obj.material_slots[i].material = original
        for mat in temp_materials:
            if mat is not None and mat.users == 0:
                try: bpy.data.materials.remove(mat)
                except Exception: pass
        for image in temp_images.values():
            if image.users == 0:
                try: bpy.data.images.remove(image)
                except Exception: pass
        # Restore selection; keep the processed object active when possible.
        try:
            bpy.ops.object.select_all(action="DESELECT")
            for item in prev_selected:
                if item.name in bpy.data.objects:
                    item.select_set(True)
            if prev_active and prev_active.name in bpy.data.objects:
                bpy.context.view_layer.objects.active = prev_active
            else:
                bpy.context.view_layer.objects.active = obj
            if prev_mode != "OBJECT" and bpy.context.view_layer.objects.active == obj:
                bpy.ops.object.mode_set(mode=prev_mode)
        except Exception:
            pass
