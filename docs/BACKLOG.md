# Backlog

The living record of unimplemented bugs and features. Kept short deliberately.
This is a list to work from, not an investigation report. When an item needs
more explanation than a line or two, that reasoning belongs in the commit that
closes it, not here.

## History

This replaces `docs/ROADMAP.md` and the four `docs/e2e-*-2026-08-16*.md` /
`docs/e2e-*-2026-08-17.md` documents, retired once the last two items they
tracked (FR-2's higher-resolution viewer capture, and the Ketcher chunk-weight
reduction) were implemented and verified live. Their full investigation,
findings, the ranked fix plan, and what was checked live versus by inspection
only, is preserved in git history rather than carried forward. To recover one:

```
git log --all --full-history -- docs/ROADMAP.md   # find the last commit that has it
git show <that-commit-sha>:docs/ROADMAP.md          # print its content
```

A fresh testing pass is expected to populate this file going forward, superseding
the 2026-08-16/17 pass's results.

The 10-phase registry v2/agent-rebuild overhaul (`docs/trackers/2026-08-job-system-overhaul.md`, all 72
steps done as of 2026-08-20) retired the `submit_job` tool this file's own
"Open" section used to name. Replaced by `start_job_draft`/
`update_job_draft`/`submit_draft`, whose ready-draft response now always
carries an explicit "NEXT STEP: ... call submit_draft now" instruction,
resolving the skipped-submission problem that item described. Recovered the
same way as `docs/ROADMAP.md` above if the original wording is ever wanted.

## Open

- **This host's api image has never been built through the stamped path.**
  The build-commit stamp that `scripts/update.sh` now relies on
  ([`trackers/2026-08-update-knows-what-it-runs.md`](trackers/2026-08-update-knows-what-it-runs.md))
  is verified everywhere except across a real `docker build`: the session that
  wrote it could not run one. A dry run therefore still reports `api image
  built from: unknown`, which is the correct reading for an image built
  outside the script and is handled as stale rather than as current, so
  nothing is broken. One run of `scripts/update.sh HEAD` from the repository
  root with node24 on PATH closes it. It should print the rebuild-only path,
  and a following `--dry-run` should report a real commit. If it instead warns
  that the container is still running an older commit, that is the
  post-build stamp check firing and the fix it prints is `--force-recreate`.

- **The job scheduler's concurrency cap is enforced within a dispatch tick but
  not across ticks.** `JobScheduler._dispatch_tick` counts its own admissions
  in `admitted_total`/`admitted_per_owner` and passes them to `block_reason`,
  which is what turns a per-tick cap back into a real cap. But `_on_admit`
  returns immediately and writes nothing, and `block_reason` counts running
  jobs by reading `status.json` off disk, so those counters reset at the tick
  boundary while the disk still shows the previous tick's admission as not
  running. The next tick therefore sees zero running and admits again under a
  cap of 1. This is what `tests/backend/perf_04_fair_scheduling.py` fails on,
  reproducibly and with an identical admission order on separate runs: user
  A's burst sets `_wake` repeatedly during submission, so ticks fire
  back-to-back mid-burst, A1 is admitted in one tick and A2 in the next before
  user B has even enqueued. The `A, A, B` the test reports is the symptom; the
  defect is over-admission, and B's position is incidental to it. The fix
  shape is a persistent in-flight set on the scheduler (admitted, not yet seen
  running or terminal on disk) folded into the counts handed to
  `block_reason`, cleared on the terminal `wake()` that already exists. Check
  `futures_at_submit_time <= 1` at the same time -- if it is also failing,
  over-admission is reaching the executor rather than stopping at the cap.

- **Prose guards on invented parameters hold, but not reliably.**
  [`docs/trackers/2026-08-clearing-the-backlog.md`](trackers/2026-08-clearing-the-backlog.md)'s
  Phase 2B added "ONLY set this when the user has said..." to thirteen
  required parameters after run 1 caught the model inventing a scan
  coordinate. Run 2 measured the same probe three times: it held twice and
  failed once. B-06 t3's prompt named no atoms, and the model wrote
  `coordinate: {atoms: [1, 2], type: bond}` unasked, straight onto an
  approval card.

  EVALUATION.md predicted this ("a recurrence is a finding about the
  prose-guard approach"), so it is a result rather than a surprise: an
  instruction in a docstring is a probabilistic guard, and the parameters
  where a wrong value is silently plausible want a structural one. Note the
  same run shows the guards are not useless -- 2 of 3, and the sibling probe
  B-05 (n_states) passed all three.

## Unverified deployment surface

Resolved 2026-08-26 in
[`trackers/2026-08-clearing-the-backlog.md`](trackers/2026-08-clearing-the-backlog.md)'s
Phase 4. The public `:443` listener and its kill switch were removed rather
than verified -- the port had been commented out long enough that nothing had
ever reached it, so the controls around it were guarding a door that was not
in the wall. What multi-host operation, a real certificate and multi-operator
load would each require is now written down in `DEPLOYMENT.md` instead of
carried here as an open question.

Found and fixed in the same pass (not backlog items, noted here only so the
next pass doesn't re-discover them):

- **`cas_reco/autocas` refused the whole recommendation whenever the AVAS
  pilot space couldn't host the requested `n_states`.**
  `tests/e2e/e2e_08_job_matrix.py`'s M26 (default request: 3 states, default
  `O 2p` AVAS labels on water/STO-3G) failed live with "The AVAS pilot space
  for this molecule (6e,3o) can host at most 1 many-electron configuration(s),
  fewer than the 3 states requested." Confirmed against the real AVAS method
  (Sayfutyarova, Sun, Chan & Knizia, *JCTC* 2017) and against PySCF's own
  `avas.avas()` call site (`app/chemistry/jobs/pyscf_runner.py`): AVAS is a
  one-electron orbital-selection method with no notion of electronic states
  at all, so gating the recommendation on `n_states` was never something the
  underlying algorithm asked for. It was this app's own guard (`F-020`,
  added after a real crash) doing double duty as both a genuine crash
  preventer and an upfront refusal. Split the two: the early pilot-space
  check is now informational only (the pipeline always runs and always
  produces a recommendation and its entropy plot), and the late guard,
  reached only after the existing entropy-ranked widening already tried to
  make room. Now clamps `n_states` down to what the recommended space can
  actually host and runs the final CASSCF with that many states, instead of
  refusing outright. `summary` carries `n_states_requested` and
  `n_states_clamped_note` alongside `n_states` so the clamp is visible to the
  caller, not just the log. Verified live: the exact M26 case now succeeds,
  clamped to 1 state, `converged: True`; an unclamped request still returns
  `n_states_clamped_note: None`. M26's fixture is left as-is. It now
  regression-tests the clamp path rather than testing a dead end.

- BAGEL had no runner wired up at all for a plain HF `single_point/gs`
  energy job, despite `capabilities.py` declaring it supported. Nothing had
  run that exact combination through the full agent pipeline before this
  pass did. Fixed in commit `03ddb12`.
- `tests/e2e/e2e_00_preflight.py`'s G2a/G2b hardcoded a stale `N_CORES`
  expectation of `8`; both `docker-compose.yml` and `app/config.py`'s real
  default were already `4` and agreed with each other, unreconciled since
  Phase 3/4's fair-scheduler work. Fixed as a one-line test correction; the
  whole preflight script is 16/16 again.
