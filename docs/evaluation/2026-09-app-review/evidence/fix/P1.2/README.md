# P1.2, R-001 and R-090

`R-001-before.log` is the regression test run against the deployment as it
stood before the fix reached it: **11 of 35 checks passed**. The eleven are
the in-process half, which exercises the working tree and therefore already
carries the fix, plus the two source-level checks. The twenty-four failures
are the live half, and they are the finding itself: eight children of the
batch master `186fe458ec9e` each served their full job record, their
16 KB artifact download, and accepted a rename, to an account minutes old
that owned nothing, while the master itself correctly returned 404 to the
same session.

`R-001-after.log` is the same script once `update.sh` has put the deployment
on the fixed code, at the Phase 1 gate. See the tracker's rule 2 for why the
two halves are timed differently: only nginx publishes a host port, so there
is no working-tree route server to test against, and a route test can only
turn green after a rebuild.

The write probe restores what it changes. The first run of it renamed eight
of the deployment's real jobs before that was added; the labels were put back
by clearing the `label` override from each `meta.json`, which is what the
rename route writes, and the app then derives the original name from the spec
again.
