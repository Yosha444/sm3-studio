# SPDX-License-Identifier: GPL-3.0-or-later
"""qualite_hq.py - the "HQ" quality options, applied locally, without modifying the installed toolkit.

("qualité HQ" = "HQ quality".) Imported inside Blender by chaine_officielle.py (red suit, black
suit) and by venom_atlas.py / venom_custom.py (Venom). It reads <SM3 Studio>/qualite.json, the
file the window's "General / Quality" panel writes; its keys are French and kept:
    resolution                atlas size: 2048, 4096 or 8192
    geometrie                 geometry mode: conserver (keep), retrianguler (retriangulate
                              quads and n-gons), subdiviser (subdivide x4 without smoothing)
    marge_pixels              bake margin, 2 to 32 pixels
    limite_triangles          working limit: above it no geometry is added, and a source model
                              already above it is refused (nothing is decimated automatically)
    autoriser_couleurs_unies  "allow flat colours": bake image-less materials as flat colours
                              even when no material of the model has an image
Functions, in the order the chain calls them: settings(), geometry(), jeter_decalques(),
validate_materials(), peindre_couleurs_unies(), then validate_atlas() after the bake (writes
qualite_hq_rapport.json next to the build).

WARNING: this file only holds INPUT safeguards. They must ADAPT to the model they are given: a
refusal is only justified if CONTINUING would produce a broken mod. The check of what we DELIVER
is elsewhere (the checks on the delivered bytes in `sm3_convertir.py`) and stays strict: we relax
the input, not the quality of the output.

In the red-suit chain only lines starting with '[chaine]' reach the window's log
(sm3_convertir.lance() relays only those prefixes from Blender's output; the log() passed in by
chaine_officielle.py adds it). '!!' marks a warning.
"""
import json
from pathlib import Path
import bpy
import bmesh


# ---------------------------------------------------------------------------- thresholds, measurements
# A material WITHOUT AN IMAGE is not necessarily a mistake: rips drag along decal, VFX or marker
# layers that represent nothing visible. The question is "what share of the SURFACE does it
# cover?" -- not "how many triangles?": on the MCU Spider-Man, `MI_Punches_2_005` weighed 6032
# triangles (9.5 % of the model) for 0.00 % of the surface.
#
# Both thresholds come from measurements, not from intuition:
#
#   THE REFEREE, the game itself. The 10 sections of the vanilla CH_SPIDERMAN, as shares of the
#   surface:
#       44.572 / 26.558 / 7.461 / 6.918 / 6.175 / 3.340 / 2.575 / 1.331 / 0.873 / 0.197 %
#   The smallest piece the game really ships is therefore 0.197 % of the surface. Below that,
#   nothing SM3 considers a character piece remains: this is the CERTAIN zone.
#
#   THE DECALS MET SO FAR:
#       MI_Punches_2_005 (MCU Spider-Man)  0.00 % of the surface
#       Mesh_0009.rip_2  (black suit)      0.07 %
#       VFX_Toile_Decalque (test case)     0.28 %
#
#   Between 0.197 % and 1 % we can no longer be CERTAIN: it could be a small ornament whose
#   author forgot the texture. We drop it anyway -- keeping it would only bake a flat untextured
#   patch into the atlas -- but we say so loudly, with the way to get it back.
#   Above 1 % we are no longer looking at a decal: there, we stop and say what to do.
SEUIL_CERTAIN = 0.002      # 0.2 %: below the game's smallest textured section (0.197 %)
SEUIL_DECALQUE = 0.01      # 1 %: above it nothing is dropped, the model is refused
# If the SUM of what we would drop exceeds this share, the model is not a model with decals: it
# is a model made of small untextured pieces. Emptying it would be worse than refusing, so we
# then limit ourselves to the certain zone.
PART_MAXI_JETABLE = 0.10


def settings():
    """qualite.json (project root), validated."""
    path = Path(__file__).resolve().parent.parent / 'qualite.json'
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    if config['resolution'] not in (2048, 4096, 8192):
        raise ValueError('HQ resolution: 2048, 4096 or 8192.')
    if config['geometrie'] not in ('conserver', 'retrianguler', 'subdiviser'):
        raise ValueError('Unknown HQ geometry mode.')
    if not 2 <= config['marge_pixels'] <= 32:
        raise ValueError('HQ margin: between 2 and 32 pixels.')
    if not 1 <= config['limite_triangles'] <= 10000000:
        raise ValueError('Invalid working limit.')
    return config


def geometry(obj, config):
    """Apply the geometry mode to obj's mesh, keeping UVs, weights and authored normals."""
    mesh = obj.data
    mesh.calc_loop_triangles()
    before = len(mesh.loop_triangles)
    mode = config['geometrie']
    limite = config['limite_triangles']
    # WARNING: FALL BACK rather than refuse: if `subdiviser` would overflow, `retrianguler` fits
    # in the same budget as the input and gives a correct model. We degrade and say so; we only
    # send the user back to the settings if even `conserver` does not fit -- then there is no
    # fallback left: the model is too heavy for the machine, not for a setting.
    if before * 4 > limite and mode == 'subdiviser':
        mode = 'retrianguler'
        print(f'[chaine] !! HQ: subdividing would give {before * 4:,} triangles, above the '
              f'working limit of {limite:,}. Falling back to "retrianguler" ({before:,} '
              'triangles). Raise "limite_triangles" in qualite.json to subdivide anyway.',
              flush=True)
    if before > limite:
        raise RuntimeError(f'HQ: the source model already has {before:,} triangles, above the '
                           f'working limit of {limite:,}. No automatic decimation will be '
                           'applied: raise "limite_triangles" in qualite.json, or lighten the '
                           'model before importing it.')
    if mode != 'conserver':
        # Triangulate first: subdividing planar triangles preserves the surface.
        # BMesh interpolates corner UVs and vertex weights, including UV seams.
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            # Interpolate authored corner normals alongside UVs, rather than
            # dropping the imported split normals during the BMesh round trip.
            bm.faces.ensure_lookup_table()
            normals = bm.loops.layers.float_vector.new('_sm3_hq_normal')
            for face, polygon in zip(bm.faces, mesh.polygons):
                for loop, index in zip(face.loops, polygon.loop_indices):
                    loop[normals] = mesh.corner_normals[index].vector
            bmesh.ops.triangulate(bm, faces=list(bm.faces),
                                  quad_method='BEAUTY', ngon_method='BEAUTY')
            if mode == 'subdiviser':
                bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=1,
                                         use_grid_fill=True, smooth=0.0)
                bmesh.ops.triangulate(bm, faces=list(bm.faces),
                                      quad_method='BEAUTY', ngon_method='BEAUTY')
            bm.to_mesh(mesh)
        finally:
            bm.free()
        mesh.update()
        saved = mesh.attributes.get('_sm3_hq_normal')
        if saved is not None:
            vectors = [tuple(item.vector.normalized()) for item in saved.data]
            mesh.normals_split_custom_set(vectors)
            mesh.attributes.remove(saved)
    mesh.calc_loop_triangles()
    after = len(mesh.loop_triangles)
    obj['sm3_hq_triangles_before'] = before
    obj['sm3_hq_triangles_after'] = after
    print(f'[chaine] HQ geometry {mode}: {before} -> {after} triangles', flush=True)


def _part_de_surface(obj):
    """Share of the total AREA carried by each material slot. The area, not the triangles.

    A VFX layer can weigh 10 % of the triangles and 0.00 % of the surface: on the MCU
    Spider-Man, `MI_Punches_2_005` had 6032 triangles for an area of 0.18 against 4013 for the
    body. Counting triangles would have made it look like an important piece.
    """
    obj.data.calc_loop_triangles()
    aires = {}
    for t in obj.data.loop_triangles:
        aires[t.material_index] = aires.get(t.material_index, 0.0) + t.area
    total = sum(aires.values()) or 1.0
    return {k: v / total for k, v in aires.items()}


def _sans_image(mat):
    """True if this slot cannot give any colour: no material, or no loaded image."""
    if mat is None or not mat.use_nodes or not mat.node_tree:
        return True
    return not any(n.type == 'TEX_IMAGE' and n.image is not None and min(n.image.size) > 0
                   for n in mat.node_tree.nodes)


def jeter_decalques(obj, config, log=print):
    """("drop the decals") Delete the materials WITHOUT AN IMAGE that cover almost no SURFACE.

    Before, the bake stopped on "no image" and the user had to rerun by hand with
    `--drop <name>`: we were asking for a choice that is not one. We drop them, log each one
    with its percentage, and the bake goes on.

    The thresholds and their measured justification are at the top of the file.
    Returns the list of dropped names.
    """
    # WARNING: do NOT short-circuit on `autoriser_couleurs_unies`: that flag says how to treat
    # a LARGE piece without an image, not whether to keep decals. Tying them meant that allowing
    # flat colours brought back the baking of two-triangle decals as flat patches, which is
    # exactly what this function exists to prevent.
    parts = _part_de_surface(obj)
    candidats = {}
    for slot in sorted({p.material_index for p in obj.data.polygons}):
        mat = obj.data.materials[slot] if slot < len(obj.data.materials) else None
        if not _sans_image(mat):
            continue
        part = parts.get(slot, 0.0)
        if part < SEUIL_DECALQUE:
            candidats[slot] = (mat.name if mat else '(slot %d, no material)' % slot, part,
                               getattr(mat, 'blend_method', 'OPAQUE') != 'OPAQUE' if mat else False)
    if not candidats:
        return []

    # WARNING: safeguard of the safeguard: if all of them together weigh too much, they are no
    # longer decals.
    somme = sum(v[1] for v in candidats.values())
    if somme > PART_MAXI_JETABLE:
        certains = {k: v for k, v in candidats.items() if v[1] < SEUIL_CERTAIN}
        log('!! %d image-less material(s) together weigh %.2f %% of the surface: too much for '
            'decals. Only the %d smallest (below %.1f %%) are dropped, the others will be '
            'reported.'
            % (len(candidats), 100.0 * somme, len(certains), 100.0 * SEUIL_CERTAIN))
        candidats = certains
        if not candidats:
            return []

    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    faces = [f for f in bm.faces if f.material_index in candidats]
    avant = len(bm.faces)
    bmesh.ops.delete(bm, geom=faces, context='FACES')
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context='VERTS')
    apres = len(bm.faces)
    bm.to_mesh(me)
    bm.free()
    me.update()
    for nom, part, transparent in sorted(candidats.values(), key=lambda v: -v[1]):
        sur = ', transparent' if transparent else ''
        if part < SEUIL_CERTAIN:
            log('decal dropped: %s -- %.3f %% of the surface%s, no image. Below the %.3f %% of '
                'the game\'s smallest piece: this is not a piece of the character.'
                % (nom, 100.0 * part, sur, 100.0 * SEUIL_CERTAIN))
        else:
            log('!! material dropped: %s -- %.3f %% of the surface%s, no image. Too small to be '
                'a piece of the character, but not negligible: to keep it, give it a texture '
                'with --materiaux "%s=file.png" and run again.' % (nom, 100.0 * part, sur, nom))
    log('%d face(s) deleted out of %d; %d left' % (avant - apres, avant, apres))
    return [v[0] for v in candidats.values()]


def _couleur_unie(mat):
    """The Base Color of an image-less material, in 0..255, or None."""
    if not (mat and mat.use_nodes and mat.node_tree):
        return None
    for n in mat.node_tree.nodes:
        e = n.inputs.get('Base Color') if hasattr(n, 'inputs') else None
        if e is not None and not e.links:
            try:
                c = tuple(e.default_value)[:3]
            except Exception:
                continue
            return tuple(int(round(255.0 * max(0.0, min(1.0, x)))) for x in c)
    return None


def peindre_couleurs_unies(obj, log=print):
    """("paint the flat colours") Give a real IMAGE to the materials that only have a flat colour.

    WARNING: letting an image-less piece through our validator is not enough: the toolkit's
    add-on then refuses to bake, with "Source texture setup is incomplete: N used material
    slot(s) have no diffuse image". Rather than patch its extension, we give it what it asks
    for -- an image -- filled with the material's Base Color. The baked result is exactly the
    same flat colour, and the chain goes on.

    `image.pixels` is ALWAYS linear, like the Base Color's `default_value`: the value is copied
    as it is, with no sRGB conversion.
    """
    import bpy

    peints = []
    for mat in {obj.data.materials[p.material_index]
                for p in obj.data.polygons
                if p.material_index < len(obj.data.materials)}:
        if mat is None or not mat.use_nodes or not mat.node_tree:
            continue
        nt = mat.node_tree
        if any(n.type == 'TEX_IMAGE' and n.image is not None for n in nt.nodes):
            continue
        cible = next((n for n in nt.nodes
                      if hasattr(n, 'inputs') and n.inputs.get('Base Color') is not None), None)
        if cible is None:
            continue
        # WARNING: keep the NAME, not the node: `nodes.new()` below may reallocate the
        # collection and invalidate any node or socket reference held before. Measured symptom:
        # the image was created, but `links.new()` connected nothing, silently.
        nom_cible = cible.name
        prise = cible.inputs['Base Color']
        couleur = tuple(prise.default_value)[:3] if not prise.links else (0.8, 0.8, 0.8)
        nom = 'SM3_UNI_%s' % mat.name
        img = bpy.data.images.get(nom)
        if img is not None:
            bpy.data.images.remove(img)
        img = bpy.data.images.new(nom, width=32, height=32, alpha=False)
        img.generated_color = (couleur[0], couleur[1], couleur[2], 1.0)
        img.pixels.foreach_set([couleur[0], couleur[1], couleur[2], 1.0] * (32 * 32))
        img.update()
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = img
        cible = nt.nodes[nom_cible]                 # resolved again AFTER creating the node
        prise = cible.inputs['Base Color']
        tex.location = (cible.location[0] - 320, cible.location[1])
        for lien in list(prise.links):
            nt.links.remove(lien)
        nt.links.new(tex.outputs['Color'], prise)
        # WARNING: compare by NAME, never with `is`: Blender creates a new Python wrapper on
        # every access to `l.from_node`, so `is` is always false, even for the same node. This
        # trap first made it look as if `links.new()` connected nothing.
        if not any(l.from_node.name == tex.name
                   for l in nt.nodes[nom_cible].inputs['Base Color'].links):
            raise RuntimeError('flat colour image not connected to the Base Color of "%s"' % mat.name)
        peints.append((mat.name, couleur))
        log('   %dx%d flat colour image made for "%s": RGB %d,%d,%d'
            % (32, 32, mat.name,
               round(255 * couleur[0]), round(255 * couleur[1]), round(255 * couleur[2])))
    return peints


def validate_materials(obj, config, log=print):
    """Refuse only what would give a broken mod: a LARGE material without a texture.

    The small ones are already gone through `jeter_decalques`. What arrives here covers more
    than SEUIL_DECALQUE of the surface: baking it would give a flat grey patch on a visible piece
    of the character. We refuse, but say what to do, with the figure.
    """
    problems = []
    conseils = []           # advice lines added to the error
    parts = _part_de_surface(obj)
    textures_presentes = any(
        m and m.use_nodes and m.node_tree
        and any(n.type == 'TEX_IMAGE' and n.image is not None for n in m.node_tree.nodes)
        for m in obj.data.materials)
    for slot in sorted({p.material_index for p in obj.data.polygons}):
        mat = obj.data.materials[slot] if slot < len(obj.data.materials) else None
        part = parts.get(slot, 0.0)
        if mat is None or not mat.use_nodes:
            if not (textures_presentes or config.get('autoriser_couleurs_unies')):
                problems.append(f'slot {slot} has no textured material ({100.0 * part:.2f} % '
                                'of the surface)')
            continue
        images = [n.image for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE']
        if not images:
            # WARNING: FALL BACK rather than refuse. A piece in a FLAT COLOUR -- belt, sole,
            # metal part -- bakes perfectly well: the atlas takes its flat colour. Refusing the
            # whole conversion for that makes the tool useless on half of the ripped models.
            # We only refuse if NO material of the object carries an image: then it is not an
            # artistic choice, it is a texture matching that failed, and going on would give a
            # uniformly grey character.
            if textures_presentes or config.get('autoriser_couleurs_unies'):
                couleur = _couleur_unie(mat)
                log('!! %s: %.2f %% of the surface, no image -> baked as a FLAT COLOUR %s. '
                    'For a texture: --materiaux "%s=file.png".'
                    % (mat.name, 100.0 * part,
                       ('RGB %d,%d,%d' % couleur) if couleur else '(material default)',
                       mat.name))
                continue
            problems.append(f'{mat.name}: no image ({100.0 * part:.2f} % of the surface)')
            conseils.append(
                '  %s: %.2f %% of the surface, and NO material of this model carries an image. '
                'Texture matching failed: check --textures and --materiaux '
                '"%s=file.png".'
                % (mat.name, 100.0 * part, mat.name))
        for image in images:
            if image is None or min(image.size) == 0:
                problems.append(f'{mat.name}: image missing or unreadable')
    uv = obj.data.uv_layers.active
    if uv is None:
        problems.append('no UV layer')
    if problems:
        message = 'HQ: fix the textures before baking: ' + '; '.join(problems)
        if conseils:
            message += '\n' + '\n'.join(conseils)
        raise RuntimeError(message)


def validate_atlas(obj, out_dir, config):
    """After the bake: read the add-on's bake report, write qualite_hq_rapport.json, refuse an
    atlas baked from no image at all, warn about a poorly filled one."""
    report_path = Path(out_dir) / 'SM3_Spider_Baked_Atlas.friend_bake.json'
    if not report_path.is_file():
        raise RuntimeError('HQ: bake report missing.')
    report = json.loads(report_path.read_text(encoding='utf8'))
    coverage = float(report.get('packed_uv_coverage_percent', 0))
    images = int(report.get('source_image_count', 0))
    diagnostics = dict(resolution=config['resolution'], geometrie=config['geometrie'],
                       triangles_avant=obj.get('sm3_hq_triangles_before'),
                       triangles_apres=obj.get('sm3_hq_triangles_after'),
                       couverture_uv_pourcent=coverage, images_source=images)
    (Path(out_dir) / 'qualite_hq_rapport.json').write_text(
        json.dumps(diagnostics, indent=2), encoding='utf8')
    if images == 0 and not config['autoriser_couleurs_unies']:
        # The only case where going on surely produces a broken mod: without ANY source image,
        # the atlas comes out uniform and the character is all white in game. Measured at the
        # time on a Free Fire FBX whose images sat next to it, named unrelated to the materials.
        raise RuntimeError(
            'HQ: no source image was baked, the atlas would be uniform and the character would '
            'come out all white in game. Check the texture folder, or wire the images by hand '
            'with --materiaux "material_name=file.png".')
    # WARNING: WARN, do not refuse: a poorly filled atlas gives a blurry texture, not a broken
    # mod. The model's UVs fit in a corner of the atlas; the mod loads, displays and works.
    # Refusing here blocked a conversion that would have worked.
    if coverage < 5:
        print('[chaine] !! HQ: atlas only %.4f %% filled (more than 5 %% expected). '
              'The texture will be blurry: the source UVs occupy a corner of the atlas instead of '
              'filling it. The mod will work anyway. To fix it: unwrap the source model\'s UVs '
              'again, or lower the bake resolution.' % coverage, flush=True)
    print(f'[chaine] HQ atlas: {coverage:.1f} % filled, {images} source images.', flush=True)
