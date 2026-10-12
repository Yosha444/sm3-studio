# SPDX-License-Identifier: GPL-3.0-or-later
"""sm3_sans_blender.py - GLB/glTF -> SM3 .mesh in pure Python, with NO Blender ("sans Blender").

This file has two roles.

1. Gateway to TSGAMING264's SM3 Blender Toolkit outside Blender. Almost every script of SM3 Studio
   does `from sm3_sans_blender import fmt`: `fmt` is the toolkit's sm3_format.py (the .mesh and
   .skel parser) and `mw` its sm3_mesh_writer.py, loaded straight from the add-on folder.
   Everything about the FORMAT in the toolkit is already Blender-free (sm3_format.py, 798 lines,
   and sm3_mesh_writer.py, 706 lines, in the version studied, contain no reference to `bpy`);
   only the add-on's __init__.py imports bpy, so a fake empty package is mounted below to load
   the two modules without it. The small geometry helpers tbn(), norme(), volume_signe() and
   normales_sortantes() are also imported by other scripts (transplanter_lod.py,
   tools/rvb_native.py).

2. An experimental Blender-free conversion (main()): read a glTF with glb.py instead of Blender's
   scene, then call the toolkit's writer directly. The normal conversion (sm3_convertir.py) does
   not use it; it goes through Blender (stage `chaine`).

    python sm3_sans_blender.py --glb model.glb --template 0xAC92103D.ch_spiderman000.mesh
                               --skel ...ch_spiderman000.skel --out output.mesh

   Reads:  --glb (glTF/GLB, with its images), --template (vanilla .mesh whose file layout and
           vertex declarations are reused), --skel (vanilla skeleton: bone names -> indices).
   Writes: --out (.mesh), and with --atlas the assembled atlas PNG (--canvas: one PNG per group,
           <atlas name>_<n>.png). Known limitation, kept as it is: --canvas fails on a glTF
           with more than one primitive (`lots.index()` compares dicts holding numpy arrays).

Frames and conventions, all copied from the Blender path so that the bytes come out identical:
  - frame       (x, y, z)_gltf -> (x, -z, y)      (Blender's glTF importer, see glb.py)
  - winding     corners 1 and 2 of each triangle are swapped (`reverse_winding=True`)
  - UV          V is flipped on import THEN on export: the two cancel out
  - divisors    position / 512 and UV * 1000 (not * 1024: the suit's vertex shader multiplies the
                UVs by 0.001, see tools/uv_1000.py)

Where the toolkit is looked for: the SM3_TOOLKIT_DIR environment variable if set, otherwise the
folder where Blender 5.2 installs extensions for the current Windows user,
%APPDATA%\\Blender Foundation\\Blender\\5.2\\extensions\\user_default\\sm3_blender_toolkit.
"""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import os
import sys

import numpy as np

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
import atlas as atlasmod  # noqa: E402
import glb as glbmod  # noqa: E402


def _toolkit_dir():
    """Folder of the SM3 Blender Toolkit add-on: $SM3_TOOLKIT_DIR, else Blender 5.2's default."""
    explicit = os.environ.get('SM3_TOOLKIT_DIR', '').strip().strip('"')
    if explicit:
        return explicit
    return os.path.join(os.environ.get('APPDATA', ''), 'Blender Foundation', 'Blender', '5.2',
                        'extensions', 'user_default', 'sm3_blender_toolkit')


EXT = _toolkit_dir()
if not os.path.isfile(os.path.join(EXT, 'sm3_format.py')):
    raise SystemExit('SM3 Blender Toolkit (TSGAMING264) not found: %s does not contain '
                     'sm3_format.py.\nInstall the add-on in Blender 5.2 '
                     '(https://github.com/TSGAMING264/SM3-Blender-Tools), or set the '
                     'SM3_TOOLKIT_DIR environment variable to its folder.' % EXT)


# The toolkit's modules use RELATIVE imports (`from .sm3_format import ...`), but its
# `__init__.py` imports bpy. So an empty fake package carrying only the `__path__` is mounted:
# the two modules we want have no Blender dependency.
_PKG = 'sm3_blender_toolkit'
if _PKG not in sys.modules:
    _faux = importlib.util.module_from_spec(
        importlib.machinery.ModuleSpec(_PKG, None, is_package=True))
    _faux.__path__ = [EXT]
    sys.modules[_PKG] = _faux


def _charge(nom):
    """Load <toolkit>/<nom>.py as sm3_blender_toolkit.<nom> (French: "load")."""
    plein = _PKG + '.' + nom
    s = importlib.util.spec_from_file_location(plein, os.path.join(EXT, nom + '.py'))
    m = importlib.util.module_from_spec(s)
    sys.modules[plein] = m
    s.loader.exec_module(m)
    setattr(sys.modules[_PKG], nom, m)
    return m


fmt = _charge('sm3_format')
mw = _charge('sm3_mesh_writer')


def log(*x):
    print('[sansblender]', *x)


# ---------------------------------------------------------------------------- TBN
def tbn(P, UV, tris):
    """Per-vertex tangent and binormal, accumulated per triangle (the classic method).

    It does not try to reproduce MikkTSpace bit for bit: the suit shader only uses this basis for
    the normal map, and our baked normal is limited to 45 degrees. What matters, and is checked
    further down, is the SIGN (signed volume and outward normals)."""
    T = np.zeros_like(P)
    B = np.zeros_like(P)
    i0, i1, i2 = tris[:, 0], tris[:, 1], tris[:, 2]
    e1, e2 = P[i1] - P[i0], P[i2] - P[i0]
    d1, d2 = UV[i1] - UV[i0], UV[i2] - UV[i0]
    det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(det) > 1e-12, 1.0 / np.where(det == 0, 1, det), 0.0)[:, None]
    t = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r
    b = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * r
    for idx in (i0, i1, i2):
        np.add.at(T, idx, t)
        np.add.at(B, idx, b)
    return T, B


def norme(v, defaut=(0.0, 0.0, 1.0)):
    """Normalise each row of v; zero-length rows become `defaut`."""
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return np.where(n > 1e-9, v / np.where(n == 0, 1, n), np.array(defaut, np.float64))


# ---------------------------------------------------------------------------- checks
def volume_signe(P, tris):
    """Signed volume of the closed surface (sum of tetrahedra from the origin). The vanilla
    ch_spiderman000 gives -0.116: with the game's winding, a correct model is NEGATIVE."""
    a, b, c = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    return float(np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6.0)


def normales_sortantes(P, N):
    """Mean cosine between each normal and the direction from the centre to its vertex
    ("outward normals"). The vanilla model gives +0.229: positive = normals point outwards."""
    d = P - P.mean(0)
    n = np.linalg.norm(d, axis=1, keepdims=True)
    return float(np.einsum('ij,ij->i', N, np.where(n > 1e-9, d / np.where(n == 0, 1, n), 0)).mean())


# ---------------------------------------------------------------------------- splitting
def decoupe_palette(tris, J, W, vers_sm3, maxos):
    """Group the triangles into batches whose union of bones fits in one palette (48 at most).

    Returns [(triangles of the batch, sorted unique vertex indices)]."""
    os_tri = []
    for t in tris:
        s = set()
        for iv in t:
            for c in range(J.shape[1]):
                if W[iv, c] > 1e-8:
                    s.add(int(vers_sm3[int(J[iv, c])]))
            s.add(int(vers_sm3[int(J[iv, 0])]))
        os_tri.append(s)
    paquets = []
    cour, courset = [], set()
    for i, s in enumerate(os_tri):
        if len(courset | s) > maxos and cour:
            paquets.append(cour)
            cour, courset = [], set()
        cour.append(i)
        courset |= s
    if cour:
        paquets.append(cour)
    out = []
    for p in paquets:
        st = tris[p]
        out.append((st, np.unique(st)))
    return out


# ---------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--glb', required=True)
    ap.add_argument('--template', required=True, help='vanilla .mesh used as the template')
    ap.add_argument('--skel', required=True, help='vanilla .skel, for the bone table')
    ap.add_argument('--out', required=True)
    ap.add_argument('--material-ref', default='0x614',
                    help='0x614 spider, 0x37C sideweb, 0x640 topweb, 0xA0 white (the 4 NON-tiled materials)')
    ap.add_argument('--cible', default='000', choices=['000', '001'])
    ap.add_argument('--uv-divisor', type=float, default=1000.0)
    ap.add_argument('--pos-divisor', type=float, default=512.0)
    ap.add_argument('--max-os', type=int, default=48)
    ap.add_argument('--atlas', default='', help='assemble an atlas and rewrite the UVs into it')
    ap.add_argument('--taille', type=int, default=2048)
    ap.add_argument('--marge', type=int, default=8, help='gutter in pixels around each cell')
    ap.add_argument('--zones', default='',
                    help="split the model into horizontal bands, one material ref per band, "
                         "from TOP to BOTTOM. E.g.: 0xA0,0x614,0x37C,0x640")
    ap.add_argument('--schema', type=int, default=-1,
                    help="force the vertex declaration of one template section. Without it, "
                         "section i takes the layout of template section i: on the 001 that "
                         "gives mixed strides 48/56/56. The toolkit's exporter uses "
                         "section 3 (stride 52, material 0x560).")
    ap.add_argument('--axe-hauteur', type=int, default=1,
                    help='vertical axis in the SM3 frame (1 by default; 0=X, 2=depth)')
    ap.add_argument('--canvas', default='',
                    help="one CANVAS PER GROUP (material x UDIM tile) instead of a single atlas. "
                         "Give the refs in order, e.g.: 0x614,0x37C,0xA0. Each group keeps "
                         "its page at its NATIVE resolution (no resizing) and gets its "
                         "own texture. Writes <prefix>_<n>.png next to --atlas.")
    ap.add_argument('--uv-wrap', action='store_true',
                    help='bring the UVs back into [0,1] by modulo (useful for a flat test)')
    A = ap.parse_args()

    modele = fmt.parse_mesh(A.template)
    skel = fmt.parse_skeleton(A.skel)
    par_hash = {b.name_hash: b.index for b in skel.bones}
    log('template %s: %d sections | skeleton %d bones'
        % (os.path.basename(A.template), modele.section_count, skel.bone_count))

    g = glbmod.GLB(A.glb)
    mondes = g.matrices_monde()
    prims = []
    for im, m in enumerate(g.g['meshes']):
        nd = g.noeud_du_mesh(im)
        iskin = g.g['nodes'][nd].get('skin') if nd is not None else None
        # glTF: a skinned mesh is NOT transformed by its node; its frame comes from the skin.
        M = np.eye(4) if (iskin is not None or nd is None) else mondes[nd]
        for pr in m['primitives']:
            if pr.get('mode', 4) != 4:
                log('!! primitive in mode %d skipped (triangles only)' % pr.get('mode'))
                continue
            prims.append((pr, M, iskin))
    if not prims:
        raise SystemExit('no triangle primitive in the glTF')

    ref = int(str(A.material_ref), 16) if str(A.material_ref).lower().startswith('0x') \
        else int(A.material_ref)
    lots = []
    for pr, M, iskin in prims:
        at = pr['attributes']
        P = g.acces(at['POSITION'])
        P = (M @ np.c_[P, np.ones(len(P))].T).T[:, :3]
        P = glbmod.en_repere_sm3(P)
        N = glbmod.en_repere_sm3(g.acces(at['NORMAL'])) if 'NORMAL' in at else np.zeros_like(P)
        UV = g.acces(at['TEXCOORD_0'])[:, :2] if 'TEXCOORD_0' in at else np.zeros((len(P), 2))
        CO = g.acces(at['COLOR_0']) if 'COLOR_0' in at else np.ones((len(P), 4))
        if CO.shape[1] == 3:
            CO = np.c_[CO, np.ones(len(CO))]
        tris = g.acces(pr['indices'])[:, 0].astype(np.int64).reshape(-1, 3)
        tris = tris[:, [0, 2, 1]]          # `reverse_winding=True` of the Blender path

        if iskin is not None and 'JOINTS_0' in at:
            # glTF joints -> SM3 bone indices, by the hash of the lower-case bone name
            joints = g.g['skins'][iskin]['joints']
            noms = [g.g['nodes'][j].get('name', '') for j in joints]
            vers_sm3, manquants = [], []
            for n in noms:
                h = fmt.sm3_hash(n.lower())
                if h in par_hash:
                    vers_sm3.append(par_hash[h])
                else:
                    vers_sm3.append(0)
                    manquants.append(n)
            if manquants:
                log('!! %d joint(s) not in the SM3 skeleton: %s'
                    % (len(manquants), ', '.join(manquants[:6])))
            J = g.acces(at['JOINTS_0']).astype(np.int64)
            W = g.acces(at['WEIGHTS_0']).astype(np.float64)
        else:
            vers_sm3 = [0]
            J = np.zeros((len(P), 4), np.int64)
            W = np.c_[np.ones(len(P)), np.zeros((len(P), 3))]
        s = W.sum(1, keepdims=True)
        W = W / np.where(s > 1e-9, s, 1.0)

        T, Bn = tbn(P, UV, tris)
        N = norme(N)
        T = norme(T - N * np.einsum('ij,ij->i', N, T)[:, None], (1.0, 0.0, 0.0))
        signe = np.sign(np.einsum('ij,ij->i', np.cross(N, T), Bn))
        signe[signe == 0] = 1.0
        BI = norme(np.cross(N, T) * signe[:, None], (0.0, 1.0, 0.0))

        v, o = volume_signe(P, tris), normales_sortantes(P, N)
        log('primitive: %d vertices, %d triangles | signed volume %+.4f | normals %+.4f'
            % (len(P), len(tris), v, o))
        # The two absolute tests of tools/winding_fix.py: vanilla = volume -0.116, normals +0.229.
        if v > 0 or o < 0:
            log('!! orientation inverted -> fixed (indices 1/2 swapped, normals negated)')
            tris = tris[:, [0, 2, 1]]
            N, BI = -N, -BI
            log('   after the fix: volume %+.4f | normals %+.4f'
                % (volume_signe(P, tris), normales_sortantes(P, N)))

        if A.uv_wrap:
            UV = UV - np.floor(UV)
        lots.append(dict(P=P, N=N, UV=UV, CO=CO, tris=tris, J=J, W=W, vers_sm3=vers_sm3,
                         T=T, BI=BI, mat=pr.get('material', 0)))

    # ---------------------------------------------------------------- atlas / canvas
    refs_canvas = [int(x, 16) if x.lower().startswith('0x') else int(x)
                   for x in A.canvas.split(',') if x.strip()]
    ref_par_face = None
    if refs_canvas:
        ref_par_face, bases_c, _ = canvas_par_groupe(g, lots, A, refs_canvas)
    elif A.atlas:
        atlas_global(g, lots, A)

    zones = [int(z, 16) if z.lower().startswith('0x') else int(z)
             for z in A.zones.split(',') if z.strip()] or None

    sections = []
    for L in lots:
        P, N, UV, CO, tris = L['P'], L['N'], L['UV'], L['CO'], L['tris']
        J, W, vers_sm3, T, BI = L['J'], L['W'], L['vers_sm3'], L['T'], L['BI']
        # One band = one batch of triangles, cut along the HEIGHT, with equal triangle counts:
        # quantiles, not regular slices, otherwise the top band holds three triangles and the
        # middle one everything else.
        if ref_par_face is not None:
            b0, n0 = bases_c[lots.index(L)]
            deb = sum(len(x['tris']) for x in lots[:lots.index(L)])
            rf = ref_par_face[deb:deb + len(tris)]
            paquets = [(int(r), tris[rf == r]) for r in np.unique(rf)]
        elif zones:
            # In the SM3 frame (Blender's) the HEIGHT is axis 1, not axis 2: the model's bounds
            # are X[-0.87..0.87] Y[-1.20..0.95] Z[-0.15..0.30]. Slicing along axis 2 gives
            # front/back slices, not head-to-feet bands.
            zc = P[tris].mean(1)[:, A.axe_hauteur]
            bornes = np.quantile(zc, np.linspace(0, 1, len(zones) + 1)[1:-1])
            bande = len(zones) - 1 - np.searchsorted(bornes, zc)
            paquets = [(zones[b], tris[bande == b]) for b in range(len(zones))]
        else:
            paquets = [(ref, tris)]
        for refz, trisz in paquets:
            if not len(trisz):
                log('!! band for 0x%X is empty, skipped' % refz)
                continue
            log('material band 0x%-4X: %5d triangles, height %.3f..%.3f'
                % (refz, len(trisz), P[trisz].mean(1)[:, A.axe_hauteur].min(),
                   P[trisz].mean(1)[:, A.axe_hauteur].max()))
            construit(sections, A, refz, P, N, UV, CO, trisz, J, W, vers_sm3, T, BI)

    ecrit(A, modele, sections)


def construit(sections, A, ref, P, N, UV, CO, tris, J, W, vers_sm3, T, BI):
        """Append one toolkit ExportSection per palette batch of `tris` (French: "builds")."""
        for st, sv in decoupe_palette(tris, J, W, vers_sm3, A.max_os):
            remap = -np.ones(len(P), np.int64)
            remap[sv] = np.arange(len(sv))
            utiles = set()
            for iv in sv.tolist():
                for c in range(J.shape[1]):
                    if W[iv, c] > 1e-8:
                        utiles.add(int(vers_sm3[int(J[iv, c])]))
                utiles.add(int(vers_sm3[int(J[iv, 0])]))
            pal = sorted(utiles)
            # RESERVE the whole palette. It is fixed when the .mesh is written, and the skinning
            # stage that follows can only fill it. With only the bones used here (often 30) it
            # overflowed: a whole body needs ~52 bones, and the losers were the lightest ones -
            # `upperarm`, its three `split` bones, half of the fingers. Arms and hands were left
            # with no bone to follow. The extra slots repeat the last bone: nothing points to
            # them until they are filled.
            if len(pal) < A.max_os:
                pal = pal + [pal[-1]] * (A.max_os - len(pal))
            # ExportVertex.influences wants the GLOBAL index in the SM3 skeleton, not the local
            # index in the palette: the writer converts it through `bone_palette`.
            sommets = []
            for iv in sv.tolist():
                inf = [(int(vers_sm3[int(J[iv, c])]), float(W[iv, c]))
                       for c in range(J.shape[1]) if W[iv, c] > 1e-8]
                if not inf:
                    inf = [(int(vers_sm3[int(J[iv, 0])]), 1.0)]
                sommets.append(mw.ExportVertex(
                    position=tuple(P[iv]), uv=(float(UV[iv, 0]), float(UV[iv, 1])),
                    color=tuple(float(x) for x in CO[iv]),
                    normal=tuple(N[iv]), tangent=tuple(T[iv]), binormal=tuple(BI[iv]),
                    influences=tuple(inf)))
            sections.append(mw.ExportSection(
                source_object=os.path.basename(A.glb), source_material_index=0,
                material_ref_serialized=ref, vertices=sommets,
                triangles=[tuple(int(remap[i]) for i in t) for t in st.tolist()],
                bone_palette=pal, position_divisor=A.pos_divisor,
                schema_template_section=(A.schema if A.schema >= 0 else None)))

def ecrit(A, modele, sections):
    """Write the .mesh with the toolkit's writer, then print the check (French: "writes")."""
    # The toolkit writes uv*1024; the suit's vertex shader divides by 1000. The writer's default
    # argument is patched in place (only if it still holds 1024).
    f = mw.encode_player_vertex
    if f.__defaults__ and abs(f.__defaults__[0] - 1024.0) < 1e-6:
        f.__defaults__ = (A.uv_divisor,) + f.__defaults__[1:]
        log('UV divisor forced to %g (the toolkit wrote 1024)' % A.uv_divisor)

    r = mw.write_raw_mesh(A.out, modele, sections,
                          filename_hash=modele.filename_hash, player_target=A.cible)
    log('WROTE %s' % r.output_path)
    log('  %d section(s), %d vertices, %d triangles, %d bytes, hash 0x%08X, read back %s'
        % (r.section_count, r.vertex_count, r.triangle_count, r.file_size,
           r.filename_hash, r.report.get('roundtrip_parse')))
    verifie(A.out)


def atlas_global(g, lots, A):
    """Assemble one atlas from the glTF's images (atlas.py) and rewrite the UVs of every batch.

    It is the direct replacement of the combiner's baking: no rendering, no colour space
    conversion, hence neither of the two sRGB encodings that doubled the brightness."""
    from PIL import Image
    import io as _io

    images = []
    for imat in range(max(1, len(g.g.get('materials', [])))):
        ii = g.image_de_materiau(imat)
        if ii is None:
            images.append(None)
            continue
        im = Image.open(_io.BytesIO(g.image_png(ii))).convert('RGBA')
        images.append(np.asarray(im))
        log('material %d: image %dx%d' % (imat, im.size[0], im.size[1]))

    # All batches are concatenated into a common index space while the atlas is assembled.
    UVs, tris, mats, bases = [], [], [], []
    base = 0
    for L in lots:
        UVs.append(L['UV'])
        tris.append(L['tris'] + base)
        mats.append(np.full(len(L['tris']), L['mat'], np.int64))
        bases.append((base, len(L['UV'])))
        base += len(L['UV'])
    UV = np.concatenate(UVs)
    TR = np.concatenate(tris)
    MA = np.concatenate(mats)

    img, UV2, grille, rapport = atlasmod.compose(UV, TR, MA, images,
                                                 taille=A.taille, marge_px=A.marge)
    log('atlas %dx%d, grid of %d columns x %d rows, %d group(s) (material x UDIM tile):'
        % (A.taille, A.taille, grille[0], grille[1], len(rapport)))
    for (imat, tu, tv), nf, nv, w, h in rapport:
        log('   material %d tile (%d,%d): %5d faces, %5d vertices, source %dx%d'
            % (imat, tu, tv, nf, nv, w, h))
    for L, (b, n) in zip(lots, bases):
        L['UV'] = UV2[b:b + n]

    Image.fromarray(img).save(A.atlas)
    lum = float((img[:, :, :3].astype(np.float64) @ [0.2126, 0.7152, 0.0722]).mean())
    couvert = float((img[:, :, :3].sum(2) > 0).mean())
    log('WROTE %s | luminance %.1f | coverage %.1f %%' % (A.atlas, lum, 100 * couvert))


def canvas_par_groupe(g, lots, A, refs):
    """One full canvas per group, at the NATIVE resolution of its source image.

    This is what splitting the body over the four non-tiled materials makes possible: instead of
    packing every group into one page (and resizing them), each group keeps its whole page and
    its own material. The UVs only move back into [0,1] by `v -= tile`, so no texel is
    resampled. Returns (material ref per face, batch bases, written PNG paths)."""
    from PIL import Image
    import io as _io

    images = []
    for imat in range(max(1, len(g.g.get('materials', [])))):
        ii = g.image_de_materiau(imat)
        images.append(None if ii is None
                      else np.asarray(Image.open(_io.BytesIO(g.image_png(ii))).convert('RGBA')))

    # common index space, as for the atlas
    UVs, tris, mats, bases, base = [], [], [], [], 0
    for L in lots:
        UVs.append(L['UV'])
        tris.append(L['tris'] + base)
        mats.append(np.full(len(L['tris']), L['mat'], np.int64))
        bases.append((base, len(L['UV'])))
        base += len(L['UV'])
    UV = np.concatenate(UVs)
    TR = np.concatenate(tris)
    MA = np.concatenate(mats)

    cles = sorted(atlasmod.groupes_uv(UV, TR, MA).items())
    if len(refs) < len(cles):
        raise SystemExit('%d group(s) but only %d material ref(s) given to --canvas'
                         % (len(cles), len(refs)))
    UV2 = UV.copy()
    ref_par_face = np.zeros(len(TR), np.int64)
    prefixe = os.path.splitext(A.atlas)[0] if A.atlas else 'canvas'
    sorties = []
    for k, ((imat, tu, tv), faces) in enumerate(cles):
        sommets = np.unique(TR[faces])
        UV2[sommets, 0] -= tu
        UV2[sommets, 1] -= tv
        ref_par_face[faces] = refs[k]
        src = images[imat] if imat < len(images) and images[imat] is not None else None
        if src is None:
            src = np.full((4, 4, 4), 200, np.uint8)
            src[:, :, 3] = 255
        chemin = '%s_%d.png' % (prefixe, k)
        Image.fromarray(src).save(chemin)
        sorties.append(chemin)
        log('canvas %d: material 0x%-4X <- group (mat %d, tile %d,%d), %5d faces, '
            'page %dx%d NATIVE -> %s'
            % (k, refs[k], imat, tu, tv, len(faces), src.shape[1], src.shape[0],
               os.path.basename(chemin)))
        log('          UV after re-centring: u %.3f..%.3f  v %.3f..%.3f'
            % (UV2[sommets, 0].min(), UV2[sommets, 0].max(),
               UV2[sommets, 1].min(), UV2[sommets, 1].max()))
    for L, (b, n) in zip(lots, bases):
        L['UV'] = UV2[b:b + n]
    return ref_par_face, bases, sorties


def verifie(chemin):
    """Print, per section of the written file, its counts, material and raw UV range."""
    m = fmt.parse_mesh(chemin)
    log('CHECK on the delivered bytes:')
    for s in m.sections:
        # D3DDECLUSAGE 5 = TEXCOORD, stored as 2 int16 (raw UV x divisor)
        offs = [d.offset for d in s.decl if d.usage == 5]
        u = []
        if offs and s.vertex_count:
            d = np.frombuffer(m.raw[s.vertex_buffer_offset:
                                    s.vertex_buffer_offset + s.vertex_count * s.vertex_stride],
                              np.uint8).reshape(s.vertex_count, s.vertex_stride)
            q = d[:, offs[0]:offs[0] + 4].copy().view(np.int16)
            u = [int(q.min()), int(q.max())]
        log('   sec %d: %5d vertices, %5d indices, stride %d, mat 0x%X, UV %s'
            % (s.index, s.vertex_count, s.index_count, s.vertex_stride,
               s.material_ref_serialized, u))


if __name__ == '__main__':
    main()
