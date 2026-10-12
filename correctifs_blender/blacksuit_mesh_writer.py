# SPDX-License-Identifier: GPL-3.0-or-later
"""blacksuit_mesh_writer.py - write a loose SM3 .mesh from a vanilla template and new sections.

THIRD-PARTY CODE, MODIFIED. This file is `sm3_mesh_writer.py` from TSGAMING264's "SM3 Blender
Toolkit" (https://github.com/TSGAMING264/SM3-Blender-Tools, GPL-3.0-or-later; identical in
toolkit versions 1.1.7 and 1.3.7), with the changes listed below. It is redistributed under the
same licence. Everything not listed is TSGAMING264's code and comments, unchanged.

Our changes (compared with toolkit 1.3.7 on 2026-10-12: 32 differing lines):
  1. import: `from sm3_blender_toolkit.sm3_format import ...` instead of the relative
     `from .sm3_format import ...`, so the file can live outside the add-on's package
     (sm3_sans_blender.py makes the installed toolkit importable under that name);
  2. "FIX 1/5": ExportVertex.color defaults to BLACK (0, 0, 0, 1) instead of white;
  3. "FIX 2/5": the UV divisor defaults to 1000 instead of 1024 (see tools/uv_1000.py);
  4. a comment on the 48-bone palette limit (the limit itself is the toolkit's);
  5. palette reservation: a palette shorter than 32 bones is padded to 32 entries by
     repeating its last bone (see the comment in write_raw_mesh).
The FIX numbering comes from our patch of the installed toolkit (fixes 3 to 5 live in other
files of that patch). Why a copy at all: transplanter_lod.py (stage `lod` of every red-suit
conversion), tools/blacksuit_build.py, tools/rvb_native.py and tools/cj_build.py need the writer
outside Blender, with these changes, whatever toolkit version is installed; the .exe bundles this
file (construire/SM3Studio.spec).
Where it lives: correctifs_blender/ ("Blender fixes"), the folder that holds every file derived
from TSGAMING264's code. Unlike sm3_baked_atlas.py next to it, this file is NOT meant to be
copied into Blender: SM3 Studio's own scripts import it from here (they add this folder to
sys.path). It used to be tools/blacksuit_mesh_writer.py (moved on 2026-10-12, unchanged).

Main entry points: ExportVertex, ExportSection, encode_player_vertex, write_raw_mesh(path,
template, sections, filename_hash=..., player_target=...).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import math
import struct
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sm3_blender_toolkit.sm3_format import SM3Mesh, VertexDecl, align, parse_mesh


SM3_SENTINEL = b"\xFF\x00\x00\x00\x11\x00\x00\x00"

# Canonical CH_SPIDERMAN vertex schemas recovered from the PC game.
# stream, offset, dtype, method, usage, usage_index
SM3_PLAYER000_DECL: Tuple[Tuple[int, int, int, int, int, int], ...] = (
    (0,  0,  7, 0,  0, 0),  # POSITION      SHORT4
    (0,  8,  6, 0,  5, 0),  # TEXCOORD0     SHORT2
    (0, 12,  4, 0, 10, 0),  # COLOR0        D3DCOLOR/UBYTE4
    (0, 16, 10, 0,  3, 0),  # NORMAL        SHORT4N
    (0, 24, 10, 0,  6, 0),  # TANGENT       SHORT4N
    (0, 32, 10, 0,  7, 0),  # BINORMAL      SHORT4N
    (0, 40,  5, 0,  2, 0),  # BLENDINDICES UBYTE4
    (0, 44, 10, 0,  1, 0),  # BLENDWEIGHT  SHORT4N
)
SM3_PLAYER000_STRIDE = 52

SM3_PLAYER001_DECL_48: Tuple[Tuple[int, int, int, int, int, int], ...] = (
    (0,  0,  7, 0,  0, 0),  # POSITION
    (0,  8,  6, 0,  5, 0),  # TEXCOORD0
    (0, 12, 10, 0,  3, 0),  # NORMAL
    (0, 20, 10, 0,  6, 0),  # TANGENT
    (0, 28, 10, 0,  7, 0),  # BINORMAL
    (0, 36,  5, 0,  2, 0),  # BLENDINDICES
    (0, 40, 10, 0,  1, 0),  # BLENDWEIGHT
)
SM3_PLAYER001_DECL_56: Tuple[Tuple[int, int, int, int, int, int], ...] = (
    (0,  0,  7, 0,  0, 0),  # POSITION
    (0,  8,  6, 0,  5, 0),  # TEXCOORD0
    (0, 12,  6, 0,  5, 1),  # TEXCOORD1
    (0, 16,  4, 0, 10, 0),  # COLOR0
    (0, 20, 10, 0,  3, 0),  # NORMAL
    (0, 28, 10, 0,  6, 0),  # TANGENT
    (0, 36, 10, 0,  7, 0),  # BINORMAL
    (0, 44,  5, 0,  2, 0),  # BLENDINDICES
    (0, 48, 10, 0,  1, 0),  # BLENDWEIGHT
)
SM3_PLAYER001_DECL_52 = SM3_PLAYER000_DECL


def _section_vertex_profile(template: SM3Mesh, player_target: str, section_index: int, geometry_profile: str = "TARGET_NATIVE"):
    """Return (stride, declaration, forced_position_divisor_or_None).

    Lite v0.7 uses the ORIGINAL imported target section as the native schema.
    This is the key generic-target change: Peter, New Goblin, Electro, Spider-Man,
    or any other imported SM3 MESH keeps its own vertex declaration instead of
    being forced through a ch_spiderman000/001 dropdown.
    """
    profile = str(geometry_profile or "TARGET_NATIVE").upper().strip()
    if profile not in {"TARGET_NATIVE", "TARGET_SCHEMA_UNIFORM", "STABLE_52"}:
        raise ValueError(f"unknown SM3 geometry_profile: {geometry_profile}")

    if profile == "STABLE_52":
        return 52, SM3_PLAYER000_DECL, None

    if template is not None and template.sections:
        idx = max(0, min(int(section_index), len(template.sections) - 1))
        sec = template.sections[idx]
        decl = tuple(
            (int(d.stream), int(d.offset), int(d.dtype), int(d.method), int(d.usage), int(d.usage_index))
            for d in sec.decl
        )
        return int(sec.vertex_stride), decl, None

    # Defensive fallback for legacy player-only calls.
    target = str(player_target or "").upper().strip()
    if target == "001":
        if int(section_index) == 0:
            return 48, SM3_PLAYER001_DECL_48, None
        if int(section_index) in (1, 2):
            return 56, SM3_PLAYER001_DECL_56, None
        return 52, SM3_PLAYER001_DECL_52, None
    return 52, SM3_PLAYER000_DECL, None


@dataclass
class ExportVertex:
    position: Tuple[float, float, float]
    uv: Tuple[float, float] = (0.0, 0.0)
    uv1: Optional[Tuple[float, float]] = None
    uv2: Optional[Tuple[float, float]] = None
    # FIX 1/5 - vertex colour must default to BLACK.
    # Measured on stock ch_spiderman000: [0, 0, 0, 255] on 29,674 of 55,180 vertices (every vertex of 8 of its 10 sections)
    # (D3DCOLOR at offset 12 of the 52-byte stride, byte order B,G,R,A).
    # White behaves as an ADDITIVE term: the whole body looks like light passes through it,
    # washed out, webbing drowned - and the saturating tone map pushes it further to white.
    color: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    color1: Optional[Tuple[float, float, float, float]] = None
    normal: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    tangent: Tuple[float, float, float] = (1.0, 0.0, 0.0)
    binormal: Tuple[float, float, float] = (0.0, 1.0, 0.0)
    # Global SM3 skeleton bone index + normalized weight.
    influences: Tuple[Tuple[int, float], ...] = ((0, 1.0),)


@dataclass
class ExportSection:
    source_object: str
    source_material_index: int
    material_ref_serialized: int
    vertices: List[ExportVertex]
    triangles: List[Tuple[int, int, int]]
    bone_palette: List[int]
    position_divisor: float = 512.0
    primitive_type: int = 4  # D3DPT_TRIANGLELIST for experimental exporter.
    primitive_unknown: int = 1
    unknown_30: int = 0
    unknown_38: int = 0
    unknown_40: int = 0
    # v0.5.7: optional native target section whose vertex declaration/divisor
    # should be used for this custom section. This lets material-driven output
    # use the correct 001 schema even when custom section order differs from
    # stock section order.
    schema_template_section: Optional[int] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class ExportBuildResult:
    output_path: str
    section_count: int
    vertex_count: int
    triangle_count: int
    img_size: int
    phys_size: int
    file_size: int
    filename_hash: int
    template_path: str
    report: Dict[str, object]


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _snorm16(value: float) -> int:
    value = _clamp(float(value), -1.0, 1.0)
    # Preserve -1 as -32767, matching the decoder's v/32767 convention.
    return int(round(value * 32767.0))


def _short(value: float) -> int:
    iv = int(round(value))
    if iv < -32768 or iv > 32767:
        raise ValueError(f"signed short overflow: {iv}")
    return iv


def _ubyte(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _normalize3(v: Sequence[float], fallback=(0.0, 0.0, 1.0)) -> Tuple[float, float, float]:
    x, y, z = float(v[0]), float(v[1]), float(v[2])
    length = math.sqrt(x*x + y*y + z*z)
    if length <= 1.0e-12:
        return tuple(float(x) for x in fallback)
    return (x/length, y/length, z/length)


def _normalize_influences(influences: Sequence[Tuple[int, float]]) -> Tuple[Tuple[int, float], ...]:
    cleaned = [(int(b), max(0.0, float(w))) for b, w in influences if float(w) > 1.0e-8]
    cleaned.sort(key=lambda x: x[1], reverse=True)
    cleaned = cleaned[:4]
    if not cleaned:
        return ((0, 1.0),)
    total = sum(w for _b, w in cleaned)
    if total <= 1.0e-12:
        return ((cleaned[0][0], 1.0),)
    return tuple((b, w / total) for b, w in cleaned)


def _quantized_weights(influences: Sequence[Tuple[int, float]]) -> Tuple[int, int, int, int]:
    norm = list(_normalize_influences(influences))
    vals = [0, 0, 0, 0]
    for i, (_b, w) in enumerate(norm[:4]):
        vals[i] = max(0, min(32767, int(round(w * 32767.0))))
    # Make the positive weights sum exactly 32767 to remove avoidable drift.
    active = [i for i, (_b, w) in enumerate(norm[:4]) if w > 0.0]
    if active:
        delta = 32767 - sum(vals)
        best = max(active, key=lambda i: vals[i])
        vals[best] = max(0, min(32767, vals[best] + delta))
    return tuple(vals)  # type: ignore[return-value]


def _bounds(vertices: Sequence[ExportVertex]):
    if not vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0
    xs = [v.position[0] for v in vertices]
    ys = [v.position[1] for v in vertices]
    zs = [v.position[2] for v in vertices]
    minv = (min(xs), min(ys), min(zs))
    maxv = (max(xs), max(ys), max(zs))
    center = tuple((minv[i] + maxv[i]) * 0.5 for i in range(3))
    half = tuple((maxv[i] - minv[i]) * 0.5 for i in range(3))
    radius = math.sqrt(sum(h*h for h in half))
    return center, half, radius


def _model_bounds(sections: Sequence[ExportSection]):
    points = [v.position for sec in sections for v in sec.vertices]
    if not points:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    minv = (min(xs), min(ys), min(zs))
    maxv = (max(xs), max(ys), max(zs))
    center = tuple((minv[i] + maxv[i]) * 0.5 for i in range(3))
    half = tuple((maxv[i] - minv[i]) * 0.5 for i in range(3))
    radius = math.sqrt(sum(h*h for h in half))
    return center, half, radius


def encode_player_vertex(
    vertex: ExportVertex,
    palette_lookup: Dict[int, int],
    position_divisor: float,
    # FIX 2/5 - the engine divides TEXCOORD0 by 1000, not 1024.
    # Character VS 006a19b0_vs30_169i.bin:  def c235, 0.001 ... mul o2.xy, c235.x, v1
    # with v1 = TEXCOORD0 per its input declarations. The position divisor in the same
    # shader is 0.00195312 = 1/512, which anchors the reading. At 1024 everything is
    # 2.4 % too large and whatever passes 1.0 wraps (ADDRESSU/V is WRAP).
    uv_divisor: float = 1000.0,
    *,
    stride: int = 52,
    decl: Optional[Sequence[Tuple[int, int, int, int, int, int]]] = None,
) -> bytes:
    """Encode one replacement vertex using the target's own D3D declaration.

    The old exporter only knew 48/52/56-byte Spider-Man layouts. The Lite writer
    still supports those, but TARGET_NATIVE now consumes the declaration parsed
    from the imported target MESH. Unsupported exotic semantics fail loudly
    instead of silently exporting the wrong character format.
    """
    if position_divisor <= 0.0:
        raise ValueError("position_divisor must be > 0")

    influences = _normalize_influences(vertex.influences)
    local_indices = [0, 0, 0, 0]
    for i, (global_bone, _weight) in enumerate(influences[:4]):
        if global_bone not in palette_lookup:
            raise ValueError(f"bone {global_bone} is not present in the section palette")
        local = int(palette_lookup[global_bone])
        if local < 0 or local > 255:
            raise ValueError(f"local palette index {local} exceeds UBYTE4")
        local_indices[i] = local

    weights = _quantized_weights(influences)

    # Legacy fixed layouts remain available for STABLE_52/fallback.
    if decl is None:
        px = _short(vertex.position[0] * position_divisor)
        py = _short(vertex.position[1] * position_divisor)
        pz = _short(vertex.position[2] * position_divisor)
        u0 = _short(vertex.uv[0] * uv_divisor)
        v0 = _short(vertex.uv[1] * uv_divisor)
        uv1 = vertex.uv1 if vertex.uv1 is not None else vertex.uv
        u1 = _short(uv1[0] * uv_divisor)
        v1 = _short(uv1[1] * uv_divisor)
        r, g, b, a = (_ubyte(_clamp(c, 0.0, 1.0) * 255.0) for c in vertex.color)
        nx, ny, nz = _normalize3(vertex.normal)
        tx, ty, tz = _normalize3(vertex.tangent, fallback=(1.0, 0.0, 0.0))
        bx, by, bz = _normalize3(vertex.binormal, fallback=(0.0, 1.0, 0.0))
        pos = struct.pack('<4h', px, py, pz, 0)
        uv0_bytes = struct.pack('<2h', u0, v0)
        uv1_bytes = struct.pack('<2h', u1, v1)
        color = struct.pack('<4B', r, g, b, a)
        normal = struct.pack('<4h', _snorm16(nx), _snorm16(ny), _snorm16(nz), 0)
        tangent = struct.pack('<4h', _snorm16(tx), _snorm16(ty), _snorm16(tz), 0)
        binormal = struct.pack('<4h', _snorm16(bx), _snorm16(by), _snorm16(bz), 0)
        blend_indices = struct.pack('<4B', *local_indices)
        blend_weights = struct.pack('<4h', *weights)
        if int(stride) == 48:
            out = pos + uv0_bytes + normal + tangent + binormal + blend_indices + blend_weights
        elif int(stride) == 56:
            out = pos + uv0_bytes + uv1_bytes + color + normal + tangent + binormal + blend_indices + blend_weights
        elif int(stride) == 52:
            out = pos + uv0_bytes + color + normal + tangent + binormal + blend_indices + blend_weights
        else:
            raise ValueError(f"unsupported fallback SM3 vertex stride: {stride}")
        if len(out) != int(stride):
            raise AssertionError(f"encoded vertex is {len(out)} bytes, expected {stride}")
        return out

    out = bytearray(int(stride))
    uv_sets = {
        0: vertex.uv,
        1: vertex.uv1 if vertex.uv1 is not None else vertex.uv,
        2: vertex.uv2 if vertex.uv2 is not None else (vertex.uv1 if vertex.uv1 is not None else vertex.uv),
    }
    vectors = {
        3: _normalize3(vertex.normal),
        6: _normalize3(vertex.tangent, fallback=(1.0, 0.0, 0.0)),
        7: _normalize3(vertex.binormal, fallback=(0.0, 1.0, 0.0)),
    }

    def write_at(offset: int, raw: bytes):
        end = int(offset) + len(raw)
        if int(offset) < 0 or end > len(out):
            raise ValueError(f"vertex declaration write 0x{int(offset):X}+{len(raw)} exceeds stride {len(out)}")
        out[int(offset):end] = raw

    for stream, offset, dtype, method, usage, usage_index in decl:
        if int(stream) != 0:
            raise ValueError(f"unsupported SM3 multi-stream vertex declaration: stream {stream}")
        dtype = int(dtype); usage = int(usage); usage_index = int(usage_index)

        if usage == 0:  # POSITION
            x, y, z = (float(vertex.position[0]), float(vertex.position[1]), float(vertex.position[2]))
            if dtype == 7:
                raw = struct.pack('<4h', _short(x * position_divisor), _short(y * position_divisor), _short(z * position_divisor), 0)
            elif dtype == 6:
                # Observed on SM3 LOD/billboard sections. Import preserves XY as raw SHORT2.
                raw = struct.pack('<2h', _short(x), _short(y))
            elif dtype == 2:
                raw = struct.pack('<3f', x, y, z)
            elif dtype == 3:
                raw = struct.pack('<4f', x, y, z, 1.0)
            elif dtype == 1:
                raw = struct.pack('<2f', x, y)
            elif dtype == 0:
                raw = struct.pack('<f', x)
            else:
                raise ValueError(f"unsupported target POSITION declaration type {dtype}")
            write_at(offset, raw); continue

        if usage == 5:  # TEXCOORD
            uv = uv_sets.get(usage_index, vertex.uv)
            u, v = float(uv[0]), float(uv[1])
            if dtype == 6:
                raw = struct.pack('<2h', _short(u * uv_divisor), _short(v * uv_divisor))
            elif dtype == 1:
                raw = struct.pack('<2f', u, v)
            elif dtype == 15:
                raw = struct.pack('<2e', u, v)
            elif dtype == 9:
                raw = struct.pack('<2h', _snorm16(u), _snorm16(v))
            elif dtype == 11:
                raw = struct.pack('<2H', int(_clamp(u,0.0,1.0)*65535.0+0.5), int(_clamp(v,0.0,1.0)*65535.0+0.5))
            else:
                raise ValueError(f"unsupported target TEXCOORD declaration type {dtype}")
            write_at(offset, raw); continue

        if usage == 10:  # COLOR
            source_color = vertex.color1 if usage_index == 1 and vertex.color1 is not None else vertex.color
            rgba = tuple(float(c) for c in source_color[:4])
            if dtype in (4, 5, 8):
                raw = struct.pack('<4B', *[_ubyte(_clamp(c,0.0,1.0)*255.0) for c in rgba])
            elif dtype == 3:
                raw = struct.pack('<4f', *rgba)
            elif dtype == 12:
                raw = struct.pack('<4H', *[int(_clamp(c,0.0,1.0)*65535.0+0.5) for c in rgba])
            else:
                raise ValueError(f"unsupported target COLOR declaration type {dtype}")
            write_at(offset, raw); continue

        if usage in vectors:  # NORMAL/TANGENT/BINORMAL
            x, y, z = vectors[usage]
            if dtype == 10:
                raw = struct.pack('<4h', _snorm16(x), _snorm16(y), _snorm16(z), 0)
            elif dtype == 2:
                raw = struct.pack('<3f', x, y, z)
            elif dtype == 3:
                raw = struct.pack('<4f', x, y, z, 0.0)
            elif dtype in (4, 5, 8):
                raw = struct.pack('<4B', *[_ubyte((_clamp(c,-1.0,1.0)*0.5+0.5)*255.0) for c in (x,y,z)], 255)
            elif dtype == 1:
                raw = struct.pack('<2f', x, y)
            else:
                raise ValueError(f"unsupported target vector declaration type {dtype} for usage {usage}")
            write_at(offset, raw); continue

        if usage == 2:  # BLENDINDICES
            if dtype in (4, 5):
                raw = struct.pack('<4B', *local_indices)
            elif dtype == 3:
                raw = struct.pack('<4f', *[float(v) for v in local_indices])
            else:
                raise ValueError(f"unsupported target BLENDINDICES declaration type {dtype}")
            write_at(offset, raw); continue

        if usage == 1:  # BLENDWEIGHT
            norm = list(_normalize_influences(influences))
            fweights = [0.0, 0.0, 0.0, 0.0]
            for i, (_b, w) in enumerate(norm[:4]):
                fweights[i] = float(w)
            if dtype == 10:
                raw = struct.pack('<4h', *weights)
            elif dtype == 8:
                vals = [int(_clamp(w,0.0,1.0)*255.0+0.5) for w in fweights]
                delta = 255 - sum(vals)
                if vals:
                    vals[max(range(4), key=lambda i: vals[i])] = max(0, min(255, vals[max(range(4), key=lambda i: vals[i])] + delta))
                raw = struct.pack('<4B', *vals)
            elif dtype == 12:
                vals = [int(_clamp(w,0.0,1.0)*65535.0+0.5) for w in fweights]
                delta = 65535 - sum(vals)
                best = max(range(4), key=lambda i: vals[i])
                vals[best] = max(0, min(65535, vals[best] + delta))
                raw = struct.pack('<4H', *vals)
            elif dtype == 3:
                raw = struct.pack('<4f', *fweights)
            else:
                raise ValueError(f"unsupported target BLENDWEIGHT declaration type {dtype}")
            write_at(offset, raw); continue

        # Unknown/nonessential usages are left zeroed. This is safer than
        # inventing a value and keeps the writer generic for extra declarations.

    return bytes(out)


def _write_u32(buf: bytearray, offset: int, value: int):
    struct.pack_into('<I', buf, offset, int(value) & 0xFFFFFFFF)


def build_raw_mesh_bytes(
    template: SM3Mesh,
    sections: Sequence[ExportSection],
    *,
    filename_hash: Optional[int] = None,
    default_material_section: int = 0,
    player_target: str = "000",
    geometry_profile: str = "TARGET_NATIVE",
) -> Tuple[bytes, Dict[str, object]]:
    if not sections:
        raise ValueError("No export sections were produced")
    if len(sections) > 4096:
        raise ValueError(f"Too many export sections: {len(sections)}")

    if filename_hash is None:
        filename_hash = template.filename_hash

    player_target = str(player_target or "AUTO").upper().strip()

    for sec_i, sec in enumerate(sections):
        if not sec.vertices:
            raise ValueError(f"section {sec_i} has no vertices")
        if not sec.triangles:
            raise ValueError(f"section {sec_i} has no triangles")
        if len(sec.bone_palette) > 255:
            raise ValueError(f"section {sec_i} palette has {len(sec.bone_palette)} bones; local indices are UBYTE4")
        # (SM3 Studio) WARNING: 48, not 32. Three independent measurements say so: the 12 skinned
        # vertex shaders of Game.exe declare `world` on c0..c191 (48 matrices); the game's
        # ch_spiderman000 ships three sections with 48 distinct bones; and the upstream writer of
        # TSGAMING264's toolkit (`sm3_mesh_writer.py`) allows 48. It was our copy that had been
        # lowered to 32, and that cost the forearms, the hands and all ten fingers on a full body.
        if len(sec.bone_palette) > 48:
            raise ValueError(f"section {sec_i} palette has {len(sec.bone_palette)} bones; SM3 safe skin-palette limit is 48")
        # (SM3 Studio) RESERVE the whole palette. It is frozen in the written file, and any later
        # skinning step can only fill the existing slots. With only the bones present at export
        # (often 30) it overflowed on a full body, which needs ~52, and the losers were the
        # lightest bones: `upperarm`, its three `split` bones, half of the fingers. Arms and hands
        # were left with no bone to follow. The extra slots repeat the last bone -- no vertex
        # points at them until they are filled, and palette_lookup returns the same global value
        # for a duplicate.
        # NOTE (2026-10-12): this copy pads to 32 entries, while the installed toolkit patched by
        # this project pads to 48. Kept as it is: changing it would change the written files.
        if sec.bone_palette and len(sec.bone_palette) < 32:
            sec.bone_palette = (list(sec.bone_palette)
                                + [sec.bone_palette[-1]] * (32 - len(sec.bone_palette)))
        if len(sec.vertices) > 0xFFFFFFFF:
            raise ValueError("vertex count exceeds 32-bit field")
        for tri in sec.triangles:
            if len(tri) != 3:
                raise ValueError(f"section {sec_i}: non-triangle index tuple")
            if any(i < 0 or i >= len(sec.vertices) for i in tri):
                raise ValueError(f"section {sec_i}: triangle index outside vertex range")

    # ---------------- IMG ----------------
    # Keep the template's identity/reference fields where they are meaningful to
    # the experimental NativeMESH path, but rebuild all local geometry pointers
    # as self-contained absolute offsets within this loose .mesh file.
    section_count = len(sections)
    img = bytearray(0x50 + section_count * 8)

    # Header.
    struct.pack_into('<IIII', img, 0x00,
                     template.filename_pointer_serialized,
                     filename_hash & 0xFFFFFFFF,
                     template.parsed_flags,
                     section_count)
    # Experimental self-contained pointer to section table.
    struct.pack_into('<IIII', img, 0x10,
                     0x50,
                     template.skeleton_ref_serialized,
                     template.external_mesh_count,
                     template.external_mesh_table_pointer_serialized)

    model_center, model_half, model_radius = _model_bounds(sections)
    struct.pack_into('<3f', img, 0x20, *model_center)
    struct.pack_into('<f', img, 0x2C, model_radius)
    struct.pack_into('<4f', img, 0x30, model_half[0], model_half[1], model_half[2], 0.0)

    # Preserve the 16-byte engine block after the model header when available.
    if len(template.raw) >= 0x50:
        img[0x40:0x50] = template.raw[0x40:0x50]

    while len(img) % 16:
        img.append(0)

    info_offsets: List[int] = []
    vb_pointer_fields: List[int] = []
    ib_pointer_fields: List[int] = []
    section_reports: List[Dict[str, object]] = []

    for i, sec in enumerate(sections):
        if i and len(img) % 16:
            img.extend(b'\x00' * (align(len(img), 16) - len(img)))

        info_offset = len(img)
        info_offsets.append(info_offset)
        # Section table uses a simple local-offset pointer for this experimental
        # loose format. NativeMESH can consume this directly without APKF fixups.
        struct.pack_into('<II', img, 0x50 + i * 8, 0, info_offset)

        center, half, radius = _bounds(sec.vertices)

        # Reserve MeshInfo and primitive header.
        img.extend(b'\x00' * 0x50)
        primitive_offset = len(img)
        img.extend(struct.pack('<II', int(sec.primitive_type), int(sec.primitive_unknown)))

        palette_offset = len(img)
        for bone in sec.bone_palette:
            if bone < 0 or bone > 0xFFFF:
                raise ValueError(f"section {i}: skeleton bone index {bone} exceeds ushort palette entry")
            img.extend(struct.pack('<H', int(bone)))
        if len(img) % 4:
            img.extend(b'\x00' * (align(len(img), 4) - len(img)))

        profile_section_index = (
            int(sec.schema_template_section)
            if sec.schema_template_section is not None
            else i
        )
        vertex_stride, vertex_decl, native_divisor = _section_vertex_profile(
            template, player_target, profile_section_index, geometry_profile
        )
        schema_table_offset = len(img)
        vertex_schema_offset = schema_table_offset + 12
        img.extend(struct.pack('<III', vertex_stride, vertex_schema_offset, 0))
        for decl in vertex_decl:
            img.extend(struct.pack('<HHBBBB', *decl))
        img.extend(SM3_SENTINEL)

        # Backfill MeshInfo except VB/IB, which are known after IMG size is fixed.
        material_ref = int(sec.material_ref_serialized) & 0xFFFFFFFF
        struct.pack_into('<8f', img, info_offset,
                         center[0], center[1], center[2], radius,
                         half[0], half[1], half[2], 0.0)
        struct.pack_into('<I', img, info_offset + 0x20, material_ref)
        struct.pack_into('<I', img, info_offset + 0x24, palette_offset if sec.bone_palette else 0)
        struct.pack_into('<I', img, info_offset + 0x28, len(sec.bone_palette))
        vb_pointer_fields.append(info_offset + 0x2C)
        struct.pack_into('<I', img, info_offset + 0x30, int(sec.unknown_30) & 0xFFFFFFFF)
        struct.pack_into('<I', img, info_offset + 0x34, len(sec.vertices))
        struct.pack_into('<I', img, info_offset + 0x38, int(sec.unknown_38) & 0xFFFFFFFF)
        ib_pointer_fields.append(info_offset + 0x3C)
        struct.pack_into('<I', img, info_offset + 0x40, int(sec.unknown_40) & 0xFFFFFFFF)
        index_count = len(sec.triangles) * 3
        index_size = 4 if len(sec.vertices) > 65535 else 2
        struct.pack_into('<I', img, info_offset + 0x44, index_count)
        struct.pack_into('<I', img, info_offset + 0x48, index_size)
        struct.pack_into('<I', img, info_offset + 0x4C, schema_table_offset)

        section_reports.append({
            'index': i,
            'source_object': sec.source_object,
            'source_material_index': sec.source_material_index,
            'material_ref_serialized': f"0x{material_ref:08X}",
            'vertex_count': len(sec.vertices),
            'triangle_count': len(sec.triangles),
            'bone_palette_count': len(sec.bone_palette),
            'bone_palette': list(sec.bone_palette),
            'position_divisor': float(native_divisor if native_divisor is not None else sec.position_divisor),
            'vertex_stride': int(vertex_stride),
            'schema_template_section': (
                int(sec.schema_template_section)
                if sec.schema_template_section is not None
                else int(i)
            ),
            'primitive_type': int(sec.primitive_type),
            'info_offset': info_offset,
            'palette_offset': palette_offset,
            'schema_table_offset': schema_table_offset,
            'vertex_schema_offset': vertex_schema_offset,
            'warnings': list(sec.warnings),
        })

    img_size = len(img)

    # ---------------- PHYS ----------------
    out = bytearray(img)
    phys_start = len(out)
    for i, sec in enumerate(sections):
        palette_lookup = {bone: idx for idx, bone in enumerate(sec.bone_palette)}

        profile_section_index = (
            int(sec.schema_template_section)
            if sec.schema_template_section is not None
            else i
        )
        vertex_stride, _vertex_decl, native_divisor = _section_vertex_profile(
            template, player_target, profile_section_index, geometry_profile
        )
        encode_divisor = float(native_divisor if native_divisor is not None else sec.position_divisor)
        vb_offset = len(out)
        _write_u32(out, vb_pointer_fields[i], vb_offset)
        for vertex in sec.vertices:
            out.extend(encode_player_vertex(
                vertex,
                palette_lookup,
                encode_divisor,
                stride=vertex_stride,
                decl=_vertex_decl,
            ))

        if len(out) % 4:
            out.extend(b'\x00' * (align(len(out), 4) - len(out)))

        ib_offset = len(out)
        _write_u32(out, ib_pointer_fields[i], ib_offset)
        flat = [idx for tri in sec.triangles for idx in tri]
        if len(sec.vertices) > 65535:
            out.extend(struct.pack('<' + 'I' * len(flat), *flat))
        else:
            if any(idx > 0xFFFF for idx in flat):
                raise ValueError(f"section {i}: ushort index overflow")
            out.extend(struct.pack('<' + 'H' * len(flat), *flat))

        if i != len(sections) - 1 and len(out) % 4:
            out.extend(b'\x00' * (align(len(out), 4) - len(out)))

        section_reports[i]['vertex_buffer_offset'] = vb_offset
        section_reports[i]['index_buffer_offset'] = ib_offset
        section_reports[i]['vertex_stride'] = int(vertex_stride)
        section_reports[i]['index_size'] = 4 if len(sec.vertices) > 65535 else 2

    phys_size = len(out) - phys_start
    report = {
        'format': 'SM3_RAW_MESH_EXPERIMENTAL_LOCAL_POINTERS_V1',
        'pointer_mode': 'LOCAL_FILE_OFFSETS_FOR_NATIVEMESH_EXPERIMENTAL',
        'filename_hash': f"0x{filename_hash & 0xFFFFFFFF:08X}",
        'template_path': template.path,
        'template_filename_hash': f"0x{template.filename_hash:08X}",
        'skeleton_ref_serialized_preserved': f"0x{template.skeleton_ref_serialized:08X}",
        'section_count': section_count,
        'vertex_count': sum(len(s.vertices) for s in sections),
        'triangle_count': sum(len(s.triangles) for s in sections),
        'img_size': img_size,
        'phys_size': phys_size,
        'file_size': len(out),
        'model_center': model_center,
        'model_half_extents': model_half,
        'model_sphere_radius': model_radius,
        'target_profile': player_target,
        'geometry_profile': str(geometry_profile),
        'vertex_strides': [
            int(_section_vertex_profile(
                template, player_target,
                int(sections[i].schema_template_section)
                if sections[i].schema_template_section is not None
                else i,
                geometry_profile,
            )[0])
            for i in range(section_count)
        ],
        'position_encoding': 'SHORT4 position * section_divisor',
        'uv_encoding': 'SHORT2 uv * 1024',
        'normal_tangent_binormal': 'SHORT4N',
        'blend_indices': 'UBYTE4 local palette indices',
        'blend_weights': 'SHORT4N positive normalized to 32767',
        'sections': section_reports,
    }
    return bytes(out), report


def write_raw_mesh(
    output_path: str,
    template: SM3Mesh,
    sections: Sequence[ExportSection],
    *,
    filename_hash: Optional[int] = None,
    player_target: str = "000",
    geometry_profile: str = "TARGET_NATIVE",
) -> ExportBuildResult:
    raw, report = build_raw_mesh_bytes(
        template,
        sections,
        filename_hash=filename_hash,
        player_target=player_target,
        geometry_profile=geometry_profile,
    )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)

    # Structural validation using our independent SM3 parser.
    parsed = parse_mesh(out)
    if parsed.section_count != len(sections):
        raise ValueError(f"roundtrip section count mismatch: {parsed.section_count} vs {len(sections)}")
    if len(parsed.raw) != len(raw):
        raise ValueError("roundtrip file-size mismatch")

    report['roundtrip_parse'] = 'PASS'
    report['roundtrip_img_size'] = parsed.img_size
    report['roundtrip_phys_size'] = parsed.phys_size

    return ExportBuildResult(
        output_path=str(out),
        section_count=len(sections),
        vertex_count=sum(len(s.vertices) for s in sections),
        triangle_count=sum(len(s.triangles) for s in sections),
        img_size=parsed.img_size,
        phys_size=parsed.phys_size,
        file_size=len(raw),
        filename_hash=parsed.filename_hash,
        template_path=template.path,
        report=report,
    )

