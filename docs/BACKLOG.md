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

- **`perf_02_ttft_and_concurrency` fails on an idle app stack too.** An
  earlier session left this "unconfirmed either way rather than dismissed"
  because it had not been re-run in isolation. It has been now: 5.04x
  time-to-first-token against a 3x budget with the stack otherwise empty, and
  four concurrent turns finishing no faster than four serial ones (16.3s vs
  15s). That rules out suite interference and leaves GPU contention from other
  tenants as the remaining explanation, which is plausible on this host but is
  still an assumption rather than a measurement. Measuring it needs a look at
  what else is on the GPUs at the time.

- **A deleted job can leave an orphaned directory nothing will clean.**
  After the suite run, `data/jobs/5659f1c341af/` held a single
  `orbitals.molden` and no `spec.json`. `base._iter_job_ids_on_disk` treats a
  missing `spec.json` as "not a job", so the directory is invisible to the job
  list, to the quota accounting and to `delete_job_dir` -- it had to be removed
  by hand. Most likely a runner wrote the molden after the job was deleted.
  Harmless individually, unbounded over time.

- **Backend test scripts leak their conversations.** The suite has
  `zz_99_job_cleanup.py` for jobs and it works, but scripts that open threads
  through `thread_registry.create_thread` never delete them: this run left four
  `qatest_*` conversations behind. A thread-cleanup counterpart to zz_99 would
  close it.

- **The Gaussian broadening arithmetic exists in three copies.** Server-side
  in `app/chemistry/spectrum.py`, and again in the browser in
  `UvVisSpectrumInline.tsx` and, separately, `IrSpectrumInline.tsx`. The
  client copies exist for a good reason (they work retroactively on every
  already-completed job with no backend call) but three implementations of
  one formula will drift, and a spectrum that disagrees with its own PNG is
  exactly the kind of bug nobody reports.

- **Three renderers write job artifacts that never register as plots.**
  `render_neb_plot` (`neb_plot`), `render_entropy_plateau_plot` (cas_reco) and
  `render_pes_plot` for `pes_1d` -- only `interp_pes` is registered by
  `app/plots/intrinsic.py`. They are therefore unversioned, uneditable and
  unattachable, which is now the only remaining gap in "every plot is a saved
  object you can restyle".

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
  Re-confirmed on this host after two rebuilds during the retrieval work:
  both used a plain `docker compose up -d --build`, so `GIT_COMMIT` in the
  running api container is unset and `frontend/dist/.build-commit` does not
  exist. The deployment is running main, it just cannot say so.

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

## Closed by measuring

- **The fair scheduler was never broken; `perf_04` was measuring the wrong
  event.** Settled by wrapping the live scheduler's `_on_admit` and running
  perf_04's exact scenario against the deployment, recording both observables
  at once: the true admission order was `A, B, A, A, A, A, A` -- correct
  round-robin -- while the test's `status.json` proxy read it as
  `B, A, A, A, A, A, A`, and as `A, A, B, A, A, A, A` on an earlier run.
  Admission and "running" are different events; `_dispatch_tick` returns
  immediately and the status write happens later on a pool thread, so polling
  it every 0.3s while scanning A's ids before B's manufactured the failure.
  perf_04 reads the admission hook now and passes 6/6. Three sessions in a row
  had recorded this as a scheduler fault, one of them calling it a regression
  of a shipped fix.

- **perf_04 could silently leave the whole deployment capped at one job.** Its
  `finally` restored `max_concurrent_jobs_total` with an `admin.patch` whose
  status nobody checked, so a restore that did not land left the stack
  throttled with nothing said. That is not hypothetical: this host was found in
  exactly that state, discovered only because an unrelated probe happened to
  read the config. The restore is checked and read back now, and reported as a
  named failing check.

## Closed without doing, and why

Two of the three tool consolidations this backlog listed do not survive a
closer look, recorded here so nobody re-proposes them from the token numbers
alone.

- **`convert_energy_units` is not a duplicate.** It converts arbitrary values
  -- "that absorption is at 480 nm, what is that in eV" -- which never came
  from a job at all. Folding it into the job-fields path would have covered
  only the job-sourced case and quietly removed the other, leaving the model
  to do the arithmetic itself, which is exactly what its docstring exists to
  forbid. 371 tokens is not worth that.
- **`list_ensemble_geometries_in_window` is not expressible as a field path.**
  It pools transitions across a wigner_ensemble master's sub-jobs and filters
  them on four AND-ed predicates. A field path selects from one job's stored
  summary; it computes nothing and crosses no job boundary. The backlog entry
  claiming otherwise was written from the tool's size, not its body.

The third was done: the two active-space tools are one `active_space` tool
whose mode follows from whether a space is supplied.

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
