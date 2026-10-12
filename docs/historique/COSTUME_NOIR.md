> *Historical note, kept in French as it was written on 2026-09-08 and 2026-10-06; see [README.md](README.md) in this folder for an English summary. The current documentation is the repository's README.md and docs/: where they disagree, they win.*

# Costume noir — méthode CJ

Dans **SM3 Studio.exe**, choisir **Personnage cible → Costume noir**.
Sélectionner un GLB, glTF, FBX ou OBJ, donner un nom au mod, puis cliquer sur **Convertir** et sur le bouton d’installation lorsque la conversion est terminée.

Le profil produit les deux variantes 000 et 001 avec leur squelette respectif. Il reprend la chaîne d’atlas couleur utilisée pour Spider-Man, le transfert de poids et l’adaptation utilisés pour CJ, validé en jeu par l’utilisateur le 8 septembre 2026.

La sélection applique ARGB8, vertex noir et dilatation 12 pixels. Le cel shading est absent. La résolution, la géométrie et la dilatation restent réglables. Les ressources natives du costume noir sont incluses dans `vanilla/CH_BLACKSUIT/_O0108.0xF8ACB40C.T36.apkf` (MESH, SKEL, MAT et TEX natifs).

L’installation sauvegarde les fichiers remplacés et la configuration, désactive les mods concurrents sur les mêmes ressources, puis active le nouveau mod. Les packs originaux ne sont pas réécrits. Le jeu doit être fermé.

Le modèle CJ contient 2 406 triangles. La réussite avec CJ ne valide pas les modèles très denses précédemment déformés : chaque nouveau modèle reste à tester en mouvement dans le jeu.

La conversion utilise Blender 5.2 et le toolkit installés sur cet ordinateur, ainsi que le runtime Python NumPy/Pillow disponible dans le cache Codex. Une dépendance absente bloque la conversion avant son lancement.


**Mise à jour du 2026-10-06** : les doigts du costume noir retrouvent leurs phalanges (poings serrés, 26 os de doigts sur 30 dans la section unique), et le nouveau lissage des textures ne s’applique pas à son atlas (`par_texture` dans `texture_qualite.json`). Détails : `MISE_A_JOUR_2026-10-06.md`.
