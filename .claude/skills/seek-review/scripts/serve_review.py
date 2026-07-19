#!/usr/bin/env python3
"""Serve a seek-review HTML page and write each submission to a unique feedback file.

Usage:
  python serve_review.py \
    --html /abs/path/to/Doc.review.html \
    --out  /abs/path/to/Doc.review.feedback.json \
    [--port 8765]

`--out` is a *base* path. Every POST /submit writes a new file:

  Doc.review.feedback.<UTC-YYYYMMDD-HHMMSSZ>.<8hex>.json

never overwriting a previous submission. Prints FEEDBACK_WRITTEN=<path> for the agent.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


def unique_feedback_path(base_out: Path) -> Path:
    """Derive a non-colliding path from a base *.json (or prefix) path."""
    base_out = base_out.expanduser().resolve()
    if base_out.suffix.lower() == ".json":
        stem_path = base_out.with_suffix("")  # strip .json
    else:
        stem_path = base_out
    parent = stem_path.parent
    stem = stem_path.name
    parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    for _ in range(32):
        suffix = secrets.token_hex(4)
        candidate = parent / f"{stem}.{ts}.{suffix}.json"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate unique feedback path under {parent}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", required=True, type=Path, help="Absolute path to *.review.html")
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Base path for feedback JSON (unique timestamped file written per submit)",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="Do not open a browser")
    args = parser.parse_args()

    html_path = args.html.expanduser().resolve()
    out_base = args.out.expanduser().resolve()
    if not html_path.is_file():
        print(f"ERROR: HTML not found: {html_path}", file=sys.stderr)
        return 1

    serve_root = html_path.parent
    html_name = html_path.name
    state = {"last_written": None, "count": 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))
            sys.stdout.flush()

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path in ("/", "/index.html"):
                path = f"/{html_name}"
            if path == "/status":
                body = json.dumps(
                    {
                        "ok": True,
                        "html": str(html_path),
                        "out_base": str(out_base),
                        "last_written": state["last_written"],
                        "submission_count": state["count"],
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self._cors()
                self.end_headers()
                self.wfile.write(body)
                return

            rel = path.lstrip("/")
            target = (serve_root / rel).resolve()
            if not str(target).startswith(str(serve_root)) or not target.is_file():
                self.send_error(404, "Not found")
                return
            data = target.read_bytes()
            ctype = "text/html; charset=utf-8"
            if target.suffix == ".json":
                ctype = "application/json"
            elif target.suffix == ".js":
                ctype = "application/javascript"
            elif target.suffix == ".css":
                ctype = "text/css"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/submit":
                self.send_error(404, "Not found")
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as e:
                self.send_error(400, f"Invalid JSON: {e}")
                return
            if not isinstance(payload, dict):
                self.send_error(400, "JSON body must be an object")
                return

            out_path = unique_feedback_path(out_base)
            payload["feedback_file"] = str(out_path)
            payload.setdefault("feedback_base", str(out_base))
            tmp = out_path.with_suffix(out_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, out_path)
            state["last_written"] = str(out_path)
            state["count"] += 1

            print(f"FEEDBACK_WRITTEN={out_path}", flush=True)
            print(
                f"SEEK_REVIEW_SUBMITTED n={state['count']} source={payload.get('source')} verdict={payload.get('verdict')}",
                flush=True,
            )

            body = json.dumps({"ok": True, "feedback_file": str(out_path)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/{html_name}"
    print(f"SEEK_REVIEW_SERVER url={url}", flush=True)
    print(f"SEEK_REVIEW_OUT_BASE={out_base}", flush=True)
    print(f"SEEK_REVIEW_HTML={html_path}", flush=True)
    print("Waiting for Submit review (POST /submit)… each submit writes a unique file.", flush=True)

    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down seek-review server.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
