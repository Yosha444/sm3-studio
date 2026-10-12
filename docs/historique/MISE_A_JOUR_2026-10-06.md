> *Historical note, kept in French as it was written on 2026-10-06; see [README.md](README.md) in this folder for an English summary. The current documentation is the repository's README.md and docs/: where they disagree, they win.*

# Mise à jour du 2026-10-06 — textures propres, poings serrés, slot `topweb`, costume mat

Ce qui a changé dans SM3 Studio HQ les 5 et 6 octobre 2026, pourquoi, et comment le régler.

| changement | fichier(s) | lu depuis | effet en jeu |
|---|---|---|---|
| encodeur DXT haute qualité | `tools\sm3\dxtenc.py` | disque | fini les blocs sombres le long des fils de toile |
| chaîne de texture refaite (lissage, mips, fond, normale) | `tools\png2tex.py` | disque | texture « propre », relief de normale fidèle |
| réglages des textures | `texture_qualite.json` (nouveau) | disque, à chaque texture | réglable sans rien reconstruire |
| contrôle de l'atlas noir aligné sur l'encodage réel | `tools\blacksuit_package.py` | disque | plus de faux échec du contrôle |
| auto-tests de l'encodeur et de la chaîne | `tools\sm3\dxtenc_selftest.py` (nouveau) | disque | — |
| poings serrés : les 30 os de doigts | `tools\mains_poings.py` (nouveau), `tools\winding_fix.py` | disque | les doigts se plient, poings fermés au repos |
| slot de matériau du corps `topweb` | `sm3_convertir.py` | **dans l'exe** (reconstruit le 05/10) | corps brillant possible (option) |
| case « Costume mat » (section 9) | `sm3_gui_hq.py`, `studio_language.py` ; `tools\costume_mat.py` + `.json` (nouveaux) | **dans l'exe** (reconstruit le 06/10) ; outil sur le disque | costume mat/satiné, tous les costumes, sans ligne de commande |
| installation Costume noir / Venom depuis l'exe | `SM3Studio.spec` (`configparser` embarqué) | **dans l'exe** (06/10) | fin de « No module named 'configparser' » |

Retours en jeu du 06/10 : textures — « c'est mieux » ; mains — « les poings sont serrés ».

---

## 0. Mettre à jour une installation existante

1. **Fermer SM3 Studio.exe.**
2. Remplacer `SM3 Studio.exe`, le dossier `tools\` entier, et ajouter `texture_qualite.json` à la
   racine (à côté de `qualite.json`). Garder votre `sm3_studio.json` et votre `language.txt` :
   ils ne sont pas dans le zip (chemins personnels, choix de langue).
3. **Relancer SM3 Studio.exe.** ⚠️ Un Studio déjà ouvert garde en mémoire l'ancien `png2tex`,
   l'ancien `dxtenc` et l'ancien `winding_fix` : tant qu'il n'est pas relancé, il construit avec
   les anciens outils, sans le dire.

Rien à reconstruire : tout ce qui a changé le 06/10 vit dans `tools\` et `texture_qualite.json`,
que l'exe lit sur le disque. Seule l'option `--slot topweb` (05/10) touche un module embarqué ;
l'exe livré la contient — vérifié : les 14 modules `.py` de la racine et le
`sm3_studio_original.marshal` embarqués dans l'exe sont identiques, octet pour octet, aux
fichiers livrés à côté.

**Ajout du soir du 06/10 (case Costume mat, section 9)** : l'exe a été reconstruit. Remplacer aussi
`SM3 Studio.exe` et ajouter `tools\costume_mat.py`, `tools\costume_mat_shaders.json` et
`tools\costume_mat_LISEZMOI.txt`. Vérifié : les 15 modules `.py` et le `.marshal` embarqués dans
le nouvel exe sont identiques, octet pour octet, aux fichiers livrés à côté.

`SM3 Studio Corrige.exe` (présent dans le zip précédent) était une copie de l'exe du 09/09, sans
la palette 48 os ni le reste : il n'est plus livré, ne plus l'utiliser.

Ce zip est aussi le premier à contenir la mise à jour du 14/09 (`RIG_UPDATE.md` : palette 48 os,
réparation topologique, carte de normales générée) et le dossier `correctifs_blender\` (à copier
à la main dans les extensions Blender, voir son `LISEZMOI.md`). La limite « 32 os » citée dans
`RVB_UPDATE.md` est périmée : c'est 48 (voir `RIG_UPDATE.md`).

---

## 1. Encodeur DXT haute qualité — `tools\sm3\dxtenc.py`

**Le défaut.** Le « bruit » sur le costume ne venait ni de l'image ni du moteur, mais de notre
encodeur DXT : extrémités de bloc prises sur les texels de luminance min/max, couleurs 565
**tronquées**, aucun raffinement. Résultat : des carrés 4×4 sombres et désaturés le long des
toiles, des traînées grises aux coutures.

**La correction.** Pour chaque bloc 4×4, plusieurs couples d'extrémités sont essayés (axe
principal, axe rentré, coins de la boîte, couleur unique optimale, **et le choix exact de
l'ancien encodeur**), raffinés par moindres carrés, arrondis 565 au plus proche ; on garde celui
dont le bloc **décodé** a la plus petite erreur. Le nouvel encodeur ne peut donc jamais faire
pire que l'ancien, bloc par bloc.

| mesure (atlas rouge 4096, décodeur indépendant) | ancien | nouveau |
|---|---|---|
| mip 0 | — | +4,0 dB |
| mips 1 à 6 | — | +4,2 à +4,8 dB |
| fils de toile, mip 2 | 26,1 dB | 31,6 dB |
| aplats : erreur max | 7 | 1 |
| chaîne DXT5 4096 complète | — | ~10 s |

L'ancien encodeur est conservé tel quel (`dxt1_encode_rapide` / `dxt5_encode_rapide`) :
`"encodeur": "rapide"` dans `texture_qualite.json` le remet.

---

## 2. Chaîne de texture — `tools\png2tex.py`

**Textures couleur** (atlas du costume), dans l'ordre :

1. **Lissage du mip 0 qui respecte les bords** : filtre bilatéral en CIELAB, appliqué seulement
   hors du fond. Il efface le bruit de cuisson que le DXT changeait en blocs sales, sans toucher
   aux fils de toile (fort écart de couleur). Jamais en ARGB8 (sans perte : le mip 0 doit rester
   le PNG exact).
   **Garde du noir** : sous L\* 0,5 le texel reste brut, au-dessus de L\* 3 il est lissé en
   entier, fondu entre les deux. Sans elle, les interstices presque noirs du symbiote étaient
   lavés en gris (contraste 88 % → 35 %) ; avec : 88,6 %, et le rouge ne bouge que sur 0,36 % de
   ses texels.
2. **Mips en flottant** d'un niveau à l'autre (plus d'aller-retour 8 bits), moyenne 2×2 en sRGB
   (défaut, comme avant) ou en lumière linéaire (option).
3. **Masque du fond calculé une fois au mip 0** (RGB exactement 0,0,0, ou alpha 0 si l'image a
   un vrai alpha), propagé aux mips ; seuls ces texels sont remplis avant chaque réduction.
   L'ancien seuil (R+G+B ≤ 6) écrasait les texels très sombres du corps : supprimé. Un atlas
   déjà dilaté (moins de 5 % de fond) n'est pas touché.
4. Encodeur DXT haute qualité (section 1).

**Carte de normales** (`0x61DCA273`, X dans l'alpha, Y dans le vert, toujours DXT5) :
mips calculés en flottant, moyenne 2×2 de x et de y puis **fondu linéaire** du relief par niveau
— exactement la chaîne de la normale rouge validée en jeu. L'ancienne réduction passait par
Pillow sur une image RGBA, qui **pré-multiplie par l'alpha** : or l'alpha est ici nx, donc ny
était corrompu à chaque niveau (jusqu'à 61 niveaux d'écart).

**Atlas du costume noir (`0x0133FD92`) : pas de lissage par défaut.** Tout le symbiote tient sous
L\* 10 ; le filtre y aplatissait le ton principal. Sans lissage, c'est sa version la plus fidèle
mesurée à tous les mips (mip 2 : 37,9 dB / ΔE 1,80, contre 35,4 / 2,48 pour la version lissée).

---

## 3. Régler : `texture_qualite.json`

Le fichier est à la racine de l'outil. Il est **relu à chaque écriture de texture** : une
modification prend effet au build suivant, sans reconstruire l'exe (mais relancer Studio s'il
était ouvert pendant une mise à jour de `tools\`). Fichier absent, clé absente ou valeur
invalide : valeur par défaut, et une ligne `[png2tex] reglage ... invalide` dans le journal.
Le bloc `_aide` du fichier redit tout cela ; il est ignoré par l'outil.

| clé | défaut | valeurs admises | effet |
|---|---|---|---|
| `encodeur` | `"hq"` | `"hq"`, `"rapide"` | encodeur DXT (section 1) |
| `lissage.actif` | `true` | `true` / `false` | lissage bilatéral du mip 0 couleur |
| `lissage.rayon` | `4` | entier 0 à 16 | taille du filtre en texels (0 = rien) |
| `lissage.sigma_spatial` | `3` | 0,1 à 50 | portée spatiale, en texels |
| `lissage.sigma_couleur` | `5` | 0,1 à 100 (ΔE) | plus grand = lisse aussi des écarts de couleur plus forts |
| `lissage.garde_noir` | `[0.5, 3]` | `[L0, L1]`, 0 à 100, L0 ≤ L1 | brut sous L0, lissé au-dessus de L1 ; `[0, 0]` = pas de garde |
| `mips_couleur` | `"srgb"` | `"srgb"`, `"lineaire"` | moyenne des mips couleur |
| `normale_fondu` | `[1, 1, 0.75, 0.5, 0.3, 0.15, 0]` | liste de nombres 0 à 1 | relief gardé par niveau de mip (le dernier vaut pour les suivants) |
| `normale_renormaliser` | `false` | `true` / `false` | `true` : ~20 % de relief en plus aux mips 2-5, au-delà de la chaîne validée |
| `dilatation.actif` | `true` | `true` / `false` | remplissage du fond avant chaque réduction |
| `dilatation.anneaux` | `2` | entier 0 à 64 | texels remplis par niveau |
| `dilatation.fond_min_pct` | `5` | 0 à 100 | sous cette part de fond, l'atlas est tenu pour déjà dilaté |
| `par_texture` | `{"0x0133FD92": {"lissage": {"actif": false}}}` | objet : clé = hash, valeur = les clés ci-dessus | exceptions pour UNE texture |

⚠️ `par_texture` écrit dans le fichier **remplace** la table par défaut : `{}` = aucune
exception (l'atlas noir serait alors lissé comme les autres).

Exemples :

```json
"encodeur": "rapide"                                   revenir à l'ancien encodeur
"lissage": {"actif": false}                            plus aucun lissage
"lissage": {"actif": true, "rayon": 6, "sigma_couleur": 8}   lisser plus fort
"mips_couleur": "lineaire"                             mips physiquement justes
"normale_fondu": [1, 1, 1, 0.75, 0.5, 0.25, 0]          plus de relief vu de loin
"par_texture": {"0x0133FD92": {"lissage": {"actif": true}}}  essayer l'atlas noir lissé
```

Ligne de commande (sans Studio) : `python tools\png2tex.py image.png sortie.tex --hash 0x8E661B33
--dxt5 [--genre couleur|normale] [--reglages autre_fichier.json]`.

---

## 4. Contrôle de l'atlas noir — `tools\blacksuit_package.py`

`controle_texture` compare le `.tex` écrit à sa source. Depuis que `png2tex` lisse, la référence
n'est plus le PNG brut mais **le mip 0 exact que `png2tex` encode** (`preparer_image`), préparé
avec le **hash lu dans l'en-tête du `.tex`** et le **même encodeur** que l'écriture. Sinon le
contrôle aurait pris le lissage voulu pour une perte, ou comparé un `.tex` brut à une référence
lissée.

---

## 5. Poings serrés : les 30 os de doigts — `tools\mains_poings.py`

**Le défaut.** Au repos, Spider-Man serre les poings ; les costumes convertis gardaient les mains
**ouvertes**. Les doigts n'avaient plus que 10 os sur 30 (les bases) : toutes les phalanges
sautaient, faute de place dans la palette d'une section (48 os au plus ; un corps + 30 doigts en
demande ~55). Le transfert de poids au plus proche voisin attribuait en plus 29 à 38 % des
sommets d'un doigt au doigt **voisin**.

**La correction**, appelée automatiquement à la fin des chaînes rouge ET noire par
`tools\winding_fix.py`, sur les 4 maillages joueur produits par Studio :

1. **Doigt par doigt, par la topologie** : chaque doigt est reconnu comme un morceau de surface,
   ses sommets reçoivent le profil de poids du vanilla le long de la chaîne d'os de CE doigt
   (phalanges rigides, un anneau de mélange à chaque articulation), avec un fondu vers les poids
   existants dans la paume. Tout sommet hors des doigts garde ses octets de poids : le corps ne
   bouge pas d'un bit. Test du poing hors jeu : écart au suivi rigide des phalanges 38,7 mm →
   3,4 mm ; bout des doigts à 44 mm de la paume (vanilla 44, avant 118).
2. **Costume rouge** (`0xAC92103D/E`) : xeSM3 choisit le matériau d'une section **par
   référence**. Une main est détachée dans sa propre section, de même référence que le corps
   (sommets de couture dupliqués à l'identique : aucune fente possible) → **30 os de doigts sur
   30**.
3. **Costume noir** (`0xABE79B1C/D`) : xeSM3 choisit le matériau **par index de section** (seule
   la section 3 porte la toile) : une seule vraie section, donc 48 os au plus. On replie les os
   les moins visibles d'un poing fermé (orteils, puis bouts d'annulaire et d'auriculaire...) →
   22 os de corps + **26 de doigts** (les bouts d'annulaire et d'auriculaire suivent leur
   phalange du milieu). Le pouce du squelette noir n'a pas la pose de celui du rouge (+15° et
   +44°) : les seuls sommets dont les poids de doigts changent sont reposés sur ce squelette.

**Limite.** La reconnaissance exige cinq doigts séparés par main, posés comme le vanilla
(c'est le cas de photoreal). Sinon la main est laissée telle que la chaîne l'a produite et le
journal l'écrit en `!!`. Un échec n'arrête **jamais** la conversion. Les exports RvB (poids
natifs) ne sont jamais touchés. Une trace `.mains.npz` est écrite à côté du maillage, dans le
dossier de build (jamais dans le mod).

**Désactiver** :

- un maillage à la main : `python tools\winding_fix.py <fichier.mesh> --sans-mains` ;
- toute une conversion : variable d'environnement `SM3_MAINS_POINGS=0`, posée **avant** de lancer
  Studio, par exemple depuis une invite de commandes ouverte dans le dossier de l'outil :

```bat
set SM3_MAINS_POINGS=0
"SM3 Studio.exe"
```

Le traiter seul : `python tools\mains_poings.py <entree.mesh> <sortie.mesh>` (voir `--help` ; pour
un 001, `--poids-de <trace .npz du 000>`). Dépendances : NumPy, le `sm3_format.py` du toolkit
Blender installé, et le dossier `vanilla\` de l'outil (squelettes rouge et noir).

---

## 6. Slot de matériau du corps : `--slot topweb` (exe reconstruit le 05/10)

Le corps du maillage 000 rouge peut être rebasculé sur un autre matériau du jeu, après export :

| `--slot` | matériau | brillance | tache | ambiance et rim | textures |
|---|---|---|---|---|---|
| `spider` (défaut) | `0x614` | 0,20 | 13 | éteints | atlas `ch_spiderman_spider` |
| `sideweb` | `0x37C` | 0 (mat) | — | allumés | atlas aussi livré sous `_grey` `0x06F18556` |
| `topweb` | `0x640` | 1,00 | 8 (large, un voile) | allumés, un peu de reflet | atlas aussi livré sous `_grey` `0x06F18556` |

Le relief de la carte de normales fonctionne dans les trois cas. Le LOD 001 n'est pas touché
(ses seules alternatives sont tuilées ×100). L'option n'existe qu'en **ligne de commande** :

```bat
"SM3 Studio.exe" --src "C:\chemin\modele.glb" --nom MonMod --slot topweb
```

Le rendu **mat** validé en jeu le 06/10 ne vient pas de cette option mais du correctif des
shaders de `Game.exe` (préréglage « satine »), livré à part avec les correctifs du jeu — et
désormais intégré à Studio (section 9).

---

## 7. Auto-tests

```bat
set SM3_SELFTEST_RAPIDE=1
python tools\sm3\dxtenc_selftest.py
```

Tout est décodé par le décodeur indépendant `tools\sm3\texfind.py`, jamais par l'encodeur : blocs
synthétiques, extraits de l'atlas rouge (si `build\essai_mains\atlas_dilate.png` existe, sinon
ignorés ; autre fichier : variable `SM3_ATLAS_ROUGE`), tailles 1×1 à 4096, normale sans
pré-multiplication, fond et garde du noir, `write_tex` de bout en bout, lecture de
`texture_qualite.json` (absent / partiel / invalide), `par_texture` et
`blacksuit_package.controle_texture`. Sans `SM3_SELFTEST_RAPIDE` : 105 contrôles, ~1 min, dont
la chaîne 4096 complète.

Résultats au moment de ce zip (2026-10-06, Python 3.14.7, NumPy 2.5.2, Pillow 12.3.0) :

- `dxtenc_selftest.py` en mode rapide : **102 contrôles, 0 échec** (11 s) ;
- compilation (`py_compile`) : **47 / 47** `.py` de `tools\` et **15 / 15** de la racine.

---

## 8. Fichiers de cette mise à jour

- modifiés : `SM3 Studio.exe` (05/10), `sm3_convertir.py` (05/10, embarqué dans l'exe),
  `tools\png2tex.py`, `tools\sm3\dxtenc.py`, `tools\blacksuit_package.py`, `tools\winding_fix.py`,
  `README_EN.txt` et `COSTUME_NOIR.md` (un renvoi vers ce fichier) ;
- ajoutés : `texture_qualite.json`, `tools\mains_poings.py`, `tools\sm3\dxtenc_selftest.py`,
  `MISE_A_JOUR_2026-10-06.md`.
- costume mat (soir du 06/10) : modifiés `SM3 Studio.exe` (reconstruit), `sm3_gui_hq.py` et
  `studio_language.py` (embarqués), `README_EN.txt` ; ajoutés `tools\costume_mat.py`,
  `tools\costume_mat_shaders.json`, `tools\costume_mat_LISEZMOI.txt`. Ancien exe gardé à côté :
  `SM3 Studio.exe.avant_costume_mat_20261006`.

---

## 9. Costume mat (case dans l'interface)

La brillance « huilée » du costume n'est pas dans les textures du mod : `Game.exe` la calcule
lui-même, dans les 3 pixel shaders de la classe `sm_phatspiderman`, **commune au costume rouge, au
costume noir et à tous les costumes convertis par Studio**. Le correctif `SM3_Costume_Mat` (validé
en jeu le 06/10, préréglage « satine ») est maintenant pilotable depuis Studio, sans ligne de
commande.

**Où.** Onglet **Personnage cible** (le premier), sous la ligne « Costume noir » :

- la case **Costume mat (réappliqué à chaque installation)** ;
- la liste des préréglages ;
- **Appliquer au jeu** (grisé tant que la case n'est pas cochée) et **Retirer le costume mat**
  (toujours disponible) ;
- une ligne d'état grise, qui lit `Game.exe` sans jamais l'écrire : « costume d'origine »,
  « costume mat « Satiné… » installé », « Game.exe introuvable dans … », « non reconnu »...

| préréglage | Ks | As | Ke | Ae | effet |
|---|---|---|---|---|---|
| **Satiné** (défaut) | 0 | 0,06 | 0 | 0 | léger lustre constant, aucun reflet — validé en jeu |
| Mat | 0 | 0 | 0 | 0 | ni brillance ni reflet |
| Atténué | 0,35 | 0 | 0,25 | 0 | garde les nuances du jeu, en beaucoup plus doux |
| Identité (test) | 1 | 0 | 1 | 0 | patch posé, aucun changement visible |

(brillance finale = sat(brillance du jeu × Ks + As), reflet final = sat(reflet du jeu × Ke + Ae).)

**Utilisation.**

1. Fermer le jeu.
2. Onglet **Chemins** : « Dossier du jeu » = le dossier qui contient `Game.exe`. S'il est faux
   (c'est le cas de l'ancien défaut `C:\Program Files (x86)\Activision\Spider-Man 3`), le premier
   clic sur « Appliquer » ou « Retirer » propose `C:\Games\Spider-man 3` (ou un sélecteur de
   dossier) et **met le champ à jour**. Ce champ sert aussi aux installations Costume noir et
   Venom : elles visent alors, elles aussi, le vrai dossier du jeu.
3. Cocher la case, choisir le préréglage, **Appliquer au jeu**. Une confirmation n'est demandée que
   si le préréglage change. Le Journal affiche chaque ligne du correctif ; une boite dit le
   résultat.
4. Relancer le jeu.

**Case cochée** : le préréglage est réappliqué **avant chaque installation de costume** (bouton
rouge « Installer et lancer le jeu » pour Spider-Man, installation Costume noir), sans
confirmation ; s'il est déjà en place, rien n'est écrit (« Rien a faire » dans le Journal). En cas
de refus (jeu lancé...), Studio demande s'il faut installer le costume quand même. Venom n'est pas
concerné (autre shader). **Décocher ne retire rien** : seul « Retirer le costume mat » remet les
3 shaders d'origine.

**Premier lancement** : si `sm3_studio.json` ne connaît pas encore la case, elle reprend l'état
réel de `Game.exe` à la première lecture (ex. satiné déjà installé → case cochée, Satiné), tant
qu'on n'y a pas touché. Ensuite la case et le préréglage sont enregistrés dans `sm3_studio.json`
(`costume_mat`, `costume_mat_preset`).

**Sûreté** (c'est le correctif testé qui écrit, pas l'interface) :

- `tools\costume_mat.py` est le script du zip `SM3_Costume_Mat`, ligne de commande **identique**
  (même aide, mêmes sorties, mêmes fichiers produits, vérifié), plus une fonction de lecture
  `etat_dossier()` pour la ligne d'état. Studio n'écrit que par `costume_mat.main([...])`, comme
  la ligne de commande : mêmes contrôles (taille et point d'entrée de `Game.exe`, jeu lancé,
  shaders inconnus), mêmes sauvegardes, relecture et contrôle « 0 octet modifié hors des
  3 shaders ».
- Seules les 3 zones des shaders sont écrites : le patch **caméra** et le **balancement** ne sont
  pas touchés (vérifié octet pour octet sur une copie de l'exe caméra « proto » + satiné).
- Avant la toute première écriture : `Game.exe.costume_mat_origine.bin` (les 3 shaders d'origine,
  nécessaire pour « Retirer ») et, une seule fois, `Game.exe.sauvegarde_patchs_sm3` (copie
  complète de l'exe tel qu'il était). Sur un jeu déjà patché « satiné » en ligne de commande, cette
  copie complète sera prise au premier vrai changement : c'est normal.
- L'écriture tourne dans un thread : l'interface reste libre ; boutons grisés pendant l'écriture.
  Fermer la fenêtre pendant l'écriture attend sa fin au lieu de la couper.
- Les messages du correctif vont au Journal (refus en rouge, réussite en vert), jamais dans la
  sortie de la conversion : les deux peuvent tourner en même temps.

**Messages.**

| situation | ce que dit Studio |
|---|---|
| jeu lancé | Fermer Spider-Man 3 avant de modifier Game.exe |
| dossier ou exe non inscriptible (Program Files...) | relancer SM3 Studio en administrateur (clic droit > Exécuter en tant qu'administrateur) |
| autre version de `Game.exe` | Game.exe non reconnu ; rien n'a été écrit |
| shaders modifiés par un autre outil | idem, rien n'a été écrit |
| « Retirer » sans sauvegarde des shaders d'origine | propose de choisir une **copie intacte de Game.exe** (CD, sauvegarde) |
| copie choisie déjà patchée | shaders d'origine introuvables ; rien n'a été écrit |
| problème constaté APRÈS écriture (relecture) | erreur : remettre `Game.exe.sauvegarde_patchs_sm3` |

Le détail technique sous la première phrase reste en français dans l'interface anglaise : c'est la
sortie du script.

**Ligne de commande** (inchangée, sans Studio) : `python tools\costume_mat.py etat`,
`installer satine|mat|attenue|identite` ou 4 valeurs, `retirer [--origine copie]`, option
`--jeu "dossier"` ; voir `tools\costume_mat_LISEZMOI.txt`.

**Correctif lié : installations Costume noir et Venom depuis l'exe.** `tools\blacksuit_deploy.py`
et `tools\venom_install.py` importent `configparser`, que l'exe n'embarquait pas : depuis l'exe,
ces deux boutons échouaient sur « No module named 'configparser' » (depuis Python, ils
marchaient). Ajouté à `SM3Studio.spec` ; présent dans l'exe du 06/10 (vérifié).

**Interface anglaise.** Tous les libellés et boites de la case passent par `studio_language.py`
(le libellé « Dossier du jeu » de l'onglet Chemins, jusqu'ici non traduit, l'est aussi). En
anglais, l'onglet Personnage cible fixe la hauteur du carnet d'options : la case l'agrandit de
62 px (le Journal perd autant). En français, rien ne bouge (l'onglet Skinning reste le plus haut).

**Tests (06/10, Python 3.14.7, sans fenêtre visible, sur des COPIES de Game.exe — jamais sur
`C:\Games`)** : interface 98 contrôles en français et 98 en anglais, 0 échec (widgets, case et
préréglage, enregistrement et relecture de `sm3_studio.json`, premier lancement, appliquer,
changer, retirer, caméra intacte, jeu lancé simulé, exe en lecture seule, dossier non inscriptible
simulé, exe non reconnu, shader modifié, sauvegarde absente avec et sans copie intacte, problème
après écriture simulé, choix du dossier, installation Costume noir / Spider-Man / Venom, écriture
en parallèle d'une « conversion ») ; correctif 26 contrôles (ligne de commande identique au zip,
`etat_dossier` sur les 7 états) ; `py_compile` 15/15 racine et 48/48 `tools\` ; exe lancé une fois
en ligne de commande (`--help`) pour vérifier qu'il démarre. Les scripts d'essai sont dans
`Documents\SM3-modding-projet-complet\sm3_studio_build\essais_costume_mat\`.

**Revenir en arrière** : remettre `SM3 Studio.exe.avant_costume_mat_20261006` sous le nom
`SM3 Studio.exe` (les fichiers `tools\costume_mat*` peuvent rester, l'ancien exe les ignore). Les
originaux de `sm3_gui_hq.py`, `studio_language.py`, `README_EN.txt`, de ce fichier et de la recette
sont dans `Documents\SM3-modding-projet-complet\sauvegardes\2026-10-06_studio_costume_mat\originaux\`.

## 10. Costume noir sans bruit (fin de soirée, validé en jeu : « ça fonctionne »)

Le costume noir gardait du grain alors que le rouge était propre. Deux causes, mesurées sur un
rendu éclairé (lustre satiné compris) :

- **le motif d'écailles / pointillés de l'atlas** : sur un fond presque noir, il représentait
  ~50 % de contraste relatif (14,6 % de bruit rendu contre 5,4 % sur le rouge). Le filtre
  bilatéral du rouge n'y peut rien : tout le symbiote tient sous L* 3 ;
- **le DXT 565** ne sait pas rendre les quasi-noirs (pas de ~8 niveaux en R/B) : taches
  violettes / vertes sur le tissu, liserés verts / magenta autour de la toile.

Ce que fait maintenant `tools\png2tex.py` pour l'atlas noir `0x0133FD92` (par défaut, dans
`par_texture` de `texture_qualite.json`) :

| réglage | valeur | effet |
|---|---|---|
| `lissage_tissu` | actif, sigma 16, detail 0, seuil_fil 48 | la base du tissu est floutée en lumière linéaire ; fils de toile, logos et yeux (texels clairs) intacts |
| `format_force` | `ARGB8` | plus aucune erreur de compression (le choix DXT5 de Studio est ignoré pour ce slot, signalé au journal) |
| `taille_max` | `2048` | même taille de fichier que DXT5 4096 ; le mip 0 = niveau 1 de la chaîne 4096 |

Et `tools\blacksuit_package.py` applique `noir_normale_plaquer` `[9, 14]` à la normale du noir :
relief du tissu à plat (pente lissée < 9°), arêtes de la toile gardées — comme le rouge. Le slot
`0x61DCA273` étant partagé avec le rouge, ce réglage passe par une clé à part (`normale_plaquer`
reste `[0, 0]` pour la chaîne rouge). `controle_texture` lit désormais le format dans l'en-tête du
`.tex` (ARGB8 : égalité exacte avec `preparer_image`).

Mesures : l'atlas produit par l'outil est à 52 dB de la version validée en jeu (écart moyen
0,1/255) ; la normale est à 0,01° du candidat validé ; l'atlas ROUGE ne change pas d'un octet.
Auto-test : 104 contrôles (mode rapide), 0 échec — nouveaux contrôles : atlas noir ARGB8 imposé +
tissu lissé, `taille_max`, `normale_plaquer`.

**Revenir à l'ancien rendu du noir** (DXT5 4096, motif gardé) : dans `texture_qualite.json`,
`"par_texture": {"0x0133FD92": {"lissage": {"actif": false}}}` et `"noir_normale_plaquer": [0, 0]`.

Hors outil (recolorations faites à la main pour le photoreal) : le noir « deux tons » puis « tout
noir » vient de `sauvegardes\2026-10-06_noir_deux_tons\noir_deux_tons.py` (Python système, scipy) —
ce n'est pas un réglage automatique de Studio.

## 11. Bouton « Installer et lancer le jeu » réparé (`tools\boucle_test.ps1`)

Le bouton ne pouvait ni installer ni lancer le jeu ailleurs que dans
`C:\Program Files (x86)\Activision\Spider-Man 3`, écrit en dur dans le script. Corrigé sans
reconstruire l'exe (le script est lu sur le disque) :

- **dossier du jeu cherché**, dans l'ordre : le « Dossier du jeu » de l'onglet Chemins
  (`sm3_studio.json`), le registre d'installation (`HKLM\...\Activision\Spider-Man 3\InstallPath`),
  puis les emplacements habituels — seul un dossier qui contient `Game.exe` est retenu, et le
  journal dit lequel a servi ;
- **nom de mod avec une espace** (« sm3 remake ») : l'exe le passait en deux morceaux, le script
  cherchait le mod « sm3 ». Les morceaux sont maintenant recollés ;
- le jeu ouvert est **fermé avant** la copie (et plus après) ; un échec de copie est remonté au
  journal au lieu d'annoncer « mod installé » ;
- les **captures d'écran automatiques** (Alt+F1, outil de test) sont coupées : `-Captures 3` pour
  les remettre ; `-Simuler` montre ce qui serait fait sans rien écrire.

Rappel : le bouton **désactive tous les autres mods** (dont `photoreal`) et n'active que celui
qu'il installe — c'est voulu (deux mods actifs se disputent les mêmes fichiers).
Original : `Documents\SM3-modding-projet-complet\sauvegardes\2026-10-06_bouton_installer\originaux\`.
