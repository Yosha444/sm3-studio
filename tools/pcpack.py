# SPDX-License-Identifier: GPL-3.0-or-later
"""pcpack.py - read-only reader for Spider-Man 3 (PC, 2007) .PCPACK archives.

SM3 Studio does not ship any file of the game. `tools/extraire_donnees_jeu.py` rebuilds the few
files the tool needs from the player's own copy of the game, and this module is how it reads them.
It never writes anything: open a pack, list what is inside, copy bytes out.

The format, top-down (every integer is little-endian; what is written here was MEASURED on the
1,096 packs of the retail PC game, see "Where this comes from" at the end):

    CH_SPIDERMAN.PCPACK
    |
    +-- 0x00  outer header, 0x30 bytes (build stamps; nothing we need)
    +-- 0x30  directory block, magic 'hsam' + 0x12345678
    |         +0x44 dw44 (1 or 11; 0 in GAME.PCPACK)   +0x54 entry count
    |         at 0x368 + 4*dw44: `count` records of 16 bytes  {hash, type, offset, size}
    |         = every resource of the pack: collision, sounds, scripts... and ONE record of
    |           type 54, the APKF archive, which holds all the ART of the pack.
    |
    +-- the APKF archive (type 54)
        +0x00 'APKF'   +0x04 version 0x107   +0x10 component count   +0x14 -> component table
        +0x1C group list, one group per resource kind (MAT, TEX, MESH, SKEL, ANIM, ...)
        components (usually two):
            IMG   the serialized objects: mesh headers, texture descriptors, materials...
            PHYS  the bulk data: vertex and index buffers, texture pixels
        after the last component: the fixup tables the game's loader applies (pointers to patch)

What makes the APKF tricky is that a record does NOT store where its bytes are. A record only says
how many bytes it owns in each "slot" (for a mesh: slot 0 = its header in IMG, slot 1 = its
buffers in PHYS). The game finds the bytes by walking every group in file order, every record in
order, with one running cursor per slot, rounding the cursor up to the alignment the group asks
for. `ApkfArchive._assign_pieces` is that walk, line for line. Get one alignment wrong and every
following resource comes out shifted - which is why this reader checks that each cursor ends
inside its component.

A resource extracted "as a file" (the `0x<hash>.<name>.<kind>` files SM3 Studio reads) is simply
its pieces concatenated in component order: IMG part, then PHYS part. That rule reproduces the
reference files byte for byte (186/186 CH_BLACKSUIT resources, 7/7 Venom resources, the 2 red
suit skeletons; the 12 texture headers are the IMG part alone); see tools/extraire_donnees_jeu.py
for the two red suit meshes, whose differences come from the reference files themselves, not from
this reader.

Where this comes from
---------------------
  * Directory block: our probes over all 1,096 packs (records sorted by type then hash, every
    `offset + size` inside the file, exactly one type-54 record per pack).
  * APKF layout and the cursor walk: the loader of Game.exe (relocation routine at VA 0x9CB1A0,
    slot loop at VA 0x9CB2B0-0x9CB337, cursors indexed by SLOT, zeroed once per archive), then
    re-checked on every pack: the walk ends inside its component in 1,096/1,096 packs.
  * In every observed group the slot index equals the component index (IMG = slot 0,
    PHYS = slot 1), so "a cursor per slot" and "a cursor per component" give the same offsets.
    We follow the game (per slot) and simply say so.

Command line, for humans who want to look inside a pack:

    python tools/pcpack.py "C:/Games/Spider-man 3/packs/CH_SPIDERMAN.PCPACK"
    python tools/pcpack.py <pack> --kind MESH
"""
from __future__ import annotations

import os
import re
import struct
import sys
from dataclasses import dataclass

# Resource type of the APKF archive in the pack directory (index in the game's type registry).
APKF_TYPE = 54
DIRECTORY_MAGIC = b'hsam'
APKF_MAGIC = b'APKF'
APKF_VERSION = 0x107
# A group binding of 0xFF in its top byte means "this group owns nothing in that component".
NO_SLOT = 0xFF


def _u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def _i32(data, offset):
    return struct.unpack_from('<i', data, offset)[0]


def _tag(value):
    """A four-character code stored as a dword: b'MESH', b'TEX\\0' -> 'MESH', 'TEX'."""
    return value.to_bytes(4, 'little').rstrip(b'\0').decode('ascii', 'replace')


def _align_up(value, alignment):
    if alignment <= 1:
        return value
    return (value + alignment - 1) & ~(alignment - 1)


def safe_file_name(name):
    """The file-name form of a record name, as used by every extracted file of SM3 Studio.

    Records keep the artists' names: 'ch_blacksuitred(black)_lod', 'ui_tr_01material #22',
    '_normswizzle'. The extracted files replace each run of characters outside [A-Za-z0-9_.-] by
    ONE underscore, then drop underscores at both ends:

        ch_blacksuitred(black)_lod  ->  ch_blacksuitred_black__lod
        ui_tr_01material #22        ->  ui_tr_01material_22
        ch_venom01 - default        ->  ch_venom01_-_default
        _normswizzle                ->  normswizzle

    (Rule measured on the 258 resource files of the reference installation: it reproduces every
    one of their names.)
    """
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', name).strip('_')


@dataclass(frozen=True)
class DirectoryEntry:
    """One record of the pack directory: a whole resource of the pack."""
    index: int      # position in the directory (SM3 Studio's folder names use it: "_O0069")
    hash: int       # 32-bit hash of the resource name
    type: int       # index in the game's resource-type registry (54 = APKF archive)
    offset: int     # absolute offset in the .PCPACK file
    size: int

    @property
    def folder_name(self):
        """Folder name SM3 Studio and xeSM3 use for this archive: _O<index>.0x<HASH>.T<type hex>.apkf

        Example: CH_SPIDERMAN's archive is directory record 69, hash 0xCFB154CD, type 54 = 0x36,
        hence `_O0069.0xCFB154CD.T36.apkf`.
        """
        return '_O%04d.0x%08X.T%02X.apkf' % (self.index, self.hash, self.type)


@dataclass(frozen=True)
class Component:
    """A data block of the APKF archive (IMG or PHYS)."""
    index: int
    tag: str        # 'IMG' or 'PHYS'
    flags: int
    alignment: int  # 16 for IMG; 64 or 4 for PHYS depending on the pack
    size: int
    base: int       # offset of the block inside the APKF archive


@dataclass(frozen=True)
class Group:
    """All records of one kind (MAT, TEX, MESH, SKEL, ...)."""
    kind: str
    version: int
    slot_count: int
    record_count: int
    records_offset: int     # offset of the record table inside the APKF archive
    # one entry per component: (slot index, alignment), or None when the group has no data there
    bindings: tuple


@dataclass(frozen=True)
class Piece:
    """The bytes a record owns in one component."""
    component: int
    offset: int     # inside the APKF archive
    size: int


@dataclass(frozen=True)
class Record:
    """One resource of the APKF archive: a material, a texture, a mesh, a skeleton..."""
    kind: str
    name: str
    hash: int
    sizes: tuple    # bytes owned in each slot, as stored
    pieces: tuple   # where those bytes are, in component order (computed by the cursor walk)
    record_offset: int  # offset of the record entry inside the APKF archive

    def file_name(self):
        """`0x<HASH>.<name>.<kind>`, e.g. `0xAC92103D.ch_spiderman000.mesh`."""
        return '0x%08X.%s.%s' % (self.hash, safe_file_name(self.name), self.kind.lower())


@dataclass(frozen=True)
class FixupEntry:
    """One entry of the loader's fixup tables: "the dword at `target` is a pointer to patch".

    `entry_offset` is where the ENTRY itself sits in the .PCPACK file; `target_component` and
    `target_offset` say which dword it designates (offset inside that component).
    """
    table: str              # 'relocation' (4-byte entries) or 'reference' (16-byte entries)
    entry_offset: int       # absolute offset of the entry in the .PCPACK file
    packed: int             # the stored dword: component << 26 | dword offset
    target_component: int
    target_offset: int


class ApkfArchive:
    """The APKF archive of a pack: components, groups, records and where each record's bytes are."""

    def __init__(self, data, file_offset=0, label='APKF'):
        self.data = data                # the archive bytes only
        self.file_offset = file_offset  # where the archive starts in the .PCPACK file
        self.label = label
        if data[:4] != APKF_MAGIC:
            raise ValueError('%s: not an APKF archive (magic %r)' % (label, data[:4]))
        if _u32(data, 4) & 0xFFFF != APKF_VERSION:
            raise ValueError('%s: unexpected APKF version 0x%X' % (label, _u32(data, 4)))
        self.components = self._read_components()
        self.groups = self._read_groups()
        self.records = self._assign_pieces()

    # ------------------------------------------------------------------ structure
    def _read_components(self):
        d = self.data
        count = _u32(d, 0x10)
        table = 0x14 + _i32(d, 0x14)          # self-relative pointer: target = field + value
        components = []
        for index in range(count):
            entry = table + 24 * index
            base = entry + 20 + _i32(d, entry + 20)
            component = Component(index=index, tag=_tag(_u32(d, entry)), flags=_u32(d, entry + 4),
                                  alignment=_u32(d, entry + 8), size=_u32(d, entry + 16), base=base)
            if not 0 <= component.base <= component.base + component.size <= len(d):
                raise ValueError('%s: component %s outside the archive' % (self.label, component.tag))
            components.append(component)
        return components

    def _read_groups(self):
        d = self.data
        count = len(self.components)
        groups = []
        offset = 0x1C
        while _u32(d, offset) != 0:            # the group list ends with a zero tag
            bindings = []
            for index in range(count):
                value = _u32(d, offset + 20 + 4 * index)
                slot, alignment = value >> 24, value & 0xFFFFFF
                bindings.append(None if slot == NO_SLOT else (slot, alignment))
            groups.append(Group(kind=_tag(_u32(d, offset)), version=_u32(d, offset + 4),
                                slot_count=_u32(d, offset + 8), record_count=_u32(d, offset + 16),
                                records_offset=offset + 12 + _i32(d, offset + 12),
                                bindings=tuple(bindings)))
            offset += 20 + 4 * count
            if len(groups) > 64:
                raise ValueError('%s: group list without terminator' % self.label)
        return groups

    def _assign_pieces(self):
        """The game's cursor walk (Game.exe VA 0x9CB2B0): give every record its bytes.

        One cursor per slot, shared by all groups, in file order. For each record and each
        component the group writes to: round the cursor up to the group's alignment, the record's
        piece starts there, then advance the cursor by the record's size in that slot.
        """
        d = self.data
        cursors = {}
        records = []
        for group in self.groups:
            entry_size = 4 * (group.slot_count + 2)     # {name pointer, hash, size per slot}
            for number in range(group.record_count):
                entry = group.records_offset + number * entry_size
                name = ''
                if _u32(d, entry):                      # 0 = unnamed
                    start = entry + _i32(d, entry)
                    name = d[start:d.index(b'\0', start)].decode('latin-1')
                sizes = tuple(_u32(d, entry + 8 + 4 * slot) for slot in range(group.slot_count))
                pieces = []
                for component, binding in zip(self.components, group.bindings):
                    if binding is None:
                        continue
                    slot, alignment = binding
                    start = _align_up(cursors.get(slot, 0), alignment)
                    pieces.append(Piece(component.index, component.base + start, sizes[slot]))
                    cursors[slot] = start + sizes[slot]
                records.append(Record(kind=group.kind, name=name, hash=_u32(d, entry + 4),
                                      sizes=sizes, pieces=tuple(pieces), record_offset=entry))
        # Safety net: a wrong alignment would push the last cursors past their component.
        for group in self.groups:
            for component, binding in zip(self.components, group.bindings):
                if binding and cursors.get(binding[0], 0) > component.size:
                    raise ValueError('%s: records overflow component %s (%d > %d bytes)'
                                     % (self.label, component.tag, cursors[binding[0]], component.size))
        return records

    # ------------------------------------------------------------------ access
    def find(self, kind, hash_value):
        """The record of this kind and hash. Raises KeyError when the archive does not have it."""
        for record in self.records:
            if record.kind == kind and record.hash == hash_value:
                return record
        raise KeyError('%s: no %s record with hash 0x%08X' % (self.label, kind, hash_value))

    def of_kind(self, kind):
        return [record for record in self.records if record.kind == kind]

    def piece_bytes(self, piece):
        return self.data[piece.offset:piece.offset + piece.size]

    def resource_bytes(self, record):
        """The resource as a loose file: its pieces concatenated in component order (IMG, PHYS)."""
        return b''.join(self.piece_bytes(piece) for piece in record.pieces)

    def piece_file_offset(self, piece):
        """Absolute offset of a piece in the .PCPACK file."""
        return self.file_offset + piece.offset

    # ------------------------------------------------------------------ fixups
    def fixups(self):
        """The two fixup tables the loader walks after placing the components.

        They start right after the data of the last component without flag bit 1, rounded up to
        4 bytes:
          relocations : dwords until 0xFFFFFFFF, each one designates a pointer field to rebase;
          references  : 16-byte entries {designated field, kind, name, hash} until 0xFFFFFFFF,
                        each one a named link to another resource.
        A designation is packed as `component << 26 | dword offset in that component`.
        Only the designations are decoded here: that is all SM3 Studio needs (to move a material's
        fields, see the Venom patch in tools/extraire_donnees_jeu.py).
        """
        d = self.data
        candidates = [c for c in self.components if not c.flags & 2]
        if not candidates:
            return []
        last = candidates[-1]
        cursor = _align_up(last.base + last.size, 4)
        entries = []

        def designate(packed, table, entry_offset):
            component = packed >> 26
            offset = (packed & 0x3FFFFFF) * 4
            if component >= len(self.components) or offset + 4 > self.components[component].size:
                raise ValueError('%s: fixup outside its component (0x%08X)' % (self.label, packed))
            entries.append(FixupEntry(table, self.file_offset + entry_offset, packed, component, offset))

        while _u32(d, cursor) != 0xFFFFFFFF:
            designate(_u32(d, cursor), 'relocation', cursor)
            cursor += 4
        cursor += 4
        while _u32(d, cursor) != 0xFFFFFFFF:
            designate(_u32(d, cursor), 'reference', cursor)
            cursor += 16
        return entries


class PcPack:
    """A .PCPACK file: its directory, and its APKF archive."""

    def __init__(self, path):
        self.path = os.fspath(path)
        self.name = os.path.basename(self.path)
        with open(self.path, 'rb') as stream:
            self.data = stream.read()
        self.entries = self._read_directory()

    def _read_directory(self):
        d = self.data
        if d[0x30:0x34] != DIRECTORY_MAGIC:
            raise ValueError('%s: not a Spider-Man 3 PC pack (no directory block at 0x30)' % self.name)
        style = _u32(d, 0x44)
        count = _u32(d, 0x54)
        table = 0x368 + 4 * style
        entries = []
        for index in range(count):
            hash_value, type_id, offset, size = struct.unpack_from('<4I', d, table + 16 * index)
            if offset + size > len(d):
                raise ValueError('%s: directory record %d outside the file' % (self.name, index))
            entries.append(DirectoryEntry(index, hash_value, type_id, offset, size))
        return entries

    def apkf_entry(self):
        """The directory record of the pack's APKF archive (exactly one per pack)."""
        found = [e for e in self.entries if e.type == APKF_TYPE]
        if len(found) != 1:
            raise ValueError('%s: %d APKF archives, expected exactly one' % (self.name, len(found)))
        return found[0]

    def apkf(self):
        entry = self.apkf_entry()
        return ApkfArchive(self.data[entry.offset:entry.offset + entry.size], entry.offset,
                           '%s %s' % (self.name, entry.folder_name))


def _main(argv):
    import argparse
    parser = argparse.ArgumentParser(description='List the art resources of a Spider-Man 3 PC pack.')
    parser.add_argument('pack', help='path to a .PCPACK file')
    parser.add_argument('--kind', default='', help='only this kind: MESH, TEX, MAT, SKEL, ANIM...')
    args = parser.parse_args(argv)
    pack = PcPack(args.pack)
    archive = pack.apkf()
    print('%s: %d directory records; APKF archive = %s' % (pack.name, len(pack.entries),
                                                            pack.apkf_entry().folder_name))
    for component in archive.components:
        print('  component %-4s base 0x%08X size %10d alignment %d'
              % (component.tag, component.base, component.size, component.alignment))
    for record in archive.records:
        if args.kind and record.kind != args.kind.upper():
            continue
        print('  %-4s %-60s %s' % (record.kind, record.file_name(),
                                   ' + '.join(str(piece.size) for piece in record.pieces)))


if __name__ == '__main__':
    _main(sys.argv[1:])
