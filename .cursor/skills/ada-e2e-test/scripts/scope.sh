#!/usr/bin/env bash
# Print the top-level monorepo projects changed on this branch (committed since the merge base,
# plus staged, unstaged and untracked files) and what each implies for the ADA e2e environment.
# Usage: scope.sh [base-ref]   (default origin/develop)
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"
BASE_REF="${1:-origin/develop}"

if ! git rev-parse --verify --quiet "${BASE_REF}" >/dev/null; then
  echo "error: base ref ${BASE_REF} not found; run 'git fetch origin develop' or pass a ref" >&2
  exit 1
fi
MERGE_BASE="$(git merge-base "${BASE_REF}" HEAD)"

files="$(
  {
    git diff --name-only "${MERGE_BASE}" HEAD
    git diff --name-only --cached
    git diff --name-only
    git ls-files --others --exclude-standard
  } | sort -u
)"

if [[ -z "${files}" ]]; then
  echo "branch: $(git branch --show-current)  base: ${BASE_REF} (${MERGE_BASE:0:10})"
  echo "No changes against ${BASE_REF}; scope is empty, so no code fixes are in scope."
  exit 0
fi

# Root-level files (no slash) are grouped under "(root)".
projects="$(printf '%s\n' "${files}" | awk -F/ '{ print (NF > 1 ? $1 : "(root)") }' | sort -u)"

echo "branch: $(git branch --show-current)  base: ${BASE_REF} (${MERGE_BASE:0:10})"
echo
echo "Scope (edit boundary):"
while IFS= read -r p; do
  count="$(printf '%s\n' "${files}" | awk -F/ -v p="${p}" '(NF > 1 ? $1 : "(root)") == p' | wc -l | tr -d ' ')"
  echo "  ${p}  (${count} files)"
done <<< "${projects}"

echo
echo "Environment implications:"
has() { printf '%s\n' "${projects}" | grep -qx "$1"; }
implied=0
if has platform-services; then
  echo "  - platform-services: run 'make run-rest' (native audit-api); the rest-service image lacks branch code."
  implied=1
fi
if has platform-clients-react; then
  echo "  - platform-clients-react: run the React dev server against the local backend and pass --base-url to run_ui_case.py."
  implied=1
fi
if printf '%s\n' "${files}" | grep -q '^db-financial-audit/data/collider_workflows/'; then
  echo "  - collider workflows changed: run 'make seed-collider-workflow COLLIDER_WORKFLOW=<name>' for each changed workflow."
  implied=1
fi
if has agent-services; then
  echo "  - agent-services: 'make run' hot-reloads; restart it after changing env files."
  implied=1
fi
if [[ "${implied}" -eq 0 ]]; then
  echo "  - none beyond the default stack"
fi

echo
echo "ADA-relevant changed files:"
printf '%s\n' "${files}" | grep -E 'analysis_designer_agent|configtool/agent|agent-tools-service|analysis-designer-agent|collider_workflows/analysis_designer|ParquetSchemaColumnMapper' \
  | sed 's/^/  /' || echo "  (none matched the ADA path filter)"
