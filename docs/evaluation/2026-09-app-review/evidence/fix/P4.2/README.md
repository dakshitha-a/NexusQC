# P4.2, R-099: the refinement drawer's empty occupation table

R-099 recorded that `tests/frontend/cas_14_refinement_drawer.spec.mjs` came
back 13 of 17, with the natural-orbital occupation table showing zero data
rows, and left the cause open between "the refinement published an empty
summary" and "the section is gated on a key the runner never writes". The
register's own pointer favoured the second: a comment in
`JobDetailDrawer.tsx` warns that `RefineResult` names its fields
`refined_active_*` while the runner publishes the refined size under the
recommendation's keys.

Neither was it. The app is correct, the data was always there, and the finding
was the spec asserting before the drawer had painted.

## What the repro said

`cas_14-before.log` is the register's repro as written, run against the stack
carrying every fix through Phase 5: **17 of 17**, with four occupation rows,
each carrying its natural occupation, a character label and the continuous
weights beside the label, and a two-row rotation trail. Nothing failed.

A run that passes is not a diagnosis, so two things were checked before
calling it not reproduced.

**The runner cannot publish what the review described.** The refinement
summary is assembled key by key in `pyscf_runner.py`, and
`natural_occupations`, `quick_active_orbitals` and `rotations` are all written
unconditionally from the same `RefineResult`, which is constructed at exactly
one place with `occupations` taken from `state_averaged_occupations(mc)`, one
number per active orbital. There is no path that produces a summary with the
rotation trail present and the occupations absent. Both keys were already
being written at `ca7e0ff`, the commit the review ran against, and the spec
itself has not changed since. So the review's own combination, rotations
rendering while the occupation table rendered nothing, cannot come from the
data.

**A variation with a different state count.** `variation-n_states-2.log` seeds
a recommendation and a refinement with `n_states=2` rather than 1, driving the
state-averaged path rather than the single-root one, and reads the completed
refinement's summary directly rather than through the browser.

## Where it actually came from

`JobDetailDrawer` renders its `Dialog.Content` unconditionally and puts
`Loading...` inside it until `useJobQuery` resolves. So `[role="dialog"]`
appears the instant the row is clicked, before the job has been fetched, and
the spec's only wait was on that selector. Every assertion after it raced a
network request. The four checks the review saw fail are the first four content
checks in the file; everything checked later passed, which is the signature of
a drawer that filled in partway through the assertions rather than one missing
a summary key.

The spec now waits for the drawer to have painted its job, not merely for the
dialog element to exist, through a `drawerLoaded` helper that watches for the
loading text to clear.

## The positive control

Showing the spec passes with a wait added does not show the review's reading is
what a slow fetch produces, so `cas_14` gained a section that measures it. It
opens the drawer on a page where the job's own request is held for three
seconds by a Playwright route handler, and takes two readings:

- the instant `[role="dialog"]` appears: refined-space line absent, zero
  occupation tables, zero rotation tables
- after `drawerLoaded`: refined-space line present, four occupation rows

`cas_14-after.log` is that run, **19 of 19**. Nothing about the app is changed
between the two readings; only the arrival time of a response the app was
always waiting for. The first reading is R-099 exactly: an assertion fired
there reads a loading drawer as an app that published no data.

So R-099 closes as a harness defect with a regression test that fails on the
old harness by construction. The one thing it did leave behind that was worth
having is the wait: a spec that treats "the dialog exists" and "the job has
arrived" as one event will drift back into this on any slower host, and the
helper is used everywhere this spec opens a drawer so it cannot come back one
assertion at a time.
