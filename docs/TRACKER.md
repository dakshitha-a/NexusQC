# Active Tracker: manuscript evaluation battery

The quantitative evaluation Section 7 of the RSC Digital Discovery draft
promises, run against the real deployed stack. The design is
[`rsc_digital_discovery/EVALUATION.md`](../rsc_digital_discovery/EVALUATION.md);
this file tracks executing it.

Score sheets, task cards and the harness live beside the design, under
`rsc_digital_discovery/evaluation/`, because the results belong with the
criteria that defined them rather than in a general test directory. That whole
directory is gitignored along with the rest of the manuscript draft, so this
tracker is the only part of the work that is in the repository; a fresh clone
will not have the harness or the sheets.

## How tracking works here

Development is linear, so there is never a reason to have two trackers open
at once. Each plan, feature or non-trivial request gets its own tracker, this
file is whichever one is currently in motion, and when its plan is finished
the file is closed out and moved to [`trackers/`](trackers/), then a fresh one
starts here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path:

- [`trackers/2026-08-job-system-overhaul.md`](trackers/2026-08-job-system-overhaul.md)
  the 10-phase job-type/toolchain/agent overhaul. Closed 2026-08-22, 72 steps
  across 5 merged phases.
- [`trackers/2026-08-plots-as-objects.md`](trackers/2026-08-plots-as-objects.md)
  plots as first-class objects. Closed 2026-08-22, 20 steps across 4 phases.
- the rest of `trackers/` is the same shape; each names its own scope in its
  first paragraph.

A step is `todo`, `in-progress` or `done`. A `done` step carries an evidence
line naming a script or command that a reader can run, and
`scripts/check_tracker.py` verifies the named path really exists. A phase
records its merge hash only once every step in it is done.

## Ground rules specific to this plan

- **Opus never answers chemistry on the agent's behalf.** The evaluated
  system is the local model plus the mechanical core. The harness sends
  prompts, collects artifacts and scores; it does not coach.
- **Harness failures are not agent failures.** A timeout, a dropped event
  stream or a bug in the scorer is recorded as `harness-error`, which is
  excluded from the agent's denominator. Scoring one as `gave-up` would
  corrupt the paper's numbers.
- **Reference values for tier R are produced before the conversational
  attempt** and never adjusted afterwards, per the design.
- **Every job the battery creates is deleted at the end of its condition,**
  with the job ids logged in the score sheet first.

## Phase 0: harness and environment

- [done] P0.1: record the run manifest (app commit, model tag, temperature, engine versions, host)
  evidence: rsc_digital_discovery/evaluation/run_manifest.yaml records commit 3d65089, qwen3.8:27b at temperature 0.1, PySCF 2.14.0, ORCA 6.1.1, BAGEL 1.2.2
- [done] P0.2: harness module driving a real conversational turn end to end
  evidence: rsc_digital_discovery/evaluation/harness/nexus.py opens the event stream before posting, so a turn cannot complete before the harness is listening
- [done] P0.3: vertical slice on one condition-A task, proving the whole scoring path
  evidence: rsc_digital_discovery/evaluation/results/A-01_t1.yaml carries all nine checks passing, card through artifact through quoted value
- [done] P0.4: live progress artifact, republished as conditions complete
  evidence: rsc_digital_discovery/evaluation/harness/report.py builds the page from results/ alone, so it cannot claim progress the sheets do not show

## Phase 1: tier R reference values

- [done] P1.1: scripted reference runs for R-1, R-3, R-4, R-5 (non-BAGEL)
  evidence: rsc_digital_discovery/evaluation/harness/make_references.py wrote references/R-1.yaml, R-3.yaml, R-4.yaml and R-5.yaml before any conversational attempt
- [done] P1.2: scripted reference run for R-6 (BAGEL, overnight)
  evidence: rsc_digital_discovery/evaluation/references/R-6.yaml holds the MS-CASPT2 state energies from a direct BAGEL run of the app's own generated input

## Phase 2: condition A, end-to-end task success

- [done] P2.1: write the 20 task cards
  evidence: rsc_digital_discovery/evaluation/cards/A.yaml, 8 PySCF, 8 ORCA and 4 BAGEL tasks across the capability table
- [in-progress] P2.2: run the 16 non-BAGEL tasks, 3 trials each
- [todo] P2.3: run the 4 BAGEL tasks, 3 trials each (scheduled last)

## Phase 3: condition B, elicitation

- [done] P3.1: write the 12 cards including the negative control
  evidence: rsc_digital_discovery/evaluation/cards/B.yaml, nine missing-parameter prompts, two ambiguous, one negative control
- [in-progress] P3.2: run, 3 trials each, scoring asked/assumed/refused

## Phase 4: condition C, gate integrity and refusal correctness

- [done] P4.1: 4 gate probes
  evidence: rsc_digital_discovery/evaluation/cards/C.yaml, including an instruction embedded in an uploaded file
- [done] P4.2: 6 refusal probes against the fixed list of acceptable reasons
  evidence: rsc_digital_discovery/evaluation/harness/run_c.py grades against each card's reason_groups, conjunctive across groups

## Phase 5: condition D, grounding

- [in-progress] P5.1: 6 perturbed-artifact probes
- [todo] P5.2: 2 absent-value and 2 unparseable-output probes

## Phase 6: condition E, robustness to phrasing

- [done] P6.1: five condition-A tasks rewritten three ways each
  evidence: rsc_digital_discovery/evaluation/cards/E.yaml, scored by the condition-A runner with identical pass criteria

## Phase 7: condition F, cross-job connections

- [done] P7.1: the eight scripted mini-campaigns
  evidence: rsc_digital_discovery/evaluation/cards/F.yaml and harness/run_f.py, which assert on the approval card's source-job fields

## Phase 8: tier R, conversational attempts

- [todo] P8.1: R-1 through R-5
- [todo] P8.2: R-6

## Phase 9: condition G, model sweep

- [done] P9.1: pull the mid (~14B) and small (~8B) tool-calling models
  evidence: rsc_digital_discovery/evaluation/README.md records the sweep procedure; qwen3:14b and qwen3:8b are pulled on this host
- [todo] P9.2: repeat A(10), B(6), D(6) on each

## Findings parked in the backlog

Running the battery surfaced seven things worth fixing in the app itself.
They are in [`BACKLOG.md`](BACKLOG.md) under a dated heading, with a suggested
order, rather than in this tracker: this tracker's plan is *running the
evaluation*, and starting app fixes inside it would both widen the plan and
change the system under test mid-run. That second point is not a formality --
the trials before and after such a change would not be comparable, which is
why every one of these was diagnosed, written up, and deliberately left alone.

Work them once the battery is closed out, in a tracker of their own.

## Phase 10: reporting

- [todo] P10.1: the conditions table, the model-sweep figure, the tier R paragraph
- [todo] P10.2: cleanup sweep, every battery job deleted, ids logged
