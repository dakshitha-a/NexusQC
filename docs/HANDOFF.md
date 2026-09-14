# Handoff

Work that finished in a session but still needs a person, or a machine, to
do something before it is really done. A session cannot see the previous
session's conversation, so anything left half-landed has to be written here
or it is lost.

Delete an entry once it is done. An empty "Open" section is the normal
state of this file.

## Open

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

