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


# ------------------------------------ NEVPT2, MC-PDFT and L-PDFT (2026-08-29)
#
# All three sit on a CASSCF wave function, so what separates them here is
# not whether they produce an energy -- they all do -- but which
# derivatives and which transition properties come with it. Those two
# questions decide the whole feature: no gradient means no optimization
# and no frequencies, and no transition dipole means no oscillator
# strength and therefore no nuclear-ensemble spectrum, which
# wigner_spectra requires outright rather than warns about.
#
# NEVPT2 is core pyscf (pyscf.mrpt). MC-PDFT and L-PDFT ship in
# pyscf-forge under the pyscf.mcpdft namespace.

@spike("nevpt2: energy on a CASSCF reference")
def _():
    from pyscf import mrpt
    m = scf.RHF(mol()).run()
    mc = mcscf.CASSCF(m, 4, 4).run()
    ec = mrpt.NEVPT(mc).kernel()
    return (f"E_CASSCF = {mc.e_tot:.8f}, E_corr = {ec:.8f}, "
            f"E_tot = {mc.e_tot + ec:.8f} Eh")


@spike("nevpt2: state-averaged FCI solver refused (why the excited path is CASCI)")
def _():
    from pyscf import mrpt
    m = scf.RHF(mol()).run()
    sa = mcscf.CASSCF(m, 4, 4).state_average_([0.5, 0.5]).run()
    try:
        mrpt.NEVPT(sa, root=1).kernel()
    except RuntimeError as e:
        return f"refused as expected: {e}"
    raise RuntimeError("a state-averaged solver was accepted -- the excited path can be simpler")


@spike("nevpt2/excited: SA-CASSCF orbitals -> multi-root CASCI -> per-root NEVPT2")
def _():
    from pyscf import mrpt
    m = scf.RHF(mol()).run()
    sa = mcscf.CASSCF(m, 4, 4).state_average_([1 / 3.] * 3).run()
    ci = mcscf.CASCI(m, 4, 4)
    ci.fcisolver.nroots = 3
    ci.kernel(sa.mo_coeff)
    tot = [float(ci.e_tot[r]) + float(mrpt.NEVPT(ci, root=r).kernel()) for r in range(3)]
    dE = [(t - tot[0]) * 27.211386 for t in tot[1:]]
    return f"3 roots, dE = {[round(x, 4) for x in dE]} eV"


@spike("nevpt2/gradient: nuc_grad_method")
def _():
    from pyscf import mrpt
    m = scf.RHF(mol()).run()
    mc = mcscf.CASSCF(m, 4, 4).run()
    mrpt.NEVPT(mc).nuc_grad_method()
    return "NEVPT exposes a gradient"


@spike("nevpt2/osc_strengths: transition moments")
def _():
    from pyscf import mrpt
    m = scf.RHF(mol()).run()
    mc = mcscf.CASSCF(m, 4, 4).run()
    nev = mrpt.NEVPT(mc)
    found = [a for a in dir(nev) if any(k in a.lower() for k in ("dip", "trans_moment", "osc"))]
    if not found:
        raise RuntimeError("no dipole/transition-moment attribute on the NEVPT object")
    return f"transition-property attributes: {found}"


@spike("mcpdft: energy (tPBE)")
def _():
    from pyscf import mcpdft
    m = scf.RHF(mol()).run()
    mc = mcpdft.CASSCF(m, "tPBE", 4, 4).run()
    return (f"E_tot = {mc.e_tot:.8f}, E_MCSCF = {mc.e_mcscf:.8f}, "
            f"E_ot = {mc.e_ot:.8f} Eh")


@spike("mcpdft: on-top functional names accepted")
def _():
    from pyscf import mcpdft
    m = scf.RHF(mol()).run()
    out = {}
    for name in ("tPBE", "ftPBE", "tBLYP", "tLDA", "tM06L"):
        out[name] = round(float(mcpdft.CASSCF(m, name, 4, 4).run().e_tot), 6)
    return ", ".join(f"{k} = {v}" for k, v in out.items())


@spike("mcpdft/gradient: analytic")
def _():
    from pyscf import mcpdft
    m = scf.RHF(mol()).run()
    mc = mcpdft.CASSCF(m, "tPBE", 4, 4).run()
    g = mc.nuc_grad_method().kernel()
    return f"|grad| = {np.linalg.norm(g):.6f} Eh/Bohr, shape {np.asarray(g).shape}"


@spike("mcpdft/excited: state-averaged energies")
def _():
    from pyscf import mcpdft
    from pyscf.csf_fci import csf_solver
    m = scf.RHF(mol()).run()
    mc = mcpdft.CASSCF(m, "tPBE", 4, 4)
    # The same spin-adapted solver the app puts under every pair-density
    # state average, so this records what the app actually produces.
    mc.fcisolver = csf_solver(m.mol, smult=1)
    mc = mc.state_average_([0.5, 0.5]).run()
    return f"e_states = {np.array2string(np.asarray(mc.e_states), precision=6)}"


@spike("mcpdft/excited_gradient: state-selected")
def _():
    from pyscf import mcpdft
    m = scf.RHF(mol()).run()
    mc = mcpdft.CASSCF(m, "tPBE", 4, 4).state_average_([0.5, 0.5])
    mc.kernel()
    g = mc.nuc_grad_method().kernel(state=1)
    return f"|grad(S1)| = {np.linalg.norm(g):.6f} Eh/Bohr"


@spike("mcpdft/hessian: analytic")
def _():
    from pyscf import mcpdft
    m = scf.RHF(mol()).run()
    mc = mcpdft.CASSCF(m, "tPBE", 4, 4).run()
    mc.Hessian()
    return "MC-PDFT analytic Hessian available"


@spike("mcpdft/hessian: this app's numerical Hessian drives the MC-PDFT gradient")
def _():
    from pyscf import mcpdft
    from app.chemistry.jobs.pyscf_runner import _numerical_casscf_hessian
    m = scf.RHF(mol()).run()
    mc = mcpdft.CASSCF(m, "tPBE", 4, 4)
    mc.kernel()
    h = _numerical_casscf_hessian(mc)
    return f"numerical Hessian shape {np.asarray(h).shape}"


@spike("mcpdft/nac: state pair on a state-averaged object")
def _():
    from pyscf import mcpdft
    m = scf.RHF(mol()).run()
    mc = mcpdft.CASSCF(m, "tPBE", 4, 4).state_average_([0.5, 0.5])
    mc.kernel()
    nac = mc.nac_method().kernel(state=(0, 1))
    return f"NAC shape {np.asarray(nac).shape}, norm {np.linalg.norm(nac):.6e}"


@spike("mcpdft/osc_strengths: transition dipoles on a state-averaged object")
def _():
    from pyscf import mcpdft
    m = scf.RHF(mol()).run()
    mc = mcpdft.CASSCF(m, "tPBE", 4, 4).state_average_([0.5, 0.5])
    mc.kernel()
    if not hasattr(mc, "trans_moment"):
        raise RuntimeError(
            "no trans_moment on a state-averaged MC-PDFT object; pyscf.prop.trans_dip_moment "
            "implements TransitionDipole for the CMS-PDFT variant only")
    return "state-averaged MC-PDFT exposes trans_moment"


@spike("lpdft: energies (multi_state method='LIN')")
def _():
    from pyscf import mcpdft
    from pyscf.csf_fci import csf_solver
    m = scf.RHF(mol()).run()
    mc = mcpdft.CASSCF(m, "tPBE", 4, 4)
    mc.fcisolver = csf_solver(m.mol, smult=1)
    lp = mc.multi_state([1 / 3.] * 3, method="LIN").run()
    dE = [(e - lp.e_states[0]) * 27.211386 for e in lp.e_states[1:]]
    return (f"{type(lp).__name__}, 3 states, dE = {[round(float(x), 4) for x in dE]} eV")


@spike("lpdft/gradient: ground and excited state")
def _():
    from pyscf import mcpdft
    m = scf.RHF(mol()).run()
    lp = mcpdft.CASSCF(m, "tPBE", 4, 4).multi_state([0.5, 0.5], method="LIN")
    lp.kernel()
    g0 = lp.nuc_grad_method().kernel(state=0)
    g1 = lp.nuc_grad_method().kernel(state=1)
    return (f"|grad(S0)| = {np.linalg.norm(g0):.6f}, "
            f"|grad(S1)| = {np.linalg.norm(g1):.6f} Eh/Bohr")


@spike("lpdft/nac: state pair")
def _():
    from pyscf import mcpdft
    m = scf.RHF(mol()).run()
    lp = mcpdft.CASSCF(m, "tPBE", 4, 4).multi_state([0.5, 0.5], method="LIN")
    lp.kernel()
    nac = lp.nac_method().kernel(state=(0, 1))
    return f"NAC shape {np.asarray(nac).shape}, norm {np.linalg.norm(nac):.6e}"


@spike("lpdft/osc_strengths: transition dipoles")
def _():
    from pyscf import mcpdft
    m = scf.RHF(mol()).run()
    lp = mcpdft.CASSCF(m, "tPBE", 4, 4).multi_state([0.5, 0.5], method="LIN")
    lp.kernel()
    if not hasattr(lp, "trans_moment"):
        raise RuntimeError(
            "no trans_moment on an L-PDFT object; pyscf.prop.trans_dip_moment implements "
            "TransitionDipole for the CMS-PDFT variant only")
    return "L-PDFT exposes trans_moment"


# ---------------------------------------------- CMS-PDFT (2026-08-29, later)
#
# The variant that has transition dipoles. Everything below exists to
# establish two things: that the intensities are real rather than numerical
# noise, and what has to be true of the state average for them to be.

def _furan():
    """The molecule pyscf's own transition-dipole test uses, so the values
    here can be compared against something with published references
    rather than only against themselves. Water/STO-3G is useless for this:
    its low-lying transitions are dark by symmetry, so a zero there proves
    nothing either way."""
    return gto.M(atom="""
      C   0.000000000  -0.965551055  -2.020010585
      C   0.000000000  -1.993824223  -1.018526668
      C   0.000000000  -1.352073201   0.181141565
      O   0.000000000   0.000000000   0.000000000
      C   0.000000000   0.216762264  -1.346821565
      H   0.000000000  -1.094564216  -3.092622941
      H   0.000000000  -3.062658055  -1.175803180
      H   0.000000000  -1.688293885   1.206105691
      H   0.000000000   1.250242874  -1.655874372
    """, basis="sto-3g", verbose=0)


def _cms(mol_, n=3, fix_spin=True, ot="tPBE"):
    """The app's own construction: a spin-adapted CSF solver under the state
    average, then the CMS diabatization. `fix_spin=False` reproduces the
    unconstrained version, which is what the vanishing-intensity probe
    below needs."""
    from pyscf import mcpdft
    from pyscf.csf_fci import csf_solver
    mf = scf.RHF(mol_).run()
    mc = mcpdft.CASSCF(mf, ot, 5, 6)
    if fix_spin:
        mc.fcisolver = csf_solver(mol_, smult=mol_.spin + 1)
    mc = mc.multi_state([1.0 / n] * n, "cms")
    mc.max_cycle_macro = 200
    mc.kernel()
    return mc


def _osc(mc, j):
    mu = np.asarray(mc.trans_moment(unit="AU", origin="mass_center", state=[j, 0]))
    dE = abs(float(mc.e_states[j] - mc.e_states[0]))
    return 2.0 / 3.0 * dE * float(np.dot(mu, mu))


@spike("cmspdft: energies (multi_state 'cms')")
def _():
    mc = _cms(_furan())
    dE = [(e - mc.e_states[0]) * 27.211386 for e in mc.e_states[1:]]
    return f"{type(mc).__name__}, 3 states, dE = {[round(float(x), 4) for x in dE]} eV"


@spike("cmspdft/osc_strengths: transition dipoles are real, not noise")
def _():
    mc = _cms(_furan())
    fs = [_osc(mc, j) for j in (1, 2)]
    if max(fs) < 1e-6:
        raise RuntimeError(f"all oscillator strengths vanished: {fs}")
    return f"f = {[round(x, 6) for x in fs]} (furan, tPBE/STO-3G, CAS(6,5))"


@spike("cmspdft/osc_strengths: they vanish WITHOUT a spin-constrained state average")
def _():
    """The finding that makes _fix_state_average_spin load-bearing rather
    than a refinement. An unconstrained FCI solver asked for three roots
    returns the lowest of any multiplicity, and a singlet-to-triplet
    transition dipole is identically zero.

    Worth recording separately: the obvious alternative, `fix_spin_`'s
    energy penalty, is not usable here. It leaks into the stored MCSCF
    energies and CMS-PDFT then aborts on its own consistency check with
    "Sanity fault: e_mcscf != self.e_mcscf", the mismatch being exactly the
    penalty shift. The CSF solver has no penalty to leak."""
    mc = _cms(_furan(), fix_spin=False)
    fs = [_osc(mc, j) for j in (1, 2)]
    if max(fs) > 1e-6:
        raise RuntimeError(
            f"intensities survived an unconstrained average ({fs}) -- the spin "
            f"constraint may no longer be needed, recheck before removing it")
    return (f"f = {[f'{x:.2e}' for x in fs]} without fix_spin_, against "
            f"{[round(_osc(_cms(_furan()), j), 6) for j in (1, 2)]} with it")


@spike("cmspdft/gradient: ground and excited state")
def _():
    mc = _cms(_furan(), n=2)
    g0 = mc.nuc_grad_method().kernel(state=0)
    g1 = mc.nuc_grad_method().kernel(state=1)
    return (f"|grad(S0)| = {np.linalg.norm(g0):.6f}, "
            f"|grad(S1)| = {np.linalg.norm(g1):.6f} Eh/Bohr")


@spike("cmspdft/nac: state pair")
def _():
    mc = _cms(_furan(), n=2)
    nac = mc.nac_method().kernel(state=(0, 1))
    return f"NAC shape {np.asarray(nac).shape}, norm {np.linalg.norm(nac):.6e}"


@spike("sa-casscf: a state average's own gradient is the MEAN, not a state's")
def _():
    """Why run_frequency and run_geometry_optimization pass `state=` for a
    state-averaged CASSCF. Without it the Hessian is taken on the average
    surface, which is not a surface anything moves on, and the frequencies
    come out with spurious zero modes."""
    m = scf.RHF(mol()).run()
    mc = mcscf.CASSCF(m, 4, 4).state_average_([1 / 3.] * 3)
    mc.kernel()
    e_avg, g_avg = mc.nuc_grad_method().as_scanner()(mc.mol)
    e_0, g_0 = mc.nuc_grad_method().as_scanner(state=0)(mc.mol)
    if abs(e_avg - float(np.mean(mc.e_states))) > 1e-6:
        raise RuntimeError("the unqualified scanner no longer returns the mean")
    states = np.array2string(np.asarray(mc.e_states), precision=5)
    return (f"unqualified scanner E = {e_avg:.8f} (the mean of {states}), "
            f"|grad| = {np.linalg.norm(g_avg):.4f}; state=0 gives E = {e_0:.8f}, "
            f"|grad| = {np.linalg.norm(g_0):.4f}")


@spike("pdft/opt: geomeTRIC on the state-average energy directly")
def _():
    from pyscf import mcpdft
    from pyscf.geomopt.geometric_solver import optimize
    m = scf.RHF(mol()).run()
    lp = mcpdft.CASSCF(m, "tPBE", 4, 4).multi_state([0.5, 0.5], method="LIN")
    lp.kernel()
    optimize(lp, maxsteps=3)
    return "the state-average energy itself has a gradient"


@spike("pdft/opt: geomeTRIC driven by a state-selected gradient scanner")
def _():
    from pyscf import mcpdft
    from pyscf.geomopt.geometric_solver import optimize
    m = scf.RHF(mol()).run()
    lp = mcpdft.CASSCF(m, "tPBE", 4, 4).multi_state([0.5, 0.5], method="LIN")
    lp.kernel()
    eq = optimize(lp.nuc_grad_method().as_scanner(state=1), maxsteps=6)
    return f"L-PDFT S1 optimization ran through the scanner, {eq.natm} atoms"


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
