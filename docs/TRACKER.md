# Active Tracker: clearing the backlog

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
[`trackers/2026-08-job-data-retrieval-and-plotting.md`](trackers/2026-08-job-data-retrieval-and-plotting.md)
-- 30 steps across 8 phases, closed 2026-08-29.

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

`docs/BACKLOG.md` had seven open items. Two predate this month; four came out
of the retrieval and plotting work and its live suite run; one was upgraded
from "unconfirmed" to confirmed by re-running it in isolation. They are worked
one at a time, in order of how contained each is, so that anything discovered
along the way lands against the item that exposed it rather than being
smeared across the whole plan.

The closing rule for every phase below: the fix ships with a test that would
have caught the thing, or the phase says plainly why no such test is possible.

---

## Phase 1: A deleted job leaves nothing behind

`base._iter_job_ids_on_disk` treats a directory with no `spec.json` as "not a
job", so an artifact written after deletion leaves a directory invisible to the
job list, to quota accounting and to `delete_job_dir` alike. Two turned up in
one day and both had to be removed by hand.

- [done] P1.1: A directory with artifacts but no spec is reclaimable
  evidence: tests/backend/jobs_01_orphan_directories.py → "reclaim_orphan_job_dirs removes it; a real job is never reclaimed, and _seen is never touched"
- [done] P1.2: A delete that cannot finish says so instead of going quiet
  evidence: tests/backend/jobs_01_orphan_directories.py → "8/8; rmtree no longer runs under ignore_errors alone -- it retries once and then names the files it could not remove"

## Phase 2: A test run leaves no conversations behind

`zz_99_job_cleanup.py` removes the jobs a suite run creates and works.
Nothing removes the threads, so a run leaves `qatest_*` conversations in the
list -- four after the last one.

- [done] P2.1: A thread-cleanup counterpart to zz_99
  evidence: tests/backend/zz_98_thread_cleanup.py → "against the live stack: 1 conversation pre-existed, 2 created, 2 removed, 2/2 checks"
- [done] P2.2: It removes only what the run created
  evidence: tests/backend/zz_98_thread_cleanup.py → "the operator's own 'load in uracil' conversation is untouched before and after; with no baseline file the sweep skips instead of guessing"

## Phase 3: Every plot is a saved object

`render_neb_plot`, `render_entropy_plateau_plot` and `render_pes_plot` for
`pes_1d` write job artifacts that never register as plots, so they are
unversioned, uneditable and unattachable -- the last gap left in the plotting
work.

- [todo] P3.1: The three unregistered renderers register
- [todo] P3.2: What they produce is editable and attachable like any other plot

## Phase 4: One broadening implementation

The Gaussian broadening arithmetic exists three times: server-side in
`app/chemistry/spectrum.py`, and again in `UvVisSpectrumInline.tsx` and
`IrSpectrumInline.tsx`. The client copies exist for a good reason -- they work
on an already-completed job with no backend call -- but three copies of one
formula will drift, and a spectrum that disagrees with its own PNG is a bug
nobody reports.

- [todo] P4.1: One client implementation, shared by both inline charts
- [todo] P4.2: Client and server agree on the same input, checked

## Phase 5: A structural guard where prose does not hold

Thirteen required parameters carry "ONLY set this when the user has said...",
which measured 2 of 3 on a repeat probe. `n_excited_states` is the worked
precedent for replacing a probabilistic guard with one the model cannot get
wrong.

- [todo] P5.1: Identify which of the thirteen a wrong value is silently plausible for
- [todo] P5.2: Give those a structural guard rather than a stronger sentence

## Phase 6: What perf_02 actually measures

Time-to-first-token under four users is 5.04x the single-user median against a
3x budget, and it reproduces on an idle app stack. GPU contention from other
tenants is the presumed cause and is still an assumption.

- [todo] P6.1: Establish whether the budget is being missed by the app or by the host
- [todo] P6.2: Make the test say which, rather than failing either way

## Phase 7: The deployment can say what it is running

Both rebuilds during the retrieval work used a plain `docker compose --build`,
so `GIT_COMMIT` is unset in the api container and `frontend/dist/.build-commit`
does not exist. The deployment runs main and cannot say so, which a later
`scripts/update.sh` reads as stale.

- [todo] P7.1: Deploy through the stamped path and confirm the stamp
