#!/usr/bin/env bash
# Health check for the local ADA e2e stack. Prints one line per check and the command that fixes a
# failure. Exit code is the number of failed checks. Must run outside the Cursor sandbox.
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
UI_BASE="${ADA_UI_BASE:-https://localtest.mindbridge.ai}"
TENANT="${ADA_TENANT:-localtest}"
WORKFLOW="analysis_designer_agent_run"
failures=0

ok() { echo "[ok]   $1"; }
bad() { echo "[FAIL] $1"; echo "       fix: $2"; failures=$((failures + 1)); }

listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

check_port() {
  local port="$1" name="$2" fix="$3"
  if listening "${port}"; then ok "${name} listening on :${port}"; else bad "${name} not listening on :${port}" "${fix}"; fi
}

check_port 27017 "mongo" "cd ${REPO_ROOT}/agent-services && make local"
check_port 8086 "collider" "cd ${REPO_ROOT}/docker/scripts && ./doco up -d collider (or make local)"
check_port 8080 "audit-api (rest-service)" "make local (Docker rest-service) or make run-rest when platform-services is in scope"
check_port 8764 "agent-services" "cd ${REPO_ROOT}/agent-services && JOB_POLLER_ENABLED=true make run"
check_port 8114 "agent-tools-service" "cd ${REPO_ROOT}/agent-services && make run-agent-tools"
check_port 5001 "mlflow" "make local (includes docker/mlflow.yml)"

if [[ -f "${REPO_ROOT}/.localenv/credentials/user_list.json" ]]; then
  ok "local credentials present (.localenv/credentials/user_list.json)"
else
  bad "missing .localenv/credentials/user_list.json" "cd ${REPO_ROOT}/agent-services && make local"
fi

code="$(curl -ks -o /dev/null -w '%{http_code}' "${UI_BASE}/ui/analysis-designer-agent" || echo 000)"
if [[ "${code}" =~ ^(200|302|303)$ ]]; then
  ok "ADA route ${UI_BASE}/ui/analysis-designer-agent -> HTTP ${code}"
else
  bad "ADA route returned HTTP ${code}" "cd ${REPO_ROOT}/agent-services && make pull_local (stale web-client image), then make local"
fi

code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8086/api/v1/workflows/${WORKFLOW}" || echo 000)"
if [[ "${code}" == "200" ]]; then
  ok "collider serves workflow ${WORKFLOW}"
else
  bad "collider does not serve ${WORKFLOW} (HTTP ${code})" "cd ${REPO_ROOT}/agent-services && make seed-collider-workflow"
fi

flags_out="$(
  uv run --quiet --no-project --with 'pymongo>=4.10' python - "${TENANT}" <<'PY' 2>&1
import sys
from pymongo import MongoClient

tenant = sys.argv[1]
required = ["analysis_designer", "enterprise_experience", "subledger_analysis"]
client = MongoClient("mongodb://127.0.0.1:27017/?directConnection=true", serverSelectionTimeoutMS=4000)
doc = client["tenants"]["tenants"].find_one({"tenant_id": tenant}, {"features": 1})
if doc is None:
    print(f"MISSING_TENANT {tenant}")
    sys.exit(0)
features = doc.get("features") or {}
missing = [f for f in required if f not in features]
print("MISSING " + ",".join(missing) if missing else "OK")
PY
)"
case "${flags_out}" in
  *OK*) ok "tenant ${TENANT} has analysis_designer, enterprise_experience, subledger_analysis" ;;
  *MISSING_TENANT*) bad "tenant ${TENANT} not found in Mongo" "cd ${REPO_ROOT}/agent-services && make local" ;;
  *MISSING*) bad "tenant flags missing: ${flags_out#*MISSING }" "cd ${REPO_ROOT}/agent-services && make seed-data && uv run python -m mb_agents.evals.tra.local_tra_bootstrap" ;;
  *) bad "could not read tenant flags: $(echo "${flags_out}" | tail -1)" "check mongo on :27017 (make local)" ;;
esac

chromium="$(
  uv run --quiet --no-project --with 'playwright>=1.48' python -c \
    'from playwright.sync_api import sync_playwright
p = sync_playwright().start(); print(p.chromium.executable_path); p.stop()' 2>/dev/null | tail -1
)"
if [[ -n "${chromium}" && -e "${chromium}" ]]; then
  ok "playwright chromium installed"
else
  bad "playwright chromium not installed" "uv run --no-project --with playwright playwright install chromium"
fi

echo
if [[ "${failures}" -eq 0 ]]; then echo "preflight passed"; else echo "preflight: ${failures} check(s) failed"; fi
exit "${failures}"
