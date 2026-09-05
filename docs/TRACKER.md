# Tracker

**In motion, opened 2026-09-05.** Fifteen phases.

Closing out the CAS recommendation engine. Every entry `docs/BACKLOG.md` carries
about this engine leaves during this plan, and none of them comes back. When it
finishes, `docs/CAS_ENGINE_METHOD.md` is rewritten from the final benchmark run
to describe the implementation as it then stands.

It follows [`trackers/2026-09-cas-engine-audit.md`](trackers/2026-09-cas-engine-audit.md),
which closed on 2026-09-04 at 43 steps across eleven phases, and that follows
[`trackers/2026-09-cas-engine-rebuild.md`](trackers/2026-09-cas-engine-rebuild.md).

## Rules (enforced by scripts/check_tracker.py)

Format for a step row:

    - [status] P<phase>.<step>: <short name>
      evidence: <script/command> -> "<observed result>"   (required when done)

Status is `todo`, `in-progress` or `done`. A `done` step carries an evidence
line whose first token is a path that exists. A phase records `merged:` only
when every step in it is done, and the hash has to be reachable from `HEAD`.
The tracker edit ships in the same commit as the step's final code change, so
`git log --follow docs/TRACKER.md` is the audit trail.

## The three doors

Every backlog entry leaves through exactly one, and the step that closes it says
which:

1. **Fixed.** A code change, validated across the benchmark, with a named
   regression molecule.
2. **Decided.** A product or design question settled deliberately and recorded
   in the method document.
3. **Measured and stated.** A real limitation, quantified, written into the
   method document with the measurement behind it.

A limitation reported with its number attached is not an open item. That is what
makes emptying the backlog honest rather than cosmetic.

## A change to perception is a change to everything downstream of it

Inherited from the audit, and it applies to the measurements and not only to the
results. A change under `app/chemistry/cas/geometry.py` or `projector.py` is
validated against every `cas_*` test plus `--set spaces`, `--set narrowed`,
`--set refine` and `--set nevpt2`. The last two are hours. That is the cost of
changing perception, not a reason to skip them.

The corollary governs this plan's shape: every engine change lands before the
final sweep, the sweep runs once at the final commit, and no number reaches the
method document from a mid-flight run.

## Why this plan exists

Three things made a third round necessary rather than optional.

**No committed ledger measures the shipped engine.** `spaces.md` is stamped
`86b8dc3`, `narrowed.md` `ad4a86e`, `refine.md` and `nevpt2.md` `77b692d`,
against a `HEAD` of `2049bc5`; `stability` and `excited` have never had one
committed at all. So every quantitative claim in the method document is
provisional.

**Four defects surfaced during planning that no backlog entry names**, one of
them a latent crash on a corrective path that has therefore never run.

**Two backlog entries are wrong about their own subject.** o-Nitrophenol does
finish inside the benchmark cap; the molecules that do not are anthracene and
p-benzoquinone. Acrolein's missing orbital was explained by the audit's P7.1 and
the entry was written as though it were not.

### Decisions taken with the user before starting

Transition metals go to the depth of fixing the covalent radii and measuring the
recommendation path, with the document stating exactly which stages are
exercised. Rydberg states are explored as a capability to ship rather than
settled by refusal, with methylamine at SA(2)/aug-cc-pVDZ CAS(8e,9o) as the
worked case and a pivot to refusal only if the valence path breaks. Bistability
is censused across the benchmark and then reported, so that every excitation
energy carries the reference energy it was taken from.

## Phase 0: A baseline that can be trusted

- [done] P0.1: Ledger records a dirty working tree
  evidence: scripts/casbench/ledger.py -> "stamp reads 2049bc5+dirty with the source edited and 2049bc5 clean; the first attempt reported clean either way, because a pathspec resolves against the cwd it is run in and that is this file's own directory"
- [todo] P0.2: All six sets at the baseline commit, committed as the "before"
- merged: -

## Phase 1: The latent defects in the refinement's narrowing

- [todo] P1.1: The in-loop narrowing raises TypeError and has never run
- [todo] P1.2: The budget fallback narrows a ground-state request
- [todo] P1.3: Remove the drift detection that can no longer fire
- merged: -

## Phase 2: Narrowing that is reproducible and never degenerate

- [todo] P2.1: A deterministic pool classification
- [todo] P2.2: A narrowed tier that is a full space is not published
- [todo] P2.3: Narrowing stability becomes a standing test
- merged: -

## Phase 3: Twisted ethylene, diagnosed before it is fixed

- [todo] P3.1: Separate the three candidate mechanisms
- [todo] P3.2: Fix on the diagnosis
- [todo] P3.3: Every molecule bit-identical across four runs
- merged: -

## Phase 4: Rydberg states, explored as a capability

- [todo] P4.1: Separate what the method cannot do from what the basis cannot
- [todo] P4.2: Assemble the Rydberg reference cases
- [todo] P4.3: Serve a Rydberg state
- [todo] P4.4: The decision gate, and the branch it selects
- [todo] P4.5: The states-not-looked-for report reaches a user
- merged: -

## Phase 5: Transition metals, to the depth chosen

- [todo] P5.1: Covalent radii for the rows that had none
- [todo] P5.2: Metal complexes in the benchmark
- [todo] P5.3: The recommendation path measured, and its boundary stated
- merged: -

## Phase 6: MINIMAL_ENTROPY_GAP, given the validation pass it was denied

- [todo] P6.1: Sweep over the final molecule set
- [todo] P6.2: The effect on the refinement start tier and the cost report
- [todo] P6.3: Apply it or do not, and record why
- merged: -

## Phase 7: The audits that claim more than they measured

- [todo] P7.1: A verdict says when it rests on a guess smaller than the space
- [todo] P7.2: The two state audits agree about the same state
- merged: -

## Phase 8: Bistability, a census and then honest reporting

- [todo] P8.1: How many molecules have more than one converged solution
- [todo] P8.2: Every excitation energy carries the reference energy it came from
- merged: -

## Phase 9: Cost, caps, and the two molecules that do not finish

- [todo] P9.1: Correct the record about which molecules exceed the cap
- [todo] P9.2: Anthracene and p-benzoquinone, uncapped
- [todo] P9.3: A space that cannot be built is reported, not enforced
- merged: -

## Phase 10: Measure NEVPT2 in the space a user actually receives

- [todo] P10.1: The set requests the states it reports on
- merged: -

## Phase 11: ROOT_MARGIN, formally withdrawn

- [todo] P11.1: Recorded as settled, removed from the backlog
- merged: -

## Phase 12: The final sweep

- [todo] P12.1: All six sets at the final commit, refinement uncapped
- merged: -

## Phase 13: Rewrite the method document

- [todo] P13.1: Rewritten from the final ledgers
- [todo] P13.2: Settle the hand-written measurement write-ups
- merged: -

## Phase 14: Every surface, then the backlog

- [todo] P14.1: Every surface that describes the engine
- [todo] P14.2: The backlog carries no CAS entry
- merged: -

## Found along the way
