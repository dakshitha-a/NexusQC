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
  PATH=/home/qcuser/apps/miniconda3/envs/qc-agent/bin:$PATH \
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

_(pending: `node tests/frontend/run_frontend.mjs`)_

## The end-to-end scenarios and the job matrix

_(pending: `bash tests/e2e/run_e2e.sh`, then `e2e_08 --tier 3` separately, then
`node tests/e2e/ui/run_ui.mjs`)_

## The open backlog item

`docs/BACKLOG.md`'s one open item, atom numbers not returning after a
vibrational mode change, was established during the Phase 2 audit to be a
measurement error in the spec rather than an app defect: the check snapshots the
orbital viewer's never-drawn canvas instead of the vibration viewer's. See the
frontend audit (`evidence/audit/frontend.md`) and the report. The app's actual
behaviour there is still unobserved; confirming it is a Phase 3 item.
