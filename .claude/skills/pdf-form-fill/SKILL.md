---
name: pdf-form-fill
description: >-
  Fills interactive (AcroForm) PDF forms using user-supplied PDFs and answers,
  validates required fields against source material, lists gaps in chat, and
  writes a new PDF named *_filled.pdf. Use when the user provides a PDF form,
  asks to fill a PDF form or application, or mentions AcroForm fields, fillable
  PDFs, or PDF form completion. Local tooling only; scanned or image-only PDFs
  are out of scope for now but follow the extension path in reference.md.
compatibility: >-
  Python 3.10+ with PyMuPDF installed from scripts/requirements.txt (pip).
  Scripts run locally; do not send user PDFs to external APIs. Resolve paths
  relative to the skill directory (the folder containing this SKILL.md).
---

# PDF form fill (interactive)

## Hosts and paths (Claude, Cursor, and others)

This skill follows the **Agent Skills** shape: a directory named **`pdf-form-fill`** containing **`SKILL.md`** with YAML frontmatter (`name` matches the directory name). In this repository the skill lives at **`.claude/skills/pdf-form-fill/`** (project-level Claude Code). Other tools may copy or mount it elsewhere—**always resolve `scripts/` and `examples/` relative to the directory that contains `SKILL.md`**, not hard-coded editor paths.

## Scope and limits

- **In scope:** Interactive PDFs with AcroForm field widgets; **multi-page** forms up to **20 pages** (multi-page is supported end-to-end for static fields).
- **Inputs:** **PDF only** (single or multiple PDFs the user provides). Design stays extensible for other document types later—do not claim support beyond PDF until extended.
- **Out of scope (defer explicitly):** Image-only / scanned forms (no extractable fields), **repeating sections**, **conditionally visible** fields, XFA, digital signatures, certified/locked workflows, and any pipeline that sends document content to **non-local** services.
- When the user hits a deferred case, say what is deferred, why, and what they can do next (e.g. supply an interactive PDF, flatten first, or wait for a future skill revision).

## Invocation

Apply this skill **automatically** whenever the user supplies or asks to work on a **PDF form** in the senses above. If intent is ambiguous, confirm once whether they want form-filling versus merge/split/redaction.

## Operating principles

1. **No fabrication:** Never invent values not supported by user-provided PDFs or explicit user answers. If required data is missing, leave those fields **blank** and track them.
2. **Optional fields:** **Leave optional fields blank** unless the user supplies a value or clearly directs a value. **Always stop and ask** before filling an optional field when meaning, format, or source is uncertain—do not guess.
3. **Required fields:** Cross-check user PDFs and answers; if still missing, maintain an internal list. When the user asks for missing information, give the **full list** in chat (field identifier + human label if known + what is needed).
4. **Gap reporting:** **In chat only**—no separate gap-report file unless the user asks for one.
5. **Privacy:** Prefer **local** libraries and commands only; do not upload forms or source PDFs to external APIs.

## Output file naming

Write the filled PDF as **`<original_stem>_filled.pdf`** in the same directory as the source form unless the user specifies another path.

## User preference: editable vs flattened

After field inventory and before writing the output, **ask once:** should the result **preserve editable AcroForm fields** or be **flattened** (print-like, non-editable fields)? Support **both** paths; default only if the user refuses to choose: **preserve editable fields** (reversible) and note that in chat.

## Workflow

1. **Ingest:** Confirm paths to the **template form PDF** and any **source PDFs**. Reject or split jobs over **20 pages** (count pages; if over limit, stop and explain).
2. **Classify:** Detect interactive fields (AcroForm). If no fields are found, treat as **image-based / flat**—do not OCR in this skill version; state that **image-based support is planned** and stop (or point to `reference.md` extension notes if present).
3. **Inventory:** List fields (name, type, **required** flag if present, page). Run `list_fields.py` and treat `"has_acroform_scripts": true` as a **defer** signal for automation (see Examples). **Defer** repeating section templates, conditional visibility, XFA, signatures, and certification—state plainly what was detected.
4. **Map:** For each required field, decide which source PDF or user message supplies the value. If unknown or ambiguous, **stop and ask**.
5. **Validate:** Before writing, ensure every **required** field either has a supported value or is intentionally left blank due to missing data (tracked for the gap list).
6. **Fill (interactive path):** Use the project script (see below) or equivalent **local** code. Never bypass user preference for flatten vs editable except after the explicit question.
7. **Deliver:** Save `*_filled.pdf`. Summarize in chat: page count, field count filled, optional left blank, and any required still blank.

## Local tooling

From the **skill directory** (the folder containing `SKILL.md`):

```bash
python3 scripts/list_fields.py path/to/form.pdf
python3 scripts/fill_form.py path/to/form.pdf path/to/form_filled.pdf --data path/to/values.json [--flatten]
```

- `values.json`: object mapping **field names** to string values. Omit keys for fields left blank.
- Install deps once: `pip install -r scripts/requirements.txt`

If scripts are missing or fail, you may implement the same operations with **pymupdf** locally in a one-off script; keep behavior aligned with this skill.

## Examples in-repo

- `examples/sample-form.pdf` — reference blank interactive form (regenerate via `scripts/build_samples.py` if missing).
- `examples/sample-form_filled.pdf` — golden filled output matching `examples/values.golden.json`.
- `examples/EXAMPLES.txt` — how to (re)generate the PDFs after installing `scripts/requirements.txt`.

If `list_fields.py` reports `"has_acroform_scripts": true`, **defer** JavaScript-driven or calculated fields: explain that the skill does not execute field scripts; offer manual completion or a simplified PDF.

## Additional resources

- [reference.md](reference.md) — extension path for image-based PDFs and future document types.
