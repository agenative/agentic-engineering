#!/usr/bin/env python3
"""Local Jira CLI for the Cursor jira skill.

Credentials come only from the environment (injected by `op run`).
This script never calls `op` itself and never prints the API token.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

ISSUE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-[0-9]+$")
_JQL_DATE_FORMAT = "%Y-%m-%d"

DEFAULT_ISSUE_FIELDS = [
    "summary",
    "status",
    "issuetype",
    "priority",
    "assignee",
    "reporter",
    "labels",
    "created",
    "updated",
    "description",
    "project",
    "sprint",
]

_STATUS_CATEGORIES = frozenset({"done", "in progress", "to do"})

# Resolved once per process via /rest/api/3/field (instance-specific customfield_*).
_sprint_field_id: str | None = None
_sprint_field_resolved: bool = False

_DROPPED_FIELD_KEYS = frozenset(
    {
        "issuelinks",
        "parent",
        "subtasks",
        "changelog",
        "remotelink",
        "worklog",
        "watches",
        "security",
        "attachment",
    }
)
# Media nodes carry no text value in a terminal. Card and mention nodes are kept
# and flattened to plain links / @names by adf_to_markdown: dropping them silently
# deletes URLs that the surrounding prose refers to.
_DROPPED_ADF_NODE_TYPES = frozenset({"media", "mediaSingle", "mediaGroup"})
_CARD_NODE_TYPES = frozenset({"inlineCard", "blockCard", "embedCard"})
_URL_LEAK_KEYS = frozenset({"self", "avatarUrls", "48x48", "24x24", "16x16", "32x32"})
_PII_KEYS = frozenset({"emailAddress"})

_SEARCH_PATH = "/rest/api/3/search/jql"
_ISSUE_PATH = "/rest/api/3/issue/{issue_key}"
_COMMENTS_PATH = "/rest/api/3/issue/{issue_key}/comment"
_PROJECT_SEARCH_PATH = "/rest/api/3/project/search"

_ENV_HINT = (
    "Missing credentials. Run via:\n"
    "  op run --env-file=~/.config/jira/jira.env -- python3 "
    "~/.cursor/skills/jira/scripts/jira.py ..."
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
    base = _require_env("JIRA_BASE_URL").rstrip("/")
    email = _require_env("JIRA_EMAIL")
    token = _require_env("JIRA_API_TOKEN")
    projects = [
        p.strip()
        for p in os.environ.get("JIRA_PROJECTS", "").split(",")
        if p.strip()
    ]
    return base, email, token, projects


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
) -> Any:
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
        if exc.code == 429:
            raise CliError("Jira rate limit (429); retry shortly") from None
        raise CliError(f"Jira returned {exc.code} for {method} {urllib.parse.urlparse(url).path}") from None
    except urllib.error.URLError as exc:
        raise CliError(f"Jira request failed: {type(exc.reason).__name__ if exc.reason else 'URLError'}") from None
    except ValueError as exc:
        raise CliError(f"Bad JIRA_BASE_URL: {exc}") from None


# ---------------------------------------------------------------------------
# Redaction / ADF
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


def _redact_scalar_map(value: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v for k, v in value.items() if k not in _URL_LEAK_KEYS and k not in _PII_KEYS
    }


def _redact_user(value: Any) -> Any:
    if isinstance(value, dict):
        return _redact_scalar_map(value)
    return value


def redact_fields(fields: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in fields.items():
        if key in _DROPPED_FIELD_KEYS:
            continue
        if key.startswith("customfield_"):
            continue
        if key in {"assignee", "reporter", "creator"}:
            redacted[key] = _redact_user(value)
            continue
        if key == "description" and isinstance(value, dict):
            redacted[key] = sanitize_adf(value)
            continue
        if key == "project" and isinstance(value, dict):
            redacted[key] = _redact_scalar_map(value)
            continue
        if key == "sprint":
            redacted[key] = _normalize_sprints(value)
            continue
        redacted[key] = value
    # Sprint often arrives as a customfield_* array; surface it as "sprint".
    if "sprint" not in redacted:
        extracted = _extract_sprints_from_fields(fields)
        if extracted:
            redacted["sprint"] = extracted
    return redacted


def _looks_like_sprint_list(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    first = value[0]
    if not isinstance(first, dict) or "name" not in first:
        return False
    return any(k in first for k in ("state", "boardId", "startDate", "endDate", "goal"))


def _normalize_sprints(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict) and item.get("name"):
            out.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "state": item.get("state"),
                }
            )
        elif isinstance(item, str) and item.strip():
            out.append({"name": item.strip(), "state": None, "id": None})
    return out


def _extract_sprints_from_fields(fields: dict[str, Any]) -> list[dict[str, Any]]:
    direct = fields.get("sprint")
    if direct is not None:
        return _normalize_sprints(direct)
    for key, value in fields.items():
        if key.startswith("customfield_") and _looks_like_sprint_list(value):
            return _normalize_sprints(value)
    return []


def _sprint_label(fields: dict[str, Any]) -> str:
    sprints = fields.get("sprint")
    if not isinstance(sprints, list) or not sprints:
        return "-"
    names = []
    for s in sprints:
        if isinstance(s, dict) and s.get("name"):
            state = s.get("state")
            names.append(f"{s['name']}" + (f" ({state})" if state else ""))
    return ", ".join(names) if names else "-"


def redact_issue(issue: dict[str, Any]) -> dict[str, Any]:
    redacted = _redact_scalar_map(issue)
    fields = redacted.get("fields")
    if isinstance(fields, dict):
        redacted["fields"] = redact_fields(fields)
    return redacted


def redact_comment(comment: dict[str, Any]) -> dict[str, Any]:
    redacted = _redact_scalar_map(comment)
    for user_key in ("author", "updateAuthor"):
        if user_key in redacted:
            redacted[user_key] = _redact_user(redacted[user_key])
    if isinstance(redacted.get("body"), dict):
        redacted["body"] = sanitize_adf(redacted["body"])
    return redacted


def redact_comments_page(page: dict[str, Any]) -> dict[str, Any]:
    comments = page.get("comments", [])
    return {
        **{k: v for k, v in page.items() if k != "comments"},
        "comments": [redact_comment(c) for c in comments],
    }


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
            item_text = "".join(adf_to_markdown(c) for c in (item.get("content") or [])).strip()
            for line in item_text.splitlines() or [""]:
                lines.append(f"- {line}")
        return "\n".join(lines) + "\n\n"

    if ntype == "orderedList":
        lines = []
        for i, item in enumerate(content, 1):
            item_text = "".join(adf_to_markdown(c) for c in (item.get("content") or [])).strip()
            for j, line in enumerate(item_text.splitlines() or [""]):
                prefix = f"{i}. " if j == 0 else "   "
                lines.append(f"{prefix}{line}")
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

    if ntype == "rule":
        return "---\n\n"

    if ntype == "table":
        rows = []
        for row in content:
            cells = []
            for cell in row.get("content") or []:
                cell_text = "".join(adf_to_markdown(c) for c in (cell.get("content") or [])).strip()
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

    if ntype in {"doc", "listItem", "tableRow", "tableCell", "tableHeader"}:
        return "".join(adf_to_markdown(c) for c in content)

    # Unknown / dropped node types: recurse into content if present
    return "".join(adf_to_markdown(c) for c in content)


def _display_name(user: Any) -> str:
    if not isinstance(user, dict) or not user:
        return "Unassigned"
    return str(user.get("displayName") or user.get("accountId") or "Unknown")


def _status_name(status: Any) -> str:
    if isinstance(status, dict):
        return str(status.get("name") or "?")
    return "?"


def format_issue_md(issue: dict[str, Any]) -> str:
    fields = issue.get("fields") or {}
    key = issue.get("key") or "?"
    summary = fields.get("summary") or "(no summary)"
    project = fields.get("project") or {}
    project_key = project.get("key") if isinstance(project, dict) else "?"
    issuetype = fields.get("issuetype") or {}
    type_name = issuetype.get("name") if isinstance(issuetype, dict) else "?"
    priority = fields.get("priority") or {}
    pri_name = priority.get("name") if isinstance(priority, dict) else "-"
    labels = fields.get("labels") or []
    label_str = ", ".join(labels) if labels else "-"

    desc = fields.get("description")
    if isinstance(desc, dict):
        desc_md = adf_to_markdown(desc).strip()
    elif isinstance(desc, str):
        desc_md = desc.strip()
    else:
        desc_md = ""

    lines = [
        f"# {key}: {summary}",
        "",
        f"- **Project:** {project_key}",
        f"- **Type:** {type_name}",
        f"- **Status:** {_status_name(fields.get('status'))}",
        f"- **Priority:** {pri_name}",
        f"- **Assignee:** {_display_name(fields.get('assignee'))}",
        f"- **Reporter:** {_display_name(fields.get('reporter'))}",
        f"- **Sprint:** {_sprint_label(fields)}",
        f"- **Labels:** {label_str}",
        f"- **Created:** {fields.get('created') or '-'}",
        f"- **Updated:** {fields.get('updated') or '-'}",
        "",
    ]
    if desc_md:
        lines.extend(["## Description", "", desc_md, ""])
    return "\n".join(lines)


def format_comments_md(page: dict[str, Any]) -> str:
    comments = page.get("comments") or []
    if not comments:
        return "## Comments\n\n_(none)_\n"
    lines = ["## Comments", ""]
    for c in comments:
        author = _display_name(c.get("author"))
        created = c.get("created") or ""
        body = c.get("body")
        if isinstance(body, dict):
            body_md = adf_to_markdown(body).strip()
        elif isinstance(body, str):
            body_md = body.strip()
        else:
            body_md = ""
        lines.append(f"### {author} — {created}")
        lines.append("")
        lines.append(body_md or "_(empty)_")
        lines.append("")
    return "\n".join(lines)


def format_search_md(page: dict[str, Any]) -> str:
    issues = page.get("issues") or []
    if not issues:
        return "No issues found.\n"
    lines = [f"Found {len(issues)} issue(s):", ""]
    for issue in issues:
        fields = issue.get("fields") or {}
        key = issue.get("key") or "?"
        summary = fields.get("summary") or "(no summary)"
        status = _status_name(fields.get("status"))
        assignee = _display_name(fields.get("assignee"))
        sprint = _sprint_label(fields)
        line = f"- **{key}** [{status}] {summary} — {assignee}"
        if sprint != "-":
            line += f" — {sprint}"
        lines.append(line)
    if not page.get("isLast", True):
        lines.append("")
        lines.append(
            f"_Showing {len(issues)}; more results available — raise `--max`._"
        )
    lines.append("")
    return "\n".join(lines)


def format_projects_md(projects: list[dict[str, str]]) -> str:
    if not projects:
        return "No projects visible (or JIRA_PROJECTS filter excluded all).\n"
    lines = ["Projects:", ""]
    for p in projects:
        lines.append(f"- **{p['key']}** ({p['id']}): {p['name']}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JQL
# ---------------------------------------------------------------------------


def _quoted_list(values: list[str]) -> str:
    escaped = [v.replace("\\", "\\\\").replace('"', '\\"') for v in values]
    return "(" + ", ".join(f'"{v}"' for v in escaped) + ")"


def _validate_date(value: str, *, field_name: str) -> str:
    try:
        datetime.strptime(value, _JQL_DATE_FORMAT)
    except ValueError as exc:
        raise CliError(f"{field_name} must be YYYY-MM-DD, got {value!r}") from exc
    return value


def _assignee_clause(assignees: list[str]) -> str:
    """Build assignee JQL. `me` maps to unquoted currentUser()."""
    parts: list[str] = []
    for value in assignees:
        if value.strip().lower() == "me":
            parts.append("currentUser()")
        else:
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'"{escaped}"')
    return f"assignee in ({', '.join(parts)})"


def _sprint_clause(sprint: str) -> str:
    """Build sprint JQL. `open` / `closed` map to openSprints()/closedSprints()."""
    key = sprint.strip().lower()
    if key == "open":
        return "sprint in openSprints()"
    if key == "closed":
        return "sprint in closedSprints()"
    escaped = sprint.replace("\\", "\\\\").replace('"', '\\"')
    return f'sprint = "{escaped}"'


def _status_category_clause(categories: list[str]) -> str:
    normalized: list[str] = []
    for raw in categories:
        name = raw.strip()
        if name.lower() not in _STATUS_CATEGORIES:
            raise CliError(
                f"status-category must be one of: Done, 'In Progress', 'To Do' "
                f"(got {raw!r})"
            )
        # Preserve Jira's canonical casing.
        if name.lower() == "done":
            normalized.append("Done")
        elif name.lower() == "in progress":
            normalized.append("In Progress")
        else:
            normalized.append("To Do")
    return f"statusCategory in {_quoted_list(normalized)}"


def build_jql(
    *,
    text: str | None,
    status: list[str] | None,
    status_category: list[str] | None,
    assignee: list[str] | None,
    label: list[str] | None,
    issuetype: list[str] | None,
    sprint: str | None,
    updated_after: str | None,
    updated_before: str | None,
    project_keys: list[str] | None,
    default_projects: list[str],
) -> str:
    clauses: list[str] = []

    keys = project_keys if project_keys else default_projects
    if keys:
        # Prefer keys for personal-token use (no boot-time ID resolution).
        clauses.append(f"project in {_quoted_list([k.upper() for k in keys])}")

    if text:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        clauses.append(f'text ~ "{escaped}"')
    if status:
        clauses.append(f"status in {_quoted_list(status)}")
    if status_category:
        clauses.append(_status_category_clause(status_category))
    if assignee:
        clauses.append(_assignee_clause(assignee))
    if label:
        clauses.append(f"labels in {_quoted_list(label)}")
    if issuetype:
        clauses.append(f"issuetype in {_quoted_list(issuetype)}")
    if sprint:
        clauses.append(_sprint_clause(sprint))
    if updated_after:
        clauses.append(f'updated >= "{_validate_date(updated_after, field_name="updated_after")}"')
    if updated_before:
        clauses.append(f'updated <= "{_validate_date(updated_before, field_name="updated_before")}"')

    if not clauses:
        raise CliError("search requires at least one filter or JIRA_PROJECTS")

    return " AND ".join(clauses) + " ORDER BY updated DESC"


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def resolve_sprint_field_id(base: str, email: str, token: str) -> str | None:
    """Find this site's Sprint custom field id (e.g. customfield_10003)."""
    global _sprint_field_id, _sprint_field_resolved
    if _sprint_field_resolved:
        return _sprint_field_id
    _sprint_field_resolved = True
    try:
        fields = _request("GET", f"{base}/rest/api/3/field", email=email, token=token)
    except CliError:
        return None
    if not isinstance(fields, list):
        return None
    for field in fields:
        if not isinstance(field, dict):
            continue
        schema = field.get("schema") or {}
        custom = str(schema.get("custom") or "")
        name = str(field.get("name") or "")
        fid = field.get("id")
        if not isinstance(fid, str):
            continue
        if "gh-sprint" in custom or name.lower() == "sprint":
            _sprint_field_id = fid
            break
    return _sprint_field_id


def _issue_fields(base: str, email: str, token: str) -> list[str]:
    fields = list(DEFAULT_ISSUE_FIELDS)
    sprint_id = resolve_sprint_field_id(base, email, token)
    if sprint_id and sprint_id not in fields:
        fields.append(sprint_id)
    return fields


def get_issue(base: str, email: str, token: str, issue_key: str) -> dict[str, Any]:
    fields = ",".join(_issue_fields(base, email, token))
    path = _ISSUE_PATH.format(issue_key=issue_key) + f"?fields={fields}"
    return redact_issue(_request("GET", base + path, email=email, token=token))


def get_comments(base: str, email: str, token: str, issue_key: str) -> dict[str, Any]:
    path = _COMMENTS_PATH.format(issue_key=issue_key)
    return redact_comments_page(_request("GET", base + path, email=email, token=token))


def search_issues(
    base: str,
    email: str,
    token: str,
    jql: str,
    max_results: int,
) -> dict[str, Any]:
    body = {
        "jql": jql,
        "fields": _issue_fields(base, email, token),
        "maxResults": max_results,
    }
    page = _request("POST", base + _SEARCH_PATH, email=email, token=token, body=body)
    issues = [redact_issue(i) for i in page.get("issues", [])]
    return {
        "issues": issues,
        "nextPageToken": page.get("nextPageToken"),
        "isLast": page.get("isLast", True),
    }


def list_projects(
    base: str, email: str, token: str, default_projects: list[str]
) -> list[dict[str, str]]:
    projects: list[dict[str, str]] = []
    start_at = 0
    allow = {k.upper() for k in default_projects} if default_projects else None
    while True:
        page = _request(
            "GET",
            f"{base}{_PROJECT_SEARCH_PATH}?startAt={start_at}&maxResults=50",
            email=email,
            token=token,
        )
        for item in page.get("values", []):
            key = item.get("key", "")
            if allow is not None and key.upper() not in allow:
                continue
            projects.append(
                {"id": str(item["id"]), "key": key, "name": item.get("name", "")}
            )
        if page.get("isLast", True):
            break
        start_at += len(page.get("values", []))
    return projects


def _check_issue_key(key: str) -> str:
    if not ISSUE_KEY_RE.match(key):
        raise CliError(f"Invalid issue key: {key!r} (expected e.g. ENG-123)")
    return key


def _emit(data: Any, *, as_json: bool, markdown: str) -> None:
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(markdown if markdown.endswith("\n") else markdown + "\n")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_get(args: argparse.Namespace) -> None:
    base, email, token, _ = _config()
    key = _check_issue_key(args.issue_key)
    issue = get_issue(base, email, token, key)
    _emit(issue, as_json=args.json, markdown=format_issue_md(issue))


def cmd_bundle(args: argparse.Namespace) -> None:
    base, email, token, _ = _config()
    key = _check_issue_key(args.issue_key)
    issue = get_issue(base, email, token, key)
    comments = get_comments(base, email, token, key)
    payload = {"issue": issue, "comments": comments}
    md = format_issue_md(issue) + "\n" + format_comments_md(comments)
    _emit(payload, as_json=args.json, markdown=md)


def cmd_comments(args: argparse.Namespace) -> None:
    base, email, token, _ = _config()
    key = _check_issue_key(args.issue_key)
    # Confirm issue exists (and is readable) before returning comments.
    get_issue(base, email, token, key)
    comments = get_comments(base, email, token, key)
    _emit(comments, as_json=args.json, markdown=format_comments_md(comments))


def cmd_search(args: argparse.Namespace) -> None:
    base, email, token, default_projects = _config()
    jql = build_jql(
        text=args.text,
        status=args.status,
        status_category=args.status_category,
        assignee=args.assignee,
        label=args.label,
        issuetype=args.type,
        sprint=args.sprint,
        updated_after=args.updated_after,
        updated_before=args.updated_before,
        project_keys=args.project,
        default_projects=default_projects,
    )
    page = search_issues(base, email, token, jql, args.max)
    _emit(page, as_json=args.json, markdown=format_search_md(page))


def cmd_projects(args: argparse.Namespace) -> None:
    base, email, token, default_projects = _config()
    projects = list_projects(base, email, token, default_projects)
    _emit(
        {"projects": projects},
        as_json=args.json,
        markdown=format_projects_md(projects),
    )


def _add_json_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--json",
        action="store_true",
        help="Print sanitized JSON instead of Markdown",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jira.py",
        description="Read-only Jira Cloud helper (credentials via op run env).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_get = sub.add_parser("get", help="Fetch a single issue")
    p_get.add_argument("issue_key")
    _add_json_flag(p_get)
    p_get.set_defaults(func=cmd_get)

    p_bundle = sub.add_parser("bundle", help="Issue plus comments")
    p_bundle.add_argument("issue_key")
    _add_json_flag(p_bundle)
    p_bundle.set_defaults(func=cmd_bundle)

    p_comments = sub.add_parser("comments", help="Comments for an issue")
    p_comments.add_argument("issue_key")
    _add_json_flag(p_comments)
    p_comments.set_defaults(func=cmd_comments)

    p_search = sub.add_parser("search", help="Structured-filter search (no raw JQL)")
    p_search.add_argument("--text")
    p_search.add_argument("--status", action="append")
    p_search.add_argument(
        "--status-category",
        action="append",
        dest="status_category",
        help="Done | 'In Progress' | 'To Do'",
    )
    p_search.add_argument(
        "--assignee",
        action="append",
        help='Account/email, or "me" for currentUser()',
    )
    p_search.add_argument("--label", action="append")
    p_search.add_argument("--type", action="append", dest="type")
    p_search.add_argument("--project", action="append")
    p_search.add_argument(
        "--sprint",
        help='Sprint name, or "open" / "closed" for openSprints()/closedSprints()',
    )
    p_search.add_argument("--updated-after", dest="updated_after")
    p_search.add_argument("--updated-before", dest="updated_before")
    p_search.add_argument("--max", type=int, default=25)
    _add_json_flag(p_search)
    p_search.set_defaults(func=cmd_search)

    p_projects = sub.add_parser("projects", help="List projects (respects JIRA_PROJECTS)")
    _add_json_flag(p_projects)
    p_projects.set_defaults(func=cmd_projects)

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
