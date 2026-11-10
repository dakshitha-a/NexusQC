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
- [done] P2.2: a nuclear-ensemble or Wigner request in plain words drafts wigner_spectra
  evidence: tests/backend/draft_04_task_phrases.py → "18/18; and two real agent turns with the thesis phrasings (qwen3.8:27b, scratch data dir) drafted wigner_spectra, not single_point/ee"
- [done] P2.3: a rejected draft can be dropped, and a request for a different task starts a new draft
  evidence: tests/backend/draft_05_declined_drafts.py → "8/8; real turns after Reject: 'Drop that draft.' called discard_job_draft and cleared it, and a frequency request started a fresh freq draft"
- [done] P2.4: a job drafted after a converged optimisation uses the optimised geometry, and the card says so
  evidence: tests/backend/draft_06_followup_geometry.py → "8/8; real turn: water opt 4600ce5dba8a completed, then 'compute its vibrational frequencies' drafted freq with source_geometry_job_id=4600ce5dba8a"
- merged: d693611

## Phase 3: plots

- [done] P3.1: spectra overlays take a per-series line style, and an edit the renderer cannot draw is refused by name
  evidence: tests/backend/plot_08_series_styles_and_layout.py → "19/19; real turn 'Make the B3LYP curve dashed.' sent line_styles and v2.png shows B3LYP dashed, PBE0 solid"
- [done] P3.2: dense line plots draw no markers by default
  evidence: tests/backend/plot_08_series_styles_and_layout.py → "2000-point overlay drawn with no marker; 12-point custom line keeps circles"
- [done] P3.3: long titles wrap to the figure, and the legend leaves the peaks clear
  evidence: tests/backend/plot_08_series_styles_and_layout.py → "the 68-character thesis title wraps on 8 in; y top 1.2+ above normalised peaks; plot_02-07 and spec_01 all pass"
- merged: 81b605d

## Phase 4: the interface

- [done] P4.1: the orbital table in the job drawer grows instead of scrolling when there is room
  evidence: tests/frontend/ui_09_drawer_card_print.spec.mjs → "water/STO-3G's 7 orbitals at text size 1.35: table scrollHeight 488 = clientHeight 488"
- [done] P4.2: the job drawer no longer darkens the chat beside it
  evidence: tests/frontend/ui_09_drawer_card_print.spec.mjs → "no overlay with a background; chat scrolled 1050 -> 650 by wheel with the drawer open; Escape closes it"
- [done] P4.3: a Print theme with a white field, near-black text and no scrollbars
  evidence: tests/frontend/ui_09_drawer_card_print.spec.mjs → "body rgb(255,255,255), text rgb(17,20,24), muted rgb(58,63,71), scrollbar-width none; Print in the picker"
- [done] P4.4: the approval card's input box fits its content and long notes fold away
  evidence: tests/frontend/ui_09_drawer_card_print.spec.mjs → "formaldehyde ORCA card: input scroll 0 px (was 94), long note folded to 86 px with Show all; 15/15 via the Vite dev server"
- merged: 1dcfe05

## Phase 5: closing out

- [done] P5.1: README and docs updated for the user-visible changes
  evidence: docs/GUIDE.md → "post-opt geometry, declined drafts, dashed curves and the Print theme described; CHANGELOG Unreleased lists all twelve; README chart blurb still accurate"
- [todo] P5.2: deployed with scripts/update.sh after a full backup
