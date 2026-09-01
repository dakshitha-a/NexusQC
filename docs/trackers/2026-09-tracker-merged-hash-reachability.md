# Tracker: the merged-hash check never checked reachability

**Complete as of 2026-09-01. One step in one phase, done.**
The `merged:` row records the commit it landed as.

It stays here rather than moving to [`trackers/`](trackers/) until the next
plan starts, which is when it gets archived and a fresh tracker takes its
place. **Exactly one tracker is active at a time.**

## How tracking works here

Development is linear, so there is never a reason to have two trackers open at
once. Each plan, feature or non-trivial request gets its own tracker, this file
is whichever one is currently in motion, and when its plan is finished the file
is closed out and moved to [`trackers/`](trackers/), then a fresh one starts
here for whatever comes next.

Closed trackers are kept, never deleted. They are the audit trail for why the
code looks the way it does, and code comments cite them by path. The one this
replaces is
[`trackers/2026-09-check-cannot-poison-output.md`](trackers/2026-09-check-cannot-poison-output.md)
-- 2 steps in one phase, closed 2026-09-01.

## Rules (enforced by `scripts/check_tracker.py`)

- Step status is exactly one of `todo` | `in-progress` | `done`.
- A step may be marked `done` **only with an evidence field**: the
  verification script/command path plus a one-line observed result.
- The tracker edit ships **in the same commit** as the step's final code
  change, so `git log --follow docs/TRACKER.md` is the audit trail.
- A phase's `merged` row records the commit hash the stage landed as.

Format for a step row:

```
- [status] P<phase>.<step>: <short name>
  evidence: <script/command> → "<observed result>"   (required when done)
```

---

## Why this plan exists

`scripts/check_tracker.py`'s own docstring said a merged phase's hash "must
have that hash reachable in git history". The implementation asked
`git cat-file -e <sha>^{commit}`, which is a different and much weaker
question: is this object in the database at all.

An amended-away commit stays in the object database, dangling, until git
prunes it. So the single most likely way to get a wrong hash into a tracker
slipped straight through the check that exists to catch it: read the hash from
`HEAD`, write it into the tracker, then amend that same commit to include the
tracker edit. The amend changes the hash, the row now names a commit that is
not on the branch, and the validator reports the tracker consistent.

That is not hypothetical. It happened in this session, one commit before this
one, and it was caught by hand rather than by the script whose job it was.

The fix is to ask the question the docstring already claimed: is this commit an
ancestor of `HEAD`. Development here is linear on `main`, so a merged phase's
commit either is or is not part of this history. The two failure modes are
worth distinguishing in the message, because they mean different things to
whoever reads it: a hash that never existed is a typo, and a hash that exists
but is unreachable is a rewritten history.

## Phase 1: Ask the question the docstring already promised

- [done] P1.1: Reachability from HEAD, not presence in the object database
  evidence: scripts/check_tracker.py -> "Exercised against all three cases using the real dangling commit this session produced. 9751b85, which exists in the object database but was amended away, is now rejected with 'exists but is NOT reachable from HEAD -- amended or rebased away after the row was written?' where git cat-file -e accepted it and the script passed. A hash that never existed is reported separately as 'does not exist in this repository', because a typo and a rewritten history call for different responses. The correct hash still passes. All 35 archived trackers re-audited under the stricter rule: no unreachable hashes. A shallow clone downgrades unreachable to a note, since it genuinely cannot see far enough back to judge"

- merged: 28480d8
