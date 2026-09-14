# Phase 1 baseline: the existing suites at the frozen commit

What the standing test suites report at `ca7e0ff`, before any exploratory work,
so the review starts from a known state. Every figure here says what the test
did, what its denominator counts, what a pass means, and what the result means,
per the repository's standing rule. Where a number differs from the last full
pass (`docs/evaluation/2026-09-06-full-pass.md`), the difference is called out.

Anything a suite found that is a real defect is in [`findings.md`](findings.md)
with an `R-` id; this file is the run-level picture.

## The backend suite

**What it is.** `tests/run_backend.sh`, 142 standalone invoke-and-print scripts
run in sequence against the live compose stack, covering the chemistry core,
the agent graph, the job registry, and the multi-user auth/admin layer. The
three deployment-wide purge scripts and `sec_10` are excluded from the default
run, as always.

**How to reproduce.**

```bash
QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \
  PATH=<home>/apps/miniconda3/envs/qc-agent/bin:$PATH \
  QC_AGENT_LLM_BASE_URL=http://localhost:11434/v1 \
  bash tests/run_backend.sh
```

**Result: 141 of 142 scripts report all checks passing.** The run took about
80 minutes (06:48 to 08:08 UTC on 2026-09-13); most of that is real quantum
chemistry, since scripts like `grad_01`, `opt_01`, `p7_*` and `p8_*` submit and
wait on actual PySCF and ORCA jobs, and `model_compat` is a 20-to-30-minute LLM
probe. The distilled log (stamps, every script header, every per-script
summary, and the runner summary) is at
[`evidence/backend-run.log`](evidence/backend-run.log); the full 380 KB with
every SCF trace stayed in the session scratchpad.

**The one failure is `perf_04_fair_scheduling.py`, and chasing it produced a
real finding.** `tests/README.md` says this script can fail in a full-suite run
because jobs left by earlier scripts occupy the global concurrency cap it sets
to 1, and it instructs the reader to re-run it in isolation, where it says the
script passes 5 of 5. Re-run in isolation against a stack confirmed idle (8
admin jobs and 9 threads, matching the pre-review snapshot), it failed there
too: **4 of 6 checks, with `n_observed=7`**, not the documented "observed 5 of
7" cap-occupied skew. So it is not the environmental artifact the README
describes, and the README's "5/5 on an idle stack" claim is false at this
commit. It is written up as **R-098**, cause undetermined between a real
round-robin fairness regression and a race in the test itself, with the
experiment that settles it named in the entry. The lesson worth keeping: this
was caught only by following the README's own re-run instruction rather than
trusting its stated outcome.

**The suite cleaned up after itself.** `zz_98_thread_cleanup` and
`zz_99_job_cleanup` confirm every job (331) and conversation (4) the run
created was deleted, and, in the other direction, that nothing pre-existing was
destroyed. So unlike the 2026-09-06 pass, this run did not trip a global purge;
the quarantine of the three purging scripts held.

## The frontend Playwright specs

**What it is.** `node tests/frontend/run_frontend.mjs`, 42 raw Playwright specs
(chromium, no test runner) against the same stack and the frontend build on
disk, which the specs themselves confirm is the frozen bundle (`ca7e0ff13d24`).

**Result: 38 of 42 specs report all checks passing.** The four that do not:

- **`ui_10_atom_label_toggle`** (20/21): the one open `BACKLOG.md` item, atom
  numbers not surviving a vibrational mode change. The Phase 2 audit established
  this is a spec measurement error (the check snapshots the orbital viewer's
  never-drawn canvas, not the vibration viewer's), so the app behaviour is still
  unobserved; not a new regression. Confirmed still failing identically here.
- **`scan_03_excited_state_drawer`**: not a defect. It requires
  `QC_AGENT_TEST_SCAN_JOB_ID` set to a completed `interp_pes/ee` job and skips
  with a setup message when it is not; it was not set for this run.
- **`fe_sec_02_adminpanel_silent_failure`**: a `TimeoutError` waiting for the
  forced-500 error text, after the admin console entry rendered. It timed out
  the same way in the 2026-09-06 pass, so it is recurring rather than a fresh
  regression; whether the admin error-display path actually regressed or the
  spec is brittle is re-checked live in P3.8/P3.10 (the admin error paths).
- **`cas_14_refinement_drawer`** (13/17): a candidate real defect, **R-099**.
  It seeds a real recommendation and refinement, both complete, and the
  refinement drawer's rotation trail renders correctly, but its natural-orbital
  occupation table shows zero data rows. Cause undetermined between an empty
  summary field and a render guard keyed on a `refined_*` key the runner does
  not publish; settled in P3.4.

So of the four, one is the known backlog item, one is a missing test fixture,
one is a recurring ambiguous timeout, and one (R-099) is a candidate defect
carried into the walkthrough to settle.

## The end-to-end scenarios and the job matrix

**What it is.** `bash tests/e2e/run_e2e.sh`, the agent-driven pre-deployment
suite: real browser or HTTP sessions, real agent turns against the live model,
with every assertion made on the tool trace read back from thread state. 17
scripts (preflight, harness gate, molecule resolution, agent tools, approval
flow, the 41-cell job matrix, plots, KB, param correction, stability,
logout-and-return, elicitation, wigner, blind input). LLM-nondeterministic
failures are retried up to 3 times on fresh threads, so a script's verdict is
its outcome after retries.

**Result: 15 of 17 scripts passed, 2 failed.** The two failures:

- **`e2e_03_route_auth_sweep`** is test drift, **R-100**, not an auth
  regression. It flags `GET /api/version -> 200` anonymously, but that route is
  deliberately public (documented in `server/main.py:155`, like `/api/health`);
  the test's `PUBLIC_ROUTES` list just omits it. The non-admin pass (25 admin
  routes all 403) and the cross-user pass (thread routes all 404) both hold.
- **`e2e_19_wigner_ensemble`** is a real prompt-reliability finding, **R-101**.
  The agent reaches a ready draft for both the source frequency job and the
  ensemble job, then does not call `submit_draft`, so no approval card appears,
  across all three retries. The mechanical fallback works, so the code path is
  sound; this is the agent not proceeding, and it is the deterministic end of a
  wider flaky pattern (excited-state single points, cas_reco, and some bagel
  cells in `e2e_08` failed the same way on first attempt and recovered on
  retry).

**Other observations carried into Phase 3**, none of which failed a script but
each worth a live look:

- `e2e_13_stability` reported 4/10, every failure downstream of its ORCA
  CASSCF probe reaching `failed` under host load 12-13. Whether that is
  contention (ENV) or a real defect is settled by an isolated re-run; see
  `evidence/p1-notes.md`.
- `e2e_08` M23 hit `RuntimeError: ORCA exited with code 2` on one cell, an
  engine failure to be reproduced in isolation (ENV vs CODE).
- `e2e_10_kb` K5 expects the agent to call `search_knowledge_base`, which was
  unified into `search(source=...)`; this is the same tool-name drift the audit
  recorded (the troubleshoot-prompt finding), test side.
- `e2e_11_param_correction` C2/C3 came back `method=None` and candidate menus
  `None`; whether keyword suggestion regressed or the assertion is stale is a
  P3.3 check.
- `e2e_17` L9b: after a job completed while the user was logged out, no
  unprompted summary was written; L1-L8 (the leave-and-return core: survival,
  results, artifacts, resume) all passed. A P3.5 look.

## The open backlog item

`docs/BACKLOG.md`'s one open item, atom numbers not returning after a
vibrational mode change, was established during the Phase 2 audit to be a
measurement error in the spec rather than an app defect: the check snapshots the
orbital viewer's never-drawn canvas instead of the vibration viewer's. See the
frontend audit (`evidence/audit/frontend.md`) and the report. The app's actual
behaviour there is still unobserved; confirming it is a Phase 3 item.

## The end-to-end UI specs

**What it is.** `node tests/e2e/ui/run_ui.mjs`, 9 Playwright specs driving the
whole shell through a real browser, with WebGL viewers read via `toDataURL`.

**Result: 3 of 9 specs passed, 6 failed.** This is the noisiest suite, and the
six failures split into stale tests, a setup error, and genuine candidates that
Phase 3.4 re-drives with per-job instrumentation to settle:

- **`ui_03_molecule_kb`** (14/15): "KB search input present -- not found". The
  KB search is now behind a `SearchToggle` (`KbSection.tsx` imports it), part of
  the deliberate "stop spending a row on a search box" change; the input is
  collapsed until toggled, and the test looks for it directly. Stale test.
- **`ui_04_admin_visual`** (39/40): the overview no longer shows "Public web
  access". The public listener was removed in 2026; the test still expects its
  label. Stale test, same family as the deploy audit's nginx/docs stale-public
  -listener findings.
- **`ui_06_bug_reports`**: threw at `uiRegister` (spec line 32), a setup step,
  not the bug-report flow; the likely cause is the shared-client-IP register
  rate limiter, which this review's own account creation had been consuming.
  Re-run in isolation in P3.8.
- **`ui_01_shell_and_chat`** (21/23): "assistant produced visible text -- final
  length 0". The agent produced no reply; adjacent to R-101 (agent behaviour),
  to reconfirm live in P3.1/P3.3.
- **`ui_02_approval_jobs_drawer`** (38/42): reports drawer sections rendering
  when they should be gated off ("[hf] ... Molecular orbitals", "[dft] ...
  Optimization energy") but also "[casscf] 2 elements matched job id" -- the
  selector matched two jobs, so the drawer it asserted on may not be the one it
  meant. Candidate drawer-gating issue, but the ambiguous selection has to be
  ruled out first; P3.4 drives each job type's drawer in isolation.
- **`ui_09_orbital_and_mode_panels`** (21/24): the cube loading spinner not
  clearing, the isosurface check failing at 12930 bytes (which is above the
  usual rendered-content threshold, so the assertion wants something specific),
  and a scrubber drag costing 3-4 cube renders rather than one. The last is a
  concrete viewer-perf observation worth a finding if it reproduces; P3.4/P4.4
  settle all three.

The pattern across P1.4 is that the UI specs have drifted against removed
features and are sensitive to a stack that already holds jobs, so their raw
pass rate understates the app. The definitive UI findings come from Phase 3.4,
which drives each surface with its own seeded job and reads the result back
per-job.