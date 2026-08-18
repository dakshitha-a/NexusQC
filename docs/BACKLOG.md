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

## Open

- **`submit_job` is sometimes skipped on a fully-specified request.** Observed
  at roughly 1 in 3 fresh-thread attempts: the agent calls `set_molecule` and
  stops, or calls no tool at all, even when the user's message explicitly asked
  for the job to run. Nothing incorrect results — the approval gate is
  structural — but it costs the user a second nudge. Preferred fix is
  mechanical rather than prompt-only, following the precedent set by the
  `want_oscillator_strengths` → ORCA routing: inject a follow-up prompt when a
  turn sets a molecule and stops on an explicit run request, rather than ending
  the turn.
- **Most of the app has no `data-testid`.** A small, named set of collisions
  (`"Detach"`, `"Cancel"`/`"Confirm delete"`, `"Download as PNG"`) were given
  distinct testids and titles; the rest of the ~40-element scheme sketched for
  chat (`chat-composer`, `chat-send`, …), jobs (`job-row-<id>`, `job-kill`, …),
  the drawer's 19 gated sections, and admin controls is not done.
  `CollapsibleSection` also has no `aria-expanded`, which is both a testing and
  a screen-reader gap.
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
  none), and the excited-state path (`target_state`) at all.
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

*(empty — populated by the next full pass)*
