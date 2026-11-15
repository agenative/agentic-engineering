# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright>=1.48", "pyyaml>=6"]
# ///
"""Drive one ADA e2e case through the browser.

Logs in with the local test admin (read from .localenv), opens /ui/analysis-designer-agent,
attaches the prepared file, types the case prompt, clicks Send, captures the sessionId from
POST /config_tool_agent/start, and follows the status row until COMPLETED / FAILED / LOAD_FAILED
or the timeout. Screenshots every state change; writes <out>/result.json.

Run make_parquet.py for the case first. Chromium: uv run --with playwright playwright install chromium

Usage: uv run run_ui_case.py --case <id> --out <run_dir>/<id> [--headed] [--timeout-min 20]
"""

from __future__ import annotations

import argparse
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _common import (
    DEFAULT_CASES,
    PREPARED_FILE,
    RESULT_FILE,
    load_case,
    local_credentials,
    read_json,
    repo_root,
    write_json,
)
from playwright.sync_api import Page, Response, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

ADA_PATH = "/ui/analysis-designer-agent"
TERMINAL_STATES = {"COMPLETED", "FAILED", "LOAD_FAILED"}
FILE_PICKER_ERRORS = (
    "Please select a .parquet file.",
    "The selected file is empty. Please choose a non-empty file.",
    "The selected file exceeds the upload limits. Please choose a smaller file.",
    "Something went wrong uploading your file. Please try again.",
)
START_ERROR_TOAST = "Something went wrong sending your message. Please try again."
TRACKED_API = re.compile(r"/(config_tool_agent|chunked_files)(/|$)")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Run:
    """Collects screenshots, events, and network calls for result.json."""

    def __init__(self, page: Page, out: Path) -> None:
        self.page = page
        self.shots = out / "screenshots"
        self.shots.mkdir(parents=True, exist_ok=True)
        self.events: list[dict[str, Any]] = []
        self.network: list[dict[str, Any]] = []
        self.screenshots: list[str] = []
        self.console_errors: list[str] = []
        self._n = 0

    def event(self, name: str, **detail: Any) -> None:
        self.events.append({"at": now(), "event": name, **detail})
        print(f"[{now()}] {name} {detail if detail else ''}", flush=True)

    def shot(self, label: str) -> None:
        self._n += 1
        path = self.shots / f"{self._n:02d}-{re.sub(r'[^a-zA-Z0-9_-]+', '_', label)}.png"
        try:
            self.page.screenshot(path=str(path), full_page=True)
            self.screenshots.append(str(path))
        except Exception as exc:  # screenshot failures must not hide the real outcome
            self.event("screenshot_failed", label=label, error=str(exc))

    def on_response(self, response: Response) -> None:
        if not TRACKED_API.search(response.url):
            return
        entry: dict[str, Any] = {
            "at": now(),
            "method": response.request.method,
            "url": response.url,
            "status": response.status,
        }
        if response.status >= 400 or "/config_tool_agent/" in response.url:
            try:
                entry["body"] = response.text()[:2000]
            except Exception:
                entry["body"] = None
        self.network.append(entry)


def login_if_needed(page: Page, run: Run, base_url: str, username: str, password: str) -> None:
    """Open the ADA page; complete the IdP username/password form when redirected to it."""
    page.goto(base_url + ADA_PATH, wait_until="domcontentloaded")
    page_marker = page.get_by_test_id("analysis-designer-agent-page")
    username_box = page.locator("[name='username']")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if page_marker.is_visible():
            run.event("already_authenticated")
            return
        if username_box.is_visible():
            break
        page.wait_for_timeout(500)
    else:
        run.shot("no_login_form")
        raise RuntimeError(f"neither the ADA page nor the login form appeared; url={page.url}")

    run.event("login", username=username)
    username_box.fill(username)
    page.locator("[name='password']").fill(password)
    page.locator('button:text("Sign in")').click()
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(2000)
    if ADA_PATH not in page.url:
        page.goto(base_url + ADA_PATH, wait_until="domcontentloaded")


def picker_error(page: Page) -> str | None:
    """Return the file picker's inline error text, if one is showing."""
    text = page.get_by_test_id("analysis-designer-agent-file-picker").inner_text()
    for message in FILE_PICKER_ERRORS:
        if message in text:
            return message
    return None


def drive(page: Page, run: Run, upload: Path, prompt: str, timeout_s: float) -> dict[str, Any]:
    """Attach, prompt, send, and follow the session. Returns the outcome fields of result.json."""
    page.get_by_test_id("analysis-designer-agent-page").wait_for(timeout=60_000)
    run.shot("page_loaded")

    picker = page.get_by_test_id("analysis-designer-agent-file-picker")
    picker.locator("input[type=file]").set_input_files(str(upload))
    run.event("file_attached", file=upload.name)

    prompt_box = page.get_by_test_id("analysis-designer-agent-prompt-box")
    prompt_box.locator("textarea").fill(prompt)
    send = prompt_box.get_by_role("button", name="Send", exact=True)

    upload_deadline = time.monotonic() + 300
    while time.monotonic() < upload_deadline:
        error = picker_error(page)
        if error:
            run.shot("file_picker_error")
            run.event("ui_error", message=error)
            return {"ui_state": "UI_ERROR", "ui_error": error, "session_id": None}
        if send.is_enabled():
            break
        page.wait_for_timeout(500)
    else:
        run.shot("upload_timeout")
        return {"ui_state": "UPLOAD_TIMEOUT", "ui_error": None, "session_id": None}

    run.shot("ready_to_send")
    try:
        with page.expect_response(lambda r: "/config_tool_agent/start" in r.url, timeout=120_000) as info:
            send.click()
        start = info.value
    except PlaywrightTimeout:
        run.shot("start_timeout")
        return {"ui_state": "START_TIMEOUT", "ui_error": None, "session_id": None}

    if start.status >= 400:
        page.wait_for_timeout(1500)
        toast = START_ERROR_TOAST if page.get_by_text(START_ERROR_TOAST).count() else None
        run.shot("start_failed")
        run.event("start_failed", status=start.status)
        return {"ui_state": "START_FAILED", "ui_error": toast, "session_id": None, "start_status": start.status}

    body = start.json() or {}
    session_id = body.get("session_id") or body.get("sessionId")
    run.event("session_started", session_id=session_id)

    status_row = page.get_by_test_id("analysis-designer-agent-status-row")
    last_state: str | None = None
    history: list[dict[str, str]] = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        state = status_row.get_attribute("data-state") if status_row.count() else None
        if state != last_state:
            message = status_row.inner_text() if status_row.count() else ""
            history.append({"at": now(), "state": str(state), "message": message})
            run.event("status", state=state)
            run.shot(f"status_{state}")
            last_state = state
        if state in TERMINAL_STATES:
            break
        page.wait_for_timeout(3000)
    else:
        run.shot("status_timeout")
        return {"ui_state": "TIMEOUT", "ui_error": None, "session_id": session_id, "status_history": history}

    return {
        "ui_state": last_state,
        "ui_error": None,
        "session_id": session_id,
        "status_history": history,
        "status_message": history[-1]["message"] if history else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-url", default="https://localtest.mindbridge.ai")
    parser.add_argument("--timeout-min", type=float, default=20)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    case = load_case(args.cases, args.case)
    prepared = read_json(args.out / PREPARED_FILE)
    upload = Path(prepared["upload_path"])
    username, password = local_credentials(repo_root())
    base_url = args.base_url.rstrip("/")

    result: dict[str, Any] = {"case_id": case["id"], "started_at": now(), "base_url": base_url, "upload": str(upload)}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        run = Run(page, args.out)
        page.on("response", run.on_response)
        page.on("console", lambda m: m.type == "error" and run.console_errors.append(m.text[:500]))
        try:
            login_if_needed(page, run, base_url, username, password)
            result.update(drive(page, run, upload, case["prompt"], args.timeout_min * 60))
        except Exception as exc:
            run.shot("runner_error")
            result.update({"ui_state": "RUNNER_ERROR", "runner_error": f"{type(exc).__name__}: {exc}"})
        finally:
            run.shot("final")
            result.update(
                {
                    "finished_at": now(),
                    "final_url": page.url,
                    "events": run.events,
                    "network": run.network,
                    "console_errors": run.console_errors[-50:],
                    "screenshots": run.screenshots,
                }
            )
            write_json(args.out / RESULT_FILE, result)
            browser.close()

    print(f"[done] {case['id']}: ui_state={result.get('ui_state')} session_id={result.get('session_id')}")
    print(f"       {args.out / RESULT_FILE}")
    return 0 if result.get("ui_state") != "RUNNER_ERROR" else 2


if __name__ == "__main__":
    raise SystemExit(main())
