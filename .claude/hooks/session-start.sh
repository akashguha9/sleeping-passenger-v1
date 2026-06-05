#!/bin/bash
# SessionStart hook for Claude Code on the web.
#
# Installs the Python test/lint dependencies so `pytest` and `pre-commit` work
# in remote (web) sessions. Idempotent and non-interactive. Runs synchronously
# so dependencies are guaranteed ready before the session starts.
set -euo pipefail

# Only run in the remote (Claude Code on the web) environment. Local machines
# are expected to manage their own virtualenv.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# Prefer Python 3.13, then 3.12 (repo requires >=3.12 for PEP 701 f-strings),
# falling back to python3.
PY=""
for cand in python3.13 python3.12 python3; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo "session-start: no python3 interpreter found" >&2
  exit 1
fi
echo "session-start: using $($PY --version 2>&1)"

# Test dependencies (requirements-dev.txt pulls in requirements.txt + pytest,
# fastapi, httpx, pydantic, uvicorn). pip's cache is reused across runs.
$PY -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt

# Linter (pre-commit: gitleaks + hygiene hooks). Best-effort: never block the
# session if the linter toolchain cannot be fetched.
$PY -m pip install --quiet --disable-pip-version-check pre-commit || true

# Make the chosen interpreter discoverable to the session.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export SP_PYTHON=$PY" >> "$CLAUDE_ENV_FILE"
fi

echo "session-start: dependencies ready"
