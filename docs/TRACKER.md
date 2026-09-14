<!-- artifact: https://claude.ai/code/artifact/2bff34bb-0c8e-4d5b-b38d-0887df7d20fe -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
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

## Phase 2B: The issue pipeline, before the release

Added on 2026-09-14 after the dry run passed: the user wants users to report
bugs and request features on the public repository, the maintainer to work
them in sessions here, and releases to close them, and the same flow to serve
maintainer-originated features. It ships in 1.1.0 so the public repository
lands with its templates, CI and contributor docs on day one. Decisions the
user made: PRs are accepted and land through the development repository with
authorship preserved; issues close at release, not when fixed; CI runs on both
repositories; all three in-app bridges (version in Help with prefilled issue
links, an admin "File on GitHub" action, build and browser captured on
in-app reports).

- [done] P2B.1: Inbound: issue forms, intake and CI workflows, CONTRIBUTING, SECURITY, README
  evidence: .github/workflows/ci.yml → "the four checks it runs (bash -n over 12 scripts, compileall over app/server/scripts/tests, the public-safety scan, check_tracker) all pass locally the way the job runs them; the frontend job's `npm ci && npm run build` is the same command tsc -b passed on here; issue-intake is gated on the event's repository being public and the sender not being the owner; blank issues off"
- [done] P2B.2: Version identity: git describe stamped into the image, /api/version, Help About
  evidence: tests/frontend/gh_01_version_and_issue_links.spec.mjs → "after scripts/update.sh rebuilt the dev stack, /api/version answers {commit: 938d633..., version: 938d633} and the image carries org.opencontainers.image.version; Help → About renders 'NexusQC 938d633 (938d6332f93f)', the copy button puts exactly that on the clipboard and reads Copied, and both links open the public forms with template= and version= set; screenshot looked at"
- [done] P2B.3: In-app bridge: bug_reports captures build and browser; prefilled GitHub links
  evidence: tests/frontend/gh_01_version_and_issue_links.spec.mjs → "a report filed through the flyout comes back from the admin inbox with build_commit and build_version equal to the server's and a HeadlessChrome user agent; the inbox shows Build and Browser and File on GitHub carries the body and build; Open on GitHub in the flyout carries the typed text; the report is deleted in a finally block; conf_01 20/20 and sec_16 30/30 still pass; update.sh --dry-run reported the three columns with matching ALTERs and the live update added them"
- [done] P2B.4: Working an issue: /issue skill, scripts/issues.sh, labels, workflow docs
  evidence: scripts/issues.sh → "ensure-labels created triage, needs-info and fixed-on-main on dakshitha-a/NexusQC (gh label list shows all three with their descriptions); list on the empty tracker prints nothing and exits 0; the skill, WORKFLOW's 'Working a public issue' section, DEVELOPMENT's tracker paragraph, CLAUDE.md's bullet and tests/README's issue_ row all name the same vocabulary"
- [done] P2B.5: Outbound: release_announce.sh wired into release.sh, deploy_08 test
  evidence: tests/backend/deploy_08_release_announce.py → "27/27: previous tag ignores a non-release tag and, with HEAD itself tagged, still answers the earlier one; range and referenced issues exclude NexusQC-dev#n and a pre-tag reference; a Fixes #5 is warned about; a 140,035-byte section is cut to 185 bytes of head plus the link under GitHub's cap; dry run makes no gh call; live order is create, comment, unlabel, close with pr commands for a PR; a second run repeats nothing; one failing comment still closes the next item and exits 1 with the re-run line. Against the real checkout the dry run reports 794 commits, a 143,362-byte section to be cut, no issues, no closing keywords"
- [done] P2B.6: Gate: scans, suites, browser check, dev stack rebuilt, dry run re-shown
  evidence: scripts/release.sh → "tree scan PASS; deploy_01/02/03/08 and install_01/02 pass; CI green on the private repo for both jobs on the first real run (46 s) and the intake workflow parses and is skipped there (a throwaway issue produced a 'skipped' run, then deleted); issues.sh exercised on a public throwaway (new, list, needs-info, fixed; deleted); dev stack rebuilt with all 18 jobs intact; release.sh 1.1.0 --dry-run green with the announcement plan showing 143,362-byte notes to be cut, no issues, no closing keywords"

## Phase 3: Release

- [todo] P3.1: Dry run shown to the user, re-run after Phase 2B changed release.sh
- [todo] P3.2: Live release on the user's go
- [todo] P3.3: Verify the public remote, rebuild the dev stack, clear the handoff
