---
name: research-jira
description: Given a JIRA ticket ID, fetch and deeply research the ticket, linked documents, and related work. Explore the relevant codebase, grill the user on missing requirements and technical decisions, then compile a complete requirement spec covering features and technical preferences. Use when user provides a JIRA ID, says "research this ticket", or wants requirements compiled from a JIRA.
---

# Research JIRA

Given a JIRA ticket ID, perform deep research and compile a complete requirement specification.

## Phase 1 — Fetch & Understand the JIRA

0. Validate that the provided input matches a JIRA ticket ID pattern (e.g. PROJECT-1234). If it does not, respond: "That does not look like a valid JIRA ticket ID. Please provide an ID in the format PROJECT-NUMBER (e.g. MYPROJECT-42)." Do not proceed until a valid-format ID is provided.
1. Fetch the JIRA ticket using the provided ID (use MCP tools, browser, or ask the user to paste content).
2. If the ticket cannot be fetched after attempting all three methods (MCP tools, browser, user paste), stop and respond: "I was unable to retrieve JIRA ticket [ID]. Please paste the ticket content directly so I can proceed." Do not continue to Phase 2 without ticket content.
3. Extract and summarise:
   - Title, description, acceptance criteria
   - Priority, type (story/bug/task/epic), sprint/milestone
   - Reporter, assignee, stakeholders
   - Status, history of comments and status changes
   - Sub-tasks and parent epic/story (if any)

## Phase 2 — Research Linked Documents & Related Work

1. Follow **every** linked document — Confluence pages, design docs, Figma links, Slack threads, PRDs, external specs.
2. For each linked resource, extract the relevant requirements, constraints, and decisions already made.
3. Identify related JIRA tickets (blockers, is-blocked-by, relates-to, duplicates). For each related ticket, read the title, description, and any comments that contain decisions, scope changes, or explicit exclusions. Do not follow their linked documents.
4. Summarise findings from linked resources in a structured list.

## Phase 3 — Codebase Exploration

1. Identify the area(s) of the codebase relevant to this ticket.
2. If in monorepo, identify the specific project folder first. Ask if uncertain.
3. Explore the codebase to understand:
   - Existing patterns and conventions in the affected modules
   - Related recent changes (git log)
   - Existing tests covering the area
   - Interfaces and contracts that will be touched
4. Note existing patterns — these are constraints. If no existing pattern covers what is needed, flag it as a question for Phase 4 rather than inventing a new pattern.
5. For integration, CI/CD, deployment or infrastructure tickets, explore the root project and other subfolders as well. Otherwise, focus inside your project folder.

## Phase 4 — Grill the User

Interview the user on gaps and ambiguities. Ask questions **one at a time**. For each question, provide your recommended answer based on research so far.

Focus on:
- Missing acceptance criteria or edge cases
- Ambiguous behaviour (what happens when X?)
- Technical decisions not yet made (approach A vs B?)
- Scope boundaries (what's explicitly out of scope?)
- Dependencies on other teams or tickets
- Non-functional requirements (performance, security, observability)
- When a pattern doesn't exist for something needed, ask the user for their preference — do NOT invent one

Continue grilling user with questions until no ambiguity remains that would prevent an engineer from implementing the ticket. If the user cannot or will not answer a question after one follow-up, mark it as an open question and proceed. Do not ask more than 15 questions in total. If a question can be answered by exploring the codebase, explore the codebase instead of asking.

## Phase 5 — Compile the Requirement Specification

Produce a structured requirement document with these sections:

### Output Format

```
## Summary
One-paragraph description of what this ticket delivers.

## Context & Background
Key context from JIRA, linked docs, and related work.

## Functional Requirements
- [ ] FR-1: ...
- [ ] FR-2: ...
(Numbered, testable, unambiguous)

## Technical Preferences & Constraints
- Pattern to follow: [reference existing pattern in codebase]
- Architecture decisions: ...
- Libraries/tools to use: ...
- What NOT to do: ...

## Edge Cases & Error Handling
- ...

## Non-Functional Requirements
- Performance: ...
- Security: ...
- Observability: ...

## Out of Scope
- Explicitly excluded items

## Open Questions (if any remain)
- ...

## Acceptance Criteria
- [ ] AC-1: ...
- [ ] AC-2: ...
```

### Rules
- Every functional requirement must be testable.
- Technical preferences must reference existing codebase patterns — never invent new ones. If no pattern exists, it must have been clarified with the user in Phase 4.
- If the user cannot answer a question, mark it as an open question in the output rather than guessing.
- The final spec should be complete enough for an engineer to implement without re-reading the JIRA or asking further questions.
