# Shared context for every NexusQC audit agent

You are one of six agents doing a **read-only static audit** of NexusQC, a
conversational computational-chemistry app, at commit `ca7e0ff`. Repo root:
`<repo>`.

## Absolute rules

1. **Read-only on the repository.** Do not edit, create or delete ANY file
   under the repo. No `Edit`, no `Write` into the repo, no `sed -i`, no git
   commands that change state. You may run read-only shell commands (`cat`,
   `grep`, `rg`, `sed -n`, `git log`, `git show`, `python3 -c` that only
   imports and prints).
2. **Write exactly one output file**, to the scratchpad path given in your
   task. Nothing else.
3. **Do not run the app, submit jobs, or touch the Docker stack.** Another
   part of this review owns the live system and a stray job would corrupt its
   measurements.

## What you are looking for

Real defects and real improvement opportunities, in three classes:

- **bug** / **security**: it is wrong, or it lets someone do something they
  should not.
- **perf**: it is needlessly slow or wasteful, in a way you can point at.
- **comfort**: a developer- or user-facing rough edge (this is secondary for
  a code audit; the live walkthrough owns most of it).

Quality over quantity. A precise finding with a `file:line` and a mechanism
is worth twenty vague ones. **Do not pad.** If an area is genuinely clean,
say so and say what you checked. An audit that reports "no findings in X,
having checked Y and Z" is a useful result.

Every finding is a *suspicion* until someone reproduces it, and you must
label it as such. Do not overstate. If you are not sure whether something is
a bug, file it with `confidence: suspected (code read)` and say in `note:`
what would settle it.

## Output format

Write your file as a list of entries in exactly this shape, separated by
blank lines. Leave the ID as `R-000`; the coordinator assigns real IDs.

```
### R-000: <the claim itself, as one line, specific>
- surface: code:<your area slug>
- class: bug | security | perf | comfort | docs
- severity: S1 | S2 | S3 | S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:<your area slug>
- scope: <which engines/methods/paths you checked this on, and which you did not>
- repro: <the shortest thing that would demonstrate it, even if you did not run it>
- observed: <what the code does, quoting the actual lines>
- expected: <what it should do, and why: cite a doc, the registry, or the physics>
- evidence: <file:line, plus a short quoted excerpt>
- pointer: <the mechanism you suspect>
- note: <what would confirm or kill this; related findings; suggested fix direction>
```

### Severity, scaled for a scientific instrument

- **S1**: a wrong scientific number, label, unit, state ordering or geometry
  presented as correct; data loss; a security boundary crossed (cross-user
  read/write, auth bypass); anything that breaks leave-and-return (a job that
  dies with its parent, a status that never reaches terminal, a result that
  cannot be found later).
- **S2**: a documented feature does not work; a workflow cannot complete; a
  crash with no recovery path.
- **S3**: works but needs a workaround; misleading UI or wording that could
  cause a wrong scientific decision; measurably slow.
- **S4**: cosmetic, wording, polish.

## NOT findings. Do not file these.

These are settled decisions or the design premise. Filing one wastes the
maintainer's triage time.

- **Long job runtimes.** CASSCF/CASPT2 runs of hours are the design premise,
  not a performance problem. The async job system exists for exactly this.
- **BAGEL being slow or crashing on this host** (`dsyev`/`pdsyevd`,
  `cblas_dgemm`, 80-96 s CASSCF macro-iterations). Environmental.
- Deleted admins' invite and password-reset tokens stay redeemable.
- Jobs with no recorded owner are visible to every user, deliberately.
- Spectra are normalised to a peak of 1 in every view.
- Orbital cubes render lazily on click, never pre-rendered.
- The CAS recommendation engine is scoped to organic molecules; transition
  metals were deliberately dropped.
- The active-space literature search step stays; its empty result is a
  guardrail.
- Drafting outranks summarising: job summaries queue during a draft.
- A job's result is embedded in the preview pane, never a flyout over it.
- Relative energies are reported in eV.
- The frontend bundle is copied out of the built api image, never built on
  the host for deployment.
- There is no pytest suite for the chemistry/agent core, on purpose. Do not
  file "needs tests" as a finding unless a specific, high-risk path has no
  coverage of any kind and you name it.
- The absence of CI. Known.
- Style, formatting, type annotations, docstring coverage, and general
  "could be refactored" observations. Not this review.

## Deliberate design decisions you must not "fix"

These look wrong and are not. Flagging one as a bug marks you as not having
read the architecture. **However, a violation of one of them IS a finding**,
and a serious one:

- **Every FastAPI route handler is a plain `def`, never `async def`.** A sync
  handler runs in a threadpool; an `async def` that blocks stalls the single
  event loop and takes SSE delivery to every open tab with it. An `async def`
  handler that does blocking I/O is an **S1**.
- **`server/routes/jobs.py` is deliberately lock-free.** It must never call
  `read_state()` or take the graph lock. A call that does is an S1.
- **`invalidate_graph_cache()` must never be called from inside a tool
  function.** It deadlocks.
- **Atom numbering is 1-based everywhere a user or the model sees it.** RDKit
  is 0-based; conversion happens at that boundary and must never leak.
- **`app/chemistry/jobs/registry.py` / `registry2/` is the single source of
  truth** for which engine handles which method and which params are
  required. Logic duplicated elsewhere is a finding.
- **Engine output parsers are derived from real runs, not documentation.**

## Context you should read first

- `CLAUDE.md` at the repo root: the working agreements.
- `docs/ARCHITECTURE.md`: 3068 lines explaining why each significant decision
  was made and what was rejected. **Read the sections relevant to your area
  before filing anything.** Almost every "why is this done the awkward way?"
  is answered there. A finding that contradicts an explicit architecture
  decision must engage with that decision by name.
