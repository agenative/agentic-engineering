# Cursor Agent → Local MLflow traces

User-level hooks export Cursor Agent activity as OTLP spans to local MLflow
(`local_mlflow` on port **5001**), experiment **cursor-agent**. Works for
**every** Cursor project once installed under `~/.cursor/`.

Physical source of truth: this directory in `agentic-engineering`.  
`~/.cursor/hooks` and `~/.cursor/hooks.json` are symlinks here.

Pattern follows the [Langfuse Cursor integration](https://langfuse.com/integrations/developer-tools/cursor)
([naoufalelh/cursor-langfuse](https://github.com/naoufalelh/cursor-langfuse)):
prompts/responses are **CHAT_MODEL generations**; tools/shell/MCP/file ops are spans.

## Install (user hooks)

```bash
ln -sfn ~/Github/agentic-engineering/.cursor/hooks ~/.cursor/hooks
ln -sfn ~/Github/agentic-engineering/.cursor/hooks/hooks.json ~/.cursor/hooks.json
```

`hooks.json` uses user-hook paths (`./hooks/mlflow_trace.py`) because Cursor runs
user hooks with cwd `~/.cursor/`. Config lives at `hooks/hooks.json` (not
`.cursor/hooks.json`) so opening `agentic-engineering` does not also load it as
project hooks (avoids double traces).

Reload Cursor / wait for hooks watch after changing `hooks.json`.

## Token usage caveat

Cursor hooks **do not expose provider token counts** (Langfuse’s Cursor example
does not receive them either). This hook:

- emits LLM generations named `User Prompt` and `Agent Response (<model>)`
- attaches `gen_ai.usage.*` / `mlflow.chat.tokenUsage` using **estimated** tokens
  (≈ 4 characters per token) unless the payload includes usage fields
- marks estimates with `cursor.tokens_estimated=true`
- records real **context** token counts from `preCompact` when Cursor fires it

## Start MLflow

From this repo:

```bash
docker compose -f .cursor/docker/mlflow.yml up -d
# container: local_mlflow  |  UI: http://127.0.0.1:5001
```

Or from a monorepo that ships `docker/mlflow.yml`:

```bash
./doco -f docker-compose.yml -f docker/mlflow.yml up -d mlflow
```

## Verify

1. Ensure MLflow is up on port 5001.
2. Confirm symlinks: `ls -la ~/.cursor/hooks ~/.cursor/hooks.json`
3. Run an Agent turn in any project.
4. Open http://127.0.0.1:5001 → **cursor-agent** → open a trace.
5. Look for `Agent Response (...)` spans with token attributes.

Debug log (physical path): `agentic-engineering/.cursor/hooks/mlflow_trace.log`  
Raw payloads (optional): `CURSOR_MLFLOW_DEBUG=1` → `hook_events.jsonl` in this directory.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `CURSOR_MLFLOW_URI` | `http://127.0.0.1:5001` | MLflow base URL |
| `CURSOR_MLFLOW_EXPERIMENT` | `cursor-agent` | Experiment name |
| `CURSOR_MLFLOW_REDACT` | unset | Set `1` to redact payloads |
| `CURSOR_MLFLOW_DEBUG` | unset | Set `1` to log raw hook JSON |
