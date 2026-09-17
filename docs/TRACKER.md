<!-- artifact: https://claude.ai/artifact/QPYdYFx8zo2GaJvMxVkLN7 -- re-render with scripts/render_tracker_html.py and re-publish to THIS url -->
# Tracker: mid-plan amendments and subagent models

**Active since 2026-09-16.** One phase. The tracker this replaces is
[`2026-09-first-public-release.md`](trackers/2026-09-first-public-release.md),
which closed with v1.1.0 published. **Exactly one tracker is active at a
time.**

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

Two workflow problems the NextTex repository solved on 2026-09-15 exist here
too, and the user asked for the same treatment.

**Tasks given mid-plan get dropped.** Work here starts in plan mode, and the
user gives new tasks while the plan is being executed. The rule to fold them
into the plan lived in memory and in the tracker instructions, and a rule in
the model's context is weakest exactly when a plan has run long enough for
the context to be crowded. NextTex enforces the timing from the harness
instead: a hook script wired to `ExitPlanMode`, `UserPromptSubmit` and
`SessionStart` marks a session as executing an approved plan and stamps every
later user message with the rule while the marker exists.

**Every subagent runs on the session model**, which is Opus, so read-heavy
searches are billed at Opus rates for no gain. NextTex overrides the built-in
`Explore` with a project definition on Sonnet and states in `CLAUDE.md` which
launches are lowered and which are not.

**One deliberate adaptation.** NextTex says the plan file is the ledger. Here
the ledger is `docs/TRACKER.md`, committed and machine-checked, so an
amendment lands in both the plan file (for approval) and the tracker (as a
step marked raised mid-run), and the marker is cleared when the tracker is
closed out.

Decisions the user made on 2026-09-16: `.claude/settings.json` becomes a
tracked file carrying the three hooks. The objection that kept it untracked
was to a hook on every Bash call, which these are not; the push guard stays
opt-in.

## Phase 1: The hooks, the agent definition, the documents

- [done] P1.1: Open this tracker, publish it as an artifact
  evidence: docs/TRACKER.md → "published from scripts/render_tracker_html.py output; URL recorded in the header comment; check_tracker PASS on 8 steps"
- [done] P1.2: `scripts/hooks/claude_plan_amendment.py`: started, prompt, session, done
  evidence: scripts/hooks/claude_plan_amendment.py → "nine synthetic-input cases from a scratch CLAUDE_PROJECT_DIR: a tool_response without filePath writes no marker; an approval writes amendments 0 and a second approval amendments 1 with the 'amended plan' text; prompt prints nothing for a session without a marker, the amendment text naming the plan file and docs/TRACKER.md in default mode, the merge-not-restart text in plan mode; session omits its own marker and lists a foreign one; done refuses with two markers, removes a named or lone one, errors on a missing one; garbage stdin exits 0, a bad action exits 2 with usage"
- [done] P1.3: `.claude/settings.json` tracked, with plansDirectory and the three hooks; gitignore
  evidence: .claude/settings.json → "json.tool parses it; three hooks on PostToolUse:ExitPlanMode, UserPromptSubmit and SessionStart, each python3 on the script with timeout 10, plus plansDirectory .claude/plans; .gitignore lists .claude/plans/ and .claude/plan-in-progress/; the push guard is not in the tracked file and its example's header says why"
- [done] P1.4: `.claude/agents/Explore.md` on Sonnet, with this repository's map
  evidence: .claude/agents/Explore.md → "a scratch `claude -p --model opus` session in this checkout launched one Explore agent (subagent_type Explore in the parent transcript); the subagent transcript under ~/.claude/projects shows claude-sonnet-5 on all 13 of its assistant messages and the parent claude-opus-5; the agent found that app/chemistry/jobs/registry.py no longer exists, which corrected the map and a stale CLAUDE.md bullet"
- [done] P1.5: `CLAUDE.md` and `docs/WORKFLOW.md`: the amendment rule and the subagent rule; example file and push-guard docstring corrected
  evidence: docs/WORKFLOW.md → "rules 9 and 10 added and a paragraph under 'One active tracker at a time'; CLAUDE.md gains Subagents and the amendment section plus two summary bullets, and its 'deliberately opt-in' paragraph is scoped to the per-Bash-call scan; the example file and claude_push_guard.py's docstring no longer claim settings.json is untracked; README needs nothing (its only Claude Code mention is the credits line)"
- [todo] P1.6: Stale watchdog entry removed from `docs/HANDOFF.md`
- [done] P1.7: Verify: synthetic hook input, scratch session with an Explore agent, scans
  evidence: scripts/check_public_safe.sh → "PASS on 1024 files with no host path in the hook script, agent definition or settings; compileall over scripts/hooks clean; no em dash in any touched file; check_tracker PASS"
- [todo] P1.8: Pushed; tracker closed out and archived
