# Handoff

Work that finished in a session but still needs a person, or a machine, to
do something before it is really done. A session cannot see the previous
session's conversation, so anything left half-landed has to be written here
or it is lost.

Delete an entry once it is done. An empty "Open" section is the normal
state of this file.

## Open

### The dev stack is one commit behind on its build stamp (2026-09-10)

Cosmetic, and it needs you rather than a session because updating a live
deployment is not something the agent is allowed to do unattended here.

`scripts/update.sh --dry-run` in this checkout reports every gate passing,
`no image rebuild needed`, and no jobs running or pending. The only thing
behind is the stamp: the api image and the frontend bundle were built from
`288e69c`, the checkout is at `2d0fbd2`, and until they agree `update.sh` will
keep reading this deployment as stale and rebuilding it. Nothing in the
installer audit changes anything the image contains, so there is no hurry.

```bash
cd /data/qcuser/9.NexusQC/NexusQC-dev-repo && scripts/update.sh
```

It takes a full backup first and prints the same impact report the dry run
showed. The one warning it raises is accurate and worth reading: the
backup/restore/update tooling itself changed in this work, so the recovery
path you already trust is the one that should produce the backup.

The audit's own end-to-end verification did not depend on this. `update.sh`
was run in full, twice, against a scratch deployment built for the purpose:
once as `--dry-run` and once for real, which is the only way to prove the new
`scripts/lib/common.sh` is sourced before the fast-forward rewrites it mid-run.


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

