# Handoff

Work that finished in a session but still needs a person, or a machine, to
do something before it is really done. A session cannot see the previous
session's conversation, so anything left half-landed has to be written here
or it is lost.

Delete an entry once it is done. An empty "Open" section is the normal
state of this file.

## Open

### Re-aggregating the four ethylene batches (2026-09-04, optional)

The derivative-energies work is merged, pushed and deployed; see
[`DERIVATIVE_ENERGIES_AND_PLOTTING.md`](DERIVATIVE_ENERGIES_AND_PLOTTING.md)
for what changed and why. One loose end is left, and it is a judgement call
rather than a task.

A batch's aggregate is computed once, when its last child finishes, and
written into the master's `result.json`. Nothing recomputes it. So the four
masters from the "Ethylene NAC" conversation keep the thin summaries they
were given at the time, even though the code that would produce better ones
is now running. Their children are unchanged on disk, so three of them can
be re-derived without rerunning a single calculation:

| master | what re-aggregating would recover |
|---|---|
| `796d24996e0d` (excited states, PySCF) | absolute state energies, torsion-angle axis |
| `28cd1d2493d6` (energies, PySCF) | the whole aggregate; it has none at all today |
| `271b7ea270e3` (energies, BAGEL) | the whole aggregate; it has none at all today |
| `09aafad807b9` (couplings, PySCF) | the torsion-angle axis, and nothing else |

`09aafad807b9` cannot gain state energies by any amount of re-aggregation:
its children ran before the runner change and never recorded them. Only
rerunning that batch would give it those.

Doing it is about forty lines and no new machinery. For each master, call
`batch_aggregate.aggregate(job_id, read_spec(job_id), sub_job_ids_of(job_id),
n, job_dir)` and merge the returned summary and artifacts into the master's
`result.json`. It rewrites a user's existing job results, which is why it
was not done unasked.

### 1. Fast-forward `worktree-cas-engine-audit` into `main`

Queued 2026-09-04 by the CAS engine audit session. That session ran as a
background job, whose harness requires an isolated worktree before it will
accept any file edit and forbids pushing to `main` or merging, so it could not
land its own work. The project's normal workflow is unchanged: sessions work
directly on `main` and there is usually no branch at all. This branch exists
only because of how that job was launched.

The branch is many commits ahead of `main` and 0 behind, so this is a genuine
fast-forward with nothing to reconcile. Ask the repository for the current
count rather than trusting a number written here, because a count in a document
goes stale the next time anyone commits.

```bash
cd /path/to/NexusQC          # the shared checkout, NOT .claude/worktrees/...
git status                   # expect a clean tree, on main
git merge --ff-only worktree-cas-engine-audit
git push origin main
```

`--ff-only` is the safety. If `main` has moved since this was queued it refuses
rather than quietly making a merge commit, and the right response is to say so
rather than to force it.

### 2. Rebuild the frontend and the stack onto the merged commit

Required, not optional, and in this order. The merge carries both backend and
frontend changes: seven files under `app/`, and 188 new lines in
`frontend/src/jobs/JobDetailDrawer.tsx` that render the CAS refinement's
occupation table, orbital characters and rotation trail.

```bash
conda activate node24
cd frontend && npm run build     # nginx serves frontend/dist from a host bind
                                 # mount, so `docker compose build` will NOT
                                 # refresh it
cd .. && docker compose up -d --build
```

Skipping `npm run build` leaves the refinement drawer absent from the running
stack even though its code is merged, which looks exactly like the feature not
working.

### 3. Then clear this section

Reset "Outstanding" to read *nothing outstanding* and commit it, so the next
session is not sent chasing work that is already done.

---

## What was handed over, in one paragraph

The CAS active-space engine was audited end to end. The headline finding is that
a recommended space could match the published size exactly and still be unable to
describe the state it was sized for: every n->pi\* state in the benchmark was
unreachable in the space recommended for it, nine of nine, while every pi->pi\*
state was spanned. The cause was the lone-pair target's hybridisation, aiming at
a carbonyl's s-rich lone pair where the excitation uses the p-like one, and it is
fixed: `geometry.LONE_PAIR_S_AMPLITUDE` is 0.20 rather than 0.577, uracil's
n->pi\* is recovered, and four other carbonyls find theirs 3 to 4 eV closer to
experiment. It costs one thing, pyrrole's ground-state tier match, which no
choice of amplitude avoids.

`docs/casbench/hole-capture.md` has the measurement and the sweep behind the
value, `docs/CAS_ENGINE_METHOD.md` section 10.9 has the write-up,
`docs/TRACKER.md` carries the remaining steps, and `docs/BACKLOG.md` carries
what was found and not fixed, of which the live one is *p*-benzoquinone, whose
n->pi\* is still not recovered.
