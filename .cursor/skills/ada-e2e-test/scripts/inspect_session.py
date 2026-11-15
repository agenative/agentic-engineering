# /// script
# requires-python = ">=3.11"
# dependencies = ["pymongo>=4.10", "pyyaml>=6", "mlflow-skinny>=3.10"]
# ///
"""Collect backend evidence for one ADA e2e case and judge it against the case's expectation.

Reads <out>/result.json from run_ui_case.py, then gathers:
  - the ADA session doc (tenant db, analysis_designer_agent_sessions)
  - its published configs (configtool_simple_analysis_config)
  - the Collider job(s) (collider.jobs, correlation_id = session id)
  - MLflow traces tagged ada_session_id = session id (all experiments)
Writes <out>/evidence.json and prints PASS / FAIL with reasons. Exit 0 on PASS, 1 on FAIL.

Usage: uv run inspect_session.py --case <id> --out <run_dir>/<id> [--session-id <id>]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from _common import DEFAULT_CASES, EVIDENCE_FILE, MONGO_URI, RESULT_FILE, load_case, read_json, write_json
from bson import ObjectId
from pymongo import MongoClient

SECRET_KEYS = {"jwt", "token", "secret", "secrets", "password", "authorization", "auth_token"}


def scrub(value: Any) -> Any:
    """Drop secret-looking keys before anything is written or printed."""
    if isinstance(value, dict):
        return {k: ("<redacted>" if k.lower() in SECRET_KEYS else scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def mongo_evidence(session_id: str, tenant: str) -> dict[str, Any]:
    """Session doc, published configs, and Collider jobs for one ADA session."""
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    try:
        tenant_doc = client["tenants"]["tenants"].find_one({"tenant_id": tenant}, {"db_name": 1})
        db = client[(tenant_doc or {}).get("db_name") or tenant]
        session = db["analysis_designer_agent_sessions"].find_one({"_id": ObjectId(session_id)})
        configs: list[dict[str, Any]] = []
        if session:
            ids = [p.get("published_config_id") for p in session.get("published_configs") or [] if p.get("published_config_id")]
            if ids:
                configs = list(db["configtool_simple_analysis_config"].find({"_id": {"$in": ids}}))
        jobs = list(client["collider"]["jobs"].find({"correlation_id": session_id}))
        return {"session": session, "published_configs": configs, "collider_jobs": jobs}
    finally:
        client.close()


def mlflow_evidence(session_id: str, tracking_uri: str) -> dict[str, Any]:
    """Traces tagged with the session id, with their error spans. Never raises."""
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    try:
        import mlflow
        from mlflow.tracking import MlflowClient

        mlflow.set_tracking_uri(tracking_uri)
        experiments = MlflowClient().search_experiments()
        ids = [e.experiment_id for e in experiments]
        names = {e.experiment_id: e.name for e in experiments}
        traces = mlflow.search_traces(
            locations=ids,
            filter_string=f"tag.ada_session_id = '{session_id}'",
            return_type="list",
        )
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}", "traces": []}

    out: list[dict[str, Any]] = []
    for trace in traces:
        info = trace.info
        spans = trace.data.spans if trace.data else []
        errors = []
        for span in spans:
            status = getattr(span, "status", None)
            code = str(getattr(status, "status_code", "")).upper()
            if "ERROR" in code:
                errors.append({"name": span.name, "description": getattr(status, "description", "")})
        experiment_id = getattr(info, "experiment_id", None)
        out.append(
            {
                "trace_id": info.trace_id,
                "state": str(getattr(info, "state", "")),
                "experiment_id": experiment_id,
                "experiment": names.get(experiment_id),
                "url": f"{tracking_uri}/#/experiments/{experiment_id}/traces?selectedEvaluationId={info.trace_id}",
                "span_names": sorted({s.name for s in spans}),
                "error_spans": errors,
            }
        )
    return {"available": True, "traces": out}


def judge(expect: dict[str, Any], result: dict[str, Any], evidence: dict[str, Any]) -> tuple[bool, list[str]]:
    """Apply the case's expectation. Returns (passed, reasons)."""
    outcome = expect.get("outcome")
    ui_state = result.get("ui_state")
    session = evidence.get("session") or {}
    db_status = session.get("status")
    reasons: list[str] = []
    haystack = json.dumps(scrub(evidence), default=str) + json.dumps(result, default=str)

    if outcome == "ui_error":
        wanted = expect.get("error_contains", "")
        if ui_state != "UI_ERROR":
            reasons.append(f"expected a UI file-picker error, got ui_state={ui_state}")
        elif wanted and wanted not in (result.get("ui_error") or ""):
            reasons.append(f"UI error {result.get('ui_error')!r} does not contain {wanted!r}")
        if result.get("session_id"):
            reasons.append(f"a session was started ({result['session_id']}) though the UI should have blocked it")
        return not reasons, reasons

    if not result.get("session_id"):
        reasons.append(f"no session was started (ui_state={ui_state}, ui_error={result.get('ui_error')!r})")
        return False, reasons
    if not session:
        reasons.append("session not found in Mongo analysis_designer_agent_sessions")

    if outcome == "completed":
        if ui_state != "COMPLETED":
            reasons.append(f"UI status is {ui_state}, expected COMPLETED")
        if db_status != "COMPLETED":
            reasons.append(f"Mongo session status is {db_status}, expected COMPLETED")
        if not session.get("published_configs"):
            reasons.append("session has no published_configs")
        configs_text = json.dumps(evidence.get("published_configs") or [], default=str)
        for family in expect.get("control_points") or []:
            if family not in configs_text:
                reasons.append(f"control point family {family!r} not found in published configs")
        traces = evidence.get("mlflow") or {}
        for trace in traces.get("traces") or []:
            for span in trace["error_spans"]:
                reasons.append(f"MLflow error span {span['name']}: {' '.join(span['description'].split())[:500]}")
    elif outcome == "failed":
        if ui_state not in ("FAILED", "LOAD_FAILED") and db_status != "FAILED":
            reasons.append(f"expected a failure, got ui_state={ui_state}, Mongo status={db_status}")
        wanted = expect.get("error_contains")
        if wanted and wanted not in haystack:
            reasons.append(f"error text {wanted!r} not found in UI, Mongo, Collider or MLflow evidence")
    else:
        reasons.append(f"unknown expect.outcome {outcome!r}")
    return not reasons, reasons


def summarize(evidence: dict[str, Any]) -> list[str]:
    """Short human-readable lines about what the backend recorded."""
    lines = []
    session = evidence.get("session")
    if session:
        lines.append(f"session status={session.get('status')} published_configs={len(session.get('published_configs') or [])} "
                     f"engagement_id={session.get('engagement_id')} user_data_table_id={session.get('user_data_table_id')}")
        state = session.get("session_state")
        if state:
            lines.append("session_state: " + json.dumps(scrub(state), default=str)[:600])
    for job in evidence.get("collider_jobs") or []:
        fields = {k: job.get(k) for k in ("workflow", "stage", "completed", "failed", "cancelled", "processing_message") if k in job}
        lines.append(f"collider job {job.get('_id')}: {fields}")
    mlflow_part = evidence.get("mlflow") or {}
    if mlflow_part and not mlflow_part.get("available", False):
        lines.append(f"mlflow unavailable: {mlflow_part.get('error')}")
    for trace in mlflow_part.get("traces") or []:
        lines.append(f"trace {trace['trace_id']} state={trace['state']} errors={len(trace['error_spans'])} {trace['url']}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--session-id", help="override the session id from result.json")
    parser.add_argument("--tenant", default="localtest")
    parser.add_argument("--mlflow-uri", default=os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5001"))
    args = parser.parse_args()

    case = load_case(args.cases, args.case)
    result = read_json(args.out / RESULT_FILE)
    session_id = args.session_id or result.get("session_id")
    if args.session_id:
        result["session_id"] = args.session_id

    evidence: dict[str, Any] = {"case_id": case["id"], "session_id": session_id}
    if session_id:
        evidence.update(mongo_evidence(session_id, args.tenant))
        evidence["mlflow"] = mlflow_evidence(session_id, args.mlflow_uri.rstrip("/"))

    passed, reasons = judge(case.get("expect") or {}, result, evidence)
    evidence["verdict"] = {"passed": passed, "reasons": reasons, "expect": case.get("expect")}
    write_json(args.out / EVIDENCE_FILE, scrub(evidence))

    print(f"{'PASS' if passed else 'FAIL'} {case['id']} (expected {case.get('expect', {}).get('outcome')}, "
          f"ui_state={result.get('ui_state')}, session={session_id})")
    if case.get("expect", {}).get("provisional"):
        print("  note: provisional expectation; confirm against the evidence before trusting it")
    for reason in reasons:
        print(f"  - {reason}")
    for line in summarize(evidence):
        print(f"  {line}")
    print(f"  evidence: {args.out / EVIDENCE_FILE}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
