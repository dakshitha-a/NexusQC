# P5.3: the frontend findings, measured

`ui_15_row_keyboard.spec.mjs` (R-070 and R-065) and
`perf_08_transcript_render.spec.mjs` (R-067), before and after, in this
directory. "Before" is the deployment on `f6d12c5`, which is the code as the
review found it plus Phases 1 to 3; "after" is the same specs against the
deployment carrying this step. `ui_10_atom_label_toggle.spec.mjs` (R-064) is
part of the gate's frontend suite rather than a standalone pair, for the reason
below.

## R-070: keyboard access to the selection rows

Seven components selected something with a bare `onClick` on a `div`, `li` or
`tr` and no role, `tabIndex` or key handler. Two of them are not chrome: the
orbital table and the vibration table are how a user picks which orbital the
isosurface shows and which normal mode animates, so the scientific selection
path itself was mouse-only.

Before, on the running deployment: every one of those checks fails. The job
row reports `tabindex=null` and `aria-selected=null`, Enter and Space on it do
nothing at all (the drawer stays shut), a focused row is byte-identical to an
unfocused one so there is no focus ring to see, and the same holds for the
vibration rows, the orbital rows and the conversation rows. 7 of 20 checks
pass, and four of those seven are the login and seeding steps.

## R-065: the viewers that never stop watching

`GLViewer` has no teardown method and registers two observers on its container
that it never removes. The container is a stable `<div>` that survives a viewer
swap, so after any rebuild the orphan's observers fire on the same element as
the live viewer's and the orphan runs a full `resize()`: re-read the box,
`setSize()` on the renderer, re-render into a canvas nobody can see. Every
window resize does that to every orphan ever created.

Measured by patching `ResizeObserver.prototype.observe` and `.disconnect`
before the app loads and keeping a live count, then opening and closing the job
detail drawer ten times.

**Before: live observers 1 to 11 across ten drawer cycles, from 20 `observe()`
calls.** Exactly one permanent observer left behind per cycle, none released.
That is the finding reproduced rather than inferred: it was filed as "suspected
(code read), not measured in a browser".

The fix disconnects both observers in each viewer's cleanup. The
`document.body` and `window` listeners cannot be removed from outside the
library, because the bound functions were never stored anywhere, so a residual
per-viewer allocation remains until the page is reloaded. That is stated in
`docs/ARCHITECTURE.md` rather than quietly accepted, and removing it needs an
upstream `destroy()`.

## R-067: what one streamed token costs the transcript

`ChatPane` subscribes to the whole chat store with no selector, the store
writes a new `streaming` object on every token, and the transcript was mapped
through an unmemoised component whose assistant branch runs a full remark parse
of that message's markdown from scratch on every render.

The measurement does not use a real agent turn, because a model's output length
and timing are not reproducible and the number would not be checkable by anyone
else. The app receives its tokens over an `EventSource`, so the spec replaces
`window.EventSource` before any app code loads and drives the transcript
itself: 40 synthetic messages (alternating human and assistant, each assistant
message carrying a heading, a list, a table and a fenced code block, so the
markdown parse has real work), then 300 `token` events one animation frame
apart. Identical input every run.

The figure is Chrome's own `ScriptDuration`, read through the DevTools Protocol
immediately before and after the token phase: cumulative seconds of JavaScript
on the main thread, so it counts React's render and commit and the markdown
parses inside them, and not paint or network. Three reps, median reported,
because the first run of anything in a fresh page pays JIT warmup that is not
part of what is being measured.

**Before, 40 messages and 300 tokens, median of 3 reps: 3,421 ms of script
time over the token phase, 11.40 ms per token.** Style 8 ms and layout 53 ms.
Per-rep script times were 3817, 3421 and 3380 ms, so the spread is small.

Eleven milliseconds of JavaScript per token is the whole main thread at a local
model's token rate, and it is spent producing output identical to what was
already on screen.

## R-064: why there is no before/after pair here

The vibration half of `ui_10_atom_label_toggle.spec.mjs` was reading the wrong
canvas. It snapshotted "the last visible canvas in the page", and in a
frequency job's drawer the orbitals panel comes after the vibrations panel and
mounts a viewer eagerly that never draws anything, because a frequency job has
no cubes. Two reads of a blank canvas are identical, which is exactly the
failure the `docs/BACKLOG.md` entry recorded as "the mode change had already
wiped the labels".

So the "before" for R-064 is that recorded failure, and there is nothing
useful to measure twice: the old check could only fail and, with the selector
alone corrected, could only pass, because `ModeAnimationViewer` animates
continuously and two snapshots a few hundred milliseconds apart differ whatever
the labels do. Both halves were needed. The repaired check reads
`[data-panel="vibrations"] canvas` and pauses the animation on the viewer
3Dmol hangs off its own canvas (`_3dmol_viewer`) before each read, so the only
thing that can differ between the two snapshots is what the switch changed.
Its result is in the gate's frontend suite log.
