# P5.6, R-100: three e2e specs that failed on working panels

Committed as `5e3163a`. No before/after log pair of its own, because the
"before" is the review's own e2e and e2e-UI runs, recorded in
`docs/evaluation/2026-09-app-review/baseline.md`, and the "after" is the Gate 3
run of the same suites. Nothing in the application changed in this step; all
three failures were the harness describing an app that no longer exists.

## R-100: `/api/version` and `/api/health/deep`

`tests/e2e/e2e_03_route_auth_sweep.py` walks every route and expects a 401 for
anything not in `PUBLIC_ROUTES`. `GET /api/version` has always been public and
`GET /api/health/deep` was added in Phase 2 of this fix run (it is what
`update.sh` now calls to decide a deployment is healthy, since the old check
proved only that uvicorn was answering). Both are in the set.

## `ui_03_molecule_kb`: the knowledge-base search box

The spec looked for `input[placeholder="Search sources..."]` and reported "KB
search input present: not found". The field moved behind a magnifier toggle
(`SearchToggle` in `frontend/src/app-shell/SearchField.tsx`) and is not in the
DOM until that toggle is clicked. Every panel with a search field follows the
same `<testId>-open` toggle plus `<testId>` input pattern, which is now written
down in `tests/README.md` so the next panel's spec is written the right way
round.

## `ui_04_admin_visual`: a heading that was removed

The overview pane's expected headings still listed "Public web access". That
control is gone from the console; the pane owns only the storage quota and
concurrency block. While there, the "Deployment" section was added to the
checked set: it was added to the admin nav after this spec was written and had
no coverage at all, which is the same class of drift in the other direction.
