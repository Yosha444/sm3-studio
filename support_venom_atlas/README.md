# support_venom_atlas: suspended "direct" Venom pack patch (contents not published)

In earlier releases this folder held a complete, modified copy of the game's
`packs/STORY_MOVIE_4_PHASE3.PCPACK` (20 MB) and four validation reports. The pack is game data,
so it is not in this repository. This page explains what it was, why it is not rebuilt, and what
is left of it in the code.

## What it was (September 2026)

The "direct" Venom renderer (`renderer: spider_direct_v1`) wanted Venom to be drawn by the
Spider-Man character shader, so that a converted model could use a full-colour texture instead
of Venom's 256-colour palette. To do that it changed **82 bytes** of Venom's pack:

- Venom's material record (`ch_venom01_-_default.mat`, 184 bytes at offset 1,868,480): rewritten
  from a Spider-Man class material (shader class `0x2B7A650F`), keeping Venom's identity, with
  Venom's texture references moved into the slots that shader reads (albedo, normal map);
- 5 relocation entries of that material (each one is the dword index of a field of the material,
  `0x28C + field offset / 4`): moved to the new fields (+0x38 -> +0x80, +0x34 -> +0x24,
  +0x3C -> +0x84, +0x40 -> +0xA8, +0x28 -> +0xAC).

Measured on 2026-10-12: the shipped pack was exactly the original pack plus those 6 changes, and
nothing else (same size, 82 differing bytes).

## Why it is suspended, and not rebuilt

The patch was reported to crash the game: it was installed on 2026-09-08 at 20:34 and the
original pack was put back at 20:38 (`restoration_after_crash`). SM3 Studio has refused to
install "direct" mods ever since (`tools/venom_install.py`). Rebuilding the patched pack from the
player's own pack would be possible (the rules are above), but it would only rebuild something
that crashes the game, from a game resource rewritten by us. So the public version does not do it.

What Venom conversions use today is the **native** profile: Venom's own shader and material, the
original pack, and a 256-colour palette made from your model (`tools/venom_runner.py`,
`tools/venom_native_textures.py`). The later attempt to get full colour without touching the pack
is the draw adapter in `support_venom_direct/` (experimental, never seen working in game).

## What is left in the code

`tools/venom_shader_patch.json` lists, for the 6 changed ranges, their offsets and **sha256
fingerprints only**. `tools/venom_install.py` uses it to recognise a pack that still holds the
old patch (someone who installed a "direct" mod with a September build) and to put the original
bytes back before installing or when "Restore original Venom" is clicked. Those original bytes
come from the player's own files: the material from `profiles/venom/` (extracted from the
player's game) or from a pack backup in `<game>/SM3_Studio_Backups/`; the relocation entries are
recomputed. If neither source exists, the installer refuses and changes nothing.

Measured on copies (2026-10-12): for an original pack, a patched pack, a pack restored from a
backup, unknown packs and refused builds, the public `venom_install.py` leaves the game folder in
exactly the same state as the earlier version that shipped the original bytes.
