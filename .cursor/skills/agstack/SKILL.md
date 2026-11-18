---
name: agstack
description: Orchestrate Cursor agent work through reusable playbooks, native TODO tracking, sequential execution, and verification. Use when asked to run AgStack or its smoke-test playbook.
---

# AgStack Orchestrator

Coordinate the selected playbook from start to completion. Do not stop after creating the TODO list.

## Playbook routing

Match the user's request to the most appropriate playbook.
Read the selected playbook before creating tasks. Do not assume its contents.
Only use a playbook that exists; report an unknown playbook instead of inventing one.

- **Smoke test.** Verify AgStack orchestration by executing
  two dummy tasks. File: `playbooks/smoke-test.md`.
- **Bug fix.** Reproduce, diagnose, fix, and verify a
  reported defect. File: `playbooks/bug-fix.md`.
- **Remove feature.** Scope, grill, test, and remove a
  feature described in a Jira ticket. File: `playbooks/remove-feature.md`.
- **troubleshoot-local-setup.** Troubleshoot agent-services or any agents having local startup issue. File: `playbooks/troubleshoot-local-setup.md`.

## Routing rules

1. Prefer an explicitly requested playbook.
2. Otherwise select the closest matching description.
3. If multiple playbooks match, prefer the one that
   directly addresses the user's primary goal.
4. If none match, explain the gap rather than inventing
   a playbook.
5. Read only the selected playbook.
6. Copy its numbered steps verbatim into Cursor's
   native TODO list.
7. Execute the TODO steps in order, respecting their
   dependencies and completion conditions.
