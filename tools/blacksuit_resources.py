# SPDX-License-Identifier: GPL-3.0-or-later
"""blacksuit_resources.py - find the black suit's original resources inside SM3 Studio's folder.

The black suit target ("Costume noir") is built on top of the game's own CH_BLACKSUIT archive:
its meshes, skeletons, materials and textures. They live in

    <SM3 Studio>/vanilla/CH_BLACKSUIT/<archive folder>/      e.g. _O0108.0xF8ACB40C.T36.apkf
    <SM3 Studio>/vanilla/CH_BLACKSUIT/resources.json         {"scope": <archive folder>,
                                                              "resources": {file: sha256}, ...}

Those files are not distributed with SM3 Studio: tools/extraire_donnees_jeu.py rebuilds them
from the player's copy of the game (SM3 Studio does it by itself before the first conversion).

They are always looked up under SM3 Studio's own folder, never next to the model being converted
(an early version picked them up from Downloads).
"""
from pathlib import Path
import json


def resolve(root):
    """Folder of the CH_BLACKSUIT resources; raises if the manifest or any listed file is missing."""
    base = Path(root) / 'vanilla/CH_BLACKSUIT'
    manifest_path = base / 'resources.json'
    if not manifest_path.is_file():
        raise FileNotFoundError(
            'CH_BLACKSUIT game data missing (%s). It is rebuilt from your copy of Spider-Man 3 by '
            'tools/extraire_donnees_jeu.py, which SM3 Studio runs before a conversion.' % manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    scope = manifest['scope']
    # The archive folder must be a plain name: never let the manifest point outside vanilla/.
    if Path(scope).name != scope:
        raise ValueError('Invalid native scope')
    folder = base / scope
    missing = [name for name in manifest['resources'] if not (folder / name).is_file()]
    if missing:
        raise FileNotFoundError('CH_BLACKSUIT vanilla resources missing: ' + ', '.join(missing))
    return folder
