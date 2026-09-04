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
