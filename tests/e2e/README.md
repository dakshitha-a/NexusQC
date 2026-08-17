# `tests/e2e/` — end-to-end pre-deployment suite

This suite exists because `tests/backend/` deliberately does **not** do what this one does.

Those scripts test the auth/admin layer by calling mechanisms directly — `JobManager.submit()`, `purge_user_data()`, `count_admins()` — because the mechanism is what they are testing. That is the right design for them, and it is why several of them work at all (see `perf_03`'s docstring on why a cap-blocked job's promotion dies with the submitting process).

This suite does the opposite. It drives the whole product the way a real user does: a real browser or a real HTTP session, a real user account, a real natural-language request to the agent — and then checks **which tools the agent actually called, with which arguments**.

That distinction is the whole point. A job that completes is not evidence the agent asked for the right calculation. `param_normalize.py` silently repairs some typos, `default_engine()` mechanically reroutes CASSCF to ORCA when oscillator strengths are wanted, and the keyword-suggestion menus can make a wrong request look right in the finished result. Only the tool trace answers the question.

## Observation channels

**Primary — `GET /api/threads/{id}/state`.** `app/agent/serialize.py::serialize_message` preserves `tool_calls` (name *and* args) on every `AIMessage` and `name` on every `ToolMessage`. Diffing the message list across a turn is a complete, replayable audit of the turn's tool usage. Every assertion runs against this.

**Secondary — SSE `agent_step` events.** `_run_turn` publishes `agent_step` from its streaming `"updates"` loop, and — since the F-008 fix — so does `approve_job`, via `_stream_resume`. This used to be the suite's sharpest blind spot: `approve_job` resumed with a single blocking `.invoke()` and published only `message` events, making every tool call in the post-resume tail of a turn invisible, including the re-executed `submit_job` itself. That was expected-negative `XN-14`, now retired. State-diffing stays primary regardless, because it reads what the graph actually committed and so cannot miss a call that an SSE subscriber dropped or attached too late to see (`SSEHub.publish` is fire-and-forget). `e2e_04_harness_gate.py`'s H12 check now asserts the events are present.

Two SSE facts shape the harness, both read out of `server/sse.py` rather than assumed:

- `SSEHub.publish` is fire-and-forget and **drops** an event when nobody is subscribed. `POST /messages` returns 202 and spawns its turn thread immediately, so `AgentSession.open_events()` blocks until the `: connected` preamble arrives before any message is posted.
- Each subscriber queue is bounded at 500 with drop-oldest, so a slow reader loses old events rather than blocking the publisher.

Approvals are detected by **polling** `GET /state` for a non-null `pending_approval`, never by racing the `interrupt` event: `POST /approvals/job` returns 409 when nothing is pending, so the event is an optimization, not a contract.

## Probe sizing — a deliberate two-tier choice

The default everywhere is **water / HF / STO-3G**, the smallest meaningful system and basis.

But a trivial PySCF job reaches `completed` faster than any polling loop can observe it in a transient state — this is precisely why PERF-03 was originally inconclusive. So anything that must observe a transient (queueing, the concurrency cap, the live log tail, cancel, orphan reconciliation) uses a genuinely slow probe instead: **water CASSCF(4,4)/STO-3G on ORCA** (~15s, energy verified against PySCF to 1.7e-8 Ha) or the BAGEL equivalent (minutes). Same small molecule, same minimal basis; only the method is heavier. See `_probes.py`.

## Files

| File | Purpose |
|---|---|
| `_agent.py` | `AgentSession` (SSE reader, `say`, `approve`, `await_job`), `check_tools`, durable `record()` |
| `_expected.py` | The 16 pre-registered expected negatives (`XN-01`…`XN-16`) and the failure taxonomy |
| `_probes.py` | Probe definitions, the 26-cell job matrix, elicitation negatives, disallowed pairings |
| `e2e_00_preflight.py` | 16 bring-up gates. **Nothing else runs until these are green.** |
| `e2e_03_route_auth_sweep.py` | Anonymous / non-admin / cross-user sweep over every route in `/openapi.json` |
| `e2e_04_harness_gate.py` | Proves the harness itself works before any scenario depends on it |
| `e2e_05_molecule_resolution.py` | Name / SMILES / XYZ, including the SMILES charset trap |
| `e2e_06_agent_tools.py` | Every non-`submit_job` tool, elicitation, disallowed pairings |
| `e2e_07_approval_flow.py` | Approve / reject / hand-edit / invalid-edit / spec-tamper / 409 |
| `e2e_08_job_matrix.py` | The 26-cell job_type × engine matrix (`--tier`, `--only`) |
| `e2e_09_plot_tools.py` | The three plot tools, and the cases where refusing is the pass |
| `e2e_10_kb_lifecycle.py` | KB ingest routes, per-user scoping, delete-and-reclaim |
| `e2e_11_param_correction.py` | `param_corrections`, `keyword_options`, `kb_context` |
| `e2e_12_failure_retry.py` | Induced runtime failure and the auto-retry chain |
| `e2e_13_stability.py` | Concurrency caps, cancel, orphan reconciliation |
| `e2e_16_admin_destructive.py` | Audit immutability, purges, `reset-all`, lockout recovery |
| `ui/` | Playwright specs (raw `chromium.launch()`, no `@playwright/test`) |
| `results/*.jsonl` | One line per scenario, appended as it finishes — **the report is assembled from this, never from scrollback** |

## Running

Needs the full compose stack up and `tests/backend/_00_bootstrap.py` already run.

```bash
bash tests/e2e/run_e2e.sh                    # everything except destructive
bash tests/e2e/run_e2e.sh --with-destructive
bash tests/e2e/run_e2e.sh e2e_08             # one script by prefix
python3 tests/e2e/e2e_08_job_matrix.py --tier 1
node tests/e2e/ui/run_ui.mjs                 # the browser specs
```

Unlike `tests/backend/`, **no script here is expected to fail.** Every expected negative is asserted *positively* through `_expected.py`'s `expect_by_design()`, so a `[FAIL]` is always a real regression.

## Interpreting a failure

Tag every finding with exactly one class from `_expected.py`'s `TAXONOMY`. The disambiguator that matters is the **mechanical fallback**: when an agent-driven scenario fails, re-run the same operation by calling the mechanism directly.

```bash
docker compose exec -T api python -c "
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager
m = resolve_molecule('water')
spec = JobSpec(method='single_point', engine='orca', molecule=m.to_dict(),
               params={'method':'hf','basis':'sto-3g'})
print(get_job_manager().submit(spec))
"
```

Direct call works → `LLM` (a prompt-reliability finding). Direct call fails → `CODE`.

For LLM non-determinism, a failing scenario is re-run on a **fresh thread** up to three times and reported as `k/N`: `0/3` is deterministic and actionable, `1–2/3` is flaky and belongs in the improvement plan as prompt hardening (or as a candidate for a mechanical rule, following the `want_oscillator_strengths` → ORCA precedent).

Two environment classes are `ENV`, not `CODE`, and must be reproduced twice with a matching signature before being labelled: BAGEL/MKL on this host (`dsyev`/`pdsyevd` failures, `cblas_dgemm` parameter errors, ~80–96s per CASSCF macro-iteration for a trivial system), and network reachability for PubChem, DuckDuckGo, and Semantic Scholar.
