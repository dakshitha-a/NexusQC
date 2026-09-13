# P0.2, the before-snapshot

`snapshot-before.json` is the state of the deployment at the moment the fix
phase opened, taken as `qatest_admin` through the API plus a direct read of
`data/jobs/`. It is what the two-sided cleanup diff at every gate compares
against, so nothing this phase creates is left behind and nothing that was
already here is lost.

Two counts differ and the difference is the point: `GET /api/jobs` returns
**8** jobs, while `data/jobs/` holds **16** job directories. The eight extra
are the children of the batch master `186fe458ec9e`, listed under
`unowned_children_R001`. They are hidden from the list route because they
have a `parent_job_id`, and they carry no ownership row at all, which is
R-001 itself. P1.2 backfills them and this file is the list of what has to
change.
