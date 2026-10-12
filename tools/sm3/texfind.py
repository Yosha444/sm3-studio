# SPDX-License-Identifier: GPL-3.0-or-later
"""texfind - texture decoding + identification toolkit for Spider-Man 3 (PC) files.

Where it sits in SM3 Studio: decode_level() is the INDEPENDENT decoder used to check our own
encoders (tools/sm3/dxtenc_selftest.py, the texture check of tools/blacksuit_package.py) and to
read the game's textures (tools/venom_textures.py, tools/venom_native_textures.py,
support_venom_direct/make_atlas.py). The rest (DDS parsing, likeness score, brute-force scanner,
command line) comes from the early reverse-engineering of the game files, when texture formats
were still being identified; the conversion itself does not use it.

Pure numpy, no external decoding deps (Pillow only used, optionally, to save PNGs).

Ground truth this module was validated against (in the research notes of that work, not
distributed; GAME = the Spider-Man 3 folder, see texfind_selftest.py):
  GAME\\pcinterface\\Fullkeyset_2048_eng.dds  -> DXT5 (BC3), 2048x2048, 1 mip
  GAME\\pcinterface\\waterwaves_9mips.dds     -> X8R8G8B8, 256x256, 9 mips

Public API
----------
Decoders (all return an (h, w, 4) uint8 RGBA numpy array; `data` is any
bytes-like object whose start is the first byte of the texture level):

    dxt1_decode(data, w, h)     BC1: 8 B / 4x4 block, 1-bit punch-through alpha
    dxt3_decode(data, w, h)     BC2: 16 B / block, explicit 4-bit alpha
    dxt5_decode(data, w, h)     BC3: 16 B / block, interpolated 3-bit alpha
    bc4_decode(data, w, h)      ATI1/BC4: 8 B / block, single channel (shown as gray)
    bc5_decode(data, w, h)      ATI2/BC5: 16 B / block, two channels (R,G; B=0)
    a8r8g8b8_decode(data, w, h) raw 32bpp, D3DFMT_A8R8G8B8 byte order B,G,R,A
    x8r8g8b8_decode(data, w, h) same but alpha forced opaque
    r5g6b5_decode(data, w, h)   raw 16bpp
    a1r5g5b5_decode(data, w, h) raw 16bpp
    a4r4g4b4_decode(data, w, h) raw 16bpp
    a8_decode(data, w, h)       raw 8bpp alpha (shown as grayscale, A=255)
    l8_decode(data, w, h)       raw 8bpp luminance
    a8l8_decode(data, w, h)     raw 16bpp luminance+alpha

Format registry / sizes:

    FORMATS                     dict name -> FormatInfo
    format_data_size(fmt, w, h) exact byte count of one w*h level in format fmt
    mip_chain_size(fmt, w, h, mips)
    decode_level(data, fmt, w, h)

DDS (headers parsed by hand — layout documented at parse_dds below):

    parse_dds(data)             -> DDSInfo (raises ValueError if not DDS)
    decode_dds(data)            -> list of (mip_index, w, h, rgba) for every mip

Identification:

    image_likeness_score(rgba)  -> float in [0, 1]; ~0 for noise/flat data,
                                   typically > 0.7 for correctly decoded textures
    scan_for_textures(data, ...) -> ranked list of Candidate

CLI:

    python texfind.py info FILE.dds
    python texfind.py dds FILE.dds -o out.png [--mip N | --all-mips]
    python texfind.py decode FILE --format dxt5 --width 256 --height 256
                      [--offset 0] [-o out.png]
    python texfind.py scan FILE [--formats dxt1,dxt5,a8r8g8b8] [--step 2048]
                      [--min-dim 16] [--max-dim 2048] [--threshold 0.5]
                      [--top 30] [--save-dir DIR]

Implementation notes
--------------------
* All block decoders are fully vectorised: the file bytes are viewed as an
  (n_blocks, block_bytes) array, palettes are built for every block at once,
  and pixels are gathered with np.take_along_axis. A 2048x2048 DXT5 texture
  (262,144 blocks) decodes in ~0.25 s.
* DXT1 honours the c0<=c1 "3-colour + transparent" mode. DXT3/DXT5 colour
  blocks are always decoded in 4-colour mode (per the D3D spec the c0/c1
  comparison is ignored for BC2/BC3).
* 565 -> 888 expansion uses bit replication ((r<<3)|(r>>2)), matching the D3D
  reference rasteriser.
* Interpolated colours use integer maths with round-to-nearest bias
  ((2a+b+1)//3 etc.). Real hardware decoders differ by +-1 LSB here; the
  self-tests use exactly-divisible vectors so they are rounding-agnostic.
* image_likeness_score keys on lag-1 autocorrelation restricted to 4-pixel
  block boundaries. Measured on ground truth (with a probe script of that work):
  real textures ~0.91-0.99 boundary correlation, DXT-decoded random noise
  ~0.00 (plain autocorrelation would be fooled at ~0.3-0.5 because palette
  blocks are internally smooth). Known limitation: a genuinely noisy texture
  (e.g. a stored white-noise/dither map) will score low.
"""
from __future__ import annotations

import argparse
import math
import os
import struct
import sys
from dataclasses import dataclass

import numpy as np

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _as_u8(data, count: int, what: str) -> np.ndarray:
    """View the first `count` bytes of a bytes-like object as a uint8 array."""
    buf = memoryview(data)
    if len(buf) < count:
        raise ValueError(f"{what}: need {count} bytes, have {len(buf)}")
    return np.frombuffer(buf, dtype=np.uint8, count=count)


def _expand565(c: np.ndarray):
    """RGB565 (uint arrays) -> (r, g, b) uint8 arrays with bit replication."""
    c = c.astype(np.uint32)
    r = (c >> 11) & 0x1F
    g = (c >> 5) & 0x3F
    b = c & 0x1F
    r = ((r << 3) | (r >> 2)).astype(np.uint8)
    g = ((g << 2) | (g >> 4)).astype(np.uint8)
    b = ((b << 3) | (b >> 2)).astype(np.uint8)
    return r, g, b


def _assemble_blocks(rgba: np.ndarray, w: int, h: int, bw: int, bh: int) -> np.ndarray:
    """(n_blocks, 16, 4) block pixels (row-major blocks, row-major pixels)
    -> (h, w, 4) image, cropping any partial right/bottom block."""
    img = rgba.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    if img.shape[0] != h or img.shape[1] != w:
        img = img[:h, :w]
    return np.ascontiguousarray(img)


def _block_counts(w: int, h: int):
    return (w + 3) // 4, (h + 3) // 4


# --------------------------------------------------------------------------
# block-stage decoders: (n_blocks, block_bytes) uint8 -> (n_blocks, 16, 4) RGBA
# (exposed separately so the scanner can decode once per offset and re-assemble
#  the same blocks under several width hypotheses)
# --------------------------------------------------------------------------


def _color_block_pixels(u16: np.ndarray, dxt1_mode: bool) -> np.ndarray:
    """Decode the 8-byte DXT colour block shared by BC1/BC2/BC3.

    u16: (n, 4) little-endian uint16 view: c0, c1, then 32 bits of 2-bit indices.
    dxt1_mode: if True, honour c0<=c1 (3 colours + transparent black); if False
    (BC2/BC3) always use 4-colour opaque mode.
    """
    n = u16.shape[0]
    c0 = u16[:, 0].astype(np.uint32)
    c1 = u16[:, 1].astype(np.uint32)
    bits = u16[:, 2].astype(np.uint32) | (u16[:, 3].astype(np.uint32) << np.uint32(16))

    r0, g0, b0 = _expand565(c0)
    r1, g1, b1 = _expand565(c1)

    pal = np.empty((n, 4, 4), np.uint8)
    pal[:, :, 3] = 255
    four = (c0 > c1) if dxt1_mode else np.ones(n, bool)
    for ch, (a, b) in enumerate(((r0, r1), (g0, g1), (b0, b1))):
        a16 = a.astype(np.uint16)
        b16 = b.astype(np.uint16)
        pal[:, 0, ch] = a
        pal[:, 1, ch] = b
        pal[:, 2, ch] = np.where(four, (2 * a16 + b16 + 1) // 3, (a16 + b16) // 2).astype(np.uint8)
        pal[:, 3, ch] = np.where(four, (a16 + 2 * b16 + 1) // 3, 0).astype(np.uint8)
    if dxt1_mode:
        pal[:, 3, 3] = np.where(four, 255, 0).astype(np.uint8)

    shifts = 2 * np.arange(16, dtype=np.uint32)
    idx = ((bits[:, None] >> shifts) & np.uint32(3)).astype(np.intp)  # (n, 16)
    idx += (np.arange(n, dtype=np.intp) * 4)[:, None]
    return pal.reshape(-1, 4).take(idx.ravel(), axis=0).reshape(n, 16, 4)


def _alpha_block_values(blk8: np.ndarray) -> np.ndarray:
    """Decode the 8-byte BC3/BC4 interpolated-alpha block.

    blk8: (n, 8) uint8: a0, a1, then 48 bits of 3-bit indices.
    Returns (n, 16) uint8 values.
    """
    n = blk8.shape[0]
    a0 = blk8[:, 0]
    a1 = blk8[:, 1]
    a0i = a0.astype(np.int32)
    a1i = a1.astype(np.int32)

    pal = np.empty((n, 8), np.uint8)
    pal[:, 0] = a0
    pal[:, 1] = a1
    m = a0 > a1
    for i in range(2, 8):
        v7 = ((8 - i) * a0i + (i - 1) * a1i + 3) // 7           # 8-value mode
        if i < 6:                                               # 6-value mode
            v5 = ((6 - i) * a0i + (i - 1) * a1i + 2) // 5
        elif i == 6:
            v5 = np.zeros(n, np.int32)
        else:
            v5 = np.full(n, 255, np.int32)
        pal[:, i] = np.where(m, v7, v5).astype(np.uint8)

    bits = np.zeros(n, np.uint64)
    for i in range(6):
        bits |= blk8[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    shifts = 3 * np.arange(16, dtype=np.uint64)
    idx = ((bits[:, None] >> shifts) & np.uint64(7)).astype(np.intp)
    idx += (np.arange(n, dtype=np.intp) * 8)[:, None]
    return pal.reshape(-1).take(idx.ravel()).reshape(n, 16)  # (n, 16)


def _blocks_dxt1(blk: np.ndarray) -> np.ndarray:
    return _color_block_pixels(np.ascontiguousarray(blk).view("<u2"), dxt1_mode=True)


def _blocks_dxt3(blk: np.ndarray) -> np.ndarray:
    rgba = _color_block_pixels(np.ascontiguousarray(blk[:, 8:]).view("<u2"), dxt1_mode=False)
    ab = blk[:, :8]
    n = blk.shape[0]
    alpha = np.empty((n, 16), np.uint8)
    alpha[:, 0::2] = (ab & 0x0F) * 17
    alpha[:, 1::2] = (ab >> 4) * 17
    rgba[:, :, 3] = alpha
    return rgba


def _blocks_dxt5(blk: np.ndarray) -> np.ndarray:
    rgba = _color_block_pixels(np.ascontiguousarray(blk[:, 8:]).view("<u2"), dxt1_mode=False)
    rgba[:, :, 3] = _alpha_block_values(np.ascontiguousarray(blk[:, :8]))
    return rgba


def _blocks_bc4(blk: np.ndarray) -> np.ndarray:
    v = _alpha_block_values(np.ascontiguousarray(blk))
    rgba = np.empty((blk.shape[0], 16, 4), np.uint8)
    rgba[:, :, 0] = v
    rgba[:, :, 1] = v
    rgba[:, :, 2] = v
    rgba[:, :, 3] = 255
    return rgba


def _blocks_bc5(blk: np.ndarray) -> np.ndarray:
    x = _alpha_block_values(np.ascontiguousarray(blk[:, :8]))
    y = _alpha_block_values(np.ascontiguousarray(blk[:, 8:]))
    rgba = np.empty((blk.shape[0], 16, 4), np.uint8)
    rgba[:, :, 0] = x
    rgba[:, :, 1] = y
    rgba[:, :, 2] = 0
    rgba[:, :, 3] = 255
    return rgba


# --------------------------------------------------------------------------
# pixel-stage decoders for raw formats: bytes -> (n_pixels, 4) RGBA
# --------------------------------------------------------------------------


def _pixels_a8r8g8b8(data, npix: int) -> np.ndarray:
    px = _as_u8(data, npix * 4, "a8r8g8b8").view("<u4")
    out = np.empty((npix, 4), np.uint8)
    out[:, 0] = (px >> 16) & 0xFF
    out[:, 1] = (px >> 8) & 0xFF
    out[:, 2] = px & 0xFF
    out[:, 3] = (px >> 24) & 0xFF
    return out


def _pixels_x8r8g8b8(data, npix: int) -> np.ndarray:
    out = _pixels_a8r8g8b8(data, npix)
    out[:, 3] = 255
    return out


def _pixels_r5g6b5(data, npix: int) -> np.ndarray:
    px = _as_u8(data, npix * 2, "r5g6b5").view("<u2")
    r, g, b = _expand565(px)
    out = np.empty((npix, 4), np.uint8)
    out[:, 0] = r
    out[:, 1] = g
    out[:, 2] = b
    out[:, 3] = 255
    return out


def _pixels_a1r5g5b5(data, npix: int) -> np.ndarray:
    px = _as_u8(data, npix * 2, "a1r5g5b5").view("<u2").astype(np.uint32)
    out = np.empty((npix, 4), np.uint8)
    for ch, shift in ((0, 10), (1, 5), (2, 0)):
        v = (px >> shift) & 0x1F
        out[:, ch] = ((v << 3) | (v >> 2)).astype(np.uint8)
    out[:, 3] = ((px >> 15) & 1).astype(np.uint8) * 255
    return out


def _pixels_a4r4g4b4(data, npix: int) -> np.ndarray:
    px = _as_u8(data, npix * 2, "a4r4g4b4").view("<u2").astype(np.uint32)
    out = np.empty((npix, 4), np.uint8)
    for ch, shift in ((0, 8), (1, 4), (2, 0), (3, 12)):
        out[:, ch] = (((px >> shift) & 0xF) * 17).astype(np.uint8)
    return out


def _pixels_a8(data, npix: int) -> np.ndarray:
    v = _as_u8(data, npix, "a8")
    out = np.empty((npix, 4), np.uint8)
    out[:, 0] = v
    out[:, 1] = v
    out[:, 2] = v
    out[:, 3] = 255
    return out


def _pixels_a8l8(data, npix: int) -> np.ndarray:
    px = _as_u8(data, npix * 2, "a8l8").reshape(npix, 2)
    out = np.empty((npix, 4), np.uint8)
    out[:, 0] = px[:, 0]
    out[:, 1] = px[:, 0]
    out[:, 2] = px[:, 0]
    out[:, 3] = px[:, 1]
    return out


# --------------------------------------------------------------------------
# public per-level decoders
# --------------------------------------------------------------------------


def _make_block_decoder(blocks_fn, block_bytes, name):
    def decode(data, w: int, h: int) -> np.ndarray:
        bw, bh = _block_counts(w, h)
        n = bw * bh
        blk = _as_u8(data, n * block_bytes, name).reshape(n, block_bytes)
        return _assemble_blocks(blocks_fn(blk), w, h, bw, bh)
    decode.__name__ = f"{name}_decode"
    return decode


def _make_raw_decoder(pixels_fn, name):
    def decode(data, w: int, h: int) -> np.ndarray:
        return pixels_fn(data, w * h).reshape(h, w, 4)
    decode.__name__ = f"{name}_decode"
    return decode


dxt1_decode = _make_block_decoder(_blocks_dxt1, 8, "dxt1")
dxt3_decode = _make_block_decoder(_blocks_dxt3, 16, "dxt3")
dxt5_decode = _make_block_decoder(_blocks_dxt5, 16, "dxt5")
bc4_decode = _make_block_decoder(_blocks_bc4, 8, "bc4")
bc5_decode = _make_block_decoder(_blocks_bc5, 16, "bc5")
a8r8g8b8_decode = _make_raw_decoder(_pixels_a8r8g8b8, "a8r8g8b8")
x8r8g8b8_decode = _make_raw_decoder(_pixels_x8r8g8b8, "x8r8g8b8")
r5g6b5_decode = _make_raw_decoder(_pixels_r5g6b5, "r5g6b5")
a1r5g5b5_decode = _make_raw_decoder(_pixels_a1r5g5b5, "a1r5g5b5")
a4r4g4b4_decode = _make_raw_decoder(_pixels_a4r4g4b4, "a4r4g4b4")
a8_decode = _make_raw_decoder(_pixels_a8, "a8")
l8_decode = _make_raw_decoder(_pixels_a8, "l8")   # same presentation, clearer name
a8l8_decode = _make_raw_decoder(_pixels_a8l8, "a8l8")


# --------------------------------------------------------------------------
# format registry
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FormatInfo:
    name: str
    decode: object            # callable(data, w, h) -> (h, w, 4) uint8
    block: bool               # True = 4x4 block compressed
    bytes_per_unit: int       # per block if block, per pixel if raw
    stage: object             # blocks_fn (block fmts) or pixels_fn (raw fmts)


FORMATS: dict[str, FormatInfo] = {
    "dxt1":     FormatInfo("dxt1", dxt1_decode, True, 8, _blocks_dxt1),
    "dxt3":     FormatInfo("dxt3", dxt3_decode, True, 16, _blocks_dxt3),
    "dxt5":     FormatInfo("dxt5", dxt5_decode, True, 16, _blocks_dxt5),
    "bc4":      FormatInfo("bc4", bc4_decode, True, 8, _blocks_bc4),
    "bc5":      FormatInfo("bc5", bc5_decode, True, 16, _blocks_bc5),
    "a8r8g8b8": FormatInfo("a8r8g8b8", a8r8g8b8_decode, False, 4, _pixels_a8r8g8b8),
    "x8r8g8b8": FormatInfo("x8r8g8b8", x8r8g8b8_decode, False, 4, _pixels_x8r8g8b8),
    "r5g6b5":   FormatInfo("r5g6b5", r5g6b5_decode, False, 2, _pixels_r5g6b5),
    "a1r5g5b5": FormatInfo("a1r5g5b5", a1r5g5b5_decode, False, 2, _pixels_a1r5g5b5),
    "a4r4g4b4": FormatInfo("a4r4g4b4", a4r4g4b4_decode, False, 2, _pixels_a4r4g4b4),
    "a8":       FormatInfo("a8", a8_decode, False, 1, _pixels_a8),
    "l8":       FormatInfo("l8", l8_decode, False, 1, _pixels_a8),
    "a8l8":     FormatInfo("a8l8", a8l8_decode, False, 2, _pixels_a8l8),
}


def format_data_size(fmt: str, w: int, h: int) -> int:
    """Exact byte size of one w*h mip level stored in format `fmt`."""
    info = FORMATS[fmt]
    if info.block:
        bw, bh = _block_counts(w, h)
        return bw * bh * info.bytes_per_unit
    return w * h * info.bytes_per_unit


def mip_chain_size(fmt: str, w: int, h: int, mips: int) -> int:
    total = 0
    for _ in range(max(1, mips)):
        total += format_data_size(fmt, w, h)
        w, h = max(1, w // 2), max(1, h // 2)
    return total


def decode_level(data, fmt: str, w: int, h: int) -> np.ndarray:
    return FORMATS[fmt].decode(data, w, h)


# --------------------------------------------------------------------------
# DDS container (header parsed by hand)
# --------------------------------------------------------------------------
#
# DDS file layout (all little-endian dwords):
#   +0x00  magic 'DDS ' (0x20534444)
#   +0x04  DDS_HEADER, 124 bytes:
#     +0x00 dwSize (=124)      +0x04 dwFlags        +0x08 dwHeight
#     +0x0C dwWidth            +0x10 dwPitchOrLinearSize
#     +0x14 dwDepth            +0x18 dwMipMapCount  +0x1C dwReserved1[11]
#     +0x48 DDS_PIXELFORMAT, 32 bytes:
#       +0x00 dwSize (=32)  +0x04 dwFlags  +0x08 dwFourCC  +0x0C dwRGBBitCount
#       +0x10 dwRBitMask  +0x14 dwGBitMask  +0x18 dwBBitMask  +0x1C dwABitMask
#     +0x68 dwCaps  +0x6C dwCaps2  +0x70 dwCaps3  +0x74 dwCaps4  +0x78 dwReserved2
#   +0x80  pixel data, mip levels back to back, largest first.
#
# dwFlags bits: 0x1 CAPS, 0x2 HEIGHT, 0x4 WIDTH, 0x8 PITCH, 0x1000 PIXELFORMAT,
#               0x20000 MIPMAPCOUNT, 0x80000 LINEARSIZE, 0x800000 DEPTH
# pf dwFlags:   0x1 ALPHAPIXELS, 0x2 ALPHA, 0x4 FOURCC, 0x40 RGB, 0x20000 LUMINANCE
# caps1:        0x8 COMPLEX, 0x1000 TEXTURE, 0x400000 MIPMAP

DDS_MAGIC = b"DDS "
_FOURCC_TO_FMT = {
    b"DXT1": "dxt1", b"DXT2": "dxt3", b"DXT3": "dxt3",
    b"DXT4": "dxt5", b"DXT5": "dxt5",
    b"ATI1": "bc4", b"BC4U": "bc4",
    b"ATI2": "bc5", b"BC5U": "bc5",
}
# (bitcount, rmask, gmask, bmask, amask) -> fmt, for non-FourCC pixel formats
_MASKS_TO_FMT = {
    (32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000): "a8r8g8b8",
    (32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0x00000000): "x8r8g8b8",
    (16, 0x0000F800, 0x000007E0, 0x0000001F, 0x00000000): "r5g6b5",
    (16, 0x00007C00, 0x000003E0, 0x0000001F, 0x00008000): "a1r5g5b5",
    (16, 0x00000F00, 0x000000F0, 0x0000000F, 0x0000F000): "a4r4g4b4",
    (8,  0x000000FF, 0x00000000, 0x00000000, 0x00000000): "l8",
    (8,  0x00000000, 0x00000000, 0x00000000, 0x000000FF): "a8",
    (16, 0x000000FF, 0x00000000, 0x00000000, 0x0000FF00): "a8l8",
}


@dataclass
class DDSInfo:
    width: int
    height: int
    mip_count: int            # raw header value (0 or 1 both mean "one level")
    flags: int
    pitch_or_linear: int
    depth: int
    pf_flags: int
    fourcc: bytes
    bitcount: int
    masks: tuple              # (r, g, b, a)
    caps1: int
    caps2: int
    fmt: str                  # texfind format name, or '?' if unrecognised
    data_offset: int = 128
    body_size: int = 0        # bytes present after the header

    @property
    def levels(self) -> int:
        return max(1, self.mip_count)


def parse_dds(data) -> DDSInfo:
    buf = memoryview(data)
    if len(buf) < 128 or bytes(buf[:4]) != DDS_MAGIC:
        raise ValueError("not a DDS file (missing 'DDS ' magic)")
    hsize, flags, height, width, pitch, depth, mips = struct.unpack_from("<7I", buf, 4)
    if hsize != 124:
        raise ValueError(f"bad DDS header size {hsize}")
    pfsize, pfflags = struct.unpack_from("<2I", buf, 0x4C)
    fourcc = bytes(buf[0x54:0x58])
    bitcount, rm, gm, bm, am = struct.unpack_from("<5I", buf, 0x58)
    caps1, caps2 = struct.unpack_from("<2I", buf, 0x6C)
    if pfsize != 32:
        raise ValueError(f"bad DDS pixelformat size {pfsize}")

    if pfflags & 0x4:  # DDPF_FOURCC
        if fourcc == b"DX10":
            raise ValueError("DX10 extended header not supported (not used by SM3)")
        fmt = _FOURCC_TO_FMT.get(fourcc, "?")
    else:
        fmt = _MASKS_TO_FMT.get((bitcount, rm, gm, bm, am), "?")

    return DDSInfo(width, height, mips, flags, pitch, depth, pfflags, fourcc,
                   bitcount, (rm, gm, bm, am), caps1, caps2, fmt,
                   body_size=len(buf) - 128)


def decode_dds(data):
    """Decode every mip level. Returns list of (mip_index, w, h, rgba)."""
    info = parse_dds(data)
    if info.fmt == "?":
        raise ValueError(f"unrecognised DDS pixel format: fourcc={info.fourcc!r} "
                         f"bits={info.bitcount} masks={info.masks}")
    buf = memoryview(data)
    out = []
    off = info.data_offset
    w, h = info.width, info.height
    for i in range(info.levels):
        size = format_data_size(info.fmt, w, h)
        out.append((i, w, h, decode_level(buf[off:off + size], info.fmt, w, h)))
        off += size
        w, h = max(1, w // 2), max(1, h // 2)
    return out


# --------------------------------------------------------------------------
# image-likeness heuristic
# --------------------------------------------------------------------------


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation, dot-product based (few numpy calls, BLAS inner)."""
    a = np.ascontiguousarray(a, np.float32).ravel()
    b = np.ascontiguousarray(b, np.float32).ravel()
    n = a.size
    sa = float(a.sum())
    sb = float(b.sum())
    sab = float(np.dot(a, b)) - sa * sb / n
    va = float(np.dot(a, a)) - sa * sa / n
    vb = float(np.dot(b, b)) - sb * sb / n
    if va <= 1e-9 or vb <= 1e-9:
        return 0.0
    return sab / (va * vb) ** 0.5


def _channel_likeness(g: np.ndarray, threshold: float | None = None) -> float:
    """Likeness score for one float32 2-D channel. See image_likeness_score.

    If `threshold` is given, may return early with a value that is provably
    below it (cheap pruning for the scanner); exact otherwise.
    """
    std = float(g.std())
    if std < 1.5:            # essentially constant -> no evidence of an image
        return 0.0

    # lag-1 correlation restricted to 4-pixel block boundaries, FIRST (cheap:
    # 1/4 of the pixels). Misdecoded data run through a DXT decoder is smooth
    # INSIDE each 4x4 block (palette interpolation) but uncorrelated ACROSS
    # blocks; real images are continuous everywhere.
    h, w = g.shape
    cb = []
    if w >= 8:
        cb.append(_corr(g[:, 3:-1:4], g[:, 4::4]))
    if h >= 8:
        cb.append(_corr(g[3:-1:4, :], g[4::4, :]))
    ac_bnd = sum(cb) / len(cb) if cb else None
    if ac_bnd is not None and threshold is not None:
        upper = 0.6 * max(0.0, ac_bnd) + 0.4      # best case for the rest
        if upper < threshold:
            return max(0.0, min(1.0, upper))      # provably below threshold

    # full-image lag-1 autocorrelation; combined as min with the boundary one
    ac_all = (_corr(g[:, :-1], g[:, 1:]) + _corr(g[:-1, :], g[1:, :])) / 2.0
    ac = ac_all if ac_bnd is None else min(ac_all, ac_bnd)
    ac = max(0.0, ac)

    # mean |Laplacian| normalised by the value expected for white noise
    # (mean|lap| of iid noise ~= 3.57 * sigma); real images sit far below 1.0
    lap = (4.0 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1]
           - g[1:-1, :-2] - g[1:-1, 2:])
    lap_ratio = float(np.abs(lap).mean()) / (3.57 * std + 1e-9)
    lap_score = max(0.0, 1.0 - min(lap_ratio, 1.0))

    return max(0.0, min(1.0, 0.6 * ac + 0.4 * lap_score))


def image_likeness_score(rgba: np.ndarray, threshold: float | None = None) -> float:
    """Score in [0, 1]: does this decoded RGBA array look like a real image?

    Real textures are locally smooth — high lag-1 autocorrelation (including
    across 4px block boundaries) and low Laplacian energy relative to their
    contrast. Misdecoded/random data is pixel-to-pixel uncorrelated (or, when
    run through a DXT decoder, uncorrelated across block boundaries).
    Constant images score 0 (no evidence either way).

    Scored on the RGB luma AND on the alpha channel, taking the max — font /
    UI atlases (e.g. Fullkeyset) often carry all their signal in alpha.

    `threshold`: if set, the function only guarantees exactness of the
    comparison `score >= threshold` — it may return early with a cheaper
    conservative value once the score is provably below the threshold, and it
    skips the alpha channel when the RGB channels already contain strong
    noise evidence. Use threshold=None (default) for exact scores.

    Measured reference points (ground truth + noise, n=13 decodes, probe
    script of the reverse-engineering work): real textures 0.93-0.99, DXT-decoded
    noise 0.10-0.16, raw-decoded noise ~0.00, flat 0.0.
    """
    if rgba.ndim != 3 or rgba.shape[2] < 3:
        raise ValueError("expected (h, w, 3|4) array")
    if rgba.shape[0] < 8 or rgba.shape[1] < 8:
        return 0.0
    g = rgba[..., :3].astype(np.float32).mean(axis=-1)
    score = _channel_likeness(g, threshold)
    if rgba.shape[2] == 4:
        if (threshold is not None and score < 0.5 * threshold
                and float(g.std()) >= 1.5):
            # RGB has real variance but is uncorrelated -> misdecode; the
            # alpha of the same bytes will not rescue it. (Exact mode still
            # checks alpha: rgb-flat-but-alpha-textured atlases score there.)
            return score
        score = max(score, _channel_likeness(rgba[..., 3].astype(np.float32),
                                             threshold))
    return score


# --------------------------------------------------------------------------
# brute-force texture scanner
# --------------------------------------------------------------------------


@dataclass
class Candidate:
    offset: int
    fmt: str
    width: int
    height: int               # best guess (see scan_for_textures notes)
    heights: tuple            # every power-of-two height whose data fits the file
    score: float
    run_hits: int = 1         # number of consecutive probed offsets that hit
    probe_score: float = 0.0  # score of the short head probe (sharp at texture
                              # starts; `score` comes from the deeper refine)

    def __str__(self):
        alts = ",".join(str(h) for h in self.heights)
        return (f"off=0x{self.offset:08X} fmt={self.fmt:<9} {self.width}x{self.height} "
                f"score={self.score:.3f} run={self.run_hits} (fitting heights: {alts})")


def _pow2s(lo: int, hi: int):
    v, out = 1, []
    while v <= hi:
        if v >= lo:
            out.append(v)
        v *= 2
    return out


def _bytes_per_pixel_row(fmt: str, w: int) -> float:
    return format_data_size(fmt, w, 4) / 4.0


def scan_for_textures(data, min_dim: int = 16, max_dim: int = 2048,
                      formats=("dxt1", "dxt5", "a8r8g8b8"),
                      offsets=None, offset_step: int | None = None,
                      probe_rows: int = 16, score_threshold: float = 0.5,
                      top: int = 100, refine: bool = True, crop_cols: int = 256,
                      progress: bool = False) -> list[Candidate]:
    """Brute-force scan of a binary blob for decodable textures.

    Strategy (kept fast enough for ~90 MB pack files):
      1. cheap prefilter per offset (skip constant windows: zero padding etc.)
      2. per (offset, format): decode ONE probe strip of `probe_rows` rows at
         the widest fitting width — the block/pixel decode is layout-agnostic,
         so every narrower width hypothesis reuses the same decoded blocks
         and only pays for re-assembly + scoring (cropped to `crop_cols`
         columns; scoring quality is unaffected because row alignment, not
         row length, is what separates right from wrong widths)
      3. hypotheses beating `score_threshold` get a deeper decode (`refine`,
         up to 128 rows at full width) and must beat the threshold again
      4. keep the best-scoring hypothesis per offset, group hit offsets into
         consecutive RUNS (a texture spans many probed offsets — its interior
         scores as well as its start), and report each run's FIRST offset.
         Run length then yields a data-driven height estimate:
         height ~= run_bytes / bytes_per_pixel_row, snapped to the nearest
         fitting power of two.

    Returned candidates are ranked by score (max `top`).

    Notes:
    * Only power-of-two dimensions are tried (true of this game's pipeline).
    * `height` is the run-length estimate when offsets are regularly stepped,
      else the fitting pow2 closest to the width; `heights` lists every pow2
      height whose data fits at that offset.
    * Pass explicit `offsets` when candidate offsets are known (e.g. from pack
      directory parsing) — faster and exact (no run grouping is applied unless
      the offsets are regularly spaced). Otherwise offsets are
      range(0, len(data), offset_step); default step 16 (<=1 MB), 256
      (<=16 MB), 2048 (larger).
    * Known limitations: (a) a texture whose first `probe_rows` rows are BLANK
      scores 0 at its exact start and is instead reported at the first probed
      offset with content; (b) back-to-back textures with no gap merge into
      one run and only the first is reported (mip chains do this by design —
      the run start is the mip-0 start); (c) the run height estimate
      overshoots when a same-looking texture follows immediately.
    """
    buf = memoryview(data)
    nbytes = len(buf)
    widths = _pow2s(min_dim, max_dim)
    heights_all = _pow2s(min_dim, max_dim)
    if offsets is None:
        if offset_step is None:
            offset_step = 16 if nbytes <= 1 << 20 else (256 if nbytes <= 16 << 20 else 2048)
        offsets = range(0, nbytes, offset_step)
    offsets = list(offsets)
    # regular stepping? (needed for run grouping / height estimation)
    step = None
    if len(offsets) >= 2:
        diffs = {offsets[i + 1] - offsets[i] for i in range(min(64, len(offsets) - 1))}
        if len(diffs) == 1:
            step = diffs.pop()

    rows = max(8, (probe_rows + 3) & ~3)     # multiple of 4, >= 8
    brows = rows // 4
    best_at: dict[int, Candidate] = {}       # offset -> best hypothesis
    for oi, off in enumerate(offsets):
        if progress and oi % 4096 == 0:
            print(f"\r  scan {oi}/{len(offsets)} offsets, {len(best_at)} hit offsets",
                  end="", file=sys.stderr, flush=True)
        win = np.frombuffer(buf[off:off + 512], np.uint8)
        if win.size < 64 or win.min() == win.max():
            continue
        for fmt in formats:
            info = FORMATS[fmt]
            fit_ws = [w for w in widths
                      if off + format_data_size(fmt, w, rows) <= nbytes]
            if not fit_ws:
                continue
            wmax = fit_ws[-1]
            # single decode at the widest hypothesis, reused for all widths
            if info.block:
                nb = (wmax // 4) * brows
                blk = _as_u8(buf[off:], nb * info.bytes_per_unit,
                             fmt).reshape(nb, info.bytes_per_unit)
                blockpix = info.stage(blk)              # (nb, 16, 4)
            else:
                pix = info.stage(buf[off:], wmax * rows)  # (npix, 4)
            for w in fit_ws:
                if info.block:
                    bw = w // 4
                    bcols = min(bw, max(1, crop_cols // 4))
                    sel = (np.arange(brows)[:, None] * bw + np.arange(bcols)).ravel()
                    img = blockpix[sel].reshape(brows, bcols, 4, 4, 4) \
                        .transpose(0, 2, 1, 3, 4).reshape(brows * 4, bcols * 4, 4)
                else:
                    img = pix[:w * rows].reshape(rows, w, 4)[:, :crop_cols]
                s_probe = image_likeness_score(img, threshold=score_threshold)
                if s_probe < score_threshold:
                    continue
                hs = tuple(hh for hh in heights_all
                           if off + format_data_size(fmt, w, hh) <= nbytes)
                if not hs:
                    continue
                s = s_probe
                if refine:
                    ph2 = min(128, hs[-1])
                    if ph2 > rows:
                        strip2 = format_data_size(fmt, w, ph2)
                        img2 = decode_level(buf[off:off + strip2], fmt, w, ph2)
                        s = image_likeness_score(img2[:, :max(crop_cols, 512)])
                        if s < score_threshold:
                            continue
                prev = best_at.get(off)
                if prev is None or s > prev.score:
                    hbest = min(hs, key=lambda hh: abs(hh.bit_length() - w.bit_length()))
                    best_at[off] = Candidate(off, fmt, w, hbest, hs, s,
                                             probe_score=s_probe)
    if progress:
        print(file=sys.stderr)

    # group hit offsets into consecutive runs; report each run's start.
    # Probes shortly BEFORE a texture partially overlap it and often pass the
    # threshold too, but their SHORT-PROBE score sits clearly below the
    # in-texture plateau (the deep refine score would be diluted: mostly
    # texture bytes) — so the representative is the first offset whose probe
    # score is within EPS of the run's probe-score maximum.
    EPS = 0.1
    kept: list[Candidate] = []
    hit_offs = sorted(best_at)
    i = 0
    while i < len(hit_offs):
        j = i
        if step is not None:
            while j + 1 < len(hit_offs) and hit_offs[j + 1] - hit_offs[j] <= step:
                j += 1
        run = [best_at[o] for o in hit_offs[i:j + 1]]
        run_pmax = max(c.probe_score for c in run)
        rep = next(c for c in run if c.probe_score >= run_pmax - EPS)
        rep.run_hits = j - i + 1
        rep.score = max(c.score for c in run)
        if step is not None and hit_offs[j] > rep.offset:
            run_bytes = (hit_offs[j] - rep.offset) + step
            est_rows = max(1.0, run_bytes / _bytes_per_pixel_row(rep.fmt, rep.width))
            rep.height = min(rep.heights,
                             key=lambda hh: abs(math.log2(hh) - math.log2(est_rows)))
        kept.append(rep)
        i = j + 1
    kept.sort(key=lambda c: -c.score)
    return kept[:top]


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------


def save_png(rgba: np.ndarray, path: str) -> None:
    from PIL import Image
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    Image.fromarray(np.ascontiguousarray(rgba), "RGBA").save(path)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _cmd_info(args):
    data = open(args.file, "rb").read(4096)
    info = parse_dds(data)
    body = os.path.getsize(args.file) - 128
    print(f"{args.file}")
    print(f"  {info.width} x {info.height}, mip_count={info.mip_count} "
          f"(levels={info.levels}), fmt={info.fmt}")
    print(f"  flags=0x{info.flags:08X} pf_flags=0x{info.pf_flags:08X} "
          f"fourcc={info.fourcc!r} bits={info.bitcount}")
    print(f"  masks R/G/B/A = {' '.join(f'0x{m:08X}' for m in info.masks)}")
    print(f"  caps1=0x{info.caps1:08X} caps2=0x{info.caps2:08X}")
    if info.fmt != "?":
        expect = mip_chain_size(info.fmt, info.width, info.height, info.levels)
        print(f"  body {body:,} bytes; expected for {info.fmt} chain: {expect:,} "
              f"({'MATCH' if expect == body else 'MISMATCH'})")


def _cmd_dds(args):
    data = open(args.file, "rb").read()
    levels = decode_dds(data)
    base = os.path.splitext(args.output or (os.path.basename(args.file) + ".png"))[0]
    todo = levels if args.all_mips else [levels[min(args.mip, len(levels) - 1)]]
    for i, w, h, rgba in todo:
        out = f"{base}.png" if len(todo) == 1 else f"{base}_mip{i}.png"
        save_png(rgba, out)
        print(f"  mip {i}: {w}x{h} score={image_likeness_score(rgba):.3f} -> {out}")


def _cmd_decode(args):
    with open(args.file, "rb") as f:
        f.seek(args.offset)
        data = f.read(format_data_size(args.format, args.width, args.height))
    rgba = decode_level(data, args.format, args.width, args.height)
    out = args.output or f"{os.path.basename(args.file)}_{args.offset:#x}_{args.format}.png"
    save_png(rgba, out)
    print(f"{args.format} {args.width}x{args.height} @ {args.offset:#x} "
          f"score={image_likeness_score(rgba):.3f} -> {out}")


def _cmd_scan(args):
    data = open(args.file, "rb").read()
    cands = scan_for_textures(
        data, min_dim=args.min_dim, max_dim=args.max_dim,
        formats=tuple(args.formats.split(",")), offset_step=args.step,
        score_threshold=args.threshold, top=args.top, progress=True)
    if not cands:
        print("no candidates found")
        return
    for c in cands:
        print(c)
    if args.save_dir:
        for c in cands[:args.save_top]:
            size = format_data_size(c.fmt, c.width, c.height)
            rgba = decode_level(memoryview(data)[c.offset:c.offset + size],
                                c.fmt, c.width, c.height)
            out = os.path.join(args.save_dir,
                               f"{os.path.basename(args.file)}_{c.offset:08x}_{c.fmt}"
                               f"_{c.width}x{c.height}.png")
            save_png(rgba, out)
            print(f"  saved {out}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="texfind", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("info", help="parse and print a DDS header")
    q.add_argument("file")
    q.set_defaults(func=_cmd_info)

    q = sub.add_parser("dds", help="decode a DDS file to PNG")
    q.add_argument("file")
    q.add_argument("-o", "--output")
    q.add_argument("--mip", type=int, default=0)
    q.add_argument("--all-mips", action="store_true")
    q.set_defaults(func=_cmd_dds)

    q = sub.add_parser("decode", help="decode raw texture bytes at an offset")
    q.add_argument("file")
    q.add_argument("--format", required=True, choices=sorted(FORMATS))
    q.add_argument("--width", type=int, required=True)
    q.add_argument("--height", type=int, required=True)
    q.add_argument("--offset", type=lambda s: int(s, 0), default=0)
    q.add_argument("-o", "--output")
    q.set_defaults(func=_cmd_decode)

    q = sub.add_parser("scan", help="brute-force scan a blob for textures")
    q.add_argument("file")
    q.add_argument("--formats", default="dxt1,dxt5,a8r8g8b8")
    q.add_argument("--min-dim", type=int, default=16)
    q.add_argument("--max-dim", type=int, default=2048)
    q.add_argument("--step", type=int, default=None)
    q.add_argument("--threshold", type=float, default=0.5)
    q.add_argument("--top", type=int, default=30)
    q.add_argument("--save-dir")
    q.add_argument("--save-top", type=int, default=5)
    q.set_defaults(func=_cmd_scan)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
