<!-- artifact: https://claude.ai/artifact/V1fMX18Ldz75a1qZCsKBgH -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Tracker: fixing what the thesis screenshots found

**Opened 2026-11-09.** Five phases. The tracker before this one is
[`trackers/2026-10-readme-tour.md`](trackers/2026-10-readme-tour.md).
**Exactly one tracker is active at a time.**

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: one path that
  exists on disk plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final change.
- A phase's `merged` row records the commit hash the stage landed as.
- Each fixed item is removed from `docs/BACKLOG.md` in the commit that fixes it.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <path> → "<observed result>"   (required when done)
```

---

## Why this plan exists

Taking the dissertation's NexusQC figures on 2026-11-09 meant driving the app
end to end as a user would, and twelve things went wrong or needed a
workaround. They were logged in `docs/BACKLOG.md` under "Found while taking
the thesis screenshots" (commit 479d4aa). The user asked for all of them to
be fixed.

Backend changes are verified on the host, with the tool functions or
`invoke_turn`, because the stack on port 8444 runs the deployed image until
`scripts/update.sh` rebuilds it. Frontend changes are verified in a real
browser against the Vite dev server, so the live bundle that real users see
does not change mid-session.

## Phase 1: the browser the frontend suite launches

- [done] P1.1: tests/frontend launches a Chromium that is installed
  evidence: tests/frontend/gh_01_version_and_issue_links.spec.mjs → "17/17 on HeadlessChrome 151.0.7922.34 (build 1234); with no browser, newBrowser() names the install command"
- merged: c99a4f7

## Phase 2: drafting

- [done] P2.1: the B88 excited-state gradient note appears only when a gradient is requested, and names no repo path
  evidence: tests/backend/elic_01_draft_scenarios.py → "206/206; ORCA B3LYP note absent for sp/ee and wigner_spectra, present for nac, excited opt and excited grad"
- [todo] P2.2: a nuclear-ensemble or Wigner request in plain words drafts wigner_spectra
- [todo] P2.3: a rejected draft can be dropped, and a request for a different task starts a new draft
- [todo] P2.4: a job drafted after a converged optimisation uses the optimised geometry, and the card says so

## Phase 3: plots

- [todo] P3.1: spectra overlays take a per-series line style, and an edit the renderer cannot draw is refused by name
- [todo] P3.2: dense line plots draw no markers by default
- [todo] P3.3: long titles wrap to the figure, and the legend leaves the peaks clear

## Phase 4: the interface

- [todo] P4.1: the orbital table in the job drawer grows instead of scrolling when there is room
- [todo] P4.2: the job drawer no longer darkens the chat beside it
- [todo] P4.3: a Print theme with a white field, near-black text and no scrollbars
- [todo] P4.4: the approval card's input box fits its content and long notes fold away

## Phase 5: closing out

- [todo] P5.1: README and docs updated for the user-visible changes
- [todo] P5.2: deployed with scripts/update.sh after a full backup
