# What we measured about Spider-Man 3's file formats

This page collects what SM3 Studio's authors measured about the formats of *Spider-Man 3* (PC,
Treyarch / Activision, 2007) while building the tool: the packs, the loose resources xeSM3 loads,
meshes, skeletons, textures, materials, and the shaders inside `Game.exe`. It contains descriptions
and numbers only, never bytes of the game.

**How to read it.** Every statement is *measured* unless marked *assumed* or listed under
[Open questions](#open-questions). "Measured" means one of: read on the retail PC game's files (the
1,096 packs, `Game.exe`), read in a disassembly of `Game.exe` or of xeSM3, checked by a tool of this
repository on those files, or seen in game. All integers are **little-endian**. Offsets are in hex.
Code addresses in `Game.exe` are virtual addresses (image base 0x400000); shader positions are
**file offsets** (add 0x400000 for the address).

Where it comes from: the docstrings of `tools/pcpack.py`, `tools/extraire_donnees_jeu.py`,
`sm3_convertir.py`, `tools/png2tex.py`, `tools/decoupe_sections.py`, `tools/costume_mat.py` and the
other tools, the measurements of 2026-10-12 recorded in this page, and the development notes in
[`docs/historique/`](historique/README.md). The mesh and skeleton parser SM3 Studio uses is
TSGAMING264's (`sm3_format.py` of the SM3 Blender Toolkit); the layouts below agree with it.

---

## 1. Names and hashes

Every resource, and every material *class*, is identified by a 32-bit hash of its name:

```
h = 0
for each character c of the name, lower-cased:  h = (h * 33 + c) mod 2^32
```

It is djb2 with a seed of **0** instead of 5381. Found on 41 of 41 (name, hash) pairs, then
confirmed on names outside that set; for example `ch_spiderman000` → `0xAC92103D`,
`ch_spiderman001` → `0xAC92103E`, `_normswizzle` → `0x61DCA273`, `sm_phat` → `0x99A1E0EC`,
`sm_phatspiderman` → `0x2B7A650F`. The hashes are computed at load time, so they never appear as
constants in `Game.exe`.

A loose resource is named `0x<HASH>.<name>.<kind>` (`0xAC92103D.ch_spiderman000.mesh`). The name
part is the record's name with every run of characters outside `[A-Za-z0-9_.-]` replaced by one
underscore and underscores trimmed at both ends (`_normswizzle` → `normswizzle`,
`ch_venom01 - default` → `ch_venom01_-_default`); the hash is that of the **original** name. Rule
measured on the 258 resource files SM3 Studio uses.

## 2. PCPACK archives

A `.PCPACK` (folder `packs\`, 1,096 files) holds every resource of one level or character. Layout,
measured on all 1,096:

```
0x00   outer header, 0x30 bytes (build stamps)
0x30   directory block: 'hsam', 0x12345678
       +0x44 dw44 (1 or 11; 0 in GAME.PCPACK)    +0x54 record count
       records at 0x368 + 4*dw44, 16 bytes each: { hash, type, offset, size }
       sorted by type then hash; every offset + size inside the file
       exactly ONE record of type 54: the APKF archive, which holds all the art of the pack
       (the type is an index in the game's resource-type registry: collision, scripts, sounds...;
       53 = sound bank, 54 = APKF archive, 68 = "cowbell", animated material parameters)
```

**The APKF archive** (type 54):

```
+0x00 'APKF'   +0x04 version 0x107   +0x10 component count   +0x14 -> component table
+0x1C group list: one group per resource kind (MAT, TEX, MESH, SKEL, ANIM, ASKL...)
components (two in practice):
    IMG   the serialized objects: mesh headers, texture headers, materials, skeletons (alignment 16)
    PHYS  the bulk data: vertex and index buffers, texture pixels (alignment 64 or 4)
after the last component: the fixup tables the game's loader applies (pointers to patch)
```

A record does **not** store where its bytes are: it only says how many bytes it owns in each
*slot* (for a mesh: slot 0 = its header in IMG, slot 1 = its buffers in PHYS). The game finds the
bytes by walking every group in file order and every record in order, with one running cursor per
slot, rounding each cursor up to the alignment the group asks for (the loader's relocation routine
at 0x9CB1A0, slot loop 0x9CB2B0-0x9CB337). Get one alignment wrong and everything after it is
shifted. Our reader repeats that walk and checks that every cursor ends inside its component: it
does in 1,096 of 1,096 packs (215,874 records and 2,099,710 fixup entries read, no error). In every
observed group slot *n* is component *n*.

**A resource as a loose file** is its pieces concatenated in component order: IMG part, then PHYS
part. That rule reproduces every file SM3 Studio uses: 186 of 186 black-suit resources, 7 of 7
Venom resources, the 2 red-suit skeletons; the 12 texture headers are the IMG part alone. (The two
red-suit meshes differ only because of the reference copies SM3 Studio was calibrated on, see
`tools/extraire_donnees_jeu.py`.)

Example, `CH_SPIDERMAN.PCPACK`: 126 directory records; the APKF archive is record 69, hash
`0xCFB154CD`; IMG 4,875,116 bytes, PHYS 8,197,928 bytes; groups: 48 MAT, 68 TEX, 27 MESH, 2 SKEL,
746 ANIM, 1 ASKL.

**Tagged pointers.** Inside serialized objects, pointers are dwords whose top byte is a tag (0x04
for buffers, 0xFC for names) and whose low 24 bits count dwords from a base:
`byte offset = base + (ptr & 0xFFFFFF) * 4`. Names live in a name table of the APKF archive.

**Folder names used by xeSM3 and SM3 Studio:** `_O<record index, 4 digits>.0x<archive hash>.T<type
in hex>.apkf`. The ones SM3 Studio uses:

| Pack | Archive folder | Used for |
|---|---|---|
| `CH_SPIDERMAN` | `_O0069.0xCFB154CD.T36.apkf` | red suit (reference files and mod) |
| `MARYJANE_SCARERIDE` | `_O0082.0x4F920A48.T36.apkf` | red suit (mod) |
| `STORY_MOVIE_3` | `_O0121.0x03294B12.T36.apkf` | red suit textures (mod) |
| `CH_BLACKSUIT` | `_O0108.0xF8ACB40C.T36.apkf` | black suit |
| `STORY_MOVIE_4_PHASE3` | `_O0114.0x2AF92556.T36.apkf` | Venom |

## 3. xeSM3 mods

xeSM3 (TSGAMING264) loads loose resources instead of the pack's copy:

```
<game>\Mods\<mod name>\<PACK>\<archive folder>\0x<hash>.<name>.<kind>
<game>\Mods\mods.config.ini      [EnabledMods]  <mod name>=100 (enabled) or 0 (disabled)
```

- A file only replaces the resource of **that** pack and archive: no global fallback. A suit used
  by several packs must be copied under each of them (three for the red suit).
- Only `Mods\mods.config.ini` is read; the last assignment of a name wins; an invalid value
  disables the mod rather than crashing (messages embedded in the DLL). xeSM3 writes **no log**: the
  only verdict is the game.
- Limits found in the DLL: 1 to 256 sections per mesh, 64 MiB per mesh file.
- **Material of a section**: for `ch_spiderman000/001` (`0xAC92103D/E`) xeSM3 maps a section to its
  material by **reference** (a legacy map table); for any other mesh, by section **index**. So the
  red suit can have several sections with the same material, while the black suit and Venom keep
  their native section order (the black suit's texture is carried only by section 3).
- **No suit `.mat`**: xeSM3 checks a material's class against `sm_phat` (`0x99A1E0EC`) and size
  0xA0 only; the suit's class `sm_phatspiderman` (`0x2B7A650F`, 168 bytes) is rejected (checked
  again in version 0.1.4: one comparison with `sm_phat`, none with `0x2B7A650F`). Suit mods
  therefore change materials by pointing sections at another existing material, or by patching the
  shaders.

## 4. Meshes (`.mesh`)

### Layout

```
IMG part (the serialized object)
  +0x00 name pointer          +0x04 name hash (= the file's hash)   +0x08 flags   +0x0C section count
  +0x10 section table pointer +0x14 skeleton reference              +0x18 external-mesh count
  +0x1C external-mesh table pointer
  +0x20 model offset (3 floats)  +0x2C bounding-sphere radius  +0x30 bounding box (4 floats)
  +0x40 a 0x10-byte block kept as it is
  section table: 8 bytes per section
  then, 16-byte aligned, one record per section:
    0x50 bytes: 8 floats (offset xyz, sphere radius, box) then 12 dwords:
        +0x20 material reference   +0x24 bone-palette pointer   +0x28 bone count
        +0x2C vertex-buffer pointer  ...  +0x34 vertex count  ...  +0x3C index-buffer pointer
        ...  +0x44 index count   +0x48 index size (2 or 4)   +0x4C schema pointer
    2 dwords: primitive type, unknown
    u16 bone palette x bone count, padded to 4 bytes (global skeleton indices, ascending)
    3 dwords: vertex stride, schema pointer, unknown
    vertex declaration: Direct3D 9 D3DVERTEXELEMENT9 records of 8 bytes
        (stream u16, offset u16, type u8, method u8, usage u8, usage index u8),
        ended by FF 00 00 00 11 00 00 00 (D3DDECL_END)
  external-mesh table (8 bytes per entry), at the very end of the IMG part
PHYS part: vertex buffers, then index buffers
```

Invariant used to validate the layout: `(index-buffer pointer - vertex-buffer pointer) in dwords =
vertex count * stride / 4`.

### Vertex layouts

Every vanilla section we measured is a triangle strip (primitive type 5) with 16-bit indices.

| Stride | Where | Layout (offset: content) |
|---|---|---|
| 52 | red and black suit bodies | 0 POSITION `SHORT4` · 8 TEXCOORD `SHORT2` · 12 COLOR `D3DCOLOR` · 16 NORMAL · 24 TANGENT · 32 BINORMAL (`SHORT4N` each) · 40 BLENDINDICES `UBYTE4` · 44 BLENDWEIGHT `SHORT4N` |
| 56 | some sections of the 001 models | the same with a second `SHORT2` texture coordinate at 12 (later fields shifted by 4) |
| 48 | Venom, the lens section of the red 001 | no COLOR: position, UV, normal, tangent, binormal, indices at 36, weights at 40 |
| 36 | static meshes | position, UV, normal, binormal, tangent |

Encodings:

- **position**: signed 16-bit integers **÷ 512** (the suit's vertex shader multiplies by
  0.00195312 = 1/512). The step is 1/512 whatever the size of the model: a model that is too small
  collapses (one of our test models kept 5.0 % of its points distinct, the vanilla model 89.6 %).
- **UV**: signed 16-bit integers **÷ 1000**, not 1024 (the vertex shader multiplies by 0.001;
  sections 0 and 1 of the vanilla model run from 12 to 990 and from 19 to 981, while other vanilla
  sections use other tiles of their textures). Textures wrap (address mode WRAP): a UV above 1000 shows the
  other side of the atlas. Only about 1000 positions per axis can be addressed, whatever the atlas
  size, hence SM3 Studio re-bakes the atlas on the rounded UVs.
- **normal, tangent, binormal**: `SHORT4N`. The engine lights with the **stored** normals; they do
  not follow the triangle winding (0.6 % agreement on the vanilla model).
- **bone indices**: `UBYTE4`, indices into the **section's palette**, up to 4 influences.
- **vertex colour**: `D3DCOLOR` stored B, G, R, A.

### Limits

- **65,535 vertices per section.** At upload (0x8CF1E0) the game creates one 16-bit index buffer per
  mesh and copies a section marked index size 4 keeping only the low word of each index (loop at
  0x8CF373): indices of 65,536 and above wrap, triangles join the wrong vertices, nothing reports
  it. A mesh can have many sections, and there is no limit on vertices per mesh.
- **Bones per section.** The 12 skinned vertex shaders of `Game.exe` declare `world` on registers
  c0..c191; the game's own suit has sections with 48 distinct bones; xeSM3 caps a section at 48.
  (The 2026-10-08 investigation read 3 registers per bone in the engine, i.e. 64 bones, so the 48
  cap is xeSM3's.) SM3 Studio uses 48. A whole body in one section needs about 52 bones, about 55
  with the 30 finger bones.
- An exporter can only **fill** the palette slots written in the file; a later re-skinning cannot
  add slots.

### The suit's meshes, measured (from their headers)

`ch_spiderman000` (`0xAC92103D`, skeleton reference 0x1730): 10 sections, 55,180 vertices, all stride
52.

| Section | Vertices | Bones in palette | Material reference |
|---|---|---|---|
| 0, 1 | 11,250 / 2,233 | 48 / 44 | 0x4E4 |
| 2 | 1,632 | 30 | 0x128 |
| 3 | 222 | 13 | 0x2BC |
| 4 | 1,167 | 9 | **0x614** (`spider`: the "canvas" section SM3 Studio's exporter builds on) |
| 5, 6 | 19,552 / 5,968 | 48 / 32 | 0x37C (`sideweb`) |
| 7, 8 | 9,147 / 3,937 | 48 / 41 | 0x640 (`topweb`) |
| 9 | 72 | 1 | 0xA0 (`white`, the lenses) |

Every vertex of 8 of the 10 sections has the colour `0,0,0,255` (29,674 vertices, including section
4); sections 5 and 6 carry other colours.

`ch_spiderman001` (`0xAC92103E`, skeleton reference 0x21C0): 6 sections, 5,660 vertices, strides 48,
56, 56, 52, 52, 52; materials 0x3CC (72 vertices, the lenses, class `sm_phatpalettecharnormal`),
0xCC ×2 (class `sm_decalchar`: a web **overlay**, not a surface — switching the body to it gave an
all-red character), 0x560 (player class, not tiled: the one SM3 Studio uses), 0x28 and 0x4B8 (player
class but tiled ×100: scales all over the body).

`ch_blacksuit000` (`0xABE79B1C`): 8 sections, 56,228 vertices; `ch_blacksuit001` (`0xABE79B1D`): 5
sections, 6,069 vertices. `ch_venom000` (`0xBF11C1BF`): 2 sections, 13,491 vertices, stride 48,
material 0x28C, 48-bone palettes.

**Material references are offsets in the mesh's own serialized data**, not global identifiers: the
same `topweb` material is 0x640 in `CH_SPIDERMAN`'s 000 and 0xB1C in `MARYJANE_SCARERIDE`'s, and
0x37C does not exist in the 001's address space.

**The 001 is in another frame:** `(x, y, z)₀₀₁ = (z, y + 1.199, −x)₀₀₀`, measured on three independent
models (vanilla bounds: 000 X −0.863..0.861, Y −1.197..0.953, Z −0.203..0.348; 001 X −0.203..0.348,
Y 0.002..2.152, Z −0.861..0.863). The map has determinant +1 (winding preserved); normals, tangents
and binormals take the rotation without the offset. For the black suit we measured the same kind of
transform (`profiles/blacksuit/frames.json`: identity for the 000; for the 001 a quarter turn and a
height offset of 1.198).

**External-mesh table:** the 000's header says 1 entry (+0x18) at the end of its IMG part (+0x1C);
the entry points at the `ch_spiderman001` object with the value 4.5 (*assumed:* the distance at which
the game switches models). The copy shipped with TSGAMING264's toolkit stops before those 8 bytes.

### Reference values SM3 Studio checks against (vanilla `ch_spiderman000`)

| Measure | Vanilla value | Used for |
|---|---|---|
| signed volume `Σ v0·(v1 × v2) / 6` | −0.116 (negative on everything that works) | winding check |
| mean `normal · (vertex − centre)` | +0.229 (positive = outward) | normal-direction check |
| arm angle in the bind pose (shoulder → hand) | −36.6° (an A-pose) | `redresser_bras.py` |
| width / height of the body | 0.81 (1.744 / 2.150) | "arms out of pose" below 85 % of it |
| share of vertices still distinct after ÷512 | 89.6 % | "crushed by quantisation" |
| vertices pulled by a left and a right bone at once | 0.23 % | "sides not mixed" check |
| largest hierarchy gap between two influences of a vertex | 5 | weights safeguard |
| 99th percentile of hand-edge stretch in a simulated fist | 1.55 | finger posing arbitration |
| surface shares of the 10 sections | 44.572, 26.558, 7.461, 6.918, 6.175, 3.340, 2.575, 1.331, 0.873, 0.197 % | decal thresholds (0.2 % and 1 %) |

## 5. Skeletons (`.skel`)

```
+0x00 name pointer (0xFC tag)   +0x04 name hash   +0x08 bone count   +0x0C unknown
+0x10 bone records, 0x90 bytes each:
   +0x00 4x4 floats   identity in every skeleton observed (runtime scratch)
   +0x40 4x4 floats   INVERSE BIND matrix, row-major, Direct3D row-vector convention
                      (rows 0-2 rotation, may include a uniform scale; row 3 translation;
                       column 3 is uninitialised padding: do not read it)
   +0x80 name pointer   +0x84 name hash   +0x88 parent index (-1 = root, always bone 0)   +0x8C 0
```

Bind position of a bone: `p = −(row_j · t) / |row_j|²` with `row_j` the rows of the rotation and `t`
the translation. Checked on 369 skeletons in 146 packs (23,407 bones, every name resolved;
orthonormality error at most 7.9e-05). Spider-Man's skeletons (000 and 001, red and black) have 75
bones (10,816 bytes); Venom's has 70. The game animates `v' = Σ animation[bone] · inverseBind[bone] ·
v`: a mesh in another pose than the skeleton's bind pose deforms (T-pose arms on an A-pose skeleton
give blade-like hands).

## 6. Textures (`.tex`)

```
68-byte header (0x44):
  dw0-1 0   dw2 name pointer   dw3 hash   dw4-5 0
  dw6 (+0x18) width   dw7 (+0x1C) height   dw8 (+0x20) depth (1)   dw9 (+0x24) mip count
  dw10 (+0x28) format: a FourCC 'DXT1' / 'DXT3' / 'DXT5', or a Direct3D format number
                (21 = A8R8G8B8, 50 = L8 seen on Venom's palette-index texture)
  dw11-16 0
then the pixels, mip 0 first, right at 0x44 (there is NO "PHYS" literal in between)
```

- Sizes per level: DXT1 8 bytes per 4×4 block (at least 8), DXT5 16 (at least 16), A8R8G8B8 4 bytes
  per pixel stored B, G, R, A. A full chain goes down to 1×1. Examples: a 4096 DXT5 atlas with all
  its mips is 22,369,716 bytes; ARGB8 4096 is 89,478,552; ARGB8 2048 is 22,369,688 (the same as
  DXT5 4096).
- Formats accepted by the game's mip-size routine (0x8DA790): 21, 22, 23, 32, 33 and DXT1 to DXT5.
  Textures up to 16384 are accepted by the engine.
- The example texture shipped with xeSM3 (`0xDEF62318.i_loading_screen_bkg.tex`, 1024 × 1024 DXT1)
  is exactly 0x44 + 1024 × 1024 / 2 = 524,356 bytes: the proof that the pixels start at 0x44.

### The normal map

The suit's pixel shader reads the normal map with the **raw** UVs (no tiling) and decodes
`nx = 2·alpha − 1`, `ny = 2·green − 1`: X lives in the **alpha** channel, Y in green, red and blue
are unused. In DXT1 the alpha is 255 everywhere, so `nx = +1` and the normal becomes the tangent
(88° off, measured): the normal map must be DXT5. A normal with `nx² + ny² > 1` gives a negative
square root and black pixels (DXT5 endpoints can overshoot the texels: always check after encoding).
Game normal maps are in DirectX convention (Blender expects OpenGL); detection: for an integrable
gradient field `corr(d(gy)/dx, d(gx)/dy) > 0` means DirectX.

### The texture slots SM3 Studio uses

| Hash | Name | In the vanilla game | SM3 Studio writes |
|---|---|---|---|
| `0x8E661B33` | `ch_spiderman_spider` | 128×128 DXT1, 1 mip (the emblem texture of material `0x614`) | the whole baked atlas, 2048-8192, full mip chain |
| `0x61DCA273` | `_normswizzle` | 32×32 DXT5, 6 mips, every texel identical (R 0, G 132, B 0, A 127): a **flat placeholder** shared by every suit material | a real baked normal map, DXT5 |
| `0x06F18556` | `_grey` | the diffuse that `sideweb` and `topweb` read | the atlas again, only with `--slot sideweb/topweb` |
| `0x0133FD92` | black suit atlas | 128×128 DXT1 | ARGB8 2048 (DXT cannot render near-blacks) |
| `0xA164D857`, `0xA164D85E` | Venom's palette index and palette | 2048×1024 L8 (11 mips) and 2×256 ARGB8 | an ARGB8 index texture and a palette made from the model |

## 7. Materials (`.mat`) and the suit's shine

Material classes (identified by the hash of their name, found with the hash rule):

| Class hash | Name | Record size | Used for |
|---|---|---|---|
| `0x99A1E0EC` | `sm_phat` | 0xA0 (160) | buildings, props, effects, interface |
| `0xA693F062` | `sm_phatpalettecharnormal` | 184 | characters |
| `0x64BDFE4A` | `sm_babyphat` | 136 | effects |
| `0xAB316696` | `sm_decalchar` | 44 | decals drawn over a character |
| `0x2B7A650F` | `sm_phatspiderman` | 168 | the player's suit |

Fields of the suit class (`sm_phatspiderman`) we use: the shine terms are (multiplier, constant)
pairs applied to the green channel of a map, `sat(map.G × mul + add)`:

| Field | Meaning |
|---|---|
| +0x14 | reference to a "cowbell" (resource type 68: animated material parameters, see below) |
| +0x50 / +0x54 | specular strength: `sat(spe.G × +0x50 + +0x54) × fresnel` |
| +0x58 / +0x5C | highlight size: `sat(exp.G × +0x58 + +0x5C) × 64` |
| +0x60 / +0x64 | environment reflection: `sat(rfl.G × +0x60 + +0x64) × fresnel` |
| +0x70 | 0 turns the hemispherical ambient **and** the rim light off |
| +0x80 | normal-map slot (every suit material points to `_normswizzle`) |
| +0x88 / +0x8C | tiling |

The four non-tiled materials of the 000 (values measured in the `.mat` files):

| Reference | Material | Shine | Highlight | Reflection | Ambient and rim | Diffuse |
|---|---|---|---|---|---|---|
| `0x614` | `spider` | 0.20 (fixed) | 13 | 0 | **off** | `ch_spiderman_spider` |
| `0x37C` | `sideweb` | 0 (matte) | — | 0 | on | `_grey` |
| `0x640` | `topweb` | 1.00 | 8 (wide) | green × 0.25 | on | `_grey` |
| `0x0A0` | `white` | 1.00 | 64 (tight) | its own reflection map | — | its own textures |

`spider` is the only one of the ten suit materials with +0x70 = 0: it is the emblem's material, which
the toolkit's exporter imposes on the converted body. With `spider` (and with the black suit's
`ch_blacksuitspider_black`), the specular and reflection *maps* are multiplied by zero (+0x50 and
+0x60 are 0): only the normal map still changes the shading.

**Cowbells.** A cowbell (type 68, referenced at +0x14) is evaluated at every draw and can replace the
whole parameter block; the red suit's material is driven by the `spiderman_spider` cowbell (specular
0.4 × spe.G, exponent 64 in its data). *Not confirmed in game:* whether the constants of the `.mat`
above are then overridden. This is why the Matte suit patches the **shader**, after every source of
shine, instead of the material.

## 8. Shaders inside `Game.exe`

`Game.exe` carries its 642 Direct3D 9 shaders in its read-only data; none is loaded from a file and
none is validated, so a same-size rewrite is accepted (*confirmed in game* by the Matte suit). The
suit's shaders are shader model 3.0 (`vs_3_0`, `ps_3_0`).

- **The suit's pixel shaders** (class `sm_phatspiderman`: red suit, black suit, Peter, cut-scene
  variants) are at file offsets **0x69EDF0, 0x6A04F8, 0x6A2918**. 0x6A2918 is the one whose samplers
  are exactly {0, 3, 4, 5, 6, 7, 8, 9} with the suit's names; with shadows on, 0x6A04F8 is the one
  drawn. Constant table of 0x6A2918: c0-c3 `special_effects_matrix` (the material's shine terms),
  c4-c19 four lights, c20-c23 `colorMatrix` (a global colour grading present in every shader, applied
  to the albedo), c24-c26 `local_to_world`, c27 `forcecolor`, c30 `UVScaleOffset`, c31 `fresnel`,
  c33 `rim_lighting`, c37 `exposure`, c38-c46 sky, sun, bounce and night terms. Output:
  `oC0.rgb = forcecolor + 1 − 2^(exposure · L)` with `exposure` = −2.0 (`exp` is base 2): a saturating
  tone map, so a light albedo quickly goes white. The colour, specular, exponent and reflectivity maps
  all read the same scaled UV; only the normal map uses the raw UV.
- **The suit's vertex shader** (file offset 0x6A19B0): `world` on c0..c191, positions × 1/512, UVs ×
  0.001. The vertex colour is tested as a flag (`sum of R, G, B` compared with 0): when it is not zero,
  a normal rebuilt from the colour is used instead of the stored one (our reading of the
  disassembly), hence black vertex colour on the converted suit.
- **The Matte suit patch** adds, after the shader's shine computation, `def c100` and one
  `mad_sat r3.yz, r3.yyzz, c100.xxzz, c100.yyww`: `final shine = sat(shine × Ks + As)`,
  `final reflection = sat(reflection × Ke + Ae)`. Opacity (read from another component at the end of
  the shader when the character fades out) is not touched: an earlier proposal that overwrote that
  component would have made Spider-Man invisible during fades (found by reading the shader, before
  any test). The room comes from the shader's constant-table comment ("Microsoft
  (R) HLSL Shader Compiler..."), never read by the game and shortened by 44 bytes.
- **Venom's shaders** (palette lookup): file offsets 0x6CB770, 0x6DD6E0, 0x6DF100, 0x6E05F0.

## 9. `Game.exe` facts

| Fact | Value |
|---|---|
| size of the retail PC `Game.exe` | 10,846,998 bytes |
| entry point | 0x9CEBE8 |
| index truncation at upload | 0x8CF1E0, loop at 0x8CF373 (see [Limits](#limits)) |
| APKF loader (relocation routine) | 0x9CB1A0 |
| texture mip-size routine | 0x8DA790 |
| recurring crash (not caused by mods) | 0x7C90F4 / 0x7C9105 (reported by Windows as offsets 0x3C90F4 / 0x3C9105), in a stream parser that checks a pointer for null but not against the end of its buffer; its only caller (0x7E05CD) handles the save data. 21 occurrences in the Windows event log of the development machine |

The game reads its saves from `Documents\Activision\Spider-Man 3\` (and a copy under
`AppData\Roaming\Activision\Spider-Man 3\`).

## Open questions

- Whether the cowbell overrides the `.mat` shine constants on the suit (no A/B test in game yet).
- The exact meaning of the 4.5 in the external-mesh table (switch distance is the likely reading).
- Several header fields are carried over unchanged without being understood: the 0x10-byte block
  after the mesh header, the unknown dwords of the section record, the skeleton header's +0x0C.
- Whether the 8192 atlas is fine in game (the engine accepts the size; we did not look).
- Other releases and language versions of the game: only one copy was measured.
