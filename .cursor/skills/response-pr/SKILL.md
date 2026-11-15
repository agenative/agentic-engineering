---
name: response-pr
description: >-
  Triage GitHub pull-request review comments into verdicts, draft replies, plan
  code fixes, implement after approval, then e2e-test and post replies only after
  a second approval. Use when the user asks to handle, respond to, or address PR
  comments or review feedback.
---

# Respond to PR comments

Do not post replies or edit code until the user approves the matching step below.

1. Read every reviewer comment (inline threads and top-level). Fetch with `gh` (`gh api` review comments and GraphQL `reviewThreads`). Re-run the shell with `required_permissions: ["all"]` — the sandbox often reports GitHub as a connect or Forbidden failure. Understand each comment, research the code, and give a verdict: reply only, code fix, or no action.
2. For reply-only comments, draft a short concise reply. Do not post yet.
3. For code fixes, research thoroughly and run a small experiment when the approach is uncertain. The fix must be simple, agent-services oriented, and shown to work before implementation. Do not implement yet.
4. Present one plan for approval: every verdict, each drafted reply, and each proposed code fix.
5. After approval, implement the code fixes, then follow the `ada-e2e-test` skill and actually test the result.
6. Prompt the user with a summary that includes the replies still waiting to be posted. After they approve, post those replies inline on the matching threads.
