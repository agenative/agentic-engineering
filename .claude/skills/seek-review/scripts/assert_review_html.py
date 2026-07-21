#!/usr/bin/env python3
"""Fail if a seek-review HTML is missing required mindbridge chrome.

Usage:
  python assert_review_html.py /abs/path/Doc.review.html
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def check(html: str) -> list[str]:
    errs: list[str] = []
    if "MindBridge" not in html and "--primary: #0056a2" not in html:
        errs.append("missing MindBridge / primary token chrome")
    if "Fraunces" in html or "#0d6e6e" in html:
        errs.append("forbidden legacy theme markers (Fraunces / teal accent)")
    if "data-act=" in html:
        errs.append("diagram tools use data-act= (must be data-dz= like the reference)")
    if 'data-dz="modal"' not in html and "mermaid-source" in html:
        errs.append('diagram Zoom control missing data-dz="modal"')
    if "mermaid-source" in html and '<div class="meta">' not in html:
        errs.append("diagram-card missing header .meta wrapper for tools")
    btns = re.findall(
        r'<button type="button" class="comment-btn"[^>]*>(.*?)</button>',
        html,
        re.S,
    )
    if not btns:
        errs.append("no .comment-btn buttons found")
    elif any("<svg" not in b for b in btns):
        errs.append("one or more .comment-btn buttons lack chat-bubble <svg>")
    if html.count("</body>") != 1 or html.count("</html>") != 1:
        errs.append("duplicate or missing </body>/</html> close tags")

    # Submit must POST feedback. Agent handlers are often truncated; serve_review.py
    # injects a canonical runtime, but generated HTML should still include fetch().
    if 'id="submitBtn"' in html or ">Submit review<" in html:
        if "fetch(" not in html:
            errs.append(
                "Submit review handler missing fetch() — POST will no-op "
                "(serve_review.py injects a runtime fix, but regenerate HTML with a real submit)"
            )
        if "location.origin" not in html and 'id="seek-review-config"' not in html:
            errs.append("missing seek-review-config and location.origin submit resolution")

    # Pipe tables dumped into <pre> instead of <table>
    for pre in re.findall(r"<pre\b[^>]*>(.*?)</pre>", html, re.S | re.I):
        if re.search(r"^\|.+\|\s*$", pre, re.M) and re.search(r"^\|\s*[-:| ]+\|", pre, re.M):
            errs.append("Markdown pipe table found inside <pre> — must be an HTML <table>")
            break

    # Risky Mermaid in embedded sources (common browser parse failures)
    for src in re.findall(
        r'<script[^>]*class="[^"]*mermaid-source[^"]*"[^>]*>(.*?)</script>',
        html,
        re.S,
    ):
        body = src.strip()
        if body.startswith("sequenceDiagram"):
            if re.search(r"->>?[^:\n]*:[^\n]*[;{}]", body):
                errs.append(
                    "sequenceDiagram message text contains ; { or } — rephrase per mermaid-compat.md"
                )
            if re.search(r"actor\s+User\b", body) or re.search(
                r"participant\s+User\b", body
            ):
                errs.append(
                    "sequenceDiagram uses actor/participant id User — rename per mermaid-compat.md"
                )
        if body.startswith("flowchart") or body.startswith("graph"):
            if re.search(r"-->\s*\w+\s*-->", body):
                errs.append(
                    "flowchart chains multiple --> on one line — split to one edge per line"
                )
    return errs


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: assert_review_html.py /abs/path/Doc.review.html", file=sys.stderr)
        return 2
    path = Path(sys.argv[1]).expanduser().resolve()
    if not path.is_file():
        print(f"ERROR: not found: {path}", file=sys.stderr)
        return 1
    errs = check(path.read_text(encoding="utf-8"))
    if errs:
        print(f"ASSERT_REVIEW_HTML_FAILED path={path}", file=sys.stderr)
        for e in errs:
            print(f" - {e}", file=sys.stderr)
        return 1
    print(f"ASSERT_REVIEW_HTML_OK path={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
