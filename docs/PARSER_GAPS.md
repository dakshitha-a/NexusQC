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

| Engine | Task / subtype | Method | Datum | What is needed | Status |
|--------|----------------|--------|-------|----------------|--------|
| orca | `sp/nac` | casscf | any NAC output | `%casscf` rejects `NACME` in ORCA 6.1.1 (`Unknown identifier in CASSCF block … Last token : NACME`). If CASSCF/MRCI NACs are reachable in this build under different syntax, an excerpt of a working input+output would settle it; otherwise this is a capability absence, not a parser gap. | open |
| pyscf | `sp/nac` | sa-casscf | absolute magnitude sanity | The machinery runs and scales correctly as 1/ΔE, but the absolute values are small enough that a literature or cross-engine reference case would confirm the convention (sign, ETF, normalisation). Phase 5 should cross-check against ORCA or BAGEL on the same system. | open |
| pyscf | `sp/ee` | casscf | oscillator strengths | SA-CASSCF states are available but PySCF exposes no ready transition-dipole API; strengths need manual assembly from CI vectors. Decide in Phase 5 whether to implement or to route CASSCF oscillator strengths to ORCA/BAGEL (both of which print them). | open |

### Not parser gaps — capability absences confirmed by probe

These are recorded so nobody re-litigates them from documentation:

| Engine | Capability | Finding |
|---|---|---|
| bagel | constrained optimization | `fix_atom` accepted and **silently ignored**; identical optimized geometry with and without it. |
| pyscf | CASSCF analytic Hessian | No `Hessian` attribute; numerical only. |
| pyscf | TDDFT NAC | No `pyscf.nac.tdscf` in 2.14 (pyscf-forge territory). |
| pyscf | MECI / conical intersection | No `pyscf.geomopt.meci`; would need a custom penalty driver. |


## Closed rows

| Engine | Task / subtype | Datum | Closed by | Date |
|--------|----------------|-------|-----------|------|
| _(none yet)_ | | | | |
