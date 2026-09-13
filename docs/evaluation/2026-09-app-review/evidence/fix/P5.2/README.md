# P5.2, the account, quota and admin findings

Nine findings close here: R-044, R-045, R-046, R-052, R-082, R-083, R-087,
R-088 and R-089. The regression test is
`tests/backend/sec_16_account_hardening.py`, one script for all nine, because
they are one cluster: each is a promise the app makes about an account's own
data that the code was not keeping.

## What the script checks, and how

Thirty checks. They are of two kinds, and the split matters for reading the
logs.

Twenty-four are **in-process structural checks**. They import the module under
test inside the api container and assert on what the code actually does: that
`app/auth/storage_quota.py`'s three per-user passes each measure the category
they enforce against, that `server/routes/shares.py` takes a per-recipient lock
around the check-and-copy, that `download_my_data` writes `conversations/`,
`plots/` and `projects/` members into the zip, that `purge_own_data` deletes
plots and project archives and still leaves threads alone, and so on. These
answer "is the mechanism there", and they can be checked without the stack
carrying the fix, which is why the before-run reports on all of them.

Six are **live route checks** against the running deployment: two invite
`ttl_hours` bounds, three `PATCH /api/admin/bug-reports/{id}` behaviours, and
the bug-report rate limit, which files fifteen reports as a fresh account and
counts how many are refused. A route check can only ever describe the code the
stack is running, so these are the six that had to be taken before the update
and again after it.

## Before

`before.log`, taken against the stack on `f6d12c5`, which is the code as it
stood before this step: **24 of 30 checks passed, and the six that failed are
exactly the six route checks**.

- a five-year invite was accepted, HTTP 200 (R-089)
- a zero-hour invite was accepted, HTTP 200 (R-089)
- `PATCH` on a well-formed id for a report that does not exist answered 200 and
  returned a body describing it as closed (R-082)
- `PATCH` on a malformed id answered 500, which tells a prober their input got
  further than a well-formed miss would (R-082)
- one audit row was written saying a report that does not exist had been
  changed, in a log documented as append-only and therefore obliged to be true
  (R-082)
- fifteen bug reports filed in a row from one account were all accepted, none
  refused, against a budget that is meant to be twelve an hour (R-052)

The twenty-four structural checks passed on the before-run because the commit
that carries the fixes, `5d16dfe`, was already in the tree when the log was
taken; what it was not yet in was the container. That is the shape rule 1 of
the plan describes for a route test, and the six failures above are the honest
before-state.

## After

The after-log is the gate's own run of the same script, in `P6.2`, taken once
`scripts/update.sh` has put `5d16dfe` and everything after it into the api
image. All thirty checks pass there or the step does not close.

One note for anyone re-running the rate-limit section on its own: the budget is
keyed on the account, not the address, so a second run inside the same hour
with the same account would see the first run's fifteen reports. It does not
arise here because the script registers a fresh account each run, and because
`fixtures.admin_client()` clears every `qc_agent:ratelimit:*` key before it logs
in, which includes this bucket.
