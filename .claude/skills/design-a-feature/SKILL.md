---
name: design-a-feature
description: >-
  Design a feature in two gated stages: thorough research (RESEARCH.md) with
  seek-review HTML user review before any design work, then detailed design
  (DESIGN.md) until implementation-ready. Use when the user wants to
  design-a-feature, work out a design from initial thoughts, produce RESEARCH.md
  and DESIGN.md, or iterate a design spec before coding.
---

# Design a feature

Turn initial feature thoughts into an **implementation-ready** `DESIGN.md` via
two **gated** stages: **research** (must clear user review) then **design**.
Prefer monorepo primary sources and existing practices over invention.

**Leading words:** *research stage*, *research gate*, *seek-review*, *design stage*, *second thought*, *implementation-ready*.

## Outputs

| Artifact | When | Role |
| --- | --- | --- |
| `RESEARCH.md` | Research stage | Findings, citations, outstanding questions, high-level design |
| `RESEARCH.review.html` | Research gate | Interactive seek-review of `RESEARCH.md` |
| `RESEARCH.review.feedback.<UTC>-<hex>.json` | Research gate | One seek-review submission (unique file; agent reads the path from `FEEDBACK_WRITTEN=`) |
| `DESIGN.md` | Design stage (only after research gate) | Implementation contract; source of truth once written |

Default location: next to the feature module (e.g. `<project>/…/<feature>/RESEARCH.md` and `DESIGN.md`). Match repo convention if one exists; otherwise choose a sensible path and say where.

Do **not** implement production code in this skill unless the user explicitly asks after `DESIGN.md` is implementation-ready.

## Stage gate (mandatory)

Work is split into two stages. **Do not start the design stage or write `DESIGN.md` until the user explicitly accepts `RESEARCH.md`.**

1. Complete research → write/update `RESEARCH.md`.
2. **Seek-review** via browser (background server); wait for a unique `RESEARCH.review.feedback.<UTC>-<hex>.json` / verdict.
3. If not approved: fold feedback into `RESEARCH.md`, re-run seek-review, and gate again.
4. Repeat until the user explicitly accepts `RESEARCH.md` (approve / approve-with-edits after edits are folded).
5. Only then begin the design stage and produce `DESIGN.md`.

Never draft `DESIGN.md` "in parallel," as a preview, or from assumed approval.

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

### 4. Research gate — seek-review (hard stop)

After `RESEARCH.md` is written or updated, run the [`seek-review`](../seek-review/SKILL.md) skill on it. Do not begin design.

1. Follow **seek-review** end-to-end: fix Mermaid for the browser, render `RESEARCH.review.html`, start the review server in a **background terminal**, open the browser, and invite the user to leave chat-bubble comments, answer choices, and click **Submit review**.
2. Briefly summarize in chat what research covered (and what remains open), pointing at `RESEARCH.md`, `RESEARCH.review.html`, and that feedback will land in a **new** unique `RESEARCH.review.feedback.<UTC>-<hex>.json`.
3. **Wait** until the server prints `FEEDBACK_WRITTEN=<unique-path>` (read that file) or the user gives an explicit verdict in chat. Do not assume approval from silence or from "looks good so far." Do not reuse an older feedback file.

**Verdict handling:**

- **Request changes** (or equivalent dissatisfaction): fold pinned comments, decision overrides, and freeform notes into `RESEARCH.md` (more legwork, sharper findings, resolved questions, diagram fixes as needed). Do not leave decisions only in chat. Re-run seek-review on the updated `RESEARCH.md`, then return to this gate.
- **Approve with edits**: fold the submitted feedback into `RESEARCH.md` first; re-run seek-review only if the user wants another pass. Then proceed to step 5.
- **Approve**: proceed to step 5.

Chat-only approval without the review HTML is acceptable only if the user explicitly declines seek-review for this gate; otherwise seek-review is the default review surface.

**Done when:** the user has explicitly accepted `RESEARCH.md` as satisfactory to proceed to design (via seek-review verdict or explicit chat acceptance after any required edits are folded).

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
- **Never write or draft `DESIGN.md` until the user explicitly accepts `RESEARCH.md` at the research gate** (default surface: seek-review `RESEARCH.review.html`).
- After every material `DESIGN.md` update, run the **second thought** step before declaring progress complete.
- Required diagrams for the final design: **context** (module relationships) and **sequence** (end-to-end interaction). Add others only when they earn their keep.
