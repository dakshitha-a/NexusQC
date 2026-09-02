# Tracker: one switch for the atom numbers, in every viewer and every export

**Complete as of 2026-09-02.** Three phases, 7 steps, all done.
Both phases landed as one commit: the naming fix in Phase 2 was found in the
very code path Phase 1 was rewiring, and separating them would have split one
file's changes across two commits for no gain.

It stays here rather than moving to [`trackers/`](trackers/) until the next
plan starts, which is when it gets archived and a fresh tracker takes its
place. **Exactly one tracker is active at a time.**

## How tracking works here

Development is linear, so there is never a reason to have two trackers open at
once. Each plan, feature or non-trivial request gets its own tracker, this file
is whichever one is currently in motion, and when its plan is finished the file
is closed out and moved to [`trackers/`](trackers/), then a fresh one starts
here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path. The one this
replaces is
[`trackers/2026-09-states-and-batching.md`](trackers/2026-09-states-and-batching.md)
-- 24 steps across nine phases, closed 2026-09-01.

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Why this plan exists

Every 3D viewer in the app drew a numbered chip on top of every atom, always,
with no way to turn them off. The numbering is what makes it possible to say
"scan the C4-C6 bond" or to read a constraint back, so it earns its place. It
is also clutter in a figure, and because the labels live in the 3Dmol scene
they landed in every PNG and animated PNG the viewers exported. There was no
way to get a clean picture of a structure or an orbital out of this app.

The request was one global switch that every viewer obeys, and that the
exported images follow. It lives in the molecule pane of the instrument panel
and is mirrored into each viewer's own control overlay, so it is reachable
from the job drawer without scrolling back to the dock. It defaults to on, so
nothing anybody was already looking at changed.

**The interesting part was not the switch.** Three components own a viewer
(`MoleculeViewer`, `MoCubeViewer`, `ModeAnimationViewer`) and each carried its
own copy of the same label block. Two of them wipe the whole scene with
`clear()` on inputs that have nothing to do with the molecule: `MoCubeViewer`
on every tick of the isovalue slider, `ModeAnimationViewer` on every change of
vibrational mode. So the label-drawing effect could not simply be keyed on the
preference and the molecule. Keyed that way, the numbers survive until the
first time anybody drags the isovalue or picks another mode, and then vanish
for good, with no error and nothing in the console. Both paths are the most
used controls in the drawer, so the bug would have been found by a user rather
than by us.

The rule the code now follows, stated in a comment beside each of the three
effects: **the label effect's dependency list is a superset of the model
effect's own, plus the preference.** Phase 1's browser spec drives both
rebuild paths deliberately, with the numbers on, before comparing on against
off -- those two checks are the only ones that can tell a correct dependency
list from the narrower one.

Equally, the flag could not go into the existing model effects. Each is
guarded so a re-run either bails on a content hash or re-frames the camera, on
purpose, so that dragging the isovalue does not throw away a rotation the user
set. Toggling the numbers must not either.

---

## Phase 1: One preference, three viewers, and the exports that follow

- [done] P1.1: A single persisted preference, and one definition of the labels
  evidence: frontend/src/lib/viewerPrefsStore.ts → "zustand + persist under qc-agent-viewer-prefs, atomLabels defaulting to true; applyAtomLabels in frontend/src/molecule/atomLabels.ts replaces the three copied label blocks and always removes before it adds, so it is safe against a scene that cleared its own labels"
- [done] P1.2: The switch, in the molecule pane and in every viewer's overlay
  evidence: frontend/src/molecule/AtomLabelToggle.tsx → "role=switch with aria-checked, reading the store directly so nothing threads through the four frame viewers; rendered in MoleculePanel's icon row, in its empty state so it stays reachable with no molecule loaded, and in the overlay of MoleculeViewer, MoCubeViewer and ModeAnimationViewer; the empty-state branch is asserted before any molecule is seeded"
- [done] P1.3: The labels move to their own effect in all three viewers
  evidence: tests/frontend/ui_10_atom_label_toggle.spec.mjs → "21/21 checks. Turning the numbers off changes canvas.toDataURL() in all three viewers, and they come back on"
- [done] P1.4: The rebuild paths that used to wipe the labels keep them
  evidence: tests/frontend/ui_10_atom_label_toggle.spec.mjs → "with the numbers on, an isovalue drag then a toggle still changes the orbital canvas, and a mode change then a toggle still changes the vibration canvas; both would be byte-identical if the rebuild had already wiped the labels"
- [done] P1.5: The exports follow the switch
  evidence: tests/frontend/ui_10_atom_label_toggle.spec.mjs → "the PNG the browser actually saved differs with the numbers on and off, 250931B against 245088B, read from the downloaded file rather than from the canvas; the 40-frame animated PNG still exports with the numbers off at 1007544B rather than hitting captureApng's timeout"
- merged: 6a6d850

## Phase 2: The frame viewers name what they captured

Found while wiring the switch through, and in its blast radius: the four frame
viewers that embed `MoleculeViewer` (`NebFrameViewer`, `EnsembleFrameViewer`,
`ScanFrameViewer`, `GeometrySetViewer`) passed it neither a filename stem nor
an error callback. So a PNG captured from image 4 of a NEB path downloaded as
`molecule_view.png`, against this project's own
`safename_descriptor.extension` rule, and four captures off one scan arrived
as four files that nothing but their order distinguished. A capture that
failed reached `console.error` and nothing else, so the button simply stopped
spinning.

- [done] P2.1: A captured frame is named after its job and its frame
  evidence: frontend/src/jobs/ScanFrameViewer.tsx → "all four frame viewers now pass filenameBase=jobFilenameStem(job) and a per-frame descriptor (image4_view, sample7_view, geometry2_view) to MoleculeViewer, which takes a descriptor prop defaulting to the previous hardcoded 'view'; each already received the job row, so nothing new is threaded from the drawer"
- merged: 6a6d850

---

## Phase 3: The frontend suite's own account cleanup never worked

- [done] P3.1: Every spec that deletes its test account now actually deletes it
  evidence: tests/frontend/ui_10_atom_label_toggle.spec.mjs → "a full 21/21 run now leaves no qatest thread and no qatest account on the stack; before the fix each run left one account behind, and 13 had accumulated over this session's runs alone"
- merged: 182b818

---

## Found along the way, not fixed here

Recorded rather than acted on, because each is outside this plan and wants its
own decision.

**Deleting an account leaves its conversations behind.** Ten `qatest_ui10_*`
threads outlived the accounts that owned them, with ownership recorded at
creation. The jobs and the account go; the conversations stay, listed under
nobody. This is the same shape as the project-archive leak fixed in the
current `[Unreleased]` section and looks like the same class of bug. The new
spec deletes its own thread explicitly, which stops this one leaking, but that
is a workaround in the test rather than a fix in the app.

Worth reading together with Phase 3: the accounts in that observation were
themselves never being deleted, so part of what looked like orphaned
conversations was orphaned everything. The conversation half survives even a
delete that does succeed, which is what still wants a decision.

**An agent turn landing closes an open job detail drawer.** Attaching the
seeded jobs to a thread makes the agent run a "these finished, summarise them"
turn. When that turn arrived while a job drawer was open, the drawer closed on
its own. Reproduced repeatedly during this work and confirmed by removing the
trigger, which is why the spec seeds without `set_active_job_ids`. Not
diagnosed further: it costs a user their place in a drawer they were reading.

**`FIT_MARGIN` is tuned for labels that are now optional.** `fitView.ts:50`
pulls the camera back by a fixed fraction, and `fitView.ts:40` names
"atom-number labels" as part of what that fraction compensates for. With the
numbers off the framing is now slightly more conservative than it needs to be.
Deliberately left alone: making the margin depend on the preference trades one
tidy scale-invariant constant for a conditional needing two separate tunings,
to buy a few percent of frame on one setting.

**The molecule viewer's content hash is rebuilt on every render.**
`MoleculeViewer.tsx`'s guard `JSON.stringify`s the whole coordinate array each
time the effect runs, and the frame viewers re-render on every scrub step. It
has never been measured as a problem and was left untouched rather than grow
this diff.
