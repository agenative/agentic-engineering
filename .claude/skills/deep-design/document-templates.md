# Document templates — deep-design

Disclosed reference for [`SKILL.md`](SKILL.md). Load when writing or revising `RESEARCH.md` / `DESIGN.md`.

Adapt section titles to the feature; keep the **intent** of each required element.

---

## RESEARCH.md

Purpose: evidence, citations, outstanding questions, **high-level** design — not an implementation contract.

### Required elements

1. **Status / path** — draft vs stable; where this file lives relative to the feature.
2. **Brief** — problem, goals, preferences captured from initial thoughts.
3. **Context diagram** — modules/services and relationships (mermaid `flowchart` or equivalent).
4. **Findings** — dependency behaviour, APIs, constraints; each major claim cites a primary source (repo path or first-party doc).
5. **Analogues** — in-repo (or first-party) samples that already touch the same dependency; what to borrow / avoid.
6. **High-level design** — registration/ownership, runtime shape, key flows in prose; optional early sequence sketch.
7. **Outstanding questions** — unanswered items that block or fork detailed design; mark **Resolved:** when closed.
8. **Decision summary** (optional but useful) — table of tentative choices from research.

### Sequence diagram

Include a **sequence diagram** when the feature has multi-party interaction (poll → handle → respond, request → service → store, etc.). If truly single-step, say so and skip.

### What not to put here

- Full public type tables, phase-by-phase file touch lists, exhaustive error-code catalogs — those belong in `DESIGN.md`.
- Uncited speculation presented as fact.

---

## DESIGN.md

Purpose: **implementation-ready** contract. Prefer this file over `RESEARCH.md` when they diverge.

### Required elements

1. **Status** — ready for implementation planning; link to companion `RESEARCH.md`.
2. **Goals and non-goals** — v1 scope boundaries.
3. **Context diagram** — modules and relationships.
4. **Sequence diagram** — end-to-end interaction from trigger through completion/failure.
5. **Module layout** — packages/files to add or change.
6. **Configuration** — settings/env, defaults, master switches / feature flags.
7. **Public types / APIs** — bindings, registries, request/response contracts as applicable.
8. **Runtime components** — how threads/async/workers/lifecycles collaborate; capacity and failure behaviour.
9. **Error and cancel (or equivalent) semantics** — codes, ordering of side effects.
10. **Gating / bypass matrix** — when the feature is fully off vs partially on.
11. **Test plan** — unit/integration focus areas.
12. **Implementation phases** — ordered slices that can merge independently when possible.
13. **File touch list** — concrete paths.
14. **Decision summary** — locked implementation contract table.
15. **Relationship to RESEARCH.md** — DESIGN is source of truth for v1 implementation.

### Diagrams

- **Context** and **sequence** are mandatory for the final design.
- Use mermaid; keep node IDs free of spaces; quote labels that contain special characters.

### Second-thought checklist

After each material update, verify:

- [ ] Diagrams match prose (actors, order, side effects).
- [ ] Flag/bypass paths leave no stray registration, client construction, or I/O when disabled.
- [ ] Ownership boundaries are consistent (who defines config vs who runs runtime).
- [ ] Phases and file touch list cover the modules named in the layout.
- [ ] Non-goals are not contradicted by phase work.
- [ ] Open questions are either gone or explicitly deferred.
