#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build shaders.h (needed to compile direct_runtime.cpp) from YOUR copy of Game.exe.

    python make_shaders_h.py "C:\\Games\\Spider-man 3\\Game.exe"          writes shaders.h here
    python make_shaders_h.py "path\\to\\Game.exe" --out other\\shaders.h

Why a generator. shaders.h holds 4 pixel shaders of the game, each twice: the original (so the
draw adapter can recognise it when the game sets it) and a modified copy. Both are game bytecode,
so they are not published. venom_direct_shaders.json only says how to turn the original into the
modified copy; this script reads the originals from the player's Game.exe and follows it.

What the modification is. These 4 shaders draw Venom with his palette: they read a palette INDEX
from one texture, then look the colour up in a palette texture (about 35 instructions). The
modified copy replaces that lookup with two instructions of ours:
    texld r0, v1, s6        read the colour directly from a full-colour atlas bound to sampler 6
    mov   r1, cN.w          put back the zero the removed block used to leave in r1
Everything else (lighting, fog, normal mapping) is the game's code, unchanged. The constant
table comment is dropped (like the original build did, which re-assembled the shader).

Checks. Each original shader must match its sha256 fingerprint (an already patched Game.exe is
refused: use an intact copy), the result must match the fingerprint of the expected modified
shader, and the signature (FNV-1a hash of the instruction tokens, the value direct_runtime.cpp
computes at run time to recognise a shader) is recomputed and compared.

Output format: identical, byte for byte, to the shaders.h made by the first build (Windows line
endings, no newline at the end), so a rebuild can be compared with sha256.
"""
import argparse
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RECIPE = os.path.join(HERE, 'venom_direct_shaders.json')
EXE_SIZE = 10846998              # original Game.exe of Spider-Man 3 PC (2007)


def instructions(tokens):
    """Instruction token groups after the version token: comments dropped, END token kept."""
    out, i = [], 1
    while i < len(tokens):
        t = tokens[i]
        if t == 0x0000FFFF:
            out.append([t])
            return out
        if t & 0xFFFF == 0xFFFE:                       # comment (the constant table)
            i += 1 + ((t >> 16) & 0x7FFF)
            continue
        n = (t >> 24) & 0xF                            # operand count of this instruction
        out.append(list(tokens[i:i + 1 + n]))
        i += 1 + n
    raise ValueError('shader without END token')


def signature(tokens):
    """FNV-1a over every non-comment token, exactly as HashShader() in direct_runtime.cpp."""
    h, i = 2166136261, 0
    while i < len(tokens):
        t = tokens[i]
        op = t & 0xFFFF
        if op == 0xFFFE:
            i += 1 + ((t >> 16) & 0x7FFF)
            continue
        n = 1 if i == 0 or op == 0xFFFF else 1 + ((t >> 24) & 0xF)
        for x in tokens[i:i + n]:
            for b in struct.pack('<I', x):
                h = ((h ^ b) * 16777619) & 0xFFFFFFFF
        i += n
    return h


def build(exe_bytes, recipe):
    """[(name, original tokens, modified tokens, signature)] or SystemExit with the reason."""
    if len(exe_bytes) != EXE_SIZE:
        raise SystemExit('Game.exe is %d bytes instead of %d: not the original Spider-Man 3 PC executable.'
                         % (len(exe_bytes), EXE_SIZE))
    result = []
    for s in recipe['shaders']:
        raw = exe_bytes[s['offset']:s['offset'] + s['size']]
        if hashlib.sha256(raw).hexdigest() != s['sha256_original']:
            raise SystemExit('Shader %s at file offset 0x%X is not the original one (Game.exe already '
                             'patched by another tool?). Use an intact copy of Game.exe. Nothing written.'
                             % (s['name'], s['offset']))
        original = list(struct.unpack('<%dI' % (len(raw) // 4), raw))
        listing = instructions(original)
        modified = [original[0]]                       # version token (ps_3_0)
        for e in s['edits']:
            if e['op'] == 'copy':
                for ins in listing[e['first']:e['end']]:
                    modified += ins
            elif e['op'] == 'insert':
                modified += [int(t, 16) for t in e['tokens']]
            elif e['op'] != 'skip':
                raise SystemExit('venom_direct_shaders.json is damaged (unknown edit %r).' % e['op'])
        data = struct.pack('<%dI' % len(modified), *modified)
        if hashlib.sha256(data).hexdigest() != s['sha256_modified']:
            raise SystemExit('The recipe did not rebuild the expected shader %s (damaged recipe?).' % s['name'])
        sig = signature(original)
        if '%08x' % sig != s['signature']:
            raise SystemExit('Signature mismatch for %s.' % s['name'])
        result.append((s['name'], original, modified, sig))
    return result


def header_text(recipe, shaders):
    lines = [recipe['header_comment']]
    for name, original, modified, _ in shaders:
        lines.append('static const DWORD native_' + name + '[]={' + ','.join(hex(x) for x in original) + '};')
        lines.append('static const DWORD ' + name + '[]={' + ','.join(hex(x) for x in modified) + '};')
    lines.append('struct ShaderEntry { DWORD signature; const DWORD* code; const DWORD* original; };')
    lines.append('static const ShaderEntry shaderEntries[]={' + ','.join(
        '{' + hex(sig) + ',' + name + ',native_' + name + '}' for name, _, _, sig in shaders) + '};')
    return '\r\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Build shaders.h for the Venom draw adapter from your Game.exe.')
    ap.add_argument('exe', help='Game.exe of Spider-Man 3 PC with its original shaders (or an intact copy)')
    ap.add_argument('--out', default=os.path.join(HERE, 'shaders.h'))
    a = ap.parse_args(argv)
    with open(RECIPE, encoding='utf-8') as f:
        recipe = json.load(f)
    with open(a.exe, 'rb') as f:
        shaders = build(f.read(), recipe)
    text = header_text(recipe, shaders)
    with open(a.out, 'wb') as f:
        f.write(text.encode('ascii'))
    print('written %s (%d shaders, sha256 %s)' % (a.out, len(shaders), hashlib.sha256(text.encode('ascii')).hexdigest()))
    for name, original, modified, sig in shaders:
        print('  %s: signature %08x, %d -> %d tokens' % (name, sig, len(original), len(modified)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
