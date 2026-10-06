#!/usr/bin/env python3
"""Phase 0 of the QUESTDB benchmark: can our stack reproduce King et al.'s energies?

King, Hermes, Truhlar and Gagliardi (JCTC 2022, 18, 6065) ship three test
scripts with their Zenodo record. Each loads one saved SA-CASSCF wavefunction
(orbitals and CI vectors), rebuilds the molecule, and recomputes the MC-PDFT
energy decomposition and the SC-NEVPT2 correction for every state, asserting
agreement with the stored values to 1e-5 Eh. Those scripts import `mrh` and
call `DataFrame.append`, neither of which exists in this environment, so this
is the same procedure rewritten against PySCF 2.14 and pyscf-forge's
`mcpdft`, reading the version-neutral files `quest_unpickle.py` writes.

Nothing here selects an active space or optimises orbitals. It answers one
question: given identical wavefunctions, does our downstream code (MC-PDFT
and NEVPT2) give the numbers theirs gave? If it does not, no comparison the
benchmark makes later can be attributed to the choice of active space.

    python3 scripts/casbench/quest_reproduce_king.py Jun88 water-x1 water-x6 cn-x1

Default names are the three King shipped tests. Prints, per state and per
energy component, our value, theirs and the difference, then the excitation
energies (eV) both ways.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / ".cache" / "casbench_quest"
HARTREE_TO_EV = 27.211386245988
COMPONENTS = ["e_nuc", "e_core", "e_coul", "e_otx", "e_otc", "e_wfnxc"]
SS_TO_TWO_MS = {0.0: 0, 0.75: 1, 2.0: 2}


def basis_for(name: str, elements):
    """King's 'jun-ccpvtz' is a file shipped with the record, not a PySCF name.

    `gto.basis.parse` without `symb` concatenates every element in the file
    into one shell list, which gave water 2142 functions instead of 67 and
    a segfault in the J/K build. Parse per element.
    """
    if name.replace("-", "").lower() == "junccpvtz":
        from pyscf import gto
        text = open(CACHE / "zenodo" / "jun-cc-pvtz.dat").read()
        return {el: gto.basis.parse(text, symb=el) for el in set(elements)}
    return name


def build_mol(meta):
    from pyscf import gto
    b = basis_for(meta["basis"], [s for s, _ in meta["geom"]])
    mol = gto.Mole()
    mol.atom = [(s, xyz) for s, xyz in meta["geom"]]
    mol.unit = meta["unit"]
    mol.charge = meta["charge"]
    mol.spin = meta["hf_spin"]
    mol.symmetry = True
    mol.basis = b
    mol.verbose = 0
    mol.build()
    return mol


def nelecas_for(total: int, ss: float):
    """Highest Ms for the state's spin, as King's tests do."""
    two_ms = SS_TO_TWO_MS[round(float(ss), 2)]
    na, nb = total // 2 + total % 2, total // 2
    while na - nb != two_ms:
        na += 1
        nb -= 1
    return (na, nb)


def reproduce(combo: str, name: str, do_nevpt2: bool = True) -> dict:
    from pyscf import mcpdft, mcscf, mrpt, scf

    base = CACHE / "king_npz" / combo / name
    data = json.load(open(base.with_suffix(".json")))
    arr = np.load(base.with_suffix(".npz"))
    meta = data["metadata"]
    mol = build_mol(meta)
    mf = scf.ROHF(mol)
    mo = arr["mo_coeff"]
    mf.mo_coeff = mo
    ncas = int(meta["ncas"])
    total = int(sum(meta["nelecas"]))
    rows = []
    t0 = time.time()
    for i, ref in enumerate(data["energies"]):
        nel = nelecas_for(total, ref["ss"])
        ci = arr[f"ci_{i}"]
        mc = mcpdft.CASCI(mf, meta["otfnal"], ncas, nel,
                          grids_level=meta["grid_level"])
        mc.mo_coeff = mo
        mc.ci = ci
        dec = mc.get_energy_decomposition(mo_coeff=mo, ci=ci)
        ours = dict(zip(COMPONENTS, [float(np.ravel(x)[0]) for x in dec[:6]]))
        if do_nevpt2:
            c2 = mcscf.CASCI(mf, ncas, nel)
            c2.mo_coeff = mo
            c2.ci = ci
            ours["e_nevpt2"] = float(mrpt.NEVPT(c2).kernel())
        rows.append({"state": i, "sym": ref["sym"], "ss": ref["ss"], "nelecas": nel,
                     "ours": ours,
                     "theirs": {k: ref[k] for k in ours}})
    return {"combo": combo, "name": name, "nao": mol.nao, "ncas": ncas,
            "seconds": round(time.time() - t0, 1), "states": rows,
            "energies": data["energies"]}


def main(argv) -> int:
    combo = argv[1] if len(argv) > 1 else "Jun88"
    names = argv[2:] or ["water-x1", "water-x6", "cn-x1"]
    worst = 0.0
    for name in names:
        r = reproduce(combo, name)
        print(f"\n{combo}/{name}: {r['nao']} basis functions, CAS({sum(r['states'][0]['nelecas'])},"
              f"{r['ncas']}), {len(r['states'])} states, {r['seconds']} s")
        for s in r["states"]:
            print(f"  state {s['state']} {s['sym']:4s} S^2={s['ss']:.2f} nelecas={s['nelecas']}")
            for k in s["ours"]:
                d = s["ours"][k] - s["theirs"][k]
                worst = max(worst, abs(d))
                flag = "" if abs(d) < 1e-5 else "   <-- differs"
                print(f"    {k:9s} ours {s['ours'][k]:16.8f}  theirs {s['theirs'][k]:16.8f}"
                      f"  diff {d:+.2e}{flag}")
        # Excitation energies the way the benchmark scores them: lowest state
        # of the ground-state irrep versus the highest state of the target.
        e = r["energies"]
        for method in ("tPBE", "NEVPT2"):
            theirs = [x[method] for x in e]
            ours = []
            for s in r["states"]:
                o = s["ours"]
                tpbe = sum(o[k] for k in COMPONENTS[:5])
                ours.append(tpbe if method == "tPBE" else e[s["state"]]["CASSCF"] + o["e_nevpt2"])
            ex_t = (max(theirs[1:]) - theirs[0]) * HARTREE_TO_EV
            ex_o = (max(ours[1:]) - ours[0]) * HARTREE_TO_EV
            print(f"  {method:6s} excitation  ours {ex_o:.4f} eV  theirs {ex_t:.4f} eV  "
                  f"diff {ex_o - ex_t:+.4f} eV")
    print(f"\nlargest component difference over all states: {worst:.2e} Eh "
          f"({worst * HARTREE_TO_EV:.2e} eV); King's own tolerance is 1e-5 Eh")
    return 0 if worst < 1e-5 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
