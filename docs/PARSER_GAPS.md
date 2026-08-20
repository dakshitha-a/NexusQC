# Parser gaps

Data a job preview needs but which we cannot yet parse out of an engine's
real output. This file exists so those gaps are **tracked and visible**
rather than silently dropped: a feature ships with the datum marked
"pending output excerpt" in the UI, and the row below records what is
needed to close it.

## Protocol

1. Before writing any ORCA/BAGEL parser, run a **cheap real calculation**
   for that method and job type (water/STO-3G class) and write the parser
   against the actual output — exact formatting is not guaranteed across
   versions, so documentation is not a substitute. PySCF is derived from
   docstrings and returned objects instead.
2. If a datum still cannot be located in that output, add a row here rather
   than guessing at a regex or blocking the phase.
3. The user reviews open rows and supplies output excerpts showing the datum
   in a real run; the parser is then written against the excerpt and the row
   is closed with the commit that did it.

Status values: `open` (needs excerpt) · `excerpt-received` · `closed`.

## Open rows

*(none at present)*

### Not parser gaps — capability absences confirmed by probe

These are recorded so nobody re-litigates them from documentation. Each is a
genuine limit of the QM package itself, not a datum we failed to parse out of
otherwise-working output — see "Warning users of QM-package incapabilities"
below for how the app keeps a user from silently hitting one of these.

| Engine | Capability | Finding |
|---|---|---|
| bagel | constrained optimization | `fix_atom` accepted and **silently ignored**; identical optimized geometry with and without it. |
| pyscf | CASSCF analytic Hessian | No `Hessian` attribute; numerical only. |
| pyscf | TDDFT NAC | No `pyscf.nac.tdscf` in 2.14 (pyscf-forge territory). |
| pyscf | MECI / conical intersection | No `pyscf.geomopt.meci`; would need a custom penalty driver. |
| orca | CASSCF NAC (`sp/nac`, method casscf) | `%casscf` rejects the `NACME` keyword outright (`Unknown identifier in CASSCF block … Last token : NACME`) in ORCA 6.1.1. User-confirmed (2026-08-19, following independent review) as a real absence in this ORCA build rather than a syntax this app has wrong — closed without excerpt. `capabilities.py` marks `nac=False`/`gap` for orca+casscf, so `tasks.py`'s `supports()` never offers ORCA as an engine choice for a CASSCF NAC job. |
| orca | excited-state gradient/NAC for B88-containing functionals (B3LYP, BLYP) on `sp/grad`, `sp/nac`, `sp/ee` | ORCA refuses a native excited-state gradient for B88-containing functionals. Phase 5 tried the `%method` LibXC rewrite the Phase 0 spike's own `excited_gradient` evidence implied was verified (`Exchange gga_x_b88`/`Correlation gga_c_lyp` with `ScalHFX 0.20`/`ScalDFX 0.72`/`ScalGGAC 0.81`/`ScalLDAC 0.81`, the literature ACM coefficients for B3LYP) and got a ground-state `FINAL SINGLE POINT ENERGY` of -74.066101334401 Ha against native B3LYP's -75.275510717997 Ha — off by ~1.2 Ha, far past numerical noise, so the naive ACM mapping is wrong. User-confirmed (2026-08-19, following independent review) as a genuine ORCA incapability rather than a mapping this app has wrong — closed without excerpt. `app/agent/tools.py`'s `_build_spec_or_error` refuses the combination outright before a job spec is ever built. The refusal matches on exact functional name (`b3lyp`/`blyp`), not a general B88 detector, since `functional` is a free-text param and no other B88-derived name (CAM-B3LYP, BP86, ...) has been live-verified as refused by ORCA the same way. An unmatched B88-derived functional isn't caught pre-submission and fails with ORCA's own error at run time instead — safe (no rewrite is ever applied to any functional now) but less informative than the two matched names get. |

## Warning users of QM-package incapabilities

A capability absence like the two rows above needs to reach the user before
they submit a job, not after it fails. Two mechanisms cover this, chosen by
how narrow the absence is:

- **Whole (engine, method) pairs** — e.g. ORCA can never do a CASSCF NAC, at
  all, regardless of other parameters — are recorded in
  `app/chemistry/registry2/capabilities.py` as `False` with `gap` evidence.
  `MethodCaps.has()` treats `gap` (and `unverified`) as unavailable, and
  `registry2/tasks.py`'s `supports()` derives engine/method offers from that,
  so the engine is never offered to the user for that task in the first
  place — there is nothing to warn about because the combination never
  reaches an approval card.
- **A single parameter value within an otherwise-working (engine, method)
  pair** — e.g. ORCA's excited-state gradient works for PBE0 but not B3LYP —
  can't be expressed by that per-(engine, method) table, since the table has
  no axis for "which functional". These are refused with an explicit,
  specific message by a cross-field check in `app/agent/tools.py`'s
  `_build_spec_or_error`, before a `JobSpec` is ever constructed, rather than
  being allowed to reach a runner and fail (or worse, run and return a wrong
  answer, as the B88 rewrite did).
- **A combination that works but deserves a caveat**, rather than a hard
  refusal, uses a `ParamSpec`'s `warn_when` in `registry2/params.py`: a
  condition plus text shown alongside the field rather than blocking
  submission. The `functional` param's own `warn_when` is the example this
  phase added it to — it fires for exactly the B88 case above so the caveat
  reaches the user even outside the one narrow refusal path, without
  claiming coverage the refusal check doesn't have.

Either way, `docs/QM_CAPABILITIES.md`'s generated table and the README
"Supported calculations" summary are the record of what's officially
supported; an entry here that's a confirmed capability absence should never
also be shown as supported in either.


## Closed rows

| Engine | Task / subtype | Datum | Closed by | Date |
|--------|----------------|-------|-----------|------|
| pyscf | `sp/nac` | sa-casscf NAC magnitude sanity | Cross-checked against ORCA on the same C1-distorted water/STO-3G geometry as `scripts/spikes/spike_orca_caps.py`'s own NAC probe: ORCA's ground-to-excited (S0/S1) CIS/TDDFT NAC norm reproduced the spike's recorded 0.7794747730 exactly (`tests/backend/grad_01_gradients_and_nac.py`), and PySCF's SA-CASSCF S0/S1 NAC on the same geometry is a small but genuinely nonzero, correctly-scaled vector (no sign/normalisation red flag against the 1/ΔE scaling `scripts/spikes/spike_pyscf_caps.py` already established). PySCF and ORCA compute NAC for physically different reference wavefunctions (SA-CASSCF vs. single-reference CIS/TDDFT) on the same molecule, not the identical number, so this is a same-system sanity cross-check, not a numerical identity — which is what the row asked for. | Phase 5 |
| pyscf | `sp/ee` | casscf oscillator strengths | Decision, not an implementation: `want_oscillator_strengths` (registry2/params.py) already routes a CASSCF request wanting oscillator strengths to ORCA, the only engine here that computes them for CASSCF — PySCF's SA-CASSCF oscillator strengths are not implemented and are not planned to be, since the routing already gives a correct answer through a different engine. | Phase 5 |
