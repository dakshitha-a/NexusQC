<!-- artifact: https://claude.ai/artifact/6VtufKXwCNjDRk5b5NRhCv -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Tracker: clearing the backlog

**Opened 2026-11-10.** Five phases. The tracker before this one is
[`trackers/2026-11-thesis-screenshot-fixes.md`](trackers/2026-11-thesis-screenshot-fixes.md).

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

On 2026-11-10 the user asked for everything open in `docs/BACKLOG.md` and
`docs/HANDOFF.md` to be prioritised and fixed. Most backlog entries date from
the September review and had not been rechecked, so each step starts by
reproducing the failure on the current code; an entry that no longer
reproduces is closed with that evidence rather than "fixed".

Order: anything that breaks leave-and-return first, because that workflow
is the reason jobs run detached; then wrong things the user sees; then agent
behaviour; then performance and test reliability; then data clean-up and the
decisions only a person could make.

The user's decisions, taken 2026-11-10:

- Orphaned ownership rows: remove the 40 belonging to `qatest_admin` and
  `dakshitha`; leave the one belonging to `dma`.
- QUESTDB aza-naphthalene n->pi\* misses: a separate plan later; record it now
  as a documented limitation.
- Docker userland proxy: turn it off. The user runs the root steps through
  `hc-ask` when the change is ready.

## Phase 1: leave-and-return and what the user sees

- [done] P1.1: a job that finishes while its owner is logged out has a summary waiting on return (e2e_17 L9b)
  evidence: tests/e2e/e2e_17_logout_and_return.py → "21/21 on the stack; L9b was a test race (read once when the notice appeared, while the summary turn still ran); invoke_turn_if_idle needs no live session"
- [done] P1.2: the job drawer shows only the sections a job's results support
  evidence: tests/e2e/ui/ui_02_approval_jobs_drawer.spec.mjs → "19/19 alone on 4a409cc; the drawer was right, the test keyed jobs on method (level of theory since v2); sections now checked against each job's own data"
- [done] P1.3: an empty orbital on one atom is not labelled a lone pair
  evidence: scripts/validate_orbital_character.py → "all checks passed; water/cc-pVDZ orbital 10 (empty, all oxygen) now sigma*, no empty orbital is n, the occupied lone pairs stay n"
- [done] P1.4: a mistyped functional or basis gets suggestions (e2e_11)
  evidence: tests/e2e/e2e_11_param_correction.py → "8/8 on 4a409cc; suggestions always worked (b3lp->b3lyp, ccpvdz->cc-pvdz); C2/C5 read spec.params.method, which v2 moved to spec.method"
- [done] P1.5: a draft built on another job's geometry reaches ready (e2e_12)
  evidence: tests/e2e/e2e_12_source_geometry.py → "in-process G1 turn: approval card with source_geometry_job_id and the source water geometry, no set_geometry; the test waited for DRAFT READY text that a direct-to-card draft never sends"

## Phase 2: drafting reaches the approval card

- [done] P2.1: ensemble and conical-intersection requests reach a card rather than a question (e2e_21)
  evidence: tests/backend/draft_09_target_state_count.py → "12/12; e2e_21 on 4a409cc: ensemble 3/3 (drafts its opt_freq prerequisite, user decision), others 3/3; CI 3/3 in-process with the count derived from the crossing pair; also fixed an S1 CASSCF opt running on S0"

## Phase 3: performance and test reliability

- [done] P3.1: dragging the orbital scrubber renders one cube, not three
  evidence: tests/e2e/ui/ui_09_orbital_and_mode_panels.spec.mjs → "0 during the drag, 1 in total on 4a409cc (was 3 and 4); the vibration half needs a job with modes, absent on the test account"
- [done] P3.2: deploy_05 passes while other suites load the stack
  evidence: tests/README.md → "root cause is one session per account, not load: a second login 401s the first browser; deploy_05 alone clicks through (13/15, the two misses were my concurrent e2e_21 users); suites sharing an account now documented as one at a time"

## Phase 4: data and decisions

- [done] P4.1: no ownership row names a job that does not exist, except the one left by decision
  evidence: app/auth/models.py → "40 job rows deleted by explicit id in one transaction (qatest_admin 20, dakshitha 20, Aug-Sep); 16 remain, the only orphan is dma's, kept by decision; none was in a project; today's 20 API deletes left none behind"
- [done] P4.2: the aza-naphthalene n->pi\* limitation is documented and planned
  evidence: docs/CAS_ENGINE_METHOD.md → "§4.4 states the 12 misses, the +2.3 to +6.0 eV range, APC-2 10 of 12 and the azines 33 of 42; BACKLOG carries it with the next experiment; the HANDOFF decision item is closed"
- [in-progress] P4.3: nginx and the app see real client addresses (userland proxy off)

## Phase 5: closing out

- [done] P5.1: docs and CHANGELOG updated for the user-visible changes
  evidence: docs/GUIDE.md → "ensemble prerequisite described; CHANGELOG Unreleased lists the orbital label, job-finished row, dipole, open axis, Type 42, ensemble prerequisite, Wigner phrasing, scrubber and state-count fixes; tests/README one-account note; CAS_ENGINE_METHOD 4.4"
- [done] P5.2: deployed with scripts/update.sh and the touched suites pass on the stack
  evidence: tests/e2e/e2e_21_draft_reaches_card.py → "stack 9b01639: all five cases 3/3 carded; ui_02 19/19 and now deletes its own job; e2e_11 8/8, e2e_17 21/21, ui_09 scrubber 0/1 renders; test account back to one thread, no jobs"
