#!/usr/bin/env bash
# ARCEN dev stack — backend on :3002, UI on :5173, one command, clean exit.
#
# Fixes the "second run broke" failure: the venv is activated (or created)
# before anything else, so uvicorn always runs with arcen importable; stale
# processes on 3002/5173 are killed so vite never has to fall back to 5174.
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

# 2. Kill stale processes on 3002 and 5173 — no "Port 5173 in use",
#    no orphaned backend serving an old build.
for port in 3002 5173; do
  pid="$(lsof -ti tcp:$port 2>/dev/null || true)"
  if [ -n "$pid" ]; then
    echo "[dev] killing stale process on :$port ($pid)"
    kill -9 $pid 2>/dev/null || true
  fi
done

# 3. Start the backend
echo "[dev] starting backend: uvicorn arcen.server.app:app --port 3002"
uvicorn arcen.server.app:app --port 3002 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT

# 4. Wait for health before the UI starts proxying at it
for i in $(seq 1 30); do
  if curl -sf http://localhost:3002/api/health >/dev/null 2>&1; then
    echo "[dev] backend healthy: http://localhost:3002/api/health → {\"ok\": true}"
    break
  fi
  sleep 0.5
done

# 5. Start the frontend (foreground; exit tears the backend down via trap)
echo "[dev] starting frontend (ui/)"
cd ui
exec npm run dev
