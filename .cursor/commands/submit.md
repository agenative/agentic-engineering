# Submit

1. Discover this repo’s lint, test, and CI-equivalent commands (package scripts, Makefile, workflows).
2. Run the full quality gate (lint → typecheck → tests → build/CI checks).
3. On failure: fix root causes (never weaken checks), then re-run until green.
4. When all pass: stage relevant files, commit with a concise why-focused message, and push (`git push -u origin HEAD`).
5. If remote CI fails on this change: fix, re-gate, commit, push, repeat until green or blocked.
6. Never commit secrets, design and planning documents, force-push to main/master, or skip hooks unless asked. Report checks, commit, push, and CI status.
7. Create PR if not exist with professional descriptions. Always include design session with context diagram of key components of the update and a sequence diagram to show their interaction. Include test evidence at the end to show completeness.
