#!/usr/bin/env bash
# ARCEN dev stack — backend on :3002, UI on :5173, one command, clean exit.
#
# Fixes the "second run broke" failure: the venv is activated (or created)
# before starting either service. Occupied ports cause an explicit error;
# this script never signals unrelated processes.
#
# The UI's Vite proxy targets /api/* on localhost:3002; starting the
# backend FIRST is what keeps `npm run dev` free of ECONNREFUSED spam.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 1. Activate the venv (create + install on first run) — BUG 3 fix:
#    without this, uvicorn runs on the system python and dies with
#    ModuleNotFoundError: No module named 'arcen'.
if [ -d .venv ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo "[dev] no .venv — creating one"
  python -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  pip install -e ".[dev]"
fi

# 2. Refuse occupied ports rather than killing their owners. The later
# server bind is still authoritative if another process races this check.
python scripts/dev_ports.py

# 3. Start the backend
echo "[dev] starting backend: uvicorn arcen.server.app:app --port 3002"
uvicorn arcen.server.app:app --port 3002 &
BACKEND_PID=$!
trap 'kill %1 2>/dev/null || true' EXIT

# 4. Wait for health before the UI starts proxying at it
healthy=0
for i in $(seq 1 30); do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "[dev] backend exited before becoming healthy" >&2
    exit 1
  fi
  if curl -sf http://localhost:3002/api/health >/dev/null 2>&1 && kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "[dev] backend healthy: http://localhost:3002/api/health"
    healthy=1
    break
  fi
  sleep 0.5
done
if [ "$healthy" -ne 1 ]; then
  echo "[dev] backend health check timed out" >&2
  exit 1
fi

# 5. Start the frontend (foreground; exit tears the backend down via trap)
echo "[dev] starting frontend (ui/)"
cd ui
npm run dev
