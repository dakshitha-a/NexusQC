<!-- artifact: https://claude.ai/artifact/8GM78aCjxJhpesEdmNq938 -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Closed Tracker: the README rebuilt around animated demos

**Closed 2026-10-23. Twenty-eight steps in five phases, all done; released as v1.3.0.**
No tracker is active until the next plan begins. Findings left for the
user are listed under their own heading below.

**Opened 2026-10-22.** Five phases. The tracker before this one is
[`trackers/2026-10-questdb-benchmark.md`](2026-10-questdb-benchmark.md).
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
- [done] P1.3: hero filmed in dark, frames reviewed, advisor consulted
  evidence: tests/frontend/tour/tour.mjs → "hero-dark.webp: 254 frames, 33.8 s, 2.58 MB; card heading 'Approve excited-state energies job for formaldehyde'; the advisor reviewed the first cut"

## Phase 1A: bugs the hero's first cut showed (raised along the way)

- [done] P1A.1: the approval card filed the registry's TDDFT note under "Structural check didn't recognize part of this input"
  evidence: frontend/src/approvals/JobApprovalCard.tsx → "notes are tagged severity 'note' in tools.py and shown in their own neutral box; draft_01_approval_card 11/11"
- [done] P1A.2: a TDDFT card listed want_oscillator_strengths=false as a default, beside a result that carried intensities
  evidence: tests/backend/elic_01_draft_scenarios.py → "HF and DFT join CMS-PDFT as methods that always compute intensities, so the flag is hidden; elic_01 206/206, wig_01 all passed, p8_04 18/18"
- [done] P1A.3: "colour the HOMO and LUMO red" was reported done and drawn orange; the level diagram's colours were constants
  evidence: tests/backend/plot_05_job_charts.py → "colours by legend label (Occupied, Virtual, HOMO, LUMO, HOMO / LUMO) and palette; an unknown label is refused; 0 failures, plot_02 and plot_07 0 failures"
- [done] P1A.5: the approval card's heading read "Approve single_point/ee job,  formaldehyde"
  evidence: tests/frontend/draft_01_approval_card.spec.mjs → "the card now says 'Approve excited-state energies job for formaldehyde' from the registry's TaskDef.label; the payload's task_label landed in 5533e8c"
- [done] P1A.6: troubleshooting a failed job never named its molecule, so the model asked for one, or would have drafted the fix on whatever the conversation held
  evidence: tests/backend/fail_01_notice_flow.py → "the message carries the structure, charge and multiplicity with a set_geometry instruction; the failure card says 'single-point energy job on PySCF'; the test now uses the v2 job shape and deletes its job; 23/23"
- [done] P1A.4: the fixes deployed with scripts/update.sh, after a full data backup, before the final filming
  evidence: scripts/update.sh → "updated 0d9706a0983b -> fdcf367ca887; QC_AGENT_BUILD_COMMIT is fdcf367; the hero probe reached 'Approve excited-state energies job for formaldehyde' in 9 s with no auto-corrected banner"

## Findings left for the user (seen while filming, not changed)

- **Degenerate orbital levels print their numbers on top of each other** in
  the level diagram (benzene's 18/19, 20/21). Readable, but untidy.
- **The single-geometry UV/Vis figure is in nm**, with oscillator strength
  on the y axis. The ensemble spectrum is in eV and normalised to 1. Whether
  the single-geometry figure should match is a convention question.

- **`fail_01_notice_flow` is flaky against a running stack**: two runs in
  six on 2026-10-22 found no notice and no job_failed event. The live api
  container's watcher reads the same `data/`, so it can report the job
  before the test's in-process watcher. It fails the same way without this
  plan's changes.

- **The active-space recommendation contradicts itself on the smaller
  size.** For formaldehyde (three states) the summary says "A smaller
  CAS(2e, 2o) is available", while the sizes table lists minimal as 6e, 4o
  with the recommended tier's own rationale. The CAS engine is changed only
  with a benchmark run, so this is left for a decision.
- **The single-orbital entropy chart** labels its x axis at 0.5 steps for
  whole orbitals, and its title runs past the plot's right edge.

## Phase 2: the tour scenes

- [done] P2.1: scene 1, it asks instead of guessing
  evidence: tests/frontend/tour/tour.mjs asks → "asks.webp: 91 frames, 16.1 s, 0.35 MB; the reply asks for the basis and nothing is submitted"
- [done] P2.2: scene 2, a molecule from one word
  evidence: tests/frontend/tour/tour.mjs molecule → "molecule.webp: 140 frames, 26.5 s, 0.65 MB"
- [done] P2.3: scene 3, orbitals on a finished job
  evidence: tests/frontend/tour/tour.mjs orbitals → "orbitals.webp: 132 frames, 40.7 s, 1.11 MB; isosurfaces drawn, isovalue slider moves"
- [done] P2.4: scene 4, the ensemble spectrum's live broadening
  evidence: tests/frontend/tour/tour.mjs spectrum → "spectrum.webp: 107 frames, 26.6 s, 0.84 MB; 64 transitions from 16 of 16 samples"
- [done] P2.5: scene 5, vibrations
  evidence: tests/frontend/tour/tour.mjs vibrations → "vibrations.webp: 137 frames, 24.2 s, 0.88 MB"
- [done] P2.6: scene 6, a chart drawn and restyled by asking
  evidence: tests/frontend/tour/tour.mjs plots → "plots.webp: 195 frames, 25.5 s, 1.37 MB; the HOMO and LUMO turn red"
- [done] P2.7: scene 7, troubleshooting a failed job (or a still if it is not repeatable)
  evidence: tests/frontend/tour/tour.mjs troubleshoot → "troubleshoot.webp: 82 frames, 18.8 s, 1.14 MB; ends on the drafted fix's approval card"
- [done] P2.8: scene 8, filing jobs into a project (filmed last)
  evidence: tests/frontend/tour/tour.mjs projects → "projects.webp: 93 frames, 23.3 s, 0.82 MB; filmed after the scenes that need the job list"
- [done] P2.9: hero in light; active-space still added to docs_shots.mjs
  evidence: tests/frontend/tour/tour.mjs → "hero-light.webp: 215 frames, 36.4 s, 2.56 MB; active-space.png written by the active-space scene"
- [done] P2.10: snapshot diff after filming is empty: no thread, job, plot or project left behind
  evidence: tests/frontend/tour/tour.mjs → "every scene printed left behind {threads:[], jobs:[], plots:[], projects:[]}"

## Phase 3: moving the text

- [done] P3.1: docs/GUIDE.md holds the README's feature prose, limitations and example prompts
  evidence: docs/GUIDE.md → "eleven sections moved verbatim by line range, links rewritten for docs/ and all resolving; the 'four things' sentence that listed three now names DuckDuckGo; the results screenshot's caption describes what it shows"
- [done] P3.2: docs/DEPLOYMENT.md holds the installer, update and shared-service prose, merged without duplication
  evidence: docs/DEPLOYMENT.md → "added installer flags, unattended install, the ten steps, the context-window note, 'Running it for a group', password resets and orphaned directories; the update sections were already there and gained the force-stop sentence only"

## Phase 4: the new README

- [done] P4.1: README rewritten: hero, three cards, short install, tour, capability table, how it works, what leaves the machine, docs
  evidence: README.md → "377 lines, down from 1127: hero, three cards, short install, nine-row tour, capability table, how it works, what leaves the machine, docs"
- [done] P4.2: rendered as GitHub renders it; every image loads and every link resolves; install_01_static passes
  evidence: tests/backend/install_01_static.py → "27/27 checks passed; rendered through GitHub's markdown API and previewed at claude.ai/artifact/4bhJnNDcmPbKDVRZ5wunvw"

## Phase 5: review and close

- [done] P5.1: the user has seen every clip before any image is committed
  evidence: docs/tour/hero-dark.webp → "the user reviewed every clip on a review page and the full README preview, and said: looks good. release"
- [done] P5.2: CHANGELOG and TESTING.md updated, public-safety scan passes, pushed to origin, tracker closed
  evidence: scripts/check_public_safe.sh → "PASS - nothing blocking found in 1074 files; CHANGELOG 1.3.0 section and TESTING.md tour section written; pushed to origin"
- [done] P5.3: raised mid-run: release v1.3.0 to the public repo once the README and clips are in; the changelog section is cut, the release dry run passes, and the public remote matches origin with the v1.3.0 tag
  evidence: CHANGELOG.md → "scripts/release.sh 1.3.0 published f3fb533; public/main equals origin/main, tag v1.3.0 is on the public remote, and github.com/dakshitha-a/NexusQC/releases/tag/v1.3.0 exists"
- [done] P5.4: raised mid-run: the updater stops sending the CAS benchmark cache to Docker; .dockerignore excludes .cache and the build context drops from about 22 GB to under 1 GB
  evidence: .dockerignore → "a COPY . probe image measured the context at 74 MB, down from 21.9 GB in the 2026-10-23 update log"
- [done] P5.5: raised mid-run: a first version is live on the public repo by 2 PM on 2026-10-23, for a walkthrough; filming goes ahead despite the host load
  evidence: docs/tour/hero-dark.webp → "live on the public repo at 12:39 on 2026-10-23; raw README, GUIDE and every clip return 200"
