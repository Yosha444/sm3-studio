#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""Matte suit for Spider-Man 3 PC (2007): IN-PLACE patch of the 3 suit pixel shaders inside Game.exe.

    python costume_mat.py etat                        (or: status)   show the state, change nothing
    python costume_mat.py installer satine            (or: install)  presets: identite | mat | satine | attenue
    python costume_mat.py installer Ks As Ke Ae                      4 free values (e.g. 0 0.06 0 0)
    python costume_mat.py retirer                     (or: remove)   put the original shaders back
    options: --jeu "C:\\Games\\Spider-man 3"           (or --game)     game folder (default shown)
             --origine "path\\Game.exe.copy"           (or --original) INTACT copy of Game.exe, used to
                                                                     get the original shaders back if
                                                                     their backup is missing

The command words (etat / installer / retirer) and preset names are French because SM3 Studio
calls this script with them; the English words are accepted too.

WHY. The "oily" shine of Spider-Man's suit is computed by Game.exe itself (material + "cowbell"
animation + per-view factors), so no texture in a mod can change it. The game must be closed.
In the 3 pixel shaders of the sm_phatspiderman class (red suit, black suit, Peter, cut-scene
variants; in .rdata at file offsets 0x69EDF0, 0x6A04F8, 0x6A2918), right after the game's shine
computation, one instruction is added:
    final shine      = sat(game_shine      * Ks + As)        (then fresnel, as before)
    final reflection = sat(game_reflection * Ke + Ae)
Ks = 0: the game is ignored and As becomes OUR shine. Ks = 1, As = 0: nothing changes.
Opacity (character fades) is not touched. Same size: the "Microsoft (R) HLSL..." string of the
CTAB comment, never read by the game, is shortened by as much.

HOW. This script does not ship the patched shaders (they are mostly game bytecode). It ships a
RECIPE, costume_mat_shaders.json: "copy bytes a..b of the original shader, insert these bytes of
ours, put the 4 preset values here". The recipe is followed on the player's own Game.exe, only
after the shader there has been recognised as the original one (sha256 fingerprint), and the
result is checked against the fingerprint of the expected patched shader before anything is
written. costume_mat_make_recipe.py shows how the recipe was derived.

Before the very first write, the 3 original shaders are saved next to the game in
Game.exe.costume_mat_origine.bin: that file is what makes "remove" possible. Do not delete it.
Only these 3 zones are read and written: this patch coexists with the camera and swing patches.
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys

# Many names in this file are French, kept from the first version because SM3 Studio's interface
# calls them (etat_dossier, main, fmt, dossier_du_jeu, DOSSIER_DEFAUT) or reads its keys. Glossary:
# dossier = folder, jeu = game, etat = state, origine = original, patche = patched,
# inconnu = unknown, mixte = mixed, sauvegarde = backup, donnees = data, valeurs = values,
# refus = refusal, erreur = error, installer = install, retirer = remove, ecrire = write,
# lire = read, verifier = check, chercher = look for, absent(s) = missing.

DOSSIER_DEFAUT = r'C:\Games\Spider-man 3'         # default game folder (name kept: SM3 Studio reads it)
TAILLE_EXE = 10846998            # size of the original Game.exe of Spider-Man 3 PC (2007)
EP_RVA = 0x5CEBE8                # entry point (VA 0x9CEBE8)
IMAGE_BASE = 0x400000
SAUVEGARDE = 'Game.exe.sauvegarde_patchs_sm3'      # full copy made ONCE, before the first write
FICHIER_ORIGINE = 'Game.exe.costume_mat_origine.bin'
DONNEES = 'costume_mat_shaders.json'               # the recipe
MAGIQUE = b'SM3-COSTUME-MAT-ORIGINE 1\n'           # header of the backup file (format unchanged)
RECIPE_FORMAT, RECIPE_VERSION = 'sm3_costume_mat_recipe', 2
VALUES_SIZE = 16                                   # Ks As Ke Ae, 4 little-endian float32

PRESETS = {
    'identite': ((1.0, 0.0, 1.0, 0.0), 'identity: no visible change (test)'),
    'mat':      ((0.0, 0.0, 0.0, 0.0), 'matte: no shine, no reflection'),
    'satine':   ((0.0, 0.06, 0.0, 0.0), 'satin: slight constant sheen, no reflection (recommended)'),
    'attenue':  ((0.35, 0.0, 0.25, 0.0), 'softened: keeps the game\'s nuances, much gentler'),
}
ACTIONS = {'etat': 'etat', 'status': 'etat', 'installer': 'installer', 'install': 'installer',
           'retirer': 'retirer', 'remove': 'retirer'}

# Texts that SM3 Studio looks for in this script's output (sm3_gui_hq.py, costume_mat_lancer and
# costume_mat_bilan) to colour the Log and choose its message box. Change them together.
#   refused / error   start of the last line when nothing was written (exit 1) / after a write (exit 3)
#   nothing_to_do     start of the line printed when Game.exe was already in the requested state
#   write_denied      inside the refusal when Game.exe cannot be opened for writing
#   game_running      inside the refusal when the game is running
#   original_missing  inside the refusal when "retirer" cannot find the original shaders
MARKERS = dict(refused='REFUSED: ', error='ERROR: ', nothing_to_do='Nothing to do',
               write_denied='Write access denied', game_running='is running',
               original_missing='original version is not available')


class Refus(Exception):
    """Operation refused: nothing was written to Game.exe."""


class Erreur(Exception):
    """Problem found AFTER writing (read-back check)."""


# ----------------------------------------------------------------------------- common helpers

def dossier_du_jeu(arg):
    """Game folder from a folder or a path to Game.exe (default: DOSSIER_DEFAUT)."""
    p = (arg or DOSSIER_DEFAUT).strip().strip('"').strip()
    if os.path.isfile(p) and p.lower().endswith('.exe'):
        p = os.path.dirname(p)
    return os.path.abspath(p)


def jeu_en_cours(exe):
    """True if a Game.exe is running and we cannot prove it is not the one in this folder."""
    if os.name != 'nt':
        return False
    try:
        r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Game.exe', '/FO', 'CSV', '/NH'],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
        sortie = r.stdout.decode('ascii', 'replace').lower()
    except Exception:
        return False                      # cannot check: the write lock still protects the file
    n = sortie.count('"game.exe"')
    if n == 0:
        return False
    try:                                  # another game may also be called Game.exe: compare paths
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                            '(Get-Process -Name Game -ErrorAction SilentlyContinue | '
                            'ForEach-Object { $_.Path }) -join "|"'],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
        chemins = [c.strip() for c in r.stdout.decode('utf-8', 'replace').split('|') if c.strip()]
    except Exception:
        return True
    if len(chemins) < n:                  # path hidden (game started as administrator): be careful
        return True
    cible = os.path.normcase(os.path.abspath(exe))
    return any(os.path.normcase(os.path.abspath(c)) == cible for c in chemins)


def acces_ecriture(chemin):
    try:
        with open(chemin, 'r+b'):
            pass
    except PermissionError:
        raise Refus('Write access denied on %s.\n'
                    '  - if the game is running, close it completely;\n'
                    '  - if the game is installed under C:\\Program Files (x86), start the command prompt\n'
                    '    as administrator (right click > Run as administrator);\n'
                    '  - check that the file is not read-only (Properties).' % chemin)


def lire_pe(b):
    """Check that this is the expected Game.exe; return its section table."""
    if len(b) != TAILLE_EXE:
        raise Refus('Game.exe is %d bytes instead of %d: this is not the original Game.exe of '
                    'Spider-Man 3 PC (another version, or an exe modified or enlarged by another tool).'
                    % (len(b), TAILLE_EXE))
    if b[:2] != b'MZ':
        raise Refus('Game.exe is not a Windows executable (no MZ header).')
    pe = struct.unpack_from('<I', b, 0x3C)[0]
    if pe + 0x100 > len(b) or b[pe:pe + 4] != b'PE\0\0':
        raise Refus('Game.exe: PE header not found.')
    ep, base = struct.unpack_from('<I', b, pe + 0x28)[0], struct.unpack_from('<I', b, pe + 0x34)[0]
    if ep != EP_RVA or base != IMAGE_BASE:
        raise Refus('Game.exe: entry point 0x%X / base 0x%X instead of 0x%X / 0x%X: unknown version.'
                    % (ep + base, base, EP_RVA + IMAGE_BASE, IMAGE_BASE))
    nsec = struct.unpack_from('<H', b, pe + 6)[0]
    table = pe + 0x18 + struct.unpack_from('<H', b, pe + 0x14)[0]
    sections = []
    for i in range(nsec):
        vs, va, rs, raw = struct.unpack_from('<4I', b, table + 40 * i + 8)
        sections.append((va, vs, raw, rs))
    return sections


def sauvegarde_unique(exe):
    """Full copy of Game.exe, made only once (never overwritten)."""
    s = os.path.join(os.path.dirname(exe), SAUVEGARDE)
    if os.path.exists(s):
        return None
    shutil.copyfile(exe, s)
    if os.path.getsize(s) != os.path.getsize(exe):
        raise Refus('the backup copy %s is incomplete (disk full?): nothing was modified.' % s)
    return s


def ecrire_en_place(chemin, ecritures):
    with open(chemin, 'r+b') as f:
        for off, data in ecritures:
            f.seek(off)
            f.write(data)
        f.flush()
        os.fsync(f.fileno())


def octets_hors_zones(avant, apres, zones):
    """Positions where avant and apres differ outside the [start, end) intervals of zones."""
    hors, pas = [], 1 << 16
    for d in range(0, max(len(avant), len(apres)), pas):
        if avant[d:d + pas] != apres[d:d + pas]:
            for i in range(d, min(d + pas, max(len(avant), len(apres)))):
                if (avant[i:i + 1] != apres[i:i + 1]) and not any(a <= i < z for a, z in zones):
                    hors.append(i)
    return hors


def sha256(b):
    return hashlib.sha256(b).hexdigest()


# ----------------------------------------------------------------------------- the recipe

def apply_recipe(original, shader, values):
    """Build a patched shader from the ORIGINAL shader bytes by following the recipe's edit list.

    Edits, in order, each appending to the output:
      copy   start..end  bytes of the original shader
      insert hex         bytes of ours
      zeros  count       zero bytes
      values             the 4 float32 (Ks, As, Ke, Ae)
    The caller must have checked the original's fingerprint; the result is checked by
    patched_fingerprint_ok() before it is written anywhere.
    """
    out = bytearray()
    for e in shader['edits']:
        op = e['op']
        if op == 'copy':
            out += original[e['start']:e['end']]
        elif op == 'insert':
            out += bytes.fromhex(e['hex'])
        elif op == 'zeros':
            out += bytes(e['count'])
        elif op == 'values':
            out += struct.pack('<4f', *values)
        else:
            raise Refus('%s is damaged (unknown edit "%s" in shader %s).'
                        % (DONNEES, op, shader.get('nom', shader.get('name'))))
    return bytes(out)


def masque_valeurs(data, pos):
    """The shader with its 16 value bytes set to zero (what the patched fingerprint covers)."""
    m = bytearray(data)
    m[pos:pos + VALUES_SIZE] = bytes(VALUES_SIZE)
    return bytes(m)


def charger_donnees():
    """Read and sanity-check the recipe; return one dict per shader."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), DONNEES)
    if not os.path.isfile(p):
        raise Refus('data file %s not found: it must stay next to costume_mat.py.' % DONNEES)
    with open(p, encoding='utf-8') as f:
        d = json.load(f)
    if d.get('format') != RECIPE_FORMAT or d.get('version') != RECIPE_VERSION:
        raise Refus('%s is not a recipe this script understands (format %r, version %r).'
                    % (DONNEES, d.get('format'), d.get('version')))
    blobs = []
    for s in d['shaders']:
        # The edit list must rebuild exactly s['size'] bytes, with the values where announced.
        n, pos, ok = 0, None, True
        for e in s['edits']:
            if e['op'] == 'copy':
                ok &= 0 <= e['start'] <= e['end'] <= s['size']
                n += e['end'] - e['start']
            elif e['op'] == 'insert':
                n += len(bytes.fromhex(e['hex']))
            elif e['op'] == 'zeros':
                ok &= e['count'] >= 0
                n += e['count']
            elif e['op'] == 'values':
                ok &= pos is None and e.get('count', VALUES_SIZE) == VALUES_SIZE
                pos = n
                n += VALUES_SIZE
            else:
                ok = False
        if not ok or n != s['size'] or pos != s['values_position']:
            raise Refus('%s is damaged (edit list of shader %s).' % (DONNEES, s['name']))
        blobs.append(dict(nom=s['name'], off=s['offset'], n=s['size'], pos=pos,
                          sha_orig=s['sha256_original'], sha_patche=s['sha256_patched_without_values'],
                          edits=s['edits']))
    return blobs


def patched_fingerprint_ok(data, s):
    return len(data) == s['n'] and sha256(masque_valeurs(data, s['pos'])) == s['sha_patche']


def construire(cur, etat, s, vals):
    """The bytes to write for shader s, from its current bytes in Game.exe.

    original -> follow the recipe; already patched -> only the 16 value bytes change.
    Either way the result must match the patched fingerprint, or nothing is written."""
    if etat == 'origine':
        nouveau = apply_recipe(cur, s, vals)
    else:
        nouveau = bytearray(cur)
        struct.pack_into('<4f', nouveau, s['pos'], *vals)
        nouveau = bytes(nouveau)
    if not patched_fingerprint_ok(nouveau, s):
        raise Refus('the recipe %s did not rebuild the expected shader %s (damaged recipe?). '
                    'Nothing was written.' % (DONNEES, s['nom']))
    return nouveau


def etat_blob(b, s):
    """('origine'|'patche'|'inconnu', values or None) of shader s in the Game.exe bytes b."""
    cur = b[s['off']:s['off'] + s['n']]
    if sha256(cur) == s['sha_orig']:
        return 'origine', None
    if patched_fingerprint_ok(cur, s):
        return 'patche', struct.unpack_from('<4f', cur, s['pos'])
    return 'inconnu', None


def nom_valeurs(v):
    for nom, (p, _) in PRESETS.items():
        if struct.pack('<4f', *p) == struct.pack('<4f', *v):
            return 'preset "%s"' % nom
    return 'free values'


def fmt(v):
    return 'Ks=%g As=%g Ke=%g Ae=%g' % tuple(round(x, 6) for x in v)


# ----------------------------------------------------------------------------- original shaders

def lire_fichier_origine(chemin, blobs):
    """{offset: original bytes} read from Game.exe.costume_mat_origine.bin (checked entries only)."""
    if not os.path.isfile(chemin):
        return {}
    with open(chemin, 'rb') as f:
        d = f.read()
    try:
        if not d.startswith(MAGIQUE):
            raise ValueError
        fin = d.index(b'\n', len(MAGIQUE))
        entete = json.loads(d[len(MAGIQUE):fin].decode('utf-8'))
        pos, res = fin + 1, {}
        attendus = {s['off']: s for s in blobs}
        for e in entete['blobs']:
            data = d[pos:pos + e['taille']]
            pos += e['taille']
            s = attendus.get(e['offset'])
            if s and len(data) == s['n'] and sha256(data) == s['sha_orig']:
                res[s['off']] = data
        return res
    except Exception:
        print('  WARNING: %s is unreadable or damaged: it is ignored.' % chemin)
        return {}


def ecrire_fichier_origine(chemin, originaux, blobs):
    # The keys of this small header are French; they are kept so that backups made by earlier
    # versions stay readable, and backups made now stay readable by earlier versions.
    ordre = [s for s in blobs if s['off'] in originaux]
    entete = dict(format='sm3_costume_mat_origine', version=1,
                  note='Original suit shaders, saved by costume_mat.py before patching. '
                       'Needed for "costume_mat.py retirer" (remove). Do not delete.',
                  blobs=[dict(nom=s['nom'], offset=s['off'], taille=s['n'], sha256=s['sha_orig']) for s in ordre])
    data = MAGIQUE + json.dumps(entete, ensure_ascii=True).encode('ascii') + b'\n' + \
        b''.join(originaux[s['off']] for s in ordre)
    tmp = chemin + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, chemin)
    if lire_fichier_origine(chemin, blobs) != {s['off']: originaux[s['off']] for s in ordre}:
        raise Refus('the backup of the original shaders (%s) could not be read back: nothing was modified.' % chemin)


def chercher_originaux(dossier, exe, blobs, manquants, source):
    """Look for the missing original shaders in --origine, then in the Game.exe.* copies of the folder."""
    candidats = []
    if source:
        source = source.strip().strip('"')
        if not os.path.isfile(source):
            raise Refus('--origine: file not found: %s' % source)
        candidats.append(source)
    try:
        for nom in sorted(os.listdir(dossier)):
            p = os.path.join(dossier, nom)
            if (nom.lower().startswith('game.exe') and os.path.isfile(p) and nom.lower() != 'game.exe'
                    and not nom.lower().startswith(FICHIER_ORIGINE.lower())
                    and os.path.getsize(p) == TAILLE_EXE):
                candidats.append(p)
    except OSError:
        pass
    trouves = {}
    for c in candidats:
        if os.path.normcase(os.path.abspath(c)) == os.path.normcase(os.path.abspath(exe)):
            continue
        try:
            with open(c, 'rb') as f:
                for s in blobs:
                    if s['off'] in manquants and s['off'] not in trouves:
                        f.seek(s['off'])
                        data = f.read(s['n'])
                        if sha256(data) == s['sha_orig']:
                            trouves[s['off']] = data
                            print('  original shader %s found in %s' % (s['nom'], c))
        except OSError:
            continue
    if source and not trouves:
        print('  WARNING: %s does not contain the expected original shaders (copy already patched?).' % source)
    return trouves


# ----------------------------------------------------------------------------- actions

def analyser(exe, blobs):
    b = open(exe, 'rb').read()
    lire_pe(b)
    return b, [(s,) + etat_blob(b, s) for s in blobs]


ETATS_AFFICHES = {'origine': 'original', 'patche': 'patched', 'inconnu': 'UNKNOWN'}


def afficher(etats):
    for s, e, v in etats:
        print('    shader %s (offset 0x%X, %d bytes): %s%s'
              % (s['nom'], s['off'], s['n'], ETATS_AFFICHES[e],
                 '' if v is None else '  %s  (%s)' % (fmt(v), nom_valeurs(v))))


def controler_inconnus(etats, action):
    mauvais = [s['nom'] for s, e, _ in etats if e == 'inconnu']
    if mauvais:
        raise Refus('%s impossible: shader(s) %s are neither original nor patched by this script '
                    '(another modification of Game.exe?). Nothing was written.' % (action, ', '.join(mauvais)))


def installer(dossier, exe, blobs, vals, source):
    b, etats = analyser(exe, blobs)
    controler_inconnus(etats, 'Installation')
    chemin_orig = os.path.join(dossier, FICHIER_ORIGINE)
    originaux = lire_fichier_origine(chemin_orig, blobs)
    connus = dict(originaux)
    for s, e, _ in etats:
        if e == 'origine':
            connus[s['off']] = bytes(b[s['off']:s['off'] + s['n']])
    manquants = [s['off'] for s in blobs if s['off'] not in connus]
    if manquants:
        connus.update(chercher_originaux(dossier, exe, blobs, manquants, source))
    cibles = [(s, construire(b[s['off']:s['off'] + s['n']], e, s, vals)) for s, e, _ in etats]
    ecritures = [(s['off'], n) for s, n in cibles if b[s['off']:s['off'] + s['n']] != n]
    a_sauver = set(connus) - set(originaux)
    if not ecritures:
        print('Nothing to do: the 3 shaders are already at %s.' % fmt(vals))
    if ecritures or a_sauver:
        acces_ecriture(exe)
    if a_sauver:                              # back the originals up BEFORE any write to the exe
        ecrire_fichier_origine(chemin_orig, connus, blobs)
        print('Original shaders saved (%d/3): %s' % (len(connus), chemin_orig))
    absents = [s['nom'] for s in blobs if s['off'] not in connus]
    if absents:
        print('WARNING: the original shaders %s are not available anywhere (Game.exe was already\n'
              '  patched before this script). Changing the setting works, but "retirer" (remove) will\n'
              '  need an intact copy of Game.exe:  --origine "path\\to\\original Game.exe".' % ', '.join(absents))
    if not ecritures:
        return
    s = sauvegarde_unique(exe)
    if s:
        print('Safety copy of Game.exe (made only once):', s)
    ecrire_en_place(exe, ecritures)
    verifier(exe, b, blobs, {s['off']: n for s, n in cibles})
    print('%d shader(s) written, read back and checked: %s (%s).' % (len(ecritures), fmt(vals), nom_valeurs(vals)))


def retirer(dossier, exe, blobs, source):
    b, etats = analyser(exe, blobs)
    controler_inconnus(etats, 'Removal')
    a_remettre = [s for s, e, _ in etats if e == 'patche']
    if not a_remettre:
        print('Nothing to do: the 3 suit shaders are already original.')
        return
    chemin_orig = os.path.join(dossier, FICHIER_ORIGINE)
    originaux = lire_fichier_origine(chemin_orig, blobs)
    manquants = [s['off'] for s in a_remettre if s['off'] not in originaux]
    if manquants:
        originaux.update(chercher_originaux(dossier, exe, blobs, manquants, source))
    absents = [s['nom'] for s in a_remettre if s['off'] not in originaux]
    if absents:
        raise Refus('cannot put back shader(s) %s: their original version is not available.\n'
                    '  The file %s (created by this script before its first write) is missing or\n'
                    '  incomplete: Game.exe was probably patched by another tool or an earlier\n'
                    '  version. Solutions:\n'
                    '   1) python costume_mat.py retirer --origine "path\\to\\an intact copy of Game.exe"\n'
                    '   2) or reinstall the original Game.exe (CD / backup), then reapply the other\n'
                    '      patches you want (camera: python camera_rapprochee.py installer proto).\n'
                    'Nothing was written.' % (', '.join(absents), FICHIER_ORIGINE))
    acces_ecriture(exe)
    s = sauvegarde_unique(exe)
    if s:
        print('Safety copy of Game.exe (made only once):', s)
    ecritures = [(s['off'], originaux[s['off']]) for s in a_remettre]
    ecrire_en_place(exe, ecritures)
    attendu = {s['off']: bytes(b[s['off']:s['off'] + s['n']]) for s in blobs}
    attendu.update(dict(ecritures))
    verifier(exe, b, blobs, attendu)
    print('%d suit shader(s) put back to original, read back and checked (original sha256 fingerprints).'
          % len(ecritures))


def verifier(exe, avant, blobs, attendu):
    relu = open(exe, 'rb').read()
    if len(relu) != len(avant):
        raise Erreur('the size of Game.exe changed! Put the copy %s back.' % SAUVEGARDE)
    for s in blobs:
        if relu[s['off']:s['off'] + s['n']] != attendu[s['off']]:
            raise Erreur('wrong read-back of shader %s. Run the command again; as a last resort, '
                         'put the copy %s back.' % (s['nom'], SAUVEGARDE))
    hors = octets_hors_zones(avant, relu, [(s['off'], s['off'] + s['n']) for s in blobs])
    if hors:
        raise Erreur('%d byte(s) modified outside the shaders! Put the copy %s back.' % (len(hors), SAUVEGARDE))


def lire_valeurs(args):
    if len(args) == 1:
        p = args[0].lower()
        if p not in PRESETS:
            raise Refus('unknown preset "%s". Presets: %s; or 4 values Ks As Ke Ae.' % (args[0], ', '.join(PRESETS)))
        return PRESETS[p][0]
    if len(args) == 4:
        try:
            vals = tuple(float(x.replace(',', '.')) for x in args)
        except ValueError:
            raise Refus('unreadable values: %s (expected 4 numbers, e.g. 0 0.06 0 0).' % ' '.join(args))
        if not all(math.isfinite(v) and abs(v) <= 64 for v in vals):
            raise Refus('values out of range (each value must be between -64 and 64).')
        return vals
    raise Refus('give a preset (%s) or 4 values Ks As Ke Ae.' % ', '.join(PRESETS))


def main(argv=None):
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        prog='costume_mat.py',
        description='Matte suit for Spider-Man 3 PC: in-place patch of the suit shaders (game closed).',
        epilog='presets: ' + ' | '.join('%s = %s (%s)' % (n, fmt(v), t) for n, (v, t) in PRESETS.items()))
    ap.add_argument('action', nargs='?', default='etat', choices=list(ACTIONS))
    ap.add_argument('valeurs', nargs='*', help='preset, or Ks As Ke Ae')
    ap.add_argument('--jeu', '--game', dest='jeu', help='game folder (default: %s)' % DOSSIER_DEFAUT)
    ap.add_argument('--origine', '--original', dest='origine',
                    help='intact copy of Game.exe (if the backup of the original shaders is missing)')
    a = ap.parse_args(argv)
    action = ACTIONS[a.action]
    dossier = dossier_du_jeu(a.jeu)
    exe = os.path.join(dossier, 'Game.exe')
    try:
        blobs = charger_donnees()
        if not os.path.isfile(exe):
            raise Refus('Game.exe not found in "%s". Give the game folder with --jeu "path".' % dossier)
        print('Game.exe: %s' % exe)
        if action == 'etat':
            b, etats = analyser(exe, blobs)
            print('  recognised version (10 846 998 bytes, entry point 0x9CEBE8)')
            afficher(etats)
            originaux = lire_fichier_origine(os.path.join(dossier, FICHIER_ORIGINE), blobs)
            for s, e, _ in etats:
                if e == 'origine':
                    originaux[s['off']] = True
            print('  backup of the original shaders (%s): %s' % (
                FICHIER_ORIGINE, 'present' if os.path.isfile(os.path.join(dossier, FICHIER_ORIGINE)) else 'absent'))
            print('  "retirer" (remove) possible: %s' % ('yes' if len(originaux) == len(blobs) else
                                                       'NO without --origine (original shaders not found)'))
            return 0
        if jeu_en_cours(exe):
            raise Refus('The game (Game.exe) is running: close it first.')
        if action == 'installer':
            vals = lire_valeurs(a.valeurs)
            print('Installation: %s (%s)' % (fmt(vals), nom_valeurs(vals)))
            installer(dossier, exe, blobs, vals, a.origine)
        else:
            if a.valeurs:
                raise Refus('"retirer" (remove) takes no value.')
            print('Removing the matte suit patch (the 3 shaders get their original version back).')
            retirer(dossier, exe, blobs, a.origine)
        return 0
    except Refus as e:
        print(MARKERS['refused'] + str(e))
        return 1
    except Erreur as e:
        print(MARKERS['error'] + str(e))
        return 3


# ----------------------------------------------------------------------------- API (SM3 Studio)
# Used by the "Matte suit" box of SM3 Studio. The GUI READS the state with etat_dossier() and
# WRITES only through main(['installer', preset, '--jeu', folder]) or main(['retirer', '--jeu',
# folder, ...]), so with exactly the checks, backups and messages of the command line.

def etat_dossier(jeu, chercher=False):
    """Read-only look at the Game.exe of the game folder: nothing is written.

    Returns a dict:
      etat       'absent' | 'non_reconnu' | 'inconnu' | 'origine' | 'patche' | 'mixte'
                 (absent: no Game.exe; non_reconnu: another version of Game.exe; inconnu: shaders
                 modified by another tool; origine: original; patche: patched; mixte: some of the
                 3 shaders patched, the others original)
      preset     preset name if the 3 shaders are patched with a preset's values, else None
      valeurs    (Ks, As, Ke, Ae) if the patched shaders all have the same values, else None
      retirable  True if "retirer" will find the original shaders without --origine: in
                 Game.exe.costume_mat_origine.bin, and with chercher=True also in the
                 Game.exe.* copies of the folder (as "retirer" does)
      dossier, exe, detail (the reason, for non_reconnu and inconnu)
    The keys and state names are French because SM3 Studio's interface reads them.
    """
    dossier = dossier_du_jeu(jeu)
    exe = os.path.join(dossier, 'Game.exe')
    res = dict(etat='absent', preset=None, valeurs=None, retirable=True, dossier=dossier, exe=exe,
               detail='')
    if not os.path.isfile(exe):
        return res
    blobs = charger_donnees()
    try:
        _, etats = analyser(exe, blobs)
    except Refus as e:
        res.update(etat='non_reconnu', detail=str(e))
        return res
    try:
        controler_inconnus(etats, 'Installation or removal')
    except Refus as e:
        res.update(etat='inconnu', detail=str(e))
        return res
    patches = [(s, v) for s, e, v in etats if e == 'patche']
    if not patches:
        res['etat'] = 'origine'
        return res
    res['etat'] = 'patche' if len(patches) == len(etats) else 'mixte'
    paquets = {struct.pack('<4f', *v) for _, v in patches}
    if len(paquets) == 1:
        res['valeurs'] = patches[0][1]
        if res['etat'] == 'patche':
            res['preset'] = next((n for n, (p, _) in PRESETS.items()
                                  if struct.pack('<4f', *p) in paquets), None)
    originaux = lire_fichier_origine(os.path.join(dossier, FICHIER_ORIGINE), blobs)
    manquants = [s['off'] for s, _ in patches if s['off'] not in originaux]
    if manquants and chercher:
        trouves = chercher_originaux(dossier, exe, blobs, manquants, None)
        manquants = [m for m in manquants if m not in trouves]
    res['retirable'] = not manquants
    return res


if __name__ == '__main__':
    sys.exit(main())
