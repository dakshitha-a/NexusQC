# Closed Tracker: what the agent can find out, and what it does when it cannot

Three follow-ups from the conversation that produced the context-window fix
(`trackers/2026-08-context-window-budget.md`). None of them is that bug; all
three were found while reading the transcript and the test suite around it.
Opened and closed 2026-08-24.

## The three

**A capability answer did not name the parameters a draft accepts.** Asked to
seed a CASSCF from a completed job's orbitals, the agent looked at its draft,
found no field for it, and told the user: *"I don't see a field in this draft
for seeding the CASSCF initial orbitals ... tell me and I'll check whether this
deployment supports that."* `initial_orbitals_job_id` had existed all along. The
user had to re-ask, and the agent then guessed `initial_orbitals_source_job_id`
and needed `update_job_draft` to reject it before it learned the real name,
because that rejection was the only place the names were ever printed. Two turns
lost, in the same conversation the user reported. Making the error path the only
documentation means being wrong once, in front of the user, is a precondition
for being right.

**`agent_04_old_thread_resume` was green on a laptop and red where it runs.**
15/15 on a host with no `QC_AGENT_DATABASE_URL`, 7/14 in the container. Its
`open_fixture()` pinned the checkpointer by assigning `graph_mod.CHECKPOINT_DB`,
which was sufficient when SqliteSaver was the only backend and silently stopped
being sufficient when the deployment set `DATABASE_URL`: `_get_checkpointer()`
tests that first and hands back a PostgresSaver, so the fixture's thread was
looked up in Postgres, found missing, and every path below resumed an empty
conversation. `CLAUDE.md` says this suite needs the full compose stack, so the
suite had a permanent false red exactly where it is meant to be run, which is
how people learn to ignore red.

**An empty conversation reached the model and came back a 500.** That false red
was reported as `500 no user query found in messages`, and the reason is worth
keeping after the test is fixed: a system prompt with nothing after it is not a
request Qwen's template will render. It is reachable outside the test whenever a
turn runs against a conversation whose stored state is gone, the clearest case
being an approval card still open in a tab after its thread is deleted.

Folded in with the third: the phantom-continuation cleanup now says when it
erases a stopped turn's output. The erasure is right and stays, but it deletes
work, and a conversation it has touched shows a tool result with no reply after
it and no record anywhere of why. Explaining one such gap after the fact took
real digging during the previous plan.

## How tracking works here

Development is linear, so there is never a reason to have two trackers open
at once. Each plan, feature or non-trivial request gets its own tracker, this
file is whichever one is currently in motion, and when its plan is finished
the file is closed out and moved to [`trackers/`](trackers/), then a fresh one
starts here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path:

- [`trackers/2026-08-job-system-overhaul.md`](trackers/2026-08-job-system-overhaul.md)
  the 10-phase job-type/toolchain/agent overhaul. Closed 2026-08-22, 72 steps
  across 5 merged phases.
- [`trackers/2026-08-plots-as-objects.md`](trackers/2026-08-plots-as-objects.md)
  plots as first-class objects: a real chart spec, saved plot records with
  versions, conversational editing, and the Plots panel. Closed 2026-08-22,
  20 steps across 4 merged phases.
- [`trackers/2026-08-excited-state-scans.md`](trackers/2026-08-excited-state-scans.md)
  excited states at every point of a scan or interpolated path, for any method
  and any scan mode, plus the two latent bugs that surfaced underneath it.
  Closed 2026-08-23, 9 steps across 2 merged phases.
- [`trackers/2026-08-scheduler-fairness.md`](trackers/2026-08-scheduler-fairness.md)
  the concurrency cap that bounded admissions per dispatcher tick rather than
  in total, and the rotation pointer that advanced on refused attempts and so
  handed every freed slot back to whoever sat first. Closed 2026-08-23, 5 steps
  across 2 merged phases.
- [`trackers/2026-08-test-job-cleanup.md`](trackers/2026-08-test-job-cleanup.md)
  the suite removing the jobs it creates instead of leaving them in everyone's
  job list. Closed 2026-08-23, 4 steps in 1 merged phase.
- [`trackers/2026-08-frontend-visual-fixes.md`](trackers/2026-08-frontend-visual-fixes.md)
  a long job name pushing the row's stop and delete buttons out of view, viewer
  controls floating over the wrong thing, and orbital isosurfaces corrugated by
  their own cube grid. Closed 2026-08-24, 9 steps across 3 merged phases.
- [`trackers/2026-08-wigner-oscillator-strength.md`](trackers/2026-08-wigner-oscillator-strength.md)
  making oscillator strengths a hard requirement for a nuclear-ensemble
  spectrum, so routing picks an engine that can actually supply them, and
  normalizing the live broadening preview to match the finished figure's
  scale. Closed 2026-08-24, 5 steps across 2 merged phases.

- [`trackers/2026-08-preview-pane-and-attached-geometries.md`](trackers/2026-08-preview-pane-and-attached-geometries.md)
  the job drawer showing a job's product in the preview pane rather than behind
  a click or under an overlay, the geometries of an attached job travelling with
  it so a new job can start from one named image of a path, and one shared
  energy-unit conversion for the agent and the plots. Closed 2026-08-24, 8 steps
  across 4 merged phases.

- [`trackers/2026-08-spectra-travel-with-the-job.md`](trackers/2026-08-spectra-travel-with-the-job.md)
  a tagged spectrum job carrying its own broadened curve instead of only the
  sticks behind it, and a plot kind that puts several methods' spectra on one
  shared axis. Closed 2026-08-24, 3 steps across 2 merged phases.

- [`trackers/2026-08-equilibrium-marker-on-distributions.md`](trackers/2026-08-equilibrium-marker-on-distributions.md)
  a Wigner ensemble's geometry-parameter histograms marking the structure the
  samples were displaced around, and the rule for which geometry that is moving
  into one function instead of three copies. Closed 2026-08-24, 2 steps across
  2 merged phases.

- [`trackers/2026-08-job-row-click-target.md`](trackers/2026-08-job-row-click-target.md)
  the job's name being the one part of a Job Manager row that did not open its
  preview, which read as the app being slow to answer, and an open preview
  being unmounted by a single failed poll of the list behind it. Closed
  2026-08-24, 4 steps across 2 merged phases.

- [`trackers/2026-08-bagel-blind-input.md`](trackers/2026-08-bagel-blind-input.md)
  a pasted BAGEL CASSCF input described as the Hartree-Fock section it starts
  from, the orbital file a verbatim run asked the engine to write being deleted
  before anyone could download it, and the same sweep quietly leaving BAGEL
  orbital reuse with no source to reuse. Closed 2026-08-24, 12 steps across 4
  merged phases.

- [`trackers/2026-08-named-active-space.md`](trackers/2026-08-named-active-space.md)
  naming which orbitals form a CASSCF active space instead of only how many,
  through BAGEL's `active` keyword and PySCF's `sort_mo`, and the rule that the
  list is only ever set when the user names the orbitals themselves. Closed
  2026-08-24, 6 steps across 2 merged phases.

- [`trackers/2026-08-ci-reference-determinant.md`](trackers/2026-08-ci-reference-determinant.md)
  dominant transitions measured from an excited state's own leading
  configuration, because the reference was chosen after an open-shell singlet's
  two spin partners had been summed and a closed-shell determinant's had not.
  Closed 2026-08-24, 3 steps in 1 merged phase.

- [`trackers/2026-08-context-window-budget.md`](trackers/2026-08-context-window-budget.md)
  replies cut off mid-sentence before they could raise a job-approval card,
  because history was bounded by message count while the prompt was measured in
  tokens, the declared context window was half the real one, and an attached
  job's results were re-sent in full on every turn. Closed 2026-08-24, 4 steps
  in 1 merged phase.

Closing one out means: every step `done` with evidence, a `merged:` row on each
phase, `scripts/check_tracker.py` passing, then `git mv` into `trackers/` and a
new file here. Only the active tracker is machine-checked; an archived one
records what was true when it closed and is not re-verified, since the scripts
its evidence names may legitimately have been deleted since.

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as, and it
  must be a bare hash; the checker rejects anything else.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Phase 1: Discoverable parameters, and honest failures where there is nothing to say

- [done] P1.1: A capability answer lists the parameters its task's draft accepts
  evidence: tests/backend/agent_06_capability_params_and_guards.py → "capability_answer for single_point/ee now carries all 16 registry parameters including initial_orbitals_job_id and active_space_orbital_indices, with the help text rather than the label so the 'SAME engine' constraint travels with it, and the same list comes back when the question omits the engine or the method; the whole answer is 3,122 characters, roughly 1,040 tokens, and the tool docstring that grew with it keeps the fixed prompt surface under its 10,000-token ceiling"
- [done] P1.2: The old-approval fixture is read on both checkpointer backends
  evidence: tests/backend/agent_04_old_thread_resume.py → "open_fixture pins a SqliteSaver over its own probe copy instead of assigning CHECKPOINT_DB, and a new first check fails loudly if the fixture's conversation did not load; 15/15 on the host and in the container, where it was 7/14"
- [done] P1.3: A turn with no history answers instead of returning a 500
  evidence: tests/backend/agent_06_capability_params_and_guards.py → "_agent_node returns a plain sentence and logs a warning rather than sending a system prompt alone, a conversation holding one real message is untouched by the guard, and the phantom-continuation cleanup now names the thread and the number of messages it erased while still erasing them"
- merged: 42d4b27
