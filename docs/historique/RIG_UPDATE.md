> *Historical note, kept in French as it was written on 2026-09-14; see [README.md](README.md) in this folder for an English summary. The current documentation is the repository's README.md and docs/: where they disagree, they win.*

# Rig et normales : palette 48 os, réparation topologique, carte de normales générée — 2026-09-14

## 1. La palette d'os vaut 48, pas 32

La note « 32 maximum » était **fausse**. Trois mesures indépendantes donnent 48 :

- les **12** vertex shaders skinnés de `Game.exe` déclarent tous `world` sur `c0..c191`,
  soit 48 matrices — aucun n'en déclare 32 ;
- le `ch_spiderman000` du jeu livre trois sections à 48 os distincts, `ch_blacksuit000` aussi ;
- l'écrivain amont du toolkit de TSGAMING264 (`sm3_mesh_writer.py`) autorise 48.

Un corps entier en **une seule** section demande ~52 os. À 32 slots, après les 21 os posturaux,
ce qui saute ce sont les avant-bras, les mains et les dix doigts :

| modèle | segments perdus à 32 os |
|---|---|
| `peter` | les 2 avant-bras, les 2 mains, les 10 doigts |
| `adv_large` | les 2 bras, les 2 clavicules, un pied, 8 doigts |

Un bras sans os de bras retombe sur la clavicule ; un doigt sans os de doigt retombe sur la main.
Mesure sur le costume rouge :

| | à 32 os | à 48 os | vanilla |
|---|---|---|---|
| segments couverts | 29 / 31 | **31 / 31** | — |
| os de doigts, main gauche | 5 | **9** | — |
| écart aux poids du jeu | 0,046 | **0,009** | 0 |

Le plafond était écrit à six endroits : `poids_depuis_vanilla.py`, le contrôle « indices shader »
de `sm3_convertir.py`, `tools/blacksuit_mesh_writer.py`, `tools/blacksuit_build.py`,
`tools/cj_build.py`, `tools/cj_update.py`. Tous corrigés.

## 2. Réparation topologique (`poids_depuis_vanilla.reparer`)

Le transfert décidait sommet par sommet, sans jamais regarder à côté. Quand les deux corps ne se
superposent pas — une main qui pend le long de la cuisse, deux pieds qui se touchent — un paquet
entier de sommets attrape les os du **voisin géométrique**. Part des arêtes dont les deux bouts
tombent de part et d'autre du corps (vanilla : 0,006 %) : `peter` 3,27 %, `apres_flanc2` 2,14 %.

La **topologie** du modèle, elle, ne dépend pas de la pose : une cuisse n'est jamais reliée à un
doigt par la surface. Chaque sommet est comparé à la moyenne de ses voisins ; s'il désigne un os à
plus de `--sauts-max` arcs du leur, ou de l'autre côté du corps, il est remplacé par cette
moyenne, et on recommence — la plaque fautive **fond par son bord**.

Les sommets colocalisés sont fusionnés d'abord : deux sommets au même endroit portant des poids
différents se séparent dès que ça bouge, et c'est la fente qui coupe un visage en deux.

Rien n'est touché sur un sommet qui s'accorde déjà avec son voisinage — 24 nœuds sur 10 266 pour
le costume rouge. Aucun seuil à régler. `--lisser 0` la désactive.

## 3. État du maillage (`poids_depuis_vanilla.etat_du_maillage`)

Trois défauts qu'**aucun** jeu de poids ne rattrape, et qui sortaient jusqu'ici sans un mot :

1. **Couché** — la plus grande étendue n'est pas la hauteur.
2. **Bras hors pose** — envergure sous 85 % de celle du vanilla (le vanilla est en pose A,
   x/y = 0,81). Mesures : `photoreal_rouge` 1,725 et `suku` 1,713 sont sains ; `adv_large` 1,195
   et `peter` 0,232 sont perdus.
3. **Écrasé par la quantification** — les positions sont des entiers 16 bits / 512, le pas vaut
   1/512 quelle que soit la taille du modèle. Part des sommets restant distincts : vanilla
   89,6 %, `photoreal_rouge` 91,8 %, mais `peter` **5,0 %** — ses 32 932 sommets ne désignent
   plus que 1 631 points, le modèle n'est qu'un cône.

## 4. Écart hiérarchique borné entre influences

Borner la distance à l'os dominant ne bornait pas l'écart entre les autres : deux influences à
4 arcs de part et d'autre en font 8 entre elles. Le vanilla ne dépasse jamais **5 arcs** entre
deux influences d'un même sommet. `--arcs-max 5` lâche l'influence la plus légère tant que la
portée dépasse.

## 5. La carte de normales GENEREE arrivait NOIRE

Assigner `image.colorspace_settings.name` sur une image **generee** par Blender
(`bpy.data.images.new`, sans fichier) **vide son tampon a noir** — y compris en y remettant la
valeur qu'elle porte deja. Temoin 64x64 rempli d'un degrade 0..1 :

```
sans re-set              R 0.000..1.000   ecart-type 0.2932
avec re-set colorspace   R 0.000..0.000   ecart-type 0.0000
```

`normale_bake.py` faisait exactement cela juste avant la cuisson. La normale **deduite de la
diffuse** — donc generee — arrivait noire ; le noeud Normal Map lisait (0,0,0), soit une normale
degeneree (-1,-1,-1), et la cuisson la reencodait dans le repere tangent de **chaque ilot**, d'ou
des normales couchees a plat groupees en quatre paquets diagonaux (les quatre quarts de tour de
`pack_islands`). En jeu : des plaques vertes et l'eclairage qui casse a chaque bord de texture.

|                              | pente mediane | texels impossibles |
|------------------------------|---------------|--------------------|
| avant                        | 80,96 deg     | 6,67 %             |
| apres                        | 2,93 deg      | 0,00 %             |
| build utilisant une VRAIE carte | 2,72 deg   | 0,00 %             |

Seuls les modeles **sans** carte de normales etaient touches : une carte chargee d'un fichier se
recharge du disque, une image generee n'a rien a recharger. Signature a reconnaitre : *ca marche
sur les modeles qui fournissent la carte, ca casse sur ceux ou on la genere*.

Deux mesures suffisent a juger n'importe quelle carte livree : la **pente mediane** (vraies cartes
de Web of Shadows : 1,31 / 1,31 / 2,31 / 5,74 deg) et la **part de texels impossibles**
(nx^2 + ny^2 > 1, doit valoir 0).

Corollaire : une source uniforme est desormais **ecartee** au lieu d'etre cuite. Une normale
droite est inutile, du bruit vertical ne l'est pas.

## 6. Le gain du relief deduit est auto-calibre

Un gain FIXE ne peut pas convenir a la fois aux diffuses photographiques et aux aplats durs.
`--normale-force auto` (defaut) vise la pente mediane des vraies cartes ; c'est exact, pas
iteratif : `mediane(pente) = atan(echelle x mediane(|grad|))`, donc
`echelle = tan(cible) / mediane(|grad|)`. `auto:5` vise 5 deg, un nombre force le gain comme
avant, 0 ne deduit rien.

Verification sur les quatre diffuses de Web of Shadows, contre leur vraie carte :

| diffuse | force 10 | auto | vraie carte |
|---|---|---|---|
| redsuit_tex1 | 2,10 | 3,00 | 1,31 |
| redsuit_tex2 | 1,05 | 3,00 | 1,31 |
| blacksuit1_tex2 | 3,53 | 3,00 | 2,31 |
| blacksuit1_tex1 | 6,77 | 3,00 | 5,74 |

## 7. Un petit accessoire detache suit UN groupe d'os

Une sacoche de ceinture, une boucle, une epaulette ne touchent le corps par aucune arete : elles
n'ont aucun voisin pour les corriger, et chaque moitie peut tomber sur un os different. Les
composantes connexes de moins de 2 % du maillage dont les os s'ecartent de plus de `--sauts-max`
arcs, ou changent de cote, recoivent la moyenne de leur propre composante. Seuil volontairement
bas : une cape ou un pan de tissu DOIT se deformer.

## 8. `tools/silhouette.py` et `tools/apercu_modele.py`

Voir un `.mesh` de face et de profil en deux secondes, sans Blender — numpy pur, PNG écrit à la
main. C'est ce qui a montré que `peter` était un cône alors que toutes ses statistiques de
skinning étaient parfaites.

`silhouette.py` donne la forme d'ensemble en nuage de points ; `apercu_modele.py` donne un rendu
OMBRE (tampon de profondeur + N.L), et il lit aussi bien un `.mesh` qu'un `.glb`. C'est ce qui a
montre que `peter` etait un cone alors que ses statistiques de skinning etaient parfaites, et que
le menton colle d'un Batman Beyond venait du modele source et non de la chaine.

```
python tools/silhouette.py --mesh build/<mod>/etape_bras.mesh
python tools/apercu_modele.py --modele build/<mod>/0xAC92103D.ch_spiderman000.mesh --zone 0.84,1.02
python tools/apercu_modele.py --modele mon_modele.glb --redresser
```
