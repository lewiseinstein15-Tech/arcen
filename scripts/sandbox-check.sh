#!/usr/bin/env bash
# Why did a turn fail with "isolated tool '<tool>' returned malformed output"?
# Probes the sandbox boundary the way a turn uses it, in order, and names the
# first thing that is actually broken. Read-only apart from a throwaway container.
set -uo pipefail

IMAGE=${ARCEN_SANDBOX_IMAGE:-ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0}
failed=0

step() { printf '\n== %s\n' "$*"; }

step "docker socket"
if docker info >/dev/null 2>&1; then
  echo "ok: server $(docker version --format '{{.Server.Version}}' 2>/dev/null)"
else
  echo "FAIL: cannot reach the daemon"
  echo "      Omarchy: omarchy-setup-security-sudoless-docker"
  failed=1
fi

step "image present"
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "ok: $IMAGE"
else
  echo "FAIL: $IMAGE is not present (docker pull $IMAGE)"
  failed=1
fi

step "image can read its own stdlib"
out=$(docker run --rm --network none "$IMAGE" \
  python -c "import subprocess, sys; print(sys.version.split()[0])" 2>&1)
case "$out" in
  3.*) echo "ok: python $out" ;;
  *)
    echo "FAIL: the image cannot execute python"
    printf '%s\n' "$out" | tail -6
    failed=1
    ;;
esac

step "write and read inside a turn-like container"
out=$(docker run --rm --network none "$IMAGE" \
  bash -c 'echo hi > /workspace/probe.txt && cat /workspace/probe.txt' 2>&1)
if [ "$out" = "hi" ]; then
  echo "ok"
else
  echo "FAIL: $out"
  failed=1
fi

step "storage"
df -h /var/lib/docker 2>/dev/null | tail -1 || df -h /
docker info 2>/dev/null | grep -E "Storage Driver|Root Dir|Docker Root Dir" || true

if [ "$failed" -ne 0 ]; then
  cat >&2 <<MSG

At least one probe failed — that is the failure the turn reported as
"malformed output". In order of likelihood:

  1. A partial pull leaves layers that cannot be read. Re-pull:
       docker rmi $IMAGE && docker pull $IMAGE
  2. Disk nearly full. Free space, then re-pull.
  3. "Input/output error" with a healthy disk: check the kernel log and the
     storage driver, the image is probably fine:
       sudo dmesg -T | tail -30
       docker info | grep -E "Storage Driver|Docker Root Dir"
  4. Get fresh layers without the registry:
       docker build -t $IMAGE docker/sandbox
MSG
  exit 1
fi

echo
echo "All probes passed: this sandbox can execute tools."
