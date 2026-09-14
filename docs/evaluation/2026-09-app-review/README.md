# App review, September 2026. The protocol

This directory holds a full review of NexusQC: what was checked, what was
found, and how to reproduce any of it. This file is the **executor's manual**.
[`../../TRACKER.md`](../../TRACKER.md) is the progress board and says where
the work has got to; everything about *how* the work is done is here.

Written so that a session which inherits only this repository can pick the
review up and continue it correctly. A session never inherits the previous
session's conversation, so anything not written down here is lost.

| File | What it is |
|---|---|
| `README.md` | this protocol |
| `findings.md` | the register. Every finding, in the schema below, appended as it is found |
| `baseline.md` | Phase 1. The existing suites run at the frozen commit, with every number explained |
| `perf.md` | Phase 4. Measurements, each with the command and conditions that produced it |
| `friction-log.md` | the user's own notes from using the app during the review. Merged into the register at P5.3 |
| `report.md` | Phase 6. The narrative, assembled from the register and never from scrollback |
| `evidence/` | screenshots, log excerpts, tool traces, and the small scripts written for measurements |

## Why a review, and what happens to it

The user asked for a thorough review covering three things at once: bugs, the
features and creature comforts a chemist using this daily would want, and
performance. The workflow has three stages and this is the first:

1. **Review.** This directory. Findings are recorded, not fixed.
2. **Triage.** A short session with the user. Every finding gets a confirmed
   severity and a decision: fix, defer to `docs/BACKLOG.md`, or won't fix.
3. **Fix.** A new tracker, shaped like
   [`../../trackers/2026-08-clearing-the-backlog.md`](../../trackers/2026-08-clearing-the-backlog.md),
   working the accepted items in severity order, one commit each.

## The seven ground rules

**1. Record, do not fix.** The standing "fix any bug you find along the way"
rule is suspended for the duration of this review, and only for it. The reason
is in the repository already: the first backlog tracker explains that changing
the system under test mid-run makes the findings on either side of the change
incomparable. In practice, a commit made during this review touches `docs/`
and `tests/` and nothing else. The one exception is something that blocks the
review itself, a broken test runner or a stack that will not come up, which is
fixed as narrowly as possible and recorded as a finding of class `harness` so
the report can say the ground moved.

**2. The freeze.** Every finding is attributed to one commit and one
deployment. `REVIEW_COMMIT` is recorded in P0.1's evidence line in the
tracker. Two checks keep it honest:

```bash
scripts/update.sh --dry-run    # "api image built from" and "frontend built from" both == REVIEW_COMMIT
git diff --stat <REVIEW_COMMIT>..HEAD -- app server frontend scripts docker nginx    # must be empty
```

Compare the stamp against `REVIEW_COMMIT`, **not** against `HEAD`: this
review's own docs commits move `HEAD` while the stack deliberately stays put.
**Never run `scripts/update.sh`, or the in-app update, while the review is
open.** It rebuilds whenever the stamp differs from `HEAD`, which from P0.7
onwards is the normal state of affairs.

**3. Survive the session ending.** Append to `findings.md` the moment
something is found. The end-to-end suite already works this way and says why:
the report is assembled from the register, never from scrollback. Progress
lives in the tracker's step statuses.

*To resume in a fresh session:* read `docs/HANDOFF.md`, `docs/TRACKER.md`,
this file and `findings.md`; re-verify the freeze; re-arm the two watches
(P0.6); read `<scratchpad>/background-shells.md` and reap anything stale; then
continue at the first step that is not `done`. The scratchpad path is
session-specific, so if the previous session's is gone, take a fresh snapshot
and say so in the report rather than pretending to a baseline you do not have.

**4. Test-data hygiene.** The standing rule is that you delete what you
created and nothing else, and that a full purge happens only when the user
asks for one in those words.

- Work as `qa_review`, `qa_review_2` and `qa_review_3` so everything the
  review makes is owned and identifiable.
- Anything submitted mechanically must pass an owner:
  `JobManager.submit(spec, owner_user_id=...)`
  (`app/chemistry/jobs/base.py`). A job submitted without one is unowned,
  which on this app means visible to every user, and deleting the account
  afterwards will not remove it.
- Snapshot before starting (P0.5), delete the after-minus-before set
  explicitly at the end (P6.2), then verify two-sided: nothing of ours left,
  and nothing of anyone else's missing.
- **Never run**: `tests/backend/p1_07_*`, `tests/backend/p1_03_*`,
  `tests/backend/perf_02_admin_storage_latency.py`,
  `tests/e2e/run_e2e.sh --with-destructive`, `e2e_16 --destroy`,
  `POST /api/admin/purge/*`, or `admin_cli reset-all`. The first three call
  `purge_all_jobs`, which destroys every job on the stack and not only the
  suite's own. This has already cost this deployment its job history twice,
  on 2026-08-28 and 2026-09-06.
- Log every background shell in `<scratchpad>/background-shells.md` with its
  task id or PID, what it is waiting for, and the log line or condition that
  marks it finished. Sweep periodically. Wait on log *content*
  (`until grep -qE "DONE|Traceback" run.log`), never on `pgrep -f` against a
  pattern the waiting shell's own command line contains, which matches itself
  and spins forever.

**5. Explain every figure.** No count appears without its denominator, what a
pass meant, and the IDs behind it. Every performance number carries the exact
command and the conditions it ran under. This is the repository's standing
rule for any document, and the standard to write to is that a reader holding
only the prose can reconstruct the measurement.

**6. Look at the UI, do not read it.** Browser verification means rendering
the page in chromium through Playwright and looking at the screenshot. Two
traps that have caught real work here: `page.screenshot()` cannot reliably
capture WebGL canvas content, so use `canvas.toDataURL()` through
`page.evaluate()` for the molecule, orbital, mode and frame viewers; and a
code read is not verification, which the React Strict Mode WebGL leak proved
when an inspection-only fix silently failed.

**7. Write it like a person.** No em dashes. User-facing wording names things
the way a chemist would say them, not with internal identifiers like
`single_point/grad`.

## This host

```bash
source <home>/apps/miniconda3/etc/profile.d/conda.sh
conda activate qc-agent
export PYTHONPATH=$PWD
export QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444    # this host remaps nginx from 8443
export QC_AGENT_LLM_BASE_URL=http://localhost:11434/v1  # in-process scripts only; .env says host.docker.internal, which resolves only inside a container
conda activate node24                                    # Playwright and Vite
```

Without `QC_AGENT_TEST_BASE_URL` every backend script fails with
`ConnectError: [Errno 111] Connection refused` and the run reports something
like 18 of 87, which reads exactly like a broad regression rather than a wrong
port. The compose project is `nexusqc_dev`. GPU 0 and Ollama are reserved for
NexusQC and may be used freely. The user reaches this host over Tailscale, so
any URL meant for them is `https://100.101.102.103:8444`, not a loopback address.

## The finding schema

One entry per finding in `findings.md`. IDs are `R-001`, `R-002`, and so on,
assigned in order of discovery and never renumbered, because the report, the
triage notes and the fix tracker all cite them.

```
### R-042: <the claim itself, as one line>
- surface: <a Phase 3 surface, or code:<area> for an audit-only finding>
- class: bug | security | perf | comfort | docs
- severity: S1 | S2 | S3 | S4
- cause: CODE | LLM | ENV | HARNESS          (bug and security only)
- confidence: confirmed k/N | suspected (code read) | not reproduced
- found by: P3.4 | audit:jobs | baseline | friction-log
- scope: <which engines, methods and paths this was checked on>
- repro: <exact steps or command from a fresh thread, including the prompt text>
- observed: <what happened, quoting the real output or number>
- expected: <what should have happened, and why: cite the doc, the registry, or the physics>
- evidence: evidence/<file>, or a quoted log excerpt
- pointer: <file:line and a suspected mechanism, marked as a suspicion>   (optional)
- note: <workaround, relation to other findings, anything triage will want>  (optional)
```

`scope` exists because of a standing rule: a fix here has to carry across
every engine and every supported method, not only the path where the bug was
noticed. Recording where a bug *was* and *was not* checked is what makes that
possible later.

### Severity

Scaled for a scientific instrument rather than a website, so a wrong number
outranks a crash.

| | Meaning |
|---|---|
| **S1** | A wrong scientific number, label, unit, state ordering or geometry, presented as correct. Data loss. A security boundary crossed: a cross-user read or write, or an auth bypass. Anything that breaks leave-and-return: a job that dies with its parent process, a status that never reaches terminal, a result that cannot be found afterwards. |
| **S2** | A documented feature does not work, or a workflow cannot be completed at all. A crash with no recovery path. The agent deterministically fails a well-specified request (0 of 3 on fresh threads). |
| **S3** | Works, but needs a workaround. Misleading UI or wording that could lead to a wrong scientific decision. Flaky agent behaviour (1 or 2 of 3). Performance measurably worse than the recorded baseline. |
| **S4** | Cosmetic, wording, polish. |

### Cause, and how to tell them apart

The labels are `tests/e2e/_expected.py`'s existing taxonomy, and the
disambiguator that matters is the **mechanical fallback**. When an
agent-driven scenario fails, re-run the same operation by calling the
mechanism directly:

```bash
docker compose exec -T api python -c "
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager
m = resolve_molecule('water')
spec = JobSpec(task='single_point', subtype='gs', method='hf', engine='pyscf',
               molecule=m.to_dict(), params={'basis': 'sto-3g'})
print(get_job_manager().submit(spec))
"
```

Direct call works, the label is `LLM`. Direct call fails, it is `CODE`. An
`LLM` finding is re-run on three fresh threads and reported as `k/N`: 0 of 3
is deterministic and actionable, 1 or 2 of 3 is flaky and belongs in the fix
plan as prompt hardening.

`ENV` needs two reproductions with a documented signature before it is used.
The two environment classes here are BAGEL/MKL on this host (`dsyev` or
`pdsyevd` failures, `cblas_dgemm` parameter errors, 80 to 96 seconds per
CASSCF macro-iteration on a trivial system) and network reachability for
PubChem, OPSIN, DuckDuckGo and Semantic Scholar.

### Comfort findings

Written from the chemist's seat, not the developer's: what they were trying to
do, how many steps it took, what they had to know that the interface never
told them, what they lost when they refreshed, and whether there was an undo.
A suggested design is welcome, but marked as a suggestion rather than as the
finding. The standing preference is that a genuinely better experience is
worth an unfamiliar one, so do not water a suggestion down to stay close to
what is there now.

## Not a finding

These are settled decisions, measured limitations, or the design premise.
Refiling one as a bug wastes the user's triage time, which is the scarcest
thing in this workflow.

- **Long job runtimes.** CASSCF and CASPT2 runs of tens of minutes to hours
  are the premise the asynchronous job system exists to serve. The only real
  defects in this area are ones that break leave-and-return.
- **BAGEL being slow or crashing on this host.** `ENV`, documented in
  `CLAUDE.local.md`. Not a reason to steer users away from BAGEL either.
- **The sixteen expected negatives** `XN-01` to `XN-16` in
  `tests/e2e/_expected.py`.
- **A `sec_*` backend script printing `[FAIL]`** may be informative rather
  than broken; check `tests/README.md` before filing.
- Deleted admins' invite and password-reset tokens stay redeemable.
- Jobs with no recorded owner are visible to every user, deliberately.
- Spectra are normalised to a peak of 1 in every view.
- Orbital cubes are rendered lazily on click, never as a pre-rendered set.
- The CAS recommendation engine is scoped to organic molecules. Transition
  metals were measured, found to break its central claim, and dropped.
- The active-space literature search step stays, and its empty result is the
  guardrail rather than a failure.
- Drafting outranks summarising: job-completion summaries queue until a draft
  ends in a submission or a rejection.
- A job's result is embedded in the preview pane, never shown by
  auto-opening a flyout over it.
- Relative energies are reported in eV.
- Every route handler is a plain `def`, and `server/routes/jobs.py` is
  lock-free. The *opposite* of either is a genuine finding, and an `async def`
  handler that blocks is an S1.
- The deployed frontend bundle is copied out of the built api image and never
  built a second time on the host.
- Small models failing the manuscript battery is a result, not a defect.
- `scripts/check_public_safe.sh` needs a rework before the first public
  release. Known, and not this review's business.
- The one open item in `docs/BACKLOG.md`, atom numbers not returning after a
  vibrational mode change, is known and already investigated. Confirm it in
  Phase 1 and add the mechanism if the review finds it, but do not refile it.
- The duplicated colour block across seven shell scripts is already recorded
  as an incidental finding in the installer tracker.

## Running the suites here

Each of these takes a while. Run it in the background with unbuffered output
to a log under `evidence/`, log the shell, and wait on the log's content.

```bash
# Backend, default set. Excludes the three purging scripts and sec_10.
bash tests/run_backend.sh 2>&1 | tee evidence/backend-run.log

# Frontend Playwright specs, chromium, no test runner.
node tests/frontend/run_frontend.mjs 2>&1 | tee evidence/frontend-run.log

# End-to-end scenarios. NEVER with --with-destructive.
bash tests/e2e/run_e2e.sh 2>&1 | tee evidence/e2e-run.log
python3 tests/e2e/e2e_08_job_matrix.py --tier 3   # BAGEL cells, separately, expect slow
node tests/e2e/ui/run_ui.mjs 2>&1 | tee evidence/e2e-ui-run.log
python3 tests/e2e/summarize.py                    # reads results/*.jsonl
```

Two failures that are the environment and not the code:
`fail_01_notice_flow.py` and `perf_04_fair_scheduling.py` both run their own
`JobWatcher` or `JobManager` in the host process while the container's own is
running, and race it. `tests/README.md` has the current list.

## Committing during the review

Small and often, so a lost session costs one step and not a phase. The tracker
edit ships in the same commit as the step's output, which is what makes
`git log --follow docs/TRACKER.md` the audit trail. Commit only screenshots a
finding actually cites: `scripts/check_public_safe.sh` cannot read images, and
the report lists the committed ones so a person can look at them before any
public release.
