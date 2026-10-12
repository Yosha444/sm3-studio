# SPDX-License-Identifier: GPL-3.0-or-later
"""extraire_donnees_jeu.py - rebuild SM3 Studio's game-data folders from the player's own game.

(The file name is French for "extract the game data"; it is kept because SM3 Studio calls it by
that name.)

Why this script exists
----------------------
SM3 Studio turns a 3D model into a Spider-Man 3 costume by measuring everything against the
game's own files: the red suit's meshes and skeletons give the bind pose, the skin weights and
the material slots; the black suit and Venom have their own templates. Those files belong to
Activision and Treyarch, so the repository does not contain them. This script reads them from
YOUR copy of Spider-Man 3 (PC, 2007) and writes them where the tool expects them:

    vanilla/CH_SPIDERMAN/_O0069.0xCFB154CD.T36.apkf/   red suit: 2 meshes + 2 skeletons
    vanilla/CH_BLACKSUIT/_O0108.0xF8ACB40C.T36.apkf/   black suit: its 186 art resources
    vanilla/CH_BLACKSUIT/resources.json                list + SHA-256 of those 186 files
    vanilla/tex_headers/                               68-byte headers of 12 red suit textures
    profiles/blacksuit/MESH/, SKEL/                    the black suit meshes and skeletons again
                                                       (the black suit tools read them there)
    profiles/venom/                                    Venom: mesh, skeleton, material, 4 textures,
                                                       venom_shader_patch.json,
                                                       venom_direct_material.bin, and
                                                       Venom_editable.blend (made by Blender)

It only READS the game folder, never writes into it. The folder names (`_O0069.0xCFB154CD...`)
are the ones xeSM3 and SM3 Studio use: "_O" + the archive's index in the pack directory, its
hash, and its resource type in hex (54 = 0x36 = an APKF archive).

Every file is checked against `game_data_fingerprints.json`, next to this script: the size and
SHA-256 of the file in the reference installation SM3 Studio was developed and tested with. A
fingerprint is not game data (you cannot get the bytes back from it), and it is the proof that
the tool reads exactly what it was calibrated on. A file that does not match is still written -
the tool will run - but it is reported, because your pack is then not the retail one (an old
mod written straight into the pack, another release...).

How each file is made (and why two of them are special)
-------------------------------------------------------
  * Most files are a resource of a pack's APKF archive "as a loose file": its IMG part (the
    serialized object) followed by its PHYS part (vertex buffers, pixels). See tools/pcpack.py.
  * ch_spiderman000.mesh, the red suit's main mesh: SM3 Studio was calibrated on the copy that
    ships as a sample with TSGAMING264's SM3 Blender Toolkit. That copy stops the IMG part right
    after the last vertex declaration and so drops its last 8 bytes, the mesh's "external mesh"
    table (header +0x18 = 1 entry, +0x1C = its position): one entry pointing at the
    ch_spiderman001 object (the lower-detail mesh) with the value 4.5 (most likely the switch
    distance). No tool of ours reads that table, so we reproduce the sample exactly: IMG part
    minus 8 bytes per external mesh, then PHYS part.
  * ch_spiderman001.mesh, the lower-detail red suit: here the toolkit sample does NOT come from
    the pack. Its header (the first 1,496 bytes) is the pack's, but its 328,422 bytes of buffers
    are another block of CH_SPIDERMAN.PCPACK (they lie inside a type-53 sound-bank resource), so
    its vertices are garbage. SM3 Studio only ever reads that file's HEADER (it is the template
    the LOD writer copies identity fields from), which is why nobody noticed. To stay identical
    to the reference we copy the toolkit's sample, which every SM3 Studio user has installed
    anyway (the toolkit is a required Blender add-on). Without it we fall back to the pack's real
    bytes: same size, same header, correct buffers, but a different file, and we say so.
  * venom_shader_patch.json and venom_direct_material.bin describe a Venom experiment of ours
    (render Venom with the Spider-Man shader by rewriting his material in the pack). Installing
    it is suspended - it crashed the game. The reference installation's Venom installer read
    this file to check that the Venom pack is the original one and to undo the change; today's
    tools/venom_install.py uses the fingerprints of tools/venom_shader_patch.json instead, and
    takes the original material from profiles/venom (extracted here). Both files are still
    rebuilt so that profiles/ stays identical to the reference installation. The "before" bytes
    come from your pack, the "after" bytes are built from two materials of the game (see
    build_venom_patch), so nothing of the game has to live in the repository. The result is
    checked against the fingerprints of the pack (original and patched).
  * Venom_editable.blend is the Venom mesh imported into Blender, ready to edit (the "Load the
    Venom project" button opens it). Blender files are not byte-reproducible (they store
    pointers and dates), so it has no fingerprint: it is regenerated by
    `tools/venom_blender.py --prepare`, the same code path SM3 Studio uses. Without Blender it is
    skipped; everything else, including converting a model for Venom, works without it.

Not rebuilt
-----------
  * profiles/rvb/: models from Spider-Man: Web of Shadows (another game, Xbox 360 files).
    SM3 Studio recognises two exports of those models (by SHA-256, profiles/rvb/sources.json) and
    then converts them with their original skin weights. Without these files that special mode
    is off: such a model is converted like any other model, with a message saying so. Players
    who have an older SM3 Studio installation can copy its profiles/rvb folder over.
  * the *.blend1 file next to Venom_editable.blend: Blender's automatic backup, never read.
  * profiles/*/comparison.json, frames.json, roundtrip_validation.json and rvb/sources.json are
    our own measurements (numbers, hashes) and are distributed with the tool, not extracted.

Usage
-----
    python tools/extraire_donnees_jeu.py                       game folder found automatically
    python tools/extraire_donnees_jeu.py --game "C:/Games/Spider-man 3"
    python tools/extraire_donnees_jeu.py --check               only compare what is there
    python tools/extraire_donnees_jeu.py --force               rewrite every file
    options: --root <SM3 Studio folder>  --blender <blender.exe>  --no-blender

The game folder is looked for in this order: --game, the "jeu" field of sm3_studio.json (the
"Game folder" of the Paths tab), the install path Windows keeps in the registry, then the usual
places. SM3 Studio also calls `ensure_game_data()` itself before a conversion, so most players
never have to run this by hand.

Exit code: 0 = every file present and identical, 2 = written but some files differ from the
reference, 1 = could not run (game not found...).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import pcpack  # noqa: E402  (tools/pcpack.py, next to this script)

FINGERPRINTS = HERE / 'game_data_fingerprints.json'
DEFAULT_BLENDER = r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
# Where Blender 5.2 installs TSGAMING264's toolkit for the current Windows user.
TOOLKIT_SAMPLES = ('Blender Foundation', 'Blender', '5.2', 'extensions', 'user_default',
                   'sm3_blender_toolkit', 'samples', 'CH_SPIDERMAN')

# ----------------------------------------------------------------------------- what we extract
# Packs we read, and the archive folder name SM3 Studio hard-codes for each one. The folder name
# is recomputed from the pack and compared, so a different game release is caught early.
RED_PACK, RED_FOLDER = 'CH_SPIDERMAN.PCPACK', '_O0069.0xCFB154CD.T36.apkf'
BLACK_PACK, BLACK_FOLDER = 'CH_BLACKSUIT.PCPACK', '_O0108.0xF8ACB40C.T36.apkf'
VENOM_PACK, VENOM_FOLDER = 'STORY_MOVIE_4_PHASE3.PCPACK', '_O0114.0x2AF92556.T36.apkf'

RED_DIR = 'vanilla/CH_SPIDERMAN/' + RED_FOLDER
BLACK_DIR = 'vanilla/CH_BLACKSUIT/' + BLACK_FOLDER
HEADERS_DIR = 'vanilla/tex_headers'
VENOM_DIR = 'profiles/venom'

RED_MESH_000, RED_MESH_001 = 0xAC92103D, 0xAC92103E
RED_SKELETONS = (0x461356AE, 0x461356AF)
# The black suit tools want every art resource of the archive except animations.
BLACK_KINDS = ('MESH', 'SKEL', 'MAT', 'TEX')

# Textures of the red suit whose 68-byte header (the IMG part of the texture: size, format, mip
# count, name pointer) is kept in vanilla/tex_headers. `png2tex.py --like` can copy the name
# pointer of a new texture from one of them.
RED_TEXTURE_HEADERS = (0x038C2751, 0x038C2764, 0x3EEEC795, 0x61DCA273, 0x66CED7A4, 0x70FE7BB1,
                       0x7D4C383D, 0x7D5E2562, 0x8E661B33, 0x8F6EE8BE, 0x92AAC237, 0xA06B2F53)

# Venom's resources, in STORY_MOVIE_4_PHASE3 (the only pack holding the whole Venom model).
VENOM_RESOURCES = (('MESH', 0xBF11C1BF), ('SKEL', 0x26EC9D72), ('MAT', 0x8910FC42),
                   ('TEX', 0xA164CFBD), ('TEX', 0xA164D857), ('TEX', 0xA164D85E),
                   ('TEX', 0xBF12903E))
VENOM_MESH_FILE = '0xBF11C1BF.ch_venom000.mesh'
VENOM_BLEND = 'Venom_editable.blend'

# ---- the Venom "direct" material (see build_venom_patch)
VENOM_MATERIAL = 0x8910FC42         # 'ch_venom01 - default', 184 bytes
SPIDER_MATERIAL = 0xE52A3DF4        # 'ch_spidermanspider' of CH_SPIDERMAN, 168 bytes
# Fields of Venom's material that keep their place in the new layout: name pointer, name hash,
# and the named reference at +0x14.
VENOM_KEPT_FIELDS = (0x00, 0x04, 0x14)
# Fields that move: Venom's texture/value references, from their place in Venom's material
# class to the place the Spider-Man character class reads them. Each of them has a fixup entry
# (the loader patches it at load time), and that entry has to follow the field.
VENOM_MOVED_FIELDS = {0x34: 0x24, 0x38: 0x80, 0x3C: 0x84, 0x40: 0xA8, 0x28: 0xAC}
VENOM_PATCH_PURPOSE = 'Spider-Man character shader, native Venom identity, direct albedo and normal slots'
VENOM_PATCH_STATUS = 'structurally validated; in-game test required'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    """JSON exactly as the reference files were written: indent 2, Windows line ends (CRLF),
    no newline at the end (Python's json.dumps written in text mode on Windows)."""
    return json.dumps(value, indent=2).replace('\n', '\r\n').encode('utf-8')


# ============================================================================ the game folder
def _studio_settings(root):
    try:
        with open(Path(root) / 'sm3_studio.json', encoding='utf-8-sig') as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return {}


def _registry_install_paths():
    """InstallPath written by the game's installer (32-bit key on 64-bit Windows, then native)."""
    try:
        import winreg
    except ImportError:             # not Windows
        return []
    found = []
    for key in (r'SOFTWARE\WOW6432Node\Activision\Spider-Man 3', r'SOFTWARE\Activision\Spider-Man 3'):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
                found.append(str(winreg.QueryValueEx(handle, 'InstallPath')[0]))
        except OSError:
            pass
    return found


def is_game_folder(folder):
    """A folder is the game if it holds the three packs we read."""
    packs = Path(folder) / 'packs'
    return all((packs / name).is_file() for name in (RED_PACK, BLACK_PACK, VENOM_PACK))


def find_game_folder(root, explicit=None):
    """First candidate that holds the packs, with the place it came from; (None, tried) if none.

    Same order as tools/boucle_test.ps1: explicit choice, SM3 Studio's "jeu" setting, registry,
    usual places. A Game.exe path is accepted too (its folder is used).
    """
    candidates = []
    if explicit:
        candidates.append((explicit, 'command line'))
    setting = str(_studio_settings(root).get('jeu') or '').strip().strip('"')
    if setting:
        candidates.append((setting, 'sm3_studio.json "jeu"'))
    candidates += [(path, 'registry InstallPath') for path in _registry_install_paths()]
    candidates += [(path, 'usual place') for path in (r'C:\Games\Spider-man 3',
                                                     r'C:\Program Files (x86)\Activision\Spider-Man 3',
                                                     r'C:\Program Files\Activision\Spider-Man 3')]
    tried = []
    for path, origin in candidates:
        folder = Path(path)
        if folder.suffix.lower() == '.exe':
            folder = folder.parent
        tried.append('%s (%s)' % (folder, origin))
        if is_game_folder(folder):
            return folder, origin, tried
    return None, None, tried


# ============================================================================ building files
def mesh_as_in_toolkit_sample(archive, record):
    """IMG part without its external-mesh table, then PHYS part (see the module docstring).

    The external-mesh table is the last 8 bytes per entry of the IMG part; header +0x18 holds the
    entry count and +0x1C its position (dword offset in the IMG component). We check that it is
    really at the end before cutting, so a different mesh layout fails loudly instead of being
    cut in the wrong place.
    """
    img, phys = record.pieces
    head = archive.piece_bytes(img)
    count, position = struct.unpack_from('<2I', head, 0x18)
    if count:
        table_start = position * 4 - (img.offset - archive.components[img.component].base)
        if table_start != len(head) - 8 * count:
            raise ValueError('%s: external-mesh table is not at the end of its header'
                             % record.file_name())
        head = head[:table_start]
    return head + archive.piece_bytes(phys)


def toolkit_sample(name):
    """The toolkit's copy of a red suit mesh, or None if the toolkit is not installed."""
    appdata = os.environ.get('APPDATA')
    if not appdata:
        return None
    path = Path(appdata).joinpath(*TOOLKIT_SAMPLES) / name
    return path.read_bytes() if path.is_file() else None


def build_venom_patch(venom_pack, venom_archive, spider_archive):
    """venom_shader_patch.json and venom_direct_material.bin, from the player's packs.

    The experiment rewrote Venom's material so that Venom is drawn by the Spider-Man character
    shader: same class hash and constants as `ch_spidermanspider`, but Venom's own name, hash and
    textures. Concretely the new 184 bytes are:
        * the 168 bytes of ch_spidermanspider (CH_SPIDERMAN), then 16 zero bytes;
        * Venom's name pointer, hash and +0x14 reference copied at the same place;
        * Venom's five texture/value references moved to the Spider-Man places
          (VENOM_MOVED_FIELDS).
    Each moved field has an entry in the archive's fixup tables (the dword the loader rebases);
    that entry is rewritten to designate the new position, so the loader keeps patching the right
    dword. Those entries are found by scanning the tables, not hard-coded.
    Returns (json bytes, material bytes), or raises ValueError with the reason.
    """
    venom = venom_archive.find('MAT', VENOM_MATERIAL)
    spider = spider_archive.find('MAT', SPIDER_MATERIAL)
    before = venom_archive.resource_bytes(venom)
    template = spider_archive.resource_bytes(spider)
    if len(before) != 184 or len(template) != 168:
        raise ValueError('unexpected material sizes (%d, %d)' % (len(before), len(template)))
    after = bytearray(template + bytes(len(before) - len(template)))
    for field in VENOM_KEPT_FIELDS:
        after[field:field + 4] = before[field:field + 4]
    for old, new in VENOM_MOVED_FIELDS.items():
        after[new:new + 4] = before[old:old + 4]
    after = bytes(after)

    piece = venom.pieces[0]
    material_offset = piece.offset - venom_archive.components[piece.component].base
    patches = [dict(offset=venom_archive.piece_file_offset(piece), before=before.hex(),
                    after=after.hex(), purpose=VENOM_PATCH_PURPOSE)]
    moved = []
    for entry in venom_archive.fixups():
        field = entry.target_offset - material_offset
        if entry.target_component != piece.component or field not in VENOM_MOVED_FIELDS:
            continue
        new_packed = (entry.target_component << 26) | ((material_offset + VENOM_MOVED_FIELDS[field]) // 4)
        moved.append(field)
        patches.append(dict(offset=entry.entry_offset,
                            before=struct.pack('<I', entry.packed).hex(),
                            after=struct.pack('<I', new_packed).hex(),
                            purpose='Material fixup +%X -> +%X' % (field, VENOM_MOVED_FIELDS[field])))
    if sorted(moved) != sorted(VENOM_MOVED_FIELDS):
        raise ValueError('fixup entries of the Venom material not found as expected')
    patches.sort(key=lambda item: item['offset'])

    data = bytearray(venom_pack.data)
    for item in patches:
        old, new = bytes.fromhex(item['before']), bytes.fromhex(item['after'])
        assert data[item['offset']:item['offset'] + len(old)] == old
        data[item['offset']:item['offset'] + len(new)] = new
    manifest = dict(version=1, pack=VENOM_PACK, original_sha256=sha256(venom_pack.data),
                    patched_sha256=sha256(bytes(data)), size=len(venom_pack.data),
                    patches=patches, status=VENOM_PATCH_STATUS)
    return json_bytes(manifest), after


def _open_archive(game, pack_name, folder_name):
    pack = pcpack.PcPack(Path(game) / 'packs' / pack_name)
    entry = pack.apkf_entry()
    if entry.folder_name != folder_name:
        raise ValueError('%s: archive is %s, SM3 Studio expects %s (different game release?)'
                         % (pack_name, entry.folder_name, folder_name))
    return pack, pack.apkf()


def build_files(game, fingerprints):
    """Every extractable file: {relative path: bytes}, plus {relative path: note} for remarks."""
    files, notes = {}, {}
    _, red = _open_archive(game, RED_PACK, RED_FOLDER)
    _, black = _open_archive(game, BLACK_PACK, BLACK_FOLDER)
    venom_pack, venom = _open_archive(game, VENOM_PACK, VENOM_FOLDER)

    # ---- red suit
    for skeleton in RED_SKELETONS:
        record = red.find('SKEL', skeleton)
        files['%s/%s' % (RED_DIR, record.file_name())] = red.resource_bytes(record)
    record = red.find('MESH', RED_MESH_000)
    files['%s/%s' % (RED_DIR, record.file_name())] = mesh_as_in_toolkit_sample(red, record)
    record = red.find('MESH', RED_MESH_001)
    path = '%s/%s' % (RED_DIR, record.file_name())
    sample = toolkit_sample(record.file_name())
    if sample is not None and compare(path, sample, fingerprints) == 'identical':
        files[path] = sample
        notes[path] = "copied from the SM3 Blender Toolkit's samples folder (its buffers are not the pack's)"
    else:
        files[path] = red.resource_bytes(record)
        notes[path] = ('SM3 Blender Toolkit sample not found (or not the expected file): written '
                       'from the pack instead (same header, real buffers; SM3 Studio only reads '
                       'the header of this file, so conversions are unchanged)')
    for texture in RED_TEXTURE_HEADERS:
        record = red.find('TEX', texture)
        name = '0x%08X.%s.hdr68.bin' % (record.hash, pcpack.safe_file_name(record.name))
        files['%s/%s' % (HEADERS_DIR, name)] = red.piece_bytes(record.pieces[0])

    # ---- black suit: the archive's art, a manifest of it, and the meshes/skeletons again
    loose = {}
    for kind in BLACK_KINDS:
        for record in black.of_kind(kind):
            loose[record.file_name()] = black.resource_bytes(record)
    for name, data in loose.items():
        files['%s/%s' % (BLACK_DIR, name)] = data
        if name.endswith('.mesh'):
            files['profiles/blacksuit/MESH/' + name] = data
        elif name.endswith('.skel'):
            files['profiles/blacksuit/SKEL/' + name] = data
    # resources.json (read by tools/blacksuit_resources.py): kinds in this order, names sorted.
    resources = {}
    for kind in BLACK_KINDS:
        for name in sorted(n for n in loose if n.endswith('.' + kind.lower())):
            resources[name] = sha256(loose[name])
    counts = {kind: sum(1 for n in loose if n.endswith('.' + kind.lower())) for kind in BLACK_KINDS}
    files['vanilla/CH_BLACKSUIT/resources.json'] = json_bytes(
        dict(scope=BLACK_FOLDER, resources=resources, counts=counts))

    # ---- Venom
    for kind, hash_value in VENOM_RESOURCES:
        record = venom.find(kind, hash_value)
        files['%s/%s' % (VENOM_DIR, record.file_name())] = venom.resource_bytes(record)
    try:
        patch, material = build_venom_patch(venom_pack, venom, red)
        files[VENOM_DIR + '/venom_shader_patch.json'] = patch
        files[VENOM_DIR + '/venom_direct_material.bin'] = material
    except (KeyError, ValueError) as error:
        notes[VENOM_DIR + '/venom_shader_patch.json'] = 'not built: %s' % error
    return files, notes


# ============================================================================ checking
def load_fingerprints(section=None):
    """Sizes and SHA-256 of the reference files, from game_data_fingerprints.json.

    Three sections: "extracted" (written by this script), "distributed" (our own measurements,
    shipped with SM3 Studio) and "optional" (Web of Shadows files, never extracted). Without a
    section name, all three merged."""
    with open(FINGERPRINTS, encoding='utf-8') as stream:
        table = json.load(stream)
    if section:
        return table[section]
    merged = {}
    for name in ('extracted', 'distributed', 'optional'):
        merged.update(table[name])
    return merged


def compare(path, data, fingerprints):
    expected = fingerprints.get(path)
    if expected is None:
        return 'no fingerprint'
    if len(data) == expected['size'] and sha256(data) == expected['sha256']:
        return 'identical'
    return 'different'


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(data)
    os.replace(temporary, path)        # never leave a half-written file behind


def make_venom_project(root, blender, log=print):
    """Venom_editable.blend: the Venom mesh imported by the toolkit, saved by Blender.

    Same command SM3 Studio's Venom tools use (tools/venom_blender.py --prepare). Returns a short
    status string."""
    root = Path(root)
    mesh = root / VENOM_DIR / VENOM_MESH_FILE
    output = root / VENOM_DIR / VENOM_BLEND
    if not blender or not Path(blender).is_file():
        return 'skipped: Blender not found (%s)' % blender
    if not mesh.is_file():
        return 'skipped: %s missing' % mesh.name
    command = [str(blender), '-b', '--python-exit-code', '1', '--python', str(HERE / 'venom_blender.py'),
               '--', '--src', str(mesh), '--out', str(output), '--prepare']
    log('Blender: preparing the editable Venom project (about 15 seconds)...')
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode != 0 or not output.is_file():
        tail = result.stdout.decode('utf-8', 'replace').strip().splitlines()[-5:]
        return 'failed (Blender exit code %d): %s' % (result.returncode, ' | '.join(tail))
    return 'created by Blender'


def report_lines(statuses, notes, extra):
    """Human-readable summary: identical / different / not rebuilt."""
    groups = {}
    for path, status in statuses.items():
        groups.setdefault(status, []).append(path)
    lines = ['identical to the reference: %d file(s)' % len(groups.get('identical', []))]
    for status in ('different', 'missing', 'no fingerprint'):
        if groups.get(status):
            lines.append('%s: %d file(s)' % (status, len(groups[status])))
            lines += ['    ' + path for path in sorted(groups[status])]
    for path, note in sorted(notes.items()):
        lines.append('note - %s: %s' % (path, note))
    lines += extra
    return lines


NOT_REBUILT = [
    'not rebuilt - profiles/rvb/*.glb, *.json except sources.json: Spider-Man: Web of Shadows data '
    '(Xbox 360), not part of Spider-Man 3 PC. The Web of Shadows mode stays off; copy profiles/rvb '
    'from an older SM3 Studio installation to turn it on.',
    'not rebuilt - profiles/venom/Venom_editable.blend1: Blender backup file, never read.',
]


# ============================================================================ entry points
# Rebuilt only when the Venom pack is the retail one (see build_venom_patch). No current code
# path needs them, so their absence does not trigger a new extraction before every conversion.
BEST_EFFORT = (VENOM_DIR + '/venom_shader_patch.json', VENOM_DIR + '/venom_direct_material.bin')


def missing_files(root):
    """Extracted files that are not on disk yet.

    Not counted: Venom_editable.blend (needs Blender, optional) and the BEST_EFFORT files."""
    root = Path(root)
    return [path for path in load_fingerprints('extracted')
            if path not in BEST_EFFORT and not (root / path).is_file()]


def extract(root, game, force=False, blender=None, use_blender=True, log=print):
    """Write the missing (or, with force, all) files under root. Returns (exit code, lines)."""
    root = Path(root)
    fingerprints = load_fingerprints()
    log('reading the packs of %s' % game)
    files, notes = build_files(game, fingerprints)
    statuses = {}
    written = 0
    for path, data in files.items():
        statuses[path] = compare(path, data, fingerprints)
        target = root / path
        if force or not target.is_file():
            _write(target, data)
            written += 1
    log('%d file(s) written under %s' % (written, root))
    extra = []
    blend = root / VENOM_DIR / VENOM_BLEND
    if use_blender and (force or not blend.is_file()):
        extra.append('note - %s/%s: %s' % (VENOM_DIR, VENOM_BLEND, make_venom_project(root, blender, log)))
    extra += NOT_REBUILT
    lines = report_lines(statuses, notes, extra)
    return (2 if any(s != 'identical' for s in statuses.values()) else 0), lines


def check(root):
    """Compare what is on disk with the fingerprints, without touching anything.

    Missing "optional" files (Web of Shadows) do not count as a failure."""
    root = Path(root)
    fingerprints = load_fingerprints()
    optional = load_fingerprints('optional')
    statuses = {}
    for path in fingerprints:
        target = root / path
        if target.is_file():
            statuses[path] = compare(path, target.read_bytes(), fingerprints)
        elif path not in optional:
            statuses[path] = 'missing'
    absent = sorted(path for path in optional if not (root / path).is_file())
    extra = ['optional, absent (Web of Shadows mode off): %d file(s)' % len(absent)] if absent else []
    lines = report_lines(statuses, {}, extra)
    return (0 if all(s == 'identical' for s in statuses.values()) else 2), lines


def blender_path(root, explicit=None):
    return explicit or _studio_settings(root).get('blender') or DEFAULT_BLENDER


def ensure_game_data(root, game=None, log=print, blender=None):
    """Called by SM3 Studio before a conversion: extract the game data if any of it is missing.

    `blender` is the converter's Blender (default: sm3_studio.json "blender", then the usual path).

    Does nothing (beyond a few file checks) when everything is already there, so a complete
    installation behaves exactly as before. Raises SystemExit with instructions when the game
    cannot be found.
    """
    missing = missing_files(root)
    if not missing:
        return
    log('SM3 Studio needs %d file(s) from your copy of Spider-Man 3 (first use: they are not '
        'distributed with the tool). Extracting them now...' % len(missing))
    folder, origin, tried = find_game_folder(root, game)
    if folder is None:
        raise SystemExit(
            'Spider-Man 3 was not found, so SM3 Studio cannot read the game files it measures '
            'models against.\nLooked in:\n    ' + '\n    '.join(tried) +
            '\nSet "Game folder" in the Paths tab (the folder that contains Game.exe and packs\\), '
            'then convert again, or run:\n    python tools/extraire_donnees_jeu.py --game '
            '"<your Spider-Man 3 folder>"')
    log('game folder: %s (%s)' % (folder, origin))
    try:
        code, lines = extract(root, folder, blender=blender_path(root, blender), log=log)
    except (OSError, KeyError, ValueError) as error:
        raise SystemExit('Could not read the game files SM3 Studio needs from %s:\n    %s\n'
                         'Is it the PC version of Spider-Man 3, with its original packs? Details:\n'
                         '    python tools/extraire_donnees_jeu.py --game "%s"' % (folder, error, folder))
    for line in lines:
        log(line)
    if code:
        log('WARNING: some files differ from the ones SM3 Studio was tested with (see above). '
            'The tool will run, but results may differ. Is the game modded?')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Rebuild SM3 Studio's vanilla/ and profiles/ folders from your copy of "
                    'Spider-Man 3 (PC). Nothing is written into the game folder.')
    parser.add_argument('--game', default='', help='Spider-Man 3 folder (the one with packs\\ and Game.exe)')
    parser.add_argument('--root', default=str(HERE.parent),
                        help='SM3 Studio folder to write into (default: the one holding tools/)')
    parser.add_argument('--blender', default='', help='blender.exe, for Venom_editable.blend')
    parser.add_argument('--no-blender', action='store_true', help='do not create Venom_editable.blend')
    parser.add_argument('--force', action='store_true', help='rewrite every file, even those present')
    parser.add_argument('--check', action='store_true', help='only compare the files present with the reference')
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        code, lines = check(root)
    else:
        folder, origin, tried = find_game_folder(root, args.game or None)
        if folder is None:
            print('Spider-Man 3 not found. Looked in:\n    ' + '\n    '.join(tried) +
                  '\nGive the folder with --game "<Spider-Man 3 folder>".')
            return 1
        print('game folder: %s (%s)' % (folder, origin))
        try:
            code, lines = extract(root, folder, force=args.force, blender=blender_path(root, args.blender),
                                  use_blender=not args.no_blender)
        except (OSError, KeyError, ValueError) as error:
            print('Could not read the game files: %s' % error)
            return 1
    print('\n'.join(lines))
    return code


if __name__ == '__main__':
    sys.exit(main())
