---
name: design-a-feature
description: >-
  Design a feature through research gate then design gate (each via seek-review
  on RESEARCH.md / DESIGN.md) until implementation-ready. Use when the user wants
  to design-a-feature, produce RESEARCH.md/DESIGN.md, or iterate a design before
  coding.
---

# Design a feature

Turn initial thoughts into an **implementation-ready** `DESIGN.md` via *research
stage* → *research gate* → *design stage* → *design gate*. Prefer monorepo
primary sources and existing practices over invention.

**Leading words:** *research stage*, *research gate*, *design stage*, *design gate*, *review gate*, *seek-review*, *second thought*, *implementation-ready*.

## Outputs

| Artifact | When | Role |
| --- | --- | --- |
| `RESEARCH.md` | Research stage | Findings, citations, outstanding questions, high-level design |
| `RESEARCH.review.html` + feedback JSON | Research gate | seek-review of `RESEARCH.md` |
| `DESIGN.md` | Design stage (after research gate) | Implementation contract |
| `DESIGN.review.html` + feedback JSON | Design gate | seek-review of `DESIGN.md` (every iteration) |

Default location: next to the feature module (or repo convention). Say where if choosing.

Do **not** implement production code unless the user asks after `DESIGN.md` is implementation-ready.

## Review gate

Shared *review gate* protocol (research or design). Run [`seek-review`](../seek-review/SKILL.md) on the named document end-to-end. Point at review HTML paths; do **not** re-narrate the document in chat. Wait for a verdict (or explicit chat acceptance if the user declines seek-review).

**Verdict → fold into the source document (not chat-only):**

- **Request changes:** fold feedback, more work as needed, re-run seek-review, return to this gate.
- **Approve with edits:** fold first; re-run seek-review only if the user wants another pass; then proceed.
- **Approve:** proceed.

## Steps

### 1. Capture initial thoughts

Collect goals, non-goals, preferences, and suspected dependencies (libraries, services, queues, APIs). Ask at most 1–2 **blocking** questions if the target or success condition is ambiguous; otherwise proceed.

**Done when:** a short brief exists — enough to start research, not a full design.

### 2. Research stage — legwork

Investigate against **primary sources** in this monorepo and first-party docs.

- Follow [`research`](../research/SKILL.md): prefer background agents; cite owning sources.
- Map dependencies; find **sample projects** that already use them; borrow fits, note gaps.
- Prefer existing practices over greenfield invention when they fit.

**Done when:** every suspected dependency is traced to a primary source (or marked unknown with a concrete question), and at least one analogous in-repo usage has been checked when such usage exists.

### 3. Write `RESEARCH.md`

Create or overwrite. Required shape: load [`document-templates.md`](document-templates.md) (**RESEARCH.md** section).

**Done when:** file exists at the chosen path, cites sources for major claims, states outstanding questions, and includes required diagram(s).

### 4. Research gate

Run the *review gate* on `RESEARCH.md`.

**Done when:** *research gate* cleared — user accepted `RESEARCH.md`. Never draft `DESIGN.md` before this.

### 5. Design stage — write `DESIGN.md`

Only after the research gate. Required shape: load [`document-templates.md`](document-templates.md) (**DESIGN.md** section). Treat `DESIGN.md` as the implementation contract; when it diverges from `RESEARCH.md`, update DESIGN and note the resolution.

**Done when:** a competent implementer could start an implementation plan without inventing major structure.

### 6. Clarify and update design

Ask 1–2 critical questions when a choice materially forks the design; otherwise lock a sensible default in `DESIGN.md` and proceed. Update `RESEARCH.md` only if historical findings need correction.

**Done when:** every material fork is decided in `DESIGN.md` or waiting on an explicit user answer just asked.

### 7. Second thought after every DESIGN update

After each material edit, re-read the whole design (use the second-thought checklist in [`document-templates.md`](document-templates.md)). Fix contradictions in the same turn; skip cosmetic churn.

**Done when:** a full pass finds no contradictions (or all found issues are fixed).

### 8. Design gate

After every material `DESIGN.md` update (and its *second thought*), run the *review gate* on `DESIGN.md`. On request-changes or approve-with-edits that need another pass: fold → steps 6–7 as needed → return here.

**Done when:** *design gate* cleared — user accepted this `DESIGN.md` iteration.

### 9. Gate: implementation-ready

Only after the design gate is cleared. Confirm:

- Module boundaries and key types/APIs are specified.
- End-to-end runtime flow is specified (with sequence diagram).
- Config, errors, and feature-flag/bypass behaviour are specified.
- Test plan and implementation phases are specified.
- No blocking open questions remain (deferred items are explicit non-goals or follow-ups).

If gaps remain: update `DESIGN.md`, *second thought*, re-run the *design gate*, then return here.

**Done when:** checklist satisfied and you state `DESIGN.md` is implementation-ready (path included). Do not start coding unless the user asks.
