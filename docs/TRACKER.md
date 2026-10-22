<!-- artifact: https://claude.ai/artifact/8GM78aCjxJhpesEdmNq938 -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Active Tracker: the README rebuilt around animated demos

**Opened 2026-10-22.** Five phases. The tracker before this one is
[`trackers/2026-10-questdb-benchmark.md`](trackers/2026-10-questdb-benchmark.md).
**Exactly one tracker is active at a time.**

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: one path that
  exists on disk plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final change.
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <path> → "<observed result>"   (required when done)
```

---

## Why this plan exists

On 2026-10-22 the user asked for a README like NextTex's.

- **Less text up front:** the detail moves into other files.
- **A storyboard of animated demos:** short looping clips filmed in the real
  app, one claim each.
- **Readable at a glance:** a reader should understand the app before
  reading any prose.

The plan of record is `.claude/plans/tranquil-jumping-peacock.md`. It holds
the storyboard: a hero and eight tour scenes.

## Phase 1: the filming pipeline

- [done] P1.1: recorder and camera ported from NextTex into tests/frontend/tour/
  evidence: tests/frontend/tour/tour.mjs → "hero filmed: 304 frames, 28.0 s, 3.44 MB at 1280 px; the 3Dmol viewer is captured; the clean-up diff left nothing behind"
- [done] P1.2: hero prompt reaches the approval card three times in a row with no follow-up question
  evidence: tests/frontend/tour/tour.mjs → "probe-hero x3: the card appeared after 8 s, 7 s and 8 s, with no auto-corrected banner"
- [todo] P1.3: hero filmed in dark, frames reviewed, advisor consulted

## Phase 2: the tour scenes

- [todo] P2.1: scene 1, it asks instead of guessing
- [todo] P2.2: scene 2, a molecule from one word
- [todo] P2.3: scene 3, orbitals on a finished job
- [todo] P2.4: scene 4, the ensemble spectrum's live broadening
- [todo] P2.5: scene 5, vibrations
- [todo] P2.6: scene 6, a chart drawn and restyled by asking
- [todo] P2.7: scene 7, troubleshooting a failed job (or a still if it is not repeatable)
- [todo] P2.8: scene 8, filing jobs into a project (filmed last)
- [todo] P2.9: hero in light; active-space still added to docs_shots.mjs
- [todo] P2.10: snapshot diff after filming is empty: no thread, job, plot or project left behind

## Phase 3: moving the text

- [todo] P3.1: docs/GUIDE.md holds the README's feature prose, limitations and example prompts
- [todo] P3.2: docs/DEPLOYMENT.md holds the installer, update and shared-service prose, merged without duplication

## Phase 4: the new README

- [todo] P4.1: README rewritten: hero, three cards, short install, tour, capability table, how it works, what leaves the machine, docs
- [todo] P4.2: rendered as GitHub renders it; every image loads and every link resolves; install_01_static passes

## Phase 5: review and close

- [todo] P5.1: the user has seen every clip before any image is committed
- [todo] P5.2: CHANGELOG and TESTING.md updated, public-safety scan passes, pushed to origin, tracker closed
