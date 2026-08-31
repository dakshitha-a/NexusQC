# Parser gaps

Data a job preview needs but which we cannot yet parse out of an engine's
real output. This file exists so those gaps are **tracked and visible**
rather than silently dropped: a feature ships with the datum marked
"pending output excerpt" in the UI, and the row below records what is
needed to close it.

## Protocol

1. Before writing any ORCA/BAGEL parser, run a **cheap real calculation**
   for that method and job type (water/STO-3G class) and write the parser
   against the actual output. Exact formatting is not guaranteed across
   versions, so documentation is not a substitute. PySCF is derived from
   docstrings and returned objects instead.
2. If a datum still cannot be located in that output, add a row here rather
   than guessing at a regex or blocking the phase.
3. The user reviews open rows and supplies output excerpts showing the datum
   in a real run; the parser is then written against the excerpt and the row
   is closed with the commit that did it.

Status values: `open` (needs excerpt) · `excerpt-received` · `closed`.

## Open rows

| Engine | Task / subtype | Method | Datum | What is needed | Status |
|--------|----------------|--------|-------|----------------|--------|
| orca | `sp/grad` (and presumably `sp/ee`, `sp/nac`) | dft, functional WB97X-D3BJ / WB97X-D4 / WB97X-V / WB97M-V | a working run | All four are real keywords in ORCA 6.1.1's own functional list (`data/scraped/orca/...DensityFunctionalTheory.html.txt`), unlike bare `WB97X-D` below, so this is not the same naming issue. Live-tested on water/STO-3G/S1: WB97X-D3BJ and WB97X-D4 crash with a `PAL_Abort` deep into SCF setup (not a clean input-check refusal); WB97X-V and WB97M-V abort at input-check with "Skipping actual calculation" (consistent with the VV10 non-local correlation term needing a grid/keyword this app's plain `! functional basis EnGrad` line doesn't supply). Needs either a worked ORCA example showing what additional keyword the VV10 functionals need, or confirmation this build is missing a required component (e.g. DFTD4) for the `-D4` cases. | open |

### Not parser gaps. Capability absences confirmed by probe

These are recorded so nobody re-litigates them from documentation. Each is a
genuine limit of the QM package itself, not a datum we failed to parse out of
otherwise-working output. See "Warning users of QM-package incapabilities"
below for how the app keeps a user from silently hitting one of these.

| Engine | Capability | Finding |
|---|---|---|
| bagel | constrained optimization | `fix_atom` accepted and **silently ignored**; identical optimized geometry with and without it. |
| pyscf | CASSCF analytic Hessian | No `Hessian` attribute; numerical only. |
| pyscf | TDDFT NAC | No `pyscf.nac.tdscf` in 2.14 (pyscf-forge territory). |
| pyscf | MECI / conical intersection | No `pyscf.geomopt.meci`; would need a custom penalty driver. |
| pyscf | NEVPT2 gradient | `'NEVPT' object has no attribute 'nuc_grad_method'`. `pyscf.mrpt` computes the correlation energy and nothing derived from it, so geometry optimization, frequencies and constrained optimization are all absent for NEVPT2, not merely slow. A numerical gradient would have to be this app's own code differencing NEVPT2 *energies*, which is a different and much more expensive thing than the numerical Hessian it already builds by differencing an analytic gradient; not attempted. |
| pyscf | NEVPT2 on a state-averaged solver | `RuntimeError: State-average FCI solver object cannot be used in NEVPT2 calculation`. Several roots cannot be corrected on the SA-CASSCF object that produced them. The working route, which is also what the PySCF manual describes, keeps the state-averaged orbitals and rebuilds the wavefunction as a multi-root CASCI in them, correcting each root separately. Not a gap in the app: it is why `run_nevpt2` has a CASCI step that looks redundant and is not. |
| pyscf | MC-PDFT / L-PDFT analytic Hessian | `'PDFT' object has no attribute 'Hessian'`, exactly as for CASSCF. Frequencies use this app's own numerical Hessian over the analytic pair-density gradient, which was confirmed to run unchanged on an MC-PDFT object. |
| pyscf | MC-PDFT / L-PDFT oscillator strengths | Neither a state-averaged MC-PDFT object nor an L-PDFT one has a `trans_moment` method. `pyscf.prop.trans_dip_moment` ships exactly one `TransitionDipole` implementation and it is written for the **CMS-PDFT** variant (`multi_state(weights, 'cms')`), which is a different multi-state flavour from the L-PDFT the user asked for. So these methods give excitation energies with no intensities, `capabilities.py` records `osc_strengths` as a gap for all three new methods, and `wigner_spectra` refuses them by derivation rather than running a whole ensemble and then finding nothing to convolve. **Closed 2026-08-29** by adding CMS-PDFT as a fourth method, which is the variant that implementation is written for. MC-PDFT and L-PDFT still have no intensities and still refuse `wigner_spectra`; CMS-PDFT is the route to a multireference UV/Vis spectrum on PySCF. |
| pyscf | spin purity of any multireference state average | An FCI solver asked for several roots returns the lowest of ANY multiplicity, so a closed-shell molecule's "excited states" silently come back as a mix of singlets and triplets. Two consequences, and the second is the one that bites: the excitation energies move by around 2 eV on water/STO-3G/CAS(4,4) once the triplets are excluded, and **a singlet-to-triplet transition dipole is identically zero**, so CMS-PDFT's oscillator strengths came out at 1e-15 on furan until the state average was made spin-pure (0.027 and 0.254 after). The pair-density methods now put a spin-adapted CSF solver (`pyscf.csf_fci.csf_solver`) under every state average. Note the obvious alternative, `fix_spin_`'s energy penalty, is NOT usable with CMS-PDFT: the penalty leaks into the stored MCSCF energies and the method aborts on its own consistency check with "Sanity fault: e_mcscf != self.e_mcscf", the mismatch being exactly the penalty shift. **Closed 2026-08-29**: plain CASSCF now carries the same constraint, so every PySCF multireference state average in this app is spin-pure. ORCA and BAGEL never had the problem -- ORCA writes `mult` into %casscf and BAGEL writes `nspin` into its casscf block, both of which confine the average to one multiplicity, so CASPT2 inherits it too. A single-root calculation is unaffected either way. |
| pyscf | gradient of a pair-density **state-average** energy | `NotImplementedError: Gradient of PDFT state-average energy` (and the `LPDFT` wording for L-PDFT). Only the individual states have gradients. Handing geomeTRIC the wavefunction object, which is what the CASSCF path does, therefore fails; the optimization has to be driven by `nuc_grad_method().as_scanner(state=n)`. Recorded because the failure is late and the fix is not guessable from the API. |
| orca | CASSCF NAC (`sp/nac`, method casscf) | `%casscf` rejects the `NACME` keyword outright (`Unknown identifier in CASSCF block … Last token : NACME`) in ORCA 6.1.1. User-confirmed (2026-08-19, following independent review) as a real absence in this ORCA build rather than a syntax this app has wrong, closed without excerpt. `capabilities.py` marks `nac=False`/`gap` for orca+casscf, so `tasks.py`'s `supports()` never offers ORCA as an engine choice for a CASSCF NAC job. |
| orca | excited-state gradient/NAC for B88-containing functionals (B3LYP, BLYP) on `sp/grad`, `sp/nac`, `sp/ee` | ORCA refuses a native excited-state gradient for B88-containing functionals. Phase 5 tried the `%method` LibXC rewrite the Phase 0 spike's own `excited_gradient` evidence implied was verified (`Exchange gga_x_b88`/`Correlation gga_c_lyp` with `ScalHFX 0.20`/`ScalDFX 0.72`/`ScalGGAC 0.81`/`ScalLDAC 0.81`, the literature ACM coefficients for B3LYP) and got a ground-state `FINAL SINGLE POINT ENERGY` of -74.066101334401 Ha against native B3LYP's -75.275510717997 Ha. Off by ~1.2 Ha, far past numerical noise, so the naive ACM mapping is wrong. User-confirmed (2026-08-19, following independent review) as a genuine ORCA incapability rather than a mapping this app has wrong, closed without excerpt. `app/agent/tools.py`'s `_build_spec_or_error` refuses the combination outright before a job spec is ever built. The refusal matches on exact functional name (`b3lyp`/`blyp`), not a general B88 detector, since `functional` is a free-text param and no other B88-derived name (CAM-B3LYP, BP86, ...) has been live-verified as refused by ORCA the same way. An unmatched B88-derived functional isn't caught pre-submission and fails with ORCA's own error at run time instead. Safe (no rewrite is ever applied to any functional now) but less informative than the two matched names get. |
| orca + pyscf | `sp/grad` (any excited-state-capable task) | dft, functional `WB97X-D` (bare, no dispersion-version digit) | ωB97X-D is one of the most commonly requested functionals, so checked explicitly rather than left to a user hitting it by accident. It is **invalid on both engines this app supports, for opposite reasons**: PySCF's `pyscf.dft.libxc.parse_xc('wb97x-d')` succeeds (it is a real libxc alias), but `run_gradient` still raises `NotImplementedError: wb97x-d is not supported yet` from the TDDFT gradient driver itself. Accepting the name and being able to compute a gradient with it are different claims. ORCA refuses it even earlier: `WB97X-D` (no digit) is not in ORCA 6.1.1's own functional list at all (`UNRECOGNIZED OR DUPLICATED KEYWORD`), ORCA always requires an explicit dispersion version. Bare `WB97X` (no dispersion) is confirmed working end-to-end on **both** engines. `WB97X-D3` is confirmed working on ORCA but raises the same PySCF `NotImplementedError` as the bare form. **Update (2026-08-22):** `pyscf-dispersion` is now installed, which enables the whole D3(BJ)/D4 family on PySCF, `wb97x-d3bj`, `wb97m-d3bj`, `b3lyp-d3bj` and the `-d4` variants all run, verified by an optimization+frequency job on water/6-31G* that converged with three real frequencies and no imaginary modes. It does **not** rescue `wb97x-d3` or `wb97x-d`: both sit on a hard-coded `_black_list` in `pyscf/scf/dispersion.py` and raise `NotImplementedError` no matter what is installed. `wb97x-d3bj` is PySCF's supported near-equivalent; ORCA remains the engine for `WB97X-D3` itself. **Closed 2026-08-22** by `app/chemistry/jobs/functional.py`, which resolves every spelling of this request to the right name per engine rather than leaving it to a failed job and a troubleshoot round. One further trap found while building it: PySCF's blacklist holds only the *separated* spellings (`wb97x-d`, `wb97x_d`), so `wb97xd` slipped past it, ran, and computed ωB97X-D with no dispersion term at all, a silent wrong answer, not a loud failure. The blacklist is now matched on a punctuation-free key so every spelling is refused together. Closed as a confirmed, engine-specific naming trap rather than a parser gap. Nothing to parse differently, the functional string itself needs to be engine-correct. `registry2/params.py`'s own `functional` field previously suggested `wb97x-d` as an example in its help text, which is now corrected. |
| orca | `opt/ci` (conical-intersection optimization) | hf, dft | Not a capability absence. The opposite: Phase 0's spike verdict ("`%CONICAL METHOD UBP accepted and terminated normally`") used the `! Opt` keyword, and this app's own standing rule already treats "ran without error" as worthless-grade evidence (see the BAGEL `fix_atom` row above), a Phase 6 rerun of that exact input confirmed it: `! Opt` with the identical `%TDDFT`/`%CONICAL` blocks present ran in 0.013s of "Geometry relaxation" (i.e. did nothing; the blocks were silently inert). The ORCA manual's own worked example (`data/scraped/orca/.../conicalintersections.html.txt`) uses `! CI-OPT`, not `! Opt`. Corrected in `orca_runner.py`'s `build_input_text`, and reverified live with a genuine crossing search on twisted ethylene/STO-3G for both a CIS (hf) and a TDDFT (PBE0) reference: `E diff.(CI)` converged to ~1e-4–1e-5 Ha and ORCA's own `HURRAY`/`THE OPTIMIZATION HAS CONVERGED` banner was reached both times. This is also why `app/agent/tools.py`'s old hardcoded "`opt/ci` only works with `engine='bagel'`" refusal (which cited ORCA's *separate* `%mecp` module, a general same-or-different-spin-state MECP search, not what this app's `opt/ci` task models. As evidence ORCA couldn't do it at all) was wrong and is now replaced with a `caps.has("ci_opt")` check, matching what `capabilities.py`/`QM_CAPABILITIES.md` already published. |

### Two ORCA keyword traps, found by asking ORCA rather than reading

Both surfaced during the functional-resolver work (2026-08-22), when the
scraped ORCA candidate list was run past ORCA itself
(`scripts/verify_orca_functionals.py`). Neither is discoverable from the
manual, and both had been sitting in the app's suggestion pool.

| Engine | Datum | Finding |
|---|---|---|
| orca | `M06-2X` as a functional keyword | **Rejected.** ORCA's keyword is `M062X`, unhyphenated, and `M06-2X` is the spelling a chemist is most likely to type, and the one the old fuzzy suggester ranked first. The manual's tables show the display name, which is not always the keyword. |
| orca | `SCAN` as a functional keyword | **Rejected**, because `!SCAN` is ORCA's relaxed-surface-scan keyword. The SCAN functional is `SCANFUNC`. A name collision between a functional and a task, resolvable only by running it. |

Also confirmed in the same sweep: dispersion on ORCA is a separate
keyword, not a suffix (`B3LYP D3BJ` accepted, `B3LYP-D3BJ` rejected), and
91 of 219 scraped candidates were rejected outright. Every `X_*`/`C_*`
`%method`-block component keyword, plus table fragments like `B97X-D3` and
`WHPBE0` that the all-caps regex had been offering as functionals.

One methodological note worth keeping: the first sweep used He/STO-3G and
reported 43 double hybrids as inconclusive, because `RI-MP2 needs an AuxC
basis but none was defined`. Recording those as rejections would have
deleted every double hybrid from the pool. The probe basis is def2-SVP
with both auxiliary sets for that reason.

## Warning users of QM-package incapabilities

A capability absence like the two rows above needs to reach the user before
they submit a job, not after it fails. Two mechanisms cover this, chosen by
how narrow the absence is:

- **Whole (engine, method) pairs**, e.g. ORCA can never do a CASSCF NAC, at
  all, regardless of other parameters. Are recorded in
  `app/chemistry/registry2/capabilities.py` as `False` with `gap` evidence.
  `MethodCaps.has()` treats `gap` (and `unverified`) as unavailable, and
  `registry2/tasks.py`'s `supports()` derives engine/method offers from that,
  so the engine is never offered to the user for that task in the first
  place. There is nothing to warn about because the combination never
  reaches an approval card.
- **A single parameter value within an otherwise-working (engine, method)
  pair**, e.g. ORCA's excited-state gradient works for PBE0 but not B3LYP.
  Can't be expressed by that per-(engine, method) table, since the table has
  no axis for "which functional". These are refused with an explicit,
  specific message by a cross-field check in `app/agent/tools.py`'s
  `_build_spec_or_error`, before a `JobSpec` is ever constructed, rather than
  being allowed to reach a runner and fail (or worse, run and return a wrong
  answer, as the B88 rewrite did).
- **A combination that works but deserves a caveat**, rather than a hard
  refusal, uses a `ParamSpec`'s `warn_when` in `registry2/params.py`: a
  condition plus text shown alongside the field rather than blocking
  submission. The `functional` param's own `warn_when` is the example this
  phase added it to. It fires for exactly the B88 case above so the caveat
  reaches the user even outside the one narrow refusal path, without
  claiming coverage the refusal check doesn't have.

Either way, `docs/QM_CAPABILITIES.md`'s generated table and the README
"Supported calculations" summary are the record of what's officially
supported; an entry here that's a confirmed capability absence should never
also be shown as supported in either.

**A gap none of the three mechanisms cover, found while checking the WB97X
row above:** `functional` is free text, and `elicitation.py` only runs
`suggest_functional`'s fuzzy match against the engine's real keyword list
when the field is *missing* (`missing_required`'s elicitation branch). Once
a value is present, right or wrong. The draft goes straight to "ready"
with no check that the string is one of the engine's actual functionals, so
a typo or an engine-specific naming miss (like bare `WB97X-D`) only surfaces
as a runtime crash after the job is submitted and run, not on the approval
card. `suggest_basis`/`suggest_functional`'s fuzzy-match machinery already
exists and already knows each engine's real name pool. Extending
validation to a *present* value, not only a missing one, would close this,
but that is new elicitation-flow behavior, not a doc fix, and is left as a
noted idea rather than built here.


## Closed rows

| Engine | Task / subtype | Datum | Closed by | Date |
|--------|----------------|-------|-----------|------|
| pyscf | `sp/nac` | sa-casscf NAC magnitude sanity | Cross-checked against ORCA on the same C1-distorted water/STO-3G geometry as `scripts/spikes/spike_orca_caps.py`'s own NAC probe: ORCA's ground-to-excited (S0/S1) CIS/TDDFT NAC norm reproduced the spike's recorded 0.7794747730 exactly (`tests/backend/grad_01_gradients_and_nac.py`), and PySCF's SA-CASSCF S0/S1 NAC on the same geometry is a small but genuinely nonzero, correctly-scaled vector (no sign/normalisation red flag against the 1/ΔE scaling `scripts/spikes/spike_pyscf_caps.py` already established). PySCF and ORCA compute NAC for physically different reference wavefunctions (SA-CASSCF vs. single-reference CIS/TDDFT) on the same molecule, not the identical number, so this is a same-system sanity cross-check, not a numerical identity, which is what the row asked for. | Phase 5 |
| pyscf | `sp/ee` | casscf oscillator strengths | Decision, not an implementation: a CASSCF request wanting oscillator strengths is routed away from PySCF, which has no route to them, and onto an engine that does. PySCF's SA-CASSCF oscillator strengths are not implemented and are not planned to be, since the routing already gives a correct answer through a different engine. **Correction (2026-08-31):** this row originally called ORCA "the only engine here that computes them for CASSCF". That was wrong. BAGEL computes them too, from a `forces` block with `dipole` set and an empty `grads` list, and its capability row had recorded `osc_strengths=True` all along -- what was missing was that `bagel_runner._build_input` only emitted that block for CASPT2, so a CASSCF job's `want_oscillator_strengths` was silently dropped. The routing rule that asserted the exclusivity is gone; the constraint is now a filter that keeps whichever engines really can, and ORCA wins the default on preference order alone. | Phase 5 |
