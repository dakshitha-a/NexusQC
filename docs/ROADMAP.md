# Roadmap

Designed, not built. Everything below is a specification worked out against the
real installed source rather than sketched — the 3Dmol claims were checked
against `frontend/node_modules/3dmol/build/3Dmol.js` (v2.5.5) — but **none of it
is implemented.**

Stated plainly, because the difference is easy to lose: there is no canvas
capture anywhere in the frontend today. The `Download` buttons that do exist
serve *server-rendered* matplotlib artifacts (a `.png` plot, a `.dat` data file)
over ordinary links. Capturing what a 3D viewer is currently showing is a
different mechanism entirely, and it is the thing specified here.

## What is actually left

The 2026-08-16 end-to-end review produced 26 findings and a ranked improvement
plan. Every numbered P0–P3 item in that plan (items 1–17, 19, 21, including the
`data-testid` sweep and the shared imaginary-frequency rule) was implemented and
verified — `docs/e2e-fix-verification-2026-08-17.md` records what was checked
live versus what is only code-complete, and it is the file to trust over any
"fixed" claim elsewhere.

Two things from that plan were never built, and they are the contents of this
file:

| Item | What it is | Status |
|---|---|---|
| FR-0 – FR-3 | Viewer/document downloads: shared infrastructure, flyout download buttons, a PNG of any 3D viewer's current state, and the vibrational motion as an APNG | Specified below, not implemented |
| F-019 | `submit_job` is skipped on roughly 1 in 3 fully-specified requests, so a third of job requests need a second nudge | Diagnosed, no fix attempted |

The full original review, its findings and the ranked plan are kept alongside
this file — `docs/e2e-findings-2026-08-16.md`,
`docs/e2e-test-report-2026-08-16.md` and
`docs/e2e-improvement-plan-2026-08-16.md` — rather than summarised away, since
the reasoning behind each item is worth more than its one-line title.

## Viewer downloads

All four items share one small set of new modules, so **FR-0 must land first** or
the effort estimates triple-count it.

### FR-0. Shared download infrastructure

Three new modules, so four features don't each grow their own copy of the same logic.

**`frontend/src/lib/download.ts`**

```ts
triggerDownload(href: string, filename: string): void
downloadBlob(blob: Blob, filename: string): void
downloadText(text: string, filename: string, mime?: string): void
```

Refactor `api.downloadPlotPng` onto `downloadBlob`. That also fixes two latent bugs in its current inlined version: the `<a>` is never appended to the DOM, and `URL.revokeObjectURL` fires synchronously right after `.click()` — both work in Chrome and are historically flaky elsewhere.

**`frontend/src/molecule/captureViewer.ts`**

```ts
capturePng(viewer: GLViewer): string                                  // data URL
captureApng(viewer: GLViewer, frames?: number, timeoutMs?: number): Promise<string>
```

Both swap the background to white and restore afterwards. **The ordering is load-bearing** — `setBackgroundColor` itself triggers a render, and `apngURI` captures on every render, so a swap made after hooking would land a stray dark frame in the animation:

```
set white → render() → [capture / hook apngURI] → await → restore → render()
```

`captureApng` needs a timeout guard: `apngURI` resolves only after exactly `nframes` callbacks and would hang forever against a paused viewer.

**`frontend/src/app-shell/DownloadButton.tsx`** — one icon button with a `busy` state (`Loader2`, already used for spinners) and an `onError` callback that feeds the existing `downloadError` banner in `JobDetailDrawer`.

> **Every new control needs a distinct `title` *and* a `data-testid`.** There are already three colliding `[title="Download as PNG"]` buttons, and these features add roughly ten more.

**Effort:** ~3 hours.

### FR-1. Download button on every document preview flyout

Applies to raw input, raw output, KB source preview, and the job geometry flyout.

**Placement: a new `headerActions?: ReactNode` prop on `Flyout`**, rendered immediately left of the close X. `Flyout`'s header is currently hardcoded to exactly `Dialog.Title` + `Dialog.Close`, so the slot has to be added.

Filenames should carry the job id and the artifact kind, so several downloads from one session don't collide in the browser's download directory.

**Effort:** ~1 hour once FR-0 exists.

### FR-2. Download a PNG of any 3D viewer's current state

Applies to the molecule viewer, the orbital/MO cube viewer, the NEB frame viewer and the ensemble frame viewer — every pane that owns a `GLViewer`.

The capture is of the **current** state: same camera, same zoom, same isovalue, same displayed frame. That is the whole point, and it is why this cannot be served by a server-rendered image.

White background rather than the app's dark surface, since these end up in papers and slides. `capturePng` handles the swap and restore; see FR-0's ordering rule.

**Effort:** ~1 hour once FR-0 exists.

### FR-3. Download the vibrational motion as an animation

**Format: APNG, not GIF** — decided deliberately.

`GLViewer.apngURI(nframes)` is built into 3Dmol and encodes via `upng-js`, already a hard dependency of `3dmol`. It works by hooking `viewChangeCallback`, which fires from `show()` — i.e. on **every rendered frame**, not just camera moves. So it captures the running vibration directly, with no manual frame stepping:

```ts
const uri = await viewer.apngURI(40);
```

True GIF would cost the gif.js library, the app's **first web worker**, and 256-colour quantisation that dithers visibly on smooth 3D shading. The accepted trade-off for APNG: it animates in every modern browser, Slack and GitHub, but **PowerPoint and Word show only the first frame**. Revisit only if slide embedding turns out to matter in practice.

**Frame count: 40.** `model.vibrate(10, 1.2, true)` runs `i` from `-10` to `9`, producing exactly **20 frames**, and `animate({loop:"backAndForth"})` traverses them out and back — so 40 captures one full cycle and loops seamlessly.

**Two implementation details that will otherwise bite:**

- `delays[0]` is measured from promise creation rather than a real frame boundary, so the first inter-frame delay is garbage. Normalise it to the median of the rest, or drop it.
- Set the white background **before** hooking `apngURI`, per FR-0's ordering rule, or the background-swap render itself becomes the first captured frame.

**UX:** capture takes ~4s at the default 100ms animation interval. The button needs a `busy` state, and the viewer visibly turns white during capture — acceptable as honest feedback, and simpler than an off-screen render.

**Filename:** `{job_id}_mode{n}_{freq}cm-1.png` (APNG uses the `.png` extension).

**Effort:** ~2 hours once FR-0 exists.

## Prompt reliability (F-019)

`submit_job` is skipped on roughly **1 in 3** fully-specified requests. Nothing
incorrect results — the approval gate is structural, not prompt-dependent — but a
third of job requests needing a second nudge is real friction.

This codebase has an established pattern for exactly this problem: when a
decision matters, make it mechanical rather than prompt-dependent. The
`want_oscillator_strengths` → ORCA routing is the precedent, and it was adopted
specifically because prompt-dependent behaviour had already cost hours of
misdiagnosis once.

Two options, in order of preference:

1. **Mechanical nudge.** When a turn calls `set_molecule` and stops, and the
   user's message contained an explicit run request, inject a follow-up prompt
   rather than ending the turn. This is close to what `app/agent/job_watcher.py`
   already does for failed jobs.
2. **Prompt hardening** around "the user has already authorised submission — do
   not ask again."

Track the rate rather than trusting an impression: `tests/e2e/results/*.jsonl`
records the tool trace for every scenario, so the miss rate is measurable across
model and prompt changes. Those files are machine-generated and deliberately not
tracked in git.
