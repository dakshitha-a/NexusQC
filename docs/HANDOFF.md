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

### Merging the CAS engine audit (2026-09-04)

43 commits sit on `worktree-cas-engine-audit`, already rebased onto the
derivative-energies work, so `main` is an ancestor of the branch and the merge
is a genuine fast-forward with nothing left to reconcile.

```bash
cd /path/to/NexusQC          # the shared checkout, NOT .claude/worktrees/...
git status                   # expect a clean tree, on main
git merge --ff-only worktree-cas-engine-audit    # the LOCAL branch
git push origin main
```

**Merge the local branch, not a remote one.** There are two remote branches and
one of them is a trap. `origin/cas-engine-audit-rebased` is the real history and
matches the local branch exactly. `origin/worktree-cas-engine-audit` holds the
*pre-rebase* commits and was deliberately left stale, because updating it would
have meant a force-push. A session that fetches and reaches for that second ref
gets the old history and `--ff-only` refuses for a reason that looks like a bug
and is not.

Once `main` is pushed, delete all three, since nothing should be left pointing
at either history:

```bash
git push origin --delete worktree-cas-engine-audit cas-engine-audit-rebased
git worktree remove .claude/worktrees/cas-engine-audit
git branch -d worktree-cas-engine-audit
```

The branch exists only because that session ran as a background job, whose
harness requires an isolated worktree before it will accept any file edit and
forbids pushing to `main`. The project's normal workflow is unchanged: sessions
work directly on `main` and there is usually no branch at all.

`--ff-only` is a safety rather than a prediction. It was already exercised once:
the derivative-energies fix landed on `main` while this work was in flight, the
fast-forward correctly refused, and the branch was replayed onto the new `main`
rather than merged. If `main` has moved *again* since this was written, do the
same thing rather than forcing or making a merge commit, because this project
keeps a linear history:

```bash
cd /path/to/NexusQC/.claude/worktrees/cas-engine-audit
git fetch origin
git rebase origin/main
```

The conflicts that rebase actually produced were all in `docs/BACKLOG.md` and
`docs/HANDOFF.md`, where two sessions add entries to the same list and the
resolution is to keep both sides. No code conflicted: the derivative-energies
changes to `pyscf_runner.py` sit in `run_gradient` and `run_nac`, this work's
sit in the CAS functions a thousand lines below, and the two changes to
`JobDetailDrawer.tsx` are hundreds of lines apart. A future fix touching
`app/chemistry/cas/`, `scripts/casbench/` or `tests/backend/cas_*` would
overlap directly and needs reading rather than resolving mechanically.

### Rebuild the frontend and the stack onto the merged commit

Required, not optional, and in this order. The merge carries both backend and
frontend changes: eight files under `app/` (`chemistry/cas/` in `diffuse.py`,
`excited.py`, `geometry.py`, `narrow.py`, `projector.py` and `refine.py`, plus
`chemistry/jobs/molden.py` and `chemistry/jobs/pyscf_runner.py`), and 188 new
lines in `frontend/src/jobs/JobDetailDrawer.tsx` that render the CAS
refinement's occupation table, orbital characters and rotation trail.

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

Once both are done, delete these two entries and the summary below, so the next
session is not sent chasing work that has already landed.

### What the CAS audit changed, in short

The CAS active-space engine was audited end to end. The headline finding is that
a recommended space could match the published size exactly and still be unable to
describe the state it was sized for: every n->pi\* state in the benchmark was
unreachable in the space recommended for it, nine of nine, while every pi->pi\*
state was spanned. The cause was the lone-pair target's hybridisation, aiming at
a carbonyl's s-rich lone pair where the excitation uses the p-like one, and it is
fixed: `geometry.LONE_PAIR_S_AMPLITUDE` is 0.20 rather than 0.577, uracil's
n->pi\* is recovered, and four other carbonyls find theirs 3 to 4 eV closer to
experiment. It costs one thing, pyrrole's ground-state tier match.

Downstream the result is coverage rather than accuracy, and it is worth stating
in those words because the two are easy to confuse. Over the sixteen states the
previous run scored, the SC-NEVPT2 error is 0.32 eV before and after, unchanged.
What moved is that eighteen states are now scored rather than sixteen and eleven
of twelve molecules converge rather than ten.

`docs/casbench/hole-capture.md` has the measurement and the sweep behind the
value, `docs/CAS_ENGINE_METHOD.md` section 10.9 has the write-up,
`docs/TRACKER.md` carries the remaining steps, and `docs/BACKLOG.md` carries
what was found and not fixed. The live entries there are
`MINIMAL_ENTROPY_GAP`, which is measured and not yet applied, twisted ethylene's
irreproducible recommendation, and the state audit's unreliability on large
planar spaces.
