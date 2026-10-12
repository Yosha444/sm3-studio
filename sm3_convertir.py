# SPDX-License-Identifier: GPL-3.0-or-later
"""sm3_convertir.py - one 3D model -> one Spider-Man 3 (PC, 2007) suit mod, in one command.

("convertir" = convert.) This is the converter behind SM3 Studio: the window (sm3_interface.py,
method Studio._travailler) and the command-line mode of SM3 Studio.exe (_sans_fenetre) both set
`sys.argv = ['sm3_convertir'] + options` and call main() in-process. It chains everything that
was learnt, in order, with settings calibrated on the vanilla model, and ends with a check of the
delivered bytes. Every stage keeps its output in build/<mod>/, so any stage can be re-run with
`--depuis` (French: "from").

    python sm3_convertir.py --src model.gltf --textures folder/ --nom MyMod

    stage      what it does                                            Blender?
    ---------  ------------------------------------------------------  ---------
    chaine     alignment on the template, weights from the vanilla     YES
               model, atlas baking, export of the 000
               (tools/chaine_officielle.py run inside Blender)
    ajuster    manual pose correction, only if a manual setting is     no
               used (ajuster.py)
    bras       puts the arms back into the vanilla A-pose              no
               (-36.6 deg) (redresser_bras.py); skipped for rigged
               models already conformed to the game skeleton
    poids      re-skinning: the game's own weights by neighbourhood    no
               (poids_depuis_vanilla.py, default) or by distance to
               bone SEGMENTS (poids_par_segments.py), then, for
               models without a rig, limbs and fingers posed on the
               game skeleton (tools/conformer_sans_rig.py,
               tools/doigts_sans_rig.py)
    lod        writes the REAL 001 in ITS own frame (transplanter_lod)  no
    atlas      dilates the gutters (dilater_atlas.py), then encodes    no
               the .tex files (tools/png2tex.py)
    verifier   the check list, run on the written bytes                no
    assembler  copies the files under every scope of the catalogue     no
               (mods/<mod>/<pack>/<archive folder>/, xeSM3 layout)

(chaine = chain, ajuster = adjust, bras = arms, poids = weights, lod = the second model,
verifier = check, assembler = assemble.) The stages `bras` and `poids` are only useful when the
model is a CHARACTER whose pose or proportions differ from the vanilla model; `--sans-retouche`
("without touch-up") skips them.

Files: the 000 is ch_spiderman000.mesh (hash 0xAC92103D), the player model; the 001 is
ch_spiderman001.mesh (0xAC92103E), the suit's second model, stored in another frame:
(x, y, z)_001 = (z, y + 1.199, -x)_000. The atlas is ch_spiderman_spider.tex (0x8E661B33). The
vanilla files (vanilla/CH_SPIDERMAN/...) are extracted from the player's own game by
tools/extraire_donnees_jeu.py the first time (see main()); they are not distributed.

Other targets: --target venom and --target blacksuit hand the whole conversion to
tools/venom_runner.py and tools/blacksuit_runner.py; a recognised Spider-Man: Web of Shadows
export goes to tools/rvb_runner.py.

Blender: the window passes its "blender.exe" setting. On the command line, the SM3_BLENDER
environment variable, then the "blender" key of sm3_studio.json (next to SM3 Studio.exe, or next
to this file from source), then the default Blender 5.2 install path are used.

Output conventions read by the window (sm3_interface.Studio._vider_fil colours the log by
prefix): '[convertir] ---' starts a section, '[convertir] CONTROLE' is the final verdict, lines
starting with 'OK ' or '!!' are passed / failed checks. Keep those prefixes.
"""
from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys

import numpy as np

# ICI ("here") = folder of this file (inside the .exe: sys._MEIPASS). RACINE ("root") = project
# folder; the window and the command-line mode overwrite it after loading this module. Default:
# this folder when tools\ sits next to this file (the repository and the installed tool), else
# its parent (the layout of the original development tree).
ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = ICI if os.path.isdir(os.path.join(ICI, 'tools')) else os.path.dirname(ICI)
sys.path.insert(0, ICI)
from poids_par_segments import lire_skin  # noqa: E402
from sm3_sans_blender import fmt  # noqa: E402


def _default_blender():
    """blender.exe used when the window does not provide one (command-line conversions).

    Order: the SM3_BLENDER environment variable; the "blender" setting of sm3_studio.json (Paths
    tab of the window; the file sits next to SM3 Studio.exe, or next to this file when run from
    source); the default install path of Blender 5.2."""
    explicit = os.environ.get('SM3_BLENDER', '').strip().strip('"')
    if explicit:
        return explicit
    folder = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else ICI
    try:
        import json
        with open(os.path.join(folder, 'sm3_studio.json'), encoding='utf-8-sig') as f:
            setting = str(json.load(f).get('blender') or '').strip().strip('"')
        if setting:
            return setting
    except (OSError, ValueError, AttributeError):
        pass
    return r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'


BLENDER = _default_blender()
VANILLA = os.path.join(RACINE, 'vanilla', 'CH_SPIDERMAN', '_O0069.0xCFB154CD.T36.apkf')
SKEL000 = '0x461356AE.ch_spidermanskeleton_ch_spiderman000.skel'
SKEL001 = '0x461356AF.ch_spidermanskeleton_ch_spiderman001.skel'
MESH000 = '0xAC92103D.ch_spiderman000.mesh'
MESH001 = '0xAC92103E.ch_spiderman001.mesh'
ATLAS = '0x8E661B33.ch_spiderman_spider.tex'
# The normal-map slot of ALL the suit materials (spider, sideweb, topweb) points to this same
# texture -- checked in SPIDERMAN_MESH_MAT_TEX_CHAIN.csv (a mesh -> material -> texture table of
# the research notes, not distributed), field +0x80 of the material. What the
# game puts there is a FLAT 32x32 placeholder (every texel at (0,132,0,127), standard deviation
# 0), hence a suit with no relief at all. See tools/normale_bake.py.
NORMALE = '0x61DCA273.normswizzle.tex'

# The two possible material slots for the BODY of the 000, measured on the game's .mat files:
#
#   ref     name      +0x50  +0x54   +0x70   tiling
#   0x614   spider    0.000  0.200   0.000    1.00   specular fixed at 0.200; +0x70 = 0 turns OFF
#                                                    the hemispherical ambient AND the rim light
#   0x37C   sideweb   0.000  0.000   1.000    1.00   specular multiplied by ZERO; ambient and
#                                                    rim ON
#
# Both have identity tiling, and both point their normal slot (+0x80) to `_normswizzle`: the
# relief survives the switch. The difference is `+0x70`, which the shader reads in c0.z to compute
# r6.y = sat(c0.z + c1.x), which modulates the ambient (`mad r2, r2, r6.y, r19`) and the rim
# (`mul r1, r6.y, r1`). `spider` is the ONLY one of the ten suit materials with it at zero -- it
# is the slot of the EMBLEM, not of a body.
MAT_SPIDER = 0x00000614
MAT_SIDEWEB = 0x0000037C
# The third body slot: GLOSSY. Measured on ch_spidermantopweb (0xE771757E):
#
#   shine      sat(spe.G x 2.0 + 1.0) = 1.00     five times `spider`, whatever the map
#   highlight  sat(exp.G x 0 + 0.124) x 64 = 8   WIDER than spider (13): a veil, not a dot
#   reflection sat(rfl.G x 0.25 + 0)             the atlas green x 0.25, modulated by the fresnel
#   ambient and rim ON (+0x70 = 1), tiling 1.00
#
# Its three diffuse / specular / reflection slots ALL point to `_grey`, exactly like sideweb: it
# reads the same files the sideweb option already delivers. No extra texture.
# Reference 0x640 in the blob of CH_SPIDERMAN's 000, checked in
# SPIDERMAN_MESH_MAT_TEX_CHAIN.csv (ch_spiderman000, pointer 0x640 -> ch_spidermantopweb).
MAT_TOPWEB = 0x00000640
# body slots that read the atlas under `_grey`, and the reference to write for each one
SLOTS_GRIS = {'sideweb': MAT_SIDEWEB, 'topweb': MAT_TOPWEB}
# The diffuse of sideweb: the atlas must ALSO be delivered under THIS hash, otherwise the body
# takes the game's `_grey` texture. Precedent: the CJ mod already ships a 22 MB 0x06F18556._grey.tex.
ATLAS_GRIS = '0x06F18556._grey.tex'
HASH_GRIS = 0x06F18556

# Pack -> archive folder of that pack holding the suit (xeSM3 layout: "_O" + archive index in the
# pack, archive hash, archive type 0x36 = T36). PLAN says under which packs each file goes.
SCOPES = {
    'CH_SPIDERMAN': '_O0069.0xCFB154CD.T36.apkf',
    'MARYJANE_SCARERIDE': '_O0082.0x4F920A48.T36.apkf',
    'STORY_MOVIE_3': '_O0121.0x03294B12.T36.apkf',
}
PLAN = {MESH000: ['CH_SPIDERMAN', 'MARYJANE_SCARERIDE'],
        MESH001: ['CH_SPIDERMAN', 'MARYJANE_SCARERIDE'],
        ATLAS: ['CH_SPIDERMAN', 'MARYJANE_SCARERIDE', 'STORY_MOVIE_3'],
        NORMALE: ['CH_SPIDERMAN', 'MARYJANE_SCARERIDE', 'STORY_MOVIE_3'],
        ATLAS_GRIS: ['CH_SPIDERMAN', 'MARYJANE_SCARERIDE', 'STORY_MOVIE_3']}

# Stage names, in order. They are command-line values (and values of the window's "Resume from
# stage" list): never translate them.
ETAPES = ['chaine', 'ajuster', 'bras', 'poids', 'lod', 'atlas', 'verifier', 'assembler']

FORMATS = ('.gltf', '.glb', '.fbx', '.obj', '.dae', '.ply', '.stl', '.x3d', '.abc', '.usd',
           '.usda', '.usdc', '.blend')
IMAGES = ('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.tif', '.tiff', '.dds', '.webp')
SEPT_ZIP = os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), '7-Zip', '7z.exe')


def log(*x):
    print('[convertir]', *x, flush=True)


def deballer(src, travail):
    """Accept an archive too ("unpack"): unpack it into <build>/source and find the model in it."""
    if not src.lower().endswith(('.zip', '.rar', '.7z')):
        return src
    dest = os.path.join(travail, 'source')
    os.makedirs(dest, exist_ok=True)
    if src.lower().endswith('.zip'):
        import zipfile
        zipfile.ZipFile(src).extractall(dest)
    elif os.path.exists(SEPT_ZIP):
        subprocess.run([SEPT_ZIP, 'x', '-y', '-o' + dest, src], capture_output=True)
    else:
        raise SystemExit('7-Zip not found: unpack %s by hand' % src)
    trouves = []
    for r, _, fs in os.walk(dest):
        for f in fs:
            if f.lower().endswith(FORMATS):
                trouves.append(os.path.join(r, f))
    if not trouves:
        raise SystemExit('no model (%s) in %s' % (' '.join(FORMATS), src))
    # the biggest file = the main model; the others are often variants or props
    trouves.sort(key=os.path.getsize, reverse=True)
    log('archive unpacked: %d model(s), using "%s"'
        % (len(trouves), os.path.relpath(trouves[0], dest)))
    return trouves[0]


def trouver_textures(src, donne):
    """Texture folder ("find textures"). Given > usual sub-folder > next to the model > search."""
    if donne:
        return donne
    base = os.path.dirname(os.path.abspath(src))
    # Look in the PARENT too: the `source/model.fbx` + sibling `textures/` layout is Sketchfab's,
    # very common, and a look in the model's folder alone misses it.
    for racine in (base, os.path.dirname(base)):
        for nom in ('textures', 'texture', 'tex', 'Textures', 'maps', 'images'):
            c = os.path.join(racine, nom)
            if os.path.isdir(c) and any(f.lower().endswith(IMAGES) for f in os.listdir(c)):
                log('textures: %s' % c)
                return c
    if any(f.lower().endswith(IMAGES) for f in os.listdir(base)):
        log('textures next to the model: %s' % base)
        return base
    for r, _, fs in os.walk(base):
        if any(f.lower().endswith(IMAGES) for f in fs):
            log('textures found by searching: %s' % r)
            return r
    log('no external image: the model must carry its textures inside (glb, embedded fbx)')
    return base


_MODULES = {}


def _module(chemin):
    """Import one of our scripts once, by path (the module name is the file name)."""
    import importlib.util
    nom = os.path.splitext(os.path.basename(chemin))[0]
    if nom not in _MODULES:
        sp = importlib.util.spec_from_file_location(nom, chemin)
        m = importlib.util.module_from_spec(sp)
        sys.modules[nom] = m
        sp.loader.exec_module(m)
        _MODULES[nom] = m
    return _MODULES[nom]


def lance(cmd, quoi):
    """Run one stage ("launch"). `quoi` ("what") is the human description logged as a title.

    Our own stages run IN-PROCESS, not by starting Python again. In a frozen .exe,
    `sys.executable` is the executable itself: starting it again would reopen the window instead
    of running the stage. Only Blender stays a real subprocess, since it is external anyway.
    """
    log('--- %s' % quoi)
    interne = len(cmd) >= 2 and str(cmd[1]).lower().endswith('.py') and cmd[0] == sys.executable
    if interne:
        # `sys.argv` BEFORE the import, not after. A tool written "flat" -- parse_args() at
        # module level -- otherwise read the CONVERTER's command line while loading. That is
        # what gave "sm3_convertir: error: unrecognized arguments: --nom ...": the positional
        # `mesh` of winding_fix.py swallowed the mod name, the rest became extras, and the prog
        # name shown was the converter's. So the error seemed to come from here.
        vieux = sys.argv
        sys.argv = [cmd[1]] + [str(x) for x in cmd[2:]]
        try:
            m = _module(cmd[1])
            travail = getattr(m, 'main', None)
            if callable(travail):
                travail()
        except SystemExit as e:
            if e.code:
                raise SystemExit('%s failed: %s' % (quoi, e.code))
        finally:
            sys.argv = vieux
        return
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    # Only the summary lines of the tools are echoed (their log prefixes; '  ecrit' is an older
    # tool output). These are patterns of other tools' output: keep them as they are.
    for ligne in (r.stdout or '').splitlines():
        if ligne.startswith(('[chaine]', '[poids]', '[poids-van]', '[bras]', '[transplant]', '[dilat]', '  ecrit')):
            print('    ' + ligne, flush=True)
    if r.returncode != 0:
        print((r.stdout or '')[-3000:])
        print((r.stderr or '')[-2000:])
        raise SystemExit('%s failed (code %d)' % (quoi, r.returncode))


def couleur_hq():
    """Vertex colour (R, G, B, A) to write on every vertex: qualite.json "vertex_color" (set by
    the window's "Vertex color - gray" field), mid-grey if the file is missing."""
    import json
    path = os.path.join(RACINE, 'qualite.json')
    if not os.path.isfile(path):
        return (128, 128, 128, 255)
    with open(path, encoding='utf-8-sig') as f:
        value = json.load(f).get('vertex_color', [128, 128, 128, 255])
    if len(value) != 4 or any(type(c) is not int or not 0 <= c <= 255 for c in value):
        raise ValueError('vertex_color must hold four integers from 0 to 255')
    return tuple(value)


def appliquer_couleur_hq(path, rgba=None):
    """Write `rgba` into the COLOR attribute (D3DDECLUSAGE 10, 4 bytes) of every vertex of the
    .mesh at `path`, in place. Returns the number of vertices written."""
    rgba = couleur_hq() if rgba is None else tuple(rgba)
    mesh = fmt.parse_mesh(path)
    data = bytearray(mesh.raw)
    count = 0
    for section in mesh.sections:
        if not section.vertex_count:
            continue
        declarations = [d for d in section.decl if d.usage == 10]
        if not declarations:
            raise RuntimeError('HQ: section without a colour attribute')
        for declaration in declarations:
            if declaration.offset + 4 > section.vertex_stride:
                raise RuntimeError('HQ: invalid colour declaration')
            for i in range(section.vertex_count):
                offset = section.vertex_buffer_offset + i * section.vertex_stride + declaration.offset
                data[offset:offset + 4] = bytes(rgba)
            count += section.vertex_count
    with open(path, 'wb') as f:
        f.write(data)
    log('HQ colour %s: %s on %d vertices' % (os.path.basename(path), rgba, count))
    return count


# --------------------------------------------------------------------------- checks
def verifier(dossier, vanilla):
    """The check list (step 5 of the method), run on the written bytes of build folder `dossier`
    against the vanilla folder. Prints one 'OK ' / '!! ' line per check; returns True if all
    passed."""
    ok = True
    res = []

    def dire(nom, bon, valeur, attendu):
        # "say": record one check line (name, passed?, measured value, expectation)
        nonlocal ok
        ok = ok and bon
        res.append(('  %s  %-34s %-30s %s' % ('OK ' if bon else '!! ', nom, valeur, attendu)))

    m0 = fmt.parse_mesh(os.path.join(dossier, MESH000))
    m1 = fmt.parse_mesh(os.path.join(dossier, MESH001))
    dire('internal hash of the 000', m0.filename_hash == 0xAC92103D,
         '0x%08X' % m0.filename_hash, 'expected 0xAC92103D')
    dire('internal hash of the 001', m1.filename_hash == 0xAC92103E,
         '0x%08X' % m1.filename_hash, "expected 0xAC92103E  (not the 000's)")
    r0 = {s.material_ref_serialized for s in m0.sections}
    r1 = {s.material_ref_serialized for s in m1.sections}
    NON_TILES = {0x614, 0x37C, 0x640, 0xA0}
    dire('000 materials not tiled', r0 <= NON_TILES,
         ' '.join('0x%X' % x for x in sorted(r0)), 'among 614 37C 640 A0')
    dire('material of the 001', r1 == {0x560},
         ' '.join('0x%X' % x for x in sorted(r1)), 'expected 0x560')
    # 16-bit indices only: the game truncates 32-bit indices without warning (Game.exe
    # 0x8CF1E0) and the model comes out torn. winding_fix already splits sections that are too
    # big (tools/decoupe_sections.py); this check catches a resumed run (--depuis atlas...) that
    # skipped it. Uses the toolkit reader only, so it also works inside the .exe.
    for label, model in (('000', m0), ('001', m1)):
        trop = [s for s in model.sections if s.vertex_count > 0xFFFF or s.index_size != 2]
        dire('sections of the %s' % label, not trop,
             '%d, at most %d vertices%s' % (len(model.sections),
                                            max([s.vertex_count for s in model.sections] or [0]),
                                            ', 32-bit indices' if any(s.index_size != 2 for s in trop)
                                            else ''),
             'at most 65,535 vertices, 16-bit indices')

    def infos(m):
        # positions, raw int16 UVs (D3DDECLUSAGE 5) and colours (10) of all sections
        P, U, C = [], [], []
        for s in m.sections:
            if not s.vertex_count:
                continue
            d = fmt.decode_section_vertices(m, s, uv_divisor=1000.0)
            P.append(np.array(d['positions'], np.float64))
            b = np.frombuffer(m.raw[s.vertex_buffer_offset:
                                    s.vertex_buffer_offset + s.vertex_count * s.vertex_stride],
                              np.uint8).reshape(s.vertex_count, s.vertex_stride)
            uo = [dc.offset for dc in s.decl if dc.usage == 5][0]
            co = [dc.offset for dc in s.decl if dc.usage == 10]
            U.append(b[:, uo:uo + 4].copy().view(np.int16))
            if co:
                C.append(b[:, co[0]:co[0] + 4])
        return np.concatenate(P), np.concatenate(U), (np.concatenate(C) if C else None)

    P0, U0, C0 = infos(m0)
    P1, U1, C1 = infos(m1)
    dire('colour of the 001', C1 is not None and bool(np.all(C1 == np.array(couleur_hq(), dtype=np.uint8))),
         str(couleur_hq()), 'same as the 000 on every vertex')
    dire('UV of the 000 in [0, 1000]', 0 <= U0.min() and U0.max() <= 1000,
         '%d..%d' % (U0.min(), U0.max()), 'otherwise it wraps around in game')
    dire('UV of the 001 in [0, 1000]', 0 <= U1.min() and U1.max() <= 1000,
         '%d..%d' % (U1.min(), U1.max()), '')
    if C0 is not None:
        u, c = np.unique(C0, axis=0, return_counts=True)
        dom = u[np.argmax(c)]
        dire('vertex colour', bool(np.all(C0 == np.array(couleur_hq(), dtype=np.uint8))),
             str(dom.tolist()), 'expected %s on EVERY vertex' % (couleur_hq(),))
    # frame of the 001: (z, y + 1.199, -x) of the 000
    att = np.stack([P0[:, 2], P0[:, 1] + 1.199, -P0[:, 0]], 1)
    if len(att) == len(P1):
        ec = float(np.abs(att - P1).max())
        dire('frame of the 001', ec < 0.01, 'max gap %.4f' % ec, '(z, y+1.199, -x) of the 000')
    # orientation
    T, base = [], 0
    for s in m0.sections:
        if not s.vertex_count:
            continue
        idx = fmt.read_indices(m0, s)
        T.append(np.array(fmt.indices_to_faces(idx, s.primitive_type, s.vertex_count),
                          np.int64) + base)
        base += s.vertex_count
    T = np.concatenate(T)
    a, b2, c2 = P0[T[:, 0]], P0[T[:, 1]], P0[T[:, 2]]
    vol = float(np.einsum('ij,ij->i', a, np.cross(b2, c2)).sum() / 6.0)
    dire('signed volume', vol < 0, '%+.4f' % vol, 'must be negative (vanilla -0.116)')
    pals = [len(s.bone_palette or []) for s in m0.sections]
    dire('bone palette', max(pals) <= 48, 'max %d' % max(pals), 'at most 48')
    for label,model in [('000',m0),('001',m1)]:
        maximum=0
        for section in model.sections:
            decoded=fmt.decode_section_vertices(model,section,uv_divisor=1000)
            weights=np.array(decoded['blend_weights']);indices=np.array(decoded['blend_indices'])
            if np.any(weights>0):maximum=max(maximum,int(indices[weights>0].max()))
        # 48, not 32: `world` occupies c0..c191 in the game's 12 skinned vertex shaders, i.e.
        # 48 matrices, and the vanilla ch_spiderman000 has three sections with 48 bones.
        dire('shader indices '+label,maximum<48,str(maximum),'active indices 0 to 47')

    # atlas: header of the written .tex (width +0x18, height +0x1C, mip count +0x24)
    pa = os.path.join(dossier, ATLAS)
    if os.path.exists(pa):
        import struct
        d = open(pa, 'rb').read()
        w, h, mips = (struct.unpack_from('<I', d, o)[0] for o in (0x18, 0x1C, 0x24))
        dire('atlas', mips >= 8, '%dx%d, %d mips' % (w, h, mips),
             'complete mip chain, otherwise it shimmers')

    # skinning: compared with the vanilla model
    mv, Pv, Gv, Wv = lire_skin(os.path.join(vanilla, MESH000))
    _, Pn, Gn, Wn = lire_skin(os.path.join(dossier, MESH000))
    Wnn = Wn / np.maximum(Wn.sum(1, keepdims=True), 1e-9)
    Wvn = Wv / np.maximum(Wv.sum(1, keepdims=True), 1e-9)
    # Do NOT compare the global median of the dominant weight between two models: it depends on
    # how the vertices are DISTRIBUTED. A model with a lot of head (a zone rigid at 100 % in the
    # vanilla model) comes out at 1.00 with perfect weights. This check cried wolf.
    # The right measurement: the gap between our weights and the vanilla ones AT THE SAME PLACE.
    import importlib.util as _iu0
    _sp0 = _iu0.spec_from_file_location('_pdv', os.path.join(ICI, 'poids_depuis_vanilla.py'))
    _pdv = _iu0.module_from_spec(_sp0)
    sys.modules['_pdv'] = _pdv
    _sp0.loader.exec_module(_pdv)
    _ech = np.random.default_rng(0).choice(len(Pn), min(1200, len(Pn)), replace=False)
    _idx, _dst = _pdv.plus_proches(Pn[_ech], Pv, 1)
    _ecarts = []
    for _k, _i in enumerate(_ech):
        _a = {int(Gn[_i, c]): float(Wnn[_i, c]) for c in range(Gn.shape[1]) if Wnn[_i, c] > 0.01}
        _v = int(_idx[_k, 0])
        _b = {int(Gv[_v, c]): float(Wvn[_v, c]) for c in range(Gv.shape[1]) if Wvn[_v, c] > 0.01}
        _ecarts.append(sum(abs(_a.get(o, 0) - _b.get(o, 0)) for o in set(_a) | set(_b)) / 2)
    _ec = float(np.median(_ecarts))
    dire('weights close to the vanilla', _ec < 0.35, 'median gap %.2f at the same place' % _ec,
         '0 = the game weights, 1 = no bone in common')

    # Two measurements that only show up when ANIMATED: at rest everything looks clean, and as
    # soon as the skeleton moves the limbs stretch. They caught 32.6 % of vertices pulled at the
    # same time by a left bone and a right bone - the vanilla model has 0.23 %.
    import importlib.util as _iu
    _sp = _iu.spec_from_file_location('_pps', os.path.join(ICI, 'poids_par_segments.py'))
    _pps = _iu.module_from_spec(_sp)
    sys.modules['_pps'] = _pps
    _sp.loader.exec_module(_pps)
    _skc = os.path.join(vanilla, SKEL000)
    if os.path.exists(_skc):
        _sk = fmt.parse_skeleton(_skc)
        _nm = {b.index: b.name for b in _sk.bones}
        _pa = {b.index: b.parent_index for b in _sk.bones}

        def _stats(G, W):
            # (% of vertices with influences on both sides, largest hierarchy gap)
            Wn2 = W / np.maximum(W.sum(1, keepdims=True), 1e-9)
            mixte = 0
            hmax = 0
            for i in range(len(G)):
                act = [int(G[i, c]) for c in range(G.shape[1]) if Wn2[i, c] > 0.05]
                if len(act) < 2:
                    continue
                cs = {_pps._cote(_nm.get(b, '')) for b in act if _pps._cote(_nm.get(b, ''))}
                if len(cs) > 1:
                    mixte += 1
                hmax = max(hmax, max(_pps._sauts(_pa, a, b) for a in act for b in act))
            return 100.0 * mixte / max(1, len(G)), hmax

        mx_n, h_n = _stats(Gn, Wn)
        mx_v, h_v = _stats(Gv, Wv)
        dire('sides not mixed', mx_n <= max(1.0, mx_v * 4),
             '%.2f %% of vertices left+right' % mx_n,
             'vanilla %.2f %% - above that, rubbery limbs' % mx_v)
        dire('hierarchy consistency', h_n <= max(5, h_v),
             'max gap %d edges' % h_n, 'vanilla %d' % h_v)

    print('\n'.join(res))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slot', default='spider', choices=['spider', 'sideweb', 'topweb'],
                    help='material slot of the BODY. spider = the game\'s (shine 0.20, highlight 13, ambient and rim off). sideweb = MATTE: shine at zero, ambient and rim back on. topweb = GLOSSY: shine 1.00, wide highlight (8), a little environment reflection, ambient and rim on. The relief of the normal map works in all three cases.')
    ap.add_argument('--target', default='spiderman', choices=['spiderman', 'venom', 'blacksuit'])
    ap.add_argument('--src', default='',
                    help='source model: gltf glb fbx obj dae ply stl usd blend, or a '
                         'zip/rar/7z archive (the model is looked for inside)')
    ap.add_argument('--textures', default='',
                    help='texture folder. Empty = automatic detection')
    ap.add_argument('--nom', required=True, help='mod name')
    ap.add_argument('--vanilla', default=VANILLA)
    ap.add_argument('--out', default='')
    ap.add_argument('--bake', type=int, default=2048)
    ap.add_argument('--drop', default='', help='source materials to drop (decals)')
    ap.add_argument('--materiaux', default='',
                    help="manual texture assignment: 'mat0=a.png,mat1=b.png'")
    ap.add_argument('--depuis', default='chaine', choices=ETAPES)
    ap.add_argument('--sans-retouche', action='store_true',
                    help='skip `bras` and `poids`: for a model already in the vanilla pose')
    ap.add_argument('--dilate', type=int, default=24)
    ap.add_argument('--format', default='DXT5', choices=['DXT1', 'DXT5', 'ARGB8'])
    # ---------------- MANUAL corrections, for when the automatic alignment misses
    ap.add_argument('--echelle', type=float, default=1.0, help='MANUAL: scale factor')
    ap.add_argument('--rot-x', type=float, default=0.0, help='MANUAL: rotation in degrees')
    ap.add_argument('--rot-y', type=float, default=0.0)
    ap.add_argument('--rot-z', type=float, default=0.0)
    ap.add_argument('--decalage', default='', help='MANUAL: offset dx,dy,dz')
    ap.add_argument('--poser-au-sol', action='store_true',
                    help='MANUAL: match the height exactly to the vanilla model\'s')
    ap.add_argument('--puissance', default='auto',
                    help="MANUAL: sharpness of the segment skinning. 'auto' calibrates it on the vanilla model")
    ap.add_argument('--part-mini', type=float, default=0.001,
                    help='MANUAL: share of the vanilla vertices a bone must dominate to be used')
    ap.add_argument('--methode-poids', default='vanilla', choices=['vanilla', 'segments'],
                    help="'vanilla' (default) takes Treyarch's REAL weights by neighbourhood: "
                         "right bones, right nuances, left/right consistency inherited. 'segments' "
                         "BUILDS them from distances to the bones - a fallback when the two bodies "
                         "do not overlap at all.")
    ap.add_argument('--mods', default='',
                    help='where to put the deliverable mod; by default next to --out')
    ap.add_argument('--voisins', type=int, default=6,
                    help='vanilla vertices blended per vertex (vanilla method)')
    ap.add_argument('--fondu-bras', type=float, default=0.10,
                    help='MANUAL: width of the shoulder blend when the arms are straightened')
    A = ap.parse_args()
    # The game data (vanilla/, profiles/) is not distributed with SM3 Studio: the first conversion
    # rebuilds it from the player's own copy of Spider-Man 3 (tools/extraire_donnees_jeu.py).
    # When everything is already there, this only checks that the files exist.
    extractor = os.path.join(RACINE, 'tools', 'extraire_donnees_jeu.py')
    if os.path.isfile(extractor):
        _module(extractor).ensure_game_data(RACINE, log=log, blender=BLENDER)
    if A.target in ('spiderman', 'blacksuit') and A.src:
        rvb = _module(os.path.join(RACINE, 'tools', 'rvb_runner.py'))
        if rvb.recognize(A.src, RACINE):
            return rvb.run(A, RACINE, BLENDER, fmt)
    if A.target == 'blacksuit':
        return _module(os.path.join(RACINE, 'tools', 'blacksuit_runner.py')).run(A, RACINE, BLENDER, fmt)
    if A.target == 'venom':
        return _module(os.path.join(RACINE, 'tools', 'venom_runner.py')).run(A, RACINE, BLENDER, fmt)
    # The window's quality panel writes the atlas resolution to qualite.json; it wins over --bake.
    import json
    quality_path = os.path.join(RACINE, 'qualite.json')
    if os.path.isfile(quality_path):
        with open(quality_path, encoding='utf-8-sig') as quality_file:
            A.bake = int(json.load(quality_file)['resolution'])


    out = A.out or os.path.join(RACINE, 'build', A.nom.lower())
    os.makedirs(out, exist_ok=True)
    if A.src:
        A.src = deballer(A.src, out)
        if not A.src.lower().endswith(FORMATS):
            raise SystemExit('unsupported format: %s (expected: %s)'
                             % (os.path.splitext(A.src)[1], ' '.join(FORMATS)))
        A.textures = trouver_textures(A.src, A.textures)
        log('source: %s' % A.src)
    faire = ETAPES[ETAPES.index(A.depuis):]      # "to do": the stages to run
    log('mod "%s" -> %s' % (A.nom, out))
    log('stages: %s' % ' '.join(faire))

    P = lambda *x: os.path.join(out, *x)   # noqa: E731   path in the build folder
    van = lambda f: os.path.join(A.vanilla, f)   # noqa: E731   path in the vanilla folder

    if 'chaine' in faire:
        if not A.src:
            raise SystemExit('--src is required for the `chaine` stage')
        if not os.path.isfile(BLENDER):
            raise SystemExit('Blender not found: %s\nThe `chaine` stage (atlas baking) needs '
                             'Blender 5.2 with the SM3 Blender Toolkit and SM3 Material Combiner '
                             'add-ons. Set "blender.exe" in the Paths tab, or the SM3_BLENDER '
                             'environment variable.' % BLENDER)
        cmd = [BLENDER, '-b', '--python-exit-code', '1', '--python', os.path.join(RACINE, 'tools', 'chaine_officielle.py'),
               '--', '--src', os.path.abspath(A.src), '--textures', os.path.abspath(A.textures),
               '--vanilla', os.path.abspath(A.vanilla), '--out', os.path.abspath(out),
               '--bake', str(A.bake)]
        if A.drop:
            cmd += ['--drop', A.drop]
        if A.materiaux:
            cmd += ['--materiaux', A.materiaux]
        lance(cmd, 'official chain (Blender): alignment, weights, baking, 000 export')

    courant = P(MESH000)      # "current": the 000 every stage reads and rewrites

    # Each stage used to write its output OVER its input (`courant`), so re-running
    # `--depuis bras` rotated the arms a SECOND time: two identical runs did not give the same
    # model. So the output of the chain is frozen, and each stage starts from the frozen output
    # of the previous one. Resuming in the middle is reproducible again.
    if 'chaine' in faire and os.path.isfile(P(MESH000)):
        shutil.copy2(P(MESH000), P('etape_chaine.mesh'))

    def depuis(*candidats):
        # first existing intermediate file among the candidates, else the current 000
        for c in candidats:
            if os.path.isfile(P(c)):
                return P(c)
        return courant

    manuel = (A.echelle != 1.0 or A.rot_x or A.rot_y or A.rot_z or A.decalage or A.poser_au_sol)
    for obsolete, cond in (('etape_ajuste.mesh', 'ajuster' in faire and not manuel),
                           ('etape_bras.mesh', 'bras' in faire and A.sans_retouche)):
        if cond and os.path.isfile(P(obsolete)):
            os.remove(P(obsolete))          # otherwise an old output silently becomes an input

    if 'ajuster' in faire and manuel:
        cmd = [sys.executable, os.path.join(ICI, 'ajuster.py'),
               '--mesh', depuis('etape_chaine.mesh'),
               '--out', P('etape_ajuste.mesh'), '--echelle', str(A.echelle),
               '--rot-x', str(A.rot_x), '--rot-y', str(A.rot_y), '--rot-z', str(A.rot_z),
               '--decalage', A.decalage or '0,0,0']
        if A.poser_au_sol:
            cmd += ['--poser-au-sol', '--vanilla', van(MESH000)]
        lance(cmd, 'manual pose correction')
        shutil.copy2(P('etape_ajuste.mesh'), courant)

    # The chain has placed the model's joints on those of the game skeleton (its own rig,
    # tools/conformer_squelette.py): the arms are ALREADY in the vanilla A-pose, to the joint.
    # `redresser_bras` would still rotate them (its refinement searches +-25 deg against the
    # vanilla surface, which does not have the same thickness) and undo that exact fit.
    conforme = os.path.isfile(P('conforme.json'))
    if not A.sans_retouche and 'bras' in faire and conforme:
        if os.path.isfile(P('etape_bras.mesh')):
            os.remove(P('etape_bras.mesh'))      # otherwise an old output would become the input
        log('--- bras: skipped, the model was conformed to the game skeleton (conforme.json)')
    def skinning(entree, quoi):
        # re-skin `entree` with the chosen method into etape_poids.mesh, then make it current
        if A.methode_poids == 'vanilla':
            lance([sys.executable, os.path.join(ICI, 'poids_depuis_vanilla.py'),
                   '--mesh', entree, '--vanilla', van(MESH000), '--skel', van(SKEL000),
                   '--voisins', str(A.voisins), '--out', P('etape_poids.mesh')],
                  'skinning: the REAL vanilla weights, by neighbourhood' + quoi)
        else:
            lance([sys.executable, os.path.join(ICI, 'poids_par_segments.py'),
                   '--mesh', entree, '--vanilla', van(MESH000), '--skel', van(SKEL000),
                   '--puissance', str(A.puissance), '--part-mini', str(A.part_mini),
                   '--out', P('etape_poids.mesh')],
                  'skinning built from distances to bone segments' + quoi)
        shutil.copy2(P('etape_poids.mesh'), courant)

    if not A.sans_retouche:
        if 'bras' in faire and not conforme:
            lance([sys.executable, os.path.join(ICI, 'redresser_bras.py'),
                   '--mesh', depuis('etape_ajuste.mesh', 'etape_chaine.mesh'),
                   '--vanilla', van(MESH000), '--fondu', str(A.fondu_bras),
                   '--out', P('etape_bras.mesh')],
                  'arms put back into the vanilla A-pose')
            shutil.copy2(P('etape_bras.mesh'), courant)
        if 'poids' in faire:
            skinning(depuis('etape_bras.mesh', 'etape_ajuste.mesh', 'etape_chaine.mesh'), '')
            if not conforme:
                # Model WITHOUT a rig (2026-10-07). `redresser_bras` only fixed the ANGLE of the
                # arms: elbow, wrist, knee, ankle stay where the model had them. They are placed
                # on the game skeleton along the centre line of each limb
                # (tools/conformer_sans_rig.py), the limbs being isolated by the weights just
                # computed -- after the straightening, otherwise a T-pose delimits them badly.
                # Then the weights are computed again on the posed geometry.
                membres = os.path.join(RACINE, 'tools', 'conformer_sans_rig.py')
                marque = P('conforme_sans_rig.json')
                if os.path.isfile(marque):
                    os.remove(marque)
                if os.path.isfile(membres):
                    try:
                        lance([sys.executable, membres, '--mesh', P('etape_poids.mesh'),
                               '--vanilla', van(MESH000), '--out', P('etape_membres.mesh')],
                              'arms and legs posed on the game skeleton (model without a rig)')
                    except SystemExit as e:
                        log('!! limb conformation failed (%s)' % e)
                if os.path.isfile(marque):
                    skinning(P('etape_membres.mesh'), ', on the posed limbs')
                # Fingers: found as branches of the hand and POSED on the game's phalanges
                # (tools/doigts_sans_rig.py), which writes doigts_modele.npz for mains_poings.
                doigts = os.path.join(RACINE, 'tools', 'doigts_sans_rig.py')
                if os.path.isfile(doigts):
                    try:
                        lance([sys.executable, doigts, '--mesh', P('etape_poids.mesh'),
                               '--out', P('etape_doigts.mesh')],
                              'fingers posed on the game phalanges (model without a rig)')
                        if os.path.isfile(P('etape_doigts.mesh')):
                            shutil.copy2(P('etape_doigts.mesh'), courant)
                    except SystemExit as e:
                        log('!! finger posing failed (%s): mains_poings will try the topology' % e)

    if 'lod' in faire:
        lance([sys.executable, os.path.join(ICI, 'transplanter_lod.py'), '--source', courant,
               '--gabarit', van(MESH001), '--skel-source', van(SKEL000),
               '--skel-cible', van(SKEL001), '--repere', 'vers001', '--material-ref', '0x560',
               '--cible', '001', '--schema', '3', '--lu-en', '1000', '--out', P(MESH001)],
              'writing the REAL 001, in its own frame')

    if any(etape in faire for etape in ('chaine', 'ajuster', 'bras', 'poids', 'lod')):
        for mesh_name in (MESH000, MESH001):
            appliquer_couleur_hq(P(mesh_name))

    if 'atlas' in faire:
        src_png = None
        for c in ('SM3_Spider_Baked_Atlas_atlas_final.png', 'atlas_final.png', 'atlas.png'):
            if os.path.exists(P(c)):
                src_png = P(c)
                break
        if src_png is None:
            raise SystemExit('no atlas found in %s' % out)
        log('atlas source: %s' % os.path.basename(src_png))
        lance([sys.executable, os.path.join(ICI, 'dilater_atlas.py'), '--atlas', src_png,
               '--mesh', courant, '--out', P('atlas_dilate.png'),
               '--pixels', str(A.dilate)], 'gutter dilation')
        # (`cmd` is only kept for reference: png2tex is called in-process just below)
        cmd = [sys.executable, os.path.join(RACINE, 'tools', 'png2tex.py'), P('atlas_dilate.png'),
               P(ATLAS), '--hash', '0x8E661B33']
        if A.format == 'DXT5':
            cmd.append('--dxt5')
        log('--- .tex encoding in %s' % A.format)
        sys.path.insert(0, os.path.join(RACINE, 'tools'))
        p2t = _module(os.path.join(RACINE, 'tools', 'png2tex.py'))
        rep = p2t.write_tex(P('atlas_dilate.png'), P(ATLAS), 0x8E661B33,
                            None, A.format, 'full', None)
        log('    .tex written: %s' % (rep if isinstance(rep, str) else 'OK'))
        # The normal map is ALWAYS DXT5, whatever --format says. The shader reads X from the
        # ALPHA (mad r3.xy, c47.x, r2.wyzw, c47.y): in DXT1 the alpha is 255 everywhere, so
        # nx = +1 and the normal becomes the pure tangent -- 88 degrees off, measured.
        if os.path.isfile(P('normale_swizzle.png')):
            rn = p2t.write_tex(P('normale_swizzle.png'), P(NORMALE), 0x61DCA273,
                               None, 'DXT5', 'full', None)
            log('    normal map written in DXT5%s: %s'
                % (' (--format %s ignored for this texture)' % A.format
                   if A.format != 'DXT5' else '',
                   rn if isinstance(rn, str) else 'OK'))
        else:
            log("    no baked normal map: the suit keeps the game's flat look.")

    if any(etape in faire for etape in ('chaine', 'ajuster', 'bras', 'poids', 'lod')):
        for mesh_name in (MESH000, MESH001):
            lance([sys.executable, os.path.join(RACINE, 'tools', 'winding_fix.py'), P(mesh_name)],
                  'check of face winding and normals')

    if A.slot in SLOTS_GRIS:
        CIBLE = SLOTS_GRIS[A.slot]
        # AFTER the export: the toolkit's exporter forces 0x614 on the 000 and refuses to write
        # anything else. So the reference is corrected AFTERWARDS, in the delivered bytes, by
        # rewriting the `material_ref_serialized` field of each section. It is the first of the
        # 12 integers of the section record, i.e. `info_offset + 0x20` (the record starts with 8
        # floats: offset, radius, box).
        # The 001 is NOT touched: its references live in its own serialised blob, where 0x37C
        # does not exist, and its only alternatives are tiled x100 (scales).
        chemin = P(MESH000)
        if os.path.isfile(chemin):
            m = fmt.parse_mesh(chemin)
            octets = bytearray(open(chemin, 'rb').read())
            change = 0
            for sec in m.sections:
                ref = sec.material_ref_serialized
                if ref != CIBLE and ref in (MAT_SPIDER,) + tuple(SLOTS_GRIS.values()):
                    struct.pack_into('<I', octets, sec.info_offset + 0x20, CIBLE)
                    change += 1
            if change:
                open(chemin, 'wb').write(bytes(octets))
            relu = {x.material_ref_serialized for x in fmt.parse_mesh(chemin).sections}
            log('--- body slot %s: %d section(s) switched to 0x%03X; read back %s'
                % (A.slot, change, CIBLE, ' '.join('0x%03X' % r for r in sorted(relu))))
            if relu != {CIBLE}:
                raise SystemExit('%s switch incomplete: references read back %s'
                                 % (A.slot, ' '.join('0x%03X' % r for r in sorted(relu))))
        # the diffuse of sideweb AND topweb is `_grey`: the atlas is delivered under BOTH hashes
        if os.path.isfile(P(ATLAS)):
            shutil.copy2(P(ATLAS), P(ATLAS_GRIS))
            p2t2 = _module(os.path.join(RACINE, 'tools', 'png2tex.py'))
            rg = p2t2.write_tex(P('atlas_dilate.png'), P(ATLAS_GRIS), HASH_GRIS,
                                None, A.format, 'full', None)
            log('    atlas also delivered as _grey (0x%08X): %s'
                % (HASH_GRIS, rg if isinstance(rg, str) else 'OK'))

    if 'verifier' in faire:
        log('--- check on the delivered bytes')
        bon = verifier(out, A.vanilla)
        # The window colours the line that starts with "CONTROLE" (French: check): keep the word.
        log('CONTROLE (final check): %s' % ('everything conforms' if bon else 'POINTS TO FIX'))
        if not bon and 'assembler' in faire:
            raise SystemExit('HQ: final check failed, mod not assembled.')

    if 'assembler' in faire:
        # The mod's destination MUST follow --out. It used to point to RACINE/mods, i.e. the
        # repository when run from the command line and a temporary folder when run from the
        # .exe: the build went to one place, the deliverable mod to another, and an old mod got
        # installed while the new one was believed to be tested. The build folder is
        # <root>/build/<name>: go up from there.
        base = os.path.dirname(os.path.dirname(os.path.abspath(out)))
        if A.mods:
            mod = os.path.join(A.mods, A.nom)
        elif os.path.basename(os.path.dirname(os.path.abspath(out))).lower() == 'build':
            mod = os.path.join(base, 'mods', A.nom)
        else:
            mod = os.path.join(RACINE, 'mods', A.nom)
        if os.path.isdir(mod):
            shutil.rmtree(mod)
        n = octets = 0
        for f, packs in PLAN.items():
            s = P(f)
            if not os.path.isfile(s):
                log('!! %s missing, not deployed' % f)
                continue
            for p in packs:
                dd = os.path.join(mod, p, SCOPES[p])
                os.makedirs(dd, exist_ok=True)
                shutil.copy2(s, os.path.join(dd, f))
                n += 1
                octets += os.path.getsize(s)
        log('mod assembled: %s - %d files, %.1f MB' % (mod, n, octets / 1e6))
        log('to test: boucle_test.ps1 -Mod %s  (as administrator)' % A.nom)


if __name__ == '__main__':
    main()
