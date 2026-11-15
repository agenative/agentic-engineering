---
name: sync-matt-skills
description: >-
  Pull the mattpocock/skills clone and resync Cursor/GitHub Copilot symlinks in
  agentic-engineering so every engineering and productivity skill is linked and
  orphans are removed. Use when the user asks to sync Matt Pocock skills, update
  mattpocock skills after a git pull, refresh skill symlinks, or run sync-matt-skills.
disable-model-invocation: true
---

# Sync Matt Pocock skills

Keep personal IDE skills in sync with the sibling `mattpocock/skills` clone.

## Layout (do not change)

- Clone: `~/git/skills` (sibling of `~/git/agentic-engineering`)
- Global Cursor root: `~/.cursor/skills` → `agentic-engineering/.cursor/skills`
- This skill: `agentic-engineering/.cursor/skills/sync-matt-skills/`
- Script: `scripts/sync.sh` beside this file

## What to run

Execute the sync script with unrestricted permissions (network `git pull` + writes outside the workspace):

```bash
~/.cursor/skills/sync-matt-skills/scripts/sync.sh
```

Flags:

- default: `git pull --ff-only` in `~/git/skills`, then sync `.cursor/skills` and `.github/skills`
- `--cursor-only` / `--github-only`: limit destinations
- `--skip-pull`: only resync links

## After the script

1. Summarize pull result, links created/updated, orphans pruned, and any `SKIP` local dirs.
2. Spot-check a few paths resolve (`test -f ~/.cursor/skills/tdd/SKILL.md`).
3. Note that a new Cursor chat may be needed before newly added skills show up.

## Rules

- Do not copy Matt Pocock skills into application repos.
- Do not overwrite local skill directories (jira, ada-e2e-test, sync-matt-skills, etc.).
- Do not delete non-mattpocock symlinks (e.g. into `.claude/skills`).
