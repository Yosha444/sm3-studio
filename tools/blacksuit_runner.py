# SPDX-License-Identifier: GPL-3.0-or-later
"""blacksuit_runner.py - the "Black Suit" target: a model -> the black suit's 000/001 meshes + atlas.

This is the full-colour workflow validated in game with the CJ model. Called by
sm3_convertir.main() for `--target blacksuit` (window: Target character = "Costume noir", Black
Suit). The red-suit chain does most of the work; the result is then moved onto the black suit's
own skeletons and sections:

  1. blacksuit_resources.resolve(): the game's CH_BLACKSUIT files must be in vanilla/
     (rebuilt from the player's game by extraire_donnees_jeu.py);
  2. build/<mod>/blacksuit_job.json: every setting for the next steps;
  3. Blender runs blacksuit_pipeline.py: official chain (alignment, weights, atlas bake) into
     build/<mod>/source, arms straightened, weights redone with a 48-bone limit, then
     blacksuit_build.py writes ch_blacksuit000/001.mesh and validation.json;
  4. sections_ou_refus(): refuse a section the game cannot index (see below);
  5. an external Python runs blacksuit_finalize.py: atlas dilation, winding check,
     blacksuit_package.py (texture encoding, checks, copy into mods/<mod>/CH_BLACKSUIT/...).
Installing into the game is a separate button (blacksuit_deploy.py).

Reads the model and vanilla/; writes build/<mod>/ and mods/<mod>/ (or --out / --mods).
"""
from pathlib import Path
import importlib.util,json,subprocess,sys

def sections_ou_refus(root,out):
    """Refuse a mesh whose section has more than 65,535 vertices ("sections or refusal").

    The black suit has only ONE real section: xeSM3 gives it its material by section INDEX.
    Above 65,535 vertices the game truncates the 32-bit indices and the model comes out torn
    (tools/decoupe_sections.py explains it). winding_fix already refuses it in
    blacksuit_finalize, but in a SUBPROCESS whose output may not reach the window's log; so we
    refuse here, in the window's own process, with the message that says what to do."""
    spec=importlib.util.spec_from_file_location('decoupe_sections',str(Path(root)/'tools/decoupe_sections.py'))
    ds=importlib.util.module_from_spec(spec);sys.modules['decoupe_sections']=ds;spec.loader.exec_module(ds)
    for mesh in sorted(Path(out).glob('*.ch_blacksuit00?.mesh')):
        m=ds.fmt.parse_mesh(str(mesh))
        grosses=[s for s in m.sections if s.vertex_count>ds.MAX_SOMMETS]     # oversized sections
        if grosses:raise RuntimeError('Black Suit: '+ds.message_index(m,grosses))

def run(args,root,blender,fmt):
    root=Path(root).resolve(); source=Path(args.src).resolve()
    sys.path.insert(0,str(root/'tools'))
    from blacksuit_resources import resolve
    resolve(root)
    # Python for blacksuit_finalize.py (needs numpy + Pillow): SM3_PYTHON, else the running
    # Python, else python/py on PATH when running from the .exe. See external_python.py.
    from external_python import find_python
    python=find_python()
    subprocess.run([str(python),'-c','import numpy; from PIL import Image'],check=True)
    if not source.is_file() or source.suffix.lower() not in ('.glb','.gltf','.fbx','.obj'):
        raise ValueError('Black Suit: choose an existing GLB, glTF, FBX or OBJ file.')
    if not args.nom or Path(args.nom).name!=args.nom or args.nom in ('.','..'):
        raise ValueError('Invalid mod name.')
    out=Path(args.out).resolve() if args.out else root/'build'/args.nom.lower()
    out.mkdir(parents=True,exist_ok=True)
    mods=Path(args.mods).resolve() if args.mods else root/'mods'
    # The job file passes the converter's settings to the Blender and finishing scripts.
    # _O0108.0xF8ACB40C.T36.apkf = the CH_BLACKSUIT archive folder, named as xeSM3 names it.
    config=dict(root=str(root),source=str(source),textures=args.textures or str(source.parent),out=str(out),
                destination=str(mods/args.nom/'CH_BLACKSUIT/_O0108.0xF8ACB40C.T36.apkf'),
                drop=args.drop,materiaux=args.materiaux,dilate=int(args.dilate),voisins=int(args.voisins),fondu=float(args.fondu_bras),
                format=(getattr(args,'format',None) or 'DXT5').upper())
    path=out/'blacksuit_job.json';path.write_text(json.dumps(config,indent=2),encoding='utf8')
    subprocess.run([blender,'-b','--python-exit-code','1','--python',str(root/'tools/blacksuit_pipeline.py'),'--',str(path)],check=True)
    sections_ou_refus(root,out)
    subprocess.run([str(python),str(root/'tools/blacksuit_finalize.py'),str(path)],check=True)
    print('[costume noir] 000 + 001 conversion finished: '+config['destination'],flush=True)
