# SPDX-License-Identifier: GPL-3.0-or-later
"""blacksuit_pipeline.py - Blender part of the Black Suit target (started by blacksuit_runner.py).

    blender -b --python-exit-code 1 --python blacksuit_pipeline.py -- <build>/blacksuit_job.json

Runs inside Blender, every step in this one process (runpy), in this order:
  1. tools/chaine_officielle.py (the red-suit chain: alignment, weights, atlas bake, export of a
     red-suit 000 mesh) into <build>/source, with the normal map baked (--normale 1);
  2. redresser_bras.py (project root): arms put back into the vanilla A pose -> etape_bras.mesh;
  3. tools/blacksuit_weights.py: weights redone from the vanilla, limited to 48 bones
     -> etape_poids.mesh;
  4. the final atlas image of chaine.blend saved as <build>/source/atlas_final.png;
  5. blacksuit_build.build(): the result moved onto the black suit's skeletons and written as
     ch_blacksuit000/001.mesh + validation.json in <build>.
The job file (written by blacksuit_runner.py) gives root, source, textures, out, drop,
materiaux, voisins, fondu.
"""
import sys,json,runpy
from pathlib import Path
import bpy
job=json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text(encoding='utf8'))
root=Path(job['root']);out=Path(job['out']);source=out/'source';source.mkdir(exist_ok=True)
sys.path[:0]=[str(root),str(root/'tools')]
van=root/'vanilla/CH_SPIDERMAN/_O0069.0xCFB154CD.T36.apkf'       # the red suit's vanilla files
def script(path,args,blender=False):
    """Run one of our scripts in this process, as if started with these arguments (Blender
    scripts expect their arguments after a '--')."""
    sys.argv=[str(path)]+(['--'] if blender else [])+[str(x) for x in args]
    runpy.run_path(str(path),run_name='__main__')
script(root/'tools/chaine_officielle.py',['--src',job['source'],'--textures',job['textures'],'--vanilla',van,'--out',source,'--drop',job['drop'],'--materiaux',job['materiaux'],'--normale','1'],True)
script(root/'redresser_bras.py',['--mesh',source/'0xAC92103D.ch_spiderman000.mesh','--vanilla',van/'0xAC92103D.ch_spiderman000.mesh','--out',source/'etape_bras.mesh','--fondu',job['fondu']])
script(root/'tools/blacksuit_weights.py',['--mesh',source/'etape_bras.mesh','--vanilla',van/'0xAC92103D.ch_spiderman000.mesh','--skel',van/'0x461356AE.ch_spidermanskeleton_ch_spiderman000.skel','--out',source/'etape_poids.mesh','--voisins',job['voisins'],'--max-os','48'],True)
# The bake left its result in chaine.blend: save the full-size final atlas as a PNG.
bpy.ops.wm.open_mainfile(filepath=str(source/'chaine.blend'))
images=[im for im in bpy.data.images if im.name=='SM3_Spider_Baked_Atlas_FINAL' and im.size[0]>=2048]
assert len(images)==1,'Final atlas ambiguous or missing'
im=images[0];im.filepath_raw=str(source/'atlas_final.png');im.file_format='PNG';im.save()
from blacksuit_build import build
from blacksuit_resources import resolve
build(source,out,resolve(root))
