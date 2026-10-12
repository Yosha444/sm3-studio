# SPDX-License-Identifier: GPL-3.0-or-later
"""blacksuit_finalize.py - last step of the Black Suit target, outside Blender.

    <python with numpy + Pillow> blacksuit_finalize.py <build>/blacksuit_job.json

Started by blacksuit_runner.py after the Blender part (blacksuit_pipeline.py). In order:
  1. dilater_atlas.py (project root): fills the UV gutters of source/atlas_final.png around the
     islands of etape_poids.mesh -> atlas_dilate.png (no seams once mip-mapped);
  2. winding_fix.py on each mesh listed in validation.json (face orientation and normals), then
     the mesh's sha256 is written back into validation.json, since winding_fix may rewrite it;
  3. blacksuit_package.package(): texture encoding, checks, copy into the mod folder.
"""
import sys,json,runpy
from pathlib import Path
job=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
root=Path(job['root']);out=Path(job['out']);source=out/'source'
sys.path[:0]=[str(root),str(root/'tools')]
sys.argv=['dilate','--atlas',str(source/'atlas_final.png'),'--mesh',str(source/'etape_poids.mesh'),'--out',str(out/'atlas_dilate.png'),'--pixels',str(job['dilate'])]
runpy.run_path(str(root/'dilater_atlas.py'),run_name='__main__')
from blacksuit_package import package
import subprocess,hashlib
state=json.loads((out/'validation.json').read_text())
for variant in state['variants'].values():
    mesh=out/variant['file']
    subprocess.run([sys.executable,str(root/'tools/winding_fix.py'),str(mesh)],check=True)
    variant['sha256']=hashlib.sha256(mesh.read_bytes()).hexdigest()
(out/'validation.json').write_text(json.dumps(state,indent=2))
package(out,job['destination'],job.get('format','DXT5'))
