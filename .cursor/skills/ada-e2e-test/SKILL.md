---
name: ada-e2e-test
description: >-
  End-to-end test the Analysis Designer Agent (ADA) in the MindBridge monorepo with every
  component running locally: bring up and seed a fresh stack, drive the React page at
  /ui/analysis-designer-agent with a parquet file plus a natural-language prompt, follow the
  session through audit-api, Collider, agent-services, agent-tools and MLflow, judge the
  outcome (including cases where an error is the correct result), and root-cause and fix
  failures within the branch's change scope. Use after any ADA change (agent-services
  analysis_designer_agent, analysis-config-tool agent code, agent-tools-service, the React ADA
  page, or the analysis_designer_agent_run Collider workflow), or when the user asks to e2e,
  smoke, or browser test ADA.
---

# ADA end-to-end browser test

Drives the real browser flow: login, open `https://localtest.mindbridge.ai/ui/analysis-designer-agent`,
upload a `.parquet`, type a prompt, click Send, then watch the session until it finishes. Each
case's outcome is checked against `cases.yaml`. On failure, find the root cause and fix it
inside the branch's scope.

Skill directory (referred to as `$SKILL` below): `~/.cursor/skills/ada-e2e-test`.
Monorepo root: `REPO_ROOT="$(git rev-parse --show-toplevel)"` from the workspace.
Read [reference.md](reference.md) for the component map, log locations, Mongo queries, and known
failure signatures. Read it before step 7.

## Hard rules

- **Scope boundary.** Fixes go only into the top-level projects the branch already changes (step 1).
  If the branch only touches `agent-services`, fix within `agent-services/`. Out-of-scope code is
  never edited without the user's explicit approval (step 7).
- **agent-services first.** Always prioritize fixes in `agent-services/`. Look there first for any
  failure, and only move to another project when the root cause is outside agent-services' ownership
  (for example, audit-api, Collider, agent-tools, or the React UI doing something the agent contract
  does not cover). Even then, check whether agent-services can adapt within its own code before
  proposing a change elsewhere.
- **Credentials.** Read the local test username/password yourself from
  `$REPO_ROOT/.localenv/credentials/user_list.json` (`admin`), or `MB_USERNAME` / `MB_PASSWORD` in
  `agent-services/agent-services.env`. Never ask the user for them. For any other secret (Azure SSO,
  MFA, personal IdP credentials, activation links), ask the user to complete that step themselves
  outside the agent. Never ask them to paste secrets into the chat, and never print secrets.
- **Outside the sandbox.** Docker, Chromium, Mongo on 27017, `make local`, and the browser runs all
  need full permissions. Request `all` up front for those commands.
- **Expectations are not bendable.** Never edit a case's `expect` to make it pass unless evidence
  shows the expectation was wrong. Say so explicitly in the report.
- Do not commit unless asked. If asked, use the `AIA-<n>: <description>` format (ticket from branch name).

## Workflow

Copy this checklist into your todo list and keep it updated:

```
- [ ] 1. Scope
- [ ] 2. Environment
- [ ] 3. Preflight
- [ ] 4. Select cases
- [ ] 5. Execute
- [ ] 6. Verify
- [ ] 7. RCA and fix (only if something failed)
- [ ] 8. Report
```

All scripts run with `uv run` (dependencies are declared inline). Create one run directory and reuse it:

```bash
RUN_DIR="$REPO_ROOT/.localenv/ada-e2e/$(date +%Y%m%d-%H%M%S)"; mkdir -p "$RUN_DIR"
```

### 1. Scope

```bash
bash $SKILL/scripts/scope.sh            # base defaults to origin/develop; pass another ref as $1
```

The script prints the changed top-level projects and the environment implications. State the
project set to the user at the start. It is the edit boundary for the rest of the run.
- `platform-services` changed: the Docker `rest-service` image does not have branch code, so run
  `make run-rest` (native audit-api). agent-tools-service always runs natively.
- `platform-clients-react` changed: the `web-client` image does not have branch code. Run the React
  dev server (see reference.md) and pass `--base-url` to the runner.
- `db-financial-audit` changed under `data/collider_workflows/`: run `make seed-collider-workflow`
  (it restarts collider).

### 2. Environment

All `make` targets run from `$REPO_ROOT/agent-services`, outside the sandbox.

1. Reuse or rebuild. If the user asked for a fresh stack, or preflight (step 3) fails on Docker
   services, run `make local`. It handles az login, ACR login, `init_environment.sh` (interactive),
   Docker with MLflow, and the Postgres checkpointer DB. Run it in a background terminal and watch
   its output. When it waits on `az login` or the init email prompt, ask the user to complete it
   in their own terminal, then continue. If an already running stack passes preflight, skip `make local`.
2. `make pull_local` only if the ADA route returns 404 or the image is stale for the scope.
3. `make seed-data` (TRA eval org plus the ADA demo seed and enterprise UI flags), then
   `make seed-collider-workflow`.
4. Start long-running services in background terminals and tee their logs into the run dir:
   ```bash
   JOB_POLLER_ENABLED=true make run 2>&1 | tee "$RUN_DIR/agent-services.log"
   make run-agent-tools 2>&1 | tee "$RUN_DIR/agent-tools.log"
   make run-rest 2>&1 | tee "$RUN_DIR/audit-api.log"   # only when platform-services is in scope
   ```
   `make run-rest` also sets the `subledger_analysis` flag on `localtest`. Without it, run
   `uv run python -m mb_agents.evals.tra.local_tra_bootstrap` so publish does not fail with MBER2754.
   Wait for each service's port before continuing (bootRun takes a few minutes).

### 3. Preflight

```bash
bash $SKILL/scripts/preflight.sh
```

Checks ports (8764, 8114, 8080, 8086, 5001, 27017), the ADA route, the Collider workflow, the tenant
feature flags, and the Playwright Chromium install. Every failing check prints the fix. Apply it and
re-run until it passes. Do not run cases against a stack that fails preflight.

### 4. Select cases

Run every case in `$SKILL/cases.yaml` (the baseline). Then read the branch diff (`git diff
<merge-base>`) and add one or two targeted cases that exercise what changed. For example, header
names with spaces or symbols and decimal/boolean columns when sanitization, data-table schemas, or
column type mapping changed. Put ad hoc cases in `$RUN_DIR/cases.adhoc.yaml` using the same schema.
Do not add them to the skill's `cases.yaml` unless the user asks.

### 5. Execute

For each case, prepare the upload file, then drive the browser:

```bash
uv run $SKILL/scripts/make_parquet.py --cases $SKILL/cases.yaml --case <id> --out "$RUN_DIR/<id>"
uv run $SKILL/scripts/run_ui_case.py  --cases $SKILL/cases.yaml --case <id> --out "$RUN_DIR/<id>"
```

`run_ui_case.py` reads the credentials itself, logs in, uploads, sends the prompt, captures the
`sessionId` from `POST /config_tool_agent/start`, and follows the status row's `data-state` until
COMPLETED, FAILED, or `--timeout-min` (default 20). It screenshots every state change and writes
`result.json`. Use `--headed` to watch it. First run on a machine: `uv run --with playwright
playwright install chromium`. Run cases one at a time. Each one creates its own sandbox engagement.

### 6. Verify

```bash
uv run $SKILL/scripts/inspect_session.py --cases $SKILL/cases.yaml --case <id> --out "$RUN_DIR/<id>"
```

Reads `result.json`, then collects the Mongo session doc (`analysis_designer_agent_sessions`), the
published configs (`configtool_simple_analysis_config`), the Collider job (`collider.jobs` by
`correlation_id`), and the MLflow traces tagged `ada_session_id`. It writes `evidence.json` and prints
PASS or FAIL with reasons. Exit code 0 means PASS.

Pass rules:
- `completed`: UI and Mongo both COMPLETED, `published_configs` non-empty, every
  `expect.control_points` family found in the published configs, no ERROR spans in the traces.
- `failed`: UI or Mongo FAILED, plus `error_contains` (if set) found in the evidence. A success is a FAIL.
- `ui_error`: the inline alert text contains `error_contains` and no session was started.

`provisional: true` cases were derived from code, not from a confirmed run. If one disagrees, work
out from the evidence whether the code or the expectation is wrong before touching anything.

### 7. RCA and fix

Each failing case gets at most 3 fix iterations. Then stop and report.

1. Trace the failure in this order, stopping at the first layer that shows it: the UI screenshots and
   `result.json` network log, the audit-api log, the Collider job stage and task state, the
   agent-services log, the agent-tools log, then the MLflow spans (`ada.<node>` names show where the
   graph stopped). Match what you find against the failure signatures in reference.md.
2. Classify the root cause and state the evidence:
   - **environment or seed**: fix locally (re-seed, restart, flags, pull). Never commit.
   - **in-scope code**: fix it. Run that project's checks (`make test` in agent-services; the
     module's Gradle test for platform-services; `npm test` for platform-clients-react). Restart only
     the affected service, re-run the failing case, then re-run the whole baseline before calling it fixed.
   - **out-of-scope code**: do not edit. First look for a legitimate fix or workaround inside the
     scope, such as agent-services adapting to a platform-services contract. If none exists, stop and
     use AskQuestion. Show the evidence, the file and line at fault, and the proposed out-of-scope
     change, and let the user decide.
   - **wrong expectation**: only with evidence. Report it explicitly.
3. Keep fixes minimal and consistent with the project's AGENTS.md conventions.

### 8. Report

Lead with the overall verdict. Then give a short table per case: id, expected, actual, verdict,
session id, and MLflow link (`http://127.0.0.1:5001/#/experiments/<id>/traces`). Then list
screenshot paths, fixes made (files, why, and confirmation they are inside the scope), environment
fixes applied, and any open out-of-scope issues with their evidence.

## Not covered

The React page has no HITL, approve, or publish screens yet, so this covers only the default
auto-approve path (`hitl_mode=false`). For HITL, run `make demo-ada-hitl` from agent-services.
