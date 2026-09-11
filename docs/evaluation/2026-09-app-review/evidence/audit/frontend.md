# Frontend audit (`frontend/src`), commit `ca7e0ff`

Read `docs/ARCHITECTURE.md` lines 1688-2082 ("The frontend") in full before
filing, plus `docs/BACKLOG.md`'s Open section and
`tests/frontend/ui_10_atom_label_toggle.spec.mjs`. Findings below engage with
those decisions by name where they touch them.

Ten findings. A "checked and clean" section follows them, with what was
checked and how, per the brief.

---

### R-000: A job opened from the Job Manager stops updating in the drawer while SSE is connected, because `job_update` only reaches the owning thread's stream

- surface: code:frontend
- class: bug
- severity: S2
- cause: CODE
- confidence: suspected (code read)
- found by: audit:frontend
- scope: Checked `lib/queries.ts` (`useJobQuery`, `useJobsListQuery`), `lib/sse.ts`, `app/agent/job_watcher.py`'s emit path, and every call site of `jobQueryKey`. Engine-independent: this is the drawer's cache policy, identical for PySCF/ORCA/BAGEL and every task. Not checked live in a browser.
- repro: Open conversation A. From the Job Manager panel (which is cross-conversation by design) click a *running* job belonging to conversation B, or a job submitted outside any conversation. Watch the drawer. The Job Manager row behind it turns green on its own 4 s poll; the open drawer's header keeps saying `running`, its Live output keeps ticking, and no summary or artifacts ever appear. Close and reopen the drawer and everything is there.
- observed: `frontend/src/lib/queries.ts:87-95`

  ```ts
  return useQuery({
    queryKey: jobQueryKey(jobId ?? ""),
    queryFn: () => api.getJob(jobId as string),
    enabled: !!jobId,
    refetchInterval: (query) => {
      if (sseConnected) return false;
      return isNonTerminal((query.state.data as JobRow | undefined)?.status) ? 4000 : false;
    },
  });
  ```

  `sseConnected` is a single global boolean set by `useThreadEvents` for the **active** thread (`lib/sse.ts:41,50`). The only thing that invalidates `["job", jobId]` anywhere in the app is that same per-thread stream (`lib/sse.ts:99`, and a `grep` for `jobQueryKey` / `["job",` finds no other invalidation — only `KillButton.tsx:28`'s optimistic `setQueryData`).

  On the server, the event is emitted per thread and only for that thread's own active jobs — `app/agent/job_watcher.py:463-479`:

  ```python
  for entry in thread_registry.list_threads():
      thread_id = entry["thread_id"]
      active_job_ids = entry.get("active_job_ids", [])
      if not active_job_ids:
          continue
      ...
          self._emit(thread_id, {
              "type": "job_update", "job_id": job_id, ...
          })
  ```

  So the client subscribes to `/api/threads/{activeThreadId}/events` and receives `job_update` **only** for jobs in that thread's `active_job_ids`. A job owned by another conversation, a job with no owning thread at all (deliberately visible to everyone, per the settled design), and a job whose thread has already had its summary turn and cleared `active_job_ids`, all produce no event on the open stream — yet `sseConnected` is true, so the poll fallback is disabled.
- expected: The drawer should reach a terminal status without user intervention. `queries.ts:83-85`'s own comment states the assumption ("normally `sse.ts` invalidates `["job", jobId]` on that job's own `job_update` event, so an open `JobDetailDrawer` doesn't need to poll at all while connected"), and that assumption holds only for jobs of the currently-open conversation. The architecture's "polling is separated from expensive rendering" section says job status is polled against the lock-free routes precisely so a tab is never stalled — the lock-free route is there to be called.
- evidence: `frontend/src/lib/queries.ts:82-96`; `frontend/src/lib/sse.ts:91-108`; `app/agent/job_watcher.py:461-479`.
- pointer: `sseConnected` answers "is *a* stream open", not "does that stream carry this job". The gate needs the second question.
- note: What would settle it: open two conversations, submit a job in one, open it from the Job Manager while the other is active, and watch. Partial mitigations that make it intermittent rather than permanent, and that are worth knowing before reproducing: TanStack's `refetchOnWindowFocus` defaults to true, so alt-tabbing away and back refetches after the 10 s `staleTime`; and if the SSE connection ever drops, the fallback poll switches on. The misleading part is the combination — `LiveLogPanel` is gated on `job.status === "running"` (`JobDetailDrawer.tsx:451`), so with a stuck status it polls the log forever and the user watches the engine's output finish under a header that still says the job is running. Fix direction: make the gate per-job rather than global (e.g. only disable the interval when the job's `thread_id` is the active thread), or simply always poll a non-terminal job at 4 s and let the SSE invalidation be the fast path — the route is lock-free and the cost is the same one `useJobsListQuery` already pays unconditionally.

---

### R-000: `ui_10`'s atom-label check on the vibration viewer snapshots the orbital viewer's empty canvas, which is the mechanism behind the open backlog item

- surface: code:frontend
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:frontend
- scope: `tests/frontend/ui_10_atom_label_toggle.spec.mjs` step 5, against `JobDetailDrawer`'s freq-job layout and `MoCubeViewer`'s mount behaviour. The same spec's step 4 (orbital viewer) is unaffected and does measure what it claims. Not run.
- repro: In the freq-job drawer the spec opens, evaluate `Array.from(document.querySelectorAll("canvas")).filter(c => c.offsetParent !== null).length` and then, for the last of them, `c.closest("[data-panel]")?.dataset.panel`. Expectation from this reading: two canvases, and the last one reports `orbitals`, not `vibrations`.
- observed: This is the "Atom numbers do not come back after a vibrational mode change" entry in `docs/BACKLOG.md`'s Open section, which records that the mechanism has not been established, that `applyAtomLabels` is stateless, and that the dependency list looks right on a code read. The dependency list *is* right. The check is reading the wrong canvas.

  The spec's snapshot helper takes the **last** visible canvas (`ui_10_atom_label_toggle.spec.mjs:59-68`):

  ```js
  const canvases = Array.from(document.querySelectorAll("canvas")).filter((c) => c.offsetParent !== null);
  const c = canvases[canvases.length - 1];
  ```

  In `JobDetailDrawer.tsx` the vibrations panel is at line 978 and the **orbitals** panel at line 1450 — later in the DOM. The orbitals panel renders whenever the job has cubes *or* an orbital table (`JobDetailDrawer.tsx:1433-1435`), and a PySCF frequency job always writes one: `app/chemistry/jobs/pyscf_runner.py:1467`, `molden_path, summary["orbital_table"] = _write_molden_and_table(...)` at the end of `run_frequency`. `ExpandablePanel` evaluates its render-prop child eagerly (`ExpandablePanel.tsx:183-185`), so `MoCubeViewer` mounts.

  `MoCubeViewer` creates its 3Dmol viewer — and therefore a `<canvas>` — unconditionally in its init effect, before any cube exists (`MoCubeViewer.tsx:101-118`). With no `artifacts.cubes` on a freq job, `cubeLabels` is `[]`, so `selected` is `""`, so the fetch effect's `url` is `null` and returns early (`MoCubeViewer.tsx:153-157`), and `cubeText` stays `null`. Both the render effect and the label effect then bail on `if (!v || !cubeText) return` (`MoCubeViewer.tsx:206`, `MoCubeViewer.tsx:253`).

  So the canvas the spec snapshots has never been drawn into and does not respond to the atom-label toggle at all. Two reads of it are byte-identical, which is exactly the failure reported: *"identical before/after the switch, i.e. the mode change had already wiped the labels"*.
- expected: The check should read the canvas inside `[data-panel="vibrations"]`. `ExpandablePanel`'s `name` prop exists for precisely this problem and its own comment says so (`ExpandablePanel.tsx:100-107`: a test that wants one particular panel "resorted to 'the last one in the drawer'. That silently retargets the moment a section is added below").
- evidence: `tests/frontend/ui_10_atom_label_toggle.spec.mjs:59-68` and `:349-365`; `frontend/src/jobs/JobDetailDrawer.tsx:978` vs `:1450`; `frontend/src/jobs/MoCubeViewer.tsx:101-118`, `:153-157`, `:206`, `:253`; `app/chemistry/jobs/pyscf_runner.py:1467`.
- pointer: A selector that means "the most recently mounted viewer" instead of "this panel's viewer", against a drawer whose last panel mounts a viewer eagerly and leaves it blank.
- note: This explains the known backlog item rather than being a new defect, and it explains all three things the backlog says were established: it is not a regression (the drawer has had this shape all along), the theme wiring is irrelevant, and longer settles cannot help. Two consequences for whoever fixes it. **First, the app-side behaviour is unobserved, not proven correct** — the spec never looked at the vibration viewer after a mode change, so "do the labels come back?" is still an open question, just not one this failure answers. **Second, fixing the selector alone makes the check vacuous**: `ModeAnimationViewer` calls `v.animate({loop: "backAndForth", reps: 0})` (`ModeAnimationViewer.tsx:86`), so the canvas is repainting continuously and two snapshots 400 ms apart will differ whatever the labels do. The fixed check needs the animation paused (3Dmol has `pauseAnimate()`/`stopAnimate()`) or both snapshots taken at the same animation frame, as well as `[data-panel="vibrations"] canvas` as the target. Worth noting the same reasoning applies in reverse to the orbital check, which is sound because that viewer is static.

---

### R-000: Every `createViewer()` pins its `GLViewer` to `document.body` and `window` for the life of the page; clearing the container does not release it

- surface: code:frontend
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:frontend
- scope: All seven viewer call sites — `MoleculeViewer`, `MoCubeViewer`, `ModeAnimationViewer`, and the four that render `MoleculeViewer` (`ScanFrameViewer`, `NebFrameViewer`, `EnsembleFrameViewer`, `GeometrySetViewer`). Read against the installed 3Dmol, `frontend/node_modules/3dmol/package.json` version `2.5.5`. Not measured in a browser.
- repro: Open and close the job detail drawer twenty times, then in devtools count the window `resize` listeners (`getEventListeners(window).resize.length` in Chrome) — expectation from this reading is one per viewer ever created, none removed. Then drag the dock's resize handle and watch the frame count: every orphan re-renders too.
- observed: The three components each end their init effect's cleanup with the container clear the architecture documents:

  `frontend/src/molecule/MoleculeViewer.tsx:111-115`
  ```ts
  return () => {
    stopThemeWatch();
    if (containerRef.current) containerRef.current.innerHTML = "";
    viewerRef.current = null;
  };
  ```

  That detaches the `<canvas>` and drops the app's own reference. It does not make the `GLViewer` unreachable, because the constructor registers five things that are never removed — `frontend/node_modules/3dmol/src/GLViewer.ts:729-755`:

  ```js
  document.body.addEventListener('mouseup', this._handleMouseUp.bind(this));
  document.body.addEventListener('touchend', this._handleMouseUp.bind(this));
  ...
  window.addEventListener("resize", this.resize.bind(this));
  if (typeof (window.ResizeObserver) !== "undefined") {
      this.divwatcher = new window.ResizeObserver(this.resize.bind(this));
      this.divwatcher.observe(this.container);
  }
  if (typeof (window.IntersectionObserver) !== "undefined") {
      ...
      this.intwatcher.observe(this.container);
  }
  ```

  `GLViewer` exposes no `destroy()`/`dispose()` (the architecture already records this), so those bound closures keep every viewer ever created alive, along with its scene graph, geometry buffers and detached canvas.

  There is a second, visible cost. `this.divwatcher` observes `this.container`, and in this app the container is a stable `<div ref={containerRef}>` that survives the viewer swap — `MoleculeViewer.tsx:90-91` clears that same div and builds a new viewer inside it. So after a Strict-Mode double-invoke or any rebuild, *both* the orphan and the live viewer's observers fire on the same element, and the orphan runs `resize()` (`GLViewer.ts:1459`) which re-reads the box, calls `renderer.setSize()` and re-renders into a canvas nobody can see. Every window resize does the same thing to every orphan.
- expected: A viewer that has been replaced should stop consuming work and memory. The architecture's own framing of the original bug — "browsers cap live WebGL contexts per page... once exhausted, every new context silently fails to initialize" — is the right *concern*; the container clear addresses the DOM symptom rather than the reachability.
- evidence: `frontend/node_modules/3dmol/src/GLViewer.ts:729-755` (registration), `:1459-1480` (`resize`, which the orphans keep receiving); `frontend/src/molecule/MoleculeViewer.tsx:111-115`, `frontend/src/jobs/MoCubeViewer.tsx:119-123`, `frontend/src/jobs/ModeAnimationViewer.tsx:69-74`.
- pointer: `innerHTML = ""` removes a DOM reference. The listener lists on `document.body` and `window` are a separate, stronger reference the cleanup never touches.
- note: What would settle it: hold a `WeakRef` to each created viewer in a dev-only array, cycle the drawer, force GC in devtools, and check that none of the refs clear. Fix direction, in the cleanup of each of the three init effects, before nulling the ref: `(v as any).divwatcher?.disconnect(); (v as any).intwatcher?.disconnect();` — that removes the two observers and, importantly, the last reference from the *container* side. The `document.body` and `window` bindings cannot be removed from outside the library (the bound functions were never stored), so the honest options are an upstream patch adding a `destroy()`, or accepting the residual. Related and folded in here rather than filed separately: `ModeAnimationViewer.tsx:51`'s `rafRef` is declared and cancelled in cleanup but never assigned anywhere, left over from a `requestAnimationFrame` loop that `v.animate()` replaced — dead, and misleading about what the cleanup actually cancels.

---

### R-000: The architecture's WebGL-context-cap mechanism does not describe 3Dmol 2.5.5's render path, and nothing in the app recovers from a lost context

- surface: code:frontend
- class: docs
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:frontend
- scope: `docs/ARCHITECTURE.md`'s "The 3Dmol wrapper is deliberately imperative" and "The 3D viewer follows the theme by mutation, never by remount" sections, against `frontend/node_modules/3dmol` at the pinned `2.5.5`. Not reproduced.
- repro: With two viewers open (the molecule panel and a job drawer), run in devtools: pick either viewer's canvas, take `_3dmol_viewer.renderer.getContext().getExtension('WEBGL_lose_context').loseContext()`. Expectation from this reading: **both** viewers go blank simultaneously, because they share one context, and neither recovers until a window resize or a reload.
- observed: The architecture states the constraint as "browsers cap live WebGL contexts per page (commonly 8-16). Repeated mount/unmount exhausted that cap", and records the fix as verified by "live canvas count stays at exactly 1 across dozens of rapid cycles".

  In 2.5.5 the renderer takes a shared-context path whenever `OffscreenCanvas` exists, which it does in every browser this app targets — `frontend/node_modules/3dmol/src/WebGL/Renderer.ts:2136-2154`:

  ```js
  if (OffscreenCanvas && !(this.rows != undefined && ...)) {
      if (_gl_singleton == null || _gl_singleton.isContextLost()) {
          _offscreen_singleton = new OffscreenCanvas(this._canvas.width, this._canvas.height);
          _gl_singleton = _offscreen_singleton.getContext("webgl2", {...});
      }
      this._offscreen = _offscreen_singleton;
      this._gl = _gl_singleton;
      this._bitmap = this._canvas.getContext("bitmaprenderer", { alpha: true });
  }
  ```

  `_gl_singleton` is module-level (`Renderer.ts:25`). Every viewer draws into that one offscreen context, resizes it to its own canvas immediately before each render (`Renderer.ts:299-304`), and copies the result out with `transferToImageBitmap` / `transferFromImageBitmap` (`Renderer.ts:895-899`). Each *visible* canvas holds only a `bitmaprenderer` context, which is not the capped resource.

  Two consequences. The counted quantity ("DOM canvases") was never the capped one under this render path, so the verification does not support the claim. And a single shared context is a single point of failure with no handling in this app: if it is lost, `initGL` recreates it only when a *new* `Renderer` is constructed, so every already-mounted viewer keeps a dead `this._gl` and silently draws nothing. `GLViewer.resize()` does contain a recovery path (`GLViewer.ts:1463`, `if (this.renderer.isLost() && this.WIDTH > 0 ...)`) but it only fires on a resize event, and `grep -rn "webglcontextlost" frontend/src` returns nothing.
- expected: The architecture is the place a future session goes to understand why the viewers are written this way, and the recorded mechanism should match the code that ships. Note that nothing here argues the imperative wrapper or the container clear is *wrong* — both are still right, for the reachability reason in the previous finding.
- evidence: `frontend/node_modules/3dmol/src/WebGL/Renderer.ts:25`, `:2136-2154`, `:299-304`, `:895-899`; `frontend/node_modules/3dmol/src/GLViewer.ts:289` (the library's own per-canvas `webglcontextlost` listener, which the offscreen path's loss does not fire), `:1459-1480`; `docs/ARCHITECTURE.md`'s "The 3Dmol wrapper is deliberately imperative".
- note: Deliberately **not** claiming this explains the original blank-square report — the bug was found on whatever 3Dmol was installed then, and that history is not recoverable from the current tree. What is checkable now is the shipped render path. Two suggested actions: amend the architecture section to say the pinned version shares one context and that the container clear is justified by object reachability rather than by the context cap; and add a `webglcontextlost` listener on each viewer's canvas that calls `viewer.resize()` (the library's own recovery) and, failing that, shows a "reload to restore the 3D view" line instead of a blank square. The largest allocation the app makes against that shared context is `capturePng`'s up-to-4096 px re-render (`captureViewer.ts:94`, `:164-166`), which is the most likely trigger on a modest GPU.

---

### R-000: Every streamed token re-renders the whole chat transcript and re-parses every assistant message's markdown

- surface: code:frontend
- class: perf
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:frontend
- scope: `chat/ChatPane.tsx`, `chat/MessageBubble.tsx`, `lib/chatStore.ts`. React 19.2 with no React Compiler (`frontend/vite.config.ts` has a plain `react()` plugin, no `babel-plugin-react-compiler`), and `react-markdown` 10.1 has no internal memo (`grep -n "memo(" node_modules/react-markdown/lib/index.js` is empty). Not profiled.
- repro: Open a conversation with 30+ messages, ask something that produces a long answer, and record a React Profiler trace or a Performance trace during the stream. Expectation: one commit per token, each re-running `MessageBubbleRow` for every message in the list.
- observed: `frontend/src/chat/ChatPane.tsx:15-29` subscribes to the whole store with no selector:

  ```ts
  const {
    messages, streaming, activeSteps, turnInProgress, ...
  } = useChatStore();
  ```

  and `lib/chatStore.ts:178-185` writes a new `streaming` object on every token:

  ```ts
  case "token": {
    ...
    return {
      turnInProgress: true,
      streaming: { ...s.streaming, [messageId]: (s.streaming[messageId] ?? "") + delta },
    };
  }
  ```

  So every token is a store change, every store change re-renders `ChatPane`, and `ChatPane.tsx:189-191` maps the full history through an unmemoised component:

  ```tsx
  {messages.map((m, i) => (
    <MessageBubbleRow key={m.id ?? `pending-${i}`} message={m} />
  ))}
  ```

  `MessageBubbleRow` is a plain function (`MessageBubble.tsx:253`), and for an `AIMessage` it renders `AssistantBubble`, which runs `<ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>` (`MessageBubble.tsx:86`) — a full remark parse of that message's text, from scratch, on every render. `ToolResultChip` similarly re-runs `splitPaperBlocks` and `parsePlotArtifacts` (`MessageBubble.tsx:18-60`) per render.

  With a local model at a few tens of tokens per second and a conversation of a few dozen messages, that is on the order of a thousand markdown parses per second, all of them producing identical output.
- expected: A token append should re-render the streaming bubble and nothing else. The store's `token` case leaves `s.messages` untouched, so every element of `messages` keeps its identity across a token — the memo boundary is available for free.
- evidence: `frontend/src/chat/ChatPane.tsx:15-29`, `:189-191`; `frontend/src/chat/MessageBubble.tsx:78-99`, `:253-267`; `frontend/src/lib/chatStore.ts:178-185`.
- pointer: A whole-store subscription feeding an unmemoised list whose leaves do real parsing work.
- note: What would settle it: React Profiler during a stream, or simply `console.count()` in `AssistantBubble`. Fix direction, smallest first: wrap the export as `export const MessageBubbleRow = memo(function MessageBubbleRow({message}) {...})`. Because the `token` reducer does not touch `messages`, that alone removes essentially all of the cost. Narrowing `ChatPane`'s subscription to per-field selectors is a second, larger step and is not needed for the win. This is the only place in the frontend where memoisation is actually missing — the list panels (`JobManagerPanel`, `ConversationList`, `ProjectsSection`) all memoise their filter/sort correctly.

---

### R-000: Three of the four multi-frame viewers never check `response.ok` and have no `.catch`, so an artifact that fails to load shows "Loading..." forever

- surface: code:frontend
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:frontend
- scope: `ScanFrameViewer` (pes_scan/interp_pes masters), `GeometrySetViewer` (geometry_set), `EnsembleFrameViewer` (wigner_ensemble). `NebFrameViewer` (neb_ts) does it correctly and is the counter-example. Engine-independent — these read job artifacts, not engine output.
- repro: Open a scan master's drawer for a job whose `path_xyz` has been evicted or whose artifact route 404s (an archived job whose files were cleaned, or any 500 from the artifact route). The panel renders `Loading scan path...` indefinitely, with an unhandled promise rejection in the console and no way to tell whether it is slow or broken.
- observed: `frontend/src/jobs/ScanFrameViewer.tsx:45-56`

  ```ts
  fetch(jobArtifactUrl(job.job_id, "path_xyz"))
    .then((r) => r.text())
    .then((text) => {
      if (!cancelled) setFrames(parseMultiFrameXyz(text));
    });
  return () => { cancelled = true; };
  ```

  No `r.ok` check, so a JSON error body (`{"detail": "..."}`) or an HTML error page is handed to `parseMultiFrameXyz`; and no `.catch`, so a network failure or a throw inside the parser becomes an unhandled rejection that never reaches the UI. `frames` stays `null` and line 58-60 renders `Loading scan path...` permanently.

  `GeometrySetViewer.tsx:162-173` and `EnsembleFrameViewer.tsx:42-53` are the same five lines, with `Loading geometry set...` and `Loading sampled geometries...` as the stuck states.

  `NebFrameViewer.tsx:44-56` is the one that got the treatment:

  ```ts
  fetch(jobArtifactUrl(job.job_id, "neb_frames"))
    .then((r) => { if (!r.ok) throw new Error(`${r.status} ${r.statusText}`); return r.text(); })
    .then((text) => { if (!cancelled) setFrames(parseMultiFrameXyz(text)); })
    .catch((e) => { if (!cancelled) setFetchError(String(e)); });
  ```

  and it renders `Couldn't load frames: {fetchError}` (`NebFrameViewer.tsx:96-99`).
- expected: The standing rule in `.claude` memory `fixes-span-all-engines-and-methods` is that a fix is carried across every path, not only the one where the bug was noticed. `NebFrameViewer` is that fix; the other three multi-frame viewers were left behind. A permanent spinner with no error is also the failure mode the architecture's per-region boundary work exists to avoid — except a boundary cannot catch this, because nothing throws into React.
- evidence: `frontend/src/jobs/ScanFrameViewer.tsx:45-56` and `:58-60`; `frontend/src/jobs/GeometrySetViewer.tsx:162-177`; `frontend/src/jobs/EnsembleFrameViewer.tsx:42-57`; `frontend/src/jobs/NebFrameViewer.tsx:44-56`, `:94-104`.
- pointer: `fetch` does not reject on 4xx/5xx, so the only signal a route failed is `r.ok`, and it is not read.
- note: What would settle it: `docker compose exec` a rename of one scan job's `path_xyz` on disk and open its drawer. Fix direction: lift `NebFrameViewer`'s three-line shape into one shared hook (`useArtifactFrames(jobId, key)`), so the next viewer added inherits it rather than re-deciding. All three failures are silent today because the fetches also bypass `lib/api.ts`'s `request()` (see the raw-fetch finding below).

---

### R-000: A half-typed message follows the user into whatever conversation they switch to

- surface: code:frontend
- class: bug
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:frontend
- scope: `chat/Composer.tsx` and its one mount site in `chat/ChatPane.tsx`. Not reproduced in a browser.
- repro: In conversation A, type "optimise the geometry of" into the composer without sending. Click conversation B in the sidebar. The text is still in the box, now over B's transcript. Press Enter and it is sent to B.
- observed: The composer's text is plain local state and nothing resets it on a conversation change — `frontend/src/chat/Composer.tsx:36`:

  ```ts
  const [text, setText] = useState("");
  ```

  `setText` is called in exactly three places (`Composer.tsx:114` the welcome-screen prefill, `:162` after a successful send, `:281` the user typing). `ChatPane` renders `<Composer ... />` (`ChatPane.tsx:246-253`) with no `key`, and `ChatPane` itself is never unmounted on a thread switch — `useActiveThreadController` swaps the store contents in place (`lib/useActiveThreadController.ts:168-200`), which is deliberate and correct for the transcript.

  So the draft neither persists per conversation nor is cleared: it is a single global draft attached to whichever conversation happens to be open when Enter is pressed.
- expected: Either behaviour would be defensible; this is the one that is not. Every other piece of per-conversation state is swapped by `loadThread` (`useActiveThreadController.ts:178`), whose own comment explains that leaving the previous thread's content on screen "would visibly flash the old conversation's messages/molecule under the newly-active thread's identity". A draft is the same class of state and was not included.
- evidence: `frontend/src/chat/Composer.tsx:36`, `:114`, `:162`, `:281`; `frontend/src/chat/ChatPane.tsx:246-253`; `frontend/src/lib/useActiveThreadController.ts:168-200`.
- pointer: Component-local state in a component that outlives the thing it belongs to.
- note: What would settle it: type into the composer, switch conversations, look. Fix direction, in order of increasing value: `key={activeThreadId}` on `<Composer>` clears it (and drops the draft, which is the lesser evil); or a `Record<threadId, string>` in a small zustand store so each conversation keeps its own draft, which is what a user who switches to check a result and comes back would expect. `lib/composerDraftStore.ts` already exists for the prefill path and is the natural home, though note its current single-slot `{draft, nonce}` shape is for a different job and should not just be overloaded.

---

### R-000: Every selection row in the app is a `div`/`tr` with an `onClick` and no role, `tabIndex` or key handler, so conversations, jobs, orbitals and modes cannot be reached from the keyboard

- surface: code:frontend
- class: comfort
- severity: S3
- cause: CODE
- confidence: suspected (code read)
- found by: audit:frontend
- scope: A scan of every `.tsx` in `frontend/src` for an element opening tag carrying `onClick` but neither `role=` nor `tabIndex`. Seven components; listed in full below. Radix-based controls (dialogs, popovers, tooltips) and all `<button>`s are excluded and are fine.
- repro: Load the app and press Tab repeatedly. Expectation from this reading: focus never lands on a conversation in the sidebar, a job row in either job list, an orbital row, a vibrational-mode row, a plot card, or a project's job row. Every one of those is a mouse-only target.
- observed: The scan (a small Python regex over each file's element opening tags) returns:

  | file:line | element | what it selects |
  |---|---|---|
  | `chat/ConversationList.tsx:154` | `div` | open a conversation |
  | `jobs/JobsPanel.tsx:72` | `tr` | open a job's drawer |
  | `jobs/JobManagerPanel.tsx:320` | `tr` | open a job's drawer |
  | `jobs/OrbitalTable.tsx:136` | `tr` | choose which orbital the isosurface shows |
  | `jobs/VibrationTable.tsx:64` | `tr` | choose which normal mode animates |
  | `plots/PlotsPanel.tsx:130` | `li` | open a plot |
  | `projects/ProjectFlyout.tsx:137` | `tr` | open a job filed in a project |

  For example `frontend/src/jobs/JobManagerPanel.tsx:319-338`:

  ```tsx
  <tr
    key={job.job_id}
    data-testid={`jobmanager-row-${job.job_id}`}
    onClick={() => setOpenJobId(job.job_id)}
    ...
  >
  ```

  Two of these are scientific controls rather than navigation: `OrbitalTable` and `VibrationTable` are how a user picks which orbital and which vibrational mode to look at.
- expected: The codebase already knows how to do this and does it elsewhere. `frontend/src/jobs/FrameScrubber.tsx:93` carries `tabIndex={0}`, and its own comment at `:113` records the lesson: *"`tabIndex` alone only made it reachable by Tab"* — so it handles keys too. The scrubber exists as "a second way to move through a long list without aiming at rows" (`docs/ARCHITECTURE.md`), which is currently the *only* keyboard way, and it is shown only when a panel is expanded (`JobDetailDrawer.tsx:1010`, `:1478`).
- evidence: The seven sites above; `frontend/src/jobs/FrameScrubber.tsx:93` and `:110-120` as the in-repo counter-example.
- pointer: Rows were built as styled table rows rather than as controls, so no affordance was inherited.
- note: What would settle it: tab through the running app, or an axe-core pass. Fix direction: one shared `rowProps(onActivate)` helper returning `{role: "button", tabIndex: 0, onClick, onKeyDown}` handling Enter and Space, applied at all seven sites — the same "one owner for the pattern" reasoning `ExpandablePanel` records for the overlay control row. Filed as `comfort` rather than `bug` per the brief's framing, but note the two table cases are the scientific selection path, not chrome. Checked and clean alongside this: every icon-only button in the app carries either `title` or `aria-label` (scan of all `<button>` elements with no text child found none missing both), and every modal and flyout is Radix, so focus trapping and Escape are handled.

---

### R-000: `main.tsx`'s comment says no query in the app sets `refetchInterval`; thirteen of them do

- surface: code:frontend
- class: docs
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:frontend
- scope: `frontend/src/main.tsx` against `frontend/src/lib/queries.ts`.
- repro: `grep -c refetchInterval frontend/src/lib/queries.ts`.
- observed: `frontend/src/main.tsx:17-21`:

  ```ts
  // Job/thread/state data is kept fresh by SSE push (see server/sse.py),
  // not by polling -- refetchInterval is deliberately never set on any
  // query in this app. staleTime just avoids redundant refetches on
  // component remount for data that hasn't been invalidated.
  staleTime: 10_000,
  ```

  `lib/queries.ts` sets `refetchInterval` thirteen times, across these hooks: `useJobsQuery` (4 s fallback), `useJobsListQuery` (4 s), `useProjectsQuery` (8 s), `useJobsQuotaQuery` (30 s), `useJobQuery` (4 s fallback), `useJobChildrenQuery` (3 s), `useWignerTransitionsQuery` (3 s), `useKbQuotaQuery` (30 s), `usePlotsQuery` (8 s), `useUploadsQuotaQuery` (30 s), `useJobLogQuery` (1.5 s), `useShareInboxQuery` and `useShareOutboxQuery` (8 s).
- expected: This is the first file anyone reads when asking "how much does one open tab cost", and it currently answers "nothing", which is off by roughly fifty requests a minute.
- evidence: `frontend/src/main.tsx:17-21`; `frontend/src/lib/queries.ts:40-213`.
- note: Trivial to fix and worth fixing because of what it is: the file that sets the global default is where someone will look before adding the fourteenth interval. Suggested replacement text: SSE push is the fast path for the active conversation's own data; anything cross-conversation (the job manager, projects, plots, shares) and anything with no event behind it is polled, per-hook, in `queries.ts`.

---

### R-000: Several raw `fetch()` call sites bypass `lib/api.ts`'s `request()`, so their 401 and 503 never reach the auth or maintenance handlers, and one download name ignores the naming convention

- surface: code:frontend
- class: bug
- severity: S4
- cause: CODE
- confidence: suspected (code read)
- found by: audit:frontend
- scope: All `fetch(` call sites outside `lib/api.ts`'s `request()`, plus `downloadPlotPng` inside it. Not reproduced.
- repro: With a job drawer open showing an orbital, expire the session (log in as the same user in another browser, which supersedes the Redis session key). Click a different orbital row. Expectation: the viewer shows `Couldn't load orbital: Error: 401 Unauthorized` and the app stays on screen, rather than returning to the login screen the way any `request()`-routed call would.
- observed: `request()` is where the 401 and the maintenance-503 hooks live (`lib/api.ts:236-242` and `:221-235`). These call sites do not go through it: `jobs/MoCubeViewer.tsx:178` (the orbital cube POST/GET), `jobs/ScanFrameViewer.tsx:48`, `jobs/GeometrySetViewer.tsx:165`, `jobs/EnsembleFrameViewer.tsx:45`, `jobs/NebFrameViewer.tsx:45` and `:63`, and `lib/api.ts:481` (`downloadPlotPng`, which re-implements the error branch by hand and omits both hooks).

  Separately, `downloadPlotPng`'s fallback filename does not follow the convention — `frontend/src/lib/api.ts:491`:

  ```ts
  downloadBlob(await res.blob(), filenameFromResponse(res) ?? `${jobId}_${kind}.png`);
  ```

  `${jobId}` is the raw id, not the job's `filename_stem`, and `${kind}` is an internal identifier (`uvvis_inline`, `optimization_energy`), so the fallback lands as e.g. `78a32a61e4f2...b1_uvvis_inline.png`. The header is normally present, so this is a fallback path only — but `filenameFromResponse` (`lib/api.ts:460-463`) matches only a quoted `filename="..."`, so an unquoted or `filename*=` header falls through to it.
- expected: `docs/ARCHITECTURE.md`'s "Who names a download depends on who knows its extension" states the shape as `{safe job name}_{descriptor}{extension}`, and `lib/jobFilename.ts` exists to build exactly that browser-side. The fallback should be `jobDownloadName(jobFilenameStem(job), kind, ".png")`, which needs the job row rather than just its id.
- evidence: `frontend/src/lib/api.ts:205-244` (`request`), `:478-492` (`downloadPlotPng`), `:460-463`; `frontend/src/jobs/MoCubeViewer.tsx:178`.
- note: Low severity on both halves. The maintenance case in particular is already covered in practice — `useJobsListQuery`'s unconditional 4 s poll goes through `request()` and trips `MaintenanceGate` within seconds of an update starting, which is exactly the mechanism `lib/api.ts:194-198` describes. The 401 case is the one with a real user-visible symptom (a stale-session tab whose viewers show raw HTTP errors instead of bouncing to login), and `tests/frontend/fe_sec_*` is where a check for it would belong. Fix direction: give `api.ts` an exported `requestText(path, init)` that shares `request()`'s error branch and returns text, and route all six viewer fetches through it; that also gives the three frame viewers in the finding above their `r.ok` check for free.

---

## Checked and clean

Reported per the brief, so the next reader knows what was covered rather than only what failed.

**Request volume at idle.** Counted from `lib/queries.ts`, assuming one tab, every dock and rail section expanded, and no job running. `useJobsListQuery` 4 s (15/min), `useProjectsQuery`, `usePlotsQuery`, `useShareInboxQuery`, `useShareOutboxQuery` 8 s (7.5/min each), `useJobsQuotaQuery`, `useKbQuotaQuery`, `useUploadsQuotaQuery` 30 s (2/min each) — about 51 requests/min, all against the lock-free routes. With a job running, add `useJobLogQuery` at 1.5 s (40/min) while its drawer is open and `useJobChildrenQuery` at 3 s (20/min) for a master. Three things make this defensible and were each verified rather than assumed. TanStack's `refetchIntervalInBackground` defaults to false, so nothing polls while the tab is unfocused. `CollapsibleSection` unmounts its body when collapsed (`CollapsibleSection.tsx:153-160`), so collapsing a section genuinely stops its poll — this is why the numbers above are the worst case, not the normal one. And no two components poll the same endpoint: TanStack dedupes by key, and the one key that varies (`["jobs-list", includeArchived]`) has a single consumer. One nit, not filed: `useJobsQuotaQuery` sits in `RightDock` above the `if (rightDockCollapsed) return`, so it keeps polling with the dock shut — 2/min, not worth changing.

**Theming.** All four themes define `--bg` and `--text` as six-digit hex (`index.css:52,56,89,93,113,117,139,143`), which is what `themeColors.ts:265-270`'s `/^#([0-9a-f]{6})$/i` requires, so the silent fallback to graphite never fires. Subscription order is correct by construction: `appearanceStore.ts` registers `applyAppearance` in its module body (`:136`), and `themeColors.ts` imports that module, so the `<html>` attributes are always stamped before any viewer's subscriber reads `--bg`. No component reads a colour at mount and keeps it — `getComputedStyle` appears exactly once in `frontend/src` (`themeColors.ts:267`) and is called fresh on every theme change. No viewer remounts on a theme change; `watchViewerTheme` mutates the live viewer, as the architecture requires.

**Error boundaries.** `PanelErrorBoundary` wraps App (outside `AuthGate`), Sidebar, Chat, Instrument panel, Conversations, Knowledge base, Files, Projects, Shared with me, Molecule panel, Jobs list, Plots panel, Job manager, and the job drawer body. No region is uncovered. Radix portals keep their children in the declared React tree, so flyouts and dialogs inherit their opener's boundary — checked for `Flyout`, `ShareDialog`, `PlotFlyout`, `AdminPanel`.

**Focus and modals.** Every modal and flyout is `@radix-ui/react-dialog` (`Flyout.tsx`, `MoleculeBuilderModal.tsx`, `ShareDialog.tsx`, `JobDetailDrawer.tsx`, `AdminPanel.tsx`), so focus trapping, Escape and click-outside are the library's. `Flyout` additionally threads `onEscapeKeyDown` through for `SearchableText` to intercept, with a comment explaining why `stopPropagation` would not work.

**List rendering cost.** `JobManagerPanel`'s narrow-then-fuzzy-rank pipeline is two `useMemo`s on `[jobs, statuses, engines]` and `[narrowed, query]` (`JobManagerPanel.tsx:72-103`); `ConversationList` memoises both `threads` and `shown` (`:93-104`); `ProjectsSection` memoises its fuzzy filter (`:121-135`). TanStack's default structural sharing preserves `data` identity when a poll returns unchanged JSON, so those memos genuinely do not recompute on an idle tick. None of the lists is virtualised, which is a real ceiling at thousands of rows but not something the code does wrongly today. The one genuine memoisation gap is the chat transcript, filed above.

**Viewer effect dependency arrays.** `MoCubeViewer`'s fetch effect depends on primitives (`[selected, jobId, selIndex, selSpin, selGbw]`, `MoCubeViewer.tsx:203`) and aborts superseded requests with a 200 ms settle, exactly as the architecture's "a React dep array caused a hang" section describes. `ModeAnimationViewer`'s and `MoCubeViewer`'s label effects both carry the rebuild's own inputs (`[molecule, displacement, atomLabels]` and `[cubeText, isoval, atomLabels]`), which is correct and is why the atom-label backlog item is not a dependency problem. `JobDetailDrawer` derives `geometryMolecule`, `normalModes`, `irFreqs` and `orbitalTable` as plain property reads off `job.summary` (`:291-306`), so they keep their identity across a poll and do not restart the animation or refetch a cube.

**Animation loop lifecycle.** `ModeAnimationViewer`'s rebuild effect returns `v.stopAnimate()` (`:88-90`), which cancels every timer in `animationTimers` and zeroes 3Dmol's `animated` counter, and React runs all cleanups before all effects on a dependency change — so two loops cannot overlap on a fast mode switch. `useViewerAutoFit`'s `ResizeObserver` coalesces through one `requestAnimationFrame` and cancels it on unmount (`fitView.ts:419-441`). `NebFrameViewer`'s 3 s live-frames `setInterval` is cleared in its cleanup (`:78-81`).

**LiveLogPanel.** `useJobLogQuery(jobId, true)` passes a hardcoded `true`, which reads like a bug against the hook's "stops the instant it isn't running" contract, but the parent mounts it only inside `{job.status === "running" && ...}` (`JobDetailDrawer.tsx:451-455`), so the poll does stop. Its scroll handling correctly preserves a user's position (`LiveLogPanel.tsx:16-28`).

**Download naming.** `lib/jobFilename.ts`'s `slugifyLabel` iterates code points via `Array.from`, so a space, a slash and any non-ASCII character all become `_`, runs collapse, and leading/trailing separators are stripped — a molecule called `1,3-butadiene / β-form` becomes `1_3-butadiene_-_form`, safe for a filename and for a `Content-Disposition` header. Every call site checked: `MoleculeViewer.tsx:211-218` (slugifies its own fallback), `MoCubeViewer.tsx:330`, `ModeAnimationViewer.tsx:152` (its `"vibration.png"` fallback is unreachable — `JobDetailDrawer.tsx:1039-1045` always supplies a name), `JobDetailDrawer.tsx:96`, `:157`, `:198`, `:491`. Everything served by an API route passes `triggerDownload(url)` with no name, so the server's header wins, which is what the architecture requires. The one exception is `api.ts:491`, filed above.

**Global 401 and the auth gate.** `registerAuthErrorHandler` is wired once in `main.tsx:31-33`, `request()` fires it on any 401 except `/api/auth/me`'s own (`api.ts:236-242`), and `AuthGate` has distinct branches for 404 (auth not configured — renders the app), 401 (login screen), other errors (a reachable-server message), and loading. The maintenance-503 branch is checked *before* the 401 branch, with a comment explaining that an update drops every session and a tab that read that as an auth failure would bounce to a login screen it cannot get past. `tests/frontend/fe_sec_*` covers this ground.
