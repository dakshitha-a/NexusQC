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

The 10-phase registry v2/agent-rebuild overhaul (`docs/TRACKER.md`, all 72
steps done as of 2026-08-20) retired the `submit_job` tool this file's own
"Open" section used to name. Replaced by `start_job_draft`/
`update_job_draft`/`submit_draft`, whose ready-draft response now always
carries an explicit "NEXT STEP: ... call submit_draft now" instruction,
resolving the skipped-submission problem that item described. Recovered the
same way as `docs/ROADMAP.md` above if the original wording is ever wanted.

## Open

- **`data-testid` coverage is organic, not systematic.** The overhaul grew
  real coverage as each new feature needed one to test live (28 of 75
  frontend components now carry at least one. `Composer.tsx` alone has
  `composer-file-input`/`composer-upload-note`/`composer-detach-job-<id>`/
  `composer-detach-frame`/`composer-add-file`, none of which existed when this
  item was first written), but the specific ~40-element scheme originally
  sketched was never done as one deliberate pass: `chat-composer`/`chat-send`,
  `job-row-<id>`/`job-kill`, and the drawer's 19 gated sections still don't
  exist under those names (confirmed: `JobDetailDrawer.tsx` carries only 3
  testids total). `CollapsibleSection` still has no `aria-expanded` at all,
  both a testing and a screen-reader gap, unchanged.
- **Time-to-first-token: the standing "6–32s, median ~15s" figure is stale and
  likely predates the fix that would explain it.** That number comes from
  F-009 in the retired e2e findings doc (`git show 1e00306`), an n=4 sample
  measured 2026-08-16, and the keep-warm loop
  (`QC_AGENT_MODEL_KEEPALIVE_INTERVAL`) was added the next day, 2026-08-17
  (`c339673`). F-009's own text ends by "considering whether ... a warmed
  context would help," which only makes sense if no warm-context mechanism
  existed yet at measurement time, so the range this backlog item has been
  carrying forward was very plausibly dominated by cold loads (11.4s cold vs
  2.9s warm was this same host's own later-measured gap), not a live,
  already-warm-server problem. Nobody re-measured TTFT after the keep-warm
  fix landed until now.
  Re-measured 2026-08-20 with keep-warm active, both in-process
  (`stream_turn_tokens` directly) and through the real HTTP+SSE path (a
  temporary local server instance, POST `/messages` → first SSE `token`
  event, same method F-009 used): a plain text turn ("What can you help me
  with?") reached first token at 3.85s; a tool-calling turn ("Set the active
  molecule to water") at 2.88s. Both comfortably under the old reported
  floor, and the two measurement paths agree closely, so HTTP/SSE transport
  isn't hiding extra latency. Caveats: small sample (n=1–2 per condition),
  idle single-tenant host, one representative prompt each. A real
  confirmation should pull a larger sample from the e2e harness's own `ttft`
  field (`tests/e2e/results/*.jsonl`) rather than rely on this spot-check.
  One structural, durable lever worth keeping regardless of how the
  stale-measurement question resolves: the bound tool schema sent with every
  turn is ~19.5KB JSON (13 tools via `bind_tools()`) against a 5KB system
  prompt (`app/agent/prompts.py`). Roughly 80% of the fixed per-turn prompt
  cost is tool definitions, not instructions, and is the one lever that
  would lower the ~4s floor itself if that's ever wanted. (Checked and
  ruled out as a contributor: `_build_llm()` rebuilding `ChatOpenAI` +
  `bind_tools()` on every node call costs 405ms on a process's first call
  but under 1ms on every call after, in a long-lived server process, not a
  real per-turn cost.)
- **The Ketcher 2D sketcher's own chunk could still shrink further.** The
  binaryWasm swap removed the ~21MB base64-inlined Indigo binary; what's left
  (`ketcher-react`/`ketcher-core`'s own code, ~7.6MB) hasn't been examined for
  further trimming, and there's no hover-preload to start the fetch before the
  user clicks "Build a molecule."
- **Viewer PNG capture resolution is capped by the on-screen canvas's pane
  size**, not truly independent of it. A capture at 3x an already-small
  in-panel view is still smaller than 3x an enlarged one. Rendering at a fixed
  high resolution regardless of pane size (briefly resizing the container
  before capture) is a reasonable follow-up, deliberately out of scope for the
  current implementation.

## Unverified deployment surface

Not defects. Genuinely never exercised, so don't read their absence here as
clearance:

- The public `:443` listener, end to end.
- The host-level kill switch (`scripts/toggle_public_access.sh`), needs `sudo`
  against this host's real firewall.
- `neb_ts` against a reaction with a genuine barrier (the tested geometry had
  none), and the excited-state path (`target_state`) at all. A 2026-08-20
  regression pass (`docs/TRACKER.md`'s P9.8) hit an ORCA exit-code-2 failure
  on a live `neb_ts` matrix cell (`tests/e2e/e2e_08_job_matrix.py`'s M23).
  The raw output showed a run of identical, non-decreasing energies,
  consistent with (though not confirmed as) a non-converging band on
  whatever system that turn happened to set up. Not isolated further; still
  genuinely unverified, now with a concrete failure on record rather than
  none at all.
- BAGEL CASSCF/CASPT2 to convergence, on hosts whose MKL/BAGEL install is
  abnormally slow (one observed running macro-iterations at ~85s where
  ORCA/PySCF are sub-second on the same trivial system). Not a code defect,
  an environment one, but it has kept full runs from completing on affected
  hosts. Re-verify on a host where BAGEL behaves normally before relying on
  convergence-sensitive results from it.
- The vLLM inference backend (commented out in compose).
- Multi-host operation, real (non-self-signed) TLS, and load beyond one
  operator.

Found and fixed in the same pass (not backlog items, noted here only so the
next pass doesn't re-discover them):

- **`cas_reco/autocas` refused the whole recommendation whenever the AVAS
  pilot space couldn't host the requested `n_states`.**
  `tests/e2e/e2e_08_job_matrix.py`'s M26 (default request: 3 states, default
  `O 2p` AVAS labels on water/STO-3G) failed live with "The AVAS pilot space
  for this molecule (6e,3o) can host at most 1 many-electron configuration(s),
  fewer than the 3 states requested." Confirmed against the real AVAS method
  (Sayfutyarova, Sun, Chan & Knizia, *JCTC* 2017) and against PySCF's own
  `avas.avas()` call site (`app/chemistry/jobs/pyscf_runner.py`): AVAS is a
  one-electron orbital-selection method with no notion of electronic states
  at all, so gating the recommendation on `n_states` was never something the
  underlying algorithm asked for. It was this app's own guard (`F-020`,
  added after a real crash) doing double duty as both a genuine crash
  preventer and an upfront refusal. Split the two: the early pilot-space
  check is now informational only (the pipeline always runs and always
  produces a recommendation and its entropy plot), and the late guard,
  reached only after the existing entropy-ranked widening already tried to
  make room. Now clamps `n_states` down to what the recommended space can
  actually host and runs the final CASSCF with that many states, instead of
  refusing outright. `summary` carries `n_states_requested` and
  `n_states_clamped_note` alongside `n_states` so the clamp is visible to the
  caller, not just the log. Verified live: the exact M26 case now succeeds,
  clamped to 1 state, `converged: True`; an unclamped request still returns
  `n_states_clamped_note: None`. M26's fixture is left as-is. It now
  regression-tests the clamp path rather than testing a dead end.

- BAGEL had no runner wired up at all for a plain HF `single_point/gs`
  energy job, despite `capabilities.py` declaring it supported. Nothing had
  run that exact combination through the full agent pipeline before this
  pass did. Fixed in commit `03ddb12`.
- `tests/e2e/e2e_00_preflight.py`'s G2a/G2b hardcoded a stale `N_CORES`
  expectation of `8`; both `docker-compose.yml` and `app/config.py`'s real
  default were already `4` and agreed with each other, unreconciled since
  Phase 3/4's fair-scheduler work. Fixed as a one-line test correction; the
  whole preflight script is 16/16 again.
