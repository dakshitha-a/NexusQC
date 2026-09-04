# Derivative energies, batch aggregation and the plotter

An analysis of the "Ethylene NAC" conversation and what was changed because
of it. Written as a record of *why*, in the same spirit as
[`ARCHITECTURE.md`](ARCHITECTURE.md): every item below is a real failure a
user hit in one sitting, not a hypothetical.

## The session, in order

The user pasted nineteen ethylene geometries titled "Torsion angle at 0",
"... at 10" and so on, and asked for CAS(2,2)/cc-pVTZ non-adiabatic
couplings between all three pairs of states, as one batch.

What followed, step by step:

1. The agent tried to build a geometry set as a job and was told to make
   the user upload a file. The coordinates were already in the message it
   was answering. The user uploaded the file.
2. The NAC batch ran, all nineteen images, no failures.
3. The user asked to plot the state energies against the dihedral angle.
   The batch reported couplings and no energies, so the agent said the
   energies were not there and offered to run a second batch.
4. The user pointed out the plot's x axis was image number, not torsion
   angle. Four exchanges followed. The agent explained the mapping, tried
   relabelling the axis twice, and finally told the user to plot it in
   matplotlib. The user wrote "do what i aske".
5. The user pasted the numbers as a table and asked for a plot of those.
   Refused: the plotter only draws data a job produced.
6. A second batch (excited states) ran. Its plot failed outright with
   "'coordinate_values' is a list ... add an index", a message describing
   a spec the agent had not written. The agent concluded the plotter could
   not handle the data layout and handed over another matplotlib snippet.
7. The user asked for absolute energies. The excited-states batch reports
   excitation energies only, so a third batch (single points) was run.
8. The third batch aggregated **nothing**: nineteen of nineteen complete,
   no numbers at all. The agent said it had "no way to list or read child
   job IDs from here" and offered a fourth run.
9. A fourth batch, on BAGEL, did the same. The user attached the job to
   the prompt, which is the app's own mechanism for putting a job's
   results in front of the model, and asked again. Same answer.

Four batches, seventy-six child jobs, and the number the user asked for on
turn three had been sitting on disk since turn two.

## Root causes

### 1. A coupling or gradient job threw its state energies away

Every NAC and gradient path on all three engines solves the electronic
structure problem first and differentiates it second. The energies exist by
construction. `derivatives.py` did not collect them, so a PySCF SA-CASSCF
NAC job reported three couplings and `energy_gaps_eV: [null, null, null]`
beside a converged state-averaged wavefunction that knew all three gaps.

`gradient_result` had a related, quieter bug: it wrote the energies of the
*requested* gradients under the name `state_energies_hartree`, which
everywhere else in the app means the full ladder. A gradient taken on S2
alone therefore read back as a one-state job whose total energy was S2's.

**Fixed.** Both result shapes now carry `state_energies_hartree` (absolute,
ground state first) and `excitation_energies_eV`, from every engine and
every method whose capability row claims `nac` or `gradient`. Where an
engine prints no gap of its own, each pair's `energy_gap_eV` is derived
from that ladder. The aligned per-gradient view kept its meaning under the
new name `gradient_state_energies_hartree`.

### 2. A batch of single points aggregated nothing

`batch_aggregate._SERIES_BUILDER` had entries for `nac`, `gradient` and
`excited_states` and none for `single_point`. A batch of single points
therefore produced completion counts and stopped, which is what steps 8 and
9 above ran into twice.

**Fixed.** `single_point` aggregates the state ladder, which is its
headline quantity. The other three now report the absolute ladder as
`state_energies_hartree` beside their own series -- deliberately beside and
not inside `series`, because `render_line_plot` draws every entry of that
dict on one axis and hartree does not share an axis with Eh/Bohr.

### 3. The batch x axis ignored a coordinate the user had supplied

A batch over a `pes_1d` scan inherits that scan's coordinate. A batch over
an uploaded geometry set had nothing to inherit and fell back to a 1-based
image index -- honest, but not what the user typed. The titles
"Torsion angle at 0 ... at 180" were parsed, stored in the geometry set's
own summary as `frame_names`, and then never used for anything.

**Fixed.** `geometry_resolve.coordinate_from_frame_names` reads a
coordinate out of frame titles when, and only when, every title holds
exactly one number, removing that number leaves identical text in all of
them, and the numbers are all different. Anything else falls back to the
image index as before. The ethylene set now plots against "Torsion angle"
from 0 to 180.

### 4. The plotter silently ignored `job_id`

`plot(kind="custom", job_id=..., ...)` dropped the singular argument.
Every other kind takes `job_id`; only `custom` needed `job_ids`. The
ignored id fell through to every job in the conversation, which flips the
plot from "rows are positions in one job's arrays" to "rows are jobs" the
moment a second job exists. That is exactly why step 6 failed while the
identical spec had worked in step 3: one job was active then, two were
active later.

**Fixed.** Both spellings reach the spec.

### 5. There was no way to put points on an axis the job did not store

Steps 4 and 5 were a real capability gap, not a misunderstanding.

**Fixed**, narrowly: `spec["x_values"]` places points at coordinates the
caller states, one per point, length checked exactly. It positions points
only. y values still come from a job, so the rule that a plot never draws
numbers no calculation produced is untouched.

### 6. A master job's children were invisible to the agent

`children.jsonl`, `sub_job_ids_of`, the `/api/jobs/{id}/children` route and
the drawer's child list all existed. Nothing ever told the model the
children were there or that `check_job_status` would read one. This is the
"I can see them in the job drawer and the agent cannot" complaint exactly:
attaching the job to the prompt handed over the master's summary and
nothing else.

**Fixed.** A completed master's context now lists its child job ids with
their coordinate labels, and says how to read them singly or as a table
across all of them. Capped at forty ids; past that the first and last are
named with the count.

### 7. Pasted geometries were not accepted

`parse_multi_frame_xyz` reads a file and holds it to the xmol convention:
atom-count line, comment line, that many atom lines. What people paste into
chat is a title and a run of coordinates, repeated, with no counts.
Nothing could read that, so the only answer available was "please upload a
file", about coordinates already on screen.

**Fixed.** `geometry_upload.parse_pasted_multi_geometry` tries the strict
parser first and otherwise walks the text leniently: each maximal run of
atom lines is a geometry, and the last non-blank line above it is its
title. `set_geometry` turns three or more of them into a geometry set job
and returns its id, matching the upload rules exactly (one is the active
molecule, two are path endpoints, three or more are a set). The titles
survive, so a pasted torsion scan gets its own axis by way of item 3.

### 8. Four batches shared one name

`auto_job_name` builds a master's name from `spec.molecule`, which for a
batch is an arbitrary member of the set -- carrying that image's title. All
four batches were called "Torsion angle at 0 Batch CASSCF(2,2)/cc-pvtz",
differing only in engine, and `resolve_job_label` is the single definition
of a job's name, so the collision was shared by the job list, the drawer,
the submission confirmation and every download filename.

**Fixed.** A batch is named by formula, and by what it ran on each
geometry: "C2H4 Batch NAC CASSCF(2,2)/cc-pvtz (PYSCF)" against
"C2H4 Batch Excited states ..." against "C2H4 Batch SP ...".

## One thing the fix broke on its way in

Worth recording, because it is the kind of interaction that only shows up
once two correct-looking rules meet.

`facts.canonicalize` re-indexes the per-excited-state arrays so entry `i`
always describes state `i+1`, using `n_states_total` and `n_excited_states`
derived from the state ladder. A coupling result had no ladder, so both
were `None` and the alignment never fired. Giving it a ladder gave that
code the two numbers it needed to do the wrong thing: `oscillator_strengths`
on a coupling job holds one entry per state PAIR, not per state, and for
three states and three pairs the length test passes by coincidence. A
three-pair PySCF job came out with three couplings and two intensities.

`canonicalize` now skips that whole block for a result carrying
`couplings`, and `frontend/src/jobs/excitedState.ts` makes the same call for
the same array, since a coupling job's states now render in the drawer's
excited-state table. Both places name the reason rather than the symptom.
The lesson is narrower than "be careful": one field name means two
different shapes depending on the job, and every reader of it has to know
which.

## Two things worth recording that are not code defects

The "multiply the x axis by 100" exchange started with the app's own first
plot, which set `xlim: [0, 190]` over x values running 1 to 19. The curve
was squeezed into the left tenth of the frame, which is exactly what a
fractional axis looks like. The user's reading of it was reasonable; the
plot was misleading.

The agent handed over matplotlib snippets five times. Each was correct and
each was the app declining to do its own job. A snippet is a reasonable
last resort and a bad habit: it should follow a real attempt, not replace
one.

## Decisions left open

**Literal data plotting.** The plotter refuses to draw numbers pasted into
the conversation, by design -- it is an anti-fabrication rule, and it is
what stops a model drawing a chart of remembered or invented values. The
fixes above mean the ethylene request no longer needs it: the numbers are
in a job and the axis can be stated. But the refusal in step 5 will
reappear for any figure whose data genuinely came from elsewhere (a
literature comparison, a measurement). Widening it is a real decision with
a real cost, so it is left here rather than taken quietly.

**Size of the aggregate.** `state_energies_hartree` on a master is one list
per state, one entry per image. For a 500-sample Wigner ensemble that is a
lot of renderable numbers in the model's context. `series` already had this
property, so nothing new is introduced, but if aggregates ever need
bounding, both keys should be bounded together and by the same rule.

**BAGEL and ORCA gradient ladders on a hand-edited input.** A blind or
hand-edited engine input can describe a calculation whose printed energies
this cannot interpret. The ladder parsers are deliberately lenient there:
an unreadable energy line leaves a `null` in the ladder rather than failing
a job whose gradient parsed correctly.
