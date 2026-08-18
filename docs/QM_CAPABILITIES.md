# QM engine capabilities — verified on this host

What PySCF, ORCA and BAGEL **actually do on this machine**, established by
running real calculations rather than by reading documentation. This is the
human-verified source that `app/chemistry/registry2/capabilities.py` is
transcribed from in Phase 1; from Phase 1 onward the tables here are
regenerated from that code by `scripts/generate_capability_docs.py`, and a
check script fails if the two disagree.

**Why verification rather than citation.** The starting point for this
document was an operator-supplied, documentation-derived comparison of the
three packages (kept outside the repository; its location is recorded in
`CLAUDE.local.md`). Several of its claims did not survive contact with the installed
software (see *Claims not confirmed* at the end). Engine output formatting is
likewise not guaranteed across versions, which is why this repo's parsers are
written against real runs.

**Evidence level** for every cell:

| Level | Meaning |
|-------|---------|
| `run` | Executed here; the datum was located in real output. |
| `manual` | Documented in the engine's own manual (scraped copy in `data/scraped/`), not yet executed here. |
| `gap` | Attempted here; ran but the datum could not be located, or the syntax was rejected. Tracked in [`PARSER_GAPS.md`](PARSER_GAPS.md). |
| `unverified` | Neither run nor confirmed in the manual. Must not be claimed by the routing table. |

Versions: PySCF 2.14.0, geomeTRIC 1.1.1, ASE 3.29.0, ORCA 6.1.1, BAGEL 1.2.2.
Reproduce with `scripts/spikes/spike_{pyscf,orca,bagel}_caps.py`.

---

## PySCF

Probed by `scripts/spikes/spike_pyscf_caps.py` (18/22 capabilities confirmed).

| Capability | Method(s) | Level | Observed |
|---|---|---|---|
| Analytic gradient | hf, dft, mp2, ccsd, casscf | `run` | e.g. HF \|grad\| = 0.086934 Eh/Bohr, shape (3,3) |
| Excited-state gradient | TDDFT (full) and TDA | `run` | \|grad(S1)\| = 0.6027 (TDDFT), 0.6035 (TDA) |
| Analytic Hessian | hf, dft | `run` | 3 modes; HF max 4812.5 cm⁻¹, B3LYP 4697.1 cm⁻¹ |
| Analytic Hessian | casscf | **not available** | `'CASSCF' object has no attribute 'Hessian'` — the app's existing hand-rolled numerical CASSCF Hessian is therefore load-bearing, not redundant |
| NAC (analytic) | SA-CASSCF, via `pyscf.nac.sacasscf` | `run` | Returns (natm,3). Scales as 1/ΔE across a gap scan (2.0e-6 at 10.6 eV → 2.4e-5 at 0.26 eV), i.e. real physics, not a stub. **Absolute magnitudes still to be validated against a literature reference during Phase 5.** |
| NAC | TDDFT | **not available** | no `pyscf.nac.tdscf` in 2.14 (that is pyscf-forge territory) |
| Oscillator strengths | TDDFT | `run` | f = [2.37e-3, ~0, 6.34e-2] |
| Oscillator strengths | CASSCF | `gap` | SA-CASSCF states available, but transition dipoles need manual assembly — no ready API |
| Geometry optimization | via geomeTRIC | `run` | converged in 4 steps, water/STO-3G |
| Constrained optimization | geomeTRIC `constraints` kwarg | `run` | `kernel()` exposes `constraints`; geomeTRIC 1.1.1 |
| Conical intersection (MECI) | — | **not available** | no `pyscf.geomopt.meci`; would need a custom penalty-function driver on top of geomeTRIC |
| AVAS active space | — | `run` | AVAS on `O 2p` → CAS(6,3) |
| DMRG pilot (`pyblock2.driver.core.DMRGDriver`) | — | `run` | Runs. block2 0.5.3 + pyscf-forge installed 2026-08-18; the app's own `_pilot_entropies_dmrg` returns entropies and occupations for water/STO-3G CAS(8,6). **An earlier entry here said "not installed", from probing `pyscf.dmrgscf` — the classic extension, which this app does not use.** Probe the import the code actually makes, not the one the ecosystem is named after. |

### Orbital reuse (Phase 8 flagship) — all three paths confirmed

| Path | Level | Observed |
|---|---|---|
| chkfile round-trip → CASSCF guess | `run` | `lib.chkfile.load(chk, "scf/mo_coeff")` (7,7) → `project_init_guess` → CASSCF converged, E = −74.59692618 Eh. This is the shape the feature needs: a later process reads orbitals off disk with the source object gone. |
| Across geometry change | `run` | CASSCF from projected guess converged, E = −75.01796979 Eh |
| Across basis change | `run` | sto-3g → 6-31g converged, E = −76.03695430 Eh — **requires `prev_mol=`**; without it `project_init_guess` assumes same-basis and fails on matrix shape |

---

## ORCA 6.1.1

Probed by `scripts/spikes/spike_orca_caps.py`.

| Capability | Syntax | Level | Observed |
|---|---|---|---|
| Ground-state gradient | `! EnGrad` | `run` | Both a stdout `CARTESIAN GRADIENT` block and an `input.engrad` file (26 lines, energy then gradient) — two independent parse targets |
| Excited-state gradient | `! EnGrad` + `%tddft ... iroot n` | `run` | Confirmed with PBE0 and with HF (CIS) |
| Excited-state gradient, B88 functionals | `%method ... exchange gga_x_b88 ...` | `run` | **B3LYP/BLYP are refused through the native path** (“Third functional derivative of a B88 exchange-containing functional … not available natively with ORCA. Please, use the LibXC version”), but the same functional via LibXC components **does** produce the gradient. The input builder must rewrite B88-containing functionals into LibXC form when an excited-state gradient is requested, rather than refusing the job. |
| Full TDDFT (not TDA) | `%tddft ... tda false end` | `run` | Accepted; `TD-DFT EXCITED STATES` block produced. Confirms the planned default flip is achievable. |
| NAC | `%TDDFT NROOTS n IROOT k NACME TRUE [ETF TRUE] END` | `run` | Prints `CARTESIAN NON-ADIABATIC COUPLINGS`, per-atom x/y/z, plus `Norm of the NACs`, `RMS NACs`, `MAX NAC`. Observed norm 0.7794747730. |
| NAC on `%casscf` | `nacme true` inside `%casscf` | `gap` | Rejected: `Unknown identifier in CASSCF block … Last token : NACME`. Not available under this syntax in this build. |
| Constrained optimization | `%geom Constraints {B 0 1 0.98 C} end end` | `run` | Converged with the constraint applied |
| Conical intersection | `%CONICAL METHOD {GRADIENT_PROJECTION\|GP_NONACME\|UBP} END` | `run` | `%CONICAL` (**not** `%mecp`) is the ORCA 6 spelling. `METHOD UBP` accepted, terminated normally. Manual: gradient projection is the default when NACMEs are available, UBP when they are not. |
| Opt + Freq in one input | `! Opt Freq` | `run` | Single run produced both the optimization and a `VIBRATIONAL FREQUENCIES` block |
| Orbital restart | `! MOREAD` + `%moinp "source.gbw"` | `run` | HF orbitals accepted as a CASSCF initial guess across a method change; read confirmed in output; terminated normally |

**Parser trap recorded here deliberately:** ORCA's credits banner lists
contributors' specialities — “NACMEs”, “NEB-TS”, “SF” and so on — so a naive
search for a feature name matches on *every* ORCA run, including one that
aborted on an unknown keyword. The spike suite produced exactly that false
positive before its section matcher learned to skip the banner. Any parser
written against ORCA output must anchor past it.

---

## BAGEL 1.2.2

Probed by `scripts/spikes/spike_bagel_caps.py`. See CLAUDE.local.md's standing
note: this host's BAGEL/MKL build is slow and has produced a real
`dsyev/pdsyevd` crash during orbital canonicalisation, so a timeout here is
evidence about the host as much as about BAGEL.

| Capability | Syntax | Level | Observed |
|---|---|---|---|
| Gradient | `{"title":"forces","grads":[{"title":"force","target":0}]}` | `run` | `Nuclear energy gradient` header followed by per-atom blocks (`o Atom 0` / `x` / `y` / `z`) — a different shape from ORCA's, needing its own parser |
| NAC | `grads:[{"title":"nacme","target":0,"target2":1}]` with CASSCF | `run` | `=== NACME evaluation ===` with target states, energy gap in eV, transition dipole moment, oscillator strength, then CASSCF Z-vector iterations. Richer than ORCA's NAC output — it carries the transition dipole and oscillator strength too. |
| Optimize + Hessian in one input | `optimize` block then `hessian` block | `run` | Single input produced both; frequency table carries `Freq (cm-1)`, `IR Int. (km/mol)`, `Rel. IR Int.` and the normal-mode columns |
| Orbital restart | `save_ref` / `load_ref` | `run` | `save_ref` wrote `orbitals.archive`; a separate run loaded it and ran CASSCF (rc=0). This is the BAGEL half of the Phase 8 orbital-reuse feature. |
| Constrained optimization | `fix_atom` | **not available** | See below — accepted and silently ignored. |

**BAGEL has no working constrained optimization by the `fix_atom` route, and
its exit code says otherwise.** BAGEL's JSON reader accepts unrecognised keys
without complaint, so the run exits 0 and looks successful. Optimizing the
same molecule with and without `fix_atom: [0]` puts the supposedly frozen
atom at *byte-identical* coordinates (`O 0.000432 0.000504 0.237032`), having
moved from its input z of 0.130 in both cases. The probe now performs that
differential comparison rather than trusting the exit status; any capability
claim for this engine derived from “it ran without error” is worthless.
This resolves the conflict in the *opposite* direction from the capability
summary's claim.

---

## Claims not confirmed

Differences between that documentation-derived summary and what runs here.
Each is a place the routing table must **not** follow the summary.

1. **“PySCF frequency: Analytical (HF, DFT, CASSCF)”** — CASSCF has no
   analytic Hessian in PySCF 2.14 (`no attribute 'Hessian'`). Frequencies for
   CASSCF are numerical only.
2. **“PySCF NAC: CASSCF (analytical), others via numerical finite-difference”** —
   the SA-CASSCF part is confirmed, but there is no TDDFT NAC module in
   mainline 2.14, and no generic numerical-NAC facility was found.
3. **“PySCF conical intersection searches: yes, via geomeTRIC MECI optimizer”** —
   there is no `pyscf.geomopt.meci`. A MECI driver would have to be written.
4. **“ORCA analytical gradients: … Full TDDFT”** — true, but not for
   B88-containing functionals through the native path; those need the LibXC
   route. The summary does not mention this and it silently blocks the most
   commonly requested functional (B3LYP).
5. **“ORCA nonadiabatic coupling: CASSCF, MRCI (analytical)”** — the `%casscf`
   block rejects `NACME` in this build. What is confirmed working is the
   CIS/TDDFT module's **ground-to-excited** coupling.
6. **BAGEL constrained optimization** — the summary claims Cartesian
   atom-freezing. Settled by differential probe: `fix_atom` is accepted and
   silently ignored, producing an identical optimized geometry. Not
   available. The earlier manual pass that found nothing was right.
7. ~~**DMRG** — not installed.~~ **Withdrawn: this was my own error, not a
   claim of the summary's.** The spike probed `pyscf.dmrgscf`; the app imports
   `pyblock2.driver.core.DMRGDriver`. With block2 installed the pilot runs.
   A capability probe has to exercise the import the code makes.

### A design consequence worth flagging early

The brief states that NAC should be available “only between excited states for
single reference methods, warn if the user requests between the ground and
excited states.” **The installed engines do the opposite.** ORCA's TDDFT
module computes exactly ⟨GS|∂/∂R|ES⟩ and offers no excited-to-excited
coupling; PySCF's NAC support is SA-CASSCF (multireference) only. So for
single-reference methods the ground-to-excited coupling is the *only* thing
available, not the case to warn about. Phase 5 should encode what the engines
actually support and surface this inversion rather than implementing the rule
as stated.
