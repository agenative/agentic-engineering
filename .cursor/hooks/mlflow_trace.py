#!/usr/bin/env python3
"""Export Cursor Agent hook events as OTLP spans to local MLflow.

Modeled after the Langfuse Cursor hooks integration
(https://github.com/naoufalelh/cursor-langfuse): prompts/responses are
CHAT_MODEL generations; tools/shell/MCP/file ops are spans.

Cursor hooks do not expose provider token counts. Token usage on
generations is estimated from text (≈ chars/4) unless the hook payload
includes usage fields. Marked with cursor.tokens_estimated=true.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HOOKS_DIR = Path(__file__).resolve().parent
STATE_DIR = HOOKS_DIR / ".mlflow-state"
LOG_PATH = HOOKS_DIR / "mlflow_trace.log"
EXPERIMENT_CACHE = STATE_DIR / "experiment_id.txt"
RAW_EVENTS_LOG = HOOKS_DIR / "hook_events.jsonl"

MLFLOW_BASE = os.environ.get("CURSOR_MLFLOW_URI", "http://127.0.0.1:5001").rstrip("/")
EXPERIMENT_NAME = os.environ.get("CURSOR_MLFLOW_EXPERIMENT", "cursor-agent")
REDACT = os.environ.get("CURSOR_MLFLOW_REDACT", "").lower() in ("1", "true", "yes")
DEBUG = os.environ.get("CURSOR_MLFLOW_DEBUG", "").lower() in ("1", "true", "yes")
SERVICE_NAME = "cursor-agent"


def _log(msg: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}\n")
    except OSError:
        pass


def _now_ns() -> int:
    return time.time_ns()


def _new_trace_id() -> str:
    return os.urandom(16).hex()


def _new_span_id() -> str:
    return os.urandom(8).hex()


def _ok(payload: dict[str, Any] | None = None) -> None:
    sys.stdout.write(json.dumps(payload if payload is not None else {}) + "\n")
    sys.stdout.flush()


def _http_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    *,
    ok_statuses: set[int] | None = None,
) -> tuple[int | None, dict[str, Any] | None]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=3) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(err_body) if err_body else {}
        except json.JSONDecodeError:
            parsed = {}
        if not (ok_statuses and exc.code in ok_statuses):
            _log(f"HTTP {exc.code} {url}: {err_body[:500]}")
        return exc.code, parsed
    except Exception as exc:  # noqa: BLE001
        _log(f"HTTP error {url}: {exc}")
        return None, None


def _cache_experiment_id(experiment_id: str) -> str:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    EXPERIMENT_CACHE.write_text(experiment_id, encoding="utf-8")
    return experiment_id


def resolve_experiment_id() -> str | None:
    if EXPERIMENT_CACHE.exists():
        cached = EXPERIMENT_CACHE.read_text(encoding="utf-8").strip()
        if cached:
            return cached

    encoded = urllib.parse.quote(EXPERIMENT_NAME, safe="")
    get_url = f"{MLFLOW_BASE}/api/2.0/mlflow/experiments/get-by-name?experiment_name={encoded}"
    status, result = _http_json("GET", get_url, ok_statuses={404})
    if status == 200 and result and isinstance(result.get("experiment"), dict):
        experiment_id = str(result["experiment"].get("experiment_id") or "")
        if experiment_id:
            return _cache_experiment_id(experiment_id)

    create_status, create = _http_json(
        "POST",
        f"{MLFLOW_BASE}/api/2.0/mlflow/experiments/create",
        {"name": EXPERIMENT_NAME},
        ok_statuses={400},
    )
    if create_status == 200 and create and create.get("experiment_id"):
        return _cache_experiment_id(str(create["experiment_id"]))

    status, result = _http_json("GET", get_url, ok_statuses={404})
    if status == 200 and result and isinstance(result.get("experiment"), dict):
        experiment_id = str(result["experiment"].get("experiment_id") or "")
        if experiment_id:
            return _cache_experiment_id(experiment_id)
    return None


def _attr_str(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def _attr_bool(key: str, value: bool) -> dict[str, Any]:
    return {"key": key, "value": {"boolValue": value}}


def _attr_int(key: str, value: int) -> dict[str, Any]:
    return {"key": key, "value": {"intValue": str(int(value))}}


def _attr_double(key: str, value: float) -> dict[str, Any]:
    return {"key": key, "value": {"doubleValue": float(value)}}


def estimate_tokens(text: str) -> int:
    """Rough token estimate (≈4 chars/token). Used when provider usage is absent."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def extract_usage(event: dict[str, Any], *, input_text: str = "", output_text: str = "") -> dict[str, Any]:
    """Pull usage from hook payload if present; otherwise estimate from text."""
    candidates: list[dict[str, Any]] = []
    for key in ("usage", "token_usage", "tokenUsage", "tokens"):
        val = event.get(key)
        if isinstance(val, dict):
            candidates.append(val)
    nested = event.get("metadata")
    if isinstance(nested, dict):
        for key in ("usage", "token_usage", "tokenUsage"):
            val = nested.get(key)
            if isinstance(val, dict):
                candidates.append(val)

    def _pick(d: dict[str, Any], *names: str) -> int | None:
        for n in names:
            if n in d and d[n] is not None:
                try:
                    return int(d[n])
                except (TypeError, ValueError):
                    continue
        return None

    for d in candidates:
        inp = _pick(
            d,
            "input_tokens",
            "input",
            "prompt_tokens",
            "promptTokens",
            "prompt",
        )
        out = _pick(
            d,
            "output_tokens",
            "output",
            "completion_tokens",
            "completionTokens",
            "completion",
        )
        total = _pick(d, "total_tokens", "total", "totalTokens")
        if inp is not None or out is not None:
            inp = inp or 0
            out = out or 0
            return {
                "input_tokens": inp,
                "output_tokens": out,
                "total_tokens": total if total is not None else inp + out,
                "estimated": False,
            }

    # Flat fields on the event
    inp = None
    out = None
    for k, target in (
        ("input_tokens", "in"),
        ("prompt_tokens", "in"),
        ("output_tokens", "out"),
        ("completion_tokens", "out"),
    ):
        if event.get(k) is not None:
            try:
                if target == "in":
                    inp = int(event[k])
                else:
                    out = int(event[k])
            except (TypeError, ValueError):
                pass
    if inp is not None or out is not None:
        inp = inp or 0
        out = out or 0
        return {
            "input_tokens": inp,
            "output_tokens": out,
            "total_tokens": inp + out,
            "estimated": False,
        }

    inp_e = estimate_tokens(input_text)
    out_e = estimate_tokens(output_text)
    return {
        "input_tokens": inp_e,
        "output_tokens": out_e,
        "total_tokens": inp_e + out_e,
        "estimated": True,
    }


def usage_attributes(usage: dict[str, Any]) -> list[dict[str, Any]]:
    """MLflow GenAI / OpenTelemetry GenAI usage attributes."""
    attrs = [
        _attr_int("gen_ai.usage.input_tokens", usage["input_tokens"]),
        _attr_int("gen_ai.usage.output_tokens", usage["output_tokens"]),
        _attr_int("llm.usage.total_tokens", usage["total_tokens"]),
        _attr_str(
            "mlflow.chat.tokenUsage",
            json.dumps(
                {
                    "input_tokens": usage["input_tokens"],
                    "output_tokens": usage["output_tokens"],
                    "total_tokens": usage["total_tokens"],
                }
            ),
        ),
        _attr_bool("cursor.tokens_estimated", bool(usage.get("estimated"))),
    ]
    return attrs


def export_spans(experiment_id: str, spans: list[dict[str, Any]]) -> bool:
    if not spans:
        return True
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        _attr_str("service.name", SERVICE_NAME),
                        _attr_str("deployment.environment", "local"),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "cursor.hooks", "version": "1.1.0"},
                        "spans": spans,
                    }
                ],
            }
        ]
    }
    status, _result = _http_json(
        "POST",
        f"{MLFLOW_BASE}/v1/traces",
        payload,
        headers={"x-mlflow-experiment-id": experiment_id},
    )
    return status is not None and 200 <= status < 300


def _state_path(conversation_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in conversation_id)[:120]
    return STATE_DIR / f"{safe}.json"


def load_state(conversation_id: str) -> dict[str, Any]:
    path = _state_path(conversation_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_state(conversation_id: str, state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _state_path(conversation_id).write_text(json.dumps(state), encoding="utf-8")


def clear_state(conversation_id: str) -> None:
    path = _state_path(conversation_id)
    if path.exists():
        path.unlink()


def _text(value: Any, limit: int = 12000) -> str:
    if value is None:
        return ""
    if REDACT:
        return "[redacted]"
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) > limit:
        return text[:limit] + "…[truncated]"
    return text


def _ensure_session(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    if state.get("trace_id") and state.get("session_span_id"):
        return state
    return {
        "trace_id": _new_trace_id(),
        "session_span_id": _new_span_id(),
        "session_start_ns": _now_ns(),
        "model": event.get("model") or event.get("model_id") or "",
        "generations": {},
        "open_tools": {},
        "open_subagents": {},
        "open_mcp": {},
        "open_shell": {},
        "pending_spans": [],
        "token_totals": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "transcript_path": event.get("transcript_path"),
    }


def _current_parent(state: dict[str, Any], generation_id: str | None) -> str:
    if generation_id and generation_id in state.get("generations", {}):
        return state["generations"][generation_id]["span_id"]
    gens = state.get("generations") or {}
    if gens:
        latest = max(gens.values(), key=lambda g: g.get("start_ns", 0))
        return latest["span_id"]
    return state["session_span_id"]


def _span(
    *,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
    name: str,
    start_ns: int,
    end_ns: int,
    attributes: list[dict[str, Any]],
    status_code: int = 1,
    status_message: str = "",
) -> dict[str, Any]:
    span: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": 1,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": attributes,
        "status": {"code": status_code},
    }
    if parent_span_id:
        span["parentSpanId"] = parent_span_id
    if status_message:
        span["status"]["message"] = status_message
    return span


def _accumulate_tokens(state: dict[str, Any], usage: dict[str, Any]) -> None:
    totals = state.setdefault(
        "token_totals", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    )
    totals["input_tokens"] += int(usage.get("input_tokens") or 0)
    totals["output_tokens"] += int(usage.get("output_tokens") or 0)
    totals["total_tokens"] += int(usage.get("total_tokens") or 0)


def _model_name(event: dict[str, Any], state: dict[str, Any]) -> str:
    return (
        event.get("model")
        or event.get("model_id")
        or state.get("model")
        or "cursor-agent"
    )


def handle(event: dict[str, Any]) -> dict[str, Any] | None:
    if DEBUG:
        try:
            with RAW_EVENTS_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, default=str)[:20000] + "\n")
        except OSError:
            pass

    hook = event.get("hook_event_name") or event.get("hook") or ""
    conversation_id = (
        event.get("conversation_id")
        or event.get("session_id")
        or event.get("composer_id")
        or "unknown"
    )
    generation_id = event.get("generation_id") or event.get("generationId")
    experiment_id = resolve_experiment_id()

    state = load_state(conversation_id)
    spans: list[dict[str, Any]] = []
    now = _now_ns()
    response_payload: dict[str, Any] | None = None

    if hook == "sessionStart":
        state = _ensure_session({}, event)
        save_state(conversation_id, state)
        return {"continue": True}

    state = _ensure_session(state, event)
    if event.get("model") or event.get("model_id"):
        state["model"] = event.get("model") or event.get("model_id")
    if event.get("transcript_path"):
        state["transcript_path"] = event["transcript_path"]

    trace_id = state["trace_id"]
    session_span_id = state["session_span_id"]
    model = _model_name(event, state)

    # --- Langfuse-style: User Prompt as generation ---
    if hook == "beforeSubmitPrompt":
        gen_span_id = _new_span_id()
        gen_key = generation_id or f"gen-{gen_span_id}"
        prompt = _text(event.get("prompt") or event.get("user_message") or "")
        usage = extract_usage(event, input_text=prompt, output_text="")
        # Open generation chain under session; LLM child closed on response
        state.setdefault("generations", {})[gen_key] = {
            "span_id": gen_span_id,
            "start_ns": now,
            "prompt": prompt,
            "prompt_usage": usage,
            "llm_span_id": _new_span_id(),
        }
        # Immediate "User Prompt" generation span (mirrors Langfuse)
        attrs = [
            _attr_str("cursor.hook", hook),
            _attr_str("mlflow.spanType", "CHAT_MODEL"),
            _attr_str("gen_ai.operation.name", "chat"),
            _attr_str("gen_ai.system", "cursor"),
            _attr_str("gen_ai.request.model", model),
            _attr_str(
                "mlflow.spanInputs",
                json.dumps({"messages": [{"role": "user", "content": prompt}]}),
            ),
            _attr_str("cursor.generation_role", "user_prompt"),
        ]
        attrs.extend(usage_attributes(usage))
        spans.append(
            _span(
                trace_id=trace_id,
                span_id=_new_span_id(),
                parent_span_id=session_span_id,
                name="User Prompt",
                start_ns=now,
                end_ns=now + 1_000,
                attributes=attrs,
            )
        )
        _accumulate_tokens(state, usage)
        response_payload = {"continue": True}

    # --- Thinking ---
    elif hook == "afterAgentThought":
        parent = _current_parent(state, generation_id)
        duration_ms = event.get("duration_ms")
        start = now - int(float(duration_ms) * 1_000_000) if duration_ms else now - 1_000_000
        text = _text(event.get("text") or "")
        attrs = [
            _attr_str("cursor.hook", hook),
            _attr_str("mlflow.spanType", "CHAIN"),
            _attr_str("gen_ai.operation.name", "thought"),
        ]
        if text:
            attrs.append(_attr_str("mlflow.spanOutputs", json.dumps({"thought": text})))
        if duration_ms is not None:
            attrs.append(_attr_double("cursor.duration_ms", float(duration_ms)))
        spans.append(
            _span(
                trace_id=trace_id,
                span_id=_new_span_id(),
                parent_span_id=parent,
                name="Agent Thinking",
                start_ns=start,
                end_ns=now,
                attributes=attrs,
            )
        )

    # --- Langfuse-style: Agent Response as generation with tokens ---
    elif hook == "afterAgentResponse":
        gen_key = generation_id
        gen = None
        if gen_key and gen_key in state.get("generations", {}):
            gen = state["generations"][gen_key]
        elif state.get("generations"):
            gen_key, gen = max(
                state["generations"].items(), key=lambda kv: kv[1].get("start_ns", 0)
            )

        response = _text(event.get("text") or event.get("response") or "")
        prompt = (gen or {}).get("prompt") or ""
        usage = extract_usage(event, input_text=prompt, output_text=response)
        start = (gen or {}).get("start_ns", now - 1_000_000)
        llm_span_id = (gen or {}).get("llm_span_id") or _new_span_id()
        parent = session_span_id

        attrs = [
            _attr_str("cursor.hook", hook),
            _attr_str("mlflow.spanType", "CHAT_MODEL"),
            _attr_str("gen_ai.operation.name", "chat"),
            _attr_str("gen_ai.system", "cursor"),
            _attr_str("gen_ai.request.model", model),
            _attr_str("cursor.generation_role", "assistant_response"),
            _attr_int("cursor.response_length", len(response)),
        ]
        if prompt:
            attrs.append(
                _attr_str(
                    "mlflow.spanInputs",
                    json.dumps({"messages": [{"role": "user", "content": prompt}]}),
                )
            )
        if response:
            attrs.append(
                _attr_str(
                    "mlflow.spanOutputs",
                    json.dumps(
                        {"messages": [{"role": "assistant", "content": response}]}
                    ),
                )
            )
        attrs.extend(usage_attributes(usage))
        spans.append(
            _span(
                trace_id=trace_id,
                span_id=llm_span_id,
                parent_span_id=parent,
                name=f"Agent Response ({model})",
                start_ns=start,
                end_ns=now,
                attributes=attrs,
            )
        )
        _accumulate_tokens(state, usage)
        if gen_key:
            state.get("generations", {}).pop(gen_key, None)

    # --- Generic tools ---
    elif hook == "preToolUse":
        tool_name = event.get("tool_name") or event.get("toolName") or event.get("tool") or "tool"
        call_id = (
            event.get("tool_call_id")
            or event.get("toolCallId")
            or event.get("call_id")
            or _new_span_id()
        )
        state.setdefault("open_tools", {})[call_id] = {
            "span_id": _new_span_id(),
            "parent_span_id": _current_parent(state, generation_id),
            "start_ns": now,
            "name": str(tool_name),
        }

    elif hook in ("postToolUse", "postToolUseFailure"):
        call_id = event.get("tool_call_id") or event.get("toolCallId") or event.get("call_id")
        open_tools = state.setdefault("open_tools", {})
        tool = open_tools.pop(call_id, None) if call_id else None
        if tool is None and open_tools:
            call_id, tool = max(open_tools.items(), key=lambda kv: kv[1].get("start_ns", 0))
            open_tools.pop(call_id, None)
        failed = hook == "postToolUseFailure"
        tool_name = (tool or {}).get("name") or event.get("tool_name") or "tool"
        attrs = [
            _attr_str("cursor.hook", hook),
            _attr_str("mlflow.spanType", "TOOL"),
            _attr_str("gen_ai.tool.name", str(tool_name)),
        ]
        if not REDACT and event.get("tool_input") is not None:
            attrs.append(_attr_str("mlflow.spanInputs", _text(event.get("tool_input"), 4000)))
        if not REDACT and event.get("tool_output") is not None:
            attrs.append(_attr_str("mlflow.spanOutputs", _text(event.get("tool_output"), 4000)))
        spans.append(
            _span(
                trace_id=trace_id,
                span_id=(tool or {}).get("span_id") or _new_span_id(),
                parent_span_id=(tool or {}).get("parent_span_id")
                or _current_parent(state, generation_id),
                name=f"tool.{tool_name}",
                start_ns=(tool or {}).get("start_ns", now - 1_000_000),
                end_ns=now,
                attributes=attrs,
                status_code=2 if failed else 1,
                status_message="tool failure" if failed else "",
            )
        )

    # --- Shell (Langfuse coverage) ---
    elif hook == "beforeShellExecution":
        cmd = event.get("command") or ""
        call_id = event.get("tool_call_id") or _new_span_id()
        state.setdefault("open_shell", {})[call_id] = {
            "span_id": _new_span_id(),
            "parent_span_id": _current_parent(state, generation_id),
            "start_ns": now,
            "command": cmd,
        }
        response_payload = {"permission": "allow"}

    elif hook == "afterShellExecution":
        call_id = event.get("tool_call_id")
        open_shell = state.setdefault("open_shell", {})
        sh = open_shell.pop(call_id, None) if call_id else None
        if sh is None and open_shell:
            call_id, sh = max(open_shell.items(), key=lambda kv: kv[1].get("start_ns", 0))
            open_shell.pop(call_id, None)
        cmd = (sh or {}).get("command") or event.get("command") or "command"
        duration = event.get("duration") or event.get("duration_ms")
        start = (sh or {}).get("start_ns", now - 1_000_000)
        if duration is not None and sh is None:
            start = now - int(float(duration) * 1_000_000)
        attrs = [
            _attr_str("cursor.hook", hook),
            _attr_str("mlflow.spanType", "TOOL"),
            _attr_str("gen_ai.tool.name", "Shell"),
            _attr_str("mlflow.spanInputs", _text({"command": cmd}, 4000)),
        ]
        if event.get("output") is not None and not REDACT:
            attrs.append(_attr_str("mlflow.spanOutputs", _text(event.get("output"), 4000)))
        spans.append(
            _span(
                trace_id=trace_id,
                span_id=(sh or {}).get("span_id") or _new_span_id(),
                parent_span_id=(sh or {}).get("parent_span_id")
                or _current_parent(state, generation_id),
                name=f"Shell: {str(cmd)[:50]}",
                start_ns=start,
                end_ns=now,
                attributes=attrs,
            )
        )

    # --- MCP ---
    elif hook == "beforeMCPExecution":
        tool_name = event.get("tool_name") or event.get("toolName") or "mcp"
        call_id = event.get("tool_call_id") or event.get("call_id") or _new_span_id()
        state.setdefault("open_mcp", {})[call_id] = {
            "span_id": _new_span_id(),
            "parent_span_id": _current_parent(state, generation_id),
            "start_ns": now,
            "name": str(tool_name),
            "server": str(event.get("server") or event.get("url") or ""),
        }
        response_payload = {"permission": "allow"}

    elif hook == "afterMCPExecution":
        call_id = event.get("tool_call_id") or event.get("call_id")
        open_mcp = state.setdefault("open_mcp", {})
        mcp = open_mcp.pop(call_id, None) if call_id else None
        if mcp is None and open_mcp:
            call_id, mcp = max(open_mcp.items(), key=lambda kv: kv[1].get("start_ns", 0))
            open_mcp.pop(call_id, None)
        tool_name = (mcp or {}).get("name") or event.get("tool_name") or "mcp"
        attrs = [
            _attr_str("cursor.hook", hook),
            _attr_str("mlflow.spanType", "TOOL"),
            _attr_str("gen_ai.tool.name", str(tool_name)),
            _attr_bool("cursor.mcp", True),
        ]
        result = event.get("result") if "result" in event else event.get("result_json")
        if result is not None and not REDACT:
            attrs.append(_attr_str("mlflow.spanOutputs", _text(result, 4000)))
        spans.append(
            _span(
                trace_id=trace_id,
                span_id=(mcp or {}).get("span_id") or _new_span_id(),
                parent_span_id=(mcp or {}).get("parent_span_id")
                or _current_parent(state, generation_id),
                name=f"MCP: {tool_name}",
                start_ns=(mcp or {}).get("start_ns", now - 1_000_000),
                end_ns=now,
                attributes=attrs,
            )
        )

    # --- File ops (Langfuse coverage) ---
    elif hook in ("beforeReadFile", "beforeTabFileRead"):
        path = event.get("file_path") or event.get("path") or "file"
        spans.append(
            _span(
                trace_id=trace_id,
                span_id=_new_span_id(),
                parent_span_id=_current_parent(state, generation_id),
                name=f"Read: {Path(str(path)).name}",
                start_ns=now - 1_000,
                end_ns=now,
                attributes=[
                    _attr_str("cursor.hook", hook),
                    _attr_str("mlflow.spanType", "TOOL"),
                    _attr_str("gen_ai.tool.name", "Read"),
                    _attr_str("mlflow.spanInputs", _text({"file_path": path}, 2000)),
                ],
            )
        )
        response_payload = {"permission": "allow"}

    elif hook in ("afterFileEdit", "afterTabFileEdit"):
        path = event.get("file_path") or event.get("path") or "file"
        spans.append(
            _span(
                trace_id=trace_id,
                span_id=_new_span_id(),
                parent_span_id=_current_parent(state, generation_id),
                name=f"Edit: {Path(str(path)).name}",
                start_ns=now - 1_000,
                end_ns=now,
                attributes=[
                    _attr_str("cursor.hook", hook),
                    _attr_str("mlflow.spanType", "TOOL"),
                    _attr_str("gen_ai.tool.name", "Write"),
                    _attr_str("mlflow.spanInputs", _text({"file_path": path}, 2000)),
                ],
            )
        )

    # --- Context compaction (real context token counts from Cursor) ---
    elif hook == "preCompact":
        ctx_tokens = event.get("context_tokens")
        ctx_window = event.get("context_window_size")
        ctx_pct = event.get("context_usage_percent")
        attrs = [
            _attr_str("cursor.hook", hook),
            _attr_str("mlflow.spanType", "CHAIN"),
            _attr_str("gen_ai.operation.name", "compact"),
        ]
        if ctx_tokens is not None:
            attrs.append(_attr_int("cursor.context_tokens", int(ctx_tokens)))
            attrs.append(_attr_int("gen_ai.usage.input_tokens", int(ctx_tokens)))
        if ctx_window is not None:
            attrs.append(_attr_int("cursor.context_window_size", int(ctx_window)))
        if ctx_pct is not None:
            attrs.append(_attr_double("cursor.context_usage_percent", float(ctx_pct)))
        spans.append(
            _span(
                trace_id=trace_id,
                span_id=_new_span_id(),
                parent_span_id=session_span_id,
                name="Context Compact",
                start_ns=now - 1_000,
                end_ns=now,
                attributes=attrs,
            )
        )

    elif hook == "subagentStart":
        sub_type = event.get("subagent_type") or event.get("subagentType") or "subagent"
        sub_id = event.get("subagent_id") or event.get("agent_id") or _new_span_id()
        state.setdefault("open_subagents", {})[sub_id] = {
            "span_id": _new_span_id(),
            "parent_span_id": _current_parent(state, generation_id),
            "start_ns": now,
            "name": str(sub_type),
        }

    elif hook == "subagentStop":
        sub_id = event.get("subagent_id") or event.get("agent_id")
        open_subs = state.setdefault("open_subagents", {})
        sub = open_subs.pop(sub_id, None) if sub_id else None
        if sub is None and open_subs:
            sub_id, sub = max(open_subs.items(), key=lambda kv: kv[1].get("start_ns", 0))
            open_subs.pop(sub_id, None)
        spans.append(
            _span(
                trace_id=trace_id,
                span_id=(sub or {}).get("span_id") or _new_span_id(),
                parent_span_id=(sub or {}).get("parent_span_id") or session_span_id,
                name=f"subagent.{(sub or {}).get('name') or 'subagent'}",
                start_ns=(sub or {}).get("start_ns", now - 1_000_000),
                end_ns=now,
                attributes=[
                    _attr_str("cursor.hook", hook),
                    _attr_str("mlflow.spanType", "AGENT"),
                ],
            )
        )

    elif hook in ("stop", "sessionEnd"):
        for gen_key, gen in list(state.get("generations", {}).items()):
            # Unfinished generation — still emit LLM span with prompt-only usage
            prompt = gen.get("prompt") or ""
            usage = gen.get("prompt_usage") or extract_usage({}, input_text=prompt)
            attrs = [
                _attr_str("cursor.hook", hook),
                _attr_str("mlflow.spanType", "CHAT_MODEL"),
                _attr_str("gen_ai.operation.name", "chat"),
                _attr_str("gen_ai.request.model", model),
                _attr_str(
                    "mlflow.spanInputs",
                    json.dumps({"messages": [{"role": "user", "content": prompt}]}),
                ),
            ]
            attrs.extend(usage_attributes(usage))
            spans.append(
                _span(
                    trace_id=trace_id,
                    span_id=gen.get("llm_span_id") or gen["span_id"],
                    parent_span_id=session_span_id,
                    name=f"Agent Response ({model})",
                    start_ns=gen["start_ns"],
                    end_ns=now,
                    attributes=attrs,
                )
            )
            _accumulate_tokens(state, usage)
        state["generations"] = {}

        totals = state.get("token_totals") or {}
        attrs = [
            _attr_str("cursor.hook", hook),
            _attr_str("mlflow.spanType", "AGENT"),
            _attr_str("gen_ai.operation.name", "invoke_agent"),
            _attr_str("gen_ai.system", "cursor"),
            _attr_str("cursor.conversation_id", conversation_id),
            _attr_str("gen_ai.request.model", model),
        ]
        if totals:
            attrs.extend(
                usage_attributes(
                    {
                        "input_tokens": totals.get("input_tokens", 0),
                        "output_tokens": totals.get("output_tokens", 0),
                        "total_tokens": totals.get("total_tokens", 0),
                        "estimated": True,
                    }
                )
            )
        if event.get("status"):
            attrs.append(_attr_str("cursor.stop_status", str(event["status"])))
        if event.get("loop_count") is not None:
            attrs.append(_attr_int("cursor.loop_count", int(event["loop_count"])))

        root = _span(
            trace_id=trace_id,
            span_id=session_span_id,
            parent_span_id=None,
            name="invoke_agent Cursor",
            start_ns=state.get("session_start_ns", now - 1_000_000),
            end_ns=now,
            attributes=attrs,
        )
        pending = list(state.get("pending_spans") or [])
        pending.extend(spans)
        pending.append(root)
        if experiment_id:
            export_spans(experiment_id, pending)
        else:
            _log("No MLflow experiment id; dropping buffered spans on stop")
        clear_state(conversation_id)
        return {}

    else:
        save_state(conversation_id, state)
        return response_payload

    if spans:
        state.setdefault("pending_spans", []).extend(spans)
    save_state(conversation_id, state)
    return response_payload


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            _ok()
            return 0
        event = json.loads(raw)
        out = handle(event)
        _ok(out if isinstance(out, dict) else {})
    except Exception:  # noqa: BLE001
        _log("hook failure:\n" + traceback.format_exc())
        _ok({"continue": True, "permission": "allow"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
