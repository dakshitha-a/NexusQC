# Active Tracker: NEVPT2, MC-PDFT and L-PDFT on PySCF

Live status of the plan in motion. **Exactly one tracker is active at a time.**

## How tracking works here

Development is linear, so there is never a reason to have two trackers open at
once. Each plan, feature or non-trivial request gets its own tracker, this file
is whichever one is currently in motion, and when its plan is finished the file
is closed out and moved to [`trackers/`](trackers/), then a fresh one starts
here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path. The one this
replaces is
[`trackers/2026-08-clearing-the-backlog-round-2.md`](trackers/2026-08-clearing-the-backlog-round-2.md)
-- 13 steps across 7 phases, closed 2026-08-29.

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Why this plan exists

The request was to add native support for NEVPT2, MC-PDFT and its
linear-response excited-state form L-PDFT on PySCF, across the single-point
subtypes and across optimization and frequencies where PySCF actually supports
them, with nuclear-ensemble spectra if oscillator strengths turn out to be
available.

Two of those conditions resolved to "no", and establishing that was most of the
work rather than an aside:

- **NEVPT2 has no gradient in PySCF at all.** `pyscf.mrpt` computes the
  correlation energy and nothing derived from it. So NEVPT2 is an energy-only
  method here: no optimization, no frequencies, no constrained optimization.
- **None of the three can produce oscillator strengths.** PySCF ships exactly
  one transition-dipole implementation for pair-density methods, and it is
  written for the CMS-PDFT variant rather than for L-PDFT or state-averaged
  MC-PDFT. Nuclear-ensemble spectra are therefore not offered for any of the
  three, and because `wigner_spectra` requires the capability outright rather
  than warning about its absence, the refusal is derived rather than coded.

MC-PDFT and L-PDFT do have analytic gradients for both ground and excited
states, plus non-adiabatic couplings, so everything else the request asked for
is available for those two.

The rule this plan works under: a capability cell may only claim something that
was observed on this host, because `MethodCaps.has()` treats an unverified
claim as unroutable. Every row below was written after the spike, not before.

## Phase 1: Establish what PySCF actually does

- [done] P1.1: Probe all three methods for energies, derivatives and transition properties
  evidence: scripts/spikes/spike_pyscf_caps.py → "20 new probes; NEVPT2 energy E_tot = -75.01039574 Eh, MC-PDFT tPBE E_tot = -75.22503862 Eh with E_ot = -9.37482725, L-PDFT 3 states dE = 11.0982/12.2312 eV; gradients, NACs and both refusals all recorded with their real error text"
- [done] P1.2: Determine whether optimization and frequencies are reachable
  evidence: scripts/spikes/spike_pyscf_caps.py → "geomeTRIC on the pair-density object itself raises NotImplementedError('Gradient of LPDFT state-average energy'); driven by nuc_grad_method().as_scanner(state=n) it converges. The app's own _numerical_casscf_hessian runs unchanged on an MC-PDFT object, shape (3,3,3,3)"
- [done] P1.3: Settle the oscillator-strength question, which gates Wigner support
  evidence: scripts/spikes/spike_pyscf_caps.py → "neither an L-PDFT nor a state-averaged MC-PDFT object has trans_moment, and the NEVPT object has no dipole attribute at all; pyscf.prop.trans_dip_moment implements TransitionDipole for CMS-PDFT only"

## Phase 2: The capability rows and everything derived from them

- [done] P2.1: Three capability rows, every cell carrying its own evidence
  evidence: scripts/check_capability_matrix.py → "726 assertions across 18 capability rows and 20 tasks, PASS; 16 new golden entries pin the intended split"
- [done] P2.2: Task support derives correctly, including the refusals
  evidence: scripts/check_capability_matrix.py → "wigner_spectra refuses all three by derivation, naming the specific gap; nevpt2 opt/freq refuse on the missing gradient; mcpdft/lpdft get sp gs/ee/grad/nac plus opt, freq and opt_freq"
- [done] P2.3: Parameters -- active space for all three, on-top functional for two
  evidence: app/chemistry/registry2/params.py → "_MULTIREF gains all three so active_electrons/active_orbitals become required by derivation; ot_functional is a separate spec rather than a widened `functional`, since tPBE is not a name the Kohn-Sham resolver can resolve; want_oscillator_strengths hides itself for the three methods that cannot deliver it"

## Phase 3: Runners

- [done] P3.1: Three single-point runners
  evidence: a direct run of run_nevpt2/run_mcpdft/run_lpdft on water/STO-3G/CAS(4,4) → "NEVPT2 3 roots dE = 10.687/12.335 eV; MC-PDFT tPBE reports E_tot, E_MCSCF and E_ot; L-PDFT 2 states dE = 10.801 eV; all three write a natural-orbital molden and a 7-row orbital table"
- [done] P3.2: Gradient, NAC, optimization and frequency branches
  evidence: a direct run of run_gradient/run_nac/run_geometry_optimization/run_frequency → "MC-PDFT |grad(S1)| = 0.5927, L-PDFT |grad(S1)| = 0.5885, NACs at 7.9e-06 and 5.7e-06, L-PDFT S1 optimization relaxed dE from 10.80 to 4.89 eV, MC-PDFT frequencies 1763.9/4373.0/4704.2 cm-1"
- [done] P3.3: NEVPT2 refuses optimization and frequencies with a reason, not a traceback
  evidence: a direct run of run_geometry_optimization/run_frequency at method='nevpt2' → "both raise ValueError naming the missing NEVPT2 gradient and pointing at CASSCF, MC-PDFT or L-PDFT instead"

## Phase 4: The surfaces a user actually sees

- [done] P4.1: Approval-card previews for every new job shape
  evidence: a direct exec() of all 12 generated preview scripts → "12/12 run against real PySCF. Reading them was not enough: the frequency preview called thermo.thermo(state_model, ...) with no state_model defined anywhere in the script, which reads naturally and raises NameError"
- [done] P4.2: Names, synonyms and the excited-state table
  evidence: frontend typecheck (tsc --noEmit) → "clean; STATE_ENERGY_METHODS is shared between excitedState.ts and ExcitedStateTable.tsx, and naming.py maps mcpdft to MC-PDFT and lpdft to L-PDFT rather than upper-casing them into MCPDFT and LPDFT"
- [done] P4.3: pyscf-forge declared, since MC-PDFT and L-PDFT are not optional
  evidence: requirements.txt → "pyscf-forge added with a note that the distribution name and the import path (pyscf.mcpdft) differ, so a failing `import pyscf_forge` is not evidence of a broken install"

## Phase 5: Documentation

- [done] P5.1: Regenerate the capability tables from code
  evidence: scripts/generate_capability_docs.py → "docs/QM_CAPABILITIES.md regenerated; scripts/check_capability_matrix.py reports docs in sync"
- [done] P5.2: Record the gaps with their real error text
  evidence: docs/PARSER_GAPS.md → "six new rows: the NEVPT2 gradient, the state-averaged-solver refusal, the missing pair-density Hessian, the CMS-PDFT-only transition dipoles, and the state-average gradient NotImplementedError"
- [done] P5.3: README, for the user-visible capability change
  evidence: README.md → "capability table cells derived from the registry rather than edited by hand, which also corrected a pre-existing wrong cell claiming PySCF could produce a nuclear-ensemble spectrum at EOM-CCSD or CASSCF"

## Phase 6: What review found that the live runs could not

Every live run in Phase 3 passed a state count explicitly, so nothing
exercised the default. Three published claims also had no execution behind
them.

- [done] P6.1: L-PDFT could reach READY with no state count and die after approval
  evidence: tests/backend/mrpdft_01_nevpt2_mcpdft_lpdft.py → "n_excited_states applied only to the excited-state family, and required_when is never consulted for a parameter that does not apply, so the lpdft clause was dead code for single_point/gs, opt, freq and opt_freq. applies_to widened and applies_when added to gate it; 22 applicability cases check that nothing else grew a state count"
- [done] P6.2: opt_freq actually runs for both pair-density methods
  evidence: a direct run of run_opt_freq → "MC-PDFT gives 1999.4/3573.0/3807.6 cm-1 at its own optimized geometry; L-PDFT on S1 optimizes and takes frequencies with target_state carried through the handoff"
- [done] P6.3: orbital reuse works on pair-density objects, as the README claims
  evidence: a two-job reuse round trip through a JOBS_DIR-shaped source → "an MC-PDFT job and an L-PDFT job each seeded a second job of the same method from the first's orbitals.molden across a stretched geometry; the source id is recorded in the summary. project_init_guess and sort_mo were untested on a LINPDFT multi-state wrapper before this"

## Phase 7: A standing test

- [done] P7.1: Backend script covering the three methods end to end
  evidence: tests/backend/mrpdft_01_nevpt2_mcpdft_lpdft.py → "103 passed, 0 failed; drives the registry and the runners directly so it creates no jobs and no threads. Asserts the Wigner refusal names the oscillator-strength gap, that L-PDFT demands a state count on every task while nothing else does, and that every preview uses only names it defines"

## Incidental findings, not part of this plan

Logged rather than fixed here, per the standing rule that work surfacing a bug
as a side effect writes it down instead of only mentioning it.

- **`run_frequency`'s CASSCF branch passes the state-averaged object straight
  to `pyscf_thermo.thermo`.** `thermo` reads `model.e_tot`, which on a
  state-averaged object is the average over roots rather than the energy of the
  state whose Hessian was computed, so the reported enthalpy and Gibbs energy
  of a state-averaged CASSCF frequency job are built on a weighted mean. The
  new pair-density branch avoids this with a small shim supplying the tracked
  state's own energy; the CASSCF branch was deliberately left alone rather than
  changed under an unrelated plan. Worth its own item in `BACKLOG.md`.
