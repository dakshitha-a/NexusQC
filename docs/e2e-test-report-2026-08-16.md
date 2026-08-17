# Final pre-deployment end-to-end test — report

**Date:** 2026-08-16 · **Commit:** `32a95ed` · **Host:** Ubuntu 22.04, 255 logical CPUs, 1TB RAM
**Target:** docker-compose stack (nginx `https://127.0.0.1:8443` + postgres 16 + redis 7 + api)
**Method:** clean install from zero, then the whole product exercised through a real browser and a real user account, driven by the agent itself.

---

## 1. Verdict

**Ship, with two fixes first.**

The system is in good shape. A completely fresh install came up clean, the entire existing regression suite passed on it without a single failure, and 22 of the 26 job_type × engine combinations ran end-to-end from a natural-language request through the human approval gate to a correct, fully-rendered result.

Two findings should be fixed before real users touch it:

- **F-022 — any authenticated user can read any other user's uploaded knowledge-base document.** Confidentiality gap in a multi-user deployment. Deliberate in the code, but the stated rationale does not match the actual behavior.
- **F-013 — the instrument panel's collapse button is completely covered by the "Log out" button** at every viewport size. The panel cannot be collapsed, and clicking where the control appears logs the user out.

Neither is difficult to fix. Everything else is either lower-severity, environmental, or a documentation correction.

**Not verified in this run, and deliberately so:** the host-level iptables kill switch (`scripts/toggle_public_access.sh`) was not run — it requires `sudo` and modifies this shared host's real firewall. The public `:443` listener itself was also not exercised. **Do not read this report as clearance to open port 443.**

---

## 2. What was actually done

| Phase | Outcome |
|---|---|
| 0 — Pre-flight capture | Versions recorded; two anomalies captured before they were destroyed |
| 1 — Clean install | `down -v`, `data/` wiped, `npm ci`+build, `docker compose build --no-cache`, KB re-seeded from scratch |
| 2 — Bring-up gates | **16/16** green |
| 2 — Existing regression suite | **22/22 scripts, 0 failures**, plus opt-in `sec_10` 2/2 |
| 3 — Route authorization | All **57** routes swept anonymously, as non-admin, and cross-user |
| 3.5 — Harness validation | **15/15** — proved the tool-call observation channel before trusting it |
| 4 — Job matrix | 26 cells driven through real agent turns |
| 4 — Agent tool scenarios | Param correction, plot tools, KB lifecycle, approval flow |
| 5 — UI verification | 4 Playwright specs, 130+ checks, incl. per-job-type drawer gating |
| 6 — Stability | Concurrency caps, cancel, orphan reconciliation |
| 7 — Destructive | Audit immutability, purges, `reset-all`, lockout recovery |

Total: **~340 automated checks** across roughly six hours of wall clock.

### Install path

| Step | Time |
|---|---|
| `npm ci` | 10.7s |
| `npm run build` | 13.0s |
| `docker compose build --no-cache` | **470s** (370.1MB build context) |
| stack up → `/api/health` 200 | <1s |
| KB seed (crawl + extract + ingest) | **5m11s** — 196 files, 4,186 chunks, 73s of that embedding |

The schema-creation claim was verified directly: **0 tables** existed in Postgres after `docker compose up` and a successful `/api/health`, confirming there is genuinely no migration step and `get_pool()` creates everything lazily on first use.

---

## 3. Findings

Severity: **P0** blocks deployment · **P1** fix before general rollout · **P2** next iteration · **P3** backlog.

### P0

| id | finding |
|---|---|
| **F-022** | `GET /api/kb/sources/{source}/content` serves **any** user's private upload to **any** authenticated caller. Owner A's file returned 200-with-content to unrelated user B. Listing and delete are correctly scoped (B's listing hides it; B's delete 404s) — only the content route is not. Root cause is deliberate: `_content_search_dirs()` (`server/routes/kb.py:72-85`) extends the search to every owner subdirectory. Same shape as SEC-06, which was fixed. Anonymous access correctly 401s, so this needs an account plus a guessable filename — and filenames in this domain are highly guessable. |
| **F-013** | `AccountBar` (`absolute top-2 right-2 z-30`) sits on top of `RightDock`'s header (`position: static`). `document.elementFromPoint()` at the "Collapse panel" button's exact centre returns the **"Log out"** button at 1280, 1440, 1600, 1920 and 2560 px. The instrument panel cannot be collapsed, and a click aimed at the collapse control logs the user out. The mirrored "Collapse sidebar" control on the left works correctly. |

### P1

| id | finding |
|---|---|
| **F-003** | `looks_like_smiles`'s charset gate (`molecule.py:339`) contains no `l`, `r`, `i`, `e`, `a`, `t`, `u` — so **no halogen or metal SMILES can pass**. `ClC=CCl`, `BrCC`, `CC(=O)Cl`, `[Fe]`, `[Na+].[Cl-]` are all valid per RDKit and all rejected; they fall through to a PubChem *name* lookup of the literal SMILES string and 5 of 6 fail outright. The error then reads *"Please supply a SMILES string instead"* — instructing the user to do exactly what they just did. Fix is small: consult `Chem.MolFromSmiles` (already called, but only *after* the gate) instead of the charset heuristic. |
| **F-001** | Deleting a KB source removes its Chroma chunks but **never unlinks the uploaded file**. Confirmed on the clean stack. Worse, the orphan is then invisible to every cleanup path, because `_kb_candidates()` and `_kb_usage_by_owner()` both enumerate from Chroma — so deleting the owning user cannot reclaim it either (verified: one of two files survived account deletion). Pre-wipe evidence: 31 orphaned upload directories against 1 user and 0 ownership rows. |
| **F-018** | A `custom` job's malformed input is **correctly diagnosed and then run anyway**. The agent wrote `* xyzfile 0 1` (external-file form) with inline coordinates; `validate_input()` returns exactly *"No geometry block found (expected a line like `* xyz <charge> <multiplicity>`)"* and the corrected text validates clean — but validation is non-blocking for `custom`, so 33s of compute produced an opaque ORCA "CANNOT OPEN FILE" instead of the accurate diagnosis already in hand. The non-blocking default is right for unrecognized syntax; a *positively-detected* missing required element deserves different treatment. |
| **F-023** | An invalid hand-edit **consumes the approval**. The job correctly does not run, but `POST /approvals/job` returns 200 and the interrupt is gone — a corrected retry gets 409. The user must restart the whole request. `CLAUDE.md` documents the opposite ("the interrupt stays pending so the user can fix it and click Run edited again"), which was true of the retired Streamlit UI where validation ran *before* `resume_turn`. |

### P2

| id | finding |
|---|---|
| **F-020** | `recommend_active_space` selected a (6e,3o) space and then rejected its own selection as too small for the 3 states requested — failing the job after 54s on a perfectly reasonable request. The error text is excellent; the failure should be avoidable, since `n_states` is known before selection. |
| **F-019** | `submit_job` is skipped on roughly **1 in 3** fully-specified requests (2/3 across fresh-thread retries; two distinct miss modes). Nothing incorrect happens — the approval gate is structural — but a third of job requests need a second nudge. |
| **F-006** | No `.dockerignore`: 370MB build context, and `COPY frontend/ ./` overwrites the image's own `npm ci` output with the host's `node_modules`. It worked here only because host and image are both linux/x64 Node 20. |
| **F-005** | `QC_AGENT_N_CORES` in `docker-compose.yml` is an unguarded single point of failure — without it `N_CORES` becomes 255 (verified live) and **every job hangs `pending` forever** with no error. No startup warning guards it. |
| **F-004** | Everything the container writes into the `./data` bind mount is root-owned; the host operator cannot clean, back up, or reclaim their own data directory without root or a throwaway container. |
| **F-014** | The 2D sketcher shows a blank screen for **3,484ms** (measured) with `Suspense fallback={null}` on a 28.7MB chunk. The app already has skeleton/shimmer utilities for this. |
| **F-010** | `GET /api/job-registry` is the only route with no auth at all, and its handler takes no `Request`, so it structurally cannot be gated. Exposes the full engine/method capability map (12KB) to any anonymous caller. |
| **F-026** | The three engines disagree on what counts as an imaginary frequency — BAGEL thresholds it, ORCA and PySCF use a bare `f < 0`, and `VibrationTable.tsx` uses a bare `f < 0` to paint the row red. The same molecule can be reported as a minimum on one engine and a saddle point on another, and a BAGEL result renders a −5.9 cm⁻¹ noise mode in "imaginary" red directly above `n_imaginary_frequencies: 0`. Found by looking at a rendered table, not by any assertion. |

### P3

| id | finding |
|---|---|
| **F-002** | The KB URL-fetch feature consults no `robots.txt`. `data/scraped/promoted_sources/` held 11 pyscf.org pages — a site the seeder deliberately refuses to crawl for that exact reason. User-initiated, so a different act, but worth a decision. |
| **F-007** | `ketcher-*@3.17.2` requires Node ≥24.14.1; both the Dockerfile (`node:20-slim`) and the documented host env are Node 20. Builds fine, but outside the supported range. |
| **F-008** | No `agent_step` SSE events after an approval resume, so the UI shows no per-tool progress between clicking Approve and the tail completing (`XN-14`, confirmed empirically). |
| **F-009** | Time-to-first-token measured at 6.3–31.7s (median 15.2s). |
| **F-012** | `sec_09` prints failure-phrased text as the `detail` of a **passing** check, which reads as a failure in suite output. |
| — | `pubchempy` emits `canonical_smiles is deprecated` (`molecule.py:207`) — will break on a future release. |

### Environmental (not defects)

**F-017** — BAGEL CASSCF-family jobs are not practically runnable on this host: **~85s per macro-iteration** for a trivial 3-atom STO-3G system, plus a non-fatal `oneMKL … cblas_dgemm` error. `geometry_optimization`, `casscf`, and `caspt2` on BAGEL all exceeded a 600s budget. The energies produced were physically sensible, so this is speed, not correctness. **Deployment implication (corrected 2026-08-17):** originally recorded here as "will look like a hang and should carry a warning" — that was wrong. Multi-hour CASSCF/CASPT2 runs are routine in this group and the job system exists to make them fine. The factual part stands: BAGEL is an outlier on *this host* specifically, so prefer ORCA/PySCF when a fast turnaround on a small system is what's wanted. See F-017's own correction, and `e2e_17_logout_and_return.py` for the leave-and-return workflow this reframing makes load-bearing.

### Verified as designed

**F-016** — BAGEL `frequency` **completed in 26.2s** with real frequencies, upgrading its documented "structurally confirmed, not convergence-verified" status. BAGEL `mo_visualization` (21.7s) and `custom` (87.3s) also completed.

**F-015** — WebGL context management holds: canvas count stayed at exactly 1 across four rapid mount/unmount cycles, every viewer rendered real pixels.

**F-021** — `neb_ts` correctly surfaced ORCA's *"No barrier was found"* rejection as a failed job with the real reason (0 occurrences of `ORCA TERMINATED NORMALLY`), matching the documented known limitation. The toy geometry used had no genuine barrier.

Also confirmed working exactly as documented: the `interrupt()` approval gate (structural, never bypassed); mechanical `want_oscillator_strengths` → ORCA routing; the `6-31gd` → `6-31g(d)` repair, surfaced not hidden; RHF → `hf` aliasing; keyword menus for both a mistyped basis and functional in one message; `kb_context` populated on every approval card; per-user concurrency cap reporting *"waiting for a free job slot (you have 1/1 running)"*; the cap being genuinely per-user; cancel killing the real subprocess in 0.01s; orphan reconciliation classifying a workerless job and explaining itself; audit-log immutability at the database level for UPDATE, DELETE **and** TRUNCATE; self-delete refused.

---

## 4. Job matrix

22 PASS · 3 TIMEOUT (all BAGEL, all `ENV`) · 1 real failure (M26) · 2 explained (M23 expected, M24 → F-018).

| cell | job_type | engine | tier | verdict | wall |
|---|---|---|---|---|---|
| M01 | single_point | pyscf | 1 | PASS | 25.7s |
| M02 | single_point | orca | 1 | PASS | 25.2s |
| M03 | geometry_optimization | pyscf | 1 | PASS | 15.1s |
| M04 | geometry_optimization | orca | 2 | PASS | 90.1s |
| M05 | geometry_optimization | bagel | 3 | TIMEOUT | >600s |
| M06 | frequency | pyscf | 1 | PASS | 29.6s |
| M07 | frequency | orca | 2 | PASS | 34.0s |
| M08 | frequency | bagel | 3 | **PASS** | 26.2s |
| M09 | casscf | pyscf | 1 | PASS | 21.3s |
| M10 | casscf | orca | 1 | PASS | 52.8s |
| M11 | casscf | bagel | 3 | TIMEOUT | >600s |
| M12 | caspt2 | bagel | 3 | TIMEOUT | >600s |
| M13 | tddft (CIS) | pyscf | 1 | PASS | 41.6s |
| M14 | tddft (DFT) | pyscf | 2 | PASS | 20.9s |
| M15 | tddft | orca | 2 | PASS (flaky 2/3) | 52.0s |
| M16 | eom_ccsd | orca | 2 | PASS | 39.0s |
| M17 | eom_ccsd | pyscf | 2 | PASS | 25.4s |
| M18 | mo_visualization | pyscf | 1 | PASS | 18.5s |
| M19 | mo_visualization | orca | 2 | PASS | 28.0s |
| M20 | mo_visualization | bagel | 3 | PASS | 21.7s |
| M21 | pes_scan | pyscf | 1 | PASS | 24.1s |
| M22 | pes_scan | orca | 2 | PASS | 74.2s |
| M23 | neb_ts | orca | 3 | expected fail (F-021) | 245.4s |
| M24 | custom | orca | 2 | FAIL → F-018 | 32.7s |
| M25 | custom | bagel | 3 | PASS | 87.3s |
| M26 | recommend_active_space | pyscf | 1 | FAIL → F-020 | 54.0s |

Every passing cell was verified four ways: the agent called `submit_job` with the right `job_type`/`engine`/params; the approval card appeared and showed the right engine; the job reached `completed`; and its summary carried the keys that job type is supposed to produce, with every declared artifact downloadable.

---

## 5. Authorization sweep

All **57** routes, inventory taken from the app's own `/openapi.json` rather than hand-written.

| pass | result |
|---|---|
| Anonymous | 54/54 non-public routes reject. **One exception:** `GET /api/job-registry` → 200 (F-010) |
| Non-admin → `/api/admin/*` | **14/14** return 403 |
| Cross-user (B → A's threads) | **All** return 404, indistinguishable from a nonexistent thread — no existence leak |

A first pass appeared to show a cross-user gap; it was my harness sending empty bodies, which FastAPI rejects with 422 *before* the ownership check runs. Re-probed with valid bodies, ownership enforcement is correct and A's data was verifiably unmodified. The sweep now carries a per-route valid-body table so this cannot recur.

---

## 6. Performance

| measurement | value |
|---|---|
| Agent turn (n=23) | median **14.1s**, p90 26.3s, max 78.9s |
| Full scenario incl. job (n=24) | median **28.8s**, p90 74.2s |
| Time-to-first-token (n=4) | median **15.2s**, range 6.3–31.7s |
| First authenticated request (cold, creates schema) | **3ms** |
| `docker compose build --no-cache` | 470s, 370MB context |
| KB seed | 5m11s → 4,186 chunks |
| Frontend bundle | main 1.19MB (336KB gz); **Ketcher 28.7MB (8.5MB gz)** |
| Ketcher lazy-chunk first paint | 3,484ms with no loading indicator |
| Cancel → subprocess dead | 0.01s |

No horizontal page overflow at 1280 / 1600 / 1920. Keyboard focus reaches real controls with a visible indicator. `prefers-reduced-motion` collapses animations globally to 1e-05s.

---

## 6b. Visual verification of results

Scripts can assert a canvas is non-blank; they cannot tell you the chemistry is right. Every job type's rendered drawer was inspected by eye against the 22 screenshots in `docs/e2e-artifacts/`.

**The chemistry renders correctly.** A BAGEL `mo_visualization` on water reported `homo_index_1based: 5` — right for a 10-electron closed shell — with MOs 1–5 at occupancy 2.00 and MO 6 at 0.00; the O 1s core at −550.9 eV (≈ −20.2 Ha, correct for STO-3G), and character labels that read as a chemist would expect: `O1` for the core and lone pairs, "delocalized over O1, H3, H2" for the bonding MOs. Orbital indices honoured the 1-based convention exactly as requested (`[3, 4, 5]`). Frequency jobs showed the documented 5–6 near-zero projected translational/rotational modes alongside real vibrations.

**Section gating is correct in both directions.** Across seven job types the drawer showed every section it should and — equally important — omitted every section it shouldn't: no "Molecular orbitals" on `pes_scan`, no "Excited states" on `single_point`, no "Vibrational frequencies" on anything but `frequency`. `XN-15` held (PySCF jobs expose neither raw-input nor raw-output; ORCA and BAGEL expose both) and `XN-16` held (inline and artifact spectra never coexist).

**The refusals read well.** Asked to plot a UV/Vis spectrum for a PySCF EOM-CCSD job, the agent declined *and explained the fix*: that PySCF's EOM-CCSD reports excitation energies only, and that re-running with `engine='orca'` would produce oscillator strengths — then offered to do it. That is the designed behavior working better than "refuse cleanly" required.

**One defect was found this way and no other way** — the imaginary-frequency colouring contradiction (F-026), which sits invisibly inside a passing test but is obvious the moment a human reads the table.

## 7. Testability

**The app ships exactly one `data-testid`** (`kb-drop-zone`) and two `aria-label`s (both on `ResizeHandle`). Everything else must be targeted by `title=`, visible text, or `placeholder=`, and several `title` values collide across components — `"Detach"` (3 owners), `"Cancel"` (4), `"Download as PNG"` (3), and `"Molecule"`/`"Jobs"`/`"Conversations"` which also appear on **non-interactive** collapsed-rail divs.

This cost real time in this run and produced several false failures that had to be individually disproved:

- Section headings are CSS `text-transform: uppercase`, and `innerText` returns the **transformed** text — correctly-rendered sections read as missing until compared case-insensitively.
- Clicking a `CollapsibleSection` header is a *toggle*, so a blind "open the panel" click closes it, removing every row from the DOM.
- A job id appears in 1–5 places; only some are the clickable row.

None of those are app defects. All of them are the tax of having no stable selectors — and the single highest-value engineering investment coming out of this pass.

Worth stating plainly: **F-013, the most serious UI bug found, was discovered only because an automated click timed out.** No amount of code reading would have surfaced it.

---

## 8. What was not tested

- **Host-level public-access kill switch** (`scripts/toggle_public_access.sh`) — requires `sudo` and modifies this shared host's firewall.
- **The public `:443` listener** end-to-end.
- **`neb_ts` on a reaction with a real barrier** — the toy geometry used had none, so the ground-state NEB path remains unverified beyond correct failure handling. `target_state` (excited-state NEB) was not attempted.
- **BAGEL CASSCF/CASPT2 to convergence** — not practically possible on this host (F-017).
- **vLLM inference backend** — still commented out in compose.
- **Multi-host, real TLS, and load beyond one operator.**

---

## 9. Artifacts

- `tests/e2e/` — the standing suite, with its own README explaining the observation channels and probe policy
- `tests/e2e/results/*.jsonl` — one line per scenario, appended as it completed; every table above is generated from this by `tests/e2e/summarize.py`, not transcribed
- `docs/e2e-artifacts/` — screenshots of every UI state captured during the run
- `docs/e2e-improvement-plan-2026-08-16.md` — the prioritized fix plan
