#!/usr/bin/env bash
# ARCEN dev stack — backend on :3002, UI on :5173, one command, clean exit.
#
# The UI's Vite proxy targets /api/* on localhost:3002; starting the
# backend FIRST is what keeps `npm run dev` free of ECONNREFUSED spam.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[dev] starting backend: uvicorn arcen.server.app:app --port 3002"
python -m uvicorn arcen.server.app:app --port 3002 &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT

# wait for the health endpoint before the UI starts proxying at it
for _ in $(seq 1 30); do
  if curl -sf http://localhost:3002/api/health >/dev/null 2>&1; then
    echo "[dev] backend healthy: http://localhost:3002/api/health → {\"ok\": true}"
    break
  fi
  sleep 0.5
done

echo "[dev] starting frontend (ui/)"
cd ui
npm run dev
