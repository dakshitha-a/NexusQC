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

- [todo] P1.1: a job that finishes while its owner is logged out has a summary waiting on return (e2e_17 L9b)
- [todo] P1.2: the job drawer shows only the sections a job's results support
- [done] P1.3: an empty orbital on one atom is not labelled a lone pair
  evidence: scripts/validate_orbital_character.py → "all checks passed; water/cc-pVDZ orbital 10 (empty, all oxygen) now sigma*, no empty orbital is n, the occupied lone pairs stay n"
- [todo] P1.4: a mistyped functional or basis gets suggestions (e2e_11)
- [todo] P1.5: a draft built on another job's geometry reaches ready (e2e_12)

## Phase 2: drafting reaches the approval card

- [todo] P2.1: ensemble and conical-intersection requests reach a card rather than a question (e2e_21)

## Phase 3: performance and test reliability

- [todo] P3.1: dragging the orbital scrubber renders one cube, not three
- [todo] P3.2: deploy_05 passes while other suites load the stack

## Phase 4: data and decisions

- [done] P4.1: no ownership row names a job that does not exist, except the one left by decision
  evidence: app/auth/models.py → "40 job rows deleted by explicit id in one transaction (qatest_admin 20, dakshitha 20, Aug-Sep); 16 remain, the only orphan is dma's, kept by decision; none was in a project; today's 20 API deletes left none behind"
- [done] P4.2: the aza-naphthalene n->pi\* limitation is documented and planned
  evidence: docs/CAS_ENGINE_METHOD.md → "§4.4 states the 12 misses, the +2.3 to +6.0 eV range, APC-2 10 of 12 and the azines 33 of 42; BACKLOG carries it with the next experiment; the HANDOFF decision item is closed"
- [in-progress] P4.3: nginx and the app see real client addresses (userland proxy off)

## Phase 5: closing out

- [todo] P5.1: docs and CHANGELOG updated for the user-visible changes
- [todo] P5.2: deployed with scripts/update.sh and the touched suites pass on the stack
