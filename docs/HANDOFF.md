# Handoff

Work that finished in a session but still needs a person, or a machine, to
do something before it is really done. A session cannot see the previous
session's conversation, so anything left half-landed has to be written here
or it is lost.

Delete an entry once it is done. An empty "Open" section is the normal
state of this file.

## Open

### The app review is complete; triage is the next step (2026-09-13)

The September 2026 app review (Phases 0-6 of `docs/TRACKER.md`) is finished. The
deliverable is `docs/evaluation/2026-09-app-review/`:
- `report.md` -- the narrative report, published as an artifact at
  https://claude.ai/code/artifact/e8cb6337-524e-41db-83c8-5addeecce9be
- `findings.md` -- 104 register entries (R-001..R-103 plus the cleared R-102):
  **8 S1 (all confirmed), 25 S2, 53 S3, 15 S4**; 39 confirmed, the rest
  suspected-from-code-read with their settling step named.
- `baseline.md`, `perf.md`, `evidence/` -- the supporting record.

**What the user asked comes next, and it is not this session's to do:** enter
plan mode and start the resolution (fix) phase once the report is read. Triage
assigns a confirmed severity and a fix/defer/won't-fix decision to each finding;
then a fresh tracker (shaped like `trackers/2026-08-clearing-the-backlog.md`)
does the fixing, in severity order, R-004 first.

**A few things left open on purpose, for the fix phase, each with its experiment
named in the register:**
- R-098 (fair-scheduler admission order): cause between a real regression and a
  test race is unsettled; instrument `scheduler._order`/`_rr_pos` at admission.
- R-099 (refinement drawer's empty occupation table): seed a `cas_reco/refine`
  job and inspect its `result.json` for `natural_occupations` and the
  `refined_*` gating key.
- R-103 (api RSS doubled over the review): idle-settle measurement to tell a
  cache from a leak.
- e2e_13 / e2e_08 M23 ORCA-under-load failures: re-run in isolation to classify
  ENV vs CODE (see `evidence/p1-notes.md`).

**The friction log (`friction-log.md`) is yours to fill** from real daily use;
its entries merge into the register as comfort findings. It was empty at close.

The stack is at the frozen `ca7e0ff` still; the fix phase should let it move.
The review's test data was fully torn down (two-sided verify clean).


### Three new images need a human look before the public release (2026-09-09)

`scripts/check_public_safe.sh` cannot read images, which docs/DEVELOPMENT.md
already says. The UI pass added or replaced three, and they are the only things
in this change that a scan cannot vouch for:

- `docs/screenshot.png` and `docs/screenshot-results.png`, retaken because the
  redesign made the old ones show an app that no longer exists. Both are
  driven from the live dev stack by `tests/frontend/docs_shots.mjs`, so they
  contain **this deployment's real conversation labels and job names**, on the
  sidebar and in the job manager. They are chemistry names rather than
  anything host-specific, but they are your data and nobody but you should
  decide they are publishable.
- `docs/brand-sheet.png`, which is synthetic (the mark at every size on two
  fields, plus the palette) and carries nothing from the deployment. Listed
  only so the set is complete.

Regenerate either at any time:

```bash
node tests/frontend/brand_sheet.mjs
QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 node tests/frontend/docs_shots.mjs
```

`docs_shots.mjs` drives a real agent turn to reach the approval card, deletes
the conversation it creates, and declines the job rather than leaving it
queued.

### The one-liner install URL needs a public release (2026-09-08)

README.md and docs/DEPLOYMENT.md now lead with:

```bash
curl -fsSL https://raw.githubusercontent.com/dakshitha-a/NexusQC/main/scripts/install.sh | sh
```

**That URL 404s today.** The public repository still holds only the placeholder
README it was created with; `origin/main` is several hundred commits ahead of
it. The one-liner starts working the moment `scripts/release.sh <version>`
runs, and not before.

Everything that gated a release is now cleared. `scripts/check_public_safe.sh`
passes (it was failing with three blocking categories: real host paths in
docs/HANDOFF.md, three tracker documents and data/verified/orca_functionals.txt,
plus two false positives that were narrowed rather than edited around). What is
left is the decision, which is yours, plus a `## [x.y.z]` section in
CHANGELOG.md, since release.sh refuses without one. The Unreleased section is
written and ready to be renamed.

A public push cannot be taken back, which is why this is here rather than done.
Until it happens, the honest install instruction is the `git clone` variant
directly beneath the one-liner in both documents, which works today against the
private remote.


### Installing the agent auto-resume watchdog (2026-09-06, one command)

A long agent run was asked to survive a usage limit and resume itself. The
in-session half is done and needs nothing. The durable half needs one command
from you, because installing a crontab entry is not something the agent is
permitted to do.

Everything else is already in place under `~/.claude/nexusqc-resume/`:
`resume.sh` is written and executable, `state/resume_prompt.txt` holds what the
resumed session is told, and `state/WORK_INCOMPLETE` is the sentinel that arms
it. The script no-ops unless the sentinel exists, the heartbeat at
`state/heartbeat` is more than 90 minutes stale, and no `claude` process is
running for this project, so it cannot start a second agent on top of a live
one. That guard was tested: with the heartbeat forced three hours stale it
correctly stood down and logged why.

To arm it:

```bash
( crontab -l 2>/dev/null; \
  echo "*/13 * * * * $HOME/.claude/nexusqc-resume/resume.sh" ) | crontab -
```

The previous crontab is backed up at `~/.claude/nexusqc-resume/state/crontab.backup`
(it contained only a `PATH=` line).

To disarm it when the run is finished, delete
`~/.claude/nexusqc-resume/state/WORK_INCOMPLETE`, which is enough on its own,
and remove the crontab line when you want the watchdog gone entirely. Logs land
in `~/.claude/nexusqc-resume/logs/`.

This is deliberately outside the repository. It hardcodes this machine's paths
and a particular worktree, which is exactly what `CLAUDE.md` says must never be
committed.

