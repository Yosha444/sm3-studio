# SPDX-License-Identifier: GPL-3.0-or-later
"""blacksuit_weights.py - poids_depuis_vanilla.py with a fast nearest-neighbour search (Black Suit).

Step 3 of blacksuit_pipeline.py; runs inside Blender because it uses Blender's
mathutils.kdtree. Arguments after '--' are those of poids_depuis_vanilla.py ("weights from the
vanilla": each vertex blends the skin weights of its nearest vanilla vertices).

Why: poids_depuis_vanilla.plus_proches ("nearest") is an exact brute-force search in numpy
blocks. This file swaps it for a KD-tree, then checks 32 evenly spread vertices against the
exact search (distances within 1e-6 absolute / 1e-5 relative) before trusting it, and prints
NEAREST_NEIGHBOURS_CHECKED. Equal distances are ordered by vertex index.
"""
import sys
from pathlib import Path
import numpy as np
from mathutils.kdtree import KDTree
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
import poids_depuis_vanilla as module
original=module.plus_proches
def nearest(P,Q,k,pas=192):
 """Same contract as poids_depuis_vanilla.plus_proches: (indices, distances) of the k vertices
 of Q nearest to each vertex of P. `pas` (block size) is unused, kept for the signature."""
 tree=KDTree(len(Q))
 for i,p in enumerate(Q):tree.insert(tuple(p),i)
 tree.balance();indices=np.empty((len(P),k),int);distances=np.empty((len(P),k))
 for i,p in enumerate(P):
  rows=sorted(tree.find_n(tuple(p),k),key=lambda r:(r[2],r[1]))      # r = (co, index, dist)
  indices[i]=[r[1] for r in rows];distances[i]=[r[2] for r in rows]
 sample=np.linspace(0,len(P)-1,32,dtype=int);_,exact=original(P[sample],Q,k)
 assert np.allclose(distances[sample],exact,atol=1e-6,rtol=1e-5),'KD nearest mismatch'
 print('NEAREST_NEIGHBOURS_CHECKED',len(P),flush=True)
 return indices,distances
module.plus_proches=nearest
sys.argv=['weights']+sys.argv[sys.argv.index('--')+1:]
module.main()
