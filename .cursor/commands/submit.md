# Submit

1. Discover this repo’s lint, test, and CI-equivalent commands (package scripts, Makefile, workflows).
2. Run the full quality gate (lint → typecheck → tests → build/CI checks).
3. On failure: fix root causes (never weaken checks), then re-run until green.
4. When all pass: stage relevant files, commit with a concise why-focused message, and push (`git push -u origin HEAD`).
5. If remote CI fails on this change: fix, re-gate, commit, push, repeat until green or blocked.
6. Never commit secrets, design and planning documents, force-push to main/master, or skip hooks unless asked. Report checks, commit, push, and CI status.
7. Create PR if not exist with professional descriptions. Always include design session with context diagram of key components of the update and a sequence diagram to show their interaction. If demo scripts are built, provide steps/commands to setup the local environment (e.g. `make local`) and run the demo script. Include test evidence at the end to show completeness.
8. Ensure the PR with proper babysit but don't duplicate work.
9. Before calling finish: check the PR for merge conflicts (and resolve/rebase if any) so the branch is merge-ready.

# PR summary style

Write the PR **Summary** as outcome bullets, not implementation narrative.

**Do**
- One bullet per user-visible outcome or architectural decision
- Name components only when they are the deliverable (new endpoint, demo script, migration)
- Put setup commands, test output, and diagrams in their own sections (already required above)

**Don't**
- Walk through control flow, node order, or error-routing step by step
- List class/function names, collection names, or idempotency mechanics unless essential to the decision

## Example

Bad: This change adds a `UserService` that calls `repo.upsert()` after validation, routes `ProfileError` to `END`, classifies checkpoint threads into NEW/AWAITING/APPROVED, and the demo script reads JWT from env with `--no-pause` and `--scenario` flags.

Good:
- Add human approval before publishing generated configs
- Persist configs idempotently so resume/replay is safe
- Terminate early on profile validation failures
- Add local demo script (setup steps below)
