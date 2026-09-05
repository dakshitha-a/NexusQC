"""water narrowed to (4,2) in one run of narrowing_agreement and (2,1) in the
next, with no code between them touching narrow_to_states. Is it unstable?"""
import numpy as np
from pyscf import tdscf

from app.chemistry.cas.excited import analyse
from app.chemistry.cas.geometry import perceive
from app.chemistry.cas.narrow import narrow_to_states
from app.chemistry.cas.recommend import recommend
from scripts.casbench import reference_data as ref
from scripts.casbench.run_bench import _mf

syms, co, chg, mult = ref.molecule("water")
co = np.asarray(co, float)

for trial in range(3):
    _m, mf = _mf(syms, co, "def2-svpd", chg, mult)
    rec = recommend(mf, syms, co, spin_2s=0, n_states=3)
    _m2, ks = _mf(syms, co, "def2-svpd", chg, mult, dft_xc="camb3lyp")
    td = tdscf.TDA(ks)
    td.nstates = 6
    td.kernel()
    per = perceive(syms, co, include_sigma=False)
    an = analyse(ks, td, per.targets, n_states=2)
    pi_t = [t for t in per.targets if t.kind == "pi"]
    lp_t = [t for t in per.targets if t.kind == "lone_pair"]
    base = rec.tiers[rec.recommended]
    cas, ne = narrow_to_states(mf.mol, rec, base, an, 3, pi_t, lp_t,
                               nroots=3, csf_budget=float("inf"),
                               perception=per)
    chars = [s.character for s in an.states[:2]]
    print(f"trial {trial}: pool {rec.space} -> narrowed ({ne},{len(cas)})  "
          f"caslst {sorted(cas)}  TDA states {chars}")
