# SPDX-License-Identifier: GPL-3.0-or-later
"""UI localisation. Internal command names and resource identifiers stay unchanged.

The interface (sm3_interface.py, sm3_gui_hq.py) is written in French. When the user picks
English, sm3_studio_hq.py does not import those files: it compiles them and passes the code
objects through localize(), which replaces every string constant that translate() knows, in
every function, before running them. Nothing else changes, so the French and the English
interfaces run the same instructions.

This design has two consequences for anyone editing the interface:
  * a visible message must be ONE string constant. Python 3.14 compiles '%s ... %s' % (a, b)
    into separate fragments that no longer match an EN key; use '...'.format() or %d / a single
    %s instead;
  * every constant is translated, including those used as internal values. A string that is
    both shown and compared (stage names, JSON keys, matte-suit presets such as 'satine') must
    never become an EN key, or the English interface would stop recognising it.

choose() is the small language window shown at start-up; its answer is kept in language.txt
next to the executable.
"""
import types

# French UI string -> English UI string. Exact match first, then the same text without its
# leading/trailing whitespace (see translate()).
EN = {
 'La topologie importée est conservée.':'The imported topology is preserved.',
 'Les triangles déjà présents ne changent pas.':'Existing triangles remain unchanged.',
 'Environ quatre fois plus de triangles, sans arrondir la silhouette.':'About four times as many triangles, without rounding the silhouette.',
 'ARGB8 : sans compression, 8 fois le poids du DXT1. Compatibilité en jeu à tester.':'ARGB8: uncompressed, eight times the size of DXT1. Test compatibility in game.',
 'DXT1 et DXT5 compressent les couleurs par blocs de 4 × 4 pixels.':'DXT1 and DXT5 compress colors in 4 × 4 pixel blocks.',
 'SM3 Studio HQ — qualité intégrée':'SM3 Studio HQ — integrated quality settings',
 'Le gris des sommets doit être compris entre 0 et 255.':'Vertex gray must be between 0 and 255.',
 'Choisir une résolution 2048, 4096 ou 8192.':'Choose a resolution of 2048, 4096 or 8192.',
 'Choisir une compression DXT1, DXT5 ou ARGB8.':'Choose DXT1, DXT5 or ARGB8 compression.',
 'Choisir un mode de géométrie.':'Choose a geometry mode.',
 'Apercu':'Preview','Chemins':'Paths','Convertir':'Convert','General':'General','Journal':'Log','Pose':'Pose','Skinning':'Skinning','Textures':'Textures','Modele':'Model',
 'Général / Qualité':'General / Quality','Personnage cible':'Target character','Personnage à modifier':'Character to replace','Costume noir':'Black Suit',
 'Résolution de l’atlas':'Atlas resolution','Géométrie':'Geometry','Dilatation (pixels)':'Dilation (pixels)','Vertex color — gris':'Vertex color — gray','Matériaux à exclure':'Materials to exclude',
 'Conserver le maillage':'Keep mesh','Retrianguler les quads et ngons':'Retriangulate quads and ngons','Subdiviser sans lissage (×4)':'Subdivide without smoothing (×4)',
 '0 = noir · 128 = gris · 255 = blanc · alpha 255':'0 = black · 128 = gray · 255 = white · alpha 255','0 à 255':'0 to 255',
 'Charger le projet Venom':'Load Venom project','Ouvrir ce projet dans Blender':'Open project in Blender','Restaurer le Venom du jeu':'Restore original Venom',
 'Costume noir : GLB/FBX/OBJ → 000 + 001. Méthode validée avec CJ ; atlas couleur, sans cel shading.':'Black Suit: GLB/FBX/OBJ → 000 + 001. Workflow tested with CJ; full-color atlas, no cel shading.',
 'Analyser le modele':'Analyze model','Modele source':'Source model','Nom du mod':'Mod name','Parcourir':'Browse','Dossier':'Folder','Dossier des textures':'Texture folder',
 'Installer et lancer le jeu':'Install and launch game','Ouvrir le dossier du mod':'Open mod folder','Rendre l apercu':'Render preview','Verifier seulement':'Validate only','Reprendre a l etape':'Resume from stage',
 'Taille de l atlas':'Atlas size','Format de texture':'Texture format','Materiaux a jeter':'Materials to remove','Echelle':'Scale','Decalage  dx,dy,dz':'Offset  dx,dy,dz','Methode':'Method','Voisins melanges':'Blended neighbors','Fondu a l epaule':'Shoulder blend','Nettete (puissance)':'Sharpness (power)','Part minimale d un os':'Minimum bone share',
 'Poser au sol (recale la hauteur exactement sur le vanilla)':'Place on ground (match original model height)',
 'Sans retouche — sauter le redressement des bras et le re-skinning (modele deja dans la pose vanilla)':'Skip adjustments — no arm correction or weight transfer (model already matches the original bind pose)',
 'SM3 Studio — convertir un modele pour Spider-Man 3':'SM3 Studio — convert a model for Spider-Man 3',
 'Choisis un modele source d abord.':'Choose a source model first.','Choisis un modele source.':'Choose a source model.','Une conversion est deja en cours.':'A conversion is already running.',
 'Le mod n a pas encore ete construit:\n%s':'The mod has not been built yet:\n%s','Rien a montrer : construis le mod d abord.\n%s':'Nothing to show: build the mod first.\n%s',
 'Deviner l association':'Guess texture assignments','Lance « Analyser le modele » d abord : il trouve le dossier des textures.':'Run Analyze model first to locate the texture folder.',
 '1 = rigide (articulations qui plient net), 6 = la douceur du vanilla':'1 = rigid (sharp joint bends), 6 = original smoothness','1.0 = l alignement automatique decide':'1.0 = automatic alignment','2048 est le maximum valide':'2048 is the validated maximum',
 'DXT1 : deux fois plus leger, sans alpha':'DXT1: half the size, no alpha','Ancienne methode par segments — gardee pour comparaison':'Legacy segment method — kept for comparison',
 'vanilla = reprendre les poids du jeu. C est le bon choix.':'vanilla = transfer the original game weights. Recommended.',
 'sans effet en methode vanilla':'not used by the vanilla method','elargir si l epaule se plie net':'increase if the shoulder bends sharply','degres — pour un modele couche ou tourne':'degrees — for a sideways or rotated model','vide = detection automatique':'empty = automatic detection','separes par des virgules — capes, decalques, placeholders':'comma-separated — capes, decals, placeholders',
 'remplit les gouttieres ; sans elle, un lisere sur chaque couture':'fills UV gutters to prevent visible seams','(seule « chaine » est lente : c est la cuisson)':'(only the baking stage is slow)',
 'Lance le rendu hors ligne (Blender) sur le mod construit, puis l\'affiche.':'Render the built mod offline in Blender, then display it.',
 'Reglages HQ':'HQ settings','Réglages HQ':'HQ settings','Source Venom':'Venom source','Source Venom introuvable':'Venom source not found','Installation Venom':'Venom installation','Aperçu Venom':'Venom preview',
 'Attendre la fin de la conversion.':'Wait for the conversion to finish.','Le fichier sélectionné n’existe pas.':'The selected file does not exist.',
 'Choisir un GLB, glTF, FBX, OBJ, mesh Venom ou projet Blender préparé.':'Choose a GLB, glTF, FBX, OBJ, Venom mesh or prepared Blender project.',
 'Projet Venom introuvable dans profiles/venom.':'Venom project not found in profiles/venom.',
 'Convertir le modèle pour créer son projet Venom_custom.blend.':'Convert the model to create its Venom_custom.blend project.',
 'Convertir un modèle custom pour créer son aperçu, ou ouvrir le projet natif dans Blender.':'Convert a custom model to create a preview, or open the original project in Blender.',
 'Venom natif restauré.':'Original Venom restored.','Mod Venom installé avec le pack original. Redémarrer le jeu pour tester le rendu.':'Venom mod installed with the original pack. Restart the game to test it.',
 '000 et 001 installés.\nSauvegarde : ':'000 and 001 installed.\nBackup: ','\nSauvegarde : ':'\nBackup: ',
 'pret':'ready','en cours...':'working...','termine':'finished','arrete':'stopped','rien analyse':'not analyzed yet','pas encore rendu':'not rendered yet','analyse en cours...':'analyzing...','installation...':'installing...','rendu en cours...':'rendering...','mesure de la continuite en cours...':'measuring continuity...',
 '(aucune)':'(none)','deja cablee dans le modele':'already linked in the model','decalque (plus de sommets que de triangles)':'decal (more vertices than triangles)','placeholder (bornes toutes nulles)':'placeholder (all bounds are zero)',
 '!! ERREUR INATTENDUE':'!! UNEXPECTED ERROR','!! ARRET : %s':'!! STOPPED: %s','affichage impossible : %s':'cannot display: %s','analyse illisible : %s':'cannot read analysis: %s','appariement illisible : %s':'cannot read assignments: %s',
 '%d association(s) proposee(s)%s — verifie-les, tu peux corriger a la main':'%d suggested assignment(s)%s — review and adjust them manually',', %d peu sure(s)':', %d uncertain',
 '%d materiau(x), %d sans image | %d triangles | %d image(s) dans %s':'%d material(s), %d without images | %d triangles | %d image(s) in %s',
 'Installer « %s » dans le jeu, desactiver tous les autres mods et lancer le jeu ?\n\nUne elevation UAC va etre demandee.':'Install "%s", disable all other mods and launch the game?\n\nWindows will request administrator permission.',
 # Matte suit (Target character tab). NEVER add here the internal keys (satine, mat, attenue,
 # identite, costume_mat...) nor the texts the interface looks for in the output of
 # tools\costume_mat.py (its MARKERS table: 'REFUSED: ', 'ERROR: ', 'Nothing to do',
 # 'Write access denied', 'is running', 'original version is not available').
 'Dossier du jeu':'Game folder','celui qui contient Game.exe':'the folder that contains Game.exe','Tous les fichiers':'All files',
 'Costume mat (réappliqué à chaque installation)':'Matte suit (reapplied on each install)','Costume mat':'Matte suit','Appliquer au jeu':'Apply to game','Retirer le costume mat':'Remove matte suit',
 'Satiné — léger lustre (recommandé)':'Satin — slight sheen (recommended)','Mat — ni brillance ni reflet':'Matte — no shine, no reflection',
 'Atténué — reflets du jeu adoucis':'Softened — gentler game shine','Identité — aucun changement (test)':'Identity — no change (test)',
 'Outil introuvable : %s':'Tool not found: %s',
 'Game.exe introuvable dans « %s » : indiquer le dossier du jeu (onglet Chemins).':'Game.exe not found in "%s": set the game folder (Paths tab).',
 'Game.exe non reconnu (autre version, ou exe agrandi par un autre outil) : le costume mat ne peut pas s’y appliquer.':'Unrecognized Game.exe (another version, or enlarged by another tool): the matte suit cannot be applied to it.',
 'Game.exe : shaders du costume modifiés par un autre outil : le costume mat ne peut pas s’y appliquer.':'Game.exe: suit shaders modified by another tool: the matte suit cannot be applied to it.',
 'Game.exe : costume d’origine (pas de costume mat).':'Game.exe: original suit (no matte patch).',
 'Game.exe : costume mat incomplet (écriture interrompue ?) : appliquer ou retirer pour remettre de l’ordre.':'Game.exe: incomplete matte patch (interrupted write?): apply or remove it to fix this.',
 'Game.exe : costume mat « %s » installé.':'Game.exe: matte suit "%s" installed.',
 'Game.exe : costume mat avec des valeurs libres (%s).':'Game.exe: matte suit with custom values (%s).',
 'Game.exe : costume mat avec des valeurs différentes selon les shaders.':'Game.exe: matte suit with different values per shader.',
 'Retrait : une copie intacte de Game.exe sera demandée.':'Removal will ask for an intact copy of Game.exe.',
 'Game.exe est introuvable dans :\n{}\n\nUtiliser ce dossier ?\n{}\n\n(le champ « Dossier du jeu » de l’onglet Chemins sera mis à jour)':
  'Game.exe was not found in:\n{}\n\nUse this folder?\n{}\n\n(the Game folder field in the Paths tab will be updated)',
 'Dossier du jeu (celui qui contient Game.exe)':'Game folder (the one that contains Game.exe)','Game.exe est introuvable dans ce dossier.':'Game.exe is not in this folder.',
 'Écriture de Game.exe en cours : attendre la fin.':'Game.exe is being written: wait for it to finish.','Écriture de Game.exe en cours…':'Writing Game.exe…',
 'Le costume mat n’a pas été appliqué. Installer quand même le costume ?':'The matte suit was not applied. Install the suit anyway?',
 '[costume mat] Case cochée : costume mat appliqué avant l’installation du costume.':'[costume mat] Box checked: matte suit applied before installing the suit.',
 'Game.exe non reconnu : ce n’est pas le Game.exe d’origine de Spider-Man 3 PC (2007). Rien n’a été écrit.':'Unrecognized Game.exe: this is not the original Spider-Man 3 PC (2007) Game.exe. Nothing was written.',
 'Les shaders du costume de Game.exe ont été modifiés par un autre outil. Rien n’a été écrit.':'The suit shaders in Game.exe were modified by another tool. Nothing was written.',
 'Appliquer le costume mat « {} » à Game.exe ?\n{}\n\nLe jeu doit être fermé. Une copie de sécurité de Game.exe est faite avant la première écriture.':
  'Apply the matte suit "{}" to Game.exe?\n{}\n\nThe game must be closed. A backup copy of Game.exe is made before the first write.',
 'Game.exe a déjà le costume d’origine : rien à retirer.':'Game.exe already has the original suit: nothing to remove.',
 'Game.exe non reconnu ou modifié par un autre outil : le costume mat ne peut pas en être retiré. Rien n’a été écrit.':'Game.exe is unrecognized or was modified by another tool: the matte suit cannot be removed from it. Nothing was written.',
 'Remettre les 3 shaders d’origine du costume dans Game.exe ?\nLes autres patchs (caméra, balancement) ne sont pas touchés. Le jeu doit être fermé.':
  'Restore the 3 original suit shaders in Game.exe?\nOther patches (camera, swinging) are not touched. The game must be closed.',
 'Les shaders d’origine du costume ne sont sauvegardés nulle part (Game.exe.costume_mat_origine.bin absent ou incomplet).\n\nIndiquer une copie intacte de Game.exe (CD, sauvegarde) ?':
  'The original suit shaders are not saved anywhere (Game.exe.costume_mat_origine.bin missing or incomplete).\n\nSelect an intact copy of Game.exe (CD, backup)?',
 'Copie intacte de Game.exe':'Intact copy of Game.exe',
 'Game.exe était déjà dans cet état : rien n’a été écrit.':'Game.exe was already in this state: nothing was written.',
 'Costume mat « %s » en place dans Game.exe. Relancer le jeu pour le voir.':'Matte suit "%s" applied to Game.exe. Restart the game to see it.',
 'Shaders d’origine du costume remis dans Game.exe. Relancer le jeu pour le voir.':'Original suit shaders restored in Game.exe. Restart the game to see it.',
 'Écriture refusée dans le dossier du jeu. Fermer le jeu ; s’il est installé sous C:\\Program Files (x86), relancer SM3 Studio en administrateur (clic droit > Exécuter en tant qu’administrateur).':
  'Write access denied in the game folder. Close the game; if it is installed under C:\\Program Files (x86), restart SM3 Studio as administrator (right-click > Run as administrator).',
 'Fermer Spider-Man 3 avant de modifier Game.exe.':'Close Spider-Man 3 before modifying Game.exe.',
 'Problème constaté APRÈS écriture : remettre la copie de sécurité %s.':'Problem detected AFTER writing: restore the backup copy %s.',
 'Shaders d’origine introuvables : la copie indiquée n’est pas un Game.exe intact. Rien n’a été écrit dans Game.exe.':'Original shaders not found: the selected copy is not an intact Game.exe. Nothing was written to Game.exe.',
 'Rien n’a été écrit dans Game.exe.':'Nothing was written to Game.exe.','Erreur inattendue.':'Unexpected error.',
}

def translate(text):
    """English version of one French UI string, or the string itself when it is unknown."""
    # Long help paragraphs are recognised by their first words, so that line breaks and
    # indentation inside them do not have to match exactly. (Until 2026-10-12 four more keys
    # matched the French docstrings of the window, which nothing displays; those docstrings are
    # now in English in sm3_interface.py and the keys were removed.)
    paragraphs={
      "Pourquoi 'vanilla'":'Original game weights are hand-painted. This method blends weights from nearby original vertices. Align the source model with the original bind pose first. Increase neighbors for smoother joints; check scale and rotation if limbs stretch.',
      'Deviner mesure':'Guess assignments measures color continuity across adjacent triangles. A score near 0.05 is excellent; above 0.5, choose manually. Always review suggested assignments.',
      'Venom : importer':'Venom: import a GLB, glTF, FBX or OBJ, then Convert.\nRecognized rigs use source weights and bind-pose adaptation; other models use spatial weight transfer.\nNative Venom format: 256-color palette, ARGB8 indices, 2048 × 1024 texture.\nOriginal Venom shader; test new textures in game. No native vertex color.',
    }
    for prefix,value in paragraphs.items():
        if text.strip().startswith(prefix):return value
    if text in EN:return EN[text]
    # Same text with surrounding spaces ('  Convertir  ' is a padded button label): translate
    # the core and put the original padding back.
    stripped=text.strip()
    if stripped in EN:return text[:len(text)-len(text.lstrip())]+EN[stripped]+text[len(text.rstrip()):]
    return text

def localize(code):
    """Copy of a compiled code object with its string constants translated, recursively
    (nested functions and classes are code objects stored among the constants)."""
    def item(x):
        if isinstance(x,types.CodeType):return localize(x)
        if isinstance(x,str):return translate(x)
        if isinstance(x,tuple):return tuple(item(v) for v in x)
        return x
    return code.replace(co_consts=tuple(item(x) for x in code.co_consts))

def choose(folder):
    """Ask for the interface language ('fr' or 'en'), pre-selecting the last choice saved in
    <folder>/language.txt, and save the new choice there. Closing the window quits."""
    import tkinter as tk
    from tkinter import ttk
    from pathlib import Path
    path=Path(folder)/'language.txt'
    value=path.read_text().strip() if path.exists() else 'fr'
    window=tk.Tk();window.title('SM3 Studio — Language / Langue');window.resizable(False,False)
    selected=tk.StringVar(value='English' if value=='en' else 'Français')
    ttk.Label(window,text='Language / Langue').pack(padx=45,pady=(20,8))
    ttk.Combobox(window,textvariable=selected,values=('Français','English'),state='readonly').pack(padx=30)
    accepted=[]
    def confirm():
        accepted.append('en' if selected.get()=='English' else 'fr')
        try:path.write_text(accepted[0])
        except OSError:pass
        window.destroy()
    ttk.Button(window,text='OK',command=confirm).pack(pady=18)
    window.mainloop()
    if not accepted:raise SystemExit(0)
    return accepted[0]
