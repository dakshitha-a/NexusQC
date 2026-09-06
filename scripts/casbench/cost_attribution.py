"""Where does a ground-state recommendation's time go, now that it is 1.52 s?

The method document quotes 0.27 s at the median. The fresh `spaces` ledger says
1.52 s. A figure that moved by more than five times is not something to
overwrite quietly, so this splits the cost into its parts for a sample of the
benchmark: the SCF itself, the stability analysis added when the reference
started being stabilised, and the selection that follows.
"""
import os
import statistics
import sys
import time

import numpy as np

sys.path.insert(0, os.getcwd())
from pyscf import gto, scf

from app.chemistry.cas.recommend import recommend
from app.chemistry.cas.reference import stabilise
from scripts.casbench import reference_data as ref

MOLECULES = ["water", "formaldehyde", "benzene", "pyridine", "uracil",
             "ethylene", "butadiene", "furan", "acetone", "ammonia"]
BASIS = "def2-svp"

rows = []
for name in MOLECULES:
    syms, co, chg, mult = ref.molecule(name)
    co = np.asarray(co, float)
    atom = "\n".join(f"{s} {c[0]:.8f} {c[1]:.8f} {c[2]:.8f}"
                     for s, c in zip(syms, co))
    mol = gto.M(atom=atom, basis=BASIS, charge=chg, spin=mult - 1, verbose=0)

    t0 = time.perf_counter()
    mf = (scf.RHF(mol) if mult == 1 else scf.ROHF(mol)).density_fit()
    mf.kernel()
    t_scf = time.perf_counter() - t0

    t0 = time.perf_counter()
    stabilise(mf, check_external=False)
    t_stab = time.perf_counter() - t0

    t0 = time.perf_counter()
    recommend(mf, syms, co, spin_2s=mult - 1)
    t_sel = time.perf_counter() - t0

    total = t_scf + t_stab + t_sel
    rows.append((name, t_scf, t_stab, t_sel, total))
    print(f"  {name:16s} scf {t_scf:6.2f}  stability {t_stab:6.2f}  "
          f"selection {t_sel:6.2f}  total {total:6.2f}")

print()
for label, i in (("SCF", 1), ("stability", 2), ("selection", 3), ("total", 4)):
    vals = [r[i] for r in rows]
    print(f"  median {label:10s} {statistics.median(vals):6.2f} s")
stab = statistics.median([r[2] for r in rows])
tot = statistics.median([r[4] for r in rows])
print(f"\n  stability analysis is {100 * stab / tot:.0f}% of the median total")
