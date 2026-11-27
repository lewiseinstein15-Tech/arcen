#!/usr/bin/env bash
# ARCEN on Omarchy: install once, then serve. Ctrl-C stops the server.
# Usage: bash setup-omarchy.sh [work-dir]   (default: ~/Work)
set -euo pipefail

say() { printf '[setup] %s\n' "$*"; }

sudo pacman -S --needed --noconfirm python nodejs npm git docker docker-buildx docker-compose
sudo systemctl enable --now docker.socket

# ARCEN runs one container per turn. Without the socket it plans but cannot execute
# a tool, and Omarchy leaves the docker group out on purpose (root-equivalent access).
if ! docker info >/dev/null 2>&1; then
  cat >&2 <<'MSG'
No Docker socket access — the agent would plan and then refuse every tool.

  omarchy-setup-security-sudoless-docker      # Omarchy's opt-in (Setup > Security > Sudoless Docker)
  # or a rootless daemon:
  export DOCKER_HOST=unix:///run/user/$(id -u)/docker.sock

Re-run this script afterwards.
MSG
  exit 1
fi

cd "${1:-$HOME/Work}"
say "cloning into $(pwd)/arcen"
[ -d arcen ] || git clone https://github.com/lewiseinstein15-Tech/arcen
cd arcen

say "python environment"
[ -d .venv ] || python -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[sandbox]"

say "sandbox image"
IMAGE=ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0
docker image inspect "$IMAGE" >/dev/null 2>&1 \
  || docker pull "$IMAGE" \
  || docker build -t "$IMAGE" docker/sandbox

if [ ! -f "$HOME/.arcen/config.yaml" ]; then
  mkdir -p "$HOME/.arcen"
  cat > "$HOME/.arcen/config.yaml" <<'YAML'
provider:
  name: kilo
  base_url: https://api.kilocode.ai/api/openrouter/v1
  api_key: ""
  model: baidu/ernie-5.5-flash-preview:free
YAML
  chmod 600 "$HOME/.arcen/config.yaml"
fi

# --silent hides npm's own error text, which turns a failed install into a
# script that dies with no message at all. Keep the output.
say "UI dependencies (this is the slow one)"
npm --prefix ui install --no-fund --no-audit
say "UI build"
npm --prefix ui run build

if [ ! -f ui/dist/index.html ]; then
  cat >&2 <<'MSG'
UI build produced no ui/dist/index.html, so the backend would answer / with
{"detail":"Not Found"}. Read the npm output above, or run the dev server instead:

  ./scripts/dev.sh      # backend :3002, Vite :5173
MSG
  exit 1
fi

say "starting the server"
.venv/bin/arcen serve &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  curl -sf localhost:3002/api/health >/dev/null 2>&1 && break
  sleep 0.5
done

curl -s localhost:3002/api/health; echo
curl -s localhost:3002/api/sandbox/status \
  | .venv/bin/python -c 'import json,sys; d=json.load(sys.stdin); print("sandbox:", d.get("effective"), "| degraded:", d.get("degraded"))'

echo "ARCEN: http://localhost:3002"
wait "$SERVER"
