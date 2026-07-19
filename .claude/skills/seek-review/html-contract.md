# HTML contract — seek-review

Disclosed from [`SKILL.md`](SKILL.md). Visual SSOT: [`reference/mindbridge-look-and-feel.html`](reference/mindbridge-look-and-feel.html).

## Page skeleton

- Sticky **left index**: jump links from source headings only (no meta/loyalty blurbs).
- **Form column** (`max-width` ~920px) holds the document body; **Submit review** docks here (not the viewport edge).
- Optional top bar for crumbs / theme / Comments (N). **No** marketing footer; **no** footer `Source: …` line unless the Markdown itself has a footer.

## Tokens (Light / Dark page theme)

| Role | Light | Dark |
| --- | --- | --- |
| Canvas | `#f7f8f9` | `#0e141b` |
| Surface | `#ffffff` | `#172029` |
| Sidebar | `#e8eef4` | `#121920` |
| Ink | `#1d2327` | `#e8eef4` |
| Muted | `#575760` | `#9aa6b2` |
| Line | `#d8dee6` | `#2a3542` |
| Primary | `#0056a2` | `#2fa1d3` |
| Teal | `#00a56a` | `#3dd68c` |

Typography: **DM Sans**; monospace for paths/code. Light / Dark toggle only (no System button).

## Embedded config

```json
{
  "source": "/abs/path/Document.md",
  "reviewHtml": "/abs/path/Document.review.html",
  "feedbackFileBase": "/abs/path/Document.review.feedback.json",
  "submitUrl": "http://127.0.0.1:8765/submit"
}
```

Server allocates a unique `feedback_file` per submit from `feedbackFileBase`.

## Loyalty to structure

Preserve heading order/nesting, tables (every column/cell, including Priority), lists, and callouts. Mermaid stays in place with zoom tools (below).

## Comments

- Always-visible upright **chat-bubble** icon (upper-right); pad so it never covers prose. No “+ Comment” text label; no rotated map-pin.
- Modal: textarea + **Save**; semi-transparent panel/backdrop. Re-open to edit.
- Top-bar **Comments (N)** opens a drawer of **all** comments (Jump / Edit / Delete).
- Hosts: `data-anchor`, `data-quote`, optional `data-section`.

## Mermaid (UI)

- Syntax: [mermaid-compat.md](mermaid-compat.md).
- **Always light-themed** (white viewport + light `themeVariables`), even on a dark page.
- Preserve source in `<script type="text/plain" class="mermaid-source">`. Never re-read a post-`mermaid.run` node for Zoom — clone from the store into a fresh `<pre class="mermaid">`.
- Viewport tools (inline and Zoom modal): drag pan, **+** / **−**, reset, **Zoom** modal.
- After render, grow viewport to **full diagram height** (cap ~85vh for extremes).
- On failure: show error + preserved source.

## Controls

- Open-ended: large textarea. Single-choice: radios (badge defaults). Multiselect: checkboxes when independent. Gates: verdict radios.

## Left index highlight

On click, set `active` immediately (short lock so scroll-spy does not leave the prior section highlighted).

## Submit review — form-anchored

```html
<div class="form-column">
  …sections…
  <div class="fab-dock"><button>Submit review</button></div>
</div>
```

```css
.form-column { position: relative; max-width: 920px; width: 100%; }
.fab-dock {
  position: sticky;
  bottom: 1.25rem;
  display: flex;
  justify-content: flex-end;
  z-index: 30;
}
```

Sticky while scrolling; right edge of the **form column**; at the bottom of the form when the viewport is taller than the form. On submit: self-contained JSON (`items` + `original_quote`), on-page preview, POST to `submitUrl` (Copy/Download fallback).
