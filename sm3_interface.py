# SPDX-License-Identifier: GPL-3.0-or-later
"""sm3_interface.py - the main SM3 Studio window (the "legacy" interface).

This is the window every SM3 Studio build has shown since 2026-09-09: source model, texture
assignment, pose and skinning settings, paths, live conversion log and preview. Everything the
command-line converter (sm3_convertir.py) can do is exposed here, with defaults calibrated on the
vanilla Spider-Man model and every manual setting visible.

Blender is still required for ONE stage, baking the texture atlas: it cannot be embedded in the
executable. Its path is a setting; everything else runs inside SM3 Studio.exe.

How this file is used
---------------------
* Normal start: sm3_studio_hq.py (also the entry point of SM3 Studio.exe) compiles this file,
  translates it to English if the user chose English, runs it, and then sm3_gui_hq.py replaces or
  wraps several methods of `Studio` (quality panel, target character, Venom, Black Suit, matte
  suit). Methods affected are marked "Replaced by sm3_gui_hq" or "Wrapped by sm3_gui_hq" below.
* `python sm3_interface.py` with no argument opens this bare window, without the HQ additions.
* `python sm3_interface.py --nom MyMod --src model.glb ...` converts without any window
  (see `_sans_fenetre`).

Where this file comes from
--------------------------
Until 2026-10-12 this window was only distributed as a marshalled code object
(sm3_studio_original.marshal) loaded by the executable. This source is the developers' last copy
of it, minus the "Remettre d'aplomb" (auto-orient) option that had been removed before the
bytecode was produced. Compiled with Python 3.14 it gives the same code objects as that bytecode
(same instructions, constants, names and variables; only line numbers, comments and docstrings
differ). construire/README.md explains the check and how to repeat it.

Why the visible strings are in French
-------------------------------------
The interface was written in French. English is produced at run time by
studio_language.localize(), which walks the compiled code object and replaces every string
constant listed in studio_language.EN. So, when editing this file:
  * keep each message ONE literal string, or it cannot be translated. Python 3.14 compiles
    '%s ... %s' % (a, b) into separate fragments (measured with dis); '...%d...' % x, a single
    '%s' % x, or '...'.format() keep the whole message as one constant;
  * never add to studio_language.EN a string that is also used as an internal value (stage names
    such as 'chaine' or 'poids', JSON keys, command-line options): localize() would translate the
    value too and the program logic would no longer recognise it.

Glossary of the French identifiers (kept unchanged so nothing that refers to them breaks)
-----------------------------------------------------------------------------------------
    Tuyau = pipe              fil = queue (the "wire" between threads)   travail = worker thread
    onglet = tab              chemin = path        racine = project root folder
    reglages = settings       modele = 3D model    cuisson = atlas baking (Blender)
    apercu = preview          vue = view           journal = log
    convertir = convert       installer = install  ouvrir = open        deviner = guess
    analyser = analyse        apparier = match textures to materials
    charger / sauver = load / save the settings    sans_fenetre = without a window
    poids = skinning weights  voisins = neighbours fondu (a l'epaule) = (shoulder) blend
    echelle = scale           decalage = offset    poser au sol = put on the ground
    jeter = drop              aide = help text     libelle = label      cle = key
    ICI = "here" (folder of this file, or of the .exe when frozen)
    BASE = folder holding the bundled Python modules (sys._MEIPASS inside the .exe)
    RACINE_DEFAUT = default project folder (vanilla\\, tools\\, mods\\, build\\)

    python sm3_interface.py            (or start SM3 Studio.exe)
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# Where things are. When frozen by PyInstaller, sys.executable is SM3 Studio.exe: its folder is the
# project folder, and the bundled .py modules are unpacked to sys._MEIPASS. When run from source,
# the bundled modules are next to this file, and the default project folder is this same folder
# when tools\ sits next to it (the repository layout), else its PARENT directory (the layout of
# the original development tree). The "racine" setting in sm3_studio.json, or the Paths tab,
# overrides that default.
ICI = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
if getattr(sys, 'frozen', False):
    BASE = getattr(sys, '_MEIPASS', ICI)
    RACINE_DEFAUT = ICI
else:
    BASE = ICI
    RACINE_DEFAUT = ICI if os.path.isdir(os.path.join(ICI, 'tools')) else os.path.dirname(ICI)
sys.path.insert(0, BASE)

# Every field of the window is saved here when a conversion starts and when the window closes.
REGLAGES = os.path.join(ICI, 'sm3_studio.json')

# File-dialog filter for source models. Archives are accepted because sm3_convertir.py unpacks
# them and looks for the model inside (.zip natively, .rar and .7z through an installed 7-Zip).
FORMATS_MODELE = [('Modeles 3D et archives',
                   '*.gltf *.glb *.fbx *.obj *.dae *.ply *.stl *.x3d *.abc *.usd *.usda *.usdc '
                   '*.blend *.zip *.rar *.7z'), ('Tous les fichiers', '*.*')]


# --------------------------------------------------------------------------- log
# The conversion runs in a worker thread, but Tk widgets may only be touched from the main thread.
# Tuyau is installed as sys.stdout/sys.stderr during a conversion: every complete line printed by
# the converter (or by any tool it calls) is put on a queue, and Studio._vider_fil, running in the
# Tk main loop, moves the queued lines into the log widget every 60 ms.
class Tuyau:
    """Redirect print() to the window without blocking the worker thread."""

    def __init__(self, fil):
        self.fil = fil
        self.reste = ''

    def write(self, txt):
        # Only whole lines are sent; an unfinished line waits in self.reste.
        self.reste += txt
        while '\n' in self.reste:
            ligne, self.reste = self.reste.split('\n', 1)
            self.fil.put(ligne)

    def flush(self):
        if self.reste:
            self.fil.put(self.reste)
            self.reste = ''


# The main window. self.v maps a setting name to its Tk variable: it is the single place where
# the values of every field live, what _args turns into command-line options, and what _sauver
# writes to sm3_studio.json.
class Studio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('SM3 Studio — convertir un modele pour Spider-Man 3')
        self.geometry('1120x760')
        self.minsize(940, 640)
        self.fil = queue.Queue()
        self.travail = None
        self.v = {}
        self._construire()
        self._charger()
        self.after(60, self._vider_fil)

    # ---------------------------------------------------------------- building the window
    def _construire(self):
        """Build every widget: model box, settings tabs, buttons, log and preview tabs."""
        st = ttk.Style(self)
        try:
            st.theme_use('vista')
        except Exception:
            pass   # the 'vista' theme only exists on Windows; keep Tk's default elsewhere

        haut = ttk.LabelFrame(self, text=' Modele ', padding=10)
        haut.pack(fill='x', padx=10, pady=(10, 6))
        haut.columnconfigure(1, weight=1)

        self._ligne_fichier(haut, 0, 'Modele source', 'src',
                            'gltf glb fbx obj dae ply stl usd blend, ou une archive zip rar 7z',
                            self._choisir_modele)
        self._ligne_fichier(haut, 2, 'Dossier des textures', 'textures',
                            'vide = detection automatique', self._choisir_textures, dossier=True)

        f = ttk.Frame(haut)
        f.grid(row=4, column=0, columnspan=3, sticky='we', pady=(8, 0))
        ttk.Label(f, text='Nom du mod').pack(side='left')
        self.v['nom'] = tk.StringVar(value='MonMod')
        ttk.Entry(f, textvariable=self.v['nom'], width=26).pack(side='left', padx=(8, 20))
        # Resume from stage: the converter keeps every intermediate file in build\<mod name>\, so a
        # later stage can be re-run alone. These values are the converter's internal stage names
        # (sm3_convertir.ETAPES), which is why they are never translated.
        ttk.Label(f, text='Reprendre a l etape').pack(side='left')
        self.v['depuis'] = tk.StringVar(value='chaine')
        ttk.Combobox(f, textvariable=self.v['depuis'], width=12, state='readonly',
                     values=['chaine', 'ajuster', 'bras', 'poids', 'lod', 'atlas',
                             'verifier', 'assembler']).pack(side='left', padx=8)
        ttk.Label(f, text='(seule « chaine » est lente : c est la cuisson)',
                  foreground='#666').pack(side='left', padx=6)

        # ---- settings tabs
        onglets = ttk.Notebook(self)
        onglets.pack(fill='x', padx=10, pady=6)
        self._onglet_general(onglets)
        self._onglet_textures(onglets)
        self._onglet_pose(onglets)
        self._onglet_skinning(onglets)
        self._onglet_chemins(onglets)

        # ---- buttons
        b = ttk.Frame(self)
        b.pack(fill='x', padx=10, pady=(2, 6))
        self.bt_convertir = ttk.Button(b, text='  Convertir  ', command=self.convertir)
        self.bt_convertir.pack(side='left')
        ttk.Button(b, text='Verifier seulement', command=lambda: self.convertir('verifier')
                   ).pack(side='left', padx=6)
        ttk.Button(b, text='Installer et lancer le jeu', command=self.installer).pack(side='left')
        ttk.Button(b, text='Ouvrir le dossier du mod', command=self.ouvrir).pack(side='left', padx=6)
        self.etat = ttk.Label(b, text='pret', foreground='#0a0')
        self.etat.pack(side='right')

        # ---- bottom: log and preview
        bas = ttk.Notebook(self)
        bas.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        j = ttk.Frame(bas, padding=6)
        bas.add(j, text='  Journal  ')
        self.txt = tk.Text(j, wrap='none', bg='#111418', fg='#d8dee9',
                           insertbackground='#d8dee9', font=('Consolas', 9), relief='flat')
        sy = ttk.Scrollbar(j, orient='vertical', command=self.txt.yview)
        self.txt.configure(yscrollcommand=sy.set)
        sy.pack(side='right', fill='y')
        self.txt.pack(fill='both', expand=True)
        # Colour tags used by _vider_fil: passed checks, errors, section titles, details.
        for nom, coul in (('ok', '#7ec97e'), ('ko', '#ff7b72'), ('titre', '#79c0ff'),
                          ('gris', '#8b949e')):
            self.txt.tag_configure(nom, foreground=coul)

        self._onglet_apercu(bas)
        self.onglets_bas = bas

    def _onglet_apercu(self, nb):
        """Preview tab: look at the built model without leaving the window.

        It is the one check the converter's twelve measurements cannot give: they say the file
        is valid, not that the character looks right. The render goes through Blender, like the
        atlas baking."""
        p = ttk.Frame(nb, padding=6)
        nb.add(p, text='  Apercu  ')
        barre = ttk.Frame(p)
        barre.pack(fill='x', pady=(0, 6))
        ttk.Button(barre, text='Rendre l apercu', command=self.rendre_apercu).pack(side='left')
        # (label, value): the value is part of the render file name, render_<value>.png.
        self.v['vue'] = tk.StringVar(value='face')
        for lib, val in (('face', 'face'), ('dos', 'dos'), ('trois quarts', 'trois_quarts'),
                         ('atlas', 'atlas')):
            ttk.Radiobutton(barre, text=lib, value=val, variable=self.v['vue'],
                            command=self._montrer_vue).pack(side='left', padx=4)
        self._num_inline(barre, 'zoom', 'zoom', 1.0)
        self.lab_apercu = ttk.Label(barre, text='', foreground='#666')
        self.lab_apercu.pack(side='right')
        self.toile = tk.Label(p, background='#2b2f36')
        self.toile.pack(fill='both', expand=True)
        self._image = None   # keeps a reference to the PhotoImage, or Tk would show nothing

    def _num_inline(self, parent, libelle, cle, defaut):
        """Label + small entry packed on the same row (used for the preview zoom)."""
        ttk.Label(parent, text=libelle).pack(side='left', padx=(16, 4))
        self.v[cle] = tk.StringVar(value=str(defaut))
        ttk.Entry(parent, textvariable=self.v[cle], width=6).pack(side='left')

    def rendre_apercu(self):
        """Render the built mod offline in Blender (tools/render_mesh.py), then display it.

        Wrapped by sm3_gui_hq: Venom targets show their own preview image instead."""
        out = os.path.join(self.v['racine'].get(), 'build', self.v['nom'].get().strip().lower())
        # The file that will go into the game (hashed name of ch_spiderman000.mesh): the preview
        # decodes the delivered bytes, not an intermediate Blender object.
        mesh = os.path.join(out, '0xAC92103D.ch_spiderman000.mesh')
        atlas = os.path.join(out, 'atlas_dilate.png')
        rm = os.path.join(self.v['racine'].get(), 'tools', 'render_mesh.py')
        if not os.path.exists(mesh):
            messagebox.showinfo('SM3 Studio', 'Rien a montrer : construis le mod d abord.\n%s' % mesh)
            return
        if not os.path.exists(self.v['blender'].get()) or not os.path.exists(rm):
            messagebox.showwarning('SM3 Studio', 'blender.exe ou tools\\render_mesh.py introuvable.')
            return
        self.lab_apercu.configure(text='rendu en cours...')
        self.update_idletasks()

        def travail():
            # Runs in a background thread. Note: render_mesh.py treats --out as a FOLDER, so the
            # renders end up in build\<mod>\apercu.png\render_<view>.png (see _montrer_vue).
            cmd = [self.v['blender'].get(), '-b', '--python', rm, '--',
                   '--mesh', mesh, '--out', os.path.join(out, 'apercu.png'),
                   '--zoom', self.v['zoom'].get() or '1']
            if os.path.exists(atlas):
                cmd += ['--atlas', atlas]
            subprocess.run(cmd, capture_output=True, text=True, errors='replace')
            # Tell the main thread the render is done (handled in _vider_fil).
            self.fil.put(('__apercu__', out))

        threading.Thread(target=travail, daemon=True).start()

    def _montrer_vue(self):
        """Show the selected view (or the atlas) scaled to the preview area."""
        out = os.path.join(self.v['racine'].get(), 'build', self.v['nom'].get().strip().lower())
        vue = self.v['vue'].get()
        chemin = (os.path.join(out, 'atlas_dilate.png') if vue == 'atlas'
                  else os.path.join(out, 'apercu.png', 'render_%s.png' % vue))
        if not os.path.exists(chemin):
            self.lab_apercu.configure(text='pas encore rendu')
            self.toile.configure(image='', text='—')
            return
        try:
            # Pillow is imported here, not at the top: the rest of the window works without it.
            from PIL import Image, ImageTk
            im = Image.open(chemin)
            lm = max(self.toile.winfo_width(), 400), max(self.toile.winfo_height(), 300)
            im.thumbnail(lm, Image.LANCZOS)
            self._image = ImageTk.PhotoImage(im)
            self.toile.configure(image=self._image, text='')
            self.lab_apercu.configure(text='%s — %s' % (vue, os.path.basename(chemin)))
        except Exception as e:
            self.lab_apercu.configure(text='affichage impossible : %s' % e)

    def _ligne_fichier(self, parent, r, libelle, cle, aide, cmd, dossier=False):
        """Label + entry + Browse button on grid row r, help text on row r + 1."""
        ttk.Label(parent, text=libelle).grid(row=r, column=0, sticky='w', pady=3)
        self.v[cle] = tk.StringVar()
        e = ttk.Entry(parent, textvariable=self.v[cle])
        e.grid(row=r, column=1, sticky='we', padx=8)
        ttk.Button(parent, text='Parcourir', command=cmd).grid(row=r, column=2)
        # The help text goes on ITS OWN row: placed on the same row with a pady, it overlapped
        # the next row.
        ttk.Label(parent, text=aide, foreground='#666').grid(row=r + 1, column=1, sticky='w',
                                                             padx=8, pady=(0, 4))

    def _num(self, parent, libelle, cle, defaut, largeur=8, aide=''):
        """One settings row: fixed-width label, entry bound to self.v[cle], optional grey help."""
        f = ttk.Frame(parent)
        f.pack(fill='x', pady=2)
        ttk.Label(f, text=libelle, width=22).pack(side='left')
        self.v[cle] = tk.StringVar(value=str(defaut))
        ttk.Entry(f, textvariable=self.v[cle], width=largeur).pack(side='left')
        if aide:
            ttk.Label(f, text=aide, foreground='#666').pack(side='left', padx=8)

    def _onglet_general(self, nb):
        """General tab: atlas size, texture format, dilation, materials to drop.

        Replaced by sm3_gui_hq (its "General / Quality" panel creates the same settings - bake,
        format, dilate, drop - with other defaults and choices, and adds the "Target character"
        tab). This version only appears when this file is run on its own."""
        p = ttk.Frame(nb, padding=10)
        nb.add(p, text='  General  ')
        self._num(p, 'Taille de l atlas', 'bake', 2048, aide='2048 est le maximum valide')
        f = ttk.Frame(p)
        f.pack(fill='x', pady=2)
        ttk.Label(f, text='Format de texture', width=22).pack(side='left')
        self.v['format'] = tk.StringVar(value='DXT5')
        ttk.Combobox(f, textvariable=self.v['format'], width=8, state='readonly',
                     values=['DXT5', 'DXT1']).pack(side='left')
        ttk.Label(f, text='DXT1 : deux fois plus leger, sans alpha',
                  foreground='#666').pack(side='left', padx=8)
        # Dilation pushes the colours of each UV island outwards into the empty gutters. Without
        # it, texture filtering and mipmaps blend in the background colour and every seam shows
        # a thin line.
        self._num(p, 'Dilatation (pixels)', 'dilate', 24,
                  aide='remplit les gouttieres ; sans elle, un lisere sur chaque couture')
        f2 = ttk.Frame(p)
        f2.pack(fill='x', pady=2)
        ttk.Label(f2, text='Materiaux a jeter', width=22).pack(side='left')
        self.v['drop'] = tk.StringVar()
        ttk.Entry(f2, textvariable=self.v['drop'], width=44).pack(side='left')
        ttk.Label(f2, text='separes par des virgules — capes, decalques, placeholders',
                  foreground='#666').pack(side='left', padx=8)

    def _onglet_textures(self, nb):
        """Textures tab: choose which image goes on which material.

        Many ripped models reference NO texture at all: the images sit next to the model, with
        names unrelated to the materials. Baking then produces a uniform atlas and the character
        is plain white in game.

        "Guess texture assignments" finds the link by measurement (see tools/apparier_textures.py):
        a texture read through the RIGHT UV unwrap gives a colour that is continuous over the 3D
        surface. Do not trust the average colour or the position on the body: that by-eye
        reasoning swapped two textures on one test model (Gojo), and the measurement found the
        swap."""
        p = ttk.Frame(nb, padding=10)
        nb.add(p, text='  Textures  ')
        barre = ttk.Frame(p)
        barre.pack(fill='x')
        ttk.Button(barre, text='Analyser le modele',
                   command=self.analyser).pack(side='left')
        ttk.Button(barre, text='Deviner l association',
                   command=self.deviner).pack(side='left', padx=6)
        self.lab_analyse = ttk.Label(barre, text='rien analyse', foreground='#666')
        self.lab_analyse.pack(side='left', padx=10)
        # Shown under the buttons. studio_language.translate() recognises this paragraph by its
        # first words ("Deviner mesure") and swaps in the English text as a whole.
        AIDE_TEX = '''
Deviner mesure la CONTINUITE de la couleur sur la surface 3D : une texture lue a travers le
bon depliage varie doucement d un triangle a son voisin, une texture etrangere saute. Le
score est normalise par le hasard : 0,05 est excellent, au-dela de 0,5 la mesure ne sait pas
et il faut choisir a la main. Verifie toujours -- sur ce modele elle a corrige une inversion
que deux autres methodes avaient ratee.'''
        ttk.Label(p, foreground='#666', justify='left',
                  text=AIDE_TEX).pack(anchor='w', pady=(6, 0))
        # One row per material is added here by _montrer_analyse.
        self.cadre_mats = ttk.Frame(p)
        self.cadre_mats.pack(fill='both', expand=True, pady=(8, 0))
        self.lignes_mats = []   # [(material name, StringVar of the chosen image)]

    def analyser(self):
        """List the model's materials (Blender, tools/analyser_modele.py -> build/analyse.json)."""
        src = self.v['src'].get()
        if not src or not os.path.exists(src):
            messagebox.showwarning('SM3 Studio', 'Choisis un modele source d abord.')
            return
        sc = os.path.join(self.v['racine'].get(), 'tools', 'analyser_modele.py')
        if not os.path.exists(self.v['blender'].get()) or not os.path.exists(sc):
            messagebox.showwarning('SM3 Studio',
                                   'blender.exe ou tools\\analyser_modele.py introuvable.')
            return
        self.lab_analyse.configure(text='analyse en cours...')
        self.update_idletasks()

        def travail():
            js = os.path.join(self.v['racine'].get(), 'build', 'analyse.json')
            os.makedirs(os.path.dirname(js), exist_ok=True)
            subprocess.run([self.v['blender'].get(), '-b', '--python', sc, '--',
                            '--src', src, '--json', js],
                           capture_output=True, text=True, errors='replace')
            self.fil.put(('__analyse__', js))   # -> _montrer_analyse, in the main thread

        threading.Thread(target=travail, daemon=True).start()

    def deviner(self):
        """Find which image goes on which material, by measurement.

        On a mobile-game rip NOTHING links the two: no reference in the file, no meaningful
        name, no alpha. Measurements on the image alone (gradient inside/outside the UV mask,
        variance, flat background) assume empty space outside the islands and fail as soon as
        the texture covers everything. This one looks at the 3D surface and assumes nothing.
        Runs tools/apparier_textures.py in Blender -> build/apparier.json."""
        src = self.v['src'].get()
        sc = os.path.join(self.v['racine'].get(), 'tools', 'apparier_textures.py')
        dossier = self.v['textures'].get()
        if not src or not os.path.exists(src):
            messagebox.showwarning('SM3 Studio', 'Choisis un modele source d abord.')
            return
        if not dossier or not os.path.isdir(dossier):
            messagebox.showwarning('SM3 Studio',
                                   'Lance « Analyser le modele » d abord : il trouve le dossier '
                                   'des textures.')
            return
        if not os.path.exists(self.v['blender'].get()) or not os.path.exists(sc):
            # Known slip, kept as is: '\a' is the BEL escape, so this message shows
            # "tools<BEL>pparier_textures.py". The bytecode of the shipped window contains the
            # same character; fixing it is a one-character change ('\\a').
            messagebox.showwarning('SM3 Studio',
                                   'blender.exe ou tools\apparier_textures.py introuvable.')
            return
        self.lab_analyse.configure(text='mesure de la continuite en cours...')
        self.update_idletasks()

        def travail():
            js = os.path.join(self.v['racine'].get(), 'build', 'apparier.json')
            os.makedirs(os.path.dirname(js), exist_ok=True)
            subprocess.run([self.v['blender'].get(), '-b', '--python', sc, '--',
                            '--src', src, '--textures', dossier, '--json', js],
                           capture_output=True, text=True, errors='replace')
            self.fil.put(('__apparier__', js))   # -> _montrer_apparier, in the main thread

        threading.Thread(target=travail, daemon=True).start()

    def _montrer_apparier(self, js):
        """Apply the suggested assignments to the material rows; count the uncertain ones."""
        try:
            d = json.load(open(js, encoding='utf-8'))
        except Exception as e:
            self.lab_analyse.configure(text='appariement illisible : %s' % e, foreground='#c00')
            return
        aff = d.get('affectation', {})   # material -> image file
        M = d.get('matrice', [])         # score[material][texture], normalised: lower is better
        mats, tex = d.get('materiaux', []), d.get('textures', [])
        pose, doute = 0, 0               # assignments applied, assignments with a poor score
        for nom, var in self.lignes_mats:
            # Blender may have renamed a material 'skin.001'; also try the name before the dot.
            f = aff.get(nom) or aff.get(nom.split('.')[0])
            if f:
                var.set(f)
                pose += 1
                if nom in mats and f in tex:
                    sc = M[mats.index(nom)][tex.index(f)]
                    # Above 0.5 the measurement cannot tell (see the help text of the tab).
                    doute += 1 if sc > 0.5 else 0
        self.lab_analyse.configure(
            text='%d association(s) proposee(s)%s — verifie-les, tu peux corriger a la main'
                 % (pose, ', %d peu sure(s)' % doute if doute else ''),
            foreground='#c80' if doute else '#0a0')

    def _montrer_analyse(self, js):
        """Fill the Textures tab from build/analyse.json: one row per material."""
        for w in self.cadre_mats.winfo_children():
            w.destroy()
        self.lignes_mats = []
        try:
            d = json.load(open(js, encoding='utf-8'))
        except Exception as e:
            self.lab_analyse.configure(text='analyse illisible : %s' % e)
            return
        # The images available next to the model.
        dossier = self.v['textures'].get() or ''
        if not dossier:
            base = os.path.dirname(os.path.abspath(self.v['src'].get()))
            # The parent folder too: `source/model.fbx` with `textures/` beside `source/` is the
            # Sketchfab download layout, and looking only in the model's folder misses it.
            for racine in (base, os.path.dirname(base)):
                for n in ('textures', 'texture', 'tex', 'maps', 'images'):
                    c = os.path.join(racine, n)
                    if os.path.isdir(c):
                        dossier = c
                        break
                if dossier:
                    break
            dossier = dossier or base
        exts = ('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.tif', '.dds', '.webp')
        fichiers = ['(aucune)']
        if os.path.isdir(dossier):
            fichiers += sorted(f for f in os.listdir(dossier) if f.lower().endswith(exts))
        self.v['textures'].set(dossier)

        sans = len(d.get('materiaux_sans_image', []))
        self.lab_analyse.configure(
            text='%d materiau(x), %d sans image | %d triangles | %d image(s) dans %s'
                 % (len(d['materiaux']), sans, d['triangles_total'], len(fichiers) - 1,
                    os.path.basename(dossier)),
            foreground='#c80' if sans else '#0a0')

        ent = ttk.Frame(self.cadre_mats)
        ent.pack(fill='x')
        for t, w in (('materiau', 30), ('triangles', 10), ('image a utiliser', 40)):
            ttk.Label(ent, text=t, width=w, foreground='#666').pack(side='left')
        for m in d['materiaux']:
            f = ttk.Frame(self.cadre_mats)
            f.pack(fill='x', pady=1)
            ttk.Label(f, text=m['nom'], width=30).pack(side='left')
            ttk.Label(f, text=str(m['triangles']), width=10).pack(side='left')
            var = tk.StringVar(value=(m['image'] if m['image'] in fichiers else '(aucune)'))
            ttk.Combobox(f, textvariable=var, values=fichiers, width=38,
                         state='readonly').pack(side='left')
            if m['image']:
                ttk.Label(f, text='deja cablee dans le modele',
                          foreground='#666').pack(side='left', padx=8)
            self.lignes_mats.append((m['nom'], var))
        # Cheap warnings: objects that usually have to be dropped (General tab).
        for o in d.get('objets', []):
            if o.get('decalque') or o.get('placeholder'):
                quoi = 'decalque (plus de sommets que de triangles)' if o.get('decalque') \
                    else 'placeholder (bornes toutes nulles)'
                ttk.Label(self.cadre_mats, foreground='#c80',
                          text='  ! %s : %s — a jeter dans l onglet General ?'
                               % (o['nom'], quoi)).pack(anchor='w', pady=(4, 0))

    def _mapping_materiaux(self):
        """The Textures tab as the converter's --materiaux value: 'mat=image.png,mat2=...'."""
        return ','.join('%s=%s' % (n, v.get()) for n, v in self.lignes_mats
                        if v.get() and v.get() != '(aucune)')

    def _onglet_pose(self, nb):
        """Pose tab: manual alignment of the source model on the vanilla body.

        Automatic alignment normally decides scale and position; these fields correct a model
        that is lying down, rotated, or offset."""
        p = ttk.Frame(nb, padding=10)
        nb.add(p, text='  Pose  ')
        self._num(p, 'Echelle', 'echelle', 1.0, aide='1.0 = l alignement automatique decide')
        f = ttk.Frame(p)
        f.pack(fill='x', pady=2)
        ttk.Label(f, text='Rotation X / Y / Z', width=22).pack(side='left')
        for cle in ('rot_x', 'rot_y', 'rot_z'):
            self.v[cle] = tk.StringVar(value='0')
            ttk.Entry(f, textvariable=self.v[cle], width=7).pack(side='left', padx=2)
        ttk.Label(f, text='degres — pour un modele couche ou tourne',
                  foreground='#666').pack(side='left', padx=8)
        self._num(p, 'Decalage  dx,dy,dz', 'decalage', '', largeur=18)
        self.v['poser'] = tk.BooleanVar()
        ttk.Checkbutton(p, text='Poser au sol (recale la hauteur exactement sur le vanilla)',
                        variable=self.v['poser']).pack(anchor='w', pady=(6, 0))
        self.v['sans_retouche'] = tk.BooleanVar()
        ttk.Checkbutton(p, text='Sans retouche — sauter le redressement des bras et le re-skinning '
                                '(modele deja dans la pose vanilla)',
                        variable=self.v['sans_retouche']).pack(anchor='w')
        self._num(p, 'Fondu a l epaule', 'fondu_bras', 0.10,
                  aide='elargir si l epaule se plie net')

    def _onglet_skinning(self, nb):
        """Skinning tab: how bone weights are given to the new model."""
        p = ttk.Frame(nb, padding=10)
        nb.add(p, text='  Skinning  ')

        f = ttk.Frame(p)
        f.pack(fill='x', pady=2)
        ttk.Label(f, text='Methode', width=22).pack(side='left')
        self.v['methode_poids'] = tk.StringVar(value='vanilla')
        ttk.Combobox(f, textvariable=self.v['methode_poids'], width=10, state='readonly',
                     values=('vanilla', 'segments')).pack(side='left')
        ttk.Label(f, foreground='#666',
                  text='vanilla = reprendre les poids du jeu. C est le bon choix.'
                  ).pack(side='left', padx=8)

        self._num(p, 'Voisins melanges', 'voisins', 6,
                  aide='1 = rigide (articulations qui plient net), 6 = la douceur du vanilla')
        # Why 'vanilla' (the English text shown in English mode is in studio_language.translate):
        # skinning weights cannot be computed. Treyarch painted them by hand, and any
        # distance-to-bone approximation shows as soon as the character moves (rubbery limbs, head
        # squashed while swinging). So nothing is generated: each new vertex takes the weights of
        # the nearest vanilla vertices and blends them. Right bones, right proportions and
        # left/right consistency come for free because they are already in the game's weights.
        # The only prerequisite is that both bodies OVERLAP, hence the Pose tab.
        # The paragraph is written as adjacent literals (joined into ONE constant by the parser)
        # because its two "empty" lines really contain 8 spaces: inside a triple-quoted string,
        # an editor that strips trailing whitespace would silently change the text.
        AIDE = ('\n'
                "        Pourquoi 'vanilla' : les poids ne sont pas calculables. Treyarch les a peints a la main,\n"
                '        et une approximation par distance aux os se voit des que le personnage bouge - membres\n'
                '        elastiques, tete comprimee au balancement. On ne fabrique donc plus rien : pour chaque\n'
                '        sommet on prend les sommets vanilla les plus proches et on melange leurs poids. Bons os,\n'
                "        bonnes proportions, coherence gauche/droite comprise, parce qu'elles sont deja dedans.\n"
                '        \n'
                "          membres elastiques quand il bouge  -> etre en 'vanilla', et verifier la pose\n"
                '          articulations qui plient net       -> monter les voisins (8)\n'
                '          une zone suit un os etranger       -> la pose ne se superpose pas au vanilla :\n'
                '                                                onglet Pose, echelle et rotation\n'
                '        \n'
                "        La correspondance suppose que les deux corps se SUPERPOSENT. C'est le seul prerequis.")
        # The paragraph is indented like the code; remove those 8 spaces from each line.
        ttk.Label(p, foreground='#666', justify='left', text=AIDE.replace(chr(10)+' '*8, chr(10))).pack(anchor='w')

        ttk.Separator(p, orient='horizontal').pack(fill='x', pady=8)
        ttk.Label(p, foreground='#888',
                  text='Ancienne methode par segments — gardee pour comparaison'
                  ).pack(anchor='w')
        self._num(p, 'Nettete (puissance)', 'puissance', 'auto',
                  aide='sans effet en methode vanilla')
        self._num(p, 'Part minimale d un os', 'part_mini', 0.001,
                  aide='sans effet en methode vanilla')

    def _onglet_chemins(self, nb):
        """Paths tab: Blender executable, project folder, game folder."""
        p = ttk.Frame(nb, padding=10)
        nb.add(p, text='  Chemins  ')
        p.columnconfigure(1, weight=1)
        for r, (cle, libelle, aide) in enumerate((
                ('blender', 'blender.exe', 'necessaire pour la cuisson de l atlas, rien d autre'),
                ('racine', 'Dossier du projet', 'contient vanilla\\ , tools\\ et mods\\'),
                ('jeu', 'Dossier du jeu', 'celui qui contient Game.exe'))):
            ttk.Label(p, text=libelle).grid(row=r, column=0, sticky='w', pady=4)
            self.v[cle] = tk.StringVar()
            ttk.Entry(p, textvariable=self.v[cle]).grid(row=r, column=1, sticky='we', padx=8)
            # c=cle freezes the current key: a plain closure would see the last key of the loop.
            ttk.Button(p, text='...', width=4,
                       command=lambda c=cle: self._choisir_chemin(c)).grid(row=r, column=2)
            ttk.Label(p, text=aide, foreground='#666').grid(row=r, column=3, sticky='w')

    # ---------------------------------------------------------------- file choosers
    def _choisir_modele(self):
        """Browse for the source model; propose a mod name from its file name.

        Wrapped by sm3_gui_hq: for the Venom target it opens profiles/venom instead."""
        f = filedialog.askopenfilename(title='Modele source', filetypes=FORMATS_MODELE)
        if f:
            self.v['src'].set(f)
            if self.v['nom'].get() in ('', 'MonMod'):
                # No spaces or dashes, at most 24 characters.
                self.v['nom'].set(os.path.splitext(os.path.basename(f))[0]
                                  .replace(' ', '').replace('-', '')[:24] or 'MonMod')

    def _choisir_textures(self):
        d = filedialog.askdirectory(title='Dossier des textures')
        if d:
            self.v['textures'].set(d)

    def _choisir_chemin(self, cle):
        if cle == 'blender':
            f = filedialog.askopenfilename(title='blender.exe',
                                           filetypes=[('blender.exe', 'blender.exe'),
                                                      ('Tous', '*.*')])
        else:
            f = filedialog.askdirectory(title='Dossier')
        if f:
            self.v[cle].set(f)

    def ouvrir(self):
        """Open mods\\<mod name>\\ in Explorer."""
        d = os.path.join(self.v['racine'].get(), 'mods', self.v['nom'].get())
        if os.path.isdir(d):
            os.startfile(d)
        else:
            messagebox.showinfo('SM3 Studio', 'Le mod n a pas encore ete construit :\n%s' % d)

    # ---------------------------------------------------------------- settings
    def _charger(self):
        """Fill the fields: built-in defaults first, then whatever sm3_studio.json contains.

        Wrapped by sm3_gui_hq (language of the target name, qualite.json, matte-suit state)."""
        defauts = {'blender': r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe',
                   'racine': RACINE_DEFAUT,
                   'jeu': r'C:\Program Files (x86)\Activision\Spider-Man 3'}
        for k, val in defauts.items():
            self.v[k].set(val)
        try:
            d = json.load(open(REGLAGES, encoding='utf-8'))
            for k, val in d.items():
                if k in self.v:   # keys of settings that no longer exist are ignored
                    self.v[k].set(val)
        except Exception:
            pass   # first start (no file yet) or unreadable file: keep the defaults

    def _sauver(self):
        """Write every field to sm3_studio.json. Errors are ignored on purpose: a read-only
        folder must not prevent a conversion.

        Wrapped by sm3_gui_hq, which first writes qualite.json and, unlike this method, reports
        invalid values."""
        try:
            json.dump({k: (v.get() if not isinstance(v, tk.BooleanVar) else bool(v.get()))
                       for k, v in self.v.items()},
                      open(REGLAGES, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
        except Exception:
            pass

    # ---------------------------------------------------------------- running a conversion
    def _args(self, depuis=None):
        """The window's settings as sm3_convertir.py command-line arguments.

        Wrapped by sm3_gui_hq, which appends --target (spiderman, venom or blacksuit)."""
        a = ['--nom', self.v['nom'].get().strip() or 'MonMod',
             '--depuis', depuis or self.v['depuis'].get(),
             # The vanilla Spider-Man resource (pack CH_SPIDERMAN) every conversion is measured
             # against. It is extracted from the player's own game, never shipped with the tool.
             '--vanilla', os.path.join(self.v['racine'].get(), 'vanilla', 'CH_SPIDERMAN',
                                       '_O0069.0xCFB154CD.T36.apkf'),
             '--bake', self.v['bake'].get(), '--format', self.v['format'].get(),
             '--dilate', self.v['dilate'].get(),
             '--echelle', self.v['echelle'].get(),
             '--rot-x', self.v['rot_x'].get(), '--rot-y', self.v['rot_y'].get(),
             '--rot-z', self.v['rot_z'].get(),
             '--puissance', self.v['puissance'].get(),
             '--part-mini', self.v['part_mini'].get(),
             '--methode-poids', self.v['methode_poids'].get(),
             '--mods', os.path.join(self.v['racine'].get(), 'mods'),
             '--voisins', self.v['voisins'].get(),
             '--fondu-bras', self.v['fondu_bras'].get()]
        # Optional values are only passed when set, so the converter's own defaults apply.
        if self.v['src'].get():
            a += ['--src', self.v['src'].get()]
        if self.v['textures'].get():
            a += ['--textures', self.v['textures'].get()]
        if self.v['drop'].get().strip():
            a += ['--drop', self.v['drop'].get().strip()]
        mp = self._mapping_materiaux()
        if mp:
            a += ['--materiaux', mp]
        if self.v['decalage'].get().strip():
            a += ['--decalage', self.v['decalage'].get().strip()]
        if self.v['poser'].get():
            a += ['--poser-au-sol']
        if self.v['sans_retouche'].get():
            a += ['--sans-retouche']
        return a

    def convertir(self, depuis=None):
        """Check the prerequisites, save the settings, start the conversion thread.

        depuis: stage to resume from ('verifier' for the "Validate only" button), or None for
        the stage chosen in the window. Wrapped by sm3_gui_hq (quality settings, Venom and
        Black Suit targets)."""
        if self.travail and self.travail.is_alive():
            messagebox.showinfo('SM3 Studio', 'Une conversion est deja en cours.')
            return
        d = depuis or self.v['depuis'].get()
        # Only the first stage ('chaine': import + bake) needs the source model and Blender; later
        # stages work on the files already in build\<mod name>\.
        if d == 'chaine' and not self.v['src'].get():
            messagebox.showwarning('SM3 Studio', 'Choisis un modele source.')
            return
        if d == 'chaine' and not os.path.exists(self.v['blender'].get()):
            messagebox.showwarning('SM3 Studio',
                                   "blender.exe est introuvable.\nL'etape « chaine » (la cuisson "
                                   "de l'atlas) en a besoin.\nOnglet Chemins.")
            return
        self._sauver()
        self.txt.delete('1.0', 'end')
        self.bt_convertir.state(['disabled'])
        self.etat.configure(text='en cours...', foreground='#c80')
        args = self._args(depuis)
        self.travail = threading.Thread(target=self._travailler, args=(args,), daemon=True)
        self.travail.start()

    def _travailler(self, args):
        """Worker thread: run sm3_convertir.main() in this process, its output going to the log.

        The converter is loaded from BASE, i.e. from inside the .exe when frozen: changing
        sm3_convertir.py on disk has no effect until the .exe is rebuilt. tools/ is read from the
        project folder (RACINE), so changes there apply at once."""
        import importlib.util
        vieux_out, vieux_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = Tuyau(self.fil)
        code = 0
        try:
            sp = importlib.util.spec_from_file_location(
                'sm3_convertir', os.path.join(BASE, 'sm3_convertir.py'))
            m = importlib.util.module_from_spec(sp)
            sys.modules['sm3_convertir'] = m
            sp.loader.exec_module(m)
            m.BLENDER = self.v['blender'].get()
            m.RACINE = self.v['racine'].get()
            # main() reads sys.argv through argparse. Side effect: every argparse parser created
            # during the conversion reports itself as 'sm3_convertir' in its error messages,
            # even when it belongs to a tool called further down.
            sys.argv = ['sm3_convertir'] + args
            m.main()
        except SystemExit as e:
            if e.code:   # sys.exit(0) / sys.exit() is a normal end, not an error
                print('!! ARRET : %s' % e.code)
                code = 1
        except Exception:
            print('!! ERREUR INATTENDUE')
            print(traceback.format_exc())
            code = 2
        finally:
            sys.stdout.flush()
            sys.stdout, sys.stderr = vieux_out, vieux_err
            self.fil.put(('__fin__', code))   # re-enables the Convert button (_vider_fil)

    def installer(self):
        """Install and launch game: run tools/boucle_test.ps1 elevated, then show its logs.

        The script installs mods\\<mod name>\\ into the game, disables every other mod and starts
        the game. Wrapped by sm3_gui_hq (matte suit applied first, Venom and Black Suit installers)."""
        nom = self.v['nom'].get().strip()
        ps = os.path.join(self.v['racine'].get(), 'tools', 'boucle_test.ps1')
        if not os.path.exists(ps):
            messagebox.showwarning('SM3 Studio', 'boucle_test.ps1 introuvable dans tools\\.')
            return
        if not messagebox.askyesno('SM3 Studio',
                                   'Installer « %s » dans le jeu, desactiver tous les autres mods '
                                   'et lancer le jeu ?\n\nUne elevation UAC va etre demandee.' % nom):
            return
        # `Start-Process -ArgumentList` JOINS its items with spaces without quoting them. A path
        # such as "...\New folder\tools\boucle_test.ps1" was therefore cut at "New", and the
        # elevated PowerShell received a truncated -File. The argument needs DOUBLE quotes inside
        # it, escaped for PowerShell: `\"...\"`.
        arg = ("'-NoProfile','-ExecutionPolicy','Bypass','-File','\\\"%s\\\"','-Mod','%s'"
               % (ps, nom))
        self.etat.configure(text='installation...', foreground='#c80')
        self.onglets_bas.select(0)

        def travail():
            # -Wait, then read the logs back: otherwise the elevated window opens, does its job
            # and closes, and nobody knows whether it worked.
            # The redirection is done INSIDE the thread: sys.stdout is global, and restoring it
            # from the main thread would cut the pipe before the first line.
            import sys as _s
            _vieux = _s.stdout
            _s.stdout = Tuyau(self.fil)
            print('[installer] elevation demandee (UAC), mod « %s »' % nom, flush=True)
            subprocess.run(['powershell', '-NoProfile', '-Command',
                            'Start-Process powershell -Verb RunAs -Wait -ArgumentList ' + arg],
                           capture_output=True, text=True, errors='replace')
            for j in ('install.log', 'boucle.log'):
                c = os.path.join(self.v['racine'].get(), j)
                if os.path.exists(c):
                    print('[installer] --- %s' % j, flush=True)
                    try:
                        for ligne in open(c, encoding='utf-8-sig').read().splitlines()[:40]:
                            print('    ' + ligne, flush=True)
                    except Exception as e:
                        print('    illisible : %s' % e, flush=True)
            _s.stdout.flush()
            _s.stdout = _vieux
            self.fil.put(('__fin__', 0))

        threading.Thread(target=travail, daemon=True).start()

    # ---------------------------------------------------------------- live log
    def _vider_fil(self):
        """Main-thread side of the queue, every 60 ms.

        Items are either log lines (str), coloured by their prefix, or (event, value) tuples
        posted by the worker threads: '__fin__' (conversion or install finished, value = exit
        code), '__analyse__' / '__apparier__' (JSON file to display), '__apercu__' (render
        done)."""
        try:
            while True:
                el = self.fil.get_nowait()
                if isinstance(el, tuple) and el and el[0] == '__fin__':
                    self.bt_convertir.state(['!disabled'])
                    ok = el[1] == 0
                    self.etat.configure(text='termine' if ok else 'arrete',
                                        foreground='#0a0' if ok else '#c00')
                    continue
                if isinstance(el, tuple) and el and el[0] == '__analyse__':
                    self._montrer_analyse(el[1])
                    continue
                if isinstance(el, tuple) and el and el[0] == '__apparier__':
                    self._montrer_apparier(el[1])
                    continue
                if isinstance(el, tuple) and el and el[0] == '__apercu__':
                    self.lab_apercu.configure(text='')
                    self._montrer_vue()
                    self.onglets_bas.select(1)
                    continue
                # Colours follow the converter's output conventions: 'OK ...' passed checks,
                # '!!' errors, '[convertir] ---' section titles, indented '[...]' details.
                tag = ''
                s = el.lstrip()
                if s.startswith('OK '):
                    tag = 'ok'
                elif s.startswith('!!'):
                    tag = 'ko'
                elif s.startswith('[convertir] ---') or s.startswith('[convertir] CONTROLE'):
                    tag = 'titre'
                elif s.startswith('    ['):
                    tag = 'gris'
                self.txt.insert('end', el + '\n', tag)
                self.txt.see('end')
        except queue.Empty:
            pass
        self.after(60, self._vider_fil)


def _sans_fenetre(args):
    """Command-line mode: the same executable, without any window.

    Useful for scripting, and it is also the only way to test the frozen executable: a window
    cannot be tested blind. `args` are sm3_convertir.py options; --vanilla defaults to the
    project folder's vanilla resource."""
    import importlib.util
    sp = importlib.util.spec_from_file_location(
        'sm3_convertir', os.path.join(BASE, 'sm3_convertir.py'))
    m = importlib.util.module_from_spec(sp)
    sys.modules['sm3_convertir'] = m
    sp.loader.exec_module(m)
    if not any(a == '--vanilla' for a in args):
        args += ['--vanilla', os.path.join(RACINE_DEFAUT, 'vanilla', 'CH_SPIDERMAN',
                                           '_O0069.0xCFB154CD.T36.apkf')]
    m.RACINE = RACINE_DEFAUT
    sys.argv = ['sm3_convertir'] + args
    try:
        m.main()
    except SystemExit as e:
        sys.exit(e.code or 0)


# Only when this file is run directly. sm3_studio_hq.py executes it under another __name__, so
# this block is skipped there and the HQ entry point opens the window itself.
if __name__ == '__main__':
    if len(sys.argv) > 1:
        _sans_fenetre(sys.argv[1:])
    else:
        app = Studio()
        app.protocol('WM_DELETE_WINDOW', lambda: (app._sauver(), app.destroy()))
        app.mainloop()
