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
