# The gate: four full suites, what they found, and what changed

One gate rather than the three the plan sketched. Phase 1's gate ran as
planned; the Phase 2, Phase 3 and close-out gates were merged into this one
because the stack sat on the same commit throughout Phases 2 to 5 and running
the same four suites three times against it would have measured the same thing
three times. `P3.12/README.md` records that decision at the point it was made,
including the run it voided.

Everything here ran against the api image stamped `700b8cc`, then the fixes
below were made and the affected scripts re-run against `f6381d0`.

## Why the whole run was nearly voided, and the one variable that matters

`QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444` is set inside the gate's own
runner script rather than left to whoever invokes it. This host's
`docker-compose.override.yml` remaps nginx to 8444, nothing listens on the
default 8443, and omitting the variable makes every route script fail with
`Connection refused`. That is not a hypothetical: it happened at the previous
gate, produced a 47-script "failure", and cost a full suite run. The log is
kept as `P3.12/backend-run-VOID-wrong-port.log` rather than deleted.

## What the four suites reported

Each suite's log carries the host's load average at the moment it started,
because this machine is shared and three of the failures below turn on it.

| suite | scripts clean | log |
|---|---|---|
| backend (`tests/run_backend.sh`) | 158 of 165 | `backend-run.log` |
| end to end (`tests/e2e/run_e2e.sh`) | 13 of 18 | `e2e-run.log` |
| frontend (`tests/frontend/run_frontend.mjs`) | 38 of 44 | `frontend-run.log` |
| end-to-end UI (`tests/e2e/ui/run_ui.mjs`) | 5 of 9 | `e2e-ui-run.log` |

"Clean" means every check in the script passed. A script with one failing check
out of thirty counts against it, which is why these numbers are lower than a
check-level count would be.

Two of those are worth stating next to the review's own figures. The frontend
suite was 34 of 42 at the Phase 1 gate and is 38 of 44 now, so four specs went
from failing to passing and two new ones were added. The end-to-end UI suite
was 3 of 9 in the review and is 5 of 9, the two recovered being `ui_03` and
`ui_04`, which R-100 covered.

## The measurement this whole phase was built around

`tests/e2e/e2e_21_draft_reaches_card.py`, in the gate's own run:

> RESULT R-101 across 5 families, 15 fresh threads: **15 reached the approval
> card**, 0 ended by asking the user for something, 0 ended with neither.

The review's corresponding figure was 0 of 3 for the deterministic wigner
family and 1 to 2 of 3 for the four flaky ones. What each family asks for, and
why two of the prompts had to be corrected before the number meant anything,
is in `P3.11/README.md`.

`tests/frontend/ui_10_atom_label_toggle.spec.mjs` is **21 of 21**, which closes
the `docs/BACKLOG.md` entry that had stood open since 2026-09-09.

## The three real defects the gate found

**A danger-zone route answering 500 with a database error.** `purge_own_data`
asks for the caller's project archives first since R-087, and
`models.list_owned` passed the id straight into a uuid column, so a caller
whose id is not a uuid got psycopg's `InvalidTextRepresentation` out of
`POST /api/auth/purge-my-data`. `dz_01_self_purge` proves the self-purge is a
no-op for someone with nothing by calling it with a deliberately impossible id,
and the script crashed there. `list_owned` answers "nothing" for an id that
cannot be a user id now. Before: the script died at its fourth section. After:
**12 of 12**.

**The api container accumulates zombie processes.** `entrypoint.sh` execs the
app, so the app was PID 1 and inherited every orphan in its namespace, and
Python does not reap what it did not spawn. ORCA starts a shell, `mpirun` and a
per-module binary. A job that runs to COMPLETION is fine; a CANCELLED one
leaves its grandchildren re-parented to PID 1 for the life of the process,
which for a server is forever. The distinction was measured rather than
assumed: two ORCA jobs run to completion added no zombies, and three cancelled
mid-run took the container from 20 to 30. `init: true` on the api service puts
docker's tini in front, which is the whole of PID 1's job in a container.
`proc_01_engine_orphans_are_reaped.py` is the regression test: **1 of 3 before,
3 of 3 after**, with the count going 0 to 0 across three cancellations.

That change also moves the app off PID 1, so
`perf_10_api_memory_settle.py` now resolves it by command line. Reading
`/proc/1` after the change would measure tini, which uses about 200 KB and
never moves, and every memory number would come back flat.

**A refined active space with no correlation in it, again.** Phase 4 added a
two-orbital floor to the pruning loop, and the gate found CAS(2,1) coming back
anyway. The floor was in the wrong place: `refine()` narrows to states on its
own in two branches when the recommendation published no narrowed tier, and
neither had the completion guard the tier builder has. The guard is now
`narrow.describes_correlation`, shared by all three callers, and it refuses
fewer than two orbitals, no electrons, a completely full space, and everything
on one side of the Fermi level. `cas_16_refine_space_floor.py`: **3 of 5
before**, refining water asked for two states down to CAS(2,1) with a single
occupation of 2.0000; **5 of 5 after**, the same request refining to CAS(8,6)
with occupations 1.9986, 1.9920, 1.6009, 1.6000, 0.4078 and 0.4009, which is a
space that describes something.

## The failures that were the harness, and the app being right

Six matrix cells reported "no approval card" through the whole review and both
gates, and in every case the app had stopped for a good reason that the check
could not see.

- **M05, M10, M11, M12** ask for a CAS(4,4) on water in STO-3G. Water has seven
  basis functions in that basis; three closed orbitals plus four active use all
  seven and leave no virtual orbital at all. Orbital rotation and
  canonicalisation need one, CASPT2 needs somewhere to correlate into, and
  BAGEL dies inside LAPACK rather than saying so, which is why
  `multireference_virtual_space_problem` refuses before the card. Those cells
  ask for 6-31G now, which gives thirteen functions and leaves six virtuals.
- **M13 to M17** never said how many excited states they wanted. `prompt_for`
  handled `n_states` and those cells carry `n_excited_states`, a different key.
  The registry genuinely requires it, so the app asked, and the check scored
  the question as a missing card. That is why the review recorded this family
  as "flaky 1 to 2 of 3": flaky because the model sometimes picked a number and
  sometimes asked.

The matrix prints WHY there is no card now, asked or silent, with the reply
text, so this class cannot be invisible again.

The rest were the same shape, each one a test describing an app that has since
changed:

| what failed | why | after |
|---|---|---|
| `e2e_06` T04 to T06, `e2e_10` K5 | named `search_knowledge_base` and friends, unbound since the four retrieval tools became one `search(source=...)` | 13/13 and 17/17 |
| `e2e_19` W19 | required `submit_draft` to be called, which R-101 exists to make unnecessary | 20/20 |
| `e2e_18` | sent "go ahead and run it" into a pending card and took R-038's 409; the card now comes up on the answer itself | 17/17 |
| `e2e_07` A2d | matched three exact phrasings of a message that now reads better than any of them | 24/24 |
| `e2e_07` A3d | read a job's input back before the job had run | (same run) |
| `model_compat` | required the app to refuse to card a value the model invented; `grounding.py` deliberately replaced that with flagging it as unstated on the card | 13/13 |
| `reject_03`, `share_01` | asserted a new user's job list is empty, true only when the deployment holds no unowned jobs, and unowned-means-shared is settled | 9/9 and 25/25 |
| `ui_15` | focused a row with `el.focus()` and then wondered why `focus-visible` had not painted | 21/21 |
| `e2e_21` | ended with `sys.exit(0 if summary() else 1)`, and `summary()` returns None | 10/10, exit 0 |
| `p1_01` | minted a zero-hour invite to get an expired one, which R-089's bound now refuses; it backdates the row instead, as `p1_08` already did | 15 checks then a crash, now 18/18 |
| `deploy_04` | read `/api/admin/activity` once; it answers from the one-second job index since R-051 | 24/24 |
| `scan_03` | exited 2 when its required job id was not supplied, so a skip counted as a failure | skips cleanly |
| `e2e_13` S1 | measured the probe's runtime rather than the cap: an ORCA CASSCF(4,4)/STO-3G takes about 7 s here and on a loaded host `submit` alone can take longer, so the first job finished before the second was submitted. It holds admission until both are queued now, as `perf_04` does | 8/10 then 10/10 |

`e2e_13`'s timeline, printed by the corrected script, is the per-user cap doing
its job second by second:

```
[7.53, 'running',   'pending', 'queued']
[8.03, 'running',   'pending', 'waiting for a free job slot (you have 1/1 running)']
[8.28, 'completed', 'pending', 'waiting for a free job slot (you have 1/1 running)']
[9.28, 'completed', 'running', 'running casscf via orca']
```

## Two diagnosability fixes, because both cost an hour here

`storage_quota`'s KB reconciliation sweep wrapped itself in
`except Exception: pass`, so it swallowed any bug inside it as readily as an
unreachable vector store. It logs now. And `_helpers.mjs`'s admin-user lookup
called `.find()` straight on the parsed body, so an unauthenticated response
surfaced as "users.find is not a function" from a helper several frames from
the spec that called it. It says what the request actually answered now.

## What is still failing, and why each is not fixed here

**This list was incomplete when it was written, and P6.5 says why.** It was
built from the suites' exit codes, and `deploy_05_deployment_section` printed
three `[FAIL]` lines while still exiting 0, so it never reached the list. Run
alone against the same stack minutes later the same script passes 13 of 13.
The triage, the measurement and the three changes that stop a repeat from being
this hard to read are in `evidence/fix/P6.5/README.md`.


- **`fail_01_notice_flow`** runs its own `JobWatcher` in the host process while
  the container runs one too, against the same bind-mounted `data/`. If the
  container's watcher marks the job seen first, the host's finds nothing newly
  done. `tests/README.md` has documented this since before the review.
- **`perf_02_ttft_and_concurrency`** measures time to first token under
  controlled concurrency on a machine shared with other tenants. It reported
  4.86x against a 3x bound at load average 138. That is the host, and the
  script's own docstring says so.
- **`fe_sec_02`**, **`e2e_09`** XN-03, **`e2e_11`** C2 and C3, **`e2e_12`**,
  **`e2e_17`** L9b, and the four end-to-end UI specs were all failing before
  this phase began and none of them is a finding this phase undertook to fix.
  They are in `docs/BACKLOG.md` with the next experiment named for each.
- **`e2e_04`'s H12** is a change rather than a failure and is written up in
  `docs/BACKLOG.md`: it asserts that an approval resume publishes an
  `agent_step`, which it did when `submit_draft` raised the card. R-101 moved
  the card into `update_job_draft`, so the resumed tool returns a `Command` and
  the tools node publishes no message. Tokens still stream, so the UI is not
  blank, which is what F-008 was about, but the tool chip is gone and the next
  session should decide whether to restore it or retire the check.

## Cleanup

Snapshot before: 16 jobs, 9 threads, 0 plots, 0 projects, 3 users. The suites
created 13 jobs, 16 threads and 1 plot beyond what `zz_98`/`zz_99` reap
themselves, all of which were deleted afterwards. The two-sided diff is
`+0 -0` on every category, so nothing was left behind and nothing that
pre-existed the run was destroyed by it.

`qa_fix` and `qa_fix_2` do not appear because they were never created: the
review had deleted its own accounts and the fix phase worked as `qatest_admin`
and the per-script `qatest_*` users each script mints and cleans up.
