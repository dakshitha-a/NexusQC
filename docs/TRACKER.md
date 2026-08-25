# Active Tracker: fixes from the evaluation battery

Everything the manuscript evaluation battery turned up that is worth fixing,
plus the re-runs that close it out and the hardware floor it established.

The battery itself is closed and archived at
[`trackers/2026-08-manuscript-evaluation-battery.md`](trackers/2026-08-manuscript-evaluation-battery.md).
Its results are in `rsc_digital_discovery/evaluation/summary.md`, and the
score sheet for every trial named below is in that directory's `results/`.

**Why none of this was fixed while the battery ran.** Changing the system
under test mid-run makes the trials on either side of the change
incomparable. So each item was diagnosed, reproduced, written up with its
evidence, and deliberately left alone. Phase 4 re-runs the affected trials
once the fixes land, which is what turns that discipline back into a result.

## How tracking works here

Development is linear, so there is never a reason to have two trackers open
at once. Each plan, feature or non-trivial request gets its own tracker, this
file is whichever one is currently in motion, and when its plan is finished
the file is closed out and moved to [`trackers/`](trackers/), then a fresh one
starts here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path.

A step is `todo`, `in-progress` or `done`. A `done` step carries an evidence
line naming a script or command that a reader can run, and
`scripts/check_tracker.py` verifies the named path really exists. A phase
records its merge hash only once every step in it is done.

## What is deliberately NOT here

**The small models failing is a result, not a defect.** Condition G's 8B arm
scored 1 of 48 and the 14B arm 32 of 60, against 55 of 60 for the deployed
27B. That is the expected shape and the point of running the sweep; it needs
documenting (Phase 3), not fixing. Do not open work to make an 8B model pass.

## Phase 1: the two that defeat the approval card

Both let a card promise something that cannot happen, which is the one
failure mode the whole approval design exists to prevent. Cheapest first.

- [todo] P1.1: normalise the engine name at the registry boundary
  `registry2.tasks.supports("ORCA", ...)` answers `Unknown engine 'ORCA'.`
  while `"orca"` answers supported, and `capability_answer` echoes the
  caller's spelling back rather than normalising. The model writes `ORCA` and
  `BAGEL` naturally. Four sightings in the battery: three cost a wasted tool
  round-trip ("The engine name needs to be lowercase. Let me fix that."), and
  the fourth cost the job. Asked for a CASSCF excited-state job on BAGEL, the
  agent answered "BAGEL cannot run this job here -- the engine name isn't
  recognized in this deployment. Would you like to run it on PySCF or ORCA
  instead?" and raised no card, having just run three BAGEL CASSCF jobs to
  completion minutes earlier. Lower-case at the boundary, the way the 1-based
  atom numbering conversion happens at the RDKit boundary rather than in every
  caller. Affected trials: A-18 t1/t3, B-10 t2, A-15 t1.
- [todo] P1.2: refuse a CASPT2 request with no virtual space to correlate into
  Water in STO-3G is 7 basis functions; CAS(4,4) with 3 closed orbitals uses
  all 7. CASPT2 is a second-order correction into the virtual space, so with
  none left the amplitude equations are empty and BAGEL dies inside LAPACK
  (`Parameter 9 was incorrect on entry to cblas_dgemm`, then
  `dsyev/pdsyevd failed in Matrix`). The app builds that input, cards it,
  submits it, and lets the engine crash. `nclosed + nact` against the basis
  size is already known at input-build time in `bagel_runner._build_input`,
  and the same arithmetic applies to the other multireference engines.
- [todo] P1.3: honour `orbital_indices` on `single_point`, or route it to the renderer
  `params_for('single_point', 'gs')` includes `orbital_indices` and `isoval`,
  and `registry2/tasks.py` explains why there is deliberately no `mo_viz`
  task. But `dispatch.runner_for` sends the spec to the `single_point` runner,
  and neither `orca_runner.run_single_point` nor
  `pyscf_runner.run_single_point` does anything with it -- PySCF's only
  mention writes a comment into the generated input. Cubes come solely from
  the legacy `mo_visualization` runner, which v2 dispatch never reaches. A
  user can ask for cube files, watch the card show `orbital_indices: [4, 5]`,
  approve, and get a job with no cube in it. Leaving the parameter inert is
  the one option that should be off the table, since the card promises it.

## Phase 2: honesty of what the app reports

- [todo] P2.1: attribute a BAGEL crash to the engine, not the parser
  `bagel_runner._safe_parse` wraps any parsing exception in "BAGEL ran to
  completion but the '<job_type>' output parser could not find the expected
  results", and suggests a hand-edited input as the likely cause. When BAGEL
  has died, that message is wrong in both halves and sends whoever reads it to
  the wrong place -- as it did during the battery, for some time. Scan for
  BAGEL's own `ERROR: EXCEPTION RAISED` line first and say so when it is
  there. The underlying MKL instability on this host is environmental and not
  this project's to fix; the misattribution is.
- [todo] P2.2: show defaulted-but-consequential parameters on the approval card
  Three elicitation gaps found by condition B share one shape: a default that
  is correct and invisible at the same time. `use_tda` defaults to `False`, so
  a request saying only "TDDFT" silently gets full linear response -- the
  documented intent, but the card never shows the field either way. `-D3`
  reaches the card as `functional: "B3LYP D3"`, and ORCA's bare `D3` means
  D3(zero), a materially different correction from D3BJ, with no prose saying
  which reading was taken. Showing such parameters on the card, marked as
  defaults, addresses both without changing any registry table.
- [todo] P2.3: stop the model inventing scan atom numbers
  "Scan a bond in water ... from 0.8 to 1.2 angstrom, 5 points" produced a
  card carrying `coordinate: {atoms: [1, 2], type: bond}` in two of three
  trials. `coordinate` is `required_when: ALWAYS`, so the elicitation table is
  right and the model fills it in anyway. Consider forbidding it in
  `update_job_draft`'s docstring the way inventing an
  `active_space_orbital_indices` list is already forbidden.
- [todo] P2.4: end the turn after submitting instead of polling
  On a job of more than a few seconds the model calls `check_job_status` in a
  loop within the same turn, narrating each one: fifteen consecutive "Still
  running. Let me check again." messages in one A-12 turn. Nothing breaks, but
  it burns model time on a system whose asynchronous design exists so nobody
  has to wait, and `job_watcher` already runs a follow-up turn the moment the
  job finishes. Check whether `check_job_status`'s docstring invites it.
- [todo] P2.5: gate the XMS rotation on more than one state
  `bagel_runner._build_input` sets `ms: True, xms: True` unconditionally, so a
  ground-state-only CASPT2 requests an XMS rotation of a 1x1 problem. Tidiness
  rather than a defect -- it was tested during the battery as a suspected
  crash trigger and cleared -- but a reader of the generated input should not
  have to work out that it is harmless.

## Phase 3: the hardware floor the sweep established

- [todo] P3.1: document the minimum model and VRAM in README and the manuscript
  Measured on this host: `qwen3.8:27b` at Q4_K_M is 16.5 GB on disk and sits
  at **16.3 GB resident in VRAM** while serving. With headroom for the context
  window and the embedding model alongside it, **24 GB of VRAM is the
  practical floor**, which puts the app within reach of a single RTX 4090 or
  5090 (24-32 GB) as well as workstation cards like the RTX 5000 Ada this was
  run on. Say what the sweep actually showed rather than only the
  recommendation: at 14B (8.6 GB) task success and elicitation degrade sharply
  while grounding holds, and at 8B (4.9 GB) the model cannot reliably emit
  tool calls at all. That is the floor under the "a modest local model is
  enough" claim and it is more useful stated with its failure mode than as a
  bare minimum spec.
- [todo] P3.2: state the same floor in the deployment docs
  `docs/DEPLOYMENT.md` and the install path should say it too, so someone
  standing up a deployment finds it before choosing hardware rather than after.

## Phase 4: close out the battery

Run after Phases 1 and 2 land. Every runner skips a trial whose score sheet
already exists, so a re-run is: delete the affected sheets, run the same
command, and the gaps refill. `rsc_digital_discovery/evaluation/README.md`
has the commands and the resume rules.

- [todo] P4.1: diagnose and re-run C-07
  Still a `harness-error` rather than a verdict, so one of ten C probes has no
  result. The setup builds an IR spectrum and a UV/Vis spectrum and then asks
  for them on one axis; the UV/Vis plot did not appear even after both jobs
  were moved to ORCA with oscillator strengths requested. Diagnose before
  cleanup, since it needs the jobs still on disk.
- [todo] P4.2: re-run the trials that failed on a fixed defect
  A-18 t1/t3 and B-10 t2 (engine-name case), A-15 t1/t3 (orbital cubes). Delete
  those sheets and re-run their cards. A-15 t2 is a genuine agent failure --
  the card omitted `orbital_indices` -- and stays as it is.
- [todo] P4.3: regenerate the summary and the published page
  `harness/summarise.py` then `harness/report.py`, and republish
  `evaluation/progress.html` to the same artifact URL.
- [todo] P4.4: sweep the battery's jobs and accounts
  `harness/cleanup.py` deletes only jobs named in `results/` and the
  `qatest_eval*` accounts, so the score sheets stay auditable afterwards. 155
  jobs and 40 accounts as of 2026-08-25. Do this last, after P4.1.
