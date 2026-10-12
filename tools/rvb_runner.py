# SPDX-License-Identifier: GPL-3.0-or-later
"""rvb_runner.py - Web of Shadows mode: models SM3 Studio recognises by content, with their own weights.

"RvB" comes from the names of the two models in Spider-Man: Web of Shadows (another game):
ch_spiderman_rvb000 and ch_rvbblack000. When the source is a .glb export of one of them, the
conversion keeps that game's ORIGINAL skin weights and pose instead of transferring weights from
the vanilla model.

Called by sm3_convertir.main() before any other target (red suit or Black Suit):
  * recognize(source, root): the model name if the file's SHA-256 is listed in
    profiles/rvb/sources.json AND that model's profile (profiles/rvb/<model>.json and
    <model>.skeleton.json) is installed; None otherwise, and the model then goes through the
    normal conversion. Recognition is by content, never by file name or bone count;
  * run(args, root, blender, fmt): Blender runs the official chain (alignment, atlas bake;
    --normale 0: no normal map) into build/<mod>/source, then an external Python runs
    rvb_finalize.py: rvb_native.py rebuilds the meshes from the profile, using the chain's 000
    mesh only to find each original vertex's UVs in the atlas; then texture and mod layout.
The profile files come from Web of Shadows and are NOT distributed (see profiles/README.md):
without them this mode is simply off.
"""
from pathlib import Path
import hashlib,json,subprocess,sys

def recognize(source,root):
    p=Path(source)
    if p.suffix.lower()!='.glb' or not p.is_file():return None
    profile=Path(root)/'profiles/rvb'
    catalog_path=profile/'sources.json'
    if not catalog_path.is_file():return None
    catalog=json.loads(catalog_path.read_text())          # {sha256 of the .glb: model name}
    model=catalog.get(hashlib.sha256(p.read_bytes()).hexdigest())
    # The Web of Shadows profile itself (<model>.json, <model>.skeleton.json) comes from another
    # game and is not distributed: without it this mode is off and the model is converted like
    # any other one. tools/extraire_donnees_jeu.py explains it in its report.
    if model and not all((profile/(model+suffix)).is_file() for suffix in ('.json','.skeleton.json')):
        print('[RvB] This model is a Spider-Man: Web of Shadows export SM3 Studio knows (%s), but '
              'its Web of Shadows profile is not installed (profiles/rvb/%s.json and .skeleton.json, '
              'not distributed: they come from another game). It is converted like any other model. '
              'To keep its original skin weights, copy profiles/rvb from an older SM3 Studio '
              'installation.' % (model, model), flush=True)
        return None
    return model

def run(args,root,blender,fmt=None):
    root=Path(root).resolve();model=recognize(args.src,root)
    if not model:raise ValueError('Unrecognized RvB source')
    if args.target not in ('spiderman','blacksuit'):raise ValueError('Unsupported RvB target')
    if Path(args.nom).name!=args.nom or args.nom in ('','.','..'):raise ValueError('Invalid mod name')
    out=Path(args.out).resolve() if args.out else root/'build'/args.nom
    out.mkdir(parents=True,exist_ok=True);(out/'source').mkdir(exist_ok=True)
    mods=Path(args.mods).resolve() if args.mods else root/'mods'
    job=dict(root=str(root),source=str(Path(args.src).resolve()),model=model,target=args.target,out=str(out),destination=str(mods/args.nom),dilate=int(args.dilate),format=(getattr(args,'format',None) or 'DXT5').upper())
    jobfile=out/'rvb_job.json';jobfile.write_text(json.dumps(job,indent=2))
    print('[RvB] Original skin weights; no arm correction',flush=True)
    subprocess.run([blender,'-b','--python-exit-code','1','--python',str(root/'tools/chaine_officielle.py'),'--','--src',job['source'],'--textures',str(Path(job['source']).parent),'--vanilla',str(root/'vanilla/CH_SPIDERMAN/_O0069.0xCFB154CD.T36.apkf'),'--out',str(out/'source'),'--normale','0'],check=True)
    # Python for rvb_finalize.py (needs numpy + Pillow): SM3_PYTHON, else the running Python,
    # else python/py on PATH when running from the .exe. See external_python.py.
    sys.path.insert(0,str(root/'tools'))
    from external_python import find_python
    python=find_python()
    subprocess.run([str(python),str(root/'tools/rvb_finalize.py'),str(jobfile)],check=True)
    print('[RvB] Ready: '+job['destination'],flush=True)
