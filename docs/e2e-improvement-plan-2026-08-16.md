# Improvement and bug-fix plan

Derived from the end-to-end pre-deployment test of 2026-08-16 (see `e2e-test-report-2026-08-16.md`). Every item cites the finding it comes from, names the files it touches, and states how to verify it.

Twenty-one **fixes**, ranked by deployment risk: **P0** blocks deployment · **P1** before general rollout · **P2** next iteration · **P3** backlog.

Plus four **feature requests** (`FR-0`–`FR-3`, [below](#feature-requests)) covering download buttons for document previews, 3D viewers, and vibrational animations. These are ranked separately and deliberately — a feature is never a confidentiality gap, and interleaving the two axes would make the list unreadable.

---

## P0 — fix before anyone uses this

### 1. Scope KB content retrieval to the caller *(F-022)*

`server/routes/kb.py:72-85` — `_content_search_dirs()` deliberately searches **every** user's upload directory, so `GET /api/kb/sources/{source}/content` serves any user's private upload to any authenticated caller.

```python
if owner:
    dirs.extend(d for d in UPLOADS_DIR.iterdir() if d.is_dir())   # ← remove
```

Restrict to the caller's own directory plus `_SCRAPED_DIR` (the genuinely shared corpus). Leave the `owner is None` branch alone — that is the admin / no-auth path and is correct as-is. This makes the content route match the scoping `list_sources` and the delete route already use.

The existing comment justifies the current behavior as *"mirroring list_sources' 'shared plus mine' visibility, but slightly wider"* and as legacy (*"content preview was never ownership-gated even pre-retrofit"*). Neither survives contact with the measurement: it is not slightly wider, it is unrestricted, and "it was never gated" is the same reasoning SEC-06 overturned for job artifacts. Update the comment along with the code.

**Verify:** `python3 tests/e2e/e2e_10_kb_lifecycle.py` — check `K4c` flips to PASS. Then `tests/backend/sec_06_ownership_sweep.py` should be extended to cover this route so it cannot regress.

**Effort:** ~30 minutes including the test.

### 2. Stop the AccountBar from covering the panel-collapse button *(F-013)*

`frontend/src/app-shell/ShellLayout.tsx` (AccountBar: `pointer-events-none absolute right-2 top-2 z-30`) and `frontend/src/app-shell/RightDock.tsx` (header: `position: static`).

The collapse button is unreachable at every viewport from 1280 to 2560, and a click aimed at it hits **"Log out"** — a destructive misclick on a control the user believes is a layout toggle.

Two workable fixes; the second is safer:

- give the RightDock header its own stacking context above `z-30`, or
- reserve horizontal space for the AccountBar in the dock header's layout (right padding ≈ the AccountBar's width) so the two never share coordinates.

The second avoids a z-index arms race and keeps both controls clickable.

**Verify:** `node tests/e2e/ui/run_ui.mjs ui_01` — the `[F-013] "Collapse panel" is not covered` check flips to PASS. That check uses `document.elementFromPoint()` at the button's centre, so it will catch any recurrence.

**Effort:** ~1 hour including a look at other absolutely-positioned overlays for the same pattern.

---

## P1 — before general rollout

### 3. Let RDKit decide what is a SMILES *(F-003)*

`app/chemistry/molecule.py:334-342`. The charset gate excludes every second letter of a two-letter element symbol, so no halogen or metal SMILES can pass — and `Chem.MolFromSmiles` is already called on the line *after* the gate that prevents it running.

```python
def looks_like_smiles(text: str) -> bool:
    text = text.strip()
    if not text or " " in text:
        return False
    return Chem.MolFromSmiles(text) is not None
```

Keep the whitespace guard (it cheaply rejects prose). Drop the charset set. If a fast pre-filter is still wanted to avoid RDKit parse attempts on names, widen it to the full element alphabet rather than the organic subset.

Also fix the error text in `molecule_from_name`: *"Please supply a SMILES string instead"* is actively misleading when the user just supplied one.

**Verify:** `python3 tests/e2e/e2e_05_molecule_resolution.py` — all six halogen/metal cases should resolve, controls should stay passing, and the XYZ workaround should still work.

**Effort:** ~1 hour. Check `molecule_from_smiles` handles multi-fragment inputs like `[Na+].[Cl-]` sensibly before declaring it done.

### 4. Delete the uploaded file when a KB source is deleted *(F-001)*

`server/routes/kb.py:246-289` removes Chroma chunks but never unlinks `UPLOADS_DIR/<owner>/<source>`. `app/auth/storage_quota.py:334` already does exactly the unlink that is needed — reuse it or factor it out.

The compounding problem matters as much as the leak: `_kb_candidates()` and `_kb_usage_by_owner()` both enumerate from **Chroma**, so once the vector entry is gone the file is invisible to every cleanup path, including account deletion. Two options:

- unlink at delete time (simplest, fixes the common case), and
- add a filesystem-based reconciliation to `purge_user_data()` so pre-existing orphans are reclaimed on account deletion.

Do both. Also remove the now-empty `UPLOADS_DIR/<owner>/` directory, which accumulates even on the path that works today.

**Verify:** `python3 tests/e2e/e2e_10_kb_lifecycle.py` — `K6c` and `K7` flip to PASS.

**Effort:** ~2 hours including the orphan reconciliation.

### 5. Distinguish "unrecognized syntax" from "recognized and wrong" for custom jobs *(F-018)*

`app/agent/tools.py` (`_build_custom_spec_or_error`) and `frontend/src/approvals/JobApprovalCard.tsx`.

Non-blocking validation is the right default for `custom` — the feature exists to carry syntax the validator was never built to recognize. But "No geometry block found" is not unrecognized syntax; it is a **positively detected missing required element**, and the app already produces the exact correct diagnosis before wasting 33 seconds of compute on an opaque engine error.

Split `validate_input`'s output into "unrecognized construct" (warn, as now) and "definitely wrong" (require an explicit second confirmation, or at minimum a visually distinct banner). The current yellow *"Structural check found possible issues (not blocking)"* reads as routine noise and is easy to click past.

**Verify:** compose a `custom` job with `* xyzfile 0 1` plus inline coordinates and confirm the approval card makes the problem impossible to miss.

**Effort:** ~3 hours.

### 6. Do not consume the approval on an invalid hand-edit *(F-023)*

`server/routes/chat.py::approve_job` and `app/agent/tools.py:1114-1123`.

Validation currently runs *inside* `submit_job`, i.e. after the graph has already resumed — so a rejected edit still spends the interrupt, and the corrected retry gets a 409. Move the check into the route, **before** `resume_turn()`, and return a 400 with the validation errors. That restores the behavior `CLAUDE.md` already documents and gives scripted clients a status code they can act on.

Keep the in-tool check as defense in depth.

Then correct `CLAUDE.md`, whose current description matches the retired Streamlit UI rather than the shipped React one.

**Verify:** `python3 tests/e2e/e2e_07_approval_flow.py` — `A4a`/`A4b`/`A3c` flip to PASS.

**Effort:** ~2 hours.

---

## P2 — next iteration

### 7. Add `data-testid` attributes *(report §7 — the highest-leverage item here)*

One `data-testid` and two `aria-label`s in the entire app is why UI testing is expensive and brittle, and it is why the most serious UI bug in this report (F-013) was found by a *timeout* rather than by an assertion.

Proposed scheme — `data-testid="<area>-<thing>[-<qualifier>]"`, ~40 elements, starting where `title` values already collide:

| area | elements |
|---|---|
| shell | `shell-collapse-sidebar`, `shell-collapse-panel`, `shell-help`, `shell-resize-sidebar`, `shell-resize-dock` |
| chat | `chat-composer`, `chat-send`, `chat-stop`, `chat-jump-latest`, `chat-error-dismiss` |
| approval | `approval-card`, `approval-approve`, `approval-reject`, `approval-input`, `approval-reset`, `approval-kb-context` |
| jobs | `job-row-<id>`, `job-kill`, `job-kill-confirm`, `job-delete`, `job-delete-confirm`, `job-attach`, `job-drawer` |
| drawer | `drawer-section-<name>` for each of the 19 gated sections |
| molecule | `molecule-viewer`, `molecule-builder-open`, `molecule-frame-slider`, `molecule-coords-toggle` |
| admin | `admin-open`, `admin-quota-<key>`, `admin-save-<key>`, `admin-purge-<kind>`, `admin-purge-confirm` |

Resolving the `"Detach"` (×3), `"Cancel"` (×4), `"Download as PNG"` (×3) and `"Confirm cancel"`/`"Confirm delete"` collisions first gives most of the benefit.

Two related cheap wins the specs had to work around, worth fixing at the same time: section headings are CSS-uppercased so `innerText` never matches title case, and clicking a `CollapsibleSection` header is a blind toggle with no way to query its state — an `aria-expanded` attribute would fix both testing and screen-reader behavior.

**Effort:** ~1 day, mechanical, and it permanently lowers the cost of every future UI change.

### 8. Add a `.dockerignore` and fix the Dockerfile COPY order *(F-006)*

370MB of build context, and `COPY frontend/ ./` overwrites the image's own `npm ci` output with the host's `node_modules` — which only worked here because host and image are both linux/x64 Node 20. A macOS or ARM developer would ship broken native binaries into the build.

```
# .dockerignore
.git
data
node_modules
frontend/node_modules
frontend/dist
**/__pycache__
```

With that in place the `COPY frontend/ ./` no longer clobbers anything and the `npm ci` layer starts earning its cache.

**Effort:** ~30 minutes. **Verify:** context size and build time should both drop sharply.

### 9. Guard `N_CORES` at startup *(F-005)*

Without `QC_AGENT_N_CORES`, `N_CORES` becomes 255 in-container (verified) and **every job hangs `pending` forever** with no error anywhere. The only thing preventing it is one line in `docker-compose.yml`.

Log the resolved value at startup, and warn loudly when it exceeds a plausible ceiling (e.g. `os.sched_getaffinity` count, or a configured max). A single startup line turns a silent multi-hour debugging session into an obvious misconfiguration.

**Effort:** ~30 minutes.

### 9b. Unify the imaginary-frequency rule across engines and the UI *(F-026)*

Four places, three different rules, for a number that tells a chemist whether they have a minimum or a transition state:

- `bagel_runner.py:765` — `f < -_IMAGINARY_THRESHOLD_CM1` (thresholded, correct)
- `orca_runner.py:577` and `pyscf_runner.py:483,519` — bare `f < 0`
- `VibrationTable.tsx:31` — bare `f < 0`, which is what paints the row red

So the same molecule at the same geometry can be reported as a minimum on BAGEL and a saddle point on ORCA, and the UI renders a −5.9 cm⁻¹ noise mode in "imaginary" red directly above a summary saying `n_imaginary_frequencies: 0` (see `docs/e2e-artifacts/ui02-drawer-frequency.png`).

Hoist `_IMAGINARY_THRESHOLD_CM1` into `app/config.py`, apply it in all three runners, and have the backend mark which modes are imaginary so the frontend stops re-deriving it from the sign.

**Effort:** ~1 hour. **Verify:** run a `frequency` job on each engine for the same molecule and confirm identical `n_imaginary_frequencies`, and that no row is coloured red unless the summary counts it.

### 10. Constrain `recommend_active_space` to the states requested *(F-020)*

`app/chemistry/jobs/pyscf_runner.py:~1021`. The tool selects a space, then rejects its own selection as too small for `n_states` — failing the job after the expensive step, on a reasonable request (3 states of water/STO-3G).

`n_states` is known before selection. Either constrain the candidate spaces to those that can host the requested states, or clamp and explain in the summary rather than raising. The current error text is genuinely good and should be preserved as the last-resort path.

**Effort:** ~3 hours.

### 11. Give the 2D sketcher a loading indicator *(F-014)*

`frontend/src/molecule/MoleculeBuilderModal.tsx` — `Suspense fallback={null}` on a 28.7MB chunk means a measured **3,484ms** of nothing. The app already has `.skeleton-shimmer` and animation tokens.

Longer term, that chunk is 8.5MB gzipped, larger than everything else combined; worth asking whether Ketcher can be trimmed or loaded on first hover.

**Effort:** ~15 minutes for the fallback.

### 12. Fix container file ownership on `data/` *(F-004)*

Everything the container writes is root-owned, so the host operator cannot clean, back up, or reclaim their own data directory. Either add a `USER` with a matching host uid/gid, or document the container-based cleanup recipe in the README:

```bash
docker run --rm -v "$PWD/data:/d" alpine sh -c 'rm -rf /d/jobs /d/kb'
```

Note the Dockerfile's root-user choice is deliberate (OpenMPI), so this needs care rather than a blind `USER` line.

**Effort:** ~1 hour to decide, more to implement safely.

### 13. Gate or consciously accept `/api/job-registry` *(F-010)*

The only route with no auth at all, and its handler takes no `Request`, so it *cannot* be gated as written. It exposes the full engine/method capability map to anonymous callers. Either add the `Request` parameter and gate it like every other route, or document it as intentionally public — but make it a decision rather than an accident, especially before the public listener is enabled.

**Effort:** ~15 minutes.

---

## P3 — backlog

| # | item | finding |
|---|---|---|
| 14 | Make `read_status()` return `None` (or `"unknown"`) for a job with no directory, matching `read_result`/`read_spec`. Today "queued" and "deleted" are indistinguishable to internal callers. | F-024 |
| 15 | Have the KB URL-fetch feature consult `robots.txt`, or warn the user when a site disallows fetching. `promoted_sources/` held 11 pages from a site the seeder deliberately refuses to crawl. | F-002 |
| 16 | Move to a Node version that satisfies `ketcher-*@3.17.2` (≥24.14.1), or pin Ketcher to a version supporting Node 20. | F-007 |
| 17 | Publish `agent_step` SSE events on the resume path so the UI shows tool progress after Approve is clicked. | F-008 |
| 18 | Make `sec_09`'s `detail` conditional — it currently prints failure-phrased text on a passing check. | F-012 |
| 19 | Replace the deprecated `canonical_smiles` pubchempy call with `connectivity_smiles`. | — |
| 20 | Reconcile `tests/run_backend.sh`'s failure blurb ("FAIL is expected for several `sec_*` scripts") with `tests/README.md`, which now correctly says any FAIL is a regression. | — |
| 21 | Update the README's status table: the nginx container, TLS, and the intranet listener *have* now been run end-to-end, and §Admin operations still says "There is no admin frontend yet" while the table says it is implemented. | — |

---

## Feature requests

These are **enhancements, not defects**, so they carry an `FR-` prefix rather than continuing the numbered sequence above. P0–P3 rank by deployment risk, and a feature is never a confidentiality gap — mixing the two axes would make the list unreadable.

All four share one small set of new modules, so **FR-0 must land first** or the effort estimates below triple-count it.

Every technical claim here was verified against the installed source (`frontend/node_modules/3dmol/build/3Dmol.js`, v2.5.5), not assumed.

### FR-0. Shared download infrastructure

Three new modules, so four features don't each grow their own copy of the same logic.

**`frontend/src/lib/download.ts`**

```ts
triggerDownload(href: string, filename: string): void
downloadBlob(blob: Blob, filename: string): void
downloadText(text: string, filename: string, mime?: string): void
```

Refactor `api.downloadPlotPng` onto `downloadBlob`. That also fixes two latent bugs in its current inlined version (`lib/api.ts:222-250`): the `<a>` is never appended to the DOM, and `URL.revokeObjectURL` fires synchronously right after `.click()` — both work in Chrome and are historically flaky elsewhere.

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

**`frontend/src/app-shell/DownloadButton.tsx`** — one icon button with a `busy` state (`Loader2`, already used for spinners) and an `onError` callback that feeds the existing `downloadError` banner in `JobDetailDrawer` (`:247-254`).

> **Every new control needs a distinct `title` *and* a `data-testid`.** There are already three colliding `[title="Download as PNG"]` buttons, and these features add roughly ten more. This turns **P2 item 7** from a general recommendation into a concrete forcing function — do them together.

**Effort:** ~3 hours.

### FR-1. Download button on every document preview flyout

Applies to raw input, raw output, KB source preview, and the job geometry flyout.

**Placement: a new `headerActions?: ReactNode` prop on `Flyout`**, rendered immediately left of the close X. `Flyout`'s header is currently hardcoded to exactly `Dialog.Title` + `Dialog.Close` (`app-shell/Flyout.tsx`), so the slot has to be added.

`SearchableText`'s find-bar row is the more natural-looking host and its icon convention already matches (`size={13}`, `shrink-0 rounded p-0.5 text-text-muted hover:bg-surface hover:text-text`) — but it **cannot serve the KB PDF/HTML branch**, which renders a bare `<iframe>` and has no download control of any kind today. The Flyout header serves every flyout uniformly, so that wins.

Sources are all trivially available:

| Flyout | Source | Filename |
|---|---|---|
| Raw output | `api.jobArtifactUrl(jobId, "raw_output")` — plain GET, direct `<a download>` | `{job_id}_output.txt` |
| Raw input | `api.jobRawInputUrl(jobId)` — plain GET | `{job_id}_input.inp` |
| KB preview | `api.kbSourceContentUrl(source)` — plain GET, works for the PDF branch too | the source's own name |
| Job geometry | already in memory — `moleculeToXyzBlock(molecule)` via `downloadText` | `{job_id}_geometry.xyz` |

The session cookie is HttpOnly and same-origin, so bare `<a href download>` authenticates for free — no fetch/blob round-trip needed except for the in-memory geometry case.

**Consistency gap worth folding in:** `UvVisPanel`, `IrSpectrumPanel`, and the entropy-plateau `<img>` (`JobDetailDrawer.tsx:556-560`) have **no** download control today, while the three inline SVG charts do. Same one-line `<a href={jobArtifactUrl(...)} download>` fixes all three.

**Icon:** `FileDown`. **Effort:** ~2 hours.

### FR-2. Download a PNG of any 3D viewer's current state

Applies to `MoleculeViewer`, `MoCubeViewer` (orbitals), `ScanFrameViewer`, `NebFrameViewer`, and `ModeAnimationViewer`.

**This is nearly free.** `GLViewer.pngURI()` is just `getCanvas().toDataURL('image/png')`, and 3Dmol **forces `preserveDrawingBuffer: true`** in `setupRenderer()` (`3Dmol.js:21715`), overriding whatever the app passes to `createViewer`. So the capture never returns a black frame and none of the five `createViewer` call sites need changing.

**Placement: an overlay button at `absolute right-8 top-1`**, styled identically to `ExpandablePanel`'s existing expand control at `right-1 top-1` (`z-10 rounded bg-surface/80 p-1 text-text-muted hover:bg-surface-raised hover:text-text`, `size={13}`), which already wraps most viewer call sites.

The argument for an overlay over a toolbar row is uniformity: the five viewers have completely different surroundings — `MoleculeViewer` is a bare `<div>` with no control row at all, `MoCubeViewer` has two, `ScanFrameViewer` has a frame slider. An overlay is the only placement that is identical everywhere and it sits naturally beside the expand button users already reach for. `MoleculeViewer` needs a `relative` wrapper added; the others already have one.

**White background: do it, and make it the only behaviour** — no toggle. The entire reason to export an orbital or a geometry is to put it in a manuscript, poster or slide deck, all of which are white, and a dark-ground figure is unusable there.

**Verified by rendering, not assumed.** The concern was 3Dmol's default hydrogen colour being pure white (`0xFFFFFF`), which could vanish on a white ground. It does not: hydrogens read clearly through diffuse/specular shading and their own edges, exactly as they do in PyMOL/VMD figures. Atom labels also survive, because they carry their own chip (`backgroundColor:"black", backgroundOpacity:0.55, fontColor:"white"`) which simply blends to grey. Orbital lobes (`#6e8cff` / `#e85b4e`) are unaffected. Evidence: `docs/e2e-artifacts/fr-white-bg-current-dark.png` vs `fr-white-bg-proposed-white.png`, rendered through the app's exact `createViewer`/`setStyle`/`addLabel` calls.

`viewer.setViewStyle({style:"outline"})` was evaluated as a fallback and is **not needed** — it adds a heavy black cartoon silhouette around the whole molecule. Worth remembering only as an optional publication style, not as a legibility fix.

**Known limitation:** the export is exactly the on-screen canvas, so its resolution is the pane's (~790×480 in the drawer). Fine for slides, lowish for print. Rendering at higher resolution would mean temporarily resizing the container before capture — a reasonable follow-up, deliberately out of scope here.

**Filenames:** `{job_id}_{label}.png`, e.g. `a1b2c3_HOMO.png`, `a1b2c3_geometry.png`.

**Icon:** `ImageDown`. **Effort:** ~3 hours for all five viewers.

### FR-3. Download the vibrational motion as an animation

**Format: APNG, not GIF** — decided deliberately.

`GLViewer.apngURI(nframes)` is built into 3Dmol and encodes via `upng-js`, already a hard dependency of `3dmol`. It works by hooking `viewChangeCallback`, which fires from `show()` — i.e. on **every rendered frame**, not just camera moves (`3Dmol.js:21850`, comment: *"have any scene change trigger a callback"*). So it captures the running vibration directly, with no manual frame stepping:

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

**Icon:** `Film`, to distinguish it from FR-2's still on the same viewer. **Effort:** ~2 hours.

## Prompt reliability

`submit_job` is skipped on roughly **1 in 3** fully-specified requests (F-019, 2/3 across fresh-thread retries). Nothing incorrect results — the approval gate is structural — but a third of job requests needing a second nudge is real friction.

This codebase has an established pattern for exactly this problem: when a decision matters, make it mechanical rather than prompt-dependent (the `want_oscillator_strengths` → ORCA routing is the precedent, and it was adopted specifically because prompt-dependent behavior had already cost hours of misdiagnosis once).

Two options, in order of preference:

1. **Mechanical nudge.** When a turn calls `set_molecule` and stops, and the user's message contained an explicit run request, inject a follow-up prompt rather than ending the turn. This is close to what `job_watcher.py` already does for failed jobs.
2. **Prompt hardening** around "the user has already authorized submission — do not ask again."

Track the rate: `tests/e2e/results/*.jsonl` records the tool trace for every scenario, so the miss rate is measurable across model or prompt changes rather than anecdotal.

---

## Deployment guidance to publish alongside the app

- **BAGEL CASSCF, CASPT2, and CASSCF geometry optimization are not practically runnable on this host** (F-017): ~85s per macro-iteration for a trivial 3-atom STO-3G system, so these exceed ten minutes and will look like a hang. BAGEL `frequency`, `mo_visualization`, and `custom` are fine (26s, 22s, 87s). Either warn in the UI when one of the slow combinations is selected, or route users to ORCA/PySCF for CASSCF work.
- **The host-level kill switch and the public `:443` listener remain unverified.** Do not enable public access on the strength of this report.
