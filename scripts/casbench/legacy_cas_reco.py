"""The active-space runners this project used before 2026-09-02.

Kept only so the benchmark can compare against them. They are not reachable
from the application: `cas_reco` dispatches to `run_cas_recommendation`, and
nothing under `app/` imports this module.

They are here rather than deleted because the case for deleting them is a
measurement, and a measurement needs both sides. `scripts/casbench/run_bench.py`
makes it and `docs/CAS_ENGINE_METHOD.md` section 8 records the result: the
rebuilt engine matches the literature active space on 10 of 14 molecules against
1 for these, gives a basis-independent answer where these change on 2 of 14, has
no orbital cap where these refuse above twelve, and answers open-shell molecules
where these refuse outright. On that evidence this file can go; it is kept so
the comparison stays reproducible.

Three properties are worth remembering, because they are what the rebuild was
for:

- `_PILOT_CAS_CEILING = 12` is overloaded. It is both the exact-FCI pilot pool
  ceiling and the validation ceiling for a user-supplied `max_active_orbitals`,
  and a larger request is refused rather than clamped.
- The basis is upstream of the answer. It builds the Mole that feeds RHF, AVAS,
  the pilot CASCI and the entropies, so a different basis can give a different
  space.
- `mol.spin != 0` is refused outright, so no open-shell molecule gets a
  recommendation at all.

Moved verbatim from `app/chemistry/jobs/pyscf_runner.py`. The docstrings still
describe that module's surroundings and are left as written: the point of
keeping the file is to have the old code as it was.
"""
from __future__ import annotations

import copy
import math
import os

import numpy as np
from pyscf import gto, scf, mcscf
from pyscf.mcscf import avas
from pyscf.tools import molden

from app.chemistry.jobs.pyscf_runner import (
    _apply_named_active_space,
    _apply_spin_constraint,
    _build_casscf,
    _casscf_molden_and_table,
    _dominant_transitions_casscf,
    _excitation_energies_eV,
    build_mole,
)
from app.chemistry.spectrum import render_entropy_plateau_plot

# Default AVAS valence-shell seed per element, keyed by symbol -- covers
# periods 2-4 main group plus first-row transition metals (the systems
# this app's CASSCF/CASPT2 job types are actually exercised against).
# avas_aolabels lets a caller override/extend this per molecule; an
# element outside this table with no explicit avas_aolabels raises a
# clear, actionable error rather than silently guessing a valence shell.
_AVAS_DEFAULT_SHELL = {
    **{s: "2p" for s in ["Li", "Be", "B", "C", "N", "O", "F", "Ne"]},
    **{s: "3p" for s in ["Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar"]},
    **{s: "3d" for s in ["Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn"]},
    **{s: "4p" for s in ["Ga", "Ge", "As", "Se", "Br", "Kr"]},
}


# Hard ceiling on the exact-FCI pilot CASCI's active space size -- benchmarked
# directly on this host: CAS(12,12) ~2s, CAS(14,14) ~41s, CAS(16,16) is
# infeasible (~165M determinants; CAS(20,20)-scale AVAS output was observed
# to still be running after 19 minutes of CPU time in ad hoc testing before
# being killed). This is a machine-cost limit, not a chemistry choice, so
# it is NOT exposed as a user-configurable parameter the way
# max_active_orbitals (the cap on the RECOMMENDED final space) is.
_PILOT_CAS_CEILING = 12


# Hard ceiling on the DMRG pilot's active space size, for entropy_method="dmrg"
# -- see run_recommend_active_space/_pilot_entropies_dmrg. Set from a real
# benchmark on this host at the actual "cheap unconverged pilot" settings
# _pilot_entropies_dmrg uses (bond_dim=250, 8 sweeps, SZ symmetry), using
# uracil's real 28-orbital AVAS pilot pool truncated to each size (the same
# molecule/aolabels that motivated this feature): CAS(12,12) 23s,
# CAS(16,16) 59s, CAS(24,20) 118s, CAS(32,24) 195s, CAS(40,28) 292s (~5
# min) -- growth is superlinear (roughly the expected polynomial DMRG
# scaling) but the full 28-orbital pool (uracil's own AVAS output at
# STO-3G, no truncation at all) is comfortably tractable at ~5 min, a
# reasonable bound for a background job on this shared host. 30 leaves a
# small buffer above the largest size actually measured (28) without
# extrapolating far past it.
_DMRG_PILOT_CAS_CEILING = 30


def _avas_electron_count(nelecas) -> int:
    """`avas.avas` returns nelecas as a numpy int64 OR an (nalpha, nbeta)
    tuple depending on the caller's spin handling, and numpy int64 is not
    an instance of int -- checking that was an earlier bug in this file
    (see the F-020 note in the retired recommend runner, now in
    scripts/casbench/legacy_cas_reco.py). Normalize once."""
    if isinstance(nelecas, (tuple, list)):
        return int(sum(nelecas))
    return int(nelecas)


def _avas_pilot_space(mf, mol, params: dict, log_prefix: str):
    """Run AVAS and return (ncas, nelec, mo, aolabels_used, notes).

    Shared by the entropy-screened recommendation and by AVAS-only
    construction, so the seeding rule below is defined in exactly one
    place and a fix to it reaches both.

    The rule that needs explaining is the hydrogen re-seed. The default
    labels name one valence shell per HEAVY atom, which is right for
    almost everything and catastrophically wrong for a hydride of a single
    heavy atom. Water in cc-pVDZ seeds `['O 2p']`: three orbitals, six
    electrons, completely full. A pool with no virtual orbitals in it can
    describe no correlation at all, so every stage downstream then produced
    a plausible-looking number from nothing -- entropies identically zero,
    no plateau, and a "recommendation" of (6e,3o) that cannot host a single
    excitation. Verified on this host: `['O 2p']` gives (6e,3o) and
    `['O 2p', 'H 1s']` gives (8e,6o), which is a real correlating space.

    Including hydrogens is the standard AVAS treatment for that shape --
    `['O 2p', 'H 1s']` spans the O-H sigma/sigma* pair. It is applied ONLY
    when the heavy-atom pool comes back full, rather than always, because
    adding hydrogens everywhere would enlarge the pool for every polyatomic
    that currently works and change which orbitals survive truncation to
    the pilot ceiling. Narrowing an existing, verified result to fix an
    unrelated case is not a trade worth making silently.

    An explicit `avas_aolabels` from the user is never second-guessed: they
    named the character they wanted, and re-seeding it would be the silent
    substitution this whole module is being audited for.
    """
    notes: list[str] = []
    explicit = bool(params.get("avas_aolabels"))
    aolabels = params.get("avas_aolabels") or _default_avas_aolabels(mol)
    print(f"{log_prefix} AVAS pilot space, aolabels={aolabels}", flush=True)
    ncas, nelecas, mo = avas.avas(mf, aolabels)
    if ncas == 0:
        raise RuntimeError(f"AVAS found no orbitals matching {aolabels} -- try different "
                           f"avas_aolabels.")

    if not explicit and _avas_electron_count(nelecas) == 2 * int(ncas):
        hydrogens = [f"{s} 1s" for s in {mol.atom_symbol(i) for i in range(mol.natm)}
                     if s == "H"]
        if hydrogens:
            widened = sorted(set(aolabels) | set(hydrogens))
            print(f"{log_prefix} the heavy-atom AVAS pool ({_avas_electron_count(nelecas)}e,"
                  f"{int(ncas)}o) is completely full -- no virtual orbitals to correlate "
                  f"into. Re-seeding with hydrogens: {widened}", flush=True)
            w_ncas, w_nelecas, w_mo = avas.avas(mf, widened)
            if w_ncas and _avas_electron_count(w_nelecas) < 2 * int(w_ncas):
                notes.append(
                    f"The valence pool for the heavy atom(s) alone ({aolabels}) was "
                    f"completely occupied, which cannot describe any correlation, so the "
                    f"hydrogens were included as well ({widened})."
                )
                ncas, nelecas, mo, aolabels = w_ncas, w_nelecas, w_mo, widened

    if _avas_electron_count(nelecas) == 2 * int(ncas):
        # Still full after the re-seed, or full with labels the user chose.
        # Terminal, and said so here rather than four stages later: every
        # orbital is doubly occupied, so the pool holds exactly one
        # configuration, its single-orbital entropies are all identically
        # zero, and any subset of it is equally empty of information. There
        # is no recommendation to make from it.
        raise ValueError(
            f"No meaningful active space can be recommended here: the AVAS valence pool "
            f"({_avas_electron_count(nelecas)}e, {int(ncas)}o, from {aolabels}) is completely "
            f"occupied, so it contains no virtual orbitals to correlate into and holds exactly "
            f"one electronic configuration. Give avas_aolabels naming an unoccupied shell as "
            f"well (for example ['O 2p', 'O 3p'] rather than ['O 2p']), or use a larger basis "
            f"set whose valence space includes one."
        )
    # Normalized to a plain int here so no caller has to repeat the
    # numpy-int64-or-tuple dance; pyscf's CAS APIs take either.
    return int(ncas), _avas_electron_count(nelecas), mo, aolabels, notes


def _truncate_avas_space(mol, avas_mo, avas_ncas: int, avas_nelec: int, ceiling: int,
                         why: str, n_occupied: Optional[int] = None):
    """Cut an AVAS space down to `ceiling` orbitals nearest the Fermi level,
    returning (mo, ncas, nelec, truncated, note).

    Shared by the entropy pilot and by AVAS-only construction. Both need a
    ceiling for the same reason -- exact FCI and CASSCF alike become
    infeasible well before the full valence space of a medium molecule (see
    _PILOT_CAS_CEILING's benchmark) -- and both need the surviving columns
    laid out so pyscf's own core/active/virtual split accepts them.

    `n_occupied` is how many of the kept orbitals come from the occupied
    side. Without it the split is `ceiling - ceiling // 2` virtuals and the
    rest occupied, which is very nearly 50/50 and was, until this argument
    existed, the ONLY reachable shape. That is an implementation detail
    deciding chemistry: it makes the occupied count always floor(ceiling/2),
    so on uracil a cap of 9 could only ever give (8e,9o) and a (12e,9o)
    space -- six occupied, three virtual, the standard choice when the
    n -> pi* states matter -- was unreachable at every cap. An excited state
    that promotes out of a lone pair needs those occupied orbitals in the
    space, and a symmetric split cannot express that preference.

    Clamped against what the pool actually holds, and the clamp is
    returned rather than applied quietly -- asking for six occupied
    orbitals from a pool with four is a request that has to be answered
    honestly, the same as any other truncation.

    Returns the input untouched when it already fits, so callers can invoke
    it unconditionally.
    """
    ncore = (mol.nelectron - avas_nelec) // 2
    n_occ_active = avas_nelec // 2
    n_virt_active = avas_ncas - n_occ_active
    if avas_ncas <= ceiling:
        return avas_mo, avas_ncas, avas_nelec, False, None

    note = None
    if n_occupied is None:
        keep_virt = min(ceiling - ceiling // 2, n_virt_active)
        keep_occ = min(ceiling - keep_virt, n_occ_active)
        keep_virt = min(ceiling - keep_occ, n_virt_active)
    else:
        keep_occ = min(int(n_occupied), n_occ_active, ceiling)
        keep_virt = min(ceiling - keep_occ, n_virt_active)
        if keep_virt == 0 and n_virt_active > 0 and keep_occ > 1:
            # A space with no virtual orbitals is completely full: one
            # configuration, no correlation describable, nothing worth
            # recommending -- the same degenerate case _avas_pilot_space
            # refuses at the pool level, which this truncation could
            # otherwise manufacture from a pool that was perfectly fine.
            # One orbital is given back rather than refusing, since unlike
            # the pool case there is an obvious repair.
            keep_occ -= 1
            keep_virt = 1
            note = (f"Keeping {int(n_occupied)} occupied orbitals under a {ceiling}-orbital "
                    f"cap would leave no virtual orbitals at all, which can describe no "
                    f"correlation -- kept {keep_occ} occupied and 1 virtual instead.")
        elif keep_occ != int(n_occupied):
            note = (f"Asked to keep {int(n_occupied)} occupied orbitals, but the pool holds "
                    f"only {n_occ_active} and the cap allows {ceiling} in total -- kept "
                    f"{keep_occ}.")
        elif keep_occ + keep_virt < ceiling:
            note = (f"Kept {keep_occ} occupied and {keep_virt} virtual orbitals; the pool "
                    f"has only {n_virt_active} virtual(s), so the space is smaller than the "
                    f"{ceiling}-orbital cap.")
    # boundary = column where occupied-active ends / virtual-active begins.
    # The KEPT (near-Fermi) orbitals become the new active block; every
    # DESELECTED occupied-active orbital must fold into the new core block
    # (not just the original ncore -- the resulting CASCI/CASSCF's own ncore
    # is (mol.nelectron - nelec)//2, which is larger than the original ncore
    # whenever keep_occ < n_occ_active, so the column layout must supply
    # exactly that many core columns or pyscf's own check_sanity() rejects
    # the mo_coeff outright -- confirmed on a real uracil/STO-3G run, where
    # an earlier version of this reordering undercounted the core block and
    # hit "assert nvir >= 0"). Deselected virtual-active orbitals fold into
    # the virtual block the same way.
    boundary = ncore + n_occ_active
    col_start, col_end = boundary - keep_occ, boundary + keep_virt
    mo = np.hstack([
        avas_mo[:, :ncore],                              # original core, untouched
        avas_mo[:, ncore:col_start],                     # deselected occ-active -> core
        avas_mo[:, col_start:col_end],                   # SELECTED near-Fermi -> active space
        avas_mo[:, col_end:boundary + n_virt_active],    # deselected virt-active -> virtual
        avas_mo[:, boundary + n_virt_active:],           # AVAS virtuals beyond the block, untouched
    ])
    ncas, nelec = keep_occ + keep_virt, 2 * keep_occ
    shape = (f" ({keep_occ} occupied, {keep_virt} virtual)" if n_occupied is not None else "")
    print(f"{why} -- truncating to {ncas} orbitals nearest the Fermi level{shape}.", flush=True)
    if note:
        print(f"[truncate] {note}", flush=True)
    return mo, ncas, nelec, True, note


def _clamp_states_to_space(n_elec: int, n_orb: int, n_states: int, weights, remedy: str):
    """(n_states, weights, note) -- never ask a CAS space for more roots
    than it can hold.

    An upper bound on the configuration count (ignoring symmetry and spin
    coupling, which could only shrink it) catches an unusably small space
    here, with an actionable note, rather than letting mc.kernel() produce
    fewer CI roots than requested and crash deep inside pyscf's own
    _finalize()/spin_square() with an opaque IndexError -- exactly what a
    real uracil/cc-pVDZ run did before this check existed.

    Clamps rather than refuses: the recommended space is a real result the
    user can act on, and throwing it away over the state count would lose
    the more valuable half of the answer. `weights` is dropped on clamp,
    since any the caller supplied were sized for the original count.
    """
    n_alpha = n_beta = n_elec // 2
    max_possible = math.comb(n_orb, n_alpha) * math.comb(n_orb, n_beta)
    if max_possible >= n_states:
        return n_states, weights, None
    note = (
        f"Requested {n_states} states, but the active space ({n_elec}e,{n_orb}o) can host "
        f"at most {max_possible} many-electron configuration(s). Ran the final CASSCF with "
        f"{max_possible} state(s) instead so the recommended space is still reported -- "
        f"{remedy}"
    )
    return max_possible, None, note


def _kernel_casscf_with_fallback(mc, seed_mo, log_prefix: str):
    """Run a CASSCF, retrying with the second-order solver before giving up.

    pyscf's default CASSCF solver (first-order, CI-then-orbital-rotation
    macro/micro iterations) can stall on a genuinely hard state-averaged
    case even when the active space itself is perfectly reasonable --
    confirmed as a real, reproducible failure on a live uracil/cc-pVDZ/
    (8e,7o)/3-state run, from DMRG-pilot-derived starting orbitals, on two
    separate retries that both landed on the same space. mcscf.newton()
    (augmented-Hessian Newton-Raphson) is pyscf's own documented answer for
    exactly that: more expensive per iteration, far more reliable from a
    difficult start. Tried automatically rather than made the default,
    since it is slower.
    """
    mc.kernel(seed_mo)
    if mc.converged:
        return mc
    print(f"{log_prefix} default CASSCF solver did not converge -- retrying with the "
          f"more robust Newton-Raphson solver", flush=True)
    mc = mcscf.newton(mc)
    mc.kernel(seed_mo)
    if not mc.converged:
        raise RuntimeError(
            "Final state-averaged CASSCF did not converge, even with the Newton-Raphson "
            "fallback solver. This active space/state combination may need a different "
            "starting guess or fewer states -- consider asking the user before retrying blindly."
        )
    return mc


def _default_avas_aolabels(mol) -> list[str]:
    symbols = {mol.atom_symbol(i) for i in range(mol.natm) if mol.atom_symbol(i) != "H"}
    missing = symbols - set(_AVAS_DEFAULT_SHELL)
    if missing:
        raise ValueError(
            f"No default AVAS valence-shell seed for element(s) {sorted(missing)} -- "
            f"pass avas_aolabels explicitly, e.g. ['{sorted(missing)[0]} 3d']."
        )
    return [f"{sym} {_AVAS_DEFAULT_SHELL[sym]}" for sym in sorted(symbols)]


def _single_orbital_entropies(mc) -> tuple[list[float], list[float]]:
    """Exact single-orbital entanglement entropy AND occupation (na+nb, the
    diagonal of the active-space 1-RDM -- not a true natural-orbital
    occupation number unless the pilot's own MO basis happens to diagonalize
    it, but a perfectly good "how occupied is basis orbital i" proxy for
    electron-counting the recommended active space, and correctly indexed
    in the pilot's own active-space-local order, unlike
    pyscf.mcscf.addons.make_natural_orbitals's globally-sorted output)
    per pilot-space orbital, from the pilot CASCI's own converged FCI
    wavefunction -- the same entropy quantity autoCAS computes
    approximately from a cheap DMRG-CI pilot (no DMRG package is
    available/installed here, and none is needed: the entropy definition
    is identical, DMRG is only the scalable approximation for pilot spaces
    too large for exact FCI -- see the recommend_active_space plan).
    s(1)_i = -sum_a w_a ln(w_a), w_a the eigenvalues of orbital i's local
    (empty/up/down/doubly-occupied) reduced density matrix, built from the
    spin-resolved 1-/2-particle RDMs (w1=1-na-nb+Pii, w2=na-Pii, w3=nb-Pii,
    w4=Pii). Validated numerically before being wired in here: equilibrium
    H2 CAS(2,2) gives s~0.068 (near-single-determinant), stretched H2
    (3.0 Ang) gives s~0.690, matching the closed-form diradical limit
    ln(2)=0.693 almost exactly."""
    ncas = mc.ncas
    # State-averaged when the pilot solved for more than one root. The
    # entropy definition is unchanged -- it is the same expression over the
    # same RDMs -- but the RDMs are the equally-weighted average over the
    # roots rather than the ground state's alone, which is what makes the
    # criterion able to see an orbital that only matters once you excite
    # out of it. A doubly-occupied lone pair is weakly correlated in S0 and
    # carries almost no ground-state entanglement, however much the n -> pi*
    # states depend on it; averaging over those states is what puts it back
    # in the ranking. Verified on water/STO-3G CAS(4,4): per-root 1-RDMs
    # each trace to the right electron count, the average does too, and the
    # sum(omega) == 1 sanity check below holds exactly for every orbital.
    civecs = mc.ci if isinstance(mc.ci, (list, tuple)) else [mc.ci]
    weight = 1.0 / len(civecs)
    dm1a = dm1b = dm2ab = None
    for civec in civecs:
        (a, b), (_aa, ab, _bb) = mc.fcisolver.make_rdm12s(civec, ncas, mc.nelecas)
        dm1a = a * weight if dm1a is None else dm1a + a * weight
        dm1b = b * weight if dm1b is None else dm1b + b * weight
        dm2ab = ab * weight if dm2ab is None else dm2ab + ab * weight
    entropies, occupations = [], []
    for i in range(ncas):
        na, nb, pii = dm1a[i, i], dm1b[i, i], dm2ab[i, i, i, i]
        omegas = np.clip([1 - na - nb + pii, na - pii, nb - pii, pii], 0.0, 1.0)
        total = float(omegas.sum())
        if abs(total - 1.0) > 1e-4:
            raise RuntimeError(
                f"single-orbital entropy sanity check failed for pilot orbital {i}: "
                f"sum(omega)={total:.6f}, expected 1.0 -- this indicates an RDM convention bug, not a normal failure."
            )
        entropies.append(float(-sum(w * np.log(w) for w in omegas if w > 1e-12)))
        occupations.append(float(na + nb))
    return entropies, occupations


def _pilot_entropies_dmrg(
    mf, pilot_mo: np.ndarray, ncore: int, pilot_ncas: int, pilot_nelecas: int, bond_dim: int, job_dir: str,
) -> tuple[list[float], list[float]]:
    """Real DMRG-based single-orbital entropies (block2/pyblock2), for
    entropy_method='dmrg' -- the actual autoCAS mechanism (a cheap, low-
    bond-dimension, low-sweep-count DMRG-CI pilot pass), as opposed to
    _single_orbital_entropies's exact-FCI substitute. Exists specifically to
    let the pilot screen a much larger AVAS candidate pool than exact FCI's
    12-orbital ceiling allows (DMRG cost is polynomial, not combinatorial,
    in active-space size), at the cost of an approximate (not exact) entropy
    estimate and a slower job. Returns entropies/occupations in the SAME
    shape/convention as _single_orbital_entropies (pilot-active-block-local
    0-based index) so run_recommend_active_space's downstream code (plateau
    sweep, electron counting, mc.sort_mo final-CASSCF seeding) doesn't need
    to know which backend produced them.

    API calls below were verified directly against the installed block2
    package via inspect.signature/direct testing before being wired in
    here (see the plan for this feature): get_rhf_integrals reads
    mf.mo_coeff directly (hence the shallow mf copy with pilot_mo swapped
    in, so the caller's real mf is never mutated). SymmetryTypes.SZ
    (non-spin-adapted), not SU2, is used deliberately: get_orbital_entropies
    with SU2 hit a real, reproducible bug in this installed block2 version
    (0.5.3, built from source) for orb_type=1 -- its npdm-based fast path
    raises a pybind11 vector-cast error internally (an empty index mask
    that SU2's spin-adapted single-orbital-entropy expression produces
    doesn't cast cleanly to C++ VectorUInt16), and its slower MPO-based
    fallback (use_npdm=False) explicitly `return NotImplemented` for SU2
    at orb_type=1 in the installed source -- confirmed by reading both
    code paths directly. SZ mode hits neither: get_orbital_entropies
    worked immediately and its value matched _single_orbital_entropies's
    exact-FCI H2 equilibrium result (0.06792165) to 8 significant figures
    in a direct side-by-side test. The one consequence: get_1pdm returns
    a [alpha, beta] list of separate (n,n) matrices in SZ mode (confirmed
    directly), not SU2's single spin-summed matrix, so occupations are
    reconstructed as pdm_a[i,i]+pdm_b[i,i] -- the same na+nb quantity
    _single_orbital_entropies already returns, just combined explicitly
    here instead of coming pre-summed.

    NO STATE AVERAGING HERE, and it is refused before a draft can ask for
    it (registry2/elicitation.py) rather than handled at this level. block2
    0.5.3 will happily solve for several roots -- get_random_mps(nroots=3)
    plus dmrg() returns three energies -- but get_orbital_entropies() on the
    resulting multi-root MPS **segfaults the process**, reproduced on a
    water/STO-3G CAS(4,4) probe. A segfault kills the worker outright, so no
    result is ever written and the job never reaches a terminal status,
    which is the one job-lifecycle failure this project treats as a real
    defect. Same shape as the SU2 bug above: the API accepts the call and
    the failure is inside the C++ layer. If a future block2 fixes it, the
    exact-FCI path's averaging in _single_orbital_entropies is the reference
    for what this would need to compute.
    """
    from pyblock2._pyscf.ao2mo import integrals as itg
    from pyblock2.driver.core import DMRGDriver, SymmetryTypes

    mf_pilot = copy.copy(mf)
    mf_pilot.mo_coeff = pilot_mo
    _ncas, n_elec, spin, ecore, h1e, g2e, orb_sym = itg.get_rhf_integrals(
        mf_pilot, ncore=ncore, ncas=pilot_ncas, g2e_symm=8,
    )

    scratch = os.path.join(job_dir, "dmrg_pilot_scratch")
    os.makedirs(scratch, exist_ok=True)
    driver = DMRGDriver(scratch=scratch, symm_type=SymmetryTypes.SZ, n_threads=N_CORES)
    driver.initialize_system(n_sites=pilot_ncas, n_elec=n_elec, spin=spin, orb_sym=orb_sym)
    mpo = driver.get_qc_mpo(h1e=h1e, g2e=g2e, ecore=ecore, iprint=0)
    ket = driver.get_random_mps(tag="PILOT", bond_dim=min(100, bond_dim), nroots=1)
    # Deliberately a cheap, UNCONVERGED pilot sweep schedule (few sweeps,
    # ramping to bond_dim) -- matching autoCAS's own stated design ("an
    # unconverged DMRG wavefunction with low bond dimension"), not a
    # tightly-converged production DMRG calculation.
    # Noise/threshold schedule tuned empirically, not guessed: a first draft
    # (noise dropping to 1e-5 after 2 sweeps then 0 after 4, thrds=1e-6) gave
    # a WRONG entropy (0.986 vs the correct ~0.690, a ~43% error) on a
    # deliberately hard test case (stretched H2, a genuine diradical -- the
    # same case validated in _single_orbital_entropies's own docstring) --
    # the DMRG optimization was landing in a poor local solution, not
    # actually converging, despite running without error. Holding noise at
    # 1e-4 for a full 4 sweeps (half the schedule) and tightening the
    # Davidson threshold to 1e-8 fixed it, confirmed correct (0.6903,
    # matching the exact-FCI reference) across 3 repeated trials with fresh
    # random MPS initializations -- not a one-off fluke.
    n_sweeps = 8
    bond_dims = [min(100, bond_dim)] * 2 + [bond_dim] * (n_sweeps - 2)
    noises = [1e-4] * 4 + [0.0] * (n_sweeps - 4)
    driver.dmrg(mpo, ket, n_sweeps=n_sweeps, bond_dims=bond_dims, noises=noises, thrds=[1e-8] * n_sweeps, iprint=0)

    entropies = [float(s) for s in driver.get_orbital_entropies(ket, orb_type=1)]
    pdm_a, pdm_b = driver.get_1pdm(ket)
    occupations = [float(pdm_a[i, i] + pdm_b[i, i]) for i in range(pilot_ncas)]
    return entropies, occupations


def _find_entropy_plateau(entropies: list[float], max_orbitals: int) -> tuple[list[int], float | None, bool]:
    """Sweeps a threshold down from just below the max entropy, recording
    how many orbitals would be selected (entropy > threshold) at each
    step, and looks for a plateau -- a threshold range where the selected
    count stays constant -- per autoCAS's own selection protocol (the
    0.14 value from the literature is a different, unrelated
    multiconfigurational-character diagnostic, not the selection cut
    itself; the real autoCAS selection is this threshold/plateau sweep).
    Returns (selected_orbital_indices, threshold_used, plateau_found).
    A plateau whose orbital count exceeds max_orbitals is skipped in favor
    of the next (smaller) one, so the recommendation always respects the
    user-facing cap; if no plateau survives this filter, returns
    (approx-cut-at-max_orbitals, None, False) -- a real, reported
    "no clear plateau" outcome rather than a silently fabricated cut.
    """
    order = np.argsort(-np.array(entropies))  # most-entangled first
    sorted_entropies = [entropies[i] for i in order]
    n = len(sorted_entropies)
    if n <= 1:
        return (list(order[:n]), None, False)
    # thresholds strictly between consecutive sorted entropy values -- the
    # selected count is constant (=k+1) across each such interval by
    # construction, so "plateau" reduces to: the biggest gap in the sorted
    # entropy values IS the widest stable-count threshold range. Rank gaps
    # descending and take the first one whose selected count respects the
    # user-facing cap.
    candidate_thresholds = [(sorted_entropies[k] + sorted_entropies[k + 1]) / 2 for k in range(n - 1)]
    gaps = [sorted_entropies[k] - sorted_entropies[k + 1] for k in range(n - 1)]
    ranked_gap_positions = sorted(range(n - 1), key=lambda k: -gaps[k])
    # count >= 2: a single-orbital "active space" is degenerate (it can host
    # only one many-electron configuration at most, never enough for a real
    # active space, let alone multiple state-averaged states) -- confirmed
    # as a real failure mode, not a hypothetical one: a real uracil/cc-pVDZ
    # run picked count=1 here (a lone high-entropy outlier orbital made the
    # single widest gap the very first one), producing a (0e,1o) "active
    # space" that crashed deep inside pyscf's CASSCF _finalize() with an
    # opaque IndexError once n_states=3 couldn't be satisfied. Skipping any
    # candidate gap with count < 2 rules this out at the source, rather
    # than only catching its downstream symptom.
    for k in ranked_gap_positions:
        count = k + 1
        if 2 <= count <= max_orbitals and gaps[k] > 1e-3:
            threshold = candidate_thresholds[k]
            selected = [int(order[j]) for j in range(count)]
            return (selected, threshold, True)
    count = min(max_orbitals, n)
    count = max(count, min(2, n))  # same floor for the no-plateau-found fallback
    selected = [int(order[j]) for j in range(count)]
    return (selected, None, False)


def run_recommend_active_space(molecule: dict, params: dict) -> dict:
    """AutoCAS-style Single-Orbital-Entropy active-space recommendation,
    run as one sequential in-process pipeline (same "one job_id, several
    stages" shape as run_neb_ts, not pes_scan's master/sub-job fan-out --
    every stage here depends on the previous one's in-memory result, there
    is no independent parallel work to fan out). See the
    recommend_active_space plan for the full algorithm derivation.
    print(..., flush=True) at each stage lands directly in worker.log,
    which the job panel's live log tail already reads -- no new
    "sub-calculation visible in the panel" machinery needed."""
    mol = build_mole(molecule, params["basis"])
    if mol.spin != 0:
        raise ValueError(
            "recommend_active_space currently only supports closed-shell molecules "
            "(this pilot's electron-counting/truncation math assumes a closed-shell reference)."
        )

    print(f"[recommend_active_space] RHF on {mol.natm} atoms, basis={params['basis']}", flush=True)
    mf = scf.RHF(mol)
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("SCF did not converge; try a different initial guess or check the input")

    # entropy_method picks the pilot screening backend only -- the FINAL
    # recommended active space and its CASSCF are identical either way, so
    # max_active_orbitals is validated against _PILOT_CAS_CEILING
    # unconditionally (that's the final-CASSCF ceiling, not the pilot's).
    entropy_method = params.get("entropy_method") or "exact_fci"
    if entropy_method not in ("exact_fci", "dmrg"):
        raise ValueError(f"Unknown entropy_method '{entropy_method}' -- must be 'exact_fci' or 'dmrg'.")
    dmrg_bond_dim = int(params.get("dmrg_bond_dim") or 250)
    pilot_ceiling = _DMRG_PILOT_CAS_CEILING if entropy_method == "dmrg" else _PILOT_CAS_CEILING

    max_active_orbitals = int(params.get("max_active_orbitals") or 12)
    if max_active_orbitals > _PILOT_CAS_CEILING:
        raise ValueError(
            f"max_active_orbitals={max_active_orbitals} exceeds the {_PILOT_CAS_CEILING}-orbital final-CASSCF "
            f"ceiling on this host -- this is a user-supplied number, not something AVAS produced, so "
            f"it's refused outright rather than silently capped. Ask for {_PILOT_CAS_CEILING} or fewer. "
            f"(This ceiling applies regardless of entropy_method -- DMRG only widens the pilot SCREENING "
            f"pool, not the final recommended space.)"
        )
    avas_ncas, avas_nelecas, avas_mo, aolabels, seed_notes = _avas_pilot_space(
        mf, mol, params, "[recommend_active_space]")

    pilot_mo, pilot_ncas, pilot_nelecas, pilot_space_truncated, truncation_note = \
        _truncate_avas_space(
            mol, avas_mo, avas_ncas, avas_nelecas, pilot_ceiling,
            f"[recommend_active_space] AVAS pilot space ({avas_ncas} orbitals) exceeds the "
            f"{pilot_ceiling}-orbital {entropy_method} pilot ceiling",
            n_occupied=params.get("active_occupied_orbitals"),
        )
    if truncation_note:
        seed_notes.append(truncation_note)

    # F-020, informational half. AVAS itself has no notion of n_states --
    # it is a one-electron orbital-selection method (projection of target
    # AO character onto the mean-field MOs; see Sayfutyarova, Sun, Chan &
    # Knizia, JCTC 2017), so it is never gated on state count and always
    # runs. This is a heads-up only: the selected space is a SUBSET of the
    # pilot space, so if the whole pilot space cannot host n_states, no
    # selection drawn from it can either -- knowable right here, before the
    # pilot CASCI/DMRG, the entropy computation and the plateau search. It
    # no longer stops the pipeline (the recommendation and its entropy plot
    # are worth producing regardless -- see the n_states clamp at the final
    # CASSCF step below, which is where state count actually matters).
    #
    # Real case: water/STO-3G with the default `O 2p` AVAS labels gives a
    # 3-orbital, 6-electron pilot space -- completely full, exactly one
    # configuration, so even 2 states is impossible. Widening within the
    # pilot space (below) cannot help; only a larger pilot space can, so
    # this says which knob to turn if the eventual clamp isn't wanted.
    # avas.avas returns nelecas as a scalar (a numpy int64, which is NOT an
    # instance of int -- checking that was this line's first mistake), but
    # pyscf's CAS APIs also accept an (nalpha, nbeta) tuple, so accept both.
    _pilot_nelec = int(sum(pilot_nelecas)) if isinstance(pilot_nelecas, (tuple, list)) else int(pilot_nelecas)
    _pilot_alpha = _pilot_beta = _pilot_nelec // 2
    _pilot_configs = math.comb(int(pilot_ncas), _pilot_alpha) * math.comb(int(pilot_ncas), _pilot_beta)
    _n_states_req = params.get("n_states", 1)
    if _pilot_configs < _n_states_req:
        print(
            f"[recommend_active_space] note: the AVAS pilot space ({_pilot_nelec}e,{int(pilot_ncas)}o) can "
            f"host at most {_pilot_configs} many-electron configuration(s), fewer than the {_n_states_req} "
            f"states requested -- continuing anyway to produce the recommendation; the final CASSCF step "
            f"will run with however many states the recommended space can actually host and say so.",
            flush=True,
        )

    if entropy_method == "dmrg":
        print(
            f"[recommend_active_space] pilot DMRG({pilot_nelecas},{pilot_ncas}), "
            f"bond_dim={dmrg_bond_dim} (block2, low-sweep pilot)", flush=True,
        )
        # ncore for the pilot's own active-block offset within pilot_mo -- the
        # same value mc.sort_mo below needs (same formula pilot_mc.ncore
        # would give in the exact-FCI branch, computed directly here since
        # there's no mcscf.CASCI object in the DMRG branch to read it from).
        pilot_ncore = (mol.nelectron - pilot_nelecas) // 2
        entropies, occupations = _pilot_entropies_dmrg(
            mf, pilot_mo, pilot_ncore, pilot_ncas, pilot_nelecas, dmrg_bond_dim, params["_job_dir"],
        )
    else:
        pilot_roots = max(1, int(params.get("entropy_pilot_states") or 1))
        print(f"[recommend_active_space] pilot CASCI({pilot_nelecas},{pilot_ncas}) "
              f"(exact FCI, {pilot_roots} root(s)"
              f"{', state-averaged' if pilot_roots > 1 else ''})", flush=True)
        pilot_mc = mcscf.CASCI(mf, pilot_ncas, pilot_nelecas)
        # The recommendation is read off these roots' entropies, so they
        # have to be the same kind of state the final CASSCF will average
        # over -- otherwise the space is chosen from one set of states and
        # used for another.
        _apply_spin_constraint(pilot_mc, mol)
        if pilot_roots > 1:
            pilot_mc.fcisolver.nroots = pilot_roots
        pilot_mc.kernel(pilot_mo)
        # `converged` is a per-root list once nroots > 1.
        converged = pilot_mc.converged
        if not np.all(converged):
            raise RuntimeError("Pilot CASCI did not converge.")
        print("[recommend_active_space] computing single-orbital entropies", flush=True)
        entropies, occupations = _single_orbital_entropies(pilot_mc)
        pilot_ncore = pilot_mc.ncore

    # A single-orbital entropy is non-negative by definition; the tiny
    # negative values that come out of floating-point cancellation printed
    # as "-0" in the result table, which reads as a computed quantity with a
    # sign rather than as zero. Clamp before anything reports them.
    entropies = [0.0 if abs(e) < 1e-12 else float(e) for e in entropies]

    selected, threshold, plateau_found = _find_entropy_plateau(entropies, max_active_orbitals)
    selected_sorted = sorted(selected)

    def _space_for(indices: list[int]) -> tuple[int, int]:
        """(n_elec, n_orb) for a given set of pilot-local orbital indices.

        Electron count: sum of each selected orbital's active-space
        occupation (na+nb from the pilot CASCI's own 1-RDM diagonal, in
        the pilot's own basis -- see _single_orbital_entropies), rounded
        to the nearest even integer for a closed-shell active space.
        """
        occ_sum = float(sum(occupations[i] for i in indices))
        n_e = int(round(occ_sum))
        if n_e % 2 != 0:
            n_e += 1 if (occ_sum - n_e) > 0 else -1
        return max(0, min(n_e, 2 * len(indices))), len(indices)

    # F-020: make the recommendation satisfy the request instead of
    # selecting a space and then rejecting it.
    #
    # n_states is known before selection ever runs, but the sanity check
    # below used to be the ONLY place it was consulted -- so a perfectly
    # reasonable request (3 states of water/STO-3G) could run the whole
    # expensive pilot pipeline, land on a two-orbital plateau, and fail
    # after the fact on a constraint that was knowable up front. Entropy
    # ordering already ranks every pilot orbital, so the space is now
    # widened along that same ranking -- the next-most-entangled orbitals,
    # not arbitrary ones -- until it can host the states asked for.
    #
    # Bounds are unchanged: max_active_orbitals (the user's own cap) and
    # the pilot space itself. If widening to those limits still isn't
    # enough, the original error stands, which is the right last-resort
    # answer and its text is genuinely good.
    n_states_wanted = params.get("n_states", 1)

    def _n_configurations(indices: list[int]) -> int:
        n_e, n_o = _space_for(indices)
        n_a = n_b = n_e // 2
        return math.comb(n_o, n_a) * math.comb(n_o, n_b)

    def _can_host(indices: list[int]) -> bool:
        return _n_configurations(indices) >= n_states_wanted

    widened_from = None
    if not _can_host(selected_sorted):
        widened_from = len(selected_sorted)
        remaining = set(range(len(entropies))) - set(selected_sorted)
        # Greedy on the quantity actually being satisfied -- the number of
        # many-electron configurations the space can host -- with entropy
        # as the tie-break.
        #
        # Adding the next-most-entangled orbital is NOT sufficient on its
        # own, confirmed by running exactly the case the plan names (3
        # states of water/STO-3G): entropy ranks the strongly-occupied
        # orbitals first, and each one brings ~2 electrons with it, so the
        # space grows while staying completely full -- (4e,2o) widened to
        # (6e,3o), still exactly ONE configuration, and the job failed on
        # the same error it was widened to avoid. What actually creates
        # room for excited states is adding orbitals that are NOT fully
        # occupied, and ranking candidates by the resulting configuration
        # count selects those without having to special-case occupancy.
        while remaining and len(selected_sorted) < max_active_orbitals:
            best = max(
                remaining,
                key=lambda i: (_n_configurations(sorted(selected_sorted + [i])), entropies[i]),
            )
            remaining.discard(best)
            selected_sorted = sorted(selected_sorted + [best])
            if _can_host(selected_sorted):
                break
        if _can_host(selected_sorted):
            print(
                f"[recommend_active_space] widened the recommended space from "
                f"{widened_from} to {len(selected_sorted)} orbitals so it can host the "
                f"{n_states_wanted} requested states", flush=True,
            )
        else:
            widened_from = None  # nothing usable found; fall through to the error below

    n_elec, n_orb = _space_for(selected_sorted)

    plateau_png = os.path.join(params["_job_dir"], "entropy_plateau.png")
    from app.chemistry.spectrum import render_entropy_plateau_plot
    render_entropy_plateau_plot(entropies, threshold, selected_sorted, plateau_png)

    findings_summary = (
        f"Pilot valence space of {pilot_ncas} orbitals ({'AVAS-seeded, truncated to the ' + str(pilot_ncas) + ' nearest the Fermi level' if pilot_space_truncated else 'AVAS-seeded'}); "
        + (
            f"a plateau was found selecting {n_orb} orbitals at threshold {threshold:.4f}"
            if plateau_found else
            f"no clear entropy plateau was found -- reporting the {n_orb} highest-entropy orbitals "
            f"(capped at max_active_orbitals={max_active_orbitals}) as a best-effort recommendation"
        )
        + (
            f"; widened from {widened_from} to {n_orb} orbitals along the same entropy "
            f"ranking so the space can host the {params.get('n_states', 1)} requested states"
            if widened_from is not None else ""
        )
        + f"; recommended active space: ({n_elec}e, {n_orb}o)."
        + ("" if not seed_notes else " " + " ".join(seed_notes))
    )
    print(f"[recommend_active_space] {findings_summary}", flush=True)

    weights = params.get("weights")
    n_states = params.get("n_states", 1)

    # Pre-flight sanity check: the recommended (n_elec, n_orb) active space
    # must be able to host at least n_states distinct many-electron
    # configurations, or state-averaged CASSCF has nothing to average over.
    # An upper bound on that count (C(n_orb, n_alpha) * C(n_orb, n_beta),
    # ignoring symmetry/spin-coupling reductions that could only shrink it
    # further) catches an unusably small recommended space HERE, with a
    # clear, actionable note -- rather than letting mc.kernel() silently
    # produce fewer CI roots than requested and crash deep inside pyscf's
    # own CASSCF _finalize()/spin_square() with an opaque IndexError, which
    # is exactly what happened on a real uracil/cc-pVDZ run before this
    # check existed (see _find_entropy_plateau's count>=2 floor for the
    # other half of this fix).
    #
    # F-020: this is the LAST resort, and it now clamps rather than refuses.
    # The selection step above already widens the space along the entropy
    # ranking to satisfy n_states where it can, so reaching this means even
    # the full pilot space under the user's own max_active_orbitals cap
    # genuinely cannot host the request. AVAS/the entropy pilot never had a
    # notion of state count to begin with (see the informational note
    # earlier), so refusing the whole recommendation over it would throw
    # away a real, useful result the user could otherwise verify themselves.
    # Instead: clamp n_states down to what this space can actually hold, run
    # the final CASSCF with that many states, and say plainly what happened.
    # weights is dropped on clamp -- any weights the caller supplied were
    # sized for the original n_states and would no longer match.
    n_alpha = n_beta = n_elec // 2
    max_possible_states = math.comb(n_orb, n_alpha) * math.comb(n_orb, n_beta)
    n_states_requested = n_states
    if max_possible_states < n_states:
        n_states = max_possible_states
        weights = None
        clamp_note = (
            f"Requested {n_states_requested} states, but the recommended active space "
            f"({n_elec}e,{n_orb}o) can host at most {max_possible_states} many-electron "
            f"configuration(s), even after widening along the entropy ranking up to "
            f"max_active_orbitals={max_active_orbitals}. Ran the final CASSCF with "
            f"{n_states} state(s) instead so the recommended space is still reported -- "
            f"request fewer states, or raise max_active_orbitals if there's room under "
            f"the current cap, to get all {n_states_requested}."
        )
        print(f"[recommend_active_space] note: {clamp_note}", flush=True)
        findings_summary = f"{findings_summary} {clamp_note}"
    else:
        clamp_note = None

    print(f"[recommend_active_space] final state-averaged CASSCF({n_elec},{n_orb}) for {n_states} state(s)", flush=True)

    mc = _build_casscf(mf, n_orb, n_elec, n_states, weights, CASSCF_CONV_TOL_ENERGY)
    # Seed the final CASSCF's active space with EXACTLY the entropy-selected
    # pilot orbitals (not just "some orbitals near the Fermi level", which is
    # all a plain mf.mo_coeff guess would give): mc.sort_mo(caslst, ...) is
    # pyscf's own mechanism for this -- it correctly recomputes the
    # core/active/virtual column split for a target CASSCF object's own
    # (n_elec-derived) ncore, which a hand-rolled column reorder got wrong in
    # an earlier draft of this function whenever the final n_elec didn't
    # happen to match the pilot's own occupied/virtual split exactly.
    # selected_sorted indices are local to the pilot's active block
    # (pilot_mo columns [pilot_ncore : pilot_ncore+pilot_ncas]) -- use
    # pilot_ncore, NOT the original ncore, to shift to 0-based global column
    # indices into pilot_mo: these differ whenever the pilot space was
    # truncated (pilot_ncore then also absorbs the deselected occupied-active
    # orbitals folded into the pilot's own core block, see the truncation
    # block above). pilot_ncore is set identically by both entropy_method
    # branches above (from pilot_mc.ncore in the exact-FCI branch, computed
    # directly -- same formula -- in the DMRG branch, which has no CASCI
    # object to read it from).
    caslst = [pilot_ncore + i for i in selected_sorted]
    seed_mo = mc.sort_mo(caslst, mo_coeff=pilot_mo, base=0)
    mc = _kernel_casscf_with_fallback(mc, seed_mo, "[recommend_active_space]")

    active_space_orbital_indices = list(range(mc.ncore + 1, mc.ncore + mc.ncas + 1))

    molden_path, orbital_table = _casscf_molden_and_table(mc, params["_job_dir"])

    energies = np.atleast_1d(mc.e_states if hasattr(mc, "e_states") and n_states > 1 else mc.e_tot).tolist()
    summary = {
        "literature_notes": params.get("literature_notes"),
        "findings_summary": findings_summary,
        "recommended_active_electrons": n_elec,
        "recommended_active_orbitals": n_orb,
        "active_space_orbital_indices": active_space_orbital_indices,
        "entropy_method": entropy_method,
        "dmrg_bond_dim": dmrg_bond_dim if entropy_method == "dmrg" else None,
        "pilot_space_orbitals": pilot_ncas,
        "pilot_space_truncated": pilot_space_truncated,
        "entropy_threshold_used": threshold,
        "plateau_found": plateau_found,
        # Its own row rather than a clause inside findings_summary. This is
        # where the user's requested state count changes the recommended
        # space -- orbitals added along the entropy ranking until the space
        # can host the roots asked for -- and a recommendation that was
        # widened is a different kind of claim from one that was not. Buried
        # in a sentence, it read as an aside about the run; as a field it is
        # part of the answer.
        "space_widened_for_states": (
            None if widened_from is None else
            f"widened from {widened_from} to {n_orb} orbitals so the space could host "
            f"the {params.get('n_states', 1)} requested state(s) -- this part of the "
            f"recommendation follows the state count, not the entropy plateau"
        ),
        "pilot_orbital_entropies": entropies,
        "state_energies_hartree": energies if n_states > 1 else [float(mc.e_tot)],
        "n_states": n_states,
        "n_states_requested": n_states_requested,
        "n_states_clamped_note": clamp_note,
        "converged": bool(mc.converged),
        "reference_hf_energy_hartree": float(mf.e_tot),
        "dominant_transitions": _dominant_transitions_casscf(mc, n_states),
        "orbital_table": orbital_table,
        "orbital_table_note": (
            "Natural orbitals with active-space occupation numbers, plus character (sigma/pi/n/sigma*/pi*, "
            "best-effort from plane symmetry and Mulliken populations -- see classify_orbital_character) "
            "and dominant localized atom(s). "
            "Rows active_space_orbital_indices are the recommended active space."
        ),
        "method_note": (
            (
                "Single-orbital entropies are exact-FCI (pyscf CASCI), not literal DMRG -- the identical "
                "quantity autoCAS approximates via DMRG, computed exactly here because the AVAS-seeded pilot "
                f"space was small enough for exact FCI (capped at {_PILOT_CAS_CEILING} orbitals)."
                if entropy_method == "exact_fci" else
                f"Single-orbital entropies are from a real DMRG pilot (block2, bond_dim={dmrg_bond_dim}, "
                f"low-sweep/unconverged pilot pass per autoCAS's own 'cheap pilot' design), letting the "
                f"AVAS-seeded pilot space grow up to {_DMRG_PILOT_CAS_CEILING} orbitals instead of the "
                f"{_PILOT_CAS_CEILING}-orbital exact-FCI ceiling -- a more basis-faithful screening pool, "
                f"at the cost of an approximate (not exact) entropy estimate."
            )
            + (
                " The pilot space was truncated relative to the full AVAS-selected valence space -- "
                "treat this recommendation as an approximation." if pilot_space_truncated else ""
            )
        ),
    }
    _record_named_active_space(summary, params)
    return {"summary": summary, "artifacts": {"molden": molden_path, "entropy_plateau": plateau_png}}


def run_avas_active_space(molecule: dict, params: dict) -> dict:
    """AVAS active-space construction -- the space straight from atomic
    valence character, with no entropy pilot over it.

    The sibling of run_recommend_active_space, and deliberately a separate
    function rather than a flag on it. AVAS is a one-electron orbital
    selection method (projection of target AO character onto the mean-field
    MOs; Sayfutyarova, Sun, Chan & Knizia, JCTC 2017): it returns a space
    directly, so there is no CASCI to run over it, no entropies to compute,
    no plateau to look for. Screening its output by entropy is what AutoCAS
    does, and asking for AVAS is asking not to.

    Two things AutoCAS does that have no meaning here. There is no entropy
    ranking, so a space too small for the requested states cannot be
    "widened along" one -- the request is clamped and said so, and the way
    to get more states is a bigger seed, not a reordering. And
    max_active_orbitals truncates rather than narrows a recommendation:
    AVAS produced the whole space, so the cap removes orbitals it selected,
    which is reported prominently rather than as an aside.
    """
    mol = build_mole(molecule, params["basis"])
    if mol.spin != 0:
        raise ValueError(
            "AVAS active-space construction currently only supports closed-shell molecules "
            "(the electron-counting/truncation math assumes a closed-shell reference)."
        )
    print(f"[avas_active_space] RHF on {mol.natm} atoms, basis={params['basis']}", flush=True)
    mf = scf.RHF(mol)
    mf.kernel()
    if not mf.converged:
        raise RuntimeError("SCF did not converge; try a different initial guess or check the input")

    max_active_orbitals = int(params.get("max_active_orbitals") or _PILOT_CAS_CEILING)
    if max_active_orbitals > _PILOT_CAS_CEILING:
        raise ValueError(
            f"max_active_orbitals={max_active_orbitals} exceeds the {_PILOT_CAS_CEILING}-orbital "
            f"CASSCF ceiling on this host -- this is a user-supplied number, so it's refused "
            f"outright rather than silently capped. Ask for {_PILOT_CAS_CEILING} or fewer."
        )

    avas_ncas, avas_nelec, avas_mo, aolabels, seed_notes = _avas_pilot_space(
        mf, mol, params, "[avas_active_space]")
    mo, n_orb, n_elec, truncated, truncation_note = _truncate_avas_space(
        mol, avas_mo, avas_ncas, avas_nelec, max_active_orbitals,
        f"[avas_active_space] AVAS selected {avas_ncas} orbitals, above the "
        f"max_active_orbitals={max_active_orbitals} cap",
        n_occupied=params.get("active_occupied_orbitals"),
    )
    if truncation_note:
        seed_notes.append(truncation_note)

    n_states_requested = params.get("n_states", 1)
    n_states, weights, clamp_note = _clamp_states_to_space(
        n_elec, n_orb, n_states_requested, params.get("weights"),
        "request fewer states, or seed a larger space with avas_aolabels -- AVAS has no "
        "entropy ranking to widen along, so there is no ordering in which to add orbitals "
        "here.",
    )
    if clamp_note:
        print(f"[avas_active_space] note: {clamp_note}", flush=True)

    findings_summary = (
        f"AVAS selected {avas_ncas} orbitals from atomic valence character {aolabels}"
        + (f", truncated to the {n_orb} nearest the Fermi level by "
           f"max_active_orbitals={max_active_orbitals} -- orbitals AVAS did select are "
           f"not in the final space" if truncated else "")
        + f"; active space: ({n_elec}e, {n_orb}o). No entropy screening was applied: this "
          f"space is AVAS's own selection, not a ranked subset of a larger pool."
        + ("" if not seed_notes else " " + " ".join(seed_notes))
        + ("" if not clamp_note else f" {clamp_note}")
    )
    print(f"[avas_active_space] {findings_summary}", flush=True)

    print(f"[avas_active_space] state-averaged CASSCF({n_elec},{n_orb}) for {n_states} state(s)",
          flush=True)
    mc = _build_casscf(mf, n_orb, n_elec, n_states, weights, CASSCF_CONV_TOL_ENERGY)
    # AVAS already returns mo_coeff with its selected orbitals in the active
    # block, and _truncate_avas_space preserves that layout, so the columns
    # are handed to the solver as they are -- no sort_mo indirection, which
    # the entropy path needs only because it picks a SUBSET of the pilot's
    # active block.
    mc = _kernel_casscf_with_fallback(mc, mo, "[avas_active_space]")

    active_space_orbital_indices = list(range(mc.ncore + 1, mc.ncore + mc.ncas + 1))
    molden_path, orbital_table = _casscf_molden_and_table(mc, params["_job_dir"])
    energies = np.atleast_1d(
        mc.e_states if hasattr(mc, "e_states") and n_states > 1 else mc.e_tot).tolist()

    summary = {
        "literature_notes": params.get("literature_notes"),
        "findings_summary": findings_summary,
        "recommended_active_electrons": n_elec,
        "recommended_active_orbitals": n_orb,
        "active_space_orbital_indices": active_space_orbital_indices,
        "avas_aolabels_used": aolabels,
        "avas_orbitals_selected": avas_ncas,
        "avas_space_truncated": truncated,
        "state_energies_hartree": energies if n_states > 1 else [float(mc.e_tot)],
        "n_states": n_states,
        "n_states_requested": n_states_requested,
        "n_states_clamped_note": clamp_note,
        "converged": bool(mc.converged),
        "reference_hf_energy_hartree": float(mf.e_tot),
        "dominant_transitions": _dominant_transitions_casscf(mc, n_states),
        "orbital_table": orbital_table,
        "orbital_table_note": (
            "Natural orbitals with active-space occupation numbers, plus character "
            "(sigma/pi/n/sigma*/pi*, best-effort from plane symmetry and Mulliken populations -- see "
            "classify_orbital_character) and dominant localized atom(s). Rows "
            "active_space_orbital_indices are the active space."
        ),
        "method_note": (
            "The active space is AVAS's own selection from the requested atomic valence "
            "character -- deterministic, and not screened or ranked by any correlation "
            "measure. For a space chosen by orbital entanglement instead, run the AutoCAS "
            "recommendation, which uses AVAS only to seed its pilot pool."
            + (" The space was truncated to fit max_active_orbitals -- treat it as a "
               "subset of what AVAS actually selected." if truncated else "")
        ),
    }
    _record_named_active_space(summary, params)
    return {"summary": summary, "artifacts": {"molden": molden_path}}
