"""Shared helpers for the ADA e2e scripts: repo root, case catalog, and run-dir files."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CASES = Path(__file__).resolve().parent.parent / "cases.yaml"
PREPARED_FILE = "prepared.json"
RESULT_FILE = "result.json"
EVIDENCE_FILE = "evidence.json"
MONGO_URI = "mongodb://127.0.0.1:27017/?directConnection=true"


def repo_root() -> Path:
    """Monorepo root of the current working directory."""
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    )
    return Path(out.stdout.strip())


def load_case(cases_path: Path, case_id: str) -> dict[str, Any]:
    """Return one case from a cases.yaml file, or exit with the known ids."""
    data = yaml.safe_load(cases_path.read_text(encoding="utf-8")) or {}
    cases = data.get("cases") or []
    for case in cases:
        if case.get("id") == case_id:
            return case
    known = ", ".join(c.get("id", "?") for c in cases)
    raise SystemExit(f"case {case_id!r} not in {cases_path} (known: {known})")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write pretty JSON, stringifying anything json cannot encode (ObjectId, datetime)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON file written by an earlier step, or exit naming the step to run."""
    if not path.is_file():
        raise SystemExit(f"missing {path}; run the earlier step for this case first")
    return json.loads(path.read_text(encoding="utf-8"))


def local_credentials(root: Path) -> tuple[str, str]:
    """Local test admin username/password from user_list.json, falling back to agent-services.env."""
    user_list = root / ".localenv" / "credentials" / "user_list.json"
    if user_list.is_file():
        admin = json.loads(user_list.read_text(encoding="utf-8")).get("admin") or {}
        if admin.get("username") and admin.get("password"):
            return admin["username"], admin["password"]
    env_file = root / "agent-services" / "agent-services.env"
    values: dict[str, str] = {}
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    if values.get("MB_USERNAME") and values.get("MB_PASSWORD"):
        return values["MB_USERNAME"], values["MB_PASSWORD"]
    raise SystemExit("no local credentials found; run `make local` from agent-services")
