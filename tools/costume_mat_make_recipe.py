#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Maintainer tool: derive costume_mat_shaders.json (the "recipe") from an UNMODIFIED Game.exe.

You do not need this script to use the matte suit. costume_mat.py only reads the recipe. This
script exists so that anyone can see, and re-check, where every byte of the recipe comes from.

    python costume_mat_make_recipe.py "path\\to\\intact\\Game.exe"            print the recipe
    python costume_mat_make_recipe.py "path\\to\\intact\\Game.exe" --write    (re)write costume_mat_shaders.json
    python costume_mat_make_recipe.py "path\\to\\intact\\Game.exe" --check    compare with the shipped recipe

Why a recipe and not the patched shaders themselves?
    The patched shaders are 95 % game bytecode. Publishing them would mean publishing part of
    Game.exe. The recipe only says "copy bytes a..b of YOUR shader, then insert these bytes of
    ours". costume_mat.py follows it on the player's own Game.exe, after checking (sha256) that the
    shader there is the original one.

What the patch does to each of the 3 suit pixel shaders (class sm_phatspiderman)
    1. The game computes its shine weights with one saturating instruction, e.g.
           mad_sat r3.xyz, r1, c2, c3          (c2/c3 = special_effects_matrix[2..3])
       r3.y is the specular weight, r3.z the environment-map weight, r3.x the opacity.
    2. Right after it we insert
           mad_sat r3.yz, r3.yyzz, c100.xxzz, c100.yyww
       so: specular = sat(game_specular * Ks + As), environment = sat(game_env * Ke + Ae).
       r3.x (opacity, used when the game fades Spider-Man out) is never written.
    3. c100 is declared after the last existing "def":
           def c100, Ks, As, Ke, Ae            (the 4 floats come from the preset)
    4. Those two instructions are 6 + 5 = 11 tokens (44 bytes). To keep the shader the SAME SIZE
       (it sits in the middle of Game.exe's .rdata, nothing may move), the constant-table comment
       (CTAB) gives back 44 bytes: its "creator" string ("Microsoft (R) HLSL Shader Compiler ...")
       is emptied and the comment is shortened. The game never reads that string; Direct3D 9
       accepts the shortened table (tested in game, 2026-10-06).

This script finds those places with the rules above (it does not contain any shader bytes) and
writes the byte-level edit list. It then applies the recipe with costume_mat.py's own code and
checks that the result is exactly what the rules produce.
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import costume_mat  # noqa: E402  (same folder; used for the PE check and to replay the recipe)

# The 3 suit pixel shaders, as FILE offsets in Game.exe (VA = offset + 0x400000).
# Found 2026-10-06 by following the sm_phatspiderman binders (0x4EB6E0, 0x4F9E60 ...).
SUIT_SHADERS = (0x69EDF0, 0x6A04F8, 0x6A2918)

OVERRIDE_REGISTER = 100          # c100: unused by these shaders (checked below)
TRIM_TOKENS = 11                 # 6 tokens for "def c100" + 5 for "mad_sat"

# D3D9 shader-model-3 token constants (see the D3D9 driver documentation, "Shader codes").
OP_COMMENT, OP_END, OP_DCL, OP_DEF = 0xFFFE, 0xFFFF, 0x1F, 0x51
# Instructions whose first operand is NOT a destination register (flow control, declarations).
NO_DESTINATION = {0x00, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x26, 0x27, 0x28, 0x29, 0x2A,
                  0x2B, 0x2C, 0x2D, 0x2F, 0x30, 0x51, 0x60}
REGISTER_CONST = 2               # register type "c"
FLOAT4_SET = 2                   # D3DXRS_FLOAT4 in the constant table


def shader_end(exe, offset):
    """Byte length of the shader starting at offset (version token .. END token included)."""
    version = struct.unpack_from('<I', exe, offset)[0]
    if version != 0xFFFF0300:
        raise SystemExit('0x%X is not a ps_3_0 shader: is this an intact Game.exe?' % offset)
    p = offset + 4
    while True:
        token = struct.unpack_from('<I', exe, p)[0]
        if token == 0x0000FFFF:
            return p + 4 - offset
        op = token & 0xFFFF
        length = (token >> 16) & 0x7FFF if op == OP_COMMENT else (token >> 24) & 0xF
        p += 4 + 4 * length


def instructions(tokens):
    """Yield (token index, opcode, operand count) for every instruction after the version token."""
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token == 0x0000FFFF:
            yield i, OP_END, 0
            return
        op = token & 0xFFFF
        length = (token >> 16) & 0x7FFF if op == OP_COMMENT else (token >> 24) & 0xF
        yield i, op, length
        i += 1 + length


def register_number(token):
    return token & 0x7FF


def register_type(token):
    return ((token >> 28) & 7) | ((token >> 8) & 0x18)


def constant_table(tokens, comment_index):
    """{constant register number: name} from the CTAB comment (only float4 registers)."""
    length = (tokens[comment_index] >> 16) & 0x7FFF
    body = struct.pack('<%dI' % length, *tokens[comment_index + 1:comment_index + 1 + length])
    table = body[4:]                                   # after the 'CTAB' four-character code
    _size, _creator, _version, count, info, _flags, _target = struct.unpack_from('<7I', table, 0)
    names = {}
    for k in range(count):
        name_at, reg_set, reg_index, reg_count, _r, _t, _d = struct.unpack_from('<I4HII', table, info + 20 * k)
        name = table[name_at:table.index(b'\0', name_at)].decode('latin-1')
        if reg_set == FLOAT4_SET:
            for j in range(reg_count):
                names[reg_index + j] = name + ('[%d]' % j if reg_count > 1 else '')
    return names


def derive(exe, offset):
    """Apply the rules to one original shader. Returns (patched bytes with zero values, recipe entry)."""
    size = shader_end(exe, offset)
    blob = exe[offset:offset + size]
    tokens = list(struct.unpack('<%dI' % (size // 4), blob))
    listing = list(instructions(tokens))

    # 1. the CTAB comment, and the creator / target strings inside it
    ci = next(i for i, op, n in listing if op == OP_COMMENT and tokens[i + 1] == 0x42415443)  # 'CTAB'
    n = (tokens[ci] >> 16) & 0x7FFF
    body_at = 4 * (ci + 1)                              # byte offset of the comment body in the blob
    table_at = body_at + 4                              # the table starts after 'CTAB'
    creator, target = struct.unpack_from('<I', blob, table_at + 4)[0], struct.unpack_from('<I', blob, table_at + 24)[0]
    target_len = blob.index(b'\0', table_at + target) - (table_at + target)
    if creator < target or (4 * n) - (4 + creator) < 4 * TRIM_TOKENS:
        raise SystemExit('0x%X: the creator string is not at the end of the table, or too short.' % offset)

    # 2. the game's material-weight instruction: the LAST saturating instruction that reads
    #    special_effects_matrix[3] (the "add" row of the material/cowbell shine factors)
    names = constant_table(tokens, ci)
    weight = None
    for i, op, count in listing:
        if op in (OP_COMMENT, OP_END) or op in NO_DESTINATION or count < 2:
            continue
        dst, sources = tokens[i + 1], tokens[i + 2:i + 1 + count]
        if (dst >> 20) & 1 and any(register_type(s) == REGISTER_CONST and
                                   names.get(register_number(s)) == 'special_effects_matrix[3]' for s in sources):
            weight = (i, count, dst)
    if weight is None:
        raise SystemExit('0x%X: material-weight instruction not found.' % offset)
    wi, wcount, wdst = weight
    if (wdst >> 16) & 0b0110 != 0b0110:
        raise SystemExit('0x%X: the weight instruction does not write .y and .z.' % offset)
    used = {register_number(t) for i, op, c in listing if op not in (OP_COMMENT, OP_END)
            for t in tokens[i + 1:i + 1 + c] if register_type(t) == REGISTER_CONST}
    if OVERRIDE_REGISTER in used:
        raise SystemExit('0x%X: c%d is already used.' % (offset, OVERRIDE_REGISTER))

    # 3. where "def c100" goes: after the last def (6 tokens each)
    defs = [i for i, op, c in listing if op == OP_DEF]
    after_def = defs[-1] + 6 if defs else ci + 1 + n

    reg = register_number(wdst)
    def_c100 = struct.pack('<2I', 0x05000051, 0xA00F0000 | OVERRIDE_REGISTER)
    # mad_sat rN.yz, rN.yyzz, c100.xxzz, c100.yyww  (write mask yz, saturate)
    mad = struct.pack('<5I', 0x04000004, 0x80000000 | 0x00100000 | (0b0110 << 16) | reg,
                      0x80000000 | (0xA5 << 16) | reg, 0xA0A00000 | OVERRIDE_REGISTER,
                      0xA0F50000 | OVERRIDE_REGISTER)
    weight_end = 4 * (wi + 1 + wcount)
    comment_end = 4 * (ci + 1 + n)
    old_creator_at = table_at + creator                 # first byte of the creator text
    new_comment_body = 4 * (n - TRIM_TOKENS)
    zeros = new_comment_body - (old_creator_at - body_at)

    edits = [
        dict(op='copy', start=0, end=4 * ci,
             why='version token (and anything before the constant table)'),
        dict(op='insert', hex=struct.pack('<I', OP_COMMENT | ((n - TRIM_TOKENS) << 16)).hex(),
             why='constant-table comment header, %d tokens shorter (44 bytes given back)' % TRIM_TOKENS),
        dict(op='copy', start=body_at, end=table_at + 4,
             why="'CTAB' and the table size"),
        dict(op='insert', hex=struct.pack('<I', target + target_len).hex(),
             why='creator-string offset, now pointing at the NUL that ends the target string '
                 '"ps_3_0": the creator string becomes empty'),
        dict(op='copy', start=table_at + 8, end=old_creator_at,
             why='rest of the constant table (constants, types, names, target), unchanged'),
        dict(op='zeros', count=zeros,
             why='former creator text "Microsoft (R) HLSL Shader Compiler ...", blanked; never read by the game'),
        dict(op='copy', start=comment_end, end=4 * after_def,
             why='declarations and constants of the original shader, unchanged'),
        dict(op='insert', hex=def_c100.hex(), why='def c%d, ...  (opcode and register)' % OVERRIDE_REGISTER),
        dict(op='values', count=16, why='Ks As Ke Ae: 4 little-endian float32, filled in from the preset'),
        dict(op='copy', start=4 * after_def, end=weight_end,
             why='original code up to and including the game\'s shine-weight instruction (writes r%d)' % reg),
        dict(op='insert', hex=mad.hex(),
             why='mad_sat r%d.yz, r%d.yyzz, c%d.xxzz, c%d.yyww: our shine and reflection override'
                 % (reg, reg, OVERRIDE_REGISTER, OVERRIDE_REGISTER)),
        dict(op='copy', start=weight_end, end=size, why='rest of the original shader, unchanged'),
    ]

    # The same result, built the plain way (token lists), to cross-check the edit list.
    body = bytearray(blob[body_at:comment_end])
    struct.pack_into('<I', body, 4 + 4, target + target_len)
    body[old_creator_at - body_at:] = bytes(len(body) - (old_creator_at - body_at))
    body = bytes(body[:-4 * TRIM_TOKENS])
    expected = (blob[:4 * ci] + struct.pack('<I', OP_COMMENT | ((n - TRIM_TOKENS) << 16)) + body
                + blob[comment_end:4 * after_def] + def_c100 + bytes(16) + blob[4 * after_def:weight_end]
                + mad + blob[weight_end:])
    if len(expected) != size:
        raise SystemExit('0x%X: size changed (%d -> %d).' % (offset, size, len(expected)))
    values_at = 4 * after_def - 4 * TRIM_TOKENS + len(def_c100)
    entry = dict(name='%X' % offset, offset=offset, size=size,
                 sha256_original=hashlib.sha256(blob).hexdigest(),
                 sha256_patched_without_values=hashlib.sha256(expected).hexdigest(),
                 values_position=values_at,
                 edits=edits)
    return expected, entry


def build_recipe(exe):
    shaders = []
    for offset in SUIT_SHADERS:
        expected, entry = derive(exe, offset)
        # replay the recipe with the code costume_mat.py uses, values = 0
        rebuilt = costume_mat.apply_recipe(exe[offset:offset + entry['size']], entry, (0.0, 0.0, 0.0, 0.0))
        if rebuilt != expected:
            raise SystemExit('internal error: the edit list does not rebuild shader %s.' % entry['name'])
        shaders.append(entry)
    return dict(
        format='sm3_costume_mat_recipe', version=2,
        description='How to build the 3 matte-suit pixel shaders (class sm_phatspiderman) from the '
                    'ORIGINAL ones in the player\'s own Game.exe (Spider-Man 3 PC, 2007, 10 846 998 bytes). '
                    'Contains no game bytes: "copy" ranges are byte offsets inside the original shader, '
                    '"insert" bytes are ours (shortened table header, new string offset, def c100, mad_sat), '
                    '"values" is where the preset\'s 4 floats go. Made by costume_mat_make_recipe.py.',
        shaders=shaders)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('exe', help='an UNMODIFIED Game.exe (or a copy of it)')
    ap.add_argument('--write', action='store_true', help='write costume_mat_shaders.json next to this script')
    ap.add_argument('--check', action='store_true', help='compare with the shipped costume_mat_shaders.json')
    a = ap.parse_args(argv)
    exe = open(a.exe, 'rb').read()
    costume_mat.lire_pe(exe)                           # same version check as the patcher
    recipe = build_recipe(exe)
    text = json.dumps(recipe, indent=1, ensure_ascii=True) + '\n'
    path = os.path.join(HERE, costume_mat.DONNEES)
    if a.check:
        with open(path, encoding='utf-8') as f:
            same = json.load(f) == recipe
        print('shipped recipe %s the rules applied to %s' % ('MATCHES' if same else 'DIFFERS FROM', a.exe))
        return 0 if same else 1
    if a.write:
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        print('written:', path)
        return 0
    sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
