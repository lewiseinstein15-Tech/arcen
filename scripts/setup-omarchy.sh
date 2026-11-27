#!/usr/bin/env bash
# ARCEN on Omarchy: install once, then serve. Ctrl-C stops the server.
# Usage: bash setup-omarchy.sh [work-dir]   (default: ~/Work)
set -euo pipefail

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
[ -d arcen ] || git clone https://github.com/lewiseinstein15-Tech/arcen
cd arcen

[ -d .venv ] || python -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[sandbox]"

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

npm --prefix ui install --silent
npm --prefix ui run build

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
