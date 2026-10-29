# ARCEN sandbox image — one container per server turn (BACKEND-SPEC Part 2 row 11).
#
# Pinned reference: ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0
# Built and pushed by .github/workflows/sandbox-image.yml on every push to main.
#
# Local build:
#   docker build -t ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0 docker/sandbox
#
# Server turns use the Docker-only boundary in src/arcen/sandbox/turn.py.
# If the daemon or image is unavailable, tool execution fails closed.

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash coreutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# commands are exec'd via `bash -c` by the runtime; no entrypoint needed —
# containers are started detached with `sleep infinity` and never bind the
# host filesystem (volumes={}), run with network disabled and capped resources.
