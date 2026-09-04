"""Does a pure-p lone-pair target actually bring the state back?

Capture rises monotonically as the lone-pair target's s amplitude falls, and
uracil reaches 0.80 and 0.84 at the pure-p end against 0.36 and 0.38 at the
sp2 hybrid in use. That is a suggestive number, not a working space. The gate is
the one that matters: a singlet-constrained CASCI in the seeded space, which
removes orbital optimisation from the question, has to produce an n->pi* root,
and the n orbitals have to actually deplete.

Run at the shipped amplitude and at zero, same molecule, same everything else.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from pyscf import dft, fci, gto, mcscf, scf, tdscf               # noqa: E402

from app.chemistry.cas import geometry                           # noqa: E402
from app.chemistry.cas.excited import analyse                    # noqa: E402
from app.chemistry.cas.narrow import narrow_to_states            # noqa: E402
from app.chemistry.cas.recommend import recommend                # noqa: E402
from app.chemistry.cas.refine import orbital_characters          # noqa: E402
from scripts.casbench import reference_data as ref               # noqa: E402

BASIS = "cc-pvdz"
NAME = sys.argv[1] if len(sys.argv) > 1 else "uracil"
NROOTS = 6

syms, co, chg, mult = ref.molecule(NAME)
co = np.asarray(co, float)
atom = "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}"
                 for s, c in zip(syms, co))
mol = gto.M(atom=atom, basis=BASIS, verbose=0, symmetry=True)
mf = scf.RHF(mol)
mf.kernel()
ks = dft.RKS(mol)
ks.xc = "camb3lyp"
ks.kernel()
td = tdscf.TDA(ks)
td.nstates = 6
td.kernel()

for amp in (1.0 / np.sqrt(3.0), 0.0):
    geometry.SP2_S_AMPLITUDE = amp
    per = geometry.perceive(syms, co, include_sigma=True)
    pi_t = [t for t in per.targets if t.kind == "pi"]
    lp_t = [t for t in per.targets if t.kind == "lone_pair"]
    sg_t = [t for t in per.targets if t.kind == "sigma"]
    rec = recommend(mf, syms, co, spin_2s=0, n_states=3)
    an = analyse(ks, td, per.targets, n_states=3)
    caslst, nelec = narrow_to_states(mol, rec, rec.tiers[rec.recommended], an,
                                     3, pi_t, lp_t, nroots=NROOTS,
                                     csf_budget=float("inf"), perception=per)
    ncas = len(caslst)
    n_occ = int(np.sum(np.asarray(mf.mo_occ, float) > 0))
    occ = np.array([2.0 if c < n_occ else 0.0 for c in caslst])
    labels, _w = orbital_characters(mol, rec.mo_coeff[:, caslst], occ,
                                    pi_t, lp_t, sg_t)

    print("")
    print(f"=== s amplitude {amp:.3f} === ({nelec}e,{ncas}o) caslst {caslst}")
    print(f"    labels {labels}")
    n_at = [i for i, l in enumerate(labels) if l.startswith("n")]
    e_gs = None
    for wfnsym in ("A'", 'A"'):
        mc = mcscf.CASCI(mf, ncas, nelec)
        mc.fcisolver = fci.direct_spin0_symm.FCI(mol)
        mc.fcisolver.nroots = 3
        mc.fcisolver.wfnsym = wfnsym
        seed = mcscf.sort_mo(mc, rec.mo_coeff, [c + 1 for c in caslst], base=1)
        mc.kernel(seed)
        e = np.atleast_1d(np.asarray(mc.e_tot, float))
        if e_gs is None:
            e_gs = float(e[0])
        d0 = np.diag(np.asarray(mc.fcisolver.make_rdm1(mc.ci[0], ncas, nelec)))
        for k in range(len(e)):
            d = np.diag(np.asarray(mc.fcisolver.make_rdm1(mc.ci[k], ncas,
                                                          nelec)))
            print(f"    {wfnsym} state {k}  {(e[k] - e_gs) * 27.2113862:8.3f} eV"
                  f"   n occupancy {[round(float(d[i]), 3) for i in n_at]}")
