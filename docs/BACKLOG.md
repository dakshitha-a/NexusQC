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

- **Something in the app roughly doubles the model server's concurrency
  penalty.** Measured rather than assumed: four concurrent streaming requests
  of realistic prompt size, straight at the model endpoint with none of this
  app in the way, give a time-to-first-token of 2.12x the single-user median
  (2.83x worst). The same concurrency through the app measures 5.04x. The
  connection pool is not it (max_size 20) and the per-conversation lock is not
  it (four different conversations). The SSE path and anything rebuilt per
  turn are where to look. `perf_02_ttft_and_concurrency` now measures the
  server's own penalty in the same run and fails on what the app adds to it,
  so this has a number attached rather than a shrug.

  Note this corrects two earlier records, one of them mine, that put perf_02's
  failure down to GPU contention from other tenants. The host is inside
  budget. We are not.
