#!/usr/bin/env python3
"""Local Confluence CLI for the Cursor confluence skill.

Credentials come only from the environment (injected by `op run`).
This script never calls `op` itself and never prints the API token.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

_CQL_DATE_FORMAT = "%Y-%m-%d"

_SPACES_PATH = "/wiki/api/v2/spaces"
_PAGE_PATH = "/wiki/api/v2/pages/{page_id}"
_CHILDREN_PATH = "/wiki/api/v2/pages/{page_id}/children"
_FOOTER_COMMENTS_PATH = "/wiki/api/v2/pages/{page_id}/footer-comments"
_INLINE_COMMENTS_PATH = "/wiki/api/v2/pages/{page_id}/inline-comments"
_SEARCH_PATH = "/wiki/rest/api/search"

# Media nodes carry no text value in a terminal. Card and mention nodes are kept
# and flattened to plain links / @names by adf_to_markdown: dropping them silently
# deletes URLs that the surrounding prose refers to.
_DROPPED_ADF_NODE_TYPES = frozenset({"media", "mediaSingle", "mediaGroup"})
_CARD_NODE_TYPES = frozenset({"inlineCard", "blockCard", "embedCard"})

_ENV_HINT = (
    "Missing credentials. Run via:\n"
    "  op run --env-file=~/.config/confluence/confluence.env -- python3 "
    "~/.cursor/skills/confluence/scripts/confluence.py ..."
)


class CliError(Exception):
    """User-facing error; message must never include the token or raw body."""


# ---------------------------------------------------------------------------
# Config / HTTP
# ---------------------------------------------------------------------------


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CliError(_ENV_HINT)
    return value


def _config() -> tuple[str, str, str, list[str]]:
    base = _require_env("CONFLUENCE_BASE_URL").rstrip("/")
    email = _require_env("CONFLUENCE_EMAIL")
    token = _require_env("CONFLUENCE_API_TOKEN")
    spaces = [
        s.strip()
        for s in os.environ.get("CONFLUENCE_SPACES", "").split(",")
        if s.strip()
    ]
    return base, email, token, spaces


def _auth_header(email: str, token: str) -> str:
    raw = f"{email}:{token}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _request(
    method: str,
    url: str,
    *,
    email: str,
    token: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    try:
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": _auth_header(email, token),
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode())
    except urllib.error.HTTPError as exc:
        path = urllib.parse.urlparse(url).path
        if exc.code == 429:
            raise CliError("Confluence rate limit (429); retry shortly") from None
        if exc.code == 404:
            raise CliError(f"Not found (404): {path}") from None
        raise CliError(f"Confluence returned {exc.code} for {method} {path}") from None
    except urllib.error.URLError as exc:
        reason = type(exc.reason).__name__ if exc.reason else "URLError"
        raise CliError(f"Confluence request failed: {reason}") from None
    except ValueError as exc:
        raise CliError(f"Bad CONFLUENCE_BASE_URL: {exc}") from None


# ---------------------------------------------------------------------------
# Body rendering: ADF and storage (XHTML)
# ---------------------------------------------------------------------------


def sanitize_adf(node: Any) -> Any:
    if isinstance(node, dict):
        if node.get("type") in _DROPPED_ADF_NODE_TYPES:
            return None
        cleaned: dict[str, Any] = {}
        for key, value in node.items():
            if key == "content" and isinstance(value, list):
                cleaned[key] = [
                    item
                    for item in (sanitize_adf(v) for v in value)
                    if item is not None
                ]
            else:
                cleaned[key] = sanitize_adf(value)
        return cleaned
    if isinstance(node, list):
        return [item for item in (sanitize_adf(v) for v in node) if item is not None]
    return node


def adf_to_markdown(node: Any) -> str:
    """Render sanitized ADF to compact Markdown."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""

    ntype = node.get("type")
    content = node.get("content") or []

    if ntype == "text":
        text = str(node.get("text") or "")
        for mark in node.get("marks") or []:
            mtype = mark.get("type") if isinstance(mark, dict) else None
            if mtype == "strong":
                text = f"**{text}**"
            elif mtype == "em":
                text = f"*{text}*"
            elif mtype == "code":
                text = f"`{text}`"
            elif mtype == "strike":
                text = f"~~{text}~~"
            elif mtype == "link":
                href = (mark.get("attrs") or {}).get("href", "")
                if href:
                    text = f"[{text}]({href})"
        return text

    if ntype in _CARD_NODE_TYPES:
        attrs = node.get("attrs") or {}
        url = attrs.get("url") or (attrs.get("data") or {}).get("url") or ""
        return f"<{url}>" if url else ""

    if ntype == "mention":
        name = (node.get("attrs") or {}).get("text") or ""
        return name if name.startswith("@") else f"@{name}" if name else ""

    if ntype == "hardBreak":
        return "\n"

    if ntype == "paragraph":
        return "".join(adf_to_markdown(c) for c in content) + "\n\n"

    if ntype == "heading":
        level = int((node.get("attrs") or {}).get("level") or 1)
        level = max(1, min(level, 6))
        return "#" * level + " " + "".join(adf_to_markdown(c) for c in content) + "\n\n"

    if ntype == "bulletList":
        lines = []
        for item in content:
            item_text = "".join(
                adf_to_markdown(c) for c in (item.get("content") or [])
            ).strip()
            for line in item_text.splitlines() or [""]:
                lines.append(f"- {line}")
        return "\n".join(lines) + "\n\n"

    if ntype == "orderedList":
        lines = []
        for i, item in enumerate(content, 1):
            item_text = "".join(
                adf_to_markdown(c) for c in (item.get("content") or [])
            ).strip()
            for j, line in enumerate(item_text.splitlines() or [""]):
                prefix = f"{i}. " if j == 0 else "   "
                lines.append(f"{prefix}{line}")
        return "\n".join(lines) + "\n\n"

    if ntype == "taskList":
        lines = []
        for item in content:
            state = (item.get("attrs") or {}).get("state")
            box = "[x]" if state == "DONE" else "[ ]"
            item_text = "".join(
                adf_to_markdown(c) for c in (item.get("content") or [])
            ).strip()
            lines.append(f"- {box} {item_text}")
        return "\n".join(lines) + "\n\n"

    if ntype == "codeBlock":
        lang = (node.get("attrs") or {}).get("language") or ""
        code = "".join(
            str(c.get("text") or "") if isinstance(c, dict) else "" for c in content
        )
        return f"```{lang}\n{code}\n```\n\n"

    if ntype == "blockquote":
        inner = "".join(adf_to_markdown(c) for c in content).strip()
        quoted = "\n".join(f"> {line}" for line in inner.splitlines() or [""])
        return quoted + "\n\n"

    if ntype == "panel":
        inner = "".join(adf_to_markdown(c) for c in content).strip()
        kind = (node.get("attrs") or {}).get("panelType") or "note"
        quoted = "\n".join(f"> {line}" for line in inner.splitlines() or [""])
        return f"> **[{kind}]**\n{quoted}\n\n"

    if ntype == "rule":
        return "---\n\n"

    if ntype == "table":
        rows = []
        for row in content:
            cells = []
            for cell in row.get("content") or []:
                cell_text = "".join(
                    adf_to_markdown(c) for c in (cell.get("content") or [])
                ).strip()
                cells.append(cell_text.replace("\n", " "))
            rows.append(cells)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        for r in rows:
            while len(r) < width:
                r.append("")
        lines = [
            "| " + " | ".join(rows[0]) + " |",
            "| " + " | ".join("---" for _ in range(width)) + " |",
        ]
        for r in rows[1:]:
            lines.append("| " + " | ".join(r) + " |")
        return "\n".join(lines) + "\n\n"

    if ntype in {
        "doc",
        "listItem",
        "taskItem",
        "tableRow",
        "tableCell",
        "tableHeader",
        "expand",
        "nestedExpand",
    }:
        return "".join(adf_to_markdown(c) for c in content)

    return "".join(adf_to_markdown(c) for c in content)


class _StorageToMarkdown(HTMLParser):
    """Best-effort Confluence storage (XHTML) to Markdown.

    Only used when a page has no atlas_doc_format body. Confluence macros
    (`ac:*` tags) are skipped rather than rendered, since their payloads are
    usually structured data, not prose.
    """

    _SKIP_TAGS = {"script", "style", "ri:attachment", "ri:url", "ri:page"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._list_stack: list[str] = []
        self._ordered_counter: list[int] = []
        self._in_code = False
        self._href: str | None = None
        self._link_text: list[str] = []

    def _emit(self, text: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag in self._SKIP_TAGS or tag.startswith("ac:"):
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "p":
            self._emit("\n\n")
        elif tag == "br":
            self._emit("\n")
        elif tag == "hr":
            self._emit("\n\n---\n\n")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._emit("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in {"strong", "b"}:
            self._emit("**")
        elif tag in {"em", "i"}:
            self._emit("*")
        elif tag == "code":
            self._emit("`")
        elif tag == "pre":
            self._in_code = True
            self._emit("\n\n```\n")
        elif tag == "ul":
            self._list_stack.append("ul")
            self._emit("\n")
        elif tag == "ol":
            self._list_stack.append("ol")
            self._ordered_counter.append(0)
            self._emit("\n")
        elif tag == "li":
            indent = "  " * max(0, len(self._list_stack) - 1)
            if self._list_stack and self._list_stack[-1] == "ol":
                self._ordered_counter[-1] += 1
                self._emit(f"\n{indent}{self._ordered_counter[-1]}. ")
            else:
                self._emit(f"\n{indent}- ")
        elif tag == "a":
            self._href = attr.get("href")
            self._link_text = []
        elif tag == "tr":
            self._emit("\n| ")
        elif tag in {"td", "th"}:
            pass

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS or tag.startswith("ac:"):
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in {"strong", "b"}:
            self._emit("**")
        elif tag in {"em", "i"}:
            self._emit("*")
        elif tag == "code":
            self._emit("`")
        elif tag == "pre":
            self._in_code = False
            self._emit("\n```\n\n")
        elif tag in {"ul", "ol"}:
            if self._list_stack:
                popped = self._list_stack.pop()
                if popped == "ol" and self._ordered_counter:
                    self._ordered_counter.pop()
            self._emit("\n")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p"}:
            self._emit("\n\n")
        elif tag == "a":
            text = "".join(self._link_text).strip()
            if self._href and text:
                self._emit(f"[{text}]({self._href})")
            elif text:
                self._emit(text)
            self._href = None
            self._link_text = []
        elif tag in {"td", "th"}:
            self._emit(" | ")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._href is not None:
            self._link_text.append(data)
            return
        self._emit(data if self._in_code else re.sub(r"[ \t]+", " ", data))

    def result(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def storage_to_markdown(value: str) -> str:
    parser = _StorageToMarkdown()
    try:
        parser.feed(value)
        parser.close()
    except Exception:  # malformed markup should not kill the command
        return re.sub(r"<[^>]+>", "", value).strip()
    return parser.result()


def render_body(body: dict[str, Any] | None) -> str:
    if not isinstance(body, dict):
        return ""
    adf = body.get("atlas_doc_format")
    if isinstance(adf, dict) and adf.get("value"):
        try:
            doc = json.loads(adf["value"])
        except json.JSONDecodeError:
            return ""
        return adf_to_markdown(sanitize_adf(doc)).strip()
    storage = body.get("storage")
    if isinstance(storage, dict) and storage.get("value"):
        return storage_to_markdown(storage["value"])
    return ""


# ---------------------------------------------------------------------------
# Slicing rendered Markdown: outline, sections, grep
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")


def _normalize_heading(value: str) -> str:
    """Collapse a heading or URL anchor to comparable alphanumerics.

    Confluence anchors mangle punctuation ('Part 4 - Setting' becomes
    'Part-4---Setting'), so comparison has to ignore it entirely.
    """
    value = re.sub(r"^id-\d+-", "", value.strip().lstrip("#"))
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def split_sections(md: str) -> list[dict[str, Any]]:
    """Split rendered Markdown into heading-delimited sections.

    The text before the first heading is returned as a level-0 section so no
    content is silently dropped.
    """
    lines = md.splitlines()
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] = {"level": 0, "title": "", "start": 0, "lines": []}
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if not m:
            current["lines"].append(line)
            continue
        if current["lines"] or current["title"]:
            sections.append(current)
        current = {
            "level": len(m.group(1)),
            "title": m.group(2).strip(),
            "start": i,
            "lines": [],
        }
    if current["lines"] or current["title"]:
        sections.append(current)
    for s in sections:
        s["body"] = "\n".join(s["lines"]).strip()
    return sections


def format_outline(md: str) -> str:
    sections = [s for s in split_sections(md) if s["title"]]
    if not sections:
        return "_(no headings; use --grep or --full)_\n"
    lines = ["## Outline", ""]
    for s in sections:
        indent = "  " * max(0, s["level"] - 1)
        size = len(s["body"])
        lines.append(f"{indent}- {s['title']}  ({size} chars)")
    lines.append("")
    lines.append("_Read one with:_ `get <page> --section \"<heading>\"`")
    return "\n".join(lines) + "\n"


def extract_section(md: str, query: str) -> tuple[str, str] | None:
    """Return (title, text) for the heading matching query, plus its subtree.

    Matching is exact-normalized first, then prefix, then substring, so both a
    URL anchor and a human-typed fragment like "Part 4" resolve.
    """
    sections = split_sections(md)
    titled = [(i, s) for i, s in enumerate(sections) if s["title"]]
    if not titled:
        return None
    want = _normalize_heading(query)
    if not want:
        return None

    match = None
    for predicate in (
        lambda h: h == want,
        lambda h: h.startswith(want),
        lambda h: want in h,
    ):
        for i, s in titled:
            if predicate(_normalize_heading(s["title"])):
                match = (i, s)
                break
        if match:
            break
    if not match:
        return None

    index, section = match
    level = section["level"]
    parts = [f"{'#' * level} {section['title']}", "", section["body"]]
    for s in sections[index + 1 :]:
        if s["title"] and s["level"] <= level:
            break
        if s["title"]:
            parts.extend(["", f"{'#' * s['level']} {s['title']}", "", s["body"]])
        else:
            parts.append(s["body"])
    return section["title"], "\n".join(parts).strip()


def grep_markdown(md: str, pattern: str, context: int) -> str:
    try:
        rx = re.compile(pattern, re.I)
    except re.error as exc:
        raise CliError(f"Bad --grep pattern: {exc}") from None

    lines = md.splitlines()
    # Track the nearest preceding heading so each hit says where it lives.
    heading_at: list[str] = []
    current = ""
    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            current = m.group(2).strip()
        heading_at.append(current)

    hits = [i for i, line in enumerate(lines) if rx.search(line)]
    if not hits:
        return f"No lines matching {pattern!r}.\n"

    ranges: list[list[int]] = []
    for i in hits:
        lo, hi = max(0, i - context), min(len(lines) - 1, i + context)
        if ranges and lo <= ranges[-1][1] + 1:
            ranges[-1][1] = max(ranges[-1][1], hi)
        else:
            ranges.append([lo, hi])

    out = [f"{len(hits)} matching line(s) in {len(ranges)} block(s):", ""]
    for lo, hi in ranges:
        where = heading_at[lo]
        out.append(f"### {where or '(top of page)'}  [lines {lo + 1}-{hi + 1}]")
        out.append("")
        out.extend(lines[lo : hi + 1])
        out.append("")
    return "\n".join(out) + "\n"


def truncate_body(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    kept = text[:max_chars].rstrip()
    omitted = len(text) - len(kept)
    return (
        f"{kept}\n\n_[truncated: {omitted} of {len(text)} chars omitted. "
        "Use --outline to see headings, --section/--grep to target, "
        "or --full for everything.]_"
    )


def score_snippets(
    md: str, terms: list[str], *, limit: int, chars: int
) -> list[tuple[str, str]]:
    """Pick the sections of a page that best match the query terms."""
    patterns = [re.compile(re.escape(t), re.I) for t in terms if t]
    if not patterns:
        return []
    scored = []
    for s in split_sections(md):
        text = s["body"]
        if not text:
            continue
        score = sum(len(p.findall(text)) for p in patterns)
        distinct = sum(1 for p in patterns if p.search(text))
        if score:
            scored.append((distinct, score, s["title"], text))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    out = []
    for _, _, title, text in scored[:limit]:
        if len(text) > chars:
            text = text[:chars].rstrip() + "…"
        out.append((title, text))
    return out


# ---------------------------------------------------------------------------
# CQL
# ---------------------------------------------------------------------------


def _cql_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _quoted_list(values: list[str]) -> str:
    return "(" + ", ".join(_cql_quote(v) for v in values) + ")"


def _validate_date(value: str, *, field_name: str) -> str:
    try:
        datetime.strptime(value, _CQL_DATE_FORMAT)
    except ValueError as exc:
        raise CliError(f"{field_name} must be YYYY-MM-DD, got {value!r}") from exc
    return value


def build_cql(
    *,
    text: str | None,
    title: str | None,
    space_keys: list[str] | None,
    label: list[str] | None,
    content_type: str,
    updated_after: str | None,
    updated_before: str | None,
    default_spaces: list[str],
    sort: str = "relevance",
) -> str:
    clauses: list[str] = [f"type = {_cql_quote(content_type)}"]

    keys = space_keys if space_keys else default_spaces
    if keys:
        clauses.append(f"space in {_quoted_list(keys)}")
    if text:
        # `siteSearch` is the ranked operator the Confluence UI uses; plain
        # `text` is an unranked match whose default order is close to random.
        field = "text" if sort == "recent" else "siteSearch"
        clauses.append(f"{field} ~ {_cql_quote(text)}")
    if title:
        clauses.append(f"title ~ {_cql_quote(title)}")
    if label:
        clauses.append(f"label in {_quoted_list(label)}")
    if updated_after:
        clauses.append(
            f"lastmodified >= {_cql_quote(_validate_date(updated_after, field_name='updated_after'))}"
        )
    if updated_before:
        clauses.append(
            f"lastmodified <= {_cql_quote(_validate_date(updated_before, field_name='updated_before'))}"
        )

    if len(clauses) == 1 and not keys:
        raise CliError(
            "search requires at least one filter (--text/--title/--space/--label/--updated-after) "
            "or CONFLUENCE_SPACES"
        )

    cql = " AND ".join(clauses)
    # ORDER BY would discard siteSearch's ranking, so it only applies to the
    # recency mode.
    if sort == "recent":
        cql += " ORDER BY lastmodified DESC"
    return cql


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

_PAGE_ID_RE = re.compile(r"^\d+$")


def parse_anchor(value: str) -> str:
    """Return the '#Heading-Anchor' fragment of a Confluence URL, if present."""
    _, _, fragment = value.strip().partition("#")
    return urllib.parse.unquote(fragment).strip()


def parse_page_id(value: str) -> str:
    """Accept a bare page ID or a Confluence page URL."""
    value = value.strip().split("#", 1)[0]
    if _PAGE_ID_RE.match(value):
        return value
    m = re.search(r"/pages/(\d+)", value)
    if m:
        return m.group(1)
    m = re.search(r"[?&]pageId=(\d+)", value)
    if m:
        return m.group(1)
    raise CliError(f"Could not extract a page ID from {value!r}")


def get_page(
    base: str, email: str, token: str, page_id: str, *, body_format: str
) -> dict[str, Any]:
    url = f"{base}{_PAGE_PATH.format(page_id=page_id)}?body-format={body_format}"
    return _request("GET", url, email=email, token=token)


def get_page_with_body(
    base: str, email: str, token: str, page_id: str
) -> dict[str, Any]:
    page = get_page(base, email, token, page_id, body_format="atlas_doc_format")
    body = page.get("body") or {}
    adf = body.get("atlas_doc_format") or {}
    if not adf.get("value"):
        fallback = get_page(base, email, token, page_id, body_format="storage")
        page["body"] = fallback.get("body") or {}
    return page


def list_spaces(
    base: str, email: str, token: str, default_spaces: list[str]
) -> list[dict[str, str]]:
    spaces: list[dict[str, str]] = []
    allow = {s.upper() for s in default_spaces} if default_spaces else None
    url = f"{base}{_SPACES_PATH}?limit=100"
    while url:
        page = _request("GET", url, email=email, token=token)
        for item in page.get("results", []):
            key = item.get("key", "")
            if allow is not None and key.upper() not in allow:
                continue
            spaces.append(
                {
                    "id": str(item.get("id", "")),
                    "key": key,
                    "name": item.get("name", ""),
                    "type": item.get("type", ""),
                }
            )
        next_link = ((page.get("_links") or {}).get("next")) or ""
        url = f"{base}{next_link}" if next_link else ""
    return spaces


_EXCERPT_LIMITS = {"none": 0, "short": 180, "full": 0}


def search(
    base: str,
    email: str,
    token: str,
    cql: str,
    limit: int,
    excerpt: str = "short",
) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "cql": cql,
            "limit": limit,
            "excerpt": "none" if excerpt == "none" else "highlight",
        }
    )
    page = _request("GET", f"{base}{_SEARCH_PATH}?{query}", email=email, token=token)
    cap = _EXCERPT_LIMITS.get(excerpt, 180)
    results = []
    for item in page.get("results", []):
        content = item.get("content") or {}
        title = item.get("title") or content.get("title") or ""
        text = "" if excerpt == "none" else _clean_excerpt(item.get("excerpt") or "")
        if cap and len(text) > cap:
            text = text[:cap].rstrip() + "…"
        results.append(
            {
                "id": content.get("id") or "",
                "type": content.get("type") or item.get("entityType") or "",
                "title": _strip_highlight(title),
                "space": ((item.get("resultGlobalContainer") or {}).get("title")) or "",
                "lastModified": item.get("lastModified") or "",
                "excerpt": text,
                "url": item.get("url") or "",
            }
        )
    return results


def _strip_highlight(value: str) -> str:
    """siteSearch wraps matched terms in markers; titles read better without."""
    return value.replace("@@@hl@@@", "").replace("@@@endhl@@@", "").strip()


def _clean_excerpt(value: str) -> str:
    value = value.replace("@@@hl@@@", "**").replace("@@@endhl@@@", "**")
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip().replace("\n", " ")


def list_children(
    base: str, email: str, token: str, page_id: str, limit: int
) -> list[dict[str, str]]:
    url = f"{base}{_CHILDREN_PATH.format(page_id=page_id)}?limit={limit}"
    page = _request("GET", url, email=email, token=token)
    return [
        {
            "id": str(c.get("id", "")),
            "title": c.get("title", ""),
            "status": c.get("status", ""),
        }
        for c in page.get("results", [])
    ]


def list_comments(
    base: str, email: str, token: str, page_id: str, limit: int
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"footer": [], "inline": []}
    for kind, path in (
        ("footer", _FOOTER_COMMENTS_PATH),
        ("inline", _INLINE_COMMENTS_PATH),
    ):
        url = (
            f"{base}{path.format(page_id=page_id)}"
            f"?body-format=atlas_doc_format&limit={limit}"
        )
        try:
            page = _request("GET", url, email=email, token=token)
        except CliError:
            continue
        for c in page.get("results", []):
            out[kind].append(
                {
                    "id": str(c.get("id", "")),
                    "version": (c.get("version") or {}).get("number"),
                    "createdAt": (c.get("version") or {}).get("createdAt", ""),
                    "body": render_body(c.get("body")),
                }
            )
    return out


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _page_url(base: str, page: dict[str, Any]) -> str:
    webui = (page.get("_links") or {}).get("webui") or ""
    return f"{base}/wiki{webui}" if webui else ""


def _space_key_from_links(page: dict[str, Any]) -> str:
    webui = (page.get("_links") or {}).get("webui") or ""
    m = re.search(r"/spaces/([^/]+)/", webui)
    return m.group(1) if m else str(page.get("spaceId") or "?")


def format_page_md(
    base: str, page: dict[str, Any], body: str, *, note: str = ""
) -> str:
    version = page.get("version") or {}
    lines = [
        f"# {page.get('title') or '(untitled)'}",
        "",
        f"- **ID:** {page.get('id')}",
        f"- **Space:** {_space_key_from_links(page)}",
        f"- **Version:** {version.get('number') or '-'} ({version.get('createdAt') or '-'})",
    ]
    url = _page_url(base, page)
    if url:
        lines.append(f"- **URL:** {url}")
    if note:
        lines.extend(["", note])
    lines.append("")
    if body:
        lines.extend([body, ""])
    else:
        lines.extend(["_(no renderable body)_", ""])
    return "\n".join(lines)


def format_search_md(results: list[dict[str, Any]]) -> str:
    if not results:
        return "No results found.\n"
    lines = [f"Found {len(results)} result(s):", ""]
    for r in results:
        head = f"- **{r['title']}** ({r['type']} {r['id']})"
        if r["space"]:
            head += f" — {r['space']}"
        if r["lastModified"]:
            head += f" — {r['lastModified']}"
        lines.append(head)
        if r["excerpt"]:
            lines.append(f"  - {r['excerpt']}")
    lines.append("")
    return "\n".join(lines)


def format_spaces_md(spaces: list[dict[str, str]]) -> str:
    if not spaces:
        return "No spaces visible (or CONFLUENCE_SPACES filter excluded all).\n"
    lines = [f"{len(spaces)} space(s):", ""]
    for s in spaces:
        lines.append(f"- **{s['key']}** ({s['id']}) {s['name']} [{s['type']}]")
    lines.append("")
    return "\n".join(lines)


def format_children_md(children: list[dict[str, str]]) -> str:
    if not children:
        return "No child pages.\n"
    lines = [f"{len(children)} child page(s):", ""]
    for c in children:
        lines.append(f"- **{c['title']}** ({c['id']}) [{c['status']}]")
    lines.append("")
    return "\n".join(lines)


def format_comments_md(comments: dict[str, list[dict[str, Any]]]) -> str:
    total = len(comments["footer"]) + len(comments["inline"])
    if total == 0:
        return "## Comments\n\n_(none)_\n"
    lines = ["## Comments", ""]
    for kind in ("footer", "inline"):
        for c in comments[kind]:
            lines.append(f"### {kind} comment {c['id']} — {c['createdAt']}")
            lines.append("")
            lines.append(c["body"] or "_(empty)_")
            lines.append("")
    return "\n".join(lines)


def _emit(data: Any, *, as_json: bool, markdown: str) -> None:
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(markdown if markdown.endswith("\n") else markdown + "\n")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_spaces(args: argparse.Namespace) -> None:
    base, email, token, default_spaces = _config()
    spaces = list_spaces(base, email, token, default_spaces)
    _emit({"spaces": spaces}, as_json=args.json, markdown=format_spaces_md(spaces))


def cmd_get(args: argparse.Namespace) -> None:
    base, email, token, _ = _config()
    page_id = parse_page_id(args.page)
    anchor = parse_anchor(args.page)
    page = get_page_with_body(base, email, token, page_id)
    body = render_body(page.get("body"))

    section = args.section or (anchor if not args.full else "")
    mode = "full"
    note = ""

    if args.outline:
        mode = "outline"
        rendered = format_outline(body)
    elif args.grep:
        mode = "grep"
        rendered = grep_markdown(body, args.grep, args.context)
    elif section:
        found = extract_section(body, section)
        if found:
            mode = "section"
            title, rendered = found
            source = "URL anchor" if not args.section else "--section"
            note = (
                f"_Showing only the section matched from {source}: "
                f"**{title}**. {len(body)} chars on the full page; "
                "use --outline for the rest._"
            )
        else:
            rendered = truncate_body(body, args.max_chars)
            note = (
                f"_No heading matched {section!r}; showing the page. "
                "Try --outline to see available headings._"
            )
    else:
        rendered = truncate_body(body, 0 if args.full else args.max_chars)

    payload = {
        "id": page.get("id"),
        "title": page.get("title"),
        "space": _space_key_from_links(page),
        "status": page.get("status"),
        "version": page.get("version"),
        "url": _page_url(base, page),
        "mode": mode,
        "bodyChars": len(body),
        "body": rendered,
    }
    _emit(
        payload,
        as_json=args.json,
        markdown=format_page_md(base, page, rendered, note=note),
    )


def cmd_search(args: argparse.Namespace) -> None:
    base, email, token, default_spaces = _config()
    cql = build_cql(
        text=args.text,
        title=args.title,
        space_keys=args.space,
        label=args.label,
        content_type=args.type,
        updated_after=args.updated_after,
        updated_before=args.updated_before,
        default_spaces=default_spaces,
        sort=args.sort,
    )
    results = search(base, email, token, cql, args.max, excerpt=args.excerpt)
    _emit(
        {"cql": cql, "results": results},
        as_json=args.json,
        markdown=format_search_md(results),
    )


def cmd_find(args: argparse.Namespace) -> None:
    """Search, then pull the best-matching sections from the top hits."""
    base, email, token, default_spaces = _config()
    cql = build_cql(
        text=args.query,
        title=None,
        space_keys=args.space,
        label=args.label,
        content_type="page",
        updated_after=args.updated_after,
        updated_before=args.updated_before,
        default_spaces=default_spaces,
        sort=args.sort,
    )
    hits = search(base, email, token, cql, max(args.pages, args.max), excerpt="none")
    terms = [t for t in re.split(r"\s+", args.query) if len(t) > 2] or [args.query]

    found = []
    for hit in hits[: args.pages]:
        if not hit["id"]:
            continue
        try:
            page = get_page_with_body(base, email, token, hit["id"])
        except CliError:
            continue
        body = render_body(page.get("body"))
        found.append(
            {
                **hit,
                "url": _page_url(base, page) or hit["url"],
                "snippets": [
                    {"heading": h, "text": t}
                    for h, t in score_snippets(
                        body, terms, limit=args.snippets, chars=args.snippet_chars
                    )
                ],
            }
        )

    others = [
        {k: h[k] for k in ("id", "title", "space")} for h in hits[args.pages : args.max]
    ]
    _emit(
        {"cql": cql, "matches": found, "otherHits": others},
        as_json=args.json,
        markdown=format_find_md(found, others),
    )


def format_find_md(found: list[dict[str, Any]], others: list[dict[str, Any]]) -> str:
    if not found:
        return "No results found.\n"
    lines = []
    for hit in found:
        lines.append(f"## {hit['title']}")
        lines.append(f"_page {hit['id']} · {hit['space']} · {hit['url']}_")
        lines.append("")
        if not hit["snippets"]:
            lines.append("_(no section matched the query terms; use `get` to read)_")
            lines.append("")
            continue
        for snip in hit["snippets"]:
            if snip["heading"]:
                lines.append(f"### {snip['heading']}")
            lines.append(snip["text"])
            lines.append("")
    if others:
        lines.append("---")
        lines.append("Other hits (not expanded):")
        for o in others:
            lines.append(f"- {o['title']} ({o['id']}, {o['space']})")
        lines.append("")
    return "\n".join(lines)


def cmd_children(args: argparse.Namespace) -> None:
    base, email, token, _ = _config()
    page_id = parse_page_id(args.page)
    children = list_children(base, email, token, page_id, args.max)
    _emit(
        {"children": children}, as_json=args.json, markdown=format_children_md(children)
    )


def cmd_comments(args: argparse.Namespace) -> None:
    base, email, token, _ = _config()
    page_id = parse_page_id(args.page)
    comments = list_comments(base, email, token, page_id, args.max)
    _emit(comments, as_json=args.json, markdown=format_comments_md(comments))


def _add_json_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--json", action="store_true", help="Print JSON instead of Markdown"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="confluence.py",
        description="Read-only Confluence Cloud helper (credentials via op run env).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_spaces = sub.add_parser("spaces", help="List spaces (respects CONFLUENCE_SPACES)")
    _add_json_flag(p_spaces)
    p_spaces.set_defaults(func=cmd_spaces)

    p_get = sub.add_parser("get", help="Fetch a page, or just part of one")
    p_get.add_argument("page", help="Page ID or Confluence page URL (#anchor honoured)")
    p_get.add_argument("--outline", action="store_true", help="Headings only")
    p_get.add_argument("--section", help="Only the section under this heading")
    p_get.add_argument("--grep", help="Only lines matching this regex")
    p_get.add_argument(
        "-C", "--context", type=int, default=3, help="Context lines for --grep"
    )
    p_get.add_argument("--max-chars", dest="max_chars", type=int, default=8000)
    p_get.add_argument(
        "--full", action="store_true", help="Whole page, ignore anchor and --max-chars"
    )
    _add_json_flag(p_get)
    p_get.set_defaults(func=cmd_get)

    def _add_filters(p: argparse.ArgumentParser) -> None:
        p.add_argument("--space", action="append")
        p.add_argument("--label", action="append")
        p.add_argument("--updated-after", dest="updated_after")
        p.add_argument("--updated-before", dest="updated_before")
        p.add_argument(
            "--sort",
            default="relevance",
            choices=["relevance", "recent"],
            help="Ranking; relevance is Confluence's own scoring",
        )

    p_search = sub.add_parser("search", help="Structured-filter search (no raw CQL)")
    p_search.add_argument("--text")
    p_search.add_argument("--title")
    _add_filters(p_search)
    p_search.add_argument(
        "--type", default="page", choices=["page", "blogpost", "comment", "attachment"]
    )
    p_search.add_argument("--max", type=int, default=10)
    p_search.add_argument(
        "--excerpt", default="short", choices=["short", "full", "none"]
    )
    _add_json_flag(p_search)
    p_search.set_defaults(func=cmd_search)

    p_find = sub.add_parser(
        "find", help="Search and return matching sections in one call"
    )
    p_find.add_argument("query", help="What you are looking for")
    _add_filters(p_find)
    p_find.add_argument(
        "--pages", type=int, default=3, help="How many top hits to open"
    )
    p_find.add_argument(
        "--max", type=int, default=10, help="How many hits to list overall"
    )
    p_find.add_argument("--snippets", type=int, default=2, help="Sections per page")
    p_find.add_argument(
        "--snippet-chars", dest="snippet_chars", type=int, default=700
    )
    _add_json_flag(p_find)
    p_find.set_defaults(func=cmd_find)

    p_children = sub.add_parser("children", help="Child pages of a page")
    p_children.add_argument("page", help="Page ID or Confluence page URL")
    p_children.add_argument("--max", type=int, default=50)
    _add_json_flag(p_children)
    p_children.set_defaults(func=cmd_children)

    p_comments = sub.add_parser("comments", help="Footer and inline comments")
    p_comments.add_argument("page", help="Page ID or Confluence page URL")
    p_comments.add_argument("--max", type=int, default=50)
    _add_json_flag(p_comments)
    p_comments.set_defaults(func=cmd_comments)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except CliError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
