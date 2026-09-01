# Tracker: sharing jobs and project archives between users

**Complete as of 2026-09-01. Eighteen steps across six phases, all done.**
The `merged:` row on each phase records the commit it landed as.

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
replaces is the placeholder that stood after
[`trackers/2026-08-plotter-and-casscf-intensities.md`](trackers/2026-08-plotter-and-casscf-intensities.md)
closed on 2026-09-01.

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

NexusQC is multi-user but nothing in it is shareable. `ownership_index` has
`PRIMARY KEY (kind, resource_id)`, so a resource has exactly one owner by
construction; `check_owner_or_admin` answers 404 to everyone else and
`owned_ids_filter` strips other users' rows out of every list route. Two people
in the same group who want to look at the same CASSCF result have no way to do
it short of an admin account.

The request was for user-to-user sharing of an individual job or a whole project
archive, with the picker looking people up by name or username, and with one
hard requirement: **the recipient keeps access even if the owner deletes the
original.**

That requirement settles the central design question. A reference share cannot
satisfy it, and collides with the codebase in three places: `_evict` and
`purge_user_data` in `app/auth/storage_quota.py` delete a job without consulting
anyone but its owner; `add_jobs` in `app/projects/registry.py` enforces one
project per job in a single atomic write, so donor and recipient could not both
file the same job; and the "unowned means visible to everyone" rule is
duplicated inline in three list routes, so a share check would have to land in
each of them. **A copy is the opposite: the recipient's copy is an ordinary job
they own, and neither `app/auth/ownership.py` nor any list filter changes.**

Four things were settled with the user before any code was written. The copy
counts against the **recipient's** quota and a share that does not fit is
**refused rather than evicting** their own jobs. A share arrives as a **pending
offer they accept**, so nobody can push gigabytes into another account unasked.
The picker does **prefix search across all active users**. And the inbox lives
as a **"Shared with me" section in the left rail**, beside Projects.

Two further decisions were taken during planning, with reasons. **Masters copy
as a whole family**, because a scan or Wigner master whose children were left
behind renders an empty panel, and refusing to share masters would exclude
exactly the multi-hour runs most worth sharing. **Conversations are out of
scope**, because copying LangGraph checkpoints lives behind `_graph_lock` and
doing it from these routes would break the lock-free contract `jobs.py` and
`projects.py` both hold.

The invariant the whole feature rests on: **`spec.json` is written last, and
ownership is recorded before it.** Every job-listing walk gates on `spec.json`
existing, so a half-built copy is invisible to listing, quota and deletion, and
a crash leaves a spec-less directory that `reclaim_orphan_job_dirs()` already
sweeps. Recording ownership first closes the window where a visible job has no
owner, which is the shape of the F-022 and SEC-06 bugs.

## Phase 1: The offer table, the model helpers and the user lookup

- [done] P1.1: A resource_shares table and its model helpers
  evidence: psql \di resource_shares* against the running stack -> "table plus all three indexes present after the api container rebuilt: resource_shares_pending_idx is PARTIAL on status='pending', so re-offering a declined job is legal while a duplicate pending offer raises UniqueViolation. set_share_status is a compare-and-set carrying status='pending' in its WHERE, so two accept clicks racing leave one winner and the loser gets None rather than copying the job twice"
- [done] P1.2: A user search that exposes no more than it must
  evidence: tests/backend/share_01_user_search.py -> "15/15. The projection is asserted key by key rather than by a no-secrets heuristic: exactly id/username/first_name/last_name, so neither _user_public (email, role) nor get_user_by_login (password_hash) can be swapped in later without failing here. A user is findable by first or last name, not only by handle; the caller is excluded from their own results; a 0- or 1-character query returns [] rather than the roster; '%%' is escaped to a literal; a suspended account is not offerable; anonymous callers get 401"

- merged: 82f2009


## Phase 2: The copy primitive

- [done] P2.1: Copy one job, spec.json last and ownership first
  evidence: tests/backend/share_02_copy_fidelity.py -> "17/17. The write order is the atomicity: every job-listing walk gates on spec.json, so a half-built copy is invisible to listing, quota and deletion, and a crash leaves a directory reclaim_orphan_job_dirs already sweeps. Ownership is recorded BEFORE that final write, because a visible job with no ownership row is visible to every user. worker_pid and worker_pid_create_time are stripped so no cancel path can act on a pid from the machine that ran the original"
- [done] P2.2: Artifact paths rewritten, including nested cubes
  evidence: tests/backend/share_02_copy_fidelity.py -> "The decisive check is the last one: the sender deletes their original and the recipient's copy still opens AND still serves every artifact (molden 200). Rewriting is recursive because cubes is a nested dict; a top-level-only walk would leave every orbital cube pointing at the sender. No path still contains the source job id, and the sender cannot read the recipient's copy (404)"
- [done] P2.3: Plot-rooted artifacts copied into the recipient's own space
  evidence: tests/backend/share_05_master_and_plots.py -> "15/15. A uvvis_spectrum artifact points into PLOTS_DIR, not the job directory. The copy gets a NEW plot id under the recipient's own owner directory with its own ownership row, and the image is still served after the sender deletes their job and their plot. Reusing the path would both serve the sender's file cross-user and pin it forever, since sweep_orphans only reclaims a plot once its last source job is gone"
- [done] P2.4: A master copies as a whole family
  evidence: tests/backend/share_05_master_and_plots.py -> "A real pes_1d scan is copied with every child: fresh ids, parent_job_id repointed at the new master, children.jsonl regenerated, _scan_index preserved so images keep their order. Children are asserted to be deliberately UNOWNED, matching submit -- _job_candidates does not skip child jobs, so an owned child would be an independent eviction candidate and quota pressure could delete one out from under its master. Counts are asserted against the source, not a hardcoded three, because a 3-point scan currently yields five sub-jobs (docs/BACKLOG.md)"

- merged: 82f2009


## Phase 3: Quota headroom and the share lifecycle

- [done] P3.1: A headroom check that refuses instead of evicting
  evidence: tests/backend/share_04_quota_refusal.py -> "8/8. With the per-user cap squeezed to 1 byte the accept returns 409 reading 'This share needs 6.1 KB but you have 0 B left of your 1 B job and chat allowance', and the check that matters is the next one: the recipient's own jobs are all still there. Every other quota path evicts; this one must not, because the bytes arrive on somebody else's initiative. The offer stays pending rather than being consumed, and accepts cleanly once the quota is restored"
- [done] P3.2: The lifecycle routes, in their own module
  evidence: tests/backend/share_03_lifecycle.py -> "34/34. A new server/routes/shares.py rather than additions to jobs.py or projects.py, every handler a plain def. Offering copies NOTHING into the recipient's account, which is what makes withdraw possible at all. Third parties get 404 not 403 on every route so share ids cannot be probed; the sender cannot accept their own offer and the recipient cannot withdraw; a malformed share id is 404 rather than 500. A duplicate PENDING offer is refused by the partial unique index while re-offering after a decline works. An unfinished job cannot be offered"
- [done] P3.3: Accepting a project share
  evidence: tests/backend/share_03_lifecycle.py -> "The recipient gets their OWN project holding their own copies: the new project's job_ids share no id with the sender's, so neither add_jobs' one-project-per-job rule nor the sender's own archive is disturbed, and the sender still has their original project afterwards"

- merged: 82f2009


## Phase 4: The share dialog and the user picker

- [done] P4.1: The API client and query layer
  evidence: frontend/src/lib/api.ts (verified with tsc -b and npm run lint) -> "clean, and no warning from any new file. A Sharing section in lib/api.ts with narrow UserSearchRow and ShareRow types; useShareInboxQuery polled at 8s like useProjectsQuery, since an offer arrives from another user's session entirely and there is no SSE event behind it. Both hooks take an `enabled` gate because the sharing router is only mounted when auth is configured"
- [done] P4.2: A share dialog with a fuzzy user picker
  evidence: tests/frontend/share_02_render_and_rail.spec.mjs -> "29/29. The dialog renders, the search field is focused on open so typing just works, Send is disabled until somebody is picked, and a query matching nobody renders an explicit empty state rather than a blank box. Deliberately does NOT copy ProjectDeleteDialog's onOpenAutoFocus override: there focus is taken off the buttons so no answer happens by reflex, here the search box is what the user wants first"
- [done] P4.3: Entry points on jobs and projects
  evidence: tests/frontend/share_01_share_roundtrip.spec.mjs -> "25/25. Reachable from the job manager's selection bar (single selection only, since a share is one offer of one thing), the job drawer's header action row for a finished job, and the project row's hover cluster. Labelled 'Send a copy' rather than 'Share' for two reasons: it says what actually happens, and Playwright's has-text is a case-insensitive SUBSTRING match, so a control named 'Share' would also match 'Shared with me' in the rail"

- merged: 09a02b6


## Phase 5: The inbox in the left rail

- [done] P5.1: A Shared with me section with a pending count
  evidence: tests/frontend/share_02_render_and_rail.spec.mjs -> "29/29. Renders empty and populated, aria-expanded correct both ways, and the row stays inside the rail at both 220px and 520px (195px in 220, 495px in 520) with no horizontal page scroll and no PanelErrorBoundary fallback at any point. Collapsing the rail and RELOADING still shows a Shared with me icon in the collapsed strip, which is the state a returning user lands in since leftRailCollapsed persists"
- [done] P5.2: Accept and decline, and where the copy lands
  evidence: tests/frontend/share_01_share_roundtrip.spec.mjs -> "Two accounts in two browser contexts, because one session per user is enforced in Redis. Bob's job list is empty while the offer is pending, so offering really does copy nothing; accepting puts the copy in his job manager and clears the badge; declining leaves him with just the one job he already accepted; Alice withdrawing a third offer removes it from his inbox"
- [done] P5.3: A provenance badge on a received job
  evidence: tests/frontend/share_01_share_roundtrip.spec.mjs -> "The copy carries a 'from <sender>' badge in the job manager, the same icon-plus-10px-muted-text shape as the project badge above it, fed by a shared_from field on meta.json surfaced through _job_row. Without it a received copy is indistinguishable from a job the user ran themselves"

- merged: 09a02b6


## Phase 6: The whole workflow in a browser, and the docs

- [done] P6.1: The share round trip, driven end to end
  evidence: tests/frontend/share_01_share_roundtrip.spec.mjs -> "25/25 in headless chromium. One continuous session across two accounts: register both, seed three jobs, find a colleague by SURNAME rather than handle, send, watch the pending count appear, accept, confirm the copy has its own job id and a sender badge, decline a second, withdraw a third. The decisive check is last: Alice deletes her original and Bob's copy still returns 200. Console and page errors collected throughout and an empty collection is itself a check"
- [done] P6.2: Every new component renders, at both rail widths
  evidence: tests/frontend/share_02_render_and_rail.spec.mjs -> "29/29, and proj_03_render_and_rail.spec.mjs still 38/38 after LeftRail changed. The picker publishes a human name and no email address, asserted on the rendered row rather than on the API response"
- [done] P6.3: The docs say why a share is a copy
  evidence: docs/ARCHITECTURE.md -> "A Sharing section covering the decisions worth not relitigating: why a copy rather than a grant and the three places a grant collides with the codebase, why spec.json is written last and ownership recorded before it, the two artifact shapes a directory copy gets wrong, why a master's children stay unowned, why accepting refuses instead of evicting, what the picker publishes, and why conversations are excluded. README.md and CHANGELOG.md carry the user-facing version; docs/BACKLOG.md carries two incidental findings"

- merged: 09a02b6
