---
name: design-a-feature
description: >-
  Design a feature through research then detailed design (RESEARCH.md → DESIGN.md)
  until implementation-ready. Use when the user wants to design-a-feature, work out
  a design from initial thoughts, produce RESEARCH.md and DESIGN.md, or iterate a
  design spec before coding.
---

# Design a feature

Turn initial feature thoughts into an **implementation-ready** `DESIGN.md` via a
disciplined **research stage** then **design stage**. Prefer monorepo primary
sources and existing practices over invention.

**Leading words:** *research stage*, *design stage*, *second thought*, *implementation-ready*.

## Outputs

| Artifact | When | Role |
| --- | --- | --- |
| `RESEARCH.md` | Research stage | Findings, citations, outstanding questions, high-level design |
| `DESIGN.md` | Design stage | Implementation contract; source of truth once written |

Default location: next to the feature module (e.g. `<project>/…/<feature>/RESEARCH.md` and `DESIGN.md`). Match repo convention if one exists; otherwise choose a sensible path and say where.

Do **not** implement production code in this skill unless the user explicitly asks after `DESIGN.md` is implementation-ready.

## Steps

### 1. Capture initial thoughts

Collect the user's feature need, technical preferences, and constraints.

- Record goals, non-goals, and known preferences without drilling every edge case.
- Note suspected dependencies (libraries, services, queues, APIs) as research targets.
- Ask at most 1–2 **blocking** questions if the feature target or success condition is ambiguous; otherwise proceed.

**Done when:** a short brief exists (goals / preferences / suspected deps) sufficient to start research — not a full design.

### 2. Research stage — legwork

Investigate thoroughly against **primary sources** in this monorepo and, where relevant, first-party docs.

- Follow the project [`research`](../research/SKILL.md) skill: prefer background agents; cite owning sources (code paths, APIs, configs).
- Map dependencies the feature will touch.
- Find **sample projects** already interfacing with those dependencies; note patterns to borrow (and gaps to avoid).
- Prefer existing practices over greenfield invention when they fit.

**Done when:** every suspected dependency has been traced to primary sources (or marked unknown with a concrete question), and at least one analogous in-repo usage has been checked when such usage exists.

### 3. Write `RESEARCH.md`

Create or overwrite the research note. Required shape: load [`document-templates.md`](document-templates.md) and satisfy the **RESEARCH.md** section.

- Capture findings with source citations.
- Include a **high-level design** sketch (not implementation-ready detail).
- List **outstanding questions** that research could not answer.
- Include at least a **context diagram** (modules and relationships). Prefer a **sequence diagram** when interaction order matters.

**Done when:** `RESEARCH.md` exists at the chosen path, cites sources for major claims, states outstanding questions explicitly, and contains the required diagram(s).

### 4. Iterate the research stage

Keep updating `RESEARCH.md` until research is information-complete for design.

- Resolve outstanding questions via more legwork, user answers, or locked defaults with rationale.
- Fold clarifications into `RESEARCH.md` (do not leave decisions only in chat).
- Stop inventing detail that belongs in `DESIGN.md`; keep research at high-level design + evidence.

**Done when:** no blocking unknowns remain for a detailed design (open items are either answered, deferred with rationale, or locked as explicit defaults), and `RESEARCH.md` reflects that state.

### 5. Design stage — write `DESIGN.md`

Produce a detailed design sufficient to plan implementation. Required shape: load [`document-templates.md`](document-templates.md) and satisfy the **DESIGN.md** section.

- Treat `DESIGN.md` as the **implementation contract**; when it diverges from `RESEARCH.md`, update DESIGN and note the resolution.
- Include **context** and **sequence** diagrams (and other diagrams only when they clarify the design).
- Cover module layout, public types/APIs, runtime behaviour, config, errors, flag/gating rules, test plan, and implementation phases.

**Done when:** `DESIGN.md` exists and a competent implementer could start an implementation plan without inventing major structure.

### 6. Clarify and update design

If design questions arise, resolve them now.

- Ask 1–2 critical questions at a time when a choice materially forks the design.
- Otherwise lock a sensible default, state it briefly in `DESIGN.md`, and proceed.
- Update `DESIGN.md` (and `RESEARCH.md` only if historical findings need correction).

**Done when:** every material design fork is either decided in `DESIGN.md` or waiting on an explicit user answer just asked.

### 7. Second thought after every DESIGN update

After each material edit to `DESIGN.md`, re-read the whole design for consistency.

- Check flag/bypass paths, ownership boundaries, diagrams vs prose, and phase/file lists.
- Fix contradictions in `DESIGN.md` in the same turn when found.
- Record only issues that change the contract; skip cosmetic churn.

**Done when:** a pass over the full `DESIGN.md` finds no contradictions between sections (or all found issues are fixed).

### 8. Gate: implementation-ready

Repeat steps 6–7 until the design clears the gate.

**Implementation-ready** means all of:

- Module boundaries and key types/APIs are specified.
- End-to-end runtime flow is specified (with sequence diagram).
- Config, errors, and feature-flag/bypass behaviour are specified.
- Test plan and implementation phases are specified.
- No blocking open questions remain (deferred items are explicit non-goals or follow-ups).

**Done when:** the checklist above is satisfied and you state that `DESIGN.md` is implementation-ready (path included). Do not start coding unless the user asks.

## Hard rules

- Primary sources over secondary summaries; cite paths for monorepo claims.
- Prefer borrow-from-existing over invent-from-scratch when a fit exists.
- Keep `RESEARCH.md` as evidence + high-level design; keep `DESIGN.md` as the implementation contract.
- After every material `DESIGN.md` update, run the **second thought** step before declaring progress complete.
- Required diagrams for the final design: **context** (module relationships) and **sequence** (end-to-end interaction). Add others only when they earn their keep.
