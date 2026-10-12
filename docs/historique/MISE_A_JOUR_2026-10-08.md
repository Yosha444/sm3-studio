> *Historical note, kept in French as it was written on 2026-10-08; see [README.md](README.md) in this folder for an English summary. The current documentation is the repository's README.md and docs/: where they disagree, they win.*

# SM3 Studio HQ — mise à jour du 8 octobre 2026

Demande : « des modèles et des textures plus détaillés, comme dans Web of Shadows ; si possible, patcher
l'exe pour qu'il accepte des modèles plus détaillés ».

L'enquête complète est dans
`Documents\SM3-modding-projet-complet\sauvegardes\2026-10-08_detail\SYNTHESE.md`.

## Ce qu'on a appris

- **Le moteur est déjà « large », sans patch.**
  - Aucune limite de sommets par modèle.
  - 65 535 sommets au plus **par section**, et autant de sections qu'on veut (xeSM3 : jusqu'à 256).
  - Textures jusqu'à 16384.

  Les patchs d'exe envisagés sont tous déconseillés :
  - index 32 bits : casse 7 maillages du jeu ;
  - suppression des LOD : touche environ 1 700 tables de la ville ;
  - précision des sommets : casse Peter civil et les 25 costumes livrés.
- **Le photoreal EST le costume de Web of Shadows** : 20 544 triangles, comme dans WoS. Ce qui manquait :
  1. nos propres lissages, surtout les écailles du costume noir ;
  2. le spéculaire texturé ;
  3. le filtrage anisotrope, que le pilote force sur OFF ;
  4. un bug de dilatation, décrit ci-dessous.

## Corrections de la chaîne

1. **`dilater_atlas.py` (dans l'exe).** La couverture des îlots était calculée avec V à l'envers. La
   dilatation barbouillait donc les vrais îlots :
   - photoreal rouge et noir : 3,3 et 3,5 % des texels ;
   - TASM2 : 7 % ;
   - Miles : 10 % ;
   - Gojo : 16 % ;
   - TASM1 : 20 % ;
   - Brand : 52 %.

   Ça se voyait comme des fils de toile coupés. L'orientation est maintenant choisie automatiquement : fond
   noir de l'atlas, atlas cuit voisin, ou signature du remplissage. Le journal `[dilat]` indique laquelle a
   été retenue. Test sur 36 constructions : 36 en V, aucun texel d'îlot modifié.
2. **Recuisson et normale (`tools\atlas_recuit.py`, `tools\normale_bake.py`).** Les modèles dont les UV
   sortent de [0,1] avaient un atlas recuit refusé et une normale plate : TASM2 à 2,6 % de texels portés, et
   le 2099 cassé sans aucun message. Les UV sont maintenant ramenées dans [0,1] par un décalage entier. Le
   test « assez de couleur » est remplacé par une comparaison à la source, qui n'a plus d'objection contre un
   atlas très noir. Résultat : TASM2 à 66,8 %. Miles, dont les UV sont déjà dans [0,1], ressort identique à
   l'octet près.
3. **Découpage automatique en sections (`tools\decoupe_sections.py`, appelé par `winding_fix.py`).**
   - Pour la cible Spider-Man, toute section de plus de 65 535 sommets est coupée en sections de même
     matériau, en index 16 bits. Avant, le jeu tronquait en silence les index 32 bits et le modèle sortait
     déchiré.
   - Le costume noir et Venom, qui ne permettent qu'une section, sont refusés avec un message plutôt que
     livrés cassés.
   - Contrôle bloquant ; nouvelle ligne « sections du 000/001 » dans le contrôle final.
   - Testé sur `bnd` (463 000 sommets, 8 sections) et `raimi_tpose` (237 000 sommets, 4 sections).
   - Les 124 maillages déjà livrés ressortent identiques.
4. **`mains_poings` sur les gros modèles.** Le 001 relisait sa trace `.npz` à chaque sommet : environ 5 h
   sur 463 000 sommets. Il passe à 7,5 s, avec un résultat identique. Les mains du photoreal validées en jeu
   restent identiques à l'octet près.

## Textures photoreal détaillées (mod à part, `photoreal_detail`)

Refaites depuis les sources WoS d'origine, sur les maillages installés, qui ne changent pas.

- **Noir, version A** (ARGB8 2048) :
  - les écailles reviennent : pente du tissu de 0,3° à 5,7° ;
  - noir très profond conservé : base ≈ 4 sRGB, toile, logo et yeux gardés.
- **Rouge** : normales WoS et diffuse sans lissage. Pente du tissu de 0,3° à 1,3°.
- Variantes de rechange du noir : `sauvegardes\2026-10-08_impl\textures_photoreal\variantes_noir\` (détail 0 / 0,7 / 1,0).

## Revenir en arrière

- Exe précédent : `SM3 Studio.exe.avant_detail_20261008`.
- Fichiers d'origine : `sauvegardes\2026-10-08_impl\originaux_studio\`.
