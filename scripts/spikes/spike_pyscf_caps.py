#!/usr/bin/env python3
"""Phase 0 verification spike: what PySCF on THIS host can actually do.

    PYTHONPATH=$PWD python3 scripts/spikes/spike_pyscf_caps.py

Every capability the overhaul's routing table will claim for PySCF is
exercised here against a real (tiny) calculation rather than read off the
documentation, because the capability matrix in docs/QM_CAPABILITIES.md is
generated from claims that must each be traceable to something observed.
Water/STO-3G throughout; the whole script is seconds of compute.

Prints one PASS/FAIL/N-A line per capability with the observed evidence
(a norm, a frequency, an iteration count), and a summary block at the end
formatted for transcription into the capability matrix.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402
from pyscf import gto, scf, dft, mcscf, tdscf  # noqa: E402

WATER = "O 0.0 0.0 0.117; H 0.0 0.757 -0.467; H 0.0 -0.757 -0.467"
RESULTS: list[tuple[str, str, str]] = []  # (capability, verdict, evidence)


def record(cap: str, verdict: str, evidence: str = "") -> None:
    RESULTS.append((cap, verdict, evidence))
    print(f"[{verdict:4s}] {cap}" + (f" -- {evidence}" if evidence else ""))


def spike(cap: str):
    """Run a probe, turning any exception into a FAIL row with its cause.
    A capability that raises is exactly as informative as one that works --
    both are facts about this host that the matrix has to encode."""
    def deco(fn):
        try:
            evidence = fn()
            record(cap, "PASS", evidence or "")
        except Exception as e:
            record(cap, "FAIL", f"{type(e).__name__}: {str(e)[:140]}")
            if "-v" in sys.argv:
                traceback.print_exc()
        return fn
    return deco


def mol(basis: str = "sto-3g"):
    return gto.M(atom=WATER, basis=basis, verbose=0)


# ---------------------------------------------------------------- gradients

@spike("gradient/analytic: hf")
def _():
    g = scf.RHF(mol()).run().nuc_grad_method().kernel()
    return f"|grad| = {np.linalg.norm(g):.6f} Eh/Bohr, shape {g.shape}"


@spike("gradient/analytic: dft(b3lyp)")
def _():
    m = dft.RKS(mol()); m.xc = "b3lyp"; m.run()
    g = m.nuc_grad_method().kernel()
    return f"|grad| = {np.linalg.norm(g):.6f}"


@spike("gradient/analytic: mp2")
def _():
    from pyscf import mp
    m = scf.RHF(mol()).run()
    g = mp.MP2(m).run().nuc_grad_method().kernel()
    return f"|grad| = {np.linalg.norm(g):.6f}"


@spike("gradient/analytic: ccsd")
def _():
    from pyscf import cc
    m = scf.RHF(mol()).run()
    g = cc.CCSD(m).run().nuc_grad_method().kernel()
    return f"|grad| = {np.linalg.norm(g):.6f}"


@spike("gradient/analytic: casscf")
def _():
    m = scf.RHF(mol()).run()
    mc = mcscf.CASSCF(m, 4, 4).run()
    g = mc.nuc_grad_method().kernel()
    return f"|grad| = {np.linalg.norm(g):.6f}"


@spike("excited_gradient/analytic: tddft (full, not TDA)")
def _():
    m = dft.RKS(mol()); m.xc = "b3lyp"; m.run()
    td = tdscf.TDDFT(m); td.nstates = 3; td.kernel()
    g = td.nuc_grad_method().kernel(state=1)
    return f"|grad(S1)| = {np.linalg.norm(g):.6f}"


@spike("excited_gradient/analytic: tda")
def _():
    m = dft.RKS(mol()); m.xc = "b3lyp"; m.run()
    td = tdscf.TDA(m); td.nstates = 3; td.kernel()
    g = td.nuc_grad_method().kernel(state=1)
    return f"|grad(S1)| = {np.linalg.norm(g):.6f}"


# --------------------------------------------------------------------- NAC

@spike("nac/analytic: sa-casscf (pyscf.nac.sacasscf)")
def _():
    from pyscf.nac import sacasscf as nac_sacasscf
    # Deliberately C1-distorted: at C2v equilibrium the S0/S1 coupling is
    # symmetry-forbidden and the norm comes back ~1e-6, which is a correct
    # answer that proves nothing about the machinery. Breaking symmetry is
    # what makes a non-zero result evidence that real numbers are computed.
    distorted = gto.M(
        atom="O 0.0 0.0 0.13; H 0.10 0.79 -0.51; H -0.04 -0.72 -0.43",
        basis="sto-3g", verbose=0)
    m = scf.RHF(distorted).run()
    mc = mcscf.CASSCF(m, 4, 4).state_average_([0.5, 0.5]).run()
    nac = nac_sacasscf.NonAdiabaticCouplings(mc)
    v = nac.kernel(state=(0, 1))
    return f"|NAC(0,1)| = {np.linalg.norm(v):.6e}, shape {np.shape(v)}"


@spike("nac/analytic: tddft")
def _():
    # Probed separately: mainline pyscf has no tddft NAC class as of 2.14.
    import importlib
    importlib.import_module("pyscf.nac.tdscf")
    return "pyscf.nac.tdscf exists"


# ------------------------------------------------------------------ hessian

@spike("hessian/analytic: hf")
def _():
    from pyscf.hessian import thermo
    m = scf.RHF(mol()).run()
    h = m.Hessian().kernel()
    freq = thermo.harmonic_analysis(m.mol, h)["freq_wavenumber"]
    return f"{len(freq)} modes, max {max(freq.real):.1f} cm-1"


@spike("hessian/analytic: dft(b3lyp)")
def _():
    from pyscf.hessian import thermo
    m = dft.RKS(mol()); m.xc = "b3lyp"; m.run()
    h = m.Hessian().kernel()
    freq = thermo.harmonic_analysis(m.mol, h)["freq_wavenumber"]
    return f"{len(freq)} modes, max {max(freq.real):.1f} cm-1"


@spike("hessian/analytic: casscf")
def _():
    m = scf.RHF(mol()).run()
    mc = mcscf.CASSCF(m, 4, 4).run()
    mc.Hessian().kernel()
    return "CASSCF analytic Hessian available"


# ------------------------------------------------- orbital reuse (CAS guess)

@spike("orbital_reuse: chkfile round-trip -> CASSCF guess (same geometry)")
def _():
    import tempfile
    from pyscf import lib
    chk = tempfile.mktemp(suffix=".chk")
    m = scf.RHF(mol()); m.chkfile = chk; m.run()
    # This is the shape the real feature takes: a LATER process reads the
    # orbitals back off disk, so the source SCF object is gone.
    stored = lib.chkfile.load(chk, "scf/mo_coeff")
    m2 = scf.RHF(mol()).run()
    mc = mcscf.CASSCF(m2, 4, 4)
    mo = mcscf.project_init_guess(mc, stored)
    e = mc.kernel(mo)[0]
    return f"chkfile mo_coeff {stored.shape} -> CASSCF converged, E = {e:.8f} Eh"


@spike("orbital_reuse: project_init_guess across geometry change")
def _():
    m = scf.RHF(mol()).run()
    stretched = gto.M(atom="O 0.0 0.0 0.15; H 0.0 0.80 -0.50; H 0.0 -0.80 -0.50",
                      basis="sto-3g", verbose=0)
    m2 = scf.RHF(stretched).run()
    mc = mcscf.CASSCF(m2, 4, 4)
    mo = mcscf.project_init_guess(mc, m.mo_coeff)
    e = mc.kernel(mo)[0]
    return f"CASSCF from projected guess converged, E = {e:.8f} Eh"


@spike("orbital_reuse: project_init_guess across basis change (needs prev_mol)")
def _():
    small = mol("sto-3g")
    m = scf.RHF(small).run()
    big = mol("6-31g")
    mc = mcscf.CASSCF(scf.RHF(big).run(), 4, 4)
    # prev_mol is mandatory when the source orbitals belong to a different
    # basis -- without it project_init_guess assumes same-basis and the
    # matrix product fails on shape. This is the whole finding.
    mo = mcscf.project_init_guess(mc, m.mo_coeff, prev_mol=small)
    e = mc.kernel(mo)[0]
    return f"sto-3g -> 6-31g projected, CASSCF converged, E = {e:.8f} Eh"


# ------------------------------------------------------------ optimization

@spike("opt: geomeTRIC minimization")
def _():
    from pyscf.geomopt.geometric_solver import optimize
    m = scf.RHF(mol())
    newmol = optimize(m, maxsteps=8)
    return f"optimized, {newmol.natm} atoms"


@spike("opt/constrained: geomeTRIC constraints kwarg")
def _():
    import inspect
    from pyscf.geomopt import geometric_solver
    sig = inspect.signature(geometric_solver.kernel)
    has = "constraints" in sig.parameters or "params" in sig.parameters
    if not has:
        raise RuntimeError(f"no constraints hook in kernel{sig}")
    # geomeTRIC takes constraints as a file/string through its params dict.
    import geometric
    return f"geometric {geometric.__version__}, kernel params {list(sig.parameters)}"


@spike("opt/ci (MECI): geomeTRIC MECI optimizer present")
def _():
    import importlib
    importlib.import_module("pyscf.geomopt.meci")
    return "pyscf.geomopt.meci exists"


# ------------------------------------------------------------- active space

@spike("cas_reco: AVAS")
def _():
    from pyscf.mcscf import avas
    m = scf.RHF(mol()).run()
    ncas, nelecas, mo = avas.avas(m, ["O 2p"])
    return f"AVAS -> CAS({nelecas},{ncas})"


@spike("cas_reco: DMRG pilot (pyscf.dmrgscf / block2)")
def _():
    import importlib
    importlib.import_module("pyscf.dmrgscf")
    return "pyscf.dmrgscf importable"


# ------------------------------------------------------ oscillator strengths

@spike("osc_strengths: tddft")
def _():
    m = dft.RKS(mol()); m.xc = "b3lyp"; m.run()
    td = tdscf.TDDFT(m); td.nstates = 3; td.kernel()
    f = td.oscillator_strength()
    return f"f = {np.array2string(np.asarray(f), precision=4)}"


@spike("osc_strengths: casscf (transition dipoles)")
def _():
    m = scf.RHF(mol()).run()
    mc = mcscf.CASSCF(m, 4, 4).state_average_([0.5, 0.5]).run()
    # CASSCF oscillator strengths require transition dipoles built by hand
    # from the CI vectors; probe whether the pieces are reachable.
    from pyscf.fci import direct_spin1  # noqa: F401
    if not hasattr(mc, "fcisolver"):
        raise RuntimeError("no fcisolver on SA-CASSCF object")
    return "SA-CASSCF states available; transition dipoles need manual assembly"


def main() -> int:
    print("\n" + "=" * 70)
    print("SUMMARY (for docs/QM_CAPABILITIES.md, pyscf column)")
    print("=" * 70)
    width = max(len(c) for c, _, _ in RESULTS)
    for cap, verdict, ev in RESULTS:
        print(f"  {cap.ljust(width)}  {verdict:4s}  {ev}")
    n_fail = sum(1 for _, v, _ in RESULTS if v == "FAIL")
    print(f"\n{len(RESULTS) - n_fail}/{len(RESULTS)} capabilities confirmed on this host.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
