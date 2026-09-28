# ARCEN sandbox image — one container per session (BACKEND-SPEC Part 2 row 11).
#
# Pinned reference: ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0
# Built and pushed by .github/workflows/sandbox-image.yml on every push to main.
#
# Local build:
#   docker build -t ghcr.io/lewiseinstein15-tech/arcen-sandbox:0.1.0 docker/sandbox
#
# The runtime (src/arcen/sandbox/runtime.py) uses the docker backend only
# when this image is present locally; otherwise it degrades to the
# quarantined process backend (degraded=true). Nothing is auto-pulled from
# Docker Hub — the image lives in this repo's GHCR namespace only.

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash coreutils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# commands are exec'd via `bash -c` by the runtime; no entrypoint needed —
# containers are started detached with `sleep infinity` and never bind the
# host filesystem (volumes={}), run with network disabled and capped resources.
