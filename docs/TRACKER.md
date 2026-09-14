# Tracker: the first public release

**Publishing NexusQC 1.1.0 to the public repository.** Three phases: clean the
tip and fix the release tooling, rewrite history a second time, then release.
The tracker this replaces is
[`trackers/2026-09-fixing-what-the-review-found.md`](trackers/2026-09-fixing-what-the-review-found.md),
which closed with all 102 review findings resolved. **Exactly one tracker is
active at a time.**

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

Re-render and re-publish the artifact at every step completion:

```bash
python3 scripts/render_tracker_html.py /tmp/tracker.html
```

---

## Why this plan exists

The public repository holds two README-only placeholder commits and the README's
one-line install URL 404s until a release lands. `scripts/release.sh` exists for
this, and could not run on 2026-09-14 for five reasons, each verified rather
than assumed:

1. The tree scan failed: twenty host-path hits under
   `docs/evaluation/2026-09-app-review/` in files the log-only redaction never
   covered, plus the lab hostname in two `e2e-run.log` files.
2. The history scan the pre-push hook applies to a public push failed on
   ~4,580 blobs carrying this host's paths, the hostname and the tailnet
   address; the first tainted commit is from 2026-08-19, so 575 of 790 commits
   descend from it. `release.sh` never ran that scan itself, so the failure
   would have surfaced after the tag and the private push.
3. No scanner looked at commit metadata: 319 commits were authored under the
   lab hostname and 208 under a personal address.
4. `release.sh`'s placeholder gate recognised one parentless README commit;
   the public remote had two.
5. `CHANGELOG.md` had a never-tagged `[1.0.0]` and ~2,200 lines under
   `[Unreleased]`.

Decisions the user made on 2026-09-14, recorded so they are not re-asked:

1. **Rewrite history a second time** rather than publish host paths.
2. **Version 1.1.0.**
3. **Scrub the tailnet address too**, replacing it inside 100.64/10.
4. **Publish the evidence logs and screenshots as they are.**
5. **Every commit email becomes the GitHub noreply address.**

## Phase 1: Clean the tip and fix the release tooling

- [done] P1.1: Archive the finished tracker, open this one
  evidence: docs/trackers/2026-09-fixing-what-the-review-found.md → "moved from docs/TRACKER.md with a Closed heading; this file replaces it"
- [done] P1.2: Redact the evaluation tree completely
  evidence: docs/evaluation/2026-09-app-review/evidence/redact_paths.py → "--check reports 0 identifiers in 0 files after 27 were replaced across 16 files (.md, .mjs, .log); the table is derived at runtime and the hostname, tailnet address, email and scratchpad path come from the untracked redact_terms.local"
- [done] P1.3: Scanner: /data safe-list, commit-email check, honest truncation
  evidence: scripts/check_public_safe.sh → "tree scan PASS on 1006 files; --range on one hostname-authored commit (0aa4122) fails with 'commit author/committer email at an institutional host'; clip prints 'showing 25 of 30' on 30 lines and nothing on 0"
- [done] P1.4: release.sh: placeholder gate, history gate, push order, confirmation
  evidence: scripts/release.sh → "rehearsed end to end in a scratch clone against two local bare remotes seeded with the real two-commit placeholder: --dry-run passed all ten gates including the minute-long history scan; end-of-input on the prompt aborted with nothing pushed and no tag; 'RELEASE' stamped CITATION.cff 1.1.0, replaced the placeholder and landed main plus v1.1.0 on both remotes, public first"
- [done] P1.5: Docs, CHANGELOG 1.1.0, commit email config
  evidence: CHANGELOG.md → "## [1.1.0] - 2026-09-14 heads the release notes with an empty Unreleased above it and the 1.0.0 heading annotated; DEVELOPMENT.md, WORKFLOW.md and CLAUDE.md describe the new gates; this checkout's git user.email is the noreply address"
- [done] P1.6: Gate A: tree scan passes, touched tests pass, pushed to origin
  evidence: scripts/check_public_safe.sh → "PASS on 1006 tracked files; deploy_02 14/14 and deploy_03 11/11; check_tracker PASS; pushed as 8cede57, which the rewrite below renamed to 98ccc87"
- merged: 98ccc87

## Phase 2: Rewrite history

- [done] P2.1: Mirror backup of the checkout
  evidence: docs/DEVELOPMENT.md → "git clone --mirror of the checkout at 8cede57 (791 commits, 63 MB) written to a sibling directory named NexusQC-dev-repo-pre-rewrite.git before anything was rewritten; yours to delete once satisfied"
- [done] P2.2: Rehearse in a scratch clone until three checks are clean
  evidence: scripts/check_public_safe.sh → "on the rewritten clone: tree PASS (1007 files), --range HEAD PASS over all 791 commits (4631 files materialised), raw grep over every reachable blob finds only the published contact addresses, github URLs and account usernames; 1581 of 1582 author/committer emails are the noreply address and the other is GitHub's own"
- [done] P2.3: Apply to the checkout, remap tracker merged rows, force-push origin
  evidence: scripts/check_tracker.py → "checkout reset to the rewritten tip with a byte-identical tree; 165 merged: rows and 307 hash citations across 103 files remapped by unique prefix through the commit-map, all reachable from HEAD; origin/main force-pushed with lease from 8cede57 to 78b712e"
- merged: 78b712e

## Phase 3: Release

- [todo] P3.1: Dry run shown to the user
- [todo] P3.2: Live release on the user's go
- [todo] P3.3: Verify the public remote, rebuild the dev stack, clear the handoff
