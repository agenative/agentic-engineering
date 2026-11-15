# ADA e2e reference

## Request path

```
browser /ui/analysis-designer-agent (platform-clients-react, served by web-client image)
  -> POST /chunked_files ... /close           upload -> fileStorageId
  -> POST /config_tool_agent/start           audit-api AnalysisDesignerAgentController -> sessionId
       AnalysisDesignerAgentService.createAdaSession: sandbox org/analysis type/library/engagement,
       session doc (STARTED), Collider job analysis_designer_agent_run (correlation_id = sessionId)
  -> Collider stage preparing                 audit-api prepareForAdaRun: parquet -> Iceberg table
       ada_session_input_<sessionId>, file manager copy, ada_request + jwt secret on the job
  -> Collider stage processing                agent-services job poller -> POST /ada/execute
       graph: profile -> plan -> inject_anomaly -> publish -> compute -> refine -> finalize
       profile calls agent-tools run_sql; publish calls agent-tools publish_config (JWT forwarded)
  -> stages ingesting_compute_block -> running_compute_block -> generating_token -> processing (loop)
  -> agent-tools POST /tools/analysis_designer/sessions/{id}/state  sets IN_PROGRESS / COMPLETED / FAILED
  <- GET /config_tool_agent/{id}/status every 5 s; status row data-state
```

`completeAdaRun` sets FAILED only when the Collider task fails or is cancelled. Otherwise the
agent owns COMPLETED. A session stuck IN_PROGRESS with a completed Collider job means the agent
never reported its state.

## Components

| Component | Port | Start / restart | Logs |
| --- | --- | --- | --- |
| Docker stack (mongo, postgres, collider, rest-service, web-client, idp, mlflow, ...) | many | `make local` (agent-services); `cd docker/scripts && ./doco restart <svc>` | `./doco logs -f <svc>` |
| audit-api (rest-service) | 8080 | Docker by default; `make run-rest` replaces it with a native bootRun | `./doco logs -f rest-service` or the run-rest terminal |
| agent-services | 8764 | `JOB_POLLER_ENABLED=true make run` (hot reload) | its terminal / `$RUN_DIR/agent-services.log` |
| agent-tools-service | 8114 | `make run-agent-tools` | its terminal / `$RUN_DIR/agent-tools.log` |
| Collider | 8086 | `./doco restart collider` | `./doco logs -f collider` |
| MLflow | 5001 | part of `make local` (`docker/mlflow.yml`) | UI at http://127.0.0.1:5001 |
| Mongo | 27017 | Docker, no auth on localhost | `mongosh` via `docker exec` |
| React dev server (only if platform-clients-react is in scope) | Vite | `cd platform-clients-react && npm run dev:local` | its terminal |

Docker commands need `cd $REPO_ROOT/docker/scripts`. For a React dev server, pass its URL as
`--base-url` to `run_ui_case.py` and confirm the login redirect works against it. If it does not,
test the Docker web-client and say in the report that the React change was not exercised.

Project checks before re-running a case after an in-scope fix:
- agent-services: `make test` (lint, format, ty, full pytest; do not narrow it)
- platform-services: `./gradlew :<module>:test --tests "<Class>"` for touched modules
  (analysis-config-tool, agent-tools-service, common-services, audit-api)
- platform-clients-react: `npx vitest run <path>` for touched files

## Credentials

- UI and API login: `.localenv/credentials/user_list.json` -> `admin.username` / `admin.password`
  (also written into `agent-services/agent-services.env` as `MB_USERNAME` / `MB_PASSWORD`).
  The scripts read these themselves. Never ask the user for them, never print them.
- Azure (`az login`, ACR), the `init_environment.sh` email prompt, MFA, and SSO activation links are
  human steps. Ask the user to do them in their own terminal or browser, and wait for confirmation.
  Never ask the user to paste a secret into chat.

## Mongo queries

```bash
docker exec -it $(docker ps -qf label=com.docker.compose.service=mongo) mongosh localtest --quiet
```

```js
// latest sessions
db.analysis_designer_agent_sessions.find({}, {status: 1, published_configs: 1, user_context: 1}).sort({_id: -1}).limit(5)
// one session, including the opaque agent state
db.analysis_designer_agent_sessions.findOne({_id: ObjectId("<sessionId>")})
// published config referenced by the session
db.configtool_simple_analysis_config.findOne({_id: ObjectId("<published_configs[].published_config_id>")})
// Collider job for the session (database "collider")
db.getSiblingDB("collider").jobs.find({correlation_id: "<sessionId>"})
// Collider workflow definition
db.getSiblingDB("collider").workflows.findOne({symbolic_name: "analysis_designer_agent_run"}, {stages: 1})
// fields are snake_case: status, session_state, published_configs, user_data_table_id, engagement_id
// tenant feature flags
db.getSiblingDB("tenants").tenants.findOne({tenant_id: "localtest"}, {features: 1})
```

The tenant database name comes from `tenants.tenants.db_name` and falls back to the tenant id
(`localtest`).

## MLflow

Traces carry the tag `ada_session_id`. Search in the UI (Traces tab, filter
`tags.ada_session_id = '<id>'`) or with `inspect_session.py`. Span names are `ada.<node>`. The last
span before an ERROR span shows which node failed. OTLP export goes to
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` (default `http://localhost:5001/v1/traces`), with the experiment
set by `x-mlflow-experiment-id` in `OTEL_EXPORTER_OTLP_TRACES_HEADERS`.

## Failure signatures

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| ADA route 404 or blank page | stale `web-client` image | `make pull_local`, then `./doco up -d web-client` |
| Login form never appears, page redirects elsewhere | user lacks the enterprise UI flag | `make seed-data` (sets `enterprise_experience`) |
| `/config_tool_agent/start` 403 | user missing `ANALYSIS_CONFIG_TOOL` or `analysis_designer` flag | `make seed-data`; `uv run python -m mb_agents.evals.tra.local_tra_bootstrap` |
| Status stays STARTED | Collider job not picked up: workflow missing or collider cache | `make seed-collider-workflow` (restarts collider); check `collider.jobs` stage |
| Job reaches `processing`, nothing happens | agent-services poller off or down | start with `JOB_POLLER_ENABLED=true make run`; check port 8764 |
| `verify_request_token` rejection in agent-services log | token expired (TTL 5 min) or key mismatch | check `generating_token` ran before the resume; restart rest-service after `make local` |
| profile node fails on `run_sql` / connection refused :8114 | agent-tools-service down | `make run-agent-tools` |
| MBER2754 on publish | tenant missing `subledger_analysis` | `make run-rest` or `uv run python -m mb_agents.evals.tra.local_tra_bootstrap` |
| `Cannot publish configuration for a session that is not in progress` | session status not IN_PROGRESS when publishing | agent status update ordering; check agent-tools session state calls |
| Publish rejects the config: column, field, or type mismatch | ADA config disagrees with `userDataTable` (see agent-services/docs/ada-column-names-and-types.md) | in-scope fix on whichever side broke the contract |
| Compute fails with `Source file not ready to analyze` after publish; analysis-source workflow stuck/FAILED at `ANALYZING_EFFECTIVE_DATE_METRICS` with MBER1134 | Primary date column has blank values (e.g. SAP AP `clearing_date`). Not a startAnalysis race — sources never reached COMPLETED | Prefer densest DATE in ADA export (`ADAExporter._choose_primary_date`); confirm `ui_config.primary_date_column` on the published config |
| Inspect FAIL only on missing `expect.control_points` while session COMPLETED with published configs | Stale CP-family expects vs what the LLM/`ALGORITHM_MAP` path emits after catalog removal | Update skill `cases.yaml` to families ADA reliably publishes (do not treat as a contract bug) |
| MBER2755 `The primary numeric column must be of type MONEY if subledger is selected` (ada.publish span) | ADA chose a FLOAT64/DECIMAL column as the primary amount; the subledger config requires MONEY | code: whichever side owns the amount type per ada-column-names-and-types.md (export role/type mapping in agent-services, or the publish rewrite in analysis-config-tool) |
| `connection refused` to `localhost:5001/v1/traces` | MLflow overlay not running | `make local` (it includes docker/mlflow.yml) |
| Docker pull `unauthorized` | ACR login expired (about every 2 h) | `cd docker/scripts && ./az_acr_login.sh` |
| Port already in use / mongo 27017 busy | another worktree's stack | `make local` (clears natives + stops other MindBridge stacks) |
| ADA session FAILED in `preparing` with Collider 412 / MBER1368; collider logs show `Deregistered duplicate/stale poller rest-service.*` | Docker rest-service and native `make run-rest` both polling after a worktree switch | Re-run `make local` (auto-clears prior stacks); if using native audit-api, `make run-rest` (stops every rest-service container first) |)
| LLM 401 / AAD errors in agent-services | Azure CLI session expired | ask the user to run `az login` |

## Scope rule examples

- The branch changes only `agent-services`. A publish failure caused by ADA emitting a column type
  the platform rejects gets fixed in agent-services export or sanitization code, not in
  `AnalysisDesignerAgentService.rewriteUnsupportedColumnTypes`.
- The branch changes `agent-services` and `platform-services`. Either side may be fixed. Prefer the
  side that owns the fact per the contract in `agent-services/docs/ada-column-names-and-types.md`.
- The branch changes only `platform-services`, and the failure is in an agent-services graph node.
  Check first whether the platform change broke the contract and fix it there. If agent-services
  really is at fault, stop and ask.
- Environment fixes (seeding, flags, restarts, `.localenv` or `agent-services.env` values) are always
  allowed, are never committed, and are listed in the report.
