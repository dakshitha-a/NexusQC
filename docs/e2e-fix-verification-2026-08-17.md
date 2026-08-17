# Fix verification — 2026-08-17

What was actually run against the live `docker compose` stack after implementing all 21 fixes from `e2e-improvement-plan-2026-08-16.md`, and what remains unverified.

Branch `fix/e2e-findings-2026-08-16` · commits `1ae199e`, `0623415`.

The distinction this document exists to preserve: **"the code changed" and "the behaviour changed" are different claims**, and only the second one is worth anything before a deployment. Every row below says which of the two it is.

---

## Suite results

All against the full `docker compose` stack (Postgres + Redis + api + nginx), rebuilt and restarted with the fixes in place.

| Suite | Result | Covers |
|---|---|---|
| `tests/run_backend.sh` | **22/22 scripts, 0 failures** | the whole auth/admin regression suite |
| `node tests/e2e/ui/run_ui.mjs` | **4/4 specs, 66/66 checks** | shell, chat, approval, drawer, molecule, KB, admin |
| `e2e_00_preflight.py` | **16/16** | deployment bring-up gates |
| `e2e_03_route_auth_sweep.py` | **7/7** | route-level ownership/auth inventory |
| `e2e_04_harness_gate.py` | **16/16** | full approval round trip, including new H12 |
| `e2e_05_molecule_resolution.py` | **12/12** | SMILES/name/XYZ resolution |
| `e2e_07_approval_flow.py` | **24/24** | approve, reject, tamper, hand-edit |
| `e2e_10_kb_lifecycle.py` | **17/17** | KB upload, scoping, delete, account deletion |
| `sec_06_ownership_sweep.py` | **8/8** | the ownership inventory, now incl. the KB content route |
| `e2e_17_logout_and_return.py` | **21/21** | the leave-and-return workflow (new, see below) |
| `e2e_06_agent_tools.py` | **12/13** | tool elicitation and disallowed pairings — never run in the original pass |
| `e2e_09_plot_tools.py` | **6/6** | UV/Vis, IR and job-comparison plotting |
| `e2e_11_param_correction.py` | **8/8** | method/basis typo correction |
| `e2e_12_failure_retry.py` | **10/10** | the auto investigate-and-retry cycle — never run in the original pass |
| `e2e_13_stability.py` | **10/10** | concurrency caps, cancellation, orphan recovery |
| `e2e_16_admin_destructive.py` | **9/9** (1 skipped) | audit-log immutability, purges, self-delete |

One caveat on `run_backend.sh`: an earlier run reported 21/22 with `p1_01_registration_validation` failing. That was a live test of mine running concurrently against the same stack — every script in `tests/backend/` shares one apparent client IP, so a concurrent login burst eats the per-IP rate-limit budget the script needs. Re-run with nothing else in flight: 22/22. Worth knowing before anyone reads a lone `p1_01` failure as a regression.

---

## The suites the original pass never ran

Checking the recorded scenario ids from the 2026-08-16 run showed results for `A`/`C`/`D`/`H`/`K`/`M`/`MOL`/`P`/`S`/`XN` — but none at all for `E` (`e2e_06`, agent-tool elicitation) or `R` (`e2e_12`, failure retry). Those two, plus `e2e_08`/`e2e_16` which had not been re-run after the fixes, were run here. They found **one real defect and four test bugs**.

### The real defect: a failed job led with a Python traceback

Every worker stored a bare `traceback.format_exc()`, which puts the stack first and the diagnosis last. A real failed ORCA run opened with ~300 characters of `orca_worker.py` / `orca_runner.py` frames before reaching the part that matters:

> `UNRECOGNIZED OR DUPLICATED KEYWORD(S) IN SIMPLE INPUT LINE: NOSUCHBASIS777`

Everything that truncates — the job list, the drawer's error line, `check_job_status`' report to the agent — therefore showed the reader the least informative part. This lands hardest in exactly the workflow this app is built around: coming back to a job that failed an hour ago, the first thing shown should be **why**. `format_job_error()` now leads with the message and keeps the traceback below a marker; applied in all three workers. `e2e_12`'s `R2` flips FAIL → PASS.

### The test bugs — all reading too early, or scavenging ambient state

| Test | What it did | Fix |
|---|---|---|
| `e2e_09` comparison | Compared "energy" across whatever jobs the account held. A run holding three `frequency` jobs, a `recommend_active_space` and one `single_point` failed with "found 1, need at least 2" — which is `plot_job_comparison` **refusing rather than fabricating**, exactly as designed. | Submits its own comparable single-points. |
| `e2e_13` S1b | Broke on the first non-empty pending message, which is `submit()`'s generic `"queued"` placeholder written before `_wait_for_resources` fills in the real reason. | Skips the placeholder; now reads `"waiting for a free job slot (you have 1/1 running)"`. |
| `e2e_13` S1c | Read status immediately after `cancel()`, but the terminal status is written afterwards by the manager's watcher thread. The **pre-fix run recorded the identical `j1_final: "running"`**, so this was never a regression. | Waits for terminal. |
| `e2e_12` R4 | Polled `GET /state` on the fixture's 30s timeout while the watcher's retry turn held that thread's lock. | Raised to 300s. |
| `e2e_16` D3c/D5 | Raced a probe job against an HTTP purge/delete. D3c had only ever "passed" because `read_status()` returned a synthetic `"pending"` for a job whose directory was gone — fixing that to return `None` (F-024) turned the false pass into an honest failure. | `fixtures.skip()` for genuinely inconclusive runs; D3c now exercises the rule deterministically in one in-container process (`running → running`, absent from the purged list). D5's property is covered deterministically by `sec_08b`. |

### Not a defect: `e2e_06`'s E03

The agent calls `submit_job` for a TDDFT request with no `n_states` rather than asking first. Mechanically safe, and verified rather than assumed: `missing_required_params("tddft", …)` still returns `['n_states']`, so no job and no approval card are created and the tool returns an elicitation prompt. Same class as F-019 — prompt reliability, not correctness.

---

## Leave and return — the workflow long jobs depend on

Added after the fix pass, because the original report had framed multi-hour CASSCF runtimes as a hazard to warn users about, when they are the ordinary case this application is built around. What actually matters is not how long a job takes but whether the user can walk away from it — and nothing had tested that end to end.

`tests/e2e/e2e_17_logout_and_return.py`, **21/21** against the live stack, with a real ORCA CASSCF(4,4)/STO-3G submitted through the agent and its approval gate:

| | Confirmed |
|---|---|
| **L2** | The logout is real — the session is gone (`/api/auth/me` → 401) and the client can no longer list jobs. |
| **L3** | **The worker subprocess is still alive afterwards**, verified by pid *and* its recorded `create_time` so a recycled pid cannot be mistaken for a live worker. Logging out does not touch a running calculation. |
| **L4** | The job reaches `completed` with **no session open at all**. |
| **L5** | On logging back in on a *fresh* session: the job is listed, shown `completed` (not stuck at `running`), and its real results are readable — `casscf_energy_hartree = -74.9779291936`. |
| **L6** | The conversation survived intact, including the agent's own messages from before the user left, and is listed in their sidebar. |
| **L7** | The job's artifacts are fetchable again (58 KB of raw ORCA output). |
| **L9** | **The agent summarised the finished job unprompted, while nobody was logged in.** `job_watcher` polls every ~2s, walks every conversation in the registry rather than any open tab, and injects a completion notice; that turn runs and is checkpointed regardless of who is connected. The summary — a markdown table with the CASSCF energy, active space and natural-orbital occupations — was simply waiting in the conversation on return. |
| **L8** | The user can **resume the work**: a follow-up turn in the same conversation, and the agent answers from the job that finished while they were away — it quoted `−74.9779 Ha`, matching the summary. |

Two structural points behind this, checked rather than assumed:

- `POST /api/auth/logout` clears the Redis active-session key and the cookie. It touches nothing else — no job, no process, no thread.
- Workers run detached (`start_new_session=True`, their own process group), deliberately outliving the request, the session, and the backend process itself.

**One real UI defect this workflow surfaced, now fixed.** `GET /api/threads/{id}/state` takes that thread's own lock, so opening a conversation whose agent turn is currently running waits for it — **19.5s measured** for an ordinary turn, considerably longer for the watcher's retry turn. The lock is correct and stays. What was wrong is what the UI showed meanwhile: `useActiveThreadController` clears the store to empty before the fetch (deliberately, so the previous thread's messages don't flash under the new thread's identity) and had neither a loading state nor a `.catch()` — so the pane rendered its **"start a new conversation" welcome screen** for the whole wait, and permanently if the fetch ever failed. A user returning to a conversation whose job had just failed, while the watcher was mid-retry-turn on that very thread, would be told they had no conversation. Fixed with `threadLoading`/`threadLoadError`; verified in a real browser against a genuinely lock-blocked load (`sawLoading=true, sawWelcome=false`).

**Also re-verified after the `read_status` change**, since that change touched the recovery path a multi-hour job actually depends on: a job left stuck at `running` with a terminal `result.json` — the documented symptom of a backend that died mid-job — is correctly reconciled to `completed` on the next `JobManager` construction, and a job whose directory is gone now reports `None` rather than a synthetic `pending`.

---

## Per-fix verification

### Behaviour verified live

| # | Finding | Evidence |
|---|---|---|
| 1 | **F-022** KB content leak | `sec_06` now live-proves this route: user B gets **404** for A's private upload, A still reads their own (200 + content). `e2e_10`'s `K4c` PASS. |
| 2 | **F-013** AccountBar covering the collapse control | `ui_01`'s `[F-013] "Collapse panel" is not covered` PASS — that check uses `document.elementFromPoint()` at the button's centre. Full UI suite re-run: no regression from restructuring the shell root into a column. |
| 3 | **F-003** SMILES charset gate | All 6 halogen/metal cases resolve as SMILES; `water`/`acetic acid` still fall through to name lookup; `[Na+].[Cl-]` gives 2 atoms, net charge 0. |
| 4 | **F-001** orphaned KB uploads | `e2e_10`'s `K6c` and `K7` both PASS — the raw file goes with the chunks, and account deletion reclaims pre-existing orphans. |
| 5 | **F-018** custom-job validation severity | Ran the finding's exact `* xyzfile` + inline coordinates input through a real agent turn. The approval card's payload carries `severity: "error"` for the contradiction and `severity: "warning"` for the weaker "no geometry block" finding. |
| 6 | **F-023** approval consumed by an invalid edit | `e2e_07`'s `A4a`/`A4b`/`A3c` all PASS: 400 with the validator's message, the interrupt **stays pending**, and a corrected retry then succeeds. |
| 8 | **F-006** `.dockerignore` | Build context excludes 770MB of 1.6GB. `COPY frontend/` can no longer clobber the image's `npm ci` output. |
| 9 | **F-005** `N_CORES` guard | Startup log: `INFO: N_CORES=8 (from QC_AGENT_N_CORES; 255 logical CPUs visible to this process)`. |
| 9b | **F-026** imaginary-frequency rule | Water/HF/STO-3G `frequency` on **all three engines**: PySCF, ORCA and BAGEL all report `n_imaginary_frequencies=0` with `threshold=50.0`. BAGEL's `−5.9 cm⁻¹` mode — the one the finding's screenshot showed painted red above a summary saying 0 — is now correctly flagged `False`. |
| 10 | **F-020** active-space vs. `n_states` | See the note below; verified in both directions. |
| 12 | **F-004** container file ownership | Container `id` → `uid=1002(app)`. A file it writes into `data/` appears as `qcuser` on the host and the host can delete it. |
| 13 | **F-010** ungated `/api/job-registry` | Anonymous → **401**; authenticated → 200 with the full schema. `e2e_00`'s G12 rewritten to assert this. |
| 15 | **F-002** robots.txt | pyscf.org → **409** quoting its own `Content-Signal: ai-train=no`; `ignore_robots: true` → 201; nubakery.org (which the seeder does crawl) unaffected → 201. |
| 16 | **F-007** Node version | Node 24.19.0: `npm ci` emits **no** `EBADENGINE`, `tsc --noEmit` clean, `vite build` succeeds. |
| 17 | **F-008** no `agent_step` on resume | `e2e_04`'s new H12: `agent_step` events **are** published after an approval resume — `steps=[('submit_job', 'finished')]`. |
| 18/20 | **F-012** test-harness messaging | `check()` gained `fail_detail`; `run_backend.sh`'s blurb no longer contradicts `tests/README.md`. |

### Code-complete, verified by inspection or unit-level check only

| # | Item | What was and wasn't checked |
|---|---|---|
| 7 | `data-testid` attributes | The plan's named collision subset is done — the three `"Detach"`, the `"Cancel"`/`"Confirm delete"` pair, the three `"Download as PNG"` — each now has a distinct `data-testid` **and** a distinct `title`. The full ~40-element scheme is **not** done; the rest of the app still has no testids. `aria-expanded` on `CollapsibleSection` is also outstanding. |
| 11 | **F-014** sketcher loading state | The overlay is wired to both `Suspense` boundaries and typechecks, but the UI spec measures Ketcher's load at ~2.9s and does not assert the fallback renders. Not observed on screen. |
| 14 | **F-024** `read_status` | All 8 internal callers updated and exercised by the passing suites, but no test specifically distinguishes "queued" from "deleted". |
| 19 | `connectivity_smiles` | Confirmed the attribute exists on this `pubchempy` and that name resolution still works; the deprecation warning's absence was not separately asserted. |
| 21 | README | Prose. Re-read for accuracy against what this run actually established. |

---

## F-020 — two attempts, and why the first was wrong

Worth recording, because the first fix looked right and was verified to be wrong.

**Attempt 1** widened the recommended active space by adding the next-most-entangled remaining orbital until it could host `n_states`. Running the plan's own case (3 states of water/STO-3G) took the space from (4e,2o) to (6e,3o) — and it *still* failed with the same error. Entropy ranks the strongly-occupied orbitals first, and each one brings ~2 electrons with it, so the space grew while staying completely full: exactly one configuration either way.

**Attempt 2** is greedy on the quantity actually being satisfied — the number of many-electron configurations — with entropy as the tie-break.

That case then turned out to be **unsatisfiable at any selection**: its AVAS pilot space (from the default `O 2p` labels) is (6e,3o), and the recommendation is always a subset of the pilot. So the real fix is ordering. The pilot space size is known immediately after AVAS, long before the pilot CASCI, the entropies, the plateau search and the plot — the job now stops there, in **5 seconds**, with a message naming the knob to turn:

> The AVAS pilot space for this molecule (6e,3o) can host at most 1 many-electron configuration(s) … Widen the pilot space with `avas_aolabels` … Stopping before the pilot calculation rather than after it.

A satisfiable request on a wider pilot completes normally and recommends (6e,5o).

**Unverified:** the greedy widening branch itself was never observed *firing* on a real job. The two live cases were an unsatisfiable one (stopped by the fail-fast check) and one where the entropy plateau already selected enough. The branch is code-complete and reasoned but not exercised end-to-end.

---

## Gaps found while verifying, not present in the original report

Both were found by running the verification, not by review.

1. **`validate_input` raises for any engine outside `{orca, bagel}`.** The F-023 fix put it in the approval route, so a scripted client sending `input_text` for a **PySCF** approval got a bare **500**. Reproduced live, then fixed in both the route and `submit_job`: a hand-edit for an engine with no editable input format is now dropped, since `_raw_input` is never read on that path. Re-tested: **200**. The browser never sends this (the PySCF card is read-only), but `e2e_07`'s own `A6b` already establishes hand-crafted approval bodies as in scope.

2. **`e2e_07`'s `A1h` asserted the inverse of the approval flow's safety property.** It required the running job's id to *differ* from the approved spec's. The premise is right — everything before `interrupt()` reruns on resume, including `JobSpec.job_id`'s `default_factory` — but the re-executed spec is **discarded**: `submit_job` submits `JobSpec(**decision["spec"])`, the exact dict from the interrupt payload, precisely so what runs is what the human saw. Identical ids are the evidence the property held; differing ids would mean a job ran that nobody approved. Rewritten to assert equality.

## Stale test assertions retired

Three assertions encoded behaviour these fixes changed, and would have "passed" only by demanding the old bug back:

- **`XN-14`** (no `agent_step` after a resume) — retired, kept as an id with an explanation rather than deleted, and `e2e_04` now asserts the events are *present*.
- **`e2e_05`'s F-003 check** — was "valid halogen SMILES fall through to a name lookup"; inverted into a regression test for the fix.
- **`e2e_00`'s G12** — asserted `/api/job-registry` returns 200 to an anonymous caller, which was the F-010 gap itself.

The remaining expected negatives (`XN-01`–`XN-13`, `XN-15`, `XN-16`) were re-read and are still accurate design boundaries.

---

## Still not verified, and still true from the original report

- **The public `:443` listener and the host-level kill switch remain unexercised.** Nothing in this pass changed that. The intranet listener *has* now been run end-to-end (the README status table was corrected accordingly), but do not enable public access on the strength of either document.
- **Long CASSCF/CASPT2 runtimes are expected and are not a defect.** F-017's original "will look like a hang, should carry a warning" framing was wrong and has been retracted: runs of 40–50 minutes, sometimes hours, are routine in this group, and the job system exists so that is fine. The factual remainder: BAGEL's macro-iterations on *this host* are ~85s where ORCA and PySCF are sub-second for the same trivial system, so prefer those when a fast turnaround on a small system is what's wanted. BAGEL `frequency` is unaffected — it was one of the three engines in the F-026 check above.
- **The four feature requests (`FR-0`–`FR-3`) are specifications only.** No download buttons were implemented.
