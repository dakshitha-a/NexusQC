# Backlog

The living record of unimplemented bugs and features. Kept short deliberately —
this is a list to work from, not an investigation report. When an item needs
more explanation than a line or two, that reasoning belongs in the commit that
closes it, not here.

## History

This replaces `docs/ROADMAP.md` and the four `docs/e2e-*-2026-08-16*.md` /
`docs/e2e-*-2026-08-17.md` documents, retired once the last two items they
tracked (FR-2's higher-resolution viewer capture, and the Ketcher chunk-weight
reduction) were implemented and verified live. Their full investigation —
findings, the ranked fix plan, and what was checked live versus by inspection
only — is preserved in git history rather than carried forward. To recover one:

```
git log --all --full-history -- docs/ROADMAP.md   # find the last commit that has it
git show <that-commit-sha>:docs/ROADMAP.md          # print its content
```

A fresh testing pass is expected to populate this file going forward, superseding
the 2026-08-16/17 pass's results.

The 10-phase registry v2/agent-rebuild overhaul (`docs/TRACKER.md`, all 72
steps done as of 2026-08-20) retired the `submit_job` tool this file's own
"Open" section used to name — replaced by `start_job_draft`/
`update_job_draft`/`submit_draft`, whose ready-draft response now always
carries an explicit "NEXT STEP: ... call submit_draft now" instruction,
resolving the skipped-submission problem that item described. Recovered the
same way as `docs/ROADMAP.md` above if the original wording is ever wanted.

## Open

- **`data-testid` coverage is organic, not systematic.** The overhaul grew
  real coverage as each new feature needed one to test live (28 of 75
  frontend components now carry at least one — `Composer.tsx` alone has
  `composer-file-input`/`composer-upload-note`/`composer-detach-job-<id>`/
  `composer-detach-frame`/`composer-add-file`, none of which existed when this
  item was first written), but the specific ~40-element scheme originally
  sketched was never done as one deliberate pass: `chat-composer`/`chat-send`,
  `job-row-<id>`/`job-kill`, and the drawer's 19 gated sections still don't
  exist under those names (confirmed: `JobDetailDrawer.tsx` carries only 3
  testids total). `CollapsibleSection` still has no `aria-expanded` at all —
  both a testing and a screen-reader gap, unchanged.
- **Time-to-first-token on an ordinary turn runs several seconds to tens of
  seconds** (last measured: median ~15s, range 6–32s). The keep-warm loop
  (`QC_AGENT_MODEL_KEEPALIVE_INTERVAL`) fixed the *cold-reload* case specifically
  — Ollama evicting an idle model — but this was measured against an already-warm
  server, so it's a separate, still-open latency question.
- **The Ketcher 2D sketcher's own chunk could still shrink further.** The
  binaryWasm swap removed the ~21MB base64-inlined Indigo binary; what's left
  (`ketcher-react`/`ketcher-core`'s own code, ~7.6MB) hasn't been examined for
  further trimming, and there's no hover-preload to start the fetch before the
  user clicks "Build a molecule."
- **Viewer PNG capture resolution is capped by the on-screen canvas's pane
  size**, not truly independent of it — a capture at 3x an already-small
  in-panel view is still smaller than 3x an enlarged one. Rendering at a fixed
  high resolution regardless of pane size (briefly resizing the container
  before capture) is a reasonable follow-up, deliberately out of scope for the
  current implementation.

## Unverified deployment surface

Not defects — genuinely never exercised, so don't read their absence here as
clearance:

- The public `:443` listener, end to end.
- The host-level kill switch (`scripts/toggle_public_access.sh`) — needs `sudo`
  against this host's real firewall.
- `neb_ts` against a reaction with a genuine barrier (the tested geometry had
  none), and the excited-state path (`target_state`) at all. A 2026-08-20
  regression pass (`docs/TRACKER.md`'s P9.8) hit an ORCA exit-code-2 failure
  on a live `neb_ts` matrix cell (`tests/e2e/e2e_08_job_matrix.py`'s M23) —
  the raw output showed a run of identical, non-decreasing energies,
  consistent with (though not confirmed as) a non-converging band on
  whatever system that turn happened to set up. Not isolated further; still
  genuinely unverified, now with a concrete failure on record rather than
  none at all.
- BAGEL CASSCF/CASPT2 to convergence, on hosts whose MKL/BAGEL install is
  abnormally slow (one observed running macro-iterations at ~85s where
  ORCA/PySCF are sub-second on the same trivial system) — not a code defect,
  an environment one, but it has kept full runs from completing on affected
  hosts. Re-verify on a host where BAGEL behaves normally before relying on
  convergence-sensitive results from it.
- The vLLM inference backend (commented out in compose).
- Multi-host operation, real (non-self-signed) TLS, and load beyond one
  operator.

## Found by testing

From the overhaul's closing full regression pass (2026-08-20, `docs/TRACKER.md`'s
P9.8 — `tests/run_backend.sh`, `tests/e2e/run_e2e.sh`, `tests/e2e/ui`, all three):

- **`cas_reco/autocas` can ask for more states than its own default pilot
  space can hold.** `tests/e2e/e2e_08_job_matrix.py`'s M26 (default request:
  3 states) failed live with "The AVAS pilot space for this molecule
  (6e,3o) can host at most 1 many-electron configuration(s), fewer than the
  3 states requested." Whether the real gap is the pilot-space sizing
  heuristic or the matrix's own default n_states wasn't determined — worth
  a closer look, not confirmed as a bug either way.

Found and fixed in the same pass (not backlog items — noted here only so the
next pass doesn't re-discover them):

- BAGEL had no runner wired up at all for a plain HF `single_point/gs`
  energy job, despite `capabilities.py` declaring it supported — nothing had
  run that exact combination through the full agent pipeline before this
  pass did. Fixed in commit `03ddb12`.
- `tests/e2e/e2e_00_preflight.py`'s G2a/G2b hardcoded a stale `N_CORES`
  expectation of `8`; both `docker-compose.yml` and `app/config.py`'s real
  default were already `4` and agreed with each other, unreconciled since
  Phase 3/4's fair-scheduler work. Fixed as a one-line test correction; the
  whole preflight script is 16/16 again.
