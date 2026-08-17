# E2E Test Findings Log

Running log. Each finding: ID, tag (CODE/ENV/LLM/DOC/UX/EXPECTED), severity, evidence, file:line.

---

> **All 26 findings were addressed on 2026-08-17** (branch `fix/e2e-findings-2026-08-16`, commits `1ae199e` and `0623415`). The 21 actionable ones are fixed; the 5 positive/expected/harness entries (F-011, F-015, F-016, F-021, F-025) never needed action. See **`e2e-fix-verification-2026-08-17.md`** for what was verified live versus what is only code-complete — the findings below are preserved as written, describing the state of the app *before* those fixes.

## F-001 — KB source deletion orphans the raw uploaded file on disk
**Tag:** CODE · **Severity:** Medium · **Phase:** 0 (pre-flight)

`DELETE /api/kb/sources/{source}` (`server/routes/kb.py:246-289`) calls `app/rag/store.delete_source()`, which removes the Chroma vector chunks but **never unlinks the raw uploaded file** at `UPLOADS_DIR/<owner>/<source>`. Compare `app/auth/storage_quota.py:334`, where `_evict()` for a `kind == "kb"` candidate *does* call `.unlink()`.

Compounding second-order effect: `purge_user_data()` (`storage_quota.py:506`) builds its KB candidate list from `_kb_candidates()`, which enumerates `app.rag.store.list_sources()` — i.e. from Chroma. Once the Chroma entry is gone, the orphaned file is invisible to that enumeration too, so deleting the owning user does **not** clean it up either. The file is unreachable by every cleanup path in the app.

Accounting impact: `_kb_usage_by_owner()` (`storage_quota.py:103-125`) also enumerates from Chroma, so an orphaned file is invisible to per-user quota accounting — but `app/rag/quota.py:36` `current_usage_bytes()` sums `KB_DIR + UPLOADS_DIR` off the filesystem, so on a no-auth deployment the orphan *does* count against the 10GB cap while being unreachable and undeletable through the API.

**Evidence (pre-wipe):** `data/uploads/` contained **31** per-user directories while the DB held 1 user and `ownership_index` had **0** rows. Every directory contained a `qatest_collision_doc.txt` — the fixture from `tests/backend/sec_09_kb_delete_filename_collision.py`, which registers two users, uploads an identically-named doc for each, deletes the source, then deletes the users. 23MB total. Directory listing saved to `phase0_orphan_uploads.txt`.

Also note `_evict()` unlinks the file but never removes the now-empty `UPLOADS_DIR/<owner>/` directory, so empty per-user dirs accumulate even on the path that does work.

**To confirm on the clean stack:** register a user, upload a KB source, `DELETE` it, assert the file is gone from disk. Then repeat with a user deletion instead.

---

## F-002 — `data/scraped/promoted_sources/` holds pyscf.org pages fetched without a robots.txt check
**Tag:** UX/policy · **Severity:** Low · **Phase:** 0 (pre-flight)

`data/scraped/promoted_sources/` holds 11 scraped pyscf.org HTML pages. `scripts/seed_knowledge_base.py` deliberately does **not** crawl pyscf.org — its module docstring states pyscf.org's `robots.txt` disallows ClaudeBot (`Content-Signal: ai-train=no`), which is why PySCF reference docs are generated from the installed package's docstrings instead. These files therefore came from the app's own user-initiated "add a web page" KB feature (`POST /api/kb/sources/url` → `app/rag/web_scrape.fetch_page`), which writes into `_SCRAPED_DIR` (`server/routes/kb.py:39`).

Confirmed in the numbers: Chroma held **205** sources; the seeder's own `ingest_all()` walks only `bagel`/`orca`/`pyscf` (48 + 137 + 9 = **194**); 205 − 194 = **11** = the promoted_sources count. So they were ingested by the URL-add route, not the seeder.

This is a user action rather than autonomous crawling, so it is a different act from what the seeder's policy covers — but `fetch_page` consults no `robots.txt` at all, meaning the app will happily fetch and ingest from a site that disallows it, with no warning to the user. Worth a decision, not necessarily a fix.

---

## F-003 — `looks_like_smiles` charset gate rejects every halogen and metal SMILES, and the resulting error tells the user to do the thing they just did
**Tag:** CODE · **Severity:** High · **Phase:** 0/4 (CONFIRMED empirically, 12/12 checks)

**Live result on the clean stack** — every one of these is a valid SMILES per RDKit, and 5 of 6 fail outright:

| input | valid SMILES? | passes gate | resolves | outcome |
|---|---|---|---|---|
| `ClC=CCl` | yes | **no** | **no** | ValueError |
| `BrCC` | yes | **no** | **no** | ValueError |
| `CC(=O)Cl` | yes | **no** | **no** | ValueError |
| `[Fe]` | yes | **no** | **no** | ValueError |
| `[Na+].[Cl-]` | yes | **no** | **no** | ValueError |
| `[SiH4]` | yes | **no** | yes (PubChem name lookup) | accidentally correct |

Controls (`CCO`, `c1ccccc1`, `O=C=O`, `water`) all resolve correctly, and a pasted XYZ block is a working workaround.

**The error message is the sharpest part of this.** The user typed a SMILES string and got back:

> `Could not resolve 'ClC=CCl' to a structure via PubChem or OPSIN. Please supply a SMILES string instead.`

It instructs the user to do exactly what they already did. Someone hitting this has no path to the real cause.

Mitigating: the dominant failure mode is a hard error, not a silently-wrong molecule — only `[SiH4]` resolved, and it happened to resolve correctly. So this is a "the tool refuses common input" bug rather than a "the tool computes the wrong thing" bug.

**Fix is small:** move the `Chem.MolFromSmiles(text) is not None` check ahead of (or in place of) the charset gate. RDKit already answers the question the charset heuristic is approximating, and it answers it correctly.

`app/chemistry/molecule.py:339` gates SMILES detection on

    allowed = set("BCNOPSFIHKcnosp0123456789()[]=#@+-\\/.%")

There is no `l`, `r`, `i`, `e`, `a`, `t`, `u`, `g`, or `d` — i.e. none of the second letters of any two-letter element symbol outside the organic subset. `Chem.MolFromSmiles` is only consulted *after* this gate (line 342), so RDKit never gets the chance to validate a perfectly good SMILES.

`resolve_molecule` (line 345) then falls through to `molecule_from_name()`, which does a **PubChem/OPSIN lookup of the literal SMILES string as if it were a compound name**.

Affected, all valid SMILES: `ClC=CCl`, `BrCC`, `CC(=O)Cl`, `[Fe]`, `[Na+].[Cl-]`, `[SiH4]`. Halogenated organics are first-day input for a computational-chemistry tool.

Characterized by `tests/e2e/e2e_05_molecule_resolution.py`.

---

## F-004 — Container-written files under `data/` are root-owned and unremovable by the host operator
**Tag:** UX/deployment · **Severity:** Medium · **Phase:** 1

The `api` image has no `USER` directive (deliberate — see the Dockerfile's OpenMPI-as-root note), so everything it writes into the `./data:/app/data` bind mount is owned by root on the host. Tearing down the stack and running `rm -rf data/jobs data/uploads` as the host user fails with `Permission denied` on every file. Recovery required a throwaway container (`docker run --rm -v "$PWD/data:/d" alpine …`).

An operator cannot inspect-and-clean their own data directory, take a backup with their own user, or recover disk space without either root or a container. Worth either a `USER` directive with a matching host uid/gid, or documenting the container-based cleanup recipe in the README.

---

## F-005 — `QC_AGENT_N_CORES` in docker-compose.yml is an unguarded single point of failure
**Tag:** CODE/UX · **Severity:** Medium · **Phase:** 1 (verified live)

Confirmed directly on the fresh stack:

    QC_AGENT_N_CORES=8   OMP_NUM_THREADS=unset   nproc=255
    N_CORES without the compose env var: 255

The container has no `OMP_NUM_THREADS` (unlike this host's shell profile, which is what makes `nproc` return 8 there), so `_detect_usable_cores()` reads the host's full 255 logical CPUs. The **only** thing preventing that is the explicit `QC_AGENT_N_CORES: ${QC_AGENT_N_CORES:-8}` line in `docker-compose.yml`.

If that line is dropped, overridden by a deployment-specific compose file, or the service is run outside compose, `JobManager._wait_for_resources` waits for 255 genuinely idle cores that will never exist and **every job hangs `pending` forever**, with no error anywhere. This already happened once (documented deployment bug 3). There is no startup assertion or warning guarding it.

Suggested: a startup log line, or a sanity check that warns when `N_CORES` exceeds some multiple of the cgroup/affinity-visible CPUs.

---

## F-006 — No `.dockerignore`: 370MB of build context, and host `node_modules` overwrites the image's own `npm ci`
**Tag:** CODE · **Severity:** Medium · **Phase:** 1 (measured)

Measured on this run: `docker compose build --no-cache` sent **370.1MB** of build context and took **470s**.

There is no `.dockerignore` at the repo root or in `frontend/`. The context therefore includes `data/` and `frontend/node_modules` (753MB on disk before the `data/` wipe reduced it).

Worse than slow, it is incorrect: the Dockerfile's frontend stage is

    COPY frontend/package.json frontend/package-lock.json* ./
    RUN npm ci                 # builds container-native node_modules
    COPY frontend/ ./          # <-- overwrites it with the HOST's node_modules
    RUN npm run build

So the `npm ci` layer's output is discarded every build, and the in-image build actually runs against whatever the host happened to have installed. It worked here only because the host is the same linux/x64 with the same Node 20; a developer on macOS or ARM would ship platform-mismatched native binaries into the build. The container build completed in 3.26s, which is itself the tell — it reused the copied host modules rather than its own.

Fix: add a `.dockerignore` containing at least `node_modules`, `data`, `.git`, `frontend/dist`.

---

## F-007 — Ketcher requires Node >= 24.14.1; both the Dockerfile and the documented host env use Node 20
**Tag:** CODE · **Severity:** Low · **Phase:** 1 (observed during build)

Both the host build and the in-image build emit:

    npm warn EBADENGINE Unsupported engine {
    npm warn EBADENGINE   package: 'ketcher-core@3.17.2',
    npm warn EBADENGINE   required: { node: '>=24.14.1' },
    npm warn EBADENGINE   current: { node: 'v20.20.2', npm: '10.8.2' } }

…for `ketcher-core`, `ketcher-react`, and `ketcher-standalone`. The Dockerfile pins `node:20-slim`, and `CLAUDE.md` instructs creating a `node20` conda env. The build succeeds and the 2D sketcher works, but the project is running its largest dependency outside its supported engine range.

---

## F-008 — XN-14 confirmed: no `agent_step` SSE events after an approval resume
**Tag:** UX/observability · **Severity:** Low · **Phase:** 3.5 (verified live)

Pre-registered as XN-14 and now confirmed empirically by the harness gate: `agent_step` events observed after `POST /approvals/job` = `[]`.

`_run_turn` publishes `agent_step` only from its streaming `"updates"` loop. `approve_job` resumes via `resume_turn()` — a single blocking `.invoke()` — then calls `_publish_new_messages()`, which emits only `message` events. Every tool call in the post-resume tail of a turn (including the re-executed `submit_job` itself and any follow-up `check_job_status`) is therefore invisible to `AgentStepChips`.

Consequence for the user: after clicking Approve, the UI shows no per-tool progress at all until the whole tail completes. Not a correctness bug; a real observability gap, and the reason this suite uses state-diffing rather than SSE as its primary assertion channel.

---

## F-009 — Time-to-first-token is ~19s on a simple opening turn
**Tag:** UX/perf · **Severity:** Medium · **Phase:** 3.5 (measured)

Harness gate, `set_molecule("water")` turn: **time-to-first-token 18.76s**, full turn 19.5s. The model produced its tool call and completed the whole turn essentially at the moment the first text token appeared.

The UI does show an `AgentStepChips` spinner during this window, so it is not a blank screen — but ~19s before any text on the simplest possible request is a significant perceived-latency issue for a conversational tool. Worth measuring across the full scenario set (this suite records `ttft` per turn into `tests/e2e/results/*.jsonl`) and considering whether a smaller/faster model or a warmed context would help.

---

## F-010 — `GET /api/job-registry` is the one route in the app with no auth at all, and structurally cannot have any
**Tag:** CODE · **Severity:** Low · **Phase:** 3 (verified live)

A full sweep of all **57** `/api/` routes (inventory pulled from the app's own `/openapi.json`, not hand-written) found exactly one unauthenticated 2xx outside the three documented public routes:

    GET /api/job-registry -> 200   (11,992 bytes, no cookie)

It returns the complete capability map: `methods`, `default_engine`, `allowed_engines`, `required_params`, `optional_params`, `param_help`. No user data and no secrets — this is deployment metadata, not a data leak.

The structural part is what makes it worth fixing rather than waiving: `server/routes/registry.py`'s handler takes **no `Request` parameter at all**, so it cannot call `current_user_or_none()` even if someone wanted to gate it. Every other route in the app takes a `Request` and is gated. If the public `:443` listener is ever enabled, an unauthenticated internet visitor can enumerate exactly which QC engines and methods this lab runs.

Everything else was clean: **14/14** `/api/admin/*` routes return 403 to a non-admin, and every cross-user thread route returns **404** — identical to the response for a genuinely nonexistent thread, so there is no existence leak (verified separately with valid request bodies; see F-011).

---

## F-011 — HARNESS note: FastAPI validates request bodies before ownership checks
**Tag:** HARNESS · **Severity:** n/a — recorded so it is not mistaken for a defect

An initial version of the route sweep sent `{}` as the body for every state-changing method. FastAPI validates the request body against the Pydantic schema *before* the handler runs, so routes with required fields (`RenameThreadIn.label`, `MessageIn.text`) returned **422** without ever reaching `_require_thread`'s ownership check — which read like a missing guard.

Re-probed with valid bodies: every cross-user route returns **404**, the target thread's label was verifiably unchanged, and a nonexistent thread returns the same 404. Ownership enforcement is correct. The sweep now carries a per-route `VALID_BODIES` table so this cannot recur.

---

## F-012 — `sec_09`'s pass output prints a failure-phrased explanation
**Tag:** DOC/test-quality · **Severity:** Low · **Phase:** 2 (observed)

`tests/backend/sec_09_kb_delete_filename_collision.py` emits, on a **passing** check:

    [PASS] FIX VERIFIED: user B's UNRELATED, identically-named source survived the
    owner-scoped delete -- user B's source was also deleted -- the owner scoping
    isn't actually isolating the two

`fixtures.check(name, condition, detail)` prints `detail` unconditionally, and this call site passes failure-phrased text as `detail`. The check genuinely passed; the line reads as though it failed. Anyone reviewing suite output — exactly the audience for a pre-deployment run — will misread it. The detail should be conditional, or phrased neutrally.

---

## Regression baseline (Phase 2) — clean

`bash tests/run_backend.sh` on the freshly installed stack: **22/22 scripts, every check passing, 0 failures.** `tests/backend/sec_10_*` (opt-in, excluded from the default run as destructive-shaped) also passes 2/2. Every previously-fixed finding (SEC-01 through SEC-10, SEC-08b, PERF-01/02/03, the three FE-SEC items) holds on a clean install.

---

## F-013 — The instrument panel's "Collapse panel" button is completely covered by the "Log out" button, at every viewport size
**Tag:** CODE/UX · **Severity:** **High** · **Phase:** 5 (verified live, all viewports)

`AccountBar` is absolutely positioned in the top-right corner:

    class="pointer-events-none absolute right-2 top-2 z-30 flex items-center gap-1.5"
    position: absolute, z-index: 30

`RightDock`'s header — which carries the `[title="Collapse panel"]` button — is `position: static, z-index: auto`, and lays out immediately beneath it.

The collapse button therefore sits **underneath** the AccountBar's own buttons. Measured with `document.elementFromPoint()` at the collapse button's exact centre:

| viewport | collapse button centre | element actually on top |
|---|---|---|
| 1280×800 | (1255, 22) | **"Log out"** |
| 1440×900 | (1415, 22) | **"Log out"** |
| 1600×900 | (1575, 22) | **"Log out"** |
| 1920×1080 | (1895, 22) | **"Log out"** |
| 2560×1440 | (2535, 22) | **"Log out"** |

Two consequences, and the second is the serious one:

1. **The instrument panel cannot be collapsed at all.** Playwright times out after 30s waiting for the button to become actionable; a real user's click never reaches it either.
2. **Clicking where the collapse button appears logs the user out.** This is a destructive misclick on a control the user believes is a layout toggle — the worst possible thing to be sitting underneath.

The `pointer-events-none` on the AccountBar container shows this class of collision was anticipated, but the child buttons necessarily re-enable pointer events, so the guard does not help for the buttons themselves — only for the empty gaps between them.

Note the mirror control on the left (`[title="Collapse sidebar"]`) works correctly — the AccountBar is right-aligned, so only the right dock is affected. Verified: collapse/expand of the sidebar passes.

**Suggested fix:** give `RightDock`'s header a higher stacking context than the AccountBar, or reserve horizontal space for the AccountBar in the dock header's own layout (e.g. right-padding equal to the AccountBar's width) rather than letting them share the same coordinates.

This is the highest-severity UI finding of the run and is a strong argument for the broader `data-testid` recommendation: it was found only because an automated click *timed out*. No amount of code reading would have surfaced it, and a human tester who never tries to collapse the right panel would not notice either.

---

## F-014 — The 2D sketcher shows a blank screen for ~3.5s with no loading indicator
**Tag:** UX · **Severity:** Medium · **Phase:** 5 (measured)

`MoleculeBuilderModal` is `React.lazy` with `<Suspense fallback={null}>`, and its chunk is **28.7MB** (8.5MB gzipped) — by far the largest asset in the build, larger than every other chunk combined.

Measured: **3,484ms** from clicking "Build a molecule (2D sketcher)" to the modal's first paint, on a fast local connection with a warm server. Because the Suspense fallback is `null`, the user sees *nothing at all* during that window — no spinner, no skeleton, no dimming. The click appears to have done nothing.

On a slower campus network this gets materially worse, and 8.5MB gzipped is a real download on a first visit. A `fallback` with even a minimal spinner would cost nothing and remove the "is this broken?" moment. The app already has a `.skeleton-shimmer` class and animation tokens for exactly this purpose, used elsewhere for list placeholders.

---

## F-015 — Positive: WebGL context management holds under churn
**Tag:** verified · **Phase:** 5

The documented `MoleculeViewer` fix (clear the container at the *start* of the init effect rather than in cleanup, because React 18 Strict Mode nulls the ref before running cleanup) was re-verified live: live `<canvas>` count stayed at exactly **1, 1, 1, 1** across four rapid enlarge-flyout mount/unmount cycles, and every viewer rendered real content (27,982-byte data URL at 790×480 in-panel; 71,618 bytes at 1214×1040 enlarged).

No context-cap exhaustion, no blank viewers. Verified via `canvas.toDataURL()` in `page.evaluate()`, since `page.screenshot()` cannot capture WebGL content.

---

## F-016 — Positive: BAGEL `frequency` completed end-to-end, upgrading its documented status
**Tag:** verified · **Phase:** 4

`CLAUDE.md` records BAGEL's `geometry_optimization`/`frequency` support as *"structurally confirmed and observed executing correctly rather than convergence-verified end-to-end,"* and asks for a full live test once the host's BAGEL/MKL install is behaving.

Matrix cell **M08 (frequency / bagel / water HF / STO-3G) completed in 26.2s** with a real summary carrying `frequencies_cm-1`, `df_basis_used`, `df_basis_exact_match`, and `dx_bohr`. That is a genuine convergence-verified result for BAGEL `frequency`, and the documentation can be upgraded accordingly.

BAGEL `geometry_optimization` (M05) is a different story — see F-017.

---

## F-017 — BAGEL CASSCF macro-iterations are ~85s on this host (RETRACTED as a finding — see the correction below)
**Tag:** ENV · **Severity:** Medium (deployment guidance, not a code defect) · **Phase:** 4

Matrix cell **M05 (geometry_optimization / bagel / CASSCF(4,4) / STO-3G on water)** did not reach a terminal state within a 600s budget, and an earlier unbounded attempt was still running after ~10 minutes.

Observed in the job's own output: CASSCF macro-iterations taking **84.75s each** for a trivial 3-atom STO-3G system (matching the ~80–96s figure already documented for this host), plus a non-fatal `Intel oneMKL ERROR: Parameter 9 was incorrect on entry to cblas_dgemm.` The energy sequence itself looked physically sensible (−74.978 Ha), so the calculation is *correct*, just impractically slow — a geometry optimization is many geometry steps × many macro-iterations at ~85s apiece.

Classified **ENV**, not CODE: BAGEL/MKL on this host is already documented as abnormally slow, the same job type completed structurally correctly, and the ORCA and PySCF CASSCF paths are fast.

> **Correction (2026-08-17).** The "deployment implication" originally recorded here — that this combination "should not be offered to users without a warning, because it will look like a hang" — was **wrong, and was retracted after the finding was reviewed with the group.**
>
> CASSCF and CASPT2 runs in this group routinely take **40–50 minutes, and sometimes hours**, depending on the number of atoms, the active space and the basis set. A calculation that runs for an hour is not a hang and does not need a warning; it is the ordinary case, and **the asynchronous job system exists precisely so that it is fine** — the user submits, leaves, and comes back to the result.
>
> What remains true and worth recording is the narrow, factual part: BAGEL's macro-iterations on *this specific host* are ~85s where ORCA and PySCF are sub-second for the same trivial system, which is an outlier attributable to this host's MKL/BAGEL install rather than to the method. That is a reason to prefer ORCA or PySCF *when a user wants a fast turnaround on a small system*, not a reason to steer anyone away from the engine.
>
> The property that genuinely matters for long jobs — that they survive their user logging out, and that the results and conversation are waiting on return — was untested when this finding was written. It is now covered end-to-end by `tests/e2e/e2e_17_logout_and_return.py`, **21/21**.

---

## F-018 — A malformed `custom` input is correctly diagnosed by the validator and then run anyway
**Tag:** CODE/design · **Severity:** Medium · **Phase:** 4 (verified live)

Matrix cell **M24 (custom / orca)**. The agent composed:

    !HF STO-3G
    * xyzfile 0 1
    O  0.000000  0.000000  0.117270
    H  0.000000  0.757170 -0.469080
    H  0.000000 -0.757170 -0.469080
    *

`* xyzfile` tells ORCA to read coordinates from an **external file** and expects a filename; the agent then supplied coordinates *inline*, which is the `* xyz` form. ORCA faithfully failed with a blank filename:

    The coordinates will be read from file:
    ORCA_ReadXYZFile::Error
    !!! CANNOT OPEN FILE   Filename:  !!!

The agent's mistake is a one-token slip (`xyzfile` vs `xyz`) and is `LLM`-class. **What makes this a finding is what the app did with it.** Running the app's own validator against that exact text:

    validate_input("orca", agent_text)  -> ["No geometry block found (expected a line like '* xyz <charge> <multiplicity>').") ]
    validate_input("orca", corrected)   -> []

The app **positively identified the exact defect and named the exact fix**, then ran the job anyway, because structural validation is deliberately non-blocking for `job_type='custom'`. 33 seconds of compute were spent producing an opaque ORCA file-not-found error instead of the accurate diagnosis the app already had in hand.

The non-blocking rationale is sound — `custom` exists precisely to carry ORCA/BAGEL syntax the validator was never built to recognize (`%coords` blocks, `$new_job` stacks, genuine `* xyzfile` usage with a real filename). But this case is not "unrecognized syntax"; it is a **positively-detected missing required element**. Those two deserve different treatment.

**Suggested fix:** keep warnings non-blocking by default, but distinguish "we do not recognize this construct" from "we recognize this construct and it is wrong." The latter — of which "no geometry block found" is the canonical case — warrants either a blocking confirm or much stronger visual treatment than the current yellow *"Structural check found possible issues (not blocking)"* banner, which is easy to click past.

---

## F-019 — `submit_job` is skipped on roughly 1 in 3 fully-specified requests
**Tag:** LLM-flaky · **Severity:** Medium · **Phase:** 4 (3× retry policy applied)

Matrix cell **M15 (tddft / orca)** failed its tool assertion on the first run, so the non-determinism policy was applied: three fresh-thread re-runs.

| attempt | tools called | result |
|---|---|---|
| original | `[]` | no tool call at all |
| 1 | `set_molecule`, `submit_job` | PASS |
| 2 | `set_molecule` | stopped after setting the molecule |
| 3 | `set_molecule`, `submit_job` | PASS |

**2/3 → `LLM-flaky`, ~33% miss rate.** The prompt was fully specified and ended with *"Please go ahead and submit it."* Two distinct miss modes were seen: no tools at all, and setting the molecule then stopping without submitting.

Nothing incorrect happens when it misses — the user simply has to ask again — so this is friction, not a correctness defect. But a third of job requests needing a second nudge is a real usability cost, and it is the kind of thing this codebase has an established pattern for fixing mechanically rather than by prompt (see the `want_oscillator_strengths` → ORCA routing precedent). Worth either prompt hardening around "the user has already authorized submission" or a follow-up nudge when a turn sets a molecule and stops while the user's message clearly requested a run.

Note the approval gate is unaffected either way: it is structural, so a missed `submit_job` simply means no job, never an unapproved one.

---

## F-020 — `recommend_active_space` can recommend a space too small for the number of states it was asked for
**Tag:** CODE · **Severity:** Medium · **Phase:** 4 (verified live)

Matrix cell **M26 (recommend_active_space / pyscf)**, water / STO-3G / 3 states, failed after 54s with:

    RuntimeError: The recommended active space (6e,3o) can host at most 1 many-electron
    configuration(s), fewer than the 3 states requested. This usually means the
    entropy-based selection converged on too small/degenerate a space for this many
    states -- try requesting fewer states, or raising max_active_orbitals if there's
    room under the current cap.

The tool's own entropy-based selection chose (6e,3o), then its own downstream check rejected that choice as incompatible with the request it was given. The error text is genuinely good — specific, honest about the likely cause, and actionable — but the failure arrives *after* the expensive selection step, as a failed job, on what is a completely reasonable user request (three low-lying states of water in a minimal basis).

The tool has the information to avoid this: it knows `n_states` before it selects, and it knows how many configurations a candidate space can host. It could constrain the selection to spaces that can accommodate the requested states, or clamp/repropose and explain, rather than doing the work and then failing.

Incidental positive from the same run: the job's `literature_notes` recorded *"Local paper KB empty; Semantic Scholar rate-limited; web search returned general CASSCF guidance"* — the documented four-source knowledge hierarchy degraded exactly as designed, including the expected Semantic Scholar 429.

---

## F-021 — EXPECTED: `neb_ts` correctly surfaces ORCA's "no barrier" rejection as a failed job
**Tag:** DESIGN (verified) · **Phase:** 4

Matrix cell **M23 (neb_ts / orca)** failed — correctly. ORCA reported *"No barrier was found. Skipping NEB-TS run here."*, produced **zero** occurrences of `ORCA TERMINATED NORMALLY`, and the app surfaced it as a `failed` job with the real reason rather than mishandling it or reporting a spurious success.

This matches the documented known limitation exactly: the toy ammonia-inversion endpoint geometry used here has no genuine barrier, and the app's handling of that ORCA-side rejection is the behavior the codebase already recorded as correct. Counted as a verified design confirmation, not a defect. The `neb_ts` ground-state path remains unverified end-to-end in this run because no test case with a real barrier was constructed.

---

## F-022 — Any authenticated user can read any other user's uploaded KB document
**Tag:** CODE (deliberate, but should be revisited) · **Severity:** **High** · **Phase:** 4 (verified live)

`GET /api/kb/sources/{source}/content` serves another user's private upload to any logged-in caller.

Reproduced on the clean stack with a file containing a marker string, uploaded by user A only:

| caller | status | private content returned |
|---|---|---|
| owner (user A) | 200 | **yes** |
| unrelated user B | **200** | **yes** |
| anonymous | 401 | no |

Controls confirming this is specific to the content route, not general breakage:
- `GET /api/kb/sources` correctly hides it — B's listing does not contain the file.
- `DELETE /api/kb/sources/{source}` correctly returns **404** for B, and A's source survives B's delete attempt.

So listing and deletion are properly owner-scoped; **only the content endpoint is not.**

**Root cause** — `_content_search_dirs()` in `server/routes/kb.py:72-85`. The route does pass `_owner_filter(request)`, but that helper then deliberately widens the search:

```python
if owner:
    # A shared/pre-seeded or another-owner's source can still be
    # PREVIEWED (get_source_content is read-only, no ownership check --
    # see that route below) ... so every owner subdirectory that
    # exists is searched, not just the caller's own
    dirs.extend(d for d in UPLOADS_DIR.iterdir() if d.is_dir())
```

This is **deliberate and documented**, not an oversight — which is why it deserves a considered decision rather than a silent patch. Two things argue for changing it:

1. The stated rationale — *"mirroring list_sources' 'shared plus mine' visibility, but slightly wider"* — does not match the behavior. `list_sources` is shared+mine; this is **shared + mine + every other user's**. That is not slightly wider, it is unrestricted.
2. The other justification, *"content preview was never ownership-gated even pre-retrofit,"* is a statement about legacy behavior, not a security argument. It is precisely the reasoning that SEC-06 overturned for `GET /api/jobs/{job_id}/artifacts/{key:path}`, which had the same shape and was fixed.

**Exploitability:** requires an authenticated account and knowledge of the filename. Filenames are highly guessable in this domain (`paper.pdf`, `manual.pdf`, `notes.txt`, `thesis.pdf`), and B cannot see A's filenames in their listing — but that is obscurity, not access control. For a lab deployment where users upload unpublished manuscripts and private notes, this is a real confidentiality gap.

**Fix:** restrict `_content_search_dirs` to the caller's own upload directory plus `_SCRAPED_DIR` (the genuinely shared corpus), keeping the admin/no-auth `owner is None` branch unchanged — which is exactly the scoping `list_sources` and the delete route already use.

---

## F-023 — An invalid hand-edit consumes the approval, so the user cannot fix it and retry
**Tag:** CODE/UX · **Severity:** Medium · **Phase:** 4 (verified live) · Also a **doc drift**

Editing an ORCA input on the approval card and introducing a structural error (an unterminated `%pal` block) behaves like this:

- `POST /api/threads/{id}/approvals/job` returns **200** `{"resumed": true}`
- the job is correctly **not** run — `submit_job` returns a ToolMessage: *"The edited orca input has problems and was NOT run: 1 '%...' block(s) appear unterminated…"*
- but the interrupt is **consumed**: the next attempt with a corrected input returns **409 "No job approval is pending on this conversation."**

The safety property holds — nothing invalid runs. The usability property does not: the user must restart the entire request rather than correcting the text on the card in front of them.

`CLAUDE.md` documents the opposite: *"a typo gets caught and displayed in place with no LLM round-trip, and the interrupt stays pending so the user can fix it and click 'Run edited' again."* That description is accurate for the retired Streamlit UI, where `render_approval_panel` validated **before** ever calling `resume_turn`. In the current React app the validation happens server-side inside `submit_job` (`app/agent/tools.py:1114-1123`), which is *after* the graph has already resumed — so the pause is spent either way.

Two things worth separating:
- The HTTP status is arguably wrong (200 for "your edit was rejected"), which also means a scripted client cannot tell success from rejection without parsing the transcript.
- The interrupt consumption is the real cost, and the fix is to validate in the route **before** calling `resume_turn` — restoring the documented behavior — or to re-raise a fresh interrupt on validation failure.

Either way `CLAUDE.md`'s claim should be corrected to match whatever ships.

---

## F-024 — `read_status()` reports a nonexistent job as `pending`
**Tag:** CODE (latent) · **Severity:** Low · **Phase:** 7 (verified live)

    read_status("zzzzznotarealjob")  ->  {'status': 'pending', 'message': '', 'updated_at': None}
    read_result("zzzzznotarealjob")  ->  None
    read_spec("zzzzznotarealjob")    ->  None

`read_status` (`app/chemistry/jobs/base.py:122-129`) returns a synthesized `pending` dict when `status.json` is absent, so **"queued" and "does not exist" are indistinguishable** to any internal caller. Its two sibling readers both return `None` for the same input, so the inconsistency is within one small module.

**User-facing behavior is correct** — `GET /api/jobs/<nonexistent>` returns a clean 404, because the route checks `read_spec` first. So this is a latent trap for future code rather than a live bug.

It did bite this run: after a bulk purge deleted a completed job, a check asking "is this job still running?" saw `pending` and concluded the job had been *spared* by the purge, when in fact it had been *deleted*. Any future logic that polls `read_status` to decide whether a job still needs attention will make the same mistake.

Suggested: return `None` (matching `read_result`/`read_spec`) for a job with no directory, or add an explicit `"unknown"` status.

---

## F-025 — Destructive and recovery paths verified clean
**Tag:** verified · **Phase:** 7

All confirmed live on the fresh stack:

- **Audit-log immutability at the database level.** `UPDATE`, `DELETE` **and** `TRUNCATE` are each rejected by the Postgres trigger with `admin_audit_log is append-only -- X is not permitted`. Application code is not the only thing protecting it.
- **`reset-all` preserves the audit trail.** users 9 → **0**, audit rows 126 → **127** (nothing deleted; the +1 is reset-all's own audit entry), bug reports 1 → 1. Surviving rows had `actor_user_id` nulled rather than being cascade-deleted — exactly the documented reason the command uses `DELETE FROM users` rather than `TRUNCATE ... CASCADE`.
- **The immutability trigger is re-enabled afterward.** `reset-all` temporarily disables it to null those FKs; a `DELETE` attempted after the command completed was correctly rejected again. A trigger left disabled would have silently made the audit log mutable forever, and it is not.
- **Lockout recovery works.** `bootstrap-admin` succeeded on the emptied stack and the new credentials logged in.
- **Self-delete refused** with a clear 400 (`"cannot delete your own account through this route"`).
- **Bulk purge is audit-logged** and reports the exact job ids purged.
- **A deleted user's job is not globally readable afterward** — another user gets 404 (SEC-08b's core property holds).

One assertion in this script was too strict and has been noted rather than counted: expecting the audit row count to be *unchanged* across `reset-all` ignores that the command correctly logs itself.

---

## F-026 — The three engines disagree on what counts as an imaginary frequency, and the UI disagrees with all of them
**Tag:** CODE · **Severity:** Medium · **Phase:** 5 (spotted in a rendered result, then confirmed in source)

Imaginary frequencies are how a user distinguishes a minimum from a transition state, so the count needs to mean the same thing everywhere. It does not:

| where | rule |
|---|---|
| `app/chemistry/jobs/bagel_runner.py:765` | `f < -_IMAGINARY_THRESHOLD_CM1` — **thresholded** |
| `app/chemistry/jobs/orca_runner.py:577` | `f < 0` — no threshold |
| `app/chemistry/jobs/pyscf_runner.py:483, 519` | `f < 0` — no threshold |
| `frontend/src/jobs/VibrationTable.tsx:31` | `f < 0` → renders the row red |

Two consequences:

1. **Engine-dependent reporting of the same physics.** A −5.9 cm⁻¹ mode — numerical noise in a projected translational/rotational mode, not a real imaginary frequency — is counted as imaginary by ORCA and PySCF but correctly excluded by BAGEL. The same molecule at the same geometry can therefore be reported as a minimum on one engine and a first-order saddle point on another.

2. **The UI contradicts the summary it sits next to.** Caught visually in `docs/e2e-artifacts/ui02-drawer-frequency.png`: a BAGEL water frequency job renders mode 1 at **−5.9 cm⁻¹ in red** (the "imaginary" styling) directly above a summary field reading **`n_imaginary_frequencies: 0`**. Both are on screen simultaneously and they disagree.

BAGEL's thresholded rule is the chemically correct one. **Suggested fix:** hoist `_IMAGINARY_THRESHOLD_CM1` into `app/config.py`, apply it in all three runners, and have `VibrationTable` colour on the same threshold rather than a bare sign test — ideally by having the backend mark which modes are imaginary rather than the frontend re-deriving it.

This one is a good argument for the "view every result" part of a test pass: it is invisible in any pass/fail assertion, and only shows up when a human looks at the rendered table.
