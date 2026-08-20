# NexusQC — Projected Implementation Summary

> **Status: projection.** This document describes NexusQC as it will exist
> when the overhaul in [`OVERHAUL_PLAN.md`](OVERHAUL_PLAN.md) is complete. It
> is kept current as scope shifts and finalized in Phase 9, at which point it
> becomes the basis for tutorials and the README. Until then, the shipped
> behavior at any moment is whatever [`TRACKER.md`](TRACKER.md) says is done.

## What NexusQC is

A conversational computational-chemistry agent. You describe a calculation in
plain language — or paste/attach an input file — and the agent settles on a
job type, asks for exactly the parameters that are missing, shows you the
generated input for approval, runs the job in the background across
PySCF/ORCA/BAGEL, and renders results as interactive previews: molecules,
orbitals, vibrational modes, spectra, reaction paths. Jobs are asynchronous
by design — CASSCF/CASPT2 runs of an hour or more are normal; you submit,
leave, and return.

## How a job comes to be

1. **Geometry** arrives as a molecule name, SMILES, a Ketcher sketch, pasted
   XYZ, or an attached `.xyz` file. Multi-geometry files are understood:
   one geometry becomes the active molecule; two become endpoint frames (for
   interpolation or NEB); three or more become a *geometry set* — a completed
   pseudo-job whose frames you can cycle through and tag individually.
2. **The job draft.** The agent builds the job as a draft that the backend
   validates after every change. The backend — not the model — decides what
   is still missing and composes the exact question to ask you. Method and
   basis-set spellings are fuzzy-matched against each engine's own keyword
   pools (scraped from the official manuals plus the Basis Set Exchange), so
   `6-31gd` or `b3-lyp` never reach an engine unrepaired.
3. **Engine routing** is mechanical: your stated engine wins if it supports
   the task; otherwise PySCF → ORCA → BAGEL in that order of preference, with
   hard rules (CASPT2 always runs on BAGEL). Support is decided by a verified
   capability matrix ([`QM_CAPABILITIES.md`](QM_CAPABILITIES.md)) generated
   from the same code that does the routing.
4. **Approval.** Every run pauses at an approval card showing the actual
   input. ORCA/BAGEL inputs are editable in place; edits are re-validated,
   and for multi-image jobs a single edited template cascades to every image.
5. **Execution & preview.** Jobs run as detached subprocesses that survive
   backend restarts and logouts. A fair per-user scheduler admits jobs
   round-robin, so one user's 200-image batch never starves another user's
   single job. While running you see live output; when done, a job-type-aware
   preview.
6. **If a job fails**, nothing retries behind your back. You get a notice and
   an offer to troubleshoot; on acceptance the agent reads the tail of the
   raw output, consults the manuals, explains what it thinks went wrong, and
   presents a corrected job for approval.

## Job types

| # | Task | Subtypes | Engines | Preview highlights |
|---|------|----------|---------|--------------------|
| 1 | Single point (`sp`) | `gs` (default), `ee`, `grad`, `nac` | pyscf/orca/bagel per method | energy+dipole table; excited-state table (E, eV, f, dominant transition) + UV/Vis; gradient matrix+norm; NAC matrix+norm per state pair; orbital viewer |
| 2 | Optimization (`opt`) | `min` (GS or ES), `constrained`, `ci` (conical intersection) | per capability matrix | optimized geometry, energy-vs-iteration plot, final state energies |
| 3 | Frequencies (`freq`) | — | pyscf/orca/bagel | mode table (cm⁻¹, real/imaginary, analytical-vs-numerical noted), animated mode viewer, IR spectrum where available |
| 4 | Opt + Freq (`opt_freq`) | — | single input (orca/bagel), sequential nested (pyscf) | combined opt + freq preview |
| 5 | 1D PES scan (`pes_1d`) | bond/angle/dihedral | pyscf/orca (bagel denied → interp recommended) | path viewer, energy table (Eh + relative eV), PES plot |
| 6 | Interpolated PES (`interp_pes`) | `licc`, `liic`, `idpp` (default, 8 images) | sp engine per method | steps card, path viewer during run, multi-state energy table + plot |
| 7 | NEB TS (`neb_ts`) | — | orca only | MEP path + separate TS viewer, energy table incl. TS, path plot |
| 8 | Wigner spectra (`wigner_spectra`) | — | methods with oscillator strengths | nested sample jobs, ensemble viewer, absorption spectrum with **live broadening slider** (default 50 samples, cap 500) |
| 9 | Active-space recommendation (`cas_reco`) | `explain`, `autocas` (entanglement-based), `avas` | pyscf | entropy/plateau analysis, orbital character table, then an automatic CASSCF-ee run so you inspect the orbitals yourself |
| 10 | Blind run (`blind`) | — | **orca/bagel only** (pasted/uploaded input; PySCF scripts are classified, never executed) | your input verbatim on the card (editable), raw input/output viewers, troubleshoot on failure |
| 11 | Batch (`batch`) | any of tasks 1–4, default subtype only (`sp/gs`, `opt/min`) | per child task | one independent child job per geometry; each child's own preview is the full preview of its type |

Excited-state defaults: **full TDDFT** (not TDA) unless you ask otherwise —
the approval card says so. Multireference methods count the ground state
inside `n_states`; single-reference methods treat it separately; the
elicitation knows the difference so you don't have to.

## Tagging contract

Tag any job into a prompt and the agent receives its parameters and parsed
results. Guarantees:

- Every tagged job exposes its input parameters (rerun "the same but with…")
  and its geometry — for optimizations, always the **final** geometry.
- `sp/ee`, PES, NEB, Wigner: the full result table. `grad`/`nac`: matrix and
  norm. `freq`: frequencies with real/imaginary flags.
- CASSCF-family jobs can **start from the orbitals of a tagged job** — the
  converged orbitals travel from a prior HF/CASSCF run into the new job's
  initial guess on every engine.
- A custom plotting tool turns any tagged data into the plot you describe
  (axes, scale, styling), rendered server-side; every plot downloads as a
  high-resolution 8×6 PNG.
- Ask for a bond/angle/dihedral by atom index ("the C4-C6 bond length",
  "the angle between atoms 1, 2, 3") against a tagged job or frame and get
  a table back; ask the same of a tagged **master** job (a scan, a batch, a
  multi-frame geometry set) and get a histogram of that parameter across
  every child geometry instead.

## Visualizers

All molecular viewers (master molecule, job preview, orbitals, vibrational
modes) share: in-place expansion with a close button, keyboard frame
scrubbing (arrow keys) in expanded view, PNG/APNG download, per-frame
coordinate display, and whole-trajectory download as a single xmol `.xyz`.
Orbital viewers cap unoccupied orbitals at 20. Multi-hundred-frame masters
load frames lazily so previews stay responsive.

## Files and housekeeping

- An **uploaded-file manager** (below the KB panel) lists every attached
  `.xyz`/input file with view, delete, and clear-all; upload via the `+`
  button in the chat box.
- **Account settings carry a danger zone**: clear my chats, clear my jobs
  (running ones are cancelled first), clear my KB (seeded manuals survive) —
  each behind a typed confirmation.

## For developers

- `app/chemistry/registry2/` is the single source of truth: a capability
  matrix (engine × method properties), task definitions whose requirements
  are predicates over that matrix, declarative parameter specs that drive
  elicitation, and mechanical engine routing. `QM_CAPABILITIES.md` is
  generated from it; drift fails CI-style checks.
- The agent is a single ReAct loop optimized for small local models
  (qwen3-coder:30b / qwen3.8:27B Q4_K_M): ~10 narrow tools, a backend-owned
  job-draft lifecycle, a fast capability-lookup tool so the model never
  answers chemistry-support questions from memory, and a bounded context.
- Old jobs never break: legacy specs are adapted at read time
  (`registry2/adapter.py`), not rewritten on disk.
- Anything that cannot be parsed from an engine's real output is listed in
  [`PARSER_GAPS.md`](PARSER_GAPS.md) and shown as "pending" in the UI rather
  than silently dropped.
