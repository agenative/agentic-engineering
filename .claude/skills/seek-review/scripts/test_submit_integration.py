#!/usr/bin/env python3
"""Smoke-test serve_review submit injection (no browser required).

Usage:
  python test_submit_integration.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SERVE = SCRIPTS / "serve_review.py"
RUNTIME = SCRIPTS / "submit_runtime.js"


def main() -> int:
    if not SERVE.is_file() or not RUNTIME.is_file():
        print("ERROR: missing serve_review.py or submit_runtime.js", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="seek-review-smoke-") as tmp:
        tmp_path = Path(tmp)
        html = tmp_path / "Doc.review.html"
        out = tmp_path / "Doc.review.feedback.json"
        # Intentionally broken: wrong port, truncated onclick (no fetch)
        html.write_text(
            """<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<script type="application/json" id="seek-review-config">
{"source":"/tmp/Doc.md","reviewHtml":"/tmp/Doc.review.html","feedbackFileBase":"/tmp/Doc.review.feedback.json","submitUrl":"http://127.0.0.1:1/submit"}
</script>
</head><body>
<button type="button" id="submitBtn">Submit review</button>
<pre id="jsonText"></pre>
<div id="confirmMsg" style="display:none"></div>
<script>
const CFG = {"source":"/tmp/Doc.md","reviewHtml":"/tmp/Doc.review.html","feedbackFileBase":"/tmp/Doc.review.feedback.json","submitUrl":"http://127.0.0.1:1/submit"};
document.getElementById("submitBtn").onclick = function () {
  /* truncated agent handler — must not prevent runtime submit */
};
</script>
</body></html>
""",
            encoding="utf-8",
        )

        proc = subprocess.Popen(
            [
                sys.executable,
                str(SERVE),
                "--html",
                str(html),
                "--out",
                str(out),
                "--port",
                "0",
                "--no-open",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdout is not None
        url = None
        deadline = time.time() + 8
        buf = ""
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line and proc.poll() is not None:
                break
            buf += line
            if line.startswith("SEEK_REVIEW_SERVER url="):
                url = line.split("=", 1)[1].strip()
                break
        if not url:
            proc.kill()
            print("ERROR: server did not start\n" + buf, file=sys.stderr)
            return 1

        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read().decode("utf-8")
            if "SEEK_REVIEW_SUBMIT_RUNTIME" not in body:
                print("ERROR: runtime not injected", file=sys.stderr)
                return 1
            if "http://127.0.0.1:1/submit" in body:
                print("ERROR: stale submitUrl not rewritten", file=sys.stderr)
                return 1

            submit = url.rsplit("/", 1)[0] + "/submit"
            payload = {
                "source": "/tmp/Doc.md",
                "verdict": "approve",
                "items": [],
            }
            req = urllib.request.Request(
                submit,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.load(resp)
            fb = data.get("feedback_file")
            if not fb or not Path(fb).is_file():
                print(f"ERROR: feedback not written: {data}", file=sys.stderr)
                return 1
            print(f"SEEK_REVIEW_SMOKE_OK feedback={fb}")
            return 0
        except urllib.error.URLError as exc:
            print(f"ERROR: request failed: {exc}", file=sys.stderr)
            return 1
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
