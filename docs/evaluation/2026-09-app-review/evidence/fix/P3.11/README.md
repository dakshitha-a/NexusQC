# P3.11, R-101

The regression test is `tests/backend/agent_02_draft_flow.py`, extended with
one assertion: **a complete draft raises the approval card by itself**. That
assertion is what would have caught the finding, and it is in the existing
drafting script rather than a new one because the rest of that script is the
drafting contract this changes.

`agent_02-before.log` is the script against the code as it was; the new
assertion fails there and the reply-text assertions pass. `agent_02-after.log`
is 36 of 36 after, with the ready-reply assertions now driven with
`preview_only=True`, which is the path that reply is now for.

The k/N that measured the finding is an end-to-end number and belongs to the
Phase 3 gate: `tests/e2e/e2e_19_wigner_ensemble.py`, which failed 0 of 3
across the harness's own retries, and the excited-state and BAGEL cells of
`e2e_08_job_matrix.py`. The gate's own run records it.
