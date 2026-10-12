> *Historical note, kept in French as it was written on 2026-09-09; see [README.md](README.md) in this folder for an English summary. The current documentation is the repository's README.md and docs/: where they disagree, they win.*

# Mise à jour RvB / RvB update

FR : les deux GLB dans profiles/rvb sont reconnus par SHA256. Choisir la cible Spider-Man pour le rouge, Costume noir pour le noir. Le tool conserve le nombre de triangles, reprend les poids RvB par identifiant d'os et adapte les positions aux matrices de repos PC. Le matériau canvas impose 32 os : les influences exclues sont regroupées sur le parent retenu. Aucun redressement automatique des bras n'est appliqué à l'export final RvB. Un GLB modifié n'utilise pas ce profil automatiquement : sa correspondance de sommets n'est plus garantie.

Le sens des triangles et des normales est également contrôlé en fin de conversion classique rouge/noire. Les textures ne sont pas inversées en couleurs. Le costume noir RvB corrigé a été validé en jeu par l'utilisateur ; le rouge doit encore l'être. Le changement de costume du prototype n'est pas inclus dans cette mise à jour.

EN: the two GLBs in profiles/rvb are recognized by SHA256. Select Spider-Man for red or Black Suit for black. The tool preserves triangle count, maps original RvB weights by bone identifier and adjusts positions to the PC bind matrices. The canvas shader has a 32-bone limit: omitted influences are merged into a retained ancestor. The final RvB export does not use automatic arm straightening. Modified GLBs do not automatically use this profile because vertex correspondence is no longer guaranteed.

Triangle winding and shading normals are also checked at the end of standard red/black conversions. Texture colors are not inverted. The corrected black RvB suit was user-verified in game; the red one still needs in-game verification. The prototype suit-switch mechanic is not included in this update.

## Red RvB lenses / Lentilles rouges
The Xbox lens section uses position /1000, while the legacy GLB used /1024. Native export corrects only these 62 vertices after atlas matching; UVs and the remaining character are preserved. The original section bounds confirm /1000.
La correction replace les 62 sommets des lentilles, sans decalage des UV ni changement du reste du personnage.
