# Backlog

The living record of unimplemented bugs and features. Kept short deliberately.
This is a list to work from, not an investigation report. When an item needs
more explanation than a line or two, that reasoning belongs in the commit that
closes it, not here.

## History

This replaces `docs/ROADMAP.md` and the four `docs/e2e-*-2026-08-16*.md` /
`docs/e2e-*-2026-08-17.md` documents, retired once the last two items they
tracked (FR-2's higher-resolution viewer capture, and the Ketcher chunk-weight
reduction) were implemented and verified live. Their full investigation,
findings, the ranked fix plan, and what was checked live versus by inspection
only, is preserved in git history rather than carried forward. To recover one:

```
git log --all --full-history -- docs/ROADMAP.md   # find the last commit that has it
git show <that-commit-sha>:docs/ROADMAP.md          # print its content
```

A fresh testing pass is expected to populate this file going forward, superseding
the 2026-08-16/17 pass's results.

The 10-phase registry v2/agent-rebuild overhaul (`docs/trackers/2026-08-job-system-overhaul.md`, all 72
steps done as of 2026-08-20) retired the `submit_job` tool this file's own
"Open" section used to name. Replaced by `start_job_draft`/
`update_job_draft`/`submit_draft`, whose ready-draft response now always
carries an explicit "NEXT STEP: ... call submit_draft now" instruction,
resolving the skipped-submission problem that item described. Recovered the
same way as `docs/ROADMAP.md` above if the original wording is ever wanted.

The CAS recommendation engine's entries were closed out together in September
2026 (`docs/trackers/2026-09-cas-engine-closeout.md`). Ten of them left this
file at once, which is worth explaining rather than leaving as a gap in the
history. Each left through one of three doors: fixed and validated across the
benchmark, settled as a deliberate decision, or measured and written into
`docs/CAS_ENGINE_METHOD.md` as a stated limitation with its number attached. A
limitation reported with a measurement behind it is not an open item, and
`docs/casbench/` holds the measurements.

Two of those entries turned out to be wrong about their own subject, which is
the argument for closing a set of related items together rather than one at a
time. The irreproducible recommendation was blamed on the orbital ranking and
was caused by an unstable SCF reference two stages earlier. And the molecule
said to exceed the refinement cap was not the one that did.

## Open

**Atom numbers do not come back after a vibrational mode change.**
`tests/frontend/ui_10_atom_label_toggle.spec.mjs` fails one of its 21 checks:
with the numbers on, selecting a different mode in the frequency table leaves
the vibration viewer's canvas identical whether the switch is then turned off
or on, which means the labels are not on screen to be removed.

Established rather than guessed, on 2026-09-09: it is **not** a regression from
the UI pass. The same check fails identically on a build of `f398f9a`, the
commit before that work started, served from its own worktree. It is also not
caused by the theme wiring added to `ModeAnimationViewer` in that pass, which
was removed and rebuilt to confirm. Longer settles around the snapshots (1.5 s
each side, up from 0.4) do not change it, so it is not a timing artifact
either. The equivalent check on the orbital viewer, whose rebuild path is the
same shape, passes.

What has not been established is the mechanism. `applyAtomLabels` is
stateless and always removes then re-adds, the label effect's dependency list
covers `displacement`, and React runs it after the rebuild effect that calls
`v.clear()`, so on a code read it should work. Two things are worth suspecting
before anything else: the animation loop the rebuild starts, and the APNG
capture the spec performs immediately before this check, which changes the
background and restores it.

The last entry to close was the app-versus-host latency split, which had
stood because its denominator could not be measured against a card shared
with other tenants: sampled twice in one run it came back 3.05x and 0.95x,
so the script reported the split as unavailable rather than assert one.
GPU 0 on this host is reserved for NexusQC and Ollama serves only NexusQC,
which is what made the measurement possible rather than any change to the
code. Measured 2026-09-06 on the current deployment: warm time to first
token has a median of 2.49 s over twelve samples, ranging 1.44 to 3.81 s;
with four turns at once, pooled over three bursts, the median is 6.47 s and
a whole turn 8.32 s. The stack as a whole slows by 2.60x under that load
and the model server on its own accounts for 2.13x of it, so **the app
multiplies the server's own concurrency penalty by 1.22x**. Four concurrent
turns still finish faster than four serial ones, 14.8 s against about 17 s.
Details in `evaluation/2026-09-06-full-pass.md`.
