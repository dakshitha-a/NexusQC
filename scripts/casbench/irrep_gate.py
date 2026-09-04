"""Does the lone-pair target reach the state, and does the solver then find it?

Two separate questions, and the difference between them is the whole reason this
script exists rather than a plain CASCI.

The first is whether the space can describe the state at all. That is answered
by solving the irrep the state lives in, explicitly, which sidesteps the
question of whether a solver would have stumbled into it. For a planar molecule
the reference is A' and every n->pi* is A''.

The second is whether the shipped path, an unsymmetrised Davidson asked for a
handful of roots, actually finds it. Those come apart. A Davidson reaches only
what its initial guess spans, and PySCF builds that guess from the
lowest-diagonal determinants; a mis-aimed lone-pair target pushes the n->pi*
determinants out of that window, and in a planar molecule exact symmetry then
guarantees that no iteration pulls them back, because the coupling between the
blocks is identically zero. In a small space the guess holds everything and the
state is found regardless. In a large one it is not.

So both solves run at every lone-pair target amplitude asked for, on the same
SCF and the same recommendation, and the numbers say which of the two problems a
change to the target actually fixes. The verdict line reports the only thing a
user would notice: whether the solver the engine actually runs comes back with
the state.

Works in any abelian point group: the irreps are read off the molecule rather
than hardcoded, and the unsymmetrised solve needs no symmetry at all, so a
molecule pyscf puts in C1 still gets the answer that matters.

Usage:
    python3 scripts/casbench/irrep_gate.py [molecule] [basis]
    QC_GATE_AMPS=0.577,0.35 python3 scripts/casbench/irrep_gate.py uracil
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

NAME = sys.argv[1] if len(sys.argv) > 1 else "uracil"
BASIS = sys.argv[2] if len(sys.argv) > 2 else "def2-svpd"
NROOTS = int(os.environ.get("QC_GATE_ROOTS", "8"))
AMPS = [float(a) for a in os.environ.get(
    "QC_GATE_AMPS", f"{1.0 / np.sqrt(3.0)},0.0").split(",")]
HARTREE_EV = 27.211386245988

syms, co, chg, mult = ref.molecule(NAME)
co = np.asarray(co, float)
atom = "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}"
                 for s, c in zip(syms, co))
try:
    mol = gto.M(atom=atom, basis=BASIS, verbose=0, symmetry=True)
    irreps = sorted(set(mol.irrep_name))
except Exception:                                                # noqa: BLE001
    mol = gto.M(atom=atom, basis=BASIS, verbose=0)
    irreps = []
print(f"{NAME}, {BASIS}, point group {getattr(mol, 'groupname', 'C1')}, "
      f"irreps {irreps or 'none (unsymmetrised only)'}")

mf = scf.RHF(mol)
mf.kernel()
ks = dft.RKS(mol)
ks.xc = "camb3lyp"
ks.kernel()
td = tdscf.TDA(ks)
td.nstates = 6
td.kernel()

for amp in AMPS:
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
    n_at = [i for i, l in enumerate(labels) if l.startswith("n")]

    print("")
    print(f"=== lone-pair target s amplitude {amp:.3f} ===")
    print(f"    ({nelec}e,{ncas}o) caslst {caslst}")
    print(f"    labels {labels}")

    def solve(tag, solver, nroots, wfnsym=None):
        mc = mcscf.CASCI(mf, ncas, nelec)
        mc.fcisolver = solver
        mc.fcisolver.nroots = nroots
        if wfnsym is not None:
            mc.fcisolver.wfnsym = wfnsym
        seed = mcscf.sort_mo(mc, rec.mo_coeff, [c + 1 for c in caslst], base=1)
        mc.kernel(seed)
        e = np.atleast_1d(np.asarray(mc.e_tot, float))
        d0 = np.diag(np.asarray(mc.fcisolver.make_rdm1(mc.ci[0], ncas, nelec)))
        out = []
        for k in range(len(e)):
            d = np.diag(np.asarray(mc.fcisolver.make_rdm1(mc.ci[k], ncas,
                                                          nelec)))
            dn = min(d[i] - d0[i] for i in n_at) if n_at else 0.0
            out.append((float(e[k]), dn))
        return tag, out

    # The unsymmetrised solve is the one that matters, because it is what the
    # engine actually runs. The per-irrep solves say whether a state the
    # unsymmetrised run missed is present in the space at all.
    runs = [solve("unsym'ised", fci.direct_spin0.FCI(), NROOTS)]
    for irr in irreps:
        try:
            runs.append(solve(f"{irr:9s}", fci.direct_spin0_symm.FCI(mol),
                              2, irr))
        except Exception as exc:                                 # noqa: BLE001
            print(f"    {irr:9s} solve failed: {type(exc).__name__}")
    e_gs = min(out[0][0] for _tag, out in runs)
    found_unsym = False
    for tag, out in runs:
        for k, (e, dn) in enumerate(out):
            real = dn < -0.30
            if real and tag.startswith("unsym"):
                found_unsym = True
            hole = "  <-- real n hole" if real else ""
            print(f"    {tag} state {k}  {(e - e_gs) * HARTREE_EV:8.3f} eV"
                  f"   n depletion {dn:+.3f}{hole}")
    print(f"    VERDICT: the shipped unsymmetrised solve "
          f"{'FINDS' if found_unsym else 'does NOT find'} an n-hole state "
          f"in {NROOTS} roots")

geometry.SP2_S_AMPLITUDE = 1.0 / np.sqrt(3.0)
