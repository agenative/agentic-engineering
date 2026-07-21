---
name: seek-review
description: >-
  Render a Markdown document as interactive review HTML (index, Mermaid,
  comments, inputs, choices), collect submitted feedback, then fold it back.
  Use when the user wants seek-review, or to turn RESEARCH.md / DESIGN.md /
  other Markdown into a review HTML before revising.
---

# Seek review

Turn Markdown that needs comment into a **review HTML**, open it in a browser, wait for **Submit review**, then fold the **feedback file** into the source.

**Leading words:** *seek-review*, *review HTML*, *chat bubble*, *submit review*, *feedback file*, *loyalty to structure*.

## Outputs

| Artifact | Role |
| --- | --- |
| `<stem>.review.html` | Interactive review beside the source |
| `<stem>.review.feedback.<UTC>-<hex>.json` | One submission (unique; never overwrite prior) |

Place both next to the source. The HTML is a review surface — do not invent a second document structure.

## Steps

### 1. Confirm the document

- Use the path the user named, or the single obvious target from recent conversation.
- If uncertain, **stop and confirm** (offer likely candidates). Do not guess.

**Done when:** one source path is explicit.

### 2. Load the source

Read the Markdown. Inventory headings, Mermaid fences, tables, and questions/decisions. Classify controls with the heuristics table below; every commentable/interactive block needs a short **original quote** for `data-quote`.

**Done when:** index sections, Mermaid blocks, control types, and quotes are known.

### 3. Fix Mermaid for the browser

Apply [mermaid-compat.md](mermaid-compat.md) to the source Markdown for clear syntax bugs (the fresh render in step 4 will pick them up). Do not change diagram meaning.

**Done when:** each diagram has a browser-safe definition.

### 4. Render the review HTML

**Always regenerate** `<stem>.review.html` from the current Markdown on every seek-review run — never reuse an existing review HTML.

After writing it, run `python <skill>/scripts/assert_review_html.py <abs-path-to-stem.review.html>` and fix any failures before serving.

Write `<stem>.review.html` beside the source (unless the user names another path).

Embed config (`source`, `feedbackFileBase`, `submitUrl`) per [html-contract.md](html-contract.md). Submit JS must `fetch(location.origin + "/submit")` when served over http(s). **`serve_review.py` always injects a canonical submit runtime** so truncated agent handlers and port changes cannot break **Submit review**.

**Loyalty to structure:** keep source order, headings, and meaning; enhance with controls — do not reshuffle.

**Chrome:** copy patterns from [`reference/mindbridge-look-and-feel.html`](reference/mindbridge-look-and-feel.html) (diagram-card `header`/`data-dz`, chat-bubble SVG in `.comment-btn`, HTML `<table>` for Markdown tables). Follow [html-contract.md](html-contract.md). Fix Mermaid via [mermaid-compat.md](mermaid-compat.md) before embedding. Persist drafts in `localStorage` keyed by source path.

**Done when:** HTML matches the reference patterns, Mermaid renders cleanly, Submit is form-anchored.

### 5. Open in browser (background) and wait for feedback

```bash
python <skill>/scripts/serve_review.py \
  --html <abs-path-to-stem.review.html> \
  --out  <abs-path-to-stem.review.feedback.json> \
  --port <free-port>
```

- `<skill>` = this skill directory. `--out` is a **base name**; each submit writes `<stem>.review.feedback.<UTC-YYYYMMDD-HHMMSSZ>.<8hex>.json`.
- Do **not** pass `--no-open` unless you will open the URL yourself in the next step.
- Start the server in a **background** shell (`block_until_ms: 0`).
- Immediately await `SEEK_REVIEW_SERVER url=` (then optionally `BROWSER_OPENED=`). Parse the URL from that line.
- **Browser must actually open.** If you see `BROWSER_OPEN_FAILED=` or no `BROWSER_OPENED=` within ~2s after `SEEK_REVIEW_SERVER`, open it from a **foreground** shell (macOS: `open "<url>"`; Linux: `xdg-open "<url>"`). Do not tell the user the review is live until the page has been requested or the OS open command succeeded.
- Tell the user the review URL, then await `FEEDBACK_WRITTEN=<unique-path>`; read **that** file.
- If the server cannot start: open the HTML file directly with the OS opener; still save feedback under a unique timestamped name beside the source.

**Done when:** the new feedback file exists and has been read.

### 6. Fold feedback back

Apply `items` (via `original_quote` / `anchor`) to the source Markdown. Re-run seek-review if another pass is needed. Confirm changes and ask whether to continue.

**Done when:** source reflects accepted feedback (or discards are explicit).

## Control detection heuristics

| Source signal | Control |
| --- | --- |
| Open question / notes / describe / bare `?` | Textarea |
| Resolved default / A vs B vs C | Radio (pre-select stated default) |
| Select all that apply / independent flags | Checkboxes |
| Prose, diagram, table row | Chat bubble only |

Default to **radio** when unsure between radio and checkbox.

## Feedback JSON shape

Self-contained: every `items[]` entry includes `original_quote`. Kinds: `comment` | `decision` | `freeform` | `multiselect`.

```json
{
  "source": "/path/Document.md",
  "review_html": "/path/Document.review.html",
  "feedback_file": "/path/Document.review.feedback.20260719-024812Z.a1b2c3d4.json",
  "feedback_base": "/path/Document.review.feedback.json",
  "exported_at": "ISO-8601",
  "reviewer": "",
  "verdict": "approve | approve_with_edits | request_changes | null",
  "items": [
    {
      "kind": "comment",
      "anchor": "brief",
      "section": "1. Brief",
      "original_quote": "verbatim excerpt…",
      "feedback": "user text"
    }
  ]
}
```

Omit empty freeform. Keep `items` as the primary reading path.

## Additional resources

- Visual SSOT: [reference/mindbridge-look-and-feel.html](reference/mindbridge-look-and-feel.html)
- UI contract: [html-contract.md](html-contract.md)
- Mermaid syntax: [mermaid-compat.md](mermaid-compat.md)
- Review server: [scripts/serve_review.py](scripts/serve_review.py)
- Submit runtime (injected on serve): [scripts/submit_runtime.js](scripts/submit_runtime.js)
- Submit smoke test: [scripts/test_submit_integration.py](scripts/test_submit_integration.py)
- HTML assert: [scripts/assert_review_html.py](scripts/assert_review_html.py)
