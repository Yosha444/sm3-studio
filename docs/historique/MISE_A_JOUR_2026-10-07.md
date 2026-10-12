> *Historical note, kept in French as it was written on 2026-10-07; see [README.md](README.md) in this folder for an English summary. The current documentation is the repository's README.md and docs/: where they disagree, they win.*

# SM3 Studio HQ — mise à jour du 7 octobre 2026

Deux plaintes, une même cause :

- « le TASM2 a le dos cassé » : un gros problème de proportions qui saute aux yeux en jeu ;
- « certains modèles ont toujours les doigts cassés, même après le patch des poings ».

**La cause.** Le jeu fait tourner chaque morceau du corps autour des articulations de **son**
squelette. Jusqu'ici, la conversion mettait seulement le modèle à l'échelle de la hauteur, puis le
centrait. Ses coudes, genoux, épaules, son cou et ses phalanges restaient là où le modèle les avait
mis. Le corps pliait donc au mauvais endroit, et les doigts pivotaient autour d'axes posés à côté
d'eux.

Mesures sur le TASM2, avec l'ancienne conversion :
- coude 7 cm trop loin le long du bras ;
- genoux 7 cm trop bas ;
- tout le corps **10 à 19 cm derrière** le squelette du jeu : buste penché, tête en avant ;
- les deux mains laissées telles quelles par le patch des poings.

## 1. Modèle avec son propre rig : chaque articulation posée sur celle du jeu

Nouveau fichier : `tools\conformer_squelette.py`, appelé par la chaîne Blender.

Si le modèle a un rig, la chaîne reconnaît ses os. Formats reconnus :
- Mixamo, y compris avec les suffixes « _012 » de Sketchfab ;
- Unreal / Fortnite ;
- Auto-Rig Pro (2099) ;
- Biped ;
- Free Fire ;
- noms libres (« left arm », « upperarm_l »).

Ensuite, la chaîne :
- **pose** chaque os sur l'os du jeu correspondant : position, direction, longueur. Le maillage suit
  avec ses propres poids. L'épaisseur du corps, la tête et les mains gardent leur taille ;
- garde **les pieds à plat** : la semelle reste posée sur celle du jeu (le pied n'est plus en pointe) ;
- prend les doigts **du rig** pour le patch des poings, au lieu de les deviner par la topologie. Ils
  sont écrits dans `doigts_modele.npz`, à côté du `.mesh`.

Résultats :

| Modèle | Os reconnus | Doigts |
|---|---|---|
| TASM2 | 52 | 30/30 |
| Fortnite | 52 | 30/30 |
| 2099 Auto-Rig Pro | 52 | 30/30 |
| Free Fire | 41 | 20/30 (2 phalanges par doigt) |

Au poing simulé, le 99e centile de l'étirement des arêtes de la main passe de 10,1 à 3,0 sur le
TASM2. Fortnite est à 1,6, comme le vanilla (1,55).

Pour le désactiver : variable d'environnement `SM3_CONFORMER=0`.

## 2. Modèle sans rig : bras et jambes posés par leur forme

Nouveau fichier : `tools\conformer_sans_rig.py`, placé entre `poids` et `lod`. Pour chaque membre :
1. le membre est isolé par les poids qu'il a reçus du vanilla ;
2. on calcule sa ligne centrale ;
3. coude, poignet, genou et cheville sont placés sur cette ligne aux **mêmes fractions** que chez
   le vanilla, mesurées par le même algorithme ;
4. chaque segment est posé sur celui du jeu, et les pieds restent à plat.

Un membre incohérent (longueur hors 70–135 %, coupe à plus de 12 cm) est refusé et reste tel quel.
`redresser_bras` (angle du bras) tourne toujours avant.

## 3. Doigts d'un modèle sans rig : trouvés, posés, et arbitrés

Nouveau fichier : `tools\doigts_sans_rig.py`. Les doigts sont trouvés comme **branches** de la
main : distance géodésique depuis le poignet, qu'ils se touchent ou non, et même si la main est une
pièce séparée de la manche. Ensuite :
- chacun est **posé** sur les phalanges du jeu ;
- un doigt déjà replié dans le modèle reste solidaire de la main ;
- les pièces séparées collées à un doigt (ongles, surcouches) suivent ce doigt.

**Arbitrage.** Pour chaque main, le poing du jeu est simulé sur deux variantes : doigts posés, ou
main laissée. L'outil garde **la moins déchirée**. Aucune règle fixe ne gagnait partout. Exemples :
la pose aide Brand et le TASM1 ; pour Miles, la main laissée est meilleure, et la topologie trouve
alors seule les 30 phalanges.

## 4. Autres corrections de la chaîne

- **Profondeur.** Le corps est centré sur le **tronc** du vanilla, et non plus sur la médiane de
  tous les sommets. C'est cette médiane qui mettait les modèles 10 à 19 cm derrière le squelette.
- **Modèle de dos.** Si les orteils pointent vers l'arrière, le modèle est tourné de 180°. Mesuré
  sur `tasm_1_spider-man.glb`, qu'il fallait jusqu'ici retourner à la main.
- **Pièces accrochées aux os** (griffes, ailes de cape). L'armature passe en position de repos avant
  la jointure. Elles atterrissaient sous les pieds, et le modèle 2099 rapetissait d'un tiers.
- **`poids_depuis_vanilla` (dans l'exe).**
  - Les phalanges passent après les os du corps quand la palette de 48 déborde : `mains_poings` les
    refait derrière.
  - Un os de torsion jeté (`foretwist`, `upperarm split`) rend ses sommets à l'os principal de son
    segment. Avant, `foretwist`, enfant du **bras** dans ce squelette, envoyait l'avant-bras près
    du coude sur le bras, et le coude ne pliait plus.
- **`mains_poings`.** Les mains déjà validées en jeu (photoreal rouge et noir) ressortent **à
  l'octet près**, vérifié.

## Revenir en arrière

- Exe précédent : `SM3 Studio.exe.avant_conformation_20261007`.
- Fichiers d'origine : `Documents\SM3-modding-projet-complet\sauvegardes\2026-10-07_proportions\originaux\`.

Les modèles déjà convertis ne changent pas. **Il faut les reconvertir** pour en profiter.
