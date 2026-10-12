# SPDX-License-Identifier: GPL-3.0-or-later
"""SM3 .PCSKEL / nal_skeleton parser.

NOT USED by SM3 Studio: no module imports it (checked with a search of the whole repository).
It is a stand-alone parser kept from the early reverse-engineering of the game files; the
conversion reads skeletons with the toolkit's sm3_format.parse_skeleton (sm3_sans_blender.fmt).
Its layout notes below remain a useful reference.

Skeletons live inside the APKF ("merged animation pack") blob that occupies the
type-54 bulk section of a .PCPACK. Skeleton blob layout (little-endian):

  +0x00  u32  name_ptr    0xFC-tagged: name at name_base + (ptr & 0xFFFFFF)*4
  +0x04  u32  name_hash   32-bit resource hash of the skeleton name
  +0x08  u32  bone_count
  +0x0C  u32  unknown
  +0x10  bone records, bone_count x 0x90 bytes:
     +0x00  float[16]  matrix A   4x4 row-major; identity in all 369 observed
                                  skeletons ([3][3] junk) - runtime pose scratch
     +0x40  float[16]  matrix B   4x4 row-major INVERSE BIND matrix (model->bone,
                                  D3D row-vector convention). Rows 0-2 = rotation
                                  (may include scale, e.g. Rhino 2.6x), row 3 =
                                  translation, column 3 = uninitialized junk.
     +0x80  u32  name_ptr        0xFC-tagged bone name pointer
     +0x84  u32  name_hash       bone name hash
     +0x88  i32  parent          parent bone index, -1 = root
     +0x8C  u32  pad (0)

Bind-pose bone position (model space, origin at pelvis, Y up):
    p_j = -(row_j . t) / |row_j|^2
Bone->model ("world") matrix = inverse of B.
"""
import struct
import numpy as np

REC = 0x90


def find_skeletons(d):
    """Scan a whole pack buffer for skeleton blobs.

    Signature: arithmetic progression of 0xFC-top-byte dwords with stride 0x90
    (header name_ptr at X, bone i name_ptr at X + 0x90*(i+1)), a plausible count
    at X+8, parent[0] == -1 and 0 <= parent[i] < i.
    """
    out = []
    b = np.frombuffer(d, dtype=np.uint8)
    fc = np.flatnonzero(b[3::4] == 0xFC) * 4
    fcset = set(int(x) for x in fc)
    for X in fc:
        X = int(X)
        if X + 0x10 + REC > len(d):
            continue
        count = struct.unpack_from('<I', d, X + 8)[0]
        if not (1 <= count <= 1024):
            continue
        if X + 0x10 + count * REC > len(d):
            continue
        if not all((X + 0x90 * (i + 1)) in fcset for i in range(count)):
            continue
        ok = True
        for i in range(count):
            par = struct.unpack_from('<i', d, X + 0x10 + i * REC + 0x88)[0]
            if i == 0 and par != -1:
                ok = False; break
            if i > 0 and not (0 <= par < i):
                ok = False; break
        if ok:
            out.append(X)
    pruned = []
    for X in sorted(out):
        count = struct.unpack_from('<I', d, X + 8)[0]
        end = X + 0x10 + count * REC
        if pruned and X < pruned[-1][1]:
            continue
        pruned.append((X, end))
    return [x for x, _ in pruned]


def _cstr(d, off):
    e = d.find(b'\0', off, off + 256)
    if e < 0:
        return None
    s = d[off:e]
    if not s or not all(32 <= c < 127 for c in s):
        return None
    return s.decode('latin1')


def solve_name_base(d, X, count):
    """Find base so that fc-ptrs resolve to strings; score = ptrs landing on
    string STARTS (previous byte not printable). Anchors: any occurrence of
    'skeleton' / 'pelvis' aligned to the header/bone-0 ptr."""
    ptrs = [struct.unpack_from('<I', d, X)[0]]
    for i in range(count):
        ptrs.append(struct.unpack_from('<I', d, X + 0x10 + i * REC + 0x80)[0])
    offs = [(p & 0xFFFFFF) * 4 for p in ptrs]

    def score(base):
        """(valid_ptr_count, string_start_count) for a candidate base."""
        if base < 0:
            return (0, 0)
        nvalid = nstart = 0
        for o in offs:
            p = base + o
            if p + 2 > len(d) or _cstr(d, p) is None:
                continue
            nvalid += 1
            if p == 0 or not (32 <= d[p - 1] < 127):
                nstart += 1
        return (nvalid, nstart)

    import re
    cands = set()
    for pat, anchor_idx in ((b'skeleton', 0), (b'pelvis', 1), (b'bone', 1)):
        for m in re.finditer(pat, d):
            s = m.start()
            while s > 0 and 32 <= d[s - 1] < 127:
                s -= 1
            # the true name start is anywhere in [s, m.start()] (leading bytes of
            # the printable run may be padding garbage); names are 4-aligned
            for p in range(s, m.start() + 1):
                cands.add(p - offs[anchor_idx])
    best, best_sc = None, (0, 0)
    for base in sorted(cands):
        sc = score(base)
        if sc > best_sc:
            best, best_sc = base, sc
    # only accept a base that resolves every pointer
    if best is not None and best_sc[0] == len(offs):
        return best
    return None


def parse_skeleton(d, X, name_base=None):
    nptr, shash, count, unk = struct.unpack_from('<4I', d, X)
    if name_base is None:
        name_base = solve_name_base(d, X, count)

    def nm(ptr):
        if name_base is None:
            return None
        return _cstr(d, name_base + (ptr & 0xFFFFFF) * 4)

    bones = []
    worlds = []
    for i in range(count):
        base = X + 0x10 + i * REC
        Am = np.array(struct.unpack_from('<16f', d, base)).reshape(4, 4)
        Bm = np.array(struct.unpack_from('<16f', d, base + 0x40)).reshape(4, 4)
        bptr, bhash, par, _pad = struct.unpack_from('<IIiI', d, base + 0x80)
        R = Bm[:3, :3]                       # rows
        t = Bm[3, :3]
        s = np.linalg.norm(R, axis=1)        # per-row scale
        Rn = R / s[:, None]
        pos = -(Rn @ t) / s
        ortho = float(np.abs(Rn @ Rn.T - np.eye(3)).max())
        a_dev = float(np.abs(Am[:3, :3] - np.eye(3)).max() + np.abs(Am[3, :3]).max())
        # column-vector 4x4 of the inverse bind: C = [[R^T_rows, t],[0,1]]
        C = np.eye(4)
        C[:3, :3] = R.T
        C[:3, 3] = t
        W = np.linalg.inv(C)                 # bone -> model
        worlds.append(W)
        bones.append(dict(index=i, name=nm(bptr), hash=bhash, parent=par,
                          pos=pos, scale=s, inv_bind=Bm, matrix_a=Am,
                          world=W, ortho_err=ortho, a_dev=a_dev))
    for bn in bones:
        par = bn['parent']
        W = bn['world']
        bn['local'] = W if par < 0 else np.linalg.inv(worlds[par]) @ W
    return dict(offset=X, name=nm(nptr), hash=shash, bone_count=count,
                unknown=unk, name_base=name_base, bones=bones)
