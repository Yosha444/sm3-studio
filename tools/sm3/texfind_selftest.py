# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit-style self-tests for sm3.texfind (the texture decoder of tools/sm3/texfind.py).

Not part of the conversion: run it by hand after changing texfind.py.

Run:  python texfind_selftest.py
Round-trips against the two known-good loose DDS files of the game, in GAME\\pcinterface
(Fullkeyset_2048_eng.dds and waterwaves_9mips.dds, read only), and against hand-constructed
known-vector blocks. Decoded images are saved as PNG under WORK\\extracted\\probe for a visual
check.

GAME = the Spider-Man 3 folder: the SM3_GAME environment variable, else the first usual install
folder that has a pcinterface\\ sub-folder. WORK = the SM3_WORK environment variable, else
<temp>\\sm3_texfind_selftest. (Both defaults used to be paths of the author's machine.)
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sm3 import texfind as tf  # noqa: E402


def _game_folder():
    """Spider-Man 3 folder holding pcinterface\\: $SM3_GAME, else the usual install places."""
    explicit = os.environ.get("SM3_GAME", "").strip().strip('"')
    if explicit:
        return explicit
    for folder in (r"C:\Games\Spider-man 3",
                   r"C:\Program Files (x86)\Activision\Spider-Man 3",
                   r"C:\Program Files\Activision\Spider-Man 3"):
        if os.path.isdir(os.path.join(folder, "pcinterface")):
            return folder
    return r"C:\Games\Spider-man 3"


GAME = _game_folder()
WORK = os.environ.get(
    "SM3_WORK", os.path.join(tempfile.gettempdir(), "sm3_texfind_selftest"))
PROBE_DIR = os.path.join(WORK, "extracted", "probe")

KEYSET = os.path.join(GAME, "pcinterface", "Fullkeyset_2048_eng.dds")
WAVES = os.path.join(GAME, "pcinterface", "waterwaves_9mips.dds")

_results = []


def check(name, cond, detail=""):
    _results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


# --------------------------------------------------------------------------


def test_dds_header_fullkeyset():
    data = open(KEYSET, "rb").read()
    info = tf.parse_dds(data)
    check("keyset magic/size parse", True)
    check("keyset dims 2048x2048", info.width == 2048 and info.height == 2048)
    check("keyset fourcc DXT5", info.fourcc == b"DXT5" and info.fmt == "dxt5",
          f"fourcc={info.fourcc!r}")
    check("keyset mip_count 0 (single level)", info.mip_count == 0 and info.levels == 1)
    body = len(data) - 128
    expect = tf.format_data_size("dxt5", 2048, 2048)
    check("keyset body == dxt5 size == 2048*2048*1B", body == expect == 2048 * 2048,
          f"body={body:,}")
    return data, info


def test_dds_header_waterwaves():
    data = open(WAVES, "rb").read()
    info = tf.parse_dds(data)
    check("waves dims 256x256", info.width == 256 and info.height == 256)
    check("waves fmt x8r8g8b8", info.fmt == "x8r8g8b8",
          f"bits={info.bitcount} masks={tuple(hex(m) for m in info.masks)}")
    check("waves mip_count 9", info.mip_count == 9)
    body = len(data) - 128
    expect = tf.mip_chain_size("x8r8g8b8", 256, 256, 9)
    check("waves body == 9-mip 32bpp chain", body == expect,
          f"body={body:,} expect={expect:,}")
    return data, info


def test_decode_fullkeyset(data):
    t0 = time.perf_counter()
    levels = tf.decode_dds(data)
    dt = time.perf_counter() - t0
    (_, w, h, rgba), = levels
    check("keyset decode shape", rgba.shape == (2048, 2048, 4))
    s = tf.image_likeness_score(rgba)
    check("keyset likeness > 0.6", s > 0.6, f"score={s:.3f}, decode {dt*1000:.0f} ms")
    tf.save_png(rgba, os.path.join(PROBE_DIR, "Fullkeyset_2048_eng_dxt5.png"))
    return rgba


def test_decode_waterwaves(data):
    levels = tf.decode_dds(data)
    check("waves 9 levels decoded", len(levels) == 9)
    off = 128
    for i, w, h, _ in levels:
        off += tf.format_data_size("x8r8g8b8", w, h)
    check("waves mip chain consumes file exactly", off == len(data),
          f"consumed={off} file={len(data)}")
    rgba0 = levels[0][3]
    s = tf.image_likeness_score(rgba0)
    check("waves mip0 likeness > 0.6", s > 0.6, f"score={s:.3f}")
    check("waves alpha forced opaque", int(rgba0[..., 3].min()) == 255)
    tf.save_png(rgba0, os.path.join(PROBE_DIR, "waterwaves_mip0_x8r8g8b8.png"))
    tf.save_png(levels[4][3], os.path.join(PROBE_DIR, "waterwaves_mip4_x8r8g8b8.png"))
    return rgba0


def test_dxt1_known_vectors():
    # Block A: 4-colour mode. c0 = pure red 0xF800 > c1 = pure blue 0x001F.
    # indices: pixel k gets index k % 4  -> bits = 0b11100100 repeated (0xE4)
    blk_a = struct.pack("<2H4B", 0xF800, 0x001F, 0xE4, 0xE4, 0xE4, 0xE4)
    # Block B: 3-colour mode. c0 = 0x0000 <= c1 = 0xFFFF; all pixels index 3
    # -> transparent black.
    blk_b = struct.pack("<2H4B", 0x0000, 0xFFFF, 0xFF, 0xFF, 0xFF, 0xFF)
    img = tf.dxt1_decode(blk_a + blk_b, 8, 4)
    # block A pixel (0,0): index 0 -> c0 = (255,0,0,255)
    ok_a0 = tuple(img[0, 0]) == (255, 0, 0, 255)
    # (0,1): index 1 -> c1 = (0,0,255,255)
    ok_a1 = tuple(img[0, 1]) == (0, 0, 255, 255)
    # (0,2): index 2 -> (2*c0+c1)/3 = (170,0,85,255)
    ok_a2 = tuple(img[0, 2]) == (170, 0, 85, 255)
    # (0,3): index 3 -> (c0+2*c1)/3 = (85,0,170,255)
    ok_a3 = tuple(img[0, 3]) == (85, 0, 170, 255)
    check("dxt1 4-colour palette exact", ok_a0 and ok_a1 and ok_a2 and ok_a3,
          f"px={[tuple(img[0, i]) for i in range(4)]}")
    ok_b = np.all(img[:, 4:] == 0)
    check("dxt1 3-colour transparent black", bool(ok_b))
    # every pixel of a uniform-index-0 block equals c0
    blk_c = struct.pack("<2H4B", 0xF800, 0x001F, 0, 0, 0, 0)
    img_c = tf.dxt1_decode(blk_c, 4, 4)
    check("dxt1 uniform block", bool(np.all(img_c == np.array([255, 0, 0, 255]))))


def test_dxt3_known_vector():
    # alpha nibbles 0..15 -> 0,17,34,...,255; colour = uniform red
    a_bytes = bytes((lo | (hi << 4)) for lo, hi in
                    zip(range(0, 16, 2), range(1, 16, 2)))
    blk = a_bytes + struct.pack("<2H4B", 0xF800, 0xF800, 0, 0, 0, 0)
    img = tf.dxt3_decode(blk, 4, 4)
    alphas = img[..., 3].ravel()
    check("dxt3 explicit alpha = nibble*17",
          bool(np.array_equal(alphas, np.arange(16, dtype=np.uint16) * 17)),
          f"alphas={alphas.tolist()}")
    check("dxt3 colour always 4-colour (c0==c1 ok)",
          bool(np.all(img[..., 0] == 255)))


def test_dxt5_known_vectors():
    # 8-value mode: a0=224 > a1=0 -> pal = [224,0,192,160,128,96,64,32]
    # (224*k/7 all exact). indices 0..7 across first 8 pixels, then repeat.
    idx = [i % 8 for i in range(16)]
    bits = 0
    for k, v in enumerate(idx):
        bits |= v << (3 * k)
    a_blk = struct.pack("<2B6s", 224, 0, bits.to_bytes(6, "little"))
    c_blk = struct.pack("<2H4B", 0xFFFF, 0xFFFF, 0, 0, 0, 0)
    img = tf.dxt5_decode(a_blk + c_blk, 4, 4)
    expect = [224, 0, 192, 160, 128, 96, 64, 32] * 2
    got = img[..., 3].ravel().tolist()
    check("dxt5 8-value alpha exact", got == expect, f"got={got}")
    # 6-value mode: a0=0 <= a1=250 -> pal=[0,250,50,100,150,200,0,255]
    a_blk2 = struct.pack("<2B6s", 0, 250, bits.to_bytes(6, "little"))
    img2 = tf.dxt5_decode(a_blk2 + c_blk, 4, 4)
    expect2 = [0, 250, 50, 100, 150, 200, 0, 255] * 2
    got2 = img2[..., 3].ravel().tolist()
    check("dxt5 6-value alpha exact (incl. 0/255 endpoints)", got2 == expect2,
          f"got={got2}")


def test_bc4_bc5_known_vectors():
    idx = [i % 8 for i in range(16)]
    bits = 0
    for k, v in enumerate(idx):
        bits |= v << (3 * k)
    blk = struct.pack("<2B6s", 224, 0, bits.to_bytes(6, "little"))
    img = tf.bc4_decode(blk, 4, 4)
    expect = np.array([224, 0, 192, 160, 128, 96, 64, 32] * 2, np.uint8).reshape(4, 4)
    check("bc4 exact + grayscale replicate",
          bool(np.array_equal(img[..., 0], expect)) and
          bool(np.array_equal(img[..., 0], img[..., 1])) and
          bool(np.array_equal(img[..., 0], img[..., 2])) and
          int(img[..., 3].min()) == 255)
    blk_g = struct.pack("<2B6s", 70, 0, bits.to_bytes(6, "little"))
    img5 = tf.bc5_decode(blk + blk_g, 4, 4)
    expect_g = np.array([70, 0, 60, 50, 40, 30, 20, 10] * 2, np.uint8).reshape(4, 4)
    check("bc5 two channels exact, B=0",
          bool(np.array_equal(img5[..., 0], expect)) and
          bool(np.array_equal(img5[..., 1], expect_g)) and
          int(img5[..., 2].max()) == 0)


def test_raw_roundtrips():
    rng = np.random.default_rng(7)
    h, w = 16, 32
    rgba = rng.integers(0, 256, (h, w, 4), dtype=np.uint8)
    # a8r8g8b8: pack as little-endian AARRGGBB dwords
    px = (rgba[..., 3].astype(np.uint32) << 24) | (rgba[..., 0].astype(np.uint32) << 16) \
        | (rgba[..., 1].astype(np.uint32) << 8) | rgba[..., 2].astype(np.uint32)
    dec = tf.a8r8g8b8_decode(px.astype("<u4").tobytes(), w, h)
    check("a8r8g8b8 roundtrip exact", bool(np.array_equal(dec, rgba)))
    dec_x = tf.x8r8g8b8_decode(px.astype("<u4").tobytes(), w, h)
    check("x8r8g8b8 alpha=255, rgb matches",
          bool(np.array_equal(dec_x[..., :3], rgba[..., :3])) and
          int(dec_x[..., 3].min()) == 255)
    # r5g6b5: quantise, then expect exact bit-replication expansion
    r5 = (rgba[..., 0] >> 3).astype(np.uint16)
    g6 = (rgba[..., 1] >> 2).astype(np.uint16)
    b5 = (rgba[..., 2] >> 3).astype(np.uint16)
    p16 = ((r5 << 11) | (g6 << 5) | b5).astype("<u2")
    dec = tf.r5g6b5_decode(p16.tobytes(), w, h)
    ok = (np.array_equal(dec[..., 0], ((r5 << 3) | (r5 >> 2)).astype(np.uint8)) and
          np.array_equal(dec[..., 1], ((g6 << 2) | (g6 >> 4)).astype(np.uint8)) and
          np.array_equal(dec[..., 2], ((b5 << 3) | (b5 >> 2)).astype(np.uint8)))
    check("r5g6b5 roundtrip exact", bool(ok))
    # a1r5g5b5
    a1 = (rgba[..., 3] >> 7).astype(np.uint16)
    g5 = (rgba[..., 1] >> 3).astype(np.uint16)
    p16 = ((a1 << 15) | (r5 << 10) | (g5 << 5) | b5).astype("<u2")
    dec = tf.a1r5g5b5_decode(p16.tobytes(), w, h)
    check("a1r5g5b5 roundtrip exact",
          bool(np.array_equal(dec[..., 3], (a1 * 255).astype(np.uint8))) and
          bool(np.array_equal(dec[..., 0], ((r5 << 3) | (r5 >> 2)).astype(np.uint8))))
    # a4r4g4b4
    q = (rgba >> 4).astype(np.uint16)
    p16 = ((q[..., 3] << 12) | (q[..., 0] << 8) | (q[..., 1] << 4) | q[..., 2]).astype("<u2")
    dec = tf.a4r4g4b4_decode(p16.tobytes(), w, h)
    check("a4r4g4b4 roundtrip exact",
          bool(np.array_equal(dec, (q * 17).astype(np.uint8)[..., [0, 1, 2, 3]])))
    # a8 / l8 / a8l8
    v = rng.integers(0, 256, (h, w), dtype=np.uint8)
    dec = tf.l8_decode(v.tobytes(), w, h)
    check("l8 roundtrip exact", bool(np.array_equal(dec[..., 0], v)) and
          bool(np.array_equal(dec[..., 0], dec[..., 2])))
    la = rng.integers(0, 256, (h, w, 2), dtype=np.uint8)
    dec = tf.a8l8_decode(la.tobytes(), w, h)
    check("a8l8 roundtrip exact",
          bool(np.array_equal(dec[..., 0], la[..., 0])) and
          bool(np.array_equal(dec[..., 3], la[..., 1])))


def test_likeness_discrimination(keyset_rgba, waves_rgba):
    rng = np.random.default_rng(3)
    noise = rng.integers(0, 256, 512 * 512, dtype=np.uint8).tobytes()
    s_noise_dxt5 = tf.image_likeness_score(tf.dxt5_decode(noise, 128, 128))
    s_noise_raw = tf.image_likeness_score(tf.a8r8g8b8_decode(noise, 256, 256))
    s_flat = tf.image_likeness_score(np.full((64, 64, 4), 137, np.uint8))
    s_key = tf.image_likeness_score(keyset_rgba)
    s_wav = tf.image_likeness_score(waves_rgba)
    check("likeness: real textures score high",
          s_key > 0.6 and s_wav > 0.6, f"keyset={s_key:.3f} waves={s_wav:.3f}")
    check("likeness: noise scores low",
          s_noise_dxt5 < 0.35 and s_noise_raw < 0.35,
          f"noise_dxt5={s_noise_dxt5:.3f} noise_raw={s_noise_raw:.3f}")
    check("likeness: flat scores 0", s_flat == 0.0, f"flat={s_flat:.3f}")
    # wrong-format decode of real data should score below right-format decode
    kdata = open(KEYSET, "rb").read()[128:]
    s_wrong = tf.image_likeness_score(tf.dxt1_decode(kdata, 2048, 2048))
    check("likeness: wrong format < right format", s_wrong < s_key,
          f"dxt1(wrong)={s_wrong:.3f} vs dxt5={s_key:.3f}")


def test_scan_finds_embedded():
    rng = np.random.default_rng(11)
    waves = open(WAVES, "rb").read()
    wav_mip0 = waves[128:128 + 256 * 256 * 4]                  # raw X8R8G8B8 256x256
    keyset = open(KEYSET, "rb").read()
    key_strip = keyset[128:128 + tf.format_data_size("dxt5", 2048, 256)]  # 2048x256 dxt5

    blob = bytearray(rng.integers(0, 256, 2 << 20, dtype=np.uint8).tobytes())
    off_raw, off_dxt = 0x40000, 0x100000
    blob[off_raw:off_raw + len(wav_mip0)] = wav_mip0
    blob[off_dxt:off_dxt + len(key_strip)] = key_strip

    t0 = time.perf_counter()
    cands = tf.scan_for_textures(bytes(blob), offset_step=4096, top=10,
                                 formats=("dxt1", "dxt5", "a8r8g8b8"))
    dt = time.perf_counter() - t0
    hit_raw = [c for c in cands if c.offset == off_raw and c.fmt == "a8r8g8b8"
               and c.width == 256]
    hit_dxt = [c for c in cands if c.offset == off_dxt and c.fmt == "dxt5"
               and c.width == 2048]
    check("scan finds embedded raw 256-wide at exact offset", bool(hit_raw),
          f"{len(cands)} candidates, {dt:.1f}s")
    check("scan finds embedded dxt5 2048-wide at exact offset", bool(hit_dxt))
    if hit_raw and hit_dxt:
        top_fp = [c for c in cands if c.offset not in (off_raw, off_dxt)]
        best_fp = max((c.score for c in top_fp), default=0.0)
        best_real = max(c.score for c in cands if c.offset in (off_raw, off_dxt))
        check("scan: real hits outrank noise", best_real > best_fp + 0.2,
              f"real={best_real:.3f} best_noise={best_fp:.3f}")
    else:
        check("scan: real hits outrank noise", False, "prerequisite hits missing")


def test_scan_speed():
    # representative throughput measurement on 8 MB of incompressible data
    rng = np.random.default_rng(5)
    blob = rng.integers(0, 256, 8 << 20, dtype=np.uint8).tobytes()
    t0 = time.perf_counter()
    tf.scan_for_textures(blob, offset_step=2048,
                         formats=("dxt1", "dxt5", "a8r8g8b8"))
    dt = time.perf_counter() - t0
    mbs = 8 / dt
    est90 = 90 / mbs
    check("scan speed acceptable (90 MB under ~10 min at step 2048)", est90 < 600,
          f"{mbs:.1f} MB/s -> est {est90:.0f}s for 90 MB")


def main():
    if not (os.path.isfile(KEYSET) and os.path.isfile(WAVES)):
        sys.exit("Spider-Man 3's pcinterface DDS files not found in %s.\n"
                 "Set the SM3_GAME environment variable to the game folder." % GAME)
    os.makedirs(PROBE_DIR, exist_ok=True)
    print("== DDS header ground truth ==")
    kdata, _ = test_dds_header_fullkeyset()
    wdata, _ = test_dds_header_waterwaves()
    print("== full decode of ground-truth files ==")
    k_rgba = test_decode_fullkeyset(kdata)
    w_rgba = test_decode_waterwaves(wdata)
    print("== known-vector block tests ==")
    test_dxt1_known_vectors()
    test_dxt3_known_vector()
    test_dxt5_known_vectors()
    test_bc4_bc5_known_vectors()
    print("== raw format roundtrips ==")
    test_raw_roundtrips()
    print("== likeness heuristic ==")
    test_likeness_discrimination(k_rgba, w_rgba)
    print("== scanner ==")
    test_scan_finds_embedded()
    test_scan_speed()

    npass = sum(1 for _, ok, _ in _results if ok)
    nfail = len(_results) - npass
    print(f"\n{npass} passed, {nfail} failed, {len(_results)} total")
    return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())
