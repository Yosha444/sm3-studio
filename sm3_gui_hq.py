# SPDX-License-Identifier: GPL-3.0-or-later
"""HQ additions to the SM3 Studio window (sm3_interface.Studio).

The original window (sm3_interface.py) is kept as it is; integrate() then patches its class:
  * replaces the "General" tab by a "General / Quality" panel (atlas resolution 2048/4096/8192,
    DXT1/DXT5/ARGB8, geometry mode, vertex colour) saved to qualite.json, which the converter
    reads;
  * adds a "Target character" tab: Spider-Man (red suit), Venom or Black Suit, and the matte-suit
    switch that patches Game.exe through tools/costume_mat.py;
  * wraps the load / save / convert / arguments / preview / model-chooser / install methods so
    they take the target character into account, then call the original method.

Visible strings are French; the English interface comes from studio_language.localize(), applied
to this module's compiled code exactly as to sm3_interface.py (see the notes there).
"""
import json
import os
import tkinter as tk
from tkinter import ttk, messagebox

# Geometry mode: label shown in the panel -> value written to qualite.json ("geometrie").
MODES = {
    'Conserver le maillage': 'conserver',
    'Retrianguler les quads et ngons': 'retrianguler',
    'Subdiviser sans lissage (×4)': 'subdiviser',
}

# Matte suit: internal key (saved in sm3_studio.json, passed to tools\costume_mat.py) -> label shown.
# The keys must NEVER be added to studio_language.EN: localize() translates every constant of the
# module, and a translated key would no longer be recognised by costume_mat.py.
COSTUME_MAT = {
    'satine': 'Satiné — léger lustre (recommandé)',
    'mat': 'Mat — ni brillance ni reflet',
    'attenue': 'Atténué — reflets du jeu adoucis',
    'identite': 'Identité — aucun changement (test)',
}


def integrate(namespace):
    """Patch the Studio class found in `namespace` (the globals of sm3_interface.py) and return it.

    The original methods are kept in original_* variables so each replacement can fall back on
    them. Everything is assigned to the class at the end of this function, before any window
    exists, so the buttons built by Studio._construire already point to the new methods."""
    Studio = namespace['Studio']
    REGLAGES = namespace.get('REGLAGES')
    original_load = Studio._charger
    original_save = Studio._sauver
    original_convert = Studio.convertir
    original_args = Studio._args
    original_preview = Studio.rendre_apercu
    original_choose_model = Studio._choisir_modele
    original_install = Studio.installer

    def panel(self, notebook):
        """Replaces Studio._onglet_general: "General / Quality" panel + "Target character" tab."""
        frame = ttk.Frame(notebook, padding=10)
        notebook.add(frame, text='  Général / Qualité  ')
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)
        self.hq_panel = frame
        defaults = dict(bake='4096', format='DXT5', dilate='12', drop='',
                        hq_geometry='Retrianguler les quads et ngons', hq_gray='128')
        for name, value in defaults.items():
            self.v[name] = tk.StringVar(self, value=value)

        def label(text, row, col):
            ttk.Label(frame, text=text).grid(row=row, column=col, sticky='w', padx=(0, 10), pady=5)

        label('Résolution de l’atlas', 0, 0)
        self.hq_resolution = ttk.Combobox(frame, textvariable=self.v['bake'],
            values=('2048', '4096', '8192'), state='readonly', width=10)
        self.hq_resolution.grid(row=0, column=1, sticky='w')
        label('Compression', 0, 2)
        self.hq_format = ttk.Combobox(frame, textvariable=self.v['format'], values=('DXT1', 'DXT5', 'ARGB8'),
            state='readonly', width=10)
        self.hq_format.grid(row=0, column=3, sticky='w')

        label('Géométrie', 1, 0)
        self.hq_geometry = ttk.Combobox(frame, textvariable=self.v['hq_geometry'],
            values=tuple(MODES), state='readonly', width=36)
        self.hq_geometry.grid(row=1, column=1, sticky='w')
        label('Dilatation (pixels)', 1, 2)
        ttk.Spinbox(frame, from_=0, to=128, textvariable=self.v['dilate'], width=10).grid(
            row=1, column=3, sticky='w')

        label('Vertex color — gris', 2, 0)
        color_row = ttk.Frame(frame)
        color_row.grid(row=2, column=1, sticky='w')
        self.hq_gray = ttk.Spinbox(color_row, from_=0, to=255,
            textvariable=self.v['hq_gray'], width=8)
        self.hq_gray.pack(side='left')
        self.hq_swatch = tk.Label(color_row, width=3, background='#808080', relief='sunken')
        self.hq_swatch.pack(side='left', padx=8)
        self.hq_hex = ttk.Label(color_row, text='#808080')
        self.hq_hex.pack(side='left')
        ttk.Label(frame, text='0 = noir · 128 = gris · 255 = blanc · alpha 255').grid(
            row=2, column=2, columnspan=2, sticky='w')

        label('Matériaux à exclure', 3, 0)
        ttk.Entry(frame, textvariable=self.v['drop']).grid(
            row=3, column=1, columnspan=3, sticky='ew')
        self.hq_note = ttk.Label(frame, text='', foreground='#555', wraplength=920)
        self.hq_note.grid(row=4, column=0, columnspan=4, sticky='w', pady=(6, 0))
        for name in ('hq_gray', 'hq_geometry', 'bake', 'format'):
            self.v[name].trace_add('write', lambda *_: self._hq_preview())
        self._hq_preview()
        target = ttk.Frame(notebook, padding=10)
        notebook.insert(0, target, text='  Personnage cible  ')
        self.v['target'] = tk.StringVar(self, value='Spider-Man')
        def target_controls(*_):
            black = self.v['target'].get() == 'Costume noir'
            if black:
                # Texture slot 0x0133FD92 is DXT1 128x128 in the vanilla game, and the 71 textures
                # of the vanilla CH_BLACKSUIT pack are DXT1/DXT3/DXT5: none is ARGB8. At 4096 the
                # same atlas weighs 89,478,552 bytes in ARGB8 against 22,369,716 bytes in DXT5,
                # the exact size of the mods that work. So choosing the Black Suit turns ARGB8
                # back into DXT5 (and sets black vertex colour and 12 px dilation); the format
                # can still be changed afterwards, ARGB8 is no longer forced.
                if self.v['format'].get() == 'ARGB8':
                    self.v['format'].set('DXT5')
                self.v['hq_gray'].set('0')
                self.v['dilate'].set('12')
            self.hq_format.configure(state='readonly')
            self.hq_gray.configure(state='disabled' if black else 'normal')
        self.v['target'].trace_add('write', target_controls)
        ttk.Label(target, text='Personnage à modifier').grid(row=0, column=0, sticky='w', padx=(0, 15))
        ttk.Combobox(target, textvariable=self.v['target'], values=('Spider-Man', 'Venom', 'Costume noir'),
                     state='readonly', width=18).grid(row=0, column=1, sticky='w')
        ttk.Button(target, text='Charger le projet Venom', command=self._venom_select).grid(
            row=1, column=0, pady=12, sticky='w')
        ttk.Button(target, text='Ouvrir ce projet dans Blender', command=self._venom_open).grid(
            row=1, column=1, padx=10, sticky='w')
        ttk.Label(target, text='Venom : importer un GLB, glTF, FBX ou OBJ, puis Convertir.\n'
                  'Rig reconnu : poids source et adaptation au repos ; sinon transfert spatial à vérifier.\n'
                  'Format natif Venom : palette 256 couleurs, indices ARGB8, texture 2048 x 1024.\n'
                  'Shader Venom original conservé. Nouveau format de textures à valider en jeu ; aucun vertex color natif.',
                  foreground='#555').grid(row=2, column=0, columnspan=3, sticky='w')
        ttk.Label(target, text='Costume noir : GLB/FBX/OBJ → 000 + 001. Méthode validée avec CJ ; atlas couleur, sans cel shading.').grid(row=4, column=0, columnspan=3, sticky='w')
        ttk.Button(target, text='Restaurer le Venom du jeu', command=lambda: self._venom_install(True)).grid(row=3, column=0, pady=10, sticky='w')
        self._costume_mat_panneau(target, 5)

    def preview(self):
        """Refresh the colour swatch and the explanatory note of the quality panel."""
        try:
            gray = int(self.v['hq_gray'].get())
            if not 0 <= gray <= 255:
                raise ValueError()
            color = '#%02X%02X%02X' % (gray, gray, gray)
            self.hq_swatch.configure(background=color)
            self.hq_hex.configure(text=color)
        except ValueError:
            self.hq_hex.configure(text='0 à 255')
        text = {'conserver': 'La topologie importée est conservée.',
                'retrianguler': 'Les triangles déjà présents ne changent pas.',
                'subdiviser': 'Environ quatre fois plus de triangles, sans arrondir la silhouette.'}
        mode = MODES.get(self.v['hq_geometry'].get(), 'conserver')
        compression = ('ARGB8 : sans compression, 8 fois le poids du DXT1. Compatibilité en jeu à tester.'
            if self.v['format'].get() == 'ARGB8' else 'DXT1 et DXT5 compressent les couleurs par blocs de 4 × 4 pixels.')
        self.hq_note.configure(text=text[mode] + ' ' + compression)

    def load(self):
        """Wraps Studio._charger: also reads qualite.json and prepares the matte-suit state."""
        original_load(self)
        from studio_language import translate, EN
        # The target character is saved by its displayed label, which depends on the language
        # the window was in at the time ('Costume noir' / 'Black Suit'): convert it to the
        # current language.
        current=self.v['target'].get()
        if os.environ.get('SM3_UI_LANGUAGE')=='en':
            self.v['target'].set(translate(current))
        else:
            self.v['target'].set(next((fr for fr,en in EN.items() if en==current),current))
        self.title('SM3 Studio HQ — qualité intégrée')
        path = os.path.join(self.v['racine'].get(), 'qualite.json')
        try:
            with open(path, encoding='utf-8-sig') as f:
                config = json.load(f)
            self.v['bake'].set(str(config['resolution']))
            self.v['hq_gray'].set(str(config.get('vertex_color', [128])[0]))
            self.v['hq_geometry'].set(next(label for label, mode in MODES.items()
                if mode == config['geometrie']))
        except (OSError, ValueError, KeyError, StopIteration):
            pass
        self._hq_preview()
        # Matte suit: unknown preset -> satin. First start with the check box (key missing from
        # sm3_studio.json): the box will take the real state of Game.exe at the first read, as long
        # as the user has not touched it.
        if self.v['costume_mat_preset'].get() not in COSTUME_MAT:
            self.v['costume_mat_preset'].set('satine')
        try:
            with open(REGLAGES, encoding='utf-8-sig') as f:
                self.cm_synchroniser = 'costume_mat' not in json.load(f)
        except (OSError, ValueError, TypeError):
            self.cm_synchroniser = True
        for nom in ('costume_mat', 'costume_mat_preset'):
            self.v[nom].trace_add('write', lambda *_: setattr(self, 'cm_synchroniser', False))
        attente = []

        def jeu_change(*_):
            # re-read at most once every half second while the user types in the Paths tab
            for ident in attente:
                self.after_cancel(ident)
            attente[:] = [self.after(500, self._costume_mat_rafraichir)]
        self.v['jeu'].trace_add('write', jeu_change)
        self.after(300, self._costume_mat_rafraichir)

    def config(self):
        """Validate the quality panel; return (path of qualite.json, new content). Raises
        ValueError with a message for the user when a value is invalid."""
        gray = int(self.v['hq_gray'].get())
        resolution = int(self.v['bake'].get())
        if not 0 <= gray <= 255:
            raise ValueError('Le gris des sommets doit être compris entre 0 et 255.')
        if resolution not in (2048, 4096, 8192):
            raise ValueError('Choisir une résolution 2048, 4096 ou 8192.')
        if self.v['format'].get() not in ('DXT1', 'DXT5', 'ARGB8'):
            raise ValueError('Choisir une compression DXT1, DXT5 ou ARGB8.')
        if self.v['hq_geometry'].get() not in MODES:
            raise ValueError('Choisir un mode de géométrie.')
        path = os.path.join(self.v['racine'].get(), 'qualite.json')
        try:
            with open(path, encoding='utf-8-sig') as f:
                value = json.load(f)
        except FileNotFoundError:
            # No qualite.json yet: start from the converter's other settings (see qualite.json).
            value = dict(marge_pixels=8, limite_triangles=10000000, autoriser_couleurs_unies=False)
        value.update(resolution=resolution, geometrie=MODES[self.v['hq_geometry'].get()],
                     vertex_color=[gray, gray, gray, 255], format=self.v['format'].get())
        # Cel-shading keys that older versions could leave in qualite.json; this panel never
        # writes them (no cel shading, see the Black Suit note of the Target character tab).
        value.pop('cel_shading', None)
        value.pop('venom_cel_enabled', None)
        return path, value

    def save(self):
        """Wraps Studio._sauver: write qualite.json first. Unlike the original, invalid values
        raise (the close handler of sm3_studio_hq.py shows the error and keeps the window open)."""
        path, value = self._hq_config()
        # Replace atomically so the conversion never reads a partially written setting file.
        temporary = path + '.tmp'
        with open(temporary, 'w', encoding='utf8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
        original_save(self)

    def convert(self, depuis=None):
        """Wraps Studio.convertir: check the Venom source, save the quality settings, and restart
        from the first stage when the target or a quality setting requires it."""
        if self.travail and self.travail.is_alive():
            return original_convert(self, depuis)   # the original shows "already running"
        if self.v['target'].get() == 'Venom':
            source = self.v['src'].get().strip()
            if os.path.splitext(source)[1].lower() not in ('.mesh', '.blend', '.glb', '.gltf', '.fbx', '.obj'):
                messagebox.showwarning('Source Venom', 'Choisir un GLB, glTF, FBX, OBJ, mesh Venom ou projet Blender préparé.', parent=self)
                return
            if not os.path.isfile(source):
                messagebox.showwarning('Source Venom introuvable', 'Le fichier sélectionné n’existe pas.', parent=self)
                return
        try:
            path, value = self._hq_config()
            try:
                with open(path, encoding='utf-8-sig') as f:
                    previous = json.load(f)
            except FileNotFoundError:
                previous = {}
            self._sauver()
        except (ValueError, OSError, KeyError) as error:
            messagebox.showerror('Réglages HQ', str(error), parent=self)
            return
        # Venom and Black Suit are converted by their own pipelines (tools/venom_runner.py,
        # tools/blacksuit_runner.py), which the window always starts from the first stage.
        if self.v['target'].get() in ('Venom', 'Costume noir'):
            self.v['depuis'].set('chaine')
            return original_convert(self, 'chaine')
        changed = any(previous.get(k) != value[k]
                      for k in ('resolution', 'geometrie', 'vertex_color', 'format'))
        if changed:
            # Earlier cached stages may contain another topology, atlas or colour.
            self.v['depuis'].set('chaine')
            depuis = 'chaine'
        return original_convert(self, depuis)

    def args(self, depuis=None):
        """Wraps Studio._args: adds --target for sm3_convertir.py."""
        result = original_args(self, depuis)
        result += ['--target', {'Venom': 'venom', 'Costume noir': 'blacksuit'}.get(self.v['target'].get(), 'spiderman')]
        return result

    def venom_select(self):
        """Load Venom project button: select the prepared Blender project of the game's Venom."""
        path = os.path.join(self.v['racine'].get(), 'profiles', 'venom', 'Venom_editable.blend')
        if not os.path.isfile(path):
            messagebox.showerror('Venom', 'Projet Venom introuvable dans profiles/venom.', parent=self)
            return
        self.v['target'].set('Venom')
        self.v['src'].set(path)
        self.v['nom'].set('Venom_Mod')
        self.v['depuis'].set('chaine')

    def choose_model(self):
        """Wraps Studio._choisir_modele: for Venom, browse from profiles/venom and accept .mesh."""
        if self.v['target'].get() != 'Venom':
            return original_choose_model(self)
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self, title='Modèle pour Venom',
            initialdir=os.path.join(self.v['racine'].get(), 'profiles', 'venom'),
            filetypes=[('Modèles 3D', '*.glb *.gltf *.fbx *.obj *.blend *.mesh'), ('Tous les fichiers', '*.*')])
        if path:
            self.v['src'].set(path)

    def venom_open(self):
        """Open the converted Venom project (or the selected .blend) in Blender."""
        import subprocess
        root = self.v['racine'].get()
        generated = os.path.join(root, 'build', self.v['nom'].get().lower(), 'Venom_custom.blend')
        source = self.v['src'].get()
        path = generated if os.path.isfile(generated) else source
        if not path.lower().endswith('.blend'):
            messagebox.showinfo('Venom', 'Convertir le modèle pour créer son projet Venom_custom.blend.', parent=self)
            return
        try:
            subprocess.Popen([self.v['blender'].get(), path])
        except OSError as error:
            messagebox.showerror('Blender', str(error), parent=self)

    def render_preview(self):
        """Wraps Studio.rendre_apercu: Venom shows the image written by its own pipeline."""
        if self.v['target'].get() == 'Venom':
            path = os.path.join(self.v['racine'].get(), 'build', self.v['nom'].get().lower(), 'apercu_venom.png')
            if not os.path.isfile(path):
                messagebox.showinfo('Aperçu Venom', 'Convertir un modèle custom pour créer son aperçu, ou ouvrir le projet natif dans Blender.', parent=self)
                return
            from PIL import Image, ImageTk
            window = tk.Toplevel(self); window.title('Venom — couleurs exportées, pose au repos (sans éclairage du jeu)')
            with Image.open(path) as image:
                image.thumbnail((750, 750))
                window.preview_image = ImageTk.PhotoImage(image, master=window)
            ttk.Label(window, image=window.preview_image).pack()
            return
        return original_preview(self)

    def venom_install(self, restore=False):
        """Install the Venom mod (or restore the game's Venom) with tools/venom_install.py,
        read from disk at each use so a fix in tools/ applies without rebuilding the .exe."""
        if self.travail and self.travail.is_alive():
            messagebox.showinfo('Venom', 'Attendre la fin de la conversion.', parent=self)
            return
        import importlib.util
        try:
            root = self.v['racine'].get()
            spec = importlib.util.spec_from_file_location('venom_install_local', os.path.join(root, 'tools', 'venom_install.py'))
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            result = module.install(root, self.v['jeu'].get(), self.v['nom'].get(), restore=restore)
            messagebox.showinfo('Venom', ('Venom natif restauré.' if restore else 'Mod Venom installé avec le pack original. Redémarrer le jeu pour tester le rendu.')
                + '\nSauvegarde : ' + result['backup'], parent=self)
        except Exception as error:
            messagebox.showerror('Installation Venom', str(error), parent=self)

    def install(self):
        """Wraps Studio.installer ("Install and launch game") according to the target character."""
        cible = self.v['target'].get()
        conversion = self.travail and self.travail.is_alive()
        if (cible in ('Spider-Man', 'Costume noir') and self.v['costume_mat'].get()
                and not self.cm_avant_installation and not (conversion and cible == 'Costume noir')):
            # Box checked: the matte suit is guaranteed BEFORE the install (the button starts the
            # game right after). Nothing is written if it is already in place (costume_mat says
            # "Nothing to do"). Venom is not concerned: it uses another shader class.
            def ensuite():
                self.cm_avant_installation = True
                try:
                    self.installer()
                finally:
                    self.cm_avant_installation = False
            return self._costume_mat_appliquer(confirmer=False, ensuite=ensuite)
        if self.v['target'].get() == 'Costume noir':
            if self.travail and self.travail.is_alive():
                messagebox.showinfo('Costume noir', 'Attendre la fin de la conversion.', parent=self)
                return
            try:
                import sys
                sys.path.insert(0, os.path.join(self.v['racine'].get(), 'tools'))
                from blacksuit_deploy import install as deploy
                result = deploy(self.v['racine'].get(), self.v['jeu'].get(), self.v['nom'].get())
                messagebox.showinfo('Costume noir', '000 et 001 installés.\nSauvegarde : '+result['backup'], parent=self)
            except Exception as error:
                messagebox.showerror('Costume noir', str(error), parent=self)
            return
        if self.v['target'].get() == 'Venom':
            return self._venom_install()
        return original_install(self)

    # ------------------------------------------------------------------ matte suit (Game.exe)
    # The "oily" shine of the suit is computed by Game.exe itself (shader class sm_phatspiderman,
    # shared by the red suit, the black suit and every suit mod): tools\costume_mat.py patches
    # its 3 pixel shaders in place. The module is re-read from disk at each use, like
    # venom_install.py. State is read with costume_mat.etat_dossier(); writing goes ONLY through
    # costume_mat.main([...]), hence through the same checks as its command line, in a thread.
    # Nothing is written to Game.exe without a click.
    def costume_mat_panneau(self, parent, row):
        """Matte-suit row of the Target character tab: check box, preset, Apply, Remove, state."""
        self.v['costume_mat'] = tk.BooleanVar(self, value=False)
        self.v['costume_mat_preset'] = tk.StringVar(self, value='satine')
        # displayed label, kept outside self.v: sm3_studio.json only stores the key
        self.cm_libelle = tk.StringVar(self, value=COSTUME_MAT['satine'])
        self.cm_travail = None
        self.cm_avant_installation = False
        self.cm_synchroniser = False
        # Two rows only: in English this tab sets the height of the settings notebook, and every
        # row added here is taken from the Log.
        ttk.Separator(parent).grid(row=row, column=0, columnspan=3, sticky='we', pady=(6, 6))
        self.cm_cadre = ttk.Frame(parent)
        self.cm_cadre.grid(row=row + 1, column=0, columnspan=3, sticky='w')
        ttk.Checkbutton(self.cm_cadre, text='Costume mat (réappliqué à chaque installation)',
                        variable=self.v['costume_mat']).pack(side='left')
        self.cm_preset = ttk.Combobox(self.cm_cadre, textvariable=self.cm_libelle,
            values=tuple(COSTUME_MAT.values()), state='readonly', width=36)
        self.cm_preset.pack(side='left', padx=8)
        self.cm_appliquer = ttk.Button(self.cm_cadre, text='Appliquer au jeu', command=self._costume_mat_appliquer)
        self.cm_appliquer.pack(side='left')
        self.cm_retirer = ttk.Button(self.cm_cadre, text='Retirer le costume mat', command=self._costume_mat_retirer)
        self.cm_retirer.pack(side='left', padx=(6, 0))
        self.cm_etat = ttk.Label(parent, text='', foreground='#555', wraplength=840)
        self.cm_etat.grid(row=row + 2, column=0, columnspan=3, sticky='w', pady=(4, 0))

        def vers_cle(*_):
            cle = next((k for k, texte in COSTUME_MAT.items() if texte == self.cm_libelle.get()), None)
            if cle and self.v['costume_mat_preset'].get() != cle:
                self.v['costume_mat_preset'].set(cle)

        def vers_libelle(*_):
            texte = COSTUME_MAT.get(self.v['costume_mat_preset'].get())
            if texte and self.cm_libelle.get() != texte:
                self.cm_libelle.set(texte)
        self.cm_libelle.trace_add('write', vers_cle)
        self.v['costume_mat_preset'].trace_add('write', vers_libelle)
        self.v['costume_mat'].trace_add('write', self._costume_mat_activer)
        self._costume_mat_activer()

    def costume_mat_activer(self, *_):
        """Box unchecked: preset and Apply greyed out; Remove stays available.
        While Game.exe is being written: everything is greyed out."""
        libre = not (self.cm_travail and self.cm_travail.is_alive())
        actif = libre and self.v['costume_mat'].get()
        self.cm_preset.configure(state='readonly' if actif else 'disabled')
        self.cm_appliquer.configure(state='normal' if actif else 'disabled')
        self.cm_retirer.configure(state='normal' if libre else 'disabled')

    def costume_mat_module(self, sortie=None):
        """tools\\costume_mat.py, re-read from disk. Its print() calls go to sortie(line), or
        nowhere: never to sys.stdout, which a running conversion redirects for the whole process.
        Both can therefore work at the same time without mixing their lines."""
        import builtins
        import importlib.util
        chemin = os.path.join(self.v['racine'].get(), 'tools', 'costume_mat.py')
        if not os.path.isfile(chemin):
            raise FileNotFoundError('Outil introuvable : %s' % chemin)
        spec = importlib.util.spec_from_file_location('costume_mat_local', chemin)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def imprimer(*valeurs, sep=None, end=None, file=None, flush=False):
            if file is not None:
                return builtins.print(*valeurs, sep=sep, end=end, file=file, flush=flush)
            texte = (' ' if sep is None else sep).join(str(v) for v in valeurs)
            for ligne in texte.splitlines():
                if sortie:
                    sortie(ligne)
        # a module-level `print` shadows the builtin one for every function of that module
        module.print = imprimer
        return module

    def costume_mat_rafraichir(self):
        """State line: read-only look at Game.exe (a few milliseconds)."""
        if self.cm_travail and self.cm_travail.is_alive():
            return  # re-read when the write is over
        jeu = self.v['jeu'].get().strip().strip('"')
        try:
            module = self._costume_mat_module()
            lu = module.etat_dossier(jeu) if jeu else dict(etat='absent')
        except Exception as erreur:
            self.cm_etat.configure(text='{}: {}'.format(type(erreur).__name__, erreur), foreground='#c00')
            return
        etat = lu['etat']
        if self.cm_synchroniser and etat != 'absent':
            # first start: the box reflects what is already in Game.exe
            self.cm_synchroniser = False
            if etat == 'patche' and lu['preset'] in COSTUME_MAT:
                self.v['costume_mat_preset'].set(lu['preset'])
                self.v['costume_mat'].set(True)
        couleur = '#555'
        if etat == 'absent':
            texte = 'Game.exe introuvable dans « %s » : indiquer le dossier du jeu (onglet Chemins).' % jeu
            couleur = '#a50'
        elif etat == 'non_reconnu':
            texte = 'Game.exe non reconnu (autre version, ou exe agrandi par un autre outil) : le costume mat ne peut pas s’y appliquer.'
            couleur = '#a50'
        elif etat == 'inconnu':
            texte = 'Game.exe : shaders du costume modifiés par un autre outil : le costume mat ne peut pas s’y appliquer.'
            couleur = '#a50'
        elif etat == 'origine':
            texte = 'Game.exe : costume d’origine (pas de costume mat).'
        elif etat == 'mixte':
            texte = 'Game.exe : costume mat incomplet (écriture interrompue ?) : appliquer ou retirer pour remettre de l’ordre.'
            couleur = '#a50'
        elif lu['preset'] in COSTUME_MAT:
            texte = 'Game.exe : costume mat « %s » installé.' % COSTUME_MAT[lu['preset']]
        elif lu['valeurs']:
            texte = 'Game.exe : costume mat avec des valeurs libres (%s).' % module.fmt(lu['valeurs'])
        else:
            texte = 'Game.exe : costume mat avec des valeurs différentes selon les shaders.'
        if etat in ('patche', 'mixte') and not lu['retirable']:
            texte += ' ' + 'Retrait : une copie intacte de Game.exe sera demandée.'
        self.cm_etat.configure(text=texte, foreground=couleur)

    def costume_mat_dossier(self, module):
        """Game folder containing Game.exe; asked for if needed, then remembered in "jeu"."""
        jeu = self.v['jeu'].get().strip().strip('"')
        if jeu and os.path.isfile(os.path.join(module.dossier_du_jeu(jeu), 'Game.exe')):
            return module.dossier_du_jeu(jeu)
        from tkinter import filedialog
        choix = module.DOSSIER_DEFAUT
        if not (os.path.isfile(os.path.join(choix, 'Game.exe')) and messagebox.askyesno('Dossier du jeu',
                'Game.exe est introuvable dans :\n{}\n\nUtiliser ce dossier ?\n{}\n\n'
                '(le champ « Dossier du jeu » de l’onglet Chemins sera mis à jour)'.format(jeu, choix),
                parent=self)):
            choix = filedialog.askdirectory(parent=self, title='Dossier du jeu (celui qui contient Game.exe)')
        if not choix:
            return None
        if not os.path.isfile(os.path.join(choix, 'Game.exe')):
            messagebox.showerror('Dossier du jeu', 'Game.exe est introuvable dans ce dossier.', parent=self)
            return None
        self.v['jeu'].set(os.path.normpath(choix))
        return module.dossier_du_jeu(choix)

    def costume_mat_occupe(self):
        """True (after telling the user) while Game.exe is being written."""
        if self.cm_travail and self.cm_travail.is_alive():
            messagebox.showinfo('Costume mat', 'Écriture de Game.exe en cours : attendre la fin.', parent=self)
            return True
        return False

    def costume_mat_abandon(self, raison, ensuite=None, detail=''):
        """The matte suit was not applied: say so; before an install, offer to go on anyway."""
        texte = '\n\n'.join(t for t in (raison, detail) if t)
        if ensuite is None:
            if texte:
                messagebox.showwarning('Costume mat', texte, parent=self)
            return
        question = 'Le costume mat n’a pas été appliqué. Installer quand même le costume ?'
        if messagebox.askyesno('Costume mat', '\n\n'.join(t for t in (texte, question) if t), parent=self):
            ensuite()

    def costume_mat_appliquer(self, confirmer=True, ensuite=None):
        """Apply to game button; with `ensuite` (then): called by the install, without asking."""
        if self._costume_mat_occupe():
            return
        try:
            module = self._costume_mat_module()
            dossier = self._costume_mat_dossier(module)
            lu = module.etat_dossier(dossier) if dossier else None
        except Exception as erreur:
            return self._costume_mat_abandon('{}: {}'.format(type(erreur).__name__, erreur), ensuite)
        if not dossier:
            return self._costume_mat_abandon('', ensuite)
        if lu['etat'] == 'non_reconnu':
            return self._costume_mat_abandon('Game.exe non reconnu : ce n’est pas le Game.exe d’origine de '
                                             'Spider-Man 3 PC (2007). Rien n’a été écrit.', ensuite, lu['detail'])
        if lu['etat'] == 'inconnu':
            return self._costume_mat_abandon('Les shaders du costume de Game.exe ont été modifiés par un autre '
                                             'outil. Rien n’a été écrit.', ensuite, lu['detail'])
        cle = self.v['costume_mat_preset'].get()
        if cle not in COSTUME_MAT:
            cle = 'satine'
        if confirmer and lu['preset'] != cle and not messagebox.askyesno('Costume mat',
                'Appliquer le costume mat « {} » à Game.exe ?\n{}\n\nLe jeu doit être fermé. '
                'Une copie de sécurité de Game.exe est faite avant la première écriture.'.format(
                    COSTUME_MAT[cle], lu['exe']), parent=self):
            return
        if ensuite is not None:
            self.fil.put('[costume mat] Case cochée : costume mat appliqué avant l’installation du costume.')
        self._costume_mat_lancer(['installer', cle, '--jeu', dossier], ensuite)

    def costume_mat_retirer(self):
        """Remove matte suit button: put the 3 original shaders back into Game.exe."""
        if self._costume_mat_occupe():
            return
        from tkinter import filedialog
        try:
            module = self._costume_mat_module()
            dossier = self._costume_mat_dossier(module)
            if not dossier:
                return
            # chercher=True: like the "retirer" command, also look at the Game.exe.* copies in the folder
            lu = module.etat_dossier(dossier, chercher=True)
        except Exception as erreur:
            messagebox.showerror('Costume mat', '{}: {}'.format(type(erreur).__name__, erreur), parent=self)
            return
        if lu['etat'] == 'origine':
            messagebox.showinfo('Costume mat', 'Game.exe a déjà le costume d’origine : rien à retirer.', parent=self)
            return
        if lu['etat'] in ('non_reconnu', 'inconnu'):
            messagebox.showwarning('Costume mat', 'Game.exe non reconnu ou modifié par un autre outil : '
                                   'le costume mat ne peut pas en être retiré. Rien n’a été écrit.'
                                   + '\n\n' + lu['detail'], parent=self)
            return
        if not messagebox.askyesno('Costume mat', 'Remettre les 3 shaders d’origine du costume dans Game.exe ?\n'
                'Les autres patchs (caméra, balancement) ne sont pas touchés. Le jeu doit être fermé.', parent=self):
            return
        argv = ['retirer', '--jeu', dossier]
        if not lu['retirable']:
            if not messagebox.askyesno('Costume mat', 'Les shaders d’origine du costume ne sont sauvegardés nulle part '
                    '(Game.exe.costume_mat_origine.bin absent ou incomplet).\n\n'
                    'Indiquer une copie intacte de Game.exe (CD, sauvegarde) ?', parent=self):
                return
            copie = filedialog.askopenfilename(parent=self, title='Copie intacte de Game.exe',
                filetypes=[('Game.exe', 'Game.exe*'), ('Tous les fichiers', '*.*')])
            if not copie:
                return
            argv += ['--origine', os.path.normpath(copie)]
        self._costume_mat_lancer(argv)

    def costume_mat_lancer(self, argv, ensuite=None):
        """costume_mat.main(argv) in a thread; every line goes to the Log, the window stays usable."""
        import threading
        lignes, resultat = [], {}

        def recevoir(ligne):
            # to the Log AND kept for the final message box; refusals in red ("!!" prefix).
            # The texts looked for here and in costume_mat_bilan are those of
            # tools/costume_mat.py (its MARKERS table): change them together. Never add them to
            # studio_language.EN.
            lignes.append(ligne)
            self.fil.put(('!! ' if ligne.startswith(('REFUSED', 'ERROR')) else '    ') + ligne)
        try:
            module = self._costume_mat_module(recevoir)
        except Exception as erreur:
            return self._costume_mat_abandon('{}: {}'.format(type(erreur).__name__, erreur), ensuite)

        def travail():
            try:
                resultat['code'] = module.main(argv)
            except SystemExit as fin:
                resultat['code'] = fin.code
            except Exception as erreur:
                resultat['erreur'] = erreur

        self.cm_synchroniser = False
        self.fil.put('[costume mat] costume_mat.py ' + ' '.join('"%s"' % a if ' ' in a else a for a in argv))
        self.onglets_bas.select(0)
        self.cm_etat.configure(text='Écriture de Game.exe en cours…', foreground='#c80')
        # not a daemon: closing the window during the write waits for the end instead of cutting it
        self.cm_travail = threading.Thread(target=travail, daemon=False)
        self.cm_travail.start()
        self._costume_mat_activer()

        def attendre():
            if self.cm_travail.is_alive():
                self.after(150, attendre)
                return
            self._costume_mat_activer()
            self._costume_mat_rafraichir()
            self._costume_mat_bilan(argv, resultat, lignes, ensuite)
        self.after(150, attendre)

    def costume_mat_bilan(self, argv, resultat, lignes, ensuite=None):
        """End of a write: one green or red line in the Log, one message box, then the requested
        install (ensuite) if Game.exe is in the wanted state. Returns True in that case."""
        erreur, code = resultat.get('erreur'), resultat.get('code')
        exe = os.path.join(argv[argv.index('--jeu') + 1], 'Game.exe')
        if code == 0 and erreur is None:
            if any(ligne.startswith('Nothing to do') for ligne in lignes):
                texte = 'Game.exe était déjà dans cet état : rien n’a été écrit.'
            elif argv[0] == 'installer':
                texte = 'Costume mat « %s » en place dans Game.exe. Relancer le jeu pour le voir.' % COSTUME_MAT.get(argv[1], argv[1])
            else:
                texte = 'Shaders d’origine du costume remis dans Game.exe. Relancer le jeu pour le voir.'
            self.fil.put('OK [costume mat] ' + texte)
            if ensuite:
                ensuite()  # before an install the Log is enough: one message box only, the install's
            else:
                messagebox.showinfo('Costume mat', texte, parent=self)
            return True
        detail = next(('\n'.join(lignes[i:]) for i, ligne in enumerate(lignes)
                       if ligne.startswith(('REFUSED: ', 'ERROR: '))), '\n'.join(lignes[-6:]))
        if erreur is not None:
            detail = '{}: {}'.format(type(erreur).__name__, erreur)
        if isinstance(erreur, PermissionError) or 'Write access denied' in detail:
            tete = ('Écriture refusée dans le dossier du jeu. Fermer le jeu ; s’il est installé sous '
                    'C:\\Program Files (x86), relancer SM3 Studio en administrateur (clic droit > '
                    'Exécuter en tant qu’administrateur).')
        elif 'is running' in detail:
            tete = 'Fermer Spider-Man 3 avant de modifier Game.exe.'
        elif code == 3:
            tete = 'Problème constaté APRÈS écriture : remettre la copie de sécurité %s.' % (exe + '.sauvegarde_patchs_sm3')
        elif 'original version is not available' in detail:
            tete = ('Shaders d’origine introuvables : la copie indiquée n’est pas un Game.exe intact. '
                    'Rien n’a été écrit dans Game.exe.')
        elif code == 1:
            tete = 'Rien n’a été écrit dans Game.exe.'
        else:
            tete = 'Erreur inattendue.'
        self.fil.put('!! [costume mat] ' + tete)
        # Write done but wrong when read back, or unexpected error: no install afterwards.
        # A refusal (code 1) or a PermissionError always happens BEFORE anything is written to
        # Game.exe, so the user may still choose to install the suit.
        if erreur is not None:
            grave = not isinstance(erreur, PermissionError)
        else:
            grave = code != 1
        if grave:
            messagebox.showerror('Costume mat', tete + '\n\n' + detail, parent=self)
        else:
            self._costume_mat_abandon(tete, ensuite, detail)
        return False

    # Install everything on the class. Names starting with _hq_, _venom_ and _costume_mat_ are new
    # methods; the others replace the original methods of sm3_interface.Studio.
    Studio._onglet_general = panel
    Studio._hq_preview = preview
    Studio._charger = load
    Studio._hq_config = config
    Studio._sauver = save
    Studio.convertir = convert
    Studio._args = args
    Studio.installer = install
    Studio._venom_install = venom_install
    Studio._venom_select = venom_select
    Studio._venom_open = venom_open
    Studio.rendre_apercu = render_preview
    Studio._choisir_modele = choose_model
    Studio._costume_mat_panneau = costume_mat_panneau
    Studio._costume_mat_activer = costume_mat_activer
    Studio._costume_mat_module = costume_mat_module
    Studio._costume_mat_rafraichir = costume_mat_rafraichir
    Studio._costume_mat_dossier = costume_mat_dossier
    Studio._costume_mat_occupe = costume_mat_occupe
    Studio._costume_mat_abandon = costume_mat_abandon
    Studio._costume_mat_appliquer = costume_mat_appliquer
    Studio._costume_mat_retirer = costume_mat_retirer
    Studio._costume_mat_lancer = costume_mat_lancer
    Studio._costume_mat_bilan = costume_mat_bilan
    return Studio

