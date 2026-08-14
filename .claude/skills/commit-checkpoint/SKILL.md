---
name: commit-checkpoint
description: Use this proactively in this repository whenever a coherent unit of work has just been completed -- a new job type or engine integration, a new agent tool or capability, a UI feature, a real bug fix, or any other functional change worth being able to point to later. Do NOT invoke after trivial edits (typo fixes, comment/docstring tweaks, formatting, a single small refactor with no behavior change) -- let those ride along with the next real checkpoint instead of creating commit noise. Also use when the user explicitly asks to commit.
---

# Commit checkpoint

Create a single well-scoped git commit for the work just completed in this repository.

## When to actually commit

Ask: "if someone bisected history later, would they want a marker here?" Yes for a new capability, a fixed bug, a completed refactor, a working end-to-end feature. No for an in-progress edit, an experiment you're not sure survives, or a change smaller than one logical unit.

If several small edits accumulated toward one goal (e.g. a feature plus the test/debug fixes it took to get it working), that's **one** commit, not one per edit.

## Steps

1. `git status` and `git diff` (staged + unstaged) to see exactly what changed. Read the diff, don't guess from memory of what you edited.
2. Confirm nothing sensitive is being swept in -- check for stray `.env` files, credentials, tokens, or large generated artifacts that don't belong (the project `.gitignore` already excludes `data/`, `__pycache__/`, logs, etc.; if something outside that pattern looks like it shouldn't be committed, flag it before proceeding rather than committing it).
3. Stage the relevant files specifically (`git add <files>`), not `git add -A`, so unrelated in-progress changes elsewhere aren't swept in.
4. Write a commit message that explains **why**, not just what changed (the diff already shows what). One line if that's enough; a short body only if the reasoning needs it. Follow the style of recent commits (`git log --oneline -10`) once there's history to match.
5. Commit. Do not push unless the user has asked for that separately -- a local checkpoint is the goal here, not publishing.
6. Report back in one line what was committed and why it was a good checkpoint.

## Before pushing

Whenever a push is about to happen (whether or not this skill was used for the commit itself), check whether README.md needs updating first -- new capabilities, changed setup/run steps, new job types/engines, or other user-facing behavior changes documented there. Update it in the same commit (or a follow-up commit) before pushing, rather than after. Skip this only when the change genuinely has no README-visible surface (e.g. an internal refactor, a bug fix with no behavior change a reader would notice).

## What NOT to do

- Don't invoke this for every single file save -- that defeats the purpose of a checkpoint.
- Don't amend previous commits to fold in new work; each checkpoint is its own commit.
- Don't skip hooks (`--no-verify`) to force a commit through.
- Don't commit obviously broken/non-functional intermediate states just to have a checkpoint -- finish getting it working first, or note in the message that it's a known-incomplete checkpoint if the user specifically wants one anyway.
